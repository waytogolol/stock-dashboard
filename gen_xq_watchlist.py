# -*- coding: utf-8 -*-
"""
gen_xq_watchlist.py
從 capital_flow.db 依題材熱度「變化量(Δ)」生成 XQ 自選股匯入檔

輸出規則：
  - 取熱度上升前 N 個題材 + 熱度下降前 N 個題材（預設各15）
  - 台股：排行榜有出現的全放
  - 其他市場（美/日/韓/陸）：各前5名
  - 編碼：Big5 + CRLF（XQ 匯入標準格式）

用法：
  python gen_xq_watchlist.py
  python gen_xq_watchlist.py --top 10 --per 5
"""
import argparse
import sqlite3
from pathlib import Path

import pandas as pd

DB = "capital_flow.db"
OUT_DIR = "XQ檔案匯入"

SUFFIX = {
    "台": ".TW",
    "美": ".US",
    "日": ".JP",
    "韓": ".KS",
}

DEFAULT_MARKETS = ["台", "美", "日", "韓", "陸"]

_CURRENCY_MAP = {"TWD": "TWD", "KRW": "KRW", "JPY_million": "JPY", "CNY": "CNY", "USD": "USD"}
_BAD_CHARS = str.maketrans({"/": "-", "(": "", ")": ""})


def xq_code(country: str, code: str) -> str:
    if country == "陸":
        if code.lower().startswith("sh"):
            return f"{code[2:]}.SH"
        if code.lower().startswith("sz"):
            return f"{code[2:]}.SZ"
        return f"{code}.{'SH' if code.startswith('6') else 'SZ'}"
    return f"{code}{SUFFIX.get(country, '')}"


def get_two_latest_snapshots(conn):
    rows = conn.execute(
        "SELECT DISTINCT snapshot_date FROM rankings ORDER BY snapshot_date DESC LIMIT 2"
    ).fetchall()
    current = rows[0][0]
    previous = rows[1][0] if len(rows) >= 2 else None
    return current, previous


def _to_twd_yi(amount, amount_unit, fx_dict):
    if amount_unit == "JPY_million":
        base, curr = amount * 1e6, "JPY"
    else:
        base, curr = amount, _CURRENCY_MAP.get(amount_unit, "TWD")
    return base * fx_dict.get(curr, 1.0) / 1e8


def compute_theme_hotness(conn, snapshot_date: str, markets: list) -> pd.DataFrame:
    """各國台幣金額佔比%，五國加總 → 熱度分數（與 dashboard 公式相同）"""
    placeholders = ",".join("?" * len(markets))

    all_snap = pd.read_sql(f"""
        SELECT country, amount, amount_unit FROM rankings
        WHERE snapshot_date = ? AND country IN ({placeholders})
    """, conn, params=[snapshot_date] + markets)

    classified_snap = pd.read_sql(f"""
        SELECT r.country, r.code, r.amount, r.amount_unit, c.main_group
        FROM rankings r
        JOIN classification c ON c.country = r.country AND c.code = r.code
        WHERE r.snapshot_date = ? AND r.country IN ({placeholders})
    """, conn, params=[snapshot_date] + markets)

    fx = pd.read_sql("SELECT currency, twd_per_unit FROM fx_rates WHERE snapshot_date = ?",
                     conn, params=[snapshot_date])
    fx_dict = dict(zip(fx["currency"], fx["twd_per_unit"]))

    all_snap["twd_yi"] = all_snap.apply(
        lambda r: _to_twd_yi(r["amount"], r["amount_unit"], fx_dict), axis=1)
    classified_snap["twd_yi"] = classified_snap.apply(
        lambda r: _to_twd_yi(r["amount"], r["amount_unit"], fx_dict), axis=1)

    country_totals = all_snap.groupby("country")["twd_yi"].sum()

    theme_amt = (
        classified_snap
        .drop_duplicates(subset=["main_group", "country", "code"])
        .groupby(["main_group", "country"])["twd_yi"]
        .sum()
        .unstack(fill_value=0)
    )
    for c in markets:
        if c not in theme_amt.columns:
            theme_amt[c] = 0.0

    share = theme_amt[markets].div(country_totals.reindex(markets), axis=1) * 100
    scores = share.sum(axis=1).reset_index()
    scores.columns = ["main_group", "theme_score"]
    return scores


