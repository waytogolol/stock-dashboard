# -*- coding: utf-8 -*-
"""台陸題材連動考卷(2026-08-05,使用者假說:「陸股動的題材跟台股是否同步」)。

背景: 台美隔夜題材連動已驗證(build_us_tw_overnight_link.py+build_us_tw_pocket_refine.py,
題材獨漲口袋活口)。使用者追問陸股版。陸股日線管線=抓取/fetch_cn_daily_price.py
(cn_daily_price,337檔/27個台陸共同題材/2015起,yfinance調整價)。

═══ 與美股版的關鍵時序差異(寫程式前先想清楚) ═══
台股9:00-13:30、陸股9:30-15:00,同時區、盤面幾乎完全重疊:
· 「同日同步」= 兩市同時交易時一起動,描述性問題(回答使用者的「同步嗎」),**不可交易**
  (台股收盤時陸股還有1.5小時,反之陸股開盤比台股晚30分)。
· 可交易口徑=「陸股昨日收盤→台股今日」: 陸股t-1的15:00收盤,台股t的9:00開盤前已完全確認,零前視。
· 時序鏈(台股日t開盤前已知): 陸股t-1收盤(昨15:00) → 美股t-1收盤(今晨4-5點) → 台股t開盤。
  美股訊號比陸股「新」11-14小時——陸股訊號要有價值,必須在控制美股同夜訊號後仍有增量(§3回歸)。

═══ 考卷五問(預先註冊) ═══
Q1 同日同步性: corr(陸題材demean_t, 台題材demean_t)分題材,描述層。
Q2 陸股昨日→台股今日: 陸題材超額(減SSE)分層→台股同題材demean(cc/跳空/oc/CAR),比照美股版主檢定。
Q3 增量拆解: tw_cc ~ 陸題材超額 + 美題材超額(同夜) + SPX + SSE,日群bootstrap——陸股訊號
   是否只是美股訊號的影子?(台陸題材同漲常常都是跟著美股夜盤走)
Q4 口袋類比: 陸題材>2%且SSE<0(題材獨漲)→台股次日,比照美股口袋設計;另測美陸雙確認
   (美陸同題材同夜皆>2%,feedback第5條多層確認)。
Q5 反向: 台題材demean_t-1→陸題材demean_t(誰領先誰,對稱誠實)。

口徑: 台股側fm_daily_price close>0 AND money>0;兩側題材報酬=成員等權(當日有值成員>=2);
fresh限定(訊號日>=前一台股日,排除連假陳舊訊號——陸股春節/國慶黃金週與台股連假不同步,此檢查必要);
統計=月群bootstrap 95%CI+逐年;A股漲跌停(10/20%)與長停牌由成員有值門檻自然處理,誠實揭露。

用法: python 研究腳本/題材動能/build_cn_tw_theme_link.py   (從根目錄執行,鐵律)
產出: 研究報告/research_cn_tw_theme_link.html + console
"""
import json
import sqlite3
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

DB = "capital_flow.db"
OUT = "研究報告/research_cn_tw_theme_link.html"
START = "2015-01-01"
MIN_MEMBERS = 2
K_LIST = [1, 3, 5, 10]
ADR_EXCLUDE = {"TSM", "UMC", "ASX"}
rng = np.random.default_rng(20260805)

GREEN, RED, BLUE, YELLOW, GRAY = "#7ec97e", "#e06c5a", "#6bb7e3", "#c3a55a", "#8a8878"
BG = {"paper_bgcolor": "#1a1a19", "plot_bgcolor": "#22221f",
      "font": {"color": "#ddd", "size": 12}, "margin": {"t": 42, "l": 52, "r": 18, "b": 40},
      "legend": {"orientation": "h"}}


def theme_ret(px_ret, members, min_n=MIN_MEMBERS):
    cols = [c for c in members if c in px_ret.columns]
    if not cols:
        return None
    m = px_ret[cols]
    n = m.notna().sum(axis=1)
    return m.mean(axis=1).where(n >= min_n)


