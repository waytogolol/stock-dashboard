# -*- coding: utf-8 -*-
"""把 capital_flow.db 匯出成一個獨立的 dashboard.html，雙擊就能在瀏覽器打開，不需要跑streamlit/python。
用法: python export_html.py
"""
import json
import os
import sqlite3
from datetime import datetime

import pandas as pd

DB_PATH = "capital_flow.db"
OUT_PATH = "dashboard.html"

BROAD_GROUPS = {
    "金融", "科技(綜合)", "生技醫藥", "消費(非必需)", "工業", "傳統產業", "傳統消費", "公用事業", "能源",
    "不動產", "電信", "傳統產業/原材料", "電力設備", "控股公司", "航運", "造船", "商社", "商社/建設",
    "汽車", "其他", "未分類", "媒體/娛樂", "遊戲/娛樂", "品牌3C", "IT/系統整合", "網路服務", "人力資源",
    "工業電腦/物聯網", "IC通路", "安防設備",
}

UNIT_YI_LABEL = {"TWD": "億元", "KRW": "億韓元", "JPY_million": "億日圓", "CNY": "億人民幣", "USD": "億美元"}
COUNTRIES = ["台", "日", "美", "韓", "陸"]


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

    all_dates = sorted(rankings["snapshot_date"].unique())
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
        print(f"週收盤價未載入(可先跑 fetch_prices.py): {e}")
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
        print(f"題材國別子分數計算失敗: {e}")
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
        "theme_country_history": data_theme_country,
        "countries": COUNTRIES,
        "snapshot_dates": sorted(rankings["snapshot_date"].unique().tolist()),
        "theme_pivot_all": theme_pivot_all,
        "theme_pivot_thematic": theme_pivot_thematic,
        "theme_detail": theme_detail,
        "theme_history": theme_history,
        "theme_list": sorted(theme_history.keys()),
        "theme_list_thematic": sorted(g for g in theme_history.keys() if g not in BROAD_GROUPS),
        "full_records": full_records,
        "company_history": company_history,
        "company_list": sorted(
            [{"key": k, "label": v["label"]} for k, v in company_history.items()],
            key=lambda x: x["label"],
        ),
        "us_earnings": load_earnings_csv("us_earnings_watch.csv"),
        "tw_earnings": load_earnings_csv("tw_earnings_watch.csv"),
        "jpkr_earnings": load_earnings_csv("jp_kr_earnings_watch.csv"),
        "theme_news": pd.read_csv("theme_news.csv").to_dict("records") if os.path.exists("theme_news.csv") else [],
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
        print(f"基本面資料未載入(可先跑 fetch_fundamentals.py): {e}")

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
        print(f"陸股東財標籤未載入(可先跑 fetch_cn_eastmoney.py): {e}")

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
        print(f"capex未載入(可先跑 fetch_capex.py): {e}")
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
        print(f"供應鏈資料載入失敗: {e}")
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
            chk["n_ok"] = sum([chk["streak_ok"], chk["breadth_ok"], chk["rising_ok"], chk["share_ok"]])
            if chk["n_ok"] == 4:
                chk["verdict"] = "🟢 黃金訊號" if chk["pos"] < 70 else "🟡 觸發(高位階慎追)"
            else:
                chk["verdict"] = ""
            sig_current.append(chk)
        sig_current.sort(key=lambda x: (-x["n_ok"], -x["score"]))
        sig_history.sort(key=lambda x: x["date"], reverse=True)
        data["signal_current"] = sig_current
        data["signal_history"] = sig_history
    except Exception as e:
        print(f"進場訊號計算失敗: {e}")
        data["signal_current"] = []
        data["signal_history"] = []

    # 微題材脈衝雷達（規則v2：脈衝>=2.5x + 跳升中位>=+35名 + 毛利方向分級）
    try:
        import statistics

        from micro_themes import MICRO_THEMES
        conn_m = sqlite3.connect(DB_PATH)
        subp = pd.read_sql("SELECT DISTINCT code, sub_product FROM classification WHERE country='台'", conn_m)
        mh = pd.read_sql("SELECT code, quarter, gm FROM margin_history", conn_m)
        conn_m.close()
        mdir = {}
        for code, g in mh.groupby("code"):
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
                level = "🅰 脈衝+毛利升" if nd and up * 2 >= nd else "🅱 脈衝(待季報驗證)"
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
        micro_current.sort(key=lambda x: -(x["pulse"] or 0))
        micro_hist.sort(key=lambda x: x["date"], reverse=True)
        data["micro_current"] = micro_current
        data["micro_history"] = micro_hist
    except Exception as e:
        print(f"微題材雷達計算失敗: {e}")
        data["micro_current"] = []
        data["micro_history"] = []

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
        print(f"產業鏈資料載入失敗: {e}")
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
        print(f"公司資訊面板資料失敗: {e}")
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
        catchup_rows.sort(key=lambda r: (-r["n_tags"], r["pb"] if r["pb"] is not None else 99))
        data["catchup_radar"] = {"themes": sorted(ignited), "rows": catchup_rows[:60]}
    except Exception as e:
        print(f"補漲雷達計算失敗: {e}")
        data["catchup_radar"] = {"themes": [], "rows": []}

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
        ]
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
            _item("PB估值(官方)", _q("SELECT MAX(updated) FROM tw_valuation"), 40, 80, "每月"),
            _item("五國基本面(yf)", _q("SELECT MAX(updated) FROM fundamentals"), 100, 150, "每季"),
            _item("微題材毛利", _q("SELECT MAX(updated) FROM margin_history"), 100, 150, "每季"),
            _item("資本支出(yf)", _q("SELECT MAX(updated) FROM capex_history"), 100, 150, "每季"),
            _item("供應鏈標註", data.get("supply_last_updated"), 60, 120, "手動(Gemini)"),
        ]
        conn_h.close()
        data["health"] = health
    except Exception as e:
        print(f"資料健康列計算失敗: {e}")
        data["health"] = []

    return data


