# -*- coding: utf-8 -*-
"""雙新高九宮格考卷: 價格狀態×營收創高 全矩陣(2026-08-07,使用者裁示直接開卷)。

背景: 「創高家族」三卷收斂——①價格新高突破(newhigh卷:題材成員90/240日突破=波段活口)
②營收創新高(rev_preposition v2/v3:季末月+次月連創12月高=埋伏配方+4.25~5.68%✓,
P(gm改善|三月全創高)=68.5%)③毛利率QoQ(gm×動能/三重門檻)。使用者提出完整矩陣:
不只「雙新高共振」,還有「價格落後×營收創高」(基本面先行/補漲候選 vs 價值陷阱)等格。

═══ 設計(預先註冊) ═══
形成日: 每月13日後首個交易日(上月營收10日前已全公布),2018-02~2026-04(~99個月頻決策點);
池=20日均額>=0.3億(前一日止)。進場=形成日收盤(可執行),outcome=k20/40/60前瞻demean(減TAIEX)。
價格軸(形成日): dist=收盤/126日(半年)滾動高-1 → P1貼高帶(dist>=-2%)/P2中間/P3落後(dist<=-20%)。
營收軸: R1=最近兩個公布月營收皆創12月高(v3驗證的「連創」一般化)/R0=否;streak=截至上月的連創月數。
毛利軸(④拆解+附錄): 最新已公告季gm_chg(avail_date口徑)>0/<=0/無;gm_lv創4季高(獲利品質新高)。
段落: A六宮格 B④格拆解(P3×R1×gm) C lead-lag路徑(P1R1的前月狀態: 營收先行/價格先行/持續雙高)
D streak劑量(1/2/3+) E附錄三新高(P1×R1×gm_lv創4季高) F題材成員split。
統計: 月群bootstrap(形成月=集群)+逐年+勝率/賺賠比;k40主判讀。
已知限制: 月頻重疊窗(k40跨2個形成月)靠月群集群;除權息未還原(保守);
P3落後格天生混「錯殺」與「有理由的弱」(B段就是在拆這個);對照數字引用母卷不重算。
用法: python 研究腳本/綜合策略/build_dual_newhigh_matrix.py  (從根目錄執行,鐵律)
產出: 研究報告/research_dual_newhigh_matrix.html + console
"""
import sqlite3
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

DB = "capital_flow.db"
OUT = "研究報告/research_dual_newhigh_matrix.html"
LIQ_MIN = 0.3e8
K_LIST = [20, 40, 60]
P_HIGH_TH = -0.02
P_LAG_TH = -0.20
BUFFER_DAYS = 5
STATUTORY = {1: (5, 15, 0), 2: (8, 14, 0), 3: (11, 14, 0), 4: (3, 31, 1)}
rng = np.random.default_rng(20260807)


def avail_date(qe):
    q = (qe.month - 1) // 3 + 1
    m, d, yoff = STATUTORY[q]
    return pd.Timestamp(qe.year + yoff, m, d) + pd.Timedelta(days=BUFFER_DAYS)


