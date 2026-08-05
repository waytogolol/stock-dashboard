# -*- coding: utf-8 -*-
"""美股題材成員創新高→台股同題材反應考卷(2026-08-05,使用者指定測試的未測變體)。

與既有判決的分工:
· 獨漲線hi_frac=「題材大漲日」上疊創新高比例(條件於大漲,短窗反轉k40拉平)——本卷測**無條件**版:
  美股成員「獨立突破新高」本身當事件(前20美股日無N日新高的首破),不用等題材大漲。
· 台股新高卷(build_newhigh_breakout_swing)=台股個股破自己的高;本卷=美股破高→台股同題材,跨市場傳導。
· 財報卷判決「台股只讀美股價格語言」——新高突破正是純價格事件,理論上應傳導;但hi_frac教訓=
  新高訊號傳到台股常伴大跳空過衝,可執行性要盯緊。

═══ 設計(預先註冊) ═══
事件: 美股成員收盤=近N日最高(N=90/240;台股卷已證60最弱故略),獨立突破=前20美股日無N日新高;
  聚合到(題材,美股日d): n_break=當日突破成員數、r_best=突破成員中當日最大報酬、
  theme_sig=題材當日均報酬(判斷是否同時題材大漲)、SPX。
台股: t=d後首個台股交易日(fresh<=3日曆天),同題材demean cc/跳空/oc/CAR k=1,3,5,10,20,40(開盤錨)。
分層: ①全部突破事件 ②突破成員當日漲>=2%(有力突破) ③×SPX<0(獨漲交乘) ④×題材大漲>=2%(共振)
  ⑤n_break>=2(多成員齊破) ⑥對照=無突破的普通題材日。
統計: 月群bootstrap+逐年+分題材(n>=15);絕對與demean並列;可執行性=跳空/oc分解必列。

用法: python 研究腳本/題材動能/build_us_newhigh_tw_link.py  (從根目錄執行,鐵律)
產出: 研究報告/research_us_newhigh_tw_link.html + console
"""
import sqlite3
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

DB = "capital_flow.db"
OUT = "研究報告/research_us_newhigh_tw_link.html"
START = "2015-01-01"
N_LIST = [90, 240]
FRESH_GAP = 20
K_LIST = [1, 3, 5, 10, 20, 40]
ADR_EXCLUDE = {"TSM", "UMC", "ASX"}
MAPPED_THEMES = [
    "IC設計", "CPO/光通訊", "AI伺服器", "半導體設備", "記憶體", "晶圓代工",
    "功率半導體", "電力設備", "組裝代工(EMS)", "機器人/自動化", "半導體材料",
    "電池/儲能", "連接器", "網通設備", "綠能/太陽能", "封測(OSAT/測試)",
    "被動元件", "化合物半導體", "PCB/CCL", "電信",
]
MIN_TW_MEMBERS = 2
rng = np.random.default_rng(20260805)


