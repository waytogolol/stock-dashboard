# -*- coding: utf-8 -*-
"""回補財報日歷史 -> DB earnings_dates 表(供財報事件研究)
- 台/日/韓/美: yfinance earnings_dates(每檔約25季)，取近380天+未來
- 陸: 東方財富披露預約API，近5個財報期的實際發布日(整批JSON低頻請求)
範圍: 最新快照各市場前100名。用法: python fetch_earnings_history.py (每季跑一次即可)
"""
import sqlite3
import sys
import time
from datetime import date, timedelta

import yfinance as yf

sys.path.insert(0, ".")
from backfill_history import ticker_variants
from fetch_earnings_dates import fetch_cn_period

DB = "capital_flow.db"
TOP_N = 100
LOOKBACK = 380


def main():
    conn = sqlite3.connect(DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS earnings_dates (
        market TEXT, code TEXT, date TEXT, fetched TEXT,
        PRIMARY KEY (market, code, date))""")
    latest = conn.execute("SELECT MAX(snapshot_date) FROM rankings").fetchone()[0]
    today = date.today()
    floor = today - timedelta(days=LOOKBACK)
    rows = []

    for market in ("台", "日", "韓", "美"):
        plan = conn.execute(
            """SELECT code, MIN(rank) FROM rankings
               WHERE snapshot_date=? AND country=? AND rank<=?
               GROUP BY code""", (latest, market, TOP_N)).fetchall()
        got = 0
        for i, (code, _rank) in enumerate(plan):
            for t in ticker_variants(market, code) or []:
                try:
                    ed = yf.Ticker(t).earnings_dates
                    if ed is None or ed.empty:
                        continue
                    for ts in ed.index:
                        d = ts.date()
                        if d >= floor:
                            rows.append((market, code, str(d), str(today)))
                    got += 1
                    break
                except Exception:
                    time.sleep(3)
            time.sleep(0.5)
            if (i + 1) % 25 == 0:
                print(f"{market} 進度 {i+1}/{len(plan)}")
        print(f"{market}: {got}/{len(plan)} 檔有歷史財報日")

    # 陸股: 近5個財報期(涵蓋約一年)的披露日(過去=實際發布日)
    cn_codes = set(c for (c,) in conn.execute(
        "SELECT DISTINCT code FROM rankings WHERE country='陸'"))
    for rp in ("2025-06-30", "2025-09-30", "2025-12-31", "2026-03-31", "2026-06-30"):
        try:
            m = fetch_cn_period(rp)
            n0 = len(rows)
            for code, eff in m.items():
                if code in cn_codes:
                    rows.append(("陸", code, eff, str(today)))
            print(f"陸 {rp}: {len(rows) - n0} 筆")
            time.sleep(2)
        except Exception as e:
            print(f"陸 {rp} 失敗: {e}")

    conn.executemany("INSERT OR IGNORE INTO earnings_dates VALUES (?,?,?,?)", rows)
    conn.commit()
    n = conn.execute("SELECT COUNT(*), COUNT(DISTINCT market||code) FROM earnings_dates").fetchone()
    conn.close()
    print(f"earnings_dates 累積: {n[0]} 筆 / {n[1]} 檔")


if __name__ == "__main__":
    main()
