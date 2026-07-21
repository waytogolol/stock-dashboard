# -*- coding: utf-8 -*-
"""多週期共振研究(使用者2026-07-21提案):同題材裡多檔同時日線+週線技術面對齊(爆量長紅+雙線同步創高),
是否比單一個股突破更容易走出大行情(案例:記憶體族群2025年8-9月)。

⚠關鍵前車之鑑(封存/研究_20260711/研究紀錄_20260711...節三十二,H1案例):記憶體2025-09那次事後解剖發現外資
點火前4週由賣轉買(-1.5M/日→+29M/日),但把這個「外資先行」特徵凍結套到2022-24其餘64次題材點火事件,
結果反轉、被判否定——「案例腳印不外推,記憶體外資先行是個案個性」。本研究記取教訓:
共振訊號的定義**只借用本專案已經在別處驗證過/慣用的通用門檻**(pat_volume_bar的4%+2倍量、bear_test_2022的
gap_newhigh邏輯),不用記憶體2025這個案例本身的具體數字反推定義,案例只拿來做「事後有沒有被抓到」的
面子檢查(face validity),不是校準來源——避免重蹈覆轍。

設計(預註冊):
- 個股日線觸發: 借pattern_mining_2022.py::pat_volume_bar慣例=單日漲幅>=4% 且 量>=2倍20日均量(shift(1)避免前視);
  同時要求該日收盤價創60個交易日新高(借bear_test_2022.py::gap_newhigh_week的「帶量突破」定義,不是空漲)
- 個股週線觸發: fm_daily_price resample("W-FRI")比照pattern_mining_2022.py慣例組週K,該週收盤創12週新高
  (12週≈60交易日,跟日線窗口對齊同一把尺)
- 個股「共振週」= 該週日線觸發至少一次 且 該週週線也觸發(雙線同步,不是只有一邊)
- 題材共振 = 同一main_group(country='台',classification表)裡,同一週有>=2檔個股同時進入共振週
  (單一個股觸發不算「共振」,共振的定義就是多檔同時)
- episode化: 同題材前後兩次共振週相隔<=4週視為同一波(比照scan_signals.py::find_triggers的4週去重慣例),
  只取每波第一週為主事件
- 前向報酬: 訊號週後k=4/8/12週,參與共振的成員等權組合報酬(次週一開盤進,收盤對收盤同單位)
- 驗證: LOTO(逐年剔除)+ cluster bootstrap(年群,B=10000,seed=42),比照build_attention_validate.py規格
用法: python build_resonance_theme.py
"""
import sqlite3

import numpy as np
import pandas as pd

SEED = 42
B = 10000


def stat(x, lab):
    x = pd.Series(x).dropna()
    if len(x) < 15:
        print(f"  {lab}: n={len(x)}太少")
        return None
    print(f"  {lab}: 中位{x.median():+6.2f}% 均值{x.mean():+6.2f}% 勝率{(x > 0).mean() * 100:3.0f}% n={len(x):,}")
    return x


