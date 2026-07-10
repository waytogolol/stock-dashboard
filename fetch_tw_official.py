# -*- coding: utf-8 -*-
"""台股官方基本面資料抓取（取代Goodinfo爬蟲的正規做法）
來源皆為官方開放API，整批端點（一次請求=全市場），無反爬風險：
- 月營收+YoY: TWSE/TPEX openAPI t187ap05
- 季損益表(毛利率/EPS): MOPS開放資料CSV t187ap06
- 每日PB/PE/殖利率: TWSE BWIBBU_ALL / TPEX對應

存入DB: tw_monthly_revenue / tw_quarterly_fin / tw_valuation
用法: python fetch_tw_official.py   (每月10日後、每季財報後、或每週跑皆可)
"""
import io
import sqlite3
import time
from datetime import date

import pandas as pd
import requests

DB = "capital_flow.db"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Accept": "application/json"}


def get_json(url):
    r = requests.get(url, headers=UA, timeout=30)
    r.raise_for_status()
    return r.json()


def get_csv(url):
    r = requests.get(url, headers=UA, timeout=30)
    r.raise_for_status()
    return pd.read_csv(io.BytesIO(r.content), encoding="utf-8-sig", dtype=str)


def pick(d, *subs):
    """依欄位名子字串取值(官方欄位名偶有變動，防禦性比對)"""
    for k, v in d.items():
        if all(s in k for s in subs):
            return v
    return None


def to_f(x):
    try:
        return float(str(x).replace(",", ""))
    except (ValueError, TypeError):
        return None


def fetch_monthly(conn, log):
    rows = []
    for name, url in [
        ("上市", "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"),
        ("上櫃", "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O"),
    ]:
        try:
            data = get_json(url)
            for d in data:
                code = pick(d, "公司代號") or pick(d, "SecuritiesCompanyCode")
                ym = pick(d, "資料年月")
                rev = to_f(pick(d, "當月營收"))
                yoy = to_f(pick(d, "去年同月增減"))
                if code and ym and rev is not None:
                    rows.append((str(code).strip(), str(ym).strip(), rev, yoy))
            log.append(f"月營收 {name}: {len(data)} 筆 OK")
        except Exception as e:
            log.append(f"月營收 {name}: 失敗 {e}")
        time.sleep(2)
    if rows:
        conn.execute("""CREATE TABLE IF NOT EXISTS tw_monthly_revenue (
            code TEXT, year_month TEXT, revenue REAL, yoy_pct REAL,
            updated TEXT, PRIMARY KEY (code, year_month))""")
        today = str(date.today())
        conn.executemany(
            "INSERT OR REPLACE INTO tw_monthly_revenue VALUES (?,?,?,?,?)",
            [(c, ym, rv, yy, today) for c, ym, rv, yy in rows])
        conn.commit()
    return len(rows)


