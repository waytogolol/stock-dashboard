# -*- coding: utf-8 -*-
"""CB逐檔日成交+三大法人 -> cb_daily / cb_inst 表(使用者2026-07-16)
目的: ①驗證「CB上市第6天=CBAS拆解日爆大量」 ②自營商買超spike=CBAS承作腳印(事件偵測器,
     非方向訊號——自營流主體=拆解+套利避險,使用者提醒) ③S3危機訊號的真未跟vs沒成交分辨
資料集: TaiwanStockConvertibleBondDaily / TaiwanStockConvertibleBondInstitutionalInvestors
       (皆2020-04起,Backer限定); 宇宙=cb_info全部cb_id(~1799檔×2=3598請求≈2.6hr)
斷點續傳tmp_cb_daily_cache.pkl; 冪等; ⚠與fetch_cb_fundamentals.py共用額度,勿同時跑
用法: python fetch_cb_daily.py
"""
import os
import pickle
import sqlite3
import time
from datetime import date

import requests

DB = "capital_flow.db"
CACHE = "tmp_cb_daily_cache.pkl"
TOKEN = open("finmind_token.txt").read().strip()
START = "2020-04-01"
SLEEP = 2.6
DATASETS = ("TaiwanStockConvertibleBondDaily", "TaiwanStockConvertibleBondInstitutionalInvestors")


def fm_get(ds, code):
    for attempt in range(4):
        try:
            r = requests.get("https://api.finmindtrade.com/api/v4/data",
                             params={"dataset": ds, "data_id": code,
                                     "start_date": START, "end_date": str(date.today()),
                                     "token": TOKEN}, timeout=40)
            if r.status_code == 402:
                print(f"  額度限制,休息70s (attempt{attempt})", flush=True)
                time.sleep(70)
                continue
            j = r.json()
            if j.get("msg") != "success":
                print(f"  {ds}/{code}: {j.get('msg')}", flush=True)
                time.sleep(20)
                continue
            return j.get("data") or []
        except Exception as e:
            print(f"  {ds}/{code}: {type(e).__name__}, 重試", flush=True)
            time.sleep(15)
    return None


def main():
    conn = sqlite3.connect(DB, timeout=120)  # 防database is locked
    ids = [c for (c,) in conn.execute("SELECT DISTINCT cb_id FROM cb_info").fetchall()]
    conn.execute("""CREATE TABLE IF NOT EXISTS cb_daily (
        cb_id TEXT, date TEXT, open REAL, high REAL, low REAL, close REAL,
        volume REAL, value REAL, n_trans REAL, PRIMARY KEY (cb_id, date))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS cb_inst (
        cb_id TEXT, date TEXT, fi_buy REAL, fi_sell REAL, it_buy REAL, it_sell REAL,
        dealer_buy REAL, dealer_sell REAL, total_overbuy REAL, PRIMARY KEY (cb_id, date))""")
    cache = {}
    if os.path.exists(CACHE):
        with open(CACHE, "rb") as f:
            cache = pickle.load(f)
    total = len(ids) * len(DATASETS)
    print(f"CB宇宙 {len(ids)} 檔 × 2資料集 (已完成{len(cache)}/{total})", flush=True)
    shown = set()
    done = fail = 0
    for ds in DATASETS:
        for cid in ids:
            key = (ds, cid)
            if key in cache:
                continue
            data = fm_get(ds, cid)
            if data is None:
                fail += 1
                time.sleep(SLEEP)
                continue
            if data and ds not in shown:
                print(f"  {ds} 樣本欄位: {sorted(data[0].keys())}", flush=True)
                shown.add(ds)
            if ds == "TaiwanStockConvertibleBondDaily":
                rows = [(cid, d.get("date"), d.get("open"),
                         d.get("max") or d.get("high"), d.get("min") or d.get("low"),
                         d.get("close"), d.get("unit") or d.get("trading_volume"),
                         d.get("trading_value"), d.get("no_of_transactions")) for d in data]
                conn.executemany("INSERT OR REPLACE INTO cb_daily VALUES (?,?,?,?,?,?,?,?,?)",
                                 rows)
            else:
                rows = [(cid, d.get("date"),
                         d.get("Foreign_Investor_Buy"), d.get("Foreign_Investor_Sell"),
                         d.get("Investment_Trust_Buy"), d.get("Investment_Trust_Sell"),
                         d.get("Dealer_self_Buy"), d.get("Dealer_self_Sell"),
                         d.get("Total_Overbuy")) for d in data]
                conn.executemany("INSERT OR REPLACE INTO cb_inst VALUES (?,?,?,?,?,?,?,?,?)",
                                 rows)
            conn.commit()
            cache[key] = len(rows)
            done += 1
            if done % 50 == 0:
                with open(CACHE, "wb") as f:
                    pickle.dump(cache, f)
                print(f"進度 {len(cache)}/{total} (本次成功{done}, 待重試{fail})", flush=True)
            time.sleep(SLEEP)
    with open(CACHE, "wb") as f:
        pickle.dump(cache, f)
    for t in ("cb_daily", "cb_inst"):
        n = conn.execute(f"SELECT COUNT(*), COUNT(DISTINCT cb_id) FROM {t}").fetchone()
        print(f"{t}: {n[0]}筆 / {n[1]}檔", flush=True)
    conn.close()
    print(f"完成！成功{done} 待重試{fail}", flush=True)


if __name__ == "__main__":
    main()