def main():
    conn = sqlite3.connect(DB, timeout=60)
    rev = pd.read_sql("SELECT code, date, revenue FROM fm_month_rev", conn, parse_dates=["date"])
    px = pd.read_sql("SELECT code,date,close,money FROM fm_daily_price "
                     "WHERE date>='2017-01-01' AND close>0 AND money>0", conn)
    tai = pd.read_sql("SELECT date,close FROM index_daily WHERE market='TAIEX' "
                      "AND date>='2017-01-01' ORDER BY date", conn)
    fin = pd.read_sql("SELECT code, date, gross_margin FROM tw_quarterly_financials_history",
                      conn, parse_dates=["date"])
    theme_codes = {r[0] for r in conn.execute(
        "select distinct code from classification where country='台'")}
    conn.close()

    # 營收: 月創12月高 + 連創streak
    rev_w = rev.pivot_table(index="date", columns="code", values="revenue", aggfunc="first").sort_index()
    hi_m = (rev_w >= rev_w.rolling(12, min_periods=12).max()) & rev_w.notna()
    streak = hi_m.astype(int).copy()
    arr = hi_m.values.astype(int)
    for i in range(1, len(arr)):
        arr[i] = np.where(hi_m.values[i], arr[i - 1] + 1, 0)
    streak = pd.DataFrame(arr, index=hi_m.index, columns=hi_m.columns)

    # 價格
    C = px.pivot_table(index="date", columns="code", values="close", aggfunc="first").sort_index()
    MN = px.pivot_table(index="date", columns="code", values="money", aggfunc="first").sort_index()
    tai = tai.set_index("date")["close"]
    t_dates = np.array(C.index)
    liq20 = MN.rolling(20, min_periods=15).mean().shift(1)
    hi126 = C.rolling(126, min_periods=100).max()
    Cf = C.ffill(limit=5)
    tai_f = tai.reindex(C.index).ffill()

    # 毛利: gm_chg + gm_lv創4季高, per code (avail排序)
    fundmap = {}
    for code, g in fin.groupby("code"):
        g = g.sort_values("date")
        qidx = pd.PeriodIndex(g.date, freq="Q")
        g = g.set_index(qidx)
        g = g[~g.index.duplicated(keep="first")]
        full = pd.period_range(g.index.min(), g.index.max(), freq="Q")
        g = g.reindex(full)
        gm = g.gross_margin * 100
        chg = gm - gm.shift(1)
        hi4 = gm >= gm.rolling(4, min_periods=4).max()
        av = np.array([np.datetime64(avail_date(p.end_time.normalize())) for p in g.index])
        ok = g.gross_margin.notna().values
        fundmap[code] = (av[ok], chg.values[ok], hi4.values[ok])

    def gm_at(code, d64):
        fm = fundmap.get(code)
        if fm is None:
            return np.nan, False
        k = int(np.searchsorted(fm[0], d64, side="right")) - 1
        if k < 0 or (pd.Timestamp(d64) - pd.Timestamp(fm[0][k])).days > 200:
            return np.nan, False
        return fm[1][k], bool(fm[2][k])

    # 形成日循環
    months = [m for m in rev_w.index if "2018-02-01" <= str(m)[:10] <= "2026-04-30"]
    recs = []
    for m in months:
        f_ts = m + pd.Timedelta(days=12)          # 該月13日
        f_i = int(np.searchsorted(t_dates, f_ts.strftime("%Y-%m-%d")))
        if f_i >= len(t_dates) - max(K_LIST) - 1:
            continue
        f_d = t_dates[f_i]
        d64 = np.datetime64(f_d)
        # 該形成日已知的最近兩個營收月=m-1, m-2
        try:
            mi = rev_w.index.get_loc(m)
        except KeyError:
            continue
        if mi < 2:
            continue
        m1, m2 = rev_w.index[mi - 1], rev_w.index[mi - 2]
        h1, h2 = hi_m.loc[m1], hi_m.loc[m2]
        stk = streak.loc[m1]
        close_row = C.iloc[f_i]
        dist_row = close_row / hi126.iloc[f_i] - 1
        liq_row = liq20.iloc[f_i]
        for code in C.columns:
            c0 = close_row[code]
            if pd.isna(c0) or pd.isna(liq_row[code]) or liq_row[code] < LIQ_MIN:
                continue
            dist = dist_row[code]
            if pd.isna(dist):
                continue
            r1 = bool(h1.get(code, False)) and bool(h2.get(code, False))
            pcell = "P1貼高" if dist >= P_HIGH_TH else ("P3落後" if dist <= P_LAG_TH else "P2中間")
            gmc, gmhi4 = gm_at(code, d64)
            rec = {"code": code, "f": str(f_d)[:10], "m": str(m)[:7],
                   "pcell": pcell, "r1": r1, "streak": int(stk.get(code, 0)),
                   "gm": gmc, "gmhi4": gmhi4, "theme": code in theme_codes, "dist": dist}
            ok = True
            for k in K_LIST:
                x = Cf.iat[f_i + k, Cf.columns.get_loc(code)]
                if pd.isna(x):
                    ok = False
                    break
                rec[f"dm{k}"] = (x / c0 - 1) - (tai_f.iloc[f_i + k] / tai_f.iloc[f_i] - 1)
            if ok:
                recs.append(rec)
    E = pd.DataFrame(recs)
    E["year"] = E.f.str[:4]
    print(f"[panel] {len(E):,}筆 code×形成月({E.m.nunique()}個月, {E.f.min()}~{E.f.max()}); "
          f"R1={E.r1.sum():,} P1={int((E.pcell == 'P1貼高').sum()):,} P3={int((E.pcell == 'P3落後').sum()):,}")

    # 前月狀態(lead-lag用): 同code上一個形成月的(pcell, r1)
    E = E.sort_values(["code", "f"])
    E["prev_p"] = E.groupby("code").pcell.shift(1)
    E["prev_r"] = E.groupby("code").r1.shift(1)

    def boot(vals, ms, n_iter=1000):
        v = pd.DataFrame({"v": vals, "m": ms}).dropna()
        if len(v) < 30 or v.m.nunique() < 8:
            return None
        grp = {k: g.v.values for k, g in v.groupby("m")}
        keys = list(grp)
        means = [np.mean(np.concatenate([grp[k] for k in rng.choice(keys, len(keys))]))
                 for _ in range(n_iter)]
        lo, hi = np.percentile(means, [2.5, 97.5])
        return {"mean": float(v.v.mean()), "lo": float(lo), "hi": float(hi),
                "sig": bool(lo > 0 or hi < 0)}

    def line(sub, lab, out):
        if len(sub) < 100:
            print(f"  {lab:<30} n={len(sub)} 不足")
            return
        r = {"lab": lab, "n": len(sub)}
        for k in K_LIST:
            b = boot(sub[f"dm{k}"].values, sub.m.values)
            v = sub[f"dm{k}"]
            w, l = v[v > 0], v[v <= 0]
            r[k] = {"mean": v.mean() * 100, "b": b, "win": len(w) / len(v) * 100,
                    "wl": (w.mean() / abs(l.mean())) if len(w) and len(l) else np.nan}
        y = sub.groupby("year")[f"dm40"].mean()
        r["yr"] = f"{int((y > 0).sum())}/{len(y)}"
        out.append(r)
        f40 = r[40]
        print(f"  {lab:<30} n={r['n']:>7,} k20:{r[20]['mean']:+.2f} k40:{f40['mean']:+.2f}"
              + (f"[{f40['b']['lo'] * 100:+.2f},{f40['b']['hi'] * 100:+.2f}]{'✓' if f40['b']['sig'] else ''}"
                 if f40["b"] else "")
              + f" k60:{r[60]['mean']:+.2f} 勝率{f40['win']:.0f}% 賺賠{f40['wl']:.2f} 逐年{r['yr']}")

    print("\n" + "=" * 96, "\nA) 六宮格(k20/40/60 demean%, k40主判讀)")
    A = []
    for pc in ("P1貼高", "P2中間", "P3落後"):
        for r1, rl in ((True, "R1營收連創高"), (False, "R0未創高")):
            line(E[(E.pcell == pc) & (E.r1 == r1)], f"{pc}×{rl}", A)

    print("\nB) ④格拆解: P3落後×R1營收創高 × 毛利率(價值陷阱 vs 錯殺)")
    B = []
    p3r1 = E[(E.pcell == "P3落後") & E.r1]
    line(p3r1[p3r1.gm > 0], "④a P3×R1×gm改善(錯殺候選)", B)
    line(p3r1[p3r1.gm <= 0], "④b P3×R1×gm惡化(價值陷阱?)", B)
    line(p3r1[p3r1.gm.isna()], "④c P3×R1×無財報", B)

    print("\nC) lead-lag路徑: 本月P1×R1(雙新高)者,按前月狀態分")
    Cc = []
    dd = E[(E.pcell == "P1貼高") & E.r1 & E.prev_p.notna()]
    line(dd[(dd.prev_p != "P1貼高") & (dd.prev_r == True)], "營收先行(前月R1但價未貼高)", Cc)
    line(dd[(dd.prev_p == "P1貼高") & (dd.prev_r == False)], "價格先行(前月貼高但R0)", Cc)
    line(dd[(dd.prev_p == "P1貼高") & (dd.prev_r == True)], "持續雙高(前月已P1R1)", Cc)

    print("\nD) streak劑量反應(截至上月連創月數,全池)")
    D = []
    for lab, mask in [("streak=1", E.streak == 1), ("streak=2", E.streak == 2),
                      ("streak=3+", E.streak >= 3), ("streak=0(對照)", E.streak == 0)]:
        line(E[mask], lab, D)

    print("\nE) 附錄: 三新高(P1×R1×毛利率創4季高)")
    Ee = []
    line(E[(E.pcell == "P1貼高") & E.r1 & E.gmhi4], "三新高(價+營收+毛利)", Ee)
    line(E[(E.pcell == "P1貼高") & E.r1 & (~E.gmhi4) & E.gm.notna()], "雙新高但毛利未創高", Ee)

    print("\nF) 題材成員split(P1×R1)")
    Ff = []
    p1r1 = E[(E.pcell == "P1貼高") & E.r1]
    line(p1r1[p1r1.theme], "P1×R1×題材成員", Ff)
    line(p1r1[~p1r1.theme], "P1×R1×非題材", Ff)

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

    def tbl(rows, hl_labs=()):
        h = ("<div class='scroll'><table><tr><th>組</th><th>n</th>"
             + "".join(f"<th>k{k} demean/CI</th>" for k in K_LIST)
             + "<th>k40勝率/賺賠</th><th>逐年40</th></tr>")
        for r in rows:
            cells = ""
            for k in K_LIST:
                s = r[k]
                ci = (f"<br><span style='color:#777;font-size:10.5px'>[{s['b']['lo'] * 100:+.2f},"
                      f"{s['b']['hi'] * 100:+.2f}]{'✓' if s['b']['sig'] else ''}</span>" if s["b"] else "")
                cells += f"<td>{s['mean']:+.2f}%{ci}</td>"
            s40 = r[40]
            hl = " class='hl'" if any(x in r["lab"] for x in hl_labs) else ""
            h += (f"<tr{hl}><th>{r['lab']}</th><td>{r['n']:,}</td>{cells}"
                  f"<td>{s40['win']:.0f}%/{s40['wl']:.2f}</td><td>{r['yr']}</td></tr>")
        return h + "</table></div>"

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>雙新高九宮格(2026-08-07)</title><style>{CSS}</style></head><body>
<h1>🧩 雙新高九宮格考卷: 價格狀態 × 營收創高 全矩陣</h1>
<div class="note">形成日=每月13日後首個交易日(上月營收全公布),2018-02~2026-04共{E.m.nunique()}個月頻決策點,
panel {len(E):,}筆;池=20日均額>=0.3億;進場=形成日收盤,outcome=k20/40/60 demean(減TAIEX),月群bootstrap。
價格軸: P1貼高=收盤距126日高2%內 / P3落後=距高>20% / P2中間。營收軸: R1=最近兩個公布月皆創12月高。
母卷: newhigh(價格突破)/rev_preposition(營收埋伏)/newhigh_gm(毛利門檻)。</div>
<h2>A) 六宮格</h2>
{tbl(A, ("P1貼高×R1", "P3落後×R1"))}
<h2>B) ④格拆解: 價格落後×營收創高 × 毛利率(使用者格: 錯殺 vs 價值陷阱)</h2>
{tbl(B, ("④a",))}
<h2>C) lead-lag路徑(本月雙新高者的前月狀態)</h2>
{tbl(Cc)}
<h2>D) 營收連創月數劑量反應</h2>
{tbl(D)}
<h2>E) 附錄: 三新高(價+營收+毛利率創4季高)</h2>
{tbl(Ee, ("三新高",))}
<h2>F) 題材成員split(P1×R1)</h2>
{tbl(Ff)}
<h2>⚖️ 判決(2026-08-07首輪)</h2>
<ul>
<li><span class="verdict v-good">①雙新高共振確認=全專案季級最強格</span>
P1貼高×R1營收連創: <b>k40 demean+8.90%✓[+4.40,+14.22]/勝率55%/賺賠比2.13/逐年9/9全正</b>
(k60+10.78%);交乘增量明確——遠大於兩個單邊之和(P1×R0僅+1.62/P2×R1僅+3.09)=真共振非相加。
題材成員版<b>+10.93%✓/勝率59%/賺賠2.35</b>;約5檔/月,月頻可操作。對照: 三重門檻k40 dm+3.84
——雙新高量級更高(口徑差異: 狀態月頻vs事件層,方向結論不變)。</li>
<li><span class="verdict v-warn">②使用者格(P3落後×R1營收創高)=方向正但薄,正確用法是「預備名單」</span>
整格+1.90%含0;毛利拆解方向如預期(④a gm改善+2.51 &gt; ④b惡化+1.71)但皆含0=「錯殺修復」
存在但單獨不可交易。<b>它的價值在C段</b>: 落後/中間帶的營收創高股一旦突破進貼高帶
(lead-lag「營收先行」路徑)=+6.49%✓——<b>P3×R1不是買點,是觀察名單;突破那一刻才是買點</b>。</li>
<li><span class="verdict v-good">③lead-lag: 「營收先行→價格跟上」是雙新高的最佳形態</span>
前月R1但價未貼高→本月進貼高帶: k40+6.49%✓/k60+10.22%(n=136)——基本面先確認、價格剛突破的
組合,正好是「用營收創高預篩、等價格突破觸發」的可執行流程(價格先行/持續雙高路徑樣本不足待累積)。</li>
<li><b>④streak甜蜜點=連創2個月</b>(+4.04✓ &gt; 1個月+2.47 &gt; 3+個月+3.11)——v3埋伏配方的
「兩月連創」正好是最佳劑量,3個月以上不再加值(高基期效應);streak=0全池-1.17✓=不創高的股票
整體輸大盤(池內demean的另一面)。</li>
<li><b>⑤毛利率創高第三維=冗餘</b>: 三新高+9.20✓ vs 雙新高但毛利未創高+11.13✓——毛利層不加值
(與52週突破吸收gm同理: 雙新高已隱含基本面確認),<b>不用疊,兩個新高就夠</b>。</li>
<li><b>⑥雙新高讓非題材股也活了</b>(+6.57%✓ vs 純價格突破時非題材為負)——營收創高扮演了
「題材故事」的替代角色=基本面確認;雙新高比純價格突破更普適,但題材成員版仍更強。</li>
<li><b>⑦誠實保留</b>: 月頻狀態面板同股連月重複入樣(P1R1狀態平均持續數月),月群bootstrap只部分
處理;P1R1格n=476(獨立股數更少);題材split沿名單偏誤。下一步=雙新高月頻掃描live化+與三重門檻
合併成單一季級持股框架。</li>
</ul>
<h2>已知限制</h2>
<div class="note">①月頻形成×k40/60前瞻=重疊窗,月群bootstrap集群處理;②除權息未還原(保守偏誤);
③P1「貼高帶」為狀態定義(含持續創高股),與newhigh卷「獨立突破」(事件定義)不同口徑,
兩卷數字不可直接相比;④P3落後格的「落後」原因異質(本卷只用毛利率拆,產業逆風/一次性因素未拆);
⑤六宮格×多段=多重比較,主判讀靠k40+跨窗一致+逐年,不靠單格CI;⑥題材成員=事後名單偏誤沿卷。</div>
<div class="note">維運: python 研究腳本/綜合策略/build_dual_newhigh_matrix.py(從根目錄執行)。</div>
</body></html>"""
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n[report] 已輸出 {OUT}")


if __name__ == "__main__":
    main()
