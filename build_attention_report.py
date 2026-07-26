# -*- coding: utf-8 -*-
"""注意股跌觸發完整報告產生器(2026-07-26,使用者批評0720判決缺權益曲線/持有期依據/分組刨析)
產出: 研究報告/research_attention.html(取代靜態版)
新增內容(預註冊):
- 持有期網格 k=3/5/10/15/20(次日開盤買→T+k收盤,扣0.45%房規;原考卷0.3%的+5.79%作錨對照)
- 分組: ①初犯vs連續(90日內有無前episode) ②30日內公告次數1/2-5/6+(6+=瀕臨處置事前代理,
  升級標準道=10日6次/30日12次) ③事後真升級組(20交易日內進處置,ex-post描述用)
  ④款別(純1/混合/含4排除驗證) ⑤市場別
- 權益曲線: trade10單利Σ(全體/純款1/混合)+cap10併發限制版+年度Σ表
- 驗證: headline(k=10)LOTO逐年+年群bootstrap重跑(0.45%口徑);錨=0.3%口徑重現+5.79%/n=475
用法: python -X utf8 build_attention_report.py
"""
import json
import sqlite3
import sys
import time

import numpy as np
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DB = "capital_flow.db"
OUT = "研究報告/research_attention.html"
COST = 0.45
KS = [3, 5, 10, 15, 20]
B_BOOT = 10000
SEED = 42


def rd(sql, tries=6, wait=4):
    for i in range(tries):
        try:
            con = sqlite3.connect(DB, timeout=30)
            df = pd.read_sql(sql, con)
            con.close()
            return df
        except sqlite3.OperationalError as e:
            if "locked" in str(e) and i < tries - 1:
                time.sleep(wait)
            else:
                raise


def sstat(x):
    x = pd.Series(x).dropna()
    if len(x) < 10:
        return None
    return dict(med=x.median(), mean=x.mean(), win=(x > 0).mean() * 100, n=len(x))


def loto_boot(sig, ctl, val, b=B_BOOT, seed=SEED):
    sig, ctl = sig.dropna(subset=[val]), ctl.dropna(subset=[val])
    years = sorted(set(sig.y) | set(ctl.y))
    rows = []
    for yr in years:
        s2, c2 = sig[sig.y != yr], ctl[ctl.y != yr]
        if len(s2) >= 10 and len(c2) >= 10:
            rows.append((yr, s2[val].median() - c2[val].median()))
    rows.sort(key=lambda r: r[1])
    pos = sum(1 for _, d in rows if d > 0)
    rng = np.random.default_rng(seed)
    sg = {yr: sig.loc[sig.y == yr, val].values for yr in sig.y.unique()}
    cg = {yr: ctl.loc[ctl.y == yr, val].values for yr in ctl.y.unique()}
    diffs = []
    for _ in range(b):
        pick = rng.choice(years, size=len(years), replace=True)
        sa = [sg[y] for y in pick if y in sg]
        ca = [cg[y] for y in pick if y in cg]
        if sa and ca:
            sa, ca = np.concatenate(sa), np.concatenate(ca)
            if len(sa) >= 10 and len(ca) >= 10:
                diffs.append(np.median(sa) - np.median(ca))
    diffs = np.array(diffs)
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    return dict(worst_yr=rows[0][0], worst=rows[0][1], pos=pos, tot=len(rows),
                lo=lo, hi=hi, p=(diffs <= 0).mean())


