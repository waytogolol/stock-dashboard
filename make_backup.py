# -*- coding: utf-8 -*-
"""產生備份用精簡DB: git備份只留「不可重建的小表」(rankings歷史/tdcc_holders官方無archive/
分類/財報日曆/pledge/disposition/tx_5min等), 守住GitHub 100MB限制。
排除的大表分兩類, 皆由 make_cold_backup.py 的冷備zip(冷備/資料夾→使用者上傳Google雲端)承接:
  可重爬: inst_flow/margin_flow(TWSE) + fm_daily_price/fm_income/fm_cashflow/fm_month_rev(FinMind)
  Backer限定(8/15後拿不回): tdcc_weekly/cb_overview/cb_daily/cb_inst
  (cb_info/cb_purpose/margin_maintenance_official極小,git備份與冷備雙保留)
用法: python make_backup.py  -> db_backup/capital_flow.db
"""
import os
import sqlite3

SKIP = {"inst_flow", "margin_flow",
        "fm_daily_price", "fm_income", "fm_cashflow", "fm_month_rev",
        "tdcc_weekly", "cb_overview", "cb_daily", "cb_inst"}
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
