# -*- coding: utf-8 -*-
"""漲停×跳空×題材=飆股配方驗證(使用者2026-07-15觀察提案)
主張: 短期飆股不可或缺漲停;近期出現過漲停+跳空(今低>昨高)+題材對 → 飆股候選。

設計(預註冊,單一設定不掃參數):
- 面板: 題材-月×前5大成員(口徑同build_score4_early_entry),sigT 2020-08~2026-03,
  價格=fm_daily_price未調整價(特徵需未調整;報酬配TWII價格指數=兩邊皆不含息一致)。
- 特徵窗=[進場日d2前一交易日往回20日](不含d2,確保進場可執行):
  LU=窗內有收盤鎖漲停(limit_up_detect口徑) GAP=窗內有今低>昨高(全日不回補跳空)
  四格: LU&GAP / LU only / GAP only / 無
- 前瞻: ex_hold=d2收→次月d3收超額(現行持有段); runup60=d2後60交易日內最高收盤漲幅,
  飆股=runup60>=30%(預註冊,50%當尾部複核);runup需>=40日資料。
- 三問驗證:
  ①score=4組四格梯度(可交易性) ②score<=2組同表(題材交乘:爛題材也有效=純型態非配方)
  ③case-control必要性: 飆股組vs非飆股組的事前LU/GAP比例+基準率
- 判準: LU&GAP格超額/飆股率明顯高於無格且score=4>score<=2 → 配方成立。
注意: 成員-事件按題材-月聚類,快篩未bootstrap;鎖死漲停日收盤買不到的實務摩擦未計。
用法: python build_limitup_gap_theme.py  (需fm_daily_price全量)
"""
import sqlite3

import numpy as np
import pandas as pd

from build_score4_early_entry import build_score_panel, seg_dates
from limit_up_detect import limit_prices

WIN = 20
RUNUP_D = 60
MIN_RUNUP_OBS = 40


def prep_stock(g):
    """單檔日線 -> close序列+特徵旗標(lu_close, gap)"""
    g = g.sort_values("date").reset_index(drop=True)
    prev = g.close.shift(1)
    lim = prev.map(lambda p: limit_prices(p)[0] if pd.notna(p) else np.nan)
    tol = lim.map(lambda u: 0.005 if pd.isna(u) else
                  (0.005 if u < 10 else 0.025 if u < 50 else 0.05 if u < 100
                   else 0.25 if u < 500 else 0.5 if u < 1000 else 2.5))
    lu = (g.close - lim).abs() < tol
    gap = g.low > g.high.shift(1)
    return pd.DataFrame({"close": g.close.values, "lu": lu.values, "gap": gap.values},
                        index=pd.DatetimeIndex(g.date))


def cell_stats(d):
    if len(d) == 0:
        return "n=0"
    return (f"超額中位{d.ex.median():+7.2f} 勝率{(d.ex > 0).mean() * 100:3.0f}% "
            f"飆股率{(d.runup >= 30).mean() * 100:4.1f}% (>=50%:{(d.runup >= 50).mean() * 100:4.1f}%) n={len(d)}")


