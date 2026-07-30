# -*- coding: utf-8 -*-
"""300萬十格艙位制逐日模擬(2026-07-29使用者裁示開工,設計稿v0→模擬v0)
========================================================================
結構: 格=NAV/N_SLOT動態複利;A艙=處置V4槽位制(事件重用tmp_dispo_pool_sim口徑:
  T1-T3非毒格∧tv3>=0.3億,第3日收盤進/出關+1開盤出,净-0.45%,單檔<=1%×tv3容量鐵律,
  同日優先序=Tier升冪→tv3降冪,逐日以收盤mark-to-market=真MDD)
C艙=溫度計機動(四燈窗聯集期間持TAIEX指數載具:甜蜜格>=20→60日/跌停廣度>=20→20日/
  亞跌B→10日/雙收斂→20日;燈亮=唯一加碼時機,熊市不關)
B艙=題材波段近似(策略棧S3⑤強訊號+階梯週線,tmp_bear_trades.csv 2022-05起;
  階梯=週線MA4/MA13自帶regime減碼;B=事件籃近似,個股槽位粒度未模擬=v0已知簡化)
現金=剩餘;無槓桿無利息;A靠短週轉自然限縮曝險。
輸出: NAV vs 大盤300萬買進持有(倍數/CAGR/日頻MDD/夏普/逐年勝負/平均曝險)+格數敏感度掃描。
限制: B艙2022-05前空窗(現金);無攤平腿(保守);S3為B艙代理非交集頁⭐全集;
  2019-21只有A+C=偏防守。用法: python build_portfolio_sim_300w.py
"""
import pickle
import sqlite3
import sys
import time

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
DB = "capital_flow.db"
CAP0 = 3_000_000.0
COST_S3 = 0.5
HOLD_S3 = 8


def rd(sql, params=None, tries=5, wait=3):
    for i in range(tries):
        try:
            con = sqlite3.connect(DB, timeout=30)
            df = pd.read_sql(sql, con, params=params)
            con.close()
            return df
        except sqlite3.OperationalError as e:
            if "locked" in str(e) and i < tries - 1:
                time.sleep(wait)
            else:
                raise


def build_v4_events():
    """處置V4事件(口徑=tmp_dispo_pool_sim):回傳(events_df, close_map)。"""
    disp = rd("SELECT * FROM disposition")
    px = rd("SELECT code, date, open, close, money FROM fm_daily_price ORDER BY code, date")
    cls = rd("SELECT code FROM classification WHERE country='台'")
    theme_codes = set(cls.code)
    for c in ("start_date", "end_date"):
        disp[c] = pd.to_datetime(disp[c], errors="coerce")
    disp = disp.dropna(subset=["start_date", "end_date"]).reset_index(drop=True)
    px["date"] = pd.to_datetime(px["date"])
    stocks = {c: g.sort_values("date").reset_index(drop=True) for c, g in px.groupby("code")}
    close_map = {}
    rows = []
    for _, e in disp.iterrows():
        g = stocks.get(e.code)
        if g is None:
            continue
        dts = g["date"].values
        n = len(g)
        s = int(np.searchsorted(dts, np.datetime64(e.start_date)))
        en = int(np.searchsorted(dts, np.datetime64(e.end_date), side="right") - 1)
        if s >= n or en <= s or en - s > 25 or en - s < 6 or en + 1 >= n:
            continue
        c_, o_, m_ = g["close"].values, g["open"].values, g["money"].values
        if c_[s + 2] <= 0 or o_[en + 1] <= 0:
            continue
        if "人工管制" in str(e.reason):
            continue
        mm = str(e.match_min)
        theme = e.code in theme_codes
        tier = 1 if (theme and mm == "20") else (2 if theme else (3 if mm == "20" else 4))
        if tier == 4 or m_[s + 2] / 1e8 < 0.3:
            continue
        rows.append({"code": e.code, "tier": tier,
                     "entry": g["date"].iloc[s + 2], "exit": g["date"].iloc[en + 1],
                     "tv3": m_[s + 2] / 1e8, "entry_px": c_[s + 2],
                     "net": (o_[en + 1] / c_[s + 2] - 1) * 100 - 0.45})
        if e.code not in close_map:
            close_map[e.code] = g.set_index("date")["close"]
    ev = pd.DataFrame(rows).sort_values(["entry", "tier"]).reset_index(drop=True)
    return ev, close_map


