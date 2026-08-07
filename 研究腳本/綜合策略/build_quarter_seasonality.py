# -*- coding: utf-8 -*-
"""季度季節性考卷(2026-08-07,使用者提問「哪一個季度的平均表現最好」)。

三層: ①大盤層=TAIEX逐月/逐季季節性(1999起全史+2015起近代兩窗,誠實看regime穩定度)
②訊號層=雙新高月頻事件、三重門檻事件的k40 demean按「進場所屬季」分組(訊號在哪一季進場最肥)
③既有判決引用=埋伏配方Q4王者(+9.20✓)/Q1-Q3含0(rev_preposition卷)。
統計: 月/季群bootstrap;季節性樣本天生薄(每季只有N年個樣本),誠實標註觀察層。
用法: python 研究腳本/綜合策略/build_quarter_seasonality.py  (從根目錄執行,鐵律)
產出: 研究報告/research_quarter_seasonality.html + console
"""
import sqlite3
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

DB = "capital_flow.db"
OUT = "研究報告/research_quarter_seasonality.html"
LIQ_MIN = 0.3e8
FRESH_GAP = 20
BUFFER_DAYS = 5
STATUTORY = {1: (5, 15, 0), 2: (8, 14, 0), 3: (11, 14, 0), 4: (3, 31, 1)}
rng = np.random.default_rng(20260807)


def avail_date(qe):
    q = (qe.month - 1) // 3 + 1
    m, d, yoff = STATUTORY[q]
    return pd.Timestamp(qe.year + yoff, m, d) + pd.Timedelta(days=BUFFER_DAYS)


