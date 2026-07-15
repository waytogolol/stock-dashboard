# -*- coding: utf-8 -*-
"""處置有價證券歷史庫(TWSE+TPEx官方查詢) -> capital_flow.db (disposition)
用途: 處置股先跌後漲假說(使用者2026-07-15提案:尾盤買進1-2日出的候選池)
來源: TWSE rwd/announcement/punish(西元參數) + TPEx www/zh-tw/bulletin/disposal(民國參數)
範圍: 2019-01起,季度分塊,免API金鑰;欄位=市場/代號/公布日/累計次數/處置起迄/措施(5或20分鐘分盤)
用法: python fetch_disposition.py
"""
import re
import sqlite3
import time

import requests

H = {"User-Agent": "Mozilla/5.0"}


def roc2iso(s):
    m = re.search(r"(\d{2,3})/(\d{2})/(\d{2})", s or "")
    if not m:
        return None
    return f"{int(m.group(1)) + 1911}-{m.group(2)}-{m.group(3)}"


def parse_span(s):
    parts = re.split(r"[～~]", s or "")
    if len(parts) == 2:
        return roc2iso(parts[0]), roc2iso(parts[1])
    return None, None


def quarters():
    for y in range(2019, 2027):
        for m in (1, 4, 7, 10):
            a = f"{y}{m:02d}01"
            eb = {1: "0331", 4: "0630", 7: "0930", 10: "1231"}[m]
            b = f"{y}{eb}"
            if a > "20260716":
                return
            yield a, b


def fetch_twse():
    rows = []
    for a, b in quarters():
        for attempt in range(3):
            try:
                r = requests.get("https://www.twse.com.tw/rwd/zh/announcement/punish",
                                 params={"startDate": a, "endDate": b, "response": "json"},
                                 headers=H, timeout=30)
                j = r.json()
                for d in (j.get("data") or []):
                    st, en = parse_span(str(d[6]))
                    mins = "20" if "二十分鐘" in str(d[8]) else "5"
                    # reason=處置條件(d[5],如「連續三次」),原第一版誤存d[7]處置措施(2026-07-16修)
                    rows.append(("上市", str(d[2]).strip(), roc2iso(str(d[1])),
                                 int(d[4]) if str(d[4]).isdigit() else None,
                                 st, en, str(d[5]).strip()[:40], mins))
                print(f"TWSE {a}-{b}: 累計{len(rows)}", flush=True)
                break
            except Exception as e:
                print(f"TWSE {a}: {type(e).__name__} 重試", flush=True)
                time.sleep(5)
        time.sleep(3)
    return rows


def fetch_tpex():
    rows = []
    for a, b in quarters():
        ra = f"{int(a[:4]) - 1911}/{a[4:6]}/{a[6:]}"
        rb = f"{int(b[:4]) - 1911}/{b[4:6]}/{b[6:]}"
        for attempt in range(3):
            try:
                r = requests.get("https://www.tpex.org.tw/www/zh-tw/bulletin/disposal",
                                 params={"startDate": ra, "endDate": rb, "response": "json"},
                                 headers=H, timeout=30)
                j = r.json()
                for d in (j["tables"][0].get("data") or []):
                    code = str(d[2]).strip()
                    if not re.fullmatch(r"\d{4,6}", code):
                        continue  # 「本日無處置資料」列
                    st, en = parse_span(str(d[5]))
                    mins = "20" if ("二十分鐘" in str(d[7]) or "20分鐘" in str(d[7])) else "5"
                    rows.append(("上櫃", code, roc2iso(str(d[1])),
                                 int(d[4]) if str(d[4]).isdigit() else None,
                                 st, en, str(d[6]).strip()[:40], mins))
                print(f"TPEX {ra}: 累計{len(rows)}", flush=True)
                break
            except Exception as e:
                print(f"TPEX {ra}: {type(e).__name__} 重試", flush=True)
                time.sleep(5)
        time.sleep(3)
    return rows


def main():
    con = sqlite3.connect("capital_flow.db")
    con.execute("""CREATE TABLE IF NOT EXISTS disposition(
        market TEXT, code TEXT, announce_date TEXT, cum_count INTEGER,
        start_date TEXT, end_date TEXT, reason TEXT, match_min TEXT,
        PRIMARY KEY(market, code, start_date))""")
    rows = fetch_twse() + fetch_tpex()
    con.executemany("INSERT OR REPLACE INTO disposition VALUES(?,?,?,?,?,?,?,?)",
                    [r for r in rows if r[4]])
    con.commit()
    n = con.execute("select count(*), count(distinct code), min(announce_date), max(announce_date) "
                    "from disposition").fetchone()
    print(f"完成: disposition {n[0]}筆 / {n[1]}檔 / {n[2]}~{n[3]}")
    con.close()


if __name__ == "__main__":
    main()
