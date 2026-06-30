# -*- coding: utf-8 -*-
"""
抓取美/日/韓/台股「成交金額」前N名個股(排除ETF/權證/ETN/REIT等)，N可分市場調整。
資料源(2026-06-21驗證可用):
  台股上市 TWSE    https://www.twse.com.tw/exchangeReport/MI_INDEX
  台股上櫃 TPEx    https://www.tpex.org.tw/web/stock/aftertrading/daily_close_quotes/stk_quote_result.php
  日股     Kabutan  https://kabutan.jp/warning/trading_value_ranking
  韓股     FinanceDataReader (KRX)
  美股     Nasdaq screener  https://api.nasdaq.com/api/screener/stocks
"""
import math
import re
import time
import unicodedata

import pandas as pd
import requests
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"


def fetch_taiwan(date_str, top_n=200):
    """date_str: 'YYYYMMDD' (西元), 須為最近交易日"""
    headers = {"User-Agent": UA}
    rows = []

    # 上市 TWSE
    r = requests.get(
        "https://www.twse.com.tw/exchangeReport/MI_INDEX",
        params={"response": "json", "date": date_str, "type": "ALLBUT0999"},
        headers=headers, timeout=20,
    )
    j = r.json()
    table = next(t for t in j["tables"] if t.get("fields") and "成交金額" in t["fields"])
    fcode, fname, famt = table["fields"].index("證券代號"), table["fields"].index("證券名稱"), table["fields"].index("成交金額")
    for row in table["data"]:
        code = row[fcode].strip()
        if re.fullmatch(r"[1-9][0-9]{3}", code):  # 只留4位數一般股票代碼，排除ETF(00開頭)/權證等
            rows.append({"market": "TW-上市", "code": code, "name": row[fname], "amount": int(row[famt].replace(",", ""))})

    # 上櫃 TPEx (民國年)
    roc_date = f"{int(date_str[:4]) - 1911}/{date_str[4:6]}/{date_str[6:]}"
    r = requests.get(
        "https://www.tpex.org.tw/web/stock/aftertrading/daily_close_quotes/stk_quote_result.php",
        params={"l": "zh-tw", "d": roc_date},
        headers=headers, timeout=20,
    )
    j = r.json()
    fields = j["tables"][0]["fields"]
    fcode, fname, famt = fields.index("代號"), fields.index("名稱"), fields.index("成交金額(元)")
    for row in j["tables"][0]["data"]:
        code = row[fcode].strip()
        if re.fullmatch(r"[1-9][0-9]{3}", code):
            amt = row[famt].replace(",", "")
            if amt and amt != "0":
                rows.append({"market": "TW-上櫃", "code": code, "name": row[fname], "amount": int(amt)})

    df = pd.DataFrame(rows).sort_values("amount", ascending=False).head(top_n).reset_index(drop=True)
    df["rank"] = df.index + 1
    return df


def fetch_japan(top_n=200, per_page=15):
    """Kabutan 売買代金ランキング，排除ETF/ETN/REIT/インフラファンド"""
    headers = {"User-Agent": UA, "Accept-Language": "ja,en-US;q=0.9", "Referer": "https://kabutan.jp/"}
    exclude_market = {"東E", "東EN", "東R", "東IF", "名E"}
    pages = math.ceil(top_n / per_page) + 2  # 多抓2頁緩衝給過濾掉的ETF留餘量
    rows = []
    for page in range(1, pages + 1):
        r = requests.get(
            "https://kabutan.jp/warning/trading_value_ranking",
            params={"market": 0, "capitalization": -1, "dispmode": "normal", "page": page},
            headers=headers, timeout=20,
        )
        soup = BeautifulSoup(r.text, "html.parser")
        table = soup.select_one("table.stock_table.st_market")
        if table is None:
            break
        trs = table.find_all("tr")[1:]  # 跳過表頭
        if not trs:
            break
        for tr in trs:
            cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            if len(cells) < 10:
                continue
            code_tag = tr.find("a", href=re.compile(r"/stock/\?code=\d+"))
            code = re.search(r"code=(\d+)", code_tag["href"]).group(1) if code_tag else None
            name, market, price, value = cells[1], cells[2], cells[5], cells[9]
            market_normalized = unicodedata.normalize("NFKC", market)  # Kabutan用全角字母(Ｐ/Ｅ/Ｓ/Ｇ/Ｒ)，正規化成半角才能比對
            if not code or market_normalized in exclude_market:
                continue
            rows.append({
                "market": f"JP-{market}", "code": code, "name": name,
                "amount_mil_jpy": int(value.replace(",", "")) if re.fullmatch(r"[\d,]+", value) else 0,
            })
        time.sleep(1)
    df = pd.DataFrame(rows).drop_duplicates(subset=["code"]).sort_values("amount_mil_jpy", ascending=False).head(top_n).reset_index(drop=True)
    df["rank"] = df.index + 1
    return df


