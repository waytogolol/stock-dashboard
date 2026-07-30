# -*- coding: utf-8 -*-
"""新假說(使用者提案 2026-07-13 深夜)：產業營收趨勢向上 -> 月初買進該產業成員 -> 該股自己月營收公布時看反應 ->
反應好(>=0)續抱到月底、反應弱(<0)當下出場。

設計要點(吸取同業龍頭那次的教訓，逐一檢查)：
1. 趨勢訊號用「前3個月(不含當月)」的產業YoY中位數平均(shift(1).rolling(3))，
   不能用當月YoY——那要等當月全部公司報完才知道，但我們是月初就要決定買不買，避免look-ahead。
2. 進出場價格全部鎖定同一檔股票自己的收盤價序列，不會有跟同業龍頭那次一樣『兩支股票價格互除』的錯。
3. 取價一律檢查跟目標日期的間隔，超過5天視為資料缺口，不用陳舊價格湊數(沿用build_revenue_diffusion_panel.py的作法)。
4. 三組對照：A=條件式(反應好續抱/弱出場)、B=無條件持有到月底(不管反應)、C=不篩趨勢(月初無條件買，同樣的條件式出場規則)。
   A vs B 可看『反應後決定去留』這件事本身有沒有加分；A vs C 可看『先篩趨勢』這件事本身有沒有加分。

用法: python build_industry_trend_ride.py
"""
import pickle
import sqlite3

import pandas as pd

MAX_GAP_DAYS = 5


def get_close(cache, code, date, mode="onOrBefore"):
    df = cache.get(code)
    if df is None:
        return None
    c = df["Close"]
    if hasattr(c, "columns"):
        c = c.iloc[:, 0]
    target = pd.Timestamp(date)
    if mode == "onOrBefore":
        idx = c.index[c.index <= target]
    elif mode == "onOrAfter":
        idx = c.index[c.index >= target]
    else:
        raise ValueError(mode)
    if len(idx) == 0:
        return None
    found = idx[0] if mode == "onOrAfter" else idx[-1]
    if abs((target - found).days) > MAX_GAP_DAYS:
        return None
    return float(c.loc[found]), found


def main():
    conn = sqlite3.connect("capital_flow.db")
    news = pd.read_sql("SELECT * FROM tw_revenue_news", conn, dtype={"code": str})
    imap = pd.read_csv("tw_industry_map.csv", dtype=str, encoding="utf-8")
    m = news.merge(imap[["code", "industry"]], on="code", how="inner")
    m["yoy_pct"] = m.yoy_pct.astype(float)
    m["announce_date"] = pd.to_datetime(m.announce_dt).dt.date

    # 產業月YoY中位數 + 前3個月趨勢訊號(look-ahead-safe)
    ind = m.groupby(["industry", "year_month"]).yoy_pct.median().reset_index()
    ind = ind.sort_values(["industry", "year_month"])
    ind["trend_yoy"] = ind.groupby("industry").yoy_pct.transform(
        lambda s: s.shift(1).rolling(3, min_periods=2).mean())
    ind["trend_up"] = ind.trend_yoy > 0

    m = m.merge(ind[["industry", "year_month", "trend_up", "trend_yoy"]], on=["industry", "year_month"], how="left")
    m = m.dropna(subset=["trend_up"])  # 前3個月資料不足的組跳過
    print(f"有效樣本(可判斷趨勢): {len(m)} 筆；trend_up=True: {m.trend_up.sum()} 筆")

    with open("tmp_revenue_price_cache.pkl", "rb") as f:
        cache = pickle.load(f)

    m["month_start"] = pd.to_datetime(m.year_month, format="%Y%m")
    m["month_end"] = m.month_start + pd.offsets.MonthEnd(0)

    def calc_row(row):
        entry = get_close(cache, row.code, row.month_start, "onOrAfter")
        if entry is None:
            return pd.Series([None] * 4)
        entry_px, entry_date = entry
        react = get_close(cache, row.code, row.announce_date, "onOrBefore")
        if react is None:
            return pd.Series([None] * 4)
        react_px, _ = react
        mend = get_close(cache, row.code, row.month_end, "onOrBefore")
        if mend is None:
            return pd.Series([None] * 4)
        mend_px, mend_date = mend
        if mend_date <= entry_date:
            return pd.Series([None] * 4)
        reaction_ret = (react_px / entry_px - 1) * 100
        hold_to_end_ret = (mend_px / entry_px - 1) * 100
        conditional_ret = hold_to_end_ret if reaction_ret >= 0 else reaction_ret
        return pd.Series([reaction_ret, hold_to_end_ret, conditional_ret, True])

    m[["reaction_ret", "hold_to_end_ret", "conditional_ret", "ok"]] = m.apply(calc_row, axis=1)
    panel = m.dropna(subset=["ok"]).copy()
    print(f"可計算報酬的筆數: {len(panel)}")
    panel.to_pickle("tmp_industry_trend_ride_panel.pkl")
    print("已存 -> tmp_industry_trend_ride_panel.pkl")


if __name__ == "__main__":
    main()
