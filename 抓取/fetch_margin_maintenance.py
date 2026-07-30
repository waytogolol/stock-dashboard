# -*- coding: utf-8 -*-
"""官方大盤融資維持率 例行增量 -> capital_flow.db (margin_maintenance_official)
背景: 2026-07-15 Backer升級時一次性落庫(2002起)後被標成「凍結線,無自動腳本」,
     2026-07-28使用者發現溫度計「融資警戒帶」卡在7/14——本腳本補上例行更新,已入update_all每日組。
雙源設計(2026-07-28使用者提案公式版,當日驗證收工):
  主源=FinMind TaiwanTotalExchangeMarginMaintenance(⚠Backer限定,效期2026-08-15)。
  備援=公式版(全公開資料,8/15後自動接手,亦可--calc強制):
    維持率 = Σ(個股融資餘額張×1000×官方收盤價) / 融資總金額餘額 ×100
    分子=margin_flow.fin_bal(TWSE MI_MARGN逐股,fetch_margin.py先跑)×MI_INDEX全市場收盤(含ETF);
    分母=MI_MARGN selectType=MS「信用交易統計」融資金額今日餘額(仟元)。
    對帳驗證(scratch validate_mm_formula2.py): 2024~2026測試日誤差<=0.14pp、最近日-0.01pp=口徑完全還原
    (證實FinMind數列=上市/純融資口徑);2022-23個別日-1~-2.7pp為歷史資料端差異,live前瞻無虞。
    ⚠公式版分子價格覆蓋要用MI_INDEX(fm_daily_price缺ETF約200檔會低估7pp,勿省這一刀)。
上櫃線(2026-07-28使用者追問「上櫃是否也做得出來」,同日驗證收工): margin_maintenance_otc表,
  純公式版(無FinMind對應數列): Σ(TPEX margin/balance逐股資餘額張×1000×dailyQuotes收盤)÷
  balance.summary融資金(仟元)今日餘額;覆蓋99.5-100%,API歷史至少回到2019,壓力日與上市形狀一致
  (2025-04-09上櫃128.99 vs 上市130.36)但水位不同步=中小型槓桿獨立資訊;回補新到舊冪等,
  每run上限350日(update_all步驟3600s內),--backfill不設上限一次補完。
注意: 官方源有毛刺(如2020-03-24=92.6%),照舊原樣入庫,讀取端自行濾<100(既有慣例)。
用法: python fetch_margin_maintenance.py [--calc 跳過FinMind直接用公式版] [--backfill 上櫃回補不設上限]
"""
import sqlite3
import sys
import time

import requests

sys.stdout.reconfigure(encoding="utf-8")
DB = "capital_flow.db"
URL = "https://api.finmindtrade.com/api/v4/data"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
SLEEP = 3.0


def fetch_finmind(last):
    """回傳[(date, ratio)];失敗(含Backer到期)回傳None交給公式版。"""
    try:
        token = open("finmind_token.txt").read().strip()
        r = requests.get(URL, params={"dataset": "TaiwanTotalExchangeMarginMaintenance",
                                      "start_date": last, "token": token}, timeout=60)
        j = r.json()
        if j.get("status") != 200:
            print(f"FinMind失敗: {j.get('status')} {str(j.get('msg'))[:60]} → 改用公式版")
            return None
        return [(d["date"], d["TotalExchangeMarginMaintenance"]) for d in j.get("data", [])]
    except Exception as e:
        print(f"FinMind例外: {e} → 改用公式版")
        return None


def calc_day(conn, d):
    """公式版單日: 需margin_flow當日資料(fetch_margin.py先跑);回傳ratio或None。"""
    rows = conn.execute("SELECT code, fin_bal FROM margin_flow WHERE date=?", (d,)).fetchall()
    if not rows:
        print(f"  {d}: margin_flow無資料(先跑fetch_margin.py),跳過")
        return None
    d8 = d.replace("-", "")
    r = requests.get("https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN",
                     params={"date": d8, "selectType": "MS", "response": "json"},
                     headers=UA, timeout=30)
    den = None
    for tb in r.json().get("tables", []):
        for row in tb.get("data") or []:
            if str(row[0]).startswith("融資金額"):
                den = float(str(row[5]).replace(",", "")) * 1000
    if not den:
        print(f"  {d}: MS彙總無融資金額,跳過")
        return None
    time.sleep(SLEEP)
    r = requests.get("https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX",
                     params={"date": d8, "type": "ALLBUT0999", "response": "json"},
                     headers=UA, timeout=60)
    px = {}
    for tb in r.json().get("tables", []):
        f = tb.get("fields") or []
        if "收盤價" in f and "證券代號" in f:
            ic, ip = f.index("證券代號"), f.index("收盤價")
            for row in tb.get("data") or []:
                try:
                    px[str(row[ic]).strip()] = float(str(row[ip]).replace(",", ""))
                except (ValueError, IndexError):
                    continue
    num = sum(bal * 1000 * px[c] for c, bal in rows if c in px)
    miss = sum(1 for c, _ in rows if c not in px)
    ratio = round(num / den * 100, 3)
    print(f"  {d}: 公式版={ratio}% (缺價{miss}檔)")
    return ratio


OTC_START = "2011-01-01"  # TPEX API實測深度斷點:2011-01有/2010-07 fallback(防呆會擋)


def roc(d):
    y, m, dd = d.split("-")
    return f"{int(y) - 1911}/{m}/{dd}"


