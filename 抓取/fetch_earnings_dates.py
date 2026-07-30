# -*- coding: utf-8 -*-
"""抓日/韓/陸股財報公布日期 -> jp_kr_earnings_watch.csv (法說會日曆用)
來源: 日韓=yfinance calendar(Yahoo，韓股偶有過期日期故只留未來日)
      陸股=東方財富數據中心披露預約API(整批JSON，單次低頻請求，非逐檔爬蟲)
範圍: 最新快照各市場成交金額前100名，未來90天內。
用法: python fetch_earnings_dates.py   (每週或財報季前跑)
"""
import csv
import sqlite3
import sys
import time
from datetime import date, timedelta

import requests
import yfinance as yf

sys.path.insert(0, ".")
from backfill_history import ticker_variants

DB = "capital_flow.db"
OUT = "jp_kr_earnings_watch.csv"
TOP_N = 100
HORIZON = 90   # 只留未來90天內
EM_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
         "Referer": "https://data.eastmoney.com/"}


def cn_effective_date(d):
    """實際發布日 > 最新變更日 > 首次預約日"""
    for k in ("ACTUAL_PUBLISH_DATE", "THIRD_CHANGE_DATE", "SECOND_CHANGE_DATE",
              "FIRST_CHANGE_DATE", "FIRST_APPOINT_DATE"):
        if d.get(k):
            return str(d[k])[:10]
    return None


def fetch_cn_period(report_date, sleep=1.2):
    """抓一個財報期的全部披露時程(分頁整批)，回傳 {代碼: (生效日, 市場前綴)}"""
    out = {}
    page = 1
    while True:
        url = ("https://datacenter-web.eastmoney.com/api/data/v1/get"
               "?reportName=RPT_PUBLIC_BS_APPOIN&columns=ALL&pageSize=500"
               f"&pageNumber={page}&filter=(REPORT_DATE%3D'{report_date}')")
        r = requests.get(url, headers=EM_UA, timeout=30)
        r.raise_for_status()
        res = (r.json() or {}).get("result") or {}
        data = res.get("data") or []
        if not data:
            break
        for d in data:
            eff = cn_effective_date(d)
            mkt = d.get("TRADE_MARKET") or ""
            pfx = "sh" if "上交所" in mkt else ("sz" if "深交所" in mkt else None)
            if eff and pfx:
                out[pfx + str(d["SECURITY_CODE"])] = eff
        if page * 500 >= (res.get("count") or 0):
            break
        page += 1
        time.sleep(sleep)
    return out


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

    # 陸股：東方財富披露預約(當前財報期整批)，取前100大且日期在未來90天內
    try:
        cn_plan = conn.execute(
            """SELECT r.code, r.rank, COALESCE(n.name_zh, r.name), COALESCE(c.main_group,'')
               FROM rankings r
               LEFT JOIN company_names n ON n.country=r.country AND n.code=r.code
               LEFT JOIN classification c ON c.country=r.country AND c.code=r.code
               WHERE r.snapshot_date=? AND r.country='陸' AND r.rank<=?
               GROUP BY r.code""", (latest, TOP_N)).fetchall()
        # 當前季報期：依月份推(7-9月抓半年報6/30、10-12月抓Q3、1-4月抓年報、5-6月抓Q1)
        mth = today.month
        rp = {7: "-06-30", 8: "-06-30", 9: "-09-30", 10: "-09-30", 11: "-09-30", 12: "-12-31",
              1: f"", 2: "", 3: "", 4: "", 5: "-03-31", 6: "-03-31"}[mth]
        report_date = f"{today.year}{rp}" if rp else f"{today.year - 1}-12-31"
        cn_dates = fetch_cn_period(report_date)
        got = 0
        for code, rank, name, grp in cn_plan:
            eff = cn_dates.get(code)
            if not eff:
                continue
            try:
                d = date.fromisoformat(eff)
            except ValueError:
                continue
            if today <= d <= today + timedelta(days=HORIZON):
                rows_out.append((eff, "陸", code, name or "", rank, grp))
                got += 1
        print(f"陸: {got}/{len(cn_plan)} 檔有未來披露日(財報期{report_date})")
    except Exception as e:
        print(f"陸股披露預約抓取失敗(不影響日韓): {e}")

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
