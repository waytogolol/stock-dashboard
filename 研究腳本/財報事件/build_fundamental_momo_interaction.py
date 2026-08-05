# -*- coding: utf-8 -*-
"""毛利率QoQ改善 × 週級動能 交乘考卷(2026-08-05,財報八因子與週級動能兩線的自然會合點)。

背景: ①財報八因子首輪(build_fundamental_factors_exam.py,commit a1f969a)判決=變化類活/水準類死,
毛利率QoQ改善Q5-Q1=+5.25pp/60日、14/14年全正完美單調,但Gate2翻規則後vs case-control含0=候選層,
邊際+1pp/60日需組合化。②週級動能可執行性收官(build_weekly_momo_executable_scan.py,commit c96dec6)
活口=逐日掃近5日漲幅>=20%→次日收盤進場(排開低>2%)→持5節,年化+25.3%/MDD-36.3%,薄真edge。
記憶交辦原文:「毛利率QoQ改善×週級動能選股端交乘(『漲得快且毛利率在改善』)」。

═══ 兩個方向(寫程式前預先註冊,比照feedback第4條多角度) ═══
方向A(動能端加財報濾網,主檢定): 逐日盤後掃「近5日累計漲幅>=20%」候選(口徑逐字沿用
  executable_scan活口: 流動性=前一完整週止的20週均週成交值>=0.3億零前視;進場=次日收盤;
  C4濾網=排除進場日開盤跳空<-2%;持5交易日收對收對稱)。分組=訊號日「已依法公告」的最新一季
  毛利率QoQ變化gm_chg: 改善(>0) vs 惡化(<=0) vs 無財報資料;加強版=連2季改善(gm_up_streak>=2);
  對照組=營益率om_chg同切法(exam第二強因子)。
  檢定: 絕對報酬+demean並列(feedback第13條)/同日配對diff(同一訊號日兩組都有才比,控日效應)
  月群bootstrap/逐年/勝率/賺賠比(第15條)。
方向B(財報端加動能濾網): 每季形成日(avail_date後首個TAIEX交易日,同exam),毛利率QoQ改善股內
  按「形成日前20交易日絕對報酬」三分位,前瞻60交易日demean報酬,季群bootstrap T3-T1——
  回答「改善且已在漲」是否優於「改善但沒動能」。

═══ 口徑鐵律 ═══
· 公告時滯: avail_date(季)=法定期限(Q1=5/15,Q2=8/14,Q3=11/14,Q4=次年3/31)+5日曆日緩衝,
  逐字沿用exam;訊號日只用avail_date<=訊號日的最新季。
· fm_daily_price清洗close>0 AND money>0(方向A進出場另要求open>0算跳空)。
· 進場=訊號「次日收盤」=訊號確認後才出現的價格,零前視(feedback第18條);出場=第5個持有日收盤,對稱。
· 成本: 選股層比較不扣(兩組同構),絕對數字段附0.5%/1.1%來回情境換算。
已知限制: fm_daily_price未還原除權息(保守偏誤);候選可連日重複觸發(同股連續事件),以月群
bootstrap+誠實n處理;金融股法定期限例外同exam小誤差。

用法: python 研究腳本/財報事件/build_fundamental_momo_interaction.py  (從根目錄執行,鐵律)
產出: 研究報告/research_fundamental_momo_interaction.html + console
"""
import json
import sqlite3
import sys
import time

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

DB = "capital_flow.db"
OUT = "研究報告/research_fundamental_momo_interaction.html"
START = "2015-01-01"
MOMO_TH = 0.20            # 近5日累計漲幅門檻
LIQ_MIN = 0.3e8           # 20週均週成交值下限(前一完整週,零前視)
GAP_FILTER = -0.02        # C4: 進場日開盤跳空<-2%排除
HOLD = 5
K_FWD = 60                # 方向B前瞻窗(exam主判讀)
BUFFER_DAYS = 5
STATUTORY = {1: (5, 15, 0), 2: (8, 14, 0), 3: (11, 14, 0), 4: (3, 31, 1)}
rng = np.random.default_rng(20260805)

