# -*- coding: utf-8 -*-
"""⑫延伸:「score=4訊號來時,題材內該買誰?」兩題(使用者2026-07-15提案)
T1: 進場日成員在自身均線(MA5/10/20)之上 vs 之下,前瞻是否有差?
T2: 族群內按進場前股價表現排名,第一名(強者) vs 其他名次,前瞻是否有差?

設計(預註冊,單一設定不掃參數):
- 事件/成員/日期切點沿用build_score4_early_entry(score=4題材-月,top5成員,
  進場d2=15號起首個交易日收盤,出場d3=次月15號,超額=扣同期TWII)。
- T1: 進場日收盤 vs 自身MA5/MA10/MA20(調整價);絕對組比較+同題材配對
  (同事件內同時有之上/之下成員者,之上組均值-之下組均值)。
- T2: 主口徑=進場前20日報酬排名(月頻節奏);60日版只作穩健性複核。
  rank1(最強) vs 其他均值配對;末名(補漲候選)同樣看。
- 判準: 配對中位差>1pp且勝率>55%才算有選股價值;絕對組單邊好看但配對無差=題材行情噪音。
先驗提醒: 系統既有結論「位階不擋大魚」「週動能>20%絕對值有效」「龍頭破線=輪動非出貨」
→ 預期強者恆強方向,但題材內排名是新考卷。
注意: yfinance調整價;~87事件20題材聚類,快篩性質未bootstrap。
用法: python build_score4_member_select.py
"""
import pickle

import numpy as np
import pandas as pd

from build_score4_early_entry import MIN_MEMBERS, PRICE_CACHE, TWII_PKL, build_score_panel, seg_dates, px_ret


def stats(x):
    x = pd.Series(x).dropna()
    if len(x) == 0:
        return "n=0"
    return f"中位{x.median():+7.2f} 均{x.mean():+7.2f} 勝率{(x > 0).mean() * 100:3.0f}% n={len(x)}"


def main():
    panel, top5map = build_score_panel()
    prices = pickle.load(open(PRICE_CACHE, "rb"))

    def _close(v):
        c = v["Close"]
        if isinstance(c, pd.DataFrame):
            c = c.iloc[:, 0]
        return c.dropna()
    closes = {k: _close(v) for k, v in prices.items()}
    twii = pd.read_pickle(TWII_PKL).dropna()
    cal = twii.index[twii.index >= "2022-01-01"]

    ev = panel[(panel.score == 4) & (panel.sigT >= "2022-02-01") & (panel.sigT <= "2026-06-01")]
    rows = []
    for _, e in ev.iterrows():
        d = seg_dates(cal, e.sigT)
        if d is None:
            continue
        _, _, d2, d3 = d
        tw_fwd = (twii.asof(d3) / twii.asof(d2) - 1) * 100
        for c in top5map[e.industry].get(e.sigT, []):
            if c not in closes:
                continue
            s = closes[c][closes[c].index <= d2]
            if len(s) < 61 or s.index[-1] < d2 - pd.Timedelta(days=7):
                continue  # 需60日動能窗+近7日有價
            fwd = px_ret(closes[c], d2, d3)
            if fwd is None:
                continue
            c0 = s.iloc[-1]
            rows.append({
                "industry": e.industry, "sigT": e.sigT, "code": c,
                "ex": fwd - tw_fwd,
                "mom20": (c0 / s.iloc[-21] - 1) * 100, "mom60": (c0 / s.iloc[-61] - 1) * 100,
                "ma5": c0 > s.iloc[-5:].mean(), "ma10": c0 > s.iloc[-10:].mean(),
                "ma20": c0 > s.iloc[-20:].mean(),
            })
    df = pd.DataFrame(rows)
    nev = df.groupby(["industry", "sigT"]).ngroups
    print(f"成員-事件: {len(df)}筆 ({nev}題材-月, {df.industry.nunique()}題材, "
          f"{df.sigT.min():%Y-%m}~{df.sigT.max():%Y-%m})")

    print("\n== T1 進場日均線狀態(前瞻至次月15號, TWII超額%) ==")
    for ma, lab in [("ma20", "月線MA20"), ("ma10", "MA10"), ("ma5", "MA5")]:
        up, dn = df[df[ma]], df[~df[ma]]
        print(f"{lab} 之上: {stats(up.ex)}")
        print(f"{lab} 之下: {stats(dn.ex)}")
        pair = []
        for _, g in df.groupby(["industry", "sigT"]):
            if g[ma].any() and (~g[ma]).any():
                pair.append(g[g[ma]].ex.mean() - g[~g[ma]].ex.mean())
        print(f"  同題材配對(之上-之下): {stats(pair)}")

    print("\n== T2 族群內進場前動能排名(主口徑=20日報酬) ==")
    df["rk"] = df.groupby(["industry", "sigT"]).mom20.rank(ascending=False, method="first")
    for r in range(1, 6):
        print(f"  第{r}名: {stats(df[df.rk == r].ex)}")
    p1, pL = [], []
    for _, g in df.groupby(["industry", "sigT"]):
        if len(g) < MIN_MEMBERS:
            continue
        g = g.sort_values("rk")
        p1.append(g.ex.iloc[0] - g.ex.iloc[1:].mean())
        pL.append(g.ex.iloc[-1] - g.ex.iloc[:-1].mean())
    print(f"配對 第1名-其他均值: {stats(p1)}")
    print(f"配對 末名-其他均值: {stats(pL)}")

    print("\n逐年(第1名-其他, 20日口徑):")
    tmp = []
    for (ind, t), g in df.groupby(["industry", "sigT"]):
        if len(g) >= MIN_MEMBERS:
            g = g.sort_values("rk")
            tmp.append({"y": t.year, "d": g.ex.iloc[0] - g.ex.iloc[1:].mean()})
    tmp = pd.DataFrame(tmp)
    for y, g in tmp.groupby("y"):
        print(f"  {y}: {stats(g.d)}")

    print("\n穩健性複核(60日動能排名, 配對第1名-其他):")
    df["rk60"] = df.groupby(["industry", "sigT"]).mom60.rank(ascending=False, method="first")
    p60 = []
    for _, g in df.groupby(["industry", "sigT"]):
        if len(g) >= MIN_MEMBERS:
            g = g.sort_values("rk60")
            p60.append(g.ex.iloc[0] - g.ex.iloc[1:].mean())
    print(f"  {stats(p60)}")

    df.to_pickle("tmp_score4_member_select_panel.pkl")
    print("\n面板存 tmp_score4_member_select_panel.pkl")


if __name__ == "__main__":
    main()
