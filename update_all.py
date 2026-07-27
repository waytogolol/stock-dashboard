# -*- coding: utf-8 -*-
"""一鍵集體更新:跑完整套例行抓取+重產dashboard+新鮮度紅綠燈總驗收。
背景:2026-07-21與07-27兩次教訓——只更新單一資料線,其他線(溫度計index_daily/題材熱度rankings)
     悄悄過期,使用者打開dashboard才發現。這支腳本取代人腦記清單:一個指令跑完全部,
     結尾用「資料庫實際max日期vs預期節奏」逐線判紅綠,紅燈=沒更新到,不能只看腳本有沒有跑完。

用法:
  python update_all.py            # 日常:日線組+自動偵測(rankings快照>6天舊就順帶跑週線組)
  python update_all.py --weekly   # 強制含週線組(五市場排行/週收盤/解質/法說會/TX5分)
  python update_all.py --check    # 只做新鮮度總驗收,不跑任何抓取
  python update_all.py --dry-run  # 只列出這次會跑哪些步驟
  python update_all.py --push     # 全部跑完且驗收通過後,自動git add+commit+push(GitHub Pages更新)

注意:凍結線(CB三表=一次性回補設計/margin_maintenance_official=無自動腳本/tdcc_weekly=永久封存/
     rankings歷史XQ匯入已停用)不列紅燈,只顯示現況。每週收尾的make_backup.py不在此腳本內,結尾會提醒。
"""
import argparse
import os
import sqlite3
import subprocess
import sys
import time
from datetime import date, timedelta

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
DB = "capital_flow.db"
PY = sys.executable


# ---------- 步驟定義 ----------
# (名稱, 指令argv, 組別)  組別: daily=每次都跑 / weekly=週線組 / build=最後重產dashboard
STEPS = [
    ("個股日價",        [PY, "fetch_daily_price.py", "--update"], "daily"),
    ("處置股",          [PY, "fetch_disposition.py"],             "daily"),
    ("注意股",          [PY, "fetch_attention.py"],               "daily"),
    ("台股指數",        [PY, "fetch_index_daily.py"],             "daily"),
    ("全球指數",        [PY, "fetch_global_index.py"],            "daily"),
    ("三大法人",        [PY, "fetch_t86.py"],                     "daily"),
    ("融資券",          [PY, "fetch_margin.py"],                  "daily"),
    ("集保大戶",        [PY, "fetch_tdcc.py"],                    "daily"),
    ("五市場排行",      "TOP200",                                  "weekly"),  # 特殊:見run_top200
    ("rankings快照",    "BUILD_DB",                                "weekly"),  # 特殊:今天日期
    ("週收盤價",        [PY, "fetch_prices.py"],                  "weekly"),
    ("內部人解質",      [PY, "fetch_pledge.py"],                  "weekly"),
    ("台股法說會",      [PY, "fetch_conference_yahoo.py"],        "weekly"),
    ("TX5分K",          [PY, "fetch_tx_5min.py"],                 "weekly"),
    ("月營收缺漏",      [PY, "fetch_month_rev_gap.py"],           "weekly"),
    ("財報日曆",        [PY, "check_earnings.py"],                "build"),
    ("題材共振",        [PY, "build_resonance_theme.py"],         "build"),
    ("dashboard",       [PY, "export_html.py"],                   "build"),
    ("XQ匯入檔",        [PY, "gen_xq_watchlist.py"],              "build"),
    ("處置K棒檢視器",   [PY, "build_disposition_trade_viewer.py"], "build"),
]

# ---------- 新鮮度規則 ----------
# (表, 日期欄, 容忍日曆天數)  容忍值含週末/連假緩衝
FRESH_RULES = [
    ("fm_daily_price", "date",          4),
    ("index_daily",    "date",          4),
    ("inst_flow",      "date",          4),
    ("margin_flow",    "date",          4),
    ("attention",      "announce_date", 4),
    ("disposition",    "announce_date", 5),
    ("tdcc_holders",   "date",          9),
    ("tdcc_people",    "date",          9),
    ("tx_5min",        "date",          4),
    ("rankings",       "snapshot_date", 9),
    ("weekly_close",   "snapshot_date", 9),
    ("fx_rates",       "snapshot_date", 9),
    ("fm_month_rev",   "date",          50),
]
# 凍結線:只顯示不判紅
FROZEN = [
    ("cb_daily",     "date", "CB回補設計,非例行"),
    ("cb_inst",      "date", "CB回補設計,非例行"),
    ("cb_overview",  "date", "CB回補設計,非例行"),
    ("margin_maintenance_official", "date", "無自動腳本"),
    ("tdcc_weekly",  "date", "永久封存"),
]


def run_step(name, argv):
    t0 = time.time()
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    try:
        p = subprocess.run(argv, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env=env, timeout=3600)
        tail = "\n".join((p.stdout or "").strip().splitlines()[-3:])
        ok = p.returncode == 0
        print(f"{'✅' if ok else '🔴'} {name}  ({time.time()-t0:.0f}s)")
        if tail:
            print("   " + tail.replace("\n", "\n   "))
        if not ok:
            err = "\n".join((p.stderr or "").strip().splitlines()[-5:])
            print("   stderr尾段: " + err.replace("\n", "\n   "))
        return ok
    except Exception as e:
        print(f"🔴 {name}  例外: {e}")
        return False


