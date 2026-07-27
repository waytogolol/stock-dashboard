# -*- coding: utf-8 -*-
"""FinMind 個股PER/PBR/殖利率 歷史回補+例行增量 -> capital_flow.db (per_daily)
背景: 2026-07-27使用者提案估值研究線(機制假說=法人PE先行上調→營收後至/過熱找低PE有營收潛力/
     修正到合理PE介入;路徑=題材PE位階→個股,結合題材營收動能1-2月週期)。
模式: 整市場按日一刀(~1,970檔/刀,實測免費層可用;data_id模式反而一檔一刀較貴)。
     交易日曆=fm_daily_price實際日期(不浪費假日請求);斷點=per_done_days表(冪等可中斷)。
範圍: 2018-01-01起(與注意股/處置8年研究窗一致)。回補後每次重跑只補缺的新交易日=例行友善。
用法: python fetch_per.py
"""
import sqlite3
import sys
import time

import requests

sys.stdout.reconfigure(encoding="utf-8")
DB = "capital_flow.db"
TOKEN = open("finmind_token.txt").read().strip()
START = "2018-01-01"
SLEEP = 2.6
URL = "https://api.finmindtrade.com/api/v4/data"


def fetch_day(day):
    for attempt in range(3):
        try:
            r = requests.get(URL, params={"dataset": "TaiwanStockPER", "start_date": day,
                                          "end_date": day, "token": TOKEN}, timeout=60)
            j = r.json()
            if j.get("status") == 200:
                return j.get("data", [])
            if "quota" in str(j.get("msg", "")).lower() or j.get("status") == 402:
                print(f"  {day}: 配額用盡,睡5分鐘後重試({j.get('msg')})", flush=True)
                time.sleep(300)
                continue
            return None
        except Exception as e:
            print(f"  {day}: 請求例外 {e} (重試{attempt + 1}/3)", flush=True)
            time.sleep(30)
    return None


def main():
    conn = sqlite3.connect(DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS per_daily(
        date TEXT, code TEXT, per REAL, pbr REAL, dy REAL, PRIMARY KEY(date, code))""")
    conn.execute("CREATE TABLE IF NOT EXISTS per_done_days(day TEXT PRIMARY KEY)")
    days = [r[0] for r in conn.execute(
        "SELECT DISTINCT date FROM fm_daily_price WHERE date>=? ORDER BY date", (START,))]
    done = {r[0] for r in conn.execute("SELECT day FROM per_done_days")}
    todo = [d for d in days if d not in done]
    print(f"交易日 {len(days)},已完成 {len(done)},待抓 {len(todo)} (預估 {len(todo) * SLEEP / 60:.0f} 分鐘)",
          flush=True)
    fail = 0
    for i, day in enumerate(todo):
        data = fetch_day(day)
        if data is None:
            fail += 1
            time.sleep(SLEEP)
            continue
        conn.executemany("INSERT OR REPLACE INTO per_daily VALUES (?,?,?,?,?)",
                         [(d["date"], d["stock_id"], d.get("PER"), d.get("PBR"),
                           d.get("dividend_yield")) for d in data])
        conn.execute("INSERT OR REPLACE INTO per_done_days VALUES (?)", (day,))
        conn.commit()
        if (i + 1) % 50 == 0 or i == len(todo) - 1:
            n = conn.execute("SELECT COUNT(*) FROM per_daily").fetchone()[0]
            print(f"[{i + 1}/{len(todo)}] {day} 累計{n:,}筆 失敗{fail}", flush=True)
        time.sleep(SLEEP)
    n, nc, nd = conn.execute(
        "SELECT COUNT(*), COUNT(DISTINCT code), COUNT(DISTINCT date) FROM per_daily").fetchone()
    print(f"完成: per_daily {n:,}筆 / {nc}檔 / {nd}日 失敗{fail}", flush=True)
    conn.close()


if __name__ == "__main__":
    main()