def render_html(data, out_path=OUT_PATH, local=False):
    data_json = json.dumps(data, ensure_ascii=False)
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
.cal-evt.fire { animation: pulse 1.2s infinite; }
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
  <button class="tab-btn" onclick="showTab(2)">公司歷史趨勢</button>
  <button class="tab-btn" onclick="showTab(1)">排行榜明細</button>
  <button class="tab-btn" onclick="showTab(3)">財報/法說會提醒</button>
  <button class="tab-btn" onclick="showTab(4)">新聞/目標價</button>
</div>
</div>

<div class="tab-content active" id="tab0">
  <div class="controls">
    <label><input type="checkbox" id="onlyThematic" checked onchange="renderThemePivot()"> 只看題材概念股(排除金融/消費/傳統產業等廣義分類)</label>
  </div>
  <div class="hint" id="hintTheme">熱度分數 = 該題材在每個國家的「台幣金額 ÷ 該國全部上榜公司台幣金額總和」百分比，五國加總而成。分數越高表示資金集中度越高，不是只看公司數量。點欄位標題可排序。</div>
  <div class="scroll-box"><table id="themePivotTable"></table></div>
  <div class="controls" style="margin-top:12px">
    對比期間：<select id="moverPeriod" onchange="renderMoversChart()">
      <option value="1" selected>上一次快照</option>
      <option value="2">2週前</option>
      <option value="4">4週前(月)</option>
      <option value="8">8週前</option>
      <option value="12">12週前(季)</option>
    </select>
    <label><input type="checkbox" id="hmIncludeBroad" checked onchange="renderMoversChart(); renderRotationHeatmap()"> 含金融/傳產等廣義分類(觀察避險資金)</label>
  </div>
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
  <div class="hint">列標籤附「目前分數·自身位階%」(位階=目前分數在顯示範圍內自身高低的百分位)。建議配對：<b>位階排序+相對色階</b>=看錢往哪動(正在發動的在上)；<b>熱度排序+絕對色階</b>=看錢在哪(資金量層次)。只含有台股公司的題材，滑鼠停留可看實際分數。</div>
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
  <div class="hint">上圖=該題材在五市場的資金份額子分數，◆=點火週(份額週變化&gt;1個標準差)——看哪個市場先動。中圖=集中度：台股第1大成員佔題材台股金額%，上升=龍頭獨走、下降=擴散(全員行情較健康)。下表=台股成員點火時序，最早點火標🐑。<b>提醒</b>：回測顯示跨市場接力僅弱訊號(最強=韓→台 lift 1.19)、領頭羊帶動整體 lift 1.15——先後順序是「觀察起點」不是「買進理由」，決策仍看位階+廣度。</div>
  <div id="anaChart" style="height:340px"></div>
  <div id="anaConc" style="height:130px"></div>
  <div class="scroll-box"><table id="anaTable"></table></div>
  <hr style="border:none;border-top:1px solid var(--bd);margin:20px 0">
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

