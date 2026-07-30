# -*- coding: utf-8 -*-
"""恐慌梯度甜蜜格穩健性體檢(使用者2026-07-16問:參數自己設計不夠嚴謹?隔日開盤進場如何?)
方法論立場: 參數不重新優化(那是過擬合的開始);正確檢驗=①逐參數敏感度(一次動一個,
看edge是高原還是尖刺) ②剔除最肥年/大盤黑K日的組成穩健性 ③進場時點分解(尾盤vs隔日開盤
=隔夜跳空吃掉多少)。基準規則凍結: 15日高>40日低*1.2 × 回檔>=20% × 當日跌(-9,-6] × 成交值>1億,
T收盤進T+2開盤出,扣0.45%。
用法: python build_panic_sweetspot_robust.py
"""
import sqlite3

import numpy as np
import pandas as pd

COST = 0.45


def stat(x, lab):
    x = pd.Series(x).dropna()
    if len(x) < 15:
        print(f"  {lab}: n={len(x)}太少")
        return
    print(f"  {lab}: 中位{x.median():+6.2f}% 勝率{(x > 0).mean() * 100:3.0f}% n={len(x):,}")


def main():
    conn = sqlite3.connect("capital_flow.db")
    px = pd.read_sql("SELECT code, date, open, close, money FROM fm_daily_price ORDER BY code, date", conn)
    conn.close()
    px["date"] = pd.to_datetime(px.date)
    rows = []
    for code, g in px.groupby("code"):
        g = g.sort_values("date").reset_index(drop=True)
        c, o = g.close, g.open
        tv = g.money / 1e8
        c1 = c.shift(1)
        dd = 100 * (c / c1 - 1)
        pull = 100 * (1 - c / c.rolling(10).max())
        run_ratio = c.rolling(15).max() / c.rolling(40).min()
        cand = (dd <= -5) & (run_ratio > 1.1) & (pull >= 12) & (tv > 0.5)  # 寬鬆超集,細篩在分析層
        for i in np.where(cand.fillna(False))[0]:
            if i + 3 >= len(g):
                continue
            ent, o1, o2, o3 = c[i], o[i + 1], o[i + 2], o[i + 3]
            if not (ent > 0 and o1 > 0 and o2 > 0):
                continue
            rows.append({"code": code, "d0": g.date[i], "dd": dd[i], "pull": pull[i],
                         "rr": run_ratio[i], "tv": tv[i],
                         "on": (o1 / ent - 1) * 100,
                         "co2": (o2 / ent - 1) * 100 - COST,
                         "o1o2": (o2 / o1 - 1) * 100 - COST,
                         "o1o3": (o3 / o1 - 1) * 100 - COST if o3 > 0 else np.nan,
                         "co3": (o3 / ent - 1) * 100 - COST if o3 > 0 else np.nan})
    df = pd.DataFrame(rows)

    def base_mask(d, ddlo=-9, ddhi=-6, pmin=20, rmin=1.2, tvmin=1.0):
        return (d.dd > ddlo) & (d.dd <= ddhi) & (d.pull >= pmin) & (d.rr > rmin) & (d.tv > tvmin)

    base = df[base_mask(df)]
    print(f"基準規則: n={len(base):,}")
    print("\n== 進場時點分解 ==")
    stat(base.on, "隔夜跳空段(T收→T+1開,未扣成本)")
    stat(base.co2, "尾盤進T+2開出(基準)      ")
    stat(base.co3, "尾盤進T+3開出            ")
    stat(base.o1o2, "隔日開進T+2開出(持1天)    ")
    stat(base.o1o3, "隔日開進T+3開出(持2天)    ")

    print("\n== 逐參數敏感度(一次動一個,其餘=基準) ==")
    for lab, kw in [("跌幅帶(-8,-5]", dict(ddlo=-8, ddhi=-5)), ("跌幅帶(-10,-7]", dict(ddlo=-10, ddhi=-7)),
                    ("回檔>=15%", dict(pmin=15)), ("回檔>=25%", dict(pmin=25)),
                    ("漲幅背景1.15x", dict(rmin=1.15)), ("漲幅背景1.3x", dict(rmin=1.3)),
                    ("成交值>0.5億", dict(tvmin=0.5)), ("成交值>2億", dict(tvmin=2.0))]:
        stat(df[base_mask(df, **kw)].co2, lab)

    print("\n== 組成穩健性 ==")
    b = base.copy()
    b["y"] = b.d0.dt.year
    stat(b[b.y != 2025].co2, "剔除2025年")
    stat(b[b.y != 2020].co2, "剔除2020年")
    twii = pd.read_pickle("tmp_twii_long.pkl").dropna()
    twr = twii.pct_change() * 100
    mkt = b.d0.map(lambda d: twr.asof(d))
    stat(b[mkt > -2].co2, "剔除大盤<-2%日")
    stat(b[mkt > -1].co2, "剔除大盤<-1%日")

    df.to_pickle("tmp_panic_sweetspot_events.pkl")
    print("\n寬鬆超集面板存 tmp_panic_sweetspot_events.pkl")


if __name__ == "__main__":
    main()
