# -*- coding: utf-8 -*-
"""高價股上市/上櫃split × 三大法人考卷(2026-08-07,使用者提問)。

承接: high_price_stability(穩定性否定/RS活口)、high_price_followup(RS三關過/高價新貴/籌碼翻案)、
high_price_ignition(觸發全含0/大戶增加是唯一活因子)。本卷補兩個未拆維度:
①市場別: 上市(TWSE)高價股 vs 上櫃(OTC)高價股——上櫃高價股多為利基型中小成長股,
  波動/籌碼/報酬結構可能完全不同(既有教訓: 上櫃大戶接刀反向、上櫃融資單獨破警戒=領跌警訊)。
②三大法人: 外資/投信/自營在高價股的參與度與買超位階,以及「法人買超位階」能否在高價子集內選股。
口徑: 池=20日均額>=0.3億;高價=逐日池內前5%(相對)+>=500元(絕對)兩版;月頻等權(月初調倉,毛報酬);
demean減對應市場指數(上市TAIEX/上櫃TPEx,比只用TAIEX更公允);inst_flow覆蓋期較短(誠實揭露n)。
用法: python 研究腳本/綜合策略/build_high_price_market_inst.py  (從根目錄執行,鐵律)
產出: 研究報告/research_high_price_market_inst.html + console
"""
import json
import sqlite3
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

DB = "capital_flow.db"
OUT = "研究報告/research_high_price_market_inst.html"
LIQ_MIN = 0.3e8
rng = np.random.default_rng(20260807)


