# -*- coding: utf-8 -*-
"""TWSE T86 三大法人買賣超(上市) -> capital_flow.db inst_flow 表
金額=買賣超股數x當日收盤價(官方個股層級僅有股數,金額版只有全市場彙總)
每交易日2請求(T86+MI_INDEX收盤), 節流3.5s, tmp_t86_cache.pkl續傳, 連續8日全失敗熔斷
用法: python fetch_t86.py [起始日 預設2022-01-01]   (中斷重跑續傳)
"""
import os
import pickle
import sqlite3
import sys
import time
from datetime import date, timedelta

import requests

DB = "capital_flow.db"
CACHE = "tmp_t86_cache.pkl"
SLEEP = 3.5
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
START = sys.argv[1] if len(sys.argv) > 1 else "2022-01-01"


def get_json(url, params):
    r = requests.get(url, params=params, headers=UA, timeout=30)
    r.raise_for_status()
    return r.json()


def fetch_day(dstr):
    """dstr=YYYYMMDD; 回傳 rows=[(code, fnet, tnet, dnet, close)] 或 None(休市)"""
    t86 = get_json("https://www.twse.com.tw/rwd/zh/fund/T86",
                   {"date": dstr, "selectType": "ALLBUT0999", "response": "json"})
    if t86.get("stat") != "OK":
        return None
    time.sleep(SLEEP)
    mi = get_json("https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX",
                  {"date": dstr, "type": "ALLBUT0999", "response": "json"})
    closes = {}
    for tb in mi.get("tables", []):
        f = tb.get("fields") or []
        if "證券代號" in f and "收盤價" in f:
            ci, pi = f.index("證券代號"), f.index("收盤價")
            for row in tb.get("data", []):
                try:
                    closes[row[ci].strip()] = float(str(row[pi]).replace(",", ""))
                except (ValueError, AttributeError, IndexError):
                    continue
    f86 = t86.get("fields") or []

    def col(*keys):
        for i, name in enumerate(f86):
            if all(k in name for k in keys):
                return i
        return None

    ci = col("證券代號")
    fi = col("外陸資買賣超", "不含")
    ti = col("投信買賣超")
    di = col("三大法人買賣超")   # 用三大合計反推自營: dnet = 合計-外資-投信
    if None in (ci, fi, ti, di):
        raise RuntimeError(f"T86欄位對不到: {f86}")
    rows = []
    for row in t86.get("data", []):
        try:
            code = row[ci].strip()
            px = closes.get(code)
            if px is None:
                continue
            fnet = float(str(row[fi]).replace(",", "")) * px
            tnet = float(str(row[ti]).replace(",", "")) * px
            tot = float(str(row[di]).replace(",", "")) * px
        except (ValueError, AttributeError, IndexError):
            continue
        rows.append((dstr[:4] + "-" + dstr[4:6] + "-" + dstr[6:], code,
                     round(fnet), round(tnet), round(tot - fnet - tnet), round(px, 2)))
    return rows


def main():
    conn = sqlite3.connect(DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS inst_flow (
        date TEXT, code TEXT, foreign_net REAL, trust_net REAL, dealer_net REAL,
        close REAL, PRIMARY KEY (date, code))""")
    done = set()
    if os.path.exists(CACHE):
        with open(CACHE, "rb") as f:
            done = pickle.load(f)
    d = date.fromisoformat(START)
    today = date.today()
    fails = 0
    n_days = 0
    while d <= today:
        dstr = d.strftime("%Y%m%d")
        if dstr in done or d.weekday() >= 5:
            d += timedelta(days=1)
            continue
        try:
            rows = fetch_day(dstr)
            if rows:
                conn.executemany("INSERT OR REPLACE INTO inst_flow VALUES (?,?,?,?,?,?)", rows)
                conn.commit()
                n_days += 1
                if n_days % 20 == 0:
                    print(f"{dstr}: {len(rows)}檔 (本次累計{n_days}日)", flush=True)
            done.add(dstr)          # 休市日也記,不再重試
            fails = 0
        except Exception as e:
            fails += 1
            print(f"{dstr}: {type(e).__name__} {e} (連續{fails})", flush=True)
            if fails >= 8:
                print("[熔斷] 連續8日失敗,進度已存,稍後重跑續傳", flush=True)
                break
            time.sleep(30)
        with open(CACHE, "wb") as f:
            pickle.dump(done, f)
        time.sleep(SLEEP)
        d += timedelta(days=1)
    n = conn.execute("SELECT COUNT(*), COUNT(DISTINCT date) FROM inst_flow").fetchone()
    print(f"inst_flow: {n[0]:,} 筆 / {n[1]} 交易日")
    conn.close()


if __name__ == "__main__":
    main()
