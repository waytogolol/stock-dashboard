# -*- coding: utf-8 -*-
"""注意股票歷史庫(TWSE+TPEx官方查詢) -> capital_flow.db (attention)
用途: 處置前「注意」階段研究(使用者2026-07-19/20裁示):處置研究時已知完全沒抓過這一層,
     是「注意→處置」升級路徑與「處置前run-up」三線合一考卷的資料底座
來源: TWSE rwd/zh/announcement/notice(西元參數) + TPEx www/zh-tw/bulletin/attention(民國參數)
範圍: 2019-01起,季度分塊,免API金鑰;僅收4位數字股票代碼(權證/受益證券等衍生商品濾除,
     注意股票觸發率遠高於一般股票,不濾會淹沒股票訊號)
欄位: 市場/代號/名稱/公告日/累計次數/注意事項原文/觸發款別(1-13逗號分隔,對照官方13款規則)/收盤價/本益比
用法: python fetch_attention.py
"""
import re
import sqlite3
import time
from datetime import date

import requests

H = {"User-Agent": "Mozilla/5.0"}

CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7,
          "八": 8, "九": 9, "十": 10, "十一": 11, "十二": 12, "十三": 13}


def roc2iso(s):
    m = re.search(r"(\d{2,3})[./](\d{1,2})[./](\d{1,2})", s or "")
    if not m:
        return None
    return f"{int(m.group(1)) + 1911}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"


def parse_triggers(reason):
    nums = sorted({CN_NUM[c] for c in re.findall(r"第([一二三四五六七八九十]{1,3})款", reason or "")
                   if c in CN_NUM})
    return ",".join(str(n) for n in nums)


def to_float(s):
    s = str(s).strip()
    if not s or s in ("-----", "N/A", "--"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def quarters():
    today = date.today().strftime("%Y%m%d")
    for y in range(2019, date.today().year + 1):
        for m in (1, 4, 7, 10):
            a = f"{y}{m:02d}01"
            eb = {1: "0331", 4: "0630", 7: "0930", 10: "1231"}[m]
            b = f"{y}{eb}"
            if a > today:
                return
            yield a, b


def fetch_twse():
    rows = []
    for a, b in quarters():
        for attempt in range(3):
            try:
                r = requests.get("https://www.twse.com.tw/rwd/zh/announcement/notice",
                                 params={"startDate": a, "endDate": b, "response": "json"},
                                 headers=H, timeout=30)
                j = r.json()
                for d in (j.get("data") or []):
                    code = str(d[1]).strip()
                    if not re.fullmatch(r"\d{4}", code):
                        continue  # 排除權證/受益證券等非股票代碼
                    reason = re.sub(r"<[^>]+>", "", str(d[4])).strip()  # 去除紅字<font>標籤
                    rows.append(("上市", code, str(d[2]).strip(), roc2iso(str(d[5])),
                                 int(d[3]) if str(d[3]).isdigit() else None,
                                 reason, parse_triggers(reason),
                                 to_float(d[6]), to_float(d[7])))
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
                r = requests.get("https://www.tpex.org.tw/www/zh-tw/bulletin/attention",
                                 params={"startDate": ra, "endDate": rb, "response": "json"},
                                 headers=H, timeout=30)
                j = r.json()
                t = (j.get("tables") or [{}])[0]
                for d in (t.get("data") or []):
                    code = str(d[1]).strip()
                    if not re.fullmatch(r"\d{4}", code):
                        continue
                    reason = re.sub(r"<[^>]+>", "", str(d[4])).strip()
                    rows.append(("上櫃", code, str(d[2]).strip(), roc2iso(str(d[5])),
                                 int(d[3]) if str(d[3]).isdigit() else None,
                                 reason, parse_triggers(reason),
                                 to_float(d[6]), to_float(d[7])))
                print(f"TPEX {ra}: 累計{len(rows)}", flush=True)
                break
            except Exception as e:
                print(f"TPEX {ra}: {type(e).__name__} 重試", flush=True)
                time.sleep(5)
        time.sleep(3)
    return rows


def main():
    con = sqlite3.connect("capital_flow.db")
    con.execute("""CREATE TABLE IF NOT EXISTS attention(
        market TEXT, code TEXT, name TEXT, announce_date TEXT, cum_count INTEGER,
        reason TEXT, triggers TEXT, close_price REAL, pe REAL,
        PRIMARY KEY(market, code, announce_date))""")
    rows = fetch_twse() + fetch_tpex()
    con.executemany("INSERT OR REPLACE INTO attention VALUES(?,?,?,?,?,?,?,?,?)",
                    [r for r in rows if r[3]])
    con.commit()
    n = con.execute("select count(*), count(distinct code), min(announce_date), max(announce_date) "
                    "from attention").fetchone()
    print(f"完成: attention {n[0]}筆 / {n[1]}檔 / {n[2]}~{n[3]}")
    con.close()


if __name__ == "__main__":
    main()