def build_lights(tw_close):
    """四燈窗聯集(逐日bool)。thermo/跌停=2019起面板;亞跌B/雙收斂=指數全史。"""
    idx = rd("SELECT market, date, close FROM index_daily WHERE market IN "
             "('N225','KOSPI','SPX')", None)
    idx["date"] = pd.to_datetime(idx.date)
    n2 = idx[idx.market == "N225"].set_index("date").close.pct_change() * 100
    ko = idx[idx.market == "KOSPI"].set_index("date").close.pct_change() * 100
    sp = idx[idx.market == "SPX"].set_index("date").close.sort_index()
    spr = sp.pct_change() * 100
    twr = tw_close.pct_change() * 100
    dd250 = (tw_close / tw_close.rolling(250, min_periods=120).max() - 1) * 100
    drop10 = (tw_close / tw_close.shift(10) - 1) * 100
    p = pd.read_pickle("快取/tmp_panic_gradient_panel.pkl")
    ss = p[(p.i1 == "-6~-9") & (p.i2 == ">=20%")]
    sweet = ss.groupby("d0").size()
    lf = pd.read_pickle("快取/tmp_limit_flags.pkl")
    ldc = lf[~lf.code.str.startswith("00")].groupby("date").ld_close.sum()
    trig = {60: [], 10: [], 20: []}
    for d in tw_close.index:
        if sweet.get(d, 0) >= 20:
            trig[60].append(d)
        if ldc.get(d, 0) >= 20:
            trig[20].append(d)
        nv, kv = n2.get(d, np.nan), ko.get(d, np.nan)
        si = spr.index.searchsorted(d) - 1
        uv = float(spr.iloc[si]) if si >= 0 else np.nan
        if pd.notna(nv) and pd.notna(kv) and pd.notna(uv) and nv <= -2 and kv <= -2 and uv > -1:
            trig[10].append(d)
        dv, rv, d10 = dd250.get(d), twr.get(d), drop10.get(d)
        if (pd.notna(dv) and -20 < dv <= -10 and pd.notna(rv) and rv <= -2
                and pd.notna(d10) and d10 <= -6):
            trig[20].append(d)
    lit = pd.Series(False, index=tw_close.index)
    pos = {d: i for i, d in enumerate(tw_close.index)}
    arr = lit.values
    for hold, days in trig.items():
        for d in days:
            i = pos[d]
            arr[i:i + hold] = True
    return pd.Series(arr, index=tw_close.index)


def build_s3_weekly(tw_close):
    """S3週線報酬序列(port自build_portfolio_report_v2 build_line12,yfinance改index_daily)。"""
    prices = {k: v for k, v in pickle.load(open("快取/tmp_bear_prices.pkl", "rb")).items()
              if v is not None and len(v) > 10}
    panel = pd.DataFrame(prices)
    wret = panel.pct_change(fill_method=None) * 100
    idx = panel.index
    tr = pd.read_csv("快取/tmp_bear_trades.csv", dtype=str)
    tr = tr[tr.ret8w.str.contains("%", na=False)].copy()

    def pat_ok(r):
        try:
            a, b = r.nh.split("/")
            if int(b) and int(a) / int(b) >= 2 / 3:
                return True
        except (ValueError, AttributeError):
            pass
        return "✓" in str(r.gap)

    tr = tr[tr.apply(pat_ok, axis=1)]
    tww = tw_close.resample("W-FRI").last().dropna()
    m4, m13 = tww.rolling(4).mean(), tww.rolling(13).mean()

    def tier_at(day):
        i = tww.index.searchsorted(pd.Timestamp(day)) - 1
        if i < 13:
            return 1.0
        pxv, a, b = tww.iloc[i], m4.iloc[i], m13.iloc[i]
        if pd.notna(b) and pxv < b:
            return 0.3
        if pd.notna(a) and pxv < a:
            return 0.6
        return 1.0

    entries = []
    for t in tr.itertuples():
        ei = idx.searchsorted(pd.Timestamp(t.date))
        mems = [c.strip() for c in t.members.split("、") if c.strip() in wret.columns]
        if mems and ei < len(idx) - 1:
            entries.append((ei, mems))
    weekly = []
    for i in range(1, len(idx)):
        rets = []
        for ei, mems in entries:
            if ei < i <= ei + HOLD_S3:
                rs = [wret.iloc[i].get(m) for m in mems]
                rs = [x for x in rs if pd.notna(x)]
                if rs:
                    rets.append(sum(rs) / len(rs) - (COST_S3 if i == ei + 1 else 0))
        r = (sum(rets) / len(rets) if rets else 0.0) * tier_at(idx[i])
        weekly.append((idx[i], r, len(rets)))
    return pd.DataFrame(weekly, columns=["date", "ret", "n"]).set_index("date")


