# -*- coding: utf-8 -*-
"""MoneyDJ月營收新聞逐日抓取：解決官方彙總表沒有「逐公司公告日期」的問題。
每篇新聞標題含公司名+營收+YoY/MoM，時間戳精確到秒，可重建「誰先公布誰後公布」。

日期區間搜尋表單(txtStart/txtEnd)測試多次無法正確套用範圍(伺服器似乎忽略區間,只回傳結束日當天),
改用「單日查詢(起訖同一天)」逐日迴圈——這個方式已驗證100%準確可靠。
用法: python fetch_moneydj_revenue.py [--months N]  (預設回補最近3個月的申報窗口1-15日)
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
BASE_URL = "https://www.moneydj.com/kmdj/search/list.aspx?_Query_=%E7%87%9F%E6%94%B6&_QueryType_=NW"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
DELAY = 3.0

PAT = re.compile(
    r"^(?P<name>\S+?)自?結?\s*(?:(?P<roc_year>\d{2,3})年)?(?P<month>\d{1,2})月(?:合併)?營收"
    r"(?P<revenue>[\d,\.]+)(?P<unit>億|萬)元?[、，]\s*(?:年|月)(?P<dir>增|減)(?P<pct>[\d\.]+)%"
)


def load_name_map():
    df = pd.read_csv("tw_all_listed.csv", dtype={"code": str})
    m = {}
    for _, r in df.iterrows():
        m.setdefault(r["name"], r["code"])
    return m


def parse_title(title, announce_date):
    m = PAT.match(title.strip())
    if not m:
        return None
    g = m.groupdict()
    month = int(g["month"])
    if g["roc_year"]:
        year = int(g["roc_year"]) + 1911
    else:
        ad = announce_date
        year = ad.year if ad.month >= month else ad.year - 1
    revenue = float(g["revenue"].replace(",", "")) * (1e8 if g["unit"] == "億" else 1e4)
    pct = float(g["pct"]) * (1 if g["dir"] == "增" else -1)
    return {"name": g["name"], "year_month": f"{year}{month:02d}", "revenue": revenue, "yoy_pct": pct}


def query_day(session, day_str, name_map, log):
    """查單日(起訖同一天),回傳解析成功的紀錄列表"""
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
        "ctl00$ctl00$MainContent$Functions$dp$tbKeyword": "營收",
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
    if not table:
        return []
    recs = []
    n_skip = 0
    for tr in table.find_all("tr")[1:]:
        tds = tr.find_all("td")
        if len(tds) < 2:
            continue
        a = tds[0].find("a")
        if not a:
            continue
        title = a.get_text(strip=True)
        href = a.get("href", "")
        art_id = href.split("a=")[-1] if "a=" in href else title
        dt_str = tds[1].get_text(strip=True)
        try:
            dt = pd.Timestamp(dt_str)
        except Exception:
            continue
        parsed = parse_title(title, dt.date())
        if parsed is None:
            n_skip += 1
            continue
        code = name_map.get(parsed["name"])
        if code is None:
            log["unmatched_names"][parsed["name"]] = log["unmatched_names"].get(parsed["name"], 0) + 1
            log["unmatched_last_seen"][parsed["name"]] = day_str
            continue
        recs.append({
            "code": code, "name_matched": parsed["name"], "year_month": parsed["year_month"],
            "revenue": parsed["revenue"], "yoy_pct": parsed["yoy_pct"],
            "announce_dt": dt_str, "article_id": art_id, "raw_title": title,
        })
    log["n_rows_seen"] += len(table.find_all("tr")) - 1
    log["n_skipped"] += n_skip
    return recs


def main(months):
    name_map = load_name_map()
    conn = sqlite3.connect(DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS tw_revenue_news (
        article_id TEXT PRIMARY KEY, code TEXT, name_matched TEXT, year_month TEXT,
        revenue REAL, yoy_pct REAL, announce_dt TEXT, raw_title TEXT)""")
    conn.commit()
    conn.execute("""CREATE TABLE IF NOT EXISTS tw_revenue_news_done_days (day TEXT PRIMARY KEY)""")
    conn.commit()
    conn.execute("""CREATE TABLE IF NOT EXISTS tw_revenue_news_unmatched (
        name TEXT PRIMARY KEY, n_seen INTEGER, last_seen TEXT)""")
    conn.commit()

    today = date.today()
    days = []
    y, m = today.year, today.month
    for _ in range(months):
        for d in range(1, 16):
            try:
                day = date(y, m, d)
            except ValueError:
                continue
            if day <= today:
                days.append(day)
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    days = sorted(set(days))

    done_days = set(r[0] for r in conn.execute("SELECT day FROM tw_revenue_news_done_days"))
    days_todo = [d for d in days if str(d) not in done_days]
    print(f"預計查詢 {len(days)} 天 ({days[0]} ~ {days[-1]})，"
          f"已完成跳過 {len(days) - len(days_todo)} 天，待查 {len(days_todo)} 天")

    existing = set(r[0] for r in conn.execute("SELECT article_id FROM tw_revenue_news"))
    session = requests.Session()
    session.headers.update({"User-Agent": UA})

    log = {"unmatched_names": {}, "unmatched_last_seen": {}, "n_rows_seen": 0, "n_skipped": 0}
    total_new = 0
    for i, day in enumerate(days_todo):
        day_str = str(day)
        try:
            recs = query_day(session, day_str, name_map, log)
        except Exception as e:
            print(f"  {day_str} 失敗: {e}")
            time.sleep(10)
            continue
        new_recs = [r for r in recs if r["article_id"] not in existing]
        if new_recs:
            conn.executemany(
                "INSERT OR IGNORE INTO tw_revenue_news VALUES (?,?,?,?,?,?,?,?)",
                [(r["article_id"], r["code"], r["name_matched"], r["year_month"],
                  r["revenue"], r["yoy_pct"], r["announce_dt"], r["raw_title"]) for r in new_recs])
            existing.update(r["article_id"] for r in new_recs)
            total_new += len(new_recs)
        conn.execute("INSERT OR IGNORE INTO tw_revenue_news_done_days VALUES (?)", (day_str,))
        if log["unmatched_names"]:
            conn.executemany(
                """INSERT INTO tw_revenue_news_unmatched VALUES (?,?,?)
                   ON CONFLICT(name) DO UPDATE SET
                       n_seen = tw_revenue_news_unmatched.n_seen + excluded.n_seen,
                       last_seen = excluded.last_seen""",
                [(name, cnt, log["unmatched_last_seen"][name]) for name, cnt in log["unmatched_names"].items()])
            log["unmatched_names"].clear()
            log["unmatched_last_seen"].clear()
        conn.commit()
        print(f"  [{i+1}/{len(days_todo)}] {day_str}: 抓到{len(recs)}筆可解析, 新增{len(new_recs)}筆")
        time.sleep(DELAY + random.uniform(0, 1.5))

    n_unmatched_total = conn.execute("SELECT COUNT(*) FROM tw_revenue_news_unmatched").fetchone()[0]
    print(f"\n完成。新增 {total_new} 筆。累計解析跳過 {log['n_skipped']} 則(格式不符,如季獲利/多子公司/純公告)。")
    print(f"對不到代碼的公司名累計 {n_unmatched_total} 個,已存入 tw_revenue_news_unmatched 表(name/n_seen/last_seen),可事後盤點補別名。")
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--months", type=int, default=3, help="回補最近N個月(每月1-15日),預設3")
    args = parser.parse_args()
    main(args.months)
