# -*- coding: utf-8 -*-
"""同業龍頭先報營收→同業提前卡位：panel建構(正式存檔版,取代先前未存檔的tmp_腳本)。

方法：
1. tw_revenue_news(MoneyDJ公告時間戳) × tw_industry_map.csv(官方產業分類)合併
2. size proxy＝該公司「截至上個月為止」的歷史平均營收(擴張窗,只用該月之前的資料)，
   不能直接用當月營收排百分位——那需要同產業當月「所有」公司都已公布才能算出排名，
   等於用了公布當下還不存在的未來資訊(look-ahead bias)。size若用同月營收，
   代表「誰是龍頭」這件事要等月底全部公布完才確定，但leader照定義是「最先公布的那個」，
   兩者互相矛盾。改用截至上月的歷史均值＝市場當下就已經知道的公司規模，無此問題。
   首次出現(無歷史資料)的公司退回用該筆自己的營收值(冷啟動,無法避免)。
3. 每(產業,年月)按size proxy排前30%＝該產業內「龍頭候選」；候選中最先公布者＝leader；
   leader_react=公布當日股價反應(T-1收盤→T收盤)
4. 同產業其他公司(不限是否為龍頭候選)在leader公布之後才公布的＝lag_code；
   lag_pre_report_ret=leader公布日收盤→lag_code自己公布日收盤的報酬(等待期間持有)
5. 股價缺的公司自動用yfinance補抓(增量,寫回tmp_revenue_price_cache.pkl)
6. 取價一律檢查跟目標日期的間隔，超過5天視為資料缺口(可能下市/停牌)，不用陳舊價格湊數

輸出：tmp_revenue_prominent_panel_dated.pkl(取代舊版,欄位同名以兼容既有report腳本)
用法：python build_revenue_diffusion_panel.py
"""
import pickle
import sqlite3
import time

import pandas as pd
import yfinance as yf

PROMINENT_PCTL = 0.70  # 當月營收排前30% = percentile >= 0.70


def load_price_cache():
    try:
        with open("tmp_revenue_price_cache.pkl", "rb") as f:
            return pickle.load(f)
    except FileNotFoundError:
        return {}


def fetch_missing_prices(codes, cache):
    missing = [c for c in codes if c not in cache]
    print(f"股價快取現有 {len(cache)} 檔，缺 {len(missing)} 檔，開始補抓...")
    for i, code in enumerate(missing):
        for suffix in [".TW", ".TWO"]:
            try:
                df = yf.download(code + suffix, start="2022-01-01", end="2026-07-14",
                                  auto_adjust=True, progress=False)
                if len(df) > 20:
                    cache[code] = df
                    break
            except Exception:
                continue
        if (i + 1) % 50 == 0:
            print(f"  已補抓 {i+1}/{len(missing)}，寫入快取...")
            with open("tmp_revenue_price_cache.pkl", "wb") as f:
                pickle.dump(cache, f)
        time.sleep(0.15)
    with open("tmp_revenue_price_cache.pkl", "wb") as f:
        pickle.dump(cache, f)
    print(f"補抓完成，快取現有 {len(cache)} 檔")
    return cache


MAX_GAP_DAYS = 5  # 找到的價格跟目標日期差距上限,超過視為資料缺口(停牌/下市/快取沒抓到),不採用


def get_close(cache, code, date, strict_before=False):
    """strict_before=False: 找<=date最近一筆; True: 找<date最近一筆。超過MAX_GAP_DAYS視為缺資料。"""
    df = cache.get(code)
    if df is None:
        return None
    c = df["Close"]
    if hasattr(c, "columns"):
        c = c.iloc[:, 0]
    target = pd.Timestamp(date)
    idx = c.index[c.index < target] if strict_before else c.index[c.index <= target]
    if len(idx) == 0:
        return None
    found = idx[-1]
    if (target - found).days > MAX_GAP_DAYS:
        return None
    return float(c.loc[found])


