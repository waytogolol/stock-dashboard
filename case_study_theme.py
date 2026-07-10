# -*- coding: utf-8 -*-
"""題材進場時點案例研究：逆推動能訊號在歷史上的觸發時點與特徵
用法: python case_study_theme.py [題材1] [題材2] ...   預設: 記憶體 被動元件

輸出 tmp_case_report.txt：
- 每週時間線：熱度分數/各國子分數/週變化/連漲週數/位階/廣度/階段標籤
- 訊號觸發點標記（發動/主升段轉換）
- 台股 vs 美韓子分數的 lead-lag 相關性
"""
import os
import sqlite3
import sys

import pandas as pd

DB = os.environ.get("CF_DB", "capital_flow.db")   # 研究沙盒: set CF_DB=research_2022.db
COUNTRIES = ["台", "日", "美", "韓", "陸"]
THEMES = sys.argv[1:] if len(sys.argv) > 1 else ["記憶體", "被動元件"]


def load():
    conn = sqlite3.connect(DB)
    rankings = pd.read_sql("SELECT snapshot_date, country, code, rank, amount, amount_unit FROM rankings", conn)
    cls = pd.read_sql("SELECT country, code, main_group FROM classification", conn)
    fx = pd.read_sql("SELECT * FROM fx_rates", conn)
    conn.close()
    cur_map = {"TWD": "TWD", "KRW": "KRW", "JPY_million": "JPY", "CNY": "CNY", "USD": "USD"}
    rankings["currency"] = rankings["amount_unit"].map(cur_map)
    rankings = rankings.merge(fx, on=["snapshot_date", "currency"], how="left")
    base = rankings["amount"] * rankings["amount_unit"].eq("JPY_million").map({True: 1e6, False: 1})
    rankings["twd"] = base * rankings["twd_per_unit"]
    return rankings, cls


def theme_series(rankings, cls, theme):
    """回傳 DataFrame(index=snapshot_date)：score, 各國子分數, breadth_up_pct"""
    members = cls[cls["main_group"] == theme][["country", "code"]].drop_duplicates()
    dates = sorted(rankings["snapshot_date"].unique())
    country_totals = rankings.groupby(["snapshot_date", "country"])["twd"].sum()
    rows = []
    prev_ranks = None
    for d in dates:
        snap = rankings[rankings["snapshot_date"] == d]
        m = snap.merge(members, on=["country", "code"], how="inner")
        sub = {}
        for c in COUNTRIES:
            tot = country_totals.get((d, c), 0)
            amt = m[m["country"] == c]["twd"].sum()
            sub[c] = (amt / tot * 100) if tot else 0.0
        # 廣度：跟上週同時在榜的成員中，排名上升比例
        ranks = {(r["country"], r["code"]): r["rank"] for _, r in m.iterrows()}
        up = down = 0
        if prev_ranks:
            for k, rk in ranks.items():
                if k in prev_ranks:
                    if rk < prev_ranks[k]:
                        up += 1
                    elif rk > prev_ranks[k]:
                        down += 1
        breadth = up / (up + down) * 100 if (up + down) else None
        prev_ranks = ranks
        rows.append({"date": d, "score": sum(sub.values()), "breadth_up": breadth,
                     "n_stocks": len(m.drop_duplicates(subset=["country", "code"])),
                     **{f"sub_{c}": sub[c] for c in COUNTRIES}})
    return pd.DataFrame(rows).set_index("date")


def add_signals(df):
    """加動能特徵與階段標籤（與dashboard動能雷達同規則, n=2週）"""
    s = df["score"]
    df["d1"] = s.diff()
    df["d2"] = s.diff(2)
    streaks = []
    st = 0
    for v in df["d1"]:
        st = st + 1 if pd.notna(v) and v > 0 else 0
        streaks.append(st)
    df["連漲週"] = streaks
    # 位階：對「截至當週」的歷史 min-max（不偷看未來）
    pos = []
    for i in range(len(s)):
        hist = s.iloc[:i + 1]
        mn, mx = hist.min(), hist.max()
        pos.append((s.iloc[i] - mn) / (mx - mn) if mx > mn else 0.5)
    df["位階"] = pos
    stages = []
    for i, r in df.iterrows():
        d, p, up = r["d2"], r["位階"], r["連漲週"]
        if pd.isna(d):
            stages.append("")
        elif d > 0 and p >= 0.6:
            stages.append("主升段")
        elif d > 0 and up >= 2:
            stages.append("發動")
        elif d > 0:
            stages.append("回溫")
        elif d < 0 and p >= 0.7:
            stages.append("高檔轉弱")
        elif d < 0:
            stages.append("回檔/退潮")
        else:
            stages.append("盤整")
    df["階段"] = stages
    return df


def lead_lag(df):
    """台子分數變化 vs 美+韓子分數變化 的 lag 相關(正lag=美韓領先台)"""
    tw = df["sub_台"].diff()
    ohw = (df["sub_美"] + df["sub_韓"]).diff()
    out = []
    for lag in range(0, 7):
        c = tw.corr(ohw.shift(lag))
        out.append((lag, round(c, 3) if pd.notna(c) else None))
    return out


def main():
    rankings, cls = load()
    lines = []
    for theme in THEMES:
        df = add_signals(theme_series(rankings, cls, theme))
        lines.append(f"\n{'='*90}\n■ 題材：{theme}（成員家數最新 {int(df['n_stocks'].iloc[-1])}）\n{'='*90}")
        lines.append(f"{'日期':<12}{'分數':>7}{'台':>6}{'韓':>6}{'美':>6}{'陸':>6}{'日':>6}{'Δ2週':>7}{'連漲':>4}{'位階%':>5}{'廣度%':>5}  階段")
        prev_stage = ""
        for d, r in df.iterrows():
            mark = ""
            if r["階段"] in ("發動", "主升段") and prev_stage not in ("發動", "主升段") and r["階段"]:
                mark = "  ◀◀ 訊號"
            b = f"{r['breadth_up']:.0f}" if pd.notna(r["breadth_up"]) else "-"
            lines.append(f"{d:<12}{r['score']:>7.2f}{r['sub_台']:>6.2f}{r['sub_韓']:>6.2f}{r['sub_美']:>6.2f}"
                         f"{r['sub_陸']:>6.2f}{r['sub_日']:>6.2f}"
                         f"{r['d2'] if pd.notna(r['d2']) else 0:>7.2f}{int(r['連漲週']):>4}"
                         f"{r['位階']*100:>5.0f}{b:>5}  {r['階段']}{mark}")
            prev_stage = r["階段"]
        ll = lead_lag(df)
        best = max((x for x in ll if x[1] is not None), key=lambda x: x[1], default=None)
        lines.append(f"\n台股 vs 美韓 lead-lag 相關（正lag=美韓領先台N週）: {ll}")
        if best:
            lines.append(f"最強相關: lag={best[0]}週 (r={best[1]})")
    with open("tmp_case_report.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("done -> tmp_case_report.txt")


if __name__ == "__main__":
    main()
