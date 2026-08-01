# -*- coding: utf-8 -*-
"""當沖×借券費率全史正式考卷(2026-07-31,接續scratch_dt_lend_quick.py一年快看v2升級):
把快看版的四個假說從1年份(2025-08~2026-07單regime)擴大到2014-2026全史,並補上每題的
bootstrap/case-control顯著性檢定(快看版只有點估計,沒有CI)。

資料源(⚠刻意不寫入capital_flow.db,DB備份逼近95MB上限,考卷驗證通過才裁決是否入庫):
  根目錄 tmp_dtlend_h2014.pkl ~ tmp_dtlend_h2025.pkl (12檔,FinMind全史回補,2014-01-02~2025-07-25)
  暫存/快取/tmp_dtlend_p1.pkl ~ p6.pkl (近一年批,2025-07-28~2026-07-28)
  每個pkl用ds欄位混裝兩種資料(自行驗證確認,非轉述):
    ds=='dt' 當沖列(TaiwanStockDayTrading): stock_id,date,BuyAfterSale,Volume,BuyAmount,SellAmount
    ds=='ln' 借券列(TaiwanStockSecuritiesLending): stock_id,date,transaction_type,volume,
             fee_rate(百分比費率),close,original_return_date,original_lending_period
  兩批pkl日期範圍經檢查無重疊(h2025訖2025-07-25,p1起2025-07-28),仍做全表去重當安全網。

四題(門檻定義沿用快看版,樣本擴大至全史+補bootstrap):
  ①題材當沖佔比×波段: 題材層當沖佔比=Σ當沖BuyAmount/Σ成交金額(先加總金額再算比率),
     classification.main_group分組且成員>=3;比較當沖佔比前20%vs後20%題材的CAR(k=1,2,3,5,10,20),
     另看5日均-20日均加速度前20%組。
  ②飆股安靜成員: 飆股池=r20>=+40%∧amt20>=0.3億(20日去重);池內用「當沖ratio5日均」
     「ratio5日均-20日均之差(湧入度)」「近期借券費率」三個切法做池內三分位對照,核心假說=
     熱題材裡當沖湧入度低的安靜成員後續表現優於湧入度高者;另做有無借券成交+當沖高×費率高2x2。
  ③當沖暴增(D2定義,⚠與build_index_panic_rebound.py第5行的指數急殺D2同名異義,本卷變數名dt_surge避免混淆):
     ratio>=30%∧ratio-20日均ratio>=15pp(10日去重),核心假說=排雷(暴增後續補跌?),
     用bootstrap+case-control(同日∧同宇宙隨機抽樣非暴增股)驗證是否真的比隨機基準差。
  ④L1費率informed short: 量加權費率vwfee=Σ(fee_rate×volume)/Σvolume,每日全宇宙五分位,
     Q5(最難借券)先驗=informed short應顯著更差;L2費率跳升(vwfee-20日中位>=2pp∧vwfee>=3%,10日去重)
     依r20拆「跳升時已漲(軋空反轉)」vs「跳升時已跌(持續壓制)」兩組。

統計慣例(全題統一): CAR k=1,2,3,5,10,20;絕對報酬/勝率 + demean版(扣同日全宇宙/同日全題材
中位數報酬,⚠此為比快看版pooled-median demean更嚴謹的同日期截面版本,見下方說明)兩版並列;
bootstrap=月群重抽樣(仿build_margin_flush_exam.py的boot_diff,n_iter=2000)算中位差95%CI,
「排0」=顯著;D2暴增另加case-control(逐事件日同宇宙隨機抽同數量非暴增股當對照組)。

用法: python 研究腳本/當沖借券/build_dtlend_report.py  (從根目錄執行,鐵律)
產出: 研究報告/research_dtlend_examine.html
"""
import glob
import json
import sqlite3
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

KS = [1, 2, 3, 5, 10, 20]
DB = "capital_flow.db"
OUT = "研究報告/research_dtlend_examine.html"
rng = np.random.default_rng(20260731)

GREEN, RED, BLUE, YELLOW, GRAY = "#7ec97e", "#e06c5a", "#6bb7e3", "#c3a55a", "#8a8878"
BG = {"paper_bgcolor": "#1a1a19", "plot_bgcolor": "#22221f",
      "font": {"color": "#ddd", "size": 12}, "margin": {"t": 42, "l": 52, "r": 18, "b": 40},
      "legend": {"orientation": "h"}}


# ======================================================================
# 1. 資料載入
# ======================================================================
def load_dtlend():
    h_files = sorted(glob.glob("tmp_dtlend_h*.pkl"))
    p_files = sorted(glob.glob("暫存/快取/tmp_dtlend_p*.pkl"))
    print(f"[load] 全史批{len(h_files)}檔 + 近一年批{len(p_files)}檔")
    parts, ranges = [], []
    for f in h_files + p_files:
        d = pd.read_pickle(f)
        d["date"] = pd.to_datetime(d.date)
        ranges.append((f, d.date.min(), d.date.max()))
        parts.append(d)
    for f, lo, hi in ranges:
        print(f"  {f}: {lo.date()} ~ {hi.date()}")
    if p_files:
        h_hi = ranges[len(h_files) - 1][2]
        p_lo = ranges[len(h_files)][1]
        overlap = p_lo <= h_hi
        print(f"[load] 重疊檢查: 全史批最後日={h_hi.date()} 近一年批最早日={p_lo.date()} "
              f"→ {'⚠有重疊,以下全表去重處理' if overlap else '✓無重疊(相隔' + str((p_lo - h_hi).days) + '日曆日)'}")

    raw = pd.concat(parts, ignore_index=True)
    n_all = len(raw)
    raw = raw[(raw.stock_id.str.len() == 4) & (~raw.stock_id.str.startswith("00"))]
    n_uni = len(raw)
    raw = raw.drop_duplicates()
    print(f"[load] 合併原始{n_all:,}列 → 宇宙過濾(四碼∧非00開頭ETF){n_uni:,}列 → "
          f"全表去重後{len(raw):,}列(移除{n_uni - len(raw):,}列重複,理論值應為0因兩批無重疊)")
    print(f"[load] ds分布: {dict(raw.ds.value_counts())}")

    dt = raw[raw.ds == "dt"][["date", "stock_id", "BuyAfterSale", "Volume", "BuyAmount", "SellAmount"]] \
        .rename(columns={"stock_id": "code"}).copy()
    ln = raw[raw.ds == "ln"].dropna(subset=["fee_rate"])[["date", "stock_id", "fee_rate", "volume"]] \
        .rename(columns={"stock_id": "code"}).copy()
    print(f"[load] 當沖列dt={len(dt):,}({dt.code.nunique()}檔) "
          f"借券列ln(fee_rate非空)={len(ln):,}({ln.code.nunique()}檔) "
          f"日期範圍dt={dt.date.min().date()}~{dt.date.max().date()} "
          f"ln={ln.date.min().date()}~{ln.date.max().date()}")
    return dt, ln


