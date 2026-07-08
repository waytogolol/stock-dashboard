# -*- coding: utf-8 -*-
"""資料驗證機制：對DB內各資料源做範圍/新鮮度/交叉一致性檢查
用法: python validate_data.py   (建議每週refresh後跑，或抓完新資料後跑)
輸出: tmp_validation_report.txt，有 CRITICAL 時 exit code = 1
"""
import sqlite3
import sys
from datetime import date, datetime

import pandas as pd

DB = "capital_flow.db"
report, warns, crits = [], [], []


def check(name, ok, detail, critical=False):
    tag = "PASS" if ok else ("CRIT" if critical else "WARN")
    report.append(f"[{tag}] {name}: {detail}")
    if not ok:
        (crits if critical else warns).append(name)


conn = sqlite3.connect(DB)

# ── 1. 範圍合理性 ────────────────────────────────────────────────────
q = pd.read_sql("SELECT * FROM tw_quarterly_fin", conn)
bad_gm = q[(q["gross_margin"].notna()) & ((q["gross_margin"] < -100) | (q["gross_margin"] > 100))]
check("季損益毛利率範圍", len(bad_gm) == 0, f"{len(bad_gm)} 筆超出[-100,100]% / 共{len(q)}筆", critical=len(bad_gm) > 20)

v = pd.read_sql("SELECT * FROM tw_valuation", conn)
bad_pb = v[(v["pb"].notna()) & ((v["pb"] <= 0) | (v["pb"] > 200))]
check("估值PB範圍", len(bad_pb) == 0, f"{len(bad_pb)} 筆PB異常 / 共{len(v)}筆")

m = pd.read_sql("SELECT * FROM tw_monthly_revenue", conn)
bad_rev = m[m["revenue"] < 0]
check("月營收非負", len(bad_rev) == 0, f"{len(bad_rev)} 筆負值 / 共{len(m)}筆", critical=len(bad_rev) > 0)

# ── 2. 新鮮度 ────────────────────────────────────────────────────────
ym = sorted(m["year_month"].unique())
report.append(f"[INFO] 月營收資料年月: {ym[-3:] if len(ym) >= 3 else ym}（民國年月格式）")
qs = sorted(q["quarter"].unique())
report.append(f"[INFO] 季損益季度: {qs}（注意：MOPS此表為年初至該季累計值，Q1=單季，Q2起需扣減前季才是單季——毛利率方向計算時處理）")

rk = pd.read_sql("SELECT MAX(snapshot_date) d FROM rankings", conn)["d"].iloc[0]
days_old = (date.today() - datetime.strptime(rk, "%Y-%m-%d").date()).days
check("排名快照新鮮度", days_old <= 10, f"最新快照 {rk}（{days_old}天前）", critical=days_old > 21)

f_upd = pd.read_sql("SELECT MAX(updated) u FROM fundamentals", conn)["u"].iloc[0]
f_days = (date.today() - datetime.strptime(f_upd, "%Y-%m-%d").date()).days
check("yfinance基本面新鮮度", f_days <= 100, f"最後更新 {f_upd}（{f_days}天前，季更即可）")

# ── 3. 覆蓋率 ────────────────────────────────────────────────────────
tw300 = pd.read_csv("tw_top300.csv", dtype=str)["code"]
for tbl, col in [("tw_monthly_revenue", "月營收"), ("tw_quarterly_fin", "季損益"), ("tw_valuation", "估值")]:
    codes = set(pd.read_sql(f"SELECT DISTINCT code FROM {tbl}", conn)["code"])
    cov = tw300.isin(codes).mean() * 100
    check(f"{col}覆蓋tw_top300", cov >= 90, f"{cov:.0f}%", critical=cov < 70)

# ── 4. 交叉一致性（yfinance vs 官方）────────────────────────────────
yf_f = pd.read_sql("SELECT code, gross_margin, pb FROM fundamentals WHERE country='台'", conn)
latest_q = qs[-1]
off_q = q[q["quarter"] == latest_q][["code", "gross_margin"]].rename(columns={"gross_margin": "gm_off"})
xm = yf_f.merge(off_q, on="code")
xm = xm[xm["gross_margin"].notna() & xm["gm_off"].notna()]
xm["diff"] = (xm["gross_margin"] * 100 - xm["gm_off"]).abs()   # yfinance存比例(0.21)，MOPS存百分比(21.0)
big = xm[xm["diff"] > 8]
check("毛利率交叉(yf vs MOPS)", len(big) <= len(xm) * 0.15,
      f"{len(xm)}檔可比對，{len(big)}檔差異>8pp" + (f"，樣本: {big.head(5)[['code','gross_margin','gm_off']].values.tolist()}" if len(big) else ""))

xv = yf_f.merge(v[["code", "pb"]].rename(columns={"pb": "pb_off"}), on="code")
xv = xv[xv["pb"].notna() & xv["pb_off"].notna() & (xv["pb_off"] > 0)]
xv["ratio"] = xv["pb"] / xv["pb_off"]
bad_ratio = xv[(xv["ratio"] < 0.7) | (xv["ratio"] > 1.4)]
check("PB交叉(yf vs TWSE)", len(bad_ratio) <= len(xv) * 0.15,
      f"{len(xv)}檔可比對，{len(bad_ratio)}檔比值超出[0.7,1.4]")

# ── 5. 抽樣列印(人工eyeball) ─────────────────────────────────────────
for code, name in [("2330", "台積電"), ("2351", "順德"), ("8033", "雷虎")]:
    mr = m[m["code"] == code].sort_values("year_month").tail(2)
    qr = q[q["code"] == code]
    vr = v[v["code"] == code]
    mtxt = "; ".join(f"{r['year_month']}:{r['revenue']/1e5:.0f}億 YoY{r['yoy_pct']:.1f}%" for _, r in mr.iterrows())   # 官方單位=千元
    qtxt = "; ".join(f"{r['quarter']}:{r['gross_margin']:.1f}%" if pd.notna(r["gross_margin"]) else f"{r['quarter']}:-"
                     for _, r in qr.iterrows())
    pbtxt = vr["pb"].iloc[0] if len(vr) else "-"
    report.append(f"[樣本] {name}({code}) 月營收[{mtxt}] 季毛利率[{qtxt}] PB={pbtxt}")

conn.close()
summary = f"\n===== 總結: {len(crits)} CRITICAL / {len(warns)} WARN ====="
report.append(summary)
with open("tmp_validation_report.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(report))
print(f"done -> tmp_validation_report.txt  (CRIT={len(crits)} WARN={len(warns)})")
sys.exit(1 if crits else 0)
