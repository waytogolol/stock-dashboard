# -*- coding: utf-8 -*-
"""抓產業鏈成員+錨點客戶的季度資本支出 -> DB capex_history 表
來源: yfinance quarterly_cashflow「Capital Expenditure」(約5季，原幣別)
含數字檢驗: 1)capex/營收比異常 2)QoQ跳變>5x 3)已知大廠量級對照，寫 tmp_capex_check.txt
用法: python fetch_capex.py   (每季跑一次，快取續傳)
"""
import os
import pickle
import sqlite3
import sys
import time
from datetime import date

import yfinance as yf

sys.path.insert(0, os.getcwd())
from backfill_history import RateGuard, ticker_variants

DB = "capital_flow.db"
CACHE = "tmp_capex_cache.pkl"


def universe():
    """產業鏈成員 + 供應鏈供應商與錨點客戶(不重複)"""
    import industry_chains as ic
    import supply_chain as sc
    u = set()
    for _chain, _st, code, country, _r in ic.CHAIN_LINKS:
        u.add((country, code))
    for sup_code, sup_country, cust_code, cust_country, _p in sc.LINKS:
        u.add((sup_country, sup_code))
        u.add((cust_country, cust_code))
    return sorted(u)


def main():
    plan = universe()
    print(f"宇宙 {len(plan)} 檔")
    cache = {}
    if os.path.exists(CACHE):
        with open(CACHE, "rb") as f:
            cache = pickle.load(f)
    guard = RateGuard()
    rows = []
    today = str(date.today())
    fail = 0
    for i, (country, code) in enumerate(plan):
        key = f"{country}|{code}"
        if key not in cache:
            got = None
            for t in ticker_variants(country, code) or []:
                try:
                    cf = yf.Ticker(t).quarterly_cashflow
                    if cf is not None and not cf.empty and "Capital Expenditure" in cf.index:
                        s = cf.loc["Capital Expenditure"].dropna()
                        got = [(str(d.date()), abs(float(v))) for d, v in s.items()]
                    break
                except Exception:
                    time.sleep(3)
            cache[key] = got
            if got is None:
                fail += 1
                guard.ok()   # 無資料不算封鎖
            else:
                guard.ok()
            time.sleep(0.4)
            if (i + 1) % 50 == 0:
                with open(CACHE, "wb") as f:
                    pickle.dump(cache, f)
                print(f"進度 {i+1}/{len(plan)}，無資料 {fail}")
        got = cache[key]
        if got:
            for qd, v in got:
                rows.append((country, code, qd, v, today))
    with open(CACHE, "wb") as f:
        pickle.dump(cache, f)

    conn = sqlite3.connect(DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS capex_history (
        country TEXT, code TEXT, qdate TEXT, capex REAL, updated TEXT,
        PRIMARY KEY (country, code, qdate))""")
    conn.executemany("INSERT OR REPLACE INTO capex_history VALUES (?,?,?,?,?)", rows)
    conn.commit()

    # ── 數字檢驗 ──
    chk = ["== capex 數字檢驗報告 =="]
    n = conn.execute("SELECT COUNT(*), COUNT(DISTINCT country||code) FROM capex_history").fetchone()
    chk.append(f"capex_history: {n[0]} 筆 / {n[1]} 檔（宇宙{len(plan)}檔，覆蓋率{n[1]/len(plan):.0%}）")
    # 1) 已知大廠量級對照(原幣別，數量級不對=抓錯)
    chk.append("\n[量級對照] 應與公開報導同數量級:")
    for country, code, name, lo, hi, unit in [
        ("美", "MSFT", "微軟", 15e9, 45e9, "USD"),
        ("美", "NVDA", "輝達", 0.5e9, 5e9, "USD"),
        ("台", "2330", "台積電", 2e11, 6e11, "TWD"),
        ("韓", "005930", "三星電子", 8e12, 2e13, "KRW"),
    ]:
        r = conn.execute("""SELECT qdate, capex FROM capex_history
            WHERE country=? AND code=? ORDER BY qdate DESC LIMIT 1""", (country, code)).fetchone()
        if r:
            ok = "✓" if lo <= r[1] <= hi else "⚠ 超出預期區間"
            chk.append(f"  {name} {r[0]}: {r[1]/1e9:.1f}B {unit} {ok} (預期{lo/1e9:.0f}~{hi/1e9:.0f}B)")
        else:
            chk.append(f"  {name}: 無資料 ⚠")
    # 2) QoQ跳變>5x(可能是年報/季報混雜或幣別錯亂)
    jumps = conn.execute("""
        SELECT a.country, a.code, a.qdate, a.capex, b.capex FROM capex_history a
        JOIN capex_history b ON a.country=b.country AND a.code=b.code
          AND b.qdate = (SELECT MAX(qdate) FROM capex_history c
                         WHERE c.country=a.country AND c.code=a.code AND c.qdate < a.qdate)
        WHERE b.capex > 0 AND a.capex / b.capex > 5""").fetchall()
    chk.append(f"\n[QoQ跳變>5x] {len(jumps)} 筆(抽查前10，跳變可能是真擴產也可能是資料錯，需人工看):")
    for c, cd, q, a, b in jumps[:10]:
        chk.append(f"  {c}{cd} {q}: {b/1e9:.2f}B -> {a/1e9:.2f}B ({a/b:.1f}x)")
    # 3) capex為0或負(yf原值為流出負數，取abs後不應為0佔多數)
    z = conn.execute("SELECT COUNT(*) FROM capex_history WHERE capex <= 0").fetchone()[0]
    chk.append(f"\n[非正值] {z} 筆(應接近0)")
    conn.close()
    report = "\n".join(chk)
    with open("tmp_capex_check.txt", "w", encoding="utf-8") as f:
        f.write(report)
    try:
        print(report)
    except UnicodeEncodeError:
        print("done -> tmp_capex_check.txt (cp950主控台無法顯示部分符號)")


if __name__ == "__main__":
    main()
