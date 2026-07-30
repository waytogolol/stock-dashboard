# -*- coding: utf-8 -*-
"""FinMind月營收覆蓋擴大版：原本fetch_finmind.py只抓213檔研究宇宙(歷次觸發成員+產業鏈+供應鏈)，
產業趨勢分析需要更廣的產業覆蓋(tw_industry_map.csv全部2,297檔)才能讓每個產業有足夠公司數做加總。
只抓TaiwanStockMonthRevenue一個資料集(這次用不到損益表/現金流量表，省時間)。
節流/斷點續傳邏輯同fetch_finmind.py。
用法: python fetch_finmind_monthrev_expand.py
"""
import os
import pickle
import sqlite3
import time
from datetime import date

import pandas as pd
import requests

DB = "capital_flow.db"
CACHE = "tmp_finmind_monthrev_cache.pkl"
TOKEN = open("finmind_token.txt").read().strip()
START = "2019-01-01"
SLEEP = 6.1


def universe():
    """範圍=近期成交值>=5000萬(使用者實務門檻:成交值太爛的公司本來就不會列入交易考慮)。
    tmp_tw_top1000.csv由fetch_top200.fetch_taiwan單次抓全市場後過濾amount>=50,000,000產生(732檔)，
    不追求tw_industry_map全集2,297檔。"""
    top1000 = pd.read_csv("tmp_tw_top1000.csv", dtype=str, encoding="utf-8-sig")
    conn = sqlite3.connect(DB)
    done = set(r[0] for r in conn.execute("SELECT DISTINCT code FROM fm_month_rev"))
    return sorted(set(top1000.code) - done)


def fm_get(code):
    for attempt in range(4):
        try:
            r = requests.get("https://api.finmindtrade.com/api/v4/data",
                              params={"dataset": "TaiwanStockMonthRevenue", "data_id": code,
                                      "start_date": START, "end_date": str(date.today()),
                                      "token": TOKEN}, timeout=40)
            if r.status_code == 402:
                print(f"  額度限制,休息70s (attempt{attempt})")
                time.sleep(70)
                continue
            j = r.json()
            if j.get("msg") != "success":
                print(f"  {code}: {j.get('msg')}")
                time.sleep(20)
                continue
            return j.get("data") or []
        except Exception as e:
            print(f"  {code}: {type(e).__name__}, 重試")
            time.sleep(15)
    return None


def main():
    codes = universe()
    print(f"待補 {len(codes)} 檔(tw_industry_map全集 - 已有的fm_month_rev)")
    cache = {}
    if os.path.exists(CACHE):
        with open(CACHE, "rb") as f:
            cache = pickle.load(f)
    conn = sqlite3.connect(DB)
    done = fail = 0
    for code in codes:
        if code in cache:
            continue
        data = fm_get(code)
        if data is None:
            fail += 1
            time.sleep(SLEEP)
            continue
        rows = [(code, d["date"], d.get("revenue")) for d in data]
        conn.executemany("INSERT OR REPLACE INTO fm_month_rev VALUES (?,?,?)", rows)
        conn.commit()
        cache[code] = len(rows)
        done += 1
        if done % 25 == 0:
            with open(CACHE, "wb") as f:
                pickle.dump(cache, f)
            print(f"進度 {len(cache)}/{len(codes)} (本次成功{done}, 待重試{fail})")
        time.sleep(SLEEP)
    with open(CACHE, "wb") as f:
        pickle.dump(cache, f)
    n = conn.execute("SELECT COUNT(*), COUNT(DISTINCT code) FROM fm_month_rev").fetchone()
    print(f"fm_month_rev: {n[0]} 筆 / {n[1]} 檔")
    conn.close()
    print(f"完成！本次成功{done} 待重試{fail}")


if __name__ == "__main__":
    main()