def load_all():
    conn = sqlite3.connect(DB, timeout=60)
    themes = sorted({r[0] for r in conn.execute(
        "select main_group from classification where country='陸' group by main_group "
        "having count(distinct code)>=2")} & {r[0] for r in conn.execute(
        "select main_group from classification where country='台' group by main_group "
        "having count(distinct code)>=2")})
    mem = {}
    for country, key in (("陸", "cn"), ("台", "tw"), ("美", "us")):
        for t in themes:
            mem[(key, t)] = [r[0] for r in conn.execute(
                "select distinct code from classification where country=? and main_group=?",
                (country, t))]
    all_tw = sorted({c for t in themes for c in mem[("tw", t)]})
    cnd = pd.read_sql("select code,date,close from cn_daily_price where date>='2014-06-01'", conn)
    usd = pd.read_sql("select code,date,close from us_daily_price where date>='2014-06-01'", conn)
    twd = pd.read_sql(
        "select code,date,open,close from fm_daily_price "
        "where date>='2014-06-01' and close>0 and money>0 and code in (%s)" % ",".join("?" * len(all_tw)),
        conn, params=all_tw)
    idx = pd.read_sql("select market,date,open,close from index_daily "
                      "where market in ('TAIEX','SPX','SSE') and date>='2014-06-01'", conn)
    conn.close()
    print(f"[load] 台陸共同題材{len(themes)}個; 陸{cnd.code.nunique()}檔/{len(cnd):,}筆, "
          f"台{twd.code.nunique()}檔/{len(twd):,}筆")
    return themes, mem, cnd, usd, twd, idx


