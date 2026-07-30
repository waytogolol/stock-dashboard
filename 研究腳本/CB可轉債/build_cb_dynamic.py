# -*- coding: utf-8 -*-
"""CB動態考卷(H-CB2計時器+H-CB3終局;磁吸靜態版已否定,動態版先驗已降,快篩定生死)
H-CB2: 標的首次站上轉換價130%(前60交易日未曾)=強贖計時窗開啟→公司派有動機守住→前瞻偏多?
H-CB3: 餘額3個月轉換速度(Δout_r)→急轉=戲近尾聲→前瞻轉弱?
資料: cb_overview日頻(ratio=stock_price/conv_price直接可算),前瞻用fm_daily_price
用法: python build_cb_dynamic.py
"""
import sqlite3

import numpy as np
import pandas as pd


def stat(x, lab):
    x = pd.Series(x).dropna()
    if len(x) < 15:
        print(f"  {lab}: n={len(x)}太少")
        return
    print(f"  {lab}: 超額中位{x.median():+6.2f}% 勝率{(x > 0).mean() * 100:3.0f}% n={len(x):,}")


def main():
    conn = sqlite3.connect("capital_flow.db")
    ov = pd.read_sql("SELECT cb_id, date, conv_price, outstanding, issuance, stock_price "
                     "FROM cb_overview", conn)
    px = pd.read_sql("SELECT code, date, close FROM fm_daily_price ORDER BY code, date", conn)
    conn.close()
    ov["date"] = pd.to_datetime(ov.date)
    px["date"] = pd.to_datetime(px.date)
    closes = {c: g.set_index("date").close for c, g in px.groupby("code")}
    twii = pd.read_pickle("tmp_twii_long.pkl").dropna()
    ov = ov[(ov.conv_price > 0) & (ov.stock_price > 0)]
    ov["code"] = ov.cb_id.str[:4]
    ov["ratio"] = ov.stock_price / ov.conv_price

    def fwd_ex(code, d, days=21):
        s = closes.get(code)
        if s is None:
            return None
        seg = s[s.index >= d]
        if len(seg) < days + 1 or seg.iloc[0] <= 0:
            return None
        tw = (twii.asof(seg.index[days]) / twii.asof(seg.index[0]) - 1) * 100
        return (seg.iloc[days] / seg.iloc[0] - 1) * 100 - tw

    # ---- H-CB2 首穿130% ----
    ev2 = []
    for cb, g in ov.groupby("cb_id"):
        g = g.sort_values("date").reset_index(drop=True)
        above = (g.ratio >= 1.3).values
        for i in np.where(above)[0]:
            if i < 60:
                continue
            if above[i - 60:i].any():
                continue
            r = fwd_ex(g.code[0], g.date[i])
            if r is not None:
                ev2.append({"y": g.date[i].year, "ex": r,
                            "out_r": g.outstanding[i] / g.issuance[i] if g.issuance[i] else np.nan})
            break  # 每檔CB只取第一次
    e2 = pd.DataFrame(ev2)
    print(f"== H-CB2 首穿130%計時窗(+21日TWII超額) ==")
    stat(e2.ex, "全部首穿事件")
    stat(e2[e2.out_r > 0.5].ex, "餘額>50%(逼轉動機在)")
    stat(e2[e2.out_r <= 0.5].ex, "餘額<=50%")

    # ---- H-CB3 轉換速度 ----
    ov["m"] = ov.date.dt.to_period("M")
    snap = ov.sort_values("date").groupby(["cb_id", "m"]).tail(1).copy()
    snap["out_r"] = snap.outstanding / snap.issuance
    snap = snap.sort_values(["cb_id", "date"])
    snap["d3"] = snap.groupby("cb_id").out_r.diff(3) * 100
    snap = snap[snap.d3.notna() & (snap.out_r > 0.05)]
    snap["bucket"] = pd.cut(snap.d3, [-101, -30, -5, 101], labels=["急轉(<-30pp)", "緩轉", "未轉"])
    ev3 = []
    for r in snap.sample(min(len(snap), 12000), random_state=42).itertuples():
        ex = fwd_ex(r.code, r.date)
        if ex is not None:
            ev3.append({"bucket": r.bucket, "ex": ex})
    e3 = pd.DataFrame(ev3)
    print(f"\n== H-CB3 餘額3月轉換速度(+21日TWII超額) ==")
    for b in ["急轉(<-30pp)", "緩轉", "未轉"]:
        stat(e3[e3.bucket == b].ex, b)


if __name__ == "__main__":
    main()
