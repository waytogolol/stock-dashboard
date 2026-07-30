# -*- coding: utf-8 -*-
"""恐慌梯度統一場考卷(2026-07-15深夜,從使用者XQ c1/c4/c13解剖引出的機制假說)
假說: 強勢股短線反彈期望=賣壓暴力程度的單調函數。溫和拉回=輪動(負),暴力流血=被迫賣壓(正)。
證據排列: E2縮量拉回-2.64 < c13+0.13 < c1+0.18 < c11+0.42 < c4+2.04 < 開低承接+1.95(不同口徑)

設計(預註冊,分桶看單調性,不做參數優化):
- 宇宙1379檔2019-07~2026-06;強勢背景=近40日曾有20%漲幅(15日高>40日低*1.2);成交值>1億
- 事件=下跌日(c<c1),進場T收盤,出場T+2開盤,扣0.45%成本
- 主軸I1=當日跌幅四桶: (0,-3%] / (-3,-6%] / (-6,-9%] / <-9%(≈跌停)
- 副軸I2=距10日高回檔: <10% / 10-20% / >=20%
- 極端格覆核I3=爆量(v>=5日高)有無
- 機制驗證: 2022+子集按融資使用率中位分高低(margin_flow.fin_use),斷頭機制→高融資組edge更大
- regime: 大盤月線上/下
判準: I1×I2梯度單調遞增且極端格淨中位>+1% → 機制成立,c4是曲線上的點,可設計單一規則
用法: python build_panic_gradient.py
"""
import sqlite3

import numpy as np
import pandas as pd

COST = 0.45


def stat(x):
    x = pd.Series(x).dropna()
    if len(x) < 15:
        return f"n={len(x)}少"
    return f"中位{x.median():+6.2f} 勝{(x > 0).mean() * 100:3.0f}% n={len(x):,}"


def main():
    conn = sqlite3.connect("capital_flow.db")
    px = pd.read_sql("SELECT code, date, open, close, volume, money FROM fm_daily_price "
                     "ORDER BY code, date", conn)
    mg = pd.read_sql("SELECT code, date, fin_use FROM margin_flow", conn)
    conn.close()
    px["date"] = pd.to_datetime(px.date)
    mg["date"] = pd.to_datetime(mg.date)
    mg_by = {c: g.set_index("date").fin_use for c, g in mg.groupby("code")}
    twii = pd.read_pickle("tmp_twii_long.pkl").dropna()

    rows = []
    for code, g in px.groupby("code"):
        g = g.sort_values("date").reset_index(drop=True)
        c, o, v = g.close, g.open, g.volume
        tv = g.money / 1e8
        c1 = c.shift(1)
        runner = c.rolling(15).max() > c.rolling(40).min() * 1.2
        ev = runner & (c < c1) & (tv > 1)
        dd = 100 * (c / c1 - 1)
        pull = 100 * (1 - c / c.rolling(10).max())
        vol_hi = v >= v.rolling(5).max()
        m = mg_by.get(code)
        for i in np.where(ev.fillna(False))[0]:
            if i + 2 >= len(g):
                continue
            ent, ex1, ext = c[i], o[i + 1], o[i + 2]
            if not (ent > 0 and ext > 0):
                continue
            fin = None
            if m is not None:
                s = m[m.index <= g.date[i]]
                if len(s):
                    fin = s.iloc[-1]
            rows.append({"code": code, "d0": g.date[i], "dd": dd[i], "pull": pull[i],
                         "volhi": bool(vol_hi[i]), "fin": fin,
                         "ret1": (ex1 / ent - 1) * 100 - COST if ex1 > 0 else np.nan,
                         "ret": (ext / ent - 1) * 100 - COST})
    df = pd.DataFrame(rows)
    df["i1"] = pd.cut(df.dd, [-99, -9, -6, -3, 0], labels=["<-9%", "-6~-9", "-3~-6", "0~-3"])
    df["i2"] = pd.cut(df.pull, [-1, 10, 20, 999], labels=["<10%", "10-20%", ">=20%"])
    print(f"強勢股下跌日事件: {len(df):,}筆 / {df.code.nunique()}檔 "
          f"({df.d0.min():%Y-%m}~{df.d0.max():%Y-%m})")

    print("\n== I1當日跌幅 × I2回檔深度 (淨報酬中位/勝率) ==")
    for i1 in ["0~-3", "-3~-6", "-6~-9", "<-9%"]:
        line = f"  跌{i1:>6}: "
        for i2 in ["<10%", "10-20%", ">=20%"]:
            sub = df[(df.i1 == i1) & (df.i2 == i2)]
            line += f"| 回檔{i2} {stat(sub.ret)} "
        print(line)

    print("\n== 極端格(<-9% × >=20%)的爆量覆核 ==")
    ext = df[(df.i1 == "<-9%") & (df.i2 == ">=20%")]
    print(f"  爆量: {stat(ext[ext.volhi].ret)}")
    print(f"  非爆量: {stat(ext[~ext.volhi].ret)}")

    print("\n== 出場日對照(深跌<=-6%事件): T+1開 vs T+2開 ==")
    deep0 = df[df.dd <= -6]
    print(f"  T+1開盤出: {stat(deep0.ret1)}")
    print(f"  T+2開盤出: {stat(deep0.ret)}")

    print("\n== 機制驗證: 融資使用率(2022+有資料子集) ==")
    sub = df[df.fin.notna() & (df.dd <= -6)].copy()
    med = sub.fin.median()
    print(f"  跌幅<=-6%事件, 融資使用率中位={med:.1f}%")
    print(f"  高融資(>中位): {stat(sub[sub.fin > med].ret)}")
    print(f"  低融資(<=中位): {stat(sub[sub.fin <= med].ret)}")

    tw20 = twii.rolling(20).mean()
    deep = df[df.dd <= -6]
    ab = deep.d0.map(lambda d: twii.asof(d) > tw20.asof(d))
    print("\n== 深跌(<=-6%)事件的大盤態勢 ==")
    print(f"  月線上: {stat(deep[ab].ret)}")
    print(f"  月線下: {stat(deep[~ab].ret)}")

    print("\n== 深跌(<=-6%)逐年 ==")
    deep2 = deep.copy()
    deep2["y"] = deep2.d0.dt.year
    for y, g in deep2.groupby("y"):
        print(f"  {y}: {stat(g.ret)}")

    df.to_pickle("tmp_panic_gradient_panel.pkl")
    print("\n面板存 tmp_panic_gradient_panel.pkl")


if __name__ == "__main__":
    main()
