# -*- coding: utf-8 -*-
"""跌深贏家解剖+安穩進場考卷(2026-07-31凌晨,使用者三問:「跌更深的贏家是誰?有基本面嗎?成交值夠嗎?
很多人愛接刀,如何選安穩進場點,不可能每次買在最低」)。

背景: 領導權考卷E解剖判決「唯一跨episode重複的贏家特徵=跌更深」→本卷把跌最深組(池內dd120最深20%)
解剖到可執行:
  Q1 成分: 跌深組的成交值分布(接不接得住)
  Q2 基本面: 營收YoY>0 vs <=0 vs 無資料 分層k60(2018後episode,fm_month_rev自算YoY)
  Q3 成交值分層: 0.5-1億/1-3億/>=3億 k60(流動性門檻多少才安全)
  Q4 進場戰術對照(核心,回答「不用買最低點」):同一批股票三種進法,出場同定t0+60收盤:
     T0 止穩日t0收盤直接買(考卷原口徑)
     T1 等個股自己止穩: t0後15日內首日「低點5日不創低∧量<=前10日峰量一半」(個股版P5)收盤買
     T2 等站回10日線: t0後15日內首日收盤>MA10買
     比較: 覆蓋率(等不到=漏單)/報酬(同出場日)/MAE(進場後最深浮虧)/等待成本(進場價距t0價)
episode=領導權考卷口徑(加權+櫃買聯集,30日去重);池=tv20>=0.5億。零前視。
"""
import sqlite3
import numpy as np
import pandas as pd

from build_rebound_leadership import find_episodes

DB = "capital_flow.db"


def pivots():
    con = sqlite3.connect(DB)
    px = pd.read_sql("SELECT code, date, close, low, volume, money FROM fm_daily_price", con)
    rev = pd.read_sql("SELECT code, date, revenue FROM fm_month_rev", con)
    con.close()
    px["date"] = pd.to_datetime(px["date"])
    pv = {c: px.pivot_table(index="date", columns="code", values=c, aggfunc="last")
          for c in ("close", "low", "volume", "money")}
    pv["close"] = pv["close"].where(pv["close"] > 0)
    rev["date"] = pd.to_datetime(rev["date"])
    rpv = rev.pivot_table(index="date", columns="code", values="revenue", aggfunc="last")
    yoy = rpv / rpv.shift(12) - 1
    return pv, yoy


def episode_list():
    eps = []
    for m in ("TAIEX", "TPEx"):
        t0s, _ = find_episodes(m)
        eps += t0s
    eps = sorted(eps)
    out, last = [], None
    for d in eps:
        if last is None or (d - last).days > 30:
            out.append(d); last = d
    return out