def main():
    conn = sqlite3.connect("capital_flow.db")
    news = pd.read_sql("SELECT * FROM tw_revenue_news", conn, dtype={"code": str})
    imap = pd.read_csv("tw_industry_map.csv", dtype=str, encoding="utf-8")
    m = news.merge(imap[["code", "industry"]], on="code", how="inner")
    m["revenue"] = m.revenue.astype(float)
    m["announce_date"] = pd.to_datetime(m.announce_dt).dt.date
    m = m.sort_values(["industry", "year_month", "announce_date"])
    print(f"合併後 {len(m)} 筆，{m.industry.nunique()} 個產業，{m.code.nunique()} 檔公司")

    # 1) size proxy = 該公司「截至上個月」的擴張窗歷史平均營收(避免look-ahead,見檔頭說明)
    m = m.sort_values(["code", "year_month"]).reset_index(drop=True)
    m["cum_avg_prior"] = (m.groupby("code").revenue.cumsum() - m.revenue) / \
                          m.groupby("code").cumcount().where(m.groupby("code").cumcount() > 0, 1)
    m["size_proxy"] = m["cum_avg_prior"].where(m.groupby("code").cumcount() > 0, m["revenue"])

    # 2) 每(產業,年月)按size_proxy排前30% = prominent候選
    m["rank_pctl"] = m.groupby(["industry", "year_month"]).size_proxy.rank(pct=True)
    m["prominent"] = m.rank_pctl >= PROMINENT_PCTL

    # 2) 每(產業,年月)的leader = prominent中最早公布者
    prom = m[m.prominent].copy()
    leader_idx = prom.groupby(["industry", "year_month"]).announce_date.idxmin()
    leaders = prom.loc[leader_idx, ["industry", "year_month", "code", "announce_date"]].rename(
        columns={"code": "leader_code", "announce_date": "leader_date"})
    print(f"共 {len(leaders)} 個(產業,年月)有明確leader")

    # 3) 股價快取：需要leader本身 + 所有lag_code候選
    all_codes = set(leaders.leader_code) | set(m.code)
    cache = load_price_cache()
    cache = fetch_missing_prices(sorted(all_codes), cache)

    # 4) leader_react
    leaders["leader_react"] = leaders.apply(
        lambda r: (lambda c1, c0: (c1 / c0 - 1) * 100 if c1 and c0 else None)(
            get_close(cache, r.leader_code, r.leader_date),
            get_close(cache, r.leader_code, r.leader_date, strict_before=True)),
        axis=1)
    leaders = leaders.dropna(subset=["leader_react"])
    print(f"有股價可算leader_react的組數: {len(leaders)}")

    # 5) 配對lag_code：同(產業,年月)其他公司，公布日晚於leader
    merged = m.merge(leaders, on=["industry", "year_month"], how="inner")
    lag = merged[(merged.code != merged.leader_code) & (merged.announce_date > merged.leader_date)].copy()
    lag["wait_days"] = (pd.to_datetime(lag.announce_date) - pd.to_datetime(lag.leader_date)).dt.days
    lag = lag.rename(columns={"code": "lag_code"})

    def calc_ret(row):
        # 買的是lag_code本身,進出場價格都要是同一檔股票——c0絕對不能用leader_code的價格
        c0 = get_close(cache, row.lag_code, row.leader_date)
        c1 = get_close(cache, row.lag_code, row.announce_date)
        if not c0 or not c1:
            return None
        return (c1 / c0 - 1) * 100

    lag["lag_pre_report_ret"] = lag.apply(calc_ret, axis=1)
    panel = lag.dropna(subset=["lag_pre_report_ret"])[
        ["industry", "year_month", "leader_code", "leader_react", "lag_code", "wait_days", "lag_pre_report_ret"]].copy()
    panel["entry_date"] = lag.loc[panel.index, "leader_date"].astype(str)
    print(f"最終panel筆數: {len(panel)}")

    panel.to_pickle("tmp_revenue_prominent_panel_dated.pkl")
    print("已存 -> tmp_revenue_prominent_panel_dated.pkl")


if __name__ == "__main__":
    main()