def main():
    conn = sqlite3.connect(DB, timeout=60)
    inst_cols = [r[1] for r in conn.execute("pragma table_info(inst_flow)").fetchall()]
    print("[schema] inst_flow欄位:", inst_cols)
    px = pd.read_sql("SELECT code,date,close,money FROM fm_daily_price "
                     "WHERE date>='2013-06-01' AND close>0 AND money>0", conn)
    idx = pd.read_sql("SELECT market,date,close FROM index_daily "
                      "WHERE market IN ('TAIEX','TPEx') AND date>='2013-06-01'", conn)
    td = pd.read_sql("SELECT code, date, p1000, p_retail FROM tdcc_weekly", conn, parse_dates=["date"])
    sel = ",".join([c for c in ("foreign_net", "trust_net", "dealer_net") if c in inst_cols])
    inst = pd.read_sql(f"SELECT date, code, {sel} FROM inst_flow", conn)
    conn.close()

    mkt = pd.read_csv("tw_all_listed.csv", dtype=str).dropna(subset=["code"])
    mkt_of = dict(zip(mkt.code, mkt.market.fillna("")))
    print("[market] tw_all_listed市場別分布:", mkt.market.value_counts().to_dict())

    C = px.pivot_table(index="date", columns="code", values="close", aggfunc="first").sort_index()
    MN = px.pivot_table(index="date", columns="code", values="money", aggfunc="first").sort_index()
    dates = list(C.index)
    Cf = C.ffill(limit=5)
    liq_prev = MN.rolling(20, min_periods=15).mean().shift(1)
    pool_ok = liq_prev >= LIQ_MIN
    tai = idx[idx.market == "TAIEX"].set_index("date")["close"].reindex(C.index).ffill()
    tpex = idx[idx.market == "TPEx"].set_index("date")["close"].reindex(C.index).ffill()

    def is_otc(c):
        m = mkt_of.get(c, "")
        return ("櫃" in m) or ("otc" in m.lower()) or (m == "TWO")

    otc_flag = {c: is_otc(c) for c in C.columns}
    n_otc = sum(otc_flag.values())
    print(f"[market] 面板內上櫃{n_otc}檔 / 上市{len(C.columns) - n_otc}檔")

    didx = pd.to_datetime(pd.Index(dates))
    f_idx = [i for i in np.where(~didx.to_period("M").duplicated())[0]
             if dates[i] >= "2015-01-01" and i + 1 < len(dates)]

    def groups_at(i):
        c_row = C.iloc[i].where(pool_ok.iloc[i])
        pr = c_row.dropna()
        if len(pr) < 50:
            return {}
        th5 = pr.quantile(0.95)
        top5 = set(pr.index[pr >= th5])
        abs500 = set(pr.index[pr >= 500])
        return {
            "前5%·上市": {c for c in top5 if not otc_flag.get(c, False)},
            "前5%·上櫃": {c for c in top5 if otc_flag.get(c, False)},
            ">=500·上市": {c for c in abs500 if not otc_flag.get(c, False)},
            ">=500·上櫃": {c for c in abs500 if otc_flag.get(c, False)},
            "池·上市": {c for c in pr.index if not otc_flag.get(c, False)},
            "池·上櫃": {c for c in pr.index if otc_flag.get(c, False)},
        }

    KEYS = ["前5%·上市", "前5%·上櫃", ">=500·上市", ">=500·上櫃", "池·上市", "池·上櫃"]
    navs = {k: [1.0] for k in KEYS}
    navs["TAIEX"], navs["TPEx"] = [1.0], [1.0]
    nav_dates = [dates[f_idx[0]]]
    ev = {k: [] for k in KEYS}
    cnt = {k: [] for k in KEYS}
    for a, b in zip(f_idx[:-1], f_idx[1:]):
        g = groups_at(a)
        if not g:
            continue
        tai_r = tai.iloc[b] / tai.iloc[a] - 1
        tpex_r = tpex.iloc[b] / tpex.iloc[a] - 1
        for k in KEYS:
            bench = tpex_r if "上櫃" in k else tai_r
            rets = []
            for c in g.get(k, ()):
                ci = Cf.columns.get_loc(c)
                p0, p1 = C.iat[a, ci], Cf.iat[b, ci]
                if pd.notna(p0) and pd.notna(p1) and p0 > 0:
                    r = p1 / p0 - 1
                    rets.append(r)
                    ev[k].append((dates[a][:7], r - bench))
            cnt[k].append(len(rets))
            navs[k].append(navs[k][-1] * (1 + (np.mean(rets) if rets else 0.0)))
        navs["TAIEX"].append(navs["TAIEX"][-1] * (1 + tai_r))
        navs["TPEx"].append(navs["TPEx"][-1] * (1 + tpex_r))
        nav_dates.append(dates[b])

    def stats(v):
        s = pd.Series(v)
        yrs = (pd.Timestamp(nav_dates[-1]) - pd.Timestamp(nav_dates[0])).days / 365.25
        ann = s.iloc[-1] ** (1 / yrs) - 1
        mdd = (s / s.cummax() - 1).min()
        mr = s.pct_change().dropna()
        return (ann * 100, mdd * 100, (mr.mean() / mr.std() * np.sqrt(12)) if mr.std() > 0 else np.nan,
                (mr > 0).mean() * 100)

    def boot(lst):
        E = pd.DataFrame(lst, columns=["ym", "v"])
        if len(E) < 100:
            return None
        grp = {m: g.v.values for m, g in E.groupby("ym")}
        keys = list(grp)
        means = [np.mean(np.concatenate([grp[m] for m in rng.choice(keys, len(keys))]))
                 for _ in range(1000)]
        lo, hi = np.percentile(means, [2.5, 97.5])
        return {"mean": E.v.mean() * 100, "lo": lo * 100, "hi": hi * 100,
                "sig": bool(lo > 0 or hi < 0), "n": len(E)}

    print("\n① 市場別split(月頻等權,毛報酬,demean減各自市場指數)")
    P1 = {}
    for k in KEYS + ["TAIEX", "TPEx"]:
        ann, mdd, shp, win = stats(navs[k])
        b = boot(ev[k]) if k in ev else None
        P1[k] = {"ann": ann, "mdd": mdd, "shp": shp, "win": win, "b": b,
                 "calmar": ann / abs(mdd) if mdd < 0 else np.nan,
                 "n_avg": np.mean(cnt[k]) if k in cnt else np.nan}
        print(f"  {k:<12} 平均{P1[k]['n_avg'] if pd.notna(P1[k]['n_avg']) else 0:>5.0f}檔 "
              f"年化{ann:+.1f}% MDD{mdd:.1f}% 夏普{shp:.2f} Calmar{P1[k]['calmar']:.2f} 月勝率{win:.0f}%"
              + (f" 月demean{b['mean']:+.2f}[{b['lo']:+.2f},{b['hi']:+.2f}]{'✓' if b['sig'] else ''}" if b else ""))

    # ---------- ② 籌碼(集保)分市場 ----------
    print("\n② 籌碼分市場(千張大戶%/散戶%,季抽樣)")
    td_w = td.pivot_table(index="date", columns="code", values="p1000", aggfunc="first").sort_index()
    td_r = td.pivot_table(index="date", columns="code", values="p_retail", aggfunc="first").sort_index()
    chip = {k: {"p1000": [], "retail": []} for k in KEYS}
    for i in f_idx[::3]:
        ti = td_w.index.searchsorted(pd.Timestamp(dates[i]), side="right") - 1
        if ti < 0 or (pd.Timestamp(dates[i]) - td_w.index[ti]).days > 14:
            continue
        g = groups_at(i)
        for k in KEYS:
            m = [c for c in g.get(k, ()) if c in td_w.columns]
            if len(m) < 5:
                continue
            chip[k]["p1000"].append(td_w.iloc[ti][m].median())
            chip[k]["retail"].append(td_r.iloc[ti][m].median())
    P2 = {k: {kk: np.nanmean(v) for kk, v in chip[k].items()} for k in KEYS}
    for k in KEYS:
        print(f"  {k:<12} 千張大戶%中位{P2[k]['p1000']:.1f} 散戶%中位{P2[k]['retail']:.1f}")

    # ---------- ③ 三大法人 ----------
    print("\n③ 三大法人(inst_flow覆蓋期)")
    have = [c for c in ("foreign_net", "trust_net", "dealer_net") if c in inst.columns]
    inst["combo"] = inst[have].fillna(0).sum(axis=1)
    print(f"  可用欄位{have}, 期間{inst.date.min()}~{inst.date.max()}, {len(inst):,}列")
    wide = inst.pivot_table(index="date", columns="code", values="combo", aggfunc="sum").sort_index()
    roll20 = wide.rolling(20, min_periods=10).sum()
    pct240 = roll20.rolling(240, min_periods=120).rank(pct=True) * 100
    # 高價 vs 池 的法人買超位階;以及位階高低在高價子集內的前瞻報酬
    P3 = {"part": {}, "split": {}}
    lv_rows = {k: [] for k in KEYS}
    for i in f_idx:
        d = dates[i]
        if d not in pct240.index:
            continue
        g = groups_at(i)
        row = pct240.loc[d]
        for k in KEYS:
            m = [c for c in g.get(k, ()) if c in row.index]
            v = row[m].dropna()
            if len(v) >= 5:
                lv_rows[k].append(v.median())
    for k in KEYS:
        P3["part"][k] = np.nanmean(lv_rows[k]) if lv_rows[k] else np.nan
        print(f"  {k:<12} 法人20日買超位階中位(0-100)={P3['part'][k]:.1f}")
    # 位階分組前瞻(高價前5%合併兩市)
    hi_ev, lo_ev = [], []
    for a, b in zip(f_idx[:-1], f_idx[1:]):
        d = dates[a]
        if d not in pct240.index:
            continue
        g = groups_at(a)
        top = set(g.get("前5%·上市", set())) | set(g.get("前5%·上櫃", set()))
        row = pct240.loc[d]
        tai_r = tai.iloc[b] / tai.iloc[a] - 1
        tpex_r = tpex.iloc[b] / tpex.iloc[a] - 1
        for c in top:
            if c not in row.index or pd.isna(row[c]):
                continue
            ci = Cf.columns.get_loc(c)
            p0, p1 = C.iat[a, ci], Cf.iat[b, ci]
            if pd.isna(p0) or pd.isna(p1) or p0 <= 0:
                continue
            bench = tpex_r if otc_flag.get(c, False) else tai_r
            rec = (d[:7], p1 / p0 - 1 - bench)
            if row[c] >= 80:
                hi_ev.append(rec)
            elif row[c] <= 20:
                lo_ev.append(rec)
    b_hi, b_lo = boot(hi_ev), boot(lo_ev)
    P3["split"] = {"hi": b_hi, "lo": b_lo}
    if b_hi:
        print(f"  高價×法人位階>=80: n={b_hi['n']:,} 月demean{b_hi['mean']:+.2f}"
              f"[{b_hi['lo']:+.2f},{b_hi['hi']:+.2f}]{'✓' if b_hi['sig'] else ''}")
    if b_lo:
        print(f"  高價×法人位階<=20: n={b_lo['n']:,} 月demean{b_lo['mean']:+.2f}"
              f"[{b_lo['lo']:+.2f},{b_lo['hi']:+.2f}]{'✓' if b_lo['sig'] else ''}")

    # ---------- HTML ----------
    CSS = """
body{background:#1a1a19;color:#fff;font-family:"Noto Sans TC",sans-serif;margin:24px;max-width:1050px}
h1{font-size:20px} h2{font-size:15px;color:#c3c2b7;margin-top:28px;border-bottom:1px solid #333;padding-bottom:4px}
table{border-collapse:collapse;font-size:12.5px;font-variant-numeric:tabular-nums;margin:8px 0}
td,th{border:1px solid #333;padding:4px 9px;text-align:right} th{text-align:left;color:#c3c2b7}
.note{color:#8a8878;font-size:12.5px;line-height:1.8} .good{color:#7ec97e} .bad{color:#e06c5a}
.hl{background:#2b3a2b}
ul{margin:4px 0;padding-left:20px;font-size:12.5px;color:#ccc;line-height:1.7}
"""
    t1 = ("<table><tr><th>組</th><th>平均檔數</th><th>年化(毛)</th><th>MDD</th><th>夏普</th><th>Calmar</th>"
          "<th>月勝率</th><th>月demean CI</th></tr>")
    for k in KEYS + ["TAIEX", "TPEx"]:
        p = P1[k]
        ci = (f"{p['b']['mean']:+.2f}[{p['b']['lo']:+.2f},{p['b']['hi']:+.2f}]{'✓' if p['b']['sig'] else ''}"
              if p["b"] else "—")
        t1 += (f"<tr{' class=hl' if k.startswith('前5%') else ''}><th>{k}</th>"
               f"<td>{p['n_avg']:.0f}</td>" if pd.notna(p["n_avg"]) else f"<tr><th>{k}</th><td>—</td>")
        t1 += (f"<td>{p['ann']:+.1f}%</td><td>{p['mdd']:.1f}%</td><td>{p['shp']:.2f}</td>"
               f"<td>{p['calmar']:.2f}</td><td>{p['win']:.0f}%</td><td>{ci}</td></tr>")
    t1 += "</table>"
    t2 = ("<table><tr><th>組</th><th>千張大戶%中位</th><th>散戶%中位</th><th>法人20日買超位階中位</th></tr>"
          + "".join(f"<tr><th>{k}</th><td>{P2[k]['p1000']:.1f}</td><td>{P2[k]['retail']:.1f}</td>"
                    f"<td>{P3['part'][k]:.1f}</td></tr>" for k in KEYS) + "</table>")
    hi, lo = P3["split"]["hi"], P3["split"]["lo"]
    t3 = ("<table><tr><th>高價前5%(兩市合併)×法人位階</th><th>n</th><th>月demean</th><th>CI</th></tr>"
          + (f"<tr><th>位階>=80(法人大買)</th><td>{hi['n']:,}</td><td>{hi['mean']:+.2f}%</td>"
             f"<td>[{hi['lo']:+.2f},{hi['hi']:+.2f}]{'✓' if hi['sig'] else ''}</td></tr>" if hi else "")
          + (f"<tr><th>位階<=20(法人賣)</th><td>{lo['n']:,}</td><td>{lo['mean']:+.2f}%</td>"
             f"<td>[{lo['lo']:+.2f},{lo['hi']:+.2f}]{'✓' if lo['sig'] else ''}</td></tr>" if lo else "")
          + "</table>")
    nav_json = json.dumps([{"name": k, "dates": nav_dates, "vals": [round(x, 4) for x in navs[k]]}
                           for k in KEYS + ["TAIEX", "TPEx"]], ensure_ascii=False)

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>高價股上市櫃split×三大法人(2026-08-07)</title>
<script src="plotly.min.js"></script><style>{CSS}</style></head><body>
<h1>🏛️ 高價股: 上市/上櫃split × 三大法人</h1>
<div class="note">使用者提問。月頻等權(月初調倉,毛報酬未扣成本),池=20日均額>=0.3億,2015起;
<b>demean減各自市場指數</b>(上市TAIEX/上櫃TPEx)比統一減TAIEX公允。⚠除權息未還原(對高價績優股低估)。</div>
<h2>① 市場別split</h2>
{t1}
<div id="c_nav" style="height:460px"></div>
<h2>② 籌碼(集保)+法人參與度</h2>
{t2}
<h2>③ 高價股內的法人買超位階分組</h2>
{t3}
<h2>⚖️ 判決(2026-08-07)</h2>
<ul>
<li><span class="verdict v-good" style="background:#243b24;color:#7ec97e;padding:6px 10px;border-radius:4px;font-weight:bold">①上市/上櫃split有料: 高價股的問題主要出在上櫃</span>
上市高價(前5%)年化+15.1%/MDD-43.8%/Calmar0.35 vs <b>上櫃高價+11.0%/MDD-52.2%/Calmar0.21</b>;
絕對>=500元差更大(上市+16.6%/-47.3% vs <b>上櫃+6.6%/MDD-65.8%/Calmar0.10=全場最糟</b>)——
<b>上櫃高價股=最不該碰的格</b>(小池7-9檔+高波動+殺起來最深)。與既有「上櫃大戶接刀反向」「上櫃融資
單獨破警戒=領跌警訊」三度互證: <b>上櫃的極端族群訊號多半是陷阱</b>。</li>
<li><span class="verdict v-warn" style="background:#3b3420;color:#c3a55a;padding:6px 10px;border-radius:4px;font-weight:bold">②但兩市高價股的alpha都是0</span>
用各自市場指數demean後,四個高價組月demean全部含0(+0.19/+0.25/-0.13/+0.42)——
<b>「高價股不是因子」的結論在分市場後依然成立</b>,split只改變了風險面(上櫃更差),沒生出alpha。</li>
<li><span class="verdict v-good" style="background:#243b24;color:#7ec97e;padding:6px 10px;border-radius:4px;font-weight:bold">③籌碼結構的市場別差異巨大(本卷最大發現)</span>
千張大戶%: 上市高價<b>57.2</b> vs 上櫃高價<b>40.5</b>(池上市59.2/池上櫃38.5);散戶%: 上市高價4.5 vs
上櫃高價9.6。<b>上櫃高價股的大戶集中度低了近17pp</b>=籌碼結構鬆散,正好解釋①的MDD更深——
「高價=籌碼穩」的直覺只在上市成立,上櫃反而是「高價但籌碼散」。</li>
<li><span class="verdict v-bad" style="background:#3b2420;color:#e06c5a;padding:6px 10px;border-radius:4px;font-weight:bold">④三大法人: 資料缺口誠實揭露</span>
inst_flow涵蓋1,424檔但<b>上櫃僅4檔</b>(1,089檔上市)=<b>上櫃法人買賣超實質沒有資料</b>,
故上櫃法人欄位全NaN、法人分析只能代表上市。上市高價股法人位階中位50.5≈池53.1(無明顯偏好);
高價×法人位階>=80月demean+0.63含0 / <=20為-0.90含0=<b>法人位階在高價子集內選不出股</b>
(與融券回補卷「法人籌碼AUC不過門檻」一致)。⚠待辦: 若要補上櫃法人,需另開OTC三大法人抓取
(TPEx官方每日提供,現有管線只吃TWSE)。</li>
</ul>
<div class="note">維運: python 研究腳本/綜合策略/build_high_price_market_inst.py(從根目錄執行)。</div>
<script>
const NAVS={nav_json};
Plotly.newPlot('c_nav', NAVS.map(s=>({{x:s.dates,y:s.vals,name:s.name,mode:'lines'}})),
  {{title:'月頻等權權益曲線(毛報酬,對數軸)', paper_bgcolor:'#1a1a19',plot_bgcolor:'#22221f',
    font:{{color:'#ddd',size:12}},yaxis:{{title:'NAV',type:'log'}},legend:{{orientation:'h'}},
    margin:{{t:42,l:52,r:18,b:40}}}});
</script>
</body></html>"""
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n[report] 已輸出 {OUT}")


if __name__ == "__main__":
    main()
