# -*- coding: utf-8 -*-
"""上櫃逐股融資餘額(TPEX margin/balance逐股列) -> margin_flow_otc
背景: 2026-07-29個股融資橫斷面考卷「④上櫃pass兩市對照」——上市margin_flow有2022起逐股,
     上櫃TPEX API每天都在打(維持率公式版)但只存ratio/summary,本腳本存逐股融資欄。
     窗=2022-01起(與上市margin_flow同窗,兩市對照口徑一致;更深歷史API有到2011,
     但DB備份逼近95MB上限,先不吃==要加深時改START重跑即可)。
欄位: fin_bal=資餘額(張)/fin_use=資使用率%/fin_limit=資限額(張,=股本25%,上櫃市值代理)。
防呆: 回應date必須等於請求日(TPEX超深日期fallback教訓)。
用法: python fetch_margin_flow_otc.py                # 增量(新到舊,cap 350日)
      python fetch_margin_flow_otc.py --backfill     # 無上限
      python fetch_margin_flow_otc.py --range A B    # 平行工人
      加 --fast = 1秒限速。
"""
import sqlite3
import sys
import time

import requests

sys.stdout.reconfigure(encoding="utf-8")
DB = "capital_flow.db"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
SLEEP = 3.0
START = "2022-01-01"

DDL = ("CREATE TABLE IF NOT EXISTS margin_flow_otc("
       "date TEXT, code TEXT, fin_bal REAL, fin_use REAL, fin_limit REAL, "
       "PRIMARY KEY(date, code))")


def roc(d):
    y, m, dd = d.split("-")
    return f"{int(y) - 1911}/{m}/{dd}"


def _f(x):
    try:
        return float(str(x).replace(",", ""))
    except (ValueError, TypeError):
        return None


def fetch_day(d):
    r = requests.get("https://www.tpex.org.tw/www/zh-tw/margin/balance",
                     params={"date": roc(d), "response": "json"}, headers=UA, timeout=30)
    j = r.json()
    if str(j.get("date", "")).replace("/", "").replace("-", "") != d.replace("-", ""):
        return None
    tbs = j.get("tables") or []
    if not tbs:
        return None
    rows = []
    for row in tbs[0].get("data") or []:
        if len(row) < 10:
            continue
        code = str(row[0]).strip()
        rows.append((d, code, _f(row[6]), _f(row[8]), _f(row[9])))
    return rows or None


def run(no_cap, d_from=None, d_to=None):
    conn = sqlite3.connect(DB, timeout=120)
    conn.execute(DDL)
    have = {r[0] for r in conn.execute("SELECT DISTINCT date FROM margin_flow_otc")}
    days = [r[0] for r in conn.execute(
        "SELECT DISTINCT date FROM index_daily WHERE market='TAIEX' AND date>=? "
        "ORDER BY date DESC", (START,))]
    if d_from:
        days = [d for d in days if d_from <= d <= d_to]
    todo = [d for d in days if d not in have]
    if not todo:
        print("margin_flow_otc: 已最新")
        conn.close()
        return
    cap = len(todo) if no_cap else 350
    print(f"margin_flow_otc: 待補{len(todo)}日,本輪跑{min(cap, len(todo))}日")
    ok = 0
    for i, d in enumerate(todo[:cap]):
        try:
            rows = fetch_day(d)
        except Exception as e:
            print(f"  {d}: 例外 {str(e)[:60]}")
            rows = None
        if rows:
            conn.executemany("INSERT OR REPLACE INTO margin_flow_otc VALUES (?,?,?,?,?)", rows)
            conn.commit()
            ok += 1
        if (i + 1) % 100 == 0:
            print(f"  [{i + 1}/{min(cap, len(todo))}] 成功{ok}", flush=True)
        time.sleep(SLEEP)
    n, nd, lo, hi = conn.execute("SELECT COUNT(*), COUNT(DISTINCT date), MIN(date), MAX(date) "
                                 "FROM margin_flow_otc").fetchone()
    print(f"margin_flow_otc: 本輪+{ok}日, 表{lo}~{hi}共{nd}日{n:,}筆")
    conn.close()


def main():
    global SLEEP
    if "--fast" in sys.argv:
        SLEEP = 1.0
    if "--range" in sys.argv:
        i = sys.argv.index("--range")
        run(no_cap=True, d_from=sys.argv[i + 1], d_to=sys.argv[i + 2])
        return
    run(no_cap="--backfill" in sys.argv)


if __name__ == "__main__":
    main()