def load_price(codes, date_lo):
    conn = sqlite3.connect(DB, timeout=60)
    ph = ",".join("?" * len(codes))
    px = pd.read_sql(
        f"SELECT code, date, open, close, volume, money FROM fm_daily_price "
        f"WHERE code IN ({ph}) AND date>=? AND close>0",
        conn, params=codes + [date_lo], parse_dates=["date"])
    conn.close()
    print(f"[load] fm_daily_price: {len(px):,}列, {px.code.nunique()}檔, "
          f"{px.date.min().date()}~{px.date.max().date()}")
    close = px.pivot(index="date", columns="code", values="close")
    op = px.pivot(index="date", columns="code", values="open")
    vol = px.pivot(index="date", columns="code", values="volume")
    money = px.pivot(index="date", columns="code", values="money")
    return close, op, vol, money


def load_classification():
    conn = sqlite3.connect(DB, timeout=60)
    cls = pd.read_sql("SELECT DISTINCT code, main_group FROM classification WHERE country='台'", conn)
    conn.close()
    cls = cls.drop_duplicates(subset=["code", "main_group"])
    print(f"[load] classification(台): {len(cls):,}列, {cls.code.nunique()}檔, "
          f"{cls.main_group.nunique()}個main_group題材")
    return cls


# ======================================================================
# 2. 共用工具:事件去重/CAR統計/bootstrap
# ======================================================================
def dedup(evs, idx, gap=10):
    """逐股票以gap個交易日為最小間隔去重(idx=交易日曆索引,依位置差)。"""
    keep, last = [], {}
    pos = {d: i for i, d in enumerate(idx)}
    for r in evs.sort_values(["code", "date"]).itertuples():
        if r.date in pos and pos[r.date] - last.get(r.code, -99) >= gap:
            keep.append((r.date, r.code))
            last[r.code] = pos[r.date]
    return pd.DataFrame(keep, columns=["date", "code"])


def event_stats(evs, fwdmap, uni_df, ks=KS):
    """股票層CAR: 回傳{k: {'raw':(med,win,n,vals,dates), 'dm':(med,win,n,vals,dates)}}。
    demean baseline=同日全宇宙(uni_df為真)中位數報酬(截面版,非跨日pooled)。"""
    out = {}
    for k in ks:
        raw_v, raw_d, dm_v, dm_d = [], [], [], []
        if len(evs):
            for d, g in evs.groupby("date"):
                if d not in fwdmap[k].index:
                    continue
                row = fwdmap[k].loc[d]
                u = uni_df.loc[d] if d in uni_df.index else None
                base = row[u.index[u.fillna(False)]].median() if u is not None else np.nan
                for c in g.code:
                    v = row.get(c)
                    if pd.notna(v):
                        raw_v.append(v)
                        raw_d.append(d)
                        if pd.notna(base):
                            dm_v.append(v - base)
                            dm_d.append(d)
        raw, dm = pd.Series(raw_v, dtype=float), pd.Series(dm_v, dtype=float)
        out[k] = {
            "raw": (float(raw.median()) if len(raw) else None,
                    float((raw > 0).mean() * 100) if len(raw) else None, len(raw), raw_v, raw_d),
            "dm": (float(dm.median()) if len(dm) else None,
                   float((dm > 0).mean() * 100) if len(dm) else None, len(dm), dm_v, dm_d),
        }
    return out


def boot_diff_ci(vals_a, dates_a, vals_b, dates_b, n_iter=2000, min_n=15):
    """月群bootstrap: a組-b組中位差95%CI(仿build_margin_flush_exam.boot_diff,泛化成吃陣列而非日期字典)。"""
    a = pd.Series(vals_a, index=pd.to_datetime(dates_a), dtype=float).dropna() if len(vals_a) else pd.Series(dtype=float)
    b = pd.Series(vals_b, index=pd.to_datetime(dates_b), dtype=float).dropna() if len(vals_b) else pd.Series(dtype=float)
    if len(a) < min_n or len(b) < min_n:
        return None
    am = a.groupby(a.index.strftime("%Y-%m")).apply(list)
    bm = b.groupby(b.index.strftime("%Y-%m")).apply(list)
    diffs = []
    for _ in range(n_iter):
        av = np.concatenate([am.iloc[i] for i in rng.integers(0, len(am), len(am))])
        bv = np.concatenate([bm.iloc[i] for i in rng.integers(0, len(bm), len(bm))])
        diffs.append(np.median(av) - np.median(bv))
    d0 = float(a.median() - b.median())
    lo, hi = float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))
    return {"diff": d0, "lo": lo, "hi": hi, "sig": bool(lo > 0 or hi < 0), "na": len(a), "nb": len(b)}


def boot_median_ci(vals, dates, n_iter=2000, min_n=15):
    """月群bootstrap: 單組中位數 vs 0 的95%CI(demean值已扣同日基準,vs 0等同vs隨機基準的case-control)。"""
    a = pd.Series(vals, index=pd.to_datetime(dates), dtype=float).dropna() if len(vals) else pd.Series(dtype=float)
    if len(a) < min_n:
        return None
    am = a.groupby(a.index.strftime("%Y-%m")).apply(list)
    meds = []
    for _ in range(n_iter):
        av = np.concatenate([am.iloc[i] for i in rng.integers(0, len(am), len(am))])
        meds.append(np.median(av))
    m0 = float(a.median())
    lo, hi = float(np.percentile(meds, 2.5)), float(np.percentile(meds, 97.5))
    return {"med": m0, "lo": lo, "hi": hi, "sig": bool(lo > 0 or hi < 0), "n": len(a)}


def case_control(evs, uni_df, excl_mask, seed=20260731):
    """逐事件日,從同日∧同宇宙(uni_df)排除excl_mask為真的股票後隨機抽同數量當對照組。"""
    rng2 = np.random.default_rng(seed)
    rows = []
    for d, g in evs.groupby("date"):
        if d not in uni_df.index:
            continue
        elig_all = uni_df.columns[uni_df.loc[d].fillna(False)]
        if d in excl_mask.index:
            excl = set(excl_mask.columns[excl_mask.loc[d].fillna(False)])
        else:
            excl = set()
        pool = [c for c in elig_all if c not in excl]
        if not pool:
            continue
        k = min(len(g), len(pool))
        chosen = rng2.choice(pool, size=k, replace=False)
        rows.extend({"date": d, "code": c} for c in chosen)
    return pd.DataFrame(rows, columns=["date", "code"])


