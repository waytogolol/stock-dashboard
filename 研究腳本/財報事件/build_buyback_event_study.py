# -*- coding: utf-8 -*-
"""庫藏股宣告事件研究(2026-08-07,使用者裁示;資料=抓取/fetch_buyback.py→tw_buyback 5,698筆)。

═══ 三問(開卷前自查) ═══
①誰被迫交易?——公司宣告後在買回期間內有執行壓力=**價格不敏感的實際買方**(專案少見的非自願買盤);
  但台股容許「宣告了不買」(執行率0%有65筆/2015後),所以被迫程度是連續光譜,正好可分層。
②資訊是新的嗎?——董事會決議日當天重訊公告,是新事件;但市場對台股庫藏股半信半疑(常視為作帳)。
③為何沒被吃掉?——若有效,機制是「宣告的資訊價值被低估」;若無效,則是市場正確地不信。

═══ 分層設計(嚴格區分可交易 vs 事後解剖) ═══
【宣告當下已知=可交易】
  A目的別: 護盤型(維護信用及股東權益) / 員工型(轉讓員工) / 股權轉換
  B規模: 預定買回股數 ÷ 已發行股數(capital.shares asof)分三層
  C價格區間位置: (宣告前收盤 − 區間下限)/(上限 − 下限)——公司訂的買回區間相對現價在哪
    (>0.8=現價貼近上限,公司願意追高買;<0.2=現價貼近下限/低於下限=已跌破公司認定的便宜區)
  D前置跌幅: 宣告前20日demean報酬(護盤型多在跌後宣告)
  E市場別: 上市/上櫃(既有教訓: 上櫃極端族群訊號多為陷阱)
【事後才知=只能當解剖,不可交易,報告明確標註】
  F執行率(exec_pct): >=95% / 50-95% / 0-50% / 0%——「說到做到 vs 光說不練」的價格差異
進場=董事會決議日**次日收盤**(重訊當日盤後才知,次日可執行,零前視);
outcome=k5/10/20/40/60 demean(上市減TAIEX/上櫃減TPEx);另算「買回期間內」與「期間結束後20日」兩段。
統計=月群bootstrap 95%CI+逐年+勝率/賺賠比;2015後為主樣本(舊制/流動性差異),全樣本並列。
用法: python 研究腳本/財報事件/build_buyback_event_study.py  (從根目錄執行,鐵律)
產出: 研究報告/research_buyback_event.html + console(含權益曲線,規範第19條)
"""
import json
import sqlite3
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

DB = "capital_flow.db"
OUT = "研究報告/research_buyback_event.html"
K_LIST = [5, 10, 20, 40, 60]
START = "2015-01-01"
rng = np.random.default_rng(20260807)


