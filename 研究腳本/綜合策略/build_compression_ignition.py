# -*- coding: utf-8 -*-
"""壓縮後爆發型態考卷·換池版(2026-08-07,使用者假說在高價池測不出後換池複測)。

背景: build_high_price_ignition.py測「平常振幅小→突然大振幅長紅+爆量」在**高價股池**全含0,
且前置壓縮組僅占1.4%(高價股=成長股長期高波動,根本沒有「平常很安靜」的狀態)=池子選錯。
本卷換池: 中價(50-500元)/低價(<50元)/題材成員,這些池子才有大量長期盤整股。

═══ 設計(預先註冊) ═══
壓縮(訊號日前狀態): amp20/amp120<=0.8(主) / <=0.6(更緊,敏感度)。amp=(high-low)/close。
爆發(使用者原話): 當日振幅>=2×前20日均振幅 且 收長紅(close/open-1>=2%) 且 量>=2×20日均量。
連兩日版: 兩日累計>=5% 且 皆收紅 且 兩日量皆>=1.5×20日均量。
核心比較=**交乘增量**: (a)純爆發(不管壓縮) (b)壓縮×爆發 (c)壓縮但沒爆發(對照:光盤整不會漲)
——若(b)>(a)才代表「壓縮」這個前置狀態有加值,否則使用者直覺的價值在「爆發」不在「壓縮」。
池: 20日均額>=0.3億;中價50-500/低價<50/題材成員(classification台)三池分開跑,高價引用前卷。
進場=訊號次日收盤(可執行);outcome=k20/40/60 demean(減TAIEX);同股5日去重;月群bootstrap。
winner features(最佳格內拆): 大戶d4w>0 / 題材共振(題材20日動能正) / 營收R1 / 距126日高。
用法: python 研究腳本/綜合策略/build_compression_ignition.py  (從根目錄執行,鐵律)
產出: 研究報告/research_compression_ignition.html + console
"""
import sqlite3
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

DB = "capital_flow.db"
OUT = "研究報告/research_compression_ignition.html"
LIQ_MIN = 0.3e8
K_LIST = [20, 40, 60]
rng = np.random.default_rng(20260807)