def build_panel():
    themes, mem, cnd, usd, twd, idx = load_all()
    piv = lambda df, v: df.pivot_table(index="date", columns="code", values=v, aggfunc="first").sort_index()
    tai = idx[idx.market == "TAIEX"].set_index("date").sort_index()
    sse = idx[idx.market == "SSE"].set_index("date")["close"].sort_index()
    spx = idx[idx.market == "SPX"].set_index("date")["close"].sort_index()
    sse_ret, spx_ret = sse.pct_change(), spx.pct_change()

    cn_close = piv(cnd, "close")
    cn_ret = cn_close.pct_change(fill_method=None)
    us_close = piv(usd, "close")
    us_ret = us_close.pct_change(fill_method=None)

    tw_close = piv(twd, "close").reindex(tai.index)
    tw_open = piv(twd, "open").reindex(tai.index)
    tw_open = tw_open.where(tw_open > 0)
    cc = tw_close.pct_change(fill_method=None)
    oc = tw_close / tw_open - 1
    gap = tw_open / tw_close.shift(1) - 1
    car_o = {k: tw_close.shift(-k) / tw_open - 1 for k in K_LIST}
    tai_cc = tai["close"].pct_change()
    tai_oc = tai["close"] / tai["open"] - 1
    tai_gap = tai["open"] / tai["close"].shift(1) - 1
    tai_car_o = {k: tai["close"].shift(-k) / tai["open"] - 1 for k in K_LIST}

    cn_dates = np.array(cn_ret.index)
    us_dates = np.array(us_ret.index)
    tai_dates = list(tai.index)

    # 題材層訊號(陸/美)與台股反應
    cn_sig, us_sig, tw_r = {}, {}, {}
    for t in themes:
        r_cn = theme_ret(cn_ret, mem[("cn", t)])
        if r_cn is None:
            continue
        cn_sig[t] = pd.DataFrame({"r_raw": r_cn, "r_ex": r_cn - sse_ret.reindex(r_cn.index)})
        us_members = [c for c in mem[("us", t)] if c not in ADR_EXCLUDE]
        r_us = theme_ret(us_ret, us_members, min_n=1)
        if r_us is not None:
            us_sig[t] = r_us - spx_ret.reindex(r_us.index)
        tw_r[t] = {"cc": theme_ret(cc, mem[("tw", t)]), "oc": theme_ret(oc, mem[("tw", t)]),
                   "gap": theme_ret(gap, mem[("tw", t)]),
                   **{f"car_o{k}": theme_ret(car_o[k], mem[("tw", t)]) for k in K_LIST}}

    recs = []
    for i, day in enumerate(tai_dates):
        if day < START:
            continue
        p_cn = np.searchsorted(cn_dates, day) - 1
        p_us = np.searchsorted(us_dates, day) - 1
        if p_cn < 0 or p_us < 0:
            continue
        d_cn, d_us = cn_dates[p_cn], us_dates[p_us]
        prev = tai_dates[i - 1] if i > 0 else None
        fresh = (prev is None) or (d_cn >= prev)
        for t in cn_sig:
            if tw_r[t]["cc"] is None or day not in tw_r[t]["cc"].index:
                continue
            s = cn_sig[t]
            if d_cn not in s.index or pd.isna(s.at[d_cn, "r_raw"]):
                continue
            v_cc = tw_r[t]["cc"].get(day, np.nan)
            if pd.isna(v_cc):
                continue
            rec = {"theme": t, "t": day, "d_cn": d_cn, "fresh": fresh,
                   "cn_raw": s.at[d_cn, "r_raw"], "cn_ex": s.at[d_cn, "r_ex"],
                   "sse": sse_ret.get(d_cn, np.nan),
                   "us_ex": us_sig[t].get(d_us, np.nan) if t in us_sig else np.nan,
                   "spx": spx_ret.get(d_us, np.nan),
                   "tw_cc": v_cc - tai_cc.get(day, np.nan),
                   "tw_oc": tw_r[t]["oc"].get(day, np.nan) - tai_oc.get(day, np.nan),
                   "tw_gap": tw_r[t]["gap"].get(day, np.nan) - tai_gap.get(day, np.nan),
                   # 同日: 陸股「今天」(=day當天,若陸股今日有開)的題材demean——僅Q1描述用
                   "cn_today": (s.at[day, "r_ex"] if day in s.index else np.nan)}
            for k in K_LIST:
                rec[f"car_o{k}"] = tw_r[t][f"car_o{k}"].get(day, np.nan) - tai_car_o[k].get(day, np.nan)
            recs.append(rec)
    P = pd.DataFrame(recs)
    n_stale = int((~P["fresh"]).sum())
    P = P[P["fresh"]].copy()
    P["year"] = P["t"].str[:4]
    P["month"] = P["t"].str[:7]
    print(f"[panel] {len(P):,}筆題材×台股日({P.theme.nunique()}題材, {P.t.min()}~{P.t.max()}, "
          f"剔陳舊{n_stale})")
    return P, themes, cn_sig, tw_r, tai


def boot_ci(sub, col, n_iter=1000, cluster="month"):
    v = sub[[cluster, col]].dropna()
    if len(v) < 10 or v[cluster].nunique() < 6:
        return (np.nan, np.nan)
    grp = {d: g[col].values for d, g in v.groupby(cluster)}
    keys = list(grp)
    means = [np.mean(np.concatenate([grp[k] for k in rng.choice(keys, len(keys))]))
             for _ in range(n_iter)]
    return tuple(np.percentile(means, [2.5, 97.5]))


def ci_str(sub, col):
    lo, hi = boot_ci(sub, col)
    if pd.isna(lo):
        return "n太小"
    mark = "✓排0" if (lo > 0 or hi < 0) else "含0"
    return f"{sub[col].mean() * 100:+.2f}% [{lo * 100:+.2f},{hi * 100:+.2f}]{mark}"


