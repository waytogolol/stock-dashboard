# -*- coding: utf-8 -*-
"""集保戶股權分散表(TDCC opendata, 週頻) -> tdcc_holders + tdcc_people 表
注意: 官方只提供當週快照、無歷史archive —— 每週必跑一次累積(排進每日/每週流程)
級距: 官方17級距(1=1-999股~15=1,000,001股以上,17=合計),15=千張大戶,14=800-1000張,13=600-800張
⚠2026-08-04修正既有bug: big600_pct原本只加總level14+15(=實際「800張以上」)漏了level13,
  跟tdcc_weekly.p600交叉比對證實(2330 2026-07-03一週,舊算法85.82=tdcc_weekly.p800,
  正確值應為86.76=tdcc_weekly.p600)。已修正公式(加回level13)+用tdcc_weekly.p600回填
  2013-01-31~2026-07-09重疊期間歷史值(1,368列);2026-07-17/07-24兩週因TDCC官方API只給當週
  快照無法逆向取得已不再是「當週」的原始級距資料，維持舊值無法回補（07-31週已用修正後重跑更新）。
  影響評估: 全專案grep後確認big600_pct從未被其他任何研究/dashboard讀取(只有此檔寫入)，
  d4w訊號用的是p1000/big1000_pct(從未受影響)，600+張相關研究(如build_dormant_awakening_
  pattern.py)本來就直接讀tdcc_weekly.p600而非此欄位，故此bug對既有研究結論零影響，不需重跑。
存: tdcc_holders=千張大戶持股%/>600張持股%(已修正)/千張大戶人數/總股東人數
    tdcc_people=各級距「人數」面(2026-08-04新增,同一次請求順便補寫,零額外網路成本):
    n600/n800/n1000=持股>600/800/1000張的股東人數合計(級距13+14+15/14+15/15累加)，
    n_retail=<=10,000股(<10張)人數合計(級距1+2+3)，n_total=合計列人數，
    口徑與已停用的抓取/fetch_tdcc_people.py(FinMind版，2013-01~2026-07-24歷史已backfill)一致，
    此後由本腳本接手逐週累積，不用再手動另外跑那支1.5小時的FinMind腳本。
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

lv13 = df[df.level == 13].set_index("code")     # 600,001-800,000股
lv14 = df[df.level == 14].set_index("code")     # 800,001-1,000,000股
lv15 = df[df.level == 15].set_index("code")     # 1,000,001股以上(千張大戶)
lv17 = df[df.level == 17].set_index("code")     # 合計
codes = lv17.index
rows = []
for code in codes:
    p15 = float(lv15.pct.get(code, 0) or 0)
    p14 = float(lv14.pct.get(code, 0) or 0)
    p13 = float(lv13.pct.get(code, 0) or 0)
    rows.append((dt_iso, code.strip(), round(p15, 2), round(p15 + p14 + p13, 2),
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

# ----- tdcc_people(人數面,同一份df順便補寫,不用再跑舊版FinMind腳本) -----
lv1 = df[df.level == 1].set_index("code")
lv2 = df[df.level == 2].set_index("code")
lv3 = df[df.level == 3].set_index("code")


def h(lv, code):
    return int(lv.holders.get(code, 0) or 0)


people_rows = []
for code in codes:
    n1000 = h(lv15, code)
    n800 = n1000 + h(lv14, code)
    n600 = n800 + h(lv13, code)
    n_retail = h(lv1, code) + h(lv2, code) + h(lv3, code)
    n_total = h(lv17, code)
    people_rows.append((code.strip(), dt_iso, n600, n800, n1000, n_retail, n_total))
conn.execute("""CREATE TABLE IF NOT EXISTS tdcc_people(
    code TEXT, date TEXT, n600 INTEGER, n800 INTEGER, n1000 INTEGER,
    n_retail INTEGER, n_total INTEGER, PRIMARY KEY(code, date))""")
conn.executemany("INSERT OR REPLACE INTO tdcc_people VALUES(?,?,?,?,?,?,?)", people_rows)
conn.commit()
np_n = conn.execute("SELECT COUNT(*), COUNT(DISTINCT date) FROM tdcc_people").fetchone()
print(f"寫入 {len(people_rows):,} 檔 -> tdcc_people 累積 {np_n[0]:,} 筆 / {np_n[1]} 週")
conn.close()
