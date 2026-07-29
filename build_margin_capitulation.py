# -*- coding: utf-8 -*-
"""個股層融資橫斷面考卷(上市,預註冊2026-07-29,使用者07-29晨提案「融資分上市上櫃×成交值大小
×融資情況×市值」,設計當日已磨定)
========================================================================
預註冊三格(寫死於開工前,首跑即凍結):
  C1 主格·融資投降×深跌: 池=當日ret20<=-20% ∧ amt20>=0.3億 ∧ 非ETF ∧ 融資餘額可算(20日前>=500張)
     切分=fin_chg20(融資餘額20日增減%): 投降組<=-15% / 沒動組>=-5% / 中間
     增量判準=對照純價格深跌(池內demean當日池中位後,投降−沒動配對差)——融資維度有無加值?
     次切=成交值排名(當日<=300 vs >800,與處置💰口徑一致);梯度=五分位單調檢查;episode去重20日/股。
  C2 反向格·融資急增×小型: 全池(排除深跌ret20>-10%) ∧ fin_chg20>=+30% ∧ 市值下半
     (市值代理=fin_limit×4×1000×close,fin_limit=股本25%法規口徑,2330反推259.3億股✓)
     假說=散戶追高反指標(demeaned負);H-融資先驗=多頭限定放大器→分站上/跌破季線regime。
  C3 加碼格·融資×d4w背離(週頻): 股-週面板,fin_chg4w×d4w(千張大戶4週流向)四象限;
     重點=散戶斷頭大戶接(fin殺∧d4w>0)=肥? vs 散戶槓桿進大戶出(fin增∧d4w<0)=毒?
     進場=快照日+3天後首個交易日收盤(live一致口徑,TDCC週六公布),fwd20;全池+深跌池內雙看。
判準: demean(對date中位)/逐年LOTO(僅2022-2026=4.5年⚠短樣本單regime)/月群bootstrap;
死格先驗=2022熊市深跌池=瀑布接刀;與深跌選股(出清日買最深1/3)的分工=那是大盤事件日選股,
本卷=個股常時橫斷面。資料=margin_flow(上市2022起)/fm_daily_price/tdcc_weekly。
報告: 研究報告/research_margin_capitulation.html  用法: python build_margin_capitulation.py
"""
import json
import sqlite3
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
DB = "capital_flow.db"
KS = [10, 20, 60]
GREEN, RED, BLUE, YELLOW, GRAY = "#7ec97e", "#e06c5a", "#6bb7e3", "#c3a55a", "#8a8878"
rng = np.random.default_rng(20260729)


def med_win(v):
    v = pd.Series(v).dropna()
    if not len(v):
        return None, None, 0
    return float(v.median()), float((v > 0).mean() * 100), len(v)


def boot_diff_frame(a, b, n_iter=2000):
    """a/b=DataFrame(index含date欄位ym) value欄;月群bootstrap中位差CI。"""
    a, b = a[a.value.notna()], b[b.value.notna()]
    if len(a) < 15 or len(b) < 15:
        return None
    am = a.groupby("ym").value.apply(list)
    bm = b.groupby("ym").value.apply(list)
    diffs = []
    for _ in range(n_iter):
        av = np.concatenate([am.iloc[i] for i in rng.integers(0, len(am), len(am))])
        bv = np.concatenate([bm.iloc[i] for i in rng.integers(0, len(bm), len(bm))])
        diffs.append(np.median(av) - np.median(bv))
    return (float(a.value.median() - b.value.median()),
            float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5)))


def loto(a, b):
    a, b = a[a.value.notna()], b[b.value.notna()]
    pos = tot = 0
    for y in sorted(set(a.year) & set(b.year)):
        av, bv = a.value[a.year == y], b.value[b.year == y]
        if len(av) >= 5 and len(bv) >= 5:
            tot += 1
            pos += (av.median() - bv.median()) > 0
    return pos, tot


