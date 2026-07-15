# -*- coding: utf-8 -*-
"""使用者XQ短線策略重現驗證(2026-07-15深夜,使用者提供XQ腳本)
策略本質: 強勢/高波動/高流動股的短線黑K回檔,T收盤進場,T+2開盤出場(~2日持有)
啟用條件(進score): 1,2,4,7,8,9,10,11,12,13;獨立觸發: 14,15;停用: 3,5,6(使用者標註需維修)
最終閘: score>0 且 c>昨收*0.91 且 成交值>3億 且 ATR5/昨收>4%,或cond14/15

翻譯近似(誠實註記):
- 市場相對流動性門檻(getsymbolField×0.003~0.005)按使用者註解換算絕對值0.6/0.8/1億
- cond9法人10日買超用inst_flow(僅2022起,之前該條false)
- 宇宙=研究池1379檔(進過排行榜的偏強池,存活者偏差方向=高估)
- 出場T+2開盤;成本0.45%來回;報酬為原始淨額(2日窗beta小,另附TWII粗略超額)
用法: python build_xq_dipbuy_test.py
"""
import sqlite3

import numpy as np
import pandas as pd

COST = 0.45


def roll_all(b, n):
    return b.rolling(n).sum() == n


def cnt(b, n):
    return b.rolling(n).sum()


def prep(g, inst):
    c, o, h, l, v = g.close, g.open, g.high, g.low, g.volume
    tv = g.money / 1e8  # 成交值(億)
    c1, c2, c3 = c.shift(1), c.shift(2), c.shift(3)
    ma5, ma10, ma20 = c.rolling(5).mean(), c.rolling(10).mean(), c.rolling(20).mean()
    tr = pd.concat([h - l, (h - c1).abs(), (l - c1).abs()], axis=1).max(axis=1)
    atr5, atr14 = tr.rolling(5).mean(), tr.rolling(14).mean()
    ret1 = 100 * (c / c1 - 1)
    sd14 = ret1.rolling(14).std()
    f = pd.DataFrame(index=g.index)
    above5 = (c > ma5).shift(1)
    above10 = (c > ma10).shift(1)
    f["c1"] = roll_all(above5.fillna(False), 5) & (c < o) & (c < c1 * 0.95) & (c < ma5) & (c > ma10) & (tv > 2)
    f["c2"] = (c > c.rolling(120).max() * 0.8) & roll_all(above10.fillna(False), 10) & (c < o) & (c > c1 * 0.91) & (c < ma10) & (tv > 2)
    f["c4"] = (c.rolling(15).max() > c.rolling(40).min() * 1.3) & (c < c.rolling(10).max() * 0.8) & \
              (c < c1 * 0.94) & (o > c) & (o > c * 1.03) & (v >= v.rolling(5).max()) & (tv > 1) & (v >= v.rolling(10).mean())
    f["c7"] = (c1 > c2) & (c2 > c3) & (c < o) & (tv > 0.6) & (l.shift(1) > l.shift(2)) & (c > ma20 * 1.1) & (c < c.shift(20) * 1.4)
    tiao = 100 * (o / c2 - 1)
    f["c8"] = (cnt((tiao > 3), 5) > 0) & (c < o) & (100 * atr5 / c1 > 4) & (c < ma5) & (c > ma10) & \
              (c > c.rolling(10).min() * 1.1) & (tv > 0.8)
    if inst is not None:
        fsum = inst.foreign_net.rolling(10).sum().shift(1)
        tsum = inst.trust_net.rolling(10).sum().shift(1)
        chip = (fsum > 0) & (tsum > 0)
        chip = chip.reindex(g.index).fillna(False)
    else:
        chip = pd.Series(False, index=g.index)
    f["c9"] = (tv > 0.6) & chip & (c < o) & (c < c1) & (c1 > c2) & (c2 > c3) & (100 * atr5 / c1 > 3)
    ma5d, ma10d = ma5 - ma5.shift(10), ma10 - ma10.shift(10)
    f["c10"] = (ma10 > ma10.shift(10) * 1.01) & (ma5d > ma10d) & (c < o) & (sd14 > 4) & (tv > 1)
    body = o - c
    f["c11"] = (tv > 3) & (c1 < o.shift(1)) & (c < o) & (c < c1 * 0.95) & (c > c1 * 0.91) & (body.rolling(10).max() <= body)
    f["c12"] = (c1 >= c1.rolling(90).max()) & (c > (c1 + o.shift(1)) * 0.5) & (v > v.shift(1) + v.shift(2)) & \
               (100 * atr14 / c1 > 4) & (tv > 0.6)
    f["c13"] = (tv > 3) & (c < c1) & (c1 < c2) & (cnt((c < c1), 10) < 5) & (100 * atr5 / c1 > 4) & \
               (c < ma5) & (c > ma10) & (c > c.shift(10) * 1.1)
    f["c14"] = (c < c1) & (c2 > c1) & (tv > 1) & (c > c.rolling(90).max() * 0.9) & (c3 < c2) & \
               (ma10 > ma20) & (ma10 > ma10.shift(5)) & (ma20 > ma20.shift(5)) & (v < v.rolling(5).max()) & \
               (c < c1 * 0.97) & (100 * atr5 / c1 > 3)
    f["c15"] = (cnt((l > h.shift(1)), 10) > 0) & (c < c1) & (c > c1 * 0.91) & (c1 < c2) & (v < v.shift(1)) & \
               (ma10 > ma10.shift(3)) & (c < ma5) & (100 * atr5 / c1 > 3) & (tv > 1)
    score = f[["c1", "c2", "c4", "c7", "c8", "c9", "c10", "c11", "c12", "c13"]].sum(axis=1)
    gate = (score > 0) & (c > c1 * 0.91) & (tv > 3) & (100 * atr5 / c1 > 4)
    f["sig"] = gate | f.c14 | f.c15
    return f


