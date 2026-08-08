# -*- coding: utf-8 -*-
"""高價股啟動點考卷(2026-08-07,使用者指正觸發定義:「15%可能太多,不如抓平常振幅小、
突然一根大振幅長紅/連續幾天+成交量變大」)。

承接: high_price_stability(穩定性否定)/high_price_followup(RS三關過+高價新貴活口)。
本卷問: 高價股「起漲點」的可操作定義是什麼? 以及發動後誰走得遠(winner features)?

═══ 觸發定義五種(預先註冊,同一池同一outcome可比) ═══
T1 20日漲幅>=15%(原提案,對照組)
T2 20日漲幅>=8%(較鬆)
T3 覺醒棒(使用者版): 當日振幅>=2×前20日均振幅 且 收長紅(close/open-1>=2%) 且 量>=2×20日均量
T4 連續兩日: 兩日累計>=5% 且 兩日皆收紅 且 兩日均量>=1.5×20日均量
T5 量能結構: 20日均額/60日均額>=1.5 且 20日漲幅>0(溫和放量走高)
池=每日收盤價在流動池(20日均額>=0.3億)內前5%(相對高價,樣本跨年代穩定)+絕對>=500元子集對照。
進場=訊號次日收盤(可執行),outcome=k20/40/60 demean(減TAIEX);月群bootstrap+勝率/賺賠比。

═══ winner features(最佳觸發組內拆) ═══
①前置壓縮(使用者「平常振幅都小」): 前20日均振幅/前120日均振幅<=0.8 vs >1.0
②大戶4週變動d4w(tdcc_weekly.p1000,沉寂覺醒卷最強因子)>0 vs <=0
③營收R1(最近兩個已公布月營收皆創12月高) ④題材成員×題材20日動能正(VCP卷最強共振)
⑤距126日高(貼高<=2% vs 落後)
用法: python 研究腳本/綜合策略/build_high_price_ignition.py  (從根目錄執行,鐵律)
產出: 研究報告/research_high_price_ignition.html + console
"""
import sqlite3
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