def run_top200():
    """五市場排行→CSV。台股要指定日期:從今天往回找最近有資料的交易日(假日/未收盤自動退一天)。"""
    import fetch_top200 as m
    jobs = [
        ("US", lambda: m.fetch_us(m.TOP_N["us"]),     f"us_top{m.TOP_N['us']}.csv"),
        ("KR", lambda: m.fetch_korea(m.TOP_N["kr"]),  f"kr_top{m.TOP_N['kr']}.csv"),
        ("JP", lambda: m.fetch_japan(m.TOP_N["jp"]),  f"jp_top{m.TOP_N['jp']}.csv"),
        ("CN", lambda: m.fetch_china(m.TOP_N["cn"]),  f"cn_top{m.TOP_N['cn']}.csv"),
    ]
    ok_all = True
    for label, fn, out in jobs:
        try:
            df = fn()
            df.to_csv(out, index=False, encoding="utf-8-sig")
            print(f"   [{label}] {len(df)}筆")
        except Exception as e:
            print(f"   [{label}] 🔴 {e}")
            ok_all = False
    # 台股:退日重試(最多7天)
    d = date.today()
    for _ in range(7):
        if d.weekday() < 5:
            try:
                df = m.fetch_taiwan(d.strftime("%Y%m%d"), m.TOP_N["tw"])
                if len(df) >= 100:
                    df.to_csv(f"tw_top{m.TOP_N['tw']}.csv", index=False, encoding="utf-8-sig")
                    print(f"   [TW] {len(df)}筆 ({d})")
                    break
            except Exception:
                pass
        d -= timedelta(days=1)
    else:
        print("   [TW] 🔴 連退7天都抓不到")
        ok_all = False
    print(f"{'✅' if ok_all else '🔴'} 五市場排行")
    return ok_all


def freshness_report():
    print("\n===== 新鮮度總驗收(資料庫實際max日期) =====")
    con = sqlite3.connect(DB)
    today = date.today()
    reds = []
    for table, col, tol in FRESH_RULES:
        try:
            mx = con.execute(f"SELECT MAX({col}) FROM {table}").fetchone()[0]
            age = (today - date.fromisoformat(str(mx)[:10])).days if mx else 9999
            ok = age <= tol
            print(f"  {'✅' if ok else '🔴'} {table:24s} max={mx}  ({age}天前, 容忍{tol})")
            if not ok:
                reds.append(table)
        except Exception as e:
            print(f"  🔴 {table:24s} 查詢失敗: {e}")
            reds.append(table)
    for table, col, why in FROZEN:
        try:
            mx = con.execute(f"SELECT MAX({col}) FROM {table}").fetchone()[0]
            print(f"  ⏸️ {table:24s} max={mx}  (凍結線:{why})")
        except Exception:
            pass
    con.close()
    return reds


def rankings_age_days():
    try:
        con = sqlite3.connect(DB)
        mx = con.execute("SELECT MAX(snapshot_date) FROM rankings").fetchone()[0]
        con.close()
        return (date.today() - date.fromisoformat(mx)).days
    except Exception:
        return 999


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weekly", action="store_true", help="強制含週線組")
    ap.add_argument("--check", action="store_true", help="只做新鮮度驗收")
    ap.add_argument("--dry-run", action="store_true", help="只列步驟不執行")
    ap.add_argument("--push", action="store_true", help="完成且驗收全綠後自動commit+push")
    args = ap.parse_args()

    if args.check:
        reds = freshness_report()
        sys.exit(1 if reds else 0)

    do_weekly = args.weekly or rankings_age_days() > 6
    groups = {"daily", "build"} | ({"weekly"} if do_weekly else set())
    plan = [(n, a) for n, a, g in STEPS if g in groups]
    print(f"本次計畫 {len(plan)} 步 (週線組: {'含' if do_weekly else '略過,rankings快照仍新鮮'})")
    if args.dry_run:
        for n, _ in plan:
            print(f"  - {n}")
        return

    fails = []
    for name, argv in plan:
        if argv == "TOP200":
            ok = run_top200()
        elif argv == "BUILD_DB":
            ok = run_step(name, [PY, "build_db.py", str(date.today())])
        else:
            ok = run_step(name, argv)
        if not ok:
            fails.append(name)

    reds = freshness_report()
    print("\n===== 總結 =====")
    if fails:
        print(f"🔴 失敗步驟: {fails}")
    if reds:
        print(f"🔴 過期資料線: {reds}")
    if not fails and not reds:
        print("✅ 全部步驟完成、全部資料線新鮮")
        if args.push:
            subprocess.run(["git", "add", "-A"], check=True)
            msg = f"資料例行更新{date.today()}(update_all.py)\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
            r = subprocess.run(["git", "commit", "-m", msg])
            if r.returncode == 0:
                subprocess.run(["git", "push", "origin", "master"], check=True)
                print("✅ 已push,GitHub Pages更新中")
            else:
                print("(無變更可commit)")
        else:
            print("提醒: git add -A && git commit && git push 才會更新GitHub Pages;每週收尾另跑 make_backup.py")
    sys.exit(1 if (fails or reds) else 0)


if __name__ == "__main__":
    main()
