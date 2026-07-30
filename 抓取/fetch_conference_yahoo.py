# -*- coding: utf-8 -*-
"""Yahoo台股法說會行事曆 -> capital_flow.db (conference表)
背景(2026-07-25偵察): tw.stock.yahoo.com/calendar/earnings-call ?date=參數有效,
歷史窗=滾動約一年(2025-08✓/2025-07-01✗);事件物件含eventId/代號/名稱/精確時間/地點/訊息全文
(MOPS公告轉貼,欄位同級)。使用者裁示: 先Yahoo回補到有的深度,MOPS歷史回補緩議。
設計: 從2025-07-05起每10天一刀掃到今天+45天,每刀回傳約2-6週窗,重疊靠eventId去重;
  回傳窗與請求日差>45天=退回預設頁,跳過(防污染);每週例行重跑=自動補新場次(含未來)。
用法: python -X utf8 fetch_conference_yahoo.py
"""
import json
import re
import sqlite3
import sys
import time
from datetime import date, datetime, timedelta

import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DB = "capital_flow.db"
URL = "https://tw.stock.yahoo.com/calendar/earnings-call"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
START = date(2025, 7, 5)   # 邊界偵察: 2025-07-01退回預設/2025-08-01有效,由此起掃自動略過無效刀
STEP_DAYS = 10
SLEEP = 0.8
FALLBACK_TOL = 45          # 回傳首事件日與請求日差>45天=退回預設,棄用


def parse_events(html):
    out = []
    for m in re.finditer(r'\{"symbol":"[^"]+"[^{}]*?"eventType":"earningsCall"[^{}]*?\}', html):
        try:
            o = json.loads(m.group(0))
        except json.JSONDecodeError:
            continue
        sym = o.get("symbol", "")
        code = sym.split(".")[0]
        dtxt = o.get("date", "")
        if not code or len(dtxt) < 10:
            continue
        out.append({
            "event_id": o.get("eventId") or f"InvMet-{code}-{dtxt[:10].replace('-', '')}",
            "code": code, "date": dtxt[:10], "time": dtxt[11:16],
            "name": o.get("symbolName", ""), "market": "TWO" if sym.endswith(".TWO") else "TW",
            "place": o.get("place", ""), "information": o.get("information", ""),
            "review": o.get("corpReviewName", ""),
        })
    return out


def main():
    con = sqlite3.connect(DB, timeout=60)
    con.execute("""CREATE TABLE IF NOT EXISTS conference(
        event_id TEXT PRIMARY KEY, code TEXT, date TEXT, time TEXT, name TEXT,
        market TEXT, place TEXT, information TEXT, review TEXT,
        source TEXT, fetched TEXT)""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_conf_code_date ON conference(code, date)")
    s = requests.Session()
    s.headers.update(UA)
    today = date.today()
    d = START
    n_req = n_ok = n_ev = 0
    seen = set()
    while d <= today + timedelta(days=45):
        n_req += 1
        try:
            r = s.get(URL, params={"date": d.isoformat()}, timeout=30)
            evs = parse_events(r.text)
        except Exception as e:
            print(f"  {d}: {type(e).__name__},跳過", flush=True)
            d += timedelta(days=STEP_DAYS)
            time.sleep(SLEEP)
            continue
        if evs:
            first = min(e["date"] for e in evs)
            gap = abs((date.fromisoformat(first) - d).days)
            if gap > FALLBACK_TOL:
                print(f"  {d}: 退回預設頁(首事件{first}),棄用", flush=True)
            else:
                fresh = [e for e in evs if e["event_id"] not in seen]
                seen.update(e["event_id"] for e in fresh)
                now = datetime.now().strftime("%Y-%m-%d %H:%M")
                con.executemany(
                    "INSERT OR REPLACE INTO conference VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    [(e["event_id"], e["code"], e["date"], e["time"], e["name"], e["market"],
                      e["place"], e["information"], e["review"], "yahoo", now) for e in fresh])
                con.commit()
                n_ok += 1
                n_ev += len(fresh)
        d += timedelta(days=STEP_DAYS)
        time.sleep(SLEEP)
    n, nc, dmin, dmax = con.execute(
        "SELECT count(*), count(DISTINCT code), min(date), max(date) FROM conference").fetchone()
    print(f"完成: {n_req}刀/{n_ok}有效, 本次新增{n_ev}筆; conference表共{n:,}筆/{nc}檔/{dmin}~{dmax}")
    con.close()


if __name__ == "__main__":
    main()
