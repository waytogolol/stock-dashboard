# -*- coding: utf-8 -*-
"""當沖+借券費率歷史回補v3(2026-07-29使用者裁示全史回補:2014-01當沖新制起~2025-07,
接上既有一年份tmp_dtlend_p1~p6.pkl)。
v3新增: ①402/配額退避重試(長跑必備,否則超限日整天被跳過=洞) ②斷點續跑(重啟不歸零)。
用法: python scratch_pull_dt_lend.py --range 2014-01-01 2014-12-31 --out tmp_dtlend_h2014.pkl
量體註記: 全史~5,600刀;檔案走tmp pkl不入DB(DB備份逼近95MB上限;若考卷通過再裁正式儲存)。"""
import os
import os as _os
if _os.path.exists("STOP_DTLEND"):
    print("STOP_DTLEND旗標存在,跳過(使用者裁示明天再抓)")
    raise SystemExit(0)
import sqlite3
import sys
import time

import pandas as pd
import requests

sys.stdout.reconfigure(encoding="utf-8")
token = open("finmind_token.txt").read().strip()
URL = "https://api.finmindtrade.com/api/v4/data"
i = sys.argv.index("--range")
d_from, d_to = sys.argv[i + 1], sys.argv[i + 2]
out = sys.argv[sys.argv.index("--out") + 1]

conn = sqlite3.connect("capital_flow.db", timeout=60)
days = [r[0] for r in conn.execute(
    "SELECT DISTINCT date FROM index_daily WHERE market='TAIEX' AND date>=? AND date<=? "
    "ORDER BY date", (d_from, d_to))]
conn.close()

all_rows = []
done_days = set()
if os.path.exists(out):  # 斷點續跑
    old = pd.read_pickle(out)
    if len(old):
        all_rows = old.to_dict("records")
        done_days = set(old["date"].astype(str).str[:10])
todo = [d for d in days if d not in done_days]
print(f"{out}: 範圍{len(days)}天, 已有{len(days) - len(todo)}天, 待補{len(todo)}天")


def fetch(ds, d):
    """成功回rows;402配額→退避65s;403 ip banned→退避900s(教訓:12工人並發被封IP,
    403不重試會把整段天數燒掉);其他錯誤回None。"""
    for t in range(20):
        try:
            r = requests.get(URL, params={"dataset": ds, "start_date": d, "end_date": d,
                                          "token": token}, timeout=120)
            j = r.json()
            st = j.get("status")
            if st == 200:
                return j.get("data", [])
            msg = str(j.get("msg", ""))
            if st == 403 or "ban" in msg.lower():
                print(f"  {d}: 403封鎖中,退避31分鐘(官方政策=封30分,第{t + 1}次)", flush=True)
                time.sleep(1860)
                continue
            if st == 402 or "limit" in msg.lower() or "quota" in msg.lower():
                time.sleep(65)
                continue
            print(f"  {d} {ds[-12:]}: {st} {msg[:40]}")
            return None
        except Exception as e:
            print(f"  {d} {ds[-12:]}: {str(e)[:40]}")
            time.sleep(5)
    return None


for n, d in enumerate(todo):
    for ds, tag in (("TaiwanStockDayTrading", "dt"), ("TaiwanStockSecuritiesLending", "ln")):
        rows = fetch(ds, d)
        if rows is not None:
            for row in rows:
                row["ds"] = tag
            all_rows.extend(rows)
        time.sleep(2.5)  # 配速鐵律: Backer 1600刀/hr→最快2.25s/刀,2.5s=1,440/hr留餘裕(0.3s×12工人=封IP的根因)
    if (n + 1) % 20 == 0:
        pd.DataFrame(all_rows).to_pickle(out)
        print(f"  [{n + 1}/{len(todo)}] rows={len(all_rows):,}", flush=True)
pd.DataFrame(all_rows).to_pickle(out)
print(f"{out} 完成: {len(all_rows):,}筆")
