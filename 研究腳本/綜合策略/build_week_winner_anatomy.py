# -*- coding: utf-8 -*-
"""一週大賺股逆向工程 + 拉回進場規則對決(2026-08-08,使用者指定方法論:先定義結果再挖特徵)。

使用者目標: **持有一週(5交易日)、勝率高、賺賠比>=1.5**。專案現況缺口=既有活口全是20-40日中慢線,
週級動能是勝率46-49%的肥右尾(與目標相反)。本卷從零開始建這條線。

═══ 兩階段設計(預先註冊) ═══
【階段一 逆向工程(不預設型態)】
  母體: 20日均額>=0.3億流動池;抽樣=每5個交易日一次(fwd5窗不重疊,避免自相關灌水)。
  結果變數: fwd5 = **次日收盤進場 → 第5個交易日收盤出場**(可執行口徑,零前視)。
  贏家=同日橫斷面fwd5前5%;輸家=後5%;對照=同日全池。
  特徵(全部t日收盤已知): ①位置(距20/60/126日高) ②近期動能(ret5/ret20) ③當日K棒(實體/上下影)
  ④型態史(近20日有無漲停/長紅、距最近長紅天數) ⑤拉回結構(從20日高回檔幅度、距5/10/20日均線)
  ⑥量能(當日量/20日均量、5日均量/20日均量、20日均額=熱門度) ⑦波動(20日年化) ⑧題材(成員/題材20日動能)
  ⑨營收(兩月連創) ⑩籌碼(千張大戶4週變化)。
  輸出=贏家畫像(特徵中位數 vs 全池)+每個特徵的同日五分位fwd5階梯(看單調性,比AUC好讀)。
【階段二 規則對決(把畫像翻成可執行策略)】
  R1長紅/漲停後拉回到5日線 / R2新高後淺回(<=3%) / R3深回檔接刀(>=8%) / R4純追高(對照,不等拉回)
  / R5題材成員×拉回 / R6熱門股(均額>=3億)×拉回。每條: 勝率/賺賠比/期望值/逐年/扣0.3%與0.5%成本。
  **判準: 賺賠比>=1.5 且 勝率>=50% 且 成本後期望值>0 才算達標(使用者目標,預先註冊)。**
用法: python 研究腳本/綜合策略/build_week_winner_anatomy.py  (從根目錄執行,鐵律)
產出: 研究報告/research_week_winner.html + console
"""
import sys
import sqlite3

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

DB = "capital_flow.db"
OUT = "研究報告/research_week_winner.html"
LIQ_MIN = 0.3e8
SAMPLE_EVERY = 5           # 每5交易日抽樣(fwd5不重疊)
HOLD = 5
rng = np.random.default_rng(20260808)


