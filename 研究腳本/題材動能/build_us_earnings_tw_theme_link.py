# -*- coding: utf-8 -*-
"""美股題材成員財報公布→台股同題材反應考卷(2026-08-05,使用者提問:「美股也有財報,也有公布日,
你覺得你找的到資訊能一起回測看嗎?」——資料已建: 抓取/fetch_us_earnings_dates.py,
us_earnings_dates表,yfinance每檔~100筆回溯2001含EPS驚喜%)。

═══ 假說與定位 ═══
題材獨漲線已驗證「美股題材大漲→台股同題材」的隔夜傳導;本卷問的是**事件驅動子集**:
美股題材成員「財報公布」引發的大漲/大跌,傳導到台股同題材是更強(基本面新資訊,三問第②問=
資訊是新的)還是更弱(公司特定訊息,不代表產業)?財報事件有兩個一般題材大漲日沒有的維度:
EPS驚喜%(定量的基本面新資訊)與公布時點(盤前/盤後,精確零前視)。

═══ 設計(預先註冊) ═══
反應日R(美股): AMC(盤後,hour>=15)→公布日次一美股交易日;BMO(盤前)→公布日當日;
  DUR/UNK→取{當日,次日}中|報酬|較大者(Yahoo歷史日期偶錯置,誠實計數)。
訊號(R日收盤,台北清晨已知): ①該成員R日超額報酬exc_R(減SPX) ②EPS驚喜% ③兩者雙確認。
台股: t=R後第一個台股交易日(fresh: R與t差<=3日曆天,排除連假陳舊);同題材demean
  cc/跳空/oc/CAR k=1,3,5,10,20(開盤錨,口徑同獨漲線);同一(題材,t)多成員公布→聚合
  (成員數n_ann、exc均值、驚喜均值),事件=題材×t層。
分層: A)exc_R分層(<-5/-5~0/0~5/5~8/>8%) B)驚喜分層(<0/0~10/>10%) C)雙確認(exc>5%×驚喜>10%)
  D)財報版獨漲(exc_R>5%且SPX<0) E)對照=同題材「非財報日大漲」(獨漲線口徑)數字並列引用。
統計: 月群bootstrap+逐年+分題材(n>=10);絕對與demean並列。
已知限制: Yahoo財報日期偶錯置(已用反應日錨定緩解);財報季聚集(1/4/7/10月)使月群bootstrap
偏保守;台股側未還原除權息;EPS驚喜%對虧損轉盈/基期極小者會爆表(winsorize±100%)。

用法: python 研究腳本/題材動能/build_us_earnings_tw_theme_link.py  (從根目錄執行,鐵律)
產出: 研究報告/research_us_earnings_tw_link.html + console
"""
import json
import sqlite3
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

DB = "capital_flow.db"
OUT = "研究報告/research_us_earnings_tw_link.html"
START = "2015-01-01"
K_LIST = [1, 3, 5, 10, 20]
ADR_EXCLUDE = {"TSM", "UMC", "ASX"}
MAPPED_THEMES = [
    "IC設計", "CPO/光通訊", "AI伺服器", "半導體設備", "記憶體", "晶圓代工",
    "功率半導體", "電力設備", "組裝代工(EMS)", "機器人/自動化", "半導體材料",
    "電池/儲能", "連接器", "網通設備", "綠能/太陽能", "封測(OSAT/測試)",
    "被動元件", "化合物半導體", "PCB/CCL", "電信",
]
MIN_TW_MEMBERS = 2
rng = np.random.default_rng(20260805)


def load():
    conn = sqlite3.connect(DB, timeout=60)
    ann = pd.read_sql("select code, ann_date, session, surprise_pct from us_earnings_dates "
                      "where eps_actual is not null and ann_date>='2014-11-01'", conn)
    theme_of = {}
    for t in MAPPED_THEMES:
        for r in conn.execute("select distinct code from classification "
                              "where country='美' and main_group=?", (t,)):
            theme_of.setdefault(r[0], []).append(t)
    tw_mem = {t: [r[0] for r in conn.execute(
        "select distinct code from classification where country='台' and main_group=?", (t,))]
        for t in MAPPED_THEMES}
    all_tw = sorted({c for v in tw_mem.values() for c in v})
    usd = pd.read_sql("select code,date,close from us_daily_price where date>='2014-01-01'", conn)
    twd = pd.read_sql(
        "select code,date,open,close from fm_daily_price "
        "where date>='2014-06-01' and close>0 and money>0 and code in (%s)" % ",".join("?" * len(all_tw)),
        conn, params=all_tw)
    idx = pd.read_sql("select market,date,open,close from index_daily "
                      "where market in ('TAIEX','SPX') and date>='2014-01-01'", conn)
    conn.close()
    print(f"[load] 財報事件{len(ann):,}筆({ann.code.nunique()}檔,{ann.ann_date.min()}~{ann.ann_date.max()})")
    return ann, theme_of, tw_mem, usd, twd, idx


