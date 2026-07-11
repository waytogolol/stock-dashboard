# -*- coding: utf-8 -*-
"""TWSE 融資融券餘額(上市) -> margin_flow 表
每交易日1請求(MI_MARGN selectType=ALL); 節流3.5s; tmp_margin_cache.pkl續傳; 連8日失敗熔斷
存: 融資餘額(張)/限額/使用率%、融券餘額(張)、券資比%
用法: python fetch_margin.py [起始日 預設2022-01-01]
"""
import os
import pickle
import sqlite3
import sys
import time
from datetime import date, timedelta

import requests

DB = "capital_flow.db"
CACHE = "tmp_margin_cache.pkl"
SLEEP = 3.5
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
START = sys.argv[1] if len(sys.argv) > 1 else "2022-01-01"


def fetch_day(dstr):
    r = requests.get("https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN",
                     params={"date": dstr, "selectType": "ALL", "response": "json"},
                     headers=UA, timeout=30)
    r.raise_for_status()
    j = r.json()
    if j.get("stat") != "OK":
        return None
    table = None
    for tb in j.get("tables", []):
        f = tb.get("fields") or []
        if f and f[0] in ("代號", "股票代號"):
            table = tb
            break
    if table is None:
        return None
    rows = []
    iso = dstr[:4] + "-" + dstr[4:6] + "-" + dstr[6:]
    for row in table.get("data", []):
        if len(row) < 15:
            continue
        try:
            code = str(row[0]).strip()
            fin_bal = float(str(row[6]).replace(",", ""))
            fin_lim = float(str(row[7]).replace(",", ""))
            short_bal = float(str(row[12]).replace(",", ""))
            use = fin_bal / fin_lim * 100 if fin_lim else None
            ratio = short_bal / fin_bal * 100 if fin_bal else None
            rows.append((iso, code, fin_bal, fin_lim,
                         round(use, 2) if use is not None else None,
                         short_bal, round(ratio, 2) if ratio is not None else None))
        except (ValueError, IndexError):
            continue
    return rows


def main():
    conn = sqlite3.connect(DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS margin_flow (
        date TEXT, code TEXT, fin_bal REAL, fin_limit REAL, fin_use REAL,
        short_bal REAL, short_fin_ratio REAL, PRIMARY KEY (date, code))""")
    done = set()
    if os.path.exists(CACHE):
        with open(CACHE, "rb") as f:
            done = pickle.load(f)
    d = date.fromisoformat(START)
    today = date.today()
    fails = n_days = 0
    while d <= today:
        dstr = d.strftime("%Y%m%d")
        if dstr in done or d.weekday() >= 5:
            d += timedelta(days=1)
            continue
        try:
            rows = fetch_day(dstr)
            if rows:
                conn.executemany("INSERT OR REPLACE INTO margin_flow VALUES (?,?,?,?,?,?,?)", rows)
                conn.commit()
                n_days += 1
                if n_days % 25 == 0:
                    print(f"{dstr}: {len(rows)}檔 (本次累計{n_days}日)", flush=True)
            done.add(dstr)
            fails = 0
        except Exception as e:
            fails += 1
            print(f"{dstr}: {type(e).__name__} {e} (連續{fails})", flush=True)
            if fails >= 8:
                print("[熔斷] 進度已存,稍後重跑續傳", flush=True)
                break
            time.sleep(30)
        with open(CACHE, "wb") as f:
            pickle.dump(done, f)
        time.sleep(SLEEP)
        d += timedelta(days=1)
    n = conn.execute("SELECT COUNT(*), COUNT(DISTINCT date) FROM margin_flow").fetchone()
    print(f"margin_flow: {n[0]:,} 筆 / {n[1]} 交易日")


if __name__ == "__main__":
    main()
