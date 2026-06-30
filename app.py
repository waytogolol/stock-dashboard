# -*- coding: utf-8 -*-
"""股市資金流向儀表板。執行: streamlit run app.py"""
import os
import sqlite3
from datetime import date, datetime

import pandas as pd
import plotly.express as px
import streamlit as st

DB_PATH = "capital_flow.db"

st.set_page_config(page_title="股市資金流向", layout="wide")


@st.cache_data(ttl=60)
def load_data():
    conn = sqlite3.connect(DB_PATH)
    rankings = pd.read_sql("SELECT * FROM rankings", conn)
    classification = pd.read_sql("SELECT * FROM classification", conn)
    names = pd.read_sql("SELECT * FROM company_names", conn)
    fx = pd.read_sql("SELECT * FROM fx_rates", conn)
    conn.close()
    rankings = rankings.merge(names, on=["country", "code"], how="left")
    # 台股本身就是中文，沒有對照表時就沿用原名(美/日/韓若沒查到對照也沿用原名)
    rankings["中文名稱"] = rankings["name_zh"].fillna(rankings["name"])
    rankings["金額(億)"] = rankings.apply(format_amount_yi, axis=1)
    rankings["currency"] = rankings["amount_unit"].map({"TWD": "TWD", "KRW": "KRW", "JPY_million": "JPY", "CNY": "CNY", "USD": "USD"})
    rankings = rankings.merge(fx, on=["snapshot_date", "currency"], how="left")
    rankings["金額(億台幣)"] = rankings.apply(format_amount_twd_yi, axis=1)
    rankings["金額億台幣_num"] = rankings.apply(amount_twd_yi_num, axis=1)
    return rankings, classification


def amount_twd_yi_num(row):
    if pd.isna(row.get("twd_per_unit")):
        return None
    base_amount = row["amount"] * 1e6 if row["amount_unit"] == "JPY_million" else row["amount"]
    return base_amount * row["twd_per_unit"] / 1e8


UNIT_YI_LABEL = {"TWD": "億元", "KRW": "億韓元", "JPY_million": "億日圓", "CNY": "億人民幣", "USD": "億美元"}


def format_amount_yi(row):
    # JPY_million本身已是百萬円單位，1億=100百萬，其餘(TWD/KRW/USD)都是原始單位，1億=1e8
    yi = row["amount"] / 100 if row["amount_unit"] == "JPY_million" else row["amount"] / 1e8
    return f"{round(yi):,}{UNIT_YI_LABEL.get(row['amount_unit'], '億')}"


def format_amount_twd_yi(row):
    if pd.isna(row.get("twd_per_unit")):
        return "—"
    base_amount = row["amount"] * 1e6 if row["amount_unit"] == "JPY_million" else row["amount"]
    twd_yi = base_amount * row["twd_per_unit"] / 1e8
    return f"{round(twd_yi):,}億元"


def rank_tier(rank):
    if rank <= 50:
        return "🔥 前50(熱)"
    elif rank <= 150:
        return "🟠 51-150(中)"
    else:
        return "🟡 151+(邊緣)"


# 廣義產業/財務分類(每個市場都一定有大量公司，不是具體題材，會把記憶體/被動元件這種真正的概念股淹沒)
BROAD_GROUPS = {
    "金融", "科技(綜合)", "生技醫藥", "消費(非必需)", "工業", "傳統產業", "傳統消費", "公用事業", "能源",
    "不動產", "電信", "傳統產業/原材料", "電力設備", "控股公司", "航運", "造船", "商社", "商社/建設",
    "汽車", "其他", "未分類", "媒體/娛樂", "遊戲/娛樂", "品牌3C", "IT/系統整合", "網路服務", "人力資源",
    "工業電腦/物聯網", "IC通路", "安防設備",
}


def tier_color(tier):
    style = {
        "🔥 前50(熱)": "background-color: #ff6b6b; color: #1a1a1a",
        "🟠 51-150(中)": "background-color: #ffd166; color: #1a1a1a",
        "🟡 151+(邊緣)": "background-color: #fff9db; color: #1a1a1a",
    }.get(tier, "")
    return style


COUNTRIES = ["台", "日", "美", "韓", "陸"]