def fetch_korea(top_n=200):
    import FinanceDataReader as fdr
    df = fdr.StockListing("KRX")
    df = df[df["Market"].isin(["KOSPI", "KOSDAQ", "KONEX", "KOSDAQ GLOBAL"])].copy()
    df = df[~df["Name"].str.contains("스팩", na=False)]  # 排除SPAC
    df = df.sort_values("Amount", ascending=False).head(top_n).reset_index(drop=True)
    out = df[["Code", "Name", "Market", "Amount"]].rename(
        columns={"Code": "code", "Name": "name", "Market": "market", "Amount": "amount_krw"}
    )
    out["rank"] = out.index + 1
    return out


def fetch_china(top_n=200):
    """陸股(滬深A股)。資料源用 akshare 的 stock_zh_a_spot()(底層是新浪財經 hq.sinajs.cn，非東方財富)。
    東方財富 push2.eastmoney.com 系列host實測會回502(疑似封鎖此環境的IP段)，改用新浪財經，且akshare本身
    對新浪是分批查詢(~70批)，已經有自然間隔，不要再額外加大量並發或縮短間隔，避免被陸站偵測到異常流量。
    """
    import time
    import akshare as ak

    time.sleep(1)  # 保守起見，呼叫前先緩一下，不要緊接著上一個任務馬上打
    df = ak.stock_zh_a_spot()
    df = df.sort_values("成交额", ascending=False).head(top_n).reset_index(drop=True)
    out = df[["代码", "名称", "成交额"]].rename(columns={"代码": "code", "名称": "name", "成交额": "amount_cny"})
    out["rank"] = out.index + 1
    return out


def fetch_us(top_n=200):
    headers = {"User-Agent": UA, "Accept": "application/json, text/plain, */*"}
    r = requests.get("https://api.nasdaq.com/api/screener/stocks", params={"download": "true"}, headers=headers, timeout=30)
    j = r.json()
    rows = j["data"]["rows"]

    def to_float(s):
        try:
            return float(str(s).replace("$", "").replace(",", ""))
        except (TypeError, ValueError):
            return None

    data = []
    for row in rows:
        price, vol = to_float(row["lastsale"]), to_float(row["volume"])
        if price is None or vol is None or vol == 0:
            continue
        data.append({
            "code": row["symbol"], "name": row["name"], "sector": row["sector"], "industry": row["industry"],
            "price": price, "volume": vol, "amount_usd": price * vol,
        })
    df = pd.DataFrame(data).sort_values("amount_usd", ascending=False).head(top_n).reset_index(drop=True)
    df["rank"] = df.index + 1
    return df


# 各市場分別指定前N名(母體規模差很多，數量依市場大小調整)
TOP_N = {
    "tw": 300,
    "kr": 400,
    "jp": 500,
    "cn": 600,
    "us": 700,
}

if __name__ == "__main__":
    print("US...")
    fetch_us(TOP_N["us"]).to_csv(f"us_top{TOP_N['us']}.csv", index=False, encoding="utf-8-sig")
    print("Korea...")
    fetch_korea(TOP_N["kr"]).to_csv(f"kr_top{TOP_N['kr']}.csv", index=False, encoding="utf-8-sig")
    print("Taiwan...")
    fetch_taiwan("20260618", TOP_N["tw"]).to_csv(f"tw_top{TOP_N['tw']}.csv", index=False, encoding="utf-8-sig")
    print("Japan...")
    fetch_japan(TOP_N["jp"]).to_csv(f"jp_top{TOP_N['jp']}.csv", index=False, encoding="utf-8-sig")
    print("China...")
    fetch_china(TOP_N["cn"]).to_csv(f"cn_top{TOP_N['cn']}.csv", index=False, encoding="utf-8-sig")
    print("done")
