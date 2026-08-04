# -*- coding: utf-8 -*-
"""FinMind 台股歷史季度資產負債表+現金流量表 -> capital_flow.db (tw_quarterly_balance_cashflow_history)
動機(2026-08-04使用者提案,接續fetch_gross_margin_history.py的損益表擴大版): 使用者追問合約負債
  (前瞻性訂單指標)/存貨周轉(earnings quality訊號)/現金流量(應計異常accrual anomaly,Sloan 1996:
  現金流跟不上帳上淨利的公司後續報酬通常較差)/財務槓桿(呼應週級動能crash risk討論,高槓桿公司系統性
  重挫時可能摔更重)。這四項都不在TaiwanStockFinancialStatements(損益表)dataset裡，需另兩個獨立
  dataset分別打API，不是免費附帶取得，是本輪新增的API用量。
資料集: TaiwanStockBalanceSheet + TaiwanStockCashFlowsStatement(長格式: date/stock_id/type/value/
  origin_name)，兩個dataset對同一檔股票各自獨立呼叫(每檔2次API call，非1次)。
  ⚠已知資料缺口(2026-08-04實測4檔驗證,誠實記錄不要當成bug): CurrentContractLiabilities(合約負債)
  覆蓋率不完整——不是每家公司都在資產負債表單獨列示這個科目(部分公司併入其他流動負債)，實測1101台泥
  有此科目，2330/2317/3008皆無，屬公司揭露慣例差異非抓取失敗，下游研究須自行處理大量NULL。
欄位: 資產負債表取Inventories(存貨)/TotalAssets/Liabilities/Equity/CurrentAssets/CurrentLiabilities/
  CurrentContractLiabilities(合約負債,覆蓋率低)/AccountsReceivableNet(應收帳款，順便，質押/收現品質
  相關研究可能用得到)；現金流量表取CashFlowsFromOperatingActivities(營業活動淨現金流入，用於比較
  現金流賺的錢vs帳上淨利=應計異常代理)/Depreciation(折舊，非現金費用，供還原用)。
  leverage_ratio = Liabilities / TotalAssets 直接算好存欄位，避免下游每次重算。
範圍/節流/斷點續傳邏輯同fetch_gross_margin_history.py，共用同一份流動性股票池定義(近20日均額>=0.3億)。
用法: python fetch_balance_cashflow_history.py           (流動性股票池全量抓取，中斷重跑會續傳)
      python fetch_balance_cashflow_history.py --test     (只抓15檔驗證管線，不影響正式進度快取)
"""
import csv
import os
import pickle
import sqlite3
import sys
import time
from datetime import date

import requests

DB = "capital_flow.db"
DONE_CACHE = "快取/tmp_balance_cashflow_done.pkl"
TOKEN = open("finmind_token.txt").read().strip()
URL = "https://api.finmindtrade.com/api/v4/data"
START = "2013-01-01"
SLEEP = 2.6
LIQUIDITY_THRESHOLD = 0.3e8

BS_FIELDS = ("Inventories", "TotalAssets", "Liabilities", "Equity", "CurrentAssets",
             "CurrentLiabilities", "CurrentContractLiabilities", "AccountsReceivableNet")
CF_FIELDS = ("CashFlowsFromOperatingActivities", "Depreciation")


def universe():
    """近20個交易日均成交值>=0.3億的上市/上櫃四位數個股(同fetch_gross_margin_history.py口徑)。"""
    with open("tw_all_listed.csv", encoding="utf-8-sig") as f:
        listed = {row["code"] for row in csv.DictReader(f) if row["market"] in ("上市", "上櫃")}
    conn = sqlite3.connect(DB)
    last20 = [r[0] for r in conn.execute(
        "SELECT DISTINCT date FROM fm_daily_price ORDER BY date DESC LIMIT 20").fetchall()]
    qmarks = ",".join("?" * len(last20))
    rows = conn.execute(
        f"SELECT code, AVG(money) FROM fm_daily_price WHERE date IN ({qmarks}) "
        f"AND code GLOB '[0-9][0-9][0-9][0-9]' GROUP BY code", last20).fetchall()
    conn.close()
    liquid = {c for c, m in rows if m and m >= LIQUIDITY_THRESHOLD}
    return sorted(liquid & listed)


