# -*- coding: utf-8 -*-
"""MoneyDJ CB發行公告資金用途抓取(使用者2026-07-16提案:董事會公告的募得價款用途分類
——償還借款=營運普通 vs 充實營運資金/擴產=成長想像,對股價展望不同)
方法: 沿用fetch_moneydj_revenue.py驗證過的單日查詢法(關鍵字=轉換公司債),
      標題含「決議發行」→抓內文→regex「募得價款之用途及運用計畫/募集資金用途」→關鍵字分類
表: cb_purpose(含原文text+四旗標) / cb_purpose_done_days(斷點續傳)
用法: python fetch_cb_purpose.py [--start 2019-01-01] [--test]  (--test只跑最近5天驗證解析)
"""
import argparse
import random
import re
import sqlite3
import time
from datetime import date, timedelta

import pandas as pd
import requests
from bs4 import BeautifulSoup

DB = "capital_flow.db"
BASE_URL = ("https://www.moneydj.com/kmdj/search/list.aspx?"
            "_Query_=%E8%BD%89%E6%8F%9B%E5%85%AC%E5%8F%B8%E5%82%B5&_QueryType_=NW")
ART_URL = "https://www.moneydj.com/kmdj/news/newsviewer.aspx?a={}"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")
DELAY_DAY, DELAY_ART = 3.0, 1.5

TITLE_PAT = re.compile(r"^(?P<name>\S+?)\s*(?:本公司)?董事會決議(?:發行|辦理|通過發行).{0,20}?"
                       r"第(?P<nth>[一二三四五六七八九十\d]+)次(?P<sec>有擔保|無擔保)?")
PURPOSE_PAT = re.compile(r"(?:募得價款之?用途及運用計畫|募集資金用途|資金用途)[:：]?\s*"
                         r"(?P<txt>.{2,120}?)(?:。|\n|\r|(?:\d+\.))")
CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
SUFFIX_ALIASES = ["-創", "-DR", "-KY創", "-KY"]


def classify(txt):
    return {"f_repay": int(bool(re.search(r"償還|還款|償付", txt))),
            "f_working": int("營運資金" in txt),
            "f_capex": int(bool(re.search(r"資本支出|購置|設備|擴建|新建|廠房|擴充產能|機器", txt))),
            "f_invest": int("轉投資" in txt)}


def load_name_map():
    df = pd.read_csv("tw_all_listed.csv", dtype={"code": str})
    m = {}
    for _, r in df.iterrows():
        m.setdefault(r["name"], r["code"])
        for suf in SUFFIX_ALIASES:
            if r["name"].endswith(suf):
                m.setdefault(r["name"][: -len(suf)], r["code"])
    return m


def query_day(session, day_str):
    r0 = session.get(BASE_URL, timeout=15)
    r0.encoding = "utf-8"
    soup = BeautifulSoup(r0.text, "html.parser")

    def val(n):
        t = soup.find("input", {"name": n})
        return t.get("value", "") if t else ""

    ymd = day_str.replace("-", "/")
    data = {
        "__VIEWSTATE": val("__VIEWSTATE"),
        "__VIEWSTATEGENERATOR": val("__VIEWSTATEGENERATOR"),
        "__EVENTVALIDATION": val("__EVENTVALIDATION"),
        "__EVENTTARGET": "", "__EVENTARGUMENT": "",
        "ctl00$ctl00$MainContent$Functions$dp$tbKeyword": "轉換公司債",
        "ctl00$ctl00$MainContent$Functions$dp$SearchCount": "300",
        "ctl00$ctl00$MainContent$Functions$dp$txtStart": ymd,
        "ctl00$ctl00$MainContent$Functions$dp$txtEnd": ymd,
        "ctl00$ctl00$MainContent$Functions$dp$btnDateSearch.x": str(random.randint(5, 20)),
        "ctl00$ctl00$MainContent$Functions$dp$btnDateSearch.y": str(random.randint(5, 20)),
    }
    r1 = session.post(BASE_URL, data=data, timeout=20)
    r1.encoding = "utf-8"
    soup2 = BeautifulSoup(r1.text, "html.parser")
    table = soup2.find("table", {"id": "MainContent_Contents_data_gv"})
    out = []
    if not table:
        return out
    for tr in table.find_all("tr")[1:]:
        tds = tr.find_all("td")
        if len(tds) < 2:
            continue
        a = tds[0].find("a")
        if not a:
            continue
        title = a.get_text(strip=True)
        href = a.get("href", "")
        if "a=" not in href:
            continue
        if "決議" not in title or "轉換公司債" not in title or "海外" in title:
            continue
        if "發行" not in title or "停止轉換" in title or "除息" in title or "除權" in title:
            continue
        out.append({"article_id": href.split("a=")[-1], "title": title,
                    "announce_dt": tds[1].get_text(strip=True)})
    return out