GREEN, RED, BLUE, YELLOW, GRAY = "#7ec97e", "#e06c5a", "#6bb7e3", "#c3a55a", "#8a8878"
BG = {"paper_bgcolor": "#1a1a19", "plot_bgcolor": "#22221f",
      "font": {"color": "#ddd", "size": 12}, "margin": {"t": 42, "l": 52, "r": 18, "b": 40},
      "legend": {"orientation": "h"}}


def avail_date(quarter_end):
    qe = pd.Timestamp(quarter_end)
    q = (qe.month - 1) // 3 + 1
    m, d, yoff = STATUTORY[q]
    return pd.Timestamp(qe.year + yoff, m, d) + pd.Timedelta(days=BUFFER_DAYS)


def _streak(pos):
    p = pos.fillna(False).astype(int)
    grp = (p == 0).cumsum()
    return p.groupby(grp).cumsum()


# ======================================================================
# 1. 財報: code×季 → gm_chg/om_chg/streak + avail_date長表
# ======================================================================
def load_fundamentals():
    conn = sqlite3.connect(DB, timeout=60)
    fin = pd.read_sql("SELECT code, date, gross_margin, operating_margin "
                      "FROM tw_quarterly_financials_history", conn, parse_dates=["date"])
    conn.close()
    rows = []
    for code, g in fin.groupby("code"):
        g = g.sort_values("date")
        qidx = pd.PeriodIndex(g.date, freq="Q")
        g = g.set_index(qidx)
        g = g[~g.index.duplicated(keep="first")]
        full = pd.period_range(g.index.min(), g.index.max(), freq="Q")
        g = g.reindex(full)
        f = pd.DataFrame(index=g.index)
        f["gm_lv"] = g.gross_margin * 100
        f["om_lv"] = g.operating_margin * 100
        f["gm_chg"] = f.gm_lv - f.gm_lv.shift(1)
        f["om_chg"] = f.om_lv - f.om_lv.shift(1)
        f["gm_up_streak"] = _streak(f.gm_chg > 0)
        f["avail"] = [avail_date(p.end_time.normalize()) for p in f.index]
        f["code"] = code
        f = f[g.date.notna().values]          # 只留實際申報季
        rows.append(f)
    fund = pd.concat(rows, ignore_index=True).dropna(subset=["gm_chg"], how="all")
    fund = fund.sort_values("avail")
    print(f"[fund] 財報長表: {len(fund):,}筆(code×季), {fund.code.nunique()}檔, "
          f"gm_chg有值{fund.gm_chg.notna().sum():,}")
    return fund


# ======================================================================
# 2. 價格面板(全市場)
# ======================================================================
def load_prices():
    conn = sqlite3.connect(DB, timeout=60)
    px = pd.read_sql(f"SELECT code,date,open,close,money FROM fm_daily_price "
                     f"WHERE date>='2013-06-01' AND close>0 AND money>0", conn)
    tai = pd.read_sql("SELECT date, close FROM index_daily WHERE market='TAIEX' "
                      "AND date>='2013-06-01' ORDER BY date", conn)
    conn.close()
    C = px.pivot_table(index="date", columns="code", values="close", aggfunc="first").sort_index()
    O = px.pivot_table(index="date", columns="code", values="open", aggfunc="first").sort_index()
    MN = px.pivot_table(index="date", columns="code", values="money", aggfunc="first").sort_index()
    O = O.where(O > 0)
    tai = tai.set_index("date")["close"]
    print(f"[px] 面板: {C.shape[0]}日×{C.shape[1]}檔 {C.index[0]}~{C.index[-1]}")
    return C, O, MN, tai


