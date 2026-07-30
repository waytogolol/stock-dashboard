# -*- coding: utf-8 -*-
"""股本表(發行股數,雙市一刀) -> capital_flow.db (capital)
背景: 2026-07-29個股融資橫斷面設計時確認的三件事缺口——①個股市值(市值分層考卷)
     ②計時器v2款4/10(週轉率=成交股數/發行股數) ③上櫃個股市值(fin_limit代理只有上市)。
資料源: FinMind TaiwanStockShareholding(外資持股統計,日頻,含NumberOfSharesIssued發行股數),
     date模式一刀=上市+上櫃全部~2,360檔;2330核對=259.32億股,與margin_flow.fin_limit×4
     (融資限額=股本25%法規口徑)一致✓。順存外資持股比例(ForeignInvestmentSharesRatio)。
⚠8/15 Backer到期後若free tier拒絕: 備援=TWSE MI_QFIIS(上市)+TPEX qfii頁(上櫃),屆時擇一動工
     (股本變動頻率低,斷更數週無實害)。
用法: python fetch_capital.py              # 例行:抓最近一個交易日快照(1刀,入update_all週線組)
      python fetch_capital.py --backfill   # 月頻歷史回補(每月首個交易日,2013起,~160刀)
"""
import sqlite3
import sys
import time

import requests

sys.stdout.reconfigure(encoding="utf-8")
DB = "capital_flow.db"
URL = "https://api.finmindtrade.com/api/v4/data"
SLEEP = 3.0

DDL = ("CREATE TABLE IF NOT EXISTS capital("
       "date TEXT, code TEXT, shares REAL, foreign_pct REAL, "
       "PRIMARY KEY(date, code))")


def fetch_day(token, d):
    r = requests.get(URL, params={"dataset": "TaiwanStockShareholding",
                                  "start_date": d, "end_date": d, "token": token}, timeout=120)
    j = r.json()
    if j.get("status") != 200:
        print(f"  {d}: FinMind {j.get('status')} {str(j.get('msg'))[:60]}")
        return None
    return [(x["date"], x["stock_id"], x.get("NumberOfSharesIssued"),
             x.get("ForeignInvestmentSharesRatio")) for x in j.get("data", [])]


def main():
    token = open("finmind_token.txt").read().strip()
    conn = sqlite3.connect(DB, timeout=120)
    conn.execute(DDL)
    cal = [r[0] for r in conn.execute(
        "SELECT DISTINCT date FROM index_daily WHERE market='TAIEX' AND date>='2013-01-01' "
        "ORDER BY date")]
    if "--backfill" in sys.argv:
        # 每月首個交易日
        targets, seen = [], set()
        for d in cal:
            ym = d[:7]
            if ym not in seen:
                seen.add(ym)
                targets.append(d)
    else:
        targets = [cal[-1]]
    have = {r[0] for r in conn.execute("SELECT DISTINCT date FROM capital")}
    todo = [d for d in targets if d not in have]
    if not todo:
        print("capital: 已最新")
        conn.close()
        return
    print(f"capital: 待抓{len(todo)}個快照日")
    ok = 0
    for d in todo:
        rows = fetch_day(token, d)
        if rows:
            conn.executemany("INSERT OR REPLACE INTO capital VALUES (?,?,?,?)", rows)
            conn.commit()
            ok += 1
            print(f"  {d}: {len(rows)}檔")
        time.sleep(SLEEP)
    n, lo, hi = conn.execute("SELECT COUNT(*), MIN(date), MAX(date) FROM capital").fetchone()
    print(f"capital: +{ok}快照, 表{lo}~{hi}共{n:,}筆")
    conn.close()


if __name__ == "__main__":
    main()
