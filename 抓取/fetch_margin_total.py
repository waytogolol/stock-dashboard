# -*- coding: utf-8 -*-
"""全市場融資融券餘額(張數+金額) -> margin_total 表
背景: 2026-07-28深夜使用者提案「法人看回檔時融資殺出多少/量能放大多少=底部浮現」考卷,
     需要融資餘額金額日序列。FinMind TaiwanStockTotalMarginPurchaseShortSale(上市,Backer層)。
     實抓當日示範: 7/28融資餘額5,687億->5,455億=單日殺出232億(-4.1%),恐慌日投降進行式。
⚠8/15 Backer到期備援: TWSE MI_MARGN selectType=MS「信用交易統計」彙總=同數字,1請求/日,
  公式版fetch_margin_maintenance.py已有現成解析,屆時搬過來即可。
上櫃對應: FinMind無此數列;TPEX margin/balance summary融資金今日餘額(fetch_margin_maintenance
  的otc_calc_day已在抓但只存ratio),歷史需另跑一趟balance端點(--range四工人約16分),待裁示。
用法: python fetch_margin_total.py  (增量,首跑自2001回補全史)
"""
import sqlite3
import sys

import requests

sys.stdout.reconfigure(encoding="utf-8")
DB = "capital_flow.db"
TOKEN = open("finmind_token.txt").read().strip()
URL = "https://api.finmindtrade.com/api/v4/data"


def main():
    conn = sqlite3.connect(DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS margin_total(
        date TEXT, name TEXT, today_balance REAL, yes_balance REAL,
        buy REAL, sell REAL, repay REAL, PRIMARY KEY(date, name))""")
    last = conn.execute("SELECT MAX(date) FROM margin_total").fetchone()[0] or "2001-01-01"
    r = requests.get(URL, params={"dataset": "TaiwanStockTotalMarginPurchaseShortSale",
                                  "start_date": last, "token": TOKEN}, timeout=120)
    j = r.json()
    if j.get("status") != 200:
        print(f"API失敗: {j.get('status')} {str(j.get('msg'))[:60]} (8/15後改TWSE MS彙總,見docstring)")
        sys.exit(1)
    rows = [(d["date"], d["name"], d.get("TodayBalance"), d.get("YesBalance"),
             d.get("buy"), d.get("sell"), d.get("Return")) for d in j.get("data", [])]
    conn.executemany("INSERT OR REPLACE INTO margin_total VALUES (?,?,?,?,?,?,?)", rows)
    conn.commit()
    lo, hi, n = conn.execute("SELECT MIN(date), MAX(date), COUNT(*) FROM margin_total").fetchone()
    cur = conn.execute("SELECT today_balance FROM margin_total WHERE name='MarginPurchaseMoney' "
                       "ORDER BY date DESC LIMIT 1").fetchone()
    print(f"完成: {last}-> 表{lo}~{hi}共{n:,}筆; 最新融資餘額 {cur[0] / 1e8:,.0f}億")
    conn.close()


if __name__ == "__main__":
    main()
