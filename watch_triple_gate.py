# -*- coding: utf-8 -*-
"""季級持股統一掃描器(2026-08-05建三重門檻版,2026-08-07升級統一版;每日台股盤後,掛update_all)。

涵蓋三條季級訊號(整合卷research_quarterly_signal_integration.html判決=互補非替代):
①主幹·雙新高(月頻狀態): P1貼高(收盤距126日高2%內)×R1(最近兩個已公布月營收皆創12月高)
  ——同引擎H40·0.5%成本年化+69.2%/Calmar1.91(候選層);預備名單=R1但價格未貼高(等突破,
  「營收先行→價格突破」lead-lag+6.49✓才是買點);題材共振標記(VCP解剖卷: 題材20日動能正
  把k120從+3.58拉到+9.17,逐年12/12)。
②衛星·三重門檻(事件): 題材成員×90日獨立突破×最新季毛利率QoQ改善,次日收盤進持40日
  (事件層k40+7.25%/組合+37.1%/Calmar1.13);52週突破版不疊毛利率;「突破但查無財報」=鐵排除
  (四卷重現k120-10.4✓)。
③埋伏配方(季頻提示): 季末月營收創12月高×季後首月也創高→季後首月13日進場→財報公布後5-10日出
  (+4.25~5.68✓,rev_preposition v3;年報版1月中→4月初+9.20✓)。
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
    # 名稱: company_names全上市櫃2,335檔為主(2026-08-07回填自tw_all_listed),rankings補缺(ETF等)
    names = dict(conn.execute("select code, name_zh from company_names where country='台'"))
    for c, n in conn.execute(
            "select code, name from rankings where country='台' and snapshot_date="
            "(select max(snapshot_date) from rankings where country='台')"):
        names.setdefault(c, n)
    fin = pd.read_sql("SELECT code, date, gross_margin FROM tw_quarterly_financials_history",
                      conn, parse_dates=["date"])
    rev = pd.read_sql("SELECT code, date, revenue FROM fm_month_rev", conn, parse_dates=["date"])
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

    # ---------- ①雙新高(月頻狀態) + 預備名單 + 題材共振 ----------
    now_ts = pd.Timestamp(datetime.now().strftime("%Y-%m-%d"))
    rev_w = rev.pivot_table(index="date", columns="code", values="revenue", aggfunc="first").sort_index()
    hi_rev = (rev_w >= rev_w.rolling(12, min_periods=12).max()) & rev_w.notna()
    pub_months = [m for m in rev_w.index
                  if (m + pd.DateOffset(months=1) + pd.Timedelta(days=11)) <= now_ts
                  or rev_w.loc[m].notna().sum() > 0]   # 法定已公布月+提早公布月(DB有值=已公布)
    dual_rows, standby_rows = [], []
    kn1 = kn2 = None
    if len(pub_months) >= 2:
        kn1, kn2 = pub_months[-1], pub_months[-2]      # 顯示用(實際逐檔取最新已公布兩月)
        last3 = rev_w.index[-3:]

        def code_r1(code):
            """逐檔取最新兩個「DB有值=已公布」的月份,兩月皆創12月高才算R1(公布空窗期各檔公平)。"""
            if code not in rev_w.columns:
                return False
            s = rev_w[code].loc[last3].dropna()
            if len(s) < 2:
                return False
            ma, mb = s.index[-1], s.index[-2]
            return bool(hi_rev.at[ma, code]) and bool(hi_rev.at[mb, code])
        dist_row = C.iloc[-1] / C.rolling(126, min_periods=100).max().iloc[-1] - 1
        liq_row = MN.rolling(20, min_periods=15).mean().iloc[-1]
        # 題材20日demean動能(共振濾網,VCP解剖卷)
        r20 = C.iloc[-1] / C.iloc[-21] - 1 if len(C) > 21 else pd.Series(dtype=float)
        theme_sets = {}
        for c, gs in theme_map.items():
            for t in gs.split("/"):
                theme_sets.setdefault(t, []).append(c)
        tmom = {}
        mkt20 = r20.median() if len(r20) else np.nan
        for t, mem in theme_sets.items():
            cols = [c for c in mem if c in r20.index]
            if len(cols) >= 2:
                tmom[t] = float(r20[cols].mean() - mkt20)
        for code in C.columns:
            if pd.isna(liq_row.get(code, np.nan)) or liq_row[code] < LIQ_MIN:
                continue
            if not code_r1(code):
                continue
            dist = dist_row.get(code, np.nan)
            if pd.isna(dist):
                continue
            gs = theme_map.get(code, "")
            reso = any(tmom.get(t, -1) > 0 for t in gs.split("/")) if gs else False
            rec = {"code": code, "name": names.get(code, ""), "theme": gs or "—",
                   "dist": f"{dist * 100:+.1f}%", "reso": "🔥共振" if reso else ""}
            if dist >= -0.02:
                dual_rows.append(rec)
            elif dist >= -0.35:
                standby_rows.append({**rec, "dist_v": dist})
        standby_rows.sort(key=lambda x: -x["dist_v"])

    # ---------- ③埋伏窗提示(當前季週期) ----------
    qe = (now_ts - pd.offsets.QuarterEnd(1)).normalize()      # 最近已結束季的季底
    nm_month = (qe + pd.offsets.MonthBegin(1)).normalize()    # 季後首月
    entry_amb = qe + pd.Timedelta(days=43)                     # 次月13日≈進場日
    anchor_amb = avail_date(qe)
    amb_status = ("進行中" if entry_amb <= now_ts <= anchor_amb + pd.Timedelta(days=14)
                  else (f"將於{entry_amb.date()}開啟" if now_ts < entry_amb else "本季已過"))
    amb_rows = []
    if len(pub_months) >= 2:
        qe_month = qe.replace(day=1)                           # 季末月
        if qe_month in hi_rev.index:
            h_qe = hi_rev.loc[qe_month]
            h_nm = hi_rev.loc[nm_month] if nm_month in hi_rev.index else None
            for code in h_qe.index[h_qe.fillna(False)]:
                if pd.isna(liq_row.get(code, np.nan)) or liq_row[code] < LIQ_MIN:
                    continue
                nm_ok = bool(h_nm.get(code, False)) if h_nm is not None else None
                amb_rows.append({"code": code, "name": names.get(code, ""),
                                 "theme": theme_map.get(code, "—"),
                                 "nm": ("✓次月也創" if nm_ok else ("✗次月未創" if nm_ok is not None else "次月待公布"))})
        amb_rows = [r for r in amb_rows if "✗" not in r["nm"]]

    print("=" * 84)
    print(f"季級持股統一掃描  台股最新交易日={last_day}(距今{age}天{'⚠陳舊' if age > 4 else ''})  產表{today}")
    print("=" * 84)
    print(f"\n🌟①雙新高主幹(P1貼高×R1兩月營收連創,月頻H40): {len(dual_rows)}檔"
          f"(營收判定月={str(kn2)[:7]}+{str(kn1)[:7]})")
    for r in dual_rows:
        print(f"  {r['code']}{r['name']:<8} [{r['theme']}] 距126日高{r['dist']} {r['reso']}")
    print(f"\n📋①預備名單(R1營收連創但價格未貼高,等突破進貼高帶再買): {len(standby_rows)}檔")
    for r in standby_rows[:25]:
        print(f"  {r['code']}{r['name']:<8} [{r['theme']}] 距高{r['dist']} {r['reso']}")
    print(f"\n🪤③埋伏配方(Q{qe.quarter}財報,進場{entry_amb.date()}→出場約{anchor_amb.date()}+5~10日): {amb_status}")
    for r in amb_rows[:30]:
        print(f"  {r['code']}{r['name']:<8} [{r['theme']}] 季末月創高 {r['nm']}")
    print("\n" + "=" * 84)
    print(f"②衛星·三重門檻(題材×90日突破×gm改善,次日收盤進持{HOLD}日)")
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
<title>季級持股統一掃描 {last_day}</title><style>
body{{background:#1a1a19;color:#fff;font-family:"Noto Sans TC",sans-serif;margin:24px;max-width:1050px}}
h1{{font-size:18px}} h2{{font-size:14px;color:#c3c2b7;margin-top:22px}}
table{{border-collapse:collapse;font-size:12.5px}} td,th{{border:1px solid #333;padding:4px 9px}}
th{{text-align:left;color:#c3c2b7}} .note{{color:#8a8878;font-size:12.5px;line-height:1.8}}
</style></head><body>
<h1>🎯 季級持股統一掃描 — {last_day}{'⚠資料陳舊' if age > 4 else ''}</h1>
<div class="note">三條互補季級訊號(整合卷判決): ①主幹雙新高(月頻,Calmar1.91) ②衛星三重門檻(事件,Calmar1.13)
③埋伏配方(季頻)。🔥共振=題材20日動能正(VCP解剖卷: k120由+3.58→+9.17)。產表{today}。</div>
<h2>🌟①雙新高主幹: P1貼高×R1兩月營收連創({len(dual_rows)}檔,營收判定月{str(kn2)[:7]}+{str(kn1)[:7]};月頻,持有40交易日滾動)</h2>
{tbl(dual_rows, [("code", "代碼"), ("name", "名稱"), ("theme", "題材"), ("dist", "距126日高"), ("reso", "共振")])}
<h2>📋①預備名單: 營收連創但價未貼高——等突破進貼高帶再買(lead-lag+6.49✓,前{min(len(standby_rows), 25)}檔)</h2>
{tbl(standby_rows[:25], [("code", "代碼"), ("name", "名稱"), ("theme", "題材"), ("dist", "距高"), ("reso", "共振")])}
<h2>🪤③埋伏配方: Q{qe.quarter}財報季({amb_status};進場{entry_amb.date()}→財報後5-10日出;條件=季末月+次月營收連創)</h2>
{tbl(amb_rows[:30], [("code", "代碼"), ("name", "名稱"), ("theme", "題材"), ("nm", "次月確認")])}
<div class="note">②衛星·三重門檻: 題材成員×90日獨立突破(前20日未曾破高)×最新季毛利率QoQ改善 →
<b>次日收盤進場,持有{HOLD}交易日</b>。回測: k40絕對+7.25%/demean+3.84✓/勝率54%/賺賠比2.18/逐年12/12。
52週突破版不疊毛利率;「無財報資料」=鐵排除(四卷重現)。</div>
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

    # ---------- JSON匯出(儀表板「進場訊號→🌟季級持股」檢視吃這份, export_html.py讀) ----------
    import json
    payload = {
        "generated": today, "last_day": last_day, "age_days": age,
        "rev_months": f"{str(kn2)[:7]}+{str(kn1)[:7]}" if kn1 is not None else "—",
        "dual": [{k: r[k] for k in ("code", "name", "theme", "dist", "reso")} for r in dual_rows],
        "standby": [{k: r[k] for k in ("code", "name", "theme", "dist", "reso")} for r in standby_rows[:30]],
        "standby_total": len(standby_rows),
        "triple_today": [{k: r[k] for k in ("code", "name", "theme", "status")} for r in t3],
        "triple_recent": [{k: r[k] for k in ("d", "code", "name", "theme", "status")} for r in rec3],
        "holding": [{k: r[k] for k in ("d", "code", "name", "theme", "days_held", "exit_in")}
                    for r in sorted(rows_holding, key=lambda x: x["exit_in"])],
        "amb_status": amb_status, "amb_q": f"Q{qe.quarter}",
        "amb_entry": str(entry_amb.date()), "amb_anchor": str(anchor_amb.date()),
        "amb_rows": [{k: r[k] for k in ("code", "name", "theme", "nm")} for r in amb_rows[:30]],
    }
    with open("quarterly_signals.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    print("[watch] 已輸出 quarterly_signals.json(儀表板用)")


if __name__ == "__main__":
    main()