def boot_med(a, n_iter=2000):
    """單組月群bootstrap: 中位數95%CI。"""
    a = a[a.value.notna()]
    if len(a) < 15:
        return None
    am = a.groupby("ym").value.apply(list)
    meds = []
    for _ in range(n_iter):
        av = np.concatenate([am.iloc[i] for i in rng.integers(0, len(am), len(am))])
        meds.append(np.median(av))
    return (float(a.value.median()),
            float(np.percentile(meds, 2.5)), float(np.percentile(meds, 97.5)))


def stat_str(df):
    m, w, n = med_win(df.value)
    return f"{m:+.2f}%/{w:.0f}%(n={n})" if m is not None else "n=0"


def dedup_events(ev, gap=20):
    """ev=DataFrame(code,date,tpos...) 依股票20交易日去重(用tpos=交易日序)。"""
    keep = []
    for code, g in ev.groupby("code"):
        g = g.sort_values("tpos")
        last = -10**9
        for _, r in g.iterrows():
            if r.tpos - last >= gap:
                keep.append(r.name)
                last = r.tpos
    return ev.loc[keep]


def run_market(market="tw"):
    """market='tw'(上市margin_flow×TAIEX regime) / 'otc'(margin_flow_otc×TPEx regime,兩市對照④)。
    回傳(html片段, 摘要dict);上櫃口徑除資料表/指數外全同(預註冊一致)。"""
    tbl = "margin_flow" if market == "tw" else "margin_flow_otc"
    idx_mkt = "TAIEX" if market == "tw" else "TPEx"
    tag = "上市" if market == "tw" else "上櫃"
    conn = sqlite3.connect(DB)
    mf = pd.read_sql(f"SELECT date, code, fin_bal, fin_limit FROM {tbl}", conn,
                     parse_dates=["date"])
    codes = sorted(c for c in mf.code.unique() if not c.startswith("00") and len(c) == 4)
    ph = ",".join("?" * len(codes))
    px = pd.read_sql(f"SELECT date, code, close, money FROM fm_daily_price "
                     f"WHERE code IN ({ph}) AND date>='2021-06-01' AND close>0", conn,
                     params=codes, parse_dates=["date"])
    tw = pd.read_sql("SELECT date, close FROM index_daily WHERE market=? ORDER BY date",
                     conn, params=(idx_mkt,), parse_dates=["date"]).set_index("date").close
    td = pd.read_sql(f"SELECT date, code, p1000 FROM tdcc_weekly WHERE code IN ({ph}) "
                     f"AND date>='2021-09-01'", conn, params=codes, parse_dates=["date"])
    conn.close()
    print(f"\n{'#' * 20} {tag}({tbl}, regime={idx_mkt}) {'#' * 20}")

    close = px.pivot(index="date", columns="code", values="close")
    money = px.pivot(index="date", columns="code", values="money")
    finb = mf.pivot(index="date", columns="code", values="fin_bal").reindex(
        index=close.index, columns=close.columns)
    finl = mf.pivot(index="date", columns="code", values="fin_limit").reindex(
        index=close.index, columns=close.columns)
    finb = finb.ffill(limit=3)
    finl = finl.ffill(limit=3)

    ret20 = (close / close.shift(20) - 1) * 100
    amt20 = money.rolling(20).mean() / 1e8
    amt_rank = money.rank(axis=1, ascending=False)  # 當日成交值全池排名(池=上市融資股,近似全市場前段)
    finb20 = finb.shift(20)
    finchg = ((finb / finb20 - 1) * 100).where(finb20 >= 500)
    mcap = finl * 4 * 1000 * close  # 市值代理(元)
    mcap_med = mcap.median(axis=1)
    fwd = {k: (close.shift(-k) / close - 1) * 100 for k in KS}
    ma60 = tw.rolling(60).mean()
    bull = (tw > ma60).reindex(close.index).ffill()

    win0 = pd.Timestamp("2022-02-01")  # margin_flow 2022-01起,留20日warmup
    dates = [d for d in close.index if d >= win0]
    tpos = {d: i for i, d in enumerate(close.index)}

    # ---------- C1 主格: 深跌池內融資投降增量 ----------
    print("=" * 60 + "\nC1 主格·融資投降×深跌(池=ret20<=-20 ∧ amt20>=0.3億)")
    pool_mask = (ret20 <= -20) & (amt20 >= 0.3) & finchg.notna()
    uni_mask = (amt20 >= 0.3) & finchg.notna()  # demean基準=全池(非深跌池,免小池日歸零假象)
    recs = []
    for d in dates:
        row = pool_mask.loc[d]
        cs = row.index[row.fillna(False)]
        if not len(cs):
            continue
        f20d = {k: fwd[k].loc[d] for k in KS}
        uc = uni_mask.loc[d]
        ucs = uc.index[uc.fillna(False)]
        uni_med = {k: f20d[k][ucs].median() for k in KS}
        for c in cs:
            recs.append({"code": c, "date": d, "tpos": tpos[d], "fin": finchg.loc[d, c],
                         "rank": amt_rank.loc[d, c],
                         **{f"f{k}": f20d[k][c] for k in KS},
                         **{f"f{k}dm": f20d[k][c] - uni_med[k] for k in KS}})
    ev = pd.DataFrame(recs)
    ev = dedup_events(ev)
    ev["ym"] = ev.date.dt.strftime("%Y-%m")
    ev["year"] = ev.date.dt.year
    print(f"深跌池事件(20日去重後): {len(ev)}筆 / {ev.code.nunique()}檔 / "
          f"{ev.date.min().date()}~{ev.date.max().date()}")
    g_cap = ev[ev.fin <= -15].assign(value=lambda x: x.f20dm)
    g_flat = ev[ev.fin >= -5].assign(value=lambda x: x.f20dm)
    g_mid = ev[(ev.fin > -15) & (ev.fin < -5)].assign(value=lambda x: x.f20dm)
    c1_res = {}
    for k in KS:
        a = ev[ev.fin <= -15].assign(value=ev[ev.fin <= -15][f"f{k}dm"])
        b = ev[ev.fin >= -5].assign(value=ev[ev.fin >= -5][f"f{k}dm"])
        r = boot_diff_frame(a, b)
        p, t = loto(a, b)
        raw_a = med_win(ev[ev.fin <= -15][f"f{k}"])
        raw_b = med_win(ev[ev.fin >= -5][f"f{k}"])
        c1_res[k] = (r, p, t, raw_a, raw_b)
        rs = f"{r[0]:+.2f}pp CI[{r[1]:+.2f},{r[2]:+.2f}]" if r else "n小"
        print(f"  f{k}: 投降(<=-15%) raw {raw_a[0]:+.2f}%/{raw_a[1]:.0f}%(n={raw_a[2]}) vs "
              f"沒動(>=-5%) {raw_b[0]:+.2f}%/{raw_b[1]:.0f}%(n={raw_b[2]}) | "
              f"demean配對差 {rs} 逐年{p}/{t}正")
    # 五分位梯度(f20 demean)
    ev["q"] = pd.qcut(ev.fin, 5, labels=False, duplicates="drop")
    print("  五分位梯度(fin_chg20由小到大, f20 demean中位):")
    qrows = []
    for q in sorted(ev.q.dropna().unique()):
        sub = ev[ev.q == q]
        m, w, n = med_win(sub.f20dm)
        qrows.append((q, float(sub.fin.median()), m, w, n))
        print(f"    Q{int(q) + 1}(fin中位{sub.fin.median():+.1f}%): {m:+.2f}%/{w:.0f}%(n={n})")
    # 次切: 成交值排名
    print("  次切·當日成交值排名(投降組內):")
    cap_ev = ev[ev.fin <= -15]
    rk_rows = []
    for lab, m_ in (("排名<=300", cap_ev["rank"] <= 300), ("301~800", (cap_ev["rank"] > 300) & (cap_ev["rank"] <= 800)),
                    (">800", cap_ev["rank"] > 800)):
        sub = cap_ev[m_]
        m, w, n = med_win(sub.f20dm)
        rk_rows.append((lab, m, w, n))
        if m is not None:
            print(f"    {lab}: f20dm {m:+.2f}%/{w:.0f}%(n={n})")
    # 逐年
    print("  逐年(投降−沒動 f20 demean差):")
    yr_rows = []
    for y in sorted(ev.year.unique()):
        a = ev[(ev.year == y) & (ev.fin <= -15)].f20dm
        b = ev[(ev.year == y) & (ev.fin >= -5)].f20dm
        if len(a) >= 5 and len(b) >= 5:
            yr_rows.append((y, float(a.median() - b.median()), len(a)))
            print(f"    {y}: {a.median() - b.median():+.2f}pp (投降n={len(a)})")

    # ---------- C2 反向格: 融資急增×小型 ----------
    print("=" * 60 + "\nC2 反向格·融資急增×小型(排除深跌,fin_chg20>=+30%,市值下半)")
    surge_mask = (ret20 > -10) & (finchg >= 30) & (amt20 >= 0.3) & mcap.lt(mcap_med, axis=0)
    recs2 = []
    for d in dates:
        row = surge_mask.loc[d]
        cs = row.index[row.fillna(False)]
        if not len(cs):
            continue
        uni = (amt20.loc[d] >= 0.3) & finchg.loc[d].notna()
        uni_med = {k: fwd[k].loc[d][uni.index[uni.fillna(False)]].median() for k in KS}
        for c in cs:
            recs2.append({"code": c, "date": d, "tpos": tpos[d], "bull": bool(bull.get(d, False)),
                          **{f"f{k}dm": fwd[k].loc[d, c] - uni_med[k] for k in KS}})
    ev2 = pd.DataFrame(recs2)
    ev2 = dedup_events(ev2)
    ev2["ym"] = ev2.date.dt.strftime("%Y-%m")
    ev2["year"] = ev2.date.dt.year
    c2_res = {}
    print(f"急增事件(去重後): {len(ev2)}筆 / {ev2.code.nunique()}檔")
    for k in (20, 60):
        m, w, n = med_win(ev2[f"f{k}dm"])
        mb, wb, nb = med_win(ev2[ev2.bull][f"f{k}dm"])
        ms, ws, ns = med_win(ev2[~ev2.bull][f"f{k}dm"])
        c2_res[k] = ((m, w, n), (mb, wb, nb), (ms, ws, ns))
        bm = boot_med(ev2.assign(value=ev2[f"f{k}dm"]))
        ci = f" CI[{bm[1]:+.2f},{bm[2]:+.2f}]{'✓排0' if bm[2] < 0 or bm[1] > 0 else '含0'}" if bm else ""
        print(f"  f{k}dm: 全體 {m:+.2f}%/{w:.0f}%(n={n}){ci} | 站上季線 {mb:+.2f}%/{wb:.0f}%(n={nb})"
              f" | 跌破季線 {ms:+.2f}%/{ws:.0f}%(n={ns})")

    # ---------- C3 加碼格: 融資×d4w背離(週頻) ----------
    print("=" * 60 + "\nC3 加碼格·融資×d4w四象限(週頻,進場=快照+3天後首個交易日收盤)")
    tdw = td.pivot(index="date", columns="code", values="p1000")
    d4w = tdw - tdw.shift(4)
    all_days = close.index
    recs3 = []
    for snap in [d for d in d4w.index if d >= pd.Timestamp("2022-02-01")]:
        entry_i = all_days.searchsorted(snap + pd.Timedelta(days=3))
        if entry_i + 20 >= len(all_days):
            continue
        ed = all_days[entry_i]
        f20_e = (close.shift(-20) / close - 1).loc[ed] * 100
        fin_e = finchg.loc[ed]
        r20_e = ret20.loc[ed]
        a20_e = amt20.loc[ed]
        row = d4w.loc[snap].reindex(close.columns)
        ok = row.notna() & fin_e.notna() & f20_e.notna() & (a20_e >= 0.3)
        cs = row.index[ok]
        if not len(cs):
            continue
        med0 = f20_e[cs].median()
        for c in cs:
            recs3.append({"code": c, "date": ed, "tpos": tpos[ed], "d4w": row[c],
                          "fin": fin_e[c], "deep": bool(r20_e[c] <= -20),
                          "f20dm": f20_e[c] - med0})
    ev3 = pd.DataFrame(recs3)
    ev3["ym"] = ev3.date.dt.strftime("%Y-%m")
    ev3["year"] = ev3.date.dt.year
    quads = {"散戶斷頭·大戶接(fin<=-5∧d4w>0)": (ev3.fin <= -5) & (ev3.d4w > 0),
             "散戶斷頭·大戶跑(fin<=-5∧d4w<0)": (ev3.fin <= -5) & (ev3.d4w < 0),
             "散戶進·大戶出(fin>=+5∧d4w<0)": (ev3.fin >= 5) & (ev3.d4w < 0),
             "散戶進·大戶也進(fin>=+5∧d4w>0)": (ev3.fin >= 5) & (ev3.d4w > 0)}
    c3_res = {}
    for base_lab, base in (("全池", pd.Series(True, index=ev3.index)), ("深跌池內", ev3.deep)):
        print(f"  [{base_lab}] (股-週n={int(base.sum())})")
        for lab, m_ in quads.items():
            sub = ev3[base & m_]
            m, w, n = med_win(sub.f20dm)
            c3_res[(base_lab, lab)] = (m, w, n)
            if m is not None:
                print(f"    {lab}: f20dm {m:+.2f}%/{w:.0f}%(n={n})")
        a = ev3[base & quads["散戶斷頭·大戶接(fin<=-5∧d4w>0)"]].assign(value=lambda x: x.f20dm)
        b = ev3[base & quads["散戶斷頭·大戶跑(fin<=-5∧d4w<0)"]].assign(value=lambda x: x.f20dm)
        r = boot_diff_frame(a, b)
        p, t = loto(a, b)
        c3_res[(base_lab, "diff")] = (r, p, t)
        if r:
            print(f"    重點差(大戶接−大戶跑): {r[0]:+.2f}pp CI[{r[1]:+.2f},{r[2]:+.2f}] 逐年{p}/{t}正")

    # ---------- 報告 ----------
    def fm(v, pct=True):
        return "—" if v is None else f"{v:+.2f}{'%' if pct else ''}"

    c1rows = ""
    for k in KS:
        r, p, t, ra, rb = c1_res[k]
        rs = f"{r[0]:+.2f}pp CI[{r[1]:+.2f},{r[2]:+.2f}]" if r else "n小"
        ok = r and (r[1] > 0 or r[2] < 0)
        c1rows += (f"<tr><th>f{k}</th><td>{fm(ra[0])}/{ra[1]:.0f}%(n={ra[2]})</td>"
                   f"<td>{fm(rb[0])}/{rb[1]:.0f}%(n={rb[2]})</td>"
                   f"<td class='{'good' if ok and r[0] > 0 else 'warn'}'>{rs}</td>"
                   f"<td>{p}/{t}</td></tr>")
    qtbl = "".join(f"<tr><th>Q{int(q) + 1}(fin{f:+.1f}%)</th><td>{fm(m)}/{w:.0f}%</td><td>{n}</td></tr>"
                   for q, f, m, w, n in qrows)
    rktbl = "".join(f"<tr><th>{lab}</th><td>{fm(m)}/{w:.0f}%</td><td>{n}</td></tr>"
                    for lab, m, w, n in rk_rows if m is not None)
    yrtbl = "".join(f"<tr><th>{y}</th><td>{d:+.2f}pp</td><td>{n}</td></tr>" for y, d, n in yr_rows)
    c2tbl = ""
    for k in (20, 60):
        (m, w, n), (mb, wb, nb), (ms, ws, ns) = c2_res[k]
        c2tbl += (f"<tr><th>f{k}dm</th><td>{fm(m)}/{w:.0f}%(n={n})</td>"
                  f"<td>{fm(mb)}/{wb:.0f}%(n={nb})</td><td>{fm(ms)}/{ws:.0f}%(n={ns})</td></tr>")
    c3tbl = ""
    for base_lab in ("全池", "深跌池內"):
        for lab in quads:
            m, w, n = c3_res[(base_lab, lab)]
            if m is not None:
                c3tbl += (f"<tr><th>{base_lab}·{lab}</th>"
                          f"<td class='{'good' if m > 0 else 'bad'}'>{m:+.2f}%/{w:.0f}%</td>"
                          f"<td>{n}</td></tr>")
        r, p, t = c3_res[(base_lab, "diff")]
        rs = f"{r[0]:+.2f}pp CI[{r[1]:+.2f},{r[2]:+.2f}] 逐年{p}/{t}正" if r else "n小"
        c3tbl += f"<tr class='hl'><th>{base_lab}·大戶接−大戶跑</th><td colspan=2>{rs}</td></tr>"

    frag = f"""
<h2>[{tag}] C1 主格·深跌池內融資投降增量(demean=全池當日中位)</h2>
<table><tr><th>水平</th><th>投降組raw(fin20≤-15%)</th><th>沒動組raw(≥-5%)</th><th>demean配對差</th><th>逐年正</th></tr>{c1rows}</table>
<table><tr><th>五分位(fin_chg20)</th><th>f20dm中位/勝率</th><th>n</th></tr>{qtbl}</table>
<table><tr><th>投降組×成交值排名</th><th>f20dm</th><th>n</th></tr>{rktbl}</table>
<table><tr><th>逐年 投降−沒動</th><th>f20dm差</th><th>投降n</th></tr>{yrtbl}</table>
<h2>[{tag}] C2 反向格·融資急增×小型(demean=全池當日中位)</h2>
<table><tr><th>水平</th><th>全體</th><th>站上季線</th><th>跌破季線</th></tr>{c2tbl}</table>
<h2>[{tag}] C3 加碼格·融資×d4w四象限(週頻)</h2>
<table><tr><th>象限</th><th>f20dm中位/勝率</th><th>n</th></tr>{c3tbl}</table>"""
    return frag