def compute_theme_pivot(rankings, classification, snapshot_date):
    """回傳該snapshot_date的題材熱度分數表(主族群為index)，沒有資料回傳空表。"""
    snap = rankings[rankings["snapshot_date"] == snapshot_date]
    merged = classification.merge(snap, on=["country", "code"], how="inner")
    if merged.empty:
        return pd.DataFrame(columns=["熱度分數", "金額合計(億台幣)"] + COUNTRIES + ["合計家數"])
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
    pivot = pd.DataFrame({"熱度分數": share.sum(axis=1).round(2), "金額合計(億台幣)": theme_amt[COUNTRIES].sum(axis=1).round(0)})
    for c in COUNTRIES:
        pivot[c] = theme_cnt[c]
    pivot["合計家數"] = theme_cnt[COUNTRIES].sum(axis=1)
    return pivot


rankings, classification = load_data()
rankings["熱度"] = rankings["rank"].apply(rank_tier)

snapshot_dates = sorted(rankings["snapshot_date"].unique(), reverse=True)

st.title("股市資金流向追蹤")
st.caption("台股(上市+上櫃) / 日股 / 韓股 / 陸股(滬深A股) / 美股，依成交金額排行，依族群/題材分類")

COUNTRIES = ["台", "日", "美", "韓", "陸"]

with st.sidebar:
    st.header("篩選")
    selected_date = st.selectbox("快照日期", snapshot_dates)
    countries = st.multiselect("國家", COUNTRIES, default=COUNTRIES)
    all_groups = sorted(classification["main_group"].dropna().unique())
    selected_groups = st.multiselect("主族群(題材)", all_groups)

tab1, tab2, tab3, tab4 = st.tabs(["題材跨市場比較", "排行榜明細", "公司歷史趨勢", "財報/法說會提醒"])

# 比目前選的日期更早的最近一個snapshot，用來算「跟上次比」的變化值；只有一個snapshot時就沒有上次可比
earlier_dates = [d for d in snapshot_dates if d < selected_date]
previous_date = max(earlier_dates) if earlier_dates else None

# ---- Tab 1: 題材跨市場比較 ----
with tab1:
    st.subheader("題材熱度總表")
    st.caption(
        "熱度分數 = 該題材在每個國家的「台幣金額 ÷ 該國全部上榜公司台幣金額總和」百分比，五國加總而成。"
        "分數越高表示資金集中度越高(可能超過100，因為是五國比例加總)，不是只看公司數量。"
    )
    only_thematic = st.checkbox("只看題材概念股(排除金融/消費/傳統產業等廣義分類)", value=True)
    merged = classification.merge(rankings[rankings["snapshot_date"] == selected_date], on=["country", "code"], how="inner")

    if not merged.empty:
        pivot = compute_theme_pivot(rankings, classification, selected_date)
        if previous_date:
            prev_pivot = compute_theme_pivot(rankings, classification, previous_date)
            pivot["熱度分數Δ"] = (pivot["熱度分數"] - prev_pivot["熱度分數"].reindex(pivot.index)).round(2)
            pivot["金額Δ(億台幣)"] = (pivot["金額合計(億台幣)"] - prev_pivot["金額合計(億台幣)"].reindex(pivot.index)).round(0)
        pivot = pivot.sort_values("熱度分數", ascending=False)

        if previous_date:
            st.caption(f"Δ欄位是跟上一次快照({previous_date})比較的變化值")

            st.subheader("本次熱度分數變化最大的題材(前5上升/前5下降)")
            thematic_delta = pivot.loc[~pivot.index.isin(BROAD_GROUPS), "熱度分數Δ"].dropna()
            top_up = thematic_delta.sort_values(ascending=False).head(5)
            top_down = thematic_delta.sort_values(ascending=True).head(5)
            movers = pd.concat([top_down, top_up]).reset_index()
            movers.columns = ["主族群", "熱度分數Δ"]
            movers["方向"] = movers["熱度分數Δ"].apply(lambda v: "上升" if v >= 0 else "下降")
            fig_movers = px.bar(
                movers, x="熱度分數Δ", y="主族群", color="方向", orientation="h",
                color_discrete_map={"上升": "#ff6b6b", "下降": "#4da3ff"},
                title=f"跟上次快照({previous_date})比較",
            )
            fig_movers.update_layout(yaxis={"categoryorder": "total ascending"})
            st.plotly_chart(fig_movers, width="stretch")
        else:
            st.caption("目前只有一個快照日期，累積第二次資料後這裡會多出「跟上次比」的Δ變化欄位和漲跌排行圖")

        if only_thematic:
            pivot = pivot[~pivot.index.isin(BROAD_GROUPS)]
            st.caption("前10大最熱題材(已排除廣義分類)")
            st.dataframe(pivot.head(10), width="stretch")
        else:
            st.dataframe(pivot, width="stretch")

        st.subheader("選定題材的公司明細(依排名熱度上色)")
        theme_pick = st.selectbox("選一個主族群看明細", pivot.index.tolist())
        detail = merged[merged["main_group"] == theme_pick][
            ["country", "rank", "code", "中文名稱", "name", "sub_product", "position_note", "金額(億)", "金額(億台幣)", "熱度"]
        ].sort_values("rank")
        styled = detail.style.apply(lambda row: [tier_color(row["熱度"])] * len(row), axis=1)
        st.dataframe(styled, width="stretch", height=500)
    else:
        st.info("此快照日期沒有符合篩選條件的資料")

