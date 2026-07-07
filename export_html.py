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

    history_cols = ["snapshot_date", "country", "code", "中文名稱", "rank", "金額億", "金額億台幣", "金額億台幣_num"]
    history = rankings[history_cols].sort_values(["country", "code", "snapshot_date"])
    company_history = {}
    for (country, code), g in history.groupby(["country", "code"]):
        key = f"{country}|{code}"
        company_history[key] = {
            "label": f"{country} {code} {g['中文名稱'].iloc[0]}",
            "rows": g[["snapshot_date", "rank", "金額億", "金額億台幣", "金額億台幣_num"]].to_dict("records"),
        }

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

    def load_earnings_csv(path):
        if not os.path.exists(path):
            return {"rows": [], "mtime": None}
        df = pd.read_csv(path, dtype={"代碼": str})
        mtime = datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M")
        return {"rows": df.to_dict("records"), "mtime": mtime}

    data = {
        "latest_date": latest_date,
        "previous_date": previous_date,
        "countries": COUNTRIES,
        "snapshot_dates": sorted(rankings["snapshot_date"].unique().tolist()),
        "theme_pivot_all": theme_pivot_all,
        "theme_pivot_thematic": theme_pivot_thematic,
        "theme_detail": theme_detail,
        "theme_history": theme_history,
        "theme_list": sorted(theme_history.keys()),
        "full_records": full_records,
        "company_history": company_history,
        "company_list": sorted(
            [{"key": k, "label": v["label"]} for k, v in company_history.items()],
            key=lambda x: x["label"],
        ),
        "us_earnings": load_earnings_csv("us_earnings_watch.csv"),
        "tw_earnings": load_earnings_csv("tw_earnings_watch.csv"),
        "theme_news": pd.read_csv("theme_news.csv").to_dict("records") if os.path.exists("theme_news.csv") else [],
    }

    # 供應鏈資料
    try:
        import supply_chain as sc
        latest_lookup = {(r["country"], r["code"]): r for _, r in latest.iterrows()}
        supply_links = []
        for sup_code, sup_country, cust_code, cust_country, product in sc.LINKS:
            info = latest_lookup.get((sup_country, sup_code))
            supply_links.append({
                "supplier_code": sup_code,
                "supplier_country": sup_country,
                "customer_code": cust_code,
                "customer_country": cust_country,
                "product": product,
                "supplier_name": info["中文名稱"] if info is not None else sup_code,
                "supplier_rank": int(info["rank"]) if info is not None else None,
                "supplier_tier": info["熱度"] if info is not None else "",
                "supplier_amount_yi": info["金額億台幣"] if info is not None else "",
            })
        data["supply_links"] = supply_links
        data["supply_last_updated"] = sc.LAST_UPDATED
    except Exception as e:
        print(f"供應鏈資料載入失敗: {e}")
        data["supply_links"] = []
        data["supply_last_updated"] = None

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
  body { font-family: "Microsoft JhengHei", "PingFang TC", sans-serif; background:#1a1a1a; color:#e0e0e0; margin:0; padding:16px 24px; }
  h1 { font-size: 22px; }
  .caption { color:#999; margin-bottom: 16px; }
  .tabs { display:flex; gap:8px; margin-bottom:12px; border-bottom:1px solid #444; }
  .tab-btn { background:none; border:none; color:#aaa; padding:10px 16px; cursor:pointer; font-size:15px; }
  .tab-btn.active { color:#fff; border-bottom:2px solid #4da3ff; font-weight:bold; }
  .tab-content { display:none; }
  .tab-content.active { display:block; }
  table { border-collapse: collapse; width:100%; font-size:13px; margin-bottom: 16px; }
  th, td { border:1px solid #444; padding:6px 10px; text-align:left; white-space:nowrap; }
  th { background:#2a2a2a; cursor:pointer; position:sticky; top:0; user-select:none; }
  th:hover { background:#3a3a3a; }
  th .arrow { font-size: 11px; color:#4da3ff; }
  tr:nth-child(even) { background:#222; }
  select, input { background:#2a2a2a; color:#eee; border:1px solid #555; padding:6px; border-radius:4px; margin-right:8px; }
  .tier-hot { background:#ff6b6b !important; color:#1a1a1a !important; }
  .tier-mid { background:#ffd166 !important; color:#1a1a1a !important; }
  .tier-edge { background:#fff9db !important; color:#1a1a1a !important; }
  .scroll-box { max-height: 600px; overflow-y:auto; border:1px solid #444; }
  .controls { margin-bottom: 12px; }
  .hint { color:#888; font-size:12px; margin-bottom:8px; }
  /* ── 法說會日曆 ── */
  .cal-wrap { margin-bottom:16px; }
  .cal-nav { display:flex; align-items:center; justify-content:space-between; margin-bottom:8px; }
  .cal-nav button { background:#333; border:none; color:#e0e0e0; padding:4px 14px; cursor:pointer; border-radius:4px; font-size:15px; }
  .cal-nav button:hover { background:#444; }
  #calTitle { font-size:15px; font-weight:bold; color:#e0e0e0; }
  .cal-grid { display:grid; grid-template-columns:repeat(7,1fr); gap:3px; }
  .cal-head { text-align:center; color:#888; font-size:12px; padding:4px 0; font-weight:bold; }
  .cal-head.sun { color:#e07070; } .cal-head.sat { color:#7090d0; }
  .cal-cell { min-height:72px; background:#222; border-radius:5px; padding:5px; box-sizing:border-box; }
  .cal-cell.today { background:#12283d; border:1px solid #4da3ff; }
  .cal-cell.out { opacity:0.22; pointer-events:none; }
  .cal-num { font-size:12px; color:#888; margin-bottom:3px; }
  .cal-num.sun { color:#e07070; } .cal-num.sat { color:#7090d0; }
  .cal-cell.today .cal-num { color:#4da3ff; font-weight:bold; font-size:13px; background:#1a4a70; display:inline-block; border-radius:50%; width:20px; height:20px; line-height:20px; text-align:center; margin-bottom:4px; }
  .cal-evt { font-size:10px; border-radius:3px; padding:1px 4px; margin-bottom:2px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; cursor:default; }
  .cal-evt.tw { background:#4a1010; color:#ffaaaa; border-left:2px solid #ff6b6b; }
  .cal-evt.us { background:#0a1f3a; color:#99ccff; border-left:2px solid #4da3ff; }
  .cal-evt.fire { border-left-color:#ff2222; animation:pulse 1.2s infinite; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.6} }
  /* ── 公司搜尋框 ── */
  .search-wrap { display:inline-block; position:relative; width:300px; }
  .search-wrap input { width:100%; box-sizing:border-box; margin:0; }
  .search-dropdown { position:absolute; top:100%; left:0; right:0; background:#2a2a2a; border:1px solid #555; border-radius:4px; max-height:220px; overflow-y:auto; z-index:999; box-shadow:0 4px 12px rgba(0,0,0,.5); }
  .search-item { padding:6px 10px; cursor:pointer; font-size:13px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .search-item:hover { background:#3a3a3a; color:#fff; }
  /* ── 供應鏈頁籤 ── */
  .sc-fresh-warn { background:#3a2a00; border:1px solid #cc8800; color:#ffcc55; padding:10px 14px; border-radius:6px; margin-bottom:14px; }
  .sc-anchors { display:flex; flex-wrap:wrap; gap:8px; margin-bottom:16px; }
  .anchor-btn { background:#2a2a2a; border:1px solid #555; color:#bbb; padding:7px 16px; cursor:pointer; border-radius:6px; font-size:13px; }
  .anchor-btn.active { background:#1a3a5c; border-color:#4da3ff; color:#4da3ff; font-weight:bold; }
  .anchor-btn:hover { background:#333; color:#fff; }
  .sc-country-bar { display:flex; flex-wrap:wrap; gap:10px; margin-bottom:18px; }
  .sc-country-chip { background:#2a2a2a; border:1px solid #444; padding:6px 14px; border-radius:20px; font-size:13px; }
  .chip-hot { color:#ff6b6b; margin-left:4px; }
  .sc-country-section { margin-bottom:24px; }
  .sc-country-title { font-size:14px; font-weight:bold; color:#ccc; margin-bottom:10px; border-bottom:1px solid #333; padding-bottom:6px; }
  .sc-cards-row { display:flex; flex-wrap:wrap; gap:10px; }
  .sc-card { background:#222; border:1px solid #444; border-radius:8px; padding:12px 14px; width:220px; min-width:200px; box-sizing:border-box; }
  .sc-card.card-hot { border-color:#cc4444; background:#2a1a1a; }
  .sc-card.card-mid { border-color:#cc8800; background:#2a2210; }
  .sc-card-header { display:flex; align-items:center; gap:8px; margin-bottom:5px; }
  .rank-badge { font-size:11px; padding:2px 8px; border-radius:10px; font-weight:bold; white-space:nowrap; }
  .rank-badge.b-hot { background:#ff6b6b; color:#1a1a1a; }
  .rank-badge.b-mid { background:#ffd166; color:#1a1a1a; }
  .rank-badge.b-edge { background:#555; color:#eee; }
  .rank-badge.b-none { background:#333; color:#777; }
  .sc-code { font-size:11px; color:#888; }
  .sc-name { font-size:14px; font-weight:bold; color:#e0e0e0; margin-bottom:4px; line-height:1.3; }
  .sc-product { font-size:12px; color:#aaa; line-height:1.4; margin-bottom:4px; }
  .sc-amount { font-size:12px; color:#4da3ff; }
  @media (prefers-color-scheme:light), :root[data-theme="light"] {
    .cal-cell { background:#f4f4f4; } .cal-cell.today { background:#dbeeff; border-color:#0066cc; }
    .cal-cell.today .cal-num { color:#0066cc; background:#c0dcf8; }
    .cal-num { color:#666; } #calTitle { color:#222; }
    .cal-nav button { background:#ddd; color:#333; } .cal-nav button:hover { background:#bbb; }
    .cal-head { color:#555; } .cal-head.sun { color:#cc3333; } .cal-head.sat { color:#3366cc; }
    .cal-num.sun { color:#cc3333; } .cal-num.sat { color:#3366cc; }
    .cal-evt.tw { background:#fde8e8; color:#aa0000; border-left-color:#cc2222; }
    .cal-evt.us { background:#e8f0fe; color:#003399; border-left-color:#3366cc; }
  }
</style>
</head>
<body>
<h1>股市資金流向追蹤</h1>
<div class="caption">台股(上市+上櫃) / 日股 / 韓股 / 陸股(滬深A股) / 美股，依成交金額排行，依族群/題材分類。最新快照日期：<span id="latestDate"></span></div>

<div class="tabs">
  <button class="tab-btn active" onclick="showTab(0)">題材跨市場比較</button>
  <button class="tab-btn" onclick="showTab(1)">排行榜明細</button>
  <button class="tab-btn" onclick="showTab(2)">公司歷史趨勢</button>
  <button class="tab-btn" onclick="showTab(3)">財報/法說會提醒</button>
  <button class="tab-btn" onclick="showTab(4)">新聞/目標價</button>
  <button class="tab-btn" onclick="showTab(5)">供應鏈</button>
</div>

<div class="tab-content active" id="tab0">
  <div class="controls">
    <label><input type="checkbox" id="onlyThematic" checked onchange="renderThemePivot()"> 只看題材概念股(排除金融/消費/傳統產業等廣義分類)</label>
  </div>
  <div class="hint" id="hintTheme">熱度分數 = 該題材在每個國家的「台幣金額 ÷ 該國全部上榜公司台幣金額總和」百分比，五國加總而成。分數越高表示資金集中度越高，不是只看公司數量。點欄位標題可排序。</div>
  <div class="scroll-box"><table id="themePivotTable"></table></div>
  <div id="moversChart" style="height:550px"></div>
  <div class="controls">
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
  <div class="controls">
    追蹤對象：
    <label><input type="radio" name="histMode" value="company" checked onchange="onHistModeChange()"> 公司</label>
    <label><input type="radio" name="histMode" value="theme" onchange="onHistModeChange()"> 主族群(題材)</label>
  </div>
  <div class="controls" id="companyPickWrap">
    選擇公司：
    <div class="search-wrap">
      <input type="text" id="companySearch" placeholder="輸入代碼或公司名稱…" autocomplete="off">
      <div class="search-dropdown" id="companyDropdown" style="display:none"></div>
    </div>
    <input type="hidden" id="companyPick">
  </div>
  <div class="controls" id="themeHistPickWrap" style="display:none">
    選擇主族群：
    <div class="search-wrap">
      <input type="text" id="themeHistSearch" placeholder="輸入題材名稱…" autocomplete="off">
      <div class="search-dropdown" id="themeHistDropdown" style="display:none"></div>
    </div>
    <input type="hidden" id="themeHistPick">
  </div>
  <div id="historyChart" style="height:400px"></div>
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
  <div class="hint">點選錨點客戶，查看各國一階直接供應商的資金流向熱度。資料來源：Gemini驗證後人工確認。最後更新：<span id="scLastUpdatedInline"></span></div>
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
  <div id="scCountryBar"></div>
  <div id="scCards"></div>
</div>

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
  document.querySelectorAll(".tab-btn").forEach((b, idx) => b.classList.toggle("active", idx === i));
  document.querySelectorAll(".tab-content").forEach((t, idx) => t.classList.toggle("active", idx === i));
}

function renderThemePivot() {
  const onlyThematic = document.getElementById("onlyThematic").checked;
  const pivot = onlyThematic ? DATA.theme_pivot_thematic.slice(0, 10) : DATA.theme_pivot_all;
  const cols = [
    {key: "main_group", label: "主族群"},
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

function renderMoversChart() {
  const el = document.getElementById("moversChart");
  if (!DATA.previous_date) { el.innerHTML = ""; return; }
  const thematic = DATA.theme_pivot_thematic.filter(p => p["熱度分數Δ"] !== null && p["熱度分數Δ"] !== undefined);
  const sorted = thematic.slice().sort((a, b) => b["熱度分數Δ"] - a["熱度分數Δ"]);
  const topUp = sorted.slice(0, 10);
  const topDown = sorted.slice(-10).reverse();
  const movers = topDown.concat(topUp);
  const seen = new Set();
  const uniqueMovers = movers.filter(m => !seen.has(m.main_group) && seen.add(m.main_group));
  uniqueMovers.sort((a, b) => a["熱度分數Δ"] - b["熱度分數Δ"]);
  Plotly.newPlot(el.id, [{
    x: uniqueMovers.map(m => m["熱度分數Δ"]),
    y: uniqueMovers.map(m => m.main_group),
    type: "bar", orientation: "h",
    marker: {color: uniqueMovers.map(m => m["熱度分數Δ"] >= 0 ? "#ff6b6b" : "#4da3ff")},
  }], {
    title: `本次熱度分數變化最大的題材(前10上升/前10下降，跟${DATA.previous_date}比較)`,
    paper_bgcolor: "#1a1a1a", plot_bgcolor: "#1a1a1a", font: {color: "#e0e0e0"},
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

function renderCompanyHistory() {
  const key = document.getElementById("companyPick").value;
  const entry = DATA.company_history[key];
  if (!entry) return;
  const rows = entry.rows;
  Plotly.newPlot("historyChart", [{
    x: rows.map(r => r.snapshot_date), y: rows.map(r => r.rank), mode: "lines+markers", line: {color: "#4da3ff"},
  }], {
    title: entry.label + " 排名變化(數字越小越熱)",
    yaxis: {autorange: "reversed", title: "排名"},
    paper_bgcolor: "#1a1a1a", plot_bgcolor: "#1a1a1a", font: {color: "#e0e0e0"},
  }, {responsive: true});
  const cols = [
    {key: "snapshot_date", label: "日期"}, {key: "rank", label: "排名", numeric: true},
    {key: "金額億", label: "金額(億)"}, {key: "金額億台幣", label: "金額(億台幣)", numeric: true, sortKey: "金額億台幣_num"},
  ];
  buildTable(document.getElementById("historyTable"), cols, rows);
}

function onHistModeChange() {
  const mode = document.querySelector('input[name="histMode"]:checked').value;
  document.getElementById("companyPickWrap").style.display = mode === "company" ? "" : "none";
  document.getElementById("themeHistPickWrap").style.display = mode === "theme" ? "" : "none";
  if (mode === "company") renderCompanyHistory(); else renderThemeHistory();
}

function renderThemeHistory() {
  const g = document.getElementById("themeHistPick").value;
  const rows = DATA.theme_history[g] || [];
  Plotly.newPlot("historyChart", [{
    x: rows.map(r => r.snapshot_date), y: rows.map(r => r["熱度分數"]), mode: "lines+markers", line: {color: "#ff8c4d"},
  }], {
    title: g + " 熱度分數變化(數字越大資金越集中)",
    yaxis: {title: "熱度分數"},
    paper_bgcolor: "#1a1a1a", plot_bgcolor: "#1a1a1a", font: {color: "#e0e0e0"},
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
  renderSCCards();
}

function renderSCCards() {
  const def = ANCHOR_DEFS[scCurrentAnchor];
  if (!def) return;
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
    items.forEach(function(l) {
      const tier = l.supplier_tier || "";
      let badgeCls = "b-edge", cardCls = "";
      if (tier.indexOf("前50") >= 0)  { badgeCls = "b-hot";  cardCls = "card-hot"; }
      else if (tier.indexOf("51-150") >= 0) { badgeCls = "b-mid"; cardCls = "card-mid"; }
      const rankText = l.supplier_rank ? "#" + l.supplier_rank : "未上榜";
      const badgeClass2 = l.supplier_rank ? badgeCls : "b-none";
      html += "<div class=\"sc-card " + cardCls + "\">" +
              "<div class=\"sc-card-header\"><span class=\"rank-badge " + badgeClass2 + "\">" + rankText + "</span>" +
              "<span class=\"sc-code\">" + l.supplier_code + "</span></div>" +
              "<div class=\"sc-name\">" + (l.supplier_name || l.supplier_code) + "</div>" +
              "<div class=\"sc-product\">&#9658; " + l.product + "</div>" +
              (l.supplier_amount_yi ? "<div class=\"sc-amount\">" + l.supplier_amount_yi + "</div>" : "") +
              "</div>";
    });
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
  renderSCCards();
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
    renderCompanyHistory);
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

  renderThemePivot();
  renderFullTable();
  renderEarningsTab();
  renderNewsTable();
  initSupplyChain();
  if (DATA.company_list.length) renderCompanyHistory();
  if (DATA.theme_list.length) renderThemeHistory();
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
