# -*- coding: utf-8 -*-
"""美股題材成員個股日線 -> DB us_daily_price 表
目的: 台美隔夜題材連動研究(昨晚美股題材表現→今日台股同題材)的美股側日線基礎。
來源: yfinance(免費)。範圍: classification中「台美同名對映題材」的美股成員
      (記憶體/AI伺服器/CPO光通訊/半導體設備/IC設計/封測/被動元件/功率半導體等
       約20題材、~90檔),2015-01-01起。務實範圍——不抓全700檔。
口徑: auto_adjust=True 調整價(分割+股息還原), OHLC同步調整;
      volume為原始股數, dollar_vol=close*volume(調整後近似值,僅供流動性參考)。
      日級報酬計算直接用close即可(調整價口徑)。
用法: python 抓取/fetch_us_daily_price.py          # 增量(從DB內各檔max date續抓)
      python 抓取/fetch_us_daily_price.py --full    # 忽略DB現況全量重抓
斷點續傳: 逐檔寫入+commit,中斷重跑會自動從缺的地方補。限流退避重試3次。
注意: 美股側含台廠ADR(TSM/UMC/ASX)——研究時需可排除(機械性自我連動),照抓不刪。
"""
import sqlite3
import sys
import time
from datetime import datetime, timedelta

import yfinance as yf

DB = "capital_flow.db"
START = "2015-01-01"

# 台美同名對映題材(兩側皆有成員, 見classification main_group)
MAPPED_THEMES = [
    "IC設計", "CPO/光通訊", "AI伺服器", "半導體設備", "記憶體", "晶圓代工",
    "功率半導體", "電力設備", "組裝代工(EMS)", "機器人/自動化", "半導體材料",
    "電池/儲能", "連接器", "網通設備", "綠能/太陽能", "封測(OSAT/測試)",
    "被動元件", "化合物半導體", "PCB/CCL", "電信",
]


def get_tickers(conn):
    q = ("select distinct code from classification where country='美' "
         f"and main_group in ({','.join('?' * len(MAPPED_THEMES))}) order by code")
    return [r[0] for r in conn.execute(q, MAPPED_THEMES)]


def fetch_one(ticker, start):
    """單檔抓取, 限流退避重試3次。回傳rows或None(失敗/無資料)。"""
    for attempt in range(3):
        try:
            h = yf.Ticker(ticker).history(start=start, auto_adjust=True)
            if h is None or h.empty:
                return []
            h = h.dropna(subset=["Close"])
            rows = []
            for d, r in h.iterrows():
                vol = int(r.Volume) if r.Volume == r.Volume else None
                dv = float(r.Close) * vol if vol is not None else None
                rows.append((ticker, d.strftime("%Y-%m-%d"), float(r.Open),
                             float(r.High), float(r.Low), float(r.Close), vol, dv))
            return rows
        except Exception as e:
            wait = 15 * (attempt + 1)
            print(f"  {ticker}: 第{attempt + 1}次失敗({e}), 退避{wait}s")
            time.sleep(wait)
    return None


def main():
    full = "--full" in sys.argv
    conn = sqlite3.connect(DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS us_daily_price(
        code TEXT, date TEXT, open REAL, high REAL, low REAL, close REAL,
        volume INTEGER, dollar_vol REAL, PRIMARY KEY(code, date))""")
    tickers = get_tickers(conn)
    print(f"對映題材{len(MAPPED_THEMES)}個, 美股成員{len(tickers)}檔, 起點{START}")

    ok, empty, fail = 0, [], []
    for i, tk in enumerate(tickers):
        start = START
        if not full:
            mx = conn.execute("select max(date) from us_daily_price where code=?",
                              (tk,)).fetchone()[0]
            if mx:  # 增量: 從既有最末日重抓(覆蓋當日避免半根K)
                start = mx
        rows = fetch_one(tk, start)
        if rows is None:
            fail.append(tk)
            continue
        if not rows:
            empty.append(tk)
            continue
        conn.executemany("INSERT OR REPLACE INTO us_daily_price VALUES (?,?,?,?,?,?,?,?)",
                         rows)
        conn.commit()
        ok += 1
        if (i + 1) % 10 == 0:
            print(f"  進度 {i + 1}/{len(tickers)}")
        time.sleep(0.5)  # 溫和限速

    print(f"完成: 成功{ok}檔, 無資料{len(empty)}檔{empty}, 失敗{len(fail)}檔{fail}")
    n, dmin, dmax, nc = conn.execute(
        "select count(*), min(date), max(date), count(distinct code) "
        "from us_daily_price").fetchone()
    print(f"驗證: us_daily_price 共{n}筆 / {nc}檔 / {dmin}~{dmax}")
    conn.close()


if __name__ == "__main__":
    main()