<div class="tab-content" id="tab3">
  <div class="hint">這個分頁是 `check_earnings.py` 上次執行結果的快照，要更新請在終端機跑 <code>python check_earnings.py</code> 後重新產生 dashboard.html。🔥=3天內 🟠=7天內。</div>
  <div class="cal-wrap">
    <div class="cal-nav">
      <button onclick="calMove(-1)">&#9664;</button>
      <span id="calTitle"></span>
      <button onclick="calMove(1)">&#9654;</button>
    </div>
    <div class="cal-grid" id="calGrid"></div>
  </div>
  <h4>美股財報 <span id="usEarningsMtime" style="color:#888;font-size:12px;"></span></h4>
  <div class="scroll-box"><table id="usEarningsTable"></table></div>
  <h4>台股法說會 <span id="twEarningsMtime" style="color:#888;font-size:12px;"></span></h4>
  <div class="scroll-box"><table id="twEarningsTable"></table></div>
  <h4>日韓陸財報日 <span id="jpkrEarningsMtime" style="color:#888;font-size:12px;"></span></h4>
  <div class="hint">日韓=Yahoo(yfinance calendar，日股覆蓋率高、韓股約1/3)；陸=東方財富披露預約(整批API)。各市場前100大、僅未來90天，更新跑 <code>python fetch_earnings_dates.py</code>。歷史財報日累積於DB earnings_dates表(事件研究用)，回補跑 <code>python fetch_earnings_history.py</code>。</div>
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
  </div>
  <div id="sigMacroView">
  <h3 class="sec-title">檢查清單規則（源自記憶體2025/9案例研究，勿刪）</h3>
  <div class="rule-card">
    <div class="rule-item">① <b>連漲 ≥2 週</b>——熱度分數連續上升，排除單週噪音</div>
    <div class="rule-item">② <b>廣度 ≥50% 且連續兩週</b>——題材內過半個股排名上升，全族群行情而非一兩檔獨秀</div>
    <div class="rule-item">③ <b>≥3 國子分數同步上升</b>——跨市場共振（記憶體9月真起漲=4國齊升）</div>
    <div class="rule-item">④ <b>最大單國佔比 &lt;80%</b>——排除單國獨撐假訊號（2025年5-8月記憶體假訊號=韓國佔85%+）</div>
    <div class="rule-item">⑤ 四條全過後看位階：<b>位階 &lt;70% = 🟢 黃金訊號</b>（歷史勝率~6成、所有大倍率案例都在這組）；<b>位階 ≥70% = 🟡 慎追</b>（勝率~3成半，要求廣度連3週等更嚴確認）</div>
    <div class="rule-item">⑥ <b>基本面確認（僅輔助，勿當主決策）</b>——訊號觸發時看題材成員「EPS預估成長比例」與「季營收YoY為正比例」：兩者過半=資金與基本面共振；資金熱但比例低=純題材炒作警覺。<b>資料源限制務必留意</b>：EPS欄=yfinance分析師共識的forward vs trailing比較（是「預估成長」非嚴格「上修」）；小型股可能僅1-2位分析師覆蓋、台股上櫃與陸股品質更弱、共識調整常滯後於行情；且無法回測（歷史預估不可得）。營收YoY為已公告實績，可信度高於EPS欄。</div>
    <div class="rule-item" style="color:var(--tx3)">回測基礎：2025-04~2026-07共43次觸發，+8週熱度上漲比例42.5%，賺賠比不對稱（贏1.5-3.9x/輸0.7-0.9x）。倍率為熱度分數非股價。台股跟隨美韓約5週：「美韓子分數高檔+台股低檔」=預備窗。已知盲點：微題材（ABF載板/導線架等細分產品層級）的脈衝式行情會被規則①②漏接，微題材專用規則開發中。</div>
  </div>
  <h3 class="sec-title">本週檢查表（每次資料更新自動重算）</h3>
  <div class="hint">依通過條數排序。✓/✗ 對應規則①~④；觸發中的題材可去「產業鏈視圖」看上中下游誰先動、動能雷達看象限位置。</div>
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
    <div class="rule-item">③ 毛利率方向分級：<b>🅰 = 有資料成員過半最新季毛利QoQ走升</b>（漲價週期確認）；<b>🅱 = 尚未轉升</b>（資金先行，把下個季報日當驗證點：Q1→5月中/Q2→8月中/Q3→11月中/Q4→3月底）</div>
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
    <div class="rule-item" style="color:var(--tx3)">定位=研究清單非買進清單：進場等的是成員「自己的點火」(排名跳升/加入廣度)；符合條件但遲遲不點火=市場不認同，放掉。毛利QoQ方向(Q2財報後官方資料就有兩季可比)與合約負債(MOPS簡表無此細項，需XBRL/FinMind)待資料到位後補上。</div>
  </div>
  <div class="hint" id="catchupThemes"></div>
  <div class="scroll-box"><table id="catchupTable"></table></div>
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
  document.getElementById("resTheme").innerHTML = themes.map(function(g) {
    return "<option value=\"" + g + "\">" + g + "（" + (score[g] || 0).toFixed(1) + "）</option>";
  }).join("");
  if (themes.length) renderResonance();
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
      title: {text: theme + "　五市場子分數與點火週（◆）", font: {size: 14}},
      yaxis: {title: {text: "子分數(份額%)", font: {size: 11}}},
      paper_bgcolor: "#0c1118", plot_bgcolor: "#131c27", font: {color: "#d4dde8"},
      legend: {orientation: "h", y: 1.14, font: {size: 11}},
      hovermode: "x unified", margin: {t: 46, b: 36},
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
    return {
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
          (info.g.length ? info.g.map(function(g) { return "<span class=\"chip\" style=\"padding:1px 8px\">" + g + "</span>"; }).join(" ") : "未分類") +
          (info.sub ? "　<span style=\"color:var(--tx3)\">" + info.sub + "</span>" : "") + "</div>";
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
  html += "</div>";
  el.innerHTML = html;
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

function renderEarningsTab() {
  document.getElementById("usEarningsMtime").textContent = DATA.us_earnings.mtime ? `(最後查詢: ${DATA.us_earnings.mtime})` : "(尚未查詢過)";
  document.getElementById("twEarningsMtime").textContent = DATA.tw_earnings.mtime ? `(最後查詢: ${DATA.tw_earnings.mtime})` : "(尚未查詢過)";

  const usCols = [
    {key: "日期", label: "日期"}, {key: "時段", label: "時段"}, {key: "代碼", label: "代碼"},
    {key: "公司", label: "公司"}, {key: "成交金額排名", label: "排名", numeric: true},
    {key: "主族群", label: "主族群"}, {key: "市值", label: "市值"}, {key: "EPS預估", label: "EPS預估"},
  ];
  buildTable(document.getElementById("usEarningsTable"), usCols, DATA.us_earnings.rows, r => earningsTierClass(r["日期"]));

  const twCols = [
    {key: "日期", label: "日期"}, {key: "時間", label: "時間"}, {key: "代碼", label: "代碼"},
    {key: "公司", label: "公司"}, {key: "成交金額排名", label: "排名", numeric: true}, {key: "主族群", label: "主族群"},
  ];
  buildTable(document.getElementById("twEarningsTable"), twCols, DATA.tw_earnings.rows, r => earningsTierClass(r["日期"]));

  const jpkr = DATA.jpkr_earnings || {rows: []};
  document.getElementById("jpkrEarningsMtime").textContent = jpkr.mtime ? `(最後查詢: ${jpkr.mtime})` : "(尚未查詢過)";
  const jpkrCols = [
    {key: "日期", label: "日期"}, {key: "市場", label: "市場"}, {key: "代碼", label: "代碼"},
    {key: "公司", label: "公司"}, {key: "成交金額排名", label: "排名", numeric: true}, {key: "主族群", label: "主族群"},
  ];
  buildTable(document.getElementById("jpkrEarningsTable"), jpkrCols, jpkr.rows, r => earningsTierClass(r["日期"]));

  // 初始化日曆：顯示當月
  const _now = new Date();
  renderCalendar(_now.getFullYear(), _now.getMonth());
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
    m[d].push({label: r["代碼"] + " " + r["公司"], market: "tw", date: d});
  });
  (DATA.us_earnings.rows || []).forEach(r => {
    const d = r["日期"]; if (!d) return;
    if (!m[d]) m[d] = [];
    m[d].push({label: r["代碼"], market: "us", date: d});
  });
  ((DATA.jpkr_earnings || {}).rows || []).forEach(r => {
    const d = r["日期"]; if (!d) return;
    if (!m[d]) m[d] = [];
    m[d].push({label: r["市場"] + " " + (r["公司"] || r["代碼"]), market: "jpkr", date: d});
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
    parts.push("🔔 進場訊號 <b class=\"wb-up\">" + sigs.map(function(c) { return themeLink(c.theme) + (c.pos < 70 ? "🟢" : "🟡"); }).join("、") + "</b>");
  }
  const mic = (DATA.micro_current || []).filter(function(c) { return c.level; });
  if (mic.length) {
    parts.push("🔔 微題材脈衝 <b class=\"wb-up\">" + mic.map(function(c) { return c.theme + (c.level.indexOf("🅰") >= 0 ? "🅰" : "🅱") + (c.second ? "⚠" : ""); }).join("、") + "</b>");
  }
  if (!parts.length) return;
  const el = document.getElementById("weeklyBanner");
  el.innerHTML = "📌 " + parts.join("<span class=\"wb-sep\"> · </span>");
  el.style.display = "flex";
}

