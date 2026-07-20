# -*- coding: utf-8 -*-
"""①系統性資料驗證器(每週例行): 通用掃描+跨表一致性+外部抽查(TWSE 2請求)。
輸出PASS/WARN/FAIL行; FAIL=資料損毀要處理, WARN=已知特性或輕微異常。
用法: python validate_db.py   (每週流程末尾跑)
"""
import random
import sqlite3
import sys

import pandas as pd
import requests

DB = "capital_flow.db"
random.seed()
# Windows console cp950編不出≈等字元會炸(2026-07-19每週鏈實測),強制UTF-8輸出
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def flag(level, msg):
    print(f"[{level}] {msg}")


def main():
    conn = sqlite3.connect(DB)

    # --- 1. 通用掃描: 筆數/日期範圍/主鍵重複 ---
    tables = {
        "fm_daily_price": ("code, date", "date"),
        "cb_daily": ("cb_id, date", "date"),
        "cb_inst": ("cb_id, date", "date"),
        "cb_overview": ("cb_id, date", "date"),
        "index_daily": ("market, date", "date"),
        "inst_flow": ("code, date", "date"),
        "margin_flow": ("code, date", "date"),
        "disposition": (None, None),
        "tdcc_weekly": ("code, date", "date"),
        "fm_month_rev": ("code, date", "date"),
    }
    print("=== 1. 通用掃描 ===")
    for t, (pk, dcol) in tables.items():
        try:
            n = conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        except Exception as e:
            flag("FAIL", f"{t}: 表不存在或壞損 {e}")
            continue
        rng = ""
        if dcol:
            lo, hi = conn.execute(f"SELECT min({dcol}), max({dcol}) FROM {t}").fetchone()
            rng = f" {lo}~{hi}"
        dup = 0
        if pk:
            dup = conn.execute(
                f"SELECT count(*) FROM (SELECT {pk} FROM {t} GROUP BY {pk} HAVING count(*)>1)"
            ).fetchone()[0]
        lv = "PASS" if dup == 0 else "FAIL"
        flag(lv, f"{t}: {n:,}筆{rng} 主鍵重複={dup}")

    # --- 2. 跨表一致性 ---
    print("\n=== 2. 跨表一致性 ===")
    # 2a cb_inst 三法人加總 == total_overbuy
    bad = conn.execute("""SELECT count(*) FROM cb_inst
        WHERE abs((fi_buy-fi_sell)+(it_buy-it_sell)+(dealer_buy-dealer_sell)-total_overbuy)>1
        """).fetchone()[0]
    n = conn.execute("SELECT count(*) FROM cb_inst").fetchone()[0]
    flag("PASS" if bad / max(n, 1) < 0.001 else "FAIL",
         f"cb_inst 三法人加總=total_overbuy: 異常{bad}/{n}")
    # 2b cb_daily value ≈ volume×close×1000 (張=面額10萬,價百元報價)
    df = pd.read_sql("SELECT volume, value, close FROM cb_daily "
                     "WHERE volume>0 AND value>0 AND close>0 ORDER BY RANDOM() LIMIT 5000", conn)
    ratio = (df.value / (df.volume * df.close * 1000)).median()
    flag("PASS" if 0.97 < ratio < 1.03 else "FAIL",
         f"cb_daily value/volume/close量綱: 中位比率{ratio:.4f}(期望≈1)")
    # 2c cb_daily close vs cb_overview ref_price 同日吻合(有成交日)
    j = pd.read_sql("""SELECT d.close AS c, o.ref_price AS r FROM cb_daily d
        JOIN cb_overview o ON d.cb_id=o.cb_id AND d.date=o.date
        WHERE d.volume>0 AND o.ref_price>0 ORDER BY RANDOM() LIMIT 5000""", conn)
    agree = (abs(j.c - j.r) / j.r < 0.01).mean() * 100
    flag("PASS" if agree > 90 else "WARN",
         f"cb_daily收盤vs cb_overview ref(有成交日): 1%內吻合率{agree:.1f}%")
    # 2d 法人買超 <= 當日成交量
    j = pd.read_sql("""SELECT i.fi_buy+i.it_buy+i.dealer_buy AS b, d.volume AS v
        FROM cb_inst i JOIN cb_daily d ON i.cb_id=d.cb_id AND i.date=d.date
        WHERE d.volume>0 ORDER BY RANDOM() LIMIT 5000""", conn)
    bad = (j.b > j.v * 1.001).mean() * 100
    flag("PASS" if bad < 1 else "WARN", f"CB法人買張<=成交量: 違反率{bad:.2f}%")
    # 2e fm_month_rev vs tw_monthly_revenue 重疊核對
    j = pd.read_sql("""SELECT f.code, f.date, f.revenue AS fr, t.revenue AS tr
        FROM fm_month_rev f JOIN tw_monthly_revenue t
        ON f.code=t.code AND substr(f.date,1,4)||substr(f.date,6,2)=t.year_month
        WHERE t.revenue>0 ORDER BY RANDOM() LIMIT 3000""", conn)
    if len(j):
        agree = (abs(j.fr / 1000 - j.tr) / j.tr < 0.02).mean() * 100
        flag("PASS" if agree > 95 else "WARN",
             f"fm_month_rev vs tw_monthly_revenue(千元口徑): 2%內吻合率{agree:.1f}% n={len(j)}")
    # 2f inst_flow close vs fm_daily_price close
    j = pd.read_sql("""SELECT i.close AS a, p.close AS b FROM inst_flow i
        JOIN fm_daily_price p ON i.code=p.code AND i.date=p.date
        WHERE p.close>0 AND i.close>0 ORDER BY RANDOM() LIMIT 5000""", conn)
    agree = (abs(j.a - j.b) / j.b < 0.005).mean() * 100
    flag("PASS" if agree > 98 else "WARN", f"inst_flow vs fm_daily_price收盤吻合率{agree:.1f}%")
    # 2g margin_flow 使用率範圍
    bad = conn.execute("SELECT count(*) FROM margin_flow WHERE fin_use<0 OR fin_use>100").fetchone()[0]
    flag("PASS" if bad == 0 else "WARN", f"margin_flow fin_use出界(0-100): {bad}筆")
    # 2h index_daily 錨點
    anchors = [("TAIEX", "2020-03-19", 8681), ("TAIEX", "2022-10-25", 12666)]
    for mkt, d, exp in anchors:
        v = conn.execute("SELECT close FROM index_daily WHERE market=? AND date=?",
                         (mkt, d)).fetchone()
        ok = v and abs(v[0] - exp) / exp < 0.005
        flag("PASS" if ok else "FAIL", f"index錨點 {mkt}@{d}={v[0] if v else None}(期望{exp})")

    # --- 3. 外部抽查: TWSE STOCK_DAY vs fm_daily_price (2請求) ---
    print("\n=== 3. 外部抽查(TWSE官方) ===")
    codes = [r[0] for r in conn.execute(
        "SELECT DISTINCT code FROM fm_daily_price WHERE date>'2026-06-01' "
        "AND code IN ('2330','2317','2454','3231','3037','2603')")]
    for code in random.sample(codes, min(2, len(codes))):
        try:
            r = requests.get("https://www.twse.com.tw/exchangeReport/STOCK_DAY",
                             params={"response": "json", "date": "20260701", "stockNo": code},
                             timeout=30, headers={"User-Agent": "Mozilla/5.0"})
            data = r.json().get("data") or []
            n_ok = n_chk = 0
            for row in data:
                y, m, d = row[0].split("/")
                dt = f"{int(y) + 1911}-{m}-{d}"
                off = conn.execute("SELECT close FROM fm_daily_price WHERE code=? AND date=?",
                                   (code, dt)).fetchone()
                if off:
                    n_chk += 1
                    if abs(off[0] - float(row[6].replace(",", ""))) / off[0] < 0.005:
                        n_ok += 1
            flag("PASS" if n_chk and n_ok == n_chk else ("WARN" if n_chk else "WARN"),
                 f"TWSE官方 {code} 2026-07月收盤核對: {n_ok}/{n_chk}吻合")
        except Exception as e:
            flag("WARN", f"TWSE外部抽查{code}失敗(網路?): {type(e).__name__}")

    conn.close()
    print("\n驗證完畢。FAIL須處理; WARN記錄在案。")


if __name__ == "__main__":
    main()