# ---------- Q1 同日同步 ----------
def q1_sync(P):
    print("\n" + "=" * 80, "\nQ1 同日同步性: corr(陸題材超額_t, 台題材demean_t)(描述層,不可交易)")
    rows = []
    for t, g in P.dropna(subset=["cn_today", "tw_cc"]).groupby("theme"):
        if len(g) < 200:
            continue
        r = float(np.corrcoef(g.cn_today, g.tw_cc)[0, 1])
        rows.append({"theme": t, "n": len(g), "corr": r})
    rows.sort(key=lambda x: -x["corr"])
    for r in rows:
        print(f"  {r['theme']:<14} n={r['n']:>5} corr={r['corr']:+.3f}")
    allg = P.dropna(subset=["cn_today", "tw_cc"])
    pooled = float(np.corrcoef(allg.cn_today, allg.tw_cc)[0, 1])
    print(f"  [pooled] n={len(allg):,} corr={pooled:+.3f}")
    return rows, pooled


# ---------- Q2 陸股昨日→台股今日 ----------
def q2_buckets(P):
    print("\n" + "=" * 80, "\nQ2 陸題材超額(減SSE,昨日)分層 → 台股同題材今日demean")
    edges = [("大跌<-2%", P.cn_ex <= -0.02),
             ("普通-2~2%", (P.cn_ex > -0.02) & (P.cn_ex < 0.02)),
             ("大漲2~3%", (P.cn_ex >= 0.02) & (P.cn_ex < 0.03)),
             ("大漲>3%", P.cn_ex >= 0.03),
             ("大漲>2%合併", P.cn_ex >= 0.02)]
    rows = []
    for lab, mask in edges:
        s = P[mask]
        if len(s) < 10:
            continue
        r = {"lab": lab, "n": len(s), "cc": s.tw_cc.mean() * 100, "gap": s.tw_gap.mean() * 100,
             "oc": s.tw_oc.mean() * 100,
             **{f"car{k}": s[f"car_o{k}"].mean() * 100 for k in K_LIST}}
        rows.append(r)
        print(f"  {lab:<12} n={r['n']:>6} 當日cc{r['cc']:+.2f} 跳空{r['gap']:+.2f} oc{r['oc']:+.2f} "
              + " ".join(f"CAR{k}={r[f'car{k}']:+.2f}" for k in K_LIST))
    big = P[P.cn_ex >= 0.02]
    print(f"  [>2%合併CI] 當日cc: {ci_str(big, 'tw_cc')}  當日oc: {ci_str(big, 'tw_oc')}  "
          f"CAR5開錨: {ci_str(big, 'car_o5')}")
    print("  逐年(>2%合併, 當日cc / CAR5):")
    yearly = []
    for yy, g in big.groupby("year"):
        yearly.append((yy, len(g), g.tw_cc.mean() * 100, g.car_o5.mean() * 100))
        print(f"   {yy}: n={len(g):>4} cc={g.tw_cc.mean() * 100:+.2f} CAR5={g.car_o5.mean() * 100:+.2f}")
    print("  分題材(>2%, n>=15):")
    theme_rows = []
    for t, g in big.groupby("theme"):
        if len(g) < 15:
            continue
        theme_rows.append({"theme": t, "n": len(g), "cc": g.tw_cc.mean() * 100,
                           "car5": g.car_o5.mean() * 100})
    theme_rows.sort(key=lambda x: -x["cc"])
    for r in theme_rows:
        print(f"   {r['theme']:<14} n={r['n']:>4} cc={r['cc']:+.2f} CAR5={r['car5']:+.2f}")
    return rows, yearly, theme_rows, big


