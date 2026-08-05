# -*- coding: utf-8 -*-
"""美股題材成員歷史財報公布日 -> DB us_earnings_dates 表
目的: 「美股題材成員財報公布→台股同題材反應」研究的事件日基礎(2026-08-05使用者提問開線)。
來源: yfinance Ticker.get_earnings_dates(limit=100)——實測每檔約100筆回溯到2001年,
      含EPS Estimate/Reported EPS/Surprise(%),時間戳可分盤前盤後(hour>=15≈盤後AMC,<=9≈盤前BMO)。
範圍: 與抓取/fetch_us_daily_price.py同一批「台美同名對映題材」美股成員(~89檔)。
欄位: code, ann_date(美東日曆日), hour(美東時), session(AMC/BMO/DUR/UNK),
      eps_est, eps_actual, surprise_pct, fetched。
用法: python 抓取/fetch_us_earnings_dates.py    # 全量重抓(每檔一次API,~2分鐘,直接REPLACE)
斷點/重複: PRIMARY KEY(code, ann_date) INSERT OR REPLACE,重跑安全;未來財報日(actual=NaN)也入庫
      (live watch可用),研究端自行濾eps_actual非空或ann_date<今天。
注意: yfinance此API偶爾對個別檔限流回空,重試3次;Yahoo歷史財報「日期」偶有錯置(社群已知),
      研究端建議用「公布日±1的美股自身反應日」錨定,不盲信單日。
"""
import sqlite3
import sys
import time
from datetime import datetime

import pandas as pd
import yfinance as yf

DB = "capital_flow.db"
MAPPED_THEMES = [
    "IC設計", "CPO/光通訊", "AI伺服器", "半導體設備", "記憶體", "晶圓代工",
    "功率半導體", "電力設備", "組裝代工(EMS)", "機器人/自動化", "半導體材料",
    "電池/儲能", "連接器", "網通設備", "綠能/太陽能", "封測(OSAT/測試)",
    "被動元件", "化合物半導體", "PCB/CCL", "電信",
]

sys.stdout.reconfigure(encoding="utf-8")


def get_tickers(conn):
    q = ("select distinct code from classification where country='美' "
         f"and main_group in ({','.join('?' * len(MAPPED_THEMES))}) order by code")
    return [r[0] for r in conn.execute(q, MAPPED_THEMES)]


def session_of(hour):
    if hour >= 15:
        return "AMC"     # after market close
    if hour <= 9:
        return "BMO"     # before market open
    return "DUR"         # 盤中/不明


def fetch_one(tk):
    for attempt in range(3):
        try:
            ed = yf.Ticker(tk).get_earnings_dates(limit=100)
            if ed is None or ed.empty:
                return []
            rows = []
            for ts, r in ed.iterrows():
                rows.append((tk, ts.strftime("%Y-%m-%d"), int(ts.hour), session_of(int(ts.hour)),
                             float(r["EPS Estimate"]) if pd.notna(r["EPS Estimate"]) else None,
                             float(r["Reported EPS"]) if pd.notna(r["Reported EPS"]) else None,
                             float(r["Surprise(%)"]) if pd.notna(r["Surprise(%)"]) else None))
            return rows
        except Exception as e:
            wait = 15 * (attempt + 1)
            print(f"  {tk}: 第{attempt + 1}次失敗({e}), 退避{wait}s", flush=True)
            time.sleep(wait)
    return None


def main():
    conn = sqlite3.connect(DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS us_earnings_dates(
        code TEXT, ann_date TEXT, hour INTEGER, session TEXT,
        eps_est REAL, eps_actual REAL, surprise_pct REAL, fetched TEXT,
        PRIMARY KEY(code, ann_date))""")
    tickers = get_tickers(conn)
    today = datetime.now().strftime("%Y-%m-%d")
    print(f"對映題材美股成員{len(tickers)}檔", flush=True)
    ok, empty, fail = 0, [], []
    for i, tk in enumerate(tickers):
        rows = fetch_one(tk)
        if rows is None:
            fail.append(tk)
            continue
        if not rows:
            empty.append(tk)
            continue
        conn.executemany("INSERT OR REPLACE INTO us_earnings_dates VALUES (?,?,?,?,?,?,?,?)",
                         [r + (today,) for r in rows])
        conn.commit()
        ok += 1
        if (i + 1) % 10 == 0:
            print(f"  進度 {i + 1}/{len(tickers)}", flush=True)
        time.sleep(0.5)
    print(f"完成: 成功{ok}檔, 空{len(empty)}檔{empty}, 失敗{len(fail)}檔{fail}", flush=True)
    n, dmin, dmax, nc = conn.execute(
        "select count(*), min(ann_date), max(ann_date), count(distinct code) "
        "from us_earnings_dates").fetchone()
    n_act = conn.execute("select count(*) from us_earnings_dates where eps_actual is not null").fetchone()[0]
    print(f"驗證: us_earnings_dates 共{n}筆({n_act}筆有實際EPS) / {nc}檔 / {dmin}~{dmax}", flush=True)
    conn.close()


if __name__ == "__main__":
    main()