# ---- HTML 呈現小工具 ----
def group_row(label, st, ks=KS):
    tds = ""
    for k in ks:
        raw, dm = st[k]["raw"], st[k]["dm"]
        if raw[0] is None:
            tds += "<td>—</td>"
            continue
        cls = "good" if raw[0] > 0 else "bad"
        dmtxt = f"<br><span class='sub'>dm{dm[0]:+.2f}pp</span>" if dm[0] is not None else ""
        tds += f"<td class='{cls}'>{raw[0]:+.2f}% / {raw[1]:.0f}%{dmtxt}</td>"
    n = st[ks[0]]["raw"][2]
    return f"<tr><th>{label}(n={n})</th>{tds}</tr>"


def car_table(rows, ks=KS):
    head = "<tr><th>組別</th>" + "".join(f"<th>k{k}(絕對/勝率,dm=demean)</th>" for k in ks) + "</tr>"
    return f"<table>{head}{''.join(rows)}</table>"


def boot_line(label, r, unit="pp"):
    if r is None:
        return f"<li>{label}: n太小,觀察層(未達bootstrap最低樣本門檻)</li>"
    key = "diff" if "diff" in r else "med"
    sig = "<b>✓排0(顯著)</b>" if r["sig"] else "含0(不顯著)"
    return f"<li>{label}: {r[key]:+.2f}{unit} 95%CI[{r['lo']:+.2f},{r['hi']:+.2f}] {sig}</li>"


# ======================================================================
# 3. 題① 題材當沖佔比×波段
# ======================================================================
def build_topic1(dt, money, uni, fwd, cls):
    code2themes = cls.groupby("code")["main_group"].apply(list).to_dict()
    buy_wide = dt.pivot_table(index="date", columns="code", values="BuyAmount", aggfunc="sum")
    common_idx = buy_wide.index.intersection(money.index)

    rows = []
    for d in common_idx:
        buy_row = buy_wide.loc[d].dropna()
        mon_row = money.loc[d]
        u_row = uni.loc[d] if d in uni.index else None
        agg = {}
        for c, b in buy_row.items():
            if c not in code2themes:
                continue
            m = mon_row.get(c)
            if pd.isna(m) or m <= 0:
                continue
            if u_row is not None and not bool(u_row.get(c, False)):
                continue
            for th in code2themes[c]:
                a = agg.setdefault(th, [0.0, 0.0, 0])
                a[0] += b
                a[1] += m
                a[2] += 1
        for th, (b, m, n) in agg.items():
            if n >= 3:
                rows.append((d, th, b / m * 100, n))
    th_df = pd.DataFrame(rows, columns=["date", "theme", "dtpct", "n"])
    th_df["rk"] = th_df.groupby("date")["dtpct"].rank(pct=True)
    print(f"[topic1] 題材-日面板 n={len(th_df):,}, {th_df.theme.nunique()}個題材(成員>=3且有效),"
          f" {th_df.date.nunique()}個交易日")

    # 5日均-20日均加速度
    ma = th_df.pivot_table(index="date", columns="theme", values="dtpct")
    acc = ma.rolling(5).mean() - ma.rolling(20).mean()
    acc_long = acc.stack().rename("acc").reset_index()
    acc_long.columns = ["date", "theme", "acc"]
    acc_long["rk"] = acc_long.groupby("date")["acc"].rank(pct=True)

    # 題材fwd=成員中位(等權),同日跨題材中位數當demean基準(比快看版pooled-median更嚴謹的截面版)
    th_fwd, daily_med = {}, {}
    for k in KS:
        s = fwd[k].stack()
        s.index.names = ["date", "code"]
        s = s.reset_index(name="ret")
        merged = s.merge(cls, on="code")
        tf = merged.groupby(["date", "main_group"])["ret"].median()
        th_fwd[k] = tf
        daily_med[k] = tf.groupby(level=0).median()

    def lookup(sub):
        out = {}
        for k in KS:
            raw_v, raw_d, dm_v, dm_d = [], [], [], []
            for r in sub.itertuples():
                v = th_fwd[k].get((r.date, r.theme))
                if v is None or pd.isna(v):
                    continue
                raw_v.append(v)
                raw_d.append(r.date)
                base = daily_med[k].get(r.date, np.nan)
                if pd.notna(base):
                    dm_v.append(v - base)
                    dm_d.append(r.date)
            raw, dm = pd.Series(raw_v, dtype=float), pd.Series(dm_v, dtype=float)
            out[k] = {
                "raw": (float(raw.median()) if len(raw) else None,
                        float((raw > 0).mean() * 100) if len(raw) else None, len(raw), raw_v, raw_d),
                "dm": (float(dm.median()) if len(dm) else None,
                       float((dm > 0).mean() * 100) if len(dm) else None, len(dm), dm_v, dm_d),
            }
        return out

    hi = th_df[th_df.rk >= 0.8]
    lo = th_df[th_df.rk <= 0.2]
    acc_hi = acc_long[acc_long.rk >= 0.8].dropna(subset=["acc"])

    st_hi, st_lo, st_acc = lookup(hi), lookup(lo), lookup(acc_hi)

    boot = {}
    for k in (5, 10, 20):
        boot[f"hi_lo_k{k}"] = boot_diff_ci(st_hi[k]["dm"][3], st_hi[k]["dm"][4],
                                           st_lo[k]["dm"][3], st_lo[k]["dm"][4])
        boot[f"acc_k{k}"] = boot_median_ci(st_acc[k]["dm"][3], st_acc[k]["dm"][4])

    print(f"[topic1] 前20%題材(n={len(hi)}) k20 raw={st_hi[20]['raw'][0]}, dm={st_hi[20]['dm'][0]}")
    print(f"[topic1] 後20%題材(n={len(lo)}) k20 raw={st_lo[20]['raw'][0]}, dm={st_lo[20]['dm'][0]}")

    return {"th_df": th_df, "st_hi": st_hi, "st_lo": st_lo, "st_acc": st_acc, "boot": boot,
            "n_hi": len(hi), "n_lo": len(lo), "n_acc": len(acc_hi),
            "n_themes": th_df.theme.nunique(), "n_rows": len(th_df)}