def main():
    pv, yoy = pivots()
    close, low, vol, money = pv["close"], pv["low"], pv["volume"], pv["money"]
    dd120 = close / close.rolling(120).max() - 1
    tv20 = money.rolling(20).mean() / 1e8
    ma10 = close.rolling(10).mean()
    cal = close.index
    eps = [e for e in episode_list() if e in close.index]
    print(f"episodes聯集: {len(eps)}個")
    rows = []
    for t0 in eps:
        i = cal.get_loc(t0)
        if i + 75 >= len(cal) or i < 250:
            continue
        exit_i = i + 60
        snap = pd.DataFrame({"dd": dd120.iloc[i], "tv": tv20.iloc[i]}).dropna()
        u = snap[snap["tv"] >= 0.5]
        if len(u) < 100:
            continue
        deep = u[u["dd"] <= u["dd"].quantile(0.2)]
        ym = yoy.index.asof(t0 - pd.Timedelta(days=12))   # 用t0前已公告月(上月10日公告,保守退12日)
        for code in deep.index:
            c = close[code]; e0 = c.iloc[i]
            if pd.isna(e0) or pd.isna(c.iloc[exit_i]):
                continue
            # T1 個股版P5 / T2 站回10日線
            entries = {"T0": i, "T1": None, "T2": None}
            lo, vo = low[code], vol[code]
            for j in range(i + 1, i + 16):
                if entries["T1"] is None:
                    l5 = lo.iloc[j - 5:j].min(); vmax = vo.iloc[j - 10:j].max()
                    if pd.notna(l5) and pd.notna(vmax) and lo.iloc[j] > l5 and vo.iloc[j] <= vmax * 0.5:
                        entries["T1"] = j
                if entries["T2"] is None and pd.notna(ma10[code].iloc[j]) and c.iloc[j] > ma10[code].iloc[j]:
                    entries["T2"] = j
            yv = yoy[code].get(ym, np.nan) if code in yoy.columns else np.nan
            r = {"ep": t0, "code": code, "tv": deep.loc[code, "tv"], "dd": deep.loc[code, "dd"],
                 "yoy": yv, "k60_T0": c.iloc[exit_i] / e0 - 1}
            for tac in ("T1", "T2"):
                j = entries[tac]
                if j is not None and pd.notna(c.iloc[j]):
                    r[f"k60_{tac}"] = c.iloc[exit_i] / c.iloc[j] - 1
                    r[f"wait_{tac}"] = c.iloc[j] / e0 - 1
                    r[f"mae_{tac}"] = low[code].iloc[j + 1:exit_i].min() / c.iloc[j] - 1
            r["mae_T0"] = low[code].iloc[i + 1:exit_i].min() / e0 - 1
            rows.append(r)
    df = pd.DataFrame(rows)
    print(f"跌深組總樣本: {len(df)} (episodes {df['ep'].nunique()}個)")

    print("\n=== Q1 跌深組成交值分布 ===")
    print(f"  tv20中位 {df['tv'].median():.2f}億;  >=1億占{(df['tv']>=1).mean()*100:.0f}%  >=3億占{(df['tv']>=3).mean()*100:.0f}%")

    print("\n=== Q2 基本面分層(營收YoY,2018後episode) ===")
    sub = df[df["ep"] >= pd.Timestamp("2018-01-01")]
    for lab, m in [("YoY>0", sub["yoy"] > 0), ("YoY<=0", sub["yoy"] <= 0), ("無營收資料", sub["yoy"].isna())]:
        r = sub.loc[m, "k60_T0"]
        if len(r):
            print(f"  {lab:10s} n={len(r):4d}  k60中位{r.median()*100:+.2f}%  勝率{(r>0).mean()*100:.0f}%")

    print("\n=== Q3 成交值分層(全episode) ===")
    for lab, lo_, hi in [("0.5~1億", 0.5, 1), ("1~3億", 1, 3), (">=3億", 3, 1e9)]:
        r = df.loc[(df["tv"] >= lo_) & (df["tv"] < hi), "k60_T0"]
        print(f"  {lab:8s} n={len(r):4d}  k60中位{r.median()*100:+.2f}%  勝率{(r>0).mean()*100:.0f}%")

    print("\n=== Q4 進場戰術對照(同出場日t0+60收盤) ===")
    for tac, desc in [("T0", "t0收盤直接買"), ("T1", "等個股縮量止穩(15日內)"), ("T2", "等站回10日線(15日內)")]:
        k = df[f"k60_{tac}"].dropna() if f"k60_{tac}" in df else pd.Series(dtype=float)
        cov = len(k) / len(df) * 100
        mae = df[f"mae_{tac}"].dropna()
        wait = df[f"wait_{tac}"].dropna() if f"wait_{tac}" in df else pd.Series([0.0])
        print(f"  {tac} {desc:20s} 覆蓋{cov:.0f}%  報酬中位{k.median()*100:+.2f}% 勝{(k>0).mean()*100:.0f}%  "
              f"MAE中位{mae.median()*100:.2f}% p10 {mae.quantile(0.1)*100:.2f}%  等待成本{wait.median()*100:+.2f}%")

    print("\n=== 近例: 2026-04 episode 跌深組k60前10名 ===")
    recent = df[df["ep"] == df["ep"].max()].nlargest(10, "k60_T0") if len(df) else df
    for _, r in recent.iterrows():
        print(f"  {r['code']}  dd{r['dd']*100:.0f}%  tv{r['tv']:.1f}億  YoY{'' if pd.isna(r['yoy']) else f'{r['yoy']*100:+.0f}%'}  k60 {r['k60_T0']*100:+.1f}%")
    df.to_pickle("快取/tmp_deep_faller_entry.pkl")
    print("\n樣本已存 快取/tmp_deep_faller_entry.pkl")


if __name__ == "__main__":
    main()
