# -*- coding: utf-8 -*-
"""FinMind CB每日總覽歷史庫 -> capital_flow.db (cb_overview)
用途: CB三假說(H-CB1磁吸/H-CB2計時器/H-CB3終局)+賣回窗;逐日全市場一天一請求
範圍: 2019-01起(資料集歷史下限已實測至少2019);交易日曆=tmp_twii_long.pkl(省掉週末空請求)
節流: 2.6s(Backer 1600/hr);斷點續傳 tmp_cb_overview_done.pkl;Backer效期2026-08-15前要跑完
用法: python fetch_cb_overview.py
"""
import os
import pickle
import sqlite3
import time

import pandas as pd
import requests

DB = "capital_flow.db"
DONE_CACHE = "tmp_cb_overview_done.pkl"
TOKEN = open("finmind_token.txt").read().strip()
SLEEP = 2.6
COLS = ["cb_id", "date", "ConversionPrice", "NextEffectiveDateOfConversionPrice",
        "OutstandingAmount", "IssuanceAmount", "ReferencePrice", "PriceOfUnderlyingStock",
        "LatestInitialDateOfPut", "LatestDueDateOfPut", "LatestPutPrice",
        "InitialDateOfEarlyRedemption", "DueDateOfEarlyRedemption", "EarlyRedemptionPrice",
        "DateOfDelisted", "CouponRate"]


def fm_get(day):
    for attempt in range(4):
        try:
            r = requests.get("https://api.finmindtrade.com/api/v4/data",
                             params={"dataset": "TaiwanStockConvertibleBondDailyOverview",
                                     "start_date": day, "end_date": day, "token": TOKEN},
                             timeout=60)
            if r.status_code == 402:
                print(f"  額度限制,休息70s (attempt{attempt})", flush=True)
                time.sleep(70)
                continue
            j = r.json()
            if j.get("msg") != "success":
                print(f"  {day}: {j.get('msg')}", flush=True)
                time.sleep(20)
                continue
            return j.get("data") or []
        except Exception as e:
            print(f"  {day}: {type(e).__name__}, 重試", flush=True)
            time.sleep(15)
    return None


def main():
    con = sqlite3.connect(DB)
    con.execute("""CREATE TABLE IF NOT EXISTS cb_overview(
        cb_id TEXT, date TEXT, conv_price REAL, next_conv_date TEXT,
        outstanding REAL, issuance REAL, ref_price REAL, stock_price REAL,
        put_start TEXT, put_due TEXT, put_price REAL,
        redeem_start TEXT, redeem_due TEXT, redeem_price REAL,
        delist_date TEXT, coupon REAL, PRIMARY KEY(cb_id, date))""")
    done = set()
    if os.path.exists(DONE_CACHE):
        with open(DONE_CACHE, "rb") as f:
            done = pickle.load(f)
    cal = pd.read_pickle("tmp_twii_long.pkl").dropna()
    days = [d.strftime("%Y-%m-%d") for d in cal.index if d >= pd.Timestamp("2019-01-01")]
    todo = [d for d in days if d not in done]
    print(f"交易日{len(days)}, 已完成{len(done)}, 待抓{len(todo)}"
          f" (預估{len(todo) * SLEEP / 3600:.1f}hr)", flush=True)
    for i, day in enumerate(todo):
        rows = fm_get(day)
        if rows is None:
            print(f"  {day}: 連續失敗跳過(下次續傳重試)", flush=True)
            time.sleep(SLEEP)
            continue
        con.executemany(
            "INSERT OR REPLACE INTO cb_overview VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [tuple(r.get(c) for c in COLS) for r in rows])
        con.commit()
        done.add(day)
        with open(DONE_CACHE, "wb") as f:
            pickle.dump(done, f)
        if i % 100 == 0:
            print(f"[{i + 1}/{len(todo)}] {day}: {len(rows)}檔CB", flush=True)
        time.sleep(SLEEP)
    n = con.execute("select count(*), count(distinct cb_id), min(date) from cb_overview").fetchone()
    print(f"完成: cb_overview {n[0]:,}筆 / {n[1]}檔CB / 最早{n[2]}", flush=True)
    con.close()


if __name__ == "__main__":
    main()
