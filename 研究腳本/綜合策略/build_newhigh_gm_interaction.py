# -*- coding: utf-8 -*-
"""台股新高突破 × 毛利率QoQ改善 交乘考卷(2026-08-05,使用者指定;兩條季級持股層訊號的會師)。

背景: ①build_newhigh_breakout_swing(同日稍早): 題材成員90/240日獨立突破=波段活口
(90日k20 demean+1.52✓/k60+4.22,240日k20+2.14✓/k60+6.16),候選層(事後名單偏誤保留)。
②build_fundamental_momo_interaction(同日): 動能溢價只在毛利率QoQ改善股內存在(真交乘+1.69pp排0),
「最新季毛利率QoQ改善」=季級持股資格門檻。
本卷問: 新高突破的波段肉是否也集中在毛利率改善股?若是→「題材成員×新高突破×gm改善」三重
資格門檻=本專案季級持股層的合成訊號;若否→新高突破與財報層正交,兩訊號獨立可疊加。

═══ 設計(預先註冊) ═══
事件: 逐字沿用newhigh卷口徑——N=90/240日新高獨立突破(前20日無新高),池=20日均額>=0.3億
(前一日止),進場=次日收盤,outcome=k20/40/60絕對+demean(減TAIEX)。
財報: 訊號日已依法公告的最新季gm_chg(avail_date=法定期限+5日,merge_asof容忍200日,
逐字沿用fundamental_momo卷)。
分組(每N): ①gm改善(>0) ②gm惡化(<=0) ③無財報資料;交乘=×題材成員2×2;
檢定: 同日配對diff(同一訊號日兩組皆有)月群bootstrap——這是「交乘是否為真」的主判準;
逐年;勝率/賺賠比。
用法: python 研究腳本/綜合策略/build_newhigh_gm_interaction.py  (從根目錄執行,鐵律)
產出: 研究報告/research_newhigh_gm.html + console
"""
import sqlite3
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

DB = "capital_flow.db"
OUT = "研究報告/research_newhigh_gm.html"
START = "2015-01-01"
N_LIST = [90, 240]
K_LIST = [20, 40, 60]
LIQ_MIN = 0.3e8
FRESH_GAP = 20
BUFFER_DAYS = 5
STATUTORY = {1: (5, 15, 0), 2: (8, 14, 0), 3: (11, 14, 0), 4: (3, 31, 1)}
rng = np.random.default_rng(20260805)


def avail_date(quarter_end):
    qe = pd.Timestamp(quarter_end)
    q = (qe.month - 1) // 3 + 1
    m, d, yoff = STATUTORY[q]
    return pd.Timestamp(qe.year + yoff, m, d) + pd.Timedelta(days=BUFFER_DAYS)


def load_fund():
    conn = sqlite3.connect(DB, timeout=60)
    fin = pd.read_sql("SELECT code, date, gross_margin FROM tw_quarterly_financials_history",
                      conn, parse_dates=["date"])
    conn.close()
    rows = []
    for code, g in fin.groupby("code"):
        g = g.sort_values("date")
        qidx = pd.PeriodIndex(g.date, freq="Q")
        g = g.set_index(qidx)
        g = g[~g.index.duplicated(keep="first")]
        full = pd.period_range(g.index.min(), g.index.max(), freq="Q")
        g = g.reindex(full)
        gm = g.gross_margin * 100
        f = pd.DataFrame({"gm_chg": gm - gm.shift(1)})
        f["avail"] = [avail_date(p.end_time.normalize()) for p in f.index]
        f["code"] = code
        f = f[g.date.notna().values]
        rows.append(f)
    fund = pd.concat(rows, ignore_index=True).dropna(subset=["gm_chg"]).sort_values("avail")
    print(f"[fund] gm_chg長表{len(fund):,}筆/{fund.code.nunique()}檔")
    return fund