def fm_get(dataset, code):
    for attempt in range(4):
        try:
            r = requests.get(URL, params={"dataset": dataset, "data_id": code,
                                          "start_date": START, "end_date": str(date.today()),
                                          "token": TOKEN}, timeout=60)
            if r.status_code == 402:
                print(f"  額度限制,休息70s (attempt{attempt})", flush=True)
                time.sleep(70)
                continue
            j = r.json()
            if j.get("msg") != "success":
                print(f"  {code}/{dataset}: {j.get('msg')}", flush=True)
                time.sleep(20)
                continue
            return j.get("data") or []
        except Exception as e:
            print(f"  {code}/{dataset}: {type(e).__name__}, 重試", flush=True)
            time.sleep(15)
    return None


def to_rows(code, bs_data, cf_data):
    by_date = {}
    for d in (bs_data or []):
        if d.get("type") not in BS_FIELDS:
            continue
        by_date.setdefault(d["date"], {})[d["type"]] = d.get("value")
    for d in (cf_data or []):
        if d.get("type") not in CF_FIELDS:
            continue
        by_date.setdefault(d["date"], {})[d["type"]] = d.get("value")
    updated = str(date.today())
    rows = []
    for dt, vals in by_date.items():
        inv = vals.get("Inventories")
        ta = vals.get("TotalAssets")
        liab = vals.get("Liabilities")
        eq = vals.get("Equity")
        ca = vals.get("CurrentAssets")
        cl = vals.get("CurrentLiabilities")
        contract_liab = vals.get("CurrentContractLiabilities")
        ar = vals.get("AccountsReceivableNet")
        ocf = vals.get("CashFlowsFromOperatingActivities")
        dep = vals.get("Depreciation")
        leverage = (liab / ta) if (ta not in (None, 0) and liab is not None) else None
        current_ratio = (ca / cl) if (cl not in (None, 0) and ca is not None) else None
        rows.append((code, dt, inv, ta, liab, eq, ca, cl, contract_liab, ar,
                     leverage, current_ratio, ocf, dep, updated))
    return rows


def main():
    test = "--test" in sys.argv
    con = sqlite3.connect(DB, timeout=60)
    con.execute("""CREATE TABLE IF NOT EXISTS tw_quarterly_balance_cashflow_history(
        code TEXT, date TEXT, inventories REAL, total_assets REAL, liabilities REAL, equity REAL,
        current_assets REAL, current_liabilities REAL, contract_liabilities REAL,
        accounts_receivable REAL, leverage_ratio REAL, current_ratio REAL,
        operating_cash_flow REAL, depreciation REAL, updated TEXT, PRIMARY KEY(code, date))""")
    done = set()
    if os.path.exists(DONE_CACHE) and not test:
        with open(DONE_CACHE, "rb") as f:
            done = pickle.load(f)
    codes = universe()
    todo = [c for c in codes if c not in done]
    if test:
        todo = todo[:15]
    print(f"流動性股票池{len(codes)}檔, 已完成{len(done)}, 待抓{len(todo)}"
          f" (預估{len(todo) * SLEEP * 2 / 3600:.1f}hr,每檔2次API call)", flush=True)
    n_rows = 0
    for i, code in enumerate(todo):
        bs_data = fm_get("TaiwanStockBalanceSheet", code)
        time.sleep(SLEEP)
        cf_data = fm_get("TaiwanStockCashFlowsStatement", code)
        if bs_data is None and cf_data is None:
            print(f"  {code}: 連續失敗跳過(未記done,下次續傳重試)", flush=True)
            time.sleep(SLEEP)
            continue
        rows = to_rows(code, bs_data, cf_data)
        con.executemany(
            "INSERT OR REPLACE INTO tw_quarterly_balance_cashflow_history "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        con.commit()
        n_rows += len(rows)
        if not test:
            done.add(code)
            with open(DONE_CACHE, "wb") as f:
                pickle.dump(done, f)
        if i % 50 == 0 or test:
            print(f"[{i + 1}/{len(todo)}] {code}: {len(rows)}季 (本次累計{n_rows:,}筆)", flush=True)
        time.sleep(SLEEP)
    n = con.execute("SELECT COUNT(*), COUNT(DISTINCT code), MIN(date), MAX(date), "
                    "COUNT(contract_liabilities) FROM tw_quarterly_balance_cashflow_history").fetchone()
    print(f"完成: tw_quarterly_balance_cashflow_history {n[0]:,}筆 / {n[1]}檔 / {n[2]}~{n[3]} "
          f"/ 合約負債非空{n[4]:,}筆({n[4]/max(n[0],1):.1%})", flush=True)
    con.close()


if __name__ == "__main__":
    main()