def fetch_article(session, art_id):
    r = session.get(ART_URL.format(art_id), timeout=20)
    r.encoding = "utf-8"
    soup = BeautifulSoup(r.text, "html.parser")
    return soup.get_text(" ", strip=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2019-01-01")
    ap.add_argument("--test", action="store_true")
    args = ap.parse_args()

    name_map = load_name_map()
    conn = sqlite3.connect(DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS cb_purpose (
        article_id TEXT PRIMARY KEY, code TEXT, name TEXT, nth INTEGER, secured TEXT,
        announce_dt TEXT, title TEXT, purpose_text TEXT,
        f_repay INTEGER, f_working INTEGER, f_capex INTEGER, f_invest INTEGER)""")
    conn.execute("CREATE TABLE IF NOT EXISTS cb_purpose_done_days (day TEXT PRIMARY KEY)")
    conn.commit()

    today = date.today()
    if args.test:
        days = [today - timedelta(days=i) for i in range(5)]
    else:
        d0 = date.fromisoformat(args.start)
        days = [d0 + timedelta(days=i) for i in range((today - d0).days + 1)]
    done = set(r[0] for r in conn.execute("SELECT day FROM cb_purpose_done_days"))
    todo = [d for d in sorted(days) if str(d) not in done or args.test]
    print(f"待查 {len(todo)} 天 ({todo[0]}~{todo[-1]})", flush=True)

    session = requests.Session()
    session.headers.update({"User-Agent": UA})
    n_hit = n_parsed = 0
    for i, day in enumerate(todo):
        ds = str(day)
        try:
            items = query_day(session, ds)
        except Exception as e:
            print(f"  {ds}: {type(e).__name__}, 跳過待補", flush=True)
            time.sleep(10)
            continue
        for it in items:
            n_hit += 1
            m = TITLE_PAT.match(it["title"])
            name = m.group("name") if m else it["title"].split()[0]
            nth_raw = m.group("nth") if m else None
            nth = (CN_NUM.get(nth_raw) if nth_raw in CN_NUM
                   else int(nth_raw) if nth_raw and nth_raw.isdigit() else None)
            code = name_map.get(name)
            try:
                time.sleep(DELAY_ART + random.random())
                body = fetch_article(session, it["article_id"])
                pm = PURPOSE_PAT.search(body)
                ptxt = pm.group("txt").strip() if pm else ""
            except Exception as e:
                print(f"  文章{it['article_id'][:8]}: {type(e).__name__}", flush=True)
                ptxt = ""
            fl = classify(ptxt) if ptxt else dict(f_repay=None, f_working=None,
                                                  f_capex=None, f_invest=None)
            if ptxt:
                n_parsed += 1
            conn.execute("INSERT OR REPLACE INTO cb_purpose VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                         (it["article_id"], code, name, nth,
                          m.group("sec") if m and m.group("sec") else "",
                          it["announce_dt"], it["title"], ptxt,
                          fl["f_repay"], fl["f_working"], fl["f_capex"], fl["f_invest"]))
            if args.test:
                print(f"  [{ds}] {it['title'][:40]} | code={code} nth={nth} | {ptxt[:50]}",
                      flush=True)
        conn.execute("INSERT OR REPLACE INTO cb_purpose_done_days VALUES (?)", (ds,))
        conn.commit()
        if (i + 1) % 50 == 0:
            print(f"進度 {i + 1}/{len(todo)} 天, 命中{n_hit}篇/解析成功{n_parsed}", flush=True)
        time.sleep(DELAY_DAY + random.random())
    n = conn.execute("SELECT COUNT(*), COUNT(purpose_text) FROM cb_purpose "
                     "WHERE purpose_text<>''").fetchone()
    print(f"cb_purpose: 有用途文字{n[0]}筆; 本次命中{n_hit}/解析{n_parsed}", flush=True)
    conn.close()


if __name__ == "__main__":
    main()
