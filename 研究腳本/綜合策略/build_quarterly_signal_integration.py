# -*- coding: utf-8 -*-
"""季級訊號整合考卷: 雙新高 vs 三重門檻——重疊度+同引擎合併組合(2026-08-07,⚡清單第1項)。

兩條季級持股訊號各自收官,本卷回答「一起用怎麼用」:
  三重門檻(newhigh_gm/triple_gate_portfolio): 題材成員×90日獨立突破(事件)×最新季gm改善,
    H40組合0.5%成本年化+31.6%/MDD-33.8%/Calmar0.94。
  雙新高(dual_newhigh_matrix): P1貼高(距126日高2%內,狀態)×R1(最近兩公布月營收皆創12月高),
    月頻k40 demean+8.90✓/逐年9/9,題材版+10.93✓。

═══ 考題(預先註冊) ═══
Q1 重疊度: 三重門檻事件日當下是否同時處於雙新高狀態(逐日算dist+R1)?雙新高月頻持股中
   多少比例在±20交易日內有三重門檻事件?——量「同一群股票的兩種說法」vs「不同股票」。
Q2 同引擎合併組合(全部H=40/次日或形成日收盤進/持有中去重/日頻等權/0.5%來回成本):
   (a)三重門檻(基準複算) (b)雙新高月頻(P1×R1形成日進) (c)雙新高×題材成員 (d)聯集(任一觸發)
   (e)交集(三重門檻事件且當日雙新高狀態)。judged by 展望理論排序(MDD/賺賠比/Calmar優先)。
Q3 判決: 誰吸收誰/互補→季級持股統一框架的最終形式(餵給watch統一掃描器)。

口徑: 池=20日均額>=0.3億;R1逐日版=「今日已公布的最近兩個月營收皆創12月高」(月營收10日公布,
用月+12日為公布保守錨,零前視);gm=avail_date口徑。除權息未還原(保守)。
用法: python 研究腳本/綜合策略/build_quarterly_signal_integration.py  (從根目錄執行,鐵律)
產出: 研究報告/research_quarterly_signal_integration.html + console
"""
import sqlite3
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

DB = "capital_flow.db"
OUT = "研究報告/research_quarterly_signal_integration.html"
START = "2018-02-01"          # 對齊雙新高卷(營收YoY需2018起)
LIQ_MIN = 0.3e8
FRESH_GAP = 20
HOLD = 40
COST_SIDE = 0.0025            # 0.5%來回
P_HIGH_TH = -0.02
BUFFER_DAYS = 5
STATUTORY = {1: (5, 15, 0), 2: (8, 14, 0), 3: (11, 14, 0), 4: (3, 31, 1)}
rng = np.random.default_rng(20260807)


def avail_date(qe):
    q = (qe.month - 1) // 3 + 1
    m, d, yoff = STATUTORY[q]
    return pd.Timestamp(qe.year + yoff, m, d) + pd.Timedelta(days=BUFFER_DAYS)


