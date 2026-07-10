# -*- coding: utf-8 -*-
"""抓日/韓股財報公布日期 -> jp_kr_earnings_watch.csv (法說會日曆用)
來源: yfinance calendar(Yahoo)。日股穩定、韓股偶有過期日期故只留未來日。
範圍: 最新快照各市場成交金額前100名。陸股Yahoo無資料，需另尋交易所披露預約表。
用法: python fetch_earnings_dates.py   (每週或財報季前跑)
"""
import csv
import sqlite3
import sys
import time
from datetime import date, timedelta

import yfinance as yf

sys.path.insert(0, ".")
from backfill_history import ticker_variants

DB = "capital_flow.db"
OUT = "jp_kr_earnings_watch.csv"
TOP_N = 100
HORIZON = 90   # 只留未來90天內


def main():
    conn = sqlite3.connect(DB)
    latest = conn.execute("SELECT MAX(snapshot_date) FROM rankings").fetchone()[0]
    rows_out = []
    today = date.today()
    for market in ("日", "韓"):
        plan = conn.execute(
            """SELECT r.code, r.rank, COALESCE(n.name_zh, r.name), COALESCE(c.main_group,'')
               FROM rankings r
               LEFT JOIN company_names n ON n.country=r.country AND n.code=r.code
               LEFT JOIN classification c ON c.country=r.country AND c.code=r.code
               WHERE r.snapshot_date=? AND r.country=? AND r.rank<=?
               GROUP BY r.code""", (latest, market, TOP_N)).fetchall()
        got = 0
        for i, (code, rank, name, grp) in enumerate(plan):
            variants = ticker_variants(market, code)
            if not variants:
                continue
            for t in variants:
                try:
                    cal = yf.Ticker(t).calendar
                    eds = cal.get("Earnings Date") if isinstance(cal, dict) else None
                    if not eds:
                        continue
                    fut = [d for d in eds if today <= d <= today + timedelta(days=HORIZON)]
                    if fut:
                        rows_out.append((str(fut[0]), market, code, name or "", rank, grp))
                        got += 1
                    break
                except Exception:
                    time.sleep(3)
            time.sleep(0.5)
            if (i + 1) % 25 == 0:
                print(f"{market} 進度 {i+1}/{len(plan)}，取得 {got}")
        print(f"{market}: {got}/{len(plan)} 檔有未來財報日")
    # 累積進DB(財報日公告過就不會消失，供日後事件研究用)
    conn.execute("""CREATE TABLE IF NOT EXISTS earnings_dates (
        market TEXT, code TEXT, date TEXT, fetched TEXT,
        PRIMARY KEY (market, code, date))""")
    conn.executemany("INSERT OR IGNORE INTO earnings_dates VALUES (?,?,?,?)",
                     [(mk, c, d, str(today)) for d, mk, c, _n, _r, _g in rows_out])
    conn.commit()
    n = conn.execute("SELECT COUNT(*) FROM earnings_dates").fetchone()[0]
    conn.close()
    rows_out.sort()
    with open(OUT, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["日期", "市場", "代碼", "公司", "成交金額排名", "主族群"])
        w.writerows(rows_out)
    print(f"寫出 {OUT}: {len(rows_out)} 筆；DB earnings_dates 累積 {n} 筆")


if __name__ == "__main__":
    main()
