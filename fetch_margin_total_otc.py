# -*- coding: utf-8 -*-
"""上櫃全市場融資融券彙總(TPEX margin/balance summary) -> margin_total_otc
背景: 2026-07-29融資殺出/量能考卷需要上櫃融資金額歷史(E3上市×上櫃2×2),
     otc_calc_day每天有打同一endpoint但只存維持率ratio——本腳本存summary三列全欄位。
資料: 融資(張)/融資金(仟元)/融券(張)各自的 前日餘額/買進/賣出/現償/今日餘額。
     API深度與margin/balance逐股相同(2011-01起),防呆=回應date必須等於請求日
     (TPEX對超深日期會fallback回傳最新日,見fetch_margin_maintenance.py教訓)。
用法: python fetch_margin_total_otc.py                # 增量(新到舊,cap 350日,入update_all)
      python fetch_margin_total_otc.py --backfill     # 不設上限一次補完
      python fetch_margin_total_otc.py --range A B    # 平行回補工人(日期段,無上限)
      加 --fast = 1秒限速(回補衝刺);例行預設3秒禮貌限速。
"""
import sqlite3
import sys
import time

import requests

sys.stdout.reconfigure(encoding="utf-8")
DB = "capital_flow.db"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
SLEEP = 3.0
START = "2011-01-01"  # TPEX API實測深度斷點(與margin/balance逐股同源)

DDL = """CREATE TABLE IF NOT EXISTS margin_total_otc(
    date TEXT PRIMARY KEY,
    fin_yes_vol REAL, fin_buy_vol REAL, fin_sell_vol REAL, fin_repay_vol REAL, fin_today_vol REAL,
    money_yes REAL, money_buy REAL, money_sell REAL, money_repay REAL, money_today REAL,
    short_yes REAL, short_sell REAL, short_buy REAL, short_repay REAL, short_today REAL)"""


def roc(d):
    y, m, dd = d.split("-")
    return f"{int(y) - 1911}/{m}/{dd}"


def _f(x):
    try:
        return float(str(x).replace(",", ""))
    except (ValueError, TypeError):
        return None


def fetch_day(d):
    """回傳16欄tuple或None。融券欄序=前日/賣出/買進/現償/今日(空頭方向)。"""
    r = requests.get("https://www.tpex.org.tw/www/zh-tw/margin/balance",
                     params={"date": roc(d), "response": "json"}, headers=UA, timeout=30)
    j = r.json()
    if str(j.get("date", "")).replace("/", "").replace("-", "") != d.replace("-", ""):
        return None
    tbs = j.get("tables") or []
    if not tbs:
        return None
    fin = money = None
    for row in tbs[0].get("summary") or []:
        if len(row) < 15:
            continue
        name = str(row[1])
        if name.startswith("合計"):
            fin = row
        elif name.startswith("融資金"):
            money = row
    if fin is None or money is None:
        return None
    return (d,
            _f(fin[2]), _f(fin[3]), _f(fin[4]), _f(fin[5]), _f(fin[6]),
            _f(money[2]), _f(money[3]), _f(money[4]), _f(money[5]), _f(money[6]),
            _f(fin[10]), _f(fin[11]), _f(fin[12]), _f(fin[13]), _f(fin[14]))


def run(no_cap, d_from=None, d_to=None):
    conn = sqlite3.connect(DB, timeout=120)  # 平行工人+讀端並存,鎖等待要長
    conn.execute(DDL)
    have = {r[0] for r in conn.execute("SELECT date FROM margin_total_otc")}
    days = [r[0] for r in conn.execute(
        "SELECT DISTINCT date FROM index_daily WHERE market='TAIEX' AND date>=? "
        "ORDER BY date DESC", (START,))]
    if d_from:
        days = [d for d in days if d_from <= d <= d_to]
    todo = [d for d in days if d not in have]
    if not todo:
        print("margin_total_otc: 已最新")
        conn.close()
        return
    cap = len(todo) if no_cap else 350
    print(f"margin_total_otc: 待補{len(todo)}日,本輪跑{min(cap, len(todo))}日(新到舊,冪等可中斷)")
    ok = 0
    for i, d in enumerate(todo[:cap]):
        try:
            row = fetch_day(d)
        except Exception as e:
            print(f"  {d}: 例外 {str(e)[:60]}")
            row = None
        if row is not None:
            conn.execute("INSERT OR REPLACE INTO margin_total_otc VALUES "
                         "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", row)
            conn.commit()
            ok += 1
        if (i + 1) % 100 == 0:
            print(f"  [{i + 1}/{min(cap, len(todo))}] 成功{ok}", flush=True)
        time.sleep(SLEEP)
    lo, hi, n = conn.execute(
        "SELECT MIN(date), MAX(date), COUNT(*) FROM margin_total_otc").fetchone()
    print(f"margin_total_otc: 本輪+{ok}日, 表{lo}~{hi}共{n:,}筆")
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
