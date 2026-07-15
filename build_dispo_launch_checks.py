# -*- coding: utf-8 -*-
"""處置V4上線前三項檢查(使用者2026-07-16核准後動儀表板)
A 分盤流動性: 第3日/倒數第3日成交值分布+相對處置前縮量倍數+可容納部位規模判定
B 選件規則: 優先序分層(題材成員>20分盤>前段跌)績效+月容量+cap-5優先序模擬vs先到先選
C 去重: V4事件與甜蜜格訊號重疊率+與開低承接母體(當日成交值前150)重疊率
用法: python build_dispo_launch_checks.py
"""
import sqlite3

import numpy as np
import pandas as pd

COST = 0.45


def main():
    conn = sqlite3.connect("capital_flow.db")
    disp = pd.read_sql("SELECT * FROM disposition", conn)
    px = pd.read_sql("SELECT code, date, open, close, money FROM fm_daily_price ORDER BY code, date", conn)
    cls = pd.read_sql("SELECT code, main_group g FROM classification WHERE country='台'",
                      conn, dtype={"code": str}).drop_duplicates("code").set_index("code").g
    conn.close()
    px["date"] = pd.to_datetime(px.date)
    stocks = {c: g.sort_values("date").reset_index(drop=True) for c, g in px.groupby("code")}
    for c in ("start_date", "end_date"):
        disp[c] = pd.to_datetime(disp[c], errors="coerce")
    disp = disp.dropna(subset=["start_date", "end_date"])
    # 當日成交值前150名單(逐日)
    px["rank"] = px.groupby("date").money.rank(ascending=False)
    top150 = set(zip(px.loc[px["rank"] <= 150, "code"], px.loc[px["rank"] <= 150, "date"]))
    twii = pd.read_pickle("tmp_twii_long.pkl").dropna()

    ev = []
    for _, e in disp.iterrows():
        g = stocks.get(e.code)
        if g is None:
            continue
        dts = g.date
        s = np.searchsorted(dts.values, np.datetime64(e.start_date))
        en = np.searchsorted(dts.values, np.datetime64(e.end_date), side="right") - 1
        if s >= len(g) or en <= s or en - s > 25 or en - s < 6:
            continue
        c_, o_, m_ = g.close.values, g.open.values, g.money.values
        i3 = s + 2
        if en + 1 >= len(g) or not (c_[i3] > 0 and o_[en + 1] > 0):
            continue
        pre_tv = np.nanmean(m_[max(0, s - 21):s - 1]) / 1e8 if s > 1 else np.nan
        legs = [(dts[j], c_[j] / c_[j - 1] - 1) for j in range(i3 + 1, en + 1) if c_[j] > 0 and c_[j - 1] > 0]
        legs.append((dts[en + 1], o_[en + 1] / c_[en] - 1))
        ev.append({"code": e.code, "d0": dts[i3], "mins": e.match_min, "reason": e.reason,
                   "theme": cls.get(e.code), "tv3": m_[i3] / 1e8, "tvL3": m_[en - 2] / 1e8 if en - 2 >= 0 else np.nan,
                   "pre_tv": pre_tv, "pre_path": (c_[en - 3] / c_[s] - 1) * 100 if en - 3 > s and c_[s] > 0 else np.nan,
                   "top150": (e.code, dts[i3]) in top150, "legs": legs,
                   "net": (o_[en + 1] / c_[i3] - 1) * 100 - COST})
    df = pd.DataFrame(ev)
    df = df[~df.reason.astype(str).str.contains("人工管制")]  # 毒格剔除
    print(f"V4事件(剔毒格): {len(df):,}筆")

    print("\n【A 分盤流動性】第3日成交值分布(億):")
    q = df.tv3.quantile([.1, .25, .5, .75, .9])
    print("  p10/p25/中位/p75/p90 = " + " / ".join(f"{v:.2f}" for v in q))
    print(f"  縮量倍數(第3日/處置前20日均): 中位{(df.tv3 / df.pre_tv).median():.2f}x")
    for f_ in (0.1, 0.3, 1.0):
        print(f"  第3日成交值>={f_}億的事件占比: {(df.tv3 >= f_).mean() * 100:.0f}%")
    print(f"  倒數第3日成交值中位: {df.tvL3.median():.2f}億")
    print("  判定參考: 部位若=當日成交值1%,中位事件可容納約"
          f"{df.tv3.median() * 1e8 * 0.01 / 1e4:.0f}萬")

    print("\n【B 選件規則】優先序分層(V4淨額):")
    df["tier"] = np.where(df.theme.notna() & (df.mins == "20"), "T1 題材∩20分盤",
                 np.where(df.theme.notna(), "T2 題材成員",
                 np.where(df.mins == "20", "T3 20分盤", "T4 其餘")))
    for t, g in df.groupby("tier"):
        mo = len(g) / 90
        print(f"  {t}: 中位{g.net.median():+6.2f}% 勝率{(g.net > 0).mean() * 100:3.0f}% n={len(g):,} 月均{mo:.1f}件")
    # cap-5 模擬: 優先序 vs 先到先選
    def sim(order_key):
        bydate = {}
        for r in df.itertuples():
            bydate.setdefault(r.d0, []).append(r)
        cal = twii.index[(twii.index >= df.d0.min()) & (twii.index <= max(l[-1][0] for l in df.legs))]
        active, daily = [], {}
        tier_rank = {"T1 題材∩20分盤": 0, "T2 題材成員": 1, "T3 20分盤": 2, "T4 其餘": 3}
        for d in cal:
            r = 0.0
            still = []
            for legs in active:
                if legs and legs[0][0] == d:
                    nleg = len(legs)
                    r += 0.2 * legs[0][1]
                    legs = legs[1:]
                if legs:
                    still.append(legs)
            active = still
            cands = bydate.get(d, [])
            cands = sorted(cands, key=order_key)
            for t in cands:
                if len(active) < 5:
                    active.append(list(t.legs))
            daily[d] = r - 0.2 * COST / 100 * sum(1 for t in cands[:max(0, 5 - len(active))])  # 成本近似
        ser = pd.Series(daily).reindex(cal).fillna(0)
        eq = (1 + ser).cumprod()
        mdd = ((eq / eq.cummax()) - 1).min() * 100
        return eq.iloc[-1], ser.mean() / ser.std() * np.sqrt(252), mdd
    tier_rank = {"T1 題材∩20分盤": 0, "T2 題材成員": 1, "T3 20分盤": 2, "T4 其餘": 3}
    c1_, s1_, m1_ = sim(lambda t: (tier_rank[t.tier], -(t.pre_path is not None and not np.isnan(t.pre_path) and -t.pre_path or 0)))
    c2_, s2_, m2_ = sim(lambda t: t.code)
    print(f"  cap-5模擬 優先序版: 複利{c1_:.2f}x 夏普{s1_:.2f} MDD{m1_:.1f}%")
    print(f"  cap-5模擬 先到先選: 複利{c2_:.2f}x 夏普{s2_:.2f} MDD{m2_:.1f}%")

    print("\n【C 去重】")
    sweet = pd.read_pickle("tmp_panic_sweetspot_events.pkl")
    sw = sweet[(sweet.dd <= -6) & (sweet.dd > -9) & (sweet.pull >= 20) & (sweet.rr > 1.2) & (sweet.tv > 1)]
    swset = set(zip(sw.code, sw.d0))
    hold_overlap = 0
    for r in df.itertuples():
        days = [d for d, _ in r.legs]
        if any((r.code, d) in swset for d in [r.d0] + days):
            hold_overlap += 1
    print(f"  V4持有窗內同股觸發甜蜜格: {hold_overlap}/{len(df)} ({hold_overlap / len(df) * 100:.1f}%)")
    print(f"  V4進場日該股在成交值前150(開低承接母體): {df.top150.mean() * 100:.1f}%")
    df.drop(columns="legs").to_pickle("tmp_dispo_launch_panel.pkl")


if __name__ == "__main__":
    main()