# ======================================================================
# 4. 題② 飆股安靜成員
# ======================================================================
def build_topic2(close, uni, fwd, ratio, vwfee):
    r20 = (close / close.shift(20) - 1) * 100
    pool = (r20 >= 40) & uni
    evp = pool.stack()
    evp = evp[evp].reset_index()
    evp.columns = ["date", "code", "_v"]
    evp = evp[["date", "code"]]
    hb = dedup(evp, close.index, gap=20)
    print(f"[topic2] 飆股池事件(r20>=+40%∧amt20>=0.3億,20日去重) n={len(hb)}")

    base_st = event_stats(hb, fwd, uni)

    ratio5 = ratio.rolling(5).mean()
    ratio20 = ratio.rolling(20).mean()
    feats = []
    for r in hb.itertuples():
        d, c = r.date, r.code
        f5 = ratio5.loc[d].get(c) if d in ratio5.index else np.nan
        f20 = ratio20.loc[d].get(c) if d in ratio20.index else np.nan
        dr = (f5 - f20) if pd.notna(f5) and pd.notna(f20) else np.nan
        fee = np.nan
        if c in vwfee.columns:
            s = vwfee[c].loc[:d].dropna()
            fee = s.iloc[-1] if len(s) else np.nan
        feats.append({"date": d, "code": c, "ratio5": f5, "dratio": dr, "fee": fee})
    hbf = pd.DataFrame(feats)
    print(f"[topic2] 飆股事件特徵覆蓋: ratio5={hbf.ratio5.notna().sum()} "
          f"dratio={hbf.dratio.notna().sum()} fee={hbf.fee.notna().sum()}")

    splits, boot = {}, {}
    for col in ("ratio5", "dratio", "fee"):
        v = hbf[hbf[col].notna()]
        if len(v) < 30:
            splits[col] = None
            continue
        t = v[col].quantile([1 / 3, 2 / 3]).values
        lo_g = v[v[col] <= t[0]][["date", "code"]]
        hi_g = v[v[col] >= t[1]][["date", "code"]]
        st_lo, st_hi = event_stats(lo_g, fwd, uni), event_stats(hi_g, fwd, uni)
        splits[col] = {"cut": t, "lo": st_lo, "hi": st_hi, "n_lo": len(lo_g), "n_hi": len(hi_g)}
        for k in (5, 10, 20):
            # 核心假說方向=安靜(低)組 - 湧入(高)組;fee則低費率=冷門 vs 高費率=熱門(方向仍lo-hi)
            boot[f"{col}_k{k}"] = boot_diff_ci(st_lo[k]["dm"][3], st_lo[k]["dm"][4],
                                               st_hi[k]["dm"][3], st_hi[k]["dm"][4])

    nofee = hbf[hbf.fee.isna()][["date", "code"]]
    hasfee = hbf[hbf.fee.notna()][["date", "code"]]
    st_nofee = event_stats(nofee, fwd, uni) if len(nofee) >= 20 else None
    st_hasfee = event_stats(hasfee, fwd, uni) if len(hasfee) >= 20 else None
    if st_nofee and st_hasfee:
        for k in (5, 10, 20):
            boot[f"nofee_k{k}"] = boot_diff_ci(st_nofee[k]["dm"][3], st_nofee[k]["dm"][4],
                                               st_hasfee[k]["dm"][3], st_hasfee[k]["dm"][4])

    st_both = st_neither = None
    if hbf.ratio5.notna().sum() >= 60 and hbf.fee.notna().sum() >= 60:
        rmed = hbf.ratio5.median()
        fmed = hbf[hbf.fee.notna()].fee.median()
        both = hbf[(hbf.ratio5 > rmed) & (hbf.fee > fmed)][["date", "code"]]
        neither = hbf[(hbf.ratio5 <= rmed) & (hbf.fee.notna()) & (hbf.fee <= fmed)][["date", "code"]]
        st_both, st_neither = event_stats(both, fwd, uni), event_stats(neither, fwd, uni)
        for k in (5, 10, 20):
            boot[f"2x2_k{k}"] = boot_diff_ci(st_neither[k]["dm"][3], st_neither[k]["dm"][4],
                                             st_both[k]["dm"][3], st_both[k]["dm"][4])

    return {"n_pool": len(hb), "base": base_st, "splits": splits, "boot": boot,
            "st_nofee": st_nofee, "st_hasfee": st_hasfee, "n_nofee": len(nofee), "n_hasfee": len(hasfee),
            "st_both": st_both, "st_neither": st_neither}


# ======================================================================
# 5. 題③ 當沖暴增(dt_surge,⚠與指數急殺D2同名異義)
# ======================================================================
def build_topic3(ratio, uni, fwd):
    ma20 = ratio.rolling(20, min_periods=15).mean()
    surge_raw = (ratio >= 0.30) & ((ratio - ma20) >= 0.15) & uni.reindex_like(ratio).fillna(False)
    ev = surge_raw.stack()
    ev = ev[ev].reset_index()
    ev.columns = ["date", "code", "_v"]
    ev = ev[["date", "code"]]
    d2 = dedup(ev, ratio.index, gap=10)
    print(f"[topic3] 當沖暴增dt_surge事件(ratio>=30%∧-20日均>=15pp,10日去重) n={len(d2)} "
          f"(去重前{len(ev):,}列)")

    st = event_stats(d2, fwd, uni)
    ctrl = case_control(d2, uni, surge_raw, seed=20260731)
    st_ctrl = event_stats(ctrl, fwd, uni)
    print(f"[topic3] case-control對照組(同日同宇宙隨機抽,排除當日所有暴增股) n={len(ctrl)}")

    boot = {}
    for k in (5, 10, 20):
        boot[f"vs0_k{k}"] = boot_median_ci(st[k]["dm"][3], st[k]["dm"][4])
        boot[f"vsctrl_k{k}"] = boot_diff_ci(st[k]["raw"][3], st[k]["raw"][4],
                                            st_ctrl[k]["raw"][3], st_ctrl[k]["raw"][4])
    # d2/surge_raw加回傳(2026-07-31波動regime加值考卷用,build_vol_addvalue_report.py需要事件層date/code
    # 才能拆高波/低波regime重跑case-control,原本只回傳彙總統計不夠用;純additive不影響既有呼叫端)
    return {"n_events": len(d2), "st": st, "st_ctrl": st_ctrl, "n_ctrl": len(ctrl), "boot": boot,
            "d2": d2, "surge_raw": surge_raw}


