# -*- coding: utf-8 -*-
"""把 capital_flow.db 匯出成一個獨立的 dashboard.html，雙擊就能在瀏覽器打開，不需要跑streamlit/python。
用法: python export_html.py
"""
import json
import os
import sqlite3
import sys
from datetime import datetime

import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DB_PATH = "capital_flow.db"
OUT_PATH = "dashboard.html"

# 2026-07-20使用者裁示: 個股歷史趨勢圖先不上儀表板(company_history佔payload 57%≈4.4MB);
# 題材歷史(theme_history)是熱力圖/共振欄的計算原料「必須留」; 產業月營收動能(theme_momentum)不受影響。
# 要恢復個股歷史: 改False重跑 python export_html.py 即可(內部照算,只是不進payload)。
SLIM_HISTORY = True

BUILD_FAILS = []  # 各區塊建置失敗收集(2026-07-20健檢: 防「except吞錯→儀表板靜默缺角」,前端頂部banner)


def _sec_fail(msg, e):
    BUILD_FAILS.append(f"{msg}: {type(e).__name__}: {e}")

BROAD_GROUPS = {
    "金融", "科技(綜合)", "生技醫藥", "消費(非必需)", "工業", "傳統產業", "傳統消費", "公用事業", "能源",
    "不動產", "電信", "傳統產業/原材料", "電力設備", "控股公司", "航運", "造船", "商社", "商社/建設",
    "汽車", "其他", "未分類", "媒體/娛樂", "遊戲/娛樂", "品牌3C", "IT/系統整合", "網路服務", "人力資源",
    "工業電腦/物聯網", "IC通路", "安防設備",
}

UNIT_YI_LABEL = {"TWD": "億元", "KRW": "億韓元", "JPY_million": "億日圓", "CNY": "億人民幣", "USD": "億美元"}
COUNTRIES = ["台", "日", "美", "韓", "陸"]

# 展覽效應研究(2026-07)：官方產業分類宇宙+2022-2025歷史事件研究常客名單，日期需每年手動更新(比照tw_earnings_watch.csv)
def _expo_window_open(start_str, trading_days=40):
    """展覽開始日往回推N個「平常日」(週一到週五,未扣除國定假日,近似值)當觀察窗開啟日"""
    from datetime import datetime as _dt, timedelta as _td
    d = _dt.strptime(start_str, "%Y-%m-%d")
    n = 0
    while n < trading_days:
        d -= _td(days=1)
        if d.weekday() < 5:
            n += 1
    return d.strftime("%Y-%m-%d")


EXPO_CALENDAR = {
    "biotech": {
        "label": "BIO Asia-Taiwan(亞洲生技大展)",
        "dates": [
            {"year": 2022, "start": "2022-07-28", "end": "2022-07-31"},
            {"year": 2023, "start": "2023-07-26", "end": "2023-07-30"},
            {"year": 2024, "start": "2024-07-25", "end": "2024-07-28"},
            {"year": 2025, "start": "2025-07-24", "end": "2025-07-27"},
            {"year": 2026, "start": "2026-07-16", "end": "2026-07-19"},
        ],
        "watchlist": [
            {"code": "6796", "name": "晉弘", "hits": ["2022:+109%", "2023:+36%", "2024:+14%"]},
            {"code": "6472", "name": "保瑞", "hits": ["2022:+39%(40日)", "2023:+32%", "2024:+11%"]},
            {"code": "6446", "name": "藥華藥", "hits": ["2022:+49%(40日)", "2024:+21%", "2026:進行中"]},
            {"code": "6861", "name": "睿生光電", "hits": ["2022:+26%", "2023:+19%", "2025:+8%"]},
            {"code": "4771", "name": "望隼", "hits": ["2022:+21%", "2023:+18%"]},
            {"code": "1786", "name": "科妍", "hits": ["2023:+16%", "2025:+28%"]},
            {"code": "4169", "name": "泰宗", "hits": ["2023:+11%", "2025:+29%"]},
        ],
    },
    "computex": {
        "label": "COMPUTEX Taipei(台北國際電腦展)",
        "dates": [
            {"year": 2022, "start": "2022-05-24", "end": "2022-05-27"},
            {"year": 2023, "start": "2023-05-30", "end": "2023-06-02"},
            {"year": 2024, "start": "2024-06-03", "end": "2024-06-07"},
            {"year": 2025, "start": "2025-05-20", "end": "2025-05-23"},
            {"year": 2026, "start": "2026-06-02", "end": "2026-06-05"},
        ],
        "watchlist": [
            {"code": "3017", "name": "奇鋐", "hits": ["2022:+7%", "2023:+24%", "2025:+48%"]},
            {"code": "3013", "name": "晟銘電", "hits": ["2022:+23%", "2025:+33%"]},
        ],
    },
    "semicon": {
        "label": "SEMICON Taiwan(國際半導體展)",
        "dates": [
            {"year": 2022, "start": "2022-09-14", "end": "2022-09-16"},
            {"year": 2023, "start": "2023-09-06", "end": "2023-09-08"},
            {"year": 2024, "start": "2024-09-04", "end": "2024-09-06"},
            {"year": 2025, "start": "2025-09-10", "end": "2025-09-12"},
            {"year": 2026, "start": "2026-09-02", "end": "2026-09-04"},
        ],
        "watchlist": [
            {"code": "3661", "name": "世芯-KY", "hits": ["2022:+19%", "2023:+20%", "2024:+18%"]},
            {"code": "6515", "name": "穎崴", "hits": ["2022:+8%", "2024:+28%", "2025:+55%"]},
        ],
    },
}
for _expo in EXPO_CALENDAR.values():
    for _d in _expo["dates"]:
        _d["window_open"] = _expo_window_open(_d["start"])


def rank_tier(rank):
    if rank <= 50:
        return "🔥 前50(熱)"
    elif rank <= 150:
        return "🟠 51-150(中)"
    else:
        return "🟡 151+(邊緣)"


def amount_yi_num(row):
    """原始幣別下的億單位數值(不格式化，純數字，給排序/計算用)"""
    return row["amount"] / 100 if row["amount_unit"] == "JPY_million" else row["amount"] / 1e8


def format_amount_yi(row):
    yi = amount_yi_num(row)
    return f"{round(yi):,}{UNIT_YI_LABEL.get(row['amount_unit'], '億')}"


def amount_twd_yi_num(row):
    """換算成台幣的億元數值(不格式化，純數字，給排序/計算用)，缺匯率時回傳None"""
    if pd.isna(row.get("twd_per_unit")):
        return None
    base_amount = row["amount"] * 1e6 if row["amount_unit"] == "JPY_million" else row["amount"]
    return base_amount * row["twd_per_unit"] / 1e8


def format_amount_twd_yi(row):
    v = row["金額億台幣_num"]
    return "—" if v is None else f"{round(v):,}億元"


def compute_theme_pivot(rankings, classification, snapshot_date):
    """回傳該snapshot_date的題材熱度分數表(主族群為index)。"""
    snap = rankings[rankings["snapshot_date"] == snapshot_date]
    merged = classification.merge(snap, on=["country", "code"], how="inner")
    country_totals = snap.groupby("country")["金額億台幣_num"].sum()
    theme_amt = (
        merged.drop_duplicates(subset=["main_group", "country", "code"])
        .groupby(["main_group", "country"])["金額億台幣_num"].sum().unstack(fill_value=0)
    )
    theme_cnt = (
        merged.drop_duplicates(subset=["main_group", "country", "code"])
        .groupby(["main_group", "country"])["code"].count().unstack(fill_value=0)
    )
    for c in COUNTRIES:
        if c not in theme_amt.columns:
            theme_amt[c] = 0.0
        if c not in theme_cnt.columns:
            theme_cnt[c] = 0
    share = theme_amt[COUNTRIES].div(country_totals.reindex(COUNTRIES), axis=1) * 100
    pivot = pd.DataFrame({"熱度分數": share.sum(axis=1), "金額合計億台幣": theme_amt[COUNTRIES].sum(axis=1)})
    for c in COUNTRIES:
        pivot[c] = theme_cnt[c].astype(int)
    pivot["合計家數"] = theme_cnt[COUNTRIES].sum(axis=1).astype(int)
    return pivot