def main():
    panel, top5map = build_score_panel()
    conn = sqlite3.connect("capital_flow.db")
    px = pd.read_sql("SELECT code, date, high, low, close FROM fm_daily_price", conn)
    conn.close()
    px["date"] = pd.to_datetime(px.date)
    stocks = {c: prep_stock(g) for c, g in px.groupby("code")}
    twii = pd.read_pickle("tmp_twii_long.pkl").dropna()
    cal = twii.index[twii.index >= "2019-06-01"]

    ev = panel[(panel.sigT >= "2020-08-01") & (panel.sigT <= "2026-03-01")]
    rows = []
    for _, e in ev.iterrows():
        d = seg_dates(cal, e.sigT)
        if d is None:
            continue
        _, _, d2, d3 = d
        for c in top5map[e.industry].get(e.sigT, []):
            s = stocks.get(c)
            if s is None:
                continue
            hist = s[s.index < d2]
            if len(hist) < WIN + 1 or hist.index[-1] < d2 - pd.Timedelta(days=7):
                continue
            w = hist.iloc[-WIN:]
            fut = s[s.index > d2]
            ent = hist.close.iloc[-1]
            ex_ = s[(s.index <= d3)]
            if len(fut) < MIN_RUNUP_OBS or ent <= 0:
                continue
            exit_px = ex_.close.iloc[-1] if len(ex_) else np.nan
            tw = (twii.asof(d3) / twii.asof(d2) - 1) * 100
            rows.append({
                "industry": e.industry, "sigT": e.sigT, "code": c, "score": e.score,
                "lu": bool(w.lu.any()), "gap": bool(w.gap.any()),
                "ex": (exit_px / ent - 1) * 100 - tw,
                "runup": (fut.close.iloc[:RUNUP_D].max() / ent - 1) * 100,
            })
    df = pd.DataFrame(rows).dropna(subset=["ex", "runup"])
    df["cell"] = np.select(
        [df.lu & df.gap, df.lu & ~df.gap, ~df.lu & df.gap],
        ["LU&GAP", "LU only", "GAP only"], "無")
    print(f"成員-事件: {len(df):,}筆 ({df.groupby(['industry', 'sigT']).ngroups}題材-月, "
          f"{df.sigT.min():%Y-%m}~{df.sigT.max():%Y-%m})")

    for lab, sub in [("score=4(題材對)", df[df.score == 4]), ("score<=2(題材不對,對照)", df[df.score <= 2])]:
        print(f"\n== {lab} 四格 ==")
        for cell in ["LU&GAP", "LU only", "GAP only", "無"]:
            print(f"  {cell:<9}: {cell_stats(sub[sub.cell == cell])}")

    print("\n== case-control 必要性(全樣本) ==")
    boom, rest = df[df.runup >= 30], df[df.runup < 30]
    print(f"飆股組(runup60>=30%, n={len(boom)}): 事前有LU {boom.lu.mean() * 100:.1f}% | "
          f"有GAP {boom.gap.mean() * 100:.1f}% | 兩者皆有 {(boom.lu & boom.gap).mean() * 100:.1f}%")
    print(f"非飆股組(n={len(rest)}):            事前有LU {rest.lu.mean() * 100:.1f}% | "
          f"有GAP {rest.gap.mean() * 100:.1f}% | 兩者皆有 {(rest.lu & rest.gap).mean() * 100:.1f}%")

    print("\n== 逐年(score=4的LU&GAP格) ==")
    s4 = df[(df.score == 4) & (df.cell == "LU&GAP")].copy()
    s4["y"] = s4.sigT.dt.year
    for y, g in s4.groupby("y"):
        print(f"  {y}: {cell_stats(g)}")

    # ---- 追加複核(2026-07-15晚,混合表梯度被同題材配對翻案後的正確層級) ----
    print("\n== 同題材配對(LU成員-無LU成員, score=4) ==")
    pair = []
    for _, g in df[df.score == 4].groupby(["industry", "sigT"]):
        if g.lu.any() and (~g.lu).any():
            pair.append(g[g.lu].ex.mean() - g[~g.lu].ex.mean())
    pair = pd.Series(pair)
    print(f"  持有段超額差: 中位{pair.median():+.2f}pp 勝率{(pair > 0).mean() * 100:.0f}% n={len(pair)}"
          f"  → 成員層無選股價值(與動能排名同構=題材內輪動)")

    print("\n== 題材-月層級: 族群內有無漲停成員=點火確認 ==")
    tm = df.groupby(["industry", "sigT", "score"]).agg(
        ex=("ex", "mean"), anylu=("lu", "any"), nlu=("lu", "sum")).reset_index()
    for lab, sub in [("score=4", tm[tm.score == 4]), ("score<=2對照", tm[tm.score <= 2])]:
        a, b = sub[sub.anylu], sub[~sub.anylu]
        print(f"  {lab}: 有LU {a.ex.median():+6.2f}/{(a.ex > 0).mean() * 100:3.0f}% n={len(a)} | "
              f"無LU {b.ex.median():+6.2f}/{(b.ex > 0).mean() * 100:3.0f}% n={len(b)}")
    s4t = tm[tm.score == 4]
    for k, lab in [(0, "0家"), (1, "1家"), (2, ">=2家")]:
        g = s4t[s4t.nlu == k] if k < 2 else s4t[s4t.nlu >= 2]
        print(f"  劑量{lab}: 中位{g.ex.median():+6.2f} 勝率{(g.ex > 0).mean() * 100:3.0f}% n={len(g)}")

    df.to_pickle("tmp_limitup_gap_panel.pkl")
    print("\n面板存 tmp_limitup_gap_panel.pkl")


if __name__ == "__main__":
    main()
