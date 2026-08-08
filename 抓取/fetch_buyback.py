# -*- coding: utf-8 -*-
"""台股庫藏股(買回本公司股份)全歷史 -> DB tw_buyback
來源: 公開資訊觀測站 mopsov.twse.com.tw/mops/web/ajax_t35sc09
      「上市/上櫃公司買回自己公司股份彙總統計表」,免登入POST。
⚠2026-08-07實測發現: **一次查詢即回傳該市場全部歷史**(民國90年起,上市3,581筆),
  yy/mm參數不影響回傳範圍——故只需2次請求(sii+otc),非逐月240次。

欄位對應(表頭18欄,資料列20格: 價格區間與買回期間各拆兩格):
  0序號 1公司代號 2公司名稱 3董事會決議日 4買回目的 5買回金額上限 6預定買回股數
  7價格區間最低 8最高 9買回期間起 10迄 11是否執行完畢 12買回達一定標準資料
  13本次已買回股數 14已註銷或轉讓股數 15已買回佔預定比例% 16已買回總金額
  17平均每股買回價格 18買回股數佔已發行比例% 19未執行完畢原因
買回目的代碼: 1=轉讓股份予員工 2=股權轉換(可轉債/特別股等) 3=維護公司信用及股東權益(=護盤型)
日期: 民國年轉西元;「累計」列(公司多次買回的加總)略過不入庫。

研究定位(三問): ①誰被迫交易?——公司宣告後在期限內有執行壓力=**價格不敏感的實際買方**
(專案少見的非自願買盤);②資訊新嗎?——董事會決議公告日為事件起點,當日公開;
③為何沒被吃掉?——台股庫藏股常被視為作帳/護盤而市場半信半疑,**宣告 vs 實際執行率**差異大,
「宣告後真的買」與「宣告了不買」可拆真假訊號(本表有執行率欄位,是這條線最有價值的角度)。

用法: python 抓取/fetch_buyback.py         # 全量重抓(2次請求,約1分鐘)
產出: capital_flow.db.tw_buyback (PRIMARY KEY: code+board_date)
"""
import re
import sqlite3
import sys
import time
from datetime import date

import requests
from bs4 import BeautifulSoup

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DB = "capital_flow.db"
URL = "https://mopsov.twse.com.tw/mops/web/ajax_t35sc09"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
HEADERS = {"User-Agent": UA, "Referer": "https://mopsov.twse.com.tw/mops/web/t35sc09"}
PURPOSE = {"1": "轉讓員工", "2": "股權轉換", "3": "維護信用及股東權益"}


def roc_to_iso(s):
    """民國日期 97/11/12 -> 2008-11-12;非日期回None。"""
    if not s or "/" not in s:
        return None
    m = re.match(r"^(\d{2,3})/(\d{1,2})/(\d{1,2})$", s.strip())
    if not m:
        return None
    y, mo, d = int(m.group(1)) + 1911, int(m.group(2)), int(m.group(3))
    try:
        return date(y, mo, d).isoformat()
    except ValueError:
        return None


def num(s):
    if s is None:
        return None
    s = s.replace(",", "").strip()
    if s in ("", "----", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def fetch_market(typek):
    for attempt in range(3):
        try:
            r = requests.post(URL, data={"encodeURIComponent": "1", "step": "1", "firstin": "1",
                                         "off": "1", "TYPEK": typek, "yy": "115", "mm": "07"},
                              headers=HEADERS, timeout=90)
            r.encoding = "utf-8"
            soup = BeautifulSoup(r.text, "html.parser")
            tables = sorted(soup.find_all("table"), key=lambda t: -len(t.find_all("tr")))
            if not tables:
                raise ValueError("找不到表格")
            rows = []
            seen = set()
            for tr in tables[0].find_all("tr"):
                c = [x.get_text(strip=True) for x in tr.find_all("td")]
                if len(c) < 19 or not c[1].isdigit() or c[0] == "累計":
                    continue
                bd = roc_to_iso(c[3])
                if bd is None:
                    continue
                key = (c[1], bd)
                if key in seen:      # 巢狀表格會重複輸出同一列
                    continue
                seen.add(key)
                rows.append((
                    c[1], bd, c[2], "上市" if typek == "sii" else "上櫃",
                    c[4], PURPOSE.get(c[4], c[4]), num(c[5]), num(c[6]),
                    num(c[7]), num(c[8]), roc_to_iso(c[9]), roc_to_iso(c[10]),
                    c[11], num(c[13]), num(c[14]), num(c[15]), num(c[16]),
                    num(c[17]), num(c[18]), (c[19][:200] if len(c) > 19 else None),
                    date.today().isoformat()))
            return rows
        except Exception as e:
            wait = 15 * (attempt + 1)
            print(f"  {typek}: 第{attempt + 1}次失敗({e}), 退避{wait}s", flush=True)
            time.sleep(wait)
    return []


def main():
    conn = sqlite3.connect(DB, timeout=30)
    conn.execute("""CREATE TABLE IF NOT EXISTS tw_buyback(
        code TEXT, board_date TEXT, name TEXT, market TEXT,
        purpose_code TEXT, purpose TEXT, amount_cap REAL, planned_shares REAL,
        price_low REAL, price_high REAL, period_start TEXT, period_end TEXT,
        completed TEXT, bought_shares REAL, cancelled_shares REAL,
        exec_pct REAL, bought_amount REAL, avg_price REAL, pct_of_capital REAL,
        reason TEXT, fetched TEXT,
        PRIMARY KEY(code, board_date))""")
    total = 0
    for typek, lab in (("sii", "上市"), ("otc", "上櫃")):
        rows = fetch_market(typek)
        print(f"{lab}: 取得{len(rows):,}筆", flush=True)
        if rows:
            conn.executemany(
                "INSERT OR REPLACE INTO tw_buyback VALUES (" + ",".join(["?"] * 21) + ")", rows)
            conn.commit()
            total += len(rows)
        time.sleep(3)
    n, dmin, dmax, nc = conn.execute(
        "select count(*), min(board_date), max(board_date), count(distinct code) "
        "from tw_buyback").fetchone()
    n_exec = conn.execute("select count(*) from tw_buyback where exec_pct is not null").fetchone()[0]
    by_p = conn.execute("select purpose, count(*) from tw_buyback group by purpose order by 2 desc").fetchall()
    print(f"\n驗證: tw_buyback {n:,}筆 / {nc}家 / {dmin}~{dmax}; 有執行率{n_exec:,}筆")
    print("買回目的分布:", by_p)
    print("近5筆:")
    for r in conn.execute("select code,name,board_date,purpose,planned_shares,exec_pct,avg_price "
                          "from tw_buyback order by board_date desc limit 5"):
        print("  ", r)
    conn.close()


if __name__ == "__main__":
    main()