def simulate(cal, tw_close, ev, close_map, lit, s3w,
             n_slot=10, a_slots=3, b_slots=3, c_slots=2, label="", start="2019-06-01",
             end="2026-07-01", quiet=False):
    cal = [d for d in cal if pd.Timestamp(start) <= d <= pd.Timestamp(end)]
    ev_by_day = {d: g for d, g in ev.groupby("entry")}
    s3_dates = set(s3w.index)
    cash, b_val = CAP0, 0.0
    a_pos = []  # dict(code,size,entry_px,exit,net)
    c_size, c_entry_px = 0.0, None
    nav_series = []
    a_pnl = c_pnl = 0.0
    b_base = 0.0
    for d in cal:
        # A出場
        keep = []
        for p in a_pos:
            if p["exit"] <= d:
                cash += p["size"] * (1 + p["net"] / 100)
                a_pnl += p["size"] * p["net"] / 100
            else:
                keep.append(p)
        a_pos = keep
        # C出入場
        twp = tw_close.get(d)
        if lit.get(d, False) and c_size == 0 and pd.notna(twp):
            nav_now = cash + b_val + sum(
                p["size"] * (close_map[p["code"]].asof(d) / p["entry_px"]) for p in a_pos)
            want = c_slots * nav_now / n_slot
            c_size = min(want, cash)
            c_entry_px = twp
            cash -= c_size
        elif not lit.get(d, False) and c_size > 0 and pd.notna(twp):
            cash += c_size * (twp / c_entry_px)
            c_pnl += c_size * (twp / c_entry_px - 1)
            c_size = 0.0
        # B週線(週五結算+再平衡)
        if d in s3_dates:
            r = s3w.loc[d]
            b_val *= (1 + r.ret / 100)
            nav_now = cash + b_val + c_size * (twp / c_entry_px if c_size else 0) + sum(
                p["size"] * (close_map[p["code"]].asof(d) / p["entry_px"]) for p in a_pos)
            target = (b_slots * nav_now / n_slot) if r.n > 0 else 0.0
            delta = target - b_val
            if delta > 0:
                delta = min(delta, cash)
            cash -= delta
            b_val += delta
            b_base += 1
        # A進場(優先序=tier→tv3)
        g = ev_by_day.get(d)
        if g is not None:
            for r in g.sort_values(["tier", "tv3"], ascending=[True, False]).itertuples():
                if len(a_pos) >= a_slots:
                    break
                nav_now = cash + b_val + c_size * (twp / c_entry_px if c_size else 0) + sum(
                    p["size"] * (close_map[p["code"]].asof(d) / p["entry_px"]) for p in a_pos)
                size = min(nav_now / n_slot, 0.01 * r.tv3 * 1e8, cash)
                if size <= 10_000:
                    continue
                cash -= size
                a_pos.append({"code": r.code, "size": size, "entry_px": r.entry_px,
                              "exit": r.exit, "net": r.net})
        # 日終NAV
        a_mark = sum(p["size"] * (close_map[p["code"]].asof(d) / p["entry_px"]) for p in a_pos)
        c_mark = c_size * (twp / c_entry_px) if c_size and pd.notna(twp) else c_size
        nav = cash + b_val + a_mark + c_mark
        nav_series.append((d, nav, (a_mark + b_val + c_mark) / nav))
    nv = pd.DataFrame(nav_series, columns=["date", "nav", "expo"]).set_index("date")
    tw_win = tw_close.reindex(nv.index).ffill()
    bh = tw_win / tw_win.iloc[0]
    mult = nv.nav.iloc[-1] / CAP0
    yrs = (nv.index[-1] - nv.index[0]).days / 365.25
    dr = nv.nav.pct_change().dropna()
    sharpe = dr.mean() / dr.std() * np.sqrt(252) if dr.std() > 0 else np.nan
    mdd = float(((nv.nav / nv.nav.cummax()) - 1).min() * 100)
    bh_mdd = float(((bh / bh.cummax()) - 1).min() * 100)
    yearly = []
    for y, gy in nv.groupby(nv.index.year):
        r_p = gy.nav.iloc[-1] / gy.nav.iloc[0] - 1
        b_y = tw_win.loc[gy.index]
        r_b = b_y.iloc[-1] / b_y.iloc[0] - 1
        yearly.append((y, r_p * 100, r_b * 100, r_p > r_b))
    if not quiet:
        print(f"[{label}] {nv.index[0].date()}~{nv.index[-1].date()}  "
              f"組合{mult:.2f}x(CAGR{(mult ** (1 / yrs) - 1) * 100:+.1f}%) vs 大盤{bh.iloc[-1]:.2f}x | "
              f"MDD {mdd:+.1f}% vs 大盤{bh_mdd:+.1f}% | 夏普{sharpe:.2f} | "
              f"平均曝險{nv.expo.mean() * 100:.0f}%")
        wy = sum(1 for _, _, _, w in yearly if w)
        print("   逐年: " + "  ".join(f"{y}:{rp:+.1f}%vs{rb:+.1f}%{'✓' if w else '✗'}"
                                      for y, rp, rb, w in yearly) + f"  ({wy}/{len(yearly)}年勝)")
        print(f"   損益歸因: A處置{a_pnl / 1e4:+,.0f}萬 C機動{c_pnl / 1e4:+,.0f}萬 "
              f"B題材={'(併入NAV,週線結算)' if b_base else '未啟用'}")
    return dict(mult=mult, mdd=mdd, sharpe=sharpe, bh=float(bh.iloc[-1]), bh_mdd=bh_mdd,
                wy=sum(1 for _, _, _, w in yearly if w), ny=len(yearly),
                expo=float(nv.expo.mean()))