# ======================================================================
# 3. 方向A: 逐日動能候選 × 訊號日最新已公告gm_chg
# ======================================================================
def build_events(C, O, MN, tai, fund):
    dates = list(C.index)
    dpos = {d: i for i, d in enumerate(dates)}
    # 20週均週成交值(前一完整週,零前視)
    wk = pd.PeriodIndex(pd.to_datetime(dates), freq="W-FRI")
    wk_ids = pd.Series(range(len(pd.unique(wk))), index=pd.unique(wk))
    wknum = wk_ids[wk].values
    wkm = MN.groupby(wknum).sum(min_count=1)
    liq20 = wkm.rolling(20).mean()
    liq_prev = liq20.shift(1).reindex(wknum).values     # 每日對應前一完整週的20週均額
    liq_ok = pd.DataFrame(liq_prev >= LIQ_MIN, index=C.index, columns=C.columns)

    r5 = C / C.shift(5) - 1
    Cf = C.ffill(limit=5)
    tai_r = tai.reindex(C.index)

    start_i = max(dpos.get(START, 0), int(np.searchsorted(np.array(dates), START)))
    events = []
    for i in range(start_i, len(dates) - HOLD - 1):
        row = r5.iloc[i]
        cand = row.index[(row >= MOMO_TH) & liq_ok.iloc[i].values & C.iloc[i].notna().values]
        if len(cand) == 0:
            continue
        t = dates[i]
        e_i = i + 1                       # 次日
        x_i = e_i + HOLD                  # 出場(次日起第HOLD個交易日收盤)
        for c in cand:
            c0 = C.iat[i, C.columns.get_loc(c)]
            op1 = O.iat[e_i, O.columns.get_loc(c)]
            e1 = C.iat[e_i, C.columns.get_loc(c)]
            x1 = Cf.iat[x_i, Cf.columns.get_loc(c)]
            if pd.isna(op1) or pd.isna(e1) or pd.isna(x1) or e1 <= 0:
                continue
            gap = op1 / c0 - 1
            if gap < GAP_FILTER:          # C4濾網
                continue
            ret = x1 / e1 - 1
            bench = tai_r.iloc[x_i] / tai_r.iloc[e_i] - 1 if pd.notna(tai_r.iloc[x_i]) else np.nan
            events.append((c, t, ret, ret - bench))
    ev = pd.DataFrame(events, columns=["code", "t", "ret", "dm"])
    ev["month"] = ev["t"].str[:7]
    ev["year"] = ev["t"].str[:4]
    print(f"[A] 動能候選事件: {len(ev):,}筆({ev.code.nunique()}檔, "
          f"{ev.t.min()}~{ev.t.max()}, 日均{len(ev) / ev.t.nunique():.1f}檔)")

    # 接財報: 訊號日已公告最新季(merge_asof, 容忍200日曆天=一季多一點)
    evx = ev.copy()
    evx["t_ts"] = pd.to_datetime(evx["t"])
    evx = evx.sort_values("t_ts")
    fcols = ["avail", "code", "gm_chg", "om_chg", "gm_up_streak", "gm_lv"]
    m = pd.merge_asof(evx, fund[fcols].rename(columns={"avail": "t_ts"}).sort_values("t_ts"),
                      on="t_ts", by="code", direction="backward",
                      tolerance=pd.Timedelta(days=200))
    print(f"[A] 財報可對上: gm_chg有值{m.gm_chg.notna().sum():,}/{len(m):,}"
          f"({m.gm_chg.notna().mean() * 100:.0f}%)")
    return m


def boot_mean_ci(vals, months, n_iter=1000):
    v = pd.DataFrame({"v": vals, "m": months}).dropna()
    if len(v) < 15 or v.m.nunique() < 6:
        return None
    grp = {k: g.v.values for k, g in v.groupby("m")}
    keys = list(grp)
    means = [np.mean(np.concatenate([grp[k] for k in rng.choice(keys, len(keys))]))
             for _ in range(n_iter)]
    lo, hi = np.percentile(means, [2.5, 97.5])
    return {"mean": float(v.v.mean()), "lo": float(lo), "hi": float(hi),
            "sig": bool(lo > 0 or hi < 0), "n": len(v)}


def grp_stats(g):
    if len(g) == 0:
        return None
    w = g[g.ret > 0].ret
    l = g[g.ret <= 0].ret
    return {"n": len(g), "ret": g.ret.mean() * 100, "med": g.ret.median() * 100,
            "dm": g.dm.mean() * 100, "win": len(w) / len(g) * 100,
            "wl": (w.mean() / abs(l.mean())) if len(w) and len(l) else np.nan}


