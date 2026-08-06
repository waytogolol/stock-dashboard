# -*- coding: utf-8 -*-
"""三重門檻live掃描器(2026-08-05建,每日台股盤後跑,掛update_all build步)。

三重門檻=題材成員×90日獨立突破(收盤破近90日高且前20日未曾破)×最新已公告季毛利率QoQ改善。
依據: research_newhigh_gm.html(事件層k40絕對+7.25%/demean+3.84✓/勝率54%/賺賠比2.18/逐年12/12)
+ research_triple_gate_portfolio.html(組合層)。狀態=候選層live驗證中,本工具就是樣本外累積器。
操作口徑: 訊號日**次日收盤**進場,持有40交易日(收對收);52週(240日)突破版不用疊毛利率門檻
(交乘卷判決);「突破但查無財報」=排除(三卷一致大負)。
用法: python watch_triple_gate.py   (從根目錄執行;前置=當日fm_daily_price已更新)
產出: console + 研究報告/watch_triple_gate.html
"""
import sqlite3
import sys
from datetime import datetime

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

DB = "capital_flow.db"
OUT = "研究報告/watch_triple_gate.html"
LIQ_MIN = 0.3e8
N_HI = 90
N_HI_LT = 240
FRESH_GAP = 20
HOLD = 40
LOOKBACK_TRIG = 5        # 近N日觸發清單
BUFFER_DAYS = 5
STATUTORY = {1: (5, 15, 0), 2: (8, 14, 0), 3: (11, 14, 0), 4: (3, 31, 1)}


def avail_date(quarter_end):
    qe = pd.Timestamp(quarter_end)
    q = (qe.month - 1) // 3 + 1
    m, d, yoff = STATUTORY[q]
    return pd.Timestamp(qe.year + yoff, m, d) + pd.Timedelta(days=BUFFER_DAYS)


