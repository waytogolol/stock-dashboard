# -*- coding: utf-8 -*-
"""產生備份用精簡DB: 排除可重爬的大表(inst_flow/margin_flow 各~80-110MB, TWSE可重抓)
保留不可重建資料: rankings歷史/tdcc_holders(官方無archive!)/分類/FinMind/財報日曆等
用法: python make_backup.py  -> db_backup/capital_flow.db
"""
import os
import sqlite3

SKIP = {"inst_flow", "margin_flow"}
SRC = "capital_flow.db"
DST = os.path.join("db_backup", "capital_flow.db")

if os.path.exists(DST):
    os.remove(DST)
src = sqlite3.connect(SRC)
src.execute("ATTACH DATABASE ? AS bk", (DST,))
tables = [r[0] for r in src.execute(
    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
kept = 0
for t in tables:
    if t in SKIP:
        continue
    src.execute(f'CREATE TABLE bk."{t}" AS SELECT * FROM main."{t}"')
    kept += 1
src.commit()
src.close()
mb = os.path.getsize(DST) / 1e6
print(f"備份DB: {kept} 表 (排除 {sorted(SKIP)}), {mb:.1f} MB")
if mb > 95:
    raise SystemExit("備份仍超過95MB, 需再排除表!")
