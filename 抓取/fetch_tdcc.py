# -*- coding: utf-8 -*-
"""集保戶股權分散表(TDCC opendata, 週頻) -> tdcc_holders 表
注意: 官方只提供當週快照、無歷史archive —— 每週必跑一次累積(排進每週流程)
級距: 15=1000張以上(千張大戶), 14=600-1000張; 「800張」為第三方切法官方無此級
存: 千張大戶持股%、>600張持股%、千張大戶人數、總股東人數
用法: python fetch_tdcc.py
"""
import io
import sqlite3

import pandas as pd
import requests

DB = "capital_flow.db"
URL = "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5"

r = requests.get(URL, timeout=120, headers={"User-Agent": "Mozilla/5.0"})
r.raise_for_status()
df = pd.read_csv(io.BytesIO(r.content), dtype=str)
df.columns = ["date", "code", "level", "holders", "shares", "pct"]
for c in ("holders", "shares", "pct"):
    df[c] = pd.to_numeric(df[c], errors="coerce")
df["level"] = pd.to_numeric(df["level"], errors="coerce")
dt = df["date"].iloc[0]
dt_iso = f"{dt[:4]}-{dt[4:6]}-{dt[6:]}"
print(f"資料日期 {dt_iso}, 原始 {len(df):,} 列")

lv15 = df[df.level == 15].set_index("code")
lv14 = df[df.level == 14].set_index("code")
lv17 = df[df.level == 17].set_index("code")     # 合計
codes = lv17.index
rows = []
for code in codes:
    p15 = float(lv15.pct.get(code, 0) or 0)
    p14 = float(lv14.pct.get(code, 0) or 0)
    rows.append((dt_iso, code.strip(), round(p15, 2), round(p15 + p14, 2),
                 int(lv15.holders.get(code, 0) or 0), int(lv17.holders.get(code, 0) or 0)))
conn = sqlite3.connect(DB)
conn.execute("""CREATE TABLE IF NOT EXISTS tdcc_holders (
    date TEXT, code TEXT, big1000_pct REAL, big600_pct REAL,
    big1000_n INTEGER, total_holders INTEGER, PRIMARY KEY (date, code))""")
conn.executemany("INSERT OR REPLACE INTO tdcc_holders VALUES (?,?,?,?,?,?)", rows)
conn.commit()
n = conn.execute("SELECT COUNT(*), COUNT(DISTINCT date) FROM tdcc_holders").fetchone()
print(f"寫入 {len(rows):,} 檔 -> tdcc_holders 累積 {n[0]:,} 筆 / {n[1]} 週")
for c in ("2330", "2408", "2327"):
    r2 = conn.execute("SELECT big1000_pct, big1000_n, total_holders FROM tdcc_holders "
                      "WHERE code=? AND date=?", (c, dt_iso)).fetchone()
    if r2:
        print(f"  {c}: 千張大戶 {r2[0]}% ({r2[1]}人) / 總股東 {r2[2]:,}")