def main():
    conn = sqlite3.connect("capital_flow.db")
    px = pd.read_sql("SELECT code, date, open, high, low, close, volume, money FROM fm_daily_price "
                     "ORDER BY code, date", conn)
    inst = pd.read_sql("SELECT code, date, foreign_net, trust_net FROM inst_flow", conn)
    conn.close()
    px["date"] = pd.to_datetime(px.date)
    inst["date"] = pd.to_datetime(inst.date)
    inst_by = {c: g.set_index("date")[["foreign_net", "trust_net"]] for c, g in inst.groupby("code")}
    twii = pd.read_pickle("tmp_twii_long.pkl").dropna()

    rows = []
    conds = ["c1", "c2", "c4", "c7", "c8", "c9", "c10", "c11", "c12", "c13", "c14", "c15"]
    for code, g in px.groupby("code"):
        g = g.sort_values("date").set_index("date")
        if len(g) < 130:
            continue
        f = prep(g, inst_by.get(code))
        sig_days = f.index[f.sig.fillna(False)]
        pos = {d: i for i, d in enumerate(g.index)}
        for d in sig_days:
            i = pos[d]
            if i + 2 >= len(g):
                continue
            ent, ext = g.close.iloc[i], g.open.iloc[i + 2]
            if not (ent > 0 and ext > 0):
                continue
            tw = (twii.asof(g.index[i + 1]) / twii.asof(d) - 1) * 100
            r = {"code": code, "d0": d, "ret": (ext / ent - 1) * 100 - COST,
                 "ex": (ext / ent - 1) * 100 - tw - COST}
            for cc in conds:
                r[cc] = bool(f[cc].loc[d]) if pd.notna(f[cc].loc[d]) else False
            rows.append(r)
    df = pd.DataFrame(rows)
    print(f"訊號: {len(df):,}筆 / {df.code.nunique()}檔 ({df.d0.min():%Y-%m}~{df.d0.max():%Y-%m}), "
          f"月均{len(df) / ((df.d0.max() - df.d0.min()).days / 30.4):.0f}件")

    def stat(x, lab):
        x = pd.Series(x).dropna()
        if len(x) < 10:
            print(f"  {lab}: n={len(x)}太少")
            return
        print(f"  {lab}: 淨中位{x.median():+6.2f}% 均{x.mean():+6.2f}% 勝率{(x > 0).mean() * 100:3.0f}% n={len(x):,}")

    print(f"\n== 全訊號(T收→T+2開,扣{COST}%) ==")
    stat(df.ret, "原始淨額")
    stat(df.ex, "TWII粗略超額")

    print("\n== 逐條件(原始淨額;多條件同日重複計) ==")
    for cc in conds:
        stat(df[df[cc]].ret, cc)

    print("\n== 逐年 ==")
    df["y"] = df.d0.dt.year
    for y, g in df.groupby("y"):
        stat(g.ret, str(y))

    tw20 = twii.rolling(20).mean()
    above = df.d0.map(lambda d: twii.asof(d) > tw20.asof(d))
    print("\n== 大盤態勢 ==")
    stat(df[above].ret, "月線上")
    stat(df[~above].ret, "月線下")

    df.to_pickle("tmp_xq_dipbuy_panel.pkl")
    print("\n面板存 tmp_xq_dipbuy_panel.pkl")


if __name__ == "__main__":
    main()