def main():
    conn = sqlite3.connect(DB, timeout=60)
    bb = pd.read_sql("SELECT * FROM tw_buyback", conn)
    px = pd.read_sql("SELECT code,date,open,close,money FROM fm_daily_price "
                     "WHERE date>='2013-06-01' AND close>0 AND money>0 AND open>0", conn)
    idx = pd.read_sql("SELECT market,date,open,close FROM index_daily "
                      "WHERE market IN ('TAIEX','TPEx') AND date>='2013-06-01'", conn)
    cap = pd.read_sql("SELECT code, date, shares FROM capital ORDER BY code, date", conn)
    conn.close()

    C = px.pivot_table(index="date", columns="code", values="close", aggfunc="first").sort_index()
    O = px.pivot_table(index="date", columns="code", values="open", aggfunc="first").sort_index()
    MN = px.pivot_table(index="date", columns="code", values="money", aggfunc="first").sort_index()
    Cf = C.ffill(limit=5)
    dates = list(C.index)
    t_arr = np.array(dates)
    tai = idx[idx.market == "TAIEX"].set_index("date")["close"].reindex(C.index).ffill()
    tpex = idx[idx.market == "TPEx"].set_index("date")["close"].reindex(C.index).ffill()
    tai_o = idx[idx.market == "TAIEX"].set_index("date")["open"].reindex(C.index).ffill()
    tpex_o = idx[idx.market == "TPEx"].set_index("date")["open"].reindex(C.index).ffill()
    liq20 = MN.rolling(20, min_periods=15).mean().shift(1)
    capmap = {c: (g.date.values, g.shares.values) for c, g in cap.groupby("code")}

    def shares_at(code, d):
        """d=ISO字串;capital.date亦為字串(SQL原樣),字串比較=時間比較。"""
        cp = capmap.get(code)
        if cp is None:
            return np.nan
        i = int(np.searchsorted(cp[0], d, side="right")) - 1
        return cp[1][i] if i >= 0 else np.nan

    rows = []
    n_nopx = 0
    for r in bb.itertuples():
        if r.code not in C.columns or not r.board_date:
            n_nopx += 1
            continue
        i = int(np.searchsorted(t_arr, r.board_date))
        if i >= len(dates) - max(K_LIST) - 2 or i < 25:
            continue
        ci = C.columns.get_loc(r.code)
        e = i + 1                                   # 次日收盤進場
        p0 = Cf.iat[e, ci]
        prev = Cf.iat[i, ci]                        # 宣告日收盤(價格區間位置用)
        if pd.isna(p0) or p0 <= 0 or pd.isna(prev):
            continue
        bench = tpex if r.market == "上櫃" else tai
        rec = {"code": r.code, "name": r.name, "market": r.market, "d": dates[i],
               "ym": dates[i][:7], "yr": dates[i][:4], "purpose": r.purpose,
               "exec_pct": r.exec_pct, "liq": liq20.iat[i, ci]}
        bad = False
        for k in K_LIST:
            p1 = Cf.iat[e + k, ci]
            if pd.isna(p1):
                bad = True
                break
            rec[f"dm{k}"] = (p1 / p0 - 1) - (bench.iloc[e + k] / bench.iloc[e] - 1)
        if bad:
            continue
        # 宣告前20日demean(前置跌幅)
        rec["pre20"] = (prev / Cf.iat[i - 20, ci] - 1) - (bench.iloc[i] / bench.iloc[i - 20] - 1)
        # ── 短打口徑(使用者提問): 宣告日/次日/第三日的跳空與盤中拆解 ──
        bo = tpex_o if r.market == "上櫃" else tai_o
        rec["d0_cc"] = prev / Cf.iat[i - 1, ci] - 1                      # 宣告日當天(重訊可能盤中已反應)
        for lag, tag in ((1, "d1"), (2, "d2")):
            oi = i + lag
            if oi >= len(dates):
                continue
            op = O.iat[oi, ci] if oi < len(O) else np.nan
            cl = Cf.iat[oi, ci]
            pv = Cf.iat[oi - 1, ci]
            if pd.isna(op) or pd.isna(cl) or pd.isna(pv) or op <= 0 or pv <= 0:
                continue
            b_op, b_cl, b_pv = bo.iloc[oi], bench.iloc[oi], bench.iloc[oi - 1]
            rec[f"{tag}_gap"] = (op / pv - 1) - (b_op / b_pv - 1)        # 跳空(demean)
            rec[f"{tag}_oc"] = (cl / op - 1) - (b_cl / b_op - 1)         # 開盤買→收盤賣(當沖,demean)
            rec[f"{tag}_oc_abs"] = cl / op - 1                            # 絕對(成本敏感度用)
            rec[f"{tag}_cc"] = (cl / pv - 1) - (b_cl / b_pv - 1)         # 前收→收盤
        # 規模: 預定買回股數/已發行股數
        sh = shares_at(r.code, r.board_date)
        rec["size_pct"] = (r.planned_shares / sh * 100) if (pd.notna(sh) and sh > 0
                                                            and pd.notna(r.planned_shares)) else np.nan
        # 價格區間位置
        if pd.notna(r.price_low) and pd.notna(r.price_high) and r.price_high > r.price_low:
            rec["band_pos"] = (prev - r.price_low) / (r.price_high - r.price_low)
        else:
            rec["band_pos"] = np.nan
        # 買回期間內/期間後20日
        if r.period_end:
            j = int(np.searchsorted(t_arr, r.period_end))
            if e < j < len(dates) - 21:
                pj = Cf.iat[j, ci]
                pj20 = Cf.iat[j + 20, ci]
                if pd.notna(pj) and pd.notna(pj20):
                    rec["in_period"] = (pj / p0 - 1) - (bench.iloc[j] / bench.iloc[e] - 1)
                    rec["post_period20"] = (pj20 / pj - 1) - (bench.iloc[j + 20] / bench.iloc[j] - 1)
        rows.append(rec)
    E = pd.DataFrame(rows)
    E15 = E[E.d >= START]
    print(f"[panel] 事件{len(E):,}筆(無價格略過{n_nopx}) 全期{E.d.min()}~{E.d.max()}; "
          f"2015後{len(E15):,}筆; 上市{int((E15.market == '上市').sum())}/上櫃{int((E15.market == '上櫃').sum())}")

    def boot(sub, col):
        s = sub[["ym", col]].dropna()
        if len(s) < 30 or s.ym.nunique() < 8:
            return None
        grp = {m: g[col].values for m, g in s.groupby("ym")}
        keys = list(grp)
        means = [np.mean(np.concatenate([grp[m] for m in rng.choice(keys, len(keys))]))
                 for _ in range(1000)]
        lo, hi = np.percentile(means, [2.5, 97.5])
        return {"mean": s[col].mean() * 100, "lo": lo * 100, "hi": hi * 100,
                "sig": bool(lo > 0 or hi < 0)}

    def line(sub, lab, out):
        if len(sub) < 30:
            print(f"  {lab:<34} n={len(sub)} 不足")
            return None
        r = {"lab": lab, "n": len(sub)}
        for k in K_LIST:
            b = boot(sub, f"dm{k}")
            v = sub[f"dm{k}"].dropna()
            w, l = v[v > 0], v[v <= 0]
            r[k] = {"mean": v.mean() * 100, "b": b, "win": len(w) / len(v) * 100 if len(v) else np.nan,
                    "wl": (w.mean() / abs(l.mean())) if len(w) and len(l) else np.nan}
        y = sub.groupby("yr")["dm40"].mean()
        r["yr"] = f"{int((y > 0).sum())}/{len(y)}"
        r["pre20"] = sub.pre20.mean() * 100
        out.append(r)
        b20, b40 = r[20], r[40]
        print(f"  {lab:<34} n={r['n']:>5,} 前20日{r['pre20']:+.1f}% | k5:{r[5]['mean']:+.2f} "
              f"k20:{b20['mean']:+.2f}"
              + (f"[{b20['b']['lo']:+.2f},{b20['b']['hi']:+.2f}]{'✓' if b20['b']['sig'] else ''}" if b20["b"] else "")
              + f" k40:{b40['mean']:+.2f}"
              + (f"[{b40['b']['lo']:+.2f},{b40['b']['hi']:+.2f}]{'✓' if b40['b']['sig'] else ''}" if b40["b"] else "")
              + f" k60:{r[60]['mean']:+.2f} 勝率{b40['win']:.0f}% 賺賠{b40['wl']:.2f} 逐年{r['yr']}")
        return r

    print("\n" + "=" * 108)
    print("① 全體 + 目的別(2015後;可交易分層)")
    A = []
    line(E15, "全體庫藏股宣告", A)
    line(E15[E15.purpose == "維護信用及股東權益"], "A護盤型(維護信用及股東權益)", A)
    line(E15[E15.purpose == "轉讓員工"], "A員工型(轉讓股份予員工)", A)
    line(E15[E15.market == "上市"], "E上市", A)
    line(E15[E15.market == "上櫃"], "E上櫃", A)
    print("\n(全樣本2000起對照)")
    A0 = []
    line(E, "全樣本全體", A0)
    line(E[E.purpose == "維護信用及股東權益"], "全樣本護盤型", A0)

    print("\n② 規模/價格區間位置/前置跌幅(2015後,宣告當下已知)")
    B = []
    q = E15.size_pct.quantile([0.33, 0.67])
    line(E15[E15.size_pct >= q.iloc[1]], f"B規模大(預定買回>={q.iloc[1]:.1f}%股本)", B)
    line(E15[E15.size_pct < q.iloc[0]], f"B規模小(<{q.iloc[0]:.1f}%股本)", B)
    line(E15[E15.band_pos >= 0.8], "C現價貼近區間上限(>=0.8,公司願追高)", B)
    line(E15[(E15.band_pos >= 0.2) & (E15.band_pos < 0.8)], "C現價區間中段(0.2-0.8)", B)
    line(E15[E15.band_pos < 0.2], "C現價貼近/低於區間下限(<0.2)", B)
    line(E15[E15.pre20 <= -0.10], "D宣告前20日重挫<=-10%", B)
    line(E15[E15.pre20 >= 0], "D宣告前20日未跌", B)
    print("\n  護盤型×前置重挫交乘:")
    line(E15[(E15.purpose == "維護信用及股東權益") & (E15.pre20 <= -0.10)], "護盤型×前20日<=-10%", B)

    print("\n③ 執行率分層(⚠事後資訊,解剖用不可交易)")
    Cx = []
    line(E15[E15.exec_pct >= 95], "F執行率>=95%(說到做到)", Cx)
    line(E15[(E15.exec_pct >= 50) & (E15.exec_pct < 95)], "F執行率50-95%", Cx)
    line(E15[(E15.exec_pct > 0) & (E15.exec_pct < 50)], "F執行率0-50%", Cx)
    line(E15[E15.exec_pct == 0], "F執行率0%(宣告不買)", Cx)

    print("\n④ 買回期間內 vs 期間後20日(2015後)")
    per = {}
    for lab, sub in (("全體", E15), ("護盤型", E15[E15.purpose == "維護信用及股東權益"]),
                     ("員工型", E15[E15.purpose == "轉讓員工"])):
        ip, pp = sub.in_period.dropna(), sub.post_period20.dropna()
        if len(ip) < 30:
            continue
        b_ip, b_pp = boot(sub, "in_period"), boot(sub, "post_period20")
        per[lab] = {"n": len(ip), "ip": ip.mean() * 100, "pp": pp.mean() * 100,
                    "b_ip": b_ip, "b_pp": b_pp}
        print(f"  {lab:<8} n={len(ip):,} 期間內{ip.mean() * 100:+.2f}%"
              + (f"[{b_ip['lo']:+.2f},{b_ip['hi']:+.2f}]{'✓' if b_ip['sig'] else ''}" if b_ip else "")
              + f" 期間後20日{pp.mean() * 100:+.2f}%"
              + (f"[{b_pp['lo']:+.2f},{b_pp['hi']:+.2f}]{'✓' if b_pp['sig'] else ''}" if b_pp else ""))

    print("\n⑤ 短打口徑(使用者提問: 宣告後第一天開盤買→收盤賣會賺嗎?第二天呢?)")
    short_rows = []

    def short_line(sub, lab):
        if len(sub) < 30:
            print(f"  {lab:<28} n={len(sub)} 不足")
            return
        r = {"lab": lab, "n": len(sub), "d0": sub.d0_cc.mean() * 100}
        for tag, nm in (("d1", "次日"), ("d2", "第三日")):
            g, oc, cc = sub[f"{tag}_gap"].dropna(), sub[f"{tag}_oc"].dropna(), sub[f"{tag}_cc"].dropna()
            b = boot(sub, f"{tag}_oc")
            r[tag] = {"gap": g.mean() * 100, "oc": oc.mean() * 100, "cc": cc.mean() * 100,
                      "oc_abs": sub[f"{tag}_oc_abs"].dropna().mean() * 100,
                      "win": (oc > 0).mean() * 100 if len(oc) else np.nan, "b": b}
        short_rows.append(r)
        d1, d2 = r["d1"], r["d2"]
        print(f"  {lab:<28} n={r['n']:>5,} 宣告日{r['d0']:+.2f}% | "
              f"次日: 跳空{d1['gap']:+.2f}% 當沖oc{d1['oc']:+.2f}%"
              + (f"[{d1['b']['lo']:+.2f},{d1['b']['hi']:+.2f}]{'✓' if d1['b']['sig'] else ''}" if d1["b"] else "")
              + f"(絕對{d1['oc_abs']:+.2f}%/勝率{d1['win']:.0f}%) 全日cc{d1['cc']:+.2f}% | "
              f"第三日: 跳空{d2['gap']:+.2f}% 當沖oc{d2['oc']:+.2f}%"
              + (f"[{d2['b']['lo']:+.2f},{d2['b']['hi']:+.2f}]{'✓' if d2['b']['sig'] else ''}" if d2["b"] else "")
              + f"(絕對{d2['oc_abs']:+.2f}%)")

    short_line(E15, "全體")
    short_line(E15[E15.purpose == "維護信用及股東權益"], "護盤型")
    short_line(E15[E15.purpose == "轉讓員工"], "員工型")
    short_line(E15[E15.size_pct >= q.iloc[1]], f"規模大(>={q.iloc[1]:.1f}%股本)")
    short_line(E15[E15.pre20 <= -0.10], "前20日重挫<=-10%")
    short_line(E15[E15.market == "上市"], "上市")
    short_line(E15[E15.market == "上櫃"], "上櫃")

    # ---------- HTML ----------
    CSS = """
body{background:#1a1a19;color:#fff;font-family:"Noto Sans TC",sans-serif;margin:24px;max-width:1150px}
h1{font-size:20px} h2{font-size:15px;color:#c3c2b7;margin-top:28px;border-bottom:1px solid #333;padding-bottom:4px}
table{border-collapse:collapse;font-size:12.5px;font-variant-numeric:tabular-nums;margin:8px 0}
td,th{border:1px solid #333;padding:4px 9px;text-align:right} th{text-align:left;color:#c3c2b7}
.note{color:#8a8878;font-size:12.5px;line-height:1.8} .good{color:#7ec97e} .bad{color:#e06c5a}
.hl{background:#2b3a2b} .scroll{overflow-x:auto}
.banner{background:#3a2a1a;border:1px solid #c3a55a;border-radius:6px;padding:12px 16px;margin:14px 0;
        color:#f0dfa8;font-size:13px;line-height:1.8}
ul{margin:4px 0;padding-left:20px;font-size:12.5px;color:#ccc;line-height:1.7}
"""

    def tbl(rows):
        h = ("<div class='scroll'><table><tr><th>組</th><th>n</th><th>宣告前20日</th>"
             + "".join(f"<th>k{k}</th>" for k in K_LIST)
             + "<th>k40勝率</th><th>k40賺賠</th><th>逐年40</th></tr>")
        best = max(rows, key=lambda r: r[40]["mean"]) if rows else None
        for r in rows:
            cells = ""
            for k in K_LIST:
                s = r[k]
                ci = (f"<br><span style='color:#777;font-size:10.5px'>[{s['b']['lo']:+.2f},{s['b']['hi']:+.2f}]"
                      f"{'✓' if s['b']['sig'] else ''}</span>" if s["b"] else "")
                cells += f"<td>{s['mean']:+.2f}%{ci}</td>"
            h += (f"<tr{' class=hl' if r is best else ''}><th>{r['lab']}</th><td>{r['n']:,}</td>"
                  f"<td>{r['pre20']:+.1f}%</td>{cells}<td>{r[40]['win']:.0f}%</td>"
                  f"<td>{r[40]['wl']:.2f}</td><td>{r['yr']}</td></tr>")
        return h + "</table></div>"

    per_html = ("<table><tr><th>組</th><th>n</th><th>買回期間內</th><th>期間結束後20日</th></tr>"
                + "".join(f"<tr><th>{k}</th><td>{v['n']:,}</td>"
                          f"<td>{v['ip']:+.2f}%{'✓' if v['b_ip'] and v['b_ip']['sig'] else ''}</td>"
                          f"<td>{v['pp']:+.2f}%{'✓' if v['b_pp'] and v['b_pp']['sig'] else ''}</td></tr>"
                          for k, v in per.items()) + "</table>")

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>庫藏股宣告事件研究(2026-08-07)</title><style>{CSS}</style></head><body>
<h1>🏢 庫藏股宣告事件研究: 目的別 × 規模 × 價格區間 × 執行率</h1>
<div class="note">資料=tw_buyback(MOPS,5,698筆/1,205家/2000-2026,抓取/fetch_buyback.py)。
進場=<b>董事會決議日次日收盤</b>(重訊當日盤後才知,零前視);demean=上市減TAIEX/上櫃減TPEx;
2015後為主樣本,全樣本並列;月群bootstrap 95%CI。</div>
<div class="banner">⚠<b>可交易 vs 事後解剖的界線</b>: ①②段(目的別/規模/價格區間位置/前置跌幅/市場別)
都是<b>宣告當下已知</b>=可交易分層;③段執行率是<b>買回期間結束後才知道</b>=只能當事後解剖,
<b>不可當進場條件</b>(否則是前視)。這條界線是本卷最重要的方法論紀律。</div>
<h2>① 全體 + 目的別 + 市場別(2015後)</h2>
{tbl(A)}
<h3>全樣本(2000起)對照</h3>
{tbl(A0)}
<h2>② 規模 / 價格區間位置 / 前置跌幅(宣告當下已知=可交易)</h2>
{tbl(B)}
<h2>③ 執行率分層(⚠事後資訊,解剖用)</h2>
{tbl(Cx)}
<h2>④ 買回期間內 vs 期間結束後20日</h2>
{per_html}
<h2>⑤ 短打口徑: 宣告後第一天/第二天「開盤買→收盤賣」(使用者提問)</h2>
<div class="note">跳空=前收→開盤(demean);當沖oc=開盤買→當日收盤賣(demean,括號內為<b>絕對報酬</b>——
當沖成本敏感,券商當沖來回約0.15-0.3%,絕對報酬要大於成本才有意義);全日cc=前收→收盤。</div>
<div class='scroll'><table><tr><th>組</th><th>n</th><th>宣告日</th>
<th>次日跳空</th><th>次日當沖oc(絕對/勝率)</th><th>次日全日cc</th>
<th>第三日跳空</th><th>第三日當沖oc(絕對)</th></tr>
{"".join(f"<tr><th>{r['lab']}</th><td>{r['n']:,}</td><td>{r['d0']:+.2f}%</td>"
         f"<td>{r['d1']['gap']:+.2f}%</td>"
         f"<td>{r['d1']['oc']:+.2f}%" + (f"[{r['d1']['b']['lo']:+.2f},{r['d1']['b']['hi']:+.2f}]{'✓' if r['d1']['b']['sig'] else ''}" if r['d1']['b'] else "") + f"<br><span class='hint'>絕對{r['d1']['oc_abs']:+.2f}%/勝率{r['d1']['win']:.0f}%</span></td>"
         f"<td>{r['d1']['cc']:+.2f}%</td><td>{r['d2']['gap']:+.2f}%</td>"
         f"<td>{r['d2']['oc']:+.2f}%<br><span class='hint'>絕對{r['d2']['oc_abs']:+.2f}%</span></td></tr>"
         for r in short_rows)}
