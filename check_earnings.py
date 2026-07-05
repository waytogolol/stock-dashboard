# -*- coding: utf-8 -*-
"""查未來N天美股財報日曆 + 台股法人說明會排程，比對我們的觀察名單(us_top700.csv / tw_top300.csv)，
只列出有在我們追蹤名單裡的公司。

資料源：
  美股財報：Nasdaq官方API(api.nasdaq.com/api/calendar/earnings)，免登入
  台股法說會：公開資訊觀測站MOPS(mopsov.twse.com.tw)，免登入，按月查詢(分上市sii/上櫃otc)

用法: python check_earnings.py [天數，預設14天]
"""
import sys
from datetime import date, timedelta

import pandas as pd
import requests
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

TIME_LABEL = {
    "time-pre-market": "盤前",
    "time-after-hours": "盤後",
    "time-not-supplied": "未公布時段",
    "time-during-market": "盤中",
}


def fetch_us_earnings_calendar(days=14):
    headers = {"User-Agent": UA, "Accept": "application/json, text/plain, */*"}
    rows = []
    for offset in range(days + 1):
        d = date.today() + timedelta(days=offset)
        r = requests.get(
            "https://api.nasdaq.com/api/calendar/earnings", params={"date": d.isoformat()}, headers=headers, timeout=15
        )
        j = r.json()
        day_rows = (j.get("data") or {}).get("rows") or []
        for row in day_rows:
            rows.append({
                "date": d.isoformat(),
                "symbol": row["symbol"],
                "name": row["name"],
                "time": TIME_LABEL.get(row.get("time"), row.get("time", "")),
                "market_cap": row.get("marketCap", ""),
                "eps_forecast": row.get("epsForecast", ""),
            })
    return pd.DataFrame(rows)


def check_us_earnings(days=14):
    print(f"\n===== 美股財報日曆(未來{days}天) =====")
    calendar = fetch_us_earnings_calendar(days)
    print(f"全市場共 {len(calendar)} 筆財報公告")

    us_list = pd.read_csv("us_top700.csv")
    classification = pd.read_csv("all_classified.csv", dtype={"代碼": str})
    us_class = classification[classification["國家"] == "美"]
    groups_per_symbol = us_class.groupby("代碼")["主族群"].apply(lambda x: ", ".join(sorted(set(x))))

    watch = calendar[calendar["symbol"].isin(us_list["code"])].copy()
    watch = watch.merge(us_list[["code", "rank"]], left_on="symbol", right_on="code", how="left")
    watch["主族群"] = watch["symbol"].map(groups_per_symbol).fillna("未分類")
    watch = watch.sort_values(["date", "rank"])[["date", "time", "symbol", "name", "rank", "主族群", "market_cap", "eps_forecast"]]
    watch.columns = ["日期", "時段", "代碼", "公司", "成交金額排名", "主族群", "市值", "EPS預估"]

    watch.to_csv("us_earnings_watch.csv", index=False, encoding="utf-8-sig")
    print(f"觀察名單(us_top700)裡有 {len(watch)} 檔即將公布財報：\n")
    print(watch.to_string(index=False) if len(watch) else "(無)")
    return watch


def fetch_tw_investor_meetings(roc_year, month, typek):
    headers = {"User-Agent": UA, "Referer": "https://mopsov.twse.com.tw/mops/web/t100sb02_1"}
    data = {"step": "1", "firstin": "true", "off": "1", "year": str(roc_year), "month": f"{month:02d}", "co_id": "", "TYPEK": typek}
    r = requests.post("https://mopsov.twse.com.tw/mops/web/ajax_t100sb02_1", data=data, headers=headers, timeout=20)
    soup = BeautifulSoup(r.text, "html.parser")
    table = soup.select_one("table#myTable")
    rows = []
    if table is None:
        return rows
    for tr in table.select("tr[data-type=body]"):
        tds = tr.find_all("td")
        if len(tds) < 6:
            continue
        code, name, roc_date, time_, location, summary = [tds[i].get_text(strip=True) for i in range(6)]
        try:
            y, m, d = roc_date.split("/")
            iso_date = date(int(y) + 1911, int(m), int(d)).isoformat()
        except ValueError:
            continue
        rows.append({"date": iso_date, "code": code, "name": name, "time": time_, "location": location, "summary": summary})
    return rows


def check_tw_earnings(days=14):
    print(f"\n===== 台股法人說明會排程(未來{days}天) =====")
    today = date.today()
    end = today + timedelta(days=days)
    months = sorted({(today.year, today.month), (end.year, end.month)})

    all_rows = []
    for y, m in months:
        roc_year = y - 1911
        for typek in ["sii", "otc"]:
            all_rows.extend(fetch_tw_investor_meetings(roc_year, m, typek))

    calendar = pd.DataFrame(all_rows).drop_duplicates(subset=["code", "date"])
    calendar = calendar[(calendar["date"] >= today.isoformat()) & (calendar["date"] <= end.isoformat())]
    print(f"全市場共 {len(calendar)} 筆法說會公告(未來{days}天內)")

    tw_list = pd.read_csv("tw_top300.csv", dtype={"code": str})
    classification = pd.read_csv("all_classified.csv", dtype={"代碼": str})
    tw_class = classification[classification["國家"] == "台"]
    groups_per_code = tw_class.groupby("代碼")["主族群"].apply(lambda x: ", ".join(sorted(set(x))))

    watch = calendar[calendar["code"].isin(tw_list["code"])].copy()
    watch = watch.merge(tw_list[["code", "rank"]], on="code", how="left")
    watch = watch[watch["rank"] <= 200]   # 只追蹤成交值前200名（儀表板可見範圍）
    watch["主族群"] = watch["code"].map(groups_per_code).fillna("未分類")
    watch = watch.sort_values(["date", "rank"])[["date", "time", "code", "name", "rank", "主族群", "location", "summary"]]
    watch.columns = ["日期", "時間", "代碼", "公司", "成交金額排名", "主族群", "地點", "摘要"]

    watch.to_csv("tw_earnings_watch.csv", index=False, encoding="utf-8-sig")
    print(f"觀察名單(tw_top300)裡有 {len(watch)} 檔即將開法說會：\n")
    print(watch.drop(columns=["地點", "摘要"]).to_string(index=False) if len(watch) else "(無)")
    return watch


if __name__ == "__main__":
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 14
    check_us_earnings(days)
    check_tw_earnings(days)
    print("\n已存成 us_earnings_watch.csv 和 tw_earnings_watch.csv")