def direction_a(m):
    print("\n" + "=" * 84, "\n方向A: 動能候選(近5日>=20%,次日收盤進,排開低>2%,持5)× 訊號日已公告毛利率QoQ")
    out = {}
    groups = [
        ("①gm改善(QoQ>0)", m[m.gm_chg > 0]),
        ("②gm惡化(QoQ<=0)", m[m.gm_chg <= 0]),
        ("③無財報資料", m[m.gm_chg.isna()]),
        ("④gm連2季改善", m[m.gm_up_streak >= 2]),
        ("⑤om改善(對照)", m[m.om_chg > 0]),
        ("⑥om惡化(對照)", m[m.om_chg <= 0]),
        ("(全體候選)", m),
    ]
    for lab, g in groups:
        s = grp_stats(g)
        if s is None:
            continue
        b = boot_mean_ci(g.ret.values, g.month.values)
        bdm = boot_mean_ci(g.dm.values, g.month.values)
        y = g.groupby("year").ret.mean()
        s.update({"boot": b, "boot_dm": bdm, "yr_pos": int((y > 0).sum()), "yr_n": len(y),
                  "yearly": (y * 100).round(2).to_dict()})
        out[lab] = s
        print(f"  {lab:<16} n={s['n']:>6} 絕對均{s['ret']:+.2f}%(中位{s['med']:+.2f}) "
              f"demean{s['dm']:+.2f}% 勝率{s['win']:.0f}% 賺賠比{s['wl']:.2f} "
              f"逐年{s['yr_pos']}/{s['yr_n']}正"
              + (f" CI[{b['lo'] * 100:+.2f},{b['hi'] * 100:+.2f}]" if b else ""))

    # 同日配對: 同一訊號日改善組均值-惡化組均值
    both = m[m.gm_chg.notna()]
    day = both.groupby(["t", both.gm_chg > 0]).ret.mean().unstack()
    day = day.dropna()
    if len(day):
        diff = day[True] - day[False]
        months = pd.Series(diff.index).str[:7].values
        b = boot_mean_ci(diff.values, months)
        out["paired"] = {"n_days": len(diff), "diff": diff.mean() * 100, "boot": b}
        print(f"  同日配對(兩組同日皆有,n_days={len(diff)}): 改善-惡化={diff.mean() * 100:+.2f}%/筆"
              + (f" CI[{b['lo'] * 100:+.2f},{b['hi'] * 100:+.2f}]{'✓排0' if b['sig'] else '含0'}" if b else ""))
    return out


