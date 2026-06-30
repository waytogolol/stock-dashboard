# -*- coding: utf-8 -*-
"""每週更新流程：重新抓取四市場排行 -> 套用既有分類規則(新進榜的公司若不在MAP裡會顯示在「未分類」清單) -> 寫入新的snapshot到資料庫。
用法: python weekly_refresh.py [日期，預設今天，格式YYYY-MM-DD]
"""
import subprocess
import sys
from datetime import date, timedelta

import pandas as pd
import requests

from fetch_top200 import UA, fetch_china, fetch_japan, fetch_korea, fetch_taiwan, fetch_us, TOP_N


def latest_tw_trading_day(max_lookback=10):
    """從今天往前找，回傳TWSE有資料的最近一個交易日(YYYYMMDD)"""
    headers = {"User-Agent": UA}
    for offset in range(max_lookback):
        d = date.today() - timedelta(days=offset)
        d_str = d.strftime("%Y%m%d")
        r = requests.get(
            "https://www.twse.com.tw/exchangeReport/MI_INDEX",
            params={"response": "json", "date": d_str, "type": "ALLBUT0999"},
            headers=headers, timeout=20,
        )
        j = r.json()
        if j.get("stat") == "OK":
            return d_str
    raise RuntimeError(f"往前找了{max_lookback}天都沒有TWSE交易資料，請確認日期")


def refresh_rankings():
    print("抓取美股...")
    fetch_us(TOP_N["us"]).to_csv("us_top700.csv", index=False, encoding="utf-8-sig")
    print("抓取韓股...")
    fetch_korea(TOP_N["kr"]).to_csv("kr_top400.csv", index=False, encoding="utf-8-sig")
    print("抓取台股...")
    today_str = latest_tw_trading_day()
    print(f"  -> 最近交易日: {today_str}")
    fetch_taiwan(today_str, TOP_N["tw"]).to_csv("tw_top300.csv", index=False, encoding="utf-8-sig")
    print("抓取日股...")
    fetch_japan(TOP_N["jp"]).to_csv("jp_top500.csv", index=False, encoding="utf-8-sig")
    print("抓取陸股(新浪財經，請勿縮短內部間隔)...")
    fetch_china(TOP_N["cn"]).to_csv("cn_top600.csv", index=False, encoding="utf-8-sig")


def refresh_classification():
    for script in ["classify_tw.py", "classify_jp.py", "classify_kr.py", "classify_cn.py", "classify_us.py"]:
        print(f"套用分類規則: {script}")
        subprocess.run([sys.executable, script], check=True)
    tw = pd.read_csv("tw_classified.csv", dtype={"代碼": str})
    jp = pd.read_csv("jp_classified.csv", dtype={"代碼": str})
    kr = pd.read_csv("kr_classified.csv", dtype={"代碼": str})
    cn = pd.read_csv("cn_classified.csv", dtype={"代碼": str})
    us = pd.read_csv("us_classified.csv", dtype={"代碼": str})
    all_df = pd.concat([tw, jp, kr, cn, us], ignore_index=True)
    all_df = all_df[["主族群", "細分產品", "國家", "排名", "代碼", "公司", "產業地位"]]
    all_df.to_csv("all_classified.csv", index=False, encoding="utf-8-sig")
    print(f"合併分類表完成，共 {len(all_df)} 筆標籤")


def report_unclassified():
    from classify_tw import MAP as tw_map
    from classify_jp import MAP as jp_map
    from classify_kr import MAP as kr_map
    from classify_cn import MAP as cn_map
    tw = pd.read_csv("tw_top300.csv")
    jp = pd.read_csv("jp_top500.csv")
    kr = pd.read_csv("kr_top400.csv")
    cn = pd.read_csv("cn_top600.csv", dtype={"code": str})
    new_tw = tw[~tw["code"].astype(str).isin(tw_map.keys())]
    new_jp = jp[~jp["code"].astype(str).isin(jp_map.keys())]
    new_kr = kr[~kr["code"].astype(str).isin(kr_map.keys())]
    new_cn = cn[~cn["code"].astype(str).isin(cn_map.keys())]
    n = len(new_tw) + len(new_jp) + len(new_kr) + len(new_cn)
    print(f"提醒：本次有 {n} 檔台/日/韓/陸個股不在既有分類規則裡(可能是新進榜的)，這些會被當成未分類，之後可以手動補進對應的 classify_*.py 的 MAP")


if __name__ == "__main__":
    snapshot_date = sys.argv[1] if len(sys.argv) > 1 else str(date.today())
    refresh_rankings()
    refresh_classification()
    report_unclassified()
    print("寫入資料庫...")
    subprocess.run([sys.executable, "build_db.py", snapshot_date], check=True)
    print("產出靜態網頁...")
    subprocess.run([sys.executable, "export_html.py"], check=True)
    print(f"完成！snapshot_date={snapshot_date}。雙擊 dashboard.html 看靜態網頁，或執行 `streamlit run app.py` 看互動式儀表板。")
