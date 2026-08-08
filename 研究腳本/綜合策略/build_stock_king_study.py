# -*- coding: utf-8 -*-
"""股王研究考卷(2026-08-07,使用者兩假說):
①「上市股價最高 vs 上櫃股價最高的表現,是否影響/預示大盤強弱?」
②「股王換人時,動能是否很強?」

承接: high_price_stability(高價非因子)、high_price_followup(前5%組RS溫度計三關過安慰劑)。
本卷把「一籃子前5%」縮到極致=**單一股王**,看單股訊號能否複製RS溫度計的大盤預示力,
並測「換王事件」的個股動能(里程碑事件家族: 高價新貴k40+5.66✓的極致版)。

═══ 設計(預先註冊) ═══
股王定義: 每個交易日,池內(20日均額>=0.3億,排除ETF/權證代碼>=4碼非普通股)收盤價最高者,
  上市/上櫃各一位。⚠不設價格門檻(讓資料決定),但要求連續性去雜訊: 換王須「新王收盤價高於舊王」
  且維持>=3個交易日才算正式換王(避免單日插花)。
①大盤預示: 股王近20/60日報酬 減 對應指數 = 股王RS;RS>0 vs <=0 → 下月(20交易日)指數報酬;
  另測「上市股王RS − 上櫃股王RS」的蹺蹺板(誰強代表資金偏好大型或中小型)。
  對照組=前5%籃子RS(followup卷已驗證+2.12pp),看單股版是否更強/更弱=**簡化成本值不值得**。
②換王事件: 新王上任日=事件日,進場=次日收盤(可執行),k20/40/60 demean;
  對照=(a)舊王被超越後的後續(是否見頂) (b)同期高價新貴事件(引用followup卷+5.66✓)。
  另測換王頻率(每年換幾次)當市場情緒指標: 高換王年 vs 低換王年的大盤表現。
統計: 月群bootstrap(大盤段用月報酬序列,樣本天生小=觀察層);事件段用月群+逐年。
用法: python 研究腳本/綜合策略/build_stock_king_study.py  (從根目錄執行,鐵律)
產出: 研究報告/research_stock_king.html + console
"""
import json
import sqlite3
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

DB = "capital_flow.db"
OUT = "研究報告/research_stock_king.html"
LIQ_MIN = 0.3e8
MIN_REIGN = 3          # 新王須維持>=3交易日才算正式換王
K_LIST = [20, 40, 60]
rng = np.random.default_rng(20260807)