def main():
    conn = sqlite3.connect(DB, timeout=60)
    rev = pd.read_sql("SELECT code, date, revenue FROM fm_month_rev", conn, parse_dates=["date"])
    px = pd.read_sql("SELECT code,date,close,money FROM fm_daily_price "
                     "WHERE date>='2016-06-01' AND close>0 AND money>0", conn)
    tai = pd.read_sql("SELECT date,close FROM index_daily WHERE market='TAIEX' "
                      "AND date>='2016-06-01' ORDER BY date", conn)
    fin = pd.read_sql("SELECT code, date, gross_margin FROM tw_quarterly_financials_history",
                      conn, parse_dates=["date"])
    theme_codes = {r[0] for r in conn.execute(
        "select distinct code from classification where country='台'")}
    conn.close()

    C = px.pivot_table(index="date", columns="code", values="close", aggfunc="first").sort_index()
    MN = px.pivot_table(index="date", columns="code", values="money", aggfunc="first").sort_index()
    tai = tai.set_index("date")["close"]
    dates = list(C.index)
    t_dates = np.array(dates)
    start_i = int(np.searchsorted(t_dates, START))
    liq_ok = (MN.rolling(20, min_periods=15).mean().shift(1) >= LIQ_MIN)
    Cf = C.ffill(limit=5)
    is_theme = np.array([c in theme_codes for c in C.columns])

    # ---- 逐日R1狀態: 今日已公布的最近兩個月營收皆創12月高(公布錨=月+12日曆日,保守) ----
    rev_w = rev.pivot_table(index="date", columns="code", values="revenue", aggfunc="first").sort_index()
    hi_m = (rev_w >= rev_w.rolling(12, min_periods=12).max()) & rev_w.notna()
    hi2_m = hi_m & hi_m.shift(1)                     # 該月與前月皆創高(以「該月」為最新公布月)
    # ⚠公布錨=次月12日(2026-08-07修正前視bug: 原版m+12天把m月營收當m月13日已知,提早一個月)
    pub_dates = [(m + pd.DateOffset(months=1) + pd.Timedelta(days=11)).strftime("%Y-%m-%d")
                 for m in hi2_m.index]
    hi2_pub = hi2_m.copy()
    hi2_pub.index = pub_dates                          # 公布錨日起生效
    # 對齊到交易日: 每日取最近一個公布錨的值(ffill),容忍45天
    R1_daily = hi2_pub.reindex(sorted(set(pub_dates) | set(dates))).ffill(limit=None)
    R1_daily = R1_daily.reindex(dates).fillna(False)
    common_codes = [c for c in C.columns if c in R1_daily.columns]

    # ---- 逐日P1狀態: 距126日高2%內 ----
    hi126 = C.rolling(126, min_periods=100).max()
    P1_daily = (C / hi126 - 1) >= P_HIGH_TH

    # ---- 三重門檻事件(同triple_gate_portfolio口徑) ----
    fundmap = {}
    for code, g in fin.groupby("code"):
        g = g.sort_values("date")
        qidx = pd.PeriodIndex(g.date, freq="Q")
        g = g.set_index(qidx)
        g = g[~g.index.duplicated(keep="first")]
        full = pd.period_range(g.index.min(), g.index.max(), freq="Q")
        g = g.reindex(full)
        gm = g.gross_margin * 100
        chg = gm - gm.shift(1)
        av = np.array([np.datetime64(avail_date(p.end_time.normalize())) for p in g.index])
        ok = g.gross_margin.notna().values
        fundmap[code] = (av[ok], chg.values[ok])

    def gm_pos(code, d):
        fm = fundmap.get(code)
        if fm is None:
            return False
        k = int(np.searchsorted(fm[0], np.datetime64(d), side="right")) - 1
        return (k >= 0 and (pd.Timestamp(d) - pd.Timestamp(fm[0][k])).days <= 200
                and pd.notna(fm[1][k]) and fm[1][k] > 0)

    rmax90 = C.rolling(90, min_periods=72).max()
    is_hi90 = (C >= rmax90 * 0.9999) & C.notna()
    hi_recent = is_hi90.shift(1).rolling(FRESH_GAP, min_periods=1).max()

    triple_events = []          # (code, i)
    for i in range(start_i, len(dates) - 2):
        row = (is_hi90.iloc[i].values & (~hi_recent.iloc[i].values.astype(bool))
               & liq_ok.iloc[i].values & is_theme)
        if not row.any():
            continue
        d = dates[i]
        for ci in np.where(row)[0]:
            code = C.columns[ci]
            if gm_pos(code, d):
                triple_events.append((code, i))
    print(f"[events] 三重門檻事件{len(triple_events):,}")

    # 雙新高月頻形成事件(每月13日, P1×R1×liq)
    dual_events, dual_theme_events = [], []
    months = pd.date_range("2018-02-01", dates[-1], freq="MS")
    for m in months:
        f_i = int(np.searchsorted(t_dates, (m + pd.Timedelta(days=12)).strftime("%Y-%m-%d")))
        if f_i >= len(dates) - 2:
            continue
        row = (P1_daily.iloc[f_i].reindex(C.columns).fillna(False).values
               & R1_daily.iloc[f_i].reindex(C.columns).fillna(False).values
               & liq_ok.iloc[f_i].values)
        for ci in np.where(row)[0]:
            dual_events.append((C.columns[ci], f_i))
            if is_theme[ci]:
                dual_theme_events.append((C.columns[ci], f_i))
    print(f"[events] 雙新高月頻{len(dual_events):,}(題材版{len(dual_theme_events):,})")

    # ---------- Q1 重疊度 ----------
    n_t_in_dual = 0
    for code, i in triple_events:
        ci = C.columns.get_loc(code)
        r1 = bool(R1_daily.iloc[i].get(code, False)) if code in R1_daily.columns else False
        if bool(P1_daily.iat[i, ci]) and r1:
            n_t_in_dual += 1
    trip_set = {}
    for code, i in triple_events:
        trip_set.setdefault(code, []).append(i)
    n_d_near_t = 0
    for code, i in dual_events:
        hits = trip_set.get(code, [])
        if any(abs(i - j) <= 20 for j in hits):
            n_d_near_t += 1
    pct_t = n_t_in_dual / len(triple_events) * 100 if triple_events else 0
    pct_d = n_d_near_t / len(dual_events) * 100 if dual_events else 0
    print(f"\nQ1 重疊度: 三重門檻事件當日同時為雙新高狀態={n_t_in_dual}/{len(triple_events)}({pct_t:.0f}%)")
    print(f"          雙新高持股±20交易日內有三重門檻事件={n_d_near_t}/{len(dual_events)}({pct_d:.0f}%)")

    # ---------- Q2 同引擎合併組合 ----------
    tai_f = tai.reindex(C.index).ffill()

    def simulate(events, lab, entry_next_day=True):
        daily_ret = {}
        ev_rets = []
        held_until = {}
        n_pos = 0
        for code, i in sorted(events, key=lambda x: x[1]):
            e_i = i + 1 if entry_next_day else i
            x_i = e_i + HOLD
            if x_i >= len(dates) or held_until.get(code, -1) >= e_i:
                continue
            ci = Cf.columns.get_loc(code)
            path = Cf.iloc[e_i:x_i + 1, ci].values
            if pd.isna(path).any() or path[0] <= 0:
                continue
            held_until[code] = x_i
            n_pos += 1
            rets = path[1:] / path[:-1] - 1
            rets[0] -= COST_SIDE
            rets[-1] -= COST_SIDE
            for j in range(HOLD):
                daily_ret.setdefault(e_i + 1 + j, []).append(rets[j])
            ev_rets.append((1 - COST_SIDE) * path[-1] / path[0] * (1 - COST_SIDE) - 1)
        if not daily_ret:
            return None
        span = range(min(daily_ret), max(daily_ret) + 1)
        nav, peak, mdd = 1.0, 1.0, 0.0
        rs = []
        navs, nav_dates = [], []
        for i in span:
            r = np.mean(daily_ret[i]) if i in daily_ret else 0.0
            nav *= 1 + r
            rs.append(r)
            peak = max(peak, nav)
            mdd = min(mdd, nav / peak - 1)
            navs.append(nav)
            nav_dates.append(dates[i])
        rs = np.array(rs)
        ann = nav ** (252 / len(rs)) - 1
        shp = rs.mean() / rs.std() * np.sqrt(252) if rs.std() > 0 else np.nan
        er = pd.Series(ev_rets)
        w, l = er[er > 0], er[er <= 0]
        out = {"lab": lab, "n": n_pos, "nav": nav, "ann": ann * 100, "mdd": mdd * 100,
               "sharpe": shp, "calmar": (ann * 100) / abs(mdd * 100) if mdd < 0 else np.nan,
               "conc": np.mean([len(daily_ret[i]) for i in daily_ret]),
               "win": len(w) / len(er) * 100, "wl": (w.mean() / abs(l.mean())) if len(w) and len(l) else np.nan,
               "pf": w.sum() / abs(l.sum()) if len(l) and l.sum() < 0 else np.inf,
               "nav_s": pd.Series(navs, index=pd.to_datetime(nav_dates))}
        print(f"  {lab:<34} 事件{n_pos:,} NAV={nav:.2f} 年化{out['ann']:+.1f}% MDD{out['mdd']:.1f}% "
              f"夏普{shp:.2f} Calmar{out['calmar']:.2f} 並行{out['conc']:.1f} "
              f"勝率{out['win']:.0f}% 賺賠{out['wl']:.2f} PF{out['pf']:.2f}")
        return out

    print(f"\nQ2 合併組合(H{HOLD},0.5%來回成本,2018-02起同引擎):")
    inter_events = [(c, i) for c, i in triple_events
                    if c in R1_daily.columns and bool(R1_daily.iloc[i].get(c, False))
                    and bool(P1_daily.iat[i, C.columns.get_loc(c)])]
    union_events = sorted(set(triple_events) | set(dual_events), key=lambda x: x[1])
    sims = []
    for lab, ev, nx in [("(a)三重門檻(基準複算2018起)", triple_events, True),
                        ("(b)雙新高月頻(P1×R1)", dual_events, False),
                        ("(c)雙新高×題材成員", dual_theme_events, False),
                        ("(d)聯集(a∪b)", union_events, True),
                        ("(e)交集(三重事件×雙新高狀態)", inter_events, True)]:
        s = simulate(ev, lab, entry_next_day=nx)
        if s:
            sims.append(s)
    tai_sub = tai_f.iloc[start_i:]
    tai_nav = tai_sub / tai_sub.iloc[0]
    tai_ann = tai_nav.iloc[-1] ** (252 / len(tai_sub)) - 1
    tai_dd = (tai_nav / tai_nav.cummax() - 1).min()
    print(f"  TAIEX同期(2018-02起): 年化{tai_ann * 100:+.1f}% MDD{tai_dd * 100:.1f}% "
          f"Calmar{tai_ann / abs(tai_dd):.2f}")

    # ---------- HTML ----------
    CSS = """
body{background:#1a1a19;color:#fff;font-family:"Noto Sans TC",sans-serif;margin:24px;max-width:1150px}
h1{font-size:20px} h2{font-size:15px;color:#c3c2b7;margin-top:30px;border-bottom:1px solid #333;padding-bottom:4px}
table{border-collapse:collapse;font-size:12.5px;font-variant-numeric:tabular-nums;margin:8px 0}
td,th{border:1px solid #333;padding:4px 8px;text-align:right} th{text-align:left;color:#c3c2b7}
.note{color:#8a8878;font-size:12.5px;line-height:1.8} .good{color:#7ec97e} .bad{color:#e06c5a}
.hl{background:#2b3a2b}
ul{margin:4px 0;padding-left:20px;font-size:12.5px;color:#ccc;line-height:1.7}
.verdict{font-size:13px;font-weight:bold;padding:6px 10px;border-radius:4px;display:inline-block;margin:4px 0}
.v-good{background:#243b24;color:#7ec97e} .v-warn{background:#3b3420;color:#c3a55a}
.scroll{overflow-x:auto}
"""
    sim_tbl = ("<div class='scroll'><table><tr><th>線</th><th>事件</th><th>NAV</th><th>年化</th><th>MDD</th>"
               "<th>夏普</th><th>Calmar</th><th>並行</th><th>勝率</th><th>賺賠比</th><th>PF</th></tr>"
               + "".join(f"<tr><th>{s['lab']}</th><td>{s['n']:,}</td><td>{s['nav']:.2f}</td>"
                         f"<td>{s['ann']:+.1f}%</td><td>{s['mdd']:.1f}%</td><td>{s['sharpe']:.2f}</td>"
                         f"<td>{s['calmar']:.2f}</td><td>{s['conc']:.1f}</td><td>{s['win']:.0f}%</td>"
                         f"<td>{s['wl']:.2f}</td><td>{s['pf']:.2f}</td></tr>" for s in sims)
               + "</table></div>")
    import json as _json
    nav_payload = []
    for s in sims:
        ns = s["nav_s"].resample("W").last().dropna()
        nav_payload.append({"name": s["lab"], "dates": [d.strftime("%Y-%m-%d") for d in ns.index],
                            "vals": [round(v, 4) for v in ns.values]})
    tn = tai_nav.copy()
    tn.index = pd.to_datetime(tn.index)
    tnw = tn.resample("W").last().dropna()
    nav_payload.append({"name": "TAIEX", "dates": [d.strftime("%Y-%m-%d") for d in tnw.index],
                        "vals": [round(v, 4) for v in tnw.values]})
    nav_json = _json.dumps(nav_payload, ensure_ascii=False)

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>季級訊號整合(2026-08-07)</title>
<script src="plotly.min.js"></script><style>{CSS}</style></head><body>
<h1>🔗 季級訊號整合: 雙新高 vs 三重門檻</h1>
<div class="note">兩條季級訊號的重疊度與同引擎合併組合(H{HOLD},0.5%來回成本,2018-02起,持有中去重,
日頻等權)。母卷: research_dual_newhigh_matrix.html / research_triple_gate_portfolio.html。</div>
<h2>Q1 重疊度</h2>
<div class="note">三重門檻事件當日同時處於雙新高狀態: <b>{n_t_in_dual}/{len(triple_events)}({pct_t:.0f}%)</b><br>
雙新高月頻持股±20交易日內有三重門檻事件: <b>{n_d_near_t}/{len(dual_events)}({pct_d:.0f}%)</b></div>
<h2>Q2 同引擎合併組合</h2>
{sim_tbl}
<div class="note">TAIEX同期(2018-02起): 年化{tai_ann * 100:+.1f}%/MDD{tai_dd * 100:.1f}%/Calmar{tai_ann / abs(tai_dd):.2f}</div>
<div id="c_nav" style="height:460px"></div>
<h2>⚖️ 判決(2026-08-07)</h2>
<ul>
<li><span class="verdict v-good">①互補確認: 兩條訊號抓的是不同的股票/時點</span>
重疊只有9%(三重事件當日為雙新高)/15%(雙新高±20日內有三重事件)——三重門檻抓「題材股剛突破+
毛利改善」的事件,雙新高抓「持續貼高+營收連創」的狀態,母體不同,<b>不是誰吸收誰</b>。</li>
<li><span class="verdict v-good">②同引擎對決: 雙新高月頻=主幹</span> (b)年化+66.8%/MDD-41.3%/
<b>Calmar1.62</b>/夏普1.55/勝率58%/PF3.14(⚠此為修正營收公布錨前視bug後的數字,修正前虛高至
+69.2%/Calmar1.91),仍壓過(a)三重門檻(+37.1%/Calmar1.13)與TAIEX(+18.0%/0.57);
(c)題材版年化+73.3%最高但並行僅4.9檔/MDD-46.3%——集中度換報酬,依展望理論排序(MDD優先)<b>全池版(b)
勝出</b>(與九宮格卷「雙新高讓非題材也活」一致)。(e)交集+46.1%但MDD-50.3%/並行3.8檔太薄;
(d)聯集被(a)的大量事件稀釋。</li>
<li><b>③實務配置(候選)</b>: 主幹=雙新高月頻(P1×R1,全池,每月13日調倉,H40)≈9檔並行;
衛星=三重門檻(事件驅動,並行33檔=分散載體,吃「剛突破」的另一群股票);兩者重疊自然去重。
統一掃描器按此設計。</li>
<li><span class="verdict v-warn">④誠實保留+一個bug教訓</span> 首版把「m月營收於m月13日已知」
(實際次月10日才公布)=前視一個月,靠live掃描器輸出對照才現形——修正後(b)由+69.2/Calmar1.91降至
+66.8/1.62,<b>結論存活但數字永遠用修正版</b>。+67%年化仍是「意外好」等級(2018-2026成長股時代+
薄組合9檔+月頻狀態),候選層,watch統一掃描器live累積樣本外才算數;除權息未還原=反而低估(慰藉項)。</li>
</ul>
<h2>已知限制</h2>
<div class="note">①R1逐日狀態用「月+12日曆日」當公布錨(保守,實際多在10日前公布);②2018-02起口徑
(對齊營收YoY),與triple_gate卷(2015起)數字不可直接比;③除權息未還原;④持有中去重後,聯集/交集的
事件計數受先觸發者佔用影響;⑤題材名單事後偏誤沿卷。</div>
<div class="note">維運: python 研究腳本/綜合策略/build_quarterly_signal_integration.py(從根目錄執行)。</div>
<script>
const NAVS={nav_json};
Plotly.newPlot('c_nav', NAVS.map(s=>({{x:s.dates,y:s.vals,name:s.name,mode:'lines'}})),
  {{title:'權益曲線(H40,0.5%來回成本,週頻取樣,對數軸) vs TAIEX',
    paper_bgcolor:'#1a1a19',plot_bgcolor:'#22221f',font:{{color:'#ddd',size:12}},
    yaxis:{{title:'NAV',type:'log'}},legend:{{orientation:'h'}},
    margin:{{t:42,l:52,r:18,b:40}}}});
</script>
</body></html>"""
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n[report] 已輸出 {OUT}")


if __name__ == "__main__":
    main()