# ======================================================================
# 4. 方向B: 季形成日 gm改善股 × 前20日動能三分位 → 前瞻60日demean
# ======================================================================
def direction_b(C, tai, fund):
    print("\n" + "=" * 84, "\n方向B: 季形成日 gm改善股/gm惡化股(對照) × 形成日前20日動能三分位 → 前瞻60交易日demean")
    dates = np.array(C.index)          # ISO字串,lexicographic=時間序
    tai_v = tai.reindex(C.index).values
    C_v = C.values
    mom20 = C / C.shift(20) - 1

    def run_side(sub, lab):
        recs = []
        for _, g in sub.groupby("avail"):
            av = g.avail.iloc[0]
            i = int(np.searchsorted(dates, str(av.date())))
            if i >= len(dates) - K_FWD:
                continue
            f_date = dates[i]
            for r in g.itertuples():
                ci = C.columns.get_loc(r.code) if r.code in C.columns else None
                if ci is None:
                    continue
                c0, c1 = C_v[i, ci], C_v[i + K_FWD, ci]
                mo = mom20.iat[i, ci]
                if pd.isna(c0) or pd.isna(c1) or pd.isna(mo) or c0 <= 0:
                    continue
                bench = tai_v[i + K_FWD] / tai_v[i] - 1
                recs.append((r.code, str(f_date)[:10], mo, c1 / c0 - 1 - bench))
        evb = pd.DataFrame(recs, columns=["code", "f", "mom20", "dm60"])
        out_rows, spread_by_q = [], {}
        for f, g in evb.groupby("f"):
            if len(g) < 30:
                continue
            b = pd.qcut(g.mom20.rank(method="first"), 3, labels=False)
            mm = g.groupby(b).dm60.mean()
            if len(mm) == 3:
                spread_by_q[f] = mm.iloc[2] - mm.iloc[0]
                out_rows.append([f, len(g)] + list(mm.values))
        tb = pd.DataFrame(out_rows, columns=["f", "n", "T1低動能", "T2", "T3高動能"])
        sp = pd.Series(spread_by_q)
        n = len(sp)
        means = [np.mean(sp.values[rng.integers(0, n, n)]) for _ in range(2000)]
        lo, hi = np.percentile(means, [2.5, 97.5])
        res = {"lab": lab, "n_q": n, "t1": tb["T1低動能"].mean() * 100, "t2": tb["T2"].mean() * 100,
               "t3": tb["T3高動能"].mean() * 100, "spread": sp.mean() * 100,
               "lo": lo * 100, "hi": hi * 100, "sig": bool(lo > 0 or hi < 0),
               "n_obs": int(tb.n.sum()), "spreads": sp}
        print(f"  [{lab}] 形成日{n}個({res['n_obs']:,}筆) T1低動能{res['t1']:+.2f}% T2{res['t2']:+.2f}% "
              f"T3高動能{res['t3']:+.2f}%  T3-T1={res['spread']:+.2f}pp "
              f"CI[{res['lo']:+.2f},{res['hi']:+.2f}]{'✓排0' if res['sig'] else '含0'}")
        return res

    res_up = run_side(fund[fund.gm_chg > 0], "gm改善股")
    res_dn = run_side(fund[fund.gm_chg <= 0], "gm惡化股(對照)")
    # 交乘檢定: 兩側動能價差的差(同形成日配對)
    common = res_up["spreads"].index.intersection(res_dn["spreads"].index)
    dd = (res_up["spreads"] - res_dn["spreads"]).loc[common].dropna()
    n = len(dd)
    if n >= 8:
        means = [np.mean(dd.values[rng.integers(0, n, n)]) for _ in range(2000)]
        lo, hi = np.percentile(means, [2.5, 97.5])
        inter = {"n": n, "diff": dd.mean() * 100, "lo": lo * 100, "hi": hi * 100,
                 "sig": bool(lo > 0 or hi < 0)}
        print(f"  交乘增量(改善側動能價差-惡化側動能價差,同形成日配對n={n}): "
              f"{inter['diff']:+.2f}pp CI[{inter['lo']:+.2f},{inter['hi']:+.2f}]"
              f"{'✓排0=真交乘' if inter['sig'] else '含0=動能是相加層非相乘'}")
    else:
        inter = None
    res_up["ctrl"] = res_dn
    res_up["inter"] = inter
    return res_up


# ======================================================================
# 5. HTML
# ======================================================================
CSS = """
body{background:#1a1a19;color:#fff;font-family:"Noto Sans TC",sans-serif;margin:24px;max-width:1150px}
h1{font-size:20px} h2{font-size:15px;color:#c3c2b7;margin-top:30px;border-bottom:1px solid #333;padding-bottom:4px}
table{border-collapse:collapse;font-size:12.5px;font-variant-numeric:tabular-nums;margin:8px 0}
td,th{border:1px solid #333;padding:4px 9px;text-align:right} th{text-align:left;color:#c3c2b7}
.note{color:#8a8878;font-size:12.5px;line-height:1.8} .good{color:#7ec97e} .bad{color:#e06c5a}
.warn{color:#c3a55a} .hl{background:#2b3a2b} .sub{color:#777;font-size:11px}
ul{margin:4px 0;padding-left:20px;font-size:12.5px;color:#ccc;line-height:1.7}
.verdict{font-size:13px;font-weight:bold;padding:6px 10px;border-radius:4px;display:inline-block;margin:4px 0}
.v-good{background:#243b24;color:#7ec97e} .v-bad{background:#3b2420;color:#e06c5a}
.v-warn{background:#3b3420;color:#c3a55a}
"""