# ---------- Q3 增量回歸 ----------
def q3_regression(P):
    print("\n" + "=" * 80, "\nQ3 增量拆解: tw_cc ~ 陸題材超額 + 美題材超額(同夜) + SPX + SSE(日群bootstrap)")
    reg = P.dropna(subset=["cn_ex", "us_ex", "spx", "sse", "tw_cc"])
    X = np.column_stack([np.ones(len(reg)), reg.cn_ex, reg.us_ex, reg.spx, reg.sse])
    y = reg.tw_cc.values
    beta = np.linalg.lstsq(X, y, rcond=None)[0]
    days = reg.t.unique()
    bidx = {d: np.where(reg.t.values == d)[0] for d in days}
    bs = []
    for _ in range(500):
        pick = rng.choice(days, size=len(days), replace=True)
        ii = np.concatenate([bidx[d] for d in pick])
        bs.append(np.linalg.lstsq(X[ii], y[ii], rcond=None)[0])
    bs = np.array(bs)
    out = []
    for j, nm in enumerate(["截距", "陸題材超額(昨15:00)", "美題材超額(今晨5:00)", "SPX", "SSE"]):
        lo, hi = np.percentile(bs[:, j], [2.5, 97.5])
        sig = lo > 0 or hi < 0
        out.append({"nm": nm, "b": float(beta[j]), "lo": float(lo), "hi": float(hi), "sig": bool(sig)})
        print(f"  {nm:<18} b={beta[j]:+.4f} CI[{lo:+.4f},{hi:+.4f}]{'*' if sig else ''}")
    print(f"  (n={len(reg):,},僅台陸美三邊皆有對映的題材)")
    return out, len(reg)


# ---------- Q4 口袋類比 + 美陸雙確認 ----------
def q4_pocket(P):
    print("\n" + "=" * 80, "\nQ4 口袋類比與雙確認")
    combos = [
        ("陸口袋(陸raw>2%且SSE<0)", (P.cn_raw >= 0.02) & (P.sse < 0)),
        ("陸大漲但SSE>=0(對照)", (P.cn_raw >= 0.02) & (P.sse >= 0)),
        ("美陸雙確認(陸ex>2%且美ex>2%)", (P.cn_ex >= 0.02) & (P.us_ex >= 0.02)),
        ("僅陸不美(陸ex>2%且美ex<1%)", (P.cn_ex >= 0.02) & (P.us_ex < 0.01)),
    ]
    rows = []
    for lab, mask in combos:
        s = P[mask]
        if len(s) < 15:
            print(f"  {lab:<28} n={len(s)} 樣本不足")
            continue
        y = s.groupby("year").car_o5.mean()
        r = {"lab": lab, "n": len(s), "nyr": f"{int((y > 0).sum())}/{len(y)}",
             "gap": s.tw_gap.mean() * 100, "oc": s.tw_oc.mean() * 100,
             "cc": s.tw_cc.mean() * 100,
             **{f"car{k}": s[f"car_o{k}"].mean() * 100 for k in K_LIST},
             "ci5": ci_str(s, "car_o5"), "ci_oc": ci_str(s, "tw_oc")}
        rows.append(r)
        print(f"  {lab:<28} n={r['n']:>5} cc{r['cc']:+.2f} 跳空{r['gap']:+.2f} oc{r['oc']:+.2f} "
              + " ".join(f"CAR{k}={r[f'car{k}']:+.2f}" for k in K_LIST)
              + f" CI5:{r['ci5']} 逐年{r['nyr']}")
    return rows


# ---------- Q5 反向: 台昨→陸今 ----------
def q5_reverse(P, cn_sig, tw_r, tai):
    print("\n" + "=" * 80, "\nQ5 反向: 台題材demean昨日>2% → 陸題材超額今日(誰領先誰)")
    tai_cc = tai["close"].pct_change()
    recs = []
    for t, s in cn_sig.items():
        twcc = tw_r.get(t, {}).get("cc")
        if twcc is None:
            continue
        tw_dm = twcc - tai_cc.reindex(twcc.index)
        tw_prev = tw_dm.shift(1)          # 台股前一交易日
        common = s.index.intersection(tw_prev.dropna().index)
        for d in common:
            v_tw, v_cn = tw_prev.get(d, np.nan), s.at[d, "r_ex"]
            if pd.notna(v_tw) and pd.notna(v_cn):
                recs.append((t, d, v_tw, v_cn))
    R = pd.DataFrame(recs, columns=["theme", "d", "tw_prev", "cn_ex"])
    R["month"] = R.d.str[:7]
    big = R[R.tw_prev >= 0.02]
    base = R[(R.tw_prev > -0.02) & (R.tw_prev < 0.02)]
    lo, hi = boot_ci(big, "cn_ex")
    print(f"  台題材昨demean>2%(n={len(big):,}): 陸題材今超額={big.cn_ex.mean() * 100:+.2f}% "
          f"CI[{lo * 100:+.2f},{hi * 100:+.2f}]{'✓排0' if (lo > 0 or hi < 0) else '含0'} "
          f"(普通日基準{base.cn_ex.mean() * 100:+.2f}%)")
    return {"n": len(big), "mean": big.cn_ex.mean() * 100, "lo": lo * 100, "hi": hi * 100,
            "sig": bool(lo > 0 or hi < 0), "base": base.cn_ex.mean() * 100}