# ======================================================================
# 6. 題④ L1費率informed short + L2費率跳升
# ======================================================================
def build_topic4(vwfee, uni, fwd, close):
    recs = []
    for d in vwfee.index:
        if d not in uni.index:
            continue
        u = uni.loc[d]
        cand = [c for c in u.index[u.fillna(False)] if c in vwfee.columns]
        r = vwfee.loc[d, cand].dropna()
        if len(r) < 30:
            continue
        qd = pd.qcut(r.rank(method="first"), 5, labels=False, duplicates="drop")
        recs.extend({"date": d, "code": c, "q": v} for c, v in qd.items())
    l1 = pd.DataFrame(recs)
    qs = sorted(l1.q.unique())
    st_q = {qq: event_stats(l1[l1.q == qq][["date", "code"]], fwd, uni) for qq in qs}
    q_lo, q_hi = int(min(qs)), int(max(qs))
    print(f"[topic4] L1費率五分位面板 n={len(l1):,}, 費率p50={np.nanmedian(vwfee.values):.2f}% "
          f"p90={np.nanquantile(vwfee.values[~np.isnan(vwfee.values)], .9):.2f}%")

    boot_l1 = {}
    for k in (5, 10, 20):
        boot_l1[f"k{k}"] = boot_diff_ci(st_q[q_hi][k]["dm"][3], st_q[q_hi][k]["dm"][4],
                                        st_q[q_lo][k]["dm"][3], st_q[q_lo][k]["dm"][4])

    med20 = vwfee.rolling(20, min_periods=10).median()
    jump = ((vwfee - med20) >= 2) & (vwfee >= 3) & uni.reindex_like(vwfee).fillna(False)
    evj = jump.stack()
    evj = evj[evj].reset_index()
    evj.columns = ["date", "code", "_v"]
    evj = evj[["date", "code"]]
    l2 = dedup(evj, vwfee.index, gap=10)
    st_l2 = event_stats(l2, fwd, uni)
    print(f"[topic4] L2費率跳升事件(vwfee-20日中位>=2pp∧vwfee>=3%,10日去重) n={len(l2)}")

    r20 = (close / close.shift(20) - 1) * 100
    l2 = l2.copy()
    r20vals = []
    for r in l2.itertuples():
        if r.date in r20.index and r.code in r20.columns:
            r20vals.append(r20.loc[r.date, r.code])
        else:
            r20vals.append(np.nan)
    l2["r20"] = r20vals
    up = l2[l2.r20 > 10][["date", "code"]]
    down = l2[l2.r20 < -10][["date", "code"]]
    st_up, st_down = event_stats(up, fwd, uni), event_stats(down, fwd, uni)
    print(f"[topic4] L2跳升時已漲(r20>+10%) n={len(up)} / 已跌(r20<-10%) n={len(down)}")

    boot_l2 = {}
    for k in (5, 10, 20):
        boot_l2[f"vs0_up_k{k}"] = boot_median_ci(st_up[k]["dm"][3], st_up[k]["dm"][4])
        boot_l2[f"vs0_down_k{k}"] = boot_median_ci(st_down[k]["dm"][3], st_down[k]["dm"][4])
        boot_l2[f"diff_k{k}"] = boot_diff_ci(st_up[k]["dm"][3], st_up[k]["dm"][4],
                                             st_down[k]["dm"][3], st_down[k]["dm"][4])

    return {"l1": l1, "st_q": st_q, "boot_l1": boot_l1, "q_lo": q_lo, "q_hi": q_hi,
            "l2_n": len(l2), "st_l2": st_l2, "st_up": st_up, "st_down": st_down,
            "n_up": len(up), "n_down": len(down), "boot_l2": boot_l2}


