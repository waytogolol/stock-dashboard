# -*- coding: utf-8 -*-
"""FinMind 台股基本面歷史庫 -> capital_flow.db (fm_income / fm_cashflow / fm_month_rev)
範圍: 研究相關台股(歷次觸發成員+產業鏈+供應鏈台股) 2019-01起
節流: 每請求間隔6.1s(免費額度600/hr)；斷點續傳 tmp_finmind_cache.pkl；402退避重試
用法: python fetch_finmind.py   (中斷重跑會續傳)
"""
import os
import pickle
import sqlite3
import time
from datetime import date

import requests

DB = "capital_flow.db"
CACHE = "tmp_finmind_cache.pkl"
TOKEN = open("finmind_token.txt").read().strip()
START = "2019-01-01"
SLEEP = 6.1

DATASETS = {
    "TaiwanStockFinancialStatements": "fm_income",
    "TaiwanStockCashFlowsStatement": "fm_cashflow",
    "TaiwanStockMonthRevenue": "fm_month_rev",
}


def universe():
    u = set()
    if os.path.exists("tmp_bear_prices.pkl"):
        with open("tmp_bear_prices.pkl", "rb") as f:
            u |= set(k for k in pickle.load(f) if isinstance(k, str) and k[:1].isdigit())
    import industry_chains as ic
    import supply_chain as sc
    u |= set(code for _c, _s, code, country, _r in ic.CHAIN_LINKS if country == "台")
    u |= set(s for s, sc_, _c, _cc, _p in sc.LINKS if sc_ == "台")
    return sorted(u)


def fm_get(dataset, code):
    for attempt in range(4):
        try:
            r = requests.get("https://api.finmindtrade.com/api/v4/data",
                             params={"dataset": dataset, "data_id": code,
                                     "start_date": START, "end_date": str(date.today()),
                                     "token": TOKEN}, timeout=40)
            if r.status_code == 402:
                print(f"  額度限制,休息70s (attempt{attempt})")
                time.sleep(70)
                continue
            j = r.json()
            if j.get("msg") != "success":
                print(f"  {dataset}/{code}: {j.get('msg')}")
                time.sleep(20)
                continue
            return j.get("data") or []
        except Exception as e:
            print(f"  {dataset}/{code}: {type(e).__name__}, 重試")
            time.sleep(15)
    return None   # 連續失敗，下次執行重試


def main():
    codes = universe()
    print(f"宇宙 {len(codes)} 檔 × {len(DATASETS)} 資料集")
    cache = {}
    if os.path.exists(CACHE):
        with open(CACHE, "rb") as f:
            cache = pickle.load(f)
    conn = sqlite3.connect(DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS fm_income (
        code TEXT, date TEXT, type TEXT, value REAL, PRIMARY KEY (code, date, type))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS fm_cashflow (
        code TEXT, date TEXT, type TEXT, value REAL, PRIMARY KEY (code, date, type))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS fm_month_rev (
        code TEXT, date TEXT, revenue REAL, PRIMARY KEY (code, date))""")
    done = fail = 0
    total = len(codes) * len(DATASETS)
    for ds, table in DATASETS.items():
        for code in codes:
            key = (ds, code)
            if key in cache:
                continue
            data = fm_get(ds, code)
            if data is None:
                fail += 1
                time.sleep(SLEEP)
                continue
            if ds == "TaiwanStockMonthRevenue":
                rows = [(code, d["date"], d.get("revenue")) for d in data]
                conn.executemany("INSERT OR REPLACE INTO fm_month_rev VALUES (?,?,?)", rows)
            else:
                rows = [(code, d["date"], d["type"], d.get("value")) for d in data]
                conn.executemany(f"INSERT OR REPLACE INTO {table} VALUES (?,?,?,?)", rows)
            conn.commit()
            cache[key] = len(rows)
            done += 1
            if done % 25 == 0:
                with open(CACHE, "wb") as f:
                    pickle.dump(cache, f)
                print(f"進度 {len(cache)}/{total} (本次成功{done}, 待重試{fail})")
            time.sleep(SLEEP)
    with open(CACHE, "wb") as f:
        pickle.dump(cache, f)
    for t in DATASETS.values():
        n = conn.execute(f"SELECT COUNT(*), COUNT(DISTINCT code) FROM {t}").fetchone()
        print(f"{t}: {n[0]} 筆 / {n[1]} 檔")
    conn.close()
    print(f"完成！成功{done} 待重試{fail}")


if __name__ == "__main__":
    main()
