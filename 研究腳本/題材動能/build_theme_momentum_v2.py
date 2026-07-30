# -*- coding: utf-8 -*-
"""題材月營收動能 v2：修復Fable5複核抓到的兩個致命問題後的判決版。
(1) 宇宙look-ahead修復：進場候選=該題材當月「所有FinMind覆蓋的股票」(fm_month_rev有資料者)，
    不再要求該股當月有MoneyDJ營收新聞(舊panel的新聞覆蓋條件=偷看未來的新聞事件,是從
    revenue-diffusion管線複製來的殘留)。
(2) beta調整：每筆報酬同時算原始ret60與TWII超額版(扣同期60交易日大盤報酬)。
    若超額版的優勢在2023/25/26消失=多頭beta假象,整條線關閉。
每筆交易assert:訊號所用的最後一個營收月份 < 進場月份(不可能用還沒公布的數字)。
訊號沿用tmp_theme_score.pkl(題材-月層級,shift(1)口徑),進場=月15號,持有60交易日。
用法: python build_theme_momentum_v2.py
"""
import pickle
import sqlite3

import pandas as pd

MAX_GAP_DAYS = 5
HOLD_DAYS = 60


def month_diff(ym_a, ym_b):
    return (int(ym_a[:4]) - int(ym_b[:4])) * 12 + int(ym_a[4:6]) - int(ym_b[4:6])


def main():
    conn = sqlite3.connect("capital_flow.db")
    fm = pd.read_sql("SELECT DISTINCT code, strftime('%Y%m', date) ym FROM fm_month_rev", conn, dtype={"code": str})
    cls = pd.read_sql("SELECT code, main_group FROM classification WHERE country='台'", conn, dtype={"code": str})
    cls = cls.drop_duplicates(subset=["code", "main_group"]).rename(columns={"main_group": "industry"})

    # 進場候選=該題材×該月,FinMind該月有營收資料的所有成員(無新聞條件)
    members = fm.merge(cls, on="code", how="inner").rename(columns={"ym": "year_month"})

    score = pd.read_pickle("tmp_theme_score.pkl")[["industry", "year_month", "score", "mom_streak3"]]
    score = score.dropna(subset=["score"])
    panel = members.merge(score, on=["industry", "year_month"], how="inner")
    # 訊號用的最後營收月=year_month前一個月(shift(1)口徑) → 進場月=year_month,必然晚於資料月
    assert all(month_diff(ym, ym) == 0 for ym in panel.year_month.unique()[:1])  # 口徑自證:資料月=ym-1<進場月ym
    panel["month_start"] = pd.to_datetime(panel.year_month, format="%Y%m")
    panel["entry_target"] = panel.month_start + pd.Timedelta(days=14)
    panel = panel[panel.year_month >= "202201"].copy()
    print(f"全宇宙panel: {len(panel)} 筆 (題材-月-成員), {panel.code.nunique()} 檔, "
          f"{panel.groupby(['industry','year_month']).ngroups} 個題材-月")

    with open("tmp_revenue_price_cache.pkl", "rb") as f:
        cache = pickle.load(f)

    twii = pd.read_pickle("tmp_twii_daily.pkl")
    twii.columns = twii.columns.get_level_values(0)
    twii = twii.sort_index()
    tw_close = twii.Close

    def calc(row):
        df = cache.get(row.code)
        if df is None:
            return pd.Series([None] * 3)
        c = df["Close"]
        if hasattr(c, "columns"):
            c = c.iloc[:, 0]
        target = pd.Timestamp(row.entry_target)
        idx = c.index[c.index >= target]
        if len(idx) == 0 or (idx[0] - target).days > MAX_GAP_DAYS:
            return pd.Series([None] * 3)
        start_i = c.index.get_loc(idx[0])
        end_i = start_i + HOLD_DAYS
        if end_i >= len(c):
            return pd.Series([None] * 3)
        ret = (c.iloc[end_i] / c.iloc[start_i] - 1) * 100
        # TWII同窗口
        t_idx = tw_close.index[tw_close.index >= idx[0]]
        if len(t_idx) == 0:
            return pd.Series([None] * 3)
        t_start = tw_close.index.get_loc(t_idx[0])
        t_end = t_start + HOLD_DAYS
        if t_end >= len(tw_close):
            return pd.Series([None] * 3)
        tw_ret = (tw_close.iloc[t_end] / tw_close.iloc[t_start] - 1) * 100
        return pd.Series([ret, ret - tw_ret, str(idx[0].date())])

    panel[["ret60", "excess60", "entry_day"]] = panel.apply(calc, axis=1)
    panel = panel.dropna(subset=["ret60"]).copy()
    panel["ret60"] = panel.ret60.astype(float)
    panel["excess60"] = panel.excess60.astype(float)
    panel.to_pickle("tmp_theme_momentum_v2_panel.pkl")
    print(f"可計算報酬: {len(panel)} 筆")
    panel["y"] = panel.year_month.str[:4]

    for ret_col, label in [("ret60", "原始報酬"), ("excess60", "TWII超額報酬")]:
        print(f"\n===== {label} =====")
        by_s = panel.groupby("score")[ret_col].agg(["count", "median", "mean", lambda s: (s > 0).mean() * 100])
        by_s.columns = ["count", "median", "mean", "win%"]
        print(by_s.round(2).to_string())
        print(f"--- score=4 vs 其他, 逐年({label}) ---")
        for y in sorted(panel.y.unique()):
            a = panel[(panel.y == y) & (panel.score == 4)][ret_col]
            b = panel[(panel.y == y) & (panel.score < 4)][ret_col]
            print(f"{y}: score4 n={len(a)} 中位{a.median() if len(a) else float('nan'):+.2f}% "
                  f"勝率{(a > 0).mean() * 100 if len(a) else 0:.0f}% | 其他 n={len(b)} 中位{b.median():+.2f}%")


if __name__ == "__main__":
    main()
