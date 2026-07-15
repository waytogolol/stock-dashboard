# -*- coding: utf-8 -*-
"""處置股先跌後漲事件研究(使用者2026-07-16提案:處置期間先跌後漲,找尾盤買1-2日出的機會)
機制假說: 處置=強制流動性凍結(分盤5/20分鐘+預收款券)→投機資金被迫離場=非資訊性賣壓
→與恐慌梯度同機制家族,預期: 處置初期跌(資金撤出),出關前後漲(資金回流)。

設計(預註冊):
- 事件: disposition表(2018-12~2026-07,4021筆),對到fm_daily_price有價格者
- 形狀段(原始,收盤對收盤): SEG_A 公布日收→處置首日收(公告衝擊) SEG_B 首日收→第3處置日收
  SEG_C 第3日收→處置末日收 SEG_D 處置末日收→出關+2開(出關行情)
- 可交易變體(淨額扣0.45%,尾盤收盤買):
  V1 處置首日尾盤買→T+2開出(公告已知,乾淨) V2 第5處置日尾盤買→T+2開出
  V3 處置末日尾盤買→出關第2日開盤出(出關行情,最像使用者目標)
  註: 公布日尾盤買需盤中預判處置(公告多在盤後),另列V0標註前視風險
- 分層: 第1次vs第2次+(5vs20分盤)、處置前20日動能(飆股被關vs跌股被關)、市場、逐年
用法: python build_disposition_event.py
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
    disp = pd.read_sql("SELECT * FROM disposition", conn)
    px = pd.read_sql("SELECT code, date, open, close FROM fm_daily_price ORDER BY code, date", conn)
    conn.close()
    px["date"] = pd.to_datetime(px.date)
    stocks = {c: g.sort_values("date").reset_index(drop=True) for c, g in px.groupby("code")}
    for c in ("announce_date", "start_date", "end_date"):
        disp[c] = pd.to_datetime(disp[c], errors="coerce")
    disp = disp.dropna(subset=["start_date", "end_date"])

    rows = []
    for _, e in disp.iterrows():
        g = stocks.get(e.code)
        if g is None:
            continue
        dts = g.date
        s_arr = np.searchsorted(dts.values, np.datetime64(e.start_date))
        e_arr = np.searchsorted(dts.values, np.datetime64(e.end_date), side="right") - 1
        if s_arr >= len(g) or e_arr < 0 or e_arr <= s_arr or e_arr - s_arr > 25:
            continue
        a_arr = s_arr - 1  # 公布日≈處置前一交易日
        c_, o_ = g.close.values, g.open.values
        n = len(g)

        def px_ok(i):
            return 0 <= i < n and c_[i] > 0

        def seg(i, j, open_exit=False):
            if not (px_ok(i) and 0 <= j < n):
                return np.nan
            p1 = o_[j] if open_exit else c_[j]
            if p1 <= 0:
                return np.nan
            return (p1 / c_[i] - 1) * 100

        pre20 = seg(a_arr - 20, a_arr) if a_arr - 20 >= 0 else np.nan
        r = {"code": e.code, "market": e.market, "cum": e.cum_count or 1,
             "y": e.start_date.year, "pre20": pre20,
             "segA": seg(a_arr, s_arr), "segB": seg(s_arr, min(s_arr + 2, e_arr)),
             "segC": seg(min(s_arr + 2, e_arr), e_arr),
             "segD": seg(e_arr, e_arr + 2, open_exit=True),
             "v0": seg(a_arr, a_arr + 2, open_exit=True) - COST if px_ok(a_arr) else np.nan,
             "v1": seg(s_arr, s_arr + 2, open_exit=True) - COST,
             "v2": seg(s_arr + 4, s_arr + 6, open_exit=True) - COST if s_arr + 4 <= e_arr else np.nan,
             "v3": seg(e_arr, e_arr + 2, open_exit=True) - COST}
        rows.append(r)
    df = pd.DataFrame(rows)
    print(f"處置事件對到價格: {len(df):,}/{len(disp):,}筆 ({df.code.nunique()}檔), "
          f"{df.y.min()}~{df.y.max()}")

    print("\n== 形狀(原始%,先跌後漲?) ==")
    stat(df.segA, "SEG_A 公布→處置首日(公告衝擊)")
    stat(df.segB, "SEG_B 首日→第3處置日        ")
    stat(df.segC, "SEG_C 第3日→處置末日        ")
    stat(df.segD, "SEG_D 末日→出關+2開(出關行情)")

    print("\n== 可交易變體(淨額) ==")
    stat(df.v0, "V0 公布日尾盤買→+2開(需盤中預判,前視風險)")
    stat(df.v1, "V1 處置首日尾盤買→+2開             ")
    stat(df.v2, "V2 第5處置日尾盤買→+2開            ")
    stat(df.v3, "V3 處置末日尾盤買→出關+2開(出關行情) ")

    print("\n== V3出關行情分層 ==")
    stat(df[df.cum == 1].v3, "第1次處置(5分盤)")
    stat(df[df.cum >= 2].v3, "第2次+(20分盤)  ")
    stat(df[df.pre20 > 10].v3, "進關前20日漲>10%(飆股被關)")
    stat(df[df.pre20 <= 0].v3, "進關前20日跌(跌股被關)   ")
    stat(df[df.market == "上市"].v3, "上市")
    stat(df[df.market == "上櫃"].v3, "上櫃")

    print("\n== V3逐年 ==")
    for y, g in df.groupby("y"):
        stat(g.v3, str(y))

    df.to_pickle("tmp_disposition_panel.pkl")
    print("\n面板存 tmp_disposition_panel.pkl")


if __name__ == "__main__":
    main()