def build():
    conn = sqlite3.connect(DB_PATH)
    rankings = pd.read_sql("SELECT * FROM rankings", conn)
    classification = pd.read_sql("SELECT * FROM classification", conn)
    names = pd.read_sql("SELECT * FROM company_names", conn)
    fx = pd.read_sql("SELECT * FROM fx_rates", conn)
    conn.close()

    rankings = rankings.merge(names, on=["country", "code"], how="left")
    rankings["中文名稱"] = rankings["name_zh"].fillna(rankings["name"])
    rankings["熱度"] = rankings["rank"].apply(rank_tier)
    rankings["金額億_num"] = rankings.apply(amount_yi_num, axis=1)
    rankings["金額億"] = rankings.apply(format_amount_yi, axis=1)
    rankings["currency"] = rankings["amount_unit"].map({"TWD": "TWD", "KRW": "KRW", "JPY_million": "JPY", "CNY": "CNY", "USD": "USD"})
    rankings = rankings.merge(fx, on=["snapshot_date", "currency"], how="left")
    rankings["金額億台幣_num"] = rankings.apply(amount_twd_yi_num, axis=1)
    rankings["金額億台幣"] = rankings.apply(format_amount_twd_yi, axis=1)

    # 網頁payload歷史上限：只在「呈現層」截斷(快照每週+1會讓HTML線性膨脹到永遠)
    # 訊號/研究計算不受影響(各自直接讀DB全史)。104週=2年,足撐52週位階/26週對比/接刀27週
    PAYLOAD_WEEKS = 104
    all_dates = sorted(rankings["snapshot_date"].unique())[-PAYLOAD_WEEKS:]
    rankings = rankings[rankings["snapshot_date"].isin(all_dates)]
    latest_date = all_dates[-1]
    previous_date = all_dates[-2] if len(all_dates) >= 2 else None
    latest = rankings[rankings["snapshot_date"] == latest_date]

    merged = classification.merge(latest, on=["country", "code"], how="inner")

    main_groups_per_company = (
        classification.groupby(["country", "code"])["main_group"]
        .apply(lambda x: ", ".join(sorted(set(x))))
        .reset_index()
        .rename(columns={"main_group": "main_groups"})
    )
    full_table = latest.merge(main_groups_per_company, on=["country", "code"], how="left")
    full_table["main_groups"] = full_table["main_groups"].fillna("未分類")

    # ---- 熱度分數：該題材在該國的台幣金額佔該國全部上榜公司台幣金額的比例，五國加總 ----
    pivot = compute_theme_pivot(rankings, classification, latest_date)
    if previous_date:
        prev_pivot = compute_theme_pivot(rankings, classification, previous_date)
        pivot["熱度分數Δ"] = pivot["熱度分數"] - prev_pivot["熱度分數"].reindex(pivot.index)
        pivot["金額Δ億台幣"] = pivot["金額合計億台幣"] - prev_pivot["金額合計億台幣"].reindex(pivot.index)
    pivot = pivot.sort_values("熱度分數", ascending=False)
    pivot_thematic = pivot[~pivot.index.isin(BROAD_GROUPS)]

    def pivot_to_records(p):
        recs = []
        for g, r in p.iterrows():
            rec = {
                "main_group": g,
                "熱度分數": round(r["熱度分數"], 2),
                "金額合計億台幣": f"{round(r['金額合計億台幣']):,}",
                "_amt_num": round(r["金額合計億台幣"]),
                "合計家數": int(r["合計家數"]),
            }
            for c in COUNTRIES:
                rec[c] = int(r[c])
            if previous_date:
                rec["熱度分數Δ"] = round(r["熱度分數Δ"], 2) if pd.notna(r["熱度分數Δ"]) else None
                rec["金額Δ億台幣"] = round(r["金額Δ億台幣"]) if pd.notna(r["金額Δ億台幣"]) else None
            recs.append(rec)
        return recs

    theme_pivot_all = pivot_to_records(pivot)
    theme_pivot_thematic = pivot_to_records(pivot_thematic)

    theme_detail = {}
    detail_cols = ["country", "rank", "code", "中文名稱", "name", "sub_product", "position_note",
                    "金額億", "金額億台幣", "金額億台幣_num", "熱度"]
    for g in pivot.index:
        rows = merged[merged["main_group"] == g][detail_cols].sort_values("rank")
        theme_detail[g] = rows.to_dict("records")

    full_cols = ["country", "rank", "code", "中文名稱", "name", "金額億", "金額億台幣", "金額億台幣_num", "main_groups", "熱度"]
    full_table_out = full_table[full_cols].copy()
    if previous_date:
        prev = rankings[rankings["snapshot_date"] == previous_date][["country", "code", "rank", "金額億台幣_num"]]
        prev = prev.rename(columns={"rank": "prev_rank", "金額億台幣_num": "prev_amt"})
        full_table_out = full_table_out.merge(prev, on=["country", "code"], how="left")
        full_table_out["排名Δ"] = full_table_out.apply(
            lambda r: "新進榜" if pd.isna(r["prev_rank"]) else f"{int(r['prev_rank'] - r['rank']):+d}", axis=1
        )
        full_table_out["排名Δ_num"] = full_table_out["prev_rank"] - full_table_out["rank"]
        full_table_out["金額Δ億台幣"] = (full_table_out["金額億台幣_num"] - full_table_out["prev_amt"]).round(0)
    full_records = full_table_out.sort_values(["country", "rank"]).to_dict("records")

    # 緊湊格式省空間：rows = [[快照索引, 排名, 金額億(原幣整數), 金額億台幣(整數或null), 週收盤價或null], ...]
    # 格式化(單位/千分位)由前端渲染時處理
    close_lookup = {}
    try:
        conn_p = sqlite3.connect(DB_PATH)
        wc = pd.read_sql("SELECT country, code, snapshot_date, close FROM weekly_close", conn_p)
        conn_p.close()
        close_lookup = {(r["country"], r["code"], r["snapshot_date"]): r["close"] for _, r in wc.iterrows()}
        print(f"週收盤價載入 {len(close_lookup)} 筆")
    except Exception as e:
        _sec_fail("週收盤價未載入(可先跑 fetch_prices.py)", e)
    date_idx = {d: i for i, d in enumerate(all_dates)}
    history_cols = ["snapshot_date", "country", "code", "中文名稱", "rank", "金額億_num", "金額億台幣_num"]
    history = rankings[history_cols].sort_values(["country", "code", "snapshot_date"])
    company_history = {}
    for (country, code), g in history.groupby(["country", "code"]):
        key = f"{country}|{code}"
        rows = []
        for _, r in g.iterrows():
            twd = r["金額億台幣_num"]
            cl = close_lookup.get((country, code, r["snapshot_date"]))
            rows.append([date_idx[r["snapshot_date"]], int(r["rank"]),
                         int(round(r["金額億_num"])),
                         int(round(twd)) if twd is not None and pd.notna(twd) else None,
                         cl if cl is not None and pd.notna(cl) else None])
        company_history[key] = {"label": f"{country} {code} {g['中文名稱'].iloc[0]}", "rows": rows}

    # 族群(題材)隨時間變化的歷史，每個歷史snapshot都重算一次熱度分數
    theme_history = {}
    for d in all_dates:
        p = compute_theme_pivot(rankings, classification, d)
        for g, r in p.iterrows():
            theme_history.setdefault(g, []).append({
                "snapshot_date": d,
                "熱度分數": round(r["熱度分數"], 2),
                "金額合計億台幣": round(r["金額合計億台幣"]),
            })

    # 題材×國別子分數歷史(族群金流解剖：看哪個市場先動)
    try:
        _r = rankings[["snapshot_date", "country", "code", "金額億台幣_num"]].copy()
        _r["tot"] = _r.groupby(["snapshot_date", "country"])["金額億台幣_num"].transform("sum")
        _r["share"] = _r["金額億台幣_num"] / _r["tot"] * 100
        _m = _r.merge(classification[["country", "code", "main_group"]].drop_duplicates(),
                      on=["country", "code"])
        _sub = _m.groupby(["main_group", "country", "snapshot_date"])["share"].sum()
        tch = {}
        for (g, c), grp in _sub.groupby(level=[0, 1]):
            s = grp.droplevel([0, 1]).reindex(all_dates).fillna(0)
            if s.max() > 0.05:
                tch.setdefault(g, {})[c] = [round(float(v), 2) for v in s]
        data_theme_country = tch
    except Exception as e:
        _sec_fail("題材國別子分數計算失敗", e)
        data_theme_country = {}

    def load_earnings_csv(path):
        if not os.path.exists(path):
            return {"rows": [], "mtime": None}
        df = pd.read_csv(path, dtype={"代碼": str})
        mtime = datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M")
        return {"rows": df.to_dict("records"), "mtime": mtime}

    try:
        import subprocess
        _vn = subprocess.run(["git", "rev-list", "--count", "HEAD"], capture_output=True, text=True).stdout.strip()
        _vh = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
        version = f"v{int(_vn) + 1}（基於{_vh}）" if _vn else ""   # 匯出後才commit，故+1=本次發版號
    except Exception:
        version = ""

    data = {
        "latest_date": latest_date,
        "previous_date": previous_date,
        "version": version,
        "theme_country_history": {} if SLIM_HISTORY else data_theme_country,
        "countries": COUNTRIES,
        "snapshot_dates": sorted(rankings["snapshot_date"].unique().tolist()),
        "theme_pivot_all": theme_pivot_all,
        "theme_pivot_thematic": theme_pivot_thematic,
        "theme_detail": theme_detail,
        "theme_history": theme_history,
        "theme_list": sorted(theme_history.keys()),
        "theme_list_thematic": sorted(g for g in theme_history.keys() if g not in BROAD_GROUPS),
        "full_records": full_records,
        "company_history": {} if SLIM_HISTORY else company_history,
        "company_list": [] if SLIM_HISTORY else sorted(
            [{"key": k, "label": v["label"]} for k, v in company_history.items()],
            key=lambda x: x["label"],
        ),
        "us_earnings": load_earnings_csv("us_earnings_watch.csv"),
        "tw_earnings": load_earnings_csv("tw_earnings_watch.csv"),
        "jpkr_earnings": load_earnings_csv("jp_kr_earnings_watch.csv"),
        "theme_news": pd.read_csv("theme_news.csv").to_dict("records") if os.path.exists("theme_news.csv") else [],
        "expo_calendar": EXPO_CALENDAR,
    }

    # 本週摘要橫幅：最熱/最退潮題材 + 新進榜檔數
    summary = {}
    if previous_date:
        th = [p for p in theme_pivot_thematic if p.get("熱度分數Δ") is not None]
        if th:
            up = max(th, key=lambda p: p["熱度分數Δ"])
            down = min(th, key=lambda p: p["熱度分數Δ"])
            summary["up"] = {"g": up["main_group"], "d": up["熱度分數Δ"]}
            summary["down"] = {"g": down["main_group"], "d": down["熱度分數Δ"]}
        summary["new_count"] = sum(1 for r in full_records if r.get("排名Δ") == "新進榜")
    data["weekly_summary"] = summary

    # 供應鏈/產業鏈共用：把公司補上最新排名、熱度、金額與排名Δ
    latest_lookup = {(r["country"], r["code"]): r for _, r in latest.iterrows()}
    prev_lookup = {}
    if previous_date:
        prev_snap = rankings[rankings["snapshot_date"] == previous_date]
        prev_lookup = {(r["country"], r["code"]): r for _, r in prev_snap.iterrows()}

    # 基本面(毛利率/營收YoY，由 fetch_fundamentals.py 每季更新)
    fund_lookup = {}
    try:
        conn_f = sqlite3.connect(DB_PATH)
        fund = pd.read_sql("SELECT * FROM fundamentals", conn_f)
        conn_f.close()
        for _, r in fund.iterrows():
            pb = r.get("pb")
            fund_lookup[(r["country"], r["code"])] = {
                "gross_margin": round(r["gross_margin"] * 100, 1) if pd.notna(r["gross_margin"]) else None,
                "revenue_growth": round(r["revenue_growth"] * 100, 1) if pd.notna(r["revenue_growth"]) else None,
                "pb": round(pb, 2) if pd.notna(pb) and 0 < pb < 100 else None,
                "eps_ttm": round(r["eps_ttm"], 2) if pd.notna(r.get("eps_ttm")) else None,
                "eps_fwd": round(r["eps_fwd"], 2) if pd.notna(r.get("eps_fwd")) else None,
            }
    except Exception as e:
        _sec_fail("基本面資料未載入(可先跑 fetch_fundamentals.py)", e)

    # 陸股東財事件標籤(業績預告/快報/調研飆升，fetch_cn_eastmoney.py更新)
    cn_note = {}
    try:
        import statistics
        conn_e = sqlite3.connect(DB_PATH)
        for code, pt, lo, hi in conn_e.execute(
                """SELECT code, predict_type, amp_lower, amp_upper FROM cn_forecast f
                   WHERE notice_date=(SELECT MAX(notice_date) FROM cn_forecast WHERE code=f.code)"""):
            rng = ""
            if lo is not None and hi is not None:
                rng = f"{lo:+.0f}~{hi:+.0f}%"
            elif lo is not None:
                rng = f"{lo:+.0f}%"
            cn_note[code] = f"📢預告{pt}{rng}"
        for code, yoy, npy in conn_e.execute(
                """SELECT code, rev_yoy, np_yoy FROM cn_flash f
                   WHERE report_date=(SELECT MAX(report_date) FROM cn_flash WHERE code=f.code)"""):
            t = []
            if yoy is not None:
                t.append(f"營收{yoy:+.0f}%")
            if npy is not None:
                t.append(f"淨利{npy:+.0f}%")
            if t:
                cn_note[code] = (cn_note.get(code, "") + "｜快報" + "/".join(t)).lstrip("｜")
        sv = {}
        for code, month, n in conn_e.execute("SELECT code, month, n FROM cn_survey"):
            sv.setdefault(code, []).append((month, n))
        for code, lst in sv.items():
            lst.sort()
            if len(lst) >= 3:
                cur = lst[-1][1]
                med = statistics.median(v for _m, v in lst[:-1])
                if cur >= 5 and cur >= 3 * max(med, 1):
                    cn_note[code] = (cn_note.get(code, "") + f"｜🔍調研飆升{cur}場/月").lstrip("｜")
        conn_e.close()
        if cn_note:
            print(f"陸股東財標籤 {len(cn_note)} 檔")
    except Exception as e:
        _sec_fail("陸股東財標籤未載入(可先跑 fetch_cn_eastmoney.py)", e)

    # 資本支出(fetch_capex.py每季更新)：卡片擴產標籤 + 錨點客戶資本開支引擎
    def _fmt_b(v):
        return f"{v/1e12:.1f}T" if v >= 1e12 else f"{v/1e9:.1f}B"

    capex_note = {}
    capex_map = {}
    try:
        conn_x = sqlite3.connect(DB_PATH)
        rowsx = conn_x.execute(
            "SELECT country, code, qdate, capex FROM capex_history ORDER BY qdate").fetchall()
        conn_x.close()
        serx = {}
        for c, cd, q, v in rowsx:
            serx.setdefault((c, cd), []).append((q, v))
        for (c, cd), lst in serx.items():
            if len(lst) < 2 or lst[-1][1] <= 0:
                continue
            qd, v = lst[-1]
            d1 = datetime.strptime(qd, "%Y-%m-%d")
            ref = None
            for q0, v0 in lst[:-1]:
                dd = (d1 - datetime.strptime(q0, "%Y-%m-%d")).days
                if 330 <= dd <= 400 and v0 > 0:
                    ref = (q0, v0, "YoY")
            if ref is None and lst[0][1] > 0 and lst[0][0] != qd:
                ref = (lst[0][0], lst[0][1], f"vs{lst[0][0][:7]}")
            if not ref:
                continue
            chg = round((v / ref[1] - 1) * 100)
            hist = "、".join(f"{q[:7]}:{_fmt_b(x)}" for q, x in lst[-5:])
            # 最小金額門檻(原幣)：排除小基數跳變雜訊(0.00B->0.01B也算+幾百%)
            min_capex = {"台": 5e8, "美": 5e7, "日": 5e9, "韓": 5e10, "陸": 3e8}.get(c, 0)
            note = ""
            if v >= min_capex:
                if chg >= 50:
                    note = f"🏗️Capex+{chg}%({ref[2]})"
                elif chg <= -40:
                    note = f"Capex{chg}%({ref[2]})"
            capex_note[(c, cd)] = {"n": note, "h": hist}
            capex_map[f"{c}|{cd}"] = {"cur": _fmt_b(v), "chg": chg, "h": hist}
        data["capex_map"] = capex_map
        print(f"capex: 序列{len(capex_map)}檔，擴產/縮減標籤{sum(1 for x in capex_note.values() if x['n'])}檔")
    except Exception as e:
        _sec_fail("capex未載入(可先跑 fetch_capex.py)", e)
        data["capex_map"] = {}

    # 產業地位描述(取分類表第一筆非空值)
    pos_lookup = {}
    for _, r in classification.iterrows():
        key = (r["country"], r["code"])
        if key not in pos_lookup and pd.notna(r["position_note"]) and r["position_note"]:
            pos_lookup[key] = r["position_note"]

    def enrich(code, country):
        info = latest_lookup.get((country, code))
        pinfo = prev_lookup.get((country, code))
        rank_delta = None
        if info is not None and pinfo is not None:
            rank_delta = int(pinfo["rank"]) - int(info["rank"])  # 正值=排名上升(變熱)
        f = fund_lookup.get((country, code), {})
        return {
            "gross_margin": f.get("gross_margin"),
            "revenue_growth": f.get("revenue_growth"),
            "pb": f.get("pb"),
            "eps_ttm": f.get("eps_ttm"),
            "eps_fwd": f.get("eps_fwd"),
            "position_note": pos_lookup.get((country, code), ""),
            "cn_note": cn_note.get(code, "") if country == "陸" else "",
            "capex_note": capex_note.get((country, code), {}).get("n", ""),
            "capex_hist": capex_note.get((country, code), {}).get("h", ""),
            "supplier_name": info["中文名稱"] if info is not None else code,
            "supplier_rank": int(info["rank"]) if info is not None else None,
            "supplier_rank_delta": rank_delta,
            "supplier_tier": info["熱度"] if info is not None else "",
            "supplier_amount_yi": info["金額億台幣"] if info is not None else "",
        }

    # 供應鏈(錨點客戶)資料
    try:
        import supply_chain as sc
        supply_links = []
        for sup_code, sup_country, cust_code, cust_country, product in sc.LINKS:
            rec = {
                "supplier_code": sup_code,
                "supplier_country": sup_country,
                "customer_code": cust_code,
                "customer_country": cust_country,
                "product": product,
            }
            rec.update(enrich(sup_code, sup_country))
            supply_links.append(rec)
        data["supply_links"] = supply_links
        data["supply_last_updated"] = sc.LAST_UPDATED
    except Exception as e:
        _sec_fail("供應鏈資料載入失敗", e)
        data["supply_links"] = []
        data["supply_last_updated"] = None

    # 進場訊號：套用檢查清單規則(源自記憶體案例研究)，每次匯出時重算
    try:
        from case_study_theme import COUNTRIES as SIG_C
        from case_study_theme import add_signals, load as sig_load, theme_series
        from scan_signals import BROAD as SIG_BROAD
        from scan_signals import find_triggers
        sig_rank, sig_cls = sig_load()
        tw_groups = set(sig_cls[sig_cls["country"] == "台"]["main_group"].unique())
        cnts = sig_cls.groupby("main_group")["code"].count()
        sig_themes = sorted(g for g in sig_cls["main_group"].unique()
                            if g in tw_groups and cnts.get(g, 0) >= 3 and g not in SIG_BROAD)
        # ⑥b 題材總營收動能：官方月營收成員加總YoY(>0且較上月改善=倉位加碼確認,回測弱加分不否決)
        _rv_conn = sqlite3.connect(DB_PATH)
        _rv = pd.read_sql("SELECT code, year_month, revenue, yoy_pct FROM tw_monthly_revenue", _rv_conn)
        _rv_conn.close()
        _rv_months = sorted(_rv.year_month.unique())

        def _agg_yoy(month, twmem):
            g = _rv[(_rv.year_month == month) & (_rv.code.isin(twmem))]
            g = g[pd.notna(g.yoy_pct) & (g.yoy_pct > -100) & pd.notna(g.revenue)]
            if len(g) < 3:
                return None, 0
            prev = (g.revenue / (1 + g.yoy_pct / 100)).sum()
            return (float(g.revenue.sum() / prev - 1) * 100 if prev else None), len(g)

        sig_current, sig_history = [], []
        for th in sig_themes:
            sdf = add_signals(theme_series(sig_rank, sig_cls, th))
            for t in find_triggers(sdf):
                t["theme"] = th
                sig_history.append(t)
            r = sdf.iloc[-1]
            rp = sdf.iloc[-2] if len(sdf) > 1 else None
            rising = sum(1 for c in SIG_C if rp is not None and (r[f"sub_{c}"] - rp[f"sub_{c}"]) > 0)
            max_share = max(r[f"sub_{c}"] for c in SIG_C) / r["score"] * 100 if r["score"] > 0 else 0
            b_ok = (pd.notna(r["breadth_up"]) and r["breadth_up"] >= 50
                    and rp is not None and pd.notna(rp["breadth_up"]) and rp["breadth_up"] >= 50)
            chk = {
                "theme": th, "score": round(float(r["score"]), 2),
                "streak": int(r["連漲週"]), "streak_ok": bool(r["連漲週"] >= 2),
                "breadth": int(r["breadth_up"]) if pd.notna(r["breadth_up"]) else None,
                "breadth_prev": int(rp["breadth_up"]) if rp is not None and pd.notna(rp["breadth_up"]) else None,
                "breadth_ok": bool(b_ok),
                "rising": int(rising), "rising_ok": bool(rising >= 3),
                "max_share": int(max_share), "share_ok": bool(max_share < 80),
                "pos": int(r["位階"] * 100), "stage": r["階段"],
            }
            # 基本面確認：題材成員中 EPS預估上修 與 季營收YoY為正 的比例
            mem = sig_cls[sig_cls["main_group"] == th][["country", "code"]].drop_duplicates()
            eps_up = eps_tot = rg_up = rg_tot = 0
            for _, mr in mem.iterrows():
                fv = fund_lookup.get((mr["country"], mr["code"]))
                if not fv:
                    continue
                et, ef = fv.get("eps_ttm"), fv.get("eps_fwd")
                if et is not None and ef is not None:
                    eps_tot += 1
                    if (et <= 0 and ef > 0) or (et > 0 and ef / et >= 1.05):
                        eps_up += 1
                if fv.get("revenue_growth") is not None:
                    rg_tot += 1
                    if fv["revenue_growth"] > 0:
                        rg_up += 1
            chk["eps_up_pct"] = int(eps_up / eps_tot * 100) if eps_tot else None
            chk["rg_up_pct"] = int(rg_up / rg_tot * 100) if rg_tot else None
            # ⑥b 題材總營收動能
            chk["rev_mom_yoy"] = chk["rev_mom_ok"] = None
            _twmem = set(sig_cls[(sig_cls["main_group"] == th) & (sig_cls["country"] == "台")]["code"])
            if len(_rv_months) >= 2 and _twmem:
                _ya, _na = _agg_yoy(_rv_months[-1], _twmem)
                _yb, _nb = _agg_yoy(_rv_months[-2], _twmem)
                if _ya is not None and _yb is not None and _na >= max(3, int(_nb * 0.6)):
                    chk["rev_mom_yoy"] = round(_ya, 1)
                    chk["rev_mom_ok"] = bool(_ya > 0 and _ya > _yb)
                elif _yb is not None:      # 最新月覆蓋不足(如颱風延報)→僅顯示前月YoY不判方向
                    chk["rev_mom_yoy"] = round(_yb, 1)
            chk["n_ok"] = sum([chk["streak_ok"], chk["breadth_ok"], chk["rising_ok"], chk["share_ok"]])
            sig_current.append(chk)
        sig_current.sort(key=lambda x: (-x["n_ok"], -x["score"]))

        # ⑤型態門檻(由內部模組計算，公式不進版控；頁面僅顯示✓/—)
        try:
            from pattern_check import evaluate as _pat_eval
            _tw_latest = sig_rank[(sig_rank["snapshot_date"] == sig_rank["snapshot_date"].max())
                                  & (sig_rank["country"] == "台")]
            _need_p = {}
            for c in sig_current:
                if c["n_ok"] < 3:
                    continue
                _memtw = set(sig_cls[(sig_cls["main_group"] == c["theme"])
                                     & (sig_cls["country"] == "台")]["code"])
                _top = _tw_latest[_tw_latest["code"].isin(_memtw)].nlargest(3, "twd")["code"].tolist()
                if len(_top) >= 2:
                    _need_p[c["theme"]] = _top
            _pats = _pat_eval(_need_p) if _need_p else {}
            print(f"⑤型態門檻評估 {len(_pats)} 題材，通過 {sum(1 for v in _pats.values() if v)}")
        except Exception as e:
            _pats = {}
            _sec_fail("⑤型態門檻未計算(不影響其他)", e)
        for c in sig_current:
            c["pat"] = _pats.get(c["theme"])
            if c["n_ok"] == 4:
                c["verdict"] = ("🔔 強訊號" if c["pat"]
                                else ("👀 觸發·⑤未過" if c["pat"] is False else "觸發(⑤未評估)"))
            else:
                c["verdict"] = ""

        # 前3大資金成員(回測口徑=觸發時買題材前3大台股等權持8週), 每題材都算供訊號頁直接顯示
        _twl = sig_rank[(sig_rank["snapshot_date"] == sig_rank["snapshot_date"].max())
                        & (sig_rank["country"] == "台")]
        for c in sig_current:
            _mem = set(sig_cls[(sig_cls["main_group"] == c["theme"])
                               & (sig_cls["country"] == "台")]["code"])
            _top = _twl[_twl["code"].isin(_mem)].nlargest(3, "twd")["code"].tolist()
            t3 = []
            for k in _top:
                info = latest_lookup.get(("台", k))
                t3.append([k, info["中文名稱"] if info is not None else ""])
            c["top3"] = t3

        # 大盤態勢(週線 vs 月線/季線 -> 建議倉位) + 推薦程度分級
        _tier, _tier_txt = 1.0, "月線上"
        try:
            import yfinance as _yf
            _tx = _yf.download("^TWII", period="8mo", interval="1wk",
                               auto_adjust=True, progress=False)["Close"]
            if hasattr(_tx, "iloc") and getattr(_tx, "ndim", 1) > 1:
                _tx = _tx.iloc[:, 0]
            _px = float(_tx.iloc[-1])
            _m4, _m13 = float(_tx.tail(4).mean()), float(_tx.tail(13).mean())
            if _px < _m13:
                _tier, _tier_txt = 0.3, "季線下"
            elif _px < _m4:
                _tier, _tier_txt = 0.6, "月線下"
        except Exception as e:
            _sec_fail("大盤態勢未取得(預設月線上)", e)
        data["market_tier"] = {"tier": _tier, "txt": _tier_txt}

        _th_hist = {g: [x["熱度分數"] for x in h] for g, h in theme_history.items()}
        for c in sig_current:
            sc_h = _th_hist.get(c["theme"], [])
            # 接刀警示(假說級): 題材熱度低於26週前 且 位階<40
            c["knife"] = bool(len(sc_h) >= 27 and sc_h[-1] < sc_h[-27] and c["pos"] < 40)
            g = ""
            if c["n_ok"] == 4 and c["pat"]:
                g = "S" if _tier >= 1.0 else "A"
            elif c["n_ok"] == 4 and c["pat"] is None:
                g = "A" if _tier >= 1.0 else "B"
            elif c["n_ok"] == 4:
                g = "B"
            elif c["n_ok"] == 3 and c["pat"]:
                g = "B"
            elif c["n_ok"] == 3:
                g = "C"
            if c["knife"] and g in ("S", "A", "B"):
                g = {"S": "A", "A": "B", "B": "C"}[g]
            c["grade"] = g
        sig_history.sort(key=lambda x: x["date"], reverse=True)
        data["signal_current"] = sig_current
        data["signal_history"] = sig_history
    except Exception as e:
        _sec_fail("進場訊號計算失敗", e)
        data["signal_current"] = []
        data["signal_history"] = []

    # 微題材脈衝雷達（規則v2：脈衝>=2.5x + 跳升中位>=+35名 + 毛利方向分級）
    try:
        import statistics

        from micro_themes import MICRO_THEMES
        conn_m = sqlite3.connect(DB_PATH)
        subp = pd.read_sql("SELECT DISTINCT code, sub_product FROM classification WHERE country='台'", conn_m)
        mh = pd.read_sql("SELECT code, quarter, gm FROM margin_history", conn_m)
        # 毛利方向：FinMind單季全史優先(2019起,已與MOPS對帳)，margin_history(yf)補未覆蓋成員
        fmq = pd.read_sql(
            "SELECT code, date, type, value FROM fm_income WHERE type IN ('GrossProfit','Revenue')", conn_m)
        conn_m.close()
        mdir = {}
        if len(fmq):
            fpv = fmq.pivot_table(index=["code", "date"], columns="type", values="value").reset_index()
            fpv = fpv[(fpv["Revenue"] > 0) & fpv["GrossProfit"].notna()]
            fpv["gm"] = fpv["GrossProfit"] / fpv["Revenue"] * 100
            for code, g in fpv.groupby("code"):
                v = g.sort_values("date")["gm"].tolist()
                if len(v) >= 2:
                    mdir[code] = {"d": round(v[-1] - v[-2], 1), "gm": round(v[-1], 1)}
        for code, g in mh.groupby("code"):
            if code in mdir:
                continue
            v = g.sort_values("quarter")["gm"].dropna().tolist()
            if len(v) >= 2:
                mdir[code] = {"d": round(v[-1] - v[-2], 1), "gm": round(v[-1], 1)}
        tw_rank = sig_rank[sig_rank["country"] == "台"]
        tw_total = tw_rank.groupby("snapshot_date")["twd"].sum()
        m_dates = sorted(tw_rank["snapshot_date"].unique())
        micro_current, micro_hist = [], []
        for name, cfg in MICRO_THEMES.items():
            kws, excl = cfg["kws"], set(cfg.get("exclude", []))
            mask = subp["sub_product"].fillna("").apply(lambda t: any(k.lower() in t.lower() for k in kws))
            codes = sorted(set(subp[mask]["code"]) - excl)
            if not codes:
                continue
            mem = tw_rank[tw_rank["code"].isin(codes)]
            svals, rmaps = [], []
            for d in m_dates:
                snap = mem[mem["snapshot_date"] == d]
                svals.append(float(snap["twd"].sum() / tw_total.get(d, 1) * 100))
                rmaps.append(dict(zip(snap["code"], snap["rank"])))

            def jump_at(i):
                js = [rmaps[i - 1][c] - rmaps[i][c] for c in rmaps[i] if c in rmaps[i - 1]]
                return statistics.median(js) if js else None

            for i in range(4, len(m_dates)):
                base = statistics.median(svals[i - 4:i])
                if base <= 0:
                    continue
                pulse = svals[i] / base
                j = jump_at(i)
                if pulse >= 2.5 and j is not None and j >= 35:
                    fwd, back = svals[i + 1:i + 5], svals[i - 4:i]
                    sus = round(sum(fwd) / 4 / (sum(back) / 4), 2) if len(fwd) == 4 and sum(back) > 0 else None
                    micro_hist.append({"date": m_dates[i], "theme": name,
                                       "pulse": round(pulse, 2), "jump": int(j), "sustain": sus})
            i = len(m_dates) - 1
            base = statistics.median(svals[i - 4:i]) if i >= 4 else 0
            pulse = round(svals[i] / base, 2) if base > 0 else None
            j = jump_at(i) if i >= 1 else None
            up = sum(1 for c in codes if c in mdir and mdir[c]["d"] > 0)
            nd = sum(1 for c in codes if c in mdir)
            trig = bool(pulse is not None and pulse >= 2.5 and j is not None and j >= 35)
            level = ""
            if trig:
                level = "🅰 脈衝+毛利升" if nd and up * 2 > nd else "🅱 脈衝(待季報驗證)"
            prior8 = max(svals[max(0, i - 8):i]) if i >= 1 else 0
            members = []
            for c in codes:
                info = latest_lookup.get(("台", c))
                md = mdir.get(c)
                members.append({"code": c,
                                "name": info["中文名稱"] if info is not None else c,
                                "rank": int(info["rank"]) if info is not None else None,
                                "gm": md["gm"] if md else None,
                                "gmd": md["d"] if md else None})
            micro_current.append({"theme": name, "n": len(codes), "score": round(svals[i], 3),
                                  "pulse": pulse, "jump": int(j) if j is not None else None,
                                  "m_up": up, "m_n": nd, "level": level,
                                  "second": bool(trig and prior8 > svals[i]),
                                  "members": members})
        # 微題材推薦程度(證據上限⭐⭐：精選勝率~68%)：觸發+毛利過半升=標準，二次脈衝/大盤轉弱各降一級
        _mt = (data.get("market_tier") or {}).get("tier", 1.0)
        for c in micro_current:
            if not c["level"]:
                c["grade"] = ""
                continue
            g = "A" if (c["m_n"] and c["m_up"] * 2 > c["m_n"]) else "B"
            if c["second"]:
                g = {"A": "B", "B": "C"}[g]
            if _mt < 1.0:
                g = {"A": "B", "B": "C", "C": "C"}[g]
            c["grade"] = g
        micro_current.sort(key=lambda x: -(x["pulse"] or 0))
        micro_hist.sort(key=lambda x: x["date"], reverse=True)
        data["micro_current"] = micro_current
        data["micro_history"] = micro_hist
    except Exception as e:
        _sec_fail("微題材雷達計算失敗", e)
        data["micro_current"] = []
        data["micro_history"] = []

    # 籌碼確認徽章(觀察層): 外資20日累計自身位階 / 券資比自身位階(近240交易日百分位)
    try:
        conn_c = sqlite3.connect(DB_PATH)
        _flc = pd.read_sql("SELECT date, code, foreign_net FROM inst_flow "
                           "WHERE date >= date((SELECT MAX(date) FROM inst_flow), '-420 day')", conn_c)
        _mgc = pd.read_sql("SELECT date, code, short_fin_ratio FROM margin_flow "
                           "WHERE date >= date((SELECT MAX(date) FROM margin_flow), '-420 day')", conn_c)
        conn_c.close()
        _fr = (_flc.pivot_table(index="date", columns="code", values="foreign_net")
               .rolling(20, min_periods=10).sum()
               .rolling(240, min_periods=120).rank(pct=True))
        _sr = (_mgc.pivot_table(index="date", columns="code", values="short_fin_ratio")
               .rolling(240, min_periods=120).rank(pct=True))
        _fl_last, _sr_last = _fr.iloc[-1], (_sr.iloc[-1] if len(_sr) else pd.Series(dtype=float))
        chip = {}
        for code in set(_fl_last.index) | set(_sr_last.index):
            rec = {}
            fv, sv = _fl_last.get(code), _sr_last.get(code)
            if pd.notna(fv):
                rec["f"] = int(round(fv * 100))
            if pd.notna(sv):
                rec["s"] = int(round(sv * 100))
            if rec:
                chip[code] = rec
        data["chip"] = chip
        data["chip_date"] = str(_flc.date.max())
        print(f"籌碼位階徽章 {len(chip)} 檔 (資料至 {data['chip_date']})")
    except Exception as e:
        data["chip"] = {}
        _sec_fail("籌碼徽章未計算(不影響其他)", e)

    # 共振標籤(2026-07-22上板,觀察層): 同題材同週>=2檔「日線爆量長紅創高+週線同步創高」共振,
    # 讀build_resonance_theme.py產出的tmp_resonance_theme_events.pkl(需定期重跑刷新,建議併入每週例行)
    # 只標記最近8週內(比照研究裡的HOLD=8週)還在窗內的事件,舊的不顯示避免誤導成「現在」還在共振
    try:
        _reso_ev = pd.read_pickle("tmp_resonance_theme_events.pkl")
        _reso_ev["week"] = pd.to_datetime(_reso_ev["week"])
        _reso_last = _reso_ev["week"].max()
        _reso_recent = _reso_ev[_reso_ev["week"] >= _reso_last - pd.Timedelta(weeks=8)]
        resonance = {}
        for _, _r in _reso_recent.sort_values("week").iterrows():
            for _c in _r["members"]:
                resonance[_c] = {"theme": _r["theme"], "n_members": int(_r["n_members"]),
                                  "week": str(_r["week"].date()),
                                  "weeks_ago": int(round((_reso_last - _r["week"]).days / 7))}
        data["resonance"] = resonance
        data["resonance_asof"] = str(_reso_last.date())
        _conn_r = sqlite3.connect(DB_PATH)
        _nm_r = dict(_conn_r.execute("SELECT code, name_zh FROM company_names WHERE country='台'"))
        _conn_r.close()
        # company_names覆蓋不全(小型股常缺,如共振事件裡的2375/3042等),補rankings表的name欄位
        _nm_r.update({k: v for k, v in rankings[rankings["country"] == "台"]
                      .drop_duplicates("code", keep="last").set_index("code")["name"].items()
                      if k not in _nm_r or not _nm_r[k]})
        _cur_ev = (_reso_recent.sort_values(["week", "n_members"], ascending=[False, False])
                   .drop_duplicates(["theme", "week"]))
        data["resonance_current"] = [
            {"theme": _r["theme"], "week": str(_r["week"].date()), "n_members": int(_r["n_members"]),
             "weeks_ago": int(round((_reso_last - _r["week"]).days / 7)),
             "members": [{"code": _c, "name": _nm_r.get(_c, _c)} for _c in _r["members"]]}
            for _, _r in _cur_ev.iterrows()
        ]
        print(f"共振標籤 {len(resonance)}檔在窗 ({len(data['resonance_current'])}個題材-週事件,最近8週內,"
              f"資料至{data['resonance_asof']},特徵=日線爆量長紅創高+週線同步創高)")
    except Exception as e:
        data["resonance"] = {}
        data["resonance_current"] = []
        _sec_fail("共振標籤未計算(需先跑build_resonance_theme.py產生tmp_resonance_theme_events.pkl)", e)

    # 產業鏈(橫向上中下游)資料
    try:
        import industry_chains as ic
        chain_links = []
        for chain, stage, code, country, role in ic.CHAIN_LINKS:
            rec = {
                "chain": chain,
                "stage": stage,
                "supplier_code": code,
                "supplier_country": country,
                "product": role,
            }
            rec.update(enrich(code, country))
            chain_links.append(rec)
        data["industry_chains"] = chain_links
        data["industry_chain_list"] = ic.CHAINS

        # 每鏈每週熱度分數(排行用)：成員台幣金額佔各國總額比例加總×100，與題材熱度同一把尺
        tot_by = rankings.groupby(["snapshot_date", "country"])["金額億台幣_num"].sum()
        amt_idx = rankings.set_index(["snapshot_date", "country", "code"])["金額億台幣_num"]
        chain_hist = {}
        for chain in ic.CHAINS:
            mem = set((code, country) for ch2, _st, code, country, _r in ic.CHAIN_LINKS if ch2 == chain)
            vals = []
            for d in all_dates:
                s = 0.0
                for code, country in mem:
                    try:
                        a = amt_idx.loc[(d, country, code)]
                    except KeyError:
                        continue
                    t = tot_by.loc[(d, country)]
                    if pd.notna(a) and t > 0:
                        s += float(a) / float(t) * 100
                vals.append(round(s, 2))
            chain_hist[chain] = vals
        data["chain_history"] = chain_hist
    except Exception as e:
        _sec_fail("產業鏈資料載入失敗", e)
        data["industry_chains"] = []
        data["industry_chain_list"] = []
        data["chain_history"] = {}

    # 公司→題材/產業鏈歸屬(公司歷史頁資訊面板用)
    try:
        grp_map = {}
        for _, r in classification.iterrows():
            grp_map.setdefault((r["country"], r["code"]), []).append((r["main_group"], r["sub_product"]))
        chain_map = {}
        for l in data.get("industry_chains", []):
            k = (l["supplier_country"], l["supplier_code"])
            chain_map.setdefault(k, [])
            if l["chain"] not in chain_map[k]:
                chain_map[k].append(l["chain"])
        comp_info = {}
        for key in company_history:
            country, code = key.split("|", 1)
            gs = grp_map.get((country, code), [])
            comp_info[key] = {
                "g": sorted(set(g for g, s in gs)),
                "sub": "、".join(sorted(set(s for g, s in gs if pd.notna(s) and s))[:3]),
                "ch": chain_map.get((country, code), []),
            }
        data["company_info"] = comp_info
    except Exception as e:
        _sec_fail("公司資訊面板資料失敗", e)
        data["company_info"] = {}

    # 補漲雷達：題材點火時，篩「尚未點火」且符合研究員邏輯(低PB/營收轉正/低位階)的台股成員
    try:
        import numpy as _np
        conn_c = sqlite3.connect(DB_PATH)
        pb_map = dict(conn_c.execute("SELECT code, pb FROM tw_valuation WHERE pb IS NOT NULL"))
        pb_median = float(_np.median(list(pb_map.values()))) if pb_map else 2.0
        rev_map = {}
        for code, yoy in conn_c.execute(
                """SELECT code, yoy_pct FROM tw_monthly_revenue m
                   WHERE year_month=(SELECT MAX(year_month) FROM tw_monthly_revenue)"""):
            rev_map[code] = yoy
        eps_map = dict(conn_c.execute(
            "SELECT code, eps_fwd FROM fundamentals WHERE country='台' AND eps_ttm<=0 AND eps_fwd>0"))
        conn_c.close()

        def _z_ignite(vals):
            """最新一週變化是否z>1；資料不足視為未點火"""
            if len(vals) < 6:
                return False, None
            d = _np.diff(vals)
            sd = d.std()
            pos = float((_np.array(vals) <= vals[-1]).mean() * 100)
            return (sd > 0 and d[-1] / sd > 1.0), pos

        # 點火題材 = 最新週熱度Δ z>1 或 檢查清單verdict觸發
        ignited = set(c["theme"] for c in data.get("signal_current", []) if c.get("verdict"))
        for g, hist in theme_history.items():
            sc = [h["熱度分數"] for h in hist]
            fire, _p = _z_ignite(sc)
            if fire:
                ignited.add(g)
        ignited -= BROAD_GROUPS

        last_idx = len(all_dates) - 1
        tw_cls = classification[classification["country"] == "台"]
        catchup_rows = []
        for g in sorted(ignited):
            mem_codes = tw_cls[tw_cls["main_group"] == g]["code"].unique()
            if len(mem_codes) < 3:
                continue
            for code in mem_codes:
                e = company_history.get(f"台|{code}")
                if not e:
                    continue
                amts = [r[3] or 0 for r in e["rows"]]
                fire, pos = _z_ignite(amts)
                if fire:
                    continue                     # 已點火的不是補漲候選
                tags = []
                pb = pb_map.get(code)
                if pb is not None and pb <= pb_median:
                    tags.append(f"低PB {pb}")
                yoy = rev_map.get(code)
                if yoy is not None and yoy > 0:
                    tags.append(f"營收YoY+{round(yoy)}%")
                if pos is not None and pos < 50:
                    tags.append(f"資金低位階{round(pos)}%")
                if code in eps_map:
                    tags.append("預估虧轉盈")
                if len(tags) < 2:
                    continue
                last_row = e["rows"][-1]
                catchup_rows.append({
                    "theme": g, "code": code,
                    "name": e["label"].split(" ", 2)[-1],
                    "rank": last_row[1] if last_row[0] == last_idx else None,
                    "pb": pb, "yoy": (round(yoy, 1) if yoy is not None else None),
                    "pos": (round(pos) if pos is not None else None),
                    "tags": tags, "n_tags": len(tags),
                })
        # 補漲雷達優先序(未回測=研究優先序非信心)：理由≥3且所屬題材為S/A級=優先，其一=一般
        _tg = {c["theme"]: c.get("grade") for c in data.get("signal_current", [])}
        for r in catchup_rows:
            strong_theme = _tg.get(r["theme"]) in ("S", "A")
            r["grade"] = ("A" if (r["n_tags"] >= 3 and strong_theme)
                          else ("B" if (r["n_tags"] >= 3 or strong_theme) else ""))
        catchup_rows.sort(key=lambda r: (-r["n_tags"], r["pb"] if r["pb"] is not None else 99))
        data["catchup_radar"] = {"themes": sorted(ignited), "rows": catchup_rows[:60]}
    except Exception as e:
        _sec_fail("補漲雷達計算失敗", e)
        data["catchup_radar"] = {"themes": [], "rows": []}

    # ---- ⑫題材月營收動能score(2026-07-14上線;凍結研究口徑,正式builder=build_theme_score_topn.py) ----
    # score=巢狀MoM streak(0-3)+近3月YoY均值>0加1分;sig[i]=以資料月i收口的訊號,進場=次月15號(全shift無look-ahead)
    # 回測:score=4 TWII超額中位+2.55%/勝率56%(828筆/115題材-月,LOTO+cluster bootstrap通過);V2倉位=訊號照進×大盤tier
    try:
        _c2 = sqlite3.connect(DB_PATH)
        _fmr = pd.read_sql("SELECT code, date, revenue FROM fm_month_rev", _c2, dtype={"code": str})
        _c2.close()
        _fmr["m"] = pd.to_datetime(_fmr["date"])
        # FinMind date=公告月(營收月+1,已比對官方表證實:fm 2026-06-01=官方11505五月營收)。
        # 最新公告月FinMind常只回補部分公司→截斷到覆蓋完整的月份,避免殘缺加總污染MoM
        _cnt = _fmr.groupby("m")["code"].nunique()
        _typ = _cnt.tail(13).head(12).median()
        _ok_months = _cnt[_cnt >= _typ * 0.7].index
        _fmr = _fmr[_fmr["m"] <= _ok_months.max()]
        # 顯示用月份=營收月(公告月-1);凍結回測口徑:營收月r公告於r+1月10-15號,進場=r+2月15號
        _fmr["m"] = _fmr["m"] - pd.offsets.MonthBegin(1)
        _cls_tw = classification[classification["country"] == "台"][["code", "main_group"]].drop_duplicates()
        _twn = (rankings[rankings["country"] == "台"].drop_duplicates("code", keep="last")
                .set_index("code")["中文名稱"].to_dict())
        tm_themes = {}
        for _g, _mem in _cls_tw.groupby("main_group"):
            _rv = _fmr[_fmr["code"].isin(_mem["code"])]
            if _rv["code"].nunique() < 3:  # 題材>=3家FinMind覆蓋(回測門檻)
                continue
            _wide = _rv.pivot_table(index="m", columns="code", values="revenue", aggfunc="first").sort_index()
            # 該月「完整」=前5大營收成員(占題材金額中位97%)全數已申報——家數覆蓋率會漏掉
            # 「缺大戶」情境(如fm最新月2330未回補=缺4千億),用價值覆蓋判斷;缺口>2月退回原序列防死鎖
            _t5c = list(_wide.tail(12).mean().sort_values(ascending=False).head(5).index)
            _full = _wide[_t5c].notna().all(axis=1)
            if _full.any():
                _cut = _full[_full].index.max()
                if (_wide.index.max().to_period("M") - _cut.to_period("M")).n <= 2:
                    _wide = _wide[_wide.index <= _cut]
                else:
                    print(f"  ⚠題材{_g}: 前5大成員申報缺口>2月,未截斷(檢查是否有成員停止申報)")
            _tot = _wide.sum(axis=1, min_count=1)
            _mom = _tot.pct_change(fill_method=None) * 100
            _yoy = _tot.pct_change(12, fill_method=None) * 100
            _s1, _s2, _s3 = _mom.gt(0), _mom.shift(1).gt(0), _mom.shift(2).gt(0)
            _msc = pd.Series(0, index=_tot.index)
            _msc[_s1] = 1
            _msc[_s1 & _s2] = 2
            _msc[_s1 & _s2 & _s3] = 3
            _ty3 = _yoy.rolling(3).mean()
            _sig = _msc + _ty3.gt(0).astype(int)
            _tail = _tot.index  # 全史(fm起2019,約90個月);範圍裁切在前端做
            _trail12 = _wide.tail(12).mean()
            _base = _trail12.sum()
            _top5_rows = []
            for _cd, _avg in _trail12.sort_values(ascending=False).head(5).items():
                _col = _wide[_cd]
                _lr = _col.iloc[-1]
                _ly = None
                if len(_col) >= 13 and pd.notna(_col.iloc[-1]) and pd.notna(_col.iloc[-13]) and _col.iloc[-13]:
                    _ly = round(float(_col.iloc[-1] / _col.iloc[-13] - 1) * 100, 1)
                _top5_rows.append([_cd, _twn.get(_cd, ""),
                                   round(float(_avg / _base * 100), 1) if _base else None,
                                   round(float(_lr) / 1e8, 1) if pd.notna(_lr) else None, _ly])

            def _ser(s):
                return [None if pd.isna(v) else round(float(v), 1) for v in s.reindex(_tail)]

            tm_themes[_g] = {
                "months": [d.strftime("%Y-%m") for d in _tail],
                "rev": [None if pd.isna(v) else round(float(v) / 1e8, 1) for v in _tot.reindex(_tail)],
                "mom": _ser(_mom), "yoy": _ser(_yoy),
                "sig": [int(v) for v in _sig.reindex(_tail).fillna(0)],
                "score": int(_sig.iloc[-1]), "msc": int(_msc.iloc[-1]),
                "ty3": None if pd.isna(_ty3.iloc[-1]) else round(float(_ty3.iloc[-1]), 1),
                "mom3": [None if pd.isna(v) else round(float(v), 1)
                         for v in [_mom.iloc[-1], _mom.iloc[-2], _mom.iloc[-3]]],
                "top5": _top5_rows, "n": int(_rv["code"].nunique()),
            }
        _asof = max(v["months"][-1] for v in tm_themes.values()) if tm_themes else None
        data["theme_momentum"] = {"asof": _asof, "themes": tm_themes}
        _trig = [g for g, v in tm_themes.items() if v["score"] == 4 and v["months"][-1] == _asof]
        print(f"題材營收動能: {len(tm_themes)}題材, 資料至{_asof}, score=4觸發={_trig}")
    except Exception as e:
        _sec_fail("題材營收動能未產生", e)
        data["theme_momentum"] = {"asof": None, "themes": {}}

    # ---- 處置股觀察(2026-07-16上線;回測=build_disposition_event.py,bootstrap CI[+2.30,+4.91]p<1e-4) ----
    # 口徑: V4=第3處置日尾盤買 / V5=倒數第3日尾盤買(前段跌更佳) / 出場=出關日開盤(出關起連三日負)
    # 未來交易日以平日近似(遇休市順延,誤差1-2日屬正常),前端依當天日期高亮行動列
    try:
        _c5 = sqlite3.connect(DB_PATH)
        _dsp = pd.read_sql("SELECT * FROM disposition", _c5)
        for _cc in ("start_date", "end_date"):
            _dsp[_cc] = pd.to_datetime(_dsp[_cc], errors="coerce")
        _dsp = _dsp.dropna(subset=["start_date", "end_date"])
        _today5 = pd.Timestamp.today().normalize()
        _act = _dsp[_dsp.end_date >= _today5 - pd.Timedelta(days=7)].copy()
        _cal5 = pd.to_datetime(pd.read_sql(
            "SELECT DISTINCT date FROM fm_daily_price ORDER BY date", _c5)["date"]).tolist()
        _dsp_rows = []
        if len(_act) and _cal5:
            _codes5 = sorted(_act.code.unique())
            _px5 = pd.read_sql(
                "SELECT code, date, close, money FROM fm_daily_price WHERE code IN (%s)"
                % ",".join("?" * len(_codes5)), _c5, params=_codes5)
            _px5["date"] = pd.to_datetime(_px5.date)
            _pxmap = {c: g.sort_values("date") for c, g in _px5.groupby("code")}
            _cls5 = classification[classification["country"] == "台"][["code", "main_group"]] \
                .drop_duplicates("code").set_index("code")["main_group"].to_dict()
            _nm5 = (rankings[rankings["country"] == "台"].drop_duplicates("code", keep="last")
                    .set_index("code")["中文名稱"].to_dict())

            def _next_tdays(base, n):
                """base之後第n個交易日:日曆內用日曆,超出用平日近似"""
                fut = [d for d in _cal5 if d > base]
                if len(fut) >= n:
                    return fut[n - 1]
                d, left = (_cal5[-1] if _cal5[-1] > base else base), n - len(fut)
                while left > 0:
                    d += pd.Timedelta(days=1)
                    if d.weekday() < 5:
                        left -= 1
                return d

            for _, _e in _act.iterrows():
                _sidx = [d for d in _cal5 if d >= _e.start_date]
                if not _sidx:
                    continue
                _s0 = _sidx[0]
                _inwin = [d for d in _cal5 if _e.start_date <= d <= _e.end_date]
                _seq = len(_inwin)  # 資料日曆內已走的處置日數
                _v4d = _next_tdays(_s0, 2) if _s0 in _cal5 else _next_tdays(_e.start_date, 3)
                # 末日=處置迄日(官方公告含順延);倒數第3日/出關日用近似
                _endd = _e.end_date
                _v5d = _endd
                _cnt = 0
                _dv5 = _endd
                while _cnt < 2:  # 末日往前退2個平日=倒數第3日(近似)
                    _dv5 -= pd.Timedelta(days=1)
                    if _dv5.weekday() < 5:
                        _cnt += 1
                _exitd = _endd + pd.Timedelta(days=1)
                while _exitd.weekday() >= 5:
                    _exitd += pd.Timedelta(days=1)
                _g5 = _pxmap.get(_e.code)
                _pre, _tv3, _last, _cap = None, None, None, None
                if _g5 is not None and len(_g5):
                    _w = _g5[_g5.date >= _s0]
                    _b4 = _g5[_g5.date < _s0].tail(20)
                    if len(_b4) >= 5:
                        _cap = round(float(_b4.money.mean()) / 1e8, 1)  # 處置前20日均成交值=胃納量
                    if len(_w) and _w.close.iloc[0] > 0:
                        _pre = round(float(_w.close.iloc[-1] / _w.close.iloc[0] - 1) * 100, 1)
                        if len(_w) >= 3 and _w.money.iloc[2] > 0:
                            _tv3 = round(float(_w.money.iloc[2]) / 1e8, 2)
                        _last = _w.date.iloc[-1].strftime("%Y-%m-%d")
                _poison = "人工管制" in str(_e.reason)
                _dsp_rows.append({
                    "code": _e.code, "name": _nm5.get(_e.code, ""),
                    "mkt": _e.market, "cum": int(_e.cum_count or 1), "mins": _e.match_min,
                    "theme": _cls5.get(_e.code), "poison": _poison,
                    "start": _e.start_date.strftime("%Y-%m-%d"), "end": _endd.strftime("%Y-%m-%d"),
                    "seq": _seq, "pre": _pre, "tv3": _tv3, "cap": _cap, "px_asof": _last,
                    "v4d": _v4d.strftime("%Y-%m-%d"), "v5d": _dv5.strftime("%Y-%m-%d"),
                    "exitd": _exitd.strftime("%Y-%m-%d"),
                })
        _c5.close()
        data["disposition"] = {"asof": _cal5[-1].strftime("%Y-%m-%d") if _cal5 else None,
                               "rows": _dsp_rows}
        print(f"處置股觀察: {len(_dsp_rows)}檔在窗(價格日曆至{data['disposition']['asof']})")
    except Exception as e:
        _sec_fail("處置股觀察未產生", e)
        data["disposition"] = {"asof": None, "rows": []}

    # 資料健康狀態列：各資料源最新日期+新鮮度(門檻依各源的正常更新節奏)
    try:
        from datetime import date as _date
        from datetime import datetime as _dt
        conn_h = sqlite3.connect(DB_PATH)
        today = _date.today()

        def _q(sql):
            try:
                return conn_h.execute(sql).fetchone()[0]
            except Exception:
                return None

        def _item(name, latest, ok_days, warn_days, cadence, disp=None, age_from=None):
            if not latest:
                return {"n": name, "d": "無資料", "s": "crit", "c": cadence}
            try:
                base = _dt.strptime((age_from or latest)[:10], "%Y-%m-%d").date()
            except ValueError:
                return {"n": name, "d": disp or latest, "s": "warn", "c": cadence}
            age = (today - base).days
            s = "ok" if age <= ok_days else ("warn" if age <= warn_days else "crit")
            return {"n": name, "d": disp or latest[:10], "s": s, "a": age, "c": cadence}

        health = [
            _item("資金排行", _q("SELECT MAX(snapshot_date) FROM rankings"), 9, 16, "每週"),
            _item("週收盤價", _q("SELECT MAX(snapshot_date) FROM weekly_close"), 9, 16, "每週"),
            _item("匯率", _q("SELECT MAX(snapshot_date) FROM fx_rates"), 9, 16, "每週"),
            # FinMind月營收(題材營收動能訊號源):公告月+15天內=正常,>45天=訊號已過期一輪
            _item("FinMind月營收", _q("SELECT MAX(date) FROM fm_month_rev"), 45, 75, "每月10-15號後"),
        ]
        # 月營收完整度守門(2026-07-19漢唐案例:FinMind收晚申報者有時差→缺29檔→題材卡舊月+score觸發被漏)
        # 評估月=最新一個「家數>=常態一半」的公告月(避開每月1-10號新cohort剛開的假警報)
        _mc = conn_h.execute("SELECT date, COUNT(DISTINCT code) FROM fm_month_rev "
                             "GROUP BY date ORDER BY date DESC LIMIT 14").fetchall()
        if len(_mc) > 2:
            _typ = sorted(n for _, n in _mc[1:])[len(_mc[1:]) // 2]
            _eval = next(((d, n) for d, n in _mc if n >= _typ * 0.5), _mc[0])
            _ratio = _eval[1] / _typ if _typ else 1
            health.append({"n": "月營收完整度", "d": f"{_eval[1]}/{_typ}檔({_eval[0][:7]})",
                           "s": "ok" if _ratio >= 0.95 else ("warn" if _ratio >= 0.85 else "crit"),
                           "c": "缺漏→python fetch_month_rev_gap.py 後重跑export"})
        ym = _q("SELECT MAX(year_month) FROM tw_monthly_revenue")   # 民國YYYMM
        if ym:
            y, m = int(str(ym)[:-2]) + 1911, int(str(ym)[-2:])
            # 以該月月底起算：次月10日公告完+緩衝，超過45天=下個月營收該補了
            me = _date(y + (1 if m == 12 else 0), 1 if m == 12 else m + 1, 1)
            health.append(_item("月營收(官方)", str(me), 45, 75, "每月10日後",
                                disp=f"{y}-{m:02d}", age_from=str(me)))
        else:
            health.append(_item("月營收(官方)", None, 0, 0, "每月10日後"))
        qt = _q("SELECT MAX(quarter) FROM tw_quarterly_fin")        # 民國YYYQn
        if qt:
            qy, qn = int(str(qt).split("Q")[0]) + 1911, int(str(qt).split("Q")[1])
            qe = [None, _date(qy, 3, 31), _date(qy, 6, 30), _date(qy, 9, 30), _date(qy, 12, 31)][qn]
            health.append(_item("季財報(官方)", str(qe), 140, 200, "每季報後",
                                disp=f"{qy}Q{qn}", age_from=str(qe)))
        else:
            health.append(_item("季財報(官方)", None, 0, 0, "每季報後"))
        health += [
            _item("日價(FinMind)", _q("SELECT MAX(date) FROM fm_daily_price"), 9, 16,
                  "每週(fetch_daily_price增量)"),
            _item("處置表", _q("SELECT MAX(announce_date) FROM disposition"), 12, 30,
                  "每週(fetch_disposition)"),
            _item("解質異動", _q("SELECT MAX(digest_date) FROM pledge_moves"), 9, 16,
                  "每週(fetch_pledge)"),
            _item("PB估值(官方)", _q("SELECT MAX(updated) FROM tw_valuation"), 40, 80, "每月"),
            _item("五國基本面(yf)", _q("SELECT MAX(updated) FROM fundamentals"), 100, 150, "每季"),
            _item("微題材毛利", _q("SELECT MAX(updated) FROM margin_history"), 100, 150, "每季"),
            _item("資本支出(yf)", _q("SELECT MAX(updated) FROM capex_history"), 100, 150, "每季"),
            _item("供應鏈標註", data.get("supply_last_updated"), 60, 120, "手動(Gemini)"),
        ]
        conn_h.close()
        data["health"] = health
    except Exception as e:
        _sec_fail("資料健康列計算失敗", e)
        data["health"] = []

    # 題材成員速查(2026-07-19使用者反饋: 熱力圖看得到「汽車零件」卻查不到成員——
    # 台股成員<3不進解剖選單/供應鏈僅16條/產業歷史=公司維度,三處都查不到;
    # 解法=classification全名單進payload,全站題材名旁👥彈窗列全市場成員)
    try:
        _tw_nm = (rankings[rankings.country == "台"].sort_values("snapshot_date")
                  .drop_duplicates("code", keep="last").set_index("code")["中文名稱"].to_dict())
        _nm_all = {}
        for r in names.itertuples():
            _n = getattr(r, "name_zh", None) or getattr(r, "name", None)
            if isinstance(_n, str):
                _nm_all[(r.country, r.code)] = _n
        _rk_now = {(r.country, r.code): int(r.rank) for r in latest.itertuples()}
        _morder = {"台": 0, "美": 1, "日": 2, "韓": 3, "陸": 4}
        _tm_map = {}
        for r in classification.itertuples():
            _n = _tw_nm.get(r.code, "") if r.country == "台" else (_nm_all.get((r.country, r.code)) or "")
            _sp = r.sub_product if isinstance(r.sub_product, str) else ""
            _tm_map.setdefault(r.main_group, []).append(
                [r.country, r.code, _n, _sp, _rk_now.get((r.country, r.code))])
        for _g in _tm_map:
            _tm_map[_g].sort(key=lambda x: (_morder.get(x[0], 9), x[1]))
        data["theme_members"] = _tm_map
    except Exception as e:
        _sec_fail("題材成員速查未產生", e)
        data["theme_members"] = {}

    # ---- 大盤溫度計(2026-07-19使用者裁示上板: 市場層五燈+水位讀數) ----
    # 口徑: 甜蜜格/跌停家數=研究池1379檔(與判決同尺,全市場版待複跑升級);跌停=前收×0.9進位至tick近似
    try:
        import math as _math

        import numpy as np
        _c6 = sqlite3.connect(DB_PATH)
        _px6 = pd.read_sql(
            "SELECT code, date, close, money FROM fm_daily_price WHERE close>0 "
            "AND date >= (SELECT date(MAX(date), '-260 day') FROM fm_daily_price)",
            _c6, parse_dates=["date"])
        _idx6 = {m: pd.read_sql("SELECT date, close FROM index_daily WHERE market=? ORDER BY date",
                                _c6, params=(m,), parse_dates=["date"]).set_index("date").close
                 for m in ("TAIEX", "N225", "KOSPI", "SPX")}
        _mm6 = pd.read_sql("SELECT date, ratio FROM margin_maintenance_official "
                           "WHERE ratio>=100 ORDER BY date", _c6, parse_dates=["date"])
        _c6.close()
        _lf6 = pd.read_pickle("tmp_limit_flags.pkl")
        _pool6 = set(_lf6[~_lf6.code.str.startswith("00")].code.unique())
        _px6 = _px6[_px6.code.isin(_pool6)]

        _twc = _idx6["TAIEX"]
        _tw_dates = [d for d in _twc.index
                     if d >= _px6.date.min() + pd.Timedelta(days=75) and d <= _px6.date.max()][-70:]
        _sweet = {d: 0 for d in _tw_dates}
        _ldcnt = {d: 0 for d in _tw_dates}

        def _tick6(p):
            return (0.01 if p < 10 else 0.05 if p < 50 else 0.1 if p < 100
                    else 0.5 if p < 500 else 1 if p < 1000 else 5)

        _dset6 = set(_tw_dates)
        for _code, _g6 in _px6.groupby("code"):
            _g6 = _g6.sort_values("date").reset_index(drop=True)
            _cl = _g6.close
            _c1 = _cl.shift(1)
            _run = _cl.rolling(15).max() > _cl.rolling(40).min() * 1.2
            _ddp = (_cl / _c1 - 1) * 100
            _pull = (1 - _cl / _cl.rolling(10).max()) * 100
            _tv = _g6.money / 1e8
            _sw = (_run & (_tv > 1) & (_ddp <= -6) & (_ddp > -9) & (_pull >= 20)).fillna(False)
            for _i in range(1, len(_g6)):
                _d = _g6.date[_i]
                if _d not in _dset6:
                    continue
                if _sw.iloc[_i]:
                    _sweet[_d] += 1
                _pv = _c1.iloc[_i]
                if pd.notna(_pv) and _pv > 0:
                    _raw = _pv * 0.9
                    _t = _tick6(_raw)
                    if _cl.iloc[_i] <= _math.ceil(_raw / _t - 1e-9) * _t + 1e-9:
                        _ldcnt[_d] += 1

        _twr6 = _twc.pct_change() * 100
        _n2r6 = _idx6["N225"].pct_change() * 100
        _kor6 = _idx6["KOSPI"].pct_change() * 100
        _spr6 = _idx6["SPX"].pct_change() * 100
        _dd250_6 = (_twc / _twc.rolling(250, min_periods=120).max() - 1) * 100
        _drop10_6 = (_twc / _twc.shift(10) - 1) * 100

        def _us_prev(d):
            _si = _spr6.index.searchsorted(d) - 1
            return float(_spr6.iloc[_si]) if _si >= 0 else np.nan

        _bdays6, _conv6 = [], []
        for _d in _twc.index[-30:]:
            _nv = float(_n2r6[_d]) if _d in _n2r6.index else np.nan
            _kv = float(_kor6[_d]) if _d in _kor6.index else np.nan
            _uv = _us_prev(_d)
            if (pd.notna(_nv) and pd.notna(_kv) and pd.notna(_uv)
                    and _nv <= -2 and _kv <= -2 and _uv > -1):
                _bdays6.append(_d)
            _dv, _rv, _d10 = _dd250_6.get(_d), _twr6.get(_d), _drop10_6.get(_d)
            if (pd.notna(_dv) and -20 < _dv <= -10 and pd.notna(_rv) and _rv <= -2
                    and pd.notna(_d10) and _d10 <= -6):
                _conv6.append(_d)

        _pos6 = {d: i for i, d in enumerate(_twc.index)}
        _tp6 = _pos6[_tw_dates[-1]]

        def _remain6(days, hold):
            _act = [_pos6[d] for d in days if d in _pos6 and _pos6[d] + hold > _tp6]
            return (max(_act) + hold - _tp6) if _act else 0

        _thd6 = [d for d in _tw_dates if _sweet[d] >= 20]
        _ldd6 = [d for d in _tw_dates if _ldcnt[d] >= 20]
        _last6 = _tw_dates[-1]
        _mm_last = _mm6.iloc[-1]
        _lit = {"thermo": _remain6(_thd6, 60) > 0, "b": _remain6(_bdays6, 10) > 0,
                "warn": bool(_mm_last.ratio < 150), "conv": _remain6(_conv6, 20) > 0,
                "ld": _remain6(_ldd6, 20) > 0}
        _expo6 = min(1.0, 0.6 * _lit["thermo"] + 0.4 * _lit["b"] + 0.3 * _lit["warn"]
                     + 0.3 * _lit["conv"] + 0.3 * _lit["ld"])

        # 本輪恐慌溫度計episode聚類(10交易日內視為同一波,比照attention/disposition episode慣例)
        _ep_start, _ep_peak = None, 0
        if _thd6:
            _cluster6 = [_thd6[-1]]
            for _d in reversed(_thd6[:-1]):
                if _pos6[_cluster6[-1]] - _pos6[_d] <= 10:
                    _cluster6.append(_d)
                else:
                    break
            _ep_start = min(_cluster6)
            _ep_peak = max(_sweet[_d] for _d in _cluster6)

        # 歷史同類事件(甜蜜格並發>=20,固定池1379檔,見build_panic_thermometer_report.py判決)
        _hist_ep = [
            {"d": "2020-03-13", "note": "新冠熔斷"},
            {"d": "2021-05-11", "note": "本土疫情三級警戒"},
            {"d": "2022-06-22", "note": "⚠唯一敗筆,慢熊中段非底(k60-4.42%)"},
            {"d": "2024-08-06", "note": "美股崩跌"},
            {"d": "2025-04-08", "note": "川普關稅日,隔日並發達史上最高77"},
            {"d": "2026-03-09", "note": ""},
            {"d": "2026-06-10", "note": ""},
        ]
        if _ep_start is not None and str(_ep_start.date()) not in [e["d"] for e in _hist_ep]:
            _hist_ep.append({"d": str(_ep_start.date()),
                              "note": f"本次,峰值{_ep_peak}件" + ("(史上第二高)" if _ep_peak >= 50 else "")})

        _light_names = {"thermo": "恐慌溫度計", "b": "亞跌B", "conv": "雙收斂",
                         "ld": "跌停廣度", "warn": "融資警戒帶"}
        _lit_on = [k for k in ("thermo", "b", "conv", "ld", "warn") if _lit[k]]
        if _lit["thermo"]:
            _co_lit = [_light_names[k] for k in _lit_on if k not in ("thermo",)]
            _headline = (f"🔴 {sum(_lit.values())}/5燈亮・曝險{_expo6:.2f} — "
                         f"恐慌溫度計本輪episode {str(_ep_start.date()) if _ep_start else '?'}觸發"
                         f"(峰值{_ep_peak}件{'/史上第二高' if _ep_peak >= 50 else ''}),"
                         f"持有窗剩{_remain6(_thd6, 60)}個交易日"
                         + ("；同步在窗:" + "、".join(_co_lit) if _co_lit else "")
                         + "。歷史同類事件7戰6勝(僅2022-06-22慢熊中段失手)。")
        elif sum(_lit.values()) > 0:
            _headline = (f"🟡 {sum(_lit.values())}/5燈亮・曝險{_expo6:.2f} — "
                         f"{'、'.join(_light_names[k] for k in _lit_on)}在窗,恐慌溫度計本身未觸發")
        else:
            _headline = "🟢 無燈號・曝險0.00 — 市場處於平淡期,無極端讀數"

        data["market_thermo"] = {
            "asof": str(_last6.date()),
            "series": [{"d": str(d.date())[5:], "sweet": _sweet[d], "ld": _ldcnt[d]}
                       for d in _tw_dates[-10:]],
            "thermo": {"today": _sweet[_last6], "lit": _lit["thermo"],
                       "remain": _remain6(_thd6, 60),
                       "last": str(_thd6[-1].date()) if _thd6 else None},
            "b": {"lit": _lit["b"], "remain": _remain6(_bdays6, 10),
                  "last": str(_bdays6[-1].date()) if _bdays6 else None,
                  "n225": None if pd.isna(_n2r6.get(_last6, np.nan)) else round(float(_n2r6[_last6]), 2),
                  "kospi": None if pd.isna(_kor6.get(_last6, np.nan)) else round(float(_kor6[_last6]), 2),
                  "us": None if pd.isna(_us_prev(_last6)) else round(_us_prev(_last6), 2)},
            "conv": {"lit": _lit["conv"], "remain": _remain6(_conv6, 20),
                     "dd250": round(float(_dd250_6[_last6]), 1),
                     "ret1": round(float(_twr6[_last6]), 2),
                     "drop10": round(float(_drop10_6[_last6]), 1)},
            "ld": {"today": _ldcnt[_last6], "lit": _lit["ld"], "remain": _remain6(_ldd6, 20),
                   "last": str(_ldd6[-1].date()) if _ldd6 else None},
            "warn": {"ratio": round(float(_mm_last.ratio), 1),
                     "asof": str(_mm_last.date.date()), "lit": _lit["warn"]},
            "exposure": round(_expo6, 2),
            "n_lit": sum(_lit.values()),
            "headline": _headline,
            "episodes": _hist_ep,
        }
        print(f"大盤溫度計: {data['market_thermo']['n_lit']}燈亮 曝險{_expo6:.2f} "
              f"(甜蜜格{_sweet[_last6]}/跌停{_ldcnt[_last6]}家 asof {_last6.date()})")
        print(f"  {_headline}")
    except Exception as e:
        _sec_fail("大盤溫度計未產生", e)
        data["market_thermo"] = None

    # ---- 內部人解質警戒(2026-07-20使用者裁示上板,進場訊號第7檢視;判決=build_pledge_release.py:
    #      主測x60超額-6.90%/36%,配對差-3.93pp CI上緣<0=✅;放空載具❌(均值+0.01%右尾屠殺)=僅減碼審查;
    #      設質/存量/低檔補提皆無資訊=方向專一四度確認) ----
    try:
        from datetime import date as _pd7, timedelta as _td7
        _cpl = sqlite3.connect(DB_PATH)
        _pmw = pd.read_sql(
            "SELECT digest_date, code, role, pledgor, set_lots, release_lots, cum_lots FROM pledge_moves "
            "WHERE digest_date >= ?", _cpl, params=(str(_pd7.today() - _td7(days=130)),),
            parse_dates=["digest_date"])
        _asof7 = str(_pmw.digest_date.max().date()) if len(_pmw) else None
        # 轉貸剔除(同日同人設質+解質同量級)
        _grp7 = _pmw.groupby(["digest_date", "code", "pledgor"])[["set_lots", "release_lots"]].sum()
        _b7 = _grp7[(_grp7.set_lots > 0) & (_grp7.release_lots > 0)]
        _refi7 = set(_b7[(_b7.min(axis=1) / _b7.max(axis=1)) >= 0.5].index)
        _pmw = _pmw[~_pmw.set_index(["digest_date", "code", "pledgor"]).index.isin(_refi7)]
        _pmw = _pmw[_pmw.role.str.contains("董事長|大股東", na=False) & (_pmw.release_lots > 0)]
        _ev7 = _pmw.groupby(["code", "digest_date"]).agg(
            lots=("release_lots", "sum"), cum=("cum_lots", "sum"),
            roles=("role", lambda s: "、".join(sorted(set(s))[:3])),
            persons=("pledgor", "nunique")).reset_index()
        _ev7 = _ev7[_ev7.lots >= 500]
        _rows7 = []
        if len(_ev7):
            _in7 = "(" + ",".join(repr(c) for c in _ev7.code.unique()) + ")"
            _pxp = pd.read_sql(
                f"SELECT code, date, open, close FROM fm_daily_price WHERE code IN {_in7} AND date >= ?",
                _cpl, params=(str(_pd7.today() - _td7(days=620)),), parse_dates=["date"])
            _Cp = _pxp.pivot_table(index="date", columns="code", values="close")
            _Op = _pxp.pivot_table(index="date", columns="code", values="open")
            # 交叉比對現役訊號成員(持股減碼審查實戰入口)
            _xref7 = {}
            try:
                for _sc in data.get("signal_current", []) or []:
                    for _t3 in _sc.get("top3", []) or []:
                        _xref7.setdefault(str(_t3[0]), set()).add("訊號前3大")
                for _dr in (data.get("disposition") or {}).get("rows", []) or []:
                    _xref7.setdefault(str(_dr.get("code")), set()).add("處置中")
                for _g7, _v7 in ((data.get("theme_momentum") or {}).get("themes", {}) or {}).items():
                    if _v7.get("score") == 4:
                        for _m7 in _v7.get("top5", []) or []:
                            _xref7.setdefault(str(_m7[0]), set()).add("營收前5")
            except Exception:
                pass
            _cls7 = {}
            for _cd7, _gg7 in classification[classification["country"] == "台"][["code", "main_group"]]\
                    .itertuples(index=False):
                _cls7.setdefault(_cd7, []).append(_gg7)
            _nm7 = dict(_cpl.execute("SELECT code, name_zh FROM company_names WHERE country='台'"))
            _nm7.update(rankings[rankings["country"] == "台"].drop_duplicates("code", keep="last")
                        .set_index("code")["中文名稱"].to_dict())
            for _e7 in _ev7.itertuples():
                if _e7.code not in _Cp.columns:
                    continue
                _s7 = _Cp[_e7.code].dropna()
                _elapsed = int((_s7.index > _e7.digest_date).sum())
                if _elapsed > 60:  # 效應窗60交易日,過窗下架
                    continue
                _past = _s7[_s7.index <= _e7.digest_date]
                _pr7 = None
                if len(_past) >= 120:
                    _w7 = _past.tail(240)
                    _pr7 = int(round(float((_w7 <= _w7.iloc[-1]).mean() * 100)))
                _aft = _Op[_e7.code].dropna()
                _nxt = _aft[_aft.index > _e7.digest_date]
                _ret7 = None
                if len(_nxt) and _nxt.iloc[0] > 0 and len(_s7):
                    _ret7 = round(float((_s7.iloc[-1] / _nxt.iloc[0] - 1) * 100), 1)
                if _e7.digest_date.month in (4, 5, 6):
                    _tier7 = "股東會季"
                elif _e7.lots >= 1000 and _pr7 is not None and _pr7 >= 80:
                    _tier7 = "警戒"
                else:
                    _tier7 = "觀察"
                _rows7.append({
                    "d": _e7.digest_date.strftime("%Y-%m-%d"), "code": _e7.code,
                    "name": str(_nm7.get(_e7.code, "")).rstrip("*"), "groups": _cls7.get(_e7.code, []),
                    "roles": _e7.roles, "lots": int(_e7.lots), "cum": int(_e7.cum),
                    "persons": int(_e7.persons), "pr": _pr7, "ret": _ret7,
                    "left": max(0, 60 - _elapsed), "tier": _tier7,
                    "xref": sorted(_xref7.get(_e7.code, [])),
                })
        _tord = {"警戒": 0, "觀察": 1, "股東會季": 2}
        _rows7.sort(key=lambda r: r["d"], reverse=True)   # 同層新事件在前
        _rows7.sort(key=lambda r: _tord[r["tier"]])       # 警戒>觀察>股東會季
        _rows7 = _rows7[:100]
        _cpl.close()
        data["pledge_alert"] = {"asof": _asof7, "rows": _rows7}
        print(f"內部解質警戒: 窗內{len(_rows7)}筆 (警戒{sum(r['tier'] == '警戒' for r in _rows7)}筆, "
              f"資料至{_asof7})")
    except Exception as e:
        _sec_fail("內部解質警戒未產生", e)
        data["pledge_alert"] = {"asof": None, "rows": []}

    # ---- 法說會筆記嵌入(2026-07-19使用者提案: 法說會筆記/*.md上財報/法說會提醒分頁) ----
    try:
        import glob as _glob
        import html as _hm
        import re as _re

        def _md2html(text):
            out, in_tbl, in_ul = [], False, False

            def _inline(s):
                s = _hm.escape(s)
                s = _re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
                s = _re.sub(r"\[([^\]]+)\]\((https?[^)]+)\)",
                            r'<a href="\2" target="_blank">\1</a>', s)
                return s
            for line in text.splitlines():
                st = line.strip()
                if st.startswith("|"):
                    cells = [c.strip() for c in st.strip("|").split("|")]
                    if all(_re.fullmatch(r":?-{2,}:?", c) for c in cells):
                        continue
                    if not in_tbl:
                        out.append("<table><tr>" + "".join(f"<th>{_inline(c)}</th>" for c in cells) + "</tr>")
                        in_tbl = True
                    else:
                        out.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in cells) + "</tr>")
                    continue
                if in_tbl:
                    out.append("</table>")
                    in_tbl = False
                if st.startswith("- "):
                    if not in_ul:
                        out.append("<ul>")
                        in_ul = True
                    out.append(f"<li>{_inline(st[2:])}</li>")
                    continue
                if in_ul:
                    out.append("</ul>")
                    in_ul = False
                if st.startswith("### "):
                    out.append(f"<h5>{_inline(st[4:])}</h5>")
                elif st.startswith("## "):
                    out.append(f"<h4>{_inline(st[3:])}</h4>")
                elif st.startswith("# "):
                    out.append(f"<h3>{_inline(st[2:])}</h3>")
                elif st.startswith(">"):
                    out.append(f'<div class="hint">{_inline(st.lstrip("> "))}</div>')
                elif st:
                    out.append(f"<p>{_inline(st)}</p>")
            if in_tbl:
                out.append("</table>")
            if in_ul:
                out.append("</ul>")
            return "\n".join(out)

        _notes = []
        _notes_raw = []  # (file, title, raw_text) 供下面提及個股交叉索引use，不進data
        for _f in sorted(_glob.glob("法說會筆記/*.md"), reverse=True):
            _bn = _f.replace("\\", "/").split("/")[-1]
            if _bn.startswith("_"):
                continue
            _txt = open(_f, encoding="utf-8").read()
            _mt = _re.search(r"^# (.+)$", _txt, _re.M)
            _title = _mt.group(1).replace("法說會筆記：", "") if _mt else _bn[:-3]
            _notes.append({"file": _bn, "title": _title, "html": _md2html(_txt)})
            _notes_raw.append((_bn, _title, _txt))
        data["conf_notes"] = _notes
        if _notes:
            print(f"法說會筆記嵌入 {len(_notes)} 篇")
    except Exception as e:
        _sec_fail("法說會筆記嵌入失敗", e)
        data["conf_notes"] = []
        _notes_raw = []

    # ---- 法說會提及/影射個股 交叉索引(2026-07-20使用者提案: 台積電暗示聯電成熟製程隔日跌停案例) ----
    # 筆記內以 "- 代碼|國別|公司名|原因或引述摘要" 標記(人工判斷含隱晦影射,非逐字比對),
    # 台股標的自動查price DB算T+1/T+5反應；用於公司歷史頁「曾被法說會提及」區塊。
    try:
        _mention_re = _re.compile(r"^-\s*(\d{2,6})\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*(.+?)\s*$", _re.M)
        _c6 = sqlite3.connect(DB_PATH)
        _px6 = pd.read_sql("SELECT code, date, close FROM fm_daily_price WHERE close > 0", _c6)
        _c6.close()
        _px6["date"] = pd.to_datetime(_px6.date)
        _pxmap6 = {c: g.sort_values("date").reset_index(drop=True) for c, g in _px6.groupby("code")}

        def _mention_reaction(code, base_date):
            g = _pxmap6.get(code)
            if g is None or not len(g):
                return {}
            fut = g[g.date >= base_date].reset_index(drop=True)
            if not len(fut):
                return {}
            c0 = float(fut.close.iloc[0])
            out = {"d0": fut.date.iloc[0].strftime("%Y-%m-%d")}
            if len(fut) > 1:
                out["r1"] = round((float(fut.close.iloc[1]) / c0 - 1) * 100, 1)
            if len(fut) > 5:
                out["r5"] = round((float(fut.close.iloc[5]) / c0 - 1) * 100, 1)
            return out

        _mentions = {}
        for _bn, _title, _txt in _notes_raw:
            _fdate = _bn[:8]
            try:
                _bd = pd.Timestamp(f"{_fdate[:4]}-{_fdate[4:6]}-{_fdate[6:8]}")
            except ValueError:
                continue
            for _code, _ctry, _nm, _reason in _mention_re.findall(_txt):
                _code, _ctry, _nm, _reason = _code.strip(), _ctry.strip(), _nm.strip(), _reason.strip()
                _rec = {"from_title": _title, "from_file": _bn, "date": _fdate,
                        "name": _nm, "reason": _reason}
                if _ctry == "台":
                    _rec.update(_mention_reaction(_code, _bd))
                _mentions.setdefault(_ctry + "|" + _code, []).append(_rec)
        data["company_mentions"] = _mentions
        if _mentions:
            print(f"法說會提及交叉索引: {sum(len(v) for v in _mentions.values())}筆/{len(_mentions)}檔")
    except Exception as e:
        _sec_fail("法說會提及交叉索引失敗", e)
        data["company_mentions"] = {}

    # 精簡訊號摘要匯出(供gen_xq_watchlist.py讀取,不含完整payload,避免重算)
    try:
        rule_hits = [{"theme": c["theme"], "grade": c.get("grade"),
                     "top3": [code for code, _ in c.get("top3", [])]}
                    for c in data.get("signal_current", []) if c.get("verdict")]
        micro_hits = [{"theme": c["theme"], "grade": c.get("grade"),
                       "members": [m["code"] for m in c.get("members", [])]}
                      for c in data.get("micro_current", []) if c.get("grade") in ("A", "B")]
        catchup_hits = [{"theme": r["theme"], "code": r["code"], "grade": r.get("grade")}
                        for r in data.get("catchup_radar", {}).get("rows", [])
                        if r.get("grade") in ("A", "B")]
        chip = data.get("chip", {})
        _rk_conn = sqlite3.connect(DB_PATH)
        _rk_latest = pd.read_sql(
            "SELECT code, rank FROM rankings WHERE country='台' AND "
            "snapshot_date=(SELECT MAX(snapshot_date) FROM rankings WHERE country='台')", _rk_conn)
        _rk_conn.close()
        _rank_map = dict(zip(_rk_latest.code, _rk_latest["rank"]))
        chip_hits = [code for code, v in chip.items()
                    if v.get("f", -1) >= 80 and _rank_map.get(code, 0) > 50]
        # 題材月營收動能score=4(容忍落後全域asof一個月,與儀表板觸發表同口徑),成員=前5大營收
        _tm = data.get("theme_momentum", {})
        _tm_asof = _tm.get("asof")

        def _ym_diff(a, b):
            return (int(a[:4]) - int(b[:4])) * 12 + int(a[5:7]) - int(b[5:7])

        revmom_hits = []
        if _tm_asof:
            for _g, _t in (_tm.get("themes") or {}).items():
                if _t["score"] == 4 and _ym_diff(_tm_asof, _t["months"][-1]) <= 1:
                    revmom_hits.append({"theme": _g, "top5": [m[0] for m in _t["top5"]]})
        # 處置股觀察組(處置中非毒格,排除已出關;XQ盯盤用,行動日見儀表板)
        _t6 = pd.Timestamp.today().strftime("%Y-%m-%d")
        # 2026-07-19修: 只收4位數股票代碼(5-6位數=CB/權證處置,XQ股票清單放不進去)
        dispo_hits = [{"code": r["code"], "v4d": r["v4d"], "v5d": r["v5d"], "exitd": r["exitd"]}
                      for r in data.get("disposition", {}).get("rows", [])
                      if not r.get("poison") and r["end"] >= _t6
                      and len(str(r["code"])) == 4]
        with open("signals_export.json", "w", encoding="utf-8") as f:
            json.dump({"rule_hits": rule_hits, "micro_hits": micro_hits,
                      "catchup_hits": catchup_hits, "chip_hits": chip_hits,
                      "revmom_hits": revmom_hits, "dispo_hits": dispo_hits,
                      "snapshot_date": data.get("latest_date")}, f, ensure_ascii=False)
        print(f"訊號摘要已匯出 signals_export.json "
              f"(規則{len(rule_hits)}/微題材{len(micro_hits)}/補漲{len(catchup_hits)}/籌碼{len(chip_hits)}"
              f"/月營收{len(revmom_hits)})")
    except Exception as e:
        _sec_fail("訊號摘要匯出失敗(不影響dashboard)", e)

    return data


