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
import json
import sqlite3
from pathlib import Path

import pandas as pd

DB = "capital_flow.db"
OUT_DIR = "XQ檔案匯入"
SIGNALS_FILE = "signals_export.json"

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


def build_signal_lines(name_map):
    """讀 signals_export.json(由export_html.py每次匯出時同步寫出)，組出「系統訊號候選」分類。
    來源＝規則①~⑤觸發題材前3大成員 / 微題材A・B級成員 / 補漲雷達A・B級 / 外資位階>=80中小型股(排名>50)。
    這組是「系統認為現在該盯著看」的名單，跟熱度Δ組（什麼題材在變熱/變冷）互補，不重複。"""
    path = Path(SIGNALS_FILE)
    if not path.exists():
        print(f"[提醒] 找不到 {SIGNALS_FILE}，請先跑過 export_html.py 再產生本分類（跳過不影響熱度Δ組）")
        return [], []
    sig = json.loads(path.read_text(encoding="utf-8"))

    lines, rows = [], []
    seen_codes = set()   # 同一檔股票在系統訊號組只放一次(以第一次出現的來源為準),避免XQ清單重複灌水

    def add_group(label, codes_with_theme, source):
        codes_with_theme = [(c, t) for c, t in codes_with_theme if c not in seen_codes]
        if not codes_with_theme:
            return
        # 數字用這組成員數，純整數不帶小數點(小數點在XQ匯入格式裡也會導致失敗)
        lines.append(f"{label}_{len(codes_with_theme)}:")
        for code, theme in codes_with_theme:
            code_xq = xq_code("台", code)
            lines.append(code_xq)
            seen_codes.add(code)
            rows.append({"方向": "系統訊號", "來源": source, "題材": theme,
                        "市場": "台", "代碼": code, "XQ代碼": code_xq,
                        "公司": name_map.get(("台", code), "")})

    # XQ標籤慣例是「名稱_數字分數:」結尾必須是數字，不能放等第字母(或加後綴變成空字串)，
    # 等第資訊只留在CSV摘要，標籤本身保持乾淨字串(比照既有題材Δ標籤的安全字元處理)
    for h in sig.get("rule_hits", []):
        safe_theme = h["theme"].translate(_BAD_CHARS)
        add_group(f"訊號規則_{safe_theme}",
                  [(c, h["theme"]) for c in h["top3"]], "規則①~⑤觸發前3大")
    for h in sig.get("micro_hits", []):
        safe_theme = h["theme"].translate(_BAD_CHARS)
        add_group(f"微題材_{safe_theme}",
                  [(c, h["theme"]) for c in h["members"]], "微題材脈衝")
    add_group("補漲雷達候選",
              [(h["code"], h["theme"]) for h in sig.get("catchup_hits", [])], "補漲雷達A/B級")
    add_group("籌碼位階確認",
              [(c, "") for c in sig.get("chip_hits", [])], "外資位階>=80(排名>50)")

    return lines, rows


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
    # company_names表沒有台股(只有日/美/陸/韓)，台股中文名要從rankings表拿(該表本身就存中文名)；
    # 取每檔最近一次出現的名字，避免訊號候選裡有代碼剛好不在最新一週快照裡而查無名字
    tw_name_map = {("台", r.code): r.name for r in pd.read_sql(
        "SELECT code, name FROM (SELECT code, name, snapshot_date FROM rankings "
        "WHERE country='台' ORDER BY snapshot_date) GROUP BY code",
        conn, dtype={"code": str}
    ).itertuples()}
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

    # ── 系統訊號候選(規則觸發/微題材/補漲雷達/籌碼位階)，獨立一份XQ檔 ──
    sig_lines, sig_rows = build_signal_lines(tw_name_map)
    if sig_lines:
        out_sig_xq = Path(OUT_DIR) / f"XQ_系統訊號_{date_tag}.csv"
        sig_content = "\r\n".join(sig_lines) + "\r\n"
        with open(out_sig_xq, "wb") as f:
            f.write(sig_content.encode("big5", errors="replace"))
        out_sig_summary = Path(OUT_DIR) / f"系統訊號_個股名單_{date_tag}.csv"
        pd.DataFrame(sig_rows).to_csv(out_sig_summary, index=False, encoding="utf-8-sig")
        print(f"已輸出 系統訊號XQ檔：{out_sig_xq}（共 {len(sig_rows)} 筆，{len(set(r['代碼'] for r in sig_rows))} 檔不重複）")
        print(f"已輸出 系統訊號摘要：{out_sig_summary}\n")

    print(f"{'方向':<4} {'排':>2} {'題材':<18} {'熱度Δ':>7}")
    print("-" * 40)
    seen = []
    for _, r in summary[["方向","排名","題材","熱度Δ"]].drop_duplicates("題材").iterrows():
        print(f"{r['方向']:<4} {r['排名']:>2}. {r['題材']:<18} {r['熱度Δ']:>+7.2f}")


if __name__ == "__main__":
    main()
