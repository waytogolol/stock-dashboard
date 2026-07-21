# -*- coding: utf-8 -*-
"""大盤溫度計延伸:MACD/KD位階化研究(使用者2026-07-21提案)
不看黃金/死亡交叉(散戶常用、效果不穩定的二元事件),改測「當下數值在自身過去240個交易日(約1年)分佈裡
的百分位」——比照本專案已驗證過的外資位階/券資比位階慣例(絕對門檻跨股不可比,位階化才是水準型特徵正解)。
標的用TAIEX指數(溫度計是市場層級量表,不算個股),日線+週線各算一條MACD位階、一條KD位階,共4條序列。

⚠設計紀律(比照共振研究同一套教訓):不用這次(2026-07-17)的真實恐慌讀數校準門檻,先用文獻慣用參數
(MACD 12,26,9 / KD 9,3,3)算完位階再回頭看這次讀數落在哪裡,只做面子檢查不做校準。

驗證分兩層,第二層更重要:
①獨立效力: 位階極端(<=5或>=95百分位)時,往後k=10/20/60交易日TAIEX報酬,LOTO+cluster bootstrap
②正交性(重點): 在既有溫度計「恐慌燈」已亮的區間內,位階極端能不能進一步分辨報酬強弱;
  在溫度計未亮的平淡期,位階極端單獨還有沒有邊際效果——如果只是溫度計的影子(資訊重疊),不建議加燈
用法: python build_thermo_macd_kd.py
"""
import sqlite3

import numpy as np
import pandas as pd

SEED = 42
B = 10000
WIN = 240   # 日線位階窗(交易日,約1年)
WWIN = 52   # 週線位階窗(週,約1年)


def stat(x, lab):
    x = pd.Series(x).dropna()
    if len(x) < 15:
        print(f"  {lab}: n={len(x)}太少")
        return None
    print(f"  {lab}: 中位{x.median():+6.2f}% 均值{x.mean():+6.2f}% 勝率{(x > 0).mean() * 100:3.0f}% n={len(x):,}")
    return x


def pct_rank(s, win):
    """s在自身trailing win窗內的百分位(0-100),排除look-ahead(只用含當日在內的過去win筆)"""
    return s.rolling(win, min_periods=win // 2).apply(
        lambda w: (w <= w.iloc[-1]).mean() * 100, raw=False)


def macd(close):
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    dif = ema12 - ema26
    dea = dif.ewm(span=9, adjust=False).mean()
    return dif - dea  # MACD柱狀圖


def kd(high, low, close, n=9, k_smooth=3, d_smooth=3):
    ln = low.rolling(n, min_periods=n).min()
    hn = high.rolling(n, min_periods=n).max()
    rsv = (close - ln) / (hn - ln).replace(0, np.nan) * 100
    k = rsv.ewm(alpha=1 / k_smooth, adjust=False).mean()
    d = k.ewm(alpha=1 / d_smooth, adjust=False).mean()
    return k - d  # K-D差值,同MACD柱狀圖概念,正負代表偏多/偏空動能