def main():
    conn = sqlite3.connect(DB, timeout=60)
    px = pd.read_sql(
        "SELECT code,date,close,money FROM fm_daily_price "
        "WHERE date>=date((select max(date) from fm_daily_price),'-600 day') "
        "AND close>0 AND money>0", conn)
    theme_map = dict(conn.execute(
        "select code, group_concat(main_group,'/') from classification "
        "where country='台' group by code"))
    names = dict(conn.execute(
        "select code, name from rankings where country='台' and snapshot_date="
        "(select max(snapshot_date) from rankings where country='台')"))
    fin = pd.read_sql("SELECT code, date, gross_margin FROM tw_quarterly_financials_history",
                      conn, parse_dates=["date"])
    conn.close()

    C = px.pivot_table(index="date", columns="code", values="close", aggfunc="first").sort_index()
    MN = px.pivot_table(index="date", columns="code", values="money", aggfunc="first").sort_index()
    last_day = C.index[-1]
    age = (datetime.now() - datetime.strptime(last_day, "%Y-%m-%d")).days
    today = datetime.now().strftime("%Y-%m-%d %H:%M")

    liq_ok = (MN.rolling(20, min_periods=15).mean().shift(1) >= LIQ_MIN)
    events = {}
    for N, key in ((N_HI, "90"), (N_HI_LT, "240")):
        rmax = C.rolling(N, min_periods=int(N * 0.8)).max()
        is_hi = (C >= rmax * 0.9999) & C.notna()
        fresh = is_hi & (~is_hi.shift(1).rolling(FRESH_GAP, min_periods=1).max().astype(bool)) & liq_ok
        events[key] = fresh

    # gm最新已公告季
    gm_now = {}
    cutoff = pd.Timestamp(last_day)
    for code, g in fin.groupby("code"):
        g = g.sort_values("date")
        qidx = pd.PeriodIndex(g.date, freq="Q")
        g = g.set_index(qidx)
        g = g[~g.index.duplicated(keep="first")]
        full = pd.period_range(g.index.min(), g.index.max(), freq="Q")
        g = g.reindex(full)
        gm = g.gross_margin * 100
        chg = gm - gm.shift(1)
        av = pd.Series([avail_date(p.end_time.normalize()) for p in g.index], index=g.index)
        ok = g.gross_margin.notna() & (av <= cutoff)
        if ok.any():
            last_q = g.index[ok][-1]
            v = chg.get(last_q, np.nan)
            if pd.notna(v) and (cutoff - av[last_q]).days <= 200:
                gm_now[code] = (str(last_q), float(v))

    def describe(code, di):
        nm = names.get(code, "")
        th = theme_map.get(code, "")
        q, v = gm_now.get(code, ("—", np.nan))
        return nm, th, q, v

    def classify(code):
        """回傳(gate3狀態字串, 過三關?)"""
        th = theme_map.get(code)
        g = gm_now.get(code)
        if th is None:
            return "非題材成員", False
        if g is None:
            return "無財報資料(排除)", False
        if g[1] > 0:
            return f"gm改善{g[1]:+.1f}pp({g[0]})", True
        return f"gm惡化{g[1]:+.1f}pp({g[0]})", False

    dates = list(C.index)
    rows_today, rows_recent, rows_holding, rows_lt = [], [], [], []
    f90 = events["90"]
    for offset in range(0, HOLD + 1):
        i = len(dates) - 1 - offset
        if i < 0:
            break
        d = dates[i]
        for code in f90.columns[f90.iloc[i].fillna(False).values]:
            status, ok3 = classify(code)
            nm, th, q, v = describe(code, i)
            rec = {"d": d, "code": code, "name": nm, "theme": th or "—", "status": status,
                   "ok3": ok3, "close": C.iloc[i][code], "days_held": offset,
                   "exit_in": HOLD - offset}
            if offset == 0:
                rows_today.append(rec)
            elif offset <= LOOKBACK_TRIG:
                rows_recent.append(rec)
            if ok3 and 0 < offset <= HOLD:
                rows_holding.append(rec)
    # 52週版(今日+近5日,不疊gm,只需題材成員)
    f240 = events["240"]
    for offset in range(0, LOOKBACK_TRIG + 1):
        i = len(dates) - 1 - offset
        if i < 0:
            break
        d = dates[i]
        for code in f240.columns[f240.iloc[i].fillna(False).values]:
            if theme_map.get(code) is None:
                continue
            nm = names.get(code, "")
            rows_lt.append({"d": d, "code": code, "name": nm,
                            "theme": theme_map.get(code, "—")})

    print("=" * 84)
    print(f"三重門檻live掃描  台股最新交易日={last_day}(距今{age}天{'⚠陳舊' if age > 4 else ''})  產表{today}")
    print(f"規則: 題材成員×90日獨立突破×gm改善 → 次日收盤進場,持有{HOLD}交易日;52週突破版不疊gm")
    print("=" * 84)
    t3 = [r for r in rows_today if r["ok3"]]
    print(f"\n🎯 今日三重門檻觸發({len(t3)}檔):")
    for r in t3:
        print(f"  {r['code']}{r['name']:<8} [{r['theme']}] {r['status']} 收盤{r['close']}")
    others = [r for r in rows_today if not r["ok3"]]
    if others:
        print(f"\n(今日90日突破但未過三關,參考: {len(others)}檔)")
        for r in others[:15]:
            print(f"  {r['code']}{r['name']:<8} [{r['theme']}] {r['status']}")
    rec3 = [r for r in rows_recent if r["ok3"]]
    print(f"\n近{LOOKBACK_TRIG}日三重門檻觸發({len(rec3)}檔,仍可視為進場窗):")
    for r in rec3:
        print(f"  {r['d']} {r['code']}{r['name']:<8} [{r['theme']}] {r['status']}")
    print(f"\n持有中(近{HOLD}交易日內觸發,{len(rows_holding)}檔):")
    for r in sorted(rows_holding, key=lambda x: x["exit_in"]):
        print(f"  {r['d']}進 {r['code']}{r['name']:<8} [{r['theme']}] 已持{r['days_held']}日/出場倒數{r['exit_in']}日")
    print(f"\n52週突破×題材成員(今日+近{LOOKBACK_TRIG}日,{len(rows_lt)}檔,不疊gm):")
    for r in rows_lt:
        print(f"  {r['d']} {r['code']}{r['name']:<8} [{r['theme']}]")

    def tbl(rows, cols):
        if not rows:
            return "<div class='note'>無</div>"
        head = "".join(f"<th>{c[1]}</th>" for c in cols)
        body = "".join("<tr>" + "".join(f"<td style='text-align:left'>{r.get(c[0], '')}</td>" for c in cols) + "</tr>"
                       for r in rows)
        return f"<table><tr>{head}</tr>{body}</table>"

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>三重門檻live {last_day}</title><style>
body{{background:#1a1a19;color:#fff;font-family:"Noto Sans TC",sans-serif;margin:24px;max-width:1050px}}
h1{{font-size:18px}} h2{{font-size:14px;color:#c3c2b7;margin-top:22px}}
table{{border-collapse:collapse;font-size:12.5px}} td,th{{border:1px solid #333;padding:4px 9px}}
th{{text-align:left;color:#c3c2b7}} .note{{color:#8a8878;font-size:12.5px;line-height:1.8}}
</style></head><body>
<h1>🎯 三重門檻live掃描 — {last_day}{'⚠資料陳舊' if age > 4 else ''}</h1>
<div class="note">規則: 題材成員×90日獨立突破(前20日未曾破高)×最新季毛利率QoQ改善 →
<b>次日收盤進場,持有{HOLD}交易日</b>。回測: k40絕對+7.25%/demean+3.84✓/勝率54%/賺賠比2.18/逐年12/12
(research_newhigh_gm.html+research_triple_gate_portfolio.html;候選層,本頁=live樣本外累積)。
52週突破版不疊毛利率;「無財報資料」=排除。產表{today}。</div>
<h2>今日三重門檻觸發({len(t3)})</h2>
{tbl(t3, [("code", "代碼"), ("name", "名稱"), ("theme", "題材"), ("status", "毛利率"), ("close", "收盤")])}
<h2>近{LOOKBACK_TRIG}日觸發({len(rec3)})</h2>
{tbl(rec3, [("d", "訊號日"), ("code", "代碼"), ("name", "名稱"), ("theme", "題材"), ("status", "毛利率")])}
<h2>持有中({len(rows_holding)})</h2>
{tbl(sorted(rows_holding, key=lambda x: x['exit_in']),
     [("d", "訊號日"), ("code", "代碼"), ("name", "名稱"), ("theme", "題材"), ("days_held", "已持日"), ("exit_in", "出場倒數")])}
<h2>52週突破×題材成員(今日+近{LOOKBACK_TRIG}日,{len(rows_lt)},不疊gm)</h2>
{tbl(rows_lt, [("d", "訊號日"), ("code", "代碼"), ("name", "名稱"), ("theme", "題材")])}
<h2>今日90日突破但未過三關(參考,{len(others)})</h2>
{tbl(others, [("code", "代碼"), ("name", "名稱"), ("theme", "題材"), ("status", "未過原因")])}
<div class="note">維運: python watch_triple_gate.py(從根目錄,台股日線更新後);已掛update_all build步。</div>
</body></html>"""
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n[watch] 已輸出 {OUT}")


if __name__ == "__main__":
    main()
