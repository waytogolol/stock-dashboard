# -*- coding: utf-8 -*-
"""陸股題材成員個股日線 -> DB cn_daily_price 表
目的: 台陸題材連動研究(陸股題材動→台股同題材跟不跟)的陸股側日線基礎。
      設計逐字比照抓取/fetch_us_daily_price.py(2026-08-05美股版,已驗證管線)。
來源: yfinance(免費)。範圍: classification中「台陸同名對映題材」且兩側成員數皆>=2
      的陸股成員(33共同題材篩後27題材、~380檔),2015-01-01起。務實範圍——不抓全542檔。
代碼映射: classification陸股代碼sh600011/sz000001 → yfinance 600011.SS / 000001.SZ。
口徑: auto_adjust=True 調整價(分割+股息還原), OHLC同步調整; 幣別CNY(研究只用報酬率,無匯率問題)。
      volume為原始股數, dollar_vol=close*volume(調整後近似值,僅供流動性參考)。
用法: python 抓取/fetch_cn_daily_price.py          # 增量(從DB內各檔max date續抓)
      python 抓取/fetch_cn_daily_price.py --full    # 忽略DB現況全量重抓
斷點續傳: 逐檔寫入+commit,中斷重跑會自動從缺的地方補。限流退避重試3次。
注意: A股有漲跌停10%/20%(ST 5%)與長期停牌文化,個股停牌期間yfinance無列,研究時
      題材報酬用當日有值成員均值(MIN成員數門檻)天然處理。
"""
import sqlite3
import sys
import time

import yfinance as yf

DB = "capital_flow.db"
START = "2015-01-01"
MIN_MEMBERS = 2   # 兩側成員數皆>=此值的題材才抓(單檔題材噪音大,比照美股版務實範圍精神)


def get_mapped_themes(conn):
    tw = {r[0] for r in conn.execute(
        "select main_group, count(distinct code) from classification "
        "where country='台' group by main_group having count(distinct code)>=?", (MIN_MEMBERS,))}
    cn = {r[0] for r in conn.execute(
        "select main_group, count(distinct code) from classification "
        "where country='陸' group by main_group having count(distinct code)>=?", (MIN_MEMBERS,))}
    return sorted(tw & cn)


def get_tickers(conn, themes):
    q = ("select distinct code from classification where country='陸' "
         f"and main_group in ({','.join('?' * len(themes))}) order by code")
    return [r[0] for r in conn.execute(q, themes)]


def to_yf(code):
    """sh600011 -> 600011.SS ; sz000001 -> 000001.SZ"""
    if code.startswith("sh"):
        return code[2:] + ".SS"
    if code.startswith("sz"):
        return code[2:] + ".SZ"
    return None


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
                rows.append((d.strftime("%Y-%m-%d"), float(r.Open),
                             float(r.High), float(r.Low), float(r.Close), vol, dv))
            return rows
        except Exception as e:
            wait = 15 * (attempt + 1)
            print(f"  {ticker}: 第{attempt + 1}次失敗({e}), 退避{wait}s", flush=True)
            time.sleep(wait)
    return None


def main():
    full = "--full" in sys.argv
    conn = sqlite3.connect(DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS cn_daily_price(
        code TEXT, date TEXT, open REAL, high REAL, low REAL, close REAL,
        volume INTEGER, dollar_vol REAL, PRIMARY KEY(code, date))""")
    themes = get_mapped_themes(conn)
    tickers = get_tickers(conn, themes)   # DB內存classification原始碼(sh/sz前綴)
    print(f"對映題材{len(themes)}個(兩側成員>={MIN_MEMBERS}), 陸股成員{len(tickers)}檔, 起點{START}",
          flush=True)

    ok, empty, fail = 0, [], []
    for i, code in enumerate(tickers):
        yft = to_yf(code)
        if yft is None:
            fail.append(code)
            continue
        start = START
        if not full:
            mx = conn.execute("select max(date) from cn_daily_price where code=?",
                              (code,)).fetchone()[0]
            if mx:  # 增量: 從既有最末日重抓(覆蓋當日避免半根K)
                start = mx
        rows = fetch_one(yft, start)
        if rows is None:
            fail.append(code)
            continue
        if not rows:
            empty.append(code)
            continue
        conn.executemany("INSERT OR REPLACE INTO cn_daily_price VALUES (?,?,?,?,?,?,?,?)",
                         [(code,) + r for r in rows])
        conn.commit()
        ok += 1
        if (i + 1) % 20 == 0:
            print(f"  進度 {i + 1}/{len(tickers)}", flush=True)
        time.sleep(0.5)  # 溫和限速

    print(f"完成: 成功{ok}檔, 無資料{len(empty)}檔{empty}, 失敗{len(fail)}檔{fail}", flush=True)
    n, dmin, dmax, nc = conn.execute(
        "select count(*), min(date), max(date), count(distinct code) "
        "from cn_daily_price").fetchone()
    print(f"驗證: cn_daily_price 共{n}筆 / {nc}檔 / {dmin}~{dmax}", flush=True)
    conn.close()


if __name__ == "__main__":
    main()
