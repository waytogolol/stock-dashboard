# -*- coding: utf-8 -*-
"""大盤/櫃買指數日線 -> capital_flow.db (index_daily / index_tr)
來源: FinMind TaiwanStockPrice(TAIEX 1999起 / TPEx 2005起, OHLC+成交值)
      TaiwanStockTotalReturnIndex(含息報酬指數, TAIEX 2003起 / TPEx 2006起)
共4請求, 冪等(INSERT OR REPLACE), 每週例行可重跑取增量。
用法: python fetch_index_daily.py
"""
import sqlite3
import time
from datetime import date

import requests

DB = "capital_flow.db"
TOKEN = open("finmind_token.txt").read().strip()
SLEEP = 2.6


def fm_get(dataset, data_id):
    for attempt in range(4):
        try:
            r = requests.get("https://api.finmindtrade.com/api/v4/data",
                             params={"dataset": dataset, "data_id": data_id,
                                     "start_date": "1990-01-01",
                                     "end_date": str(date.today()), "token": TOKEN},
                             timeout=60)
            if r.status_code == 402:
                print(f"  額度限制,休息70s (attempt{attempt})")
                time.sleep(70)
                continue
            j = r.json()
            if j.get("msg") != "success":
                print(f"  {dataset}/{data_id}: {j.get('msg')}")
                time.sleep(20)
                continue
            return j.get("data") or []
        except Exception as e:
            print(f"  {dataset}/{data_id}: {type(e).__name__}, 重試")
            time.sleep(15)
    raise SystemExit(f"{dataset}/{data_id} 連續失敗")


def main():
    conn = sqlite3.connect(DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS index_daily (
        market TEXT, date TEXT, open REAL, high REAL, low REAL, close REAL,
        volume REAL, money REAL, PRIMARY KEY (market, date))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS index_tr (
        market TEXT, date TEXT, price REAL, PRIMARY KEY (market, date))""")

    for mkt in ("TAIEX", "TPEx"):
        rows = fm_get("TaiwanStockPrice", mkt)
        conn.executemany(
            "INSERT OR REPLACE INTO index_daily VALUES (?,?,?,?,?,?,?,?)",
            [(mkt, d["date"], d["open"], d["max"], d["min"], d["close"],
              d["Trading_Volume"], d["Trading_money"]) for d in rows])
        print(f"index_daily/{mkt}: {len(rows)}筆 {rows[0]['date']}~{rows[-1]['date']}")
        time.sleep(SLEEP)

        rows = fm_get("TaiwanStockTotalReturnIndex", mkt)
        conn.executemany(
            "INSERT OR REPLACE INTO index_tr VALUES (?,?,?)",
            [(mkt, d["date"], d["price"]) for d in rows])
        print(f"index_tr/{mkt}: {len(rows)}筆 {rows[0]['date']}~{rows[-1]['date']}")
        time.sleep(SLEEP)

    conn.commit()
    conn.close()


if __name__ == "__main__":
    main()
