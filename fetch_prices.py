# -*- coding: utf-8 -*-
"""抓全宇宙每週收盤價(對齊rankings快照日) -> DB weekly_close 表
供公司歷史趨勢的股價走勢圖使用。含快取續傳+風控(沿用backfill機制)。
用法: python fetch_prices.py   (每週refresh後跑可補最新一週)
"""
import os
import pickle
import sqlite3
import sys
import time
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf

sys.path.insert(0, os.getcwd())
from backfill_history import CHUNK, RateGuard, UNIVERSE_FILES, ticker_variants

DB = "capital_flow.db"
CACHE = "tmp_price_cache.pkl"


def load_cache():
    if os.path.exists(CACHE):
        with open(CACHE, "rb") as f:
            return pickle.load(f)
    return {}


def save_cache(c):
    with open(CACHE, "wb") as f:
        pickle.dump(c, f)


def download_close(tickers, start, end, cache, guard):
    todo = [t for t in tickers if t not in cache]
    for i in range(0, len(todo), CHUNK):
        chunk = todo[i:i + CHUNK]
        df = None
        try:
            df = yf.download(chunk, start=start, end=end, interval="1d",
                             group_by="ticker", auto_adjust=False, threads=True, progress=False)
        except Exception as e:
            print(f"批次例外: {e}")
        got = 0
        if df is not None and not df.empty:
            for t in chunk:
                try:
                    sub = df[t] if len(chunk) > 1 else df
                    s = sub["Close"].dropna()
                    cache[t] = s if len(s) else None
                    if len(s):
                        got += 1
                except Exception:
                    cache[t] = None
        save_cache(cache)
        print(f"進度 {min(i+CHUNK, len(todo))}/{len(todo)}，本批有效 {got}")
        if df is None or df.empty or got == 0:
            if guard.fail():
                print("[熔斷] 進度已存，稍後重跑續傳")
                sys.exit(1)
        else:
            guard.ok()
    return cache


def main():
    conn = sqlite3.connect(DB)
    dates = [r[0] for r in conn.execute("SELECT DISTINCT snapshot_date FROM rankings ORDER BY snapshot_date")]
    plan = []
    for country, fname in UNIVERSE_FILES.items():
        uni = pd.read_csv(fname, dtype=str)
        for _, r in uni.iterrows():
            variants = ticker_variants(country, r["code"])
            if variants:
                plan.append((country, r["code"], variants))
    start = str(datetime.strptime(dates[0], "%Y-%m-%d").date() - timedelta(days=10))
    end = str(datetime.strptime(dates[-1], "%Y-%m-%d").date() + timedelta(days=1))
    print(f"宇宙 {len(plan)} 檔，快照 {len(dates)} 週 ({dates[0]} ~ {dates[-1]})")

    cache = load_cache()
    guard = RateGuard()
    primary = sorted(set(p[2][0] for p in plan))
    cache = download_close(primary, start, end, cache, guard)
    fallback = sorted(set(p[2][1] for p in plan if len(p[2]) > 1 and cache.get(p[2][0]) is None))
    if fallback:
        print(f"備用代碼 {len(fallback)} 檔...")
        cache = download_close(fallback, start, end, cache, guard)

    rows = []
    snap_dt = [datetime.strptime(d, "%Y-%m-%d").date() for d in dates]
    for country, code, variants in plan:
        s = next((cache[v] for v in variants if cache.get(v) is not None), None)
        if s is None:
            continue
        sd = s.copy()
        sd.index = [ts.date() for ts in sd.index]
        for d_str, d in zip(dates, snap_dt):
            win = [v for dt, v in sd.items() if d - timedelta(days=6) <= dt <= d]
            if win:
                rows.append((country, code, d_str, round(float(win[-1]), 2)))
    conn.execute("""CREATE TABLE IF NOT EXISTS weekly_close (
        country TEXT, code TEXT, snapshot_date TEXT, close REAL,
        PRIMARY KEY (country, code, snapshot_date))""")
    conn.executemany("INSERT OR REPLACE INTO weekly_close VALUES (?,?,?,?)", rows)
    conn.commit()
    n = conn.execute("SELECT COUNT(*), COUNT(DISTINCT country||code) FROM weekly_close").fetchone()
    conn.close()
    print(f"weekly_close: {n[0]} 筆 / {n[1]} 檔")


if __name__ == "__main__":
    main()
