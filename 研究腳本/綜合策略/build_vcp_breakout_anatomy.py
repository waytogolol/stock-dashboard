# -*- coding: utf-8 -*-
"""盤整突破解剖考卷: 型態(緊盤整×波動擴張×量能)×背後因子(營收/財報/市值/淨值/題材)(2026-08-07)。

使用者假說原文: 「股價盤整→波動突然放大→突破小放量→接著走了很長一段;這種背後營收?財報(毛利/
營業利益率/稅後/其他)?市值?每股淨值?產業共振?是否能歸納出不錯的交易策略?」=經典VCP
(volatility contraction pattern)型態+基本面解剖,兩段式考卷。

═══ 設計(預先註冊) ═══
事件母體: 90日獨立突破(收盤破90日高且前20日未曾破,newhigh卷口徑),池=20日均額>=0.3億,2015起;
進場=次日收盤(可執行),outcome=k20/40/60/120 demean(減TAIEX)+「長波段」判準=k120+右尾率(k120>+30%占比)。
A段 型態三維(全部只用突破日已知資訊):
  盤整緊度: 突破前60日(不含當日)收盤區間寬=(max-min)/min → 緊<25%/中25-50%/鬆>50%
  波動擴張: 近5日報酬std/前60日std >= 1.5 = 「波動突然放大」flag
  量比: 突破日成交值/前20日均值 → 溫和<1.5/小放量1.5~3/放量3~6/爆量>6
  使用者型態=緊盤整×波動擴張×小放量 vs 突破全體/爆量對照。
B段 背後因子(突破日零前視逐一檢定,各因子在「突破事件內」的分割):
  營收R1(最近兩公布月皆創12月高)/季YoY>20%;毛利率QoQ>0/營益率QoQ>0/淨利率QoQ>0(avail_date口徑);
  市值(shares×close): <100億/100-500億/>500億;P/B=價/每股淨值((資產-負債)/股本): <1.5/1.5-3/>3;
  題材共振=題材成員且題材20日demean>0。
C段 合成: 使用者型態×B段最強因子逐步疊加,vs雙新高(k40+8.90)/三重門檻(+3.84)比大小;
  多重比較誠實(A3×4+B~10格,判讀靠k40/60/120跨窗一致+逐年)。
用法: python 研究腳本/綜合策略/build_vcp_breakout_anatomy.py  (從根目錄執行,鐵律)
產出: 研究報告/research_vcp_breakout_anatomy.html + console
"""
import sqlite3
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

DB = "capital_flow.db"
OUT = "研究報告/research_vcp_breakout_anatomy.html"
START = "2015-01-01"
LIQ_MIN = 0.3e8
FRESH_GAP = 20
K_LIST = [20, 40, 60, 120]
BUFFER_DAYS = 5
STATUTORY = {1: (5, 15, 0), 2: (8, 14, 0), 3: (11, 14, 0), 4: (3, 31, 1)}
rng = np.random.default_rng(20260807)


def avail_date(qe):
    q = (qe.month - 1) // 3 + 1
    m, d, yoff = STATUTORY[q]
    return pd.Timestamp(qe.year + yoff, m, d) + pd.Timedelta(days=BUFFER_DAYS)


