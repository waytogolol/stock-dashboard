# -*- coding: utf-8 -*-
"""
gen_xq_watchlist.py
從 capital_flow.db 依題材熱度生成 XQ 自選股匯入檔

輸出規則：
  - 取當週最熱 TOP_N_THEMES 個主族群
  - 每個族群在指定市場各取前 TOP_N_PER_THEME 名（依成交值排名）
  - 台股：代碼加 .TW（如 2330.TW）
  - 美股：直接用 ticker（如 NVDA）
  - 編碼：Big5 + CRLF（XQ 匯入標準格式）

用法：
  python gen_xq_watchlist.py
  python gen_xq_watchlist.py --themes 12 --per 4   # 自訂數量
"""
import argparse
import sqlite3
from datetime import date
from pathlib import Path

import pandas as pd

DB = "capital_flow.db"
OUT_DIR = "XQ檔案匯入"

# XQ 代碼格式（market → suffix）
SUFFIX = {
    "台": ".TW",
    "美": ".US",
    "日": ".JP",
    "韓": ".KS",
    "陸": ".SS",    # A 股格式待確認
}

# 預設啟用的市場（台+美，日韓陸可手動加入）
DEFAULT_MARKETS = ["台", "美"]


def xq_code(country: str, code: str) -> str:
    return f"{code}{SUFFIX.get(country, '')}"


def get_latest_snapshot(conn) -> str:
    return conn.execute("SELECT MAX(snapshot_date) FROM rankings").fetchone()[0]


def compute_theme_scores(conn, snapshot_date: str, markets: list) -> pd.DataFrame:
    """
    計算題材熱度：在排名前200以內的公司，以 (200 - rank) 加總為熱度分數。
    回傳 DataFrame，欄位：main_group, score，依 score 降冪排列。
    """
    placeholders = ",".join("?" * len(markets))
    df = pd.read_sql(f"""
        SELECT r.country, r.code, r.rank, c.main_group
        FROM rankings r
        JOIN classification c ON c.country = r.country AND c.code = r.code
        WHERE r.snapshot_date = ?
          AND r.country IN ({placeholders})
          AND r.rank <= 200
    """, conn, params=[snapshot_date] + markets)

    df["score"] = 200 - df["rank"]
    scores = (
        df.groupby("main_group")["score"]
        .sum()
        .reset_index()
        .rename(columns={"score": "theme_score"})
        .sort_values("theme_score", ascending=False)
    )
    return scores, df


def build_xq_lines(
    conn,
    snapshot_date: str,
    markets: list,
    top_n_themes: int,
    top_n_per_market: int,
) -> tuple[list[str], int, pd.DataFrame]:
    theme_scores, classified = compute_theme_scores(conn, snapshot_date, markets)

    # 只保留台股公司數 > 0 的題材（過濾掉台=0 的純外國題材）
    tw_count = (
        classified[classified["country"] == "台"]
        .groupby("main_group")["code"]
        .count()
        .rename("tw_count")
    )
    theme_scores = theme_scores.merge(tw_count, on="main_group", how="left")
    theme_scores["tw_count"] = theme_scores["tw_count"].fillna(0)
    theme_scores = theme_scores[theme_scores["tw_count"] > 0]
    top_themes = theme_scores.head(top_n_themes)

    # 取得公司名稱
    names_df = pd.read_sql(
        "SELECT country, code, name_zh AS name FROM company_names", conn
    )
    name_map = {(r.country, r.code): r.name for r in names_df.itertuples()}

    lines = []
    total = 0
    summary_rows = []

    market_order = [m for m in ["台", "美", "日", "韓", "陸"] if m in markets]

    # XQ 標籤不接受 /()- 等符號，統一替換為全形或底線
    _bad = str.maketrans({"/": "-", "(": "", ")": ""})

    for rank_i, (_, row) in enumerate(top_themes.iterrows(), 1):
        theme = row["main_group"]
        score = row["theme_score"]
        safe_theme = theme.translate(_bad)
        score_str = f"{score:.0f}點0"
        lines.append(f"{safe_theme}_{score_str}:")

        for market in market_order:
            market_df = (
                classified[
                    (classified["main_group"] == theme) & (classified["country"] == market)
                ]
                .sort_values("rank")
                .head(top_n_per_market)
            )
            for _, s in market_df.iterrows():
                code_xq = xq_code(market, s["code"])
                lines.append(code_xq)
                total += 1
                summary_rows.append({
                    "熱度排名": rank_i,
                    "題材": theme,
                    "熱度分": int(score),
                    "市場": market,
                    "代碼": s["code"],
                    "XQ代碼": code_xq,
                    "公司": name_map.get((market, s["code"]), ""),
                    "排名": int(s["rank"]),
                })

    summary = pd.DataFrame(summary_rows)
    return lines, total, summary


def main():
    parser = argparse.ArgumentParser(description="生成XQ題材熱度自選股匯入檔")
    parser.add_argument("--themes", type=int, default=20, help="取前N個熱度族群（預設20）")
    parser.add_argument("--per",    type=int, default=5,  help="每個族群每市場取前N名（預設5）")
    parser.add_argument("--markets", nargs="+", default=DEFAULT_MARKETS,
                        help="市場列表，例如 台 美 日（預設：台 美）")
    args = parser.parse_args()

    Path(OUT_DIR).mkdir(exist_ok=True)
    conn = sqlite3.connect(DB)
    snapshot = get_latest_snapshot(conn)
    print(f"快照日期: {snapshot}  市場: {args.markets}  前{args.themes}族群  每族群每市場前{args.per}名")

    lines, total, summary = build_xq_lines(
        conn, snapshot, args.markets, args.themes, args.per
    )
    conn.close()

    date_tag = snapshot.replace("-", "")

    # ── XQ 匯入檔（Big5 + CRLF，用二進位模式避免 Windows 雙重換行）──
    out_xq = Path(OUT_DIR) / f"XQ_題材熱度_{date_tag}.csv"
    content = "\r\n".join(lines) + "\r\n"
    with open(out_xq, "wb") as f:
        f.write(content.encode("big5", errors="replace"))

    # ── 人看的摘要 Excel / CSV ──
    out_summary = Path(OUT_DIR) / f"題材熱度_個股名單_{date_tag}.csv"
    summary.to_csv(out_summary, index=False, encoding="utf-8-sig")

    print(f"\n已輸出 XQ 匯入檔：{out_xq}（共 {total} 檔）")
    print(f"已輸出 個股摘要：{out_summary}\n")

    # 印出熱度排行摘要
    print(f"{'排':>3} {'題材':<18} {'熱度分':>6}  {'台股代碼':<30} {'美股代碼'}")
    print("-" * 80)
    for theme_rank, grp in summary.groupby("熱度排名"):
        tw_codes = " ".join(grp[grp["市場"] == "台"]["代碼"].tolist())
        us_codes = " ".join(grp[grp["市場"] == "美"]["代碼"].tolist())
        theme = grp["題材"].iloc[0]
        score = grp["熱度分"].iloc[0]
        print(f"{theme_rank:>3}. {theme:<18} {score:>6}  {tw_codes:<30} {us_codes}")


if __name__ == "__main__":
    main()