def main():
    tw = rd("SELECT date, close FROM index_daily WHERE market='TAIEX' ORDER BY date")
    tw["date"] = pd.to_datetime(tw.date)
    tw_close = tw.set_index("date").close
    cal = list(tw_close.index)
    print("V4事件建構中…")
    ev, close_map = build_v4_events()
    print(f"  V4事件 {len(ev)}筆 {ev.entry.min().date()}~{ev.entry.max().date()}")
    lit = build_lights(tw_close)
    print(f"  燈亮窗日數 {int(lit.sum())}/{len(lit)}")
    s3w = build_s3_weekly(tw_close)
    print(f"  S3週線 {len(s3w)}週 {s3w.index.min().date()}~{s3w.index.max().date()}")

    print("\n===== 主配置 A3/B3/C2(10格,300萬) =====")
    simulate(cal, tw_close, ev, close_map, lit, s3w, label="主配置·全窗2019-06起")
    simulate(cal, tw_close, ev, close_map, lit, s3w, label="主配置·六線齊窗2023起",
             start="2023-01-01")
    print("\n===== 敏感度掃描(全窗;mult/MDD/夏普/勝年) =====")
    for ns, a, b, c, lab in ((10, 3, 3, 2, "A3B3C2基準"), (10, 2, 4, 2, "A2B4C2"),
                             (10, 4, 2, 2, "A4B2C2"), (10, 3, 3, 4, "C加倍A3B3C4"),
                             (10, 5, 0, 3, "無B·A5C3"), (10, 0, 5, 3, "無A·B5C3"),
                             (15, 4, 6, 3, "15格A4B6C3"), (6, 2, 2, 2, "6格A2B2C2")):
        r = simulate(cal, tw_close, ev, close_map, lit, s3w, n_slot=ns, a_slots=a,
                     b_slots=b, c_slots=c, quiet=True)
        print(f"  {lab:>12}: {r['mult']:.2f}x MDD{r['mdd']:+.1f}% 夏普{r['sharpe']:.2f} "
              f"勝{r['wy']}/{r['ny']}年 曝險{r['expo'] * 100:.0f}% (大盤{r['bh']:.2f}x/{r['bh_mdd']:+.1f}%)")


if __name__ == "__main__":
    main()