def build_xq_lines(conn, snapshot_date, previous_date, markets, top_n, top_n_per_market):
    # ── 計算熱度 Δ ──
    curr_scores = compute_theme_hotness(conn, snapshot_date, markets)

    if previous_date:
        prev_scores = compute_theme_hotness(conn, previous_date, markets)
        merged = curr_scores.merge(prev_scores, on="main_group", how="left",
                                   suffixes=("", "_prev"))
        merged["delta"] = merged["theme_score"] - merged["theme_score_prev"].fillna(0)
    else:
        merged = curr_scores.copy()
        merged["delta"] = merged["theme_score"]

    # ── 只保留台股有出現的題材 ──
    tw_count = pd.read_sql("""
        SELECT c.main_group, COUNT(*) AS tw_count
        FROM rankings r
        JOIN classification c ON c.country = r.country AND c.code = r.code
        WHERE r.snapshot_date = ? AND r.country = '台'
        GROUP BY c.main_group
    """, conn, params=[snapshot_date]).set_index("main_group")["tw_count"]

    merged = merged.merge(tw_count.rename("tw_count"), on="main_group", how="left")
    merged["tw_count"] = merged["tw_count"].fillna(0)
    merged = merged[merged["tw_count"] > 0]

    # ── 上升前N + 下降前N ──
    rising  = merged.sort_values("delta", ascending=False).head(top_n)
    falling = merged.sort_values("delta", ascending=True).head(top_n)

    # ── 當週排行榜（台股全放，其他前N名）──
    placeholders = ",".join("?" * len(markets))
    all_ranked = pd.read_sql(f"""
        SELECT r.country, r.code, r.rank, c.main_group
        FROM rankings r
        JOIN classification c ON c.country = r.country AND c.code = r.code
        WHERE r.snapshot_date = ? AND r.country IN ({placeholders})
    """, conn, params=[snapshot_date] + markets)

    names_df = pd.read_sql(
        "SELECT country, code, name_zh AS name FROM company_names", conn)
    name_map = {(r.country, r.code): r.name for r in names_df.itertuples()}

    market_order = [m for m in ["台", "美", "日", "韓", "陸"] if m in markets]

    def build_section(themes_df, label_prefix, rank_offset=0):
        lines, rows = [], []
        for i, (_, row) in enumerate(themes_df.iterrows(), 1):
            theme = row["main_group"]
            delta = row["delta"]
            sign = "+" if delta >= 0 else ""
            safe_theme = theme.translate(_BAD_CHARS)
            lines.append(f"{safe_theme}_{sign}{delta:.1f}:")

            rank_i = rank_offset + i
            for market in market_order:
                mdf = all_ranked[
                    (all_ranked["main_group"] == theme) & (all_ranked["country"] == market)
                ].sort_values("rank")
                market_df = mdf if market == "台" else mdf.head(top_n_per_market)
                for _, s in market_df.iterrows():
                    code_xq = xq_code(market, s["code"])
                    lines.append(code_xq)
                    rows.append({
                        "方向": label_prefix,
                        "排名": rank_i,
                        "題材": theme,
                        "熱度Δ": round(delta, 2),
                        "市場": market,
                        "代碼": s["code"],
                        "XQ代碼": code_xq,
                        "公司": name_map.get((market, s["code"]), ""),
                        "當週排行": int(s["rank"]),
                    })
        return lines, rows

    rising_lines,  rising_rows  = build_section(rising,  "上升")
    falling_lines, falling_rows = build_section(falling, "下降", rank_offset=top_n)

    all_lines = rising_lines + falling_lines
    all_rows  = rising_rows  + falling_rows
    summary = pd.DataFrame(all_rows)
    return all_lines, len(all_rows), summary


def main():
    parser = argparse.ArgumentParser(description="生成XQ題材熱度變化自選股匯入檔")
    parser.add_argument("--top", type=int, default=15,
                        help="上升/下降各取前N個題材（預設15）")
    parser.add_argument("--per", type=int, default=5,
                        help="非台股市場每題材取前N名（預設5）")
    parser.add_argument("--markets", nargs="+", default=DEFAULT_MARKETS)
    args = parser.parse_args()

    Path(OUT_DIR).mkdir(exist_ok=True)
    conn = sqlite3.connect(DB)
    snapshot, prev_snapshot = get_two_latest_snapshots(conn)

    print(f"當週快照: {snapshot}  對比: {prev_snapshot or '無（首週）'}")
    print(f"市場: {args.markets}  上升/下降各前{args.top}題材  非台股各前{args.per}名\n")

    lines, total, summary = build_xq_lines(
        conn, snapshot, prev_snapshot, args.markets, args.top, args.per
    )
    conn.close()

    date_tag = snapshot.replace("-", "")
    out_xq = Path(OUT_DIR) / f"XQ_題材Δ_{date_tag}.csv"
    content = "\r\n".join(lines) + "\r\n"
    with open(out_xq, "wb") as f:
        f.write(content.encode("big5", errors="replace"))

    out_summary = Path(OUT_DIR) / f"題材Δ_個股名單_{date_tag}.csv"
    summary.to_csv(out_summary, index=False, encoding="utf-8-sig")

    print(f"已輸出 XQ 匯入檔：{out_xq}（共 {total} 筆）")
    print(f"已輸出 個股摘要：{out_summary}\n")

    print(f"{'方向':<4} {'排':>2} {'題材':<18} {'熱度Δ':>7}")
    print("-" * 40)
    seen = []
    for _, r in summary[["方向","排名","題材","熱度Δ"]].drop_duplicates("題材").iterrows():
        print(f"{r['方向']:<4} {r['排名']:>2}. {r['題材']:<18} {r['熱度Δ']:>+7.2f}")


if __name__ == "__main__":
    main()
