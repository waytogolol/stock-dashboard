# -*- coding: utf-8 -*-
"""FinMind 暫停融券賣出表(融券回補日) -> capital_flow.db (margin_short_suspend)
動機(2026-08-02使用者提案): 股東會/除權息前交易所公告「停止融資融券」,期間內融券未回補部位
強制買回=被迫買方,與斷頭線(被迫賣方)鏡像對照,三問機制①很扎實,值得建表做事件研究。
資料集: TaiwanStockMarginShortSaleSuspension(確認於finmind.github.io/llms-full.txt)
  欄位: stock_id/date(停止融資融券起始日)/end_date(結束日,含)/reason(股東常會/除權/除息/除權息/股東臨時會等)
  範圍: 2015-01-01~now,免費層需data_id逐檔查(單檔一次拿全期,比逐日查全市場省請求數);
        Backer/Sponsor可不帶data_id但僅限「單一start_date」精準比對(=逐日全市場模式,已測試確認,
        本腳本用逐檔模式因總請求數更省)。最後回補日≈date前一交易日(公告當日起停止融資融券,
        故回補須在此之前完成),事件研究由分析腳本自行對到交易日曆。
用法: python fetch_margin_short_suspend.py           (逐檔全量回補,中斷重跑會續傳)
      python fetch_margin_short_suspend.py --test     (只抓5檔驗證管線)
"""
import csv
import os
import pickle
import re
import sqlite3
import sys
import time
from datetime import date

import requests

DB = "capital_flow.db"
DONE_CACHE = "快取/tmp_margin_suspend_done.pkl"
TOKEN = open("finmind_token.txt").read().strip()
URL = "https://api.finmindtrade.com/api/v4/data"
DATASET = "TaiwanStockMarginShortSaleSuspension"
START = "2015-01-01"
SLEEP = 2.6  # Backer額度1600/hr節流慣例(同fetch_daily_price.py)


def universe():
    """上市+上櫃四位數個股(同fetch_daily_price.py口徑,排除00xxx ETF/興櫃)。
    融券暫停僅適用有信用交易資格個股,全市場名單已是超集,不刻意再交集margin_flow。"""
    with open("tw_all_listed.csv", encoding="utf-8-sig") as f:
        codes = {row["code"] for row in csv.DictReader(f) if row["market"] in ("上市", "上櫃")}
    return sorted(c for c in codes if isinstance(c, str) and re.fullmatch(r"\d{4}", c))


def fm_get(code):
    for attempt in range(4):
        try:
            r = requests.get(URL, params={"dataset": DATASET, "data_id": code,
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
    return None  # 連續失敗,下次執行重試


def main():
    test = "--test" in sys.argv
    con = sqlite3.connect(DB, timeout=60)
    con.execute("""CREATE TABLE IF NOT EXISTS margin_short_suspend(
        code TEXT, start_date TEXT, end_date TEXT, reason TEXT,
        PRIMARY KEY(code, start_date))""")
    done = set()
    if os.path.exists(DONE_CACHE):
        with open(DONE_CACHE, "rb") as f:
            done = pickle.load(f)
    codes = universe()
    todo = [c for c in codes if c not in done]
    if test:
        todo = todo[:5]
    print(f"宇宙{len(codes)}檔, 已完成{len(done)}, 待抓{len(todo)}"
          f" (預估{len(todo) * SLEEP / 3600:.1f}hr)", flush=True)
    n_rows = 0
    for i, code in enumerate(todo):
        rows = fm_get(code)
        if rows is None:
            print(f"  {code}: 連續失敗跳過(未記done,下次續傳重試)", flush=True)
            time.sleep(SLEEP)
            continue
        con.executemany(
            "INSERT OR REPLACE INTO margin_short_suspend VALUES(?,?,?,?)",
            [(r["stock_id"], r["date"], r["end_date"], r["reason"]) for r in rows])
        con.commit()
        n_rows += len(rows)
        done.add(code)
        with open(DONE_CACHE, "wb") as f:
            pickle.dump(done, f)
        if i % 100 == 0 or test:
            print(f"[{i + 1}/{len(todo)}] {code}: {len(rows)}筆 (本次累計{n_rows:,})", flush=True)
        time.sleep(SLEEP)
    n = con.execute("SELECT COUNT(*), COUNT(DISTINCT code), MIN(start_date), MAX(start_date) "
                    "FROM margin_short_suspend").fetchone()
    print(f"完成: margin_short_suspend {n[0]:,}筆 / {n[1]}檔 / {n[2]}~{n[3]}", flush=True)
    con.close()


if __name__ == "__main__":
    main()