DB = "capital_flow.db"
OUT = "研究報告/research_high_price_ignition.html"
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
    t_arr = np.array(dates)
    Cf = C.ffill(limit=5)
    tai_f = tai.reindex(C.index).ffill()
    liq20 = MN.rolling(20, min_periods=15).mean()
    liq_prev = liq20.shift(1)
    pool_ok = liq_prev >= LIQ_MIN

    # 高價旗標(逐日池內前5%)
    Cm = C.where(pool_ok)
    q95 = Cm.quantile(0.95, axis=1)
    hp_rel = Cm.ge(q95, axis=0) & pool_ok
    hp_abs = Cm.ge(500) & pool_ok

    # 觸發素材
    ret20 = C / C.shift(20) - 1
    amp = (H - L) / C
    amp20 = amp.rolling(20, min_periods=15).mean().shift(1)
    amp120 = amp.rolling(120, min_periods=90).mean().shift(1)
    body = C / O - 1
    v20 = V.rolling(20, min_periods=15).mean().shift(1)
    up = C > O
    ret1 = C.pct_change(fill_method=None)
    liq60 = MN.rolling(60, min_periods=45).mean()
    dist126 = C / C.rolling(126, min_periods=100).max() - 1

    TRIG = {
        "T1 20日漲>=15%(原提案)": (ret20 >= 0.15),
        "T2 20日漲>=8%": (ret20 >= 0.08),
        "T3 覺醒棒(振幅2x×長紅2%×量2x)": (amp >= 2 * amp20) & (body >= 0.02) & (V >= 2 * v20),
        "T4 連兩日(累計5%×皆紅×量1.5x)": ((C / C.shift(2) - 1 >= 0.05) & up & up.shift(1)
                                     & (V >= 1.5 * v20) & (V.shift(1) >= 1.5 * v20.shift(1))),
        "T5 量能結構(20/60均額1.5x×20日正)": (liq20 / liq60 >= 1.5) & (ret20 > 0),
    }

    # 特徵素材
    rev_w = rev.pivot_table(index="date", columns="code", values="revenue", aggfunc="first").sort_index()
    hi_rev = (rev_w >= rev_w.rolling(12, min_periods=12).max()) & rev_w.notna()
    td_w = td.pivot_table(index="date", columns="code", values="p1000", aggfunc="first").sort_index()
    d4w = td_w - td_w.shift(4)
    td_dates = td_w.index
    theme_of = cls.groupby("code").main_group.first().to_dict()
    themes = sorted(set(theme_of.values()))
    tm_mom = {}
    for t in themes:
        mem = [c for c in theme_of if theme_of[c] == t and c in C.columns]
        if len(mem) >= 2:
            tm_mom[t] = (C[mem].mean(axis=1) / C[mem].mean(axis=1).shift(20) - 1)

    start_i = int(np.searchsorted(t_arr, "2015-01-01"))
    end_i = len(dates) - max(K_LIST) - 2

    def collect(trig_mask, hp_mask, gap=5):
        """事件收集: 同股間隔gap日去重(避免連續觸發重複計)。"""
        M = (trig_mask & hp_mask).fillna(False).values
        rows = []
        last = {}
        for i in range(start_i, end_i):
            idxs = np.where(M[i])[0]
            if len(idxs) == 0:
                continue
            d = dates[i]
            ti = td_dates.searchsorted(pd.Timestamp(d), side="right") - 1
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
                # 特徵
                a20, a120 = amp20.iat[i, ci], amp120.iat[i, ci]
                rec["compress"] = (a20 / a120) if (pd.notna(a20) and pd.notna(a120) and a120 > 0) else np.nan
                rec["d4w"] = (d4w.iat[ti, d4w.columns.get_loc(code)]
                              if (ti >= 4 and code in d4w.columns
                                  and (pd.Timestamp(d) - td_dates[ti]).days <= 14) else np.nan)
                mons = [m for m in rev_w.index
                        if (m + pd.DateOffset(months=1) + pd.Timedelta(days=11)) <= pd.Timestamp(d)]
                rec["r1"] = (bool(hi_rev.loc[mons[-1]].get(code, False))
                             and bool(hi_rev.loc[mons[-2]].get(code, False))) if len(mons) >= 2 else False
                th = theme_of.get(code)
                rec["theme"] = th is not None
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
                 for _ in range(1000)]
        lo, hi = np.percentile(means, [2.5, 97.5])
        return {"mean": E[col].mean() * 100, "lo": lo * 100, "hi": hi * 100,
                "sig": bool(lo > 0 or hi < 0)}

    def line(E, lab, out):
        if len(E) < 40:
            print(f"  {lab:<34} n={len(E)} 不足")
            return None
        r = {"lab": lab, "n": len(E), "per_yr": len(E) / 11.5}
        for k in K_LIST:
            b = boot(E, f"dm{k}")
            v = E[f"dm{k}"]
            w, l = v[v > 0], v[v <= 0]
            r[k] = {"mean": v.mean() * 100, "b": b, "win": len(w) / len(v) * 100,
                    "wl": (w.mean() / abs(l.mean())) if len(w) and len(l) else np.nan}
        out.append(r)
        b40 = r[40]
        print(f"  {lab:<34} n={r['n']:>5,}({r['per_yr']:.0f}/年) k20:{r[20]['mean']:+.2f} "
              f"k40:{b40['mean']:+.2f}"
              + (f"[{b40['b']['lo']:+.2f},{b40['b']['hi']:+.2f}]{'✓' if b40['b']['sig'] else ''}" if b40["b"] else "")
              + f" k60:{r[60]['mean']:+.2f} 勝率{b40['win']:.0f}% 賺賠{b40['wl']:.2f}")
        return r

    print("=" * 100)
    print("① 觸發定義對決(高價=池內前5%,進場=次日收盤,demean)")
    A, events = [], {}
    for lab, mask in TRIG.items():
        E = collect(mask, hp_rel)
        events[lab] = E
        line(E, lab, A)
    print("\n(對照: 絕對>=500元池)")
    A500 = []
    for lab in ("T1 20日漲>=15%(原提案)", "T3 覺醒棒(振幅2x×長紅2%×量2x)"):
        line(collect(TRIG[lab], hp_abs), lab + "·>=500元", A500)

    best_lab = max(A, key=lambda r: r[40]["mean"])["lab"] if A else None
    print(f"\n② winner features(拆最佳觸發: {best_lab})")
    B = []
    E = events[best_lab]
    line(E[E.compress <= 0.8], "①前置壓縮(20日振幅<=0.8×120日)", B)
    line(E[E.compress > 1.0], "①無壓縮(振幅>1.0×)", B)
    line(E[E.d4w > 0], "②大戶4週增加(d4w>0)", B)
    line(E[E.d4w <= 0], "②大戶4週減少", B)
    line(E[E.r1], "③營收兩月連創高", B)
    line(E[~E.r1], "③營收未連創", B)
    line(E[E.reso], "④題材共振(成員×題材20日動能正)", B)
    line(E[E.theme & ~E.reso], "④題材成員但無共振", B)
    line(E[E.dist >= -0.02], "⑤貼126日高(<=2%)", B)
    line(E[E.dist < -0.10], "⑤距高>10%", B)
    print("\n(交乘: 最佳觸發×壓縮×共振)")
    Cc = []
    line(E[(E.compress <= 0.8) & E.reso], "壓縮×共振", Cc)
    line(E[(E.compress <= 0.8) & (E.d4w > 0)], "壓縮×大戶增", Cc)
    line(E[E.reso & E.r1], "共振×營收連創", Cc)

    # ---------- HTML ----------
    CSS = """
body{background:#1a1a19;color:#fff;font-family:"Noto Sans TC",sans-serif;margin:24px;max-width:1100px}
h1{font-size:20px} h2{font-size:15px;color:#c3c2b7;margin-top:28px;border-bottom:1px solid #333;padding-bottom:4px}
table{border-collapse:collapse;font-size:12.5px;font-variant-numeric:tabular-nums;margin:8px 0}
td,th{border:1px solid #333;padding:4px 9px;text-align:right} th{text-align:left;color:#c3c2b7}
.note{color:#8a8878;font-size:12.5px;line-height:1.8} .good{color:#7ec97e} .bad{color:#e06c5a}
.hl{background:#2b3a2b}
ul{margin:4px 0;padding-left:20px;font-size:12.5px;color:#ccc;line-height:1.7}
.scroll{overflow-x:auto}
"""

    def tbl(rows):
        h = ("<div class='scroll'><table><tr><th>組</th><th>n(次/年)</th>"
             + "".join(f"<th>k{k} demean</th>" for k in K_LIST)
             + "<th>k40勝率</th><th>k40賺賠</th></tr>")
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
                  f"<td>{r[40]['win']:.0f}%</td><td>{r[40]['wl']:.2f}</td></tr>")
        return h + "</table></div>"

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>高價股啟動點(2026-08-07)</title><style>{CSS}</style></head><body>
<h1>🔥 高價股啟動點考卷: 觸發定義對決 + winner features</h1>
<div class="note">使用者指正:「20日15%可能太多,不如抓平常振幅小、突然一根大振幅長紅/連續幾天+量放大」。
池=逐日收盤在流動池(20日均額>=0.3億)前5%;進場=訊號次日收盤;同股5日內去重;demean減TAIEX;月群bootstrap。</div>
<h2>① 觸發定義對決</h2>
{tbl(A)}
<h3>絕對>=500元池對照</h3>
{tbl(A500)}
<h2>② winner features(拆最佳觸發: {best_lab})</h2>
{tbl(B)}
<h2>③ 交乘</h2>
{tbl(Cc)}
<h2>⚖️ 判決(2026-08-07)</h2>
<ul>
<li><span style="background:#3b2420;color:#e06c5a;padding:6px 10px;border-radius:4px;font-weight:bold">①五種觸發全部含0=高價股沒有可用的「啟動點」訊號</span>
T5量能結構k40+1.50(最佳)/T1原提案+1.39/T4連兩日+0.70/<b>T3覺醒棒-0.26(最差)</b>——
使用者的覺醒棒定義在高價股上<b>不但沒贏,還是唯一負值</b>;>=500元池對照同樣全含0。
與VCP解剖卷「波動突然放大k120為負」同向=<b>「爆量長紅」在台股是出貨/情緒高點多過起漲點</b>。</li>
<li><span style="background:#3b3420;color:#c3a55a;padding:6px 10px;border-radius:4px;font-weight:bold">②「平常振幅小」的前提在高價股身上幾乎不存在</span>
前置壓縮(20日振幅<=0.8×120日)在最佳觸發組內<b>只有17筆/1,185</b>(1.4%)——高價股=成長股,
本來就長期高波動(穩定性卷已測: 波動42.7%全場最高),「壓縮後爆發」的型態在這個池子裡罕見到無法統計。
若要測壓縮型態,該去中低價股池而非高價池。</li>
<li><span style="background:#243b24;color:#7ec97e;padding:6px 10px;border-radius:4px;font-weight:bold">③唯一活口=大戶4週增加(第N次重現)</span>
觸發後 d4w>0組 k40 <b>+3.01%✓[+0.52,+5.52]</b>/賺賠1.74 vs d4w<=0組+1.28含0/k60轉負-0.51——
<b>觸發本身沒訊號,籌碼方向才有</b>;題材共振(+2.56)與貼高(+2.12)方向正但含0。
與沉寂覺醒卷「52週大戶增幅是唯一真差異因子」完全同構。</li>
<li><b>④實務翻譯</b>: 不要為高價股另立啟動訊號;要用就用既有三條(雙新高/三重門檻/高價新貴)+
<b>大戶4週增加當加分項</b>。使用者的型態直覺(壓縮→爆發)值得換池測(中低價/題材成員),已記待辦。</li>
</ul>
<h2>已知限制</h2>
<div class="note">①高價=逐日相對前5%(跨年代可比),與絕對500元池結論並列;②同股5日去重仍可能同段行情
多次入樣;③除權息未還原;④觸發參數(2x/1.5x/2%)為研究者選定未做敏感度;⑤多重比較(5觸發×多特徵),
判讀靠跨窗一致+勝率賺賠比,不靠單格CI。</div>
<div class="note">維運: python 研究腳本/綜合策略/build_high_price_ignition.py(從根目錄執行)。</div>
</body></html>"""
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n[report] 已輸出 {OUT}")


if __name__ == "__main__":
    main()
