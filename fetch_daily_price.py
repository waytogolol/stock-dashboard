# -*- coding: utf-8 -*-
"""FinMind台股日OHLC歷史庫 -> capital_flow.db (fm_daily_price)
用途: 漲停研究(需未調整價,yfinance調整價除權息日會誤判)+score=4事件樣本延伸到2019
範圍: 研究宇宙(classification台∪fm_month_rev∪inst_flow=~1682檔) 2019-01起
節流: 每請求間隔2.6s(Backer額度1600/hr,留~200/hr餘裕;免費層改回6.1s)；斷點續傳 tmp_daily_price_done.pkl；402退避重試
用法: python fetch_daily_price.py           (逐檔全量回補,中斷重跑會續傳)
      python fetch_daily_price.py --update  (增量:單日全市場查詢補齊缺日,Backer限定,每週流程用)
      python fetch_daily_price.py --test    (只抓2檔驗證管線)
欄位: open/high/low/close=未調整價, spread=收盤漲跌價差, volume=成交股數, money=成交金額
"""
import os
import pickle
import re
import sqlite3
import sys
import time
from datetime import date

import requests

DB = "capital_flow.db"
DONE_CACHE = "tmp_daily_price_done.pkl"
TOKEN = open("finmind_token.txt").read().strip()
START = "2019-01-01"
SLEEP = 2.6


def universe():
    con = sqlite3.connect(DB)
    u = set()
    for q in ["select distinct code from classification where country='台'",
              "select distinct code from fm_month_rev",
              "select distinct code from inst_flow"]:
        u |= set(r[0] for r in con.execute(q))
    con.close()
    # 只留4位純數字=個股(排除00xxxA債券ETF等303檔,漲停規則不同也非題材成員)
    return sorted(c for c in u if isinstance(c, str) and re.fullmatch(r"\d{4}", c))


def fm_get(code):
    for attempt in range(4):
        try:
            r = requests.get("https://api.finmindtrade.com/api/v4/data",
                             params={"dataset": "TaiwanStockPrice", "data_id": code,
                                     "start_date": START, "end_date": str(date.today()),
                                     "token": TOKEN}, timeout=60)
            if r.status_code == 402:
                print(f"  額度限制,休息70s (attempt{attempt})", flush=True)
                time.sleep(70)
                continue
            j = r.json()
            if j.get("msg") != "success":
                print(f"  {code}: {j.get('msg')}", flush=True)
                time.sleep(20)
                continue
            return j.get("data") or []
        except Exception as e:
            print(f"  {code}: {type(e).__name__}, 重試", flush=True)
            time.sleep(15)
    return None  # 連續失敗，下次執行重試


def update_mode():
    """增量: 從庫內最新日之後逐日抓全市場(1請求/日,Backer限定),只留宇宙內個股"""
    con = sqlite3.connect(DB)
    last = con.execute("SELECT MAX(date) FROM fm_daily_price").fetchone()[0]
    keep = set(universe())
    d = date.fromisoformat(last) + __import__("datetime").timedelta(days=1)
    n_days = 0
    while d <= date.today():
        if d.weekday() < 5:
            for attempt in range(3):
                try:
                    r = requests.get("https://api.finmindtrade.com/api/v4/data",
                                     params={"dataset": "TaiwanStockPrice", "start_date": str(d),
                                             "end_date": str(d), "token": TOKEN}, timeout=120)
                    j = r.json()
                    if j.get("msg") != "success":
                        print(f"  {d}: {j.get('msg')}", flush=True)
                        time.sleep(20)
                        continue
                    rows = [x for x in (j.get("data") or []) if x["stock_id"] in keep]
                    con.executemany(
                        "INSERT OR REPLACE INTO fm_daily_price VALUES(?,?,?,?,?,?,?,?,?)",
                        [(x["stock_id"], x["date"], x["open"], x["max"], x["min"], x["close"],
                          x["spread"], x["Trading_Volume"], x["Trading_money"]) for x in rows])
                    con.commit()
                    if rows:
                        n_days += 1
                    print(f"  {d}: {len(rows)}檔", flush=True)
                    break
                except Exception as e:
                    print(f"  {d}: {type(e).__name__} 重試", flush=True)
                    time.sleep(15)
            time.sleep(SLEEP)
        d += __import__("datetime").timedelta(days=1)
    nn = con.execute("SELECT COUNT(*), MAX(date) FROM fm_daily_price").fetchone()
    print(f"增量完成: 補{n_days}個交易日, 總{nn[0]:,}筆, 最新{nn[1]}", flush=True)
    con.close()


def main():
    if "--update" in sys.argv:
        update_mode()
        return
    test = "--test" in sys.argv
    con = sqlite3.connect(DB)
    con.execute("""CREATE TABLE IF NOT EXISTS fm_daily_price(
        code TEXT, date TEXT, open REAL, high REAL, low REAL, close REAL,
        spread REAL, volume INTEGER, money REAL, PRIMARY KEY(code, date))""")
    done = set()
    if os.path.exists(DONE_CACHE):
        with open(DONE_CACHE, "rb") as f:
            done = pickle.load(f)
    codes = universe()
    todo = [c for c in codes if c not in done]
    if test:
        todo = todo[:2]
    print(f"宇宙{len(codes)}檔, 已完成{len(done)}, 待抓{len(todo)}"
          f" (預估{len(todo) * SLEEP / 3600:.1f}hr)", flush=True)
    for i, code in enumerate(todo):
        rows = fm_get(code)
        if rows is None:
            print(f"  {code}: 連續失敗跳過(未記done,下次續傳重試)", flush=True)
            time.sleep(SLEEP)
            continue
        con.executemany(
            "INSERT OR REPLACE INTO fm_daily_price VALUES(?,?,?,?,?,?,?,?,?)",
            [(r["stock_id"], r["date"], r["open"], r["max"], r["min"], r["close"],
              r["spread"], r["Trading_Volume"], r["Trading_money"]) for r in rows])
        con.commit()
        done.add(code)
        with open(DONE_CACHE, "wb") as f:
            pickle.dump(done, f)
        if i % 50 == 0 or test:
            print(f"[{i + 1}/{len(todo)}] {code}: {len(rows)}筆", flush=True)
        time.sleep(SLEEP)
    n = con.execute("select count(*), count(distinct code) from fm_daily_price").fetchone()
    print(f"完成: fm_daily_price {n[0]}筆 / {n[1]}檔", flush=True)
    con.close()


if __name__ == "__main__":
    main()
