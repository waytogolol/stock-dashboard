# -*- coding: utf-8 -*-
"""H-解質資料管線: MoneyDJ每日彙整文「X/X上市櫃公司董監質設異動公告」→ pledge_moves表。
假說(2026-07-17登記): 質押股不能賣,解質=出貨前置腳印(國巨董座2026-06-01解質11,400張→6月底頂)。
方法: 沿用fetch_cb_purpose.py單日查詢法(關鍵字=質設異動),文章內7欄表逐列入庫。
表: pledge_moves(公司/身份/姓名/設質張/解質張/累積張/質權人) / pledge_done_days(斷點續傳)
用法: python fetch_pledge.py [--start 2019-01-01] [--test]  (--test只跑最近7天)
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
HEADERS7 = ["公司", "設質人身份", "設質人姓名", "設質張數", "解質張數", "累積張數", "質權人"]
TITLE_PAT = re.compile(r"^(\d{1,2})/(\d{1,2})上市櫃公司董監質設異動公告$")
SUFFIX_ALIASES = ["-創", "-DR", "-KY創", "-KY"]


def load_name_map():
    # 2026-07-20修: csv名的「*」=減資註記(使用者指正;全市場41檔如國巨*/矽力*-KY/尚凡*),
    # MoneyDJ文章寫的是無星號名→精確比對失敗→該公司整段歷史靜默漏抓
    # (國巨事故:全表1,082列code=None;孤兒列回填=fix_pledge_codes.py)
    df = pd.read_csv("tw_all_listed.csv", dtype={"code": str})
    m = {}
    for _, r in df.iterrows():
        names = {r["name"], r["name"].rstrip("*")}
        for nm in names:
            m.setdefault(nm, r["code"])
            for suf in SUFFIX_ALIASES:
                if nm.endswith(suf):
                    m.setdefault(nm[: -len(suf)], r["code"])
    return m


def query_day(session, day_str):
    r0 = session.get(BASE_URL, timeout=15)
    r0.encoding = "utf-8"
    soup = BeautifulSoup(r0.text, "html.parser")

    def val(n):
        t = soup.find("input", {"name": n})
        return t.get("value", "") if t else ""

    data = {
        "__VIEWSTATE": val("__VIEWSTATE"),
        "__VIEWSTATEGENERATOR": val("__VIEWSTATEGENERATOR"),
        "__EVENTVALIDATION": val("__EVENTVALIDATION"),
        "__EVENTTARGET": "", "__EVENTARGUMENT": "",
        "ctl00$ctl00$MainContent$Functions$dp$tbKeyword": "質設異動",
        "ctl00$ctl00$MainContent$Functions$dp$SearchCount": "300",
        "ctl00$ctl00$MainContent$Functions$dp$txtStart": day_str.replace("-", "/"),
        "ctl00$ctl00$MainContent$Functions$dp$txtEnd": day_str.replace("-", "/"),
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
        a = tr.find("a")
        if not a:
            continue
        title = a.get_text(strip=True)
        href = a.get("href", "")
        if TITLE_PAT.match(title) and "a=" in href:
            out.append({"article_id": href.split("a=")[-1], "title": title})
    return out


def digest_date(title, article_day):
    m = TITLE_PAT.match(title)
    mth, day = int(m.group(1)), int(m.group(2))
    year = article_day.year - 1 if mth > article_day.month else article_day.year
    try:
        return str(date(year, mth, day))
    except ValueError:
        return None


def parse_article(session, art_id):
    r = session.get(ART_URL.format(art_id), timeout=20)
    r.encoding = "utf-8"
    soup = BeautifulSoup(r.text, "html.parser")
    best = None
    for t in soup.find_all("table"):
        rows = t.find_all("tr")
        if rows and [td.get_text(strip=True) for td in rows[0].find_all(["td", "th"])] == HEADERS7:
            best = rows   # 巢狀表重複內容,取最內層(最後一個符合者)
    if not best:
        return []
    out = []
    for tr in best[1:]:
        tds = [td.get_text(strip=True) for td in tr.find_all("td")]
        if len(tds) != 7:
            continue

        def num(s):
            s = s.replace(",", "").strip()
            return int(s) if s.isdigit() else None

        out.append({"company": tds[0].rstrip("*"), "role": tds[1], "pledgor": tds[2],
                    "set_lots": num(tds[3]), "release_lots": num(tds[4]),
                    "cum_lots": num(tds[5]), "pledgee": tds[6]})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2019-01-01")
    ap.add_argument("--test", action="store_true")
    args = ap.parse_args()

    name_map = load_name_map()
    conn = sqlite3.connect(DB, timeout=120)
    conn.execute("""CREATE TABLE IF NOT EXISTS pledge_moves (
        article_id TEXT, digest_date TEXT, company TEXT, code TEXT, role TEXT,
        pledgor TEXT, set_lots INTEGER, release_lots INTEGER, cum_lots INTEGER, pledgee TEXT)""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pledge_date ON pledge_moves(digest_date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pledge_code ON pledge_moves(code)")
    conn.execute("CREATE TABLE IF NOT EXISTS pledge_done_days (day TEXT PRIMARY KEY)")
    conn.commit()

    today = date.today()
    if args.test:
        days = [today - timedelta(days=i) for i in range(7)]
    else:
        d0 = date.fromisoformat(args.start)
        days = [d0 + timedelta(days=i) for i in range((today - d0).days + 1)]
    done = set(r[0] for r in conn.execute("SELECT day FROM pledge_done_days"))
    todo = [d for d in sorted(days) if str(d) not in done or args.test]
    print(f"待查 {len(todo)} 天 ({todo[0]}~{todo[-1]})", flush=True)

    session = requests.Session()
    session.headers.update({"User-Agent": UA})
    n_rows = n_art = 0
    for i, day in enumerate(todo):
        ds = str(day)
        try:
            arts = query_day(session, ds)
            for a in arts:
                dd = digest_date(a["title"], day)
                if dd is None:
                    continue
                time.sleep(DELAY_ART)
                rows = parse_article(session, a["article_id"])
                conn.execute("DELETE FROM pledge_moves WHERE article_id=?", (a["article_id"],))
                for r in rows:
                    conn.execute(
                        "INSERT INTO pledge_moves VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (a["article_id"], dd, r["company"], name_map.get(r["company"]),
                         r["role"], r["pledgor"], r["set_lots"], r["release_lots"],
                         r["cum_lots"], r["pledgee"]))
                n_rows += len(rows)
                n_art += 1
            conn.execute("INSERT OR REPLACE INTO pledge_done_days VALUES (?)", (ds,))
            conn.commit()
        except Exception as e:
            print(f"  {ds} ERR {e} (跳過,下次續傳)", flush=True)
            time.sleep(10)
            continue
        if (i + 1) % 50 == 0 or i == len(todo) - 1:
            print(f"  [{i + 1}/{len(todo)}] {ds} 文章{n_art} 列{n_rows}", flush=True)
        time.sleep(DELAY_DAY)
    conn.close()
    print(f"完成: 文章{n_art} 列{n_rows}", flush=True)


if __name__ == "__main__":
    main()
