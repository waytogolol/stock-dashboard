# -*- coding: utf-8 -*-
"""月營收品質→季報埋伏考卷(2026-08-06,使用者假說:「當月營收預期值都很好的時候,季財報公布
就很可能優於預期,因此可以公布季報前就先埋伏買」)。

台股結構優勢: 月營收強制揭露(次月10日前)→ 季底次月10日「該季三個月營收全部已知」,而季報
要到法定期限(Q1=5/15/Q2=8/14/Q3=11/14/年報=3/31)才公布——中間~1個月=「已知營收、未知毛利」
的埋伏窗。既有判決: research_earnings_preannounce_reaction=全樣本公告前短窗**不顯著**、
熱度分組才有(+4.95pp/20日);本卷測的新角度=用「月營收品質」篩埋伏對象。

═══ 三段考題(預先註冊) ═══
P0 前提檢查(使用者的因果鏈第一環): P(該季毛利率QoQ改善 | 季營收YoY強) vs 基準率——
   營收好是否真的預示財報內容好?(case-control基準率鐵律,feedback第11條)
P1 埋伏窗報酬: entry=季底次月13日後首個交易日(三個月營收全部已知+2天緩衝)收盤買進,
   持有到anchor=財報可得日(法定期限+5→首個交易日)=「純埋伏窗」;另測entry→anchor+10
   (含公告後10日,吃PEAD)與anchor→anchor+10(純公告窗)三段分解。
   分組: 季營收YoY絕對門檻(<0 / 0~20% / >20%)+同季cross-sectional五分位Q5-Q1價差;
   加強版=「三個月YoY皆>0且逐月遞增」(加速flag,呼應使用者『都很好』的直覺)。
P2 可交易性/穩健: 池=entry日20日均額>=0.3億;demean減TAIEX;季群bootstrap+逐年;
   勝率/賺賠比;Q4(年報,埋伏窗長達3個月)單獨拆出誠實列。

已知混淆(誠實聲明): 營收YoY強的股票天生是動能股,埋伏窗超額={營收動能延續}+{財報預期定價}
兩者混合,本卷用「三段窗分解」區分: 若肉集中在公告窗(anchor±)則是財報預期故事;若均勻散在
埋伏窗則只是動能延續的另一種切法。
用法: python 研究腳本/財報事件/build_rev_preposition_exam.py  (從根目錄執行,鐵律)
產出: 研究報告/research_rev_preposition.html + console
"""
import sqlite3
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

DB = "capital_flow.db"
OUT = "研究報告/research_rev_preposition.html"
LIQ_MIN = 0.3e8
BUFFER_DAYS = 5
STATUTORY = {1: (5, 15, 0), 2: (8, 14, 0), 3: (11, 14, 0), 4: (3, 31, 1)}
rng = np.random.default_rng(20260806)


def avail_date(qe):
    q = (qe.month - 1) // 3 + 1
    m, d, yoff = STATUTORY[q]
    return pd.Timestamp(qe.year + yoff, m, d) + pd.Timedelta(days=BUFFER_DAYS)