def main():
    conn = sqlite3.connect(DB, timeout=120)
    px = pd.read_sql("SELECT code,date,open,high,low,close,volume,money FROM fm_daily_price "
                     "WHERE date>='2014-06-01' AND close>0 AND money>0 AND open>0", conn)
    tai = pd.read_sql("SELECT date,close FROM index_daily WHERE market='TAIEX' AND date>='2014-06-01' "
                      "ORDER BY date", conn)
    rev = pd.read_sql("SELECT code,date,revenue FROM fm_month_rev", conn, parse_dates=["date"])
    td = pd.read_sql("SELECT code,date,p1000 FROM tdcc_weekly", conn, parse_dates=["date"])
    cls = pd.read_sql("SELECT code,main_group FROM classification WHERE country='台'", conn)
    conn.close()

    piv = lambda c: px.pivot_table(index="date", columns="code", values=c, aggfunc="first").sort_index()
    C, O, H, L, V, MN = piv("close"), piv("open"), piv("high"), piv("low"), piv("volume"), piv("money")
    Cf = C.ffill(limit=3)
    tai = tai.set_index("date")["close"].reindex(C.index).ffill()
    dates = list(C.index)
    print(f"[panel] {C.shape[0]}日×{C.shape[1]}檔 {dates[0]}~{dates[-1]}")

    # ---- 特徵矩陣(全部t日收盤可知) ----
    F = {}
    F["dist20"] = (C / C.rolling(20, min_periods=15).max() - 1) * 100
    F["dist60"] = (C / C.rolling(60, min_periods=45).max() - 1) * 100
    F["dist126"] = (C / C.rolling(126, min_periods=100).max() - 1) * 100
    F["ret5"] = (C / C.shift(5) - 1) * 100
    F["ret20"] = (C / C.shift(20) - 1) * 100
    F["body"] = (C / O - 1) * 100
    rng_hl = (H - L).replace(0, np.nan)
    F["upwick"] = ((H - np.maximum(C, O)) / rng_hl * 100)
    F["lowick"] = ((np.minimum(C, O) - L) / rng_hl * 100)
    chg = C.pct_change() * 100
    limitup = (chg >= 9.0)
    longbar = (chg >= 5.0)
    F["n_limitup20"] = limitup.rolling(20, min_periods=10).sum()
    F["n_longbar20"] = longbar.rolling(20, min_periods=10).sum()
    # 距最近長紅天數(0=今天就是)
    idx_arr = np.arange(len(C))[:, None] * np.ones((1, C.shape[1]))
    last_lb = pd.DataFrame(np.where(longbar.values, idx_arr, np.nan), index=C.index, columns=C.columns).ffill()
    F["days_since_longbar"] = pd.DataFrame(idx_arr, index=C.index, columns=C.columns) - last_lb
    ma5, ma10, ma20 = (C.rolling(w, min_periods=w - 2).mean() for w in (5, 10, 20))
    F["ma5_dist"] = (C / ma5 - 1) * 100
    F["ma10_dist"] = (C / ma10 - 1) * 100
    F["ma20_dist"] = (C / ma20 - 1) * 100
    v20 = V.rolling(20, min_periods=15).mean()
    F["vol_ratio"] = V / v20
    F["vol_trend"] = V.rolling(5, min_periods=4).mean() / v20
    F["money20"] = MN.rolling(20, min_periods=15).mean() / 1e8      # 億元(熱門度)
    F["vol20_ann"] = C.pct_change().rolling(20, min_periods=15).std() * np.sqrt(252) * 100
    F["amp20"] = ((H - L) / C).rolling(20, min_periods=15).mean() * 100

    theme_of = cls.groupby("code").main_group.first().to_dict()
    is_theme = pd.DataFrame(np.tile([[1.0 if c in theme_of else 0.0 for c in C.columns]], (len(C), 1)),
                            index=C.index, columns=C.columns)
    F["is_theme"] = is_theme
    tm = {}
    for t in set(theme_of.values()):
        mem = [c for c in theme_of if theme_of[c] == t and c in C.columns]
        if len(mem) >= 2:
            s = C[mem].mean(axis=1)
            tm[t] = (s / s.shift(20) - 1) * 100
    theme_mom = pd.DataFrame(index=C.index, columns=C.columns, dtype=float)
    for t, s in tm.items():
        mem = [c for c in theme_of if theme_of[c] == t and c in C.columns]
        for c in mem:
            theme_mom[c] = s
    F["theme_mom"] = theme_mom

    rev_w = rev.pivot_table(index="date", columns="code", values="revenue", aggfunc="first").sort_index()
    hi_rev = ((rev_w >= rev_w.rolling(12, min_periods=12).max()) & rev_w.notna()).astype(float)
    r1_m = (hi_rev * hi_rev.shift(1))                       # 兩月連創
    r1_daily = r1_m.copy()
    r1_daily.index = [(m + pd.DateOffset(months=1) + pd.Timedelta(days=11)) for m in r1_m.index]
    F["rev_r1"] = r1_daily.reindex(pd.to_datetime(C.index), method="ffill").set_axis(C.index).reindex(
        columns=C.columns)
    td_w = td.pivot_table(index="date", columns="code", values="p1000", aggfunc="first").sort_index()
    d4w = (td_w - td_w.shift(4))
    F["d4w"] = d4w.reindex(pd.to_datetime(C.index), method="ffill").set_axis(C.index).reindex(columns=C.columns)

    # ---- 結果變數: 次日收盤進 → +5日收盤出 ----
    entry = Cf.shift(-1)
    exit_ = Cf.shift(-(1 + HOLD))
    fwd5 = (exit_ / entry - 1) * 100
    tai_e = tai.shift(-1)
    tai_x = tai.shift(-(1 + HOLD))
    fwd5_bench = (tai_x / tai_e - 1) * 100
    fwd5_dm = fwd5.sub(fwd5_bench, axis=0)

    pool = (MN.rolling(20, min_periods=15).mean().shift(1) >= LIQ_MIN) & C.notna() & entry.notna() & exit_.notna()
    start_i = int(np.searchsorted(np.array(dates), "2015-01-01"))
    samp = list(range(start_i, len(dates) - HOLD - 2, SAMPLE_EVERY))
    print(f"[sample] 抽樣日{len(samp)}個(每{SAMPLE_EVERY}交易日)")

    recs = []
    feat_names = list(F.keys())
    for i in samp:
        m = pool.iloc[i].values
        if m.sum() < 50:
            continue
        codes = C.columns[m]
        d = dates[i]
        row = {"d": d, "ym": d[:7], "yr": d[:4], "code": codes,
               "fwd5": fwd5.iloc[i].values[m], "fwd5dm": fwd5_dm.iloc[i].values[m]}
        for fn in feat_names:
            row[fn] = F[fn].iloc[i].values[m]
        recs.append(row)
    D = pd.concat([pd.DataFrame({k: (v if isinstance(v, np.ndarray) else [v] * len(r["code"]))
                                 for k, v in r.items()}) for r in recs], ignore_index=True)
    D = D.dropna(subset=["fwd5"])
    print(f"[data] 樣本{len(D):,}筆 ({D.d.nunique()}個抽樣日); "
          f"fwd5均{D.fwd5.mean():+.2f}% 中位{D.fwd5.median():+.2f}% 勝率{(D.fwd5 > 0).mean() * 100:.0f}%")

    # ---- 階段一: 贏家畫像 ----
    D["rank"] = D.groupby("d").fwd5.rank(pct=True)
    win = D[D["rank"] >= 0.95]
    lose = D[D["rank"] <= 0.05]
    print(f"\n階段一 贏家畫像(同日fwd5前5%,n={len(win):,}; 平均報酬{win.fwd5.mean():+.1f}%) "
          f"vs 輸家(後5%,{lose.fwd5.mean():+.1f}%)")
    prof = []
    for fn in feat_names:
        w, l, a = win[fn].median(), lose[fn].median(), D[fn].median()
        if pd.isna(w) or pd.isna(a):
            continue
        prof.append({"f": fn, "win": w, "lose": l, "all": a, "gap": w - a})
    prof.sort(key=lambda x: -abs(x["gap"]))
    for p in prof:
        print(f"  {p['f']:<18} 贏家{p['win']:>8.2f} | 全池{p['all']:>8.2f} | 輸家{p['lose']:>8.2f} "
              f"| 贏-全池{p['gap']:+.2f}")

    # ---- 特徵五分位階梯(同日橫斷面) ----
    print("\n階段一b 特徵五分位 → fwd5均值/勝率/賺賠比(同日橫斷面分位)")
    ladders = {}
    for fn in feat_names:
        sub = D[["d", fn, "fwd5"]].dropna()
        if len(sub) < 5000:
            continue
        q = sub.groupby("d")[fn].transform(lambda x: pd.qcut(x.rank(method="first"), 5, labels=False)
                                           if x.notna().sum() >= 25 else np.nan)
        sub = sub.assign(q=q).dropna(subset=["q"])
        rows = []
        for qq, g in sub.groupby("q"):
            w, l = g.fwd5[g.fwd5 > 0], g.fwd5[g.fwd5 <= 0]
            rows.append({"q": int(qq) + 1, "mean": g.fwd5.mean(), "win": (g.fwd5 > 0).mean() * 100,
                         "wl": (w.mean() / abs(l.mean())) if len(w) and len(l) else np.nan, "n": len(g)})
        ladders[fn] = rows
        spread = rows[-1]["mean"] - rows[0]["mean"]
        print(f"  {fn:<18} Q1{rows[0]['mean']:+.2f} Q3{rows[2]['mean']:+.2f} Q5{rows[-1]['mean']:+.2f} "
              f"價差{spread:+.2f}pp | Q5勝率{rows[-1]['win']:.0f}%/賺賠{rows[-1]['wl']:.2f}")

    # ---- 階段二: 規則對決 ----
    print("\n階段二 拉回進場規則對決(次日收盤進,持5日;判準=賺賠比>=1.5且勝率>=50%且成本後>0)")
    D["hot"] = D.money20 >= 3.0
    rules = {
        "R1長紅後拉回5日線": (D.n_longbar20 >= 1) & (D.days_since_longbar.between(1, 5)) &
                        (D.ma5_dist.between(-3, 1)),
        "R2新高後淺回(<=3%)": (D.dist20 >= -3) & (D.dist20 < 0) & (D.ret20 > 0),
        "R3深回檔接刀(>=8%)": (D.dist20 <= -8) & (D.ret20 > 0),
        "R4純追高(對照)": (D.dist20 >= -0.5) & (D.ret5 > 0),
        "R5題材成員×淺回": (D.is_theme == 1) & (D.dist20 >= -3) & (D.dist20 < 0) & (D.theme_mom > 0),
        "R6熱門股×淺回": D.hot & (D.dist20 >= -3) & (D.dist20 < 0) & (D.ret20 > 0),
        "R7漲停後拉回": (D.n_limitup20 >= 1) & (D.days_since_longbar.between(1, 5)) & (D.ma5_dist < 2),
        "R8淺回×大戶增": (D.dist20 >= -3) & (D.dist20 < 0) & (D.d4w > 0),
        "R9淺回×營收連創": (D.dist20 >= -3) & (D.dist20 < 0) & (D.rev_r1 == 1),
        "(全池基準)": pd.Series(True, index=D.index),
    }
    res = []
    for lab, mask in rules.items():
        sub = D[mask.fillna(False)]
        if len(sub) < 200:
            print(f"  {lab:<22} n={len(sub)} 不足")
            continue
        w, l = sub.fwd5[sub.fwd5 > 0], sub.fwd5[sub.fwd5 <= 0]
        wl = (w.mean() / abs(l.mean())) if len(w) and len(l) else np.nan
        winr = (sub.fwd5 > 0).mean() * 100
        exp0 = sub.fwd5.mean()
        y = sub.groupby("yr").fwd5.mean()
        ok = (wl >= 1.5) and (winr >= 50) and (exp0 - 0.3 > 0)
        r = {"lab": lab, "n": len(sub), "per_yr": len(sub) / 11.5, "mean": exp0,
             "dm": sub.fwd5dm.mean(), "win": winr, "wl": wl,
             "c03": exp0 - 0.3, "c05": exp0 - 0.5,
             "yr": f"{int((y > 0).sum())}/{len(y)}", "pass": ok}
        res.append(r)
        print(f"  {'✅' if ok else '  '}{lab:<22} n={r['n']:>7,}({r['per_yr']:.0f}/年) "
              f"均{exp0:+.2f}%/demean{r['dm']:+.2f}% 勝率{winr:.0f}% 賺賠{wl:.2f} "
              f"扣0.3%{r['c03']:+.2f}% 扣0.5%{r['c05']:+.2f}% 逐年{r['yr']}")

    # ---- HTML ----
    CSS = """
body{background:#1a1a19;color:#fff;font-family:"Noto Sans TC",sans-serif;margin:24px;max-width:1150px}
h1{font-size:20px} h2{font-size:15px;color:#c3c2b7;margin-top:26px;border-bottom:1px solid #333;padding-bottom:4px}
table{border-collapse:collapse;font-size:12.5px;font-variant-numeric:tabular-nums;margin:8px 0}
td,th{border:1px solid #333;padding:4px 9px;text-align:right} th{text-align:left;color:#c3c2b7}
.note{color:#8a8878;font-size:12.5px;line-height:1.8} .good{color:#7ec97e} .bad{color:#e06c5a}
.hl{background:#2b3a2b} .scroll{overflow-x:auto}
ul{margin:4px 0;padding-left:20px;font-size:12.5px;color:#ccc;line-height:1.7}
"""
    prof_html = ("<table><tr><th>特徵</th><th>贏家中位</th><th>全池中位</th><th>輸家中位</th><th>贏−全池</th></tr>"
                 + "".join(f"<tr><th>{p['f']}</th><td>{p['win']:.2f}</td><td>{p['all']:.2f}</td>"
                           f"<td>{p['lose']:.2f}</td><td class='{'good' if p['gap'] > 0 else 'bad'}'>"
                           f"{p['gap']:+.2f}</td></tr>" for p in prof) + "</table>")
    lad_html = ""
    for fn, rows in ladders.items():
        cells = "".join(f"<td>{r['mean']:+.2f}<br><span style='color:#777;font-size:10.5px'>"
                        f"{r['win']:.0f}%/{r['wl']:.2f}</span></td>" for r in rows)
        lad_html += f"<tr><th>{fn}</th>{cells}<td>{rows[-1]['mean'] - rows[0]['mean']:+.2f}</td></tr>"
    lad_html = ("<div class='scroll'><table><tr><th>特徵</th><th>Q1(最低)</th><th>Q2</th><th>Q3</th>"
                "<th>Q4</th><th>Q5(最高)</th><th>Q5−Q1</th></tr>" + lad_html + "</table></div>"
                "<div class='note'>格內第二行=勝率/賺賠比。</div>")
    rule_html = ("<div class='scroll'><table><tr><th>規則</th><th>n(次/年)</th><th>fwd5均值</th>"
                 "<th>demean</th><th>勝率</th><th>賺賠比</th><th>扣0.3%</th><th>扣0.5%</th>"
                 "<th>逐年</th><th>達標</th></tr>"
                 + "".join(f"<tr{' class=hl' if r['pass'] else ''}><th>{r['lab']}</th>"
                           f"<td>{r['n']:,}({r['per_yr']:.0f})</td><td>{r['mean']:+.2f}%</td>"
                           f"<td>{r['dm']:+.2f}%</td><td>{r['win']:.0f}%</td>"
                           f"<td class='{'good' if r['wl'] >= 1.5 else ''}'>{r['wl']:.2f}</td>"
                           f"<td>{r['c03']:+.2f}%</td><td>{r['c05']:+.2f}%</td><td>{r['yr']}</td>"
                           f"<td>{'✅' if r['pass'] else '—'}</td></tr>" for r in res) + "</table></div>")

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>一週大賺股逆向工程(2026-08-08)</title><style>{CSS}</style></head><body>
<h1>🎯 一週大賺股逆向工程 + 拉回進場規則對決</h1>
<div class="note">使用者目標: <b>持有一週(5交易日)、勝率高、賺賠比>=1.5</b>。方法=先定義結果(同日fwd5前5%)
再回頭挖特徵,不預設型態。口徑: 次日收盤進場→第5個交易日收盤出場(可執行,零前視);
池=20日均額>=0.3億;每5交易日抽樣(fwd5窗不重疊);2015起,樣本{len(D):,}筆。
判準(預先註冊)=<b>賺賠比>=1.5 且 勝率>=50% 且 扣0.3%成本後期望值>0</b>。</div>
<h2>階段一 贏家畫像(前5% vs 全池 vs 後5%)</h2>
{prof_html}
<h2>階段一b 特徵五分位階梯(同日橫斷面)</h2>
{lad_html}
<h2>階段二 拉回進場規則對決</h2>
{rule_html}
<h2>⚖️ 判決(2026-08-08首輪)</h2>
<ul>
<li><span style="background:#3b2420;color:#e06c5a;padding:6px 10px;border-radius:4px;font-weight:bold">
①最重要的發現: <b>一週尺度的大賺股與大賠股,事前長得幾乎一模一樣</b></span>
贏家(前5%,平均+13.8%)vs 輸家(後5%)的事前特徵中位數: ret20 <b>5.67 vs 7.16(輸家更高)</b>、
ma20_dist 2.37 vs <b>2.92(輸家更高)</b>、amp20 4.21 vs 4.46、vol_ratio 0.81 vs 0.88——
<b>兩端都是高動能、高波動、貼近均線上方的同一批股票</b>,只是硬幣的兩面。
這是「頂部無指紋定理」的短線版: <b>一週尺度沒有指紋</b>,你能篩出「會大幅波動的股票」,
但篩不出「往哪邊波動」。</li>
<li><span style="background:#3b3420;color:#c3a55a;padding:6px 10px;border-radius:4px;font-weight:bold">
②所有特徵的五分位階梯都極平: 最大價差僅0.53pp</span>
最強的是題材動能(theme_mom Q5−Q1=+0.53pp/Q5賺賠1.36)與題材成員(+0.50pp),
其餘位置/動能/量能/波動/籌碼/營收全在±0.4pp內;<b>Q5賺賠比天花板1.13~1.36,沒有任何單一特徵能推到1.5</b>。
使用者提到的「熱門成交值大」在資料上幾乎無效(money20 Q5−Q1僅+0.17pp)。
一個有用的細節: days_since_longbar <b>Q1(剛長紅)+0.43 vs Q5(很久沒長紅)+0.17</b>=
「事件剛發生」比「安靜很久」好——與壓縮爆發卷結論一致。</li>
<li><span style="background:#3b3420;color:#c3a55a;padding:6px 10px;border-radius:4px;font-weight:bold">
③規則對決: 拉回確實勝過追高,但<b>全部沒達標</b>(賺賠比>=1.5×勝率>=50%×成本後>0)</span>
最好三條: <b>R7漲停後拉回(+0.90%/勝率48%/賺賠1.42/扣0.5%後+0.40%)</b>、
R1長紅後拉回5日線(+0.82%/49%/1.40/+0.32%)、R5題材成員×淺回(+0.52%/<b>勝率50%</b>/1.35/+0.02%);
對照組: 純追高R4僅+0.42%、全池基準+0.27%(扣0.3%成本即為負)——
<b>「等拉回」是對的(R7/R1 是基準的3倍),但賺賠比天花板在1.4</b>,離1.5差一步、勝率也上不了50%。
深回檔接刀(R3)與大戶增(R8)無效。</li>
<li><b>④下一步的方向(進場端已榨乾,要靠出場端)</b>: 本卷把進場端的特徵空間掃過一遍,
結論是<b>賺賠比不可能只靠選股達到1.5</b>。真正還沒動的槓桿是<b>出場</b>——
固定持有5日是最鈍的做法;可測「目標價停利(+5%/+8%)」「移動停損」「首日不利即出」「賺就抱到轉弱」等
動態出場,<b>賺賠比正是出場端的直接產物</b>(截斷虧損=分母變小)。這是下一張卷,也是唯一還有機會
達標的路徑。</li>
</ul>
<div class="note">維運: python 研究腳本/綜合策略/build_week_winner_anatomy.py(從根目錄執行)。</div>
</body></html>"""
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n[report] 已輸出 {OUT}")


if __name__ == "__main__":
    main()
