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
    # v2追加操作化(2026-08-06使用者指定): 創新高/優於預期代理
    hi_m = rev_w >= rev_w.rolling(12, min_periods=12).max()          # 月營收=近12月最高(含當月)
    q_rev = rev_w.groupby(q_of).sum(min_count=3)                      # 季合計(3個月齊才算)
    q_yoy_df = q_rev / q_rev.shift(4) - 1
    q_hi4_df = q_rev >= q_rev.shift(1).rolling(4, min_periods=4).max()   # 季營收創4季新高
    beat_df = q_yoy_df > q_yoy_df.shift(1).rolling(4, min_periods=4).mean()  # YoY超越自身前4季均值(beat代理)

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
            hi3 = hi_m.loc[months, code].values if code in hi_m.columns else np.array([False] * 3)
            hi_last = bool(hi3[-1])                     # 季末月創12月新高
            hi_all3 = bool(hi3.all())                   # 三個月全創(使用者「都很好」嚴格版)
            qp = pd.Period(qs, freq="Q")
            q_hi4 = bool(q_hi4_df.at[qp, code]) if (qp in q_hi4_df.index and code in q_hi4_df.columns
                                                    and pd.notna(q_hi4_df.at[qp, code])) else False
            beat = bool(beat_df.at[qp, code]) if (qp in beat_df.index and code in beat_df.columns
                                                  and pd.notna(beat_df.at[qp, code])) else False
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
            # v3時點變體(2026-08-06使用者提案「月底埋伏買進到公布季報後幾天出場」):
            # entry2=季底+30日曆(月底埋伏) / entry3=季底+43日曆(次月營收公布後=次月13日,含「次月也創高」確認)
            e2_i = int(np.searchsorted(t_dates, (qe + pd.Timedelta(days=30)).strftime("%Y-%m-%d")))
            e3_i = int(np.searchsorted(t_dates, (qe + pd.Timedelta(days=43)).strftime("%Y-%m-%d")))
            m4 = months[-1] + pd.DateOffset(months=1)          # 季後首月(次月)
            hi_next = bool(hi_m.at[m4, code]) if (m4 in hi_m.index and code in hi_m.columns
                                                  and pd.notna(hi_m.at[m4, code])) else False
            amb2 = thr3_5 = thr3_10 = thr3abs = np.nan
            if e2_i < a_i and a_i + 5 < len(t_dates):
                p2 = C.iat[e2_i, ci]
                x5 = Cf.iat[a_i + 5, ci]
                if pd.notna(p2) and pd.notna(x5) and p2 > 0:
                    amb2 = (x5 / p2 - 1) - (tai_f.iloc[a_i + 5] / tai_f.iloc[e2_i] - 1)
            if e3_i < a_i and a_i + 10 < len(t_dates):
                p3 = C.iat[e3_i, ci]
                x5 = Cf.iat[a_i + 5, ci]
                x10 = Cf.iat[a_i + 10, ci]
                if pd.notna(p3) and pd.notna(x5) and p3 > 0:
                    thr3_5 = (x5 / p3 - 1) - (tai_f.iloc[a_i + 5] / tai_f.iloc[e3_i] - 1)
                    thr3abs = x5 / p3 - 1                     # 絕對報酬(權益曲線用)
                if pd.notna(p3) and pd.notna(x10) and p3 > 0:
                    thr3_10 = (x10 / p3 - 1) - (tai_f.iloc[a_i + 10] / tai_f.iloc[e3_i] - 1)
            recs.append({"code": code, "q": qs, "qtype": f"Q{p.quarter}",
                         "hi_next": hi_next, "amb2": amb2, "thr3_5": thr3_5, "thr3_10": thr3_10,
                         "thr3abs": thr3abs,
                         "entry": str(t_dates[e_i])[:10], "anchor": str(t_dates[a_i])[:10],
                         "qyoy": qyoy, "accel": accel,
                         "hi_last": hi_last, "hi_all3": hi_all3, "q_hi4": q_hi4, "beat": beat,
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
                      ("加速flag", sub0.accel),
                      ("季末月創12月高", sub0.hi_last), ("三個月全創高", sub0.hi_all3),
                      ("季營收創4季高", sub0.q_hi4), ("beat自身趨勢", sub0.beat),
                      ("創4季高×YoY>20%", sub0.q_hi4 & (sub0.qyoy >= 0.2)),
                      ("beat×YoY>20%", sub0.beat & (sub0.qyoy >= 0.2))]:
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
                      ("季末月創12月高", E.hi_last), ("三個月全創高", E.hi_all3),
                      ("季營收創4季高", E.q_hi4), ("beat自身趨勢", E.beat),
                      ("創4季高×YoY>20%", E.q_hi4 & (E.qyoy >= 0.2)),
                      ("beat×YoY>20%", E.beat & (E.qyoy >= 0.2)),
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

    # ---------- P3 v3時點變體(使用者提案: 月底埋伏/次月確認→公布後幾天出場) ----------
    print("\nP3 時點變體(demean%): entry2=季底+30日(月底埋伏)→公布後5日 / "
          "entry3=次月13日(次月營收已公布)→公布後5/10日")
    P3 = []

    def line3(sub, lab):
        if len(sub) < 50:
            print(f"  {lab:<28} n={len(sub)} 不足")
            return
        r = {"lab": lab, "n": len(sub)}
        for col in ("amb2", "thr3_5", "thr3_10"):
            b = boot_q(sub[col].values, sub.q.values)
            v = sub[col].dropna()
            w, l = v[v > 0], v[v <= 0]
            r[col] = {"mean": v.mean() * 100, "b": b,
                      "win": len(w) / len(v) * 100 if len(v) else np.nan,
                      "wl": (w.mean() / abs(l.mean())) if len(w) and len(l) else np.nan}
        P3.append(r)
        f = lambda c: (f"{r[c]['mean']:+.2f}%"
                       + (f"[{r[c]['b']['lo'] * 100:+.2f},{r[c]['b']['hi'] * 100:+.2f}]"
                          f"{'✓' if r[c]['b']['sig'] else ''}" if r[c]["b"] else ""))
        print(f"  {lab:<28} n={r['n']:>6,} 月底→公告+5:{f('amb2')} "
              f"次月13→公告+5:{f('thr3_5')}(勝率{r['thr3_5']['win']:.0f}%/賺賠{r['thr3_5']['wl']:.2f}) "
              f"次月13→公告+10:{f('thr3_10')}")

    line3(E[E.hi_all3], "三月全創高")
    line3(E[E.hi_all3 & E.hi_next], "三月全創高×次月也創高(使用者情境)")
    line3(E[E.hi_last & E.hi_next], "季末月創高×次月也創高")
    line3(E[E.hi_all3 & E.hi_next & (E.qtype != "Q4")], "Q1-Q3×三月全創×次月創")
    line3(E[E.qyoy.notna()], "(全樣本)")

    # ---------- 權益曲線: v3配方逐季複利(次月13進→公告+5出,窗外空手) vs TAIEX買進持有 ----------
    sub_curve = E[E.hi_last & E.hi_next].dropna(subset=["thr3abs"])
    q_pts = []
    for qq, g in sub_curve.groupby("q"):
        if len(g) >= 5:
            q_pts.append((qq, g.thr3abs.mean(), g.anchor.max()))
    q_pts.sort()
    nav = 1.0
    curve_dates, curve_vals = [], []
    for qq, r, ad in q_pts:
        nav *= (1 + r)
        curve_dates.append(ad)
        curve_vals.append(round(nav, 4))
    tai_vals = []
    if curve_dates:
        t0v = tai_f.loc[curve_dates[0]] if curve_dates[0] in tai_f.index else np.nan
        tai_vals = [round(float(tai_f.loc[d] / t0v), 4) if d in tai_f.index else None
                    for d in curve_dates]
    yrs_c = max((pd.Timestamp(curve_dates[-1]) - pd.Timestamp(curve_dates[0])).days / 365.25, 0.5) if curve_dates else 1
    curve_ann = (nav ** (1 / yrs_c) - 1) * 100 if curve_dates else np.nan
    mdd_c = (pd.Series(curve_vals) / pd.Series(curve_vals).cummax() - 1).min() * 100 if curve_vals else np.nan
    print(f"\n[nav] v3配方(季末月×次月連創,次月13→公告+5)逐季複利: NAV={nav:.2f} "
          f"年化{curve_ann:+.1f}% 季頻MDD{mdd_c:.1f}%(窗外空手,毛報酬)")
    import json as _json
    nav_json = _json.dumps([
        {"name": "v3配方(窗外空手,毛報酬)", "dates": curve_dates, "vals": curve_vals},
        {"name": "TAIEX買進持有", "dates": curve_dates, "vals": tai_vals}], ensure_ascii=False)

    # Q4拆出(含歸因對照: Q4弱營收組——若也大正,肉是「1-4月窗口」不是「營收訊號」)
    print("\nQ4(年報,埋伏窗~3個月)單獨+歸因對照:")
    P4 = []
    line(E[(E.qtype == "Q4") & (E.qyoy >= 0.2)], "Q4×YoY>20%", P4)
    line(E[(E.qtype == "Q4") & (E.qyoy < 0)], "Q4×YoY<0(歸因對照)", P4)
    line(E[(E.qtype == "Q4") & E.q_hi4], "Q4×季營收創4季高", P4)
    line(E[(E.qtype == "Q4") & E.q_hi4 & (E.qyoy >= 0.2)], "Q4×創4季高×YoY>20%", P4)
    line(E[(E.qtype == "Q4") & E.beat & (E.qyoy >= 0.2)], "Q4×beat×YoY>20%", P4)
    line(E[(E.qtype != "Q4") & (E.qyoy >= 0.2)], "Q1-Q3×YoY>20%", P4)
    line(E[(E.qtype != "Q4") & E.q_hi4 & (E.qyoy >= 0.2)], "Q1-Q3×創4季高×YoY>20%", P4)
    line(E[(E.qtype != "Q4") & E.hi_all3 & (E.qyoy >= 0.2)], "Q1-Q3×三月全創高×YoY>20%", P4)
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
<title>月營收→季報埋伏考卷(2026-08-06)</title>
<script src="plotly.min.js"></script><style>{CSS}</style></head><body>
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
<h2>權益曲線: v3最終配方逐季複利(窗外空手,毛報酬)</h2>
<div class="note">配方=季末月創12月高×次月也創高,次月13日收盤進→財報可得日+5收盤出;
NAV={nav:.2f} 年化{curve_ann:+.1f}%(曝險僅每季2-3週) vs TAIEX買進持有。</div>
<div id="c_nav" style="height:420px"></div>
<script>
const NAVS={nav_json};
Plotly.newPlot('c_nav', NAVS.map(s=>({{x:s.dates,y:s.vals,name:s.name,mode:'lines+markers'}})),
  {{title:'埋伏配方權益曲線(季頻)', paper_bgcolor:'#1a1a19',plot_bgcolor:'#22221f',
    font:{{color:'#ddd',size:12}},yaxis:{{title:'NAV'}},legend:{{orientation:'h'}},
    margin:{{t:42,l:52,r:18,b:40}}}});
</script>
<h2>⚖️ 判決(2026-08-06首輪+v2改操作化翻盤)</h2>
<ul>
<li><span class="verdict v-good">①v2定調: 「營收創新高」遠強於「YoY水準」——使用者指定的操作化翻盤了首輪</span>
前提鏈: P(毛利率QoQ改善|<b>三個月全創12月高</b>)=<b>68.5%</b>(+17pp!)、季末月創高63.1%(+11.5pp),
vs YoY>20%只有54.5%(+3pp)、beat自身趨勢代理55.0%(無效)。「都很好」的正確操作化=創新高,
不是YoY水準——feedback第16條(null可能只是操作化不對)的又一實例。</li>
<li><span class="verdict v-good">②埋伏窗翻盤: 創新高版全部排0(首輪YoY版含0)</span>
季末月創12月高: 埋伏窗<b>+3.92%✓[+1.48,+6.34]/勝率48%/賺賠1.96/逐年7/9</b>;
三個月全創高: +4.23%✓;季營收創4季高×YoY>20%: +2.97%✓逐年7/9——事件量~70/季(全創版~17/季),可操作。</li>
<li><span class="verdict v-good">③王者組合=Q4×季營收創4季高×YoY>20%</span>
<b>埋伏窗+9.20%✓[+3.54,+13.98]/勝率55%/賺賠比2.19/逐年6/8</b>(n=883,~110檔/年)——
1月中(12月營收全知)進場→4月初年報可得日;歸因已過關(Q4弱營收對照+0.42含0/同季配對+4.86✓)。</li>
<li><span class="verdict v-warn">④Q1-Q3單獨仍含0(方向已轉正)</span> 創4季高×YoY>20%=+0.87含0/
三月全創高×YoY>20%=+2.31含0(n=356薄)——pooled顯著主要由Q4驅動;Q1-Q3的純公告窗
三月全創版+2.24✓是各分層最高,但埋伏層以Q4為主、Q1-Q3當觀察。</li>
<li><b>⑤機制收斂</b>: 營收創新高=基本面版的「新高突破」——與價格新高突破卷(90日/52週,題材成員)
同構,兩個「新高家族」訊號交乘(價格突破×營收創高)是自然下一張考卷;beat代理(YoY超越自身趨勢)
無效=市場錨定的是「絕對水位創高」的顯著性,不是統計意義的預期差。</li>
<li><span class="verdict v-good">⑥v3時點變體(使用者提案「月底埋伏→公布後幾天出場」)=效率更高的最終配方</span>
<b>季末月創12月高×次月營收也創高</b>: 次月13日進場(次月營收已公布=「預計也創高」不用預計,等公布確認)
→公告+5日出=<b>+4.25%✓[+1.50,+7.37]/勝率53%/賺賠比2.14</b>,→公告+10日出=+5.68%✓;月底(季底+30日)
進場版+4.77%✓——窗長只有2-4週,單位時間效率約為原版埋伏窗(25日+3.92%)的兩倍。
使用者原始情境(三月全創×次月創)+2.41%✓/+3.77%✓也成立但略遜(條件更嚴只刪樣本沒加肉);
<b>Q1-Q3也被救活</b>(三月全創×次月創→公告+10=+1.91%✓,首輪Q1-Q3 null的解=更晚進場+次月確認+抱過公告);
全樣本基準(次月13→公告+10)+2.35%✓=財報季本身有drift,訊號增量約+3.3pp。
⚠執行注意: anchor=法定可得日,部分公司提早公布——實際操作配合dashboard「台股財報公布日」提醒,
進場時已公布財報的個股跳過(埋伏已失效)。</li>
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