# ---- Tab 2: 排行榜明細 ----
with tab2:
    st.subheader("排行榜原始明細(依篩選條件)")
    view = rankings[(rankings["snapshot_date"] == selected_date) & (rankings["country"].isin(countries))]
    if selected_groups:
        codes_in_groups = classification[classification["main_group"].isin(selected_groups)][["country", "code"]].drop_duplicates()
        view = view.merge(codes_in_groups, on=["country", "code"], how="inner")
    view = view.merge(
        classification.groupby(["country", "code"])["main_group"].apply(lambda x: ", ".join(sorted(set(x)))).reset_index(),
        on=["country", "code"], how="left",
    )
    display_cols = ["country", "rank", "code", "中文名稱", "name", "金額(億)", "金額(億台幣)", "main_group", "熱度"]
    if previous_date:
        prev = rankings[rankings["snapshot_date"] == previous_date][["country", "code", "rank", "金額億台幣_num"]]
        prev = prev.rename(columns={"rank": "prev_rank", "金額億台幣_num": "prev_amt"})
        view = view.merge(prev, on=["country", "code"], how="left")
        view["排名Δ"] = (view["prev_rank"] - view["rank"]).apply(lambda v: "新進榜" if pd.isna(v) else f"{int(v):+d}")
        view["金額Δ(億台幣)"] = (view["金額億台幣_num"] - view["prev_amt"]).round(0)
        display_cols += ["排名Δ", "金額Δ(億台幣)"]
        st.caption(f"排名Δ/金額Δ是跟上一次快照({previous_date})比較的變化值，正數代表排名進步/金額增加")
    else:
        st.caption("目前只有一個快照日期，累積第二次資料後這裡會多出「跟上次比」的Δ變化欄位")
    sort_choice = st.radio(
        "排序方式", ["排名(預設)", "金額(台幣)由大到小", "金額(台幣)由小到大"], horizontal=True,
    )
    if sort_choice == "金額(台幣)由大到小":
        view = view.sort_values("金額億台幣_num", ascending=False)
    elif sort_choice == "金額(台幣)由小到大":
        view = view.sort_values("金額億台幣_num", ascending=True)
    else:
        view = view.sort_values(["country", "rank"])
    styled_view = view[display_cols].style.apply(lambda row: [tier_color(row["熱度"])] * len(display_cols), axis=1)
    st.dataframe(styled_view, width="stretch", height=600)

