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

# 排除過於廣泛的族群（跟現有 export_html.py 保持一致）
BROAD_GROUPS = {
    "金融", "科技(綜合)", "生技醫藥", "消費(非必需)", "工業", "傳統產業", "傳統消費",
    "公用事業", "能源", "不動產", "電信", "傳統產業/原材料", "電力設備", "控股公司",
    "航運", "造船", "商社", "商社/建設", "汽車", "其他", "未分類", "媒體/娛樂",
    "遊戲/娛樂", "品牌3C", "IT/系統整合", "網路服務", "人力資源", "工業電腦/物聯網",
    "IC通路", "安防設備",
}

# XQ 代碼格式（market → suffix）
SUFFIX = {
    "台": ".TW",
    "美": "",       # US ticker 直接用，不加後綴
    "日": ".T",     # 東京交易所（XQ 支援度待確認）
    "韓": ".KS",    # 韓國（XQ 支援度待確認）
    "陸": ".SS",    # A 股（XQ 支援度待確認）
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
) -> list[str]:
    theme_scores, classified = compute_theme_scores(conn, snapshot_date, markets)

    # 過濾廣泛族群
    theme_scores = theme_scores[~theme_scores["main_group"].isin(BROAD_GROUPS)]
    top_themes = theme_scores.head(top_n_themes)

    lines = [f"題材熱度Top{top_n_themes}_{snapshot_date}:"]
    total = 0

    for _, row in top_themes.iterrows():
        theme = row["main_group"]
        score = row["theme_score"]
        score_str = f"{score:.0f}點{int((score % 1) * 10)}" if score % 1 else f"{score:.0f}點0"
        lines.append(f"{theme}_{score_str}:")

        # 逐市場取前 N 名（台股優先）
        market_order = [m for m in ["台", "美", "日", "韓", "陸"] if m in markets]
        for market in market_order:
            market_df = (
                classified[
                    (classified["main_group"] == theme) & (classified["country"] == market)
                ]
                .sort_values("rank")
                .head(top_n_per_market)
            )
            for _, s in market_df.iterrows():
                lines.append(xq_code(market, s["code"]))
                total += 1

    lines.append(f"# 共{total}檔  產生:{date.today().isoformat()}")
    return lines, total


def main():
    parser = argparse.ArgumentParser(description="生成XQ題材熱度自選股匯入檔")
    parser.add_argument("--themes", type=int, default=10, help="取前N個主題（預設10）")
    parser.add_argument("--per",    type=int, default=3,  help="每個主題每市場取前N名（預設3）")
    parser.add_argument("--markets", nargs="+", default=DEFAULT_MARKETS,
                        help="市場列表，例如 台 美 日（預設：台 美）")
    args = parser.parse_args()

    Path(OUT_DIR).mkdir(exist_ok=True)
    conn = sqlite3.connect(DB)
    snapshot = get_latest_snapshot(conn)
    print(f"快照日期: {snapshot}，市場: {args.markets}，"
          f"前{args.themes}主題，每主題每市場前{args.per}名")

    lines, total = build_xq_lines(
        conn, snapshot, args.markets, args.themes, args.per
    )
    conn.close()

    date_tag = snapshot.replace("-", "")
    out_path = Path(OUT_DIR) / f"XQ_題材熱度_{date_tag}.csv"
    content = "\r\n".join(lines)
    with open(out_path, "w", encoding="big5", errors="replace") as f:
        f.write(content)

    print(f"已輸出：{out_path}（共 {total} 檔）")
    # 順便印出預覽
    for line in lines[:40]:
        print(" ", line)
    if len(lines) > 40:
        print(f"  ...（共 {len(lines)} 行）")


if __name__ == "__main__":
    main()
