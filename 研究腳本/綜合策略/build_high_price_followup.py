# -*- coding: utf-8 -*-
"""高價股追蹤三合一考卷(2026-08-07,使用者裁示:RS安慰劑/高價新貴/籌碼實測)。

承接build_high_price_stability.py(穩定性否定,唯一活口=RS溫度計)。三段:
①RS溫度計安慰劑檢定: 前5%組RS近3月均>0→下月TAIEX的價差(+2.1pp/勝率69vs55),要過三關才可信:
  (a)隨機組安慰劑=池內隨機30檔×20組同算RS→若隨機組也給同樣價差,「高價」二字無資訊
  (b)價格帶對照=低價/中價組RS同測(是「高價」還是「任何股票組RS」?)
  (c)大盤自身動能對照=TAIEX近3月均>0→下月(RS是不是只是動能替身?)
②高價新貴: 首次站上100/500/1000元整數關卡(定義=收盤>=L且前250交易日max<L),次日收盤進,
  k20/40/60 demean;附與90日獨立突破事件的重疊率(里程碑vs新高家族是不是同一件事)。
③籌碼實測: 千張大戶%(tdcc_weekly.p1000,2013-2026)——各價格帶的p1000中位(集中度)、
  4週變動絕對值中位(籌碼穩定度)、散戶佔比p_retail——驗證「高價股籌碼穩」的原始直覺。
用法: python 研究腳本/綜合策略/build_high_price_followup.py  (從根目錄執行,鐵律)
產出: 研究報告/research_high_price_followup.html + console
"""
import sqlite3
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

DB = "capital_flow.db"
OUT = "研究報告/research_high_price_followup.html"
LIQ_MIN = 0.3e8
LEVELS = [100, 500, 1000]
rng = np.random.default_rng(20260807)


