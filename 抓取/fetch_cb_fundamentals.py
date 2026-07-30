# -*- coding: utf-8 -*-
"""CB發行公司基本面補抓(使用者2026-07-16批准) -> fm_month_rev / fm_income 增量
宇宙: cb_info全部發行公司(~861家,含已在庫213檔=順便補2017-2018暖身段)
起始2017-01(讓2019事件的營收YoY有12個月暖身); Backer額度1600/hr(sleep 2.6s)
斷點續傳 tmp_cb_fund_cache.pkl; INSERT OR REPLACE冪等
用法: python fetch_cb_fundamentals.py   (中斷重跑會續傳)
"""
import os
import pickle
import sqlite3
import time
from datetime import date

import requests

DB = "capital_flow.db"
CACHE = "tmp_cb_fund_cache.pkl"
TOKEN = open("finmind_token.txt").read().strip()
START = "2017-01-01"
SLEEP = 2.6

DATASETS = {
    "TaiwanStockMonthRevenue": "fm_month_rev",
    "TaiwanStockFinancialStatements": "fm_income",
}


def universe():
    conn = sqlite3.connect(DB)
    rows = conn.execute("SELECT DISTINCT substr(cb_id,1,4) FROM cb_info").fetchall()
    conn.close()
    return sorted(c for (c,) in rows if c.isdigit() and len(c) == 4)


def fm_get(dataset, code):
    for attempt in range(4):
        try:
            r = requests.get("https://api.finmindtrade.com/api/v4/data",
                             params={"dataset": dataset, "data_id": code,
                                     "start_date": START, "end_date": str(date.today()),
                                     "token": TOKEN}, timeout=40)
            if r.status_code == 402:
                print(f"  額度限制,休息70s (attempt{attempt})", flush=True)
                time.sleep(70)
                continue
            j = r.json()
            if j.get("msg") != "success":
                print(f"  {dataset}/{code}: {j.get('msg')}", flush=True)
                time.sleep(20)
                continue
            return j.get("data") or []
        except Exception as e:
            print(f"  {dataset}/{code}: {type(e).__name__}, 重試", flush=True)
            time.sleep(15)
    return None


def main():
    codes = universe()
    print(f"CB發行公司宇宙 {len(codes)} 檔 × {len(DATASETS)} 資料集", flush=True)
    cache = {}
    if os.path.exists(CACHE):
        with open(CACHE, "rb") as f:
            cache = pickle.load(f)
    conn = sqlite3.connect(DB, timeout=120)  # 分析腳本讀大表時等鎖,防database is locked
    conn.execute("""CREATE TABLE IF NOT EXISTS fm_income (
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
                conn.executemany("INSERT OR REPLACE INTO fm_income VALUES (?,?,?,?)", rows)
            conn.commit()
            cache[key] = len(rows)
            done += 1
            if done % 25 == 0:
                with open(CACHE, "wb") as f:
                    pickle.dump(cache, f)
                print(f"進度 {len(cache)}/{total} (本次成功{done}, 待重試{fail})", flush=True)
            time.sleep(SLEEP)
    with open(CACHE, "wb") as f:
        pickle.dump(cache, f)
    for t in ["fm_month_rev", "fm_income"]:
        n = conn.execute(f"SELECT COUNT(*), COUNT(DISTINCT code) FROM {t}").fetchone()
        print(f"{t}: {n[0]} 筆 / {n[1]} 檔", flush=True)
    conn.close()
    print(f"完成！成功{done} 待重試{fail}", flush=True)


if __name__ == "__main__":
    main()