# ---------- HTML ----------
CSS = """
body{background:#1a1a19;color:#fff;font-family:"Noto Sans TC",sans-serif;margin:24px;max-width:1150px}
h1{font-size:20px} h2{font-size:15px;color:#c3c2b7;margin-top:30px;border-bottom:1px solid #333;padding-bottom:4px}
table{border-collapse:collapse;font-size:12.5px;font-variant-numeric:tabular-nums;margin:8px 0}
td,th{border:1px solid #333;padding:4px 9px;text-align:right} th{text-align:left;color:#c3c2b7}
.note{color:#8a8878;font-size:12.5px;line-height:1.8} .good{color:#7ec97e} .bad{color:#e06c5a}
.warn{color:#c3a55a} .hl{background:#2b3a2b}
ul{margin:4px 0;padding-left:20px;font-size:12.5px;color:#ccc;line-height:1.7}
.verdict{font-size:13px;font-weight:bold;padding:6px 10px;border-radius:4px;display:inline-block;margin:4px 0}
.v-good{background:#243b24;color:#7ec97e} .v-bad{background:#3b2420;color:#e06c5a}
.v-warn{background:#3b3420;color:#c3a55a}
.banner{background:#1d2a36;border:1px solid #6bb7e3;border-radius:6px;padding:14px 18px;margin:16px 0;
        color:#cfe6f5;font-size:13.5px;line-height:1.8}
"""