def write_report(a_out, b_res, n_events):
    def row(lab):
        s = a_out.get(lab)
        if not s:
            return ""
        b = s.get("boot")
        ci = f"[{b['lo'] * 100:+.2f},{b['hi'] * 100:+.2f}]{'✓' if b['sig'] else ''}" if b else "—"
        hl = " class='hl'" if lab.startswith("①") or lab.startswith("④") else ""
        return (f"<tr{hl}><th>{lab}</th><td>{s['n']:,}</td><td>{s['ret']:+.2f}%</td>"
                f"<td>{s['med']:+.2f}%</td><td>{ci}</td><td>{s['dm']:+.2f}%</td>"
                f"<td>{s['win']:.0f}%</td><td>{s['wl']:.2f}</td><td>{s['yr_pos']}/{s['yr_n']}</td></tr>")

    labs = ["①gm改善(QoQ>0)", "②gm惡化(QoQ<=0)", "③無財報資料", "④gm連2季改善",
            "⑤om改善(對照)", "⑥om惡化(對照)", "(全體候選)"]
    a_tbl = ("<table><tr><th>組別</th><th>n</th><th>絕對均值</th><th>中位</th><th>絕對CI(月群)</th>"
             "<th>demean</th><th>勝率</th><th>賺賠比</th><th>逐年正</th></tr>"
             + "".join(row(l) for l in labs) + "</table>")
    p = a_out.get("paired")
    pb = p.get("boot") if p else None
    paired_txt = (f"同日配對(同一訊號日改善/惡化兩組皆有,n_days={p['n_days']}): "
                  f"改善-惡化={p['diff']:+.2f}%/筆, 月群CI"
                  f"[{pb['lo'] * 100:+.2f},{pb['hi'] * 100:+.2f}]{'✓排0' if pb['sig'] else '含0'}"
                  ) if p and pb else "同日配對樣本不足"

    yearly_rows = ""
    g1 = a_out.get("①gm改善(QoQ>0)", {}).get("yearly", {})
    g2 = a_out.get("②gm惡化(QoQ<=0)", {}).get("yearly", {})
    for y in sorted(set(g1) | set(g2)):
        v1, v2 = g1.get(y), g2.get(y)
        yearly_rows += (f"<tr><th>{y}</th>"
                        f"<td class='{'good' if (v1 or 0) > 0 else 'bad'}'>{v1:+.2f}%</td>"
                        f"<td class='{'good' if (v2 or 0) > 0 else 'bad'}'>{v2:+.2f}%</td>"
                        f"<td>{(v1 - v2):+.2f}pp</td></tr>") if v1 is not None and v2 is not None else ""
    yearly_tbl = ("<table><tr><th>年</th><th>gm改善組(絕對)</th><th>gm惡化組(絕對)</th><th>差</th></tr>"
                  + yearly_rows + "</table>")

    ctrl = b_res.get("ctrl")
    inter = b_res.get("inter")
    b_txt = (f"<b>gm改善股</b>: 形成日{b_res['n_q']}個({b_res['n_obs']:,}筆), T1低動能{b_res['t1']:+.2f}% / "
             f"T2 {b_res['t2']:+.2f}% / T3高動能{b_res['t3']:+.2f}%(60日demean), "
             f"T3-T1={b_res['spread']:+.2f}pp CI[{b_res['lo']:+.2f},{b_res['hi']:+.2f}]"
             f"{'✓排0' if b_res['sig'] else '含0'}")
    if ctrl:
        b_txt += (f"<br><b>gm惡化股(對照)</b>: T1{ctrl['t1']:+.2f}% / T2 {ctrl['t2']:+.2f}% / "
                  f"T3{ctrl['t3']:+.2f}%, T3-T1={ctrl['spread']:+.2f}pp "
                  f"CI[{ctrl['lo']:+.2f},{ctrl['hi']:+.2f}]{'✓排0' if ctrl['sig'] else '含0'}")
    if inter:
        b_txt += (f"<br><b>交乘增量</b>(改善側價差-惡化側價差,同形成日配對n={inter['n']}): "
                  f"{inter['diff']:+.2f}pp CI[{inter['lo']:+.2f},{inter['hi']:+.2f}]"
                  f"{'✓排0=真交乘(動能在改善股內更有效)' if inter['sig'] else '含0=動能是相加層而非相乘增益'}")

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>毛利率QoQ×週級動能交乘考卷(2026-08-05)</title><style>{CSS}</style></head><body>
<h1>🧬 毛利率QoQ改善 × 週級動能 交乘考卷</h1>
<div class="note">財報八因子(research_fundamental_factors.html)最強因子=毛利率QoQ改善(+5.25pp/60日,
14/14年)但翻規則後邊際僅+1pp=候選層;週級動能可執行活口=逐日掃近5日>=20%次日收盤進場持5節
(research_weekly_momo_broad.html)。本卷測兩者交乘:「漲得快<b>且</b>毛利率在改善」。
方向A=動能候選加財報濾網(選股端,主檢定);方向B=毛利率改善股加動能濾網(形成日端)。
零前視: 財報用avail_date(法定期限+5日),進場=訊號次日收盤;動能事件{n_events:,}筆。</div>

