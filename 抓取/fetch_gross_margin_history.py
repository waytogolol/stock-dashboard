# -*- coding: utf-8 -*-
"""FinMind 台股歷史季度損益表科目 -> capital_flow.db (tw_quarterly_financials_history)
動機(2026-08-04使用者提案,原僅抓毛利率,同日擴大範圍): 既有毛利率資料只有capital_flow.db.fundamentals
  單一快照(810檔,快照日2026-07-08)+tw_quarterly_fin(1,924筆但全部是115Q1單一季),都無法做跨年度
  bootstrap/LOTO逐年檢驗。可行性查證確認: FinMind TaiwanStockFinancialStatements資料集(與
  fetch_finmind.py抓fm_income同一資料集)官方文件涵蓋1990-03-01~now,實測2330/1101等個股實際可回溯至
  2005~2013年，遠超過本專案regime穩健度檢驗最低門檻(需涵蓋2018年以前以跨過2022熊市)。fm_income表雖
  已有部分相關type，但範圍是「研究相關台股」窄宇宙(923檔)非流動性股票池，且history只到2017（受限
  fetch_finmind.py的START=2019-01-01附帶比較期間），故另建本表，用流動性股票池+更早的START重新抓取，
  不動既有fm_income/tw_quarterly_fin。
  2026-08-04同日擴大：原版只取Revenue/GrossProfit/CostOfGoodsSold三科目(第一輪跑到78/827檔時中止)，
  使用者追問「還有哪些有用的財報數據」，實測單次API回應本身就含17個type(單一dataset同一次請求)，
  多抓不必再多打API，故擴大到7個科目一次抓齊，避免之後為了新因子重複打整批API。使用者提到合約負債
  (有人會看的前瞻指標)/存貨周轉/現金流量不在此dataset(屬TaiwanStockBalanceSheet/
  TaiwanStockCashFlowsStatement，資產負債表與現金流量表是獨立dataset，需另開抓取，留作後續)。
資料集: TaiwanStockFinancialStatements(長格式: date/stock_id/type/value/origin_name)
  取7個原始科目：Revenue/GrossProfit/CostOfGoodsSold(毛利率用)/OperatingExpenses/OperatingIncome
  (營業利益率用)/PreTaxIncome/IncomeAfterTaxes(稅後淨利率用)/EPS/EquityAttributableToOwnersOfParent
  (母公司權益，可算簡易ROE=IncomeAfterTaxes/Equity，注意此為單季稅後淨利非TTM，season化需自行年化)。
  實測值均為當季單季數字(非累計YTD)，比率類欄位(gross_margin/operating_margin/net_margin)直接逐季
  計算，不需再做差分。
範圍: 近20日均成交值>=0.3億(本專案慣用流動性門檻，同fetch_margin_short_suspend.py精神)的上市/上櫃
  四位數個股，由fm_daily_price現算(非用現成清單，避免清單過期)。
節流: 每請求間隔2.6s(Backer額度1600/hr節流慣例，同fetch_daily_price.py/fetch_margin_short_suspend.py)
  ；斷點續傳 tmp_gross_margin_done.pkl；402退避重試。
用法: python fetch_gross_margin_history.py           (流動性股票池全量抓取，中斷重跑會續傳)
      python fetch_gross_margin_history.py --test     (只抓15檔驗證管線，不影響正式進度快取)
"""
import os
import pickle
import sqlite3
import sys
import time
from datetime import date

import requests

DB = "capital_flow.db"
DONE_CACHE = "快取/tmp_financials_done.pkl"
TOKEN = open("finmind_token.txt").read().strip()
URL = "https://api.finmindtrade.com/api/v4/data"
DATASET = "TaiwanStockFinancialStatements"
START = "2013-01-01"  # 台灣IFRS採用後(2013起)科目分類一致，且遠早於2018熊市檢驗門檻
SLEEP = 2.6
LIQUIDITY_THRESHOLD = 0.3e8  # 近20日均成交值>=0.3億
FIELDS = ("Revenue", "GrossProfit", "CostOfGoodsSold", "OperatingExpenses", "OperatingIncome",
          "PreTaxIncome", "IncomeAfterTaxes", "EPS", "EquityAttributableToOwnersOfParent")