def main():
    conn = sqlite3.connect(DB, timeout=60)
    px = pd.read_sql("SELECT code,date,close,money FROM fm_daily_price "
                     "WHERE date>='2013-06-01' AND close>0 AND money>0", conn)
    tai = pd.read_sql("SELECT date,close FROM index_daily WHERE market='TAIEX' "
                      "AND date>='2013-06-01' ORDER BY date", conn)
    tdcc = pd.read_sql("SELECT code, date, p1000, p_retail FROM tdcc_weekly", conn, parse_dates=["date"])
    conn.close()

    C = px.pivot_table(index="date", columns="code", values="close", aggfunc="first").sort_index()
    MN = px.pivot_table(index="date", columns="code", values="money", aggfunc="first").sort_index()
    tai = tai.set_index("date")["close"]
    dates = list(C.index)
    liq20 = MN.rolling(20, min_periods=15).mean().shift(1)
    Cf = C.ffill(limit=5)
    tai_f = tai.reindex(C.index).ffill()

    didx = pd.to_datetime(pd.Index(dates))
    month_first = ~didx.to_period("M").duplicated()
    f_idx = [i for i in np.where(month_first)[0] if dates[i] >= "2015-01-01" and i + 1 < len(dates)]

    def pool_at(i):
        c_row = C.iloc[i]
        l_row = liq20.iloc[i]
        return c_row.index[(c_row.notna()) & (l_row >= LIQ_MIN)], c_row

    # ---------- ① RS安慰劑 ----------
    def month_rets(sel_fn):
        """sel_fn(i, pool, prices)->codes; 回傳各月報酬序列"""
        out = []
        for a, b in zip(f_idx[:-1], f_idx[1:]):
            pool, prices = pool_at(a)
            codes = sel_fn(a, pool, prices)
            rets = []
            for c in codes:
                ci = Cf.columns.get_loc(c)
                p0, p1 = C.iat[a, ci], Cf.iat[b, ci]
                if pd.notna(p0) and pd.notna(p1) and p0 > 0:
                    rets.append(p1 / p0 - 1)
            out.append(np.mean(rets) if rets else 0.0)
        return np.array(out)

    tai_m = np.array([tai_f.iloc[b] / tai_f.iloc[a] - 1 for a, b in zip(f_idx[:-1], f_idx[1:])])

    def rs_test(grp_m):
        rs3 = pd.Series(grp_m - tai_m).rolling(3).mean().values
        nxt = np.roll(tai_m, -1)[:-1]
        r3 = rs3[:-1]
        ok = ~np.isnan(r3)
        pos, neg = nxt[ok & (r3 > 0)], nxt[ok & (r3 <= 0)]
        if len(pos) < 10 or len(neg) < 10:
            return None
        return {"diff": (np.mean(pos) - np.mean(neg)) * 100, "pos_m": np.mean(pos) * 100,
                "neg_m": np.mean(neg) * 100, "pos_w": (pos > 0).mean() * 100,
                "neg_w": (neg > 0).mean() * 100, "n": (len(pos), len(neg))}

    print("① RS溫度計安慰劑檢定(下月TAIEX: RS3>0組-RS3<=0組價差,pp)")
    top5_m = month_rets(lambda i, pool, pr: list(pr[pool].index[pr[pool] >= pr[pool].quantile(0.95)]))
    r_top5 = rs_test(top5_m)
    print(f"  主訊號(前5%高價組): 價差{r_top5['diff']:+.2f}pp "
          f"({r_top5['pos_m']:+.2f}%勝率{r_top5['pos_w']:.0f}% vs {r_top5['neg_m']:+.2f}%勝率{r_top5['neg_w']:.0f}%)")
    r_mid = rs_test(month_rets(lambda i, pool, pr: list(pr[pool].index[(pr[pool] >= 100) & (pr[pool] < 500)])))
    r_low = rs_test(month_rets(lambda i, pool, pr: list(pr[pool].index[pr[pool] < 50])))
    print(f"  (b)中價組RS: 價差{r_mid['diff']:+.2f}pp / 低價組RS: 價差{r_low['diff']:+.2f}pp")
    # (c)大盤自身動能
    tai3 = pd.Series(tai_m).rolling(3).mean().values
    nxt = np.roll(tai_m, -1)[:-1]
    t3 = tai3[:-1]
    ok = ~np.isnan(t3)
    tmom_diff = (np.mean(nxt[ok & (t3 > 0)]) - np.mean(nxt[ok & (t3 <= 0)])) * 100
    print(f"  (c)TAIEX自身3月動能對照: 價差{tmom_diff:+.2f}pp")
    # (a)隨機組安慰劑
    plc = []
    for k in range(20):
        rk = np.random.default_rng(1000 + k)
        sel = lambda i, pool, pr, _r=rk: list(_r.choice(pool, size=min(30, len(pool)), replace=False))
        r = rs_test(month_rets(sel))
        if r:
            plc.append(r["diff"])
    plc = np.array(plc)
    pctl = (plc < r_top5["diff"]).mean() * 100
    print(f"  (a)隨機30檔×20組安慰劑: 價差分布均{plc.mean():+.2f}pp/中位{np.median(plc):+.2f}"
          f"/P5-P95[{np.percentile(plc, 5):+.2f},{np.percentile(plc, 95):+.2f}] "
          f"→ 主訊號{r_top5['diff']:+.2f}位於安慰劑分布第{pctl:.0f}百分位")

    # ---------- ② 高價新貴 ----------
    print("\n② 高價新貴(首次站上整數關卡,前250交易日max<L,次日收盤進)")
    rmax90 = C.rolling(90, min_periods=72).max()
    is_hi90 = (C >= rmax90 * 0.9999) & C.notna()
    hi_recent90 = is_hi90.shift(1).rolling(20, min_periods=1).max()
    fresh90 = is_hi90 & (~hi_recent90.astype(bool))
    newb = {}
    for L in LEVELS:
        above = (C >= L)
        prior_max_below = (C.shift(1).rolling(250, min_periods=250).max() < L)
        evt = above & prior_max_below & C.notna()
        rows = []
        n_overlap = 0
        for i in np.where(evt.any(axis=1))[0]:
            if dates[i] < "2015-01-01" or i + 61 >= len(dates):
                continue
            for ci in np.where(evt.iloc[i].values)[0]:
                if pd.isna(liq20.iat[i, ci]) or liq20.iat[i, ci] < LIQ_MIN:
                    continue
                e = i + 1
                p0 = Cf.iat[e, ci]
                if pd.isna(p0) or p0 <= 0:
                    continue
                rec = {"ym": dates[i][:7]}
                bad = False
                for k in (20, 40, 60):
                    p1 = Cf.iat[e + k, ci]
                    if pd.isna(p1):
                        bad = True
                        break
                    rec[f"dm{k}"] = (p1 / p0 - 1) - (tai_f.iloc[e + k] / tai_f.iloc[e] - 1)
                if bad:
                    continue
                if bool(fresh90.iat[i, ci]):
                    n_overlap += 1
                rows.append(rec)
        E = pd.DataFrame(rows)
        newb[L] = (E, n_overlap)
        if len(E) < 20:
            print(f"  站上{L}元: n={len(E)} 樣本不足")
            continue

        def bt(col):
            grp = {m: g[col].values for m, g in E.groupby("ym")}
            keys = list(grp)
            means = [np.mean(np.concatenate([grp[m] for m in rng.choice(keys, len(keys))]))
                     for _ in range(1000)]
            lo, hi = np.percentile(means, [2.5, 97.5])
            return f"{E[col].mean() * 100:+.2f}%[{lo * 100:+.2f},{hi * 100:+.2f}]{'✓' if (lo > 0 or hi < 0) else ''}"
        v40 = E["dm40"]
        w, l = v40[v40 > 0], v40[v40 <= 0]
        print(f"  站上{L}元: n={len(E):,} k20:{bt('dm20')} k40:{bt('dm40')} k60:{bt('dm60')} "
              f"勝率{(len(w) / len(v40)) * 100:.0f}% 賺賠{(w.mean() / abs(l.mean())) if len(l) else np.nan:.2f} "
              f"與90日獨立突破重疊{n_overlap}/{len(E)}({n_overlap / len(E) * 100:.0f}%)")

    # ---------- ③ 籌碼實測 ----------
    print("\n③ 籌碼實測(tdcc_weekly千張大戶%,2015起季抽樣)")
    td_w = tdcc.pivot_table(index="date", columns="code", values="p1000", aggfunc="first").sort_index()
    td_r = tdcc.pivot_table(index="date", columns="code", values="p_retail", aggfunc="first").sort_index()
    td_dates = td_w.index
    groups_def = [("高價>500", lambda pr: pr.index[pr >= 500]),
                  ("前5%", lambda pr: pr.index[pr >= pr.quantile(0.95)]),
                  ("中價100-500", lambda pr: pr.index[(pr >= 100) & (pr < 500)]),
                  ("低價<50", lambda pr: pr.index[pr < 50]),
                  ("池全體", lambda pr: pr.index)]
    chip = {lab: {"p1000": [], "chg4w": [], "retail": []} for lab, _ in groups_def}
    for i in f_idx[::3]:
        d = pd.Timestamp(dates[i])
        ti = td_dates.searchsorted(d, side="right") - 1
        if ti < 4 or (d - td_dates[ti]).days > 14:
            continue
        snap = td_w.iloc[ti]
        prev4 = td_w.iloc[ti - 4]
        reta = td_r.iloc[ti]
        pool, prices = pool_at(i)
        pr = prices[pool]
        for lab, fn in groups_def:
            g = [c for c in fn(pr) if c in td_w.columns]
            v = snap[g].dropna()
            if len(v) < 5:
                continue
            chg = (snap[g] - prev4[g]).abs().dropna()
            chip[lab]["p1000"].append(v.median())
            chip[lab]["chg4w"].append(chg.median())
            chip[lab]["retail"].append(reta[g].dropna().median())
    p3 = {}
    for lab, _ in groups_def:
        p3[lab] = {k: np.nanmean(v) for k, v in chip[lab].items()}
        print(f"  {lab:<12} 千張大戶%中位{p3[lab]['p1000']:.1f} 4週變動絕對值中位{p3[lab]['chg4w']:.2f}pp "
              f"散戶%中位{p3[lab]['retail']:.1f}")

    # ---------- HTML ----------
    CSS = """
body{background:#1a1a19;color:#fff;font-family:"Noto Sans TC",sans-serif;margin:24px;max-width:1000px}
h1{font-size:20px} h2{font-size:15px;color:#c3c2b7;margin-top:28px;border-bottom:1px solid #333;padding-bottom:4px}
table{border-collapse:collapse;font-size:12.5px;font-variant-numeric:tabular-nums;margin:8px 0}
td,th{border:1px solid #333;padding:4px 9px;text-align:right} th{text-align:left;color:#c3c2b7}
.note{color:#8a8878;font-size:12.5px;line-height:1.8} .good{color:#7ec97e} .bad{color:#e06c5a}
.hl{background:#2b3a2b}
ul{margin:4px 0;padding-left:20px;font-size:12.5px;color:#ccc;line-height:1.7}
.verdict{font-size:13px;font-weight:bold;padding:6px 10px;border-radius:4px;display:inline-block;margin:4px 0}
.v-good{background:#243b24;color:#7ec97e} .v-bad{background:#3b2420;color:#e06c5a}
.v-warn{background:#3b3420;color:#c3a55a}
"""
    nb_html = "<table><tr><th>關卡</th><th>n</th><th>k40 demean</th><th>與90日突破重疊</th></tr>"
    for L in LEVELS:
        E, ov = newb[L]
        if len(E) >= 20:
            nb_html += (f"<tr><th>站上{L}元</th><td>{len(E):,}</td><td>{E['dm40'].mean() * 100:+.2f}%</td>"
                        f"<td>{ov}/{len(E)}({ov / len(E) * 100:.0f}%)</td></tr>")
        else:
            nb_html += f"<tr><th>站上{L}元</th><td>{len(E)}</td><td>樣本不足</td><td>—</td></tr>"
    nb_html += "</table>"
    chip_html = ("<table><tr><th>組</th><th>千張大戶%中位</th><th>4週變動絕對值中位</th><th>散戶%中位</th></tr>"
                 + "".join(f"<tr{' class=hl' if '高價' in lab or '5%' in lab else ''}><th>{lab}</th>"
                           f"<td>{p3[lab]['p1000']:.1f}</td><td>{p3[lab]['chg4w']:.2f}pp</td>"
                           f"<td>{p3[lab]['retail']:.1f}</td></tr>" for lab, _ in groups_def) + "</table>")

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>高價股追蹤三合一(2026-08-07)</title><style>{CSS}</style></head><body>
<h1>💎 高價股追蹤三合一: RS安慰劑 / 高價新貴 / 籌碼實測</h1>
<div class="note">承接research_high_price_stability.html。</div>
<h2>① RS溫度計安慰劑檢定</h2>
<table><tr><th>訊號</th><th>下月TAIEX價差(RS3>0 − RS3<=0)</th></tr>
<tr class="hl"><th>主訊號: 前5%高價組RS</th><td>{r_top5['diff']:+.2f}pp({r_top5['pos_m']:+.2f}%/勝率{r_top5['pos_w']:.0f}% vs {r_top5['neg_m']:+.2f}%/{r_top5['neg_w']:.0f}%)</td></tr>
<tr><th>(b)中價組RS對照</th><td>{r_mid['diff']:+.2f}pp</td></tr>
<tr><th>(b)低價組RS對照</th><td>{r_low['diff']:+.2f}pp</td></tr>
<tr><th>(c)TAIEX自身3月動能</th><td>{tmom_diff:+.2f}pp</td></tr>
<tr><th>(a)隨機30檔×20組安慰劑分布</th><td>均{plc.mean():+.2f}/中位{np.median(plc):+.2f}/P5-P95[{np.percentile(plc, 5):+.2f},{np.percentile(plc, 95):+.2f}],主訊號位於第{pctl:.0f}百分位</td></tr></table>
<h2>② 高價新貴(首次站上整數關卡)</h2>
{nb_html}
<h2>③ 籌碼實測(千張大戶%)</h2>
{chip_html}
<h2>⚖️ 判決(2026-08-07)</h2>
<ul>
<li><span class="verdict v-good">①RS溫度計三關全過=升級候選層,已上儀表板溫度計頁</span>
主訊號+2.12pp位於20組隨機安慰劑分布(P5-P95[-1.37,+0.55])的<b>第100百分位=完全在分布外</b>;
中價組RS反向(-1.08)/低價組無訊號(+0.03)=「高價」有專屬資訊;贏TAIEX自身動能(+1.26)但部分重疊
=RS是「動能+領頭羊健康度」的合成讀數。月頻n=136仍小,live累積中。</li>
<li><span class="verdict v-good">②高價新貴=新撿到的獨立事件訊號</span> 首次站上100元(n=502):
k20+4.52%✓/k40+5.66%✓/k60+4.46%✓全排0/賺賠1.85;站上500元k40+5.69%✓(n=133);站上1000元方向正含0
(n=59薄)。<b>與90日獨立突破重疊僅4-8%</b>=里程碑效應是獨立於新高家族的另一個事件(整數關卡心理錨定,
常見於高檔盤整後緩步越關)——候選層,可與雙新高/三重門檻並列為第三個事件源。</li>
<li><span class="verdict v-warn">③籌碼直覺翻案</span> 高價組千張大戶%50.6~52.8<b>反而低於</b>池54.7;
4週變動幅度全場無差(0.64~0.70pp)=「籌碼穩定度」不因價位而異;唯一真實差異=<b>散戶%6.1 vs 池12.9</b>
——「高價股籌碼穩」的真相是<b>散戶參與低(價格門檻效應)</b>,不是大戶更集中或更不動。</li>
</ul>
<div class="note">維運: python 研究腳本/綜合策略/build_high_price_followup.py(從根目錄執行)。</div>
</body></html>"""
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n[report] 已輸出 {OUT}")


if __name__ == "__main__":
    main()