def loto_bootstrap(sub, val_col, label):
    sub = sub.dropna(subset=[val_col]).copy()
    sub["y"] = pd.to_datetime(sub.index if "date" not in sub.columns else sub["date"]).year \
        if not isinstance(sub.index, pd.DatetimeIndex) else sub.index.year
    if len(sub) < 30 or sub["y"].nunique() < 3:
        print(f"    [{label}] n={len(sub)}或年份不足,略過LOTO/bootstrap")
        return
    rows = []
    for yr in sorted(sub["y"].unique()):
        s2 = sub[sub["y"] != yr]
        if len(s2) >= 15:
            rows.append((yr, s2[val_col].median(), len(s2)))
    if not rows:
        return
    rows.sort(key=lambda x: x[1])
    print(f"    LOTO最壞: 剔{rows[0][0]}年後中位{rows[0][1]:+.2f}%(剩n={rows[0][2]}), "
          f"為正比例{sum(1 for _, m, _ in rows if m > 0) / len(rows) * 100:.0f}%")
    rng = np.random.default_rng(SEED)
    years = sub["y"].unique()
    groups = {yr: sub[sub["y"] == yr] for yr in years}
    abs_stats = []
    for _ in range(B):
        pick = rng.choice(years, size=len(years), replace=True)
        boot = pd.concat([groups[yr] for yr in pick])
        if len(boot) >= 15:
            abs_stats.append(boot[val_col].median())
    abs_stats = np.array(abs_stats)
    alo, ahi = np.percentile(abs_stats, [2.5, 97.5])
    p_abs = (abs_stats <= 0).mean()
    print(f"    bootstrap(年群,B={len(abs_stats)}): CI95=[{alo:+.2f}, {ahi:+.2f}], P(<=0)={p_abs:.4f}")