def render_html(data, out_path=OUT_PATH, local=False):
    data["build_fails"] = BUILD_FAILS  # 在render時才收,涵蓋所有區塊
    if BUILD_FAILS:
        print(f"⚠⚠ {len(BUILD_FAILS)} 個區塊建置失敗(儀表板對應區塊=空資料): " + " | ".join(BUILD_FAILS))
    data_json = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    html = HTML_TEMPLATE.replace("__DATA_JSON__", data_json)
    if local:
        plotly_path = "plotly.min.js"
        if not os.path.exists(plotly_path):
            raise FileNotFoundError("找不到 plotly.min.js，請先執行：\n  python -c \"import requests; open('plotly.min.js','wb').write(requests.get('https://cdn.plot.ly/plotly-2.27.0.min.js').content)\"")
        plotly_js = open(plotly_path, encoding="utf-8").read()
        html = html.replace(
            '<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>',
            f'<script>{plotly_js}</script>'
        )
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"已產出 {out_path}，雙擊它就能在瀏覽器打開(最新快照: {data['latest_date']})")


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<title>股市資金流向追蹤</title>
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
<style>
/* ── Design tokens ──────────────────────────────────────────────── */
:root {
  --bg:        #0c1118;
  --sf:        #131c27;
  --sf2:       #19253a;
  --sfh:       #1e2f46;
  --bd:        #1a2a3d;
  --bdm:       #263c57;
  --tx:        #d4dde8;
  --tx2:       #7d95aa;
  --tx3:       #435868;
  --ac:        #3c8cf0;
  --ac-bg:     rgba(60,140,240,.13);
  --red:       #e84545;
  --red-bg:    rgba(232,69,69,.11);
  --amb:       #d49610;
  --amb-bg:    rgba(212,150,16,.10);
  --grn:       #34b87a;
  --r:         8px;
}
@media (prefers-color-scheme:light) { :root {
  --bg:#edf1f7; --sf:#ffffff; --sf2:#f3f6fb; --sfh:#e6ecf4;
  --bd:#d6e0ec; --bdm:#b8c8da; --tx:#18253a; --tx2:#4e6278; --tx3:#8096a8;
  --ac:#1a6ee0; --ac-bg:rgba(26,110,224,.10);
  --red:#c93535; --red-bg:rgba(201,53,53,.08);
  --amb:#a87208; --amb-bg:rgba(168,114,8,.08); --grn:#1d9058;
}}
:root[data-theme="dark"] {
  --bg:#0c1118; --sf:#131c27; --sf2:#19253a; --sfh:#1e2f46;
  --bd:#1a2a3d; --bdm:#263c57; --tx:#d4dde8; --tx2:#7d95aa; --tx3:#435868;
  --ac:#3c8cf0; --ac-bg:rgba(60,140,240,.13);
  --red:#e84545; --red-bg:rgba(232,69,69,.11);
  --amb:#d49610; --amb-bg:rgba(212,150,16,.10); --grn:#34b87a;
}
:root[data-theme="light"] {
  --bg:#edf1f7; --sf:#ffffff; --sf2:#f3f6fb; --sfh:#e6ecf4;
  --bd:#d6e0ec; --bdm:#b8c8da; --tx:#18253a; --tx2:#4e6278; --tx3:#8096a8;
  --ac:#1a6ee0; --ac-bg:rgba(26,110,224,.10);
  --red:#c93535; --red-bg:rgba(201,53,53,.08);
  --amb:#a87208; --amb-bg:rgba(168,114,8,.08); --grn:#1d9058;
}

/* ── Base ──────────────────────────────────────────────────────── */
*, *::before, *::after { box-sizing: border-box; }
body {
  font-family: "Microsoft JhengHei","PingFang TC",system-ui,-apple-system,sans-serif;
  background: var(--bg); color: var(--tx);
  margin: 0; padding: 0; font-size: 14px;
  -webkit-font-smoothing: antialiased;
}

/* ── Page header (sticky) ──────────────────────────────────────── */
.page-header {
  padding: 14px 28px 0;
  background: var(--sf);
  border-bottom: 1px solid var(--bd);
  position: sticky; top: 0; z-index: 50;
}
h1 { font-size: 15px; font-weight: 700; margin: 0 0 2px; letter-spacing: .02em; color: var(--tx); }
.caption { font-size: 11px; color: var(--tx3); margin-bottom: 10px; line-height: 1.5; }

/* ── Tabs ──────────────────────────────────────────────────────── */
.tabs { display: flex; gap: 0; border-bottom: none; margin: 0; }
.tab-btn {
  background: none; border: none; color: var(--tx2);
  padding: 9px 15px 10px; cursor: pointer;
  font-size: 13px; font-family: inherit;
  border-bottom: 2px solid transparent;
  transition: color .15s, border-color .15s;
  white-space: nowrap;
}
.tab-btn:hover { color: var(--tx); }
.tab-btn.active { color: var(--ac); border-bottom-color: var(--ac); font-weight: 600; }

/* ── Tab content ───────────────────────────────────────────────── */
.tab-content { display: none; padding: 20px 28px; }
.tab-content.active { display: block; }

/* ── Tables ────────────────────────────────────────────────────── */
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th {
  background: var(--sf); color: var(--tx3);
  font-size: 11px; font-weight: 700;
  text-transform: uppercase; letter-spacing: .07em;
  padding: 8px 12px;
  border-bottom: 1px solid var(--bdm);
  cursor: pointer; position: sticky; top: 0; user-select: none; white-space: nowrap;
}
th:hover { color: var(--tx2); }
th .arrow { font-size: 9px; color: var(--ac); margin-left: 3px; }
td {
  padding: 7px 12px; border-bottom: 1px solid var(--bd);
  white-space: nowrap; font-variant-numeric: tabular-nums;
}
tr:last-child td { border-bottom: none; }
tr:hover td { background: var(--sfh); }

/* Tier rows — left stripe instead of full bright background */
.tier-hot { background: var(--red-bg) !important; }
.tier-hot td:first-child { border-left: 3px solid var(--red); }
.tier-mid { background: var(--amb-bg) !important; }
.tier-mid td:first-child { border-left: 3px solid var(--amb); }
.tier-edge td:first-child { border-left: 3px solid var(--tx3); }

/* ── Scroll box ────────────────────────────────────────────────── */
.scroll-box {
  max-height: 580px; overflow-y: auto;
  border: 1px solid var(--bd); border-radius: var(--r);
  background: var(--sf);
}