def main():
    conn = sqlite3.connect(DB, timeout=60)
    px = pd.read_sql("SELECT code,date,close,money FROM fm_daily_price "
                     "WHERE date>='2014-06-01' AND close>0 AND money>0", conn)
    idx = pd.read_sql("SELECT market,date,close FROM index_daily "
                      "WHERE market IN ('TAIEX','TPEx') AND date>='2014-06-01'", conn)
    conn.close()
    mkt = pd.read_csv("tw_all_listed.csv", dtype=str).dropna(subset=["code"])
    mkt_of = dict(zip(mkt.code, mkt.market.fillna("")))
    name_of = dict(zip(mkt.code, mkt.name.fillna("")))

    C = px.pivot_table(index="date", columns="code", values="close", aggfunc="first").sort_index()
    MN = px.pivot_table(index="date", columns="code", values="money", aggfunc="first").sort_index()
    dates = list(C.index)
    Cf = C.ffill(limit=5)
    liq_ok = (MN.rolling(20, min_periods=15).mean().shift(1) >= LIQ_MIN)
    tai = idx[idx.market == "TAIEX"].set_index("date")["close"].reindex(C.index).ffill()
    tpex = idx[idx.market == "TPEx"].set_index("date")["close"].reindex(C.index).ffill()

    def is_otc(c):
        m = mkt_of.get(c, "")
        return ("櫃" in m) or (m == "TWO")

    otc = {c: is_otc(c) for c in C.columns}
    listed = {c for c in C.columns if mkt_of.get(c, "") in ("上市", "上櫃")}   # 排除興櫃/未對應
    start_i = int(np.searchsorted(np.array(dates), "2015-01-01"))

    # ---------- 每日股王 ----------
    kings = {"上市": [], "上櫃": []}
    for i in range(start_i, len(dates)):
        row = C.iloc[i]
        ok = liq_ok.iloc[i]
        for mk, want_otc in (("上市", False), ("上櫃", True)):
            cand = [(row[c], c) for c in C.columns
                    if c in listed and otc[c] == want_otc and pd.notna(row.get(c))
                    and bool(ok.get(c, False))]
            kings[mk].append(max(cand)[1] if cand else None)
    king_df = pd.DataFrame(kings, index=dates[start_i:])
    for mk in ("上市", "上櫃"):
        cur = king_df[mk].tolist()
        n_uni = len({x for x in cur if x})
        print(f"[king] {mk}股王: 歷任{n_uni}位; 現任={cur[-1]}({name_of.get(cur[-1], '')}) "
              f"收盤{C.iloc[-1][cur[-1]]:.0f}元")

    # 正式換王事件(新王須維持>=MIN_REIGN日)
    events = []
    for mk in ("上市", "上櫃"):
        s = king_df[mk].tolist()
        idxs = king_df.index.tolist()
        prev = s[0]
        for j in range(1, len(s)):
            if s[j] and s[j] != prev:
                if all(s[j + t] == s[j] for t in range(min(MIN_REIGN, len(s) - j))):
                    events.append({"market": mk, "d": idxs[j], "new": s[j], "old": prev})
                    prev = s[j]
            elif s[j]:
                prev = s[j]
    EV = pd.DataFrame(events)
    print(f"[換王] 正式換王事件{len(EV)}次(上市{int((EV.market == '上市').sum())}/"
          f"上櫃{int((EV.market == '上櫃').sum())}),年均{len(EV) / 11.5:.1f}次")
    print("  近8次:", [(r.d, r.market, f"{r.old}→{r.new}") for r in EV.tail(8).itertuples()])

    # ---------- ① 大盤預示 ----------
    didx = pd.to_datetime(pd.Index(dates))
    mf = [i for i in np.where(~didx.to_period("M").duplicated())[0] if i >= start_i]
    rows = []
    for a, b in zip(mf[:-1], mf[1:]):
        d_a = dates[a]
        if d_a not in king_df.index:
            continue
        rec = {"d": d_a, "tai": tai.iloc[b] / tai.iloc[a] - 1, "tpex": tpex.iloc[b] / tpex.iloc[a] - 1}
        for mk, bench in (("上市", tai), ("上櫃", tpex)):
            k = king_df.loc[d_a, mk]
            if k and pd.notna(C.iloc[a].get(k)) and pd.notna(Cf.iloc[b].get(k)):
                rec[f"king_{mk}"] = (Cf.iloc[b][k] / C.iloc[a][k] - 1) - (bench.iloc[b] / bench.iloc[a] - 1)
        rows.append(rec)
    M = pd.DataFrame(rows)
    for mk in ("上市", "上櫃"):
        M[f"rs3_{mk}"] = M[f"king_{mk}"].rolling(3).mean()
    M["nxt_tai"] = M.tai.shift(-1)
    M["nxt_tpex"] = M.tpex.shift(-1)
    M["seesaw"] = M.rs3_上市 - M.rs3_上櫃

    print("\n① 股王RS → 下月指數(月頻,觀察層)")
    P1 = []
    for lab, col, tgt in (("上市股王RS3>0", "rs3_上市", "nxt_tai"),
                          ("上櫃股王RS3>0", "rs3_上櫃", "nxt_tpex"),
                          ("蹺蹺板(上市王-上櫃王)>0", "seesaw", "nxt_tai")):
        s = M.dropna(subset=[col, tgt])
        pos, neg = s[s[col] > 0][tgt], s[s[col] <= 0][tgt]
        if len(pos) < 10 or len(neg) < 10:
            continue
        r = {"lab": lab, "pos_m": pos.mean() * 100, "pos_w": (pos > 0).mean() * 100, "pos_n": len(pos),
             "neg_m": neg.mean() * 100, "neg_w": (neg > 0).mean() * 100, "neg_n": len(neg),
             "diff": (pos.mean() - neg.mean()) * 100,
             "corr": float(np.corrcoef(s[col], s[tgt])[0, 1])}
        P1.append(r)
        print(f"  {lab:<22} >0時下月{r['pos_m']:+.2f}%(n={r['pos_n']},勝{r['pos_w']:.0f}%) vs "
              f"<=0時{r['neg_m']:+.2f}%(n={r['neg_n']},勝{r['neg_w']:.0f}%) "
              f"價差{r['diff']:+.2f}pp corr={r['corr']:+.3f}")
    print("  對照: 前5%籃子RS版(high_price_followup卷)=價差+2.12pp/勝率69% vs 55%")

    # ---------- ② 換王事件 ----------
    def ev_returns(codes_dates, bench_map):
        out = []
        for mk, d, code in codes_dates:
            if code not in C.columns or d not in king_df.index:
                continue
            i = dates.index(d)
            if i + max(K_LIST) + 2 >= len(dates):
                continue
            ci = C.columns.get_loc(code)
            e = i + 1
            p0 = Cf.iat[e, ci]
            if pd.isna(p0) or p0 <= 0:
                continue
            bench = bench_map[mk]
            rec = {"market": mk, "d": d, "ym": d[:7], "yr": d[:4], "code": code}
            bad = False
            for k in K_LIST:
                p1 = Cf.iat[e + k, ci]
                if pd.isna(p1):
                    bad = True
                    break
                rec[f"dm{k}"] = (p1 / p0 - 1) - (bench.iloc[e + k] / bench.iloc[e] - 1)
            if not bad:
                out.append(rec)
        return pd.DataFrame(out)

    bench_map = {"上市": tai, "上櫃": tpex}
    NEW = ev_returns([(r.market, r.d, r.new) for r in EV.itertuples()], bench_map)
    OLD = ev_returns([(r.market, r.d, r.old) for r in EV.itertuples()], bench_map)

    def boot(E, col):
        if len(E) < 20 or E.ym.nunique() < 6:
            return None
        grp = {m: g[col].values for m, g in E.groupby("ym")}
        keys = list(grp)
        means = [np.mean(np.concatenate([grp[m] for m in rng.choice(keys, len(keys))]))
                 for _ in range(1000)]
        lo, hi = np.percentile(means, [2.5, 97.5])
        return {"mean": E[col].mean() * 100, "lo": lo * 100, "hi": hi * 100,
                "sig": bool(lo > 0 or hi < 0)}

    def line(E, lab, out):
        if len(E) < 15:
            print(f"  {lab:<26} n={len(E)} 不足")
            return
        r = {"lab": lab, "n": len(E)}
        for k in K_LIST:
            b = boot(E, f"dm{k}")
            v = E[f"dm{k}"]
            w, l = v[v > 0], v[v <= 0]
            r[k] = {"mean": v.mean() * 100, "b": b, "win": len(w) / len(v) * 100,
                    "wl": (w.mean() / abs(l.mean())) if len(w) and len(l) else np.nan}
        y = E.groupby("yr")["dm40"].mean()
        r["yr"] = f"{int((y > 0).sum())}/{len(y)}"
        out.append(r)
        b40 = r[40]
        print(f"  {lab:<26} n={r['n']:>4} k20:{r[20]['mean']:+.2f} k40:{b40['mean']:+.2f}"
              + (f"[{b40['b']['lo']:+.2f},{b40['b']['hi']:+.2f}]{'✓' if b40['b']['sig'] else ''}" if b40["b"] else "")
              + f" k60:{r[60]['mean']:+.2f} 勝率{b40['win']:.0f}% 賺賠{b40['wl']:.2f} 逐年{r['yr']}")

    print("\n② 換王事件(新王上任日次日收盤進場)")
    P2 = []
    line(NEW, "新王(全部)", P2)
    line(NEW[NEW.market == "上市"], "新王·上市", P2)
    line(NEW[NEW.market == "上櫃"], "新王·上櫃", P2)
    line(OLD, "舊王(被超越後)", P2)
    line(OLD[OLD.market == "上市"], "舊王·上市", P2)

    # 換王頻率 vs 大盤
    print("\n③ 換王頻率(年)與大盤表現")
    freq = EV.assign(yr=EV.d.str[:4]).groupby("yr").size()
    tai_y = tai.groupby(pd.to_datetime(pd.Index(dates)).year).last()
    tai_yr = (tai_y / tai_y.shift(1) - 1).dropna() * 100
    freq_rows = []
    for y, n in freq.items():
        r = tai_yr.get(int(y), np.nan)
        freq_rows.append({"yr": y, "n": int(n), "tai": r})
        print(f"  {y}: 換王{n}次 TAIEX年報酬{r:+.1f}%" if pd.notna(r) else f"  {y}: 換王{n}次")
    fr = pd.DataFrame(freq_rows).dropna()
    if len(fr) >= 6:
        cc = float(np.corrcoef(fr.n, fr.tai)[0, 1])
        print(f"  corr(換王次數, 當年TAIEX報酬)={cc:+.3f}")
    else:
        cc = np.nan

    # ---------- HTML ----------
    CSS = """
body{background:#1a1a19;color:#fff;font-family:"Noto Sans TC",sans-serif;margin:24px;max-width:1050px}
h1{font-size:20px} h2{font-size:15px;color:#c3c2b7;margin-top:28px;border-bottom:1px solid #333;padding-bottom:4px}
table{border-collapse:collapse;font-size:12.5px;font-variant-numeric:tabular-nums;margin:8px 0}
td,th{border:1px solid #333;padding:4px 9px;text-align:right} th{text-align:left;color:#c3c2b7}
.note{color:#8a8878;font-size:12.5px;line-height:1.8} .good{color:#7ec97e} .bad{color:#e06c5a}
.hl{background:#2b3a2b} .scroll{overflow-x:auto}
ul{margin:4px 0;padding-left:20px;font-size:12.5px;color:#ccc;line-height:1.7}
"""
    t1 = ("<table><tr><th>訊號</th><th>RS>0時下月指數</th><th>RS<=0時</th><th>價差</th><th>corr</th></tr>"
          + "".join(f"<tr><th>{r['lab']}</th><td>{r['pos_m']:+.2f}%(n={r['pos_n']},勝{r['pos_w']:.0f}%)</td>"
                    f"<td>{r['neg_m']:+.2f}%(n={r['neg_n']},勝{r['neg_w']:.0f}%)</td>"
                    f"<td><b>{r['diff']:+.2f}pp</b></td><td>{r['corr']:+.3f}</td></tr>" for r in P1)
          + "<tr><th>對照: 前5%籃子RS(followup卷)</th><td>+2.25%(勝69%)</td><td>+0.13%(勝55%)</td>"
            "<td><b>+2.12pp</b></td><td>+0.253</td></tr></table>")

    def tbl(rows):
        h = ("<div class='scroll'><table><tr><th>組</th><th>n</th>"
             + "".join(f"<th>k{k} demean</th>" for k in K_LIST)
             + "<th>k40勝率</th><th>k40賺賠</th><th>逐年40</th></tr>")
        for r in rows:
            cells = ""
            for k in K_LIST:
                s = r[k]
                ci = (f"<br><span style='color:#777;font-size:10.5px'>[{s['b']['lo']:+.2f},{s['b']['hi']:+.2f}]"
                      f"{'✓' if s['b']['sig'] else ''}</span>" if s["b"] else "")
                cells += f"<td>{s['mean']:+.2f}%{ci}</td>"
            h += (f"<tr><th>{r['lab']}</th><td>{r['n']}</td>{cells}"
                  f"<td>{r[40]['win']:.0f}%</td><td>{r[40]['wl']:.2f}</td><td>{r['yr']}</td></tr>")
        return h + "</table></div>"

    reign = "".join(f"<tr><td>{r.d}</td><td>{r.market}</td><td>{r.old}{name_of.get(r.old, '')}</td>"
                    f"<td>{r.new}{name_of.get(r.new, '')}</td></tr>" for r in EV.tail(15).itertuples())
    freq_html = ("<table><tr><th>年</th><th>換王次數</th><th>TAIEX年報酬</th></tr>"
                 + "".join(f"<tr><th>{r['yr']}</th><td>{r['n']}</td>"
                           f"<td>{r['tai']:+.1f}%</td></tr>" if pd.notna(r["tai"]) else
                           f"<tr><th>{r['yr']}</th><td>{r['n']}</td><td>—</td></tr>" for r in freq_rows)
                 + "</table>")

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>股王研究(2026-08-07)</title><style>{CSS}</style></head><body>
<h1>👑 股王研究: 兩市股王RS能否預示大盤 + 換王動能</h1>
<div class="note">使用者兩假說。股王=每日池內(20日均額>=0.3億)收盤價最高者,上市/上櫃各一;
正式換王須新王維持>=3交易日(去單日插花)。2015起。⚠單股訊號樣本天生小=觀察層。</div>
<h2>① 股王RS → 下月指數(月頻)</h2>
{t1}
<h2>② 換王事件(新王上任次日收盤進場)</h2>
{tbl(P2)}
<h3>近15次換王</h3>
<table><tr><th>日期</th><th>市場</th><th>舊王</th><th>新王</th></tr>{reign}</table>
<h2>③ 換王頻率與大盤(corr={cc:+.3f} if 有值)</h2>
{freq_html}
<h2>⚖️ 判決(2026-08-07)</h2>
<ul>
<li><span style="background:#3b3420;color:#c3a55a;padding:6px 10px;border-radius:4px;font-weight:bold">
①股王RS的大盤預示力<b>遠不如「前5%籃子」</b>——粒度縮太細反而失真</span>
上市股王RS>0→下月價差僅<b>+0.22pp</b>(corr+0.222);上櫃股王版+1.33pp(三者最好);
蹺蹺板(上市王−上櫃王)+0.72pp——全部輸給前5%籃子版的<b>+2.12pp/勝率69% vs 55%</b>(followup卷)。
機制: 單一股王的報酬被個股特有事件(法說、單月營收、大單)主導,雜訊蓋過風險偏好訊號;
<b>結論=大盤溫度計繼續用籃子版,不要換成股王版</b>(簡化不划算)。</li>
<li><span style="background:#243b24;color:#7ec97e;padding:6px 10px;border-radius:4px;font-weight:bold">
②換王=真的有強動能,尤其上市</span>
新王上任(次日收盤進場,n=38): k20<b>+3.87%</b>/k40+6.90%/k60<b>+10.37%</b>/勝率66%/逐年9/11;
<b>上市新王(n=17): k20+5.16%/k40+12.69%/k60+14.04%/勝率71%/賺賠比2.42</b>——
與高價新貴(首次站上關卡k40+5.66✓)同屬「里程碑事件」家族但更猛;
上櫃新王較弱(k40+2.21含0/賺賠0.80)=又一次「上櫃極端族群較差」。
⚠<b>樣本極小(11年39次換王/上市18次)、CI含0</b>=觀察層,不能當獨立策略,
但可當「已持有該股時的加碼/續抱依據」。</li>
<li><b>③舊王被超越≠見頂</b>: 舊王後續k20+1.18/k40+0.78含0/k60+4.99/勝率45%——沒有反轉,
只是<b>明顯弱化</b>(新王k60+10.37 vs 舊王+4.99),資金確實往新王移動,但不必急著砍舊王。</li>
<li><b>④換王頻率與大盤無關</b>(corr=-0.076)——「換王頻繁=多頭熱」的直覺不成立,
台股股王更迭主要由個別產業週期(記憶體/IC設計/散熱)驅動,不是市場情緒的代理。</li>
<li><b>⑤現況</b>: 上市股王=2059川湖(9,495元,歷任6位),上櫃股王=5274信驊(15,500元,歷任5位);
兩者近年更迭都與AI伺服器/IC設計題材週期同步。</li>
</ul>
<div class="note">維運: python 研究腳本/綜合策略/build_stock_king_study.py(從根目錄執行)。</div>
</body></html>"""
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n[report] 已輸出 {OUT}")


if __name__ == "__main__":
    main()