# ---- Tab 3: 公司/族群歷史趨勢 ----
with tab3:
    st.subheader("歷史趨勢")
    if len(snapshot_dates) < 2:
        st.info("目前只有一個快照日期，累積更多次資料後(建議每週重跑一次)，這裡會顯示隨時間變化的趨勢線。")
    hist_mode = st.radio("追蹤對象", ["公司", "主族群(題材)"], horizontal=True)

    if hist_mode == "公司":
        company_options = rankings[["country", "code", "name", "中文名稱"]].drop_duplicates()
        company_options["label"] = company_options["country"] + " " + company_options["code"] + " " + company_options["中文名稱"]
        pick = st.selectbox("選擇公司", company_options["label"].tolist())
        if pick:
            country_pick, code_pick = pick.split(" ")[0], pick.split(" ")[1]
            hist = rankings[(rankings["country"] == country_pick) & (rankings["code"] == code_pick)].sort_values("snapshot_date")
            fig = px.line(hist, x="snapshot_date", y="rank", markers=True, title=f"{pick} 排名變化(數字越小越熱)")
            fig.update_yaxes(autorange="reversed")
            st.plotly_chart(fig, width="stretch")
            st.dataframe(hist[["snapshot_date", "rank", "金額(億)", "金額(億台幣)"]], width="stretch")
    else:
        theme_pick_hist = st.selectbox("選擇主族群", sorted(classification["main_group"].dropna().unique()))
        theme_hist_rows = []
        for d in snapshot_dates:
            p = compute_theme_pivot(rankings, classification, d)
            if theme_pick_hist in p.index:
                theme_hist_rows.append({"snapshot_date": d, "熱度分數": p.loc[theme_pick_hist, "熱度分數"], "金額合計(億台幣)": p.loc[theme_pick_hist, "金額合計(億台幣)"]})
        theme_hist = pd.DataFrame(theme_hist_rows).sort_values("snapshot_date")
        fig = px.line(theme_hist, x="snapshot_date", y="熱度分數", markers=True, title=f"{theme_pick_hist} 熱度分數變化(數字越大資金越集中)")
        st.plotly_chart(fig, width="stretch")
        st.dataframe(theme_hist, width="stretch")

# ---- Tab 4: 財報/法說會提醒 ----
with tab4:
    st.subheader("觀察名單裡，即將公布財報/開法說會的公司")
    days_window = st.slider("查詢未來幾天", 7, 30, 14)
    if st.button("重新查詢最新財報/法說會日曆(會即時連線查詢，需要幾十秒)"):
        from check_earnings import check_tw_earnings, check_us_earnings
        with st.spinner("查詢中..."):
            check_us_earnings(days_window)
            check_tw_earnings(days_window)
        st.cache_data.clear()
        st.rerun()

    def load_earnings_csv(path):
        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M")
            return pd.read_csv(path, dtype={"代碼": str}), mtime
        except FileNotFoundError:
            return None, None

    today_str = date.today().isoformat()

    def days_until(d):
        try:
            return (date.fromisoformat(d) - date.today()).days
        except ValueError:
            return None

    def highlight_soon(df, date_col):
        def _style(row):
            n = days_until(row[date_col])
            if n is not None and n <= 3:
                return ["background-color: #ff6b6b; color: #1a1a1a"] * len(row)
            elif n is not None and n <= 7:
                return ["background-color: #ffd166; color: #1a1a1a"] * len(row)
            return [""] * len(row)
        return df.style.apply(_style, axis=1)

    us_watch, us_mtime = load_earnings_csv("us_earnings_watch.csv")
    tw_watch, tw_mtime = load_earnings_csv("tw_earnings_watch.csv")

    timeline_rows = []
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**美股財報**")
        if us_watch is not None:
            st.caption(f"最後查詢時間: {us_mtime}(🔥=3天內 🟠=7天內)")
            st.dataframe(highlight_soon(us_watch, "日期"), width="stretch", height=300)
            for _, r in us_watch.iterrows():
                timeline_rows.append({"日期": r["日期"], "標的": f"美:{r['代碼']}", "市場": "美股"})
        else:
            st.info("還沒查詢過，按上面按鈕查詢一次")
    with col2:
        st.markdown("**台股法說會**")
        if tw_watch is not None:
            st.caption(f"最後查詢時間: {tw_mtime}(🔥=3天內 🟠=7天內)")
            st.dataframe(highlight_soon(tw_watch, "日期"), width="stretch", height=300)
            for _, r in tw_watch.iterrows():
                timeline_rows.append({"日期": r["日期"], "標的": f"台:{r['代碼']}", "市場": "台股"})
        else:
            st.info("還沒查詢過，按上面按鈕查詢一次")

    if timeline_rows:
        st.subheader("時間軸總覽")
        timeline = pd.DataFrame(timeline_rows)
        fig_tl = px.scatter(
            timeline, x="日期", y="標的", color="市場", symbol="市場",
            color_discrete_map={"美股": "#4da3ff", "台股": "#ff6b6b"},
        )
        fig_tl.update_traces(marker={"size": 14})
        fig_tl.add_vline(x=today_str, line_dash="dash", line_color="white")
        st.plotly_chart(fig_tl, width="stretch")
