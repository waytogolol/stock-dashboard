# -*- coding: utf-8 -*-
"""FinMind TDCC股權分級歷史庫「人數」版 -> capital_flow.db (tdcc_people)
用途: 大戶「人數」增減 vs 持股「比例」增減 象限分析(千張大戶人數變化特徵);
  tdcc_weekly建表時只留了percent、把各級距people丟掉,本腳本補抓同一資料集的人數面
級距聚合: 與fetch_tdcc_history.py完全同口徑(定義一致,可直接join tdcc_weekly):
  n600/n800/n1000=持股>600/800/1000張的股東人數合計(級距累加),
  n_retail=<10張人數合計, n_total=total列人數(應等於tdcc_weekly.n_people)
節流: 2.6s(Backer 1600/hr);斷點續傳 tmp_tdcc_people_cache.pkl(code->週數,含空檔);
  連續8檔失敗=斷路器存檔退出;效期2026-08-15前跑完
宇宙: tdcc_weekly ∪ fm_daily_price 的4碼代號(≈2,028檔, 約1.5hr)
用法: python fetch_tdcc_people.py
"""
import os
import pickle
import re
import sqlite3
import sys
import time
from datetime import date

import requests

sys.stdout.reconfigure(encoding="utf-8")

DB = "capital_flow.db"
DONE_CACHE = "tmp_tdcc_people_cache.pkl"
TOKEN = open("finmind_token.txt").read().strip()
SLEEP = 2.6
MAX_CONSEC_FAIL = 8
LV1000 = {"more than 1,000,001"}
LV800 = LV1000 | {"800,001-1,000,000"}
LV600 = LV800 | {"600,001-800,000"}
LV_RETAIL = {"1-999", "1,000-5,000", "5,001-10,000"}


def universe():
    con = sqlite3.connect(DB)
    u = set(r[0] for r in con.execute("select distinct code from tdcc_weekly"))
    u |= set(r[0] for r in con.execute(
        "select distinct code from fm_daily_price"))
    con.close()
    return sorted(c for c in u if isinstance(c, str) and re.fullmatch(r"\d{4}", c))


def fm_get(code):
    for attempt in range(4):
        try:
            r = requests.get("https://api.finmindtrade.com/api/v4/data",
                             params={"dataset": "TaiwanStockHoldingSharesPer", "data_id": code,
                                     "start_date": "2013-01-01", "end_date": str(date.today()),
                                     "token": TOKEN}, timeout=90)
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
    return None


def aggregate(rows):
    """FinMind級距列 -> {date: (n600,n800,n1000,n_retail,n_total)} 人數版"""
    out = {}
    for r in rows:
        d = r["date"]
        lv = r["HoldingSharesLevel"]
        if d not in out:
            out[d] = {"n600": 0, "n800": 0, "n1000": 0, "nr": 0, "nt": None}
        o = out[d]
        if lv == "total":
            o["nt"] = r["people"]
            continue
        if lv in LV600:
            o["n600"] += r["people"]
        if lv in LV800:
            o["n800"] += r["people"]
        if lv in LV1000:
            o["n1000"] += r["people"]
        if lv in LV_RETAIL:
            o["nr"] += r["people"]
    return out


def main():
    con = sqlite3.connect(DB)
    con.execute("""CREATE TABLE IF NOT EXISTS tdcc_people(
        code TEXT, date TEXT, n600 INTEGER, n800 INTEGER, n1000 INTEGER,
        n_retail INTEGER, n_total INTEGER, PRIMARY KEY(code, date))""")
    done = {}
    if os.path.exists(DONE_CACHE):
        with open(DONE_CACHE, "rb") as f:
            done = pickle.load(f)
    codes = universe()
    todo = [c for c in codes if c not in done]
    print(f"宇宙{len(codes)}檔, 已完成{len(done)}, 待抓{len(todo)}"
          f" (預估{len(todo) * SLEEP / 3600:.1f}hr)", flush=True)
    t0 = time.time()
    consec_fail = 0
    n_req = 0
    for i, code in enumerate(todo):
        rows = fm_get(code)
        n_req += 1
        if rows is None:
            consec_fail += 1
            print(f"  {code}: 連續失敗跳過(下次續傳重試) [{consec_fail}/{MAX_CONSEC_FAIL}]",
                  flush=True)
            if consec_fail >= MAX_CONSEC_FAIL:
                print(f"斷路器: 連續{MAX_CONSEC_FAIL}檔失敗, 進度已存{DONE_CACHE}, "
                      f"請檢查網路/token後重跑續傳", flush=True)
                con.close()
                sys.exit(1)
            time.sleep(SLEEP)
            continue
        consec_fail = 0
        agg = aggregate(rows)
        con.executemany(
            "INSERT OR REPLACE INTO tdcc_people VALUES(?,?,?,?,?,?,?)",
            [(code, d, o["n600"], o["n800"], o["n1000"], o["nr"], o["nt"])
             for d, o in agg.items()])
        con.commit()
        done[code] = len(agg)
        with open(DONE_CACHE, "wb") as f:
            pickle.dump(done, f)
        if i % 50 == 0:
            el = time.time() - t0
            eta = el / (i + 1) * (len(todo) - i - 1) / 3600
            print(f"[{i + 1}/{len(todo)}] {code}: {len(agg)}週 "
                  f"(耗時{el / 60:.0f}min, 剩約{eta:.1f}hr)", flush=True)
        time.sleep(SLEEP)
    n = con.execute("select count(*), count(distinct code), min(date), max(date) "
                    "from tdcc_people").fetchone()
    empty = sum(1 for v in done.values() if v == 0)
    print(f"完成: tdcc_people {n[0]:,}筆 / {n[1]}檔 / {n[2]}~{n[3]} "
          f"(本次{n_req}請求, 空資料{empty}檔, 總耗時{(time.time() - t0) / 3600:.2f}hr)",
          flush=True)
    con.close()


if __name__ == "__main__":
    main()