# ======================================================================
# 7. 報告組裝
# ======================================================================
def write_report(t1, t2, t3, t4, n_cls_codes):
    css = """
body{background:#1a1a19;color:#fff;font-family:"Noto Sans TC",sans-serif;margin:24px;max-width:1150px}
h1{font-size:20px} h2{font-size:15px;color:#c3c2b7;margin-top:30px;border-bottom:1px solid #333;padding-bottom:4px}
h3{font-size:13.5px;color:#a8a79a;margin:16px 0 4px}
table{border-collapse:collapse;font-size:12.5px;font-variant-numeric:tabular-nums;margin:8px 0}
td,th{border:1px solid #333;padding:4px 9px;text-align:right} th{text-align:left;color:#c3c2b7}
.note{color:#8a8878;font-size:12.5px;line-height:1.8} .good{color:#7ec97e} .bad{color:#e06c5a}
.warn{color:#c3a55a} .hl{background:#2b3a2b} .sub{color:#777;font-size:11px}
ul{margin:4px 0;padding-left:20px;font-size:12.5px;color:#ccc;line-height:1.7}
.verdict{font-size:13px;font-weight:bold;padding:6px 10px;border-radius:4px;display:inline-block;margin:4px 0}
.v-good{background:#243b24;color:#7ec97e} .v-bad{background:#3b2420;color:#e06c5a}
.v-warn{background:#3b3420;color:#c3a55a}
"""
    # ---------- 題① ----------
    t1_rows = [group_row("當沖佔比前20%題材", t1["st_hi"]), group_row("當沖佔比後20%題材", t1["st_lo"]),
               group_row("佔比加速度前20%題材(5日均-20日均)", t1["st_acc"])]
    t1_table = car_table(t1_rows)
    t1_boot = "".join([
        boot_line("前20%題材−後20%題材 (demean中位差) k5", t1["boot"]["hi_lo_k5"]),
        boot_line("前20%題材−後20%題材 (demean中位差) k10", t1["boot"]["hi_lo_k10"]),
        boot_line("前20%題材−後20%題材 (demean中位差) k20", t1["boot"]["hi_lo_k20"]),
        boot_line("加速度前20%題材 demean中位數 vs 0 k5", t1["boot"]["acc_k5"]),
        boot_line("加速度前20%題材 demean中位數 vs 0 k10", t1["boot"]["acc_k10"]),
        boot_line("加速度前20%題材 demean中位數 vs 0 k20", t1["boot"]["acc_k20"]),
    ])
    hi_lo_20 = t1["boot"]["hi_lo_k20"]
    t1_sig = hi_lo_20 is not None and hi_lo_20["sig"]
    t1_dir_good = hi_lo_20 is not None and hi_lo_20["diff"] < 0  # 假說=高佔比題材"更差"(排雷/追高風險)非必然
    t1_verdict_cls = "v-warn"
    t1_verdict_txt = "🟡觀察層:前20%−後20%題材demean k20中位差CI含0" if hi_lo_20 is None or not hi_lo_20["sig"] \
        else ("⚠有方向但非追高有利:高佔比題材後續反而較弱" if hi_lo_20["diff"] < 0 else "高佔比題材後續較強")
    if hi_lo_20 is not None and hi_lo_20["sig"]:
        t1_verdict_cls = "v-bad" if hi_lo_20["diff"] < 0 else "v-good"

    # ---------- 題② ----------
    t2_rows = [group_row("飆股池全體(基準)", t2["base"])]
    for col, lab in (("ratio5", "當沖ratio 5日均"), ("dratio", "湧入度(ratio5-ratio20)"), ("fee", "近期借券費率")):
        sp = t2["splits"].get(col)
        if sp is None:
            continue
        t2_rows.append(group_row(f"{lab}·低組(安靜)", sp["lo"]))
        t2_rows.append(group_row(f"{lab}·高組(湧入/熱)", sp["hi"]))
    if t2["st_nofee"] is not None:
        t2_rows.append(group_row("無借券成交(空方缺席)", t2["st_nofee"]))
        t2_rows.append(group_row("有借券成交", t2["st_hasfee"]))
    if t2["st_neither"] is not None:
        t2_rows.append(group_row("2x2:當沖低∧費率低(安靜)", t2["st_neither"]))
        t2_rows.append(group_row("2x2:當沖高∧費率高(擁擠)", t2["st_both"]))
    t2_table = car_table(t2_rows)
    t2_boot_items = []
    for col, lab in (("ratio5", "當沖ratio5日均:安靜−湧入"), ("dratio", "湧入度:安靜−湧入"),
                     ("fee", "借券費率:低費率−高費率")):
        for k in (5, 10, 20):
            key = f"{col}_k{k}"
            if key in t2["boot"]:
                t2_boot_items.append(boot_line(f"{lab} demean中位差 k{k}", t2["boot"][key]))
    for k in (5, 10, 20):
        key = f"nofee_k{k}"
        if key in t2["boot"]:
            t2_boot_items.append(boot_line(f"無借券成交−有借券成交 demean中位差 k{k}", t2["boot"][key]))
    for k in (5, 10, 20):
        key = f"2x2_k{k}"
        if key in t2["boot"]:
            t2_boot_items.append(boot_line(f"2x2:安靜(當沖低∧費率低)−擁擠(當沖高∧費率高) demean中位差 k{k}",
                                           t2["boot"][key]))
    t2_boot = "".join(t2_boot_items)
    r5_20 = t2["boot"].get("ratio5_k20")
    dr_20 = t2["boot"].get("dratio_k20")
    t2_sig_count = sum(1 for r in (r5_20, dr_20) if r is not None and r["sig"] and r["diff"] > 0)
    if t2_sig_count >= 1:
        t2_verdict_cls, t2_verdict_txt = "v-good", "✅方向成立且部分排0:安靜成員k20顯著優於湧入成員"
    elif (r5_20 and r5_20["diff"] > 0) or (dr_20 and dr_20["diff"] > 0):
        t2_verdict_cls, t2_verdict_txt = "v-warn", "🟡方向對但CI含0:安靜組中位優於湧入組,樣本仍不足以排0"
    else:
        t2_verdict_cls, t2_verdict_txt = "v-warn", "🟡方向不穩定,需詳見逐項數字"

    # ---------- 題③ ----------
    t3_rows = [group_row("當沖暴增dt_surge事件", t3["st"]), group_row("case-control對照組(同日隨機非暴增股)", t3["st_ctrl"])]
    t3_table = car_table(t3_rows)
    t3_boot = "".join([
        boot_line("暴增事件 demean中位數 vs 0 k5", t3["boot"]["vs0_k5"]),
        boot_line("暴增事件 demean中位數 vs 0 k10", t3["boot"]["vs0_k10"]),
        boot_line("暴增事件 demean中位數 vs 0 k20", t3["boot"]["vs0_k20"]),
        boot_line("暴增事件−case-control對照組 中位差 k5", t3["boot"]["vsctrl_k5"]),
        boot_line("暴增事件−case-control對照組 中位差 k10", t3["boot"]["vsctrl_k10"]),
        boot_line("暴增事件−case-control對照組 中位差 k20", t3["boot"]["vsctrl_k20"]),
    ])
    vsctrl20 = t3["boot"]["vsctrl_k20"]
    if vsctrl20 is not None and vsctrl20["sig"] and vsctrl20["diff"] < 0:
        t3_verdict_cls, t3_verdict_txt = "v-good", "✅排雷假說成立且排0:暴增後續顯著弱於隨機對照組"
    elif vsctrl20 is not None and vsctrl20["diff"] < 0:
        t3_verdict_cls, t3_verdict_txt = "v-warn", "🟡方向支持排雷但CI含0:暴增組弱於對照組,未達顯著"
    else:
        t3_verdict_cls, t3_verdict_txt = "v-bad", "❌排雷假說不成立:暴增組未顯著弱於隨機對照組"

    # ---------- 題④ ----------
    t4_rows = [group_row(f"L1 Q{qq + 1}{'(低費率)' if qq == t4['q_lo'] else '(hard-to-borrow)' if qq == t4['q_hi'] else ''}",
                         t4["st_q"][qq]) for qq in sorted(t4["st_q"])]
    t4_rows += [group_row("L2跳升∧已漲(r20>+10%,可能軋空反轉)", t4["st_up"]),
               group_row("L2跳升∧已跌(r20<-10%,可能持續壓制)", t4["st_down"])]
    t4_table = car_table(t4_rows)
    t4_boot = "".join([
        boot_line("L1 Q5(hard-to-borrow)−Q1 demean中位差 k5", t4["boot_l1"]["k5"]),
        boot_line("L1 Q5(hard-to-borrow)−Q1 demean中位差 k10", t4["boot_l1"]["k10"]),
        boot_line("L1 Q5(hard-to-borrow)−Q1 demean中位差 k20", t4["boot_l1"]["k20"]),
        boot_line("L2跳升∧已漲 demean中位數 vs 0 k10", t4["boot_l2"]["vs0_up_k10"]),
        boot_line("L2跳升∧已跌 demean中位數 vs 0 k10", t4["boot_l2"]["vs0_down_k10"]),
        boot_line("L2跳升∧已漲 − 已跌 demean中位差 k10", t4["boot_l2"]["diff_k10"]),
        boot_line("L2跳升∧已漲 demean中位數 vs 0 k20", t4["boot_l2"]["vs0_up_k20"]),
        boot_line("L2跳升∧已跌 demean中位數 vs 0 k20", t4["boot_l2"]["vs0_down_k20"]),
        boot_line("L2跳升∧已漲 − 已跌 demean中位差 k20", t4["boot_l2"]["diff_k20"]),
    ])
    l1_20 = t4["boot_l1"]["k20"]
    if l1_20 is not None and l1_20["sig"] and l1_20["diff"] < 0:
        t4_verdict_cls, t4_verdict_txt = "v-good", "✅informed short假說成立且排0:Q5高費率組k20顯著弱於Q1"
    elif l1_20 is not None and l1_20["diff"] < 0:
        t4_verdict_cls, t4_verdict_txt = "v-warn", "🟡方向支持informed short但CI含0"
    else:
        t4_verdict_cls, t4_verdict_txt = "v-bad", "❌informed short假說於本資料不成立"

    # ---------- 圖表資料 ----------
    def bar_payload(labels, meds, colors):
        return {"labels": labels, "meds": [round(m, 2) if m is not None else None for m in meds], "colors": colors}

    c1 = bar_payload(["前20%題材", "後20%題材", "加速度前20%"],
                     [t1["st_hi"][20]["dm"][0], t1["st_lo"][20]["dm"][0], t1["st_acc"][20]["dm"][0]],
                     [RED, GREEN, YELLOW])
    c2_labels, c2_meds, c2_colors = [], [], []
    for col, lab in (("ratio5", "當沖ratio5日均"), ("dratio", "湧入度"), ("fee", "借券費率")):
        sp = t2["splits"].get(col)
        if sp is None:
            continue
        c2_labels += [f"{lab}·低(安靜)", f"{lab}·高(熱)"]
        c2_meds += [sp["lo"][20]["dm"][0], sp["hi"][20]["dm"][0]]
        c2_colors += [GREEN, RED]
    c2 = bar_payload(c2_labels, c2_meds, c2_colors)
    c3 = bar_payload(["暴增事件(demean)", "case-control對照組(raw)"],
                     [t3["st"][20]["dm"][0], t3["st_ctrl"][20]["raw"][0]], [RED, BLUE])
    c4_labels = [f"Q{qq + 1}" for qq in sorted(t4["st_q"])]
    c4_meds = [t4["st_q"][qq][20]["dm"][0] for qq in sorted(t4["st_q"])]
    c4 = bar_payload(c4_labels, c4_meds, [BLUE] * (len(c4_labels) - 1) + [RED])

    payload = {"c1": c1, "c2": c2, "c3": c3, "c4": c4}

    # ---------- 下一步建議 ----------
    all_sig = [hi_lo_20 is not None and hi_lo_20["sig"], t2_sig_count >= 1,
               vsctrl20 is not None and vsctrl20["sig"], l1_20 is not None and l1_20["sig"]]
    n_sig = sum(all_sig)
    if n_sig == 4:
        next_step = ("四題全部達到bootstrap顯著(排0)。建議正式入庫:新增<code>dt_daily</code>"
                     "(date,code,volume,buy_amount,sell_amount,ratio)與<code>lend_daily</code>"
                     "(date,code,vwfee,volume)兩表(逐日彙總版即可,不必存FinMind逐筆transaction_type明細),"
                     "供日後策略/儀表板直接查詢不必重讀12+6個pkl。")
    else:
        next_step = (f"四題中{n_sig}/4達到bootstrap顯著,其餘{4 - n_sig}題訊號較弱或方向不如預期"
                     "(見下方逐題判讀與已知限制)。建議<b>先不整批正式入庫</b>,只把達顯著的子題(見判讀)"
                     "的彙總欄位(如dt_surge旗標、L1 vwfee五分位)存進既有相關考卷的快取,"
                     "而非另開新table;待更多題目补充驗證或使用者裁示後再議整批schema。")

    payload_json = json.dumps(payload, ensure_ascii=False)

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>當沖×借券費率全史正式考卷(2026-07-31)</title>
<script src="plotly.min.js"></script><style>{css}</style></head><body>
<h1>📊 當沖×借券費率全史正式考卷——四題升級版(2014-2026,接續一年快看v2)</h1>
<div class="note">資料=根目錄tmp_dtlend_h2014~h2025.pkl(全史回補)+暫存/快取/tmp_dtlend_p1~p6.pkl(近一年,
2025-07-28~2026-07-28),經檢查兩批日期無重疊,合併去重後當沖列dt+借券列ln共用一份全史面板。
⚠此批資料刻意不寫入capital_flow.db(DB備份逼近95MB上限),考卷驗證通過才裁決是否入庫(見文末建議)。
本卷=scratch_dt_lend_quick.py(1年快看v2)的正式升級版:樣本擴大到全史,並補上每題的bootstrap/case-control
顯著性檢定(快看版只有點估計)。統計慣例:CAR k=1,2,3,5,10,20;絕對/demean(扣<b>同日</b>全宇宙或全題材
中位數報酬的截面版,比快看版的pooled-median demean更嚴謹)並列;bootstrap=月群重抽樣(n_iter=2000)算
中位差95%CI,「排0」=顯著。</div>

