# -*- coding: utf-8 -*-
"""FinMind TDCC股權分級歷史庫 -> capital_flow.db (tdcc_weekly)
用途: 大戶持股×題材動能考卷+H4千張連升回測;歷史2013起(已實測),推翻「TDCC無歷史」限制
儲存: 原始15級距×700週×1379檔≈1500萬列會爆DB→聚合後存,每檔-週一列:
  p600/p800/p1000=持股>600/800/1000張的合計%(級距累加), p_retail=<10張合計%,
  n_people=總股東人數(total列), 差異數調整列剔除
節流: 2.6s(Backer 1600/hr);斷點續傳 tmp_tdcc_hist_done.pkl;效期2026-08-15前跑完
用法: python fetch_tdcc_history.py
"""
import os
import pickle
import re
import sqlite3
import time
from datetime import date

import requests

DB = "capital_flow.db"
DONE_CACHE = "tmp_tdcc_hist_done.pkl"
TOKEN = open("finmind_token.txt").read().strip()
SLEEP = 2.6
LV1000 = {"more than 1,000,001"}
LV800 = LV1000 | {"800,001-1,000,000"}
LV600 = LV800 | {"600,001-800,000"}
LV_RETAIL = {"1-999", "1,000-5,000", "5,001-10,000"}


def universe():
    con = sqlite3.connect(DB)
    u = set()
    for q in ["select distinct code from classification where country='台'",
              "select distinct code from fm_month_rev",
              "select distinct code from inst_flow"]:
        u |= set(r[0] for r in con.execute(q))
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
    """FinMind級距列 -> {date: (p600,p800,p1000,p_retail,n_people)}"""
    out = {}
    for r in rows:
        d = r["date"]
        lv = r["HoldingSharesLevel"]
        if d not in out:
            out[d] = {"p600": 0.0, "p800": 0.0, "p1000": 0.0, "pr": 0.0, "np": None}
        o = out[d]
        if lv == "total":
            o["np"] = r["people"]
            continue
        if lv in LV600:
            o["p600"] += r["percent"]
        if lv in LV800:
            o["p800"] += r["percent"]
        if lv in LV1000:
            o["p1000"] += r["percent"]
        if lv in LV_RETAIL:
            o["pr"] += r["percent"]
    return out


def main():
    con = sqlite3.connect(DB)
    con.execute("""CREATE TABLE IF NOT EXISTS tdcc_weekly(
        code TEXT, date TEXT, p600 REAL, p800 REAL, p1000 REAL,
        p_retail REAL, n_people INTEGER, PRIMARY KEY(code, date))""")
    done = set()
    if os.path.exists(DONE_CACHE):
        with open(DONE_CACHE, "rb") as f:
            done = pickle.load(f)
    codes = universe()
    todo = [c for c in codes if c not in done]
    print(f"宇宙{len(codes)}檔, 已完成{len(done)}, 待抓{len(todo)}"
          f" (預估{len(todo) * SLEEP / 3600:.1f}hr)", flush=True)
    for i, code in enumerate(todo):
        rows = fm_get(code)
        if rows is None:
            print(f"  {code}: 連續失敗跳過(下次續傳重試)", flush=True)
            time.sleep(SLEEP)
            continue
        agg = aggregate(rows)
        con.executemany(
            "INSERT OR REPLACE INTO tdcc_weekly VALUES(?,?,?,?,?,?,?)",
            [(code, d, round(o["p600"], 3), round(o["p800"], 3), round(o["p1000"], 3),
              round(o["pr"], 3), o["np"]) for d, o in agg.items()])
        con.commit()
        done.add(code)
        with open(DONE_CACHE, "wb") as f:
            pickle.dump(done, f)
        if i % 50 == 0:
            print(f"[{i + 1}/{len(todo)}] {code}: {len(agg)}週", flush=True)
        time.sleep(SLEEP)
    n = con.execute("select count(*), count(distinct code), min(date) from tdcc_weekly").fetchone()
    print(f"完成: tdcc_weekly {n[0]:,}筆 / {n[1]}檔 / 最早{n[2]}", flush=True)
    con.close()


if __name__ == "__main__":
    main()
