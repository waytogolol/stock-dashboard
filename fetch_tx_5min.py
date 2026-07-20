# -*- coding: utf-8 -*-
"""TX台指期日盤5分K歷史庫 -> capital_flow.db (tx_5min)
用途: H-尾盤結構性賣壓正式考卷(全史+結算日週三/週五分層+崩盤日拆出)
方法: TaiwanFuturesTick逐日抓(1請求/天)→主力契約(日盤量最大)→5分K聚合落庫
     (使用者裁示: 尾盤研究5分K夠用;13:25強平死線正好在5分邊界;原始tick不落庫)
範圍: 2019-01-01起日盤08:45-13:45, 約1850交易日×60根=~11萬列
節流: 2.6s/請求(Backer 1600/hr); 斷點續傳tx_5min_done_days表; 402退避
用法: python fetch_tx_5min.py [--start 2019-01-01]
"""
import argparse
import sqlite3
import time
from datetime import date, timedelta

import pandas as pd
import requests

DB = "capital_flow.db"
TOKEN = open("finmind_token.txt").read().strip()
SLEEP = 2.6


def fetch_day(ds):
    for att in range(4):
        try:
            r = requests.get("https://api.finmindtrade.com/api/v4/data",
                             params={"dataset": "TaiwanFuturesTick", "data_id": "TX",
                                     "start_date": ds, "token": TOKEN}, timeout=180)
            if r.status_code == 402:
                print(f"  {ds} 額度限制,休息70s", flush=True)
                time.sleep(70)
                continue
            j = r.json()
            if j.get("msg") == "success":
                return j.get("data") or []
            print(f"  {ds}: {j.get('msg')}", flush=True)
            time.sleep(20)
        except Exception as e:
            print(f"  {ds}: {type(e).__name__} 重試", flush=True)
            time.sleep(15)
    return None


def to_1min(ticks):
    df = pd.DataFrame(ticks)
    df = df[~df.contract_date.astype(str).str.contains("/")]
    if df.empty:
        return []
    df["dt"] = pd.to_datetime(df.date)
    d0 = df.dt.dt.normalize().iloc[0]
    day = df[(df.dt >= d0 + pd.Timedelta("08:45:00")) &
             (df.dt <= d0 + pd.Timedelta("13:45:00"))]
    if len(day) < 100:
        return []
    main = day.groupby("contract_date").volume.sum().idxmax()
    day = day[day.contract_date == main].set_index("dt").sort_index()
    bars = day.price.resample("5min").ohlc()
    bars["volume"] = day.volume.resample("5min").sum()
    bars = bars.dropna(subset=["open"])
    ds = str(d0.date())
    return [(ds, ts.strftime("%H:%M"), str(main), r.open, r.high, r.low, r.close, int(r.volume))
            for ts, r in bars.iterrows()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2019-01-01")
    args = ap.parse_args()
    conn = sqlite3.connect(DB, timeout=120)
    conn.execute("""CREATE TABLE IF NOT EXISTS tx_5min (
        date TEXT, time TEXT, contract TEXT,
        open REAL, high REAL, low REAL, close REAL, volume INTEGER,
        PRIMARY KEY(date, time))""")
    conn.execute("CREATE TABLE IF NOT EXISTS tx_5min_done_days (day TEXT PRIMARY KEY)")
    conn.commit()

    d0 = date.fromisoformat(args.start)
    days = [str(d0 + timedelta(days=i)) for i in range((date.today() - d0).days + 1)]
    done = set(r[0] for r in conn.execute("SELECT day FROM tx_5min_done_days"))
    todo = [d for d in days if d not in done]
    print(f"待抓 {len(todo)} 天 ({todo[0]}~{todo[-1]})", flush=True)

    n_bars = n_days = 0
    for i, ds in enumerate(todo):
        ticks = fetch_day(ds)
        if ticks is None:            # 連續失敗,留給下次續傳
            print(f"  {ds} 連續失敗,跳過", flush=True)
            time.sleep(SLEEP)
            continue
        rows = to_1min(ticks) if ticks else []
        if rows:
            conn.executemany("INSERT OR REPLACE INTO tx_5min VALUES (?,?,?,?,?,?,?,?)", rows)
            n_bars += len(rows)
            n_days += 1
        conn.execute("INSERT OR REPLACE INTO tx_5min_done_days VALUES (?)", (ds,))
        conn.commit()
        if (i + 1) % 100 == 0 or i == len(todo) - 1:
            print(f"  [{i + 1}/{len(todo)}] {ds} 有效{n_days}天 {n_bars}根", flush=True)
        time.sleep(SLEEP)
    conn.close()
    print(f"完成: {n_days}交易日 {n_bars}根5分K", flush=True)


if __name__ == "__main__":
    main()