def main():
    conn = sqlite3.connect(DB, timeout=60)
    rev = pd.read_sql("SELECT code, date, revenue FROM fm_month_rev", conn, parse_dates=["date"])
    px = pd.read_sql("SELECT code,date,close,money FROM fm_daily_price "
                     "WHERE date>='2017-06-01' AND close>0 AND money>0", conn)
    tai = pd.read_sql("SELECT date,close FROM index_daily WHERE market='TAIEX' "
                      "AND date>='2017-06-01' ORDER BY date", conn)
    fin = pd.read_sql("SELECT code, date, gross_margin FROM tw_quarterly_financials_history",
                      conn, parse_dates=["date"])
    conn.close()

    C = px.pivot_table(index="date", columns="code", values="close", aggfunc="first").sort_index()
    MN = px.pivot_table(index="date", columns="code", values="money", aggfunc="first").sort_index()
    tai = tai.set_index("date")["close"]
    t_dates = np.array(C.index)
    liq20 = MN.rolling(20, min_periods=15).mean().shift(1)
    Cf = C.ffill(limit=5)
    tai_f = tai.reindex(C.index).ffill()

    # 月營收→(code, 季) 訊號
    rev_w = rev.pivot_table(index="date", columns="code", values="revenue", aggfunc="first").sort_index()
    yoy_m = rev_w / rev_w.shift(12) - 1                      # 逐月YoY
    q_of = rev_w.index.to_period("Q")

    # 毛利率QoQ(該季,前提檢查用)
    gm_chg = {}
    for code, g in fin.groupby("code"):
        g = g.sort_values("date")
        qidx = pd.PeriodIndex(g.date, freq="Q")
        g = g.set_index(qidx)
        g = g[~g.index.duplicated(keep="first")]
        full = pd.period_range(g.index.min(), g.index.max(), freq="Q")
        g = g.reindex(full)
        gm = g.gross_margin * 100
        chg = gm - gm.shift(1)
        for p, v in chg.items():
            if pd.notna(v):
                gm_chg[(code, str(p))] = float(v)

    quarters = sorted({str(p) for p in q_of.unique() if str(p) >= "2018Q1" and str(p) <= "2026Q1"})
    recs = []
    for qs in quarters:
        p = pd.Period(qs, freq="Q")
        months = [m for m in rev_w.index if m.to_period("Q") == p]
        if len(months) != 3:
            continue
        qe = p.end_time.normalize()
        # entry: 季底次月13日後首個交易日
        em = qe + pd.Timedelta(days=13)
        e_i = int(np.searchsorted(t_dates, em.strftime("%Y-%m-%d")))
        av = avail_date(qe)
        a_i = int(np.searchsorted(t_dates, av.strftime("%Y-%m-%d")))
        if e_i >= len(t_dates) or a_i + 10 >= len(t_dates) or a_i <= e_i:
            continue
        q_yoy_num = rev_w.loc[months].sum()
        q_yoy_den = rev_w.shift(12).loc[months].sum()
        m_yoy = yoy_m.loc[months]
        for code in rev_w.columns:
            den = q_yoy_den.get(code, np.nan)
            if pd.isna(den) or den <= 0:
                continue
            qyoy = q_yoy_num.get(code, np.nan) / den - 1
            if pd.isna(qyoy):
                continue
            my = m_yoy[code].values
            if np.isnan(my).any():
                continue
            accel = bool((my > 0).all() and my[2] > my[1] > my[0])
            if code not in C.columns:
                continue
            ci = C.columns.get_loc(code)
            liq = liq20.iat[e_i, ci] if e_i < len(C) else np.nan
            if pd.isna(liq) or liq < LIQ_MIN:
                continue
            pe = C.iat[e_i, ci]
            pa = Cf.iat[a_i, ci]
            pa10 = Cf.iat[a_i + 10, ci]
            if pd.isna(pe) or pd.isna(pa) or pd.isna(pa10) or pe <= 0:
                continue
            b_ea = tai_f.iloc[a_i] / tai_f.iloc[e_i] - 1
            b_ea10 = tai_f.iloc[a_i + 10] / tai_f.iloc[e_i] - 1
            b_aa10 = tai_f.iloc[a_i + 10] / tai_f.iloc[a_i] - 1
            recs.append({"code": code, "q": qs, "qtype": f"Q{p.quarter}",
                         "entry": str(t_dates[e_i])[:10], "anchor": str(t_dates[a_i])[:10],
                         "qyoy": qyoy, "accel": accel,
                         "amb": (pa / pe - 1) - b_ea,          # 埋伏窗demean
                         "thr": (pa10 / pe - 1) - b_ea10,      # 含公告+10
                         "ann": (pa10 / pa - 1) - b_aa10,      # 純公告窗
                         "gm": gm_chg.get((code, qs), np.nan)})
    E = pd.DataFrame(recs)
    print(f"[panel] {len(E):,}筆 code×季({E.q.nunique()}季, {E.q.min()}~{E.q.max()}), "
          f"gm可對上{E.gm.notna().sum():,}({E.gm.notna().mean() * 100:.0f}%), 加速flag{E.accel.sum():,}")

    # ---------- P0 前提檢查 ----------
    print("\n" + "=" * 92, "\nP0 前提: P(該季毛利率QoQ改善 | 季營收YoY分層) vs 基準率")
    sub0 = E.dropna(subset=["gm"])
    base = (sub0.gm > 0).mean() * 100
    p0_rows = []
    for lab, mask in [("YoY<0", sub0.qyoy < 0), ("YoY 0~20%", (sub0.qyoy >= 0) & (sub0.qyoy < 0.2)),
                      ("YoY>20%", sub0.qyoy >= 0.2), ("YoY>50%", sub0.qyoy >= 0.5),
                      ("加速flag", sub0.accel)]:
        s = sub0[mask]
        p = (s.gm > 0).mean() * 100
        p0_rows.append({"lab": lab, "n": len(s), "p": p})
        print(f"  {lab:<12} n={len(s):>6,} P(gm改善)={p:.1f}%  (全樣本基準{base:.1f}%)")

    # ---------- P1 三段窗分解 ----------
    def boot_q(vals, qs_arr, n_iter=1000):
        v = pd.DataFrame({"v": vals, "q": qs_arr}).dropna()
        if len(v) < 30 or v.q.nunique() < 8:
            return None
        grp = {k: g.v.values for k, g in v.groupby("q")}
        keys = list(grp)
        means = [np.mean(np.concatenate([grp[k] for k in rng.choice(keys, len(keys))]))
                 for _ in range(n_iter)]
        lo, hi = np.percentile(means, [2.5, 97.5])
        return {"mean": float(v.v.mean()), "lo": float(lo), "hi": float(hi),
                "sig": bool(lo > 0 or hi < 0)}

    def line(sub, lab, out):
        if len(sub) < 50:
            print(f"  {lab:<14} n={len(sub)} 不足")
            return
        r = {"lab": lab, "n": len(sub)}
        for col, wl in (("amb", "埋伏窗"), ("thr", "含公告+10"), ("ann", "純公告窗")):
            b = boot_q(sub[col].values, sub.q.values)
            w = sub[sub[col] > 0][col]
            l = sub[sub[col] <= 0][col]
            r[col] = {"mean": sub[col].mean() * 100, "b": b,
                      "win": len(w) / len(sub) * 100,
                      "wl": (w.mean() / abs(l.mean())) if len(w) and len(l) else np.nan}
        y = sub.groupby(sub.q.str[:4]).amb.mean()
        r["yr"] = f"{int((y > 0).sum())}/{len(y)}"
        out.append(r)
        print(f"  {lab:<14} n={r['n']:>6,} 埋伏窗{r['amb']['mean']:+.2f}%"
              + (f"[{r['amb']['b']['lo'] * 100:+.2f},{r['amb']['b']['hi'] * 100:+.2f}]"
                 f"{'✓' if r['amb']['b']['sig'] else ''}" if r["amb"]["b"] else "")
              + f" 含公告{r['thr']['mean']:+.2f}% 純公告窗{r['ann']['mean']:+.2f}%"
              + (f"[{r['ann']['b']['lo'] * 100:+.2f},{r['ann']['b']['hi'] * 100:+.2f}]"
                 f"{'✓' if r['ann']['b']['sig'] else ''}" if r["ann"]["b"] else "")
              + f" 勝率{r['amb']['win']:.0f}% 賺賠{r['amb']['wl']:.2f} 逐年{r['yr']}")

    print("\nP1 三段窗(demean%): 埋伏窗=營收全知日→財報可得日 / 含公告+10 / 純公告窗=可得日→+10日")
    P1 = []
    for lab, mask in [("YoY<0", E.qyoy < 0), ("YoY 0~20%", (E.qyoy >= 0) & (E.qyoy < 0.2)),
                      ("YoY>20%", E.qyoy >= 0.2), ("YoY>50%", E.qyoy >= 0.5),
                      ("加速flag", E.accel), ("加速×YoY>20%", E.accel & (E.qyoy >= 0.2)),
                      ("(全樣本)", E.qyoy.notna())]:
        line(E[mask], lab, P1)

    # 同季配對: YoY>20% vs YoY<0
    print("\n同季配對(強-弱, 埋伏窗):")
    pair_out = {}
    for col, wl in (("amb", "埋伏窗"), ("ann", "純公告窗")):
        day = E.groupby(["q", E.qyoy >= 0.2])[col].mean().unstack()
        day = day.dropna()
        diff = day[True] - day[False]
        n = len(diff)
        means = [np.mean(diff.values[rng.integers(0, n, n)]) for _ in range(2000)]
        lo, hi = np.percentile(means, [2.5, 97.5])
        pair_out[col] = {"n": n, "diff": diff.mean() * 100, "lo": lo * 100, "hi": hi * 100,
                        "sig": bool(lo > 0 or hi < 0), "pos": int((diff > 0).sum())}
        p = pair_out[col]
        print(f"  {wl}: 強-弱={p['diff']:+.2f}% CI[{p['lo']:+.2f},{p['hi']:+.2f}]"
              f"{'✓排0' if p['sig'] else '含0'} 正號{p['pos']}/{p['n']}季")

    # Q4拆出(含歸因對照: Q4弱營收組——若也大正,肉是「1-4月窗口」不是「營收訊號」)
    print("\nQ4(年報,埋伏窗~3個月)單獨+歸因對照:")
    P4 = []
    line(E[(E.qtype == "Q4") & (E.qyoy >= 0.2)], "Q4×YoY>20%", P4)
    line(E[(E.qtype == "Q4") & (E.qyoy < 0)], "Q4×YoY<0(歸因對照)", P4)
    line(E[(E.qtype != "Q4") & (E.qyoy >= 0.2)], "Q1-Q3×YoY>20%", P4)
    # Q4同季配對(強-弱)
    e4 = E[E.qtype == "Q4"]
    day4 = e4.groupby(["q", e4.qyoy >= 0.2]).amb.mean().unstack().dropna()
    if len(day4) >= 5:
        d4 = day4[True] - day4[False]
        n4 = len(d4)
        means4 = [np.mean(d4.values[rng.integers(0, n4, n4)]) for _ in range(2000)]
        lo4, hi4 = np.percentile(means4, [2.5, 97.5])
        q4_pair = {"n": n4, "diff": d4.mean() * 100, "lo": lo4 * 100, "hi": hi4 * 100,
                   "sig": bool(lo4 > 0 or hi4 < 0), "pos": int((d4 > 0).sum())}
        print(f"  Q4同季配對(強-弱,埋伏窗): {q4_pair['diff']:+.2f}% "
              f"CI[{q4_pair['lo']:+.2f},{q4_pair['hi']:+.2f}]{'✓排0' if q4_pair['sig'] else '含0'} "
              f"正號{q4_pair['pos']}/{q4_pair['n']}年")
    else:
        q4_pair = None

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
.v-good{background:#243b24;color:#7ec97e} .v-bad{background:#3b2420;color:#e06c5a}
.v-warn{background:#3b3420;color:#c3a55a}
"""
    p0_tbl = ("<table><tr><th>季營收分層</th><th>n</th><th>P(該季gm QoQ改善)</th></tr>"
              + "".join(f"<tr><th>{r['lab']}</th><td>{r['n']:,}</td>"
                        f"<td class='{'good' if r['p'] > base else 'bad'}'>{r['p']:.1f}%</td></tr>"
                        for r in p0_rows)
              + f"<tr><th>全樣本基準</th><td>{len(sub0):,}</td><td>{base:.1f}%</td></tr></table>")

    def cell(r, col):
        s = r[col]
        ci = (f"<br><span style='color:#777;font-size:10.5px'>[{s['b']['lo'] * 100:+.2f},{s['b']['hi'] * 100:+.2f}]"
              f"{'✓' if s['b']['sig'] else ''}</span>" if s["b"] else "")
        return f"<td>{s['mean']:+.2f}%{ci}</td>"

    p1_tbl = ("<table><tr><th>分層</th><th>n</th><th>埋伏窗</th><th>含公告+10</th><th>純公告窗</th>"
              "<th>埋伏勝率</th><th>賺賠</th><th>逐年</th></tr>"
              + "".join(f"<tr{' class=hl' if '加速×' in r['lab'] or r['lab'] == 'YoY>50%' else ''}>"
                        f"<th>{r['lab']}</th><td>{r['n']:,}</td>"
                        + cell(r, "amb") + cell(r, "thr") + cell(r, "ann")
                        + f"<td>{r['amb']['win']:.0f}%</td><td>{r['amb']['wl']:.2f}</td><td>{r['yr']}</td></tr>"
                        for r in P1) + "</table>")
    p4_tbl = ("<table><tr><th>分層</th><th>n</th><th>埋伏窗</th><th>含公告+10</th><th>純公告窗</th></tr>"
              + "".join(f"<tr><th>{r['lab']}</th><td>{r['n']:,}</td>" + cell(r, "amb") + cell(r, "thr")
                        + cell(r, "ann") + "</tr>" for r in P4) + "</table>")
    pr = pair_out
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>月營收→季報埋伏考卷(2026-08-06)</title><style>{CSS}</style></head><body>
<h1>🪤 月營收品質 → 季報公布前埋伏考卷</h1>
<div class="note">使用者假說:「當月營收都很好時,季財報就可能優於預期,可以公布前先埋伏買」。
台股結構: 季底次月10日三個月營收全知 vs 財報法定期限(Q1=5/15/Q2=8/14/Q3=11/14/Q4=3/31)——
埋伏窗~1個月(Q4~3個月)。entry=季底次月13日後首個交易日收盤(可執行),池=20日均額>=0.3億,
demean減TAIEX,季群bootstrap。既有判決: 公告前短窗全樣本不顯著(preannounce_reaction卷),
本卷=月營收品質條件版。panel {len(E):,}筆({E.q.min()}~{E.q.max()})。</div>
<h2>P0 前提檢查: 營收好→財報內容真的好嗎?</h2>
{p0_tbl}
<h2>P1 三段窗分解(埋伏窗 / 含公告+10 / 純公告窗)</h2>
{p1_tbl}
<div class="note">同季配對(YoY>20% − YoY<0): 埋伏窗{pr['amb']['diff']:+.2f}%
CI[{pr['amb']['lo']:+.2f},{pr['amb']['hi']:+.2f}]{'✓排0' if pr['amb']['sig'] else '含0'}
(正號{pr['amb']['pos']}/{pr['amb']['n']}季) · 純公告窗{pr['ann']['diff']:+.2f}%
CI[{pr['ann']['lo']:+.2f},{pr['ann']['hi']:+.2f}]{'✓排0' if pr['ann']['sig'] else '含0'}
(正號{pr['ann']['pos']}/{pr['ann']['n']}季)</div>
<h2>Q4(年報)單獨 vs Q1-Q3</h2>
{p4_tbl}
<h2>⚖️ 判決(2026-08-06首輪)</h2>
<ul>
<li><span class="verdict v-warn">①前提鏈比直覺弱很多</span> P(毛利率QoQ改善|季營收YoY>20%)=54.5%
vs 基準51.6%——「營收好→財報很可能優於預期」實際只是+3pp的微傾斜,不是高機率事件;
最好的前提訊號是<b>加速flag(三個月YoY皆正且逐月遞增)=58.7%</b>(+7pp),方向如使用者直覺但幅度有限。</li>
<li><span class="verdict v-bad">②一般季度(Q1-Q3)埋伏=null</span> YoY>20%組埋伏窗-0.37%含0——
月營收在逐月公布當下已被市場消化三次,一個月的埋伏窗沒剩肉。公告窗本身普遍+1~1.6%✓
(財報季效應)但<b>與營收品質無關</b>(強-弱配對+0.17%含0)=公告窗的肉用營收挑不出來。</li>
<li><span class="verdict v-good">③活口=年報版(Q4)</span> 年營收YoY>20%: 1月中(12月營收全知)進場
→4月初年報可得日=<b>埋伏窗+7.04%✓[+2.16,+11.59]/勝率53%/賺賠比1.98/逐年6/8</b>;
歸因過關: Q4弱營收對照僅+0.42%含0、同季配對強-弱+4.86%✓排0(正號6/8年)=肉是營收訊號的功勞,
不是1-4月窗口(年初行情)本身。機制候選=全年成績單敘事+股利宣告預期+Q1法說季的持續re-rate。
僅8個年度樣本=<b>候選層</b>,每年1月中可操作一次。</li>
<li><b>④實務翻譯</b>: 「埋伏季報」改成「埋伏年報」——每年1月10日12月營收公布後,
篩「年營收YoY>20%」(加速版更佳)+流動池,1月中進場持有到4月初;Q1-Q3不做埋伏
(該做的是公布後的三重門檻/毛利率資格門檻,見newhigh_gm卷)。</li>
</ul>
<h2>已知限制</h2>
<div class="note">①營收YoY強=動能股,埋伏窗超額混合{{營收動能延續+財報預期定價}},靠三段窗分解區分
(肉在公告窗=財報故事,散在埋伏窗=動能延續);②anchor=法定期限+5的可得日,實際公布常提早
(top40可用tw_board actual精確化,未做=v2方向);③fm_month_rev自2017起,YoY需2018起;
④除權息未還原(Q2/Q3埋伏窗跨除息季,強營收股常高配息=顯著保守偏誤,真實更好);
⑤「優於預期」無台股全面分析師預估資料,以毛利率QoQ改善(P0)+公告窗反應(P1 ann欄)雙代理。</div>
<div class="note">維運: python 研究腳本/財報事件/build_rev_preposition_exam.py(從根目錄執行)。
姊妹卷: build_earnings_preannounce_reaction(公告前熱度)、build_fundamental_factors_exam(八因子)、
build_fundamental_momo_interaction(gm×動能)。</div>
</body></html>"""
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n[report] 已輸出 {OUT}")


if __name__ == "__main__":
    main()