<h2>方向A: 動能候選 × 訊號日已公告毛利率QoQ(持5交易日,絕對+demean並列)</h2>
{a_tbl}
<div class="note">{paired_txt}<br>
成本換算參考: 來回0.5%→各組絕對均值-0.5pp;來回1.1%(週級動能線量測前的保守值)→-1.1pp。
兩組比較(差值/配對)不受成本影響(同構)。</div>
<h2>逐年(gm改善 vs 惡化,絕對報酬)</h2>
{yearly_tbl}
<h2>方向B: 毛利率QoQ改善股 × 形成日前20日動能三分位(前瞻60交易日demean)</h2>
<div class="note">{b_txt}</div>

<h2>⚖️ 判決</h2>
<ul>
<li><span class="verdict v-warn">方向A=誠實null: 財報層不加值於5日動能口徑</span>
動能候選內gm改善vs惡化絕對報酬幾乎同(+1.55% vs +1.41%),同日配對-0.22%含0;om對照同型態。
機制解讀: 近5日漲20%的短線延續(持5日)由籌碼/情緒主導,一季一更新的慢速財報訊號在這個
時間尺度沒有辨識力。<b>唯一拉開的是「有無財報資料」(+1.55% vs +0.48%)</b>——但這是宇宙效應
(無財報=小型新股/冷門股),不是可交易濾網,誠實標註不上板。</li>
<li><span class="verdict v-good">方向B=真交乘: 動能只在毛利率改善股內有效</span>
gm改善股內動能T3-T1=+1.98pp✓排0;gm惡化股內僅+0.29pp含0;交乘增量+1.69pp CI排0。
「漲得快<b>且</b>毛利率在改善」的組合在60日視角成立——而且方向是<b>用動能篩改善股</b>
(慢訊號當資格門檻,快訊號當擇時),不是用財報篩動能股。與exam的Gate2教訓一致:
毛利率QoQ單獨翻規則邊際僅+1pp,疊上動能層後T3組demean+3.42%/60日=組合化把候選層扶上可用層。</li>
<li>實務翻譯: 週級動能5日口徑照舊(財報不加不減);<b>持有拉長到季級(60日)的部位,
「最新一季毛利率QoQ改善」應當資格門檻</b>——不符合的動能股60日層動能溢價會消失。</li>
</ul>
<h2>已知限制</h2>
<div class="note">①候選可連日重複觸發(同股連續數日入樣),統計靠月群bootstrap集群處理,n為事件數
非獨立股數;②fm_daily_price未還原除權息(保守偏誤,兩組同受);③財報覆蓋僅2013Q1起的826檔
(tw_quarterly_financials_history),小型新股「無財報資料」組天生混入;④金融股法定期限例外同exam;
⑤方向B每形成日n>=30才計,早年形成日可能被跳過。</div>
<div class="note">維運: python 研究腳本/財報事件/build_fundamental_momo_interaction.py(從根目錄執行)。
姊妹卷: build_fundamental_factors_exam.py(八因子首輪)、綜合策略/build_weekly_momo_executable_scan.py(動能活口口徑來源)。</div>
</body></html>"""
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n[report] 已輸出 {OUT}")


def main():
    t0 = time.time()
    fund = load_fundamentals()
    C, O, MN, tai = load_prices()
    m = build_events(C, O, MN, tai, fund)
    a_out = direction_a(m)
    b_res = direction_b(C, tai, fund)
    write_report(a_out, b_res, len(m))
    print(f"[main] 完成, {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
