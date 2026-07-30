# -*- coding: utf-8 -*-
"""⑫季節性副產品複驗(預註冊於⑫b):10-11月觸發率是否偏高+報酬是否站得住。
在修復後乾淨panel(tmp_theme_momentum_v2_panel.pkl)上重算:
(1) 各月份score=4觸發率(題材-月層級,非交易筆數,避免大題材灌水)
(2) 各月份score=4的TWII超額報酬(交易層+題材-月群數)
2月=農曆年工作天數污染MoM,單獨標註;3月n小勿過度解讀。
用法: python build_theme_momentum_seasonal.py
"""
import pandas as pd


def main():
    panel = pd.read_pickle("tmp_theme_momentum_v2_panel.pkl").copy()
    panel["m"] = panel.year_month.str[4:6]

    tm = panel.groupby(["industry", "year_month"]).agg(
        score=("score", "first"), m=("m", "first")).reset_index()
    print("--- (1) 各月份 score=4 觸發率(題材-月層級) ---")
    trig = tm.groupby("m").agg(n=("score", "size"), s4=("score", lambda s: (s == 4).sum()))
    trig["觸發率%"] = (trig.s4 / trig.n * 100).round(1)
    print(trig.to_string())

    print("\n--- (2) 各月份 score=4 交易 TWII超額報酬 ---")
    s4 = panel[panel.score == 4]
    for m in sorted(s4.m.unique()):
        g = s4[s4.m == m]
        ng = g.groupby(["industry", "year_month"]).ngroups
        note = " ⚠2月MoM受農曆年污染" if m == "02" else ""
        print(f"  {m}月: n={len(g):3d} 群={ng:2d} 中位{g.excess60.median():+7.2f}% "
              f"均{g.excess60.mean():+7.2f}% 勝率{(g.excess60 > 0).mean() * 100:3.0f}%{note}")

    q4 = s4[s4.m.isin(["10", "11"])]
    other = s4[~s4.m.isin(["10", "11", "02"])]
    print(f"\n10-11月合併: n={len(q4)} 群={q4.groupby(['industry','year_month']).ngroups} "
          f"中位{q4.excess60.median():+.2f}% 勝率{(q4.excess60 > 0).mean() * 100:.0f}%")
    print(f"其他月(排2月): n={len(other)} 中位{other.excess60.median():+.2f}% "
          f"勝率{(other.excess60 > 0).mean() * 100:.0f}%")
    t4 = tm[tm.m.isin(["10", "11"])]
    to = tm[~tm.m.isin(["10", "11", "02"])]
    print(f"觸發率: 10-11月 {(t4.score == 4).mean() * 100:.1f}% vs 其他月(排2月) "
          f"{(to.score == 4).mean() * 100:.1f}%")


if __name__ == "__main__":
    main()