</table></div>
<h2>⚖️ 判決(2026-08-07首輪)</h2>
<ul>
<li><span style="background:#3b3420;color:#c3a55a;padding:6px 10px;border-radius:4px;font-weight:bold">
①宣告效應存在但短命</span> 全體k5+1.01/<b>k20+1.70✓</b>/k40+1.16含0/<b>k60-0.46(歸零)</b>——
宣告後一個月有肉,兩個月後消失;宣告前20日平均-4.0%=<b>庫藏股是跌後才宣告的反應型事件</b>,
不是預測型訊號。</li>
<li><span style="background:#3b2420;color:#e06c5a;padding:6px 10px;border-radius:4px;font-weight:bold">
②反直覺一: 護盤型比員工型<b>差</b></span> 護盤型(維護信用及股東權益)k20+0.75含0/k40-0.26/k60-1.65
vs 員工型k20<b>+2.23✓</b>/k40+1.98/勝率52%——「公司出來救股價」聽起來最有力,實際最弱;
機制解讀=<b>護盤型宣告本身是「股價已經很糟」的自我揭露</b>(前20日-3.8%且多在恐慌期),
員工型則常伴隨成長期發放員工股票的正常經營節奏。</li>
<li><span style="background:#243b24;color:#7ec97e;padding:6px 10px;border-radius:4px;font-weight:bold">
③可交易分層: <b>規模</b>是最好的篩子</span> 預定買回<b>>=2.6%股本</b>: k5+1.66/k20<b>+2.90✓</b>/k40+3.42/
勝率56%/賺賠1.36 vs 規模小(<1.4%)k20+0.65含0/k40-0.67——<b>買多少比為什麼買更重要</b>;
價格區間位置<0.2(現價已跌破公司訂的買回下限)k20+3.50/k40+3.84/勝率58%/賺賠1.42方向最好但含0(n=220)。</li>
<li><span style="background:#3b2420;color:#e06c5a;padding:6px 10px;border-radius:4px;font-weight:bold">
④反直覺二(本卷最有價值的機制): 執行率與報酬<b>負相關</b>——但這不是策略,是內生性</span>
執行率>=95%(說到做到): k40<b>-1.67</b>/賺賠0.87(最差);執行率0-50%: k40<b>+5.67✓</b>;
執行率0%(宣告了不買): k20<b>+6.22✓</b>/賺賠2.23(最好)。<b>機制=執行率內生於股價</b>:
股價一直不漲→公司只好買好買滿;股價自己漲過買回區間上限→公司不買了。
⚠所以<b>「挑執行率高的買」是錯的推論</b>(且執行率事後才知=不可交易),
本段的正確用途是<b>反向理解</b>: 看到公司拼命執行,代表市場沒有跟進。</li>
<li><span style="background:#243b24;color:#7ec97e;padding:6px 10px;border-radius:4px;font-weight:bold">
⑤可交易的出場紀律: <b>買回期間結束後20日顯著為負</b></span>
全體-1.88%✓[-2.70,-0.96]/護盤型-1.80✓/員工型-1.92✓——公司買盤退場後回吐,
而<b>期間結束日在宣告時就已知</b>(period_end欄位)=這是本卷唯一乾淨可執行的規則:
<b>不要抱過買回期間結束日</b>。</li>
<li><b>⑥實務配方(候選層)</b>: 宣告日次日收盤進場,只做<b>預定買回≥2.6%股本</b>(可加碼條件: 現價已跌破
買回區間下限),持有約20交易日且<b>不超過買回期間結束日</b>;護盤型不加分、執行率別當篩選。
⚠樣本1,330筆(2015後,受fm_daily_price流動池覆蓋限制),k40多數含0=定位候選層。</li>
</ul>
<h2>已知限制</h2>
<div class="note">①除權息未還原(長窗保守偏誤);②同公司多次宣告未去重(頻繁買回的公司權重較高);
③2015前樣本含舊制與低流動性個股,故主樣本取2015後;④價格區間位置用宣告日收盤,
公司訂區間時可能參考更早價格;⑤執行率分層天生事後(已標註);⑥多重比較(多分層×5窗)。</div>
<div class="note">維運: python 研究腳本/財報事件/build_buyback_event_study.py(從根目錄執行);
資料更新=python 抓取/fetch_buyback.py(已掛update_all週頻)。</div>
</body></html>"""
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n[report] 已輸出 {OUT}")


if __name__ == "__main__":
    main()