def write_report(P, sync_rows, pooled, q2_rows, yearly, theme_rows, big, reg_out, reg_n,
                 q4_rows, rev):
    sync_tbl = "<table><tr><th>題材</th><th>n</th><th>同日corr</th></tr>" + "".join(
        f"<tr><th>{r['theme']}</th><td>{r['n']:,}</td><td>{r['corr']:+.3f}</td></tr>"
        for r in sync_rows) + "</table>"
    q2_tbl = ("<table><tr><th>陸題材超額分層(昨日)</th><th>n</th><th>當日cc</th><th>跳空</th><th>oc</th>"
              + "".join(f"<th>CAR{k}</th>" for k in K_LIST) + "</tr>" + "".join(
        f"<tr><th>{r['lab']}</th><td>{r['n']:,}</td><td>{r['cc']:+.2f}</td><td>{r['gap']:+.2f}</td>"
        f"<td>{r['oc']:+.2f}</td>" + "".join(f"<td>{r[f'car{k}']:+.2f}</td>" for k in K_LIST) + "</tr>"
        for r in q2_rows) + "</table>")
    yr_tbl = "<table><tr><th>年</th><th>n</th><th>當日cc</th><th>CAR5</th></tr>" + "".join(
        f"<tr><th>{y}</th><td>{n}</td><td class='{'good' if c > 0 else 'bad'}'>{c:+.2f}</td>"
        f"<td class='{'good' if c5 > 0 else 'bad'}'>{c5:+.2f}</td></tr>"
        for y, n, c, c5 in yearly) + "</table>"
    th_tbl = "<table><tr><th>題材(陸ex>2%)</th><th>n</th><th>當日cc</th><th>CAR5</th></tr>" + "".join(
        f"<tr><th>{r['theme']}</th><td>{r['n']}</td><td>{r['cc']:+.2f}</td><td>{r['car5']:+.2f}</td></tr>"
        for r in theme_rows) + "</table>"
    reg_tbl = "<table><tr><th>係數</th><th>b</th><th>95%CI(日群)</th></tr>" + "".join(
        f"<tr><th>{r['nm']}</th><td>{r['b']:+.4f}</td><td>[{r['lo']:+.4f},{r['hi']:+.4f}]"
        f"{'<b>*</b>' if r['sig'] else ''}</td></tr>" for r in reg_out) + "</table>"
    q4_tbl = ("<table><tr><th>組合</th><th>n</th><th>當日cc</th><th>跳空</th><th>oc</th>"
              + "".join(f"<th>CAR{k}</th>" for k in K_LIST) + "<th>CAR5 CI</th><th>逐年</th></tr>" + "".join(
        f"<tr><th>{r['lab']}</th><td>{r['n']:,}</td><td>{r['cc']:+.2f}</td><td>{r['gap']:+.2f}</td>"
        f"<td>{r['oc']:+.2f}</td>" + "".join(f"<td>{r[f'car{k}']:+.2f}</td>" for k in K_LIST)
        + f"<td>{r['ci5']}</td><td>{r['nyr']}</td></tr>" for r in q4_rows) + "</table>")

    cn_b = next((r for r in reg_out if "陸題材" in r["nm"]), None)
    us_b = next((r for r in reg_out if "美題材" in r["nm"]), None)
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>台陸題材連動考卷(2026-08-05)</title><style>{CSS}</style></head><body>
<h1>🐉 台陸題材連動考卷: 同步性 + 陸股昨日→台股今日 + 美陸增量拆解</h1>
<div class="note">使用者假說:「陸股動的題材跟台股是否同步」。陸股側=cn_daily_price
(fetch_cn_daily_price.py,337檔/27個台陸共同題材/2015起,yfinance調整價);panel {len(P):,}筆
題材×台股日(fresh限定)。姊妹卷: 台美版build_us_tw_overnight_link.py/build_us_tw_pocket_refine.py。</div>
<div class="banner">🕓 <b>時序</b>: 台陸同時區、盤面幾乎重疊(台9:00-13:30/陸9:30-15:00)——
「同日同步」是描述性問題不可交易;可交易口徑=<b>陸股昨15:00收盤→台股今日</b>;
且美股同夜訊號(今晨4-5點收盤)比陸股訊號新11-14小時,陸股訊號必須在控制美股後仍有增量才算獨立訊號(Q3)。</div>

<h2>Q1 同日同步性(描述層): 陸題材超額 vs 台題材demean 同日相關</h2>
<div class="note">pooled corr={pooled:+.3f}(n={len(P.dropna(subset=['cn_today', 'tw_cc'])):,})。分題材:</div>
{sync_tbl}

<h2>Q2 陸股昨日→台股今日(可交易口徑)</h2>
{q2_tbl}
<div class="note">>2%合併格CI: 當日cc {ci_str(big, 'tw_cc')} · 當日oc {ci_str(big, 'tw_oc')} ·
CAR5開錨 {ci_str(big, 'car_o5')}</div>
<h3>逐年(陸ex>2%)</h3>{yr_tbl}
<h3>分題材(陸ex>2%, n>=15)</h3>{th_tbl}

<h2>Q3 增量拆解回歸(關鍵格): tw_cc ~ 陸超額+美超額+SPX+SSE</h2>
{reg_tbl}
<div class="note">n={reg_n:,}(僅台陸美三邊皆有對映的題材)。判讀: 美題材係數b={us_b['b']:+.3f}
{'*' if us_b and us_b['sig'] else ''} vs 陸題材係數b={cn_b['b']:+.3f}{'*' if cn_b and cn_b['sig'] else ''}——
陸股訊號{'在控制美股後仍有獨立增量' if cn_b and cn_b['sig'] else '被美股訊號吸收,無獨立增量'}。</div>

<h2>Q4 口袋類比 + 美陸雙確認</h2>
{q4_tbl}

