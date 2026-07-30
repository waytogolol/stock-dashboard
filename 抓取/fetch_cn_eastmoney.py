# -*- coding: utf-8 -*-
"""東方財富數據中心 -> DB：陸股 業績預告/業績快報/機構調研月統計
整批JSON分頁、低頻請求(1.2s間隔)，非逐檔爬蟲。每月或每季跑一次。
表: cn_forecast / cn_flash / cn_survey
"""
import sqlite3
import time
from datetime import date

import requests

DB = "capital_flow.db"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
      "Referer": "https://data.eastmoney.com/"}
PERIODS = ["2025-06-30", "2025-09-30", "2025-12-31", "2026-03-31", "2026-06-30"]


def em_pages(report, flt, sleep=1.2, max_pages=250):
    page = 1
    while True:
        url = ("https://datacenter-web.eastmoney.com/api/data/v1/get"
               f"?reportName={report}&columns=ALL&pageSize=500&pageNumber={page}"
               + (f"&filter={flt}" if flt else ""))
        r = requests.get(url, headers=UA, timeout=30)
        r.raise_for_status()
        res = (r.json() or {}).get("result") or {}
        data = res.get("data") or []
        if not data:
            return
        for d in data:
            yield d
        if page * 500 >= (res.get("count") or 0) or page >= max_pages:
            return
        page += 1
        time.sleep(sleep)


def pfx_code(d):
    """SECUCODE '603992.SH' -> 'sh603992'；北交所回傳None跳過"""
    sc = d.get("SECUCODE") or ""
    if sc.endswith(".SH"):
        return "sh" + sc[:-3]
    if sc.endswith(".SZ"):
        return "sz" + sc[:-3]
    return None


def main():
    conn = sqlite3.connect(DB)
    cn_codes = set(c for (c,) in conn.execute(
        "SELECT DISTINCT code FROM rankings WHERE country='陸'"))
    today = str(date.today())
    print(f"陸股宇宙 {len(cn_codes)} 檔")

    # 業績預告
    conn.execute("""CREATE TABLE IF NOT EXISTS cn_forecast (
        code TEXT, report_date TEXT, notice_date TEXT, predict_type TEXT,
        amp_lower REAL, amp_upper REAL, reason TEXT, fetched TEXT,
        PRIMARY KEY (code, report_date, notice_date))""")
    rows = []
    for rp in PERIODS:
        n0 = len(rows)
        for d in em_pages("RPT_PUBLIC_OP_NEWPREDICT", f"(REPORT_DATE%3D'{rp}')"):
            c = pfx_code(d)
            if c not in cn_codes:
                continue
            rows.append((c, rp, str(d.get("NOTICE_DATE"))[:10], d.get("PREDICT_TYPE"),
                         d.get("ADD_AMP_LOWER"), d.get("ADD_AMP_UPPER"),
                         (d.get("CHANGE_REASON_EXPLAIN") or "")[:200], today))
        print(f"業績預告 {rp}: +{len(rows) - n0}")
        time.sleep(2)
    conn.executemany("INSERT OR REPLACE INTO cn_forecast VALUES (?,?,?,?,?,?,?,?)", rows)
    conn.commit()

    # 業績快報
    conn.execute("""CREATE TABLE IF NOT EXISTS cn_flash (
        code TEXT, report_date TEXT, rev REAL, rev_yoy REAL,
        np REAL, np_yoy REAL, eps REAL, notice_date TEXT, fetched TEXT,
        PRIMARY KEY (code, report_date))""")
    rows = []
    for rp in PERIODS:
        n0 = len(rows)
        for d in em_pages("RPT_FCI_PERFORMANCEE", f"(REPORT_DATE%3D'{rp}')"):
            c = pfx_code(d)
            if c not in cn_codes:
                continue
            rows.append((c, rp, d.get("TOTAL_OPERATE_INCOME"), d.get("YSTZ"),
                         d.get("PARENT_NETPROFIT"), d.get("JLRTBZCL"), d.get("BASIC_EPS"),
                         str(d.get("NOTICE_DATE") or d.get("UPDATE_DATE"))[:10], today))
        print(f"業績快報 {rp}: +{len(rows) - n0}")
        time.sleep(2)
    conn.executemany("INSERT OR REPLACE INTO cn_flash VALUES (?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()

    # 機構調研(聚合成 每股×每月 場次/機構家數)
    # 首跑抓近12個月；之後增量=只抓「已有資料最新月的前一月」起(當月與前月重抓覆蓋)
    conn.execute("""CREATE TABLE IF NOT EXISTS cn_survey (
        code TEXT, month TEXT, n INTEGER, orgs INTEGER, fetched TEXT,
        PRIMARY KEY (code, month))""")
    agg = {}
    last_m = conn.execute("SELECT MAX(month) FROM cn_survey").fetchone()[0]
    if last_m:
        y, m = int(last_m[:4]), int(last_m[5:7])
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
        since = f"{y}-{m:02d}-01"
    else:
        since = f"{date.today().year - 1}-{date.today().month:02d}-01"
    print(f"調研抓取起始日: {since}")
    for d in em_pages("RPT_ORG_SURVEYNEW", f"(NOTICE_DATE%3E%3D'{since}')"):
        c = pfx_code(d)
        if c not in cn_codes:
            continue
        m = str(d.get("NOTICE_DATE"))[:7]
        k = (c, m)
        a = agg.setdefault(k, [0, 0])
        a[0] += 1
        try:
            a[1] += int(d.get("NUM") or 0)
        except (ValueError, TypeError):
            pass
    conn.executemany("INSERT OR REPLACE INTO cn_survey VALUES (?,?,?,?,?)",
                     [(c, m, v[0], v[1], today) for (c, m), v in agg.items()])
    conn.commit()
    print(f"機構調研: {len(agg)} 檔×月")

    for t in ("cn_forecast", "cn_flash", "cn_survey"):
        print(t, conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0])
    conn.close()


if __name__ == "__main__":
    main()