def main():
    conn = sqlite3.connect(DB, timeout=60)
    px = pd.read_sql("SELECT code,date,close,money FROM fm_daily_price "
                     "WHERE date>='2013-01-01' AND close>0 AND money>0", conn)
    tai = pd.read_sql("SELECT date,close FROM index_daily WHERE market='TAIEX' "
                      "AND date>='2013-01-01' ORDER BY date", conn)
    theme_codes = {r[0] for r in conn.execute(
        "select distinct code from classification where country='台'")}
    conn.close()
    fund = load_fund()

    C = px.pivot_table(index="date", columns="code", values="close", aggfunc="first").sort_index()
    MN = px.pivot_table(index="date", columns="code", values="money", aggfunc="first").sort_index()
    tai = tai.set_index("date")["close"]
    dates = np.array(C.index)
    start_i = int(np.searchsorted(dates, START))
    liq_ok = (MN.rolling(20, min_periods=15).mean().shift(1) >= LIQ_MIN)
    Cf = C.ffill(limit=5)
    tai_r = tai.reindex(C.index)
    is_theme = np.array([c in theme_codes for c in C.columns])
    max_k = max(K_LIST)

    def boot(vals, months, n_iter=1000):
        v = pd.DataFrame({"v": vals, "m": months}).dropna()
        if len(v) < 15 or v.m.nunique() < 6:
            return None
        grp = {k: g.v.values for k, g in v.groupby("m")}
        keys = list(grp)
        means = [np.mean(np.concatenate([grp[k] for k in rng.choice(keys, len(keys))]))
                 for _ in range(n_iter)]
        lo, hi = np.percentile(means, [2.5, 97.5])
        return {"mean": float(v.v.mean()), "lo": float(lo), "hi": float(hi),
                "sig": bool(lo > 0 or hi < 0)}

    all_res = {}
    for N in N_LIST:
        rmax = C.rolling(N, min_periods=int(N * 0.8)).max()
        is_hi = (C >= rmax * 0.9999) & C.notna()
        hi_recent = is_hi.shift(1).rolling(FRESH_GAP, min_periods=1).max()
        events = []
        for i in range(start_i, len(dates) - max_k - 1):
            row = is_hi.iloc[i].values & (~hi_recent.iloc[i].values.astype(bool)) & liq_ok.iloc[i].values
            if not row.any():
                continue
            e_i = i + 1
            for ci in np.where(row)[0]:
                e1 = C.iat[e_i, ci]
                if pd.isna(e1) or e1 <= 0:
                    continue
                rec = {"code": C.columns[ci], "t": dates[i], "theme": bool(is_theme[ci])}
                ok = True
                for k in K_LIST:
                    x = Cf.iat[e_i + k, ci]
                    if pd.isna(x):
                        ok = False
                        break
                    b = tai_r.iloc[e_i + k] / tai_r.iloc[e_i] - 1
                    rec[f"r{k}"] = x / e1 - 1
                    rec[f"dm{k}"] = rec[f"r{k}"] - b
                if ok:
                    events.append(rec)
        E = pd.DataFrame(events)
        E["t_ts"] = pd.to_datetime(E["t"])
        E = E.sort_values("t_ts")
        E = pd.merge_asof(E, fund[["avail", "code", "gm_chg"]].rename(columns={"avail": "t_ts"}).sort_values("t_ts"),
                          on="t_ts", by="code", direction="backward",
                          tolerance=pd.Timedelta(days=200))
        E["month"] = E["t"].str[:7]
        E["year"] = E["t"].str[:4]
        all_res[N] = E
        print(f"[N={N}] 獨立突破事件{len(E):,}筆, gm可對上{E.gm_chg.notna().sum():,}"
              f"({E.gm_chg.notna().mean() * 100:.0f}%)")

    def line(sub, lab):
        if len(sub) < 30:
            print(f"  {lab:<30} n={len(sub)} 樣本不足")
            return None
        r = {"lab": lab, "n": len(sub)}
        for k in K_LIST:
            v = sub[f"r{k}"]
            w, l = v[v > 0], v[v <= 0]
            b = boot(sub[f"dm{k}"].values, sub.month.values)
            r[k] = {"abs": v.mean() * 100, "dm": sub[f"dm{k}"].mean() * 100,
                    "win": len(w) / len(v) * 100,
                    "wl": (w.mean() / abs(l.mean())) if len(w) and len(l) else np.nan, "boot": b}
        y = sub.groupby("year")[f"dm40"].mean()
        r["yr40"] = f"{int((y > 0).sum())}/{len(y)}"
        s = r[40]
        print(f"  {lab:<30} n={r['n']:>6,} k20dm{r[20]['dm']:+.2f} k40絕對{s['abs']:+.2f}/dm{s['dm']:+.2f}"
              + (f" CI[{s['boot']['lo'] * 100:+.2f},{s['boot']['hi'] * 100:+.2f}]{'✓' if s['boot']['sig'] else ''}" if s["boot"] else "")
              + f" 勝率{s['win']:.0f}% 賺賠{s['wl']:.2f} k60dm{r[60]['dm']:+.2f} 逐年40:{r['yr40']}")
        return r

    print("\n" + "=" * 100)
    print("台股新高獨立突破 × 訊號日已公告毛利率QoQ(進場=次日收盤)")
    print("=" * 100)
    RES = {}
    for N in N_LIST:
        E = all_res[N]
        print(f"\n【N={N}日】")
        RES[(N, "up")] = line(E[E.gm_chg > 0], "①gm改善")
        RES[(N, "dn")] = line(E[E.gm_chg <= 0], "②gm惡化")
        RES[(N, "na")] = line(E[E.gm_chg.isna()], "③無財報資料")
        RES[(N, "th_up")] = line(E[E.theme & (E.gm_chg > 0)], "④題材成員×gm改善(三重門檻)")
        RES[(N, "th_dn")] = line(E[E.theme & (E.gm_chg <= 0)], "⑤題材成員×gm惡化")
        RES[(N, "nth_up")] = line(E[~E.theme & (E.gm_chg > 0)], "⑥非題材×gm改善")
        # 同日配對(全樣本層): 改善-惡化
        both = E[E.gm_chg.notna()]
        for k in (20, 40, 60):
            day = both.groupby(["t", both.gm_chg > 0])[f"r{k}"].mean().unstack().dropna()
            if len(day) < 30:
                continue
            diff = day[True] - day[False]
            b = boot(diff.values, pd.Series(diff.index).str[:7].values)
            print(f"  同日配對k{k}(n_days={len(day)}): 改善-惡化={diff.mean() * 100:+.2f}%"
                  + (f" CI[{b['lo'] * 100:+.2f},{b['hi'] * 100:+.2f}]{'✓排0' if b['sig'] else '含0'}" if b else ""))
            RES[(N, f"pair{k}")] = {"n_days": len(day), "diff": diff.mean() * 100, "boot": b}

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

    def tbl(N):
        h = ("<div class='scroll'><table><tr><th>組</th><th>n</th>"
             + "".join(f"<th>k{k}絕對/<b>dm</b>/CI</th>" for k in K_LIST)
             + "<th>k40勝率/賺賠</th><th>逐年40</th></tr>")
        for key, hl in (("up", 0), ("dn", 0), ("na", 0), ("th_up", 1), ("th_dn", 0), ("nth_up", 0)):
            r = RES.get((N, key))
            if r is None:
                continue
            cells = ""
            for k in K_LIST:
                s = r[k]
                ci = (f"[{s['boot']['lo'] * 100:+.1f},{s['boot']['hi'] * 100:+.1f}]{'✓' if s['boot']['sig'] else ''}"
                      if s["boot"] else "—")
                cells += f"<td>{s['abs']:+.2f}/<b>{s['dm']:+.2f}</b><br><span style='color:#777;font-size:10.5px'>{ci}</span></td>"
            s40 = r[40]
            h += (f"<tr{' class=hl' if hl else ''}><th>{r['lab']}</th><td>{r['n']:,}</td>{cells}"
                  f"<td>{s40['win']:.0f}%/{s40['wl']:.2f}</td><td>{r['yr40']}</td></tr>")
        pair_txt = ""
        for k in (20, 40, 60):
            p = RES.get((N, f"pair{k}"))
            if p and p["boot"]:
                b = p["boot"]
                pair_txt += (f"同日配對k{k}: 改善-惡化={p['diff']:+.2f}% "
                             f"CI[{b['lo'] * 100:+.2f},{b['hi'] * 100:+.2f}]{'✓排0' if b['sig'] else '含0'} · ")
        return h + f"</table></div><div class='note'>{pair_txt}</div>"

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>新高突破×毛利率QoQ交乘(2026-08-05)</title><style>{CSS}</style></head><body>
<h1>🧗 台股新高突破 × 毛利率QoQ改善 交乘考卷</h1>
<div class="note">兩條季級持股層訊號的會師: newhigh卷(題材成員90/240日獨立突破=波段活口)×
fundamental_momo卷(動能溢價只在毛利率改善股內存在)。口徑逐字沿用兩卷: 獨立突破+次日收盤進場+
avail_date財報時滯。問題: 突破肉是否集中在gm改善股?④列=題材成員×gm改善=三重資格門檻。</div>
<h2>N=90日新高突破</h2>
{tbl(90)}
<h2>N=240日(52週)新高突破</h2>
{tbl(240)}
<h2>⚖️ 判決(2026-08-05首輪)</h2>
<ul>
<li><span class="verdict v-good">①毛利率QoQ在90日突破內=真增量(同日配對三窗全排0)</span>
改善-惡化: k20+1.06✓/k40+1.83✓/k60+2.55✓——與fundamental_momo卷「動能溢價只在改善股內」
同構的第二次獨立重現,慢訊號(財報)×中速訊號(90日突破)交乘成立。</li>
<li><span class="verdict v-warn">②但在240日(52週)突破內增量被吸收</span> 同日配對全含0,
題材成員內gm改善+4.70 vs 惡化+4.74幾乎相同——52週突破本身已是夠強的篩選(能破年線高的股票
基本面多半已在改善),財報層資訊重疊;<b>gm門檻只該加在90日突破上,52週突破不用疊</b>。</li>
<li><span class="verdict v-good">③三重門檻=本專案季級持股層目前最強合成訊號</span>
題材成員×90日獨立突破×gm改善: <b>k40絕對+7.25%/demean+3.84✓[+2.46,+5.18]/勝率54%/賺賠比2.18/
k60 demean+5.64/逐年k40 12/12全正</b>(240日版三重門檻k40 dm+4.70✓/賺賠2.36/12/12,絕對+8.56%
更高但gm層非增量來源);n=1,760~2,369=每年~150-200事件,可操作頻率。</li>
<li><b>④「無財報資料」組再次大負</b>(90日k40 dm-3.32✓/240日-2.29✓,逐年3-4/12)——第三次重現,
可直接當排除規則: 突破但查無財報的股票(小型新股/冷門)不碰。</li>
<li><b>⑤保留同前</b>: 事後名單偏誤(題材成員)+單一樣本內三因子疊加=多重比較風險,已靠同日配對
主判準+跨N結構一致性緩解;定位候選層,live驗證與walk-forward前不上板。</li>
</ul>
<h2>已知限制</h2>
<div class="note">①事後名單偏誤(題材成員,同newhigh卷)與財報覆蓋偏誤(gm可對上~60%,「無財報」組
混入小型新股)並存;②除權息未還原(長窗保守);③同日配對是全樣本層(未按題材成員再分,樣本會太薄);
④多重比較(2N×6組×3窗)判讀靠同日配對+跨N一致性。</div>
<div class="note">維運: python 研究腳本/綜合策略/build_newhigh_gm_interaction.py(從根目錄執行)。
姊妹卷: build_newhigh_breakout_swing.py、財報事件/build_fundamental_momo_interaction.py。</div>
</body></html>"""
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n[report] 已輸出 {OUT}")


if __name__ == "__main__":
    main()
