# -*- coding: utf-8 -*-
"""產生冷備zip到 冷備/ 資料夾(使用者手動上傳Google雲端硬碟做離機保險)。
兩包分工:
  backer包   = Backer(8/15到期)後拿不回來的表 → 冷備_backer_YYYYMMDD.zip
  recrawl包  = 可重爬但很花時間的大表(git備份已排除) → 冷備_可重爬_YYYYMMDD.zip
同日已存在的zip會跳過(冪等);表結構=每表一個CSV,串流寫入不吃記憶體。
用法: python make_cold_backup.py   (建議大回補後或每月重跑一次)
還原: pandas.read_csv(zip內csv) → to_sql(表名, sqlite3.connect('capital_flow.db'))
"""
import csv
import datetime
import io
import os
import sqlite3
import sys
import zipfile

sys.stdout.reconfigure(encoding="utf-8")

GROUPS = {
    "backer": ["cb_info", "cb_overview", "cb_daily", "cb_inst", "cb_purpose",
               "margin_maintenance_official", "tdcc_weekly"],
    "可重爬": ["fm_daily_price", "fm_income", "fm_cashflow", "fm_month_rev",
               "inst_flow", "margin_flow"],
}
today = datetime.date.today().strftime("%Y%m%d")
os.makedirs("冷備", exist_ok=True)
conn = sqlite3.connect("capital_flow.db")

for gname, tables in GROUPS.items():
    zpath = os.path.join("冷備", f"冷備_{gname}_{today}.zip")
    if os.path.exists(zpath):
        print(f"{zpath} 已存在, 跳過")
        continue
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for t in tables:
            cur = conn.execute(f'SELECT * FROM "{t}"')
            cols = [d[0] for d in cur.description]
            n = 0
            with z.open(f"{t}.csv", "w") as raw, \
                    io.TextIOWrapper(raw, encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f)
                w.writerow(cols)
                for row in cur:
                    w.writerow(row)
                    n += 1
            print(f"  {t}: {n:,}筆")
    with zipfile.ZipFile(zpath) as z:
        bad = z.testzip()
    mb = os.path.getsize(zpath) / 1e6
    print(f"{zpath}: {mb:.1f} MB, 完整性{'FAIL:' + bad if bad else 'PASS'}")
conn.close()
