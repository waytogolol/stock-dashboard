# -*- coding: utf-8 -*-
"""建立/更新 SQLite 資料庫，把每次抓取的排行存成一個時間點快照(snapshot_date)。"""
import sqlite3
import sys
from datetime import date

import pandas as pd
import requests

DB_PATH = "capital_flow.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS rankings (
    snapshot_date TEXT,
    country TEXT,
    code TEXT,
    name TEXT,
    rank INTEGER,
    amount REAL,
    amount_unit TEXT,
    PRIMARY KEY (snapshot_date, country, code)
);
CREATE TABLE IF NOT EXISTS classification (
    country TEXT,
    code TEXT,
    main_group TEXT,
    sub_product TEXT,
    position_note TEXT,
    PRIMARY KEY (country, code, main_group, sub_product)
);
CREATE TABLE IF NOT EXISTS company_names (
    country TEXT,
    code TEXT,
    name_zh TEXT,
    PRIMARY KEY (country, code)
);
CREATE TABLE IF NOT EXISTS fx_rates (
    snapshot_date TEXT,
    currency TEXT,
    twd_per_unit REAL,
    PRIMARY KEY (snapshot_date, currency)
);
"""

COUNTRY_FILES = {
    "台": ("tw_top300.csv", "amount", "TWD"),
    "韓": ("kr_top400.csv", "amount_krw", "KRW"),
    "日": ("jp_top500.csv", "amount_mil_jpy", "JPY_million"),
    "陸": ("cn_top600.csv", "amount_cny", "CNY"),
    "美": ("us_top700.csv", "amount_usd", "USD"),
}


def init_schema(conn):
    conn.executescript(SCHEMA)


def load_snapshot(conn, snapshot_date):
    for country, (fname, amount_col, unit) in COUNTRY_FILES.items():
        df = pd.read_csv(fname, dtype={"code": str})
        df = df.rename(columns={amount_col: "amount"})
        rows = [
            (snapshot_date, country, r["code"], r["name"], int(r["rank"]), float(r["amount"]), unit)
            for _, r in df.iterrows()
        ]
        conn.executemany(
            "INSERT OR REPLACE INTO rankings (snapshot_date,country,code,name,rank,amount,amount_unit) VALUES (?,?,?,?,?,?,?)",
            rows,
        )
        print(f"{country}: {len(rows)} 筆寫入 snapshot {snapshot_date}")


def load_classification(conn):
    df = pd.read_csv("all_classified.csv", dtype={"代碼": str})
    df = df.rename(columns={"主族群": "main_group", "細分產品": "sub_product", "國家": "country",
                              "代碼": "code", "公司": "name", "產業地位": "position_note"})
    conn.execute("DELETE FROM classification")
    rows = df[["country", "code", "main_group", "sub_product", "position_note"]].values.tolist()
    conn.executemany("INSERT OR REPLACE INTO classification (country,code,main_group,sub_product,position_note) VALUES (?,?,?,?,?)", rows)
    print(f"分類表寫入 {len(rows)} 筆")


def load_fx_rates(conn, snapshot_date):
    """抓即時匯率(1單位外幣=多少台幣)，存進對應的snapshot_date，之後換算才會用當時的匯率而不是抓取當下的最新匯率。"""
    r = requests.get("https://open.er-api.com/v6/latest/TWD", timeout=10)
    j = r.json()
    if j.get("result") != "success":
        raise RuntimeError(f"匯率API回應異常: {j}")
    twd_rates = j["rates"]  # 1 TWD = twd_rates[X] 單位的X幣
    rows = [(snapshot_date, "TWD", 1.0)]
    for cur in ["USD", "JPY", "KRW", "CNY"]:
        rows.append((snapshot_date, cur, 1.0 / twd_rates[cur]))  # 1單位cur = 多少台幣
    conn.execute("DELETE FROM fx_rates WHERE snapshot_date=?", (snapshot_date,))
    conn.executemany("INSERT OR REPLACE INTO fx_rates (snapshot_date,currency,twd_per_unit) VALUES (?,?,?)", rows)
    print(f"匯率表寫入 snapshot {snapshot_date}: {rows}")


def load_names(conn):
    import zhconv

    from names_jp import NAME_ZH as jp_names
    from names_kr import NAME_ZH as kr_names
    from names_us import NAME_ZH as us_names

    rows = []
    for country, names in [("日", jp_names), ("韓", kr_names), ("美", us_names)]:
        rows.extend((country, code, name_zh) for code, name_zh in names.items())

    # 陸股名稱本身已是中文(簡體)，用zhconv自動轉繁體即可，不需要人工翻譯表
    cn = pd.read_csv("cn_top600.csv", dtype={"code": str})
    rows.extend((("陸", code, zhconv.convert(name, "zh-tw")) for code, name in zip(cn["code"], cn["name"])))

    conn.execute("DELETE FROM company_names")
    conn.executemany("INSERT OR REPLACE INTO company_names (country,code,name_zh) VALUES (?,?,?)", rows)
    print(f"中文名稱表寫入 {len(rows)} 筆")


if __name__ == "__main__":
    snapshot_date = sys.argv[1] if len(sys.argv) > 1 else str(date.today())
    conn = sqlite3.connect(DB_PATH)
    init_schema(conn)
    load_snapshot(conn, snapshot_date)
    load_classification(conn)
    load_names(conn)
    load_fx_rates(conn, snapshot_date)
    conn.commit()
    conn.close()
    print(f"完成，snapshot_date={snapshot_date}, db={DB_PATH}")
