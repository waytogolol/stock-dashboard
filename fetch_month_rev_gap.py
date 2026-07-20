# -*- coding: utf-8 -*-
"""補抓fm_month_rev最新公告月缺漏的晚申報公司(FinMind收錄晚申報者有時差,每月10-15號後跑一次)。
背景: 2026-07-19發現漢唐等29檔6月營收缺漏→半導體設備題材卡在5月且score=4觸發被漏掉。
用法: python fetch_month_rev_gap.py (跑完重跑 python export_html.py 更新儀表板)"""
import sys
import time
import sqlite3

import requests

sys.stdout.reconfigure(encoding="utf-8")
TOKEN = open("finmind_token.txt").read().strip()
conn = sqlite3.connect("capital_flow.db")
latest, prev = [r[0] for r in conn.execute(
    "SELECT DISTINCT date FROM fm_month_rev ORDER BY date DESC LIMIT 2")]
missing = [r[0] for r in conn.execute(f"""
    SELECT DISTINCT code FROM fm_month_rev WHERE date='{prev}'
    AND code NOT IN (SELECT code FROM fm_month_rev WHERE date='{latest}')""")]
print(f"最新公告月{latest}: 對比{prev}缺{len(missing)}檔 → 補抓")
ok = still = 0
for i, code in enumerate(missing):
    r = requests.get("https://api.finmindtrade.com/api/v4/data",
                     params={"dataset": "TaiwanStockMonthRevenue", "data_id": code,
                             "start_date": prev, "end_date": str(__import__("datetime").date.today()),
                             "token": TOKEN}, timeout=40)
    data = r.json().get("data", [])
    rows = [(code, d["date"], d.get("revenue")) for d in data if d["date"] == latest]
    if rows:
        conn.executemany("INSERT OR REPLACE INTO fm_month_rev VALUES (?,?,?)", rows)
        conn.commit()
        ok += 1
    else:
        still += 1
        print(f"  {code}: FinMind仍無2026-07資料")
    time.sleep(2.6)
n = conn.execute("SELECT COUNT(DISTINCT code) FROM fm_month_rev WHERE date=?", (latest,)).fetchone()[0]
print(f"補到{ok}檔/仍缺{still}檔; {latest}公告月現有{n}檔")
conn.close()