def main():
    conn = sqlite3.connect(DB, timeout=60)
    tai_full = pd.read_sql("SELECT date,close FROM index_daily WHERE market='TAIEX' ORDER BY date", conn)
    px = pd.read_sql("SELECT code,date,close,money FROM fm_daily_price "
                     "WHERE date>='2013-01-01' AND close>0 AND money>0", conn)
    rev = pd.read_sql("SELECT code, date, revenue FROM fm_month_rev", conn, parse_dates=["date"])
    fin = pd.read_sql("SELECT code, date, gross_margin FROM tw_quarterly_financials_history",
                      conn, parse_dates=["date"])
    theme_codes = {r[0] for r in conn.execute(
        "select distinct code from classification where country='台'")}
    conn.close()

    # ---------- ①大盤層 ----------
    tai_full["date"] = pd.to_datetime(tai_full["date"])
    tai_full = tai_full.set_index("date")["close"]
    mret = tai_full.resample("ME").last().pct_change().dropna()

    def season_table(s, lab):
        print(f"\n【TAIEX {lab}】")
        rows_m = []
        for m in range(1, 13):
            v = s[s.index.month == m]
            rows_m.append({"m": m, "n": len(v), "mean": v.mean() * 100, "win": (v > 0).mean() * 100})
        for r in rows_m:
            print(f"  {r['m']:>2}月: n={r['n']:>2} 均{r['mean']:+.2f}% 勝率{r['win']:.0f}%")
        rows_q = []
        qret = s.groupby([s.index.year, s.index.quarter]).apply(lambda x: (1 + x).prod() - 1)
        for q in range(1, 5):
            v = qret[qret.index.get_level_values(1) == q]
            rows_q.append({"q": q, "n": len(v), "mean": v.mean() * 100, "win": (v > 0).mean() * 100})
            print(f"  Q{q}: n={rows_q[-1]['n']} 均{rows_q[-1]['mean']:+.2f}% 勝率{rows_q[-1]['win']:.0f}%")
        return rows_m, rows_q

    m_all, q_all = season_table(mret, "全史(1999起)")
    m_new, q_new = season_table(mret[mret.index >= "2015-01-01"], "近代(2015起)")

    # ---------- ②訊號層共用面板 ----------
    C = px.pivot_table(index="date", columns="code", values="close", aggfunc="first").sort_index()
    MN = px.pivot_table(index="date", columns="code", values="money", aggfunc="first").sort_index()
    dates = list(C.index)
    t_arr = np.array(dates)
    start_i = int(np.searchsorted(t_arr, "2015-01-01"))
    liq_ok = (MN.rolling(20, min_periods=15).mean().shift(1) >= LIQ_MIN)
    Cf = C.ffill(limit=5)
    tai_d = tai_full.reindex(pd.to_datetime(pd.Index(dates))).ffill()
    tai_v = tai_d.values
    is_theme = np.array([c in theme_codes for c in C.columns])

    def k40(ci, i):
        e, x = i + 1, i + 41
        if x >= len(dates):
            return np.nan
        p0, p1 = Cf.iat[e, ci], Cf.iat[x, ci]
        if pd.isna(p0) or pd.isna(p1) or p0 <= 0:
            return np.nan
        return (p1 / p0 - 1) - (tai_v[x] / tai_v[e] - 1)

    # 三重門檻事件
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
        av = np.array([np.datetime64(avail_date(p.end_time.normalize())) for p in g.index])
        ok = g.gross_margin.notna().values
        fundmap[code] = (av[ok], chg.values[ok])

    def gm_pos(code, d):
        fm = fundmap.get(code)
        if fm is None:
            return False
        k = int(np.searchsorted(fm[0], np.datetime64(d), side="right")) - 1
        return (k >= 0 and (pd.Timestamp(d) - pd.Timestamp(fm[0][k])).days <= 200
                and pd.notna(fm[1][k]) and fm[1][k] > 0)

    rmax90 = C.rolling(90, min_periods=72).max()
    is_hi = (C >= rmax90 * 0.9999) & C.notna()
    hi_recent = is_hi.shift(1).rolling(FRESH_GAP, min_periods=1).max()
    trip = []
    for i in range(start_i, len(dates) - 45):
        row = is_hi.iloc[i].values & (~hi_recent.iloc[i].values.astype(bool)) & liq_ok.iloc[i].values & is_theme
        if not row.any():
            continue
        d = dates[i]
        qtr = (pd.Timestamp(d).month - 1) // 3 + 1
        for ci in np.where(row)[0]:
            if gm_pos(C.columns[ci], d):
                v = k40(ci, i)
                if pd.notna(v):
                    trip.append({"q": qtr, "ym": d[:7], "v": v})
    T = pd.DataFrame(trip)

    # 雙新高月頻事件(m-1/m-2口徑,零前視)
    rev_w = rev.pivot_table(index="date", columns="code", values="revenue", aggfunc="first").sort_index()
    hi_m = (rev_w >= rev_w.rolling(12, min_periods=12).max()) & rev_w.notna()
    hi126 = C.rolling(126, min_periods=100).max()
    dual = []
    months = [m for m in rev_w.index if "2018-02-01" <= str(m)[:10] <= "2026-04-30"]
    for m in months:
        f_i = int(np.searchsorted(t_arr, (m + pd.Timedelta(days=12)).strftime("%Y-%m-%d")))
        if f_i >= len(dates) - 45:
            continue
        try:
            mi = rev_w.index.get_loc(m)
        except KeyError:
            continue
        if mi < 2:
            continue
        h1, h2 = hi_m.iloc[mi - 1], hi_m.iloc[mi - 2]
        dist = C.iloc[f_i] / hi126.iloc[f_i] - 1
        liq_r = liq_ok.iloc[f_i]
        qtr = (pd.Timestamp(dates[f_i]).month - 1) // 3 + 1
        for code in C.columns:
            if (bool(h1.get(code, False)) and bool(h2.get(code, False))
                    and pd.notna(dist.get(code, np.nan)) and dist[code] >= -0.02
                    and bool(liq_r.get(code, False))):
                ci = C.columns.get_loc(code)
                v = k40(ci, f_i - 1)          # k40()內部+1=形成日收盤進場
                if pd.notna(v):
                    dual.append({"q": qtr, "ym": dates[f_i][:7], "v": v})
    D = pd.DataFrame(dual)
    print(f"\n[events] 三重門檻{len(T):,} / 雙新高{len(D):,}")

    def boot_m(sub):
        if len(sub) < 30 or sub.ym.nunique() < 6:
            return None
        grp = {k: g.v.values for k, g in sub.groupby("ym")}
        keys = list(grp)
        means = [np.mean(np.concatenate([grp[k] for k in rng.choice(keys, len(keys))]))
                 for _ in range(1000)]
        lo, hi = np.percentile(means, [2.5, 97.5])
        return {"lo": lo, "hi": hi, "sig": bool(lo > 0 or hi < 0)}

    def sig_season(E, lab):
        print(f"\n【{lab} k40 demean按進場季】")
        out = []
        for q in range(1, 5):
            s = E[E.q == q]
            b = boot_m(s)
            r = {"q": q, "n": len(s), "mean": s.v.mean() * 100,
                 "win": (s.v > 0).mean() * 100, "b": b}
            out.append(r)
            print(f"  Q{q}: n={r['n']:>6,} 均{r['mean']:+.2f}%"
                  + (f"[{b['lo'] * 100:+.2f},{b['hi'] * 100:+.2f}]{'✓' if b['sig'] else ''}" if b else "")
                  + f" 勝率{r['win']:.0f}%")
        return out

    t_season = sig_season(T, "三重門檻")
    d_season = sig_season(D, "雙新高")

    # ---------- HTML ----------
    CSS = """
body{background:#1a1a19;color:#fff;font-family:"Noto Sans TC",sans-serif;margin:24px;max-width:1000px}
h1{font-size:20px} h2{font-size:15px;color:#c3c2b7;margin-top:28px;border-bottom:1px solid #333;padding-bottom:4px}
table{border-collapse:collapse;font-size:12.5px;font-variant-numeric:tabular-nums;margin:8px 0}
td,th{border:1px solid #333;padding:4px 9px;text-align:right} th{text-align:left;color:#c3c2b7}
.note{color:#8a8878;font-size:12.5px;line-height:1.8} .good{color:#7ec97e} .bad{color:#e06c5a}
.hl{background:#2b3a2b}
ul{margin:4px 0;padding-left:20px;font-size:12.5px;color:#ccc;line-height:1.7}
"""

    def mtbl(rows_a, rows_b):
        h = "<table><tr><th>月</th><th>全史均</th><th>全史勝率</th><th>2015起均</th><th>2015起勝率</th></tr>"
        for a, b in zip(rows_a, rows_b):
            h += (f"<tr><th>{a['m']}月</th><td>{a['mean']:+.2f}%</td><td>{a['win']:.0f}%</td>"
                  f"<td>{b['mean']:+.2f}%</td><td>{b['win']:.0f}%</td></tr>")
        return h + "</table>"

    def qtbl(rows_a, rows_b):
        h = "<table><tr><th>季</th><th>全史均</th><th>全史勝率</th><th>2015起均</th><th>2015起勝率</th></tr>"
        for a, b in zip(rows_a, rows_b):
            h += (f"<tr><th>Q{a['q']}</th><td>{a['mean']:+.2f}%</td><td>{a['win']:.0f}%</td>"
                  f"<td>{b['mean']:+.2f}%</td><td>{b['win']:.0f}%</td></tr>")
        return h + "</table>"

    def stbl(rows):
        h = "<table><tr><th>進場季</th><th>n</th><th>k40 demean</th><th>CI(月群)</th><th>勝率</th></tr>"
        best = max(rows, key=lambda r: r["mean"])
        for r in rows:
            ci = (f"[{r['b']['lo'] * 100:+.2f},{r['b']['hi'] * 100:+.2f}]{'✓' if r['b']['sig'] else ''}"
                  if r["b"] else "—")
            h += (f"<tr{' class=hl' if r is best else ''}><th>Q{r['q']}</th><td>{r['n']:,}</td>"
                  f"<td>{r['mean']:+.2f}%</td><td>{ci}</td><td>{r['win']:.0f}%</td></tr>")
        return h + "</table>"

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>季度季節性(2026-08-07)</title><style>{CSS}</style></head><body>
<h1>📆 季度季節性考卷: 哪一季表現最好?</h1>
<div class="note">使用者提問。三層: 大盤月/季季節性(全史vs 2015起兩窗看穩定度)、
訊號層(三重門檻/雙新高事件k40 demean按進場季)、埋伏配方既有判決引用。
⚠季節性樣本天生薄(每格~10-27年),觀察層定位,不當硬濾網。</div>
<h2>①TAIEX逐月季節性</h2>
{mtbl(m_all, m_new)}
<h2>①TAIEX逐季季節性</h2>
{qtbl(q_all, q_new)}
<h2>②三重門檻: 進場季分組(k40 demean)</h2>
{stbl(t_season)}
<h2>②雙新高: 進場季分組(k40 demean)</h2>
{stbl(d_season)}
<h2>③既有判決(引用)</h2>
<ul>
<li>埋伏配方: <b>Q4(年報窗)壓倒性最強</b>(×創4季高×YoY>20%=+9.20%✓),Q1-Q3含0(research_rev_preposition.html)。</li>
<li>美股題材財報季(1/4/7/10月)=財報版獨漲的事件密集期(research_us_earnings_tw_link.html)。</li>
</ul>
<h2>⚖️ 判決(2026-08-07)</h2>
<ul>
<li><span class="verdict v-good">①答案: Q1最好、Q3最弱、9月最毒——兩個時間窗一致=穩定結構</span>
TAIEX全史Q1+4.93%/勝率75%、Q4+4.92%/78%(12月勝率81%) vs Q3-2.61%/46%(9月-2.25%/勝率44%);
2015起同構(Q4勝率91%、9月勝率36%)。</li>
<li><span class="verdict v-good">②訊號層同季節</span> 三重門檻Q1+5.79✓>Q2+4.71✓>Q4+3.26✓>Q3+1.60含0;
雙新高Q1+15.11✓最肥——<b>但雙新高Q4含0(+2.24)是例外</b>,與埋伏配方「Q4王者」正好互補:
年底資金從「追新高」轉向「埋伏年報」,兩訊號的季節輪替自然成立。</li>
<li><b>③操作翻譯(觀察層,不當硬濾網)</b>: Q1-Q2放心做雙新高;Q3(尤其9月)新開倉降預期/減碼;
Q4雙新高讓位給埋伏配方(1月中年報版)。⚠每格樣本僅11-28年,且週級動能卷的教訓=時間/regime濾網
容易過擬合(6窗僅1有效),此卷當「預期管理」用,不做開關。</li>
</ul>
<div class="note">維運: python 研究腳本/綜合策略/build_quarter_seasonality.py(從根目錄執行)。</div>
</body></html>"""
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n[report] 已輸出 {OUT}")


if __name__ == "__main__":
    main()