def main():
    att = rd("SELECT code, announce_date AS date, market, reason, triggers, pe, close_price "
             "FROM attention ORDER BY code, announce_date")
    att["date"] = pd.to_datetime(att.date)
    att = att[att.code.str.fullmatch(r"\d{4}")]
    cls = set(rd("SELECT DISTINCT code FROM classification WHERE country='台'").code)
    px = rd("SELECT code, date, open, close, money FROM fm_daily_price ORDER BY code, date")
    px["date"] = pd.to_datetime(px.date)
    cal = pd.DatetimeIndex(sorted(px.date.unique()))
    cal_idx = {d: i for i, d in enumerate(cal)}
    stocks = {c: g.sort_values("date").reset_index(drop=True) for c, g in px.groupby("code")}
    disp = rd("SELECT code, start_date FROM disposition")
    disp["start_date"] = pd.to_datetime(disp.start_date, errors="coerce")
    disp_map = disp.dropna().groupby("code").start_date.apply(list).to_dict()

    # 方向分類(同原考卷): 跌觸發=含跌幅不含漲幅
    att["down"] = att.reason.astype(str).str.contains("跌幅") & ~att.reason.astype(str).str.contains("漲幅")
    # episode化: 同碼相鄰公告<=10交易日=同波,取首筆
    att["ci"] = att.date.map(lambda d: cal_idx.get(d, np.nan))
    att = att.dropna(subset=["ci"])
    att["ci"] = att.ci.astype(int)
    att = att.sort_values(["code", "date"])
    att["gap"] = att.groupby("code").ci.diff()
    att["ep_first"] = att.gap.isna() | (att.gap > 10)
    eps = att[att.ep_first].copy()

    # 30日內公告次數(含自身,事前可知): 用原始公告列計
    cnt30 = []
    by_code = {c: g.ci.values for c, g in att.groupby("code")}
    for r in eps.itertuples():
        arr = by_code[r.code]
        cnt30.append(int(((arr >= r.ci - 22) & (arr <= r.ci)).sum()))
    eps["n30"] = cnt30
    # 初犯vs連續: 90日曆日內有無前一個episode
    eps["prev_gap"] = eps.groupby("code").date.diff().dt.days
    eps["repeat"] = eps.prev_gap.notna() & (eps.prev_gap <= 90)
    # 事後升級(描述用): 20交易日內進處置
    upg = []
    for r in eps.itertuples():
        ds = disp_map.get(r.code, [])
        upg.append(any(0 <= cal_idx.get(d, -1) - r.ci <= 20 for d in ds if d in cal_idx))
    eps["upgrade"] = upg

    # 交易報酬網格 + 規模(公告前20日均成交值,事前可知)
    for k in KS:
        eps[f"t{k}"] = np.nan
    eps["t10_03"] = np.nan  # 0.3%錨口徑
    eps["amt20"] = np.nan
    for i, r in enumerate(eps.itertuples()):
        g = stocks.get(r.code)
        if g is None:
            continue
        dts = g.date.values
        n = len(g)
        j = int(np.searchsorted(dts, np.datetime64(r.date), side="right"))  # 公告次日(含休市順延)
        if j >= n or g.open.values[j] <= 0:
            continue
        o0 = g.open.values[j]
        if j >= 11:
            w = g.money.values[max(0, j - 21):j - 1]
            w = w[w > 0]
            if len(w) >= 10:
                eps.iloc[i, eps.columns.get_loc("amt20")] = float(np.mean(w)) / 1e8
        for k in KS:
            jj = j + k
            if jj < n and g.close.values[jj] > 0:
                eps.iloc[i, eps.columns.get_loc(f"t{k}")] = (g.close.values[jj] / o0 - 1) * 100 - COST
        if j + 10 < n and g.close.values[j + 10] > 0:
            eps.iloc[i, eps.columns.get_loc("t10_03")] = (g.close.values[j + 10] / o0 - 1) * 100 - 0.3
    eps["theme"] = eps.code.isin(cls)
    # 觸發強度劑量(使用者2026-07-26提案「注意的原因本身是因子」): 原文解析累積跌幅%
    import re as _re
    eps["drop_mag"] = eps.reason.astype(str).map(
        lambda s: max((float(x) for x in _re.findall(r"跌幅[達為]?\s*(-?[\d.]+)\s*%", s)), default=np.nan))
    eps["loss_pe"] = eps.pe.isna() | (eps.pe <= 0)  # 虧損/無本益比
    eps["y"] = eps.date.dt.year
    eps.to_pickle("tmp_attention_full_panel.pkl")  # 含amt20/drop_mag/pe/close_price/theme等全特徵
    down = eps[eps.down & eps.t10.notna()].copy()
    other = eps[~eps.down & eps.t10.notna()].copy()
    print(f"episodes: 全體{len(eps):,} 跌觸發可交易{len(down):,} 其餘{len(other):,}")
    anchor = sstat(down.t10_03)
    print(f"錨(0.3%口徑,對照0720的+5.79%/n=475): 中位{anchor['med']:+.2f}%/{anchor['win']:.0f}%/n={anchor['n']}")

    # headline驗證(0.45%)
    v = loto_boot(down, other, "t10")
    h = sstat(down.t10)
    print(f"headline t10(0.45%): 中位{h['med']:+.2f}%/勝{h['win']:.0f}%/n={h['n']}; "
          f"LOTO {v['pos']}/{v['tot']}年正(最壞剔{v['worst_yr']}={v['worst']:+.2f}pp); "
          f"差值CI[{v['lo']:+.2f},{v['hi']:+.2f}] P={v['p']:.4f}")

    # 持有期網格
    grid = {k: sstat(down[f"t{k}"]) for k in KS}
    # 分組(皆t10)
    def gs(mask):
        return sstat(down.loc[mask, "t10"])
    groups = {
        "初犯(90日內無前波)": gs(~down.repeat), "連續犯(90日內有前波)": gs(down.repeat),
        "30日1次(剛冒頭)": gs(down.n30 <= 1), "30日2-5次(升溫)": gs(down.n30.between(2, 5)),
        "30日6次+(瀕臨處置)": gs(down.n30 >= 6),
        "事後真升級處置(ex-post)": gs(down.upgrade), "未升級": gs(~down.upgrade),
        "上市": gs(down.market.str.contains("上市|twse|TWSE", na=False)),
        "上櫃": gs(~down.market.str.contains("上市|twse|TWSE", na=False)),
        "純款1": gs(down.triggers == "1"),
        "混合觸發(2款+)": gs(down.triggers.astype(str).str.contains(",")),
        "含款4(排除驗證)": gs(down.triggers.astype(str).str.split(",").map(lambda x: "4" in x)),
        "題材成員": gs(down.theme), "非題材": gs(~down.theme),
        "金流大(前1/3)": gs(down.amt20 >= down.amt20.quantile(2 / 3)),
        "金流中": gs(down.amt20.between(down.amt20.quantile(1 / 3), down.amt20.quantile(2 / 3))),
        "金流小(後1/3)": gs(down.amt20 < down.amt20.quantile(1 / 3)),
    }
    # 觸發強度劑量四分位(先驗=跌越深越肥,V5/深跌選股同構;預註冊主測=Q4深-Q1淺)
    dq = down.dropna(subset=["drop_mag"]).copy()
    dq["mq"] = pd.qcut(dq.drop_mag.rank(method="first"), 4, labels=["Q1淺", "Q2", "Q3", "Q4深"])
    dose = {}
    for q in ["Q1淺", "Q2", "Q3", "Q4深"]:
        sub = dq[dq.mq == q]
        s = sstat(sub.t10)
        if s:
            s["rng"] = f"{sub.drop_mag.min():.0f}~{sub.drop_mag.max():.0f}%"
            s["upg"] = sub.upgrade.mean() * 100
        dose[q] = s
    # 劑量×金流交叉(使用者胃納疑慮): 深跌組多小票,但肉在有量的
    d2 = down.dropna(subset=["drop_mag", "amt20"]).copy()
    s1, s2 = d2.amt20.quantile(1 / 3), d2.amt20.quantile(2 / 3)
    d2["sz"] = np.where(d2.amt20 < s1, "小", np.where(d2.amt20 < s2, "中", "大"))
    d2["mq"] = pd.qcut(d2.drop_mag.rank(method="first"), 4, labels=["Q1淺", "Q2", "Q3", "Q4深"])
    cross = {}
    for q in ["Q3", "Q4深"]:
        for sz in ["小", "中", "大"]:
            cross[f"{q}×金流{sz}"] = sstat(d2.loc[(d2.mq == q) & (d2.sz == sz), "t10"])
    rule1 = sstat(d2.loc[(d2.drop_mag >= 34) & (d2.amt20 >= 1.0), "t10"])
    rule03 = sstat(d2.loc[(d2.drop_mag >= 34) & (d2.amt20 >= 0.3), "t10"])
    liq_note = {q: d2.loc[d2.mq == q, "amt20"].median() for q in ["Q1淺", "Q2", "Q3", "Q4深"]}
    groups["PE虧損/無值"] = gs(down.loss_pe)
    groups["PE有值"] = gs(~down.loss_pe)
    groups["低價股(價位後1/3)"] = gs(down.close_price < down.close_price.quantile(1 / 3))
    groups["高價股(前1/3)"] = gs(down.close_price >= down.close_price.quantile(2 / 3))
    sub_tests = {}
    for la, ma, mb in [("連續-初犯", down.repeat, ~down.repeat),
                       ("瀕臨處置6+-其餘", down.n30 >= 6, down.n30 < 6),
                       ("題材-非題材", down.theme, ~down.theme),
                       ("劑量Q4深-Q1淺", down.index.isin(dq[dq.mq == "Q4深"].index),
                        down.index.isin(dq[dq.mq == "Q1淺"].index)),
                       ("PE虧損-有值", down.loss_pe, ~down.loss_pe)]:
        ma, mb = pd.Series(ma, index=down.index), pd.Series(mb, index=down.index)
        if ma.sum() >= 15 and mb.sum() >= 15:
            sub_tests[la] = loto_boot(down[ma], down[mb], "t10")

    # 權益曲線(單利Σ)與cap10併發版 — 全變體(使用者2026-07-27要求全部疊圖供判斷)
    dd = down.sort_values("date")
    excl4 = ~dd.triggers.astype(str).str.split(",").map(lambda x: "4" in x)
    m34 = dd.drop_mag >= 34
    rule03_m = excl4 & m34 & (dd.amt20 >= 0.3) & (~dd.loss_pe)
    rule1_m = excl4 & m34 & (dd.amt20 >= 1.0) & (~dd.loss_pe)
    q4_m = dd.drop_mag >= dd.drop_mag.quantile(0.75)
    curves = {}
    for lab, sub in [("全體跌觸發", dd), ("純款1", dd[dd.triggers == "1"]),
                     ("混合觸發", dd[dd.triggers.astype(str).str.contains(",")]),
                     ("劑量Q4深(前25%)", dd[q4_m]),
                     ("規則卡(≥34%∧0.3億∧PE)", dd[rule03_m]),
                     ("規則卡嚴格(≥34%∧1億∧PE)", dd[rule1_m])]:
        eq = sub.t10.cumsum()
        curves[lab] = (sub.date.dt.strftime("%Y-%m-%d").tolist(), eq.round(1).tolist())
    # 圖B: 持有期比較(t10 vs t20, 全體與規則卡)
    curves2 = {}
    for lab, sub, col in [("全體 t10", dd, "t10"), ("全體 t20", dd, "t20"),
                          ("規則卡0.3億 t10", dd[rule03_m], "t10"),
                          ("規則卡0.3億 t20", dd[rule03_m], "t20")]:
        _sc = sub.dropna(subset=[col])
        curves2[lab] = (_sc.date.dt.strftime("%Y-%m-%d").tolist(), _sc[col].cumsum().round(1).tolist())
    open_pos, eq10, val10 = [], [], 0.0
    capd, capv = [], []
    for r in dd.itertuples():
        open_pos = [x for x in open_pos if x > r.ci]
        if len(open_pos) < 10:
            open_pos.append(r.ci + 10)
            val10 += r.t10
            capd.append(r.date.strftime("%Y-%m-%d"))
            capv.append(round(val10, 1))
    curves["cap10併發限制"] = (capd, capv)
    yr_tab = dd.groupby("y").t10.agg(["median", "mean", lambda s: (s > 0).mean() * 100, "count", "sum"])
    yr_tab.columns = ["med", "mean", "win", "n", "sum"]
    eqs = dd.t10.cumsum()
    mdd = (eqs - eqs.cummax()).min()
    print(f"單利equity: Σ={eqs.iloc[-1]:+.0f}pp MDD={mdd:+.0f}pp; cap10版Σ={capv[-1] if capv else 0:+.1f}pp(成交{len(capd)}/{len(dd)})")

    # ---------- HTML ----------
    def row(lab, s, hl=False):
        if s is None:
            return f"<tr><td style='text-align:left'>{lab}</td><td colspan=4>n太少</td></tr>"
        c = "good" if s["med"] > 0 else "bad"
        b = "<b>" if hl else ""
        return (f"<tr><td style='text-align:left'>{b}{lab}{'</b>' if hl else ''}</td>"
                f"<td class='{c}'>{b}{s['med']:+.2f}%{'</b>' if hl else ''}</td>"
                f"<td>{s['mean']:+.2f}%</td><td>{s['win']:.0f}%</td><td>{s['n']:,}</td></tr>")

    grid_rows = "".join(row(f"持有{k}日", grid[k], hl=(k == 10)) for k in KS)
    grp_rows = "".join(row(k, v) for k, v in groups.items())
    dose_rows = "".join(
        f"<tr><td style='text-align:left'>{q}({v['rng']})</td>"
        f"<td class='{'good' if v['med'] > 0 else 'bad'}'>{v['med']:+.2f}%</td>"
        f"<td>{v['mean']:+.2f}%</td><td>{v['win']:.0f}%</td><td>{v['n']}</td><td>{v['upg']:.0f}%</td></tr>"
        for q, v in dose.items() if v)
    cross_rows = "".join(
        f"<tr><td style='text-align:left'>{k}</td>"
        f"<td class='{'good' if v['med'] > 0 else 'bad'}'>{v['med']:+.2f}%</td>"
        f"<td>{v['mean']:+.2f}%</td><td>{v['win']:.0f}%</td><td>{v['n']}</td></tr>"
        for k, v in cross.items() if v)
    liq_txt = " / ".join(f"{q}={v:.2f}億" for q, v in liq_note.items())
    yr_rows = "".join(
        f"<tr><td style='text-align:left'>{y}</td><td class='{'good' if r.med > 0 else 'bad'}'>{r.med:+.2f}%</td>"
        f"<td>{r.win:.0f}%</td><td>{int(r.n)}</td><td>{r['sum']:+.0f}pp</td></tr>"
        for y, r in yr_tab.iterrows())
    st_rows = "".join(
        f"<div class='note'>[{k}] LOTO {v['pos']}/{v['tot']}年正(最壞剔{v['worst_yr']}={v['worst']:+.2f}pp); "
        f"差值bootstrap CI95=[{v['lo']:+.2f},{v['hi']:+.2f}]pp P(≤0)={v['p']:.4f}</div>"
        for k, v in sub_tests.items())
    traces = []
    colors = {"全體跌觸發": "#e8b34b", "純款1": "#7ab8e0", "混合觸發": "#7ec97e",
              "劑量Q4深(前25%)": "#b393d3", "規則卡(≥34%∧0.3億∧PE)": "#f2f2ee",
              "規則卡嚴格(≥34%∧1億∧PE)": "#6bb7e3", "cap10併發限制": "#e06c5a"}
    for lab, (xs, ys) in curves.items():
        traces.append({"x": xs, "y": ys, "name": lab, "mode": "lines",
                       "line": {"color": colors.get(lab, "#8a8878"), "width": 2}})
    traces2 = []
    colors2 = {"全體 t10": "#e8b34b", "全體 t20": "#e06c5a",
               "規則卡0.3億 t10": "#f2f2ee", "規則卡0.3億 t20": "#7ec97e"}
    for lab, (xs, ys) in curves2.items():
        traces2.append({"x": xs, "y": ys, "name": lab, "mode": "lines",
                        "line": {"color": colors2.get(lab, "#8a8878"), "width": 2}})
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>注意股跌觸發完整報告(2026-07-26)</title>
<script src="plotly.min.js"></script><style>
body{{background:#1a1a19;color:#fff;font-family:"Noto Sans TC",sans-serif;margin:24px;max-width:1100px}}
h1{{font-size:20px}} h2{{font-size:15px;color:#c3c2b7;margin-top:28px}}
table{{border-collapse:collapse;font-size:13px;font-variant-numeric:tabular-nums}}
td,th{{border:1px solid #333;padding:5px 12px;text-align:right}} th{{text-align:left}}
.note{{color:#8a8878;font-size:12px;line-height:1.7}}
.good{{color:#7ec97e}}.bad{{color:#e06c5a}}
.card{{background:#20201e;border:1px solid #2c2c2a;border-radius:6px;padding:10px 14px;margin:10px 0;line-height:1.8}}
</style></head><body>
<h1>注意股「跌觸發」完整報告（判決2026-07-20/21・完整版2026-07-26）</h1>
<div class="note">母體=attention表episode化(相鄰≤10交易日=同波取首筆);跌觸發=觸發原因含累積跌幅不含漲幅。
本頁全部數字=次日開盤買→T+k收盤賣、<b>扣0.45%(房規)</b>;0720原判決口徑0.3%的錨重現:中位{anchor['med']:+.2f}%/{anchor['win']:.0f}%/n={anchor['n']}(對照+5.79%/67%/475✓)。
狀態=<b>晉級候選,尚未上板</b>。</div>
<div class="card"><b>⚡headline(0.45%口徑重驗)</b>: 跌觸發 t10 中位 <b class="good">{h['med']:+.2f}%</b>/勝率{h['win']:.0f}%/n={h['n']:,};
LOTO {v['pos']}/{v['tot']}年為正(最壞剔{v['worst_yr']}仍{v['worst']:+.2f}pp);對其餘組差值CI95=[{v['lo']:+.2f},{v['hi']:+.2f}] P={v['p']:.4f}——雙關卡續過。</div>
<h2>一、持有期網格（為什麼10日）</h2>
<table><tr><th>持有</th><th>中位</th><th>均值</th><th>勝率</th><th>n</th></tr>{grid_rows}</table>
<h2>二、分組刨析（t10）</h2>
<table><tr><th>分組</th><th>中位</th><th>均值</th><th>勝率</th><th>n</th></tr>{grp_rows}</table>
{st_rows}
<div class="note">「30日6次+」=升級處置標準道(10日6次/30日12次)的事前代理=「準備進處置」組;「事後真升級」為ex-post描述,不可當進場條件。</div>
<h2>二b、觸發強度劑量（公告原文解析「累積跌幅達XX%」,事前可知;先驗=跌越深越肥）</h2>
<table><tr><th>劑量四分位(跌幅範圍)</th><th>中位</th><th>均值</th><th>勝率</th><th>n</th><th>事後升級處置率</th></tr>{dose_rows}</table>
<h2>二c、劑量×金流交叉（胃納量體檢:深跌組六成是&lt;0.3億小票,但肉在有量的）</h2>
<table><tr><th>格(金流三分位切點{s1:.2f}/{s2:.2f}億)</th><th>中位</th><th>均值</th><th>勝率</th><th>n</th></tr>{cross_rows}</table>
<div class="card"><b>⚡候選規則卡（三刀探索格,待live驗證後上板）</b>: 跌觸發∧排除款4∧<b>跌幅≥34%</b>∧<b>金流≥1億</b>
→ t10中位 <b class="good">{rule1['med']:+.2f}%</b>/勝率{rule1['win']:.0f}%/n={rule1['n']}(約5件/年);
放寬金流≥0.3億 → <b class="good">{rule03['med']:+.2f}%</b>/{rule03['win']:.0f}%/n={rule03['n']}(約11件/年)。
劑量組金流中位: {liq_txt}。amt20=公告<b>前</b>20日常態量(公告後必爆量=保守估);流動性濾網是加分不是成本(有量=有人接非殭屍票)。
<span style="color:#e06c5a">⚠警語: 此格由跌觸發→劑量→金流三刀互動切出+2026年整體負年份,證據等級=候選;先掛觀察清單live驗證。</span></div>
<h2>三、權益曲線A：全變體比較（單利Σ,每筆1單位;點圖例可開關線;紅線=cap10併發限制較貼實戰）</h2>
<div id="eq" style="height:440px"></div>
<div class="note">判讀:規則卡線(白/藍)斜率最陡但事件稀(n=91/41);劑量Q4深(紫)介於中間;cap10(紅)=全體訊號在10檔併發上限下的實戰版。注意各線事件數不同,比「斜率與回撤形狀」不比絕對高度。</div>
<h2>三b、權益曲線B：持有期比較（t10 vs t20）</h2>
<div id="eq2" style="height:400px"></div>
<h2>四、逐年表（t10）</h2>
<table><tr><th>年</th><th>中位</th><th>勝率</th><th>n</th><th>年Σ</th></tr>{yr_rows}</table>
<div class="note">單利Σ={eqs.iloc[-1]:+.0f}pp、equity MDD={mdd:+.0f}pp;cap10版Σ={capv[-1] if capv else 0:+.1f}pp(成交{len(capd)}/{len(dd)}筆)。
規則卡:跌觸發次日開盤買/持10日/排除款4/混合觸發加分;與處置V4同機制家族不同事件批=分散來源;上板待裁示。</div>
<script>
const LAYOUT={{paper_bgcolor:"#1a1a19",plot_bgcolor:"#1e1e1c",font:{{color:"#c3c2b7"}},margin:{{t:20}},
xaxis:{{gridcolor:"#2b2b29"}},yaxis:{{gridcolor:"#2b2b29",title:"累計pp"}},legend:{{orientation:"h"}}}};
Plotly.newPlot("eq",{json.dumps(traces)},LAYOUT,{{displayModeBar:false}});
Plotly.newPlot("eq2",{json.dumps(traces2)},LAYOUT,{{displayModeBar:false}});
</script>
</body></html>"""
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"輸出 {OUT}")


if __name__ == "__main__":
    main()
