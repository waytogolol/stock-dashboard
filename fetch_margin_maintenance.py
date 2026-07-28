# -*- coding: utf-8 -*-
"""FinMind 官方大盤融資維持率 例行增量 -> capital_flow.db (margin_maintenance_official)
背景: 2026-07-15 Backer升級時一次性落庫(2002起)後被標成「凍結線,無自動腳本」,
     2026-07-28使用者發現溫度計「融資警戒帶」卡在7/14——本腳本補上例行更新,已入update_all每日組。
資料集: TaiwanTotalExchangeMarginMaintenance(整體市場融資維持率,單一數列,一刀全補)。
⚠效期: 此資料集Backer限定(免費層400拒絕,2026-07-28實測),Backer 2026-08-15到期後斷炊。
  備援(使用者2026-07-28裁示): ①B估計版build_margin_maintenance.py=個股融資餘額逆推大盤維持率,
  歷史急殺日錨點誤差不大,斷炊後可改寫成寫入margin_maintenance_official的接軌版(estimate旗標區隔);
  ②或找公開源(histock/富邦e01有公開刊出大盤維持率,可爬)。屆時擇一接軌,別讓警戒帶再卡死。
注意: 官方源有毛刺(如2020-03-24=92.6%),照舊原樣入庫,讀取端自行濾<100(既有慣例)。
用法: python fetch_margin_maintenance.py
"""
import sqlite3
import sys

import requests

sys.stdout.reconfigure(encoding="utf-8")
DB = "capital_flow.db"
TOKEN = open("finmind_token.txt").read().strip()
URL = "https://api.finmindtrade.com/api/v4/data"


def main():
    conn = sqlite3.connect(DB)
    last = conn.execute("SELECT MAX(date) FROM margin_maintenance_official").fetchone()[0]
    r = requests.get(URL, params={"dataset": "TaiwanTotalExchangeMarginMaintenance",
                                  "start_date": last, "token": TOKEN}, timeout=60)
    j = r.json()
    if j.get("status") != 200:
        print(f"API失敗: {j.get('status')} {j.get('msg')}")
        print("提示: 若為Backer到期(8/15後),改接B估計版(build_margin_maintenance.py個股逆推)"
              "或公開源,見本檔docstring備援段")
        sys.exit(1)
    rows = [(d["date"], d["TotalExchangeMarginMaintenance"]) for d in j.get("data", [])]
    conn.executemany("INSERT OR REPLACE INTO margin_maintenance_official VALUES (?,?)", rows)
    conn.commit()
    new_last, n = conn.execute(
        "SELECT MAX(date), COUNT(*) FROM margin_maintenance_official").fetchone()
    print(f"完成: {last} -> {new_last} (+{len(rows)}筆覆寫含重疊, 總{n:,}筆)")
    conn.close()


if __name__ == "__main__":
    main()
