# -*- coding: utf-8 -*-
"""抓微題材台股成員的季度毛利率歷史 -> DB margin_history 表
來源: yfinance quarterly_income_stmt(近4-5季) + MOPS官方最新季(tw_quarterly_fin，同季覆蓋yf)
用法: python fetch_micro_margins.py   (每季財報後跑一次)
"""
import sqlite3
import time
from datetime import date

import pandas as pd
import yfinance as yf

from micro_themes import MICRO_THEMES

DB = "capital_flow.db"

conn = sqlite3.connect(DB)
subp = pd.read_sql("SELECT DISTINCT code, sub_product FROM classification WHERE country='台'", conn)

codes = set()
for name, cfg in MICRO_THEMES.items():
    kws, excl = cfg["kws"], set(cfg.get("exclude", []))
    mask = subp["sub_product"].fillna("").apply(lambda t: any(k.lower() in t.lower() for k in kws))
    codes |= set(subp[mask]["code"]) - excl
codes = sorted(codes)
print(f"微題材成員共 {len(codes)} 檔")

rows = []
today = str(date.today())
fail = []
for i, code in enumerate(codes):
    got = False
    for suffix in (".TW", ".TWO"):
        try:
            q = yf.Ticker(code + suffix).quarterly_income_stmt
            if q is None or q.empty:
                continue
            gp = q.loc["Gross Profit"] if "Gross Profit" in q.index else None
            rev = q.loc["Total Revenue"] if "Total Revenue" in q.index else None
            if gp is None and rev is not None and "Cost Of Revenue" in q.index:
                gp = rev - q.loc["Cost Of Revenue"]
            if gp is None or rev is None:
                continue
            gm = (gp / rev * 100).dropna()
            for d, v in gm.items():
                quarter = f"{d.year}Q{(d.month - 1) // 3 + 1}"
                rows.append((code, quarter, round(float(v), 2), "yf", today))
            got = True
            break
        except Exception:
            time.sleep(5)
    if not got:
        fail.append(code)
    time.sleep(0.6)
    if (i + 1) % 20 == 0:
        print(f"進度 {i+1}/{len(codes)}")

conn.execute("""CREATE TABLE IF NOT EXISTS margin_history (
    code TEXT, quarter TEXT, gm REAL, src TEXT, updated TEXT, PRIMARY KEY (code, quarter))""")
conn.executemany("INSERT OR REPLACE INTO margin_history VALUES (?,?,?,?,?)", rows)

# 官方最新季覆蓋(同季以MOPS為準)；民國年季 -> 西元
try:
    off = pd.read_sql("SELECT code, quarter, gross_margin FROM tw_quarterly_fin", conn)
    off_rows = []
    for _, r in off.iterrows():
        if r["code"] not in codes or pd.isna(r["gross_margin"]):
            continue
        yr, s = r["quarter"].split("Q")
        off_rows.append((r["code"], f"{int(yr) + 1911}Q{s}", round(r["gross_margin"], 2), "mops", today))
    conn.executemany("INSERT OR REPLACE INTO margin_history VALUES (?,?,?,?,?)", off_rows)
    print(f"官方季資料覆蓋 {len(off_rows)} 筆")
except Exception as e:
    print(f"官方覆蓋略過: {e}")

conn.commit()
n = conn.execute("SELECT COUNT(*), COUNT(DISTINCT code) FROM margin_history").fetchone()
conn.close()
print(f"margin_history: {n[0]} 筆 / {n[1]} 檔；yf無資料 {len(fail)} 檔: {','.join(fail)}")