def main():
    conn = sqlite3.connect(DB, timeout=60)
    mem = {}
    for country, key in (("美", "us"), ("台", "tw")):
        for t in MAPPED_THEMES:
            mem[(key, t)] = [r[0] for r in conn.execute(
                "select distinct code from classification where country=? and main_group=?",
                (country, t))]
    all_tw = sorted({c for t in MAPPED_THEMES for c in mem[("tw", t)]})
    usd = pd.read_sql("select code,date,close from us_daily_price where date>='2014-01-01'", conn)
    twd = pd.read_sql(
        "select code,date,open,close from fm_daily_price "
        "where date>='2014-06-01' and close>0 and money>0 and code in (%s)" % ",".join("?" * len(all_tw)),
        conn, params=all_tw)
    idx = pd.read_sql("select market,date,open,close from index_daily "
                      "where market in ('TAIEX','SPX') and date>='2014-01-01'", conn)
    conn.close()

    piv = lambda df, v: df.pivot_table(index="date", columns="code", values=v, aggfunc="first").sort_index()
    spx = idx[idx.market == "SPX"].set_index("date")["close"].sort_index()
    tai = idx[idx.market == "TAIEX"].set_index("date").sort_index()
    spx_ret = spx.pct_change()

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

    def tw_theme(mat, members):
        cols = [c for c in members if c in mat.columns]
        m = mat[cols]
        n = m.notna().sum(axis=1)
        return m.mean(axis=1).where(n >= MIN_TW_MEMBERS)

    tw_sig = {t: {"cc": tw_theme(cc, mem[("tw", t)]), "oc": tw_theme(oc, mem[("tw", t)]),
                  "gap": tw_theme(gap, mem[("tw", t)]),
                  **{f"car_o{k}": tw_theme(car_o[k], mem[("tw", t)]) for k in K_LIST}}
              for t in MAPPED_THEMES}
    tai_dates = np.array(tai.index)

    panels = {}
    for N in N_LIST:
        rmax = us_close.rolling(N, min_periods=int(N * 0.8)).max()
        is_hi = (us_close >= rmax * 0.9999) & us_close.notna()
        fresh = is_hi & (~is_hi.shift(1).rolling(FRESH_GAP, min_periods=1).max().astype(bool))
        recs = []
        for t in MAPPED_THEMES:
            cols = [c for c in mem[("us", t)] if c not in ADR_EXCLUDE and c in us_close.columns]
            if not cols:
                continue
            fr = fresh[cols]
            n_break = fr.sum(axis=1)
            theme_r = us_ret[cols].mean(axis=1)
            best = us_ret[cols].where(fr).max(axis=1)
            for d in fr.index[n_break > 0]:
                if d < "2014-12-01":
                    continue
                p = int(np.searchsorted(tai_dates, d, side="right"))
                if p >= len(tai_dates):
                    continue
                t_day = tai_dates[p]
                if (pd.Timestamp(t_day) - pd.Timestamp(d)).days > 3:
                    continue
                s = tw_sig[t]
                v_cc = s["cc"].get(t_day, np.nan)
                if pd.isna(v_cc):
                    continue
                rec = {"theme": t, "d": d, "t": t_day, "n_break": int(n_break[d]),
                       "r_best": best[d], "theme_sig": theme_r[d], "spx": spx_ret.get(d, np.nan),
                       "tw_cc": v_cc - tai_cc.get(t_day, np.nan),
                       "tw_oc": s["oc"].get(t_day, np.nan) - tai_oc.get(t_day, np.nan),
                       "tw_gap": s["gap"].get(t_day, np.nan) - tai_gap.get(t_day, np.nan)}
                for k in K_LIST:
                    rec[f"car_o{k}"] = s[f"car_o{k}"].get(t_day, np.nan) - tai_car_o[k].get(t_day, np.nan)
                recs.append(rec)
        P = pd.DataFrame(recs)
        P = P[P["t"] >= START]
        P["month"] = P["t"].str[:7]
        P["year"] = P["t"].str[:4]
        panels[N] = P
        print(f"[N={N}] 題材×美股日突破事件{len(P):,}筆({P.theme.nunique()}題材,"
              f"{P.t.min()}~{P.t.max()},多成員齊破{int((P.n_break >= 2).sum())})")

    def boot_ci(sub, col, n_iter=1000):
        v = sub[["month", col]].dropna()
        if len(v) < 12 or v.month.nunique() < 6:
            return (np.nan, np.nan)
        grp = {d: g[col].values for d, g in v.groupby("month")}
        keys = list(grp)
        means = [np.mean(np.concatenate([grp[d] for d in rng.choice(keys, len(keys))]))
                 for _ in range(n_iter)]
        return tuple(np.percentile(means, [2.5, 97.5]))

    def ci_str(sub, col):
        lo, hi = boot_ci(sub, col)
        if pd.isna(lo):
            return "n太小"
        mark = "✓排0" if (lo > 0 or hi < 0) else "含0"
        return f"{sub[col].mean() * 100:+.2f}% [{lo * 100:+.2f},{hi * 100:+.2f}]{mark}"

    def line(sub, lab):
        if len(sub) < 10:
            print(f"  {lab:<26} n={len(sub)} 樣本不足")
            return None
        y = sub.groupby("year").car_o5.mean()
        r = {"lab": lab, "n": len(sub), "cc": sub.tw_cc.mean() * 100,
             "gap": sub.tw_gap.mean() * 100, "oc": sub.tw_oc.mean() * 100,
             **{f"car{k}": sub[f"car_o{k}"].mean() * 100 for k in K_LIST},
             "ci_cc": ci_str(sub, "tw_cc"), "ci5": ci_str(sub, "car_o5"),
             "ci20": ci_str(sub, "car_o20"), "yr": f"{int((y > 0).sum())}/{len(y)}"}
        print(f"  {lab:<26} n={r['n']:>5} cc{r['cc']:+.2f} 跳空{r['gap']:+.2f} oc{r['oc']:+.2f} "
              + " ".join(f"CAR{k}={r[f'car{k}']:+.2f}" for k in K_LIST)
              + f"  cc:{r['ci_cc']} CAR5:{r['ci5']} CAR20:{r['ci20']} 逐年{r['yr']}")
        return r

    print("\n" + "=" * 100)
    print("美股題材成員獨立突破新高 → 台股同題材(demean,開盤錨)")
    print("=" * 100)
    results = {}
    for N in N_LIST:
        P = panels[N]
        print(f"\n【N={N}日新高突破】")
        results[(N, "all")] = line(P, "①全部突破事件")
        results[(N, "strong")] = line(P[P.r_best >= 0.02], "②突破成員當日漲>=2%")
        results[(N, "pocket")] = line(P[(P.r_best >= 0.02) & (P.spx < 0)], "③×SPX<0(獨漲交乘)")
        results[(N, "surge")] = line(P[(P.r_best >= 0.02) & (P.theme_sig >= 0.02)], "④×題材大漲>=2%(共振)")
        results[(N, "multi")] = line(P[P.n_break >= 2], "⑤多成員齊破(n_break>=2)")

    print("\n分題材(N=240全部事件, n>=15)")
    TH = []
    for t, g in panels[240].groupby("theme"):
        if len(g) >= 15:
            TH.append({"theme": t, "n": len(g), "cc": g.tw_cc.mean() * 100,
                       "car5": g.car_o5.mean() * 100, "car20": g.car_o20.mean() * 100})
    TH.sort(key=lambda x: -x["car5"])
    for r in TH:
        print(f"  {r['theme']:<14} n={r['n']:>4} cc={r['cc']:+.2f} CAR5={r['car5']:+.2f} CAR20={r['car20']:+.2f}")

    # ---------- HTML ----------
    CSS = """
body{background:#1a1a19;color:#fff;font-family:"Noto Sans TC",sans-serif;margin:24px;max-width:1150px}
h1{font-size:20px} h2{font-size:15px;color:#c3c2b7;margin-top:30px;border-bottom:1px solid #333;padding-bottom:4px}
table{border-collapse:collapse;font-size:12.5px;font-variant-numeric:tabular-nums;margin:8px 0}
td,th{border:1px solid #333;padding:4px 8px;text-align:right} th{text-align:left;color:#c3c2b7}
.note{color:#8a8878;font-size:12.5px;line-height:1.8} .good{color:#7ec97e} .bad{color:#e06c5a}
ul{margin:4px 0;padding-left:20px;font-size:12.5px;color:#ccc;line-height:1.7}
.verdict{font-size:13px;font-weight:bold;padding:6px 10px;border-radius:4px;display:inline-block;margin:4px 0}
.v-good{background:#243b24;color:#7ec97e} .v-bad{background:#3b2420;color:#e06c5a}
.v-warn{background:#3b3420;color:#c3a55a}
.scroll{overflow-x:auto}
"""
    khead = "".join(f"<th>CAR{k}</th>" for k in K_LIST)

    def tbl(N):
        h = (f"<div class='scroll'><table><tr><th>組</th><th>n</th><th>當日cc</th><th>跳空</th><th>oc</th>"
             f"{khead}<th>cc CI</th><th>CAR5 CI</th><th>CAR20 CI</th><th>逐年</th></tr>")
        for key in ("all", "strong", "pocket", "surge", "multi"):
            r = results.get((N, key))
            if r is None:
                continue
            h += (f"<tr><th>{r['lab']}</th><td>{r['n']:,}</td><td>{r['cc']:+.2f}</td>"
                  f"<td>{r['gap']:+.2f}</td><td>{r['oc']:+.2f}</td>"
                  + "".join(f"<td>{r[f'car{k}']:+.2f}</td>" for k in K_LIST)
                  + f"<td>{r['ci_cc']}</td><td>{r['ci5']}</td><td>{r['ci20']}</td><td>{r['yr']}</td></tr>")
        return h + "</table></div>"

    th_html = ("<table><tr><th>題材(N=240)</th><th>n</th><th>當日cc</th><th>CAR5</th><th>CAR20</th></tr>"
               + "".join(f"<tr><th>{r['theme']}</th><td>{r['n']}</td><td>{r['cc']:+.2f}</td>"
                         f"<td>{r['car5']:+.2f}</td><td>{r['car20']:+.2f}</td></tr>" for r in TH) + "</table>")

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>美股題材新高突破→台股(2026-08-05)</title><style>{CSS}</style></head><body>
<h1>⛰️ 美股題材成員創新高突破 → 台股同題材反應考卷</h1>
<div class="note">使用者指定的未測變體。事件=美股成員收盤破近N日高(N=90/240)且前{FRESH_GAP}美股日
未曾破(獨立突破),聚合到題材×美股日;台股t=次一台股交易日(fresh<=3日曆天),demean口徑同獨漲線。
與hi_frac(獨漲內創新高比例,條件於大漲日)不同——本卷是無條件突破事件。
N=90: {len(panels[90]):,}事件 / N=240: {len(panels[240]):,}事件。</div>
<h2>N=90日新高突破</h2>
{tbl(90)}
<h2>N=240日(52週)新高突破</h2>
{tbl(240)}
<h2>分題材(N=240)</h2>
{th_html}
<h2>⚖️ 判決(2026-08-05首輪)</h2>
<ul>
<li><span class="verdict v-bad">①短線層死: 跳空過衝再現</span> 全部事件跳空+0.33~0.37/oc-0.26~-0.28
(開盤追買買貴又回吐),當日cc僅+0.06~0.08,CAR5全含0——美股新高訊號傳到台股與hi_frac教訓同型:
顯著性事件伴大跳空,短線無肉。多成員齊破(⑤)更差(240日CAR5-0.38)=齊破日多為題材過熱日。</li>
<li><span class="verdict v-warn">②慢波段層有薄訊號</span> CAR20全事件+0.77~0.83✓排0/共振格+0.98~1.30✓,
CAR40+2.0~3.6%——與獨漲線「創新高只在多日持有有價值」一致;但量級遠低於台股自家新高突破卷
(題材成員90日k20+1.52/240日+2.14)。</li>
<li><b>③定位=被台股自家突破訊號支配,不獨立上板</b>: 美股成員突破→台股同題材的傳導,實務上會在
1-數日內體現為「台股成員自己突破」——直接用台股新高卷訊號(更精準到個股、更早)即可;本卷價值=
確認跨市場傳導存在(CAR20✓)+live參考(美股側突破可當台股突破的先行提示,記憶體/AI伺服器/晶圓代工
傳導最強,電信/機器人無效)。</li>
</ul>
<h2>已知限制</h2>
<div class="note">①事件在美股多頭段聚集(月群bootstrap處理日內相關,跨月聚集仍偏保守);
②突破成員數/強度的操作化(n_break/r_best)為研究者選擇;③台股側未還原除權息;
④美股成員僅對映題材~89檔;⑤與獨漲/財報事件同日重疊未去重(訊號家族天然共現,分層表已含交乘格)。</div>
<div class="note">維運: python 研究腳本/題材動能/build_us_newhigh_tw_link.py(從根目錄執行)。
姊妹卷: build_us_tw_pocket_refine.py(獨漲線)、build_newhigh_breakout_swing.py(台股新高卷)、
build_us_earnings_tw_theme_link.py(財報事件卷)。</div>
</body></html>"""
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n[report] 已輸出 {OUT}")


if __name__ == "__main__":
    main()