/* ── Controls / filters ────────────────────────────────────────── */
.controls { margin-bottom: 12px; display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.hint { color: var(--tx3); font-size: 12px; margin-bottom: 10px; line-height: 1.6; }
select, input[type="text"], input:not([type="radio"]):not([type="checkbox"]) {
  background: var(--sf); color: var(--tx);
  border: 1px solid var(--bdm);
  padding: 6px 10px; border-radius: 6px;
  font-size: 13px; font-family: inherit;
  transition: border-color .15s;
}
select:focus, input:focus { outline: none; border-color: var(--ac); }
input[type="checkbox"] { accent-color: var(--ac); }
input[type="radio"] { accent-color: var(--ac); }
input[type="range"] { border: none !important; padding: 0 !important; background: transparent !important; accent-color: var(--ac); vertical-align: middle; }
label { font-size: 13px; color: var(--tx2); }
code { background: var(--sf2); color: var(--ac); padding: 2px 6px; border-radius: 4px; font-size: 12px; }

/* ── Calendar ──────────────────────────────────────────────────── */
.cal-wrap { margin-bottom: 16px; }
.cal-nav { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.cal-nav button {
  background: var(--sf2); border: 1px solid var(--bd);
  color: var(--tx2); padding: 4px 14px;
  cursor: pointer; border-radius: 6px; font-size: 14px;
}
.cal-nav button:hover { background: var(--sfh); color: var(--tx); }
#calTitle { font-size: 14px; font-weight: 600; color: var(--tx); }
.cal-grid { display: grid; grid-template-columns: repeat(7,1fr); gap: 3px; }
.cal-head { text-align: center; color: var(--tx3); font-size: 11px; font-weight: 700; letter-spacing: .05em; padding: 4px 0; }
.cal-head.sun { color: #c05050; } .cal-head.sat { color: var(--ac); }
.cal-cell { min-height: 72px; background: var(--sf); border: 1px solid var(--bd); border-radius: 6px; padding: 5px; box-sizing: border-box; }
.cal-cell.today { background: var(--sf2); border-color: var(--ac); }
.cal-cell.out { opacity: 0.2; pointer-events: none; }
.cal-num { font-size: 12px; color: var(--tx3); margin-bottom: 3px; }
.cal-num.sun { color: #c05050; } .cal-num.sat { color: var(--ac); }
.cal-cell.today .cal-num { color: var(--ac); font-weight: 700; font-size: 13px; background: var(--ac-bg); display: inline-block; border-radius: 50%; width: 20px; height: 20px; line-height: 20px; text-align: center; margin-bottom: 4px; }
.cal-evt { font-size: 10px; border-radius: 3px; padding: 1px 5px; margin-bottom: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; cursor: default; }
.cal-evt.tw { background: var(--red-bg); color: var(--red); border-left: 2px solid var(--red); }
.cal-evt.us { background: var(--ac-bg); color: var(--ac); border-left: 2px solid var(--ac); }
.cal-evt.jpkr { background: rgba(52,184,122,.1); color: var(--grn); border-left: 2px solid var(--grn); }
.cal-evt.expo { background: rgba(180,120,220,.15); color: #b478dc; border-left: 2px solid #b478dc; }
.cal-evt.fire { animation: pulse 1.2s infinite; }
.expo-watch-table td, .expo-watch-table th { font-size: 12px; }
.expo-watch-card { border: 1px solid var(--bd); border-radius: 8px; padding: 10px 14px; margin-bottom: 10px; }
.expo-watch-card.active { border-color: #b478dc; background: rgba(180,120,220,.06); }
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.55} }

/* ── Search dropdown ───────────────────────────────────────────── */
.search-wrap { display: inline-block; position: relative; width: 300px; }
.search-wrap input { width: 100%; box-sizing: border-box; margin: 0; }
.search-dropdown {
  position: absolute; top: 100%; left: 0; right: 0;
  background: var(--sf2); border: 1px solid var(--bdm);
  border-radius: 6px; max-height: 220px; overflow-y: auto;
  z-index: 999; box-shadow: 0 8px 24px rgba(0,0,0,.3);
}
.search-item { padding: 7px 12px; cursor: pointer; font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: var(--tx2); }
.search-item:hover { background: var(--sfh); color: var(--tx); }

/* ── Supply chain ──────────────────────────────────────────────── */
.sc-fresh-warn {
  background: var(--amb-bg); border: 1px solid var(--amb);
  color: var(--amb); padding: 10px 14px; border-radius: var(--r);
  margin-bottom: 14px; font-size: 13px;
}
.sc-anchors { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 16px; }
.anchor-btn {
  background: var(--sf); border: 1px solid var(--bdm);
  color: var(--tx2); padding: 6px 16px;
  cursor: pointer; border-radius: 20px; font-size: 13px; font-family: inherit;
  transition: all .15s;
}
.anchor-btn:hover { background: var(--sf2); color: var(--tx); }
.anchor-btn.active { background: var(--ac-bg); border-color: var(--ac); color: var(--ac); font-weight: 600; }
.sc-country-bar { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 18px; }
.sc-country-chip { background: var(--sf); border: 1px solid var(--bd); padding: 5px 14px; border-radius: 20px; font-size: 13px; color: var(--tx2); }
.chip-hot { color: var(--red); margin-left: 4px; font-weight: 600; }
.sc-country-section { margin-bottom: 24px; }
.sc-country-title { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .07em; color: var(--tx3); margin-bottom: 10px; padding-bottom: 6px; border-bottom: 1px solid var(--bd); }
.sc-cards-row { display: flex; flex-wrap: wrap; gap: 10px; }
.sc-card {
  background: var(--sf); border: 1px solid var(--bd); border-radius: var(--r);
  padding: 12px 14px; width: 210px; min-width: 190px;
  transition: border-color .15s, background .15s;
}
.sc-card:hover { border-color: var(--bdm); background: var(--sf2); }
.sc-card.card-hot { border-left: 3px solid var(--red); }
.sc-card.card-mid { border-left: 3px solid var(--amb); }
.sc-card-header { display: flex; align-items: center; gap: 8px; margin-bottom: 5px; }
.rank-badge { font-size: 11px; padding: 2px 8px; border-radius: 10px; font-weight: 700; white-space: nowrap; font-variant-numeric: tabular-nums; }
.rank-badge.b-hot { background: var(--red-bg); color: var(--red); }
.rank-badge.b-mid { background: var(--amb-bg); color: var(--amb); }
.rank-badge.b-edge, .rank-badge.b-none { background: var(--sf2); color: var(--tx3); }
.sc-code { font-size: 11px; color: var(--tx3); }
.sc-name { font-size: 13px; font-weight: 600; color: var(--tx); margin-bottom: 4px; line-height: 1.3; }
.sc-product { font-size: 12px; color: var(--tx2); line-height: 1.5; margin-bottom: 4px; }
.sc-amount { font-size: 12px; color: var(--ac); font-variant-numeric: tabular-nums; }
.sc-fund { font-size: 11px; color: var(--tx3); margin-top: 2px; font-variant-numeric: tabular-nums; }
/* 台股慣例：紅=漲/成長、綠=跌/衰退 */
.fund-up { color: var(--red); }
.fund-down { color: var(--grn); }

/* ── 進場訊號頁 ───────────────────────────────────────────────── */
.rule-card { background: var(--sf); border: 1px solid var(--bd); border-radius: var(--r); padding: 14px 18px; margin-bottom: 8px; }
.rule-item { font-size: 13px; color: var(--tx2); line-height: 1.8; }
.sig-pass { color: var(--grn); font-weight: 700; }
.sig-fail { color: var(--tx3); }
.pos-badge { font-size: 10px; padding: 1px 6px; border-radius: 8px; font-weight: 700; white-space: nowrap; vertical-align: middle; margin-left: 4px; }
.pos-badge.crown { background: var(--amb-bg); color: var(--amb); border: 1px solid var(--amb); }
.pos-badge.star { background: var(--ac-bg); color: var(--ac); }
.pos-badge.silver { background: var(--sf2); color: var(--tx2); border: 1px solid var(--bdm); }
.sc-delta { font-size: 11px; font-weight: 700; font-variant-numeric: tabular-nums; }
.sc-delta.up { color: var(--red); }
.sc-delta.down { color: var(--grn); }
.sc-delta.flat { color: var(--tx3); }

/* ── 本週摘要橫幅 ──────────────────────────────────────────────── */
.week-banner {
  display: flex; flex-wrap: wrap; align-items: center; gap: 8px;
  font-size: 12px; color: var(--tx2);
  padding: 6px 12px; margin-bottom: 10px;
  background: var(--sf2); border: 1px solid var(--bd); border-radius: 6px;
}
.week-banner b { font-weight: 700; font-variant-numeric: tabular-nums; }
.wb-up { color: var(--red); }
.wb-down { color: var(--ac); }
.wb-sep { color: var(--tx3); }

/* ── 區段標題 ─────────────────────────────────────────────────── */
.sec-title {
  font-size: 12px; font-weight: 700; color: var(--tx2);
  text-transform: uppercase; letter-spacing: .07em;
  margin: 24px 0 6px;
}

/* ── 法說會筆記 ───────────────────────────────────────────────── */
#confNotesPanel { max-height: 580px; overflow-y: auto; padding: 2px 4px; }
.conf-note { border: 1px solid var(--bd); border-radius: 8px; padding: 8px 12px; margin: 8px 0; background: var(--sf); }
.conf-note summary { cursor: pointer; }
.cn-body table { border-collapse: collapse; font-size: 12px; margin: 8px 0; }
.cn-body td, .cn-body th { border: 1px solid var(--bd); padding: 4px 8px; text-align: left; }
.cn-body h3, .cn-body h4, .cn-body h5 { margin: 10px 0 4px; }
.cn-body p, .cn-body li { font-size: 13px; line-height: 1.6; }
/* ── 題材成員速查彈窗 ─────────────────────────────────────────── */
#themeMemberModal { display: none; position: fixed; inset: 0; background: rgba(0,0,0,.55); z-index: 99; align-items: center; justify-content: center; }
#themeMemberModal .tm-body { background: var(--sf); border: 1px solid var(--bd); border-radius: 8px; max-width: 760px; width: 92%; max-height: 80vh; overflow: auto; padding: 16px; }
.tm-table { width: 100%; border-collapse: collapse; font-size: 12px; margin-top: 8px; }
.tm-table td, .tm-table th { border: 1px solid var(--bd); padding: 4px 8px; text-align: center; }
/* ── 資金輪動熱力圖 ───────────────────────────────────────────── */
.heatmap-box { overflow-x: auto; overflow-y: auto; max-height: 640px; border: 1px solid var(--bd); border-radius: var(--r); background: var(--sf); padding: 12px; }
.hm-table { border-collapse: separate; border-spacing: 3px; width: auto; }
.hm-table th, .hm-table td { border: none; padding: 0; position: static; background: none; cursor: default; }
.hm-table tr:hover td { background: none; }
.hm-table tr:hover td.hm-empty { background: var(--sf2); }
.hm-date { font-size: 10px; color: var(--tx3); font-weight: 600; padding: 0 2px 4px; text-align: center; }
.hm-name { font-size: 12px; color: var(--tx2); padding-right: 10px; text-align: right; white-space: nowrap; }
.hm-score { font-size: 10px; color: var(--tx3); font-variant-numeric: tabular-nums; }
.hm-cell { width: 36px; min-width: 36px; height: 22px; border-radius: 4px; }
.hm-cell.hm-empty { background: var(--sf2); }

/* ── 供應鏈生態系排行 ─────────────────────────────────────────── */
.sc-ranking { display: flex; flex-direction: column; gap: 4px; margin-bottom: 8px; }
.scr-row {
  display: flex; align-items: center; gap: 10px;
  padding: 6px 12px; font-size: 13px;
  background: var(--sf); border: 1px solid var(--bd); border-radius: 6px;
  cursor: pointer; transition: background .15s, border-color .15s;
}
.scr-row:hover { background: var(--sf2); }
.scr-row.active { border-color: var(--ac); background: var(--ac-bg); }
.scr-rank { font-weight: 700; color: var(--tx3); width: 18px; text-align: right; font-variant-numeric: tabular-nums; }
.scr-label { width: 130px; font-weight: 600; color: var(--tx); white-space: nowrap; }
.scr-bar-wrap { flex: 1; height: 8px; background: var(--sf2); border-radius: 4px; overflow: hidden; min-width: 60px; }
.scr-bar { display: block; height: 100%; background: linear-gradient(90deg, var(--ac), var(--red)); border-radius: 4px; }
.scr-stats { color: var(--tx2); white-space: nowrap; font-variant-numeric: tabular-nums; font-size: 12px; }
.scr-updown { color: var(--tx3); font-size: 11px; margin-left: 4px; }

/* ── 對比 chips ───────────────────────────────────────────────── */
.chip-row { display: flex; flex-wrap: wrap; gap: 6px; margin: 4px 0 10px; }
.chip {
  display: inline-flex; align-items: center; gap: 6px;
  background: var(--ac-bg); border: 1px solid var(--ac); color: var(--ac);
  border-radius: 14px; padding: 3px 10px; font-size: 12px;
}
.chip-x { cursor: pointer; font-weight: 700; }
.chip-x:hover { color: var(--red); }
.theme-link { color: inherit; text-decoration: none; border-bottom: 1px dotted var(--tx3); cursor: pointer; }
.theme-link:hover { color: var(--ac); border-bottom-color: var(--ac); }
.health-bar {
  display: flex; flex-wrap: wrap; gap: 6px 14px; align-items: center;
  padding: 10px 28px 16px; border-top: 1px solid var(--bd);
  font-size: 11px; color: var(--tx3);
}
.health-item { white-space: nowrap; }
.health-dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; margin-right: 4px; vertical-align: 1px; }
.health-dot.ok { background: var(--grn); }
.health-dot.warn { background: var(--amb); }
.health-dot.crit { background: var(--red); }

/* ── 供應鏈視圖切換 + 產業鏈上中下游 ─────────────────────────── */
.sc-view-switch { display: flex; gap: 8px; margin-bottom: 16px; }
.view-btn {
  background: var(--sf); border: 1px solid var(--bdm); color: var(--tx2);
  padding: 7px 18px; border-radius: 6px; cursor: pointer;
  font-size: 13px; font-family: inherit; transition: all .15s;
}
.view-btn:hover { background: var(--sf2); color: var(--tx); }
.view-btn.active { background: var(--ac-bg); border-color: var(--ac); color: var(--ac); font-weight: 600; }
tr.hl-row td { background: var(--ac-bg); font-weight: 600; }
.chain-stages { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 14px; align-items: start; }
.stage-col { background: var(--sf2); border: 1px solid var(--bd); border-radius: var(--r); padding: 10px; }
.stage-head {
  font-size: 12px; font-weight: 700; color: var(--tx2);
  text-transform: uppercase; letter-spacing: .06em;
  margin-bottom: 10px; padding-bottom: 6px; border-bottom: 1px solid var(--bd);
}
.stage-meta { color: var(--tx3); font-weight: 600; margin-left: 6px; }
.stage-cards { display: flex; flex-direction: column; gap: 8px; }
.stage-cards .sc-card { width: 100%; min-width: 0; }
</style>
</head>
<body>
<div class="page-header">
<h1>股市資金流向追蹤</h1>
<div class="caption">台股(上市+上櫃) / 日股 / 韓股 / 陸股(滬深A股) / 美股，依成交金額排行，依族群/題材分類。最新快照：<span id="latestDate"></span>。2026-06-21前的歷史快照為估算回補值(yfinance收盤×成交量，僅含現任成分股)。</div>
<div id="weeklyBanner" class="week-banner" style="display:none"></div>
<div class="tabs">
  <button class="tab-btn active" onclick="showTab(0)">題材跨市場比較</button>
  <button class="tab-btn" id="signalTabBtn" onclick="showTab(7)">進場訊號</button>
  <button class="tab-btn" onclick="showTab(6)">動能雷達</button>
  <button class="tab-btn" onclick="showTab(5)">供應鏈</button>
  <button class="tab-btn" onclick="showTab(2);if(document.getElementById('histRevmomView').style.display!=='none')renderRevmomChart()">題材動能與共振</button>
  <button class="tab-btn" onclick="showTab(1)">排行榜明細</button>
  <button class="tab-btn" onclick="showTab(3)">財報/法說會提醒</button>
  <button class="tab-btn" onclick="showTab(4)">新聞/目標價</button>
</div>
<div id="thermoStrip" style="display:none;margin-top:6px;font-size:12px"></div>
</div>

<div class="tab-content active" id="tab0">
  <div class="controls">
    <label><input type="checkbox" id="onlyThematic" checked onchange="renderThemePivot()"> 只看題材概念股(排除金融/消費/傳統產業等廣義分類)</label>
  </div>
  <div class="hint" id="hintTheme">熱度分數 = 該題材在每個國家的「台幣金額 ÷ 該國全部上榜公司台幣金額總和」百分比，五國加總而成。分數越高表示資金集中度越高，不是只看公司數量。點欄位標題可排序。</div>
  <div class="scroll-box"><table id="themePivotTable"></table></div>
  <div class="controls" style="margin-top:12px">
    對比期間：<select id="moverPeriod" onchange="renderMoversChart()">
      <option value="1" selected>1週前(上次快照)</option>
      <option value="2">2週前</option>
      <option value="4">4週前(月)</option>
      <option value="8">8週前</option>
      <option value="12">12週前(季)</option>
      <option value="26">26週前(半年)</option>
    </select>
    <label><input type="checkbox" id="hmIncludeBroad" checked onchange="renderMoversChart(); renderRotationHeatmap()"> 含金融/傳產等廣義分類(觀察避險資金)</label>
  </div>
  <div class="hint">建議觀察 <b>4週(月)</b>：回測驗證過的脈衝基準——本週熱度達前4週的2.5倍以上才算真脈衝(微題材規則實測勝率68%)。<b>1週前</b>適合掃「本週誰動了」，但單週雜訊大，確認要靠連漲2週＋廣度＋多國同步(見進場訊號頁)。<b>26週前(半年)</b>用來分辨「回檔還是退潮」：Δ為<b>正</b>＝題材仍在半年上升週期，短線降溫較可能是洗盤；Δ為<b>負</b>＝熱度連半年前都不如＝退潮題材，裡面看似便宜的低位階成員多半是接刀(2022航運教訓：退潮題材低位階四次進場全賠)。</div>
  <div id="moversChart" style="height:550px"></div>
  <h3 class="sec-title">資金輪動熱力圖（題材 × 時間）</h3>
  <div class="controls">
    排序：<select id="hmSort" onchange="renderRotationHeatmap()">
      <option value="pos" selected>位階優先(正在自己高點的在上)</option>
      <option value="heat">熱度優先(錢最多的在上)</option>
    </select>
    範圍：<select id="hmRange" onchange="renderRotationHeatmap()">
      <option value="8">近8週</option>
      <option value="13" selected>近13週(一季)</option>
      <option value="26">近26週(半年)</option>
      <option value="all">全部</option>
    </select>
    色階：<select id="hmColorMode" onchange="renderRotationHeatmap()">
      <option value="rel" selected>相對(每列自身節奏)</option>
      <option value="abs">絕對(全題材同一把尺)</option>
    </select>
    <label><input type="checkbox" id="hmShowAll" onchange="renderRotationHeatmap()"> 顯示全部題材(預設前20)</label>
  </div>
  <div class="hint">列標籤附「目前分數·52週位階%」(固定近52週自身高低的百分位；訊號頁位階=全史口徑，兩者概念相同、窗口不同。位階管<b>倉位大小</b>，不是進場門票)。表頭下「共振」列=該週點火題材數(點火=熱度週變化z>1，與族群金流解剖◆同定義)，<b>紅字=點火數超過全期平均+1SD的異常共振週</b>(門檻隨資料與題材篩選自動重算，滑鼠停留可看當前門檻；歷史紅標例：2025-09-14真起漲、2026-03-01行情22個題材齊點火，也含2025年6-8月假訊號期——共振是發現層，決策仍過檢查清單)——研究結論：資金不沿產業鏈爬行而是整條鏈同週點火，共振本身就是訊號。判讀優先序：<b>直欄同亮(共振)＞橫帶連暖(連漲2週)＞單格突亮(噪音)</b>；格子變暗是常態(高檔題材6週內回落15%的基準率84%)，關鍵看守不守點火前水準，別猜頭。建議配對：<b>位階排序+相對色階</b>=看錢往哪動；<b>熱度排序+絕對色階</b>=看錢在哪。只含有台股公司的題材，滑鼠停留可看實際分數。</div>
  <div class="heatmap-box" id="rotationHeatmap"></div>
  <div class="controls" style="margin-top:16px">
    選一個主族群看明細：<select id="themePick" onchange="renderThemeDetail()"></select>
  </div>
  <div class="scroll-box"><table id="themeDetailTable"></table></div>
</div>

<div class="tab-content" id="tab1">
  <div class="controls">
    國家：<select id="countryFilter" multiple size="5" onchange="renderFullTable()">
      <option value="台" selected>台</option><option value="日" selected>日</option>
      <option value="美" selected>美</option><option value="韓" selected>韓</option>
      <option value="陸" selected>陸</option>
    </select>
    題材：<select id="groupFilter" onchange="renderFullTable()"><option value="">(不篩選)</option></select>
  </div>
  <div class="hint" id="hintFull">點欄位標題可排序(例如點「金額(億台幣)」可依跨市場可比較的台幣金額排大小)。</div>
  <div class="scroll-box"><table id="fullTable"></table></div>
</div>

<div class="tab-content" id="tab2">
  <div class="sc-view-switch">
    <button class="view-btn active" id="histViewRevmomBtn" onclick="switchHistView('revmom')">產業月營收動能</button>
    <button class="view-btn" id="histViewResBtn" onclick="switchHistView('res')">族群共振/金流解剖</button>
    <button class="view-btn" id="histViewCompanyBtn" onclick="switchHistView('company')">個股/題材歷史</button>
  </div>
  <div id="histResView" style="display:none">
  <h3 class="sec-title" style="margin-top:0">族群共振（前幾大成員是否齊漲）</h3>
  <div class="controls">
    題材：<select id="resTheme" onchange="renderResonance()"></select>
    範圍：<select id="resRange" onchange="renderResonance()">
      <option value="13" selected>近13週(一季)</option>
      <option value="26">近26週(半年)</option>
      <option value="52">近52週(一年)</option>
    </select>
    成員數：<select id="resN" onchange="renderResonance()">
      <option value="6" selected>前6大</option>
      <option value="8">前8大</option>
      <option value="10">前10大</option>
    </select>
    <span id="resScoreBadge"></span>
  </div>
  <div class="hint">上=成員週收盤歸一化(範圍起點=100)，線綁在一起走=共振；中=資金排名(越上面越熱)；下=滾動8週共振分數(成員週報酬兩兩相關均值，虛線0.7以上=強共振)。成員取該題材台股最新資金額前N大。點下方成員標籤可跳到單股檢視。</div>
  <div id="resChart" style="height:620px"></div>
  <div id="resChips" class="chip-row"></div>
  <h3 class="sec-title">族群金流解剖（誰先動：市場層 → 台股成員層）</h3>
  <div class="hint">上圖=該題材在五市場的資金份額子分數，◆=點火週(份額週變化&gt;1個標準差)——看哪個市場先動。中圖=集中度：台股第1大成員佔題材台股金額%，上升=龍頭獨走、下降=擴散(全員行情較健康)。下表=台股成員點火時序，最早點火標🐑。<b>提醒</b>：回測顯示跨市場接力僅弱訊號(最強=韓→台 lift 1.19)、領頭羊帶動整體 lift 1.15——先後順序是「觀察起點」不是「買進理由」，決策仍看位階+廣度。<b>籌碼欄(2026-07新增,觀察層)</b>：外資位階=該股「外資近20日累計買賣超」在自身近一年的百分位——回測顯示<b>中小型股(資金榜51名以後)起漲＋外資位階≥80(綠✓)為有效加分</b>，前50大該欄無資訊價值(顯示—)；不論真假外資皆讀作「聰明錢腳印」。券資比位階≥80(⚡)=空單水位在自身一年高檔=軋空燃料，證據等級較弱僅供參考。<b>態勢警語(回測)</b>：籌碼訊號各態勢下平均皆正，但<b>災難級單週(-29%)全部集中在大盤季線下</b>——徽章一律搭配態勢倉位使用(月線下6成/季線下3成，掛階梯後夏普1.69→1.89/MDD-41%→-26%)，alpha決定買什麼、態勢決定買多少。每週隨 fetch_t86/fetch_margin 更新。</div>
  <div id="anaChart" style="height:340px"></div>
  <div id="anaConc" style="height:130px"></div>
  <div class="scroll-box"><table id="anaTable"></table></div>
  </div>

  <div id="histCompanyView" style="display:none">
  <h3 class="sec-title" style="margin-top:0">個股/題材歷史</h3>
  <div class="controls">
    追蹤對象：
    <label><input type="radio" name="histMode" value="company" checked onchange="onHistModeChange()"> 公司</label>
    <label><input type="radio" name="histMode" value="theme" onchange="onHistModeChange()"> 主族群(題材)</label>
  </div>
  <div class="controls" id="companyPickWrap">
    加入公司(可多選對比，最多6家)：
    <div class="search-wrap">
      <input type="text" id="companySearch" placeholder="輸入代碼或公司名稱…" autocomplete="off">
      <div class="search-dropdown" id="companyDropdown" style="display:none"></div>
    </div>
    <input type="hidden" id="companyPick">
  </div>
  <div id="companyChips" class="chip-row"></div>
  <div class="controls" id="themeHistPickWrap" style="display:none">
    選擇主族群：
    <div class="search-wrap">
      <input type="text" id="themeHistSearch" placeholder="輸入題材名稱…" autocomplete="off">
      <div class="search-dropdown" id="themeHistDropdown" style="display:none"></div>
    </div>
    <input type="hidden" id="themeHistPick">
  </div>
  <div id="historyChart" style="height:420px"></div>
  <div id="companyInfoPanel"></div>
  <table id="historyTable"></table>
  </div>

  <div id="histRevmomView">
  <h3 class="sec-title" style="margin-top:0">產業(題材)月營收動能</h3>
  <div class="controls">
    題材：<select id="revmomTheme" onchange="renderRevmomChart()"></select>
    範圍：<select id="revmomRange" onchange="renderRevmomChart()">
      <option value="24" selected>近24月</option>
      <option value="36">近36月</option>
      <option value="60">近60月</option>
      <option value="999">全部(2019起)</option>
    </select>
  </div>
  <div class="hint">柱＝題材成員(FinMind覆蓋)月營收<b>加總</b>(億台幣)；線＝MoM%/YoY%(右軸)；<b>▲＝至該營收月止構成「月營收訊號」</b>(=連3月月增+近3月年增均值為正,4項條件全過；進場口徑=公告月的次月15號、持有60交易日——訊號規則與回測數據詳「進場訊號」頁的「題材營收動能」檢視)。下表＝前5大營收成員(12月平均占比，中位涵蓋97%題材營收)。題材下拉選單「▲」＝本月觸發中。</div>
  <div id="revmomChart" style="height:380px"></div>
  <table id="revmomMembers"></table>
  </div>
</div>

<div class="tab-content" id="tab3">
  <div class="hint">這個分頁是 `check_earnings.py` 上次執行結果的快照，要更新請在終端機跑 <code>python check_earnings.py</code> 後重新產生 dashboard.html。🔥=3天內 🟠=7天內(表格底色/日曆火焰=日期迫近度)；⭐/🔹=公司份量(美股用市值、台/日韓陸用成交金額排名近似，標在公司名前，跟表格底色是兩個獨立維度)。</div>
  <div class="cal-wrap">
    <div class="cal-nav">
      <button onclick="calMove(-1)">&#9664;</button>
      <span id="calTitle"></span>
      <button onclick="calMove(1)">&#9654;</button>
    </div>
    <div class="cal-grid" id="calGrid"></div>
  </div>
  <h4>展覽效應觀察 🎪</h4>
  <div class="hint">研究依據(2026-07回測,觀察層,樣本2022-2025各4年)：題材裡不是全體齊漲,只有少數個股會展前提前動,且常客股逐年重複出現；效應約從<b>展前40個交易日(約2個月)</b>開始累積,不是展前一週才發動；用「漲停/單日爆量」當偵測門檻經測試無效(跟非展覽期比沒有鑑別力)——真正的卡位是安靜緩慢的累積,不是明顯的噴出日。展後多數常客會回吐(利多出盡),藥華藥/泰宗展後續漲屬少數例外。日期需每年手動更新此檔。</div>
  <div id="expoWatchPanel"></div>
  <h4>📝 重大法說會筆記</h4>
  <div class="hint">重大法說會隔天請Claude「補XX法說筆記」→ 存入 法說會筆記/*.md → 重跑 export_html.py 即上板。
  結構：市場在意(共識vs實際=預期差) / 董座發言原文 / 供應鏈題材連動 / 會後價格驗收 / 操作含義 / 與上次法說會的差異。</div>
  <div id="confNotesPanel"></div>
  <h4>美股財報 <span id="usEarningsMtime" style="color:#888;font-size:12px;"></span></h4>
  <div class="hint">⭐=市值≥3000億美元、🔹=市值≥1000億美元(標在公司名前)，一天跳出幾十檔時用這個抓真正牽動大盤的重量級，不用逐行看市值欄。</div>
  <div class="scroll-box"><table id="usEarningsTable"></table></div>
  <div class="hint"><b>財報季作戰指南(2026-07回測,觀察層)</b>：①<b>美股龍頭財報「後」10日=台鏈跟漲觀察窗</b>(+0.9%中位/55%，MSFT/AAPL系最明顯；NVDA鏈反向=行情多在財報前price in、開獎後留意獲利了結)。②<b>首發者效應</b>：同題材首家開法說者的市場反應會傳染給還沒開的同業——首發開差→短窗迴避同題材後發成員(PCB/封測/CPO系最靈)；首發開好→後發者進關注清單。記憶體例外(公開報價題材無此效應)。③<b>台積電法說前後</b>：事前2週方向=市場對半導體的預期放大器(多頭年正/熊市年負,環境給方向)。④法說隔日的環節暴衝多為短打資金,等週級資金流訊號接手才算數。<b>點公司名→跳公司歷史頁(題材/產業鏈歸屬+同鏈成員)。</b></div>
  <h4>台股法說會 <span id="twEarningsMtime" style="color:#888;font-size:12px;"></span></h4>
  <div class="hint">⭐=成交金額排名前20、🔹=前50(標在公司名前，台股沒有市值欄，用排名近似份量)。</div>
  <div class="scroll-box"><table id="twEarningsTable"></table></div>
  <h4>日韓陸財報日 <span id="jpkrEarningsMtime" style="color:#888;font-size:12px;"></span></h4>
  <div class="hint">日韓=Yahoo(yfinance calendar，日股覆蓋率高、韓股約1/3)；陸=東方財富披露預約(整批API)。各市場前100大、僅未來90天，更新跑 <code>python fetch_earnings_dates.py</code>。歷史財報日累積於DB earnings_dates表(事件研究用)，回補跑 <code>python fetch_earnings_history.py</code>。⭐=排名前20、🔹=前50(同台股邏輯)。</div>
  <div class="scroll-box"><table id="jpkrEarningsTable"></table></div>
</div>

<div class="tab-content" id="tab4">
  <div class="hint">這個分頁是人工搜尋+逐一驗證連結真實性後手動整理的結果(不是自動爬蟲)，確保每個連結點開都看得到對應內容。要更新請另外搜尋整理後加進 theme_news.csv，再重新產生 dashboard.html。</div>
  <div class="controls">
    主族群：<select id="newsGroupFilter" multiple size="6" onchange="renderNewsTable()"></select>
    類型：<select id="newsTypeFilter" multiple size="2" onchange="renderNewsTable()"></select>
  </div>
  <div class="scroll-box"><table id="newsTable"></table></div>
</div>

<div class="tab-content" id="tab5">
  <div id="scFreshWarn" class="sc-fresh-warn" style="display:none">
    ⚠️ 供應鏈資料已超過90天未更新（最後更新：<span id="scLastUpdated"></span>），部分關係可能已變動，建議重新執行 Gemini 審查流程
  </div>
  <div class="hint">資料來源：Gemini驗證後人工確認，每筆代碼經資料庫核對。最後更新：<span id="scLastUpdatedInline"></span></div>
  <div class="sc-view-switch">
    <button class="view-btn active" id="viewAnchorBtn" onclick="switchSCView('anchor')">錨點客戶視圖</button>
    <button class="view-btn" id="viewChainBtn" onclick="switchSCView('chain')">產業鏈視圖(上中下游)</button>
  </div>
  <div id="scAnchorView">
  <h3 class="sec-title">供應鏈生態系熱度排行</h3>
  <div class="hint">熱度分 = 🔥前50供應商×2 + 🟠前150供應商×1，直接點列可切換下方明細。▲▼ = 供應商中排名較上週上升/下降的家數。</div>
  <div id="scRanking" class="sc-ranking"></div>
  <h3 class="sec-title">錨點客戶明細</h3>
  <div class="sc-anchors">
    <button class="anchor-btn active" onclick="selectAnchor('NVDA')">🔵 NVIDIA</button>
    <button class="anchor-btn" onclick="selectAnchor('CLOUD')">☁️ 雲端三巨頭</button>
    <button class="anchor-btn" onclick="selectAnchor('AAPL')">🍎 Apple</button>
    <button class="anchor-btn" onclick="selectAnchor('TSLA')">⚡ Tesla</button>
    <button class="anchor-btn" onclick="selectAnchor('TSMC')">🏭 台積電(上游)</button>
    <button class="anchor-btn" onclick="selectAnchor('HK_AUTO')">🚗 現代起亞</button>
    <button class="anchor-btn" onclick="selectAnchor('KR_MEM')">🧠 三星/SK海力士</button>
    <button class="anchor-btn" onclick="selectAnchor('BABA')">🛒 阿里巴巴</button>
    <button class="anchor-btn" onclick="selectAnchor('TENCENT')">🎮 騰訊</button>
    <button class="anchor-btn" onclick="selectAnchor('HUAWEI')">📡 華為</button>
  </div>
  <div id="anchorCapexStrip" class="hint" style="margin-top:6px"></div>
  <div id="scCountryBar"></div>
  <div id="scCards"></div>
  </div>
  <div id="scChainView" style="display:none">
    <h3 class="sec-title">產業鏈熱度排行</h3>
    <div class="hint">熱度分數 = 鏈上全部成員(五市場)台幣金額佔各國總額比例加總，與題材熱度分數同一把尺。週/月 = 與1週/4週前比較。點列切換下方上中下游明細。</div>
    <div id="chainRanking" class="sc-ranking"></div>
    <div class="hint">選一條產業鏈，看上游材料/設備 → 中游製造 → 下游應用的跨國全貌。卡片按資金流向排名排序，左色條=熱度(紅=前50、琥珀=前150)，▲▼=排名週變化。基本面欄(yfinance季度值，每季更新)：毛利率、<b>季營收YoY</b>(最新季vs去年同季，非台股月營收)、PB股價淨值比(循環股位置參考)、EPS預估方向(forward vs trailing，↗=分析師預估成長)。</div>
    <div class="sc-anchors" id="chainBtns"></div>
    <div class="sc-anchors" style="margin-top:6px">
      <span id="chainCountryBtns"></span>
      <label style="font-size:12px;margin-left:8px"><input type="checkbox" id="chainOnlyRanked" onchange="renderChainView()"> 只看上榜成員(有資金排名)</label>
    </div>
    <div class="chain-stages" id="chainStages"></div>
  </div>
</div>

<div class="tab-content" id="tab6">
  <div class="controls">
    顯示：<select id="radarShow" onchange="renderRadar()">
      <option value="hot15" selected>熱度前15</option>
      <option value="mover15">動能前15(變化最大)</option>
      <option value="up">領漲+轉強(動能為正)</option>
      <option value="all">全部題材</option>
    </select>
    動能期間：<select id="radarPeriod" onchange="renderRadar()">
      <option value="1">1週</option>
      <option value="2" selected>2週</option>
      <option value="4">4週(月)</option>
      <option value="8">8週</option>
    </select>
    <label><input type="checkbox" id="radarIncludeBroad" checked onchange="renderRadar()"> 含金融/傳產等廣義分類</label>
    <button class="view-btn" id="radarPlayBtn" onclick="toggleRadarPlay()">▶ 播放</button>
    <input type="range" id="radarSlider" style="width:220px" oninput="onRadarSlide()">
    <span id="radarDate" style="font-size:12px;color:var(--tx2);font-variant-numeric:tabular-nums"></span>
  </div>
  <div id="radarFocusChips" class="chip-row"></div>
  <div class="hint">X軸=熱度分數(對數尺度，越右越強)，Y軸=選定期間的熱度變化(越上越加速)。用「顯示」篩選聚焦：熱度前15看主戰場、動能前15看正在動的、領漲+轉強只看多方。<b>點擊圓點可聚焦該題材(其他變暗)，可連點複選，再點一次取消</b>——聚焦後按▶播放即為單題材聚光燈動畫。點少於18個時全部標名。下方訊號表永遠含全部題材不受篩選影響。按▶播放或拖曳時間軸，可看題材在象限間的移動軌跡——順時針繞行即資金輪動。虛線=全題材中位數與零軸，分四象限：右上<b>領漲</b>(續抱)、左上<b>轉強</b>(進場甜蜜點)、右下<b>退潮</b>(減碼)、左下<b>弱勢</b>(避開)。灰色尾巴=最近4週軌跡，順時針轉動即教科書式輪動。只標注重點題材名稱，全部題材滑鼠停留可見。</div>
  <div id="radarChart" style="height:640px"></div>
  <h3 class="sec-title">動能訊號表(雷達)</h3>
  <div class="hint">加速度=本期Δ−上期Δ(正值代表越漲越快)。連漲/連跌=週快照連續上升/下降次數。廣度=題材內個股排名較上週上升▲/下降▼家數(全市場)。階段規則：Δ>0且處自身高檔=主升段、Δ>0連漲2週+=發動、高檔轉弱=位階高但Δ轉負、連跌2週+=退潮。點欄位可排序。</div>
  <div class="scroll-box"><table id="momentumTable"></table></div>
</div>

<div class="tab-content" id="tab7">
  <div class="sc-view-switch">
    <button class="view-btn active" id="sigViewMacroBtn" onclick="switchSigView('macro')">大題材檢查清單</button>
    <button class="view-btn" id="sigViewMicroBtn" onclick="switchSigView('micro')">微題材脈衝雷達</button>
    <button class="view-btn" id="sigViewCatchupBtn" onclick="switchSigView('catchup')">補漲雷達</button>
    <button class="view-btn" id="sigViewRevmomBtn" onclick="switchSigView('revmom')">題材營收動能</button>
    <button class="view-btn" id="sigViewDispoBtn" onclick="switchSigView('dispo')">處置股觀察</button>
    <button class="view-btn" id="sigViewResoBtn" onclick="switchSigView('reso')">🔥共振</button>
    <button class="view-btn" id="sigViewThermoBtn" onclick="switchSigView('thermo')">🌡️大盤溫度計</button>
    <button class="view-btn" id="sigViewPledgeBtn" onclick="switchSigView('pledge')">🔓內部解質警戒</button>
  </div>
  <div id="sigMacroView">
  <h3 class="sec-title">檢查清單規則（源自記憶體2025/9案例研究，勿刪）</h3>
  <div class="rule-card">
    <div class="rule-item">① <b>連漲 ≥2 週</b>——熱度分數連續上升，排除單週噪音</div>
    <div class="rule-item">② <b>廣度 ≥50% 且連續兩週</b>——題材內過半個股排名上升，全族群行情而非一兩檔獨秀</div>
    <div class="rule-item">③ <b>≥3 國子分數同步上升</b>——跨市場共振（記憶體9月真起漲=4國齊升）</div>
    <div class="rule-item">④ <b>最大單國佔比 &lt;80%</b>——排除單國獨撐假訊號（2025年5-8月記憶體假訊號=韓國佔85%+）</div>
    <div class="rule-item">⑤ <b>型態門檻（內部標準）</b>——資金四關通過後，再驗證成員價格結構是否同步確認。✓ = 2022-2026樣本外驗證中勝率顯著提升的結構條件成立。位階改為<b>參考值</b>：高位階的洗盤回檔=蓄勢；題材長期趨勢向下＋低位階=⚠接刀風險——不再作為進場評級。</div>
    <div class="rule-item">⑥ <b>基本面確認（僅輔助，勿當主決策）</b>——訊號觸發時看題材成員「EPS預估成長比例」與「季營收YoY為正比例」：兩者過半=資金與基本面共振；資金熱但比例低=純題材炒作警覺。<b>資料源限制務必留意</b>：EPS欄=yfinance分析師共識的forward vs trailing比較（是「預估成長」非嚴格「上修」）；小型股可能僅1-2位分析師覆蓋、台股上櫃與陸股品質更弱、共識調整常滯後於行情；且無法回測（歷史預估不可得）。營收YoY為已公告實績，可信度高於EPS欄。<b>總營收欄(2026-07新增)</b>＝題材台股成員官方月營收加總的YoY：<b>↑✓＝YoY為正且較上月改善</b>——回測顯示觸發時總營收動能向上的題材後續表現較佳(弱加分)，定位=<b>倉位加碼的信心條件</b>，不是進場門檻；「·」＝最新月覆蓋不足僅供參考(如申報延後期間)。</div>
    <div class="rule-item" style="color:var(--tx3)">回測基礎（2022-2026共234週，含熊市壓力測試，以成員實際股價驗證）：資金四關訊號在多頭期股價勝率54-80%；加上⑤型態門檻後，樣本外(2025-26)勝率72-90%。賺賠比約2.8（平均賺+23%/賠-8%）。已知弱點：熊市中成交金額型熱度會被賣壓觸發（2022年勝率27%），建議依大盤相對月線/季線位置調整倉位（月線下六成、季線下三成，回測夏普1.56優於滿倉1.29）。台股跟隨美韓約5週；微題材脈衝行情由下方微題材雷達補接。</div>
  </div>
  <h3 class="sec-title">本週檢查表（每次資料更新自動重算）</h3>
  <div class="hint" id="sigRegime" style="font-weight:600"></div>
  <div class="hint"><b>前3大成員=回測口徑</b>：歷次回測的買法就是「觸發時買題材前3大台股資金成員、等權持8週」——這欄就是「該做哪幾隻」的直接答案；點股名跳單股雙軸圖、🔎跳族群金流解剖看完整成員點火時序；名後✓/⚡=籌碼位階徽章(外資/券資比在自身一年高檔)。依通過條數排序。✓/✗ 對應規則①~④；推薦程度=綜合①~⑤與大盤態勢的信心分級（內部權重）：<b>⭐⭐⭐重點</b>=歷史最高勝率情境、<b>⭐⭐標準</b>、<b>⭐觀察</b>=等結構確認、<b>⚠</b>=退潮接刀警示（假說級，自動降一級）。分級是研究地圖，非投資建議。</div>
  <div class="scroll-box"><table id="signalNowTable"></table></div>
  <h3 class="sec-title">歷史訊號紀錄</h3>
  <div class="hint">+8週/13週最大 = 觸發後熱度分數倍率(非股價)。對照概念股名單見專案資料夾 tmp_scan_members.txt。</div>
  <div class="scroll-box"><table id="signalHistTable"></table></div>
  </div>

  <div id="sigMicroView" style="display:none">
  <h3 class="sec-title">微題材脈衝雷達（規則v2，台股細分產品層級）</h3>
  <div class="rule-card">
    <div class="rule-item">① <b>脈衝倍率 ≥2.5</b>——本週台股分數 / 前4週中位數（微題材是脈衝行情，不適用大題材的連漲規則）</div>
    <div class="rule-item">② <b>成員排名跳升中位數 ≥ +35名</b>——全員同週大幅躍升</div>
    <div class="rule-item">③ 毛利率方向分級：<b>🅰 = 有資料成員過半最新季毛利QoQ走升</b>（漲價週期確認）；<b>🅱 = 尚未轉升</b>（資金先行，把下個季報日當驗證點：Q1→5月中/Q2→8月中/Q3→11月中/Q4→3月底）。<b>回測註記(2026-07)</b>：🅱 的歷史虧損集中在<b>大盤非多頭時期</b>，樣本內顯著劣於🅰——非多頭環境建議直接跳過🅱只做🅰，多頭環境🅱才可小倉位試單（樣本小，隨資料累積持續驗證）。毛利資料源：FinMind單季全史優先、yf補缺。</div>
    <div class="rule-item">⚠ = 前8週內有更高分數峰值（二次脈衝，出貨疑慮——基本面再好也要警惕）</div>
    <div class="rule-item" style="color:var(--tx3)">回測60週全樣本：43次觸發21次延續(49%)，但賺賠比極不對稱(贏家sustain 1.8~25x/輸家0.8~1.0)——定位是「提醒你去看」的警示訊號，配合③毛利分級與⚠二次脈衝過濾後精選案例勝率約68%。案例驗證：順德2026/3脈衝=毛利連兩季走升確認當口；ABF 2025/12假脈衝=2/3成員毛利下滑。毛利資料=yfinance季報+MOPS官方季報。</div>
  </div>
  <div class="scroll-box"><table id="microNowTable"></table></div>
  <h3 class="sec-title">微題材歷史脈衝</h3>
  <div class="hint">sustain = 之後4週均值/之前4週均值，&gt;1.5=行情延續。</div>
  <div class="scroll-box"><table id="microHistTable"></table></div>
  </div>

  <div id="sigCatchupView" style="display:none">
  <h3 class="sec-title">補漲雷達（研究員邏輯：點火題材裡誰還沒動）</h3>
  <div class="rule-card">
    <div class="rule-item">邏輯：資金常跟著券商研究員的報告邏輯走——題材點火後，下一份報告傾向寫「同題材裡低PB、營收轉正、還沒漲」的公司。本雷達在題材點火當週自動列出這份候選名單，搶在報告之前。</div>
    <div class="rule-item">① <b>題材點火</b> = 熱度分數週變化 z&gt;1 或檢查清單訊號觸發　② <b>成員未點火</b> = 個股資金額最新週變化 z≤1</div>
    <div class="rule-item">③ 埋伏理由（至少符合2項才上榜）：<b>低PB</b>(≤全市場中位數，官方BWIBBU)｜<b>營收YoY為正</b>(官方月營收)｜<b>資金低位階</b>(&lt;50%自身歷史)｜<b>預估虧轉盈</b>(yf分析師共識，僅參考)</div>
    <div class="rule-item" style="color:var(--tx3)">定位=研究清單非買進清單：進場等的是成員「自己的點火」(排名跳升/加入廣度)；符合條件但遲遲不點火=市場不認同，放掉。毛利QoQ方向(Q2財報後官方資料就有兩季可比)與合約負債(MOPS簡表無此細項，需XBRL/FinMind)待資料到位後補上。成員名後若出現<b>外資位階✓/券資比⚡</b>徽章=籌碼位階在自身一年高檔(回測加分項，說明見族群金流解剖頁)，季線下慎用並依態勢降倉。</div>
  </div>
  <div class="hint" id="catchupThemes"></div>
  <div class="scroll-box"><table id="catchupTable"></table></div>
  </div>

  <div id="sigRevmomView" style="display:none">
  <h3 class="sec-title">題材月營收動能——月營收訊號（2026-07-14上線·live驗證中）</h3>
  <div class="rule-card">
    <div class="rule-item">訊號＝把題材成員(FinMind覆蓋)月營收<b>加總</b>後看兩件事：① <b>連續3個月月增(MoM)為正</b>——中斷歸零的連續計數，給0~3分　② <b>近3個月年增率(YoY)平均為正</b>——排除低基期反彈，+1分。<b>滿分4分才是訊號</b>。時序口徑(凍結回測版)：營收月r於次月(r+1)10-15號公告、<b>再次月(r+2)的15號進場</b>——進場日只用早已公告的數字，無偷看未來(此口徑比「公告後立刻用」再保守一個月，回測數字皆基於此)。</div>
    <div class="rule-item">信心分級：<b style="color:var(--red)">⭐⭐⭐ 極高＝score 4</b>(唯一回測有超額報酬的層級)；<b>⭐ 觀察＝score 3</b>(差一分，表中標示缺哪個條件——回測無超額，僅供追蹤接近觸發的題材)；<b>score≤2不列</b>：回測顯示0-2分是雜訊不是「中等信心」，劑量反應是斷崖不是階梯，給星等會誤導。</div>
    <div class="rule-item">回測(2022-2026，828筆/115題材-月/27題材)：<b>次月15號進場、持有60個交易日</b>。單筆中位+7.4%/勝率67%/TWII超額中位+2.55%(唯一超額為正的分層)。<b>倉位用法(V2形態)</b>：訊號照進——大盤破線時觸發的批次反而是最強反彈(回測擋掉它們MDD惡化到-39%)——但<b>整體部位×大盤態勢係數</b>(月線上100%/月線下60%/季線下30%)：縮放版夏普2.07/MDD-21.6% vs 滿倉1.90/-29.8%。</div>
    <div class="rule-item" style="color:var(--tx3)">警語：<b>regime依賴</b>——超額集中在題材行情年(2025年獨立顯著、2024年偏負)，屬「行情放大器」非全天候訊號；獨立樣本僅115個題材-月(LOTO+cluster bootstrap通過但n有限)；宇宙=FinMind覆蓋∩題材分類約283檔。成員欄列<b>前5大營收</b>(占題材營收中位97%，top-N等價測試佐證)——回測買法是題材全成員等權，前5大是聚焦顯示。📈=跳「題材動能與共振」頁看該題材營收圖。</div>
  </div>
  <div class="hint" id="revmomTier" style="font-weight:600"></div>
  <h3 class="sec-title">最新訊號（<span id="revmomSigMonth"></span>）</h3>
  <div class="scroll-box"><table id="revmomNowTable"></table></div>
  <h3 class="sec-title">持有中訊號</h3>
  <div class="hint">回測口徑＝訊號月15號進場、持有60個交易日(約3個月)；到期日為近似值(進場+87日曆天)。訊號月15號尚未到＝「等進場」。</div>
  <div class="scroll-box"><table id="revmomHoldTable"></table></div>
  </div>

  <div id="sigDispoView" style="display:none">
  <h3 class="sec-title">處置股觀察——流動性凍結週期策略（2026-07-16上線·live驗證中）</h3>
  <div class="rule-card">
    <div class="rule-item">機制：處置＝監管製造的可預測流動性凍結（分盤撮合＋預收全額款券趕走投機資金→公告衝擊跌），期滿前資金搶跑回流。逐日解剖(~1,890事件)：<b>公告首日−1.87%→中段築底→倒數第2日+1.43%(全週期最強日)→出關起連三日負</b>。「出關行情」是迷思——出關日進場的人是本策略的出場流動性。</div>
    <div class="rule-item">兩個進場形態(皆<b>尾盤收盤買</b>)：<b>V4＝第3個處置日</b>買、抱全段(~8交易日，淨中位+3.78%/勝率62%)；<b>V5＝倒數第3日</b>買、搶跑段(~4交易日，前段一直跌組+4.14%/66%——前段已大漲的別買，出關後是50/50肥尾樂透)。<b>出場鐵律＝出關日開盤，不戀棧</b>。</div>
    <div class="rule-item">加分項(劑量單調)：<b>20分鐘分盤</b>(第2次處置)+6.96%/71% &gt; 5分鐘+2.26%；<b>題材成員</b>+6.88%/70%(名單有事後偏差,幅度打折看)；公告衝擊跌越深越好。<b>⚠避開</b>：「人工管制撮合」類(−4.71%/38%)、第3日成交值&lt;0.3億的小票、前段已漲&gt;10%的強勢票。</div>
    <div class="rule-item">選件分層(回測V4淨額,倉位大小參考——T1給大份/T4給小份,取捨用先到先選+並發上限5)：
      <table style="margin:6px 0 2px">
        <tr><th>Tier</th><th>條件</th><th>淨中位</th><th>勝率</th><th>月均</th></tr>
        <tr><td><b>T1</b></td><td style="text-align:left">題材成員∩20分盤</td><td><b>+8.77%</b></td><td>76%</td><td>3.1件</td></tr>
        <tr><td>T2</td><td style="text-align:left">題材成員</td><td>+5.50%</td><td>66%</td><td>3.9件</td></tr>
        <tr><td>T3</td><td style="text-align:left">20分盤</td><td>+5.63%</td><td>67%</td><td>3.7件</td></tr>
        <tr><td>T4</td><td style="text-align:left">其餘</td><td>+1.53%</td><td>56%</td><td>9.2件</td></tr>
      </table>
    (題材成員欄有事後名單偏差,幅度打折看;下表「Tier」欄=每檔自動判定)。<b>胃納量梯度(2026-07-16補測)</b>：處置前20日均成交值越大效果越好——&lt;0.5億+0.70%/55%→0.5-2億+2.41%→2-10億+4.65%→<b>&gt;10億+6.76%/71%</b>；胃納≥2億×T1=+8.83%/78%=實戰甜蜜格(被凍結趕走的投機資金越多,回流越猛;大票可放大部位,小票本來就該跳過)。</div>
    <div class="rule-item" style="color:var(--tx3)">回測(2019-2026,1,878事件,扣0.45%成本)：扣TWII超額八年全正(含2022熊市)；月群bootstrap CI95=[+2.30,+4.91] p&lt;0.0001；2026年反而史上最肥(擁擠化指紋不存在,預收款券+分盤=結構性護城河)。載具建議：並發上限5檔、先到先選、tier調倉位(題材∩20分盤給大份)。處置期間買賣皆需預收全額款券、5/20分鐘才撮合一次——掛單用限價、部位≤當日成交值1%。未來行動日以平日近似，遇休市順延1-2日屬正常，以XQ/券商公告為準。詳研究報告/research_panic_liquidity.html。</div>
  </div>
  <div class="hint" id="dispoAsof" style="font-weight:600"></div>
  <div style="margin:6px 0 8px">
    分盤 <select id="dispoFilterMins" onchange="renderDispoTab()">
      <option value="">全部</option><option value="5">5分鐘(第1次)</option><option value="20">20分鐘(第2次,較嚴)</option>
    </select>
    　Tier <select id="dispoFilterTier" onchange="renderDispoTab()">
      <option value="">全部</option><option value="1">T1 題材∩20分</option><option value="2">T2 題材</option>
      <option value="3">T3 20分</option><option value="4">T4 其餘</option>
    </select>
    <span class="hint" style="display:inline">（制度只有5分/20分兩檔；更嚴的「人工管制撮合」=⚠毒格已標）</span>
  </div>
  <div class="scroll-box"><table id="dispoNowTable"></table></div>
  <h3 class="sec-title" style="margin-top:16px">CB處置（5位數代碼＝可轉債標的）</h3>
  <div class="hint">CB被處置＝標的股投機過熱的外溢訊號；不適用V4/V5股票回測口徑，供關聯觀察（對應股票＝前4碼）。</div>
  <div class="scroll-box"><table id="dispoCbTable"></table></div>
  </div>

  <div id="sigResoView" style="display:none">
  <h3 class="sec-title">🔥多週期題材共振（2026-07-22上線·研究稿,尚未上正式回測看板）</h3>
  <div class="rule-card">
    <div class="rule-item">訊號：同題材(main_group,≥5檔成員)同一週≥2檔個股「日線爆量長紅創高(單日+4%且量≥2倍20日均量)＋週線同步創12週高」雙線對齊——breadth越多檔同振後續越強(2檔中位+2.46%/3檔+以上+6.22%,fwd8週)。</div>
    <div class="rule-item">驗證(2005-2026,22題材,1,117筆episode)：LOTO 21年100%為正、cluster bootstrap CI95=[+1.85,+5.96]/P(≤0)=0.0005——雙過。疊加TWII/OTC週線水位階梯後MDD由-44%收斂到-16~-21%、夏普由1.14拉高到2.3+(季線下0.3/月線下0.6/月線上1.0)。出場：固定8週持有(資金週轉),8-16週內若拉回(跌破自身月線)可加碼再抱8週(合計中位+3.98%/勝率57%,LOTO+bootstrap雙過)。</div>
    <div class="rule-item" style="color:var(--tx3)">⚠尚未查證跟既有檢查清單/題材營收動能訊號的重疊率與獨立增量，先列觀察層；成本0.5%/筆未含滑價；個股雙題材標籤可能重複計入。詳細研究報告/research_resonance.html。</div>
  </div>
  <div class="hint" id="resoAsof" style="font-weight:600"></div>
  <div class="scroll-box"><table id="resoTable"></table></div>
  </div>

  <div id="sigPledgeView" style="display:none">
  <h3 class="sec-title">🔓內部解質警戒——大股東/董事長高檔解質＝出貨嫌疑（2026-07-20上板·觀察層）</h3>
  <div class="rule-card">
    <div class="rule-item">機制：質押中的股票不能賣，<b>解質＝賣出前的必要步驟</b>——內部人（董事長系/大股東）在股價高檔大額解質＝出貨準備腳印。回測（2019-2026，n=330，錨點案例=國巨2026-06-01解質11,400張→6月底作頂）：事件後60日超額中位<b>−6.90%</b>／勝率36%；配對複核過（同股高檔日常態−2.88%，配對差−3.93pp，bootstrap CI上緣&lt;0）＝增量真實非池飄移。效應是<b>過程不是單日</b>（10日−1.6%→20日−3.1%→60日−6.9%），60日窗吃滿。</div>
    <div class="rule-item" style="color:var(--red);font-weight:600">⚠ 用法＝只做減碼審查，絕不放空。事件分布中位−6.9%但均值+0.01%——右尾火箭（18個漲逾+50%、最大+225%）把均值吃回零，純放空載具七年半剩0.13x／MDD−91%＝❌判死。正確動作：持有中個股觸發→列入減碼檢討（避開中位結局；萬一是火箭只是少賺不虧損）；選股時當避開名單。</div>
    <div class="rule-item">⚠ <b>設質沒有資訊</b>（方向專一四度確認）：高檔設質＝借錢留倉（配對差+0.79pp跨零，要賣得先解質，押進去反而暗示不賣）、低檔補提（−0.99pp跨零）、質押存量位階（高低無梯度）——質押資料整座礦只有「高檔×解質」一格有金，所以本檢視只列解質。股東會季（4-6月）解質＝表決權技術操作亦無資訊（−1.25%≈基準），下表以「股東會季」標籤降級記錄。</div>
    <div class="rule-item" style="color:var(--tx3)">口徑：內部人=申報身分含董事長/大股東（含法人代表人、他人名義、配偶變體）；🔴警戒格=解質≥1,000張×事件日股價240日位階≥80×非4-6月；已剔除轉貸（同日同人設質+解質同量級）。效應窗60個交易日，過窗自動下架。維運：<code>python fetch_pledge.py</code>每週跑（MoneyDJ每日董監質設異動彙整）。詳研究報告/research_pledge_release.html。</div>
  </div>
  <div class="hint" id="pledgeAsof" style="font-weight:600"></div>
  <h3 class="sec-title" style="margin-top:12px">題材聚合——現在哪些產業的高層在賣</h3>
  <div class="scroll-box"><table id="pledgeThemeAgg"></table></div>
  <h3 class="sec-title" style="margin-top:16px">窗內事件明細</h3>
  <div class="scroll-box"><table id="pledgeTable"></table></div>
  <div class="hint">狀態欄：🔴警戒=主測口徑（回測−6.9%那格）；觀察=內部人大額解質但位階未達80（半數真頂部事前位階不高，低位階≠安全）；股東會季=4-6月混淆組（無資訊僅記錄）。交叉欄：該股同時在訊號頁前3大／處置中／營收前5名單＝<b>持股減碼審查的實戰入口</b>。累積張=本批申報人異動後仍質押的張數。</div>
  </div>

  <div id="sigThermoView" style="display:none">
  <div class="rule-card">
    <div class="rule-title">🌡️ 大盤溫度計（市場層五燈：恐慌出清＝進場窗，機制＝非資訊性賣壓才有反彈）</div>
    <div class="rule-item">用法：燈亮＝該訊號的歷史進場窗開啟，各有建議持有期與到期倒數；多燈同亮＝證據疊加（2025-04-08溫度計×警戒帶同亮→k60+23%）。合成曝險=水位階梯v0（研究稿）：溫度計0.6/60日＋B 0.4/10日＋警戒帶0.3＋雙收斂0.3/20日＋跌停廣度0.3/20日，加總封頂1.0。</div>
    <div class="rule-item">⚠死格警語：<b>2022-06型慢熊中段恐慌≠底</b>（溫度計唯一敗格）；<b>跌停spike第一腿≠底</b>（2020-01-30，跌停286家後k60−6.28%）；8-10月觸發B＝亞洲逆風季吃短不抱60日；A型環境（美亞同跌）別接，等下一個climax。</div>
    <div class="rule-item">口徑註記：甜蜜格/跌停家數＝研究池1,379檔（與判決同尺，全市場版待複跑升級）；跌停＝前收×0.9進位至tick近似（考卷用官方tick精確版，門檻層級兩版同判）；並發數需當日價格——崩盤日先跑 fetch_daily_price --update 再重匯。</div>
  </div>
  <div id="thermoHeadline" style="font-size:1.05em;font-weight:700;margin:4px 0 10px;padding:10px 12px;border-radius:8px;border:1px solid var(--bd);background:var(--sf)"></div>
  <div class="hint" id="thermoAsof" style="font-weight:600"></div>
  <div id="thermoCards" style="display:flex;flex-wrap:wrap;gap:10px;margin:10px 0"></div>
  <h3 class="sec-title">近10日讀數（甜蜜格並發／跌停家數）</h3>
  <div class="scroll-box"><table id="thermoSeries"></table></div>
  <h3 class="sec-title">歷史同類事件(甜蜜格並發≥20)</h3>
  <div class="scroll-box"><table id="thermoEpisodes"></table></div>
  </div>
</div>

<div class="health-bar" id="healthBar"></div>

<script>
const DATA = __DATA_JSON__;

function tierClass(tier) {
  if (tier.indexOf("前50") >= 0) return "tier-hot";
  if (tier.indexOf("51-150") >= 0) return "tier-mid";
  return "tier-edge";
}

// columns: [{key, label, numeric(bool), sortKey(optional, defaults to key)}]
function buildTable(tableEl, columns, rows, rowClassFn) {
  tableEl._cols = columns;
  tableEl._rows = rows;
  tableEl._rowClassFn = rowClassFn;
  if (!tableEl._sortState) tableEl._sortState = {colIndex: null, dir: 1};
  renderTableBody(tableEl);
}

function renderTableBody(tableEl) {
  const columns = tableEl._cols, rowClassFn = tableEl._rowClassFn;
  let rows = tableEl._rows.slice();
  const {colIndex, dir} = tableEl._sortState;
  if (colIndex !== null) {
    const col = columns[colIndex];
    const sortKey = col.sortKey || col.key;
    rows.sort((a, b) => {
      let va = a[sortKey], vb = b[sortKey];
      if (va === undefined || va === null) va = col.numeric ? -Infinity : "";
      if (vb === undefined || vb === null) vb = col.numeric ? -Infinity : "";
      if (col.numeric) return (va - vb) * dir;
      return String(va).localeCompare(String(vb)) * dir;
    });
  }
  let thead = "<tr>" + columns.map((c, i) => {
    let arrow = "";
    if (tableEl._sortState.colIndex === i) arrow = `<span class="arrow">${tableEl._sortState.dir === 1 ? "▲" : "▼"}</span>`;
    return `<th onclick="onHeaderClick('${tableEl.id}', ${i})">${c.label} ${arrow}</th>`;
  }).join("") + "</tr>";
  let tbody = rows.map(r => {
    let cls = rowClassFn ? rowClassFn(r) : "";
    let tds = columns.map(c => {
      const v = r[c.key];
      if (c.isLink && v) return `<td><a href="${v}" target="_blank" rel="noopener">開啟↗</a></td>`;
      return `<td>${v !== undefined && v !== null ? v : ""}</td>`;
    }).join("");
    return `<tr class="${cls}">${tds}</tr>`;
  }).join("");
  tableEl.innerHTML = thead + tbody;
}

function onHeaderClick(tableId, colIndex) {
  const tableEl = document.getElementById(tableId);
  const s = tableEl._sortState;
  if (s.colIndex === colIndex) { s.dir = -s.dir; } else { s.colIndex = colIndex; s.dir = 1; }
  renderTableBody(tableEl);
}

function showTab(i) {
  // 按鈕順序與內容區塊順序脫鉤：用 onclick 內容/元素 id 對應，不用位置索引
  document.querySelectorAll(".tab-btn").forEach(b =>
    b.classList.toggle("active", (b.getAttribute("onclick") || "").indexOf("showTab(" + i + ")") >= 0));
  document.querySelectorAll(".tab-content").forEach(t => t.classList.toggle("active", t.id === "tab" + i));
}

function renderThemePivot() {
  const onlyThematic = document.getElementById("onlyThematic").checked;
  const pivotRaw = onlyThematic ? DATA.theme_pivot_thematic.slice(0, 10) : DATA.theme_pivot_all;
  const pivot = pivotRaw.map(r => Object.assign({}, r, {main_group_disp: themeLink(r.main_group)}));
  const cols = [
    {key: "main_group_disp", label: "主族群", sortKey: "main_group"},
    {key: "熱度分數", label: "熱度分數", numeric: true},
  ];
  if (DATA.previous_date) {
    cols.push({key: "熱度分數Δ", label: "熱度分數Δ", numeric: true});
    cols.push({key: "金額Δ億台幣", label: "金額Δ(億台幣)", numeric: true});
  }
  cols.push({key: "金額合計億台幣", label: "金額合計(億台幣)", numeric: true, sortKey: "_amt_num"});
  DATA.countries.forEach(c => cols.push({key: c, label: c, numeric: true}));
  cols.push({key: "合計家數", label: "合計家數", numeric: true});
  const tableEl = document.getElementById("themePivotTable");
  tableEl._sortState = {colIndex: 1, dir: -1};
  buildTable(tableEl, cols, pivot);

  const sel = document.getElementById("themePick");
  const prev = sel.value;
  sel.innerHTML = Object.keys(DATA.theme_detail).map(g => `<option value="${g}">${g}</option>`).join("");
  if (prev && DATA.theme_detail[prev]) sel.value = prev;
  renderThemeDetail();
  renderMoversChart();
}

function getVisibleThemes(includeBroad) {
  // 只留「至少有一家台股公司」的題材；廣義分類依參數決定
  if (includeBroad === undefined) includeBroad = document.getElementById("hmIncludeBroad").checked;
  const twCount = {};
  DATA.theme_pivot_all.forEach(function(p) { twCount[p.main_group] = p["台"] || 0; });
  const thematicSet = {};
  (DATA.theme_list_thematic || []).forEach(function(g) { thematicSet[g] = true; });
  return Object.keys(DATA.theme_history).filter(function(g) {
    if (!twCount[g]) return false;
    if (!includeBroad && !thematicSet[g]) return false;
    return true;
  });
}

function renderMoversChart() {
  const el = document.getElementById("moversChart");
  const dates = DATA.snapshot_dates;
  if (!dates || dates.length < 2) { el.innerHTML = ""; return; }
  let n = parseInt(document.getElementById("moverPeriod").value, 10) || 1;
  if (n > dates.length - 1) n = dates.length - 1;
  const curDate = dates[dates.length - 1];
  const baseDate = dates[dates.length - 1 - n];
  const movers = [];
  getVisibleThemes().forEach(function(g) {
    const byDate = {};
    (DATA.theme_history[g] || []).forEach(function(r) { byDate[r.snapshot_date] = r["熱度分數"]; });
    if (byDate[curDate] === undefined || byDate[baseDate] === undefined) return;
    movers.push({g: g, d: +(byDate[curDate] - byDate[baseDate]).toFixed(2)});
  });
  movers.sort(function(a, b) { return b.d - a.d; });
  const seen = {};
  const uniq = movers.slice(0, 10).concat(movers.slice(-10)).filter(function(m) {
    if (seen[m.g]) return false; seen[m.g] = true; return true;
  });
  uniq.sort(function(a, b) { return a.d - b.d; });
  Plotly.newPlot(el.id, [{
    x: uniq.map(function(m) { return m.d; }),
    y: uniq.map(function(m) { return m.g; }),
    type: "bar", orientation: "h",
    marker: {color: uniq.map(function(m) { return m.d >= 0 ? "#ff6b6b" : "#4da3ff"; })},
  }], {
    title: "熱度分數變化 前10上升/前10下降（" + baseDate + " → " + curDate + "）",
    paper_bgcolor: "#0c1118", plot_bgcolor: "#131c27", font: {color: "#d4dde8"},
    xaxis: {title: "熱度分數Δ"},
    yaxis: {automargin: true},
    margin: {l: 160},
  }, {responsive: true});
}

function renderThemeDetail() {
  const g = document.getElementById("themePick").value;
  const rows = DATA.theme_detail[g] || [];
  const cols = [
    {key: "country", label: "國家"}, {key: "rank", label: "排名", numeric: true}, {key: "code", label: "代碼"},
    {key: "中文名稱", label: "中文名稱"}, {key: "name", label: "原文名稱"}, {key: "sub_product", label: "細分產品"},
    {key: "position_note", label: "產業地位"}, {key: "金額億", label: "金額(億)"},
    {key: "金額億台幣", label: "金額(億台幣)", numeric: true, sortKey: "金額億台幣_num"}, {key: "熱度", label: "熱度"},
  ];
  const tableEl = document.getElementById("themeDetailTable");
  tableEl._sortState = {colIndex: 1, dir: 1};
  buildTable(tableEl, cols, rows, r => tierClass(r["熱度"]));
}

function renderFullTable() {
  const countries = Array.from(document.getElementById("countryFilter").selectedOptions).map(o => o.value);
  const group = document.getElementById("groupFilter").value;
  let rows = DATA.full_records.filter(r => countries.includes(r.country));
  if (group) rows = rows.filter(r => (r.main_groups || "").includes(group));
  const cols = [
    {key: "country", label: "國家"}, {key: "rank", label: "排名", numeric: true}, {key: "code", label: "代碼"},
    {key: "中文名稱", label: "中文名稱"}, {key: "name", label: "原文名稱"}, {key: "金額億", label: "金額(億)"},
    {key: "金額億台幣", label: "金額(億台幣)", numeric: true, sortKey: "金額億台幣_num"},
  ];
  if (DATA.previous_date) {
    cols.push({key: "排名Δ", label: "排名Δ", sortKey: "排名Δ_num", numeric: true});
    cols.push({key: "金額Δ億台幣", label: "金額Δ(億台幣)", numeric: true});
  }
  cols.push({key: "main_groups", label: "主族群"}, {key: "熱度", label: "熱度"});
  const tableEl = document.getElementById("fullTable");
  if (!tableEl._sortState) tableEl._sortState = {colIndex: 1, dir: 1};
  buildTable(tableEl, cols, rows, r => tierClass(r["熱度"]));
}

function initSearchBox(inputId, dropdownId, hiddenId, items, onSelect) {
  const input    = document.getElementById(inputId);
  const dropdown = document.getElementById(dropdownId);
  const hidden   = document.getElementById(hiddenId);

  function showDropdown(list) {
    if (!list.length) { dropdown.style.display = "none"; return; }
    dropdown.innerHTML = "";
    list.forEach(item => {
      const div = document.createElement("div");
      div.className = "search-item";
      div.textContent = item.label;
      div.addEventListener("mousedown", e => {
        e.preventDefault();
        hidden.value  = item.value;
        input.value   = item.label;
        dropdown.style.display = "none";
        onSelect();
      });
      dropdown.appendChild(div);
    });
    dropdown.style.display = "block";
  }

  // 預設選第一筆
  if (items.length) {
    hidden.value = items[0].value;
    input.value  = items[0].label;
  }

  input.addEventListener("input", () => {
    const q = input.value.trim().toLowerCase();
    showDropdown(q ? items.filter(i => i.label.toLowerCase().includes(q)) : items);
  });
  input.addEventListener("focus", () => {
    const q = input.value.trim().toLowerCase();
    showDropdown(q ? items.filter(i => i.label.toLowerCase().includes(q)) : items);
  });
  input.addEventListener("blur", () => {
    setTimeout(() => { dropdown.style.display = "none"; }, 150);
  });
}

// ── 多公司排名對比 ───────────────────────────────────────────────────
const COMPARE_COLORS = ["#3c8cf0", "#e84545", "#34b87a", "#d49610", "#a06ee0", "#4dc3d0"];
let histCompanies = [];

function addHistCompany() {
  const key = document.getElementById("companyPick").value;
  if (!key || !DATA.company_history[key]) return;
  if (histCompanies.indexOf(key) < 0) {
    histCompanies.push(key);
    if (histCompanies.length > 6) histCompanies.shift();
  }
  renderCompanyChips();
  renderCompanyHistory();
}

function removeHistCompany(key) {
  histCompanies = histCompanies.filter(k => k !== key);
  renderCompanyChips();
  renderCompanyHistory();
}

function renderCompanyChips() {
  const el = document.getElementById("companyChips");
  el.innerHTML = histCompanies.map(k => {
    const e = DATA.company_history[k];
    return `<span class="chip">${e ? e.label : k}<span class="chip-x" onclick="removeHistCompany('${k}')">×</span></span>`;
  }).join("");
}

// ── 族群共振視圖：同題材前N大台股成員的股價/資金是否齊動 ──────────────
const RES_COLORS = ["#3c8cf0", "#e84545", "#34b87a", "#d49610", "#a06ee0", "#4dc3d0", "#f06ba8", "#8a9a3c", "#c07840", "#6b7f91"];

function resCorr(a, b) {
  const xs = [], ys = [];
  for (let i = 0; i < a.length; i++) {
    if (a[i] !== null && b[i] !== null) { xs.push(a[i]); ys.push(b[i]); }
  }
  if (xs.length < 5) return null;
  const n = xs.length;
  const mx = xs.reduce(function(s, v) { return s + v; }, 0) / n;
  const my = ys.reduce(function(s, v) { return s + v; }, 0) / n;
  let sxy = 0, sxx = 0, syy = 0;
  for (let i = 0; i < n; i++) {
    const dx = xs[i] - mx, dy = ys[i] - my;
    sxy += dx * dy; sxx += dx * dx; syy += dy * dy;
  }
  return (sxx > 0 && syy > 0) ? sxy / Math.sqrt(sxx * syy) : null;
}

function initResonance() {
  const cnt = {};
  Object.keys(DATA.company_info || {}).forEach(function(k) {
    if (k.indexOf("台|") !== 0 || !DATA.company_history[k]) return;
    (DATA.company_info[k].g || []).forEach(function(g) { cnt[g] = (cnt[g] || 0) + 1; });
  });
  const score = {};
  (DATA.theme_pivot_all || []).forEach(function(p) { score[p.main_group] = p["熱度分數"] || 0; });
  const themes = Object.keys(cnt).filter(function(g) { return cnt[g] >= 3; });
  themes.sort(function(a, b) { return (score[b] || 0) - (score[a] || 0); });
  if (!themes.length) {
    // company_history未載入(SLIM_HISTORY=True省容量模式)時,這個相關係數版共振會是空的——
    // 不要讓它靜默看起來像壞掉,明講原因;另有事件式的🔥共振標籤(進場訊號頁)不受影響,資料源不同
    document.getElementById("resTheme").innerHTML = "";
    const chartEl = document.getElementById("resChart");
    if (chartEl) chartEl.innerHTML = "<div class=\"hint\">此功能需要個股歷史股價(company_history)，"
      + "目前為省容量模式未載入(export_html.py開頭SLIM_HISTORY=False重跑即可恢復)。"
      + "若只是想看「哪些股票最近共振」，改看「進場訊號→🔥共振」頁籤，是另一套事件式訊號不受此限制。</div>";
    return;
  }
  document.getElementById("resTheme").innerHTML = themes.map(function(g) {
    return "<option value=\"" + g + "\">" + g + "（" + (score[g] || 0).toFixed(1) + "）</option>";
  }).join("");
  renderResonance();
}

function renderResonance() {
  const theme = document.getElementById("resTheme").value;
  const nWeeks = parseInt(document.getElementById("resRange").value, 10);
  const topN = parseInt(document.getElementById("resN").value, 10);
  const dates = DATA.snapshot_dates;
  const L = dates.length;
  const start = Math.max(0, L - nWeeks);
  const chartEl = document.getElementById("resChart");

  // 候選成員：該題材台股，按最新快照資金額排序，收盤覆蓋不足者跳過
  const cand = [];
  Object.keys(DATA.company_info || {}).forEach(function(k) {
    if (k.indexOf("台|") !== 0) return;
    const info = DATA.company_info[k];
    if (!info.g || info.g.indexOf(theme) < 0) return;
    const e = DATA.company_history[k];
    if (!e) return;
    const cl = {}, rk = {};
    let amt = 0;
    e.rows.forEach(function(r) {
      rk[r[0]] = r[1];
      if (r.length > 4 && r[4] !== null && r[4] !== undefined) cl[r[0]] = r[4];
      if (r[0] === L - 1) amt = r[3] || 0;
    });
    cand.push({key: k, label: e.label, cl: cl, rk: rk, amt: amt});
  });
  cand.sort(function(a, b) { return b.amt - a.amt; });
  const need = Math.max(5, Math.floor(nWeeks * 0.5));
  const members = [];
  for (let i = 0; i < cand.length && members.length < topN; i++) {
    let valid = 0;
    for (let t = start; t < L; t++) if (cand[i].cl[t] !== undefined) valid++;
    if (valid >= need) members.push(cand[i]);
  }
  const badgeEl = document.getElementById("resScoreBadge");
  const chipsEl = document.getElementById("resChips");
  if (members.length < 3) {
    Plotly.purge(chartEl);
    chartEl.innerHTML = "<div class=\"hint\">此題材有股價資料的台股成員不足3家，無法看共振。</div>";
    badgeEl.innerHTML = ""; chipsEl.innerHTML = "";
    renderAnatomy();
    return;
  }

  // 每成員全歷史週報酬(給滾動共振用)
  members.forEach(function(m) {
    m.ret = [];
    for (let t = 0; t < L; t++) {
      m.ret.push((m.cl[t] !== undefined && m.cl[t - 1] !== undefined) ? m.cl[t] / m.cl[t - 1] - 1 : null);
    }
  });
  // 滾動8週共振分數
  const rollX = [], rollY = [];
  for (let t = Math.max(start, 8); t < L; t++) {
    const sl = members.map(function(m) { return m.ret.slice(t - 7, t + 1); });
    const cs = [];
    for (let i = 0; i < sl.length; i++) {
      for (let j = i + 1; j < sl.length; j++) {
        const c = resCorr(sl[i], sl[j]);
        if (c !== null) cs.push(c);
      }
    }
    if (cs.length) {
      rollX.push(dates[t]);
      rollY.push(cs.reduce(function(s, v) { return s + v; }, 0) / cs.length);
    }
  }
  const curScore = rollY.length ? rollY[rollY.length - 1] : null;
  if (curScore !== null) {
    const lv = curScore >= 0.7 ? ["🔴 強共振", "var(--red)"] : curScore >= 0.4 ? ["🟡 中等", "var(--amb)"] : ["⚪ 各走各的", "var(--tx3)"];
    badgeEl.innerHTML = "共振分數 <b style=\"color:" + lv[1] + ";font-size:15px\">" + curScore.toFixed(2) + "</b> " + lv[0];
  } else { badgeEl.innerHTML = ""; }

  const winDates = dates.slice(start);
  const traces = [];
  members.forEach(function(m, i) {
    const color = RES_COLORS[i % RES_COLORS.length];
    const p = m.label.split(" ");
    const short = p.length >= 3 ? p[1] + p[2] : m.label;
    m.short = short; m.color = color;
    let base = null;
    const py = [], ry = [];
    for (let t = start; t < L; t++) {
      const c = m.cl[t];
      if (base === null && c !== undefined) base = c;
      py.push((c !== undefined && base) ? +(c / base * 100).toFixed(1) : null);
      ry.push(m.rk[t] !== undefined ? m.rk[t] : null);
    }
    traces.push({x: winDates, y: py, mode: "lines", name: short, legendgroup: short,
                 connectgaps: true, line: {color: color, width: 2}});
    traces.push({x: winDates, y: ry, mode: "lines", name: short, legendgroup: short,
                 showlegend: false, yaxis: "y2", hoverinfo: "skip",
                 connectgaps: true, line: {color: color, width: 1.3}});
  });
  traces.push({x: rollX, y: rollY, mode: "lines", name: "共振分數", yaxis: "y3",
               fill: "tozeroy", line: {color: "#d49610", width: 1.5},
               fillcolor: "rgba(212,150,16,.15)", showlegend: false});
  Plotly.newPlot(chartEl, traces, {
    title: {text: theme + "　前" + members.length + "大台股成員", font: {size: 14}},
    xaxis: {domain: [0, 1]},
    yaxis: {title: {text: "股價(起點=100)", font: {size: 11}}, domain: [0.50, 1]},
    yaxis2: {title: {text: "資金排名", font: {size: 11}}, domain: [0.17, 0.44], autorange: "reversed", anchor: "x"},
    yaxis3: {title: {text: "共振", font: {size: 11}}, domain: [0, 0.11], range: [-0.5, 1], anchor: "x"},
    shapes: [{type: "line", xref: "paper", x0: 0, x1: 1, yref: "y3", y0: 0.7, y1: 0.7,
              line: {color: "rgba(232,69,69,.5)", width: 1, dash: "dot"}}],
    hovermode: "x unified",
    paper_bgcolor: "#0c1118", plot_bgcolor: "#131c27", font: {color: "#d4dde8"},
    legend: {orientation: "h", y: 1.06, font: {size: 11}},
    margin: {t: 60, b: 40},
  }, {responsive: true});

  chipsEl.innerHTML = members.map(function(m) {
    const lastRk = m.rk[L - 1];
    return "<span class=\"chip\" style=\"cursor:pointer;border-left:3px solid " + m.color + "\" " +
           "onclick=\"jumpToCompany('" + m.key + "')\" title=\"跳到下方單股檢視\">" + m.short +
           (lastRk ? " #" + lastRk : " 未上榜") + "</span>";
  }).join("");
  renderAnatomy();
}

// ── 族群金流解剖：市場層點火順序 + 集中度 + 台股成員點火時序 ────────────
const ANA_COLORS = {台: "#e84545", 美: "#3c8cf0", 韓: "#a06ee0", 日: "#34b87a", 陸: "#d49610"};

function anaIgn(series) {
  const d = [];
  for (let i = 1; i < series.length; i++) d.push(series[i] - series[i - 1]);
  if (!d.length) return [];
  const mean = d.reduce(function(s, v) { return s + v; }, 0) / d.length;
  const sd = Math.sqrt(d.reduce(function(s, v) { return s + (v - mean) * (v - mean); }, 0) / d.length);
  const out = [];
  if (!sd) return out;
  for (let i = 0; i < d.length; i++) if (d[i] / sd > 1) out.push(i + 1);
  return out;
}

function renderAnatomy() {
  const theme = document.getElementById("resTheme").value;
  const nWeeks = parseInt(document.getElementById("resRange").value, 10);
  const dates = DATA.snapshot_dates, L = dates.length;
  const start = Math.max(0, L - nWeeks);
  const winDates = dates.slice(start);
  const chartEl = document.getElementById("anaChart");
  const concEl = document.getElementById("anaConc");
  const tableEl = document.getElementById("anaTable");

  // 市場層：五國子分數 + 點火標記
  const tc = (DATA.theme_country_history || {})[theme] || {};
  const traces = [];
  ["美", "韓", "日", "陸", "台"].forEach(function(c) {
    const s = tc[c];
    if (!s) return;
    const color = ANA_COLORS[c] || "#6b7f91";
    traces.push({x: winDates, y: s.slice(start), mode: "lines", name: c,
                 line: {color: color, width: c === "台" ? 2.5 : 1.8}});
    const ig = anaIgn(s).filter(function(w) { return w >= start; });
    if (ig.length) {
      traces.push({x: ig.map(function(w) { return dates[w]; }),
                   y: ig.map(function(w) { return s[w]; }),
                   mode: "markers", showlegend: false,
                   marker: {color: color, size: 9, symbol: "diamond"},
                   hovertemplate: c + " 點火 %{x}<extra></extra>"});
    }
  });
  if (!traces.length) {
    Plotly.purge(chartEl);
    chartEl.innerHTML = "<div class=\"hint\">此題材無國別子分數資料。</div>";
  } else {
    Plotly.newPlot(chartEl, traces, {
      title: {text: theme + "　五市場子分數與點火週（◆）", font: {size: 14}, y: 0.97, yanchor: "top"},
      yaxis: {title: {text: "子分數(份額%)", font: {size: 11}}},
      paper_bgcolor: "#0c1118", plot_bgcolor: "#131c27", font: {color: "#d4dde8"},
      legend: {orientation: "h", y: 1.1, yanchor: "bottom", font: {size: 11}},
      hovermode: "x unified", margin: {t: 78, b: 36},
    }, {responsive: true});
  }

  // 台股成員
  const mem = [];
  Object.keys(DATA.company_info || {}).forEach(function(k) {
    if (k.indexOf("台|") !== 0) return;
    const info = DATA.company_info[k];
    if (!info.g || info.g.indexOf(theme) < 0) return;
    const e = DATA.company_history[k];
    if (!e) return;
    const amt = {}, rk = {};
    e.rows.forEach(function(r) { amt[r[0]] = r[3] || 0; rk[r[0]] = r[1]; });
    mem.push({key: k, label: e.label, amt: amt, rk: rk});
  });
  if (!mem.length) {
    Plotly.purge(concEl); concEl.innerHTML = ""; tableEl.innerHTML = "";
    return;
  }

  // 集中度：第1大成員佔題材台股金額%
  const concX = [], concY = [];
  for (let t = start; t < L; t++) {
    let tot = 0, mx = 0;
    mem.forEach(function(m) { const a = m.amt[t] || 0; tot += a; if (a > mx) mx = a; });
    if (tot > 0) { concX.push(dates[t]); concY.push(+(mx / tot * 100).toFixed(1)); }
  }
  Plotly.newPlot(concEl, [{x: concX, y: concY, mode: "lines", fill: "tozeroy",
    line: {color: "#d49610", width: 1.5}, fillcolor: "rgba(212,150,16,.15)"}], {
    yaxis: {title: {text: "第1大佔%", font: {size: 10}}, range: [0, 100]},
    paper_bgcolor: "#0c1118", plot_bgcolor: "#131c27", font: {color: "#d4dde8", size: 10},
    margin: {t: 8, b: 30, l: 50, r: 20}, showlegend: false,
  }, {responsive: true});

  // 成員點火時序表
  let totLast = 0;
  mem.forEach(function(m) { totLast += m.amt[L - 1] || 0; });
  const rows = mem.map(function(m) {
    const s = [];
    for (let t = 0; t < L; t++) s.push(m.amt[t] || 0);
    const ig = anaIgn(s).filter(function(w) { return w >= start; });
    const first = ig.length ? ig[0] : null;
    let streak = 0;
    for (let t = L - 1; t > 0; t--) {
      if ((m.amt[t] || 0) > (m.amt[t - 1] || 0)) streak++; else break;
    }
    const r1 = m.rk[L - 1], r5 = m.rk[L - 5];
    const p = m.label.split(" ");
    const short = p.length >= 3 ? p[1] + p[2] : m.label;
    const chip = (DATA.chip || {})[m.key.split("|")[1]] || {};
    const fB = (chip.f === undefined || (r1 !== undefined && r1 !== null && r1 <= 50)) ? "—"
             : (chip.f >= 80 ? "<span class=\"sig-pass\">" + chip.f + "✓</span>" : "" + chip.f);
    const sB = chip.s === undefined ? "—"
             : (chip.s >= 80 ? "<span class=\"sig-pass\">" + chip.s + "⚡</span>" : "" + chip.s);
    const reso = (DATA.resonance || {})[m.key.split("|")[1]];
    const rB = reso ? "<span class=\"sig-pass\" title=\"" + reso.week + "同週" + reso.n_members
             + "檔同振(" + (reso.weeks_ago === 0 ? "本週" : reso.weeks_ago + "週前") + "),特徵=日線爆量長紅創高+週線同步創高\">🔥"
             + reso.n_members + "檔</span>" : "—";
    return {
      "外資位階": fB, "_f": chip.f === undefined ? -1 : chip.f,
      "券資比位階": sB, "_s": chip.s === undefined ? -1 : chip.s,
      "共振": rB, "_reso": reso ? reso.n_members : -1,
      "成員": "<a href=\"javascript:void(0)\" onclick=\"jumpToCompany('" + m.key + "')\" style=\"color:inherit;border-bottom:1px dotted var(--tx3);text-decoration:none\">" + short + "</a>",
      "_ig": first === null ? 9999 : first,
      "首次點火": first === null ? "—" : dates[first].slice(5),
      "點火次數": ig.length,
      "最新排名": r1 !== undefined ? r1 : null,
      "4週排名Δ": (r1 !== undefined && r5 !== undefined) ? r5 - r1 : null,
      "金額連漲週": streak,
      "佔題材台股%": totLast > 0 ? +((m.amt[L - 1] || 0) / totLast * 100).toFixed(1) : 0,
    };
  });
  rows.sort(function(a, b) { return a._ig - b._ig || b["佔題材台股%"] - a["佔題材台股%"]; });
  if (rows.length && rows[0]._ig < 9999) rows[0]["成員"] = "🐑 " + rows[0]["成員"];
  tableEl._sortState = {colIndex: 1, dir: 1};
  buildTable(tableEl, [
    {key: "成員", label: "成員(點跳單股)"},
    {key: "首次點火", label: "首次點火(範圍內)", sortKey: "_ig", numeric: true},
    {key: "點火次數", label: "點火次數", numeric: true},
    {key: "最新排名", label: "最新排名", numeric: true},
    {key: "4週排名Δ", label: "4週排名Δ", numeric: true},
    {key: "金額連漲週", label: "金額連漲週", numeric: true},
    {key: "佔題材台股%", label: "佔題材台股%", numeric: true},
    {key: "外資位階", label: "外資位階(51名後有效)", sortKey: "_f", numeric: true},
    {key: "券資比位階", label: "券資比位階", sortKey: "_s", numeric: true},
    {key: "共振", label: "共振(8週內,爆量長紅+週線創高)", sortKey: "_reso", numeric: true},
  ], rows);
}

function renderCompanyHistory() {
  if (!histCompanies.length) {
    const key = document.getElementById("companyPick").value;
    if (!key || !DATA.company_history[key]) { Plotly.purge("historyChart"); document.getElementById("historyTable").innerHTML = ""; return; }
    histCompanies.push(key);
    renderCompanyChips();
  }
  const traces = histCompanies.map((k, i) => {
    const e = DATA.company_history[k];
    if (!e) return null;
    return {
      x: e.rows.map(r => DATA.snapshot_dates[r[0]]), y: e.rows.map(r => r[1]),
      mode: "lines+markers", name: e.label,
      line: {color: COMPARE_COLORS[i % COMPARE_COLORS.length], width: 2},
    };
  }).filter(Boolean);
  const single = histCompanies.length === 1 ? DATA.company_history[histCompanies[0]] : null;
  if (single) {
    const px = [], py = [];
    single.rows.forEach(function(r) {
      if (r.length > 4 && r[4] !== null && r[4] !== undefined) {
        px.push(DATA.snapshot_dates[r[0]]);
        py.push(r[4]);
      }
    });
    if (px.length) {
      traces.push({x: px, y: py, mode: "lines", name: "股價(週收盤,右軸)", yaxis: "y2",
                   line: {color: "#d49610", width: 2}});
    }
  }
  Plotly.newPlot("historyChart", traces, {
    title: single ? single.label + " 資金排名 vs 股價" : "多公司排名對比(數字越小越熱)",
    yaxis: {autorange: "reversed", title: "資金排名(左,越小越熱)"},
    yaxis2: {title: "股價", overlaying: "y", side: "right", showgrid: false},
    paper_bgcolor: "#0c1118", plot_bgcolor: "#131c27", font: {color: "#d4dde8"},
    legend: {orientation: "h", y: -0.25},
  }, {responsive: true});
  const lastKey = histCompanies[histCompanies.length - 1];
  const HIST_UNIT = {台: "億元", 日: "億日圓", 韓: "億韓元", 陸: "億人民幣", 美: "億美元"};
  const e2 = DATA.company_history[lastKey];
  const unit = HIST_UNIT[lastKey.split("|")[0]] || "億";
  const dispRows = (e2 ? e2.rows : []).map(function(r) {
    return {
      snapshot_date: DATA.snapshot_dates[r[0]], rank: r[1],
      "金額億": r[2].toLocaleString() + unit,
      "金額億台幣": r[3] === null ? "—" : r[3].toLocaleString() + "億元",
      "金額億台幣_num": r[3],
    };
  });
  const cols = [
    {key: "snapshot_date", label: "日期"}, {key: "rank", label: "排名", numeric: true},
    {key: "金額億", label: "金額(億)"}, {key: "金額億台幣", label: "金額(億台幣)", numeric: true, sortKey: "金額億台幣_num"},
  ];
  buildTable(document.getElementById("historyTable"), cols, dispRows);
  renderCompanyInfo(lastKey);
}

function jumpToCompany(key) {
  if (!DATA.company_history[key]) return;
  switchHistView("company");
  histCompanies = [key];
  document.getElementById("companyPick").value = key;
  document.getElementById("companySearch").value = DATA.company_history[key].label;
  renderCompanyChips();
  renderCompanyHistory();
}

function renderCompanyInfo(key) {
  const el = document.getElementById("companyInfoPanel");
  const info = (DATA.company_info || {})[key];
  if (!info) { el.innerHTML = ""; return; }
  const e = DATA.company_history[key];
  const parts = key.split("|");
  let html = "<div class=\"rule-card\" style=\"margin:10px 0\">";
  html += "<div class=\"rule-item\"><b>" + e.label + "</b>　所屬題材：" +
          (info.g.length ? info.g.map(function(g) {
              const ok = DATA.theme_history && DATA.theme_history[g];
              return "<span class=\"chip\" style=\"padding:1px 8px" + (ok ? ";cursor:pointer;border-bottom:1px dotted var(--tx3)" : "") + "\"" +
                     (ok ? " onclick=\"jumpToRadar('" + g + "')\" title=\"跳動能雷達看題材熱度\"" : " title=\"此題材無熱度序列\"") + ">" + g + "</span>";
            }).join(" ") : "未分類") +
          (info.sub ? "　<span style=\"color:var(--tx3)\" title=\"細分產品=公司層級的產品標籤，非題材分類，無熱度序列可跳(微題材雷達以關鍵字比對這欄)\">細分：" + info.sub + "</span>" : "") + "</div>";
  if (!info.ch.length) {
    html += "<div class=\"rule-item\" style=\"color:var(--tx3);font-size:12px\">此公司不在已建的16條產業鏈中（產業鏈視圖僅涵蓋主要製造業供應鏈）</div>";
  }
  info.ch.forEach(function(cn) {
    const links = (DATA.industry_chains || []).filter(function(l) { return l.chain === cn; });
    html += "<div class=\"rule-item\" style=\"margin-top:8px\"><b>產業鏈：" + cn + "</b>（點成員可切換）</div>";
    ["上游", "中游", "下游"].forEach(function(st) {
      const ms = links.filter(function(l) { return l.stage === st; })
        .sort(function(a, b) { return (a.supplier_rank || 9999) - (b.supplier_rank || 9999); });
      if (!ms.length) return;
      const txt = ms.map(function(l) {
        const k2 = l.supplier_country + "|" + l.supplier_code;
        const label = (COUNTRY_FLAG[l.supplier_country] || "") + (l.supplier_name || l.supplier_code) + (l.supplier_rank ? "#" + l.supplier_rank : "");
        if (l.supplier_country === parts[0] && l.supplier_code === parts[1]) {
          return "<b style=\"color:var(--ac)\">▶" + label + "</b>";
        }
        if (DATA.company_history[k2]) {
          return "<a href=\"javascript:void(0)\" onclick=\"jumpToCompany('" + k2 + "')\" style=\"color:var(--tx2);text-decoration:none;border-bottom:1px dotted var(--tx3)\">" + label + "</a>";
        }
        return "<span style=\"color:var(--tx3)\">" + label + "</span>";
      }).join("　");
      html += "<div class=\"rule-item\" style=\"font-size:12px;line-height:2\">" + st + "：" + txt + "</div>";
    });
  });
  const mentions = (DATA.company_mentions || {})[key] || [];
  if (mentions.length) {
    html += "<div class=\"rule-item\" style=\"margin-top:8px\"><b>📝 曾被法說會提及／影射</b></div>";
    mentions.slice().reverse().forEach(function(m) {
      const rx = (m.r1 !== undefined || m.r5 !== undefined)
        ? " → T+1 " + fmtPct(m.r1) + " / T+5 " + fmtPct(m.r5)
        : "";
      html += "<div class=\"rule-item\" style=\"font-size:12px;line-height:1.7\">" + m.date + " " +
        "<a href=\"javascript:void(0)\" onclick=\"jumpToConfNote('" + m.from_file + "')\" " +
        "style=\"color:var(--tx2);text-decoration:none;border-bottom:1px dotted var(--tx3)\">《" + m.from_title + "》</a>" +
        "：" + m.reason + "<span style=\"color:var(--tx3)\">" + rx + "</span></div>";
    });
  }
  html += "</div>";
  el.innerHTML = html;
}

function fmtPct(v) {
  if (v === undefined || v === null) return "—";
  return (v > 0 ? "+" : "") + v.toFixed(1) + "%";
}

function onHistModeChange() {
  const mode = document.querySelector('input[name="histMode"]:checked').value;
  document.getElementById("companyPickWrap").style.display = mode === "company" ? "" : "none";
  document.getElementById("themeHistPickWrap").style.display = mode === "theme" ? "" : "none";
  if (mode === "company") renderCompanyHistory(); else renderThemeHistory();
}

function renderThemeHistory() {
  document.getElementById("companyInfoPanel").innerHTML = "";
  const g = document.getElementById("themeHistPick").value;
  const rows = DATA.theme_history[g] || [];
  Plotly.newPlot("historyChart", [{
    x: rows.map(r => r.snapshot_date), y: rows.map(r => r["熱度分數"]), mode: "lines+markers", line: {color: "#ff8c4d"},
  }], {
    title: g + " 熱度分數變化(數字越大資金越集中)",
    yaxis: {title: "熱度分數"},
    paper_bgcolor: "#0c1118", plot_bgcolor: "#131c27", font: {color: "#d4dde8"},
  }, {responsive: true});
  const cols = [
    {key: "snapshot_date", label: "日期"}, {key: "熱度分數", label: "熱度分數", numeric: true},
    {key: "金額合計億台幣", label: "金額合計(億台幣)", numeric: true},
  ];
  buildTable(document.getElementById("historyTable"), cols, rows);
}

function daysUntil(dateStr) {
  const d = new Date(dateStr + "T00:00:00");
  const today = new Date(); today.setHours(0, 0, 0, 0);
  return Math.round((d - today) / 86400000);
}

function earningsTierClass(dateStr) {
  const n = daysUntil(dateStr);
  if (n <= 3) return "tier-hot";
  if (n <= 7) return "tier-mid";
  return "";
}

function capBadge(capStr) {
  // 2026-07-23: 美股一天跳出好幾十檔財報,用市值標重量級,不用逐行看市值欄找哪間牽動大盤
  const n = parseFloat(String(capStr || "").replace(/[$,]/g, ""));
  if (!n || isNaN(n)) return "";
  if (n >= 3e11) return "⭐ ";
  if (n >= 1e11) return "🔹 ";
  return "";
}

function rankBadge(rank) {
  // 台/日韓陸沒有市值欄,用「成交金額排名」(該市場前100-300大清單裡的名次)近似重量級,同樣零額外抓取成本
  const n = parseFloat(rank);
  if (!n || isNaN(n)) return "";
  if (n <= 20) return "⭐ ";
  if (n <= 50) return "🔹 ";
  return "";
}

function importanceBadge(r, ctry) {
  return ctry === "美" ? capBadge(r["市值"]) : rankBadge(r["成交金額排名"]);
}

function linkifyEarn(rows, ctry) {
  // 公司名可點 -> 公司歷史頁(題材chips+產業鏈上中下游成員, 一眼看懂這家是誰)
  return (rows || []).map(function(r) {
    const c = String(r["代碼"] || "").trim();
    const key = (ctry || r["市場"] || "") + "|" + c;
    const badge = importanceBadge(r, ctry);
    let name = r["公司"] || "";
    if (c && DATA.company_history && DATA.company_history[key] && name) {
      name = "<a href=\"javascript:void(0)\" onclick=\"jumpToCompany('" + key + "');showTab(2)\" style=\"color:inherit;border-bottom:1px dotted var(--tx3);text-decoration:none\">" + name + "</a>";
    }
    if (badge || name !== (r["公司"] || "")) {
      const o = Object.assign({}, r);
      o["公司"] = badge + name;
      return o;
    }
    return r;
  });
}

function mtimeLabel(mtime) {
  // 2026-07-22: 財報查詢快照太久沒重跑會靜默失效(GOOGL財報日案例),超過7天亮警示提醒重跑check_earnings.py
  if (!mtime) return "(尚未查詢過)";
  const m = mtime.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!m) return `(最後查詢: ${mtime})`;
  const queried = new Date(+m[1], +m[2] - 1, +m[3]);
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const staleDays = Math.round((today - queried) / 86400000);
  if (staleDays > 7) {
    return `<span style="color:#ff6b6b;font-weight:bold">⚠ 最後查詢: ${mtime}(已 ${staleDays} 天沒更新，請重跑 check_earnings.py)</span>`;
  }
  return `(最後查詢: ${mtime})`;
}

function renderEarningsTab() {
  document.getElementById("usEarningsMtime").innerHTML = mtimeLabel(DATA.us_earnings.mtime);
  document.getElementById("twEarningsMtime").innerHTML = mtimeLabel(DATA.tw_earnings.mtime);

  const usCols = [
    {key: "日期", label: "日期"}, {key: "時段", label: "時段"}, {key: "代碼", label: "代碼"},
    {key: "公司", label: "公司"}, {key: "成交金額排名", label: "排名", numeric: true},
    {key: "主族群", label: "主族群"}, {key: "市值", label: "市值"}, {key: "EPS預估", label: "EPS預估"},
  ];
  buildTable(document.getElementById("usEarningsTable"), usCols, linkifyEarn(DATA.us_earnings.rows, "美"), r => earningsTierClass(r["日期"]));

  const twCols = [
    {key: "日期", label: "日期"}, {key: "時間", label: "時間"}, {key: "代碼", label: "代碼"},
    {key: "公司", label: "公司"}, {key: "成交金額排名", label: "排名", numeric: true}, {key: "主族群", label: "主族群"},
  ];
  buildTable(document.getElementById("twEarningsTable"), twCols, linkifyEarn(DATA.tw_earnings.rows, "台"), r => earningsTierClass(r["日期"]));

  const jpkr = DATA.jpkr_earnings || {rows: []};
  document.getElementById("jpkrEarningsMtime").innerHTML = mtimeLabel(jpkr.mtime);
  const jpkrCols = [
    {key: "日期", label: "日期"}, {key: "市場", label: "市場"}, {key: "代碼", label: "代碼"},
    {key: "公司", label: "公司"}, {key: "成交金額排名", label: "排名", numeric: true}, {key: "主族群", label: "主族群"},
  ];
  buildTable(document.getElementById("jpkrEarningsTable"), jpkrCols, linkifyEarn(jpkr.rows, null), r => earningsTierClass(r["日期"]));

  // 初始化日曆：顯示當月
  const _now = new Date();
  renderCalendar(_now.getFullYear(), _now.getMonth());
  renderExpoWatch();
}

function renderExpoWatch() {
  const el = document.getElementById("expoWatchPanel");
  const entries = Object.values(DATA.expo_calendar || {});
  if (!entries.length) { el.innerHTML = ""; return; }
  let html = "";
  entries.forEach(function(expo) {
    const upcoming = expo.dates.filter(function(dr) { return daysUntil(dr.end) >= 0; })
                                .sort(function(a, b) { return daysUntil(a.start) - daysUntil(b.start); })[0];
    if (!upcoming) return;
    const n1 = daysUntil(upcoming.window_open), n2 = daysUntil(upcoming.start), n3 = daysUntil(upcoming.end);
    const active = n1 <= 0 && n3 >= 0;
    const statusTxt = active ? (n2 > 0 ? ("🔥 觀察窗已開，倒數" + n2 + "天") : "🔥 展覽進行中")
                              : ("觀察窗將於" + upcoming.window_open + "開啟(還有" + Math.max(n1, 0) + "天)");
    const watchRows = expo.watchlist.map(function(w) {
      const key = "台|" + w.code;
      const hasHist = DATA.company_history && DATA.company_history[key];
      const nameHtml = hasHist
        ? "<a href=\"javascript:void(0)\" onclick=\"jumpToCompany('" + key + "');showTab(2)\" style=\"color:inherit;border-bottom:1px dotted var(--tx3);text-decoration:none\">" + w.name + "</a>"
        : w.name;
      return "<tr><td>" + w.code + " " + nameHtml + "</td><td>" + w.hits.join("、") + "</td></tr>";
    }).join("");
    html += "<div class=\"expo-watch-card" + (active ? " active" : "") + "\">" +
            "<b>" + expo.label + "</b>　" + upcoming.start + " ~ " + upcoming.end + "　" + statusTxt +
            "<table class=\"expo-watch-table\"><tr><th>常客股</th><th>歷年展前報酬(20/40日窗)</th></tr>" + watchRows + "</table></div>";
  });
  el.innerHTML = html;
}

// ── 法說會日曆 ──────────────────────────────────────────────
let calYear = 0, calMonth = 0;
const WEEKDAYS = ["日","一","二","三","四","五","六"];
const MONTHS_ZH = ["1月","2月","3月","4月","5月","6月","7月","8月","9月","10月","11月","12月"];

function buildEvtMap() {
  const m = {};
  (DATA.tw_earnings.rows || []).forEach(r => {
    const d = r["日期"]; if (!d) return;
    if (!m[d]) m[d] = [];
    m[d].push({label: importanceBadge(r, "台") + r["代碼"] + " " + r["公司"], market: "tw", date: d});
  });
  (DATA.us_earnings.rows || []).forEach(r => {
    const d = r["日期"]; if (!d) return;
    if (!m[d]) m[d] = [];
    m[d].push({label: importanceBadge(r, "美") + r["代碼"], market: "us", date: d});
  });
  ((DATA.jpkr_earnings || {}).rows || []).forEach(r => {
    const d = r["日期"]; if (!d) return;
    if (!m[d]) m[d] = [];
    m[d].push({label: importanceBadge(r, r["市場"]) + r["市場"] + " " + (r["公司"] || r["代碼"]), market: "jpkr", date: d});
  });
  Object.values(DATA.expo_calendar || {}).forEach(expo => {
    expo.dates.forEach(dr => {
      if (!m[dr.start]) m[dr.start] = [];
      m[dr.start].push({label: "🎪 " + expo.label, market: "expo", date: dr.start});
    });
  });
  return m;
}

function renderCalendar(year, month) {
  calYear = year; calMonth = month;
  document.getElementById("calTitle").textContent = year + "年" + MONTHS_ZH[month];
  const evtMap = buildEvtMap();
  const todayStr = new Date().toISOString().slice(0,10);
  const grid = document.getElementById("calGrid");
  grid.innerHTML = "";

  // 標頭
  WEEKDAYS.forEach((h,i) => {
    const el = document.createElement("div");
    el.className = "cal-head" + (i===0?" sun":i===6?" sat":"");
    el.textContent = h; grid.appendChild(el);
  });

  const firstDow = new Date(year, month, 1).getDay();
  const lastDate = new Date(year, month+1, 0).getDate();
  const prevLast = new Date(year, month, 0).getDate();

  // 上個月尾巴
  for (let i = 0; i < firstDow; i++) {
    const cell = document.createElement("div");
    cell.className = "cal-cell out";
    cell.innerHTML = `<div class="cal-num">${prevLast - firstDow + 1 + i}</div>`;
    grid.appendChild(cell);
  }

  // 本月
  for (let d = 1; d <= lastDate; d++) {
    const dow = (firstDow + d - 1) % 7;
    const dateStr = `${year}-${String(month+1).padStart(2,"0")}-${String(d).padStart(2,"0")}`;
    const evts = evtMap[dateStr] || [];
    const isToday = dateStr === todayStr;
    const cell = document.createElement("div");
    cell.className = "cal-cell" + (isToday?" today":"") + (evts.length?" has-event":"");
    const numCls = dow===0?" sun":dow===6?" sat":"";
    let html = `<div class="cal-num${numCls}">${d}</div>`;
    evts.forEach(ev => {
      const n = daysUntil(ev.date);
      const fire = (n >= 0 && n <= 3) ? " fire" : "";
      html += `<div class="cal-evt ${ev.market}${fire}" title="${ev.label}">${ev.label}</div>`;
    });
    cell.innerHTML = html;
    grid.appendChild(cell);
  }

  // 下個月頭
  const trailing = (7 - ((firstDow + lastDate) % 7)) % 7;
  for (let d = 1; d <= trailing; d++) {
    const cell = document.createElement("div");
    cell.className = "cal-cell out";
    cell.innerHTML = `<div class="cal-num">${d}</div>`;
    grid.appendChild(cell);
  }
}

function calMove(delta) {
  calMonth += delta;
  if (calMonth < 0) { calMonth = 11; calYear--; }
  if (calMonth > 11) { calMonth = 0; calYear++; }
  renderCalendar(calYear, calMonth);
}

function renderNewsTable() {
  const groupSel = document.getElementById("newsGroupFilter");
  const typeSel = document.getElementById("newsTypeFilter");
  const selectedGroups = Array.from(groupSel.selectedOptions).map(o => o.value);
  const selectedTypes = Array.from(typeSel.selectedOptions).map(o => o.value);
  let rows = DATA.theme_news.slice();
  if (selectedGroups.length) rows = rows.filter(r => selectedGroups.indexOf(r["主族群"]) >= 0);
  if (selectedTypes.length) rows = rows.filter(r => selectedTypes.indexOf(r["類型"]) >= 0);
  rows.sort((a, b) => String(b["日期"]).localeCompare(String(a["日期"])));
  const cols = [
    {key: "主族群", label: "主族群"}, {key: "類型", label: "類型"}, {key: "日期", label: "日期"},
    {key: "標題", label: "標題"}, {key: "來源", label: "來源"}, {key: "連結", label: "連結", isLink: true},
    {key: "重點摘要", label: "重點摘要"}, {key: "相關公司", label: "相關公司"},
  ];
  buildTable(document.getElementById("newsTable"), cols, rows);
}

// ── 供應鏈頁籤 ────────────────────────────────────────────────────────
const ANCHOR_DEFS = {
  "NVDA":    {label:"NVIDIA",          codes:["NVDA"]},
  "CLOUD":   {label:"雲端三巨頭",       codes:["MSFT","GOOGL","AMZN"]},
  "AAPL":    {label:"Apple",           codes:["AAPL"]},
  "TSLA":    {label:"Tesla",           codes:["TSLA"]},
  "TSMC":    {label:"台積電(上游)",     codes:["2330"]},
  "HK_AUTO": {label:"現代起亞",        codes:["005380","000270"]},
  "KR_MEM":  {label:"三星/SK海力士",   codes:["005930","000660"]},
  "BABA":    {label:"阿里巴巴",        codes:["BABA"]},
  "TENCENT": {label:"騰訊",            codes:["TENCENT"]},
  "HUAWEI":  {label:"華為",            codes:["HUAWEI"]},
};
const COUNTRY_FLAG = {台:"🇹🇼", 日:"🇯🇵", 韓:"🇰🇷", 陸:"🇨🇳", 美:"🇺🇸", 港:"🇭🇰"};
const SC_COUNTRIES = ["台","日","韓","陸","美"];
let scCurrentAnchor = "NVDA";

function selectAnchor(key) {
  scCurrentAnchor = key;
  document.querySelectorAll(".anchor-btn").forEach(function(b) {
    b.classList.toggle("active", b.getAttribute("onclick") === "selectAnchor('" + key + "')");
  });
  renderSCRanking();
  renderSCCards();
}

function buildCardHTML(l, showCountry) {
  const tier = l.supplier_tier || "";
  let badgeCls = "b-edge", cardCls = "";
  if (tier.indexOf("前50") >= 0)  { badgeCls = "b-hot";  cardCls = "card-hot"; }
  else if (tier.indexOf("51-150") >= 0) { badgeCls = "b-mid"; cardCls = "card-mid"; }
  const rankText = l.supplier_rank ? "#" + l.supplier_rank : "未上榜";
  const badgeClass2 = l.supplier_rank ? badgeCls : "b-none";
  const d = l.supplier_rank_delta;
  let deltaHtml = "";
  if (l.supplier_rank && d !== null && d !== undefined) {
    if (d > 0) deltaHtml = "<span class=\"sc-delta up\" title=\"排名比上週上升" + d + "名\">▲" + d + "</span>";
    else if (d < 0) deltaHtml = "<span class=\"sc-delta down\" title=\"排名比上週下降" + (-d) + "名\">▼" + (-d) + "</span>";
    else deltaHtml = "<span class=\"sc-delta flat\">—</span>";
  }
  const countryHtml = showCountry ? "<span class=\"sc-code\">" + (COUNTRY_FLAG[l.supplier_country] || "") + l.supplier_country + "</span>" : "";
  const posText = (l.position_note || "") + "|" + (l.product || "");
  let posBadge = "";
  if (/世界第一|全球第一|絕對霸主|絕對龍頭|獨家|壟斷|絕對巨頭|市佔第一|出貨量第一|全球最大/.test(posText)) posBadge = "<span class=\"pos-badge crown\">👑 全球第一</span>";
  else if (/第二大|第三大|前三大|前兩大|全球前三|雙雄/.test(posText)) posBadge = "<span class=\"pos-badge silver\">🥈 全球前三</span>";
  else if (/龍頭|霸主|巨頭|世界級/.test(posText)) posBadge = "<span class=\"pos-badge star\">⭐ 龍頭</span>";
  const tooltip = l.position_note ? " title=\"" + l.position_note.replace(/"/g, "&quot;") + "\"" : "";
  return "<div class=\"sc-card " + cardCls + "\"" + tooltip + ">" +
         "<div class=\"sc-card-header\"><span class=\"rank-badge " + badgeClass2 + "\">" + rankText + "</span>" +
         deltaHtml + countryHtml +
         "<span class=\"sc-code\">" + l.supplier_code + "</span></div>" +
         "<div class=\"sc-name\">" + (l.supplier_name || l.supplier_code) + posBadge + "</div>" +
         "<div class=\"sc-product\">&#9658; " + l.product + "</div>" +
         (l.supplier_amount_yi ? "<div class=\"sc-amount\">" + l.supplier_amount_yi + "</div>" : "") +
         buildFundHTML(l) +
         "</div>";
}

function buildFundHTML(l) {
  const line1 = [], line2 = [];
  if (l.gross_margin !== null && l.gross_margin !== undefined) line1.push("毛利 " + l.gross_margin + "%");
  if (l.revenue_growth !== null && l.revenue_growth !== undefined) {
    const cls = l.revenue_growth >= 0 ? "fund-up" : "fund-down";
    line1.push("季營收YoY<span class=\"" + cls + "\">" + (l.revenue_growth >= 0 ? "+" : "") + l.revenue_growth + "%</span>");
  }
  if (l.pb !== null && l.pb !== undefined) line2.push("PB " + l.pb);
  if (l.eps_ttm !== null && l.eps_ttm !== undefined && l.eps_fwd !== null && l.eps_fwd !== undefined) {
    let label = "", cls = "fund-up";
    if (l.eps_ttm <= 0 && l.eps_fwd > 0) label = "EPS轉盈↗";
    else if (l.eps_ttm <= 0) { label = "EPS預估仍虧"; cls = "fund-down"; }
    else {
      const g = Math.round((l.eps_fwd / l.eps_ttm - 1) * 100);
      if (g >= 5) label = "EPS預估↗+" + g + "%";
      else if (g <= -5) { label = "EPS預估↘" + g + "%"; cls = "fund-down"; }
      else { label = "EPS預估→持平"; cls = ""; }
    }
    line2.push(cls ? "<span class=\"" + cls + "\">" + label + "</span>" : label);
  }
  let html = "";
  if (line1.length) html += "<div class=\"sc-fund\">" + line1.join("｜") + "</div>";
  if (line2.length) html += "<div class=\"sc-fund\">" + line2.join("｜") + "</div>";
  if (l.cn_note) html += "<div class=\"sc-fund\" style=\"color:var(--amb)\">" + l.cn_note + "</div>";
  if (l.capex_note) html += "<div class=\"sc-fund\" style=\"color:var(--amb)\" title=\"近幾季capex(原幣): " + (l.capex_hist || "") + "\">" + l.capex_note + "</div>";
  return html;
}

// ── 產業鏈視圖(上中下游) ─────────────────────────────────────────────
let scView = "anchor";
let currentChain = null;
let chainCountry = "全部";

function selectChainCountry(c) {
  chainCountry = c;
  renderChainView();
}

function switchSCView(v) {
  scView = v;
  document.getElementById("scAnchorView").style.display = v === "anchor" ? "" : "none";
  document.getElementById("scChainView").style.display = v === "chain" ? "" : "none";
  document.getElementById("viewAnchorBtn").classList.toggle("active", v === "anchor");
  document.getElementById("viewChainBtn").classList.toggle("active", v === "chain");
  if (v === "chain") renderChainView();
}

function selectChain(c) {
  currentChain = c;
  renderChainView();
}

function renderChainRanking() {
  const el = document.getElementById("chainRanking");
  const ch = DATA.chain_history || {};
  const chains = Object.keys(ch);
  if (!chains.length) { el.innerHTML = ""; return; }
  const twCnt = {};
  (DATA.industry_chains || []).forEach(function(l) {
    if (l.supplier_country === "台") {
      twCnt[l.chain] = twCnt[l.chain] || {};
      twCnt[l.chain][l.supplier_code] = 1;
    }
  });
  const rows = chains.map(function(c) {
    const s = ch[c], L = s.length;
    const cur = s[L - 1] || 0;
    return {c: c, cur: cur,
            d1: L > 1 ? cur - s[L - 2] : 0,
            d4: L > 4 ? cur - s[L - 5] : 0,
            tw: Object.keys(twCnt[c] || {}).length};
  });
  rows.sort(function(a, b) { return b.cur - a.cur; });
  const mx = Math.max.apply(null, rows.map(function(r) { return r.cur; }).concat([0.01]));
  function arr(d) {
    if (d > 0.05) return "<span style=\"color:var(--red)\">▲" + d.toFixed(1) + "</span>";
    if (d < -0.05) return "<span style=\"color:var(--grn)\">▼" + (-d).toFixed(1) + "</span>";
    return "<span style=\"color:var(--tx3)\">—</span>";
  }
  el.innerHTML = rows.map(function(r, i) {
    const pct = Math.round(r.cur / mx * 100);
    return "<div class=\"scr-row" + (r.c === currentChain ? " active" : "") + "\" onclick=\"selectChain('" + r.c + "')\">" +
      "<span class=\"scr-rank\">" + (i + 1) + "</span>" +
      "<span class=\"scr-label\">" + r.c + "</span>" +
      "<span class=\"scr-bar-wrap\"><span class=\"scr-bar\" style=\"width:" + pct + "%\"></span></span>" +
      "<span class=\"scr-stats\">" + r.cur.toFixed(1) + "分 週" + arr(r.d1) + " 月" + arr(r.d4) + " · 台" + r.tw + "家</span></div>";
  }).join("");
}

function renderChainView() {
  const chains = DATA.industry_chain_list || [];
  const btnsEl = document.getElementById("chainBtns");
  const stagesEl = document.getElementById("chainStages");
  if (!chains.length) {
    btnsEl.innerHTML = "";
    stagesEl.innerHTML = "<div class=\"hint\">尚無產業鏈資料</div>";
    return;
  }
  if (!currentChain || chains.indexOf(currentChain) < 0) currentChain = chains[0];
  renderChainRanking();
  btnsEl.innerHTML = chains.map(function(c) {
    return "<button class=\"anchor-btn" + (c === currentChain ? " active" : "") + "\" onclick=\"selectChain('" + c + "')\">" + c + "</button>";
  }).join("");
  const links = (DATA.industry_chains || []).filter(function(l) { return l.chain === currentChain; });
  // 國別篩選鈕(附家數)；換鏈後若原國別無成員則退回全部
  const cCnt = {全部: links.length};
  links.forEach(function(l) { cCnt[l.supplier_country] = (cCnt[l.supplier_country] || 0) + 1; });
  if (!cCnt[chainCountry]) chainCountry = "全部";
  document.getElementById("chainCountryBtns").innerHTML = ["全部", "台", "美", "日", "韓", "陸"]
    .filter(function(c) { return cCnt[c]; })
    .map(function(c) {
      return "<button class=\"anchor-btn" + (c === chainCountry ? " active" : "") + "\" onclick=\"selectChainCountry('" + c + "')\">" + c + "(" + cCnt[c] + ")</button>";
    }).join("");
  const onlyRanked = document.getElementById("chainOnlyRanked").checked;
  const stages = ["上游", "中游", "下游"];
  const stageIcons = {上游: "⛏️", 中游: "🏭", 下游: "📦"};
  let html = "";
  stages.forEach(function(st) {
    let items = links.filter(function(l) { return l.stage === st; });
    if (chainCountry !== "全部") items = items.filter(function(l) { return l.supplier_country === chainCountry; });
    if (onlyRanked) items = items.filter(function(l) { return l.supplier_rank; });
    if (!items.length) return;
    items.sort(function(a, b) { return (a.supplier_rank || 9999) - (b.supplier_rank || 9999); });
    const hot = items.filter(function(l) { return (l.supplier_tier || "").indexOf("前50") >= 0; }).length;
    html += "<div class=\"stage-col\"><div class=\"stage-head\">" + stageIcons[st] + " " + st +
            "<span class=\"stage-meta\">" + items.length + "家" + (hot ? " · 🔥" + hot : "") + "</span></div>" +
            "<div class=\"stage-cards\">";
    items.forEach(function(l) { html += buildCardHTML(l, true); });
    html += "</div></div>";
  });
  stagesEl.innerHTML = html;
}

function renderSCRanking() {
  const rows = Object.keys(ANCHOR_DEFS).map(function(key) {
    const def = ANCHOR_DEFS[key];
    const links = (DATA.supply_links || []).filter(function(l) { return def.codes.indexOf(l.customer_code) >= 0; });
    const hot = links.filter(function(l) { return (l.supplier_tier || "").indexOf("前50") >= 0; }).length;
    const mid = links.filter(function(l) { return (l.supplier_tier || "").indexOf("51-150") >= 0; }).length;
    const up = links.filter(function(l) { return (l.supplier_rank_delta || 0) > 0; }).length;
    const down = links.filter(function(l) { return (l.supplier_rank_delta || 0) < 0; }).length;
    return {key: key, label: def.label, n: links.length, hot: hot, mid: mid, score: hot * 2 + mid, up: up, down: down};
  }).filter(function(r) { return r.n > 0; });
  rows.sort(function(a, b) { return b.score - a.score || b.hot - a.hot; });
  const maxScore = Math.max.apply(null, rows.map(function(r) { return r.score; }).concat([1]));
  let html = "";
  rows.forEach(function(r, i) {
    const pct = Math.round(r.score / maxScore * 100);
    html += "<div class=\"scr-row" + (r.key === scCurrentAnchor ? " active" : "") + "\" onclick=\"selectAnchor('" + r.key + "')\">" +
      "<span class=\"scr-rank\">" + (i + 1) + "</span>" +
      "<span class=\"scr-label\">" + r.label + "</span>" +
      "<span class=\"scr-bar-wrap\"><span class=\"scr-bar\" style=\"width:" + pct + "%\"></span></span>" +
      "<span class=\"scr-stats\">🔥" + r.hot + " 🟠" + r.mid + " / " + r.n + "家" +
      (r.up || r.down ? "<span class=\"scr-updown\">▲" + r.up + " ▼" + r.down + "</span>" : "") + "</span>" +
      "</div>";
  });
  document.getElementById("scRanking").innerHTML = html;
}

const CCY = {美: "USD", 台: "TWD", 韓: "KRW", 日: "JPY", 陸: "CNY"};

function renderAnchorCapex() {
  const el = document.getElementById("anchorCapexStrip");
  const def = ANCHOR_DEFS[scCurrentAnchor];
  const cm = DATA.capex_map || {};
  const byCode = {};
  Object.keys(cm).forEach(function(k) {
    const p = k.split("|");
    byCode[p[1]] = {e: cm[k], c: p[0]};
  });
  const parts = [];
  ((def && def.codes) || []).forEach(function(code) {
    const x = byCode[code];
    if (!x) return;
    const cls = x.e.chg >= 0 ? "fund-up" : "fund-down";
    parts.push("<span title=\"近幾季capex(原幣): " + x.e.h + "\"><b>" + code + "</b> " + x.e.cur + " " + (CCY[x.c] || "") +
               " <span class=\"" + cls + "\">" + (x.e.chg >= 0 ? "+" : "") + x.e.chg + "%</span></span>");
  });
  el.innerHTML = parts.length
    ? "🏗️ <b>資本開支引擎</b>(最新季/YoY，客戶capex領先供應商營收2~4季)：" + parts.join("　·　")
    : "";
}

function renderSCCards() {
  const def = ANCHOR_DEFS[scCurrentAnchor];
  if (!def) return;
  renderAnchorCapex();
  const links = (DATA.supply_links || []).filter(function(l) { return def.codes.indexOf(l.customer_code) >= 0; });

  // Group by supplier country
  const byCountry = {};
  SC_COUNTRIES.forEach(function(c) { byCountry[c] = []; });
  links.forEach(function(l) {
    if (!byCountry[l.supplier_country]) byCountry[l.supplier_country] = [];
    byCountry[l.supplier_country].push(l);
  });

  // Country summary bar
  let barHtml = "";
  SC_COUNTRIES.forEach(function(c) {
    const items = byCountry[c];
    if (!items.length) return;
    const hot = items.filter(function(l) { return l.supplier_tier && l.supplier_tier.indexOf("前50") >= 0; }).length;
    barHtml += "<span class=\"sc-country-chip\">" + (COUNTRY_FLAG[c]||c) + " " + c + " <b>" + items.length + "家</b>" +
               (hot > 0 ? " <span class=\"chip-hot\">🔥" + hot + "</span>" : "") + "</span>";
  });
  document.getElementById("scCountryBar").innerHTML = "<div class=\"sc-country-bar\">" + barHtml + "</div>";

  // Cards
  let html = "";
  SC_COUNTRIES.forEach(function(c) {
    const items = byCountry[c];
    if (!items.length) return;
    items.sort(function(a, b) { return (a.supplier_rank || 9999) - (b.supplier_rank || 9999); });
    html += "<div class=\"sc-country-section\"><div class=\"sc-country-title\">" +
            (COUNTRY_FLAG[c]||c) + " " + c + "股供應商（" + items.length + "家）</div><div class=\"sc-cards-row\">";
    items.forEach(function(l) { html += buildCardHTML(l, false); });
    html += "</div></div>";
  });
  if (!html) html = "<div style=\"color:#888;padding:16px;\">此錨點暫無供應商資料</div>";
  document.getElementById("scCards").innerHTML = html;
}

function initSupplyChain() {
  const lu = DATA.supply_last_updated || "";
  if (lu) {
    const els = document.querySelectorAll("#scLastUpdated, #scLastUpdatedInline");
    els.forEach(function(el) { el.textContent = lu; });
    const days = Math.floor((new Date(DATA.latest_date) - new Date(lu)) / 86400000);
    if (days > 90) document.getElementById("scFreshWarn").style.display = "block";
  } else {
    document.getElementById("scLastUpdatedInline").textContent = "—";
  }
  renderSCRanking();
  renderSCCards();
}

// ── 本週摘要橫幅 ──────────────────────────────────────────────────────
function renderBanner() {
  const s = DATA.weekly_summary || {};
  const parts = [];
  if (s.up) parts.push("本週最熱 <b class=\"wb-up\">" + s.up.g + " +" + s.up.d.toFixed(2) + "</b>");
  if (s.down) parts.push("最退潮 <b class=\"wb-down\">" + s.down.g + " " + s.down.d.toFixed(2) + "</b>");
  if (s.new_count) parts.push("新進榜 <b>" + s.new_count + "</b> 檔");
  const sigs = (DATA.signal_current || []).filter(function(c) { return c.verdict; });
  if (sigs.length) {
    parts.push("🔔 進場訊號 <b class=\"wb-up\">" + sigs.map(function(c) { return themeLink(c.theme) + (c.pat ? "✓" : ""); }).join("、") + "</b>");
  }
  const mic = (DATA.micro_current || []).filter(function(c) { return c.level; });
  if (mic.length) {
    parts.push("🔔 微題材脈衝 <b class=\"wb-up\">" + mic.map(function(c) { return c.theme + (c.level.indexOf("🅰") >= 0 ? "🅰" : "🅱") + (c.second ? "⚠" : ""); }).join("、") + "</b>");
  }
  Object.values(DATA.expo_calendar || {}).forEach(function(expo) {
    const active = expo.dates.find(function(dr) {
      const n1 = daysUntil(dr.window_open), n2 = daysUntil(dr.end);
      return n1 <= 0 && n2 >= 0;
    });
    if (!active) return;
    const n = daysUntil(active.start);
    const names = expo.watchlist.map(function(w) { return w.name; }).join("、");
    const statusTxt = n > 0 ? ("倒數約" + n + "天") : "展覽進行中";
    parts.push("🎪 <a href=\"javascript:void(0)\" onclick=\"showTab(3)\" class=\"wb-up\">" + expo.label +
               statusTxt + "，觀察窗已開，常客：" + names + "</a>");
  });
  if (!parts.length) return;
  const el = document.getElementById("weeklyBanner");
  el.innerHTML = "📌 " + parts.join("<span class=\"wb-sep\"> · </span>");
  el.style.display = "flex";
}

// ── 進場訊號頁籤 ──────────────────────────────────────────────────────
function switchSigView(v) {
  ["Macro", "Micro", "Catchup", "Revmom", "Dispo", "Reso", "Thermo", "Pledge"].forEach(function(k) {
    const on = v === k.toLowerCase();
    document.getElementById("sigView" + k + "Btn").classList.toggle("active", on);
    document.getElementById("sig" + k + "View").style.display = on ? "" : "none";
  });
}

// ── 法說會筆記(2026-07-19上板) ────────────────────────────────────
function renderConfNotes() {
  const el = document.getElementById("confNotesPanel");
  if (!el) return;
  const notes = DATA.conf_notes || [];
  if (!notes.length) {
    el.innerHTML = "<div class=\"hint\">尚無筆記。</div>";
    return;
  }
  el.innerHTML = notes.map(function(n, i) {
    return "<details class=\"conf-note\" id=\"confNote_" + n.file + "\"" + (i === 0 ? " open" : "") +
      "><summary><b>" + n.title + "</b></summary><div class=\"cn-body\">" + n.html + "</div></details>";
  }).join("");
}

function jumpToConfNote(file) {
  showTab(3);
  setTimeout(function() {
    const d = document.getElementById("confNote_" + file);
    if (!d) return;
    d.open = true;
    d.scrollIntoView({behavior: "smooth", block: "start"});
  }, 50);
}

// ── 大盤溫度計(2026-07-19上板): 市場層五燈+頁頂燈條 ─────────────────
function renderThermoTab() {
  const mt = DATA.market_thermo;
  if (!mt) return;
  const cardsEl = document.getElementById("thermoCards");
  const pill = function(lit) {
    return lit ? "<span style=\"color:var(--red);font-weight:700\">● 亮</span>"
               : "<span style=\"color:var(--tx3)\">○ 滅</span>";
  };
  const cards = [
    {name: "🌡️ 恐慌溫度計", lit: mt.thermo.lit,
     read: "今日甜蜜格並發 <b>" + mt.thermo.today + "</b>（門檻20／p99≈45／史max 77）" +
           (mt.thermo.last ? "<br>最近觸發 " + mt.thermo.last + (mt.thermo.lit ? "，窗剩 " + mt.thermo.remain + " 交易日" : "") : "<br>60日內無觸發"),
     verdict: "≥20＝史冊級出清日（8/8命中）。k20 +4.93%/86%、k60 +14.21%/83%。持有60日。",
     warn: "死格＝2022-06慢熊中段。"},
    {name: "🌏 亞跌B訊號", lit: mt.b.lit,
     read: "最新交易日：N225 " + (mt.b.n225 === null ? "休市" : mt.b.n225 + "%") +
           "｜KOSPI " + (mt.b.kospi === null ? "休市" : mt.b.kospi + "%") +
           "｜SPX前夜 " + (mt.b.us === null ? "—" : mt.b.us + "%") +
           (mt.b.last ? "<br>最近B日 " + mt.b.last + (mt.b.lit ? "，窗剩 " + mt.b.remain + " 交易日" : "") : "<br>10日內無B日"),
     verdict: "日韓≤−2%×美前夜>−1%＝美國沒事的亞洲賣壓。k10 +3.12%/78%。持有10日。",
     warn: "8-10月觸發＝吃短；美亞同跌(A型)別接。"},
    {name: "📉 位階雙收斂", lit: mt.conv.lit,
     read: "台dd250 <b>" + mt.conv.dd250 + "%</b>｜當日 " + mt.conv.ret1 + "%｜10日 " + mt.conv.drop10 + "%" +
           (mt.conv.lit ? "<br>窗剩 " + mt.conv.remain + " 交易日" : ""),
     verdict: "位階−10~−20%×當日≤−2%×10日≤−6%。k20 +3.10%/69%。持有20日。",
     warn: "位階−5~−10%＝接刀死區；≤−20%只吃短。"},
    {name: "🧱 跌停廣度", lit: mt.ld.lit,
     read: "今日收盤跌停 <b>" + mt.ld.today + "</b> 家（門檻20／p99≈45）" +
           (mt.ld.last ? "<br>最近觸發 " + mt.ld.last + (mt.ld.lit ? "，窗剩 " + mt.ld.remain + " 交易日" : "") : "<br>20日內無觸發"),
     verdict: "≥20家＝出清第二軸（訊號集中熱門股層）。k10 +3.09%/75%。持有20日。",
     warn: "第一腿spike≠底（2020-01-30）。"},
    {name: "🚨 融資警戒帶", lit: mt.warn.lit,
     read: "大盤維持率 <b>" + mt.warn.ratio + "%</b>（" + mt.warn.asof + "）｜警戒線150%",
     verdict: "<150%＝斷頭出清水位（9事件勝率78%，60日中位+14.4%）。",
     warn: "2008慢熊首破例外；此為狀態非時點，帶內等急跌收斂日再進。"},
  ];
  cardsEl.innerHTML = cards.map(function(c) {
    return "<div style=\"flex:1 1 300px;border:1px solid var(--bd);border-radius:8px;padding:10px;background:var(--sf)" +
      (c.lit ? ";box-shadow:inset 0 0 0 1px var(--red)" : "") + "\">" +
      "<div style=\"display:flex;justify-content:space-between\"><b>" + c.name + "</b>" + pill(c.lit) + "</div>" +
      "<div style=\"margin:6px 0\">" + c.read + "</div>" +
      "<div class=\"hint\" style=\"margin:0\">" + c.verdict + "<br>⚠ " + c.warn + "</div></div>";
  }).join("");
  const hlEl = document.getElementById("thermoHeadline");
  if (hlEl && mt.headline) {
    hlEl.textContent = mt.headline;
    hlEl.style.color = mt.thermo.lit ? "var(--red)" : (mt.n_lit > 0 ? "#c98a1c" : "var(--tx3)");
  }
  document.getElementById("thermoAsof").textContent =
    "資料至 " + mt.asof + "｜" + mt.n_lit + " 燈亮｜水位階梯v0曝險讀數 " + mt.exposure.toFixed(2) +
    "（研究稿，非下單指令）";
  const sRows = (mt.series || []).map(function(r) {
    return {"日期": r.d, "甜蜜格並發": r.sweet >= 20 ? "<b style=\"color:var(--red)\">" + r.sweet + "</b>" : r.sweet,
            "跌停家數": r.ld >= 20 ? "<b style=\"color:var(--red)\">" + r.ld + "</b>" : r.ld};
  });
  buildTable(document.getElementById("thermoSeries"),
             [{key: "日期", label: "日期"}, {key: "甜蜜格並發", label: "甜蜜格並發(門檻20)"},
              {key: "跌停家數", label: "收盤跌停家數(門檻20)"}], sRows, null);
  const epRows = (mt.episodes || []).map(function(e) {
    return {"日期": e.d, "備註": e.note || ""};
  });
  buildTable(document.getElementById("thermoEpisodes"),
             [{key: "日期", label: "觸發日期"}, {key: "備註", label: "備註"}], epRows, null);
  // 頁頂燈條
  const strip = document.getElementById("thermoStrip");
  if (strip) {
    const mini = [["🌡️溫度計", mt.thermo.lit, mt.thermo.today], ["🌏亞跌B", mt.b.lit, ""],
                  ["📉雙收斂", mt.conv.lit, ""], ["🧱跌停廣度", mt.ld.lit, mt.ld.today],
                  ["🚨警戒帶", mt.warn.lit, mt.warn.ratio + "%"]];
    strip.innerHTML = "<a href=\"javascript:void(0)\" onclick=\"showTab(7);switchSigView('thermo')\"" +
      " style=\"color:inherit;text-decoration:none\" title=\"點開大盤溫度計檢視\">" +
      mini.map(function(m) {
        const col = m[1] ? "var(--red)" : "var(--tx3)";
        return "<span style=\"margin-right:12px;color:" + col + (m[1] ? ";font-weight:700" : "") + "\">" +
          (m[1] ? "●" : "○") + m[0] + (m[2] !== "" ? " " + m[2] : "") + "</span>";
      }).join("") +
      "<span style=\"color:var(--tx3)\">｜曝險v0 " + mt.exposure.toFixed(2) + "｜" + mt.asof + "</span></a>";
    strip.style.display = "";
    const btn = document.getElementById("sigViewThermoBtn");
    if (btn && mt.n_lit) btn.innerHTML = "🌡️大盤溫度計 🔔" + mt.n_lit;
  }
}

function renderSignalTab() {
  const cur = DATA.signal_current || [];
  const microTrig = (DATA.micro_current || []).filter(function(c) { return c.level; }).length;
  const macroTrig = cur.filter(function(c) { return c.verdict; }).length;
  const nSig = macroTrig + microTrig;
  const btn = document.getElementById("signalTabBtn");
  if (btn && nSig) btn.innerHTML = "進場訊號 🔔" + nSig;
  const macroBtn = document.getElementById("sigViewMacroBtn");
  if (macroBtn && macroTrig) macroBtn.innerHTML = "大題材檢查清單 🔔" + macroTrig;
  const microBtn = document.getElementById("sigViewMicroBtn");
  if (microBtn && microTrig) microBtn.innerHTML = "微題材脈衝雷達 🔔" + microTrig;

  // 補漲雷達
  const cu = DATA.catchup_radar || {themes: [], rows: []};
  const cuBtn = document.getElementById("sigViewCatchupBtn");
  if (cuBtn && cu.rows.length) cuBtn.innerHTML = "補漲雷達 🎯" + cu.rows.length;
  document.getElementById("catchupThemes").innerHTML = cu.themes.length
    ? "本週點火題材：" + cu.themes.map(function(g) { return themeLink(g); }).join("、")
    : "本週無題材點火，雷達休眠（點火=熱度週變化z>1或檢查清單觸發）。";
  const cuRows = cu.rows.map(function(r) {
    return {
      "點火題材": themeLink(r.theme), "_g": r.theme,
      "優先序": ({A: "<span style=\"color:var(--amb);font-weight:700\">⭐⭐ 優先研究</span>",
                B: "<span style=\"color:var(--tx2)\">⭐ 一般</span>"})[r.grade] || "—",
      "_gr": ({A: 2, B: 1})[r.grade] || 0,
      "成員": "<a href=\"javascript:void(0)\" onclick=\"jumpToCompany('台|" + r.code + "')\" style=\"color:inherit;border-bottom:1px dotted var(--tx3);text-decoration:none\">" + r.code + " " + r.name + "</a>"
              + (function(ch) { if (!ch) return "";
                  let t = [];
                  if (ch.f !== undefined && ch.f >= 80) t.push("外資位階" + ch.f + "✓");
                  if (ch.s !== undefined && ch.s >= 80) t.push("券資比" + ch.s + "⚡");
                  return t.length ? " <span class=\"hm-score\">" + t.join("·") + "</span>" : "";
                })((DATA.chip || {})[r.code]),
      "最新排名": r.rank, "PB": r.pb, "營收YoY%": r.yoy, "資金位階%": r.pos,
      "埋伏理由": r.tags.join("｜"), "_n": r.n_tags,
    };
  });
  const cuEl = document.getElementById("catchupTable");
  cuEl._sortState = {colIndex: 6, dir: -1};
  buildTable(cuEl, [
    {key: "點火題材", label: "點火題材", sortKey: "_g"},
    {key: "優先序", label: "優先序(未回測)", sortKey: "_gr", numeric: true},
    {key: "成員", label: "成員(未點火)"},
    {key: "最新排名", label: "最新排名", numeric: true}, {key: "PB", label: "PB", numeric: true},
    {key: "營收YoY%", label: "營收YoY%", numeric: true}, {key: "資金位階%", label: "資金位階%", numeric: true},
    {key: "埋伏理由", label: "埋伏理由(符合數排序)", sortKey: "_n", numeric: true},
  ], cuRows);

  // 微題材脈衝雷達
  const microRows = (DATA.micro_current || []).map(function(c) {
    const memTxt = c.members.map(function(m) {
      let g = "";
      if (m.gm !== null && m.gm !== undefined) {
        g = "(" + m.gm + "%" + (m.gmd > 0 ? "↗" : m.gmd < 0 ? "↘" : "") + ")";
      }
      return m.code + m.name + (m.rank ? "#" + m.rank : "") + g;
    }).join("　");
    const MG = {A: "<span style=\"color:var(--amb);font-weight:700\">⭐⭐ 標準</span>",
                B: "<span style=\"color:var(--tx2)\">⭐ 觀察</span>", C: "—"};
    return {
      "微題材": c.theme,
      "推薦": MG[c.grade] || "—",
      "_gr": ({A: 3, B: 2, C: 1})[c.grade] || 0,
      "判定": (c.level || "—") + (c.second ? " ⚠二次脈衝" : ""),
      "_trig": c.level ? 1 : 0,
      "脈衝x": c.pulse, "跳升中位": c.jump, "本週分數": c.score,
      "毛利方向": c.m_n ? "↗" + c.m_up + "/共" + c.m_n : "—",
      "成員(排名/最新季毛利)": memTxt,
    };
  });
  const microCols = [
    {key: "微題材", label: "微題材"},
    {key: "推薦", label: "推薦程度", sortKey: "_gr", numeric: true},
    {key: "判定", label: "判定", sortKey: "_trig", numeric: true},
    {key: "脈衝x", label: "脈衝x", numeric: true},
    {key: "跳升中位", label: "跳升中位", numeric: true},
    {key: "本週分數", label: "本週分數", numeric: true},
    {key: "毛利方向", label: "③毛利方向"},
    {key: "成員(排名/最新季毛利)", label: "成員(排名/最新季毛利)"},
  ];
  const microEl = document.getElementById("microNowTable");
  microEl._sortState = {colIndex: 2, dir: -1};
  buildTable(microEl, microCols, microRows);

  const microHist = (DATA.micro_history || []).map(function(h) {
    return {"日期": h.date, "微題材": h.theme, "脈衝x": h.pulse,
            "跳升中位": h.jump, "sustain": h.sustain,
            "結果": h.sustain === null ? "觀察中" : (h.sustain >= 1.5 ? "✅延續" : "✗未延續")};
  });
  buildTable(document.getElementById("microHistTable"), [
    {key: "日期", label: "日期"}, {key: "微題材", label: "微題材"},
    {key: "脈衝x", label: "脈衝x", numeric: true}, {key: "跳升中位", label: "跳升中位", numeric: true},
    {key: "sustain", label: "sustain", numeric: true}, {key: "結果", label: "結果"},
  ], microHist);

  function pf(ok, text) {
    return ok ? "<span class=\"sig-pass\">✓ " + text + "</span>" : "<span class=\"sig-fail\">✗ " + text + "</span>";
  }
  const regime = DATA.market_tier || {};
  const regEl = document.getElementById("sigRegime");
  if (regEl && regime.txt) {
    const pct = Math.round((regime.tier || 1) * 100);
    regEl.innerHTML = "🎚️ 大盤態勢：加權指數<b>" + regime.txt + "</b> → 建議倉位上限 <b style=\"color:var(--" +
      (pct >= 100 ? "grn" : pct >= 60 ? "amb" : "red") + ")\">" + pct + "%</b>（回測：階梯倉位夏普1.56 vs 滿倉1.29）";
  }
  const GRADE = {S: "<span style=\"color:var(--red);font-weight:700\">⭐⭐⭐ 重點</span>",
                 A: "<span style=\"color:var(--amb);font-weight:700\">⭐⭐ 標準</span>",
                 B: "<span style=\"color:var(--tx2)\">⭐ 觀察</span>", C: "—"};
  const GNUM = {S: 4, A: 3, B: 2, C: 1};
  const rows = cur.map(function(c) {
    return {
      "題材": themeLink(c.theme), "_g": c.theme,
      "推薦": (GRADE[c.grade] || "—") + (c.knife ? " <span title=\"題材長趨勢向下+低位階(假說級警示)\">⚠</span>" : ""),
      "_gr": (GNUM[c.grade] || 0),
      "判定": c.verdict || (c.n_ok + "/4"),
      "n_ok": c.n_ok,
      "前3大成員": (c.top3 || []).map(function(m) {
          const ch = (DATA.chip || {})[m[0]] || {};
          let b = "";
          if (ch.f !== undefined && ch.f >= 80) b += "✓";
          if (ch.s !== undefined && ch.s >= 80) b += "⚡";
          if ((DATA.resonance || {})[m[0]]) b += "🔥";
          return "<a href=\"javascript:void(0)\" onclick=\"jumpToCompany('台|" + m[0] + "');showTab(2)\" style=\"color:inherit;border-bottom:1px dotted var(--tx3);text-decoration:none\">" + m[0] + m[1] + "</a>" + b;
        }).join("、") + ((c.top3 && c.top3.length) ? " <a href=\"javascript:void(0)\" onclick=\"jumpToAnatomy('" + c.theme + "')\" title=\"跳族群金流解剖看完整成員點火時序\">🔎</a>" : "—"),
      "①連漲": pf(c.streak_ok, c.streak + "週"),
      "②廣度": pf(c.breadth_ok, (c.breadth === null ? "-" : c.breadth + "%") + "/" + (c.breadth_prev === null ? "-" : c.breadth_prev + "%")),
      "③升國": pf(c.rising_ok, c.rising + "國"),
      "④單國佔比": pf(c.share_ok, c.max_share + "%"),
      "⑤型態門檻": c.pat === true ? "<span class=\"sig-pass\">✓ 通過</span>"
                 : (c.pat === false ? "<span class=\"sig-fail\">✗ 未過</span>" : "—"),
      "_pat": c.pat === true ? 1 : 0,
      "位階": c.pos,
      "熱度分數": c.score,
      "階段": c.stage,
      "基本面": (c.eps_up_pct === null ? "—" : "EPS預估成長" + c.eps_up_pct + "%") + "｜" + (c.rg_up_pct === null ? "—" : "營收實績+" + c.rg_up_pct + "%")
              + "｜總營收" + (c.rev_mom_yoy === null || c.rev_mom_yoy === undefined ? "—"
                : (c.rev_mom_yoy >= 0 ? "+" : "") + c.rev_mom_yoy + "%" + (c.rev_mom_ok === true ? "<span class=\"sig-pass\">↑✓</span>" : (c.rev_mom_ok === false ? "" : "·"))),
      "eps_up_pct": c.eps_up_pct,
    };
  });
  const cols = [
    {key: "題材", label: "題材", sortKey: "_g"},
    {key: "推薦", label: "推薦程度", sortKey: "_gr", numeric: true},
    {key: "判定", label: "判定", sortKey: "n_ok", numeric: true},
    {key: "前3大成員", label: "前3大成員(回測口徑)"},
    {key: "①連漲", label: "①連漲≥2週"}, {key: "②廣度", label: "②廣度≥50%×2週"},
    {key: "③升國", label: "③≥3國同升"}, {key: "④單國佔比", label: "④單國<80%"},
    {key: "⑤型態門檻", label: "⑤型態門檻", sortKey: "_pat", numeric: true},
    {key: "位階", label: "位階%(參考)", numeric: true}, {key: "熱度分數", label: "熱度分數", numeric: true},
    {key: "基本面", label: "⑥基本面確認", sortKey: "eps_up_pct", numeric: true},
    {key: "階段", label: "階段"},
  ];
  const nowEl = document.getElementById("signalNowTable");
  nowEl._sortState = {colIndex: 1, dir: -1};
  buildTable(nowEl, cols, rows);

  const hist = (DATA.signal_history || []).map(function(h) {
    return {"日期": h.date, "題材": themeLink(h.theme), "_g": h.theme, "分數": h.score, "位階%": h.pos,
            "廣度%": h.breadth, "升國": h.rising,
            "+8週倍率": h.fwd8x, "13週最大": h.max13x,
            "評價": h.pos < 70 ? "低位階" : "高位階"};
  });
  const hcols = [
    {key: "日期", label: "日期"}, {key: "題材", label: "題材", sortKey: "_g"}, {key: "評價", label: "評價"},
    {key: "分數", label: "分數", numeric: true}, {key: "位階%", label: "位階%", numeric: true},
    {key: "廣度%", label: "廣度%", numeric: true}, {key: "升國", label: "升國", numeric: true},
    {key: "+8週倍率", label: "+8週倍率", numeric: true}, {key: "13週最大", label: "13週最大", numeric: true},
  ];
  buildTable(document.getElementById("signalHistTable"), hcols, hist);
}

// ── 資金輪動熱力圖 ────────────────────────────────────────────────────
function renderRotationHeatmap() {
  const el = document.getElementById("rotationHeatmap");
  let dates = DATA.snapshot_dates;
  const rng = document.getElementById("hmRange").value;
  if (rng !== "all") dates = dates.slice(-parseInt(rng, 10));
  if (!dates || dates.length < 2) {
    el.innerHTML = "<div class=\"hint\" style=\"margin:0\">需要至少兩個快照才能觀察輪動，之後每週更新會自動累積。</div>";
    return;
  }
  let themes = getVisibleThemes();
  // 共振欄：每週點火題材數(點火=熱度週變化z>1，與族群金流解剖◆同定義)；用全部可見題材算，不受前20顯示限制
  const igniteCount = {};
  themes.forEach(function(g) {
    const byD = {};
    (DATA.theme_history[g] || []).forEach(function(r) { byD[r.snapshot_date] = r["熱度分數"]; });
    const series = DATA.snapshot_dates.map(function(d) { return byD[d] || 0; });
    anaIgn(series).forEach(function(w) {
      const dd = DATA.snapshot_dates[w];
      igniteCount[dd] = (igniteCount[dd] || 0) + 1;
    });
  });
  // 紅標門檻自校準：點火數 ≥ 全期平均+1SD 才算異常共振週(z>1基率~16%，固定門檻會週週標紅)
  const igCounts = DATA.snapshot_dates.slice(1).map(function(d) { return igniteCount[d] || 0; });
  const igMu = igCounts.reduce(function(s, v) { return s + v; }, 0) / (igCounts.length || 1);
  const igThr = igMu + Math.sqrt(igCounts.reduce(function(s, v) { return s + (v - igMu) * (v - igMu); }, 0) / (igCounts.length || 1));
  const latestScore = {}, posMap = {};
  // 位階固定用近52週計算，與顯示範圍脫鉤(跟推薦程度表/全站位階同一把尺)
  const posDates = DATA.snapshot_dates.slice(-52);
  themes.forEach(function(g) {
    const s = {};
    (DATA.theme_history[g] || []).forEach(function(r) { s[r.snapshot_date] = r["熱度分數"]; });
    latestScore[g] = s[DATA.latest_date] || 0;
    let mn = Infinity, mx = -Infinity;
    posDates.forEach(function(d) { const v = s[d]; if (v !== undefined) { if (v < mn) mn = v; if (v > mx) mx = v; } });
    posMap[g] = (mx > mn && latestScore[g] > 0) ? (latestScore[g] - mn) / (mx - mn) : 0;
  });
  // 排序：位階優先(量化10級，同級再比熱度) 或 熱度優先
  const sortMode = document.getElementById("hmSort").value;
  themes = themes.slice().sort(function(a, b) {
    if (sortMode === "pos") {
      const pa = Math.round(posMap[a] * 10), pb = Math.round(posMap[b] * 10);
      if (pb !== pa) return pb - pa;
    }
    return latestScore[b] - latestScore[a];
  });
  const showAll = document.getElementById("hmShowAll").checked;
  if (!showAll) themes = themes.slice(0, 20);
  const mode = document.getElementById("hmColorMode").value;

  // 絕對模式：顯示範圍內全部題材共用同一個最大值
  let gMax = 0;
  if (mode === "abs") {
    const dateSet = {};
    dates.forEach(function(d) { dateSet[d] = true; });
    themes.forEach(function(g) {
      (DATA.theme_history[g] || []).forEach(function(r) {
        if (dateSet[r.snapshot_date] && r["熱度分數"] > gMax) gMax = r["熱度分數"];
      });
    });
    if (!gMax) gMax = 1;
  }

  let html = "<table class=\"hm-table\"><tr><th class=\"hm-name\"></th>";
  dates.forEach(function(d, i) {
    const cur = i === dates.length - 1 ? " style=\"color:var(--ac);font-weight:700\"" : "";
    html += "<th class=\"hm-date\"" + cur + ">" + d.slice(5) + "</th>";
  });
  html += "</tr>";
  html += "<tr><td class=\"hm-name\" style=\"font-size:10px;color:var(--tx3)\">共振(點火題材數)</td>";
  dates.forEach(function(d) {
    const k = igniteCount[d] || 0;
    const st = (k > 0 && k >= igThr) ? "color:var(--red);font-weight:700" : "color:var(--tx3)";
    html += "<td class=\"hm-cell\" style=\"text-align:center;font-size:10px;" + st + "\" title=\"" + d + "：" + k + " 個題材點火(週變化z>1)；紅標門檻=全期平均+1SD≈" + igThr.toFixed(0) + "\">" + (k || "") + "</td>";
  });
  html += "</tr>";
  themes.forEach(function(g) {
    const byDate = {};
    (DATA.theme_history[g] || []).forEach(function(r) { byDate[r.snapshot_date] = r["熱度分數"]; });
    const vals = dates.map(function(d) { return byDate[d]; }).filter(function(v) { return v !== undefined; });
    if (!vals.length) return;
    const mx = Math.max.apply(null, vals), mn = Math.min.apply(null, vals);
    html += "<tr><td class=\"hm-name\">" + themeLink(g) + " <span class=\"hm-score\">" + latestScore[g].toFixed(1) + "·52週位階" + Math.round(posMap[g] * 100) + "%</span></td>";
    dates.forEach(function(d) {
      const v = byDate[d];
      if (v === undefined) { html += "<td class=\"hm-cell hm-empty\"></td>"; return; }
      let t;
      if (mode === "abs") {
        t = Math.sqrt(v / gMax);                       // 開根號讓中低值仍可辨識
      } else {
        t = mx > mn ? (v - mn) / (mx - mn) : 0.5;
      }
      const alpha = (0.05 + t * 0.85).toFixed(2);
      html += "<td class=\"hm-cell\" style=\"background:rgba(232,69,69," + alpha + ")\" title=\"" + g + " " + d + "：" + v + "\"></td>";
    });
    html += "</tr>";
  });
  html += "</table>";
  el.innerHTML = html;
}

// ── 動能雷達：RRG象限圖 + 動能訊號表（含時間軸播放）─────────────────
let radarTimer = null;
let radarFocus = {};          // 點擊聚焦的題材集合(可複選)
let radarClickBound = false;

function radarRedraw() {
  const slider = document.getElementById("radarSlider");
  drawRadarFrame(parseInt(slider.value, 10), false);
}

function radarUnfocus(g) {
  delete radarFocus[g];
  updateRadarFocusChips();
  radarRedraw();
}

function radarClearFocus() {
  radarFocus = {};
  updateRadarFocusChips();
  radarRedraw();
}

// 全站題材名稱可點：跳到動能雷達並聚焦該題材
function jumpToAnatomy(g) {
  const sel = document.getElementById("resTheme");
  let has = false;
  if (sel) for (let i = 0; i < sel.options.length; i++) if (sel.options[i].value === g) { has = true; break; }
  // 題材不在解剖選單(台股成員<3)時改開成員速查彈窗(2026-07-19,原退回雷達會看不到成員)
  if (!has) {
    if (DATA.theme_members && DATA.theme_members[g]) { showThemeMembers(g); } else { jumpToRadar(g); }
    return;
  }
  sel.value = g;
  showTab(2);
  switchHistView("res");
  const el = document.getElementById("anaChart");
  if (el) el.scrollIntoView({behavior: "smooth"});
}

function jumpToRadar(g) {
  if (!DATA.theme_history || !DATA.theme_history[g]) return;
  const thematicSet = {};
  (DATA.theme_list_thematic || []).forEach(function(x) { thematicSet[x] = true; });
  if (!thematicSet[g]) {
    const cb = document.getElementById("radarIncludeBroad");
    if (cb) cb.checked = true;   // 廣義分類(金融等)要先打開開關才會出現在雷達
  }
  radarFocus = {};
  radarFocus[g] = true;
  updateRadarFocusChips();
  showTab(6);
  renderRadar();
}

function themeLink(g) {
  const mem = (DATA.theme_members && DATA.theme_members[g])
    ? " <a href=\"javascript:void(0)\" onclick=\"showThemeMembers('" + g + "')\" title=\"題材成員速查(全市場名單)\" style=\"text-decoration:none\">👥</a>" : "";
  if (!DATA.theme_history || !DATA.theme_history[g]) return g + mem;   // 微題材等不在雷達內的不加連結
  return "<a class=\"theme-link\" href=\"javascript:void(0)\" onclick=\"jumpToRadar('" + g + "')\" title=\"跳到動能雷達聚焦此題材\">" + g + "</a>" + mem;
}

// 題材成員速查彈窗(2026-07-19): 熱力圖/全站題材名旁👥開啟;台股成員<3的題材(如汽車零件)唯一查詢入口
function showThemeMembers(g) {
  const rows = (DATA.theme_members || {})[g] || [];
  const m = document.getElementById("themeMemberModal");
  if (!rows.length || !m) return;
  let html = "<div style=\"display:flex;justify-content:space-between;align-items:center\"><b>" + g +
    " 題材成員（" + rows.length + " 檔）</b><span style=\"cursor:pointer;font-size:20px;color:var(--tx3)\" " +
    "onclick=\"document.getElementById('themeMemberModal').style.display='none'\">×</span></div>";
  html += "<table class=\"tm-table\"><tr><th>市場</th><th>代碼</th><th>公司</th><th>本週排行</th><th style=\"text-align:left\">產品/角色</th></tr>";
  rows.forEach(function(r) {
    const nm = (r[0] === "台" && DATA.company_history && DATA.company_history["台|" + r[1]])
      ? "<a href=\"javascript:void(0)\" onclick=\"document.getElementById('themeMemberModal').style.display='none';jumpToCompany('台|" + r[1] + "');showTab(2)\">" + (r[2] || r[1]) + "</a>"
      : (r[2] || "—");
    html += "<tr><td>" + r[0] + "</td><td>" + r[1] + "</td><td>" + nm + "</td><td>" +
      (r[4] ? "#" + r[4] : "—") + "</td><td style=\"text-align:left\">" + (r[3] || "") + "</td></tr>";
  });
  html += "</table><div class=\"hint\" style=\"margin:8px 0 0\">名單＝classification全成員（不限本週上榜）；台股成員&lt;3檔的題材不進金流解剖選單，由此速查。</div>";
  m.querySelector(".tm-body").innerHTML = html;
  m.style.display = "flex";
}

function updateRadarFocusChips() {
  const el = document.getElementById("radarFocusChips");
  const keys = Object.keys(radarFocus);
  let html = keys.map(function(g) {
    return "<span class=\"chip\">" + g + "<span class=\"chip-x\" onclick=\"radarUnfocus('" + g + "')\">×</span></span>";
  }).join("");
  if (keys.length) html += "<span class=\"chip\" style=\"cursor:pointer\" onclick=\"radarClearFocus()\">全部清除</span>";
  el.innerHTML = html;
}

function stopRadarPlay() {
  if (radarTimer) { clearInterval(radarTimer); radarTimer = null; }
  const b = document.getElementById("radarPlayBtn");
  if (b) b.textContent = "▶ 播放";
}

function toggleRadarPlay() {
  if (radarTimer) { stopRadarPlay(); return; }
  const slider = document.getElementById("radarSlider");
  const maxI = parseInt(slider.max, 10);
  let i = parseInt(slider.value, 10);
  if (i >= maxI) i = parseInt(slider.min, 10);
  document.getElementById("radarPlayBtn").textContent = "⏸ 暫停";
  radarTimer = setInterval(function() {
    if (i > maxI) { stopRadarPlay(); return; }
    slider.value = i;
    drawRadarFrame(i, i === maxI);
    i++;
  }, 650);
}

function onRadarSlide() {
  stopRadarPlay();
  const slider = document.getElementById("radarSlider");
  drawRadarFrame(parseInt(slider.value, 10), slider.value === slider.max);
}

function renderRadar() {
  stopRadarPlay();
  const dates = DATA.snapshot_dates;
  const chartEl = document.getElementById("radarChart");
  if (!dates || dates.length < 3) { chartEl.innerHTML = "<div class=\"hint\">快照數不足，累積三週後可用。</div>"; return; }
  let n = parseInt(document.getElementById("radarPeriod").value, 10) || 2;
  if (n > dates.length - 2) n = dates.length - 2;
  const slider = document.getElementById("radarSlider");
  slider.min = Math.min(n, dates.length - 1);
  slider.max = dates.length - 1;
  slider.value = dates.length - 1;
  drawRadarFrame(dates.length - 1, true);
}

function drawRadarFrame(ei, withTable) {
  const dates = DATA.snapshot_dates;
  let n = parseInt(document.getElementById("radarPeriod").value, 10) || 2;
  if (n > dates.length - 2) n = dates.length - 2;
  if (ei - n < 0) ei = n;
  const includeBroad = document.getElementById("radarIncludeBroad").checked;
  const themes = getVisibleThemes(includeBroad);
  const L = ei + 1;                 // 只使用到 ei 為止的歷史(播放時不偷看未來)
  const cur = dates[ei];
  document.getElementById("radarDate").textContent = cur;

  // 廣度：題材內個股排名較上週上升/下降家數(全市場)
  const bUp = {}, bDown = {};
  (DATA.full_records || []).forEach(function(r) {
    const d = r["排名Δ_num"];
    if (d === undefined || d === null) return;
    String(r.main_groups || "").split(", ").forEach(function(g) {
      if (d > 0) bUp[g] = (bUp[g] || 0) + 1;
      else if (d < 0) bDown[g] = (bDown[g] || 0) + 1;
    });
  });
  const twCount = {};
  DATA.theme_pivot_all.forEach(function(p) { twCount[p.main_group] = p["台"] || 0; });

  const rows = [];
  themes.forEach(function(g) {
    const s = {};
    (DATA.theme_history[g] || []).forEach(function(r) { s[r.snapshot_date] = r["熱度分數"]; });
    const score = s[cur];
    const base = s[dates[L - 1 - n]];
    if (score === undefined || base === undefined) return;
    const delta = score - base;
    const prevBase = (L - 1 - 2 * n >= 0) ? s[dates[L - 1 - 2 * n]] : undefined;
    const accel = (prevBase !== undefined) ? (delta - (base - prevBase)) : null;
    let up = 0, down = 0;
    for (let i = L - 1; i > 0; i--) {
      const a = s[dates[i]], b = s[dates[i - 1]];
      if (a === undefined || b === undefined) break;
      if (a > b && down === 0) up++;
      else if (a < b && up === 0) down++;
      else break;
    }
    let mn = Infinity, mx = -Infinity;
    dates.slice(0, L).forEach(function(d0) { const v = s[d0]; if (v !== undefined) { if (v < mn) mn = v; if (v > mx) mx = v; } });
    const pos = mx > mn ? (score - mn) / (mx - mn) : 0.5;
    let stage;
    if (delta > 0 && pos >= 0.6) stage = "🚀 主升段";
    else if (delta > 0 && up >= 2) stage = "🔥 發動";
    else if (delta > 0) stage = "↗ 回溫";
    else if (delta < 0 && pos >= 0.7) stage = "⚠ 高檔轉弱";
    else if (delta < 0 && down >= 2) stage = "↘ 退潮";
    else if (delta < 0) stage = "▽ 回檔";
    else stage = "— 盤整";
    const trailX = [], trailY = [];
    for (let k = 3; k >= 0; k--) {
      const i = L - 1 - k;
      if (i - n < 0) continue;
      const v = s[dates[i]], vb = s[dates[i - n]];
      if (v === undefined || vb === undefined) continue;
      trailX.push(v); trailY.push(v - vb);
    }
    rows.push({
      g: g, score: +score.toFixed(2), delta: +delta.toFixed(2),
      accel: accel === null ? null : +accel.toFixed(2),
      up: up, down: down, stage: stage,
      bUp: bUp[g] || 0, bDown: bDown[g] || 0, tw: twCount[g] || 0,
      trailX: trailX, trailY: trailY,
    });
  });

  // 象限圖（X軸對數尺度展開；軸界與象限分界取全期間固定值，播放時畫面不跳動）
  let chartRows = rows.filter(function(r) { return r.score > 0; });
  const showMode = document.getElementById("radarShow").value;
  if (showMode === "hot15") {
    chartRows = chartRows.slice().sort(function(a, b) { return b.score - a.score; }).slice(0, 15);
  } else if (showMode === "mover15") {
    chartRows = chartRows.slice().sort(function(a, b) { return Math.abs(b.delta) - Math.abs(a.delta); }).slice(0, 15);
  } else if (showMode === "up") {
    chartRows = chartRows.filter(function(r) { return r.delta > 0; });
  }
  // 聚焦中的題材強制入圖(即使被顯示模式篩掉)
  const hasFocus = Object.keys(radarFocus).length > 0;
  if (hasFocus) {
    const present = {};
    chartRows.forEach(function(r) { present[r.g] = true; });
    rows.forEach(function(r) { if (radarFocus[r.g] && !present[r.g] && r.score > 0) chartRows.push(r); });
  }
  let gMaxY = 0.5, gMaxX = 1, gMinX = Infinity;
  const latestScores = [];
  themes.forEach(function(g) {
    const s = {};
    (DATA.theme_history[g] || []).forEach(function(r) { s[r.snapshot_date] = r["熱度分數"]; });
    dates.forEach(function(d, i) {
      const v = s[d];
      if (v === undefined) return;
      if (v > gMaxX) gMaxX = v;
      if (v > 0 && v < gMinX) gMinX = v;
      if (i - n >= 0 && s[dates[i - n]] !== undefined) {
        const dd = Math.abs(v - s[dates[i - n]]);
        if (dd > gMaxY) gMaxY = dd;
      }
    });
    const lv = s[DATA.latest_date];
    if (lv !== undefined && lv > 0) latestScores.push(lv);
  });
  latestScores.sort(function(a, b) { return a - b; });
  const medX = latestScores.length ? latestScores[Math.floor(latestScores.length / 2)] : 1;
  const labelSet = {};
  if (chartRows.length <= 18) {
    chartRows.forEach(function(r) { labelSet[r.g] = true; });   // 點少時全部標名
  } else {
    chartRows.slice().sort(function(a, b) { return b.score - a.score; }).slice(0, 10).forEach(function(r) { labelSet[r.g] = true; });
    chartRows.slice().sort(function(a, b) { return Math.abs(b.delta) - Math.abs(a.delta); }).slice(0, 4).forEach(function(r) { labelSet[r.g] = true; });
  }
  const trailSet = {};
  chartRows.slice().sort(function(a, b) { return b.score - a.score; }).slice(0, 6).forEach(function(r) { trailSet[r.g] = true; });
  chartRows.slice().sort(function(a, b) { return Math.abs(b.delta) - Math.abs(a.delta); }).slice(0, 3).forEach(function(r) { trailSet[r.g] = true; });

  const Q = {
    lead: "#e84545", improve: "#d49610", fade: "#3c8cf0", weak: "#6b7f91",
    leadT: "rgba(232,69,69,.25)", improveT: "rgba(212,150,16,.25)",
    fadeT: "rgba(60,140,240,.25)", weakT: "rgba(107,127,145,.2)",
  };
  function qKey(r) {
    if (r.delta >= 0) return r.score >= medX ? "lead" : "improve";
    return r.score >= medX ? "fade" : "weak";
  }

  const maxY = gMaxY * 1.15;
  const maxX = gMaxX * 1.3;
  const minX = Math.max(0.04, (gMinX === Infinity ? 1 : gMinX) * 0.7);
  const lg = Math.log10;

  const traces = [];
  chartRows.forEach(function(r) {
    const showTrail = hasFocus ? radarFocus[r.g] : trailSet[r.g];
    if (showTrail && r.trailX.length > 1) {
      traces.push({x: r.trailX, y: r.trailY, mode: "lines",
        line: {color: hasFocus ? Q[qKey(r)] : Q[qKey(r) + "T"], width: hasFocus ? 2 : 1.5, shape: "spline"},
        opacity: hasFocus ? 0.55 : 1,
        hoverinfo: "skip", showlegend: false});
    }
  });
  traces.push({
    x: chartRows.map(function(r) { return r.score; }),
    y: chartRows.map(function(r) { return r.delta; }),
    mode: "markers",
    customdata: chartRows.map(function(r) { return r.g; }),
    marker: {
      size: chartRows.map(function(r) { return Math.min(19, 6 + Math.sqrt(r.score) * 2.2); }),
      color: chartRows.map(function(r) { return Q[qKey(r)]; }),
      line: {color: "#0c1118", width: 1.5},
      opacity: hasFocus ? chartRows.map(function(r) { return radarFocus[r.g] ? 0.95 : 0.15; }) : 0.92,
    },
    text: chartRows.map(function(r) { return "<b>" + r.g + "</b><br>熱度 " + r.score + "｜Δ" + n + "週 " + r.delta + "<br>" + r.stage; }),
    hoverinfo: "text",
    showlegend: false,
  });
  const labeled = chartRows.filter(function(r) { return hasFocus ? radarFocus[r.g] : labelSet[r.g]; });
  traces.push({
    x: labeled.map(function(r) { return r.score; }),
    y: labeled.map(function(r) { return r.delta; }),
    mode: "text",
    text: labeled.map(function(r) { return r.g; }),
    textposition: labeled.map(function(r, i) {
      const up = r.delta >= 0;
      const cyc = i % 3;
      if (cyc === 0) return up ? "top center" : "bottom center";
      if (cyc === 1) return up ? "top right" : "bottom right";
      return up ? "top left" : "bottom left";
    }),
    textfont: {size: 10.5, color: "#b8c8d8"},
    hoverinfo: "skip",
    showlegend: false,
  });

  function qrect(x0, x1, y0, y1, color) {
    return {type: "rect", x0: lg(x0), x1: lg(x1), y0: y0, y1: y1,
            fillcolor: color, line: {width: 0}, layer: "below"};
  }
  Plotly.react("radarChart", traces, {
    title: {text: "題材輪動象限(RRG)　" + dates[L - 1 - n] + " → " + cur, font: {size: 15}},
    paper_bgcolor: "#0c1118", plot_bgcolor: "#10161f", font: {color: "#d4dde8"},
    xaxis: {title: "熱度分數(強度，對數尺度)", type: "log", range: [lg(minX), lg(maxX)],
            zeroline: false, gridcolor: "rgba(38,60,87,.35)"},
    yaxis: {title: n + "週熱度變化(動能)", range: [-maxY, maxY],
            zeroline: false, gridcolor: "rgba(38,60,87,.35)"},
    shapes: [
      qrect(medX, maxX, 0, maxY, "rgba(232,69,69,.07)"),
      qrect(minX, medX, 0, maxY, "rgba(212,150,16,.055)"),
      qrect(medX, maxX, -maxY, 0, "rgba(60,140,240,.055)"),
      qrect(minX, medX, -maxY, 0, "rgba(107,127,145,.045)"),
      {type: "line", x0: lg(medX), x1: lg(medX), y0: -maxY, y1: maxY, line: {color: "rgba(125,149,170,.5)", width: 1, dash: "dot"}},
      {type: "line", x0: lg(minX), x1: lg(maxX), y0: 0, y1: 0, line: {color: "rgba(125,149,170,.5)", width: 1, dash: "dot"}},
    ],
    annotations: [
      {x: lg(maxX * 0.92), y: maxY * 0.92, text: "領 漲", showarrow: false, font: {color: "rgba(232,69,69,.55)", size: 17}, xanchor: "right"},
      {x: lg(minX * 1.15), y: maxY * 0.92, text: "轉 強", showarrow: false, font: {color: "rgba(212,150,16,.55)", size: 17}, xanchor: "left"},
      {x: lg(maxX * 0.92), y: -maxY * 0.92, text: "退 潮", showarrow: false, font: {color: "rgba(60,140,240,.55)", size: 17}, xanchor: "right"},
      {x: lg(minX * 1.15), y: -maxY * 0.92, text: "弱 勢", showarrow: false, font: {color: "rgba(107,127,145,.55)", size: 17}, xanchor: "left"},
    ],
    margin: {t: 46, l: 60, r: 20},
  }, {responsive: true});

  // 點擊圓點聚焦/取消(可複選)
  const gd = document.getElementById("radarChart");
  if (!radarClickBound && gd.on) {
    gd.on("plotly_click", function(ev) {
      const pt = ev.points && ev.points[0];
      if (!pt || pt.customdata === undefined) return;
      const g = pt.customdata;
      if (radarFocus[g]) delete radarFocus[g]; else radarFocus[g] = true;
      updateRadarFocusChips();
      radarRedraw();
    });
    radarClickBound = true;
  }

  // 訊號表(只在時間軸停在最新時更新)
  if (withTable) {
    const cols = [
      {key: "gDisp", label: "題材", sortKey: "g"},
      {key: "stage", label: "階段"},
      {key: "score", label: "熱度分數", numeric: true},
      {key: "delta", label: "Δ" + n + "週", numeric: true},
      {key: "accel", label: "加速度", numeric: true},
      {key: "up", label: "連漲週", numeric: true},
      {key: "down", label: "連跌週", numeric: true},
      {key: "bUp", label: "廣度▲", numeric: true},
      {key: "bDown", label: "廣度▼", numeric: true},
      {key: "tw", label: "台股家數", numeric: true},
    ];
    const tableEl = document.getElementById("momentumTable");
    tableEl._sortState = {colIndex: 3, dir: -1};
    buildTable(tableEl, cols, rows.map(function(r) { return Object.assign({}, r, {gDisp: themeLink(r.g)}); }));
  }
}

function renderPledgeView() {
  const pa = DATA.pledge_alert || {};
  const rows = pa.rows || [];
  const nWarn = rows.filter(function(r) { return r.tier === "警戒"; }).length;
  document.getElementById("pledgeAsof").textContent = pa.asof
    ? ("資料至 " + pa.asof + "｜60交易日窗內 " + rows.length + " 筆內部人解質｜🔴警戒 " + nWarn + " 筆")
    : "無資料（先跑 python fetch_pledge.py）";
  // 題材聚合: 哪些產業的高層在賣
  const agg = {};
  rows.forEach(function(r) {
    (r.groups && r.groups.length ? r.groups : ["（無題材歸屬）"]).forEach(function(g) {
      if (!agg[g]) agg[g] = {n: 0, codes: {}, lots: 0, warn: 0};
      agg[g].n += 1; agg[g].codes[r.code] = 1; agg[g].lots += r.lots;
      if (r.tier === "警戒") agg[g].warn += 1;
    });
  });
  const aggRows = Object.keys(agg).map(function(g) {
    const a = agg[g];
    return {"題材": g, "事件數": a.n, "公司數": Object.keys(a.codes).length,
            "解質張數合計": a.lots.toLocaleString(),
            "警戒格": a.warn ? "<b style=\"color:var(--red)\">" + a.warn + "</b>" : "0",
            _w: a.warn, _n: a.n};
  }).sort(function(x, y) { return y._w - x._w || y._n - x._n; }).slice(0, 20);
  buildTable(document.getElementById("pledgeThemeAgg"),
    [{key: "題材", label: "題材"}, {key: "警戒格", label: "🔴警戒格"}, {key: "事件數", label: "事件數"},
     {key: "公司數", label: "公司數"}, {key: "解質張數合計", label: "解質張數合計"}],
    aggRows, function(r) { return r._w > 0 ? "hl-row" : null; });
  // 事件明細
  const evRows = rows.map(function(r) {
    const badge = r.tier === "警戒" ? "<b style=\"color:var(--red)\">🔴警戒</b>"
      : (r.tier === "股東會季" ? "<span style=\"color:var(--tx3)\">股東會季</span>" : "觀察");
    return {"狀態": badge, "日期": r.d, "股票": r.code + " " + (r.name || ""),
            "題材": (r.groups || []).join("、") || "—",
            "身分": r.roles + (r.persons > 1 ? "（" + r.persons + "人）" : ""),
            "解質張數": r.lots.toLocaleString(), "累積張": r.cum.toLocaleString(),
            "事件日位階": r.pr === null ? "—" : r.pr,
            "迄今%": r.ret === null ? "—" : (r.ret > 0 ? "+" : "") + r.ret,
            "窗剩餘": r.left + "日",
            "交叉": (r.xref || []).length ? "<b style=\"color:var(--warn,#c3a55a)\">" + r.xref.join("、") + "</b>" : "—",
            _t: r.tier};
  });
  buildTable(document.getElementById("pledgeTable"),
    [{key: "狀態", label: "狀態"}, {key: "日期", label: "彙整日"}, {key: "股票", label: "股票"},
     {key: "題材", label: "題材"}, {key: "身分", label: "身分"}, {key: "解質張數", label: "解質張數"},
     {key: "累積張", label: "累積張"}, {key: "事件日位階", label: "事件日位階"},
     {key: "迄今%", label: "迄今%"}, {key: "窗剩餘", label: "窗剩餘"}, {key: "交叉", label: "交叉比對"}],
    evRows, function(r) { return r._t === "警戒" ? "hl-row" : null; });
}

function renderHealthBar() {
  const el = document.getElementById("healthBar");
  const items = DATA.health || [];
  const fails = DATA.build_fails || [];
  if (!items.length && !fails.length) { el.style.display = "none"; return; }
  const nWarn = items.filter(function(h) { return h.s !== "ok"; }).length;
  let html = DATA.version ? "<span style=\"color:var(--tx3)\">" + DATA.version + "</span>" : "";
  if (fails.length) {
    const tip = fails.map(function(f) { return f.replace(/"/g, "'"); }).join("&#10;");
    html += "<span class=\"health-item\" style=\"color:var(--red);font-weight:700\" title=\"" + tip +
            "\"><span class=\"health-dot crit\"></span>⚠ " + fails.length +
            " 個區塊建置失敗，該區塊顯示的是空資料（懸停看明細，重跑 python export_html.py 前先修錯誤）</span>";
  }
  html += "<span style=\"font-weight:600;color:var(--tx2)\">資料健康" +
          (nWarn ? " <span class=\"health-dot warn\"></span>" + nWarn + "項待更新" : " <span class=\"health-dot ok\"></span>全部正常") + "：</span>";
  html += items.map(function(h) {
    const tip = "更新節奏：" + h.c + (h.a !== undefined ? "｜距今" + h.a + "天" : "");
    return "<span class=\"health-item\" title=\"" + tip + "\"><span class=\"health-dot " + h.s + "\"></span>" + h.n + " " + h.d + "</span>";
  }).join("");
  el.innerHTML = html;
}

// ── ⑫題材月營收動能（score訊號，2026-07-14上線）───────────────────────
function ymAdd(ym, k) {
  const y = +ym.slice(0, 4), m0 = +ym.slice(5, 7) - 1 + k;
  return (y + Math.floor(m0 / 12)) + "-" + String(m0 % 12 + 1).padStart(2, "0");
}

function revmomMemberLinks(t) {
  return (t.top5 || []).map(function(m) {
    const ch = (DATA.chip || {})[m[0]] || {};
    let b = "";
    if (ch.f !== undefined && ch.f >= 80) b += "<span title=\"外資位階≥80：近20日外資累計買賣超在自身一年高檔=聰明錢腳印(回測加分,中小型股有效)\">✓</span>";
    if (ch.s !== undefined && ch.s >= 80) b += "<span title=\"券資比位階≥80：空單/融資比在自身一年高檔=軋空燃料(證據較弱,僅供參考)\">⚡</span>";
    const reso = (DATA.resonance || {})[m[0]];
    if (reso) b += "<span title=\"" + reso.week + "同週" + reso.n_members + "檔共振,"
      + (reso.weeks_ago === 0 ? "本週" : reso.weeks_ago + "週前") + "(觀察層,爆量長紅+週線創高)\">🔥</span>";
    const label = m[0] + m[1] + "(" + (m[2] === null ? "?" : m[2]) + "%)";
    return (DATA.company_history && DATA.company_history["台|" + m[0]])
      ? "<a href=\"javascript:void(0)\" onclick=\"jumpToCompany('台|" + m[0] + "');showTab(2)\" style=\"color:inherit;border-bottom:1px dotted var(--tx3);text-decoration:none\">" + label + "</a>" + b
      : label + b;
  }).join("、");
}

function renderRevmomTab() {
  const tm = DATA.theme_momentum || {};
  const themes = tm.themes || {};
  if (!tm.asof) return;
  const sigMonth = ymAdd(tm.asof, 2);  // 營收月r→r+1月公告→r+2月15號進場(凍結回測口徑)
  document.getElementById("revmomSigMonth").textContent =
    "訊號月 " + sigMonth + "（進場口徑=" + sigMonth + "-15），使用營收月至 " + tm.asof;
  const regime = DATA.market_tier || {};
  const pct = Math.round((regime.tier || 1) * 100);
  document.getElementById("revmomTier").innerHTML =
    "🎚️ 建議倉位＝訊號照進 × 大盤態勢係數：加權指數<b>" + (regime.txt || "") + "</b> → <b style=\"color:var(--" +
    (pct >= 100 ? "grn" : pct >= 60 ? "amb" : "red") + ")\">" + pct + "%</b>（V2回測：縮放版夏普2.07/MDD-21.6% vs 滿倉1.90/-29.8%）";
  const rows = [];
  Object.keys(themes).forEach(function(g) {
    const t = themes[g];
    const own = t.months[t.months.length - 1];
    if (own !== tm.asof && ymAdd(own, 1) !== tm.asof) return;  // 落後>1月=可能有成員停報,不進表
    if (t.score < 3) return;
    const lagTag = own !== tm.asof ? "（資料至" + own + "）" : "";
    const conf = t.score === 4
      ? "<span style=\"color:var(--red);font-weight:700\">⭐⭐⭐ 極高</span>"
      : "<span style=\"color:var(--tx2)\">⭐ 觀察</span>";
    let miss = "";
    if (t.score === 3) miss = t.msc === 3 ? "（缺：近3月YoY均值未轉正）" : "（缺：連續月增僅" + t.msc + "/3）";
    rows.push({
      "題材": themeLink(g), "_g": g,
      "信心": conf, "_sc": t.score,
      "score": t.score + "/4" + miss + lagTag,
      "近3月MoM%": (t.mom3 || []).map(function(v) { return v === null ? "—" : (v > 0 ? "+" : "") + v; }).join(" / "),
      "近3月YoY均%": t.ty3 === null ? "—" : (t.ty3 > 0 ? "+" : "") + t.ty3,
      "_ty": t.ty3 === null ? -999 : t.ty3,
      "成員數": t.n,
      "前5大營收成員": revmomMemberLinks(t) +
        " <a href=\"javascript:void(0)\" onclick=\"jumpToRevmom('" + g + "')\" title=\"跳題材動能與共振頁看營收圖\">📈</a>",
    });
  });
  const el = document.getElementById("revmomNowTable");
  el._sortState = {colIndex: 1, dir: -1};
  buildTable(el, [
    {key: "題材", label: "題材", sortKey: "_g"},
    {key: "信心", label: "信心", sortKey: "_sc", numeric: true},
    {key: "score", label: "score"},
    {key: "近3月MoM%", label: "近3月MoM%(新→舊)"},
    {key: "近3月YoY均%", label: "近3月YoY均%", sortKey: "_ty", numeric: true},
    {key: "成員數", label: "FinMind成員數", numeric: true},
    {key: "前5大營收成員", label: "前5大營收成員(12月平均占比)"},
  ], rows);
  const trig = rows.filter(function(r) { return r._sc === 4; }).length;
  const btn = document.getElementById("sigViewRevmomBtn");
  if (btn && trig) btn.innerHTML = "題材營收動能 🔔" + trig;

  // 持有中：近5個資料月中sig=4且今日在[進場,約到期]內；進場未到=等進場
  const hold = [];
  const today = new Date();
  Object.keys(themes).forEach(function(g) {
    const t = themes[g];
    const L = t.months.length;
    for (let i = Math.max(0, L - 5); i < L; i++) {
      if (t.sig[i] !== 4) continue;
      const sm = ymAdd(t.months[i], 2);
      const entry = new Date(sm + "-15T00:00:00");
      const expiry = new Date(entry.getTime() + 87 * 86400000);
      if (today > expiry) continue;
      hold.push({"題材": themeLink(g), "_g": g, "訊號月": sm,
                 "進場日(口徑)": sm + "-15" + (today < entry ? "（等進場）" : ""),
                 "約到期": expiry.toISOString().slice(0, 10),
                 "前5大營收成員": revmomMemberLinks(t) +
                   " <a href=\"javascript:void(0)\" onclick=\"jumpToRevmom('" + g + "')\" title=\"跳題材動能與共振頁看營收圖\">📈</a>"});
    }
  });
  buildTable(document.getElementById("revmomHoldTable"), [
    {key: "題材", label: "題材", sortKey: "_g"}, {key: "訊號月", label: "訊號月"},
    {key: "進場日(口徑)", label: "進場日(口徑)"}, {key: "約到期", label: "約到期(60交易日)"},
    {key: "前5大營收成員", label: "前5大營收成員(12月平均占比,回測口徑=全成員等權)"},
  ], hold);
}

// ── 🔥多週期題材共振(2026-07-22上線,研究稿) ─────────────────────
function renderResoTab() {
  const el = document.getElementById("resoTable");
  if (!el) return;
  const evs = DATA.resonance_current || [];
  document.getElementById("resoAsof").textContent = evs.length
    ? "資料至 " + DATA.resonance_asof + "｜最近8週內共振事件 " + evs.length + " 筆(題材-週)"
    : "最近8週內無共振事件(需先跑 build_resonance_theme.py 產生/刷新 tmp_resonance_theme_events.pkl)";
  const rows = evs.map(function(e) {
    return {
      "題材": themeLink(e.theme), "_g": e.theme,
      "觸發週": e.week,
      "至今幾週": e.weeks_ago === 0 ? "本週" : e.weeks_ago + "週前",
      "同振數": e.n_members, "_n": e.n_members,
      "成員": e.members.map(function(m) {
        return "<a href=\"javascript:void(0)\" onclick=\"jumpToCompany('台|" + m.code + "');showTab(2)\" "
          + "style=\"color:inherit;border-bottom:1px dotted var(--tx3);text-decoration:none\">"
          + m.code + " " + m.name + "</a>";
      }).join("、"),
    };
  });
  rows.sort(function(a, b) { return e_ago(a) - e_ago(b) || b._n - a._n; });
  function e_ago(r) { return r["至今幾週"] === "本週" ? 0 : parseInt(r["至今幾週"], 10); }
  buildTable(el, [
    {key: "題材", label: "題材", sortKey: "_g"},
    {key: "觸發週", label: "觸發週"},
    {key: "至今幾週", label: "至今幾週"},
    {key: "同振數", label: "同振數", sortKey: "_n", numeric: true},
    {key: "成員", label: "成員(點跳單股)"},
  ], rows);
}

// ── 處置股觀察(2026-07-16上線) ───────────────────────────────
function renderDispoTab() {
  const dp = DATA.disposition || {};
  const el = document.getElementById("dispoNowTable");
  if (!el) return;
  const now = new Date();
  const t = now.getFullYear() + "-" + String(now.getMonth() + 1).padStart(2, "0") + "-" +
            String(now.getDate()).padStart(2, "0");
  let nAction = 0;
  // 2026-07-19: 拆股票(4位數)/CB(5-6位數)兩表+分盤/Tier篩選(使用者需求)
  const allRows = dp.rows || [];
  const rows = allRows.filter(function(r) { return String(r.code).length === 4; }).map(function(r) {
    let act, actRank;
    if (r.poison) { act = "⚠避開（人工管制類，回測−4.7%/38%）"; actRank = 9; }
    else if (t > r.exitd) { act = "已出關（" + r.exitd + " 開盤=出場點）"; actRank = 8; }
    else if (t === r.exitd) { act = "⏰ 今日開盤出場（出關日）"; actRank = 0; }
    else if (t === r.end) { act = "⏰ 持有者：明日（" + r.exitd + "）開盤出場"; actRank = 1; }
    else if (t === r.v5d) { act = "🔔 今日尾盤＝V5買點（出關前倒數第3日）"; actRank = 0; }
    else if (t === r.v4d) { act = "🔔 今日尾盤＝V4買點（第3處置日）"; actRank = 0; }
    else if (t < r.v4d) { act = "等V4買點 " + r.v4d; actRank = 3; }
    else if (t < r.v5d) { act = "V5買點 " + r.v5d + "｜持有者抱至出關"; actRank = 2; }
    else { act = "持有至出關 " + r.exitd + " 開盤"; actRank = 2; }
    if (actRank <= 1 && !r.poison) nAction++;
    const nm = r.code + " " + (r.name || "");
    const link = (DATA.company_history && DATA.company_history["台|" + r.code])
      ? "<a href=\"javascript:void(0)\" onclick=\"jumpToCompany('台|" + r.code + "');showTab(2)\"" +
        " style=\"color:inherit;border-bottom:1px dotted var(--tx3);text-decoration:none\">" + nm + "</a>"
      : nm;
    let warn = [];
    if (r.tv3 !== null && r.tv3 < 0.3) warn.push("⚠量小" + r.tv3 + "億");
    if (r.pre !== null && r.pre > 10) warn.push("⚠前段已漲(樂透格)");
    const tier = (r.theme && r.mins === "20") ? 1 : (r.theme ? 2 : (r.mins === "20" ? 3 : 4));
    return {
      "股票": link, "_c": r.code, "_mins": String(r.mins),
      "Tier": "T" + tier, "_tier": tier,
      "題材": r.theme ? themeLink(r.theme) : "—", "_th": r.theme || "",
      "處置": r.cum + "次/" + r.mins + "分盤" + (r.mkt === "上櫃" ? "·櫃" : ""),
      "_sev": (r.mins === "20" ? 1 : 0),
      "期間": r.start.slice(5) + "~" + r.end.slice(5) + "（已走" + r.seq + "日）",
      "前段%": r.pre === null ? "—" : ((r.pre > 0 ? "+" : "") + r.pre + "%"), "_pre": r.pre === null ? 0 : r.pre,
      "胃納": r.cap === null || r.cap === undefined ? "—" : r.cap + "億", "_cap": r.cap || 0,
      "第3日值": r.tv3 === null ? "—" : r.tv3 + "億", "_tv": r.tv3 === null ? 0 : r.tv3,
      "行動": act + (warn.length ? "　" + warn.join(" ") : ""), "_ar": actRank,
    };
  });
  // 篩選只影響顯示,行動鈴數(nAction)看全部股票列
  const fMins = (document.getElementById("dispoFilterMins") || {}).value || "";
  const fTier = (document.getElementById("dispoFilterTier") || {}).value || "";
  let shown = rows;
  if (fMins) shown = shown.filter(function(r) { return r._mins === fMins; });
  if (fTier) shown = shown.filter(function(r) { return String(r._tier) === fTier; });
  el._sortState = {colIndex: 8, dir: 1};
  buildTable(el, [
    {key: "股票", label: "股票", sortKey: "_c"},
    {key: "Tier", label: "Tier", sortKey: "_tier", numeric: true},
    {key: "題材", label: "題材(加分項)", sortKey: "_th"},
    {key: "處置", label: "第N次/分盤", sortKey: "_sev", numeric: true},
    {key: "期間", label: "處置期間"},
    {key: "前段%", label: "前段報酬", sortKey: "_pre", numeric: true},
    {key: "胃納", label: "胃納(前20日均值)", sortKey: "_cap", numeric: true},
    {key: "第3日值", label: "第3日成交值", sortKey: "_tv", numeric: true},
    {key: "行動", label: "行動（依今日日期自動判定）", sortKey: "_ar", numeric: true},
  ], shown, function(r) { return r._ar === 0 ? "hl-row" : null; });
  // CB處置表(5-6位數代碼,對應股票=前4碼)
  const cbEl = document.getElementById("dispoCbTable");
  if (cbEl) {
    const cbRows = allRows.filter(function(r) { return String(r.code).length > 4; }).map(function(r) {
      const stk = String(r.code).slice(0, 4);
      const stkLink = (DATA.company_history && DATA.company_history["台|" + stk])
        ? "<a href=\"javascript:void(0)\" onclick=\"jumpToCompany('台|" + stk + "');showTab(2)\"" +
          " style=\"color:inherit;border-bottom:1px dotted var(--tx3);text-decoration:none\">" + stk + "</a>"
        : stk;
      return {
        "CB代碼": r.code + " " + (r.name || ""), "_c": r.code,
        "對應股票": stkLink, "_s": stk,
        "處置": r.cum + "次/" + r.mins + "分盤" + (r.mkt === "上櫃" ? "·櫃" : ""), "_sev": (r.mins === "20" ? 1 : 0),
        "期間": r.start.slice(5) + "~" + r.end.slice(5) + "（已走" + r.seq + "日）",
        "備註": r.poison ? "⚠人工管制" : "",
      };
    });
    buildTable(cbEl, [
      {key: "CB代碼", label: "CB代碼", sortKey: "_c"},
      {key: "對應股票", label: "對應股票", sortKey: "_s"},
      {key: "處置", label: "第N次/分盤", sortKey: "_sev", numeric: true},
      {key: "期間", label: "處置期間"},
      {key: "備註", label: "備註"},
    ], cbRows, null);
  }
  const nCb = allRows.length - rows.length;
  document.getElementById("dispoAsof").textContent =
    "價格資料至 " + (dp.asof || "—") + "｜視窗內股票 " + rows.length + " 檔（顯示 " + shown.length + "）＋CB " +
    nCb + " 檔｜行動日為平日近似，遇休市順延，以官方公告為準";
  const btn = document.getElementById("sigViewDispoBtn");
  if (btn && nAction) btn.innerHTML = "處置股觀察 🔔" + nAction;
}

function renderRevmomChart() {
  const tm = DATA.theme_momentum || {};
  const g = document.getElementById("revmomTheme").value;
  const t = (tm.themes || {})[g];
  const el = document.getElementById("revmomChart");
  if (!t) { Plotly.purge(el); document.getElementById("revmomMembers").innerHTML = ""; return; }
  const n = +document.getElementById("revmomRange").value;
  const s = Math.max(0, t.months.length - n);
  const months = t.months.slice(s), rev = t.rev.slice(s), mom = t.mom.slice(s),
        yoy = t.yoy.slice(s), sig = t.sig.slice(s);
  const sigX = [], sigY = [];
  months.forEach(function(m, i) { if (sig[i] === 4) { sigX.push(m); sigY.push(rev[i]); } });
  Plotly.newPlot(el, [
    {x: months, y: rev, type: "bar", name: "月營收(億)", marker: {color: "rgba(60,140,240,.55)"}},
    {x: months, y: mom, mode: "lines", name: "MoM%", yaxis: "y2", line: {color: "#d49610", width: 1.5}},
    {x: months, y: yoy, mode: "lines", name: "YoY%", yaxis: "y2", line: {color: "#34b87a", width: 1.5}},
    {x: sigX, y: sigY, mode: "markers", name: "月營收訊號▲", marker: {symbol: "triangle-up", size: 11, color: "#e84545"}},
  ], {
    title: {text: g + "　月營收動能（成員" + t.n + "家加總）", font: {size: 14}},
    yaxis: {title: {text: "營收(億)", font: {size: 11}}},
    yaxis2: {title: {text: "%", font: {size: 11}}, overlaying: "y", side: "right",
             zeroline: true, zerolinecolor: "rgba(212,221,232,.25)"},
    hovermode: "x unified",
    paper_bgcolor: "#0c1118", plot_bgcolor: "#131c27", font: {color: "#d4dde8"},
    legend: {orientation: "h", y: 1.12, font: {size: 11}},
    margin: {t: 60, b: 40},
  }, {responsive: true});
  const rows = (t.top5 || []).map(function(m) {
    const link = (DATA.company_history && DATA.company_history["台|" + m[0]])
      ? "<a href=\"javascript:void(0)\" onclick=\"jumpToCompany('台|" + m[0] + "')\" style=\"color:inherit;border-bottom:1px dotted var(--tx3);text-decoration:none\">" + m[0] + " " + m[1] + "</a>"
      : m[0] + " " + m[1];
    return {"成員": link, "占題材營收%": m[2] === null ? "—" : m[2],
            "最新月營收(億)": m[3] === null ? "—" : m[3], "最新月YoY%": m[4] === null ? "—" : m[4]};
  });
  buildTable(document.getElementById("revmomMembers"), [
    {key: "成員", label: "前5大營收成員"},
    {key: "占題材營收%", label: "占題材營收%(12月平均)", numeric: true},
    {key: "最新月營收(億)", label: "最新月營收(億)", numeric: true},
    {key: "最新月YoY%", label: "最新月YoY%", numeric: true},
  ], rows);
}

function switchHistView(v) {
  ["Revmom", "Res", "Company"].forEach(function(k) {
    const on = v === k.toLowerCase();
    document.getElementById("histView" + k + "Btn").classList.toggle("active", on);
    document.getElementById("hist" + k + "View").style.display = on ? "" : "none";
  });
  // 切到可見後重繪,避免Plotly在display:none容器下的尺寸問題
  if (v === "revmom") renderRevmomChart();
  else if (v === "res") renderResonance();
  else if (v === "company") renderCompanyHistory();
}

function jumpToRevmom(g) {
  showTab(2);
  switchHistView("revmom");
  const sel = document.getElementById("revmomTheme");
  if (sel) { sel.value = g; renderRevmomChart(); }
  const el = document.getElementById("revmomChart");
  if (el) el.scrollIntoView({behavior: "smooth", block: "center"});
}

function init() {
  document.getElementById("latestDate").textContent = DATA.latest_date;
  if (DATA.previous_date) {
    document.getElementById("hintTheme").textContent += ` 跟上次快照(${DATA.previous_date})比較的Δ欄位已顯示。`;
    document.getElementById("hintFull").textContent += ` 跟上次快照(${DATA.previous_date})比較的Δ欄位已顯示。`;
  }
  const groupSet = new Set();
  DATA.theme_pivot_all.forEach(p => groupSet.add(p.main_group));
  const groupSel = document.getElementById("groupFilter");
  Array.from(groupSet).sort().forEach(g => {
    const opt = document.createElement("option"); opt.value = g; opt.textContent = g; groupSel.appendChild(opt);
  });
  initSearchBox("companySearch", "companyDropdown", "companyPick",
    DATA.company_list.map(c => ({value: c.key, label: c.label})),
    addHistCompany);
  initSearchBox("themeHistSearch", "themeHistDropdown", "themeHistPick",
    DATA.theme_list.map(g => ({value: g, label: g})),
    renderThemeHistory);
  const themeHistSel = document.getElementById("themeHistPick");
  DATA.theme_list.forEach(g => {
    const opt = document.createElement("option"); opt.value = g; opt.textContent = g; themeHistSel.appendChild(opt);
  });
  const newsGroupSet = new Set(), newsTypeSet = new Set();
  DATA.theme_news.forEach(n => { newsGroupSet.add(n["主族群"]); newsTypeSet.add(n["類型"]); });
  const newsGroupSel = document.getElementById("newsGroupFilter");
  Array.from(newsGroupSet).sort().forEach(g => {
    const opt = document.createElement("option"); opt.value = g; opt.textContent = g; newsGroupSel.appendChild(opt);
  });
  const newsTypeSel = document.getElementById("newsTypeFilter");
  Array.from(newsTypeSet).sort().forEach(t => {
    const opt = document.createElement("option"); opt.value = t; opt.textContent = t; newsTypeSel.appendChild(opt);
  });

  renderBanner();
  renderThemePivot();
  renderRotationHeatmap();
  renderFullTable();
  renderEarningsTab();
  renderNewsTable();
  initSupplyChain();
  renderRadar();
  renderSignalTab();
  const tmThemes = (DATA.theme_momentum || {}).themes || {};
  const tmSel = document.getElementById("revmomTheme");
  Object.keys(tmThemes).sort(function(a, b) {
    return (tmThemes[b].score - tmThemes[a].score) || a.localeCompare(b);
  }).forEach(function(g) {
    const o = document.createElement("option");
    o.value = g;
    o.textContent = g + (tmThemes[g].score === 4 ? " ▲" : "");
    tmSel.appendChild(o);
  });
  if (tmSel.options.length) renderRevmomChart();
  renderRevmomTab();
  renderDispoTab();
  renderResoTab();
  renderThermoTab();
  renderConfNotes();
  if (DATA.company_list.length) renderCompanyHistory();
  else {
    // 省容量模式: 整個「個股/題材歷史」子頁簽藏掉(SLIM_HISTORY=False重跑即恢復)
    const hb = document.getElementById("histViewCompanyBtn");
    if (hb) hb.style.display = "none";
    const cs = document.getElementById("companySearch");
    if (cs) { cs.placeholder = "個股歷史趨勢已停用(省容量模式)——export_html.py 開頭 SLIM_HISTORY=False 重跑即恢復"; cs.disabled = true; }
  }
  initResonance();
  renderHealthBar();
  renderPledgeView();
}
init();
</script>
<div id="themeMemberModal" onclick="if(event.target===this)this.style.display='none'"><div class="tm-body"></div></div>
</body>
</html>
"""

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--local", action="store_true",
                        help="產出離線版（Plotly 內嵌，存入 本地版/ 資料夾，不推 GitHub）")
    args = parser.parse_args()

    data = build()
    render_html(data)                                          # 給 GitHub Pages 的版本

    if args.local:
        import pathlib
        pathlib.Path("本地版").mkdir(exist_ok=True)
        render_html(data, out_path="本地版/dashboard.html", local=True)
        print("本地離線版已產出：本地版/dashboard.html")