<h2>📋 四題判讀總表</h2>
<table>
<tr><th>題目</th><th>核心假說</th><th>判讀</th></tr>
<tr><th>①題材當沖佔比×波段</th><td>高佔比題材=籌碼過熱風險/低佔比=安全</td>
<td><span class="verdict {t1_verdict_cls}">{t1_verdict_txt}</span></td></tr>
<tr><th>②飆股安靜成員</th><td>熱題材裡當沖湧入度低的安靜成員後續較優</td>
<td><span class="verdict {t2_verdict_cls}">{t2_verdict_txt}</span></td></tr>
<tr><th>③當沖暴增(dt_surge)排雷</th><td>暴增後續常補跌,比隨機基準差</td>
<td><span class="verdict {t3_verdict_cls}">{t3_verdict_txt}</span></td></tr>
<tr><th>④L1費率informed short</th><td>高費率(難借券)組=知情放空,後續顯著更差</td>
<td><span class="verdict {t4_verdict_cls}">{t4_verdict_txt}</span></td></tr>
</table>

<h2>① 題材當沖佔比×波段</h2>
<div class="note">題材層當沖佔比=Σ當沖BuyAmount/Σ成交金額(先加總金額再算比率),
classification.main_group分組且成員>=3(有效題材-日面板n={t1['n_rows']:,},
{t1['n_themes']}個題材)。前20%組n={t1['n_hi']:,},後20%組n={t1['n_lo']:,},
加速度(5日均-20日均)前20%組n={t1['n_acc']:,}。</div>
{t1_table}
<h3>bootstrap顯著性(月群重抽樣,95%CI)</h3><ul>{t1_boot}</ul>