def main():
    ann, theme_of, tw_mem, usd, twd, idx = load()
    piv = lambda df, v: df.pivot_table(index="date", columns="code", values=v, aggfunc="first").sort_index()
    spx = idx[idx.market == "SPX"].set_index("date")["close"].sort_index()
    tai = idx[idx.market == "TAIEX"].set_index("date").sort_index()
    spx_ret = spx.pct_change()

    us_close = piv(usd, "close")
    us_ret = us_close.pct_change(fill_method=None)
    us_dates = np.array(us_ret.index)

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

    tw_sig = {t: {"cc": tw_theme(cc, tw_mem[t]), "oc": tw_theme(oc, tw_mem[t]),
                  "gap": tw_theme(gap, tw_mem[t]),
                  **{f"car_o{k}": tw_theme(car_o[k], tw_mem[t]) for k in K_LIST}}
              for t in MAPPED_THEMES}
    tai_dates = np.array(tai.index)

    # ---------- 反應日R + 成員層事件 ----------
    n_dur, n_nodata = 0, 0
    mem_events = []
    for r in ann.itertuples():
        if r.code not in us_ret.columns:
            n_nodata += 1
            continue
        i = int(np.searchsorted(us_dates, r.ann_date))
        if i >= len(us_dates) - 2:
            continue
        same = us_dates[i] if i < len(us_dates) and us_dates[i] == r.ann_date else None
        nxt_i = i + 1 if same is not None else i
        if r.session == "AMC" or same is None:
            R_i = nxt_i
        elif r.session == "BMO":
            R_i = i
        else:
            n_dur += 1
            r0 = us_ret.iloc[i][r.code] if same is not None else np.nan
            r1 = us_ret.iloc[nxt_i][r.code]
            R_i = i if (pd.notna(r0) and (pd.isna(r1) or abs(r0) >= abs(r1))) else nxt_i
        if R_i >= len(us_dates):
            continue
        R = us_dates[R_i]
        ret_R = us_ret.iloc[R_i][r.code]
        if pd.isna(ret_R):
            continue
        exc_R = ret_R - spx_ret.get(R, np.nan)
        sp = np.clip(r.surprise_pct, -100, 100) if pd.notna(r.surprise_pct) else np.nan
        for t in theme_of.get(r.code, []):
            mem_events.append({"code": r.code, "theme": t, "R": R, "exc": exc_R,
                               "spx": spx_ret.get(R, np.nan), "surp": sp})
    ME = pd.DataFrame(mem_events)
    print(f"[event] 成員層事件{len(ME):,}筆(無價量跳過{n_nodata},DUR/UNK用反應日錨定{n_dur})")

    # (題材, R)聚合 → 台股訊號日t
    agg = ME.groupby(["theme", "R"]).agg(
        n_ann=("code", "size"), exc=("exc", "mean"), surp=("surp", "mean"),
        spx=("spx", "first")).reset_index()
    recs = []
    for r in agg.itertuples():
        p = int(np.searchsorted(tai_dates, r.R, side="right"))
        if p >= len(tai_dates):
            continue
        t_day = tai_dates[p]
        if (pd.Timestamp(t_day) - pd.Timestamp(r.R)).days > 3:
            continue
        s = tw_sig[r.theme]
        v_cc = s["cc"].get(t_day, np.nan)
        if pd.isna(v_cc):
            continue
        rec = {"theme": r.theme, "R": r.R, "t": t_day, "n_ann": r.n_ann,
               "exc": r.exc, "surp": r.surp, "spx": r.spx,
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
    print(f"[panel] 題材×反應日事件{len(P):,}筆({P.theme.nunique()}題材,{P.t.min()}~{P.t.max()})")

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
        if len(sub) < 8:
            print(f"  {lab:<26} n={len(sub)} 樣本不足")
            return None
        y = sub.groupby("year").car_o5.mean()
        r = {"lab": lab, "n": len(sub), "cc": sub.tw_cc.mean() * 100,
             "gap": sub.tw_gap.mean() * 100, "oc": sub.tw_oc.mean() * 100,
             **{f"car{k}": sub[f"car_o{k}"].mean() * 100 for k in K_LIST},
             "ci_cc": ci_str(sub, "tw_cc"), "ci5": ci_str(sub, "car_o5"),
             "yr": f"{int((y > 0).sum())}/{len(y)}"}
        print(f"  {lab:<26} n={r['n']:>5} cc{r['cc']:+.2f} 跳空{r['gap']:+.2f} oc{r['oc']:+.2f} "
              + " ".join(f"CAR{k}={r[f'car{k}']:+.2f}" for k in K_LIST)
              + f"  cc:{r['ci_cc']} CAR5:{r['ci5']} 逐年{r['yr']}")
        return r

    print("\n" + "=" * 96)
    print("A) 美股成員財報反應exc_R分層 → 台股同題材次日")
    A = []
    for lab, mask in [("反應大跌<-5%", P.exc <= -0.05),
                      ("反應-5~0%", (P.exc > -0.05) & (P.exc < 0)),
                      ("反應0~+5%", (P.exc >= 0) & (P.exc < 0.05)),
                      ("反應+5~+8%", (P.exc >= 0.05) & (P.exc < 0.08)),
                      ("反應>+8%", P.exc >= 0.08),
                      ("反應>+5%合併", P.exc >= 0.05)]:
        A.append(line(P[mask], lab))

    print("\nB) EPS驚喜分層(反應日已知,winsorize±100%)")
    B = []
    subS = P.dropna(subset=["surp"])
    for lab, mask in [("驚喜<0(miss)", subS.surp < 0),
                      ("驚喜0~10%", (subS.surp >= 0) & (subS.surp < 10)),
                      ("驚喜>10%(大beat)", subS.surp >= 10)]:
        B.append(line(subS[mask], lab))

    print("\nC) 雙確認與D) 財報版獨漲")
    C = []
    C.append(line(P[(P.exc >= 0.05) & (P.surp >= 10)], "C雙確認(exc>5%×驚喜>10%)"))
    C.append(line(P[(P.exc >= 0.05) & (P.spx < 0)], "D財報版獨漲(exc>5%×SPX<0)"))
    C.append(line(P[(P.exc >= 0.05) & (P.spx >= 0)], "D'對照(exc>5%×SPX>=0)"))

    print("\n分題材(反應>+5%, n>=10)")
    TH = []
    big = P[P.exc >= 0.05]
    for t, g in big.groupby("theme"):
        if len(g) >= 10:
            TH.append({"theme": t, "n": len(g), "cc": g.tw_cc.mean() * 100,
                       "car5": g.car_o5.mean() * 100})
    TH.sort(key=lambda x: -x["cc"])
    for r in TH:
        print(f"  {r['theme']:<14} n={r['n']:>4} cc={r['cc']:+.2f} CAR5={r['car5']:+.2f}")

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
.scroll{overflow-x:auto}
"""
    khead = "".join(f"<th>CAR{k}</th>" for k in K_LIST)

    def tbl(rows):
        h = (f"<div class='scroll'><table><tr><th>組</th><th>n</th><th>當日cc</th><th>跳空</th><th>oc</th>"
             f"{khead}<th>cc CI</th><th>CAR5 CI</th><th>逐年</th></tr>")
        for r in rows:
            if r is None:
                continue
            h += (f"<tr><th>{r['lab']}</th><td>{r['n']:,}</td><td>{r['cc']:+.2f}</td>"
                  f"<td>{r['gap']:+.2f}</td><td>{r['oc']:+.2f}</td>"
                  + "".join(f"<td>{r[f'car{k}']:+.2f}</td>" for k in K_LIST)
                  + f"<td>{r['ci_cc']}</td><td>{r['ci5']}</td><td>{r['yr']}</td></tr>")
        return h + "</table></div>"

    th_html = ("<table><tr><th>題材(反應>+5%)</th><th>n</th><th>當日cc</th><th>CAR5</th></tr>"
               + "".join(f"<tr><th>{r['theme']}</th><td>{r['n']}</td><td>{r['cc']:+.2f}</td>"
                         f"<td>{r['car5']:+.2f}</td></tr>" for r in TH) + "</table>")

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>美股財報→台股題材連動(2026-08-05)</title><style>{CSS}</style></head><body>
<h1>📅 美股題材成員財報公布 → 台股同題材反應考卷</h1>
<div class="note">使用者提問開線:「美股也有財報,也有公布日,能一起回測嗎?」——資料=us_earnings_dates
(yfinance,~89檔對映成員,每檔~100季回溯,含EPS驚喜%與盤前/盤後時點)。事件=成員財報反應日R
(AMC→次日/BMO→當日/不明→|報酬|大者)聚合到題材層,台股t=R後首個交易日(fresh<=3日曆天),
demean口徑同獨漲線。panel {len(P):,}筆題材×反應日({P.t.min()}~{P.t.max()})。
獨漲線基準參考: 一般題材大漲>2%日台股cc+0.2~0.3%/獨漲日CAR5+0.68%。</div>
<h2>A) 美股財報反應exc_R(減SPX)分層</h2>
{tbl(A)}
<h2>B) EPS驚喜分層</h2>
{tbl(B)}
<h2>C) 雙確認 / D) 財報版獨漲</h2>
{tbl(C)}
<h2>分題材(反應>+5%)</h2>
{th_html}
<h2>⚖️ 判決(2026-08-05首輪)</h2>
<ul>
<li><span class="verdict v-good">①財報事件傳導成立,但不對稱: 利多傳導、利空不傳導</span>
成員財報反應>+5%→台股同題材cc+0.13%✓/CAR5+0.45%✓/CAR20+2.31%(逐年8/12);
反應大跌&lt;-5%→台股完全不跟(cc+0.01含0,CAR5含0)——台股題材只接美股財報的好消息,
壞消息不跌(可能被「台廠受惠轉單」敘事抵銷,機制待考)。</li>
<li><span class="verdict v-bad">②傳導的是「價格反應」不是「EPS數字」</span> EPS驚喜分層完全無梯度
(miss/小beat/大beat台股反應幾乎相同,全含0);雙確認(exc>5%×驚喜>10%)不增量(+0.34含0 vs
單獨exc>5%的+0.45✓)——台股只讀美股的價格語言,EPS數字層無獨立資訊(或Yahoo驚喜資料噪音大)。
實務=live只需盯美股反應日報酬,不用管beat/miss。</li>
<li><span class="verdict v-good">③財報版獨漲=本卷最乾淨活口,獨漲機制第三次獨立重現</span>
exc>5%×SPX&lt;0: 跳空-0.01%(<b>無過衝</b>)/oc+0.13/CAR5+0.55✓[+0.18,+0.95]/CAR20+2.49/逐年9/12
vs SPX>=0對照跳空+0.49/oc-0.35(開盤過衝盤中回吐)——「無大盤掩護時題材訊號定價不足」在
一般題材層、獨漲精煉、財報事件層三個獨立面板重現,機制已非常紮實。</li>
<li><b>④量級誠實比較</b>: 單一成員財報反應>5%的題材層CAR5+0.45,比整題材大漲>2%的獨漲+0.68薄
(單檔訊號vs全題材訊號,合理);財報事件的獨特優勢=<b>公布日事先已知</b>(未來場次已入庫),
可預先排程盯盤,不像一般獨漲要每天等。</li>
<li><b>⑤強題材與獨漲線一致</b>: 記憶體/封測/半導體設備/IC設計CAR5偏高,EMS/機器人偏負。</li>
</ul>
<h2>已知限制</h2>
<div class="note">①Yahoo歷史財報日期偶錯置(已用反應日錨定+AMC/BMO時點緩解,DUR/UNK={n_dur}筆用
|報酬|大者);②財報季聚集使月群bootstrap偏保守;③EPS驚喜%已winsorize±100%(虧轉盈/低基期爆表);
④台股側未還原除權息;⑤成員層事件聚合到題材層(同題材同日多檔公布取均值),n_ann>1的事件訊號較強
但樣本少未單獨分層;⑥美股成員覆蓋=對映題材~89檔,非全部美股。</div>
<div class="note">維運: python 研究腳本/題材動能/build_us_earnings_tw_theme_link.py(從根目錄執行);
資料更新=python 抓取/fetch_us_earnings_dates.py。姊妹卷: build_us_tw_overnight_link.py(獨漲線首輪)、
build_us_tw_pocket_refine.py(獨漲精煉)。</div>
</body></html>"""
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n[report] 已輸出 {OUT}")


if __name__ == "__main__":
    main()