def main():
    conn = sqlite3.connect(DB, timeout=60)
    px = pd.read_sql("SELECT code,date,close,money FROM fm_daily_price "
                     "WHERE date>='2013-06-01' AND close>0 AND money>0", conn)
    tai = pd.read_sql("SELECT date,close FROM index_daily WHERE market='TAIEX' "
                      "AND date>='2013-06-01' ORDER BY date", conn)
    rev = pd.read_sql("SELECT code, date, revenue FROM fm_month_rev", conn, parse_dates=["date"])
    fin = pd.read_sql("SELECT code, date, gross_margin, operating_margin, net_margin "
                      "FROM tw_quarterly_financials_history", conn, parse_dates=["date"])
    bal = pd.read_sql("SELECT code, date, total_assets, liabilities "
                      "FROM tw_quarterly_balance_cashflow_history", conn, parse_dates=["date"])
    cap = pd.read_sql("SELECT code, date, shares FROM capital ORDER BY code, date",
                      conn, parse_dates=["date"])
    theme_mem = {}
    for r in conn.execute("select code, main_group from classification where country='台'"):
        theme_mem.setdefault(r[0], []).append(r[1])
    conn.close()

    C = px.pivot_table(index="date", columns="code", values="close", aggfunc="first").sort_index()
    MN = px.pivot_table(index="date", columns="code", values="money", aggfunc="first").sort_index()
    tai = tai.set_index("date")["close"]
    dates = list(C.index)
    t_dates = np.array(dates)
    start_i = int(np.searchsorted(t_dates, START))
    liq_ok = (MN.rolling(20, min_periods=15).mean().shift(1) >= LIQ_MIN)
    Cf = C.ffill(limit=5)
    tai_f = tai.reindex(C.index).ffill()
    ret1 = C.pct_change(fill_method=None)

    # 型態素材
    rng60_hi = C.shift(1).rolling(60, min_periods=48).max()
    rng60_lo = C.shift(1).rolling(60, min_periods=48).min()
    tight = (rng60_hi - rng60_lo) / rng60_lo                        # 盤整區間寬(不含突破日)
    std5 = ret1.rolling(5, min_periods=5).std()
    std60 = ret1.shift(5).rolling(60, min_periods=40).std()
    volex = std5 / std60                                             # 波動擴張比
    volx = MN / MN.shift(1).rolling(20, min_periods=15).mean()       # 量比(成交值)

    # 90日獨立突破
    rmax90 = C.rolling(90, min_periods=72).max()
    is_hi = (C >= rmax90 * 0.9999) & C.notna()
    hi_recent = is_hi.shift(1).rolling(FRESH_GAP, min_periods=1).max()

    # 營收R1逐日 + 季YoY
    rev_w = rev.pivot_table(index="date", columns="code", values="revenue", aggfunc="first").sort_index()
    hi_rev = (rev_w >= rev_w.rolling(12, min_periods=12).max()) & rev_w.notna()
    hi2 = hi_rev & hi_rev.shift(1)
    r3 = rev_w.rolling(3).sum()
    ryoy = r3 / r3.shift(12) - 1                                      # 近3月合計YoY
    # ⚠公布錨=次月12日(2026-08-07修正前視bug: 原版m+12天提早一個月)
    pub_idx = [(m + pd.DateOffset(months=1) + pd.Timedelta(days=11)).strftime("%Y-%m-%d")
               for m in rev_w.index]
    hi2_pub = hi2.copy()
    hi2_pub.index = pub_idx
    ryoy_pub = ryoy.copy()
    ryoy_pub.index = pub_idx
    all_idx = sorted(set(pub_idx) | set(dates))
    R1_daily = hi2_pub.reindex(all_idx).ffill().reindex(dates)
    RYOY_daily = ryoy_pub.reindex(all_idx).ffill().reindex(dates)

    # 財報因子 per code(avail排序): gm/om/nm chg + 每股淨值
    fin2 = fin.merge(bal, on=["code", "date"], how="outer")
    capmap = {c: (g.date.values, g.shares.values) for c, g in cap.groupby("code")}
    fundmap = {}
    for code, g in fin2.groupby("code"):
        g = g.sort_values("date")
        qidx = pd.PeriodIndex(g.date, freq="Q")
        g = g.set_index(qidx)
        g = g[~g.index.duplicated(keep="first")]
        full = pd.period_range(g.index.min(), g.index.max(), freq="Q")
        g = g.reindex(full)
        chgs = {}
        for col, key in (("gross_margin", "gm"), ("operating_margin", "om"), ("net_margin", "nm")):
            lv = g[col] * 100
            chgs[key] = (lv - lv.shift(1)).values
        bv = (pd.to_numeric(g.total_assets, errors="coerce")
              - pd.to_numeric(g.liabilities, errors="coerce")).values      # 淨值(元)
        av = np.array([np.datetime64(avail_date(p.end_time.normalize())) for p in g.index])
        ok = g.gross_margin.notna().values | pd.notna(bv)
        fundmap[code] = (av[ok], chgs["gm"][ok], chgs["om"][ok], chgs["nm"][ok], bv[ok])

    def fund_at(code, d):
        fm = fundmap.get(code)
        if fm is None:
            return (np.nan,) * 4
        k = int(np.searchsorted(fm[0], np.datetime64(d), side="right")) - 1
        if k < 0 or (pd.Timestamp(d) - pd.Timestamp(fm[0][k])).days > 200:
            return (np.nan,) * 4
        return fm[1][k], fm[2][k], fm[3][k], fm[4][k]

    # 題材20日demean動能(題材層)
    tai_r20 = C / C.shift(20) - 1
    tai20 = tai / tai.shift(20) - 1
    theme_sets = {}
    for code, gs in theme_mem.items():
        for t in gs:
            theme_sets.setdefault(t, []).append(code)
    theme_mom = {}
    for t, mem in theme_sets.items():
        cols = [c for c in mem if c in C.columns]
        if len(cols) >= 2:
            theme_mom[t] = tai_r20[cols].mean(axis=1) - tai20.reindex(C.index)

    # ---------- 事件建構 ----------
    events = []
    for i in range(start_i, len(dates) - 2):
        row = is_hi.iloc[i].values & (~hi_recent.iloc[i].values.astype(bool)) & liq_ok.iloc[i].values
        if not row.any():
            continue
        d = dates[i]
        for ci in np.where(row)[0]:
            code = C.columns[ci]
            e_i = i + 1
            if e_i + min(K_LIST) >= len(dates):
                continue
            e1 = C.iat[e_i, ci]
            if pd.isna(e1) or e1 <= 0:
                continue
            rec = {"code": code, "d": d, "m": d[:7], "year": d[:4],
                   "tight": tight.iat[i, ci], "volex": volex.iat[i, ci], "volx": volx.iat[i, ci]}
            ok_k = 0
            for k in K_LIST:
                if e_i + k < len(dates):
                    x = Cf.iat[e_i + k, ci]
                    if pd.notna(x):
                        rec[f"dm{k}"] = (x / e1 - 1) - (tai_f.iloc[e_i + k] / tai_f.iloc[e_i] - 1)
                        ok_k += 1
            if ok_k < 2 or pd.isna(rec["tight"]):
                continue
            # B段因子
            rec["r1"] = bool(R1_daily.iloc[i].get(code, False)) if code in R1_daily.columns else False
            ry = RYOY_daily.iloc[i].get(code, np.nan) if code in RYOY_daily.columns else np.nan
            rec["ryoy20"] = bool(pd.notna(ry) and ry >= 0.2)
            gm, om, nm, bv = fund_at(code, d)
            rec["gm"], rec["om"], rec["nm"] = gm, om, nm
            cp = capmap.get(code)
            mcap = pb = np.nan
            if cp is not None:
                j = int(np.searchsorted(cp[0], np.datetime64(d), side="right")) - 1
                if j >= 0 and pd.notna(cp[1][j]) and cp[1][j] > 0:
                    mcap = float(cp[1][j]) * C.iat[i, ci] / 1e8          # 億
                    if pd.notna(bv) and bv > 0:
                        pb = float(cp[1][j]) * C.iat[i, ci] / bv          # 市值/淨值=P/B
            rec["mcap"], rec["pb"] = mcap, pb
            gs = theme_mem.get(code, [])
            tm = np.nan
            for t in gs:
                if t in theme_mom:
                    v = theme_mom[t].get(d, np.nan)
                    if pd.notna(v):
                        tm = max(tm, v) if pd.notna(tm) else v
            rec["theme"] = len(gs) > 0
            rec["tmom_pos"] = bool(pd.notna(tm) and tm > 0)
            events.append(rec)
    E = pd.DataFrame(events)
    print(f"[panel] 90日獨立突破{len(E):,}筆({E.d.min()}~{E.d.max()}); "
          f"k120可用{E.dm120.notna().sum():,}")

    def boot(vals, ms, n_iter=800):
        v = pd.DataFrame({"v": vals, "m": ms}).dropna()
        if len(v) < 40 or v.m.nunique() < 8:
            return None
        grp = {k: g.v.values for k, g in v.groupby("m")}
        keys = list(grp)
        means = [np.mean(np.concatenate([grp[k] for k in rng.choice(keys, len(keys))]))
                 for _ in range(n_iter)]
        lo, hi = np.percentile(means, [2.5, 97.5])
        return {"mean": float(v.v.mean()), "lo": float(lo), "hi": float(hi),
                "sig": bool(lo > 0 or hi < 0)}

    def line(sub, lab, out):
        if len(sub) < 60:
            print(f"  {lab:<32} n={len(sub)} 不足")
            return
        r = {"lab": lab, "n": len(sub)}
        for k in K_LIST:
            b = boot(sub[f"dm{k}"].values, sub.m.values)
            v = sub[f"dm{k}"].dropna()
            r[k] = {"mean": v.mean() * 100, "b": b}
        v120 = sub["dm120"].dropna()
        w = v120[v120 > 0]
        l = v120[v120 <= 0]
        r["tail"] = (v120 > 0.30).mean() * 100 if len(v120) else np.nan
        r["win"] = len(w) / len(v120) * 100 if len(v120) else np.nan
        r["wl"] = (w.mean() / abs(l.mean())) if len(w) and len(l) else np.nan
        y = sub.groupby("year")["dm60"].mean()
        r["yr"] = f"{int((y > 0).sum())}/{len(y)}"
        out.append(r)
        f = lambda k: (f"{r[k]['mean']:+.2f}"
                       + (f"[{r[k]['b']['lo'] * 100:+.1f},{r[k]['b']['hi'] * 100:+.1f}]{'✓' if r[k]['b']['sig'] else ''}"
                          if r[k]["b"] else ""))
        print(f"  {lab:<32} n={r['n']:>6,} k20:{f(20)} k40:{f(40)} k60:{f(60)} k120:{f(120)} "
              f"右尾{r['tail']:.0f}% 勝率{r['win']:.0f}% 賺賠{r['wl']:.2f} 逐年60:{r['yr']}")

    print("\n" + "=" * 110, "\nA) 型態層(90日獨立突破內,demean%)")
    A = []
    line(E, "突破全體(基準)", A)
    tE = E[E.tight.notna()]
    line(tE[tE.tight < 0.25], "緊盤整(<25%)", A)
    line(tE[(tE.tight >= 0.25) & (tE.tight < 0.5)], "中盤整(25-50%)", A)
    line(tE[tE.tight >= 0.5], "鬆盤整(>50%)", A)
    line(E[E.volex >= 1.5], "波動擴張(std5/std60>=1.5)", A)
    line(E[E.volx < 1.5], "量比<1.5溫和", A)
    line(E[(E.volx >= 1.5) & (E.volx < 3)], "量比1.5-3(小放量)", A)
    line(E[(E.volx >= 3) & (E.volx < 6)], "量比3-6放量", A)
    line(E[E.volx >= 6], "量比>6爆量", A)
    user_mask = (E.tight < 0.25) & (E.volex >= 1.5) & (E.volx >= 1.5) & (E.volx < 3)
    line(E[user_mask], "★使用者型態(緊×擴張×小放量)", A)
    line(E[(E.tight < 0.25) & (E.volx >= 1.5) & (E.volx < 3)], "緊×小放量(不要求擴張)", A)

    print("\nB) 背後因子(突破事件內逐一分割)")
    B = []
    line(E[E.r1], "營收R1(兩月連創高)", B)
    line(E[E.ryoy20], "營收近3月YoY>20%", B)
    line(E[E.gm > 0], "毛利率QoQ改善", B)
    line(E[E.om > 0], "營益率QoQ改善", B)
    line(E[E.nm > 0], "淨利率QoQ改善", B)
    line(E[E.gm.isna()], "無財報資料(排除規則複驗)", B)
    line(E[E.mcap < 100], "市值<100億", B)
    line(E[(E.mcap >= 100) & (E.mcap < 500)], "市值100-500億", B)
    line(E[E.mcap >= 500], "市值>500億", B)
    line(E[E.pb < 1.5], "P/B<1.5", B)
    line(E[(E.pb >= 1.5) & (E.pb < 3)], "P/B 1.5-3", B)
    line(E[E.pb >= 3], "P/B>3", B)
    line(E[E.theme & E.tmom_pos], "題材成員×題材20日動能正(共振)", B)
    line(E[E.theme & (~E.tmom_pos)], "題材成員×題材動能負", B)
    line(E[~E.theme], "非題材成員", B)

    print("\nC) 合成(使用者型態逐步疊背後因子)")
    Cc = []
    line(E[user_mask & E.r1], "★型態×營收R1", Cc)
    line(E[user_mask & (E.gm > 0)], "★型態×毛利改善", Cc)
    line(E[user_mask & E.theme & E.tmom_pos], "★型態×題材共振", Cc)
    line(E[(E.tight < 0.25) & (E.volx < 3) & E.r1 & E.theme], "緊盤整×量<3×R1×題材", Cc)

    # ---------- HTML ----------
    CSS = """
body{background:#1a1a19;color:#fff;font-family:"Noto Sans TC",sans-serif;margin:24px;max-width:1200px}
h1{font-size:20px} h2{font-size:15px;color:#c3c2b7;margin-top:30px;border-bottom:1px solid #333;padding-bottom:4px}
table{border-collapse:collapse;font-size:12.5px;font-variant-numeric:tabular-nums;margin:8px 0}
td,th{border:1px solid #333;padding:4px 8px;text-align:right} th{text-align:left;color:#c3c2b7}
.note{color:#8a8878;font-size:12.5px;line-height:1.8} .good{color:#7ec97e} .bad{color:#e06c5a}
.hl{background:#2b3a2b}
ul{margin:4px 0;padding-left:20px;font-size:12.5px;color:#ccc;line-height:1.7}
.verdict{font-size:13px;font-weight:bold;padding:6px 10px;border-radius:4px;display:inline-block;margin:4px 0}
.v-good{background:#243b24;color:#7ec97e} .v-bad{background:#3b2420;color:#e06c5a}
.v-warn{background:#3b3420;color:#c3a55a}
.scroll{overflow-x:auto}
"""

    def tbl(rows, hl=("★",)):
        h = ("<div class='scroll'><table><tr><th>組</th><th>n</th>"
             + "".join(f"<th>k{k} demean/CI</th>" for k in K_LIST)
             + "<th>k120右尾(>30%)</th><th>k120勝率/賺賠</th><th>逐年60</th></tr>")
        for r in rows:
            cells = ""
            for k in K_LIST:
                s = r[k]
                ci = (f"<br><span style='color:#777;font-size:10.5px'>[{s['b']['lo'] * 100:+.1f},"
                      f"{s['b']['hi'] * 100:+.1f}]{'✓' if s['b']['sig'] else ''}</span>" if s["b"] else "")
                cells += f"<td>{s['mean']:+.2f}%{ci}</td>"
            mk = " class='hl'" if any(x in r["lab"] for x in hl) else ""
            h += (f"<tr{mk}><th>{r['lab']}</th><td>{r['n']:,}</td>{cells}"
                  f"<td>{r['tail']:.0f}%</td><td>{r['win']:.0f}%/{r['wl']:.2f}</td><td>{r['yr']}</td></tr>")
        return h + "</table></div>"

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>盤整突破解剖(2026-08-07)</title><style>{CSS}</style></head><body>
<h1>🔬 盤整突破解剖: VCP型態 × 背後因子</h1>
<div class="note">使用者假說:「盤整→波動突然放大→突破小放量→走很長一段;背後營收/財報/市值/淨值/
題材共振能否歸納策略?」。事件=90日獨立突破(前20日無新高),池=0.3億,2015起,{len(E):,}筆;
進場=次日收盤,outcome=k20/40/60/120 demean+右尾率(k120>+30%);月群bootstrap。
盤整緊度=前60日收盤區間寬;波動擴張=std5/std60>=1.5;量比=突破日成交值/20日均值。</div>
<h2>A) 型態層</h2>
{tbl(A)}
<h2>B) 背後因子(突破事件內)</h2>
{tbl(B)}
<h2>C) 合成</h2>
{tbl(Cc)}
<h2>⚖️ 判決(2026-08-07首輪)</h2>
<ul>
<li><span class="verdict v-bad">①型態層(使用者描述的VCP三要素)在台股長窗全滅、甚至反向</span>
緊盤整(&lt;25%)k120=<b>-2.09%✓為負</b>;突破前波動突然放大k120=<b>-2.36%✓為負</b>;
小放量(量比1.5-3)k120-0.62含0無結構(量能最好的是3-6中度放量+0.76,仍含0);
★三要素合體(緊×擴張×小放量)k120=-3.64%/右尾僅7%/勝率34%——教科書VCP(美式)在台股90日突破上
不成立;反而<b>鬆盤整(區間>50%)k120+4.94最高</b>(寬幅震盪=充分換手洗盤?緊盤整+小量=控盤/
冷門假突破?機制待考)。</li>
<li><span class="verdict v-good">②「背後因子」=策略本體(使用者第二問才是對的問題)</span>
突破後「走很長一段」由基本面與題材決定: <b>題材共振(題材成員×題材20日動能正)k120+9.17%✓/
右尾19%/賺賠2.26/逐年12/12全正</b>=全卷最強;營收R1(兩月連創)k120+6.10%✓(已修正營收公布錨
前視bug後的數字);毛利/營益/淨利QoQ改善k120+4.2~4.9%✓全過;<b>無財報資料k120-10.41%✓/勝率30%
(第四次重現=鐵排除規則)</b>;非題材成員k120-7.62%✓。<b>市值無結構(全含0)、P/B僅弱結構</b>
(&lt;1.5的k120+2.98邊緣✓)=使用者清單中這兩項可以放下。</li>
<li><span class="verdict v-warn">③合成: 型態把好因子拖下水</span> 型態×毛利改善k120-3.86/
型態×題材共振+3.61含0(vs題材共振單獨+9.17)——疊上緊盤整/小放量條件後反而變差,
<b>不要用型態當濾網</b>。</li>
<li><b>④歸納的交易策略(回答使用者原問)</b>: 「會走很長一段」的90日突破長相=
<b>有財報的題材成員+題材正在共振+營收兩月連創(+毛利改善加分)</b>,盤整形狀/量能不用看——
這正好收斂回既有訊號家族(雙新高/三重門檻/題材共振),背後因子清單裡真正新的增量資訊=
「題材20日動能正」這個共振濾網(k120層把+3.58拉到+9.17,值得加進統一掃描器)。</li>
<li><b>⑤誠實保留</b>: 緊/鬆盤整與流動性/市值可能糾纏(冷門股天生緊,未做正交化);★型態n=270小;
k120未還原除權息(長窗保守);多重比較~25格,判讀靠跨窗一致+逐年。</li>
</ul>
<h2>已知限制</h2>
<div class="note">①A3維×B10格×C=多重比較,判讀靠跨窗(k40/60/120)一致+逐年,單格CI僅參考;
②除權息未還原(k120長窗保守偏誤大);③每股淨值=(資產-負債)/股本,未扣特別股/少數股權(近似);
④量比用成交值非股數;⑤題材共振=題材成員且題材20日demean>0(取該股所屬題材最大值);
⑥「長波段」以k120+右尾率代理,未做逐筆最大漲幅路徑。</div>
<div class="note">維運: python 研究腳本/綜合策略/build_vcp_breakout_anatomy.py(從根目錄執行)。
母卷: build_newhigh_breakout_swing.py(突破基準)、build_dual_newhigh_matrix.py(雙新高)。</div>
</body></html>"""
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n[report] 已輸出 {OUT}")


if __name__ == "__main__":
    main()