def main():
    frags = run_market("tw")
    # 上櫃對照(④): margin_flow_otc覆蓋齊才跑
    conn = sqlite3.connect(DB)
    nd = conn.execute("SELECT COUNT(DISTINCT date) FROM margin_flow_otc").fetchone()[0]
    cal_n = conn.execute("SELECT COUNT(DISTINCT date) FROM index_daily WHERE market='TAIEX' "
                         "AND date>='2022-01-01'").fetchone()[0]
    conn.close()
    otc_frag = ""
    if nd >= cal_n * 0.95:
        otc_frag = run_market("otc")
    else:
        print(f"\n上櫃對照: margin_flow_otc覆蓋{nd}/{cal_n}日未齊,跳過(回補完成後重跑)")
        otc_frag = "<h2>[上櫃] 對照</h2><div class='note'>逐股融資歷史回補未齊,回補完成後重跑本腳本。</div>"

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>個股融資投降考卷(2026-07-29)</title>
<style>body{{background:#1a1a19;color:#fff;font-family:"Noto Sans TC",sans-serif;margin:24px;max-width:1050px}}
h1{{font-size:20px}} h2{{font-size:15px;color:#c3c2b7;margin-top:26px;border-bottom:1px solid #333;padding-bottom:4px}}
table{{border-collapse:collapse;font-size:13px;font-variant-numeric:tabular-nums;margin:8px 0}}
td,th{{border:1px solid #333;padding:4px 10px;text-align:right}} th{{text-align:left;color:#c3c2b7}}
.note{{color:#8a8878;font-size:12.5px;line-height:1.8}} .good{{color:{GREEN}}} .bad{{color:{RED}}}
.warn{{color:{YELLOW}}} .hl{{background:#2a2a28}}</style></head><body>
<h1>🩸 個股融資投降考卷(上市主卷+上櫃對照,2022起)</h1>
<div class="note">預註冊三格見build_margin_capitulation.py docstring。資料=margin_flow/margin_flow_otc(逐股融資,2022-01起)
×fm_daily_price×tdcc_weekly;市值代理=fin_limit×4(融資限額=股本25%法規口徑,2330反推259.3億股核對✓;
正式股本表capital已另落地供未來考卷)。⚠樣本僅4.5年(2022熊+2023-26修復)單regime。</div>
<h2>📋 判決(2026-07-29首跑即凍結,主卷=上市)</h2>
<table>
<tr><th>格</th><th>判決</th><th>關鍵數字</th></tr>
<tr><td>C1 融資投降×深跌(主格)</td><td class="bad">❌否定</td><td>raw +4.41%/62%全是日期組成(=深跌事件簇在恐慌底部的盤勢beta),
demean配對差僅+0.32pp CI[-1.66,+1.89]含0、五分位無單調、逐年2/5——<b>融資投降對「選哪檔」零加值</b>,
肉全在「什麼時候」(那是溫度計/深跌選股的工作)</td></tr>
<tr><td>C2 融資急增×小型(反向格)</td><td class="warn">🟡上市限定·證據薄</td><td>上市f20dm -1.13%/46% CI[-1.95,-0.09]排0
(f60壓線含0)=散戶追高反指標方向成立;<b>但上櫃對照不重現(+0.33pp含0)</b>——單市場+壓線CI=
降級「弱排雷提示」:上市小型股融資20日暴增30%+別追,別當規則</td></tr>
<tr><td>C3 融資×d4w四象限(加碼格)</td><td class="bad">❌死,但對照挖出反向真發現</td><td>上市全池四象限全≈0、
深跌池內大戶接−大戶跑+0.29pp含0=「散戶斷頭大戶接」不成立;<b>上櫃對照反轉:深跌池內大戶接f20dm
-2.22%/40%,大戶接−大戶跑-3.03pp CI[-4.64,-1.17]✓排0、逐年0/5(五年全反)</b>=上櫃深跌股的
千張大戶承接是<b>避開訊號</b>(主力自救/掩護嫌疑),與7/24「共振×千張流向上櫃子組反向-1.87pp」第二度互證。
<b>horizon延伸(tmp_c3_otc_horizons.py,使用者追問60天)</b>:f10 -0.88→<b>f20 -3.03(最毒)</b>→f40 -1.29含0→
f60 +0.35完全消失;絕對報酬兩組60日皆正(接+5.19%/61% vs 跑+6.46%/65%)=<b>「避開窗約4週」的相對弱勢提示,
非長期黑名單</b>;已上板交集頁⚠旗標(2026-07-29裁示,觀察層live驗證中)</td></tr>
</table>
<div class="note">機制總結:個股「深跌」不等於「被迫交易」——處置股的凍結是<b>制度強制</b>的,
深跌股的融資減少多半只是價格下跌的鏡子(分母縮水+自然停損),資訊已被價格吸收。
通用籌碼欄位路線第6殺,個股層融資橫斷面收官。<b>兩市對照的一句話:上市籌碼流向死在雜訊,
上櫃籌碼流向死在反向——上櫃中小型「大戶進場」故事一律別跟(第二度確認)。</b></div>
{frags}
{otc_frag}
<h2>限制</h2>
<div class="note">2022-26單週期;股息未還原;demean口徑=橫斷面相對強弱(絕對報酬看raw欄);
fin_bal<500張者剔除(比率雜訊);d4w覆蓋受tdcc_weekly範圍限制;上櫃regime線用櫃買指數60日線。</div>
</body></html>"""
    out = "研究報告/research_margin_capitulation.html"
    open(out, "w", encoding="utf-8").write(html)
    print(f"\n報告已產出 {out} ({len(html):,} chars)")


if __name__ == "__main__":
    main()
