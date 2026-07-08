# -*- coding: utf-8 -*-
"""抓產業鏈/供應鏈成員的基本面(毛利率/營收YoY)存入DB fundamentals表
來源: yfinance .info (grossMargins / revenueGrowth)
風控: 逐檔0.4s節流、快取續傳(tmp_fund_cache.pkl)、連續失敗熔斷
用法: python fetch_fundamentals.py   (每季跑一次即可)
"""
import os
import pickle
import sqlite3
import sys
import time
from datetime import date

sys.path.insert(0, os.getcwd())

import yfinance as yf

import industry_chains
import supply_chain
from backfill_history import ticker_variants

CACHE = "tmp_fund_cache.pkl"
DB = "capital_flow.db"


def load_cache():
    if os.path.exists(CACHE):
        with open(CACHE, "rb") as f:
            return pickle.load(f)
    return {}


def save_cache(c):
    with open(CACHE, "wb") as f:
        pickle.dump(c, f)


def main():
    members = set()
    for chain, stage, code, country, role in industry_chains.CHAIN_LINKS:
        members.add((country, code))
    for sup_code, sup_country, cust_code, cust_country, product in supply_chain.LINKS:
        members.add((sup_country, sup_code))
    members = sorted(members)
    print(f"成員 {len(members)} 檔")

    cache = load_cache()
    consec_fail = 0
    for i, (country, code) in enumerate(members):
        key = f"{country}|{code}"
        if key in cache:
            continue
        result = None
        for v in ticker_variants(country, code):
            try:
                info = yf.Ticker(v).info
                gm = info.get("grossMargins")
                rg = info.get("revenueGrowth")
                if gm is not None or rg is not None:
                    result = {"gm": gm, "rg": rg}
                    consec_fail = 0
                    break
            except Exception:
                consec_fail += 1
                if consec_fail >= 5:
                    save_cache(cache)
                    print(f"[熔斷] 連續失敗，進度已存({i}/{len(members)})，稍後重跑續傳")
                    sys.exit(1)
                time.sleep(15)
            time.sleep(0.4)
        cache[key] = result   # None=查無資料，之後不重試
        if (i + 1) % 50 == 0:
            save_cache(cache)
            ok = sum(1 for v in cache.values() if v)
            print(f"進度 {i+1}/{len(members)}，有資料 {ok}")
        time.sleep(0.4)
    save_cache(cache)

    conn = sqlite3.connect(DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS fundamentals (
        country TEXT, code TEXT, gross_margin REAL, revenue_growth REAL,
        updated TEXT, PRIMARY KEY (country, code))""")
    rows = []
    today = str(date.today())
    for key, v in cache.items():
        if not v:
            continue
        country, code = key.split("|", 1)
        rows.append((country, code, v["gm"], v["rg"], today))
    conn.executemany("INSERT OR REPLACE INTO fundamentals (country,code,gross_margin,revenue_growth,updated) VALUES (?,?,?,?,?)", rows)
    conn.commit()
    conn.close()
    print(f"完成：{len(rows)} 檔寫入 fundamentals 表")


if __name__ == "__main__":
    main()