<h2>Q5 反向(台昨→陸今)</h2>
<div class="note">台題材昨demean>2%(n={rev['n']:,}) → 陸題材今超額={rev['mean']:+.2f}%
CI[{rev['lo']:+.2f},{rev['hi']:+.2f}]{'✓排0' if rev['sig'] else '含0'}(普通日基準{rev['base']:+.2f}%)。</div>

<h2>⚖️ 判決(2026-08-05首輪)</h2>
<ul>
<li><span class="verdict v-warn">①同步性: 存在但很弱</span> pooled同日corr僅+0.070(台美連動的量級遠大於此);
最強的也只有PCB(+0.178)/記憶體(+0.173)。「陸股動的題材台股跟著動」方向為真,幅度很小。</li>
<li><span class="verdict v-warn">②陸昨→台今: 統計上真、經濟上薄、不可交易</span>
陸題材超額>2%→台股同題材當日demean+0.09%✓排0——但只有台美版(+0.5~0.7%)的1/6量級;
且跳空+0.27把它吃光(當日oc=-0.17%✓為負=開盤追買虧錢),CAR5含0。逐年方向大致穩(近兩年+0.26/+0.33略升)。</li>
<li><span class="verdict v-good">③增量拆解: 陸股訊號獨立於美股存在(機制上有趣)</span>
控制美題材/SPX/SSE後,陸題材超額係數b=+0.020*仍排0(美題材b=+0.030*)——陸股訊號不是美股影子,
是獨立的資訊源,只是量太薄。</li>
<li><span class="verdict v-bad">④口袋類比不複製</span> 陸口袋(陸>2%且SSE<0)CAR5+0.20含0;美陸雙確認
當日cc最高(+0.32)但跳空+0.74→oc-0.42=開盤全吃光。台美口袋的「開盤定價不足」機制在台陸之間不存在
(台股開盤時陸股訊號已舊了18小時,早被美股夜盤覆蓋定價)。</li>
<li><span class="verdict v-warn">⑤反向也通(台昨→陸今+0.19%✓ vs 基準+0.10%)</span>=互相弱外溢/共同因子,
沒有明確的單向領先者——兩市都主要跟隨美股夜盤。</li>
<li><b>總判</b>: 使用者假說方向獲驗證但不開交易線;陸股題材訊號定位=<b>觀察層/多層確認輔助</b>
(美股題材訊號已觸發時,陸股同題材同步強化可加信心),不單獨當進場依據。live訊號暫不納入
watch_us_tw_overnight(避免稀釋主訊號),資料管線保留weekly增量(update_all已掛)。</li>
</ul>

<h2>已知限制</h2>
<div class="note">①陸股側yfinance調整價,A股長停牌期間無列(成員>=2門檻自然處理),漲跌停(10/20%)
使題材日報酬分布截尾;②台股fm_daily_price未還原除權息(保守偏誤);③台陸題材對映用classification
main_group同名,兩側成員代表性未逐一人工核對(美股版同一限制);④2015-2016年cn_daily_price
部分個股上市前無資料,早年題材成員數較少;⑤同日corr(Q1)混合了「共同跟隨美股夜盤」與「盤中互相
牽引」兩種機制,本卷不拆盤中(無日內資料)。</div>
<div class="note">維運: python 研究腳本/題材動能/build_cn_tw_theme_link.py(從根目錄執行);
陸股日線增量=python 抓取/fetch_cn_daily_price.py(已掛update_all weekly)。</div>
</body></html>"""
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n[report] 已輸出 {OUT}")


def main():
    P, themes, cn_sig, tw_r, tai = build_panel()
    sync_rows, pooled = q1_sync(P)
    q2_rows, yearly, theme_rows, big = q2_buckets(P)
    reg_out, reg_n = q3_regression(P)
    q4_rows = q4_pocket(P)
    rev = q5_reverse(P, cn_sig, tw_r, tai)
    write_report(P, sync_rows, pooled, q2_rows, yearly, theme_rows, big, reg_out, reg_n,
                 q4_rows, rev)


if __name__ == "__main__":
    main()