def universe():
    """近20個交易日均成交值>=0.3億的上市/上櫃四位數個股(現算，同fetch_margin_short_suspend.py市場口徑)。"""
    import csv
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


def fm_get(code):
    for attempt in range(4):
        try:
            r = requests.get(URL, params={"dataset": DATASET, "data_id": code,
                                          "start_date": START, "end_date": str(date.today()),
                                          "token": TOKEN}, timeout=60)
            if r.status_code == 402:
                print(f"  額度限制,休息70s (attempt{attempt})", flush=True)
                time.sleep(70)
                continue
            j = r.json()
            if j.get("msg") != "success":
                print(f"  {code}: {j.get('msg')}", flush=True)
                time.sleep(20)
                continue
            return j.get("data") or []
        except Exception as e:
            print(f"  {code}: {type(e).__name__}, 重試", flush=True)
            time.sleep(15)
    return None  # 連續失敗,下次執行重試


def to_rows(code, data):
    """長格式(date/type/value) -> 寬格式一列一季，計算gross_margin/operating_margin/net_margin。"""
    by_date = {}
    for d in data:
        if d.get("type") not in FIELDS:
            continue
        by_date.setdefault(d["date"], {})[d["type"]] = d.get("value")
    updated = str(date.today())
    rows = []
    for dt, vals in by_date.items():
        rev = vals.get("Revenue")
        gp = vals.get("GrossProfit")
        cogs = vals.get("CostOfGoodsSold")
        opex = vals.get("OperatingExpenses")
        opinc = vals.get("OperatingIncome")
        pretax = vals.get("PreTaxIncome")
        niat = vals.get("IncomeAfterTaxes")
        eps = vals.get("EPS")
        equity = vals.get("EquityAttributableToOwnersOfParent")
        has_rev = rev not in (None, 0)
        gm = (gp / rev) if (has_rev and gp is not None) else None
        om = (opinc / rev) if (has_rev and opinc is not None) else None
        nm = (niat / rev) if (has_rev and niat is not None) else None
        rows.append((code, dt, rev, gp, cogs, gm, opex, opinc, om, pretax, niat, nm, eps, equity, updated))
    return rows


def main():
    test = "--test" in sys.argv
    con = sqlite3.connect(DB, timeout=60)
    con.execute("""CREATE TABLE IF NOT EXISTS tw_quarterly_financials_history(
        code TEXT, date TEXT, revenue REAL, gross_profit REAL, cost_of_goods_sold REAL,
        gross_margin REAL, operating_expenses REAL, operating_income REAL, operating_margin REAL,
        pretax_income REAL, income_after_taxes REAL, net_margin REAL, eps REAL,
        equity_attributable_parent REAL, updated TEXT, PRIMARY KEY(code, date))""")
    done = set()
    if os.path.exists(DONE_CACHE) and not test:
        with open(DONE_CACHE, "rb") as f:
            done = pickle.load(f)
    codes = universe()
    todo = [c for c in codes if c not in done]
    if test:
        todo = todo[:15]
    print(f"流動性股票池{len(codes)}檔, 已完成{len(done)}, 待抓{len(todo)}"
          f" (預估{len(todo) * SLEEP / 3600:.1f}hr)", flush=True)
    n_rows = 0
    for i, code in enumerate(todo):
        data = fm_get(code)
        if data is None:
            print(f"  {code}: 連續失敗跳過(未記done,下次續傳重試)", flush=True)
            time.sleep(SLEEP)
            continue
        rows = to_rows(code, data)
        con.executemany(
            "INSERT OR REPLACE INTO tw_quarterly_financials_history "
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
    n = con.execute("SELECT COUNT(*), COUNT(DISTINCT code), MIN(date), MAX(date) "
                    "FROM tw_quarterly_financials_history").fetchone()
    print(f"完成: tw_quarterly_financials_history {n[0]:,}筆 / {n[1]}檔 / {n[2]}~{n[3]}", flush=True)
    con.close()


if __name__ == "__main__":
    main()
