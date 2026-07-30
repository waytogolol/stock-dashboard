# -*- coding: utf-8 -*-
"""台股官方產業分類全名單：TWSE ISIN(isin.twse.com.tw)上市(strMode=2)+上櫃(=4)+興櫃(=5)三表合併。
輸出 tw_industry_map.csv(code,name,market,industry)，供同業龍頭研究等需要「官方產業別」分組的分析使用。

沿革(2026-07-13)：舊版tw_industry_map.csv只含上市+上櫃共1,418檔，興櫃完全沒收，
導致MoneyDJ營收公告配對時42%的公司找不到產業分類——跟同一天修好的tw_all_listed.csv是同一個根因
(當初抓取時漏了strMode=5)，這次直接存成正式腳本，避免下次又要重新手刻一次。

沿革(2026-07-14)：strMode=2(上市)內部其實還細分很多子區塊(股票/創新板/臺灣存託憑證TDR/ETF/特別股等)，
舊版只留「股票」這個子區塊，把「創新板」(公司名帶「-創」後綴，如巨鎧精密-創)跟「臺灣存託憑證TDR」
(公司名帶「-DR」後綴，如晨訊科-DR)整個排除掉——這是MoneyDJ營收公告配不到代碼的另一個主因
(這些公司的官方登記名稱本身就內建「-創」/「-DR」，不是MoneyDJ自己加的)。上櫃(strMode=4)沒有對應的
額外子區塊，不受影響。
用法: python fetch_tw_industry_map.py
"""
import io

import pandas as pd
import requests

MODES = [(2, "上市"), (4, "上櫃"), (5, "興櫃")]
# 每個strMode要保留的子區塊(市場別欄位值)；上市除了「股票」還要收創新板+TDR
INCLUDE_SECTIONS = {
    2: {"股票", "創新板", "上市臺灣創新板", "臺灣存託憑證(TDR)"},
    4: {"股票"},
    5: {"股票"},
}


def fetch_isin(mode, label):
    url = f"https://isin.twse.com.tw/isin/C_public.jsp?strMode={mode}"
    r = requests.get(url, timeout=30)
    r.encoding = "big5"
    df = pd.read_html(io.StringIO(r.text))[0]
    df.columns = ["code_name", "isin", "listed_date", "market", "industry", "cfi", "note"]
    include = INCLUDE_SECTIONS[mode]
    rows = []
    section = None
    saw_divider = False
    for _, row in df.iterrows():
        vals = row.tolist()
        nonnull = [v for v in vals if pd.notna(v)]
        if len(set(str(v) for v in nonnull)) == 1 and len(nonnull) >= 5:
            section = str(vals[0])
            saw_divider = True
            continue
        cn = row["code_name"]
        if pd.isna(cn) or "　" not in str(cn):
            continue
        if saw_divider and section not in include:
            continue
        code, name = str(cn).split("　", 1)
        industry = row["industry"] if pd.notna(row["industry"]) else ""
        rows.append({"code": code.strip(), "name": name.strip(), "market": label, "industry": industry})
    return pd.DataFrame(rows)


def main():
    parts = [fetch_isin(mode, label) for mode, label in MODES]
    full = pd.concat(parts, ignore_index=True).drop_duplicates(subset=["code"])
    full.to_csv("tw_industry_map.csv", index=False, encoding="utf-8-sig")
    print(f"tw_industry_map.csv 已更新：{len(full)} 檔（" +
          "、".join(f"{label} {len(p)}" for (m, label), p in zip(MODES, parts)) + "）")
    # tw_all_listed.csv(給fetch_moneydj_revenue.py當公司名->代碼對照表)跟這裡是同一份原始資料只是少industry欄，
    # 兩份分開維護容易漏改一邊(2026-07-14才發現的教訓)，這裡一次寫出，不再另外手刻腳本
    full[["code", "name", "market"]].to_csv("tw_all_listed.csv", index=False, encoding="utf-8-sig")
    print(f"tw_all_listed.csv 已同步更新：{len(full)} 檔")


if __name__ == "__main__":
    main()