def main():
    conn = sqlite3.connect("capital_flow.db")
    d = pd.read_sql("SELECT date, open, high, low, close FROM index_daily WHERE market='TAIEX' ORDER BY date",
                     conn, parse_dates=["date"]).set_index("date")
    conn.close()

    # ---- 日線位階 ----
    d["macd_pr"] = pct_rank(macd(d.close), WIN)
    d["kd_pr"] = pct_rank(kd(d.high, d.low, d.close), WIN)
    for k in (10, 20, 60):
        d[f"fwd{k}"] = (d.close.shift(-k) / d.close - 1) * 100
    d["y"] = d.index.year

    # ---- 週線位階(W-FRI OHLC重組) ----
    w = d[["open", "high", "low", "close"]].resample("W-FRI").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    w["macd_pr"] = pct_rank(macd(w.close), WWIN)
    w["kd_pr"] = pct_rank(kd(w.high, w.low, w.close), WWIN)
    for k in (4, 8, 12):
        w[f"fwd{k}"] = (w.close.shift(-k) / w.close - 1) * 100
    w["y"] = w.index.year

    print(f"日線: {len(d)}筆 {d.index.min().date()}~{d.index.max().date()}")
    print(f"週線: {len(w)}筆 {w.index.min().date()}~{w.index.max().date()}\n")

    # ---- ①獨立效力: 極端位階(<=5 / >=95百分位)往後報酬 ----
    print("== ①獨立效力(日線,位階<=5=超賣 / >=95=超買) ==")
    for name, col in [("MACD位階", "macd_pr"), ("KD位階", "kd_pr")]:
        print(f" {name}")
        for k in (10, 20, 60):
            lo = d[d[col] <= 5]
            hi = d[d[col] >= 95]
            print(f"  fwd{k} 超賣組:", end="")
            stat(lo[f"fwd{k}"], f"位階<=5")
            print(f"  fwd{k} 超買組:", end="")
            stat(hi[f"fwd{k}"], f"位階>=95")
        sub = d[d[col] <= 5].dropna(subset=["fwd20"])[["fwd20", "y"]]
        print(f"  -- 超賣組fwd20 LOTO+bootstrap --")
        loto_bootstrap(sub, "fwd20", f"{name}超賣")

    print("\n== ①獨立效力(週線,位階<=5 / >=95) ==")
    for name, col in [("週MACD位階", "macd_pr"), ("週KD位階", "kd_pr")]:
        print(f" {name}")
        for k in (4, 8, 12):
            lo = w[w[col] <= 5]
            hi = w[w[col] >= 95]
            print(f"  fwd{k}週 超賣組:", end="")
            stat(lo[f"fwd{k}"], "位階<=5")
            print(f"  fwd{k}週 超買組:", end="")
            stat(hi[f"fwd{k}"], "位階>=95")
        sub = w[w[col] <= 5].dropna(subset=["fwd8"])[["fwd8", "y"]]
        print(f"  -- 超賣組fwd8週 LOTO+bootstrap --")
        loto_bootstrap(sub, "fwd8", f"{name}超賣")

    # ---- ②正交性: 對比既有溫度計恐慌燈(甜蜜格並發>=20,60交易日持有窗) ----
    print("\n== ②正交性檢查: 對比既有恐慌溫度計燈號 ==")
    try:
        lf = pd.read_pickle("tmp_limit_flags.pkl")
        pool = set(lf[~lf.code.str.startswith("00")].code.unique())
        conn = sqlite3.connect("capital_flow.db")
        px = pd.read_sql("SELECT code, date, close, money FROM fm_daily_price WHERE close>0", conn,
                          parse_dates=["date"])
        conn.close()
        px = px[px.code.isin(pool)]
        dates_all = sorted(d.index)
        sweet = pd.Series(0, index=dates_all)
        for code, g in px.groupby("code"):
            g = g.sort_values("date").reset_index(drop=True)
            cl, c1 = g.close, g.close.shift(1)
            run = cl.rolling(15).max() > cl.rolling(40).min() * 1.2
            ddp = (cl / c1 - 1) * 100
            pull = (1 - cl / cl.rolling(10).max()) * 100
            tv = g.money / 1e8
            sw = (run & (tv > 1) & (ddp <= -6) & (ddp > -9) & (pull >= 20)).fillna(False)
            hit_dates = g.date[sw]
            for hd in hit_dates:
                if hd in sweet.index:
                    sweet[hd] += 1
        thd = sweet[sweet >= 20].index
        pos = {dt: i for i, dt in enumerate(dates_all)}
        lit = pd.Series(False, index=dates_all)
        for dt in dates_all:
            i = pos[dt]
            recent = [t for t in thd if t <= dt and pos[t] + 60 > i]
            if recent:
                lit[dt] = True
        d["thermo_lit"] = lit.reindex(d.index).fillna(False)

        print(f"  溫度計燈亮天數占比: {d.thermo_lit.mean() * 100:.1f}%")
        for name, col in [("MACD位階", "macd_pr"), ("KD位階", "kd_pr")]:
            print(f" {name} x 溫度計燈號 交叉(fwd20)")
            for lit_flag, lab in [(True, "燈亮"), (False, "燈滅")]:
                sub = d[d.thermo_lit == lit_flag]
                extreme = sub[sub[col] <= 5]
                normal = sub[(sub[col] > 5)]
                stat(extreme.fwd20, f"  {lab}且位階<=5(極端)")
                stat(normal.fwd20, f"  {lab}且位階>5(一般)")
    except Exception as e:
        print(f"  正交性檢查失敗: {type(e).__name__}: {e}")

    # ---- 面子檢查: 這次(2026-07-17前後)位階讀數,只看不校準 ----
    print("\n== 面子檢查: 本輪恐慌episode(2026-07-14起)的MACD/KD位階讀數 ==")
    for dt in ["2026-07-10", "2026-07-14", "2026-07-17", "2026-07-20", "2026-07-21"]:
        ts = pd.Timestamp(dt)
        if ts in d.index:
            r = d.loc[ts]
            print(f"  {dt}: 日MACD位階={r.macd_pr:.0f} 日KD位階={r.kd_pr:.0f}")
    wk_dates = w.index[w.index >= "2026-06-01"]
    for wd in wk_dates:
        r = w.loc[wd]
        print(f"  週{wd.date()}: 週MACD位階={r.macd_pr:.0f} 週KD位階={r.kd_pr:.0f}")

    d.to_pickle("tmp_thermo_macd_kd_daily.pkl")
    w.to_pickle("tmp_thermo_macd_kd_weekly.pkl")
    print("\n面板存 tmp_thermo_macd_kd_daily.pkl / tmp_thermo_macd_kd_weekly.pkl")


if __name__ == "__main__":
    main()
