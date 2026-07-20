# -*- coding: utf-8 -*-
"""全球指數日線 -> index_daily (與台股雙指數同表, market=代號)
來源: yfinance(免費), 全史。用法: python fetch_global_index.py
"""
import sqlite3

import yfinance as yf

TICKERS = {"^GSPC": "SPX", "^RUT": "RUT", "^SOX": "SOX", "^N225": "N225",
           "^KS11": "KOSPI", "^HSI": "HSI", "000001.SS": "SSE"}


def main():
    conn = sqlite3.connect("capital_flow.db")
    for tk, mkt in TICKERS.items():
        h = yf.Ticker(tk).history(period="max", auto_adjust=False)
        if h is None or h.empty:
            print(f"{mkt}: 無資料!")
            continue
        h = h.dropna(subset=["Close"])
        rows = [(mkt, d.strftime("%Y-%m-%d"), float(r.Open), float(r.High),
                 float(r.Low), float(r.Close),
                 float(r.Volume) if r.Volume == r.Volume else None, None)
                for d, r in h.iterrows()]
        conn.executemany("INSERT OR REPLACE INTO index_daily VALUES (?,?,?,?,?,?,?,?)", rows)
        print(f"{mkt}: {len(rows)}筆 {rows[0][1]}~{rows[-1][1]}")
    conn.commit()
    conn.close()


if __name__ == "__main__":
    main()