def otc_calc_day(d):
    """上櫃公式版單日;回傳ratio或None。
    ⚠防呆(2026-07-28發現): TPEX API對超出深度的舊日期會fallback回傳「最新一日」資料,
    必須核對回應的date欄=請求日,否則歷史會被今天的數字污染。"""
    r = requests.get("https://www.tpex.org.tw/www/zh-tw/margin/balance",
                     params={"date": roc(d), "response": "json"}, headers=UA, timeout=30)
    j = r.json()
    # 回應date格式=YYYYMMDD(如20120702),與請求日去分隔後比對
    if str(j.get("date", "")).replace("/", "").replace("-", "") != d.replace("-", ""):
        return None
    tbs = j.get("tables") or []
    if not tbs or not (tbs[0].get("data") or []):
        return None
    tb = tbs[0]
    den = None
    for row in tb.get("summary") or []:
        if len(row) > 6 and str(row[1]).startswith("融資金"):
            den = float(str(row[6]).replace(",", "")) * 1000
    if not den:
        return None
    bals = []
    for row in tb.get("data") or []:
        try:
            bals.append((str(row[0]).strip(), float(str(row[6]).replace(",", ""))))
        except (ValueError, IndexError):
            continue
    time.sleep(SLEEP)
    r = requests.get("https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes",
                     params={"date": roc(d), "response": "json"}, headers=UA, timeout=60)
    px = {}
    for tb2 in r.json().get("tables") or []:
        f = tb2.get("fields") or []
        if "收盤" in f and "代號" in f:
            ic, ip = f.index("代號"), f.index("收盤")
            for row in tb2.get("data") or []:
                try:
                    px[str(row[ic]).strip()] = float(str(row[ip]).replace(",", ""))
                except (ValueError, IndexError):
                    continue
    if not px:
        return None
    num = sum(b * 1000 * px[c] for c, b in bals if c in px)
    return round(num / den * 100, 3)


def update_otc(conn, no_cap, d_from=None, d_to=None):
    conn.execute("CREATE TABLE IF NOT EXISTS margin_maintenance_otc"
                 "(date TEXT PRIMARY KEY, ratio REAL)")
    have = {r[0] for r in conn.execute("SELECT date FROM margin_maintenance_otc")}
    days = [r[0] for r in conn.execute(
        "SELECT DISTINCT date FROM index_daily WHERE market='TAIEX' AND date>=? "
        "ORDER BY date DESC", (OTC_START,))]
    if d_from:
        days = [d for d in days if d_from <= d <= d_to]
    todo = [d for d in days if d not in have]
    if not todo:
        print("上櫃維持率: 已最新")
        return
    cap = len(todo) if no_cap else 350
    print(f"上櫃維持率(公式版): 待補{len(todo)}日,本輪跑{min(cap, len(todo))}日(新到舊,冪等可中斷)")
    ok = 0
    for i, d in enumerate(todo[:cap]):
        try:
            v = otc_calc_day(d)
        except Exception as e:
            print(f"  {d}: 例外 {str(e)[:60]}")
            v = None
        if v is not None:
            conn.execute("INSERT OR REPLACE INTO margin_maintenance_otc VALUES (?,?)", (d, v))
            conn.commit()
            ok += 1
        if (i + 1) % 50 == 0:
            print(f"  [{i + 1}/{min(cap, len(todo))}] 成功{ok}", flush=True)
        time.sleep(SLEEP)
    lo, hi, n = conn.execute(
        "SELECT MIN(date), MAX(date), COUNT(*) FROM margin_maintenance_otc").fetchone()
    print(f"上櫃維持率: 本輪+{ok}日, 表{lo}~{hi}共{n:,}筆")


def main():
    global SLEEP
    force_calc = "--calc" in sys.argv
    if "--fast" in sys.argv:  # 回補衝刺用,例行仍3秒禮貌限速
        SLEEP = 1.0
    if "--range" in sys.argv:  # 平行回補工人: --range 起日 迄日 (只跑上櫃段,跳過FinMind)
        i = sys.argv.index("--range")
        conn = sqlite3.connect(DB)
        update_otc(conn, no_cap=True, d_from=sys.argv[i + 1], d_to=sys.argv[i + 2])
        conn.close()
        return
    conn = sqlite3.connect(DB)
    last = conn.execute("SELECT MAX(date) FROM margin_maintenance_official").fetchone()[0]
    rows = None if force_calc else fetch_finmind(last)
    src = "FinMind"
    if rows is None:
        src = "公式版(TWSE公開)"
        days = [r[0] for r in conn.execute(
            "SELECT DISTINCT date FROM fm_daily_price WHERE date>? ORDER BY date", (last,))]
        rows = []
        for d in days:
            v = calc_day(conn, d)
            if v is not None:
                rows.append((d, v))
            time.sleep(SLEEP)
    conn.executemany("INSERT OR REPLACE INTO margin_maintenance_official VALUES (?,?)", rows)
    conn.commit()
    new_last, n = conn.execute(
        "SELECT MAX(date), COUNT(*) FROM margin_maintenance_official").fetchone()
    print(f"完成({src}): {last} -> {new_last} (+{len(rows)}筆覆寫含重疊, 總{n:,}筆)")
    update_otc(conn, no_cap="--backfill" in sys.argv)
    conn.close()


if __name__ == "__main__":
    main()