<h2>② 飆股安靜成員</h2>
<div class="note">飆股池=r20>=+40%∧amt20>=0.3億(20日去重),事件n={t2['n_pool']:,}。
池內三個切法(當沖ratio5日均/湧入度=ratio5日均-ratio20日均之差/近期借券費率)各做池內三分位對照,
核心假說=熱題材裡當沖湧入度低的安靜成員後續表現優於湧入度高的成員。</div>
{t2_table}
<h3>bootstrap顯著性(安靜組−湧入組 demean中位差,95%CI)</h3><ul>{t2_boot}</ul>

<h2>③ 當沖暴增排雷(dt_surge,⚠與build_index_panic_rebound.py的指數急殺「D2」同名異義)</h2>
<div class="note">當沖暴增(此處代號dt_surge避免與指數急殺D2混淆)定義=ratio>=30%∧ratio-20日均ratio>=15pp
(10日去重),事件n={t3['n_events']:,}。核心假說=排雷(暴增後續是否常補跌?)。除demean vs 0外,
另做<b>case-control</b>:逐事件日從同宇宙(amt20>=0.3億)排除當日所有暴增旗標股後隨機抽同數量的
非暴增股當對照組(n={t3['n_ctrl']:,}),比較兩組原始報酬中位差,直接回答「是否比隨機基準差」。</div>
{t3_table}
<h3>bootstrap/case-control顯著性(95%CI)</h3><ul>{t3_boot}</ul>

<h2>④ L1費率informed short + L2費率跳升</h2>
<div class="note">量加權費率vwfee=Σ(fee_rate×volume)/Σvolume(逐股逐日),每日全宇宙五分位,
L1面板n={len(t4['l1']):,}。L2費率跳升=vwfee-20日中位>=2pp∧vwfee>=3%(10日去重),事件n={t4['l2_n']:,},
依r20拆「跳升時已漲(n={t4['n_up']:,},可能軋空反轉)」vs「跳升時已跌(n={t4['n_down']:,},可能持續壓制)」。</div>
{t4_table}
<h3>bootstrap顯著性(95%CI)</h3><ul>{t4_boot}</ul>

<h2>📈 圖表(demean中位數,k20,除註明外)</h2>
<div id="c1" style="height:300px"></div>
<div id="c2" style="height:340px"></div>
<div id="c3" style="height:300px"></div>
<div id="c4" style="height:300px"></div>

<h2>🧭 下一步建議</h2>
<div class="note">{next_step}</div>

<h2>已知限制(誠實聲明)</h2>
<div class="note">
①classification覆蓋僅台股{n_cls_codes}檔題材股(非全市場),題①的題材層結論限於
被分類覆蓋的股票池,未覆蓋的個股(多為冷門/未上題材名單者)不在題①的題材聚合內,但題②③④的個股層
分析涵蓋dt/ln原始資料涉及的全部四碼非00股票(不受classification覆蓋限制,題②飆股池本身不套用題材分類);<br>
②bootstrap月群重抽樣假設「同月內事件近似獨立、跨月獨立」,恐慌/籌碼異動事件本質上會跨月成簇
(例如同一波飆股池事件可能橫跨2個月),CI寬度可能仍低估真實不確定性,是保守但非完美的做法;<br>
③demean版採「同日全宇宙(或全題材)中位數報酬」為基準,已濾掉當日大盤/題材整體方向,但未做風格
(市值/beta)配對,絕對報酬版本身仍含大盤方向;<br>
④題③case-control對照組為「同日隨機抽樣非暴增股」,抽樣使用固定亂數種子(20260731)以求可重現,
但仍是單一次抽樣非窮舉,若重新抽樣數字會有小幅波動(母體夠大時影響有限);<br>
⑤所有題目=盤點層/觀察層,本卷不涉及任何交易成本、可交易性(T+1開盤進場版)驗證,亦不預設上板。
</div>
<div class="note">維運:python 研究腳本/當沖借券/build_dtlend_report.py(從根目錄執行,鐵律)。
姊妹檔:根目錄scratch_dt_lend_quick.py(一年快看v2,本卷之前身)。</div>

<script>
const D={payload_json};
const BG={json.dumps(BG, ensure_ascii=False)};
function bar(id, title, d) {{
  Plotly.newPlot(id, [{{x:d.labels, y:d.meds, type:'bar', marker:{{color:d.colors}},
    text:d.meds.map(v=>v===null?'—':v.toFixed(2)+'%'), textposition:'outside'}}],
    Object.assign({{title:title, yaxis:{{title:'demean中位數k20(%)',zeroline:true,zerolinecolor:'#555'}}}}, BG));
}}
bar('c1', '題①:題材當沖佔比分組 k20 demean中位數', D.c1);
bar('c2', '題②:飆股池內三分位切法 k20 demean中位數', D.c2);
bar('c3', '題③:暴增事件 vs case-control對照組', D.c3);
bar('c4', '題④:L1費率五分位 k20 demean中位數(Q5=hard-to-borrow)', D.c4);
</script>
</body></html>"""
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[report] 已輸出 {OUT}")


# ======================================================================
# 8. main
# ======================================================================
def main():
    dt, ln = load_dtlend()
    cls = load_classification()
    n_cls_codes = cls.code.nunique()

    codes = sorted(set(dt.code) | set(ln.code))
    print(f"[main] 當沖+借券聯集宇宙 {len(codes)} 檔")
    close, op, vol, money = load_price(codes, "2013-10-01")

    amt20 = money.rolling(20, min_periods=15).mean() / 1e8
    uni = amt20 >= 0.3
    fwd = {k: (close.shift(-k) / close - 1) * 100 for k in KS}

    dtp = dt.pivot_table(index="date", columns="code", values="Volume", aggfunc="sum")
    ratio = (dtp / vol.reindex_like(dtp)).clip(0, 1)

    ln["fv"] = ln.fee_rate * ln.volume
    g = ln.groupby(["date", "code"]).agg(fv=("fv", "sum"), v=("volume", "sum"))
    g["vwfee"] = g.fv / g.v
    vwfee = g.reset_index().pivot(index="date", columns="code", values="vwfee")

    print("=" * 60, "\n[main] 開始計算題①")
    t1 = build_topic1(dt, money, uni, fwd, cls)
    print("=" * 60, "\n[main] 開始計算題②")
    t2 = build_topic2(close, uni, fwd, ratio, vwfee)
    print("=" * 60, "\n[main] 開始計算題③")
    t3 = build_topic3(ratio, uni, fwd)
    print("=" * 60, "\n[main] 開始計算題④")
    t4 = build_topic4(vwfee, uni, fwd, close)

    print("=" * 60, "\n[main] 組裝報告")
    write_report(t1, t2, t3, t4, n_cls_codes)


if __name__ == "__main__":
    main()
