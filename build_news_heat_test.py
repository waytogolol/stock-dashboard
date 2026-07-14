# -*- coding: utf-8 -*-
"""⑫b判決：「trailing新聞覆蓋=熱度因子」假說(使用者2026-07-14提出,預註冊設計)。

背景:舊版panel(有當月新聞條件=look-ahead)報酬明顯高於修復後無條件全宇宙版
(mom_streak3中位+11.67% vs score=4中位+7.41%),差額可能是「被媒體關注」溢價。

look-ahead-safe設計:旗標=進場日(每月15號實際交易日)之前的trailing窗口內,
該股營收曾被MoneyDJ報導(tw_revenue_news.announce_dt < entry_day,嚴格小於)。
窗口兩版:35天(~前1個月)/95天(~前3個月)。
注意:tw_revenue_news最早2021-12-01,95天版在2022年3月前的進場日窗口部分缺覆蓋。

比較(TWII超額報酬excess60為主判準,逐年拆開):
  ① score=4 × 有trailing新聞  vs  ② score=4 × 無trailing新聞
  ③ trailing新聞單獨(不看score) vs 無新聞
判決:①>>② → 熱度因子成立可疊加;③單獨有效 → 獨立因子。
用法: python build_news_heat_test.py
"""
import sqlite3

import numpy as np
import pandas as pd

WINDOWS = {"1M(35d)": 35, "3M(95d)": 95}


def stats(s):
    if len(s) == 0:
        return "n=0"
    return f"n={len(s)} 中位{s.median():+.2f}% 均{s.mean():+.2f}% 勝率{(s > 0).mean() * 100:.0f}%"


def main():
    panel = pd.read_pickle("tmp_theme_momentum_v2_panel.pkl").copy()
    panel["entry_day"] = pd.to_datetime(panel.entry_day)
    panel["y"] = panel.year_month.str[:4]

    conn = sqlite3.connect("capital_flow.db")
    news = pd.read_sql("SELECT code, announce_dt FROM tw_revenue_news", conn, dtype={"code": str})
    news["dt"] = pd.to_datetime(news.announce_dt.str.replace(r"\s+", " ", regex=True))
    by_code = {c: np.sort(g.dt.values) for c, g in news.groupby("code")}
    print(f"panel {len(panel)}筆 / 新聞 {len(news)}筆 {news.dt.min().date()}~{news.dt.max().date()} "
          f"/ panel∩新聞代碼 {len(set(panel.code) & set(by_code))}/{panel.code.nunique()}檔")

    for wname, days in WINDOWS.items():
        lo = panel.entry_day - pd.Timedelta(days=days)
        flag = np.zeros(len(panel), dtype=bool)
        for i, (code, l, e) in enumerate(zip(panel.code, lo, panel.entry_day)):
            arr = by_code.get(code)
            if arr is not None:
                # 嚴格 < entry_day,窗口 [entry_day-days, entry_day)
                j = np.searchsorted(arr, np.datetime64(e))
                flag[i] = j > 0 and arr[j - 1] >= np.datetime64(l)
        panel[f"news_{wname}"] = flag

    for wname in WINDOWS:
        col = f"news_{wname}"
        print(f"\n{'=' * 70}\n===== 窗口 {wname} | 旗標覆蓋率 全體{panel[col].mean() * 100:.0f}% =====")
        cov = panel.groupby("y")[col].mean() * 100
        print("逐年覆蓋率: " + "  ".join(f"{y}:{v:.0f}%" for y, v in cov.items()))

        for ret_col in ["excess60", "ret60"]:
            label = "TWII超額" if ret_col == "excess60" else "原始"
            s4 = panel[panel.score == 4]
            print(f"\n--- [{label}] ①② score=4 內比較 ---")
            print(f"  ①score4×有新聞  {stats(s4[s4[col]][ret_col])}")
            print(f"  ②score4×無新聞  {stats(s4[~s4[col]][ret_col])}")
            print(f"--- [{label}] ③ 新聞單獨(全score) ---")
            print(f"  ③有新聞         {stats(panel[panel[col]][ret_col])}")
            print(f"   無新聞         {stats(panel[~panel[col]][ret_col])}")
            print(f"--- [{label}] ③b 新聞單獨,排除score=4(檢查是否只是score=4的影子) ---")
            ns4 = panel[panel.score < 4]
            print(f"  有新聞×score<4  {stats(ns4[ns4[col]][ret_col])}")
            print(f"  無新聞×score<4  {stats(ns4[~ns4[col]][ret_col])}")

        print(f"\n--- 逐年(TWII超額, score=4內 ①vs②) ---")
        s4 = panel[panel.score == 4]
        for y in sorted(panel.y.unique()):
            a = s4[(s4.y == y) & s4[f"news_{wname}"]]["excess60"]
            b = s4[(s4.y == y) & ~s4[f"news_{wname}"]]["excess60"]
            print(f"  {y}: ①有 {stats(a):<40} ②無 {stats(b)}")
        print(f"--- 逐年(TWII超額, 全score ③新聞單獨) ---")
        for y in sorted(panel.y.unique()):
            a = panel[(panel.y == y) & panel[f"news_{wname}"]]["excess60"]
            b = panel[(panel.y == y) & ~panel[f"news_{wname}"]]["excess60"]
            print(f"  {y}: 有 {stats(a):<41} 無 {stats(b)}")

        # 獨立樣本感:題材-月群數
        g1 = panel[panel[f"news_{wname}"] & (panel.score == 4)].groupby(["industry", "year_month"]).ngroups
        g0 = panel[~panel[f"news_{wname}"] & (panel.score == 4)].groupby(["industry", "year_month"]).ngroups
        print(f"score=4 題材-月群數: ①有新聞 {g1} / ②無新聞 {g0}")

    panel.to_pickle("tmp_news_heat_panel.pkl")
    print("\n已存 tmp_news_heat_panel.pkl (panel+旗標)")


if __name__ == "__main__":
    main()