def fetch_quarterly(conn, log):
    """MOPS t187ap06 為「年初至今累計值」：Q1=單季可直用；Q2起必須扣減前季累計還原單季。
    tw_quarterly_cum 存官方原始累計值，tw_quarterly_fin 一律存還原後的單季值。"""
    conn.execute("""CREATE TABLE IF NOT EXISTS tw_quarterly_cum (
        code TEXT, quarter TEXT, revenue REAL, gross_profit REAL, eps REAL,
        updated TEXT, PRIMARY KEY (code, quarter))""")
    # 遷移(冪等)：既有Q1單季=累計，補進累計表，供未來Q2扣減
    conn.execute("""INSERT OR IGNORE INTO tw_quarterly_cum
        SELECT code, quarter, revenue, gross_profit, eps, updated
        FROM tw_quarterly_fin WHERE quarter LIKE '%Q1'""")
    conn.commit()

    raw = []
    for name, url in [
        ("上市一般業", "https://mopsfin.twse.com.tw/opendata/t187ap06_L_ci.csv"),
        ("上櫃一般業", "https://mopsfin.twse.com.tw/opendata/t187ap06_O_ci.csv"),
    ]:
        try:
            df = get_csv(url)
            for _, r in df.iterrows():
                d = dict(r)
                code = pick(d, "公司代號")
                yr, season = pick(d, "年度"), pick(d, "季別")
                rev = to_f(pick(d, "營業收入"))
                gp = to_f(pick(d, "營業毛利"))
                eps = to_f(pick(d, "每股盈餘"))
                if code and yr and season and rev:
                    raw.append((str(code).strip(), str(yr).strip(), int(season), rev, gp, eps))
            log.append(f"季損益 {name}: {len(df)} 筆 OK (欄位: {list(df.columns)[:8]}...)")
        except Exception as e:
            log.append(f"季損益 {name}: 失敗 {e}")
        time.sleep(2)
    if not raw:
        return 0
    today = str(date.today())
    conn.executemany("INSERT OR REPLACE INTO tw_quarterly_cum VALUES (?,?,?,?,?,?)",
                     [(c, f"{y}Q{s}", rv, gp, eps, today) for c, y, s, rv, gp, eps in raw])
    conn.commit()

    prev = {(c, q): (rv, gp, eps) for c, q, rv, gp, eps in
            conn.execute("SELECT code, quarter, revenue, gross_profit, eps FROM tw_quarterly_cum")}
    rows, skipped = [], 0
    for c, y, s, rv, gp, eps in raw:
        if s == 1:
            srv, sgp, seps = rv, gp, eps
        else:
            p = prev.get((c, f"{y}Q{s - 1}"))
            if not p or p[0] is None:
                skipped += 1        # 缺前季累計，無法還原單季，寧缺勿錯
                continue
            srv = rv - p[0]
            sgp = gp - p[1] if (gp is not None and p[1] is not None) else None
            seps = eps - p[2] if (eps is not None and p[2] is not None) else None
        gm = sgp / srv * 100 if (sgp is not None and srv) else None
        rows.append((c, f"{y}Q{s}", srv, sgp, gm, seps))
    if skipped:
        log.append(f"季損益: {skipped} 檔缺前季累計值，略過單季還原")
    if rows:
        conn.execute("""CREATE TABLE IF NOT EXISTS tw_quarterly_fin (
            code TEXT, quarter TEXT, revenue REAL, gross_profit REAL,
            gross_margin REAL, eps REAL, updated TEXT, PRIMARY KEY (code, quarter))""")
        conn.executemany(
            "INSERT OR REPLACE INTO tw_quarterly_fin VALUES (?,?,?,?,?,?,?)",
            [(c, q, rv, gp, gm, eps, today) for c, q, rv, gp, gm, eps in rows])
        conn.commit()
    return len(rows)


def fetch_valuation(conn, log):
    rows = []
    try:
        data = get_json("https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL")
        for d in data:
            code = d.get("Code") or pick(d, "公司代號") or pick(d, "股票代號")
            pe = to_f(d.get("PEratio") or pick(d, "本益比"))
            pb = to_f(d.get("PBratio") or pick(d, "股價淨值比"))
            yld = to_f(d.get("DividendYield") or pick(d, "殖利率"))
            if code:
                rows.append((str(code).strip(), pe, pb, yld))
        log.append(f"估值 上市BWIBBU_ALL: {len(data)} 筆 OK")
    except Exception as e:
        log.append(f"估值 上市: 失敗 {e}")
    time.sleep(2)
    # 上櫃估值(端點名稱可能變動，失敗不擋流程)
    for url in ["https://www.tpex.org.tw/openapi/v1/tpex_mainboard_peratio_analysis"]:
        try:
            data = get_json(url)
            n0 = len(rows)
            for d in data:
                code = pick(d, "SecuritiesCompanyCode") or pick(d, "公司代號") or d.get("Code")
                pe = to_f(pick(d, "PriceEarning") or pick(d, "本益比"))
                pb = to_f(pick(d, "PriceBook") or pick(d, "股價淨值比"))
                yld = to_f(pick(d, "Yield") or pick(d, "殖利率"))
                if code:
                    rows.append((str(code).strip(), pe, pb, yld))
            log.append(f"估值 上櫃: {len(rows)-n0} 筆 OK")
        except Exception as e:
            log.append(f"估值 上櫃: 失敗 {e}（欄位名待查，不影響上市資料）")
    if rows:
        conn.execute("""CREATE TABLE IF NOT EXISTS tw_valuation (
            code TEXT PRIMARY KEY, pe REAL, pb REAL, dividend_yield REAL, updated TEXT)""")
        today = str(date.today())
        conn.executemany("INSERT OR REPLACE INTO tw_valuation VALUES (?,?,?,?,?)",
                         [(c, pe, pb, y, today) for c, pe, pb, y in rows])
        conn.commit()
    return len(rows)


def main():
    conn = sqlite3.connect(DB)
    log = []
    n1 = fetch_monthly(conn, log)
    n2 = fetch_quarterly(conn, log)
    n3 = fetch_valuation(conn, log)
    conn.close()
    log.append(f"\n寫入: 月營收{n1} / 季損益{n2} / 估值{n3}")
    with open("tmp_tw_official_log.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(log))
    print("done -> tmp_tw_official_log.txt")


if __name__ == "__main__":
    main()