// ── 進場訊號頁籤 ──────────────────────────────────────────────────────
function switchSigView(v) {
  ["Macro", "Micro", "Catchup"].forEach(function(k) {
    const on = v === k.toLowerCase();
    document.getElementById("sigView" + k + "Btn").classList.toggle("active", on);
    document.getElementById("sig" + k + "View").style.display = on ? "" : "none";
  });
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
      "成員": "<a href=\"javascript:void(0)\" onclick=\"jumpToCompany('台|" + r.code + "')\" style=\"color:inherit;border-bottom:1px dotted var(--tx3);text-decoration:none\">" + r.code + " " + r.name + "</a>",
      "最新排名": r.rank, "PB": r.pb, "營收YoY%": r.yoy, "資金位階%": r.pos,
      "埋伏理由": r.tags.join("｜"), "_n": r.n_tags,
    };
  });
  const cuEl = document.getElementById("catchupTable");
  cuEl._sortState = {colIndex: 6, dir: -1};
  buildTable(cuEl, [
    {key: "點火題材", label: "點火題材", sortKey: "_g"}, {key: "成員", label: "成員(未點火)"},
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
    return {
      "微題材": c.theme,
      "判定": (c.level || "—") + (c.second ? " ⚠二次脈衝" : ""),
      "_trig": c.level ? 1 : 0,
      "脈衝x": c.pulse, "跳升中位": c.jump, "本週分數": c.score,
      "毛利方向": c.m_n ? "↗" + c.m_up + "/共" + c.m_n : "—",
      "成員(排名/最新季毛利)": memTxt,
    };
  });
  const microCols = [
    {key: "微題材", label: "微題材"},
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
  const rows = cur.map(function(c) {
    return {
      "題材": themeLink(c.theme), "_g": c.theme,
      "判定": c.verdict || (c.n_ok + "/4"),
      "n_ok": c.n_ok,
      "①連漲": pf(c.streak_ok, c.streak + "週"),
      "②廣度": pf(c.breadth_ok, (c.breadth === null ? "-" : c.breadth + "%") + "/" + (c.breadth_prev === null ? "-" : c.breadth_prev + "%")),
      "③升國": pf(c.rising_ok, c.rising + "國"),
      "④單國佔比": pf(c.share_ok, c.max_share + "%"),
      "位階": c.pos,
      "熱度分數": c.score,
      "階段": c.stage,
      "基本面": (c.eps_up_pct === null ? "—" : "EPS預估成長" + c.eps_up_pct + "%") + "｜" + (c.rg_up_pct === null ? "—" : "營收實績+" + c.rg_up_pct + "%"),
      "eps_up_pct": c.eps_up_pct,
    };
  });
  const cols = [
    {key: "題材", label: "題材", sortKey: "_g"}, {key: "判定", label: "判定", sortKey: "n_ok", numeric: true},
    {key: "①連漲", label: "①連漲≥2週"}, {key: "②廣度", label: "②廣度≥50%×2週"},
    {key: "③升國", label: "③≥3國同升"}, {key: "④單國佔比", label: "④單國<80%"},
    {key: "位階", label: "位階%", numeric: true}, {key: "熱度分數", label: "熱度分數", numeric: true},
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
            "評價": h.pos < 70 ? "🟢低中位階" : "🟡高位階"};
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
  const latestScore = {}, posMap = {};
  themes.forEach(function(g) {
    const s = {};
    (DATA.theme_history[g] || []).forEach(function(r) { s[r.snapshot_date] = r["熱度分數"]; });
    latestScore[g] = s[DATA.latest_date] || 0;
    let mn = Infinity, mx = -Infinity;
    dates.forEach(function(d) { const v = s[d]; if (v !== undefined) { if (v < mn) mn = v; if (v > mx) mx = v; } });
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
  themes.forEach(function(g) {
    const byDate = {};
    (DATA.theme_history[g] || []).forEach(function(r) { byDate[r.snapshot_date] = r["熱度分數"]; });
    const vals = dates.map(function(d) { return byDate[d]; }).filter(function(v) { return v !== undefined; });
    if (!vals.length) return;
    const mx = Math.max.apply(null, vals), mn = Math.min.apply(null, vals);
    html += "<tr><td class=\"hm-name\">" + themeLink(g) + " <span class=\"hm-score\">" + latestScore[g].toFixed(1) + "·位階" + Math.round(posMap[g] * 100) + "%</span></td>";
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
  if (!DATA.theme_history || !DATA.theme_history[g]) return g;   // 微題材等不在雷達內的不加連結
  return "<a class=\"theme-link\" href=\"javascript:void(0)\" onclick=\"jumpToRadar('" + g + "')\" title=\"跳到動能雷達聚焦此題材\">" + g + "</a>";
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

function renderHealthBar() {
  const el = document.getElementById("healthBar");
  const items = DATA.health || [];
  if (!items.length) { el.style.display = "none"; return; }
  const nWarn = items.filter(function(h) { return h.s !== "ok"; }).length;
  let html = DATA.version ? "<span style=\"color:var(--tx3)\">" + DATA.version + "</span>" : "";
  html += "<span style=\"font-weight:600;color:var(--tx2)\">資料健康" +
          (nWarn ? " <span class=\"health-dot warn\"></span>" + nWarn + "項待更新" : " <span class=\"health-dot ok\"></span>全部正常") + "：</span>";
  html += items.map(function(h) {
    const tip = "更新節奏：" + h.c + (h.a !== undefined ? "｜距今" + h.a + "天" : "");
    return "<span class=\"health-item\" title=\"" + tip + "\"><span class=\"health-dot " + h.s + "\"></span>" + h.n + " " + h.d + "</span>";
  }).join("");
  el.innerHTML = html;
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
  if (DATA.company_list.length) renderCompanyHistory();
  initResonance();
  renderHealthBar();
}
init();
</script>
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