def main():
    conn = sqlite3.connect(DB, timeout=60)
    px = pd.read_sql("SELECT code,date,open,high,low,close,volume,money FROM fm_daily_price "
                     "WHERE date>='2013-06-01' AND close>0 AND money>0", conn)
    tai = pd.read_sql("SELECT date,close FROM index_daily WHERE market='TAIEX' "
                      "AND date>='2013-06-01' ORDER BY date", conn)
    rev = pd.read_sql("SELECT code, date, revenue FROM fm_month_rev", conn, parse_dates=["date"])
    td = pd.read_sql("SELECT code, date, p1000 FROM tdcc_weekly", conn, parse_dates=["date"])
    cls = pd.read_sql("SELECT code, main_group FROM classification WHERE country='台'", conn)
    conn.close()

    piv = lambda c: px.pivot_table(index="date", columns="code", values=c, aggfunc="first").sort_index()
    C, O, H, L, MN, V = piv("close"), piv("open"), piv("high"), piv("low"), piv("money"), piv("volume")
    tai = tai.set_index("date")["close"]
    dates = list(C.index)
    Cf = C.ffill(limit=5)
    tai_f = tai.reindex(C.index).ffill()
    pool_ok = MN.rolling(20, min_periods=15).mean().shift(1) >= LIQ_MIN

    amp = (H - L) / C
    amp20 = amp.rolling(20, min_periods=15).mean().shift(1)
    amp120 = amp.rolling(120, min_periods=90).mean().shift(1)
    comp = amp20 / amp120
    body = C / O - 1
    v20 = V.rolling(20, min_periods=15).mean().shift(1)
    up = C > O
    dist126 = C / C.rolling(126, min_periods=100).max() - 1

    BURST = (amp >= 2 * amp20) & (body >= 0.02) & (V >= 2 * v20)
    BURST2 = ((C / C.shift(2) - 1 >= 0.05) & up & up.shift(1)
              & (V >= 1.5 * v20) & (V.shift(1) >= 1.5 * v20.shift(1)))
    COMP08, COMP06 = (comp <= 0.8), (comp <= 0.6)
    NOCOMP = comp > 1.0

    theme_of = cls.groupby("code").main_group.first().to_dict()
    is_theme = pd.Series({c: (c in theme_of) for c in C.columns})
    POOLS = {
        "中價50-500": (C >= 50) & (C < 500) & pool_ok,
        "低價<50": (C < 50) & pool_ok,
        "題材成員": pool_ok & pd.DataFrame(np.tile(is_theme.values, (len(C), 1)),
                                       index=C.index, columns=C.columns),
    }

    rev_w = rev.pivot_table(index="date", columns="code", values="revenue", aggfunc="first").sort_index()
    hi_rev = (rev_w >= rev_w.rolling(12, min_periods=12).max()) & rev_w.notna()
    td_w = td.pivot_table(index="date", columns="code", values="p1000", aggfunc="first").sort_index()
    d4w = td_w - td_w.shift(4)
    tm_mom = {}
    for t in set(theme_of.values()):
        mem = [c for c in theme_of if theme_of[c] == t and c in C.columns]
        if len(mem) >= 2:
            s = C[mem].mean(axis=1)
            tm_mom[t] = s / s.shift(20) - 1

    start_i = int(np.searchsorted(np.array(dates), "2015-01-01"))
    end_i = len(dates) - max(K_LIST) - 2

    def collect(mask, gap=5, feats=False):
        M = mask.fillna(False).values
        rows, last = [], {}
        for i in range(start_i, end_i):
            idxs = np.where(M[i])[0]
            if not len(idxs):
                continue
            d = dates[i]
            ti = td_w.index.searchsorted(pd.Timestamp(d), side="right") - 1 if feats else -1
            for ci in idxs:
                code = C.columns[ci]
                if i - last.get(code, -99) < gap:
                    continue
                e = i + 1
                p0 = Cf.iat[e, ci]
                if pd.isna(p0) or p0 <= 0:
                    continue
                rec = {"code": code, "ym": d[:7], "d": d}
                bad = False
                for k in K_LIST:
                    p1 = Cf.iat[e + k, ci]
                    if pd.isna(p1):
                        bad = True
                        break
                    rec[f"dm{k}"] = (p1 / p0 - 1) - (tai_f.iloc[e + k] / tai_f.iloc[e] - 1)
                if bad:
                    continue
                last[code] = i
                if feats:
                    rec["d4w"] = (d4w.iat[ti, d4w.columns.get_loc(code)]
                                  if (ti >= 4 and code in d4w.columns
                                      and (pd.Timestamp(d) - td_w.index[ti]).days <= 14) else np.nan)
                    mons = [m for m in rev_w.index
                            if (m + pd.DateOffset(months=1) + pd.Timedelta(days=11)) <= pd.Timestamp(d)]
                    rec["r1"] = (bool(hi_rev.loc[mons[-1]].get(code, False))
                                 and bool(hi_rev.loc[mons[-2]].get(code, False))) if len(mons) >= 2 else False
                    th = theme_of.get(code)
                    rec["reso"] = bool(th in tm_mom and pd.notna(tm_mom[th].get(d, np.nan))
                                       and tm_mom[th][d] > 0)
                    rec["dist"] = dist126.iat[i, ci]
                rows.append(rec)
        return pd.DataFrame(rows)

    def boot(E, col):
        if len(E) < 40 or E.ym.nunique() < 8:
            return None
        grp = {m: g[col].values for m, g in E.groupby("ym")}
        keys = list(grp)
        means = [np.mean(np.concatenate([grp[m] for m in rng.choice(keys, len(keys))]))
                 for _ in range(800)]
        lo, hi = np.percentile(means, [2.5, 97.5])
        return {"mean": E[col].mean() * 100, "lo": lo * 100, "hi": hi * 100,
                "sig": bool(lo > 0 or hi < 0)}

    def line(E, lab, out):
        if len(E) < 40:
            print(f"  {lab:<40} n={len(E)} 不足")
            return None
        r = {"lab": lab, "n": len(E), "per_yr": len(E) / 11.5}
        for k in K_LIST:
            b = boot(E, f"dm{k}")
            v = E[f"dm{k}"]
            w, l = v[v > 0], v[v <= 0]
            r[k] = {"mean": v.mean() * 100, "b": b, "win": len(w) / len(v) * 100,
                    "wl": (w.mean() / abs(l.mean())) if len(w) and len(l) else np.nan}
        y = E.assign(yr=E.d.str[:4]).groupby("yr")["dm40"].mean()
        r["yr"] = f"{int((y > 0).sum())}/{len(y)}"
        out.append(r)
        b40 = r[40]
        print(f"  {lab:<40} n={r['n']:>6,}({r['per_yr']:.0f}/年) k20:{r[20]['mean']:+.2f} "
              f"k40:{b40['mean']:+.2f}"
              + (f"[{b40['b']['lo']:+.2f},{b40['b']['hi']:+.2f}]{'✓' if b40['b']['sig'] else ''}" if b40["b"] else "")
              + f" k60:{r[60]['mean']:+.2f} 勝率{b40['win']:.0f}% 賺賠{b40['wl']:.2f} 逐年{r['yr']}")
        return r

    print("=" * 108)
    print("① 三池 × (純爆發 / 壓縮×爆發 / 純壓縮無爆發) —— 交乘增量才是重點")
    A = {}
    for pname, pmask in POOLS.items():
        print(f"\n【{pname}】")
        rows = []
        line(collect(pmask & BURST), "(a)純爆發(不管壓縮)", rows)
        line(collect(pmask & BURST & COMP08), "(b)壓縮<=0.8 × 爆發", rows)
        line(collect(pmask & BURST & COMP06), "(b')緊壓縮<=0.6 × 爆發", rows)
        line(collect(pmask & BURST & NOCOMP), "(b'')無壓縮(>1.0) × 爆發", rows)
        line(collect(pmask & BURST2 & COMP08), "(c)壓縮 × 連兩日版", rows)
        line(collect(pmask & COMP08 & ~BURST & ~BURST2, gap=20), "(d)純壓縮無爆發(對照)", rows)
        A[pname] = rows

    # 最佳格 winner features(取壓縮×爆發最好的池)
    best_pool = max(POOLS, key=lambda p: next((r[40]["mean"] for r in A[p]
                                               if r["lab"].startswith("(b)")), -99))
    print(f"\n② winner features(最佳池: {best_pool},壓縮<=0.8×爆發)")
    E = collect(POOLS[best_pool] & BURST & COMP08, feats=True)
    B = []
    line(E[E.d4w > 0], "大戶4週增加", B)
    line(E[E.d4w <= 0], "大戶4週減少", B)
    line(E[E.reso], "題材共振(題材20日動能正)", B)
    line(E[~E.reso], "無共振", B)
    line(E[E.r1], "營收兩月連創高", B)
    line(E[~E.r1], "營收未連創", B)
    line(E[E.dist >= -0.05], "距126日高<=5%(貼高爆發)", B)
    line(E[E.dist < -0.20], "距高>20%(低基期爆發)", B)
    print("\n(交乘)")
    Cc = []
    line(E[(E.d4w > 0) & E.reso], "大戶增×共振", Cc)
    line(E[(E.d4w > 0) & (E.dist >= -0.05)], "大戶增×貼高", Cc)

    # ---------- HTML ----------
    CSS = """
body{background:#1a1a19;color:#fff;font-family:"Noto Sans TC",sans-serif;margin:24px;max-width:1150px}
h1{font-size:20px} h2{font-size:15px;color:#c3c2b7;margin-top:28px;border-bottom:1px solid #333;padding-bottom:4px}
h3{font-size:13.5px;color:#a8a79a;margin:14px 0 4px}
table{border-collapse:collapse;font-size:12.5px;font-variant-numeric:tabular-nums;margin:8px 0}
td,th{border:1px solid #333;padding:4px 9px;text-align:right} th{text-align:left;color:#c3c2b7}
.note{color:#8a8878;font-size:12.5px;line-height:1.8} .good{color:#7ec97e} .bad{color:#e06c5a}
.hl{background:#2b3a2b} .scroll{overflow-x:auto}
ul{margin:4px 0;padding-left:20px;font-size:12.5px;color:#ccc;line-height:1.7}
"""

    def tbl(rows):
        h = ("<div class='scroll'><table><tr><th>組</th><th>n(次/年)</th>"
             + "".join(f"<th>k{k} demean</th>" for k in K_LIST)
             + "<th>k40勝率</th><th>k40賺賠</th><th>逐年40</th></tr>")
        best = max(rows, key=lambda r: r[40]["mean"]) if rows else None
        for r in rows:
            cells = ""
            for k in K_LIST:
                s = r[k]
                ci = (f"<br><span style='color:#777;font-size:10.5px'>[{s['b']['lo']:+.2f},{s['b']['hi']:+.2f}]"
                      f"{'✓' if s['b']['sig'] else ''}</span>" if s["b"] else "")
                cells += f"<td>{s['mean']:+.2f}%{ci}</td>"
            h += (f"<tr{' class=hl' if r is best else ''}><th>{r['lab']}</th>"
                  f"<td>{r['n']:,}({r['per_yr']:.0f})</td>{cells}"
                  f"<td>{r[40]['win']:.0f}%</td><td>{r[40]['wl']:.2f}</td><td>{r['yr']}</td></tr>")
        return h + "</table></div>"

    pools_html = "".join(f"<h3>{p}</h3>{tbl(A[p])}" for p in POOLS)
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>壓縮後爆發·換池版(2026-08-07)</title><style>{CSS}</style></head><body>
<h1>🧨 壓縮後爆發型態考卷(換池版): 中價/低價/題材成員</h1>
<div class="note">使用者假說「平常K棒振幅小→突然一根大振幅長紅+爆量」在高價池測不出(前卷: 五觸發全含0,
壓縮組僅1.4%=池選錯)。本卷換池複測。壓縮=前20日均振幅/前120日均振幅<=0.8(緊版<=0.6);
爆發=當日振幅>=2×20日均振幅 且 收長紅>=2% 且 量>=2×20日均量。<b>判讀重點=(b)壓縮×爆發 是否 &gt; (a)純爆發</b>
——大於才代表「壓縮」有加值,否則價值在爆發本身。進場=次日收盤,demean減TAIEX,同股5日去重,月群bootstrap。</div>
<h2>① 三池 × 型態組合</h2>
{pools_html}
<h2>② winner features(最佳池: {best_pool})</h2>
{tbl(B)}
<h3>交乘</h3>
{tbl(Cc)}
<h2>⚖️ 判決(2026-08-07)</h2>
<ul>
<li><span style="background:#3b2420;color:#e06c5a;padding:6px 10px;border-radius:4px;font-weight:bold">
①「壓縮」不是加分項,是<b>扣分項</b>——三池一致、兩種鬆緊一致</span>
中價池: 純爆發k40 <b>-1.53✓</b> → 壓縮×爆發 <b>-2.85✓</b> → 緊壓縮×爆發 <b>-4.28✓</b>(越緊越糟);
低價池同向(緊壓縮-3.44✓);題材成員池: 純爆發+1.98✓ → 壓縮×爆發<b>+0.32含0(肉被壓縮吃光)</b>。
<b>使用者的「彈簧壓縮→爆發」直覺在台股是反的</b>: 壓縮期越久越安靜的股票,突然爆量長紅後反而走弱
——機制解讀=冷門股的單日爆發多為一次性題材/假動作/出貨,沒有持續買盤接手。</li>
<li><span style="background:#243b24;color:#7ec97e;padding:6px 10px;border-radius:4px;font-weight:bold">
②但這卷撿到一個強訊號: <b>題材成員 × 爆發 × 沒有壓縮</b></span>
k20+1.59 / <b>k40+3.63✓[+1.97,+5.39] / k60+4.82% / 勝率45% / 賺賠比2.00 / 逐年12/12全正</b>(n=2,845,~247次/年)
——本來就在動的題材股(前20日振幅≥前120日)出現爆量長紅=<b>題材動能正在加速</b>,這才是真起漲;
與VCP卷「鬆盤整>50%反而最好」「題材共振最強」完全同構。</li>
<li><b>③池子決定一切</b>: 同一個爆發訊號,中價池-1.53✓(虧)、低價池-0.68(平)、題材成員+1.98✓(賺)
——<b>沒有題材故事的爆量長紅是負期望值</b>,這是「無財報排除」「非題材突破為負」之後,
同一原理的第三次重現。</li>
<li><b>④次級發現</b>: 壓縮×爆發格內,<b>大戶4週增加×貼126日高 k40+2.09✓</b>(唯一排0格)——
即使在壞格子裡,籌碼+位置仍能救回來;距高>20%的低基期爆發-1.47(最差),
再次確認「低基期突然大漲」是陷阱。</li>
<li><b>⑤實務翻譯</b>: 刪掉「等壓縮」的想法;要做爆發只做<b>題材成員×已在動(無壓縮)×貼高</b>,
或直接用既有三線(雙新高/三重門檻/高價新貴)。</li>
</ul>
<h2>已知限制</h2>
<div class="note">①池子重疊(題材成員與中價/低價有交集,非互斥);②同股5日去重仍可能同段行情多次入樣;
③除權息未還原;④參數(2x/2%/0.8)為研究者選定,已附0.6緊版敏感度;⑤多重比較(3池×6組),
判讀靠跨池一致性與交乘增量,不靠單格CI。</div>
<div class="note">維運: python 研究腳本/綜合策略/build_compression_ignition.py(從根目錄執行)。
姊妹卷: build_high_price_ignition.py(高價池版)、build_vcp_breakout_anatomy.py(突破後型態解剖)。</div>
</body></html>"""
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n[report] 已輸出 {OUT}")


if __name__ == "__main__":
    main()