def main():
    conn = sqlite3.connect("capital_flow.db")
    px = pd.read_sql("SELECT code, date, close, volume FROM fm_daily_price WHERE close>0 ORDER BY code, date", conn)
    cls = pd.read_sql("SELECT DISTINCT code, main_group FROM classification WHERE country='台'", conn)
    conn.close()
    px["date"] = pd.to_datetime(px.date)

    # 只留成員數>=5的題材(太小的group共振沒有統計意義)
    grp_size = cls.groupby("main_group").code.nunique()
    themes = sorted(grp_size[grp_size >= 5].index)
    print(f"題材數(>=5檔成員): {len(themes)} / 個股觸發計算宇宙: {px.code.nunique()}檔")

    # ---- 個股層: 日線觸發 + 週線觸發 ----
    daily_fire = {}   # code -> set(週期end date, 用W-FRI週五) 該股該週至少一次日線觸發
    weekly_ret = {}   # code -> weekly close Series(index=週五)
    for code, g in px.groupby("code"):
        g = g.sort_values("date").set_index("date")
        cl, vol = g.close, g.volume
        chg = cl.pct_change()
        vol20 = vol.rolling(20).mean().shift(1)
        hi60 = cl.rolling(60).max().shift(1)
        fire_d = (chg >= 0.04) & (vol20 > 0) & (vol >= 2 * vol20) & (cl > hi60)
        wk = cl.resample("W-FRI").last()
        weekly_ret[code] = wk
        if fire_d.any():
            fdates = fire_d[fire_d].index
            fwk = pd.Series(fdates).dt.to_period("W-FRI").dt.end_time.dt.normalize()
            daily_fire[code] = set(fwk.values)

    codes_ok = [c for c in weekly_ret if len(weekly_ret[c].dropna()) >= 20]
    print(f"週線資料足夠(>=20週)的個股: {len(codes_ok)}")

    reso_week = {}  # code -> set(共振週=日線觸發週 且 該週週線亦創12週新高)
    for code in codes_ok:
        wk = weekly_ret[code].dropna()
        wk_hi12 = wk.rolling(12).max().shift(1)
        wk_fire = (wk > wk_hi12)
        dset = daily_fire.get(code, set())
        r = set(wk_fire.index[wk_fire]) & dset
        if r:
            reso_week[code] = r

    n_reso_stocks = len(reso_week)
    n_reso_events = sum(len(v) for v in reso_week.values())
    print(f"個股共振週命中: {n_reso_stocks}檔 / 共{n_reso_events}週次(未去重)\n")

    # ---- 題材層: 同週>=2檔共振 ----
    code2groups = cls.groupby("code").main_group.apply(list).to_dict()
    theme_week_members = {}  # (theme, week) -> set(codes)
    for code, weeks in reso_week.items():
        for g in code2groups.get(code, []):
            if g not in themes:
                continue
            for w in weeks:
                theme_week_members.setdefault((g, w), set()).add(code)

    rows = []
    for (theme, wk), members in theme_week_members.items():
        if len(members) >= 2:
            rows.append({"theme": theme, "week": wk, "n_members": len(members), "members": sorted(members)})
    ev = pd.DataFrame(rows).sort_values(["theme", "week"]).reset_index(drop=True)
    print(f"題材共振週(>=2檔同週共振): {len(ev)}筆 / {ev.theme.nunique() if len(ev) else 0}個題材曾出現")

    if len(ev) == 0:
        print("無事件,結束(訊號定義可能太嚴,建議先降breadth門檻或檢查日期對齊)")
        return

    # episode化(同題材<=4週視為同一波)
    ev["episode_first"] = True
    for theme, idx in ev.groupby("theme").groups.items():
        idx = list(idx)
        wk = ev.loc[idx, "week"].tolist()
        prev = None
        for i, w in zip(idx, wk):
            if prev is not None and (w - prev).days <= 28:
                ev.loc[i, "episode_first"] = False
            else:
                prev = w
            if ev.loc[i, "episode_first"]:
                prev = w

    ep = ev[ev.episode_first].copy()
    print(f"episode化後主事件: {len(ep)}筆 (平均每波連鎖 {len(ev) / max(len(ep), 1):.1f} 週)\n")

    # ---- 前向報酬: 參與成員等權週線報酬(次週收盤對收盤,近似,未扣成本) ----
    def fwd_ret(theme_wk, members, k):
        rets = []
        for c in members:
            wk = weekly_ret.get(c)
            if wk is None:
                continue
            wk = wk.dropna()
            pos = wk.index.searchsorted(theme_wk)
            if pos >= len(wk) or wk.index[pos] != theme_wk:
                continue
            j = pos + k
            if j >= len(wk):
                continue
            p0, p1 = wk.iloc[pos], wk.iloc[j]
            if p0 > 0 and p1 > 0:
                rets.append((p1 / p0 - 1) * 100)
        return np.mean(rets) if rets else np.nan

    for k in (4, 8, 12):
        ep[f"fwd{k}"] = ep.apply(lambda r: fwd_ret(r.week, r.members, k), axis=1)
    ep["y"] = ep.week.dt.year

    print("== 題材共振事件 前向報酬(參與成員等權,收盤對收盤) ==")
    for k in (4, 8, 12):
        stat(ep[f"fwd{k}"], f"fwd{k}週")

    print("\n== 逐年(fwd8週) ==")
    for y, g in ep.groupby("y"):
        stat(g.fwd8, str(y))

    print("\n== breadth分層(共振成員數,fwd8週) ==")
    stat(ep[ep.n_members == 2].fwd8, "2檔同振")
    stat(ep[ep.n_members >= 3].fwd8, "3檔+同振")

    # ---- LOTO + cluster bootstrap(fwd8,比照build_attention_validate.py規格) ----
    d8 = ep.dropna(subset=["fwd8"])
    if len(d8) >= 30 and d8.y.nunique() >= 3:
        print("\n== LOTO(逐年剔除,fwd8中位) ==")
        rows2 = []
        for yr in sorted(d8.y.unique()):
            sub = d8[d8.y != yr]
            if len(sub) >= 15:
                rows2.append((yr, sub.fwd8.median(), len(sub)))
        rows2.sort(key=lambda x: x[1])
        for yr, m, n in rows2[:3]:
            print(f"  剔除{yr}年後最壞: 中位{m:+.2f}% (剩n={n})")
        print(f"  為正比例: {sum(1 for _, m, _ in rows2 if m > 0) / len(rows2) * 100:.0f}%")

        rng = np.random.default_rng(SEED)
        years = d8.y.unique()
        groups = {yr: d8[d8.y == yr] for yr in years}
        abs_stats = []
        for _ in range(B):
            pick = rng.choice(years, size=len(years), replace=True)
            boot = pd.concat([groups[yr] for yr in pick])
            if len(boot) >= 15:
                abs_stats.append(boot.fwd8.median())
        abs_stats = np.array(abs_stats)
        alo, ahi = np.percentile(abs_stats, [2.5, 97.5])
        p_abs = (abs_stats <= 0).mean()
        print(f"  cluster bootstrap(年群,B={len(abs_stats)}): CI95=[{alo:+.2f}, {ahi:+.2f}], P(<=0)={p_abs:.4f}")
    else:
        print(f"\n樣本或年份數不足(n={len(d8)}),LOTO/bootstrap略過,先看描述統計")

    # ---- 面子檢查: 記憶體題材2025年8-9月是否真的被抓到(不是校準來源,只是驗證) ----
    print("\n== 面子檢查: 記憶體題材是否曾被抓到共振,何時 ==")
    mem = ev[ev.theme == "記憶體"] if "記憶體" in ev.theme.values else ev.iloc[0:0]
    if len(mem):
        for _, r in mem.iterrows():
            print(f"  {r.week.date()} {r.n_members}檔同振: {r.members}")
    else:
        print("  記憶體題材從未觸發>=2檔同週共振(訊號定義可能漏掉這個案例,或案例本身不是靠這條路徑)")

    ev.to_pickle("tmp_resonance_theme_events.pkl")
    ep.to_pickle("tmp_resonance_theme_episodes.pkl")
    wk_panel = pd.DataFrame(weekly_ret)
    wk_panel.to_pickle("tmp_resonance_weekly_panel.pkl")
    print("\n面板存 tmp_resonance_theme_events.pkl(未episode化)/"
          "tmp_resonance_theme_episodes.pkl(episode化,權益曲線用)/"
          "tmp_resonance_weekly_panel.pkl(全個股週收盤,權益曲線用)")


if __name__ == "__main__":
    main()
