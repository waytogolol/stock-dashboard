# -*- coding: utf-8 -*-
"""強制回補價格壓力事件研究(預註冊2026-08-02,使用者提案「暫停融券賣出表(融券回補日)」新資料源)
========================================================================
機制故事: 股東會/除權息前交易所公告「停止融資融券」,在此之前融券未回補部位強制買回=被迫買方,
與斷頭線(被迫賣方)鏡像對照——三問機制①「誰被迫交易」在此處先驗上最扎實(空單到期強制回補,
非自願)。資料集=TaiwanStockMarginShortSaleSuspension(見fetch_margin_short_suspend.py docstring),
欄位stock_id/date(停止融資融券起始日)/end_date/reason;本卷定義:
  last_cover = date的前一個「該股」交易日 ≈ 融券最後回補日(公告當天起停止融資融券,回補須在此之前完成)
  事件錨點一律用last_cover,不用date本身(date當天已經停止,買盤理論上已經結束)。

設計(預註冊,首跑即凍結):
  A. 核心假說: CAR形狀圖(-25~+15交易日,以last_cover-25為基期)+ 定點k(1,2,3,5,10,20)pre/post表,
     絕對報酬與demean(市場指數超額,上市扣TAIEX/上櫃扣TPEx同期報酬)並列。
  B. 案例對照(case-control): 同股配對安慰劑——每個事件在同股「非事件鄰近期」(排除所有事件
     last_cover前35~後30交易日)隨機抽一個等長10日窗當對照,事件pre10 vs 安慰劑pre10月群bootstrap比較。
  C. 強度分層: 短期無關(pre-existing)融券強度=last_cover-20的短部位水位(避開回補進行中的污染):
     ①短占股本比%=short_bal/(fin_limit*4)*100 ②回補天數=short_bal/(近20日均量張數);
     三分位/五分位梯度檢查(強度越高、回補推力越大是最直接的機制驗證)。僅margin_flow覆蓋期
     (上市2022-01起/上櫃2022-01起)可算,樣本縮水,誠實揭露。
  D. 分層: 全樣本 vs 流動性池(近20日均額>=0.3億);原因別(股東會/除權息/其他)描述性拆解。
判準: 月群bootstrap(2000次,ym=last_cover所在年月)+ 逐年LOTO;去重=同股連續事件last_cover間隔
  <40交易日視為窗口重疊,僅留第一筆(house慣例gap dedup,40=覆蓋多數年配息股AGM→首次除息間隔)。
單位慣例: 所有CAR/pp數值在計算當下已經*100轉成百分比,以下函式與報表一律直接沿用,不再乘100。
資料: margin_short_suspend × fm_daily_price(2005起) × index_daily(TAIEX/TPEx) × margin_flow(_otc)。
報告: 研究報告/research_short_covering_pressure.html
用法: python 研究腳本/融券回補/build_short_covering_pressure.py   (從專案根目錄執行)
"""
import csv
import sqlite3
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
DB = "capital_flow.db"
KS = [1, 2, 3, 5, 10, 20]
SHAPE_OFF = list(range(-25, 16))
MIN_GAP = 40  # 同股連續事件去重門檻(交易日)
LIQ_TH = 0.3  # 流動性池門檻(億元,近20日均額)
GREEN, RED, BLUE, YELLOW, GRAY, PURPLE = "#7ec97e", "#e06c5a", "#6bb7e3", "#c3a55a", "#8a8878", "#b393d3"
rng = np.random.default_rng(20260802)


# ---------------------------------------------------------------- 統計工具(全卷唯一版本,避免key不一致)
def med_win(x):
    """回傳(中位數%, 勝率%, n)。x已是百分比單位。"""
    x = pd.Series(x).dropna()
    if not len(x):
        return None, None, 0
    return float(x.median()), float((x > 0).mean() * 100), int(len(x))


def boot_med(df, val_col="value", ym_col="ym", n_iter=2000):
    """單組月群bootstrap中位數95%CI。回傳dict{med,lo,hi,n}(單位=%,與val_col原始單位相同)。"""
    a = df[df[val_col].notna()]
    if len(a) < 15 or a[ym_col].nunique() < 3:
        return None
    grp = a.groupby(ym_col)[val_col].apply(list)
    meds = []
    idx = np.arange(len(grp))
    for _ in range(n_iter):
        draw = rng.choice(idx, size=len(idx), replace=True)
        meds.append(np.median(np.concatenate([grp.iloc[i] for i in draw])))
    return {"med": float(a[val_col].median()), "lo": float(np.percentile(meds, 2.5)),
            "hi": float(np.percentile(meds, 97.5)), "n": int(len(a))}


def boot_diff(df_a, df_b, val_col="value", ym_col="ym", n_iter=2000):
    """兩組月群bootstrap中位差95%CI(a−b)。回傳dict{diff,lo,hi,na,nb}。"""
    a, b = df_a[df_a[val_col].notna()], df_b[df_b[val_col].notna()]
    if len(a) < 15 or len(b) < 15:
        return None
    ga, gb = a.groupby(ym_col)[val_col].apply(list), b.groupby(ym_col)[val_col].apply(list)
    diffs = []
    for _ in range(n_iter):
        av = np.concatenate([ga.iloc[i] for i in rng.integers(0, len(ga), len(ga))])
        bv = np.concatenate([gb.iloc[i] for i in rng.integers(0, len(gb), len(gb))])
        diffs.append(np.median(av) - np.median(bv))
    return {"diff": float(a[val_col].median() - b[val_col].median()),
            "lo": float(np.percentile(diffs, 2.5)), "hi": float(np.percentile(diffs, 97.5)),
            "na": int(len(a)), "nb": int(len(b))}


def loto(df, val_col="value", year_col="year", th=0.0):
    """逐年LOTO: 該年中位數是否 > th,回傳(正年數,總年數)。"""
    a = df[df[val_col].notna()]
    pos = tot = 0
    for y in sorted(a[year_col].unique()):
        v = a[a[year_col] == y][val_col]
        if len(v) >= 8:
            tot += 1
            pos += int(v.median() > th)
    return pos, tot


def ci_tag(b, key="med"):
    if b is None:
        return "n小"
    return f"[{b['lo']:+.2f},{b['hi']:+.2f}]{'✓排0' if (b['lo'] > 0 or b['hi'] < 0) else '含0'}"


# ---------------------------------------------------------------- 資料載入
def load():
    print("載入資料...", flush=True)
    conn = sqlite3.connect(DB, timeout=60)
    susp = pd.read_sql("SELECT * FROM margin_short_suspend", conn, parse_dates=["start_date", "end_date"])
    px = pd.read_sql("SELECT code, date, close, volume, money FROM fm_daily_price WHERE close>0 ORDER BY code, date",
                     conn, parse_dates=["date"])
    mf = pd.read_sql("SELECT date, code, fin_limit, short_bal FROM margin_flow", conn, parse_dates=["date"])
    mfo = pd.read_sql("SELECT date, code, fin_limit, short_bal FROM margin_flow_otc", conn, parse_dates=["date"])
    idx = pd.read_sql("SELECT market, date, close FROM index_daily WHERE market IN ('TAIEX','TPEx')",
                      conn, parse_dates=["date"])
    conn.close()
    with open("tw_all_listed.csv", encoding="utf-8-sig") as f:
        mkt_map = {r["code"]: r["market"] for r in csv.DictReader(f)}
    print(f"  susp={len(susp):,} px={len(px):,} mf={len(mf):,} mfo={len(mfo):,}", flush=True)
    return susp, px, mf, mfo, idx, mkt_map


def build_stock_panels(px, idx, mkt_map, mf, mfo):
    """回傳dict code -> {date,close,volume,idxc(對齊市場指數),fbal(短部位),flimit}(皆為numpy array,對齊date)"""
    idx_s = {m: g.sort_values("date").set_index("date")["close"] for m, g in idx.groupby("market")}
    mf_by_code = {c: g.sort_values("date").set_index("date") for c, g in mf.groupby("code")}
    mfo_by_code = {c: g.sort_values("date").set_index("date") for c, g in mfo.groupby("code")}
    panels = {}
    for code, g in px.groupby("code"):
        mkt = mkt_map.get(code)
        if mkt not in ("上市", "上櫃"):
            continue
        g = g.sort_values("date")
        dates = g.date
        idx_series = idx_s.get("TAIEX" if mkt == "上市" else "TPEx")
        if idx_series is None:
            continue
        idxc = idx_series.reindex(dates, method="ffill").values
        if np.isnan(idxc).all():
            continue
        chip = mf_by_code.get(code) if mkt == "上市" else mfo_by_code.get(code)
        if chip is not None:
            fbal = chip["short_bal"].reindex(dates, method="ffill", limit=3).values
            flimit = chip["fin_limit"].reindex(dates, method="ffill", limit=3).values
        else:
            fbal = np.full(len(g), np.nan)
            flimit = np.full(len(g), np.nan)
        panels[code] = {"market": mkt, "date": dates.values, "close": g.close.values,
                        "volume": g.volume.values, "money": g.money.values,
                        "idxc": idxc, "fbal": fbal, "flimit": flimit}
    print(f"  股票面板建立: {len(panels):,}檔(有市場對映+指數可比對)", flush=True)
    return panels


REASON_BUCKET = {"股東常會": "股東會", "股東臨時會": "股東會",
                 "除息": "除權息", "除權": "除權息", "除權息": "除權息", "除權、息": "除權息"}


def bucket_reason(r):
    return REASON_BUCKET.get(r, "其他")


# ---------------------------------------------------------------- 事件面板建構
def build_events(susp, panels):
    rows = []
    n_skip_price = n_skip_window = n_skip_dedup = 0
    for code, eg in susp.groupby("code"):
        pan = panels.get(code)
        if pan is None:
            n_skip_price += len(eg)
            continue
        dates, close, idxc, vol = pan["date"], pan["close"], pan["idxc"], pan["volume"]
        fbal, flimit = pan["fbal"], pan["flimit"]
        n = len(dates)
        eg = eg.sort_values("start_date")
        last_kept = -10 ** 9
        for _, e in eg.iterrows():
            t0 = int(np.searchsorted(dates, np.datetime64(e.start_date)))
            last_cover = t0 - 1
            if last_cover - 25 < 0 or last_cover + 20 >= n:
                n_skip_window += 1
                continue
            if last_cover - last_kept < MIN_GAP:
                n_skip_dedup += 1
                continue
            last_kept = last_cover
            lc = last_cover
            c0, i0 = close[lc], idxc[lc]
            if c0 <= 0 or not np.isfinite(i0) or i0 <= 0:
                continue
            rec = {"code": code, "market": pan["market"], "reason": e.reason,
                  "bucket": bucket_reason(e.reason),
                  "last_cover_date": pd.Timestamp(dates[lc]),
                  "year": pd.Timestamp(dates[lc]).year,
                  "ym": pd.Timestamp(dates[lc]).strftime("%Y-%m"),
                  "amt20": float(np.nanmean(pan["money"][max(0, lc - 19):lc + 1])) / 1e8}
            for k in KS:
                c_pre, i_pre = close[lc - k], idxc[lc - k]
                c_post, i_post = close[lc + k], idxc[lc + k]
                rec[f"pre_raw_{k}"] = (c0 / c_pre - 1) * 100 if c_pre > 0 else np.nan
                rec[f"pre_dm_{k}"] = ((c0 / c_pre) / (i0 / i_pre) - 1) * 100 if (c_pre > 0 and i_pre > 0) else np.nan
                rec[f"post_raw_{k}"] = (c_post / c0 - 1) * 100 if c_post > 0 else np.nan
                rec[f"post_dm_{k}"] = ((c_post / c0) / (i_post / i0) - 1) * 100 if (c_post > 0 and i_post > 0) else np.nan
            # shape(-25..+15,基期=lc-25)
            base_c, base_i = close[lc - 25], idxc[lc - 25]
            shp_raw, shp_dm = {}, {}
            for off in SHAPE_OFF:
                ci, ii = close[lc + off], idxc[lc + off]
                shp_raw[off] = (ci / base_c - 1) * 100 if base_c > 0 else np.nan
                shp_dm[off] = ((ci / base_c) / (ii / base_i) - 1) * 100 if (base_c > 0 and base_i > 0) else np.nan
            rec["_shp_raw"], rec["_shp_dm"] = shp_raw, shp_dm
            # 強度: last_cover-20的既有短部位(避開回補進行中的污染)
            m20 = lc - 20
            sb, fl = fbal[m20], flimit[m20]
            avgvol20 = np.nanmean(vol[max(0, m20 - 19):m20 + 1]) / 1000  # 張
            rec["short_pct_float"] = sb / (fl * 4) * 100 if (np.isfinite(sb) and np.isfinite(fl) and fl > 0) else np.nan
            rec["days_to_cover"] = sb / avgvol20 if (np.isfinite(sb) and avgvol20 > 0) else np.nan
            rec["short_bal_m20"] = sb
            # 案例對照安慰劑: 同股非事件鄰近期隨機抽一個10日窗
            rec["_lc"] = lc
            rows.append(rec)
    df = pd.DataFrame(rows)
    print(f"事件面板: {len(df):,}筆(略過: 無價格面板{n_skip_price} / 窗口不足{n_skip_window} / 去重{n_skip_dedup})",
          flush=True)
    print(f"  {df.code.nunique()}檔 / {df.last_cover_date.min().date()}~{df.last_cover_date.max().date()}", flush=True)
    return df


def attach_placebo(df, panels):
    """同股配對安慰劑: 排除所有事件lc-35~lc+30的index,從剩餘池隨機抽一點做10日窗對照。
    用df.index對齊寫回(不依賴groupby輸出順序=df原順序這個脆弱假設),避免錯位。"""
    placebo_raw = pd.Series(np.nan, index=df.index)
    placebo_dm = pd.Series(np.nan, index=df.index)
    for code, eg in df.groupby("code"):
        pan = panels[code]
        n = len(pan["date"])
        close, idxc = pan["close"], pan["idxc"]
        excl = set()
        for lc in eg["_lc"]:
            excl.update(range(max(0, lc - 35), min(n, lc + 30)))
        pool = [i for i in range(25, n - 1) if i not in excl]
        for i in eg.index:
            if len(pool) < 5:
                continue
            j = int(rng.choice(pool))
            c0, cj = close[j], close[j - 10]
            i0, ij = idxc[j], idxc[j - 10]
            placebo_raw.loc[i] = (c0 / cj - 1) * 100 if cj > 0 else np.nan
            placebo_dm.loc[i] = ((c0 / cj) / (i0 / ij) - 1) * 100 if (cj > 0 and ij > 0) else np.nan
    df["placebo_pre_raw_10"] = placebo_raw
    df["placebo_pre_dm_10"] = placebo_dm
    return df


# ---------------------------------------------------------------- 報表片段
def fmt(v, digits=2, pct=True):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "—"
    return f"{v:+.{digits}f}{'%' if pct else ''}"


def cell(m, w, n):
    """med_win()三元組安全轉td內容,m/w皆可能為None(n=0時)。"""
    if m is None:
        return "n=0"
    return f"{fmt(m)}/{w:.0f}%(n={n})"


def k_table_html(df, prefix, label):
    rows = ""
    for k in KS:
        m, w, n = med_win(df[f"{prefix}_raw_{k}"])
        md, wd, nd = med_win(df[f"{prefix}_dm_{k}"])
        cls = "good" if (md is not None and md > 0) else ("bad" if md is not None else "")
        rows += (f"<tr><th>{label}{k}</th><td>{cell(m, w, n)}</td>"
                 f"<td class='{cls}'>{cell(md, wd, nd)}</td></tr>")
    return rows


def quantile_table(df, by_col, val_col="pre_dm_10", q=3, labels=None):
    d = df[[by_col, val_col, "ym", "year"]].dropna()
    if len(d) < 30:
        return "<div class='note'>樣本不足(n&lt;30),略過分層</div>", None, None
    d = d.copy()
    d["q"] = pd.qcut(d[by_col], q, labels=False, duplicates="drop")
    if d.q.nunique() < 2:
        return "<div class='note'>數值過度集中(如大量0),qcut分不出區間,略過分層</div>", None, None
    rows = ""
    for qi in sorted(d.q.unique()):
        sub = d[d.q == qi]
        m, w, n = med_win(sub[val_col])
        rows += (f"<tr><th>Q{int(qi) + 1}({by_col}中位{sub[by_col].median():.2f})</th>"
                 f"<td>{cell(m, w, n)}</td><td>{n}</td></tr>")
    lo_q, hi_q = d.q.min(), d.q.max()
    diff = boot_diff(d[d.q == hi_q].assign(value=d[d.q == hi_q][val_col]),
                     d[d.q == lo_q].assign(value=d[d.q == lo_q][val_col]))
    p, t = loto(d[d.q == hi_q].assign(value=d[d.q == hi_q][val_col]))
    return f"<table><tr><th>分位</th><th>{val_col}中位/勝率</th><th>n</th></tr>{rows}</table>", diff, (p, t)


# ---------------------------------------------------------------- 主流程
def main():
    susp, px, mf, mfo, idx, mkt_map = load()
    panels = build_stock_panels(px, idx, mkt_map, mf, mfo)
    df = build_events(susp, panels)
    df = attach_placebo(df, panels)
    df.drop(columns=["_shp_raw", "_shp_dm", "_lc"]).to_pickle("快取/tmp_short_suspend_panel.pkl")

    liq = df[df.amt20 >= LIQ_TH]
    print(f"流動性池(近20日均額>={LIQ_TH}億): {len(liq):,}/{len(df):,}", flush=True)

    print("\n== A. 核心假說 pre/post CAR(全樣本) ==")
    for k in KS:
        m, w, n = med_win(df[f"pre_raw_{k}"])
        md, wd, nd = med_win(df[f"pre_dm_{k}"])
        print(f"  pre_{k}: raw {cell(m, w, n)}  demean {cell(md, wd, nd)}")
    for k in KS:
        m, w, n = med_win(df[f"post_raw_{k}"])
        md, wd, nd = med_win(df[f"post_dm_{k}"])
        print(f"  post_{k}: raw {cell(m, w, n)}  demean {cell(md, wd, nd)}")

    boot10 = boot_med(df.assign(value=df.pre_dm_10))
    p10, t10 = loto(df.assign(value=df.pre_dm_10))
    print(f"\n  主檢定 pre_dm_10 bootstrap: med={boot10['med']:+.2f} CI{ci_tag(boot10)} n={boot10['n']} | LOTO {p10}/{t10}正"
          if boot10 else "  主檢定樣本不足")

    print("\n== A2. 流動性池對照(近20日均額>=0.3億) ==")
    for k in (5, 10, 20):
        m, w, n = med_win(liq[f"pre_dm_{k}"])
        print(f"  pre_dm_{k}: {cell(m, w, n)}")

    print("\n== B. 案例對照(同股安慰劑) ==")
    diff_placebo = boot_diff(df.assign(value=df.pre_dm_10), df.assign(value=df.placebo_pre_dm_10))
    m_ev, w_ev, n_ev = med_win(df.pre_dm_10)
    m_pl, w_pl, n_pl = med_win(df.placebo_pre_dm_10)
    print(f"  事件窗pre_dm_10: {cell(m_ev, w_ev, n_ev)}  安慰劑窗: {cell(m_pl, w_pl, n_pl)}")
    print(f"  差(事件−安慰劑) bootstrap: {diff_placebo}" if diff_placebo else "  樣本不足")

    print("\n== C. 強度分層(限margin_flow覆蓋期,~2022-01起) ==")
    strength_df = df.dropna(subset=["short_pct_float"])
    print(f"  可算強度樣本: {len(strength_df):,}")
    float_tbl, float_diff, float_loto = quantile_table(strength_df, "short_pct_float", "pre_dm_10", q=3)
    dtc_df = df.dropna(subset=["days_to_cover"])
    dtc_tbl, dtc_diff, dtc_loto = quantile_table(dtc_df, "days_to_cover", "pre_dm_10", q=3)
    print(f"  short_pct_float diff(高−低): {float_diff}")
    print(f"  days_to_cover diff(高−低): {dtc_diff}")

    print("\n== D. 原因別 ==")
    bucket_rows = []
    for b, g in df.groupby("bucket"):
        m, w, n = med_win(g.pre_dm_10)
        bucket_rows.append((b, m, w, n))
        print(f"  {b}: pre_dm_10 {cell(m, w, n)}")

    # ---------------------------------------------------------------- 報表
    # shape矩陣取自df的_shp_raw/_shp_dm欄位(dict per row,drop_pickle前保留,寫pickle後才丟棄)
    shp_raw_mat = pd.DataFrame(list(df["_shp_raw"])) if "_shp_raw" in df.columns else None
    shp_dm_mat = pd.DataFrame(list(df["_shp_dm"])) if "_shp_dm" in df.columns else None
    shape_raw_med = [float(shp_raw_mat[off].median()) for off in SHAPE_OFF] if shp_raw_mat is not None else []
    shape_dm_med = [float(shp_dm_mat[off].median()) for off in SHAPE_OFF] if shp_dm_mat is not None else []

    reason_counts = df.reason.value_counts().to_dict()
    reason_rows = "".join(f"<tr><th>{r}</th><td>{c:,}</td></tr>"
                          for r, c in sorted(reason_counts.items(), key=lambda x: -x[1]))

    pre_tbl = k_table_html(df, "pre", "pre_")
    post_tbl = k_table_html(df, "post", "post_")
    liq_pre_tbl = k_table_html(liq, "pre", "pre_")

    bucket_tbl = "".join(f"<tr><th>{b}</th><td>{cell(m, w, n)}</td><td>{n}</td></tr>"
                         for b, m, w, n in bucket_rows)

    def diff_html(d):
        if d is None:
            return "n不足"
        return f"{d['diff']:+.2f}pp CI[{d['lo']:+.2f},{d['hi']:+.2f}]{'✓排0' if (d['lo']>0 or d['hi']<0) else '含0'}"

    CSS = """
body{background:#1a1a19;color:#fff;font-family:"Noto Sans TC",sans-serif;margin:24px;max-width:1150px}
h1{font-size:20px} h2{font-size:15px;color:#c3c2b7;margin-top:30px;border-bottom:1px solid #333;padding-bottom:4px}
h3{font-size:13.5px;color:#a8a79a;margin:16px 0 4px}
table{border-collapse:collapse;font-size:12.5px;font-variant-numeric:tabular-nums;margin:8px 0}
td,th{border:1px solid #333;padding:4px 9px;text-align:right} th{text-align:left;color:#c3c2b7}
.note{color:#8a8878;font-size:12.5px;line-height:1.8} .good{color:#7ec97e} .bad{color:#e06c5a}
.warn{color:#c3a55a} .hl{background:#2b3a2b} .sub{color:#777;font-size:11px}
.banner{background:#3a2a1a;border:1px solid #c3a55a;border-radius:6px;padding:14px 18px;margin:16px 0;
        color:#f0dfa8;font-size:13.5px;line-height:1.8}
#chart1{width:100%;height:420px}
"""
    BG = {"paper_bgcolor": "#1a1a19", "plot_bgcolor": "#22221f",
         "font": {"color": "#ddd", "size": 12}, "margin": {"t": 40, "l": 55, "r": 20, "b": 40}}

    import json

    def _clean(v):
        return None if (v is None or (isinstance(v, float) and np.isnan(v))) else round(v, 3)

    chart_payload = {"x": SHAPE_OFF, "raw": [_clean(v) for v in shape_raw_med],
                     "dm": [_clean(v) for v in shape_dm_med]}

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>強制回補價格壓力考卷(2026-08-02)</title>
<script src="plotly.min.js"></script><style>{CSS}</style></head><body>
<h1>🔒 強制回補價格壓力考卷——暫停融券賣出表(融券回補日)事件研究</h1>
<div class="note">動機: 股東會/除權息前交易所公告「停止融資融券」,融券未回補部位強制買回=被迫買方,
與斷頭線(被迫賣方)鏡像對照。資料集=<code>TaiwanStockMarginShortSaleSuspension</code>
(FinMind,2015-01起,free/data_id逐檔或Backer單日全市場皆可查,本卷用逐檔一次拿全期,見
抓取/fetch_margin_short_suspend.py)。事件錨點=last_cover(公告當天前一交易日,融券最後回補日),
不是「date」本身(那天已經停止,買盤理論上已結束)。設計細節見build_short_covering_pressure.py開頭docstring。</div>

<h2>📋 資料覆蓋</h2>
<table><tr><th>項目</th><th>數字</th></tr>
<tr><th>原始事件(fetch)</th><td>{len(susp):,}筆 / {susp.code.nunique():,}檔 / {susp.start_date.min().date()}~{susp.start_date.max().date()}</td></tr>
<tr><th>可用事件(有價格面板+窗口足夠+去重後)</th><td>{len(df):,}筆 / {df.code.nunique():,}檔 / {df.last_cover_date.min().date()}~{df.last_cover_date.max().date()}</td></tr>
<tr><th>流動性池(近20日均額≥{LIQ_TH}億)</th><td>{len(liq):,}筆</td></tr>
<tr><th>可算融券強度(margin_flow覆蓋期)</th><td>{len(strength_df):,}筆</td></tr>
</table>
<table><tr><th>原因</th><th>次數</th></tr>{reason_rows}</table>

<h2>A. 核心假說: 事件日前是否有累積上漲壓力(pre)+事件後(post)</h2>
<div class="note">pre_k=(last_cover收盤/last_cover−k收盤−1),post_k=(last_cover+k收盤/last_cover收盤−1);
demean=扣同期市場指數報酬(上市扣TAIEX/上櫃扣TPEx),即case-control的第一層(排除當天大盤本身的漲跌)。</div>
<table><tr><th>水平</th><th>絕對報酬 中位/勝率(n)</th><th>demean 中位/勝率(n)</th></tr>{pre_tbl}</table>
<table><tr><th>水平(事件後)</th><th>絕對報酬 中位/勝率(n)</th><th>demean 中位/勝率(n)</th></tr>{post_tbl}</table>
<div class="note">主檢定(pre_dm_10,月群bootstrap 2000次): 中位{fmt(boot10['med']) if boot10 else '—'}
CI{ci_tag(boot10) if boot10 else 'n不足'}(n={boot10['n'] if boot10 else 0}); 逐年LOTO {p10}/{t10}年正
(僅計n≥8的年份)。</div>

<h3>CAR形狀(-25~+15交易日,基期=last_cover-25;offset=0為last_cover)</h3>
<div id="chart1"></div>

<h3>流動性池對照(近20日均額≥{LIQ_TH}億,排除小型雜訊股)</h3>
<table><tr><th>水平</th><th>絕對報酬 中位/勝率(n)</th><th>demean 中位/勝率(n)</th></tr>{liq_pre_tbl}</table>

<h2>B. 案例對照(同股配對安慰劑)</h2>
<div class="note">每個事件在同股「非事件鄰近期」(排除所有事件last_cover前35~後30交易日)隨機抽一個
等長10日窗當對照,檢驗事件窗漲勢是否顯著高於該股平常隨機10日窗(比單純扣大盤更嚴格的case-control,
排除個股自身結構性上漲慣性/小型股長期drift的混淆)。</div>
<table><tr><th>組別</th><th>pre_dm_10 中位/勝率(n)</th></tr>
<tr><th>事件窗(last_cover前10日)</th><td>{cell(m_ev, w_ev, n_ev)}</td></tr>
<tr><th>安慰劑窗(同股隨機非事件10日)</th><td>{cell(m_pl, w_pl, n_pl)}</td></tr>
<tr class="hl"><th>差(事件−安慰劑)</th><td>{diff_html(diff_placebo)}</td></tr></table>

<h2>C. 強度分層——融券部位越重,回補推力是否越大?</h2>
<div class="note">強度水位取last_cover<b>前20交易日</b>(回補潮尚未開始前的既有部位,避開污染)。
①短占股本比%=short_bal/(fin_limit×4)×100(fin_limit=股本25%法規口徑,同build_margin_capitulation口徑);
②回補天數=short_bal/近20日均量(張),即市場常見days-to-cover。僅margin_flow覆蓋期(上市/上櫃皆2022-01起)
可算,樣本縮水為{len(strength_df):,}筆(⚠僅約4.5年單一regime,earlier年份無法驗證)。</div>
<h3>① 短占股本比 三分位梯度</h3>
{float_tbl}
<div class="note">高−低分位差: {diff_html(float_diff)}{f' 逐年{float_loto[0]}/{float_loto[1]}正' if float_loto else ''}</div>
<h3>② 回補天數(days-to-cover) 三分位梯度</h3>
{dtc_tbl}
<div class="note">高−低分位差: {diff_html(dtc_diff)}{f' 逐年{dtc_loto[0]}/{dtc_loto[1]}正' if dtc_loto else ''}</div>

<h2>D. 原因別(股東會 vs 除權息 vs 其他)</h2>
<table><tr><th>原因分類</th><th>pre_dm_10 中位/勝率</th><th>n</th></tr>{bucket_tbl}</table>

<h2>🔍 三問機制自我檢查</h2>
<table><tr><th>問題</th><th>討論</th></tr>
<tr><th>①誰被迫交易?</th><td>融券未回補者。答案明確且是本表最強的先驗優勢——停止融資融券期間內
完全不能維持融券部位,回補是<b>法規強制</b>,不是自願停損或止盈,機制與斷頭線(維持率不足強制賣出)
同一家族的鏡像對照(此處是強制買方)。</td></tr>
<tr><th>②資訊是新的嗎?</th><td>不是。停止融資融券公告是全市場公開資訊,交易所在停止日前數週甚至
數月就已公告(見上方股東會事件的date通常落在實際股東會前1-2個月,除息事件date也是官方排定的除息基準日
前置作業),理論上該被市場快速消化——這點確實削弱「訊號」的意義:如果有壓力,更可能是<b>被迫回補的
實際成交量</b>造成的機械性買盤,而非「別人沒注意到」的資訊性錯價。這也是本卷選擇「事件日之前」
而非「當天」當主戰場的原因:即使日期公開,實際回補動作仍需要真實成交,買盤不會憑空消失,
只是「誰先卡位吃這段」的問題,不是「訊號本身有沒有用」的問題。</td></tr>
<tr><th>③為何別人沒吃掉它?</th><td>三個可能的執行障礙: (a)融券回補是<b>買進動作</b>,理論上任何人
都能提前買進「搶帽子」卡位,套利本身沒有放空限制那樣的執行門檛,故此訊號的公開性問題比斷頭線更嚴重
(斷頭是被動觸發、事前不確定日期;這裡的日期是<b>排定好的</b>,套利者理論上可以精準卡位在T-10甚至更早進場,
把肉吃光); (b)但融券回補的「量」本身有不確定性(公告日已知,但實際哪些券商/哪些空單會拖到最後一刻
才補、拖多久,盤中無法即時觀察到,量化上仍有資訊差); (c)個股流動性/交易成本可能限制套利資金規模
(見上方流動性池對照,若訊號只在小型股成立,大資金套利不進去,訊號才可能倖存)。三問綜合判斷=
<b>此假說的機制故事雖然扎實,但②「資訊是舊的」是先驗上最大的隱憂</b>,實際上是否還有剩餘的alpha
要看上方A/B/C三段的實證數字(是否demean後仍顯著、是否強度越高效果越大);如果C段強度分層沒有梯度,
最合理的解讀是「訊號早就被套利吃光,只剩下對強度不敏感的雜訊」。</td></tr>
</table>

<h2>限制</h2>
<div class="note">①margin_flow僅2022-01起覆蓋,強度分層樣本橫跨單一景氣循環(2022熊市+2023-26修復);
②tw_all_listed市場別為現況快照,個股歷史上市/上櫃轉換未回溯校正(少量誤分類可能);③last_cover定義=
公告date的前一交易日,若FinMind date欄位語意實際上略有出入(例如已經是最後回補日本身而非停止日),
本卷口徑會系統性偏移1個交易日,不影響CAR形狀判讀但k=1可能需要謹慎解讀;④demean僅扣大盤指數
(TAIEX/TPEx),非完整多因子模型(規模/動能因子未控制),案例對照(B段)為部分彌補;
⑤股息未還原、交易成本未計入(本卷為訊號存在性檢定,非可執行策略回測)。</div>
</body>
<script>
var p = {json.dumps(chart_payload)};
Plotly.newPlot('chart1', [
  {{x:p.x, y:p.raw, name:'絕對CAR(中位數)', line:{{color:'{BLUE}'}}}},
  {{x:p.x, y:p.dm, name:'demean CAR(中位數,扣大盤)', line:{{color:'{GREEN}'}}}},
], Object.assign({{title:'last_cover前後CAR形狀(0=最後回補日)',
  xaxis:{{title:'相對last_cover的交易日offset'}}, yaxis:{{title:'CAR(%)'}},
  shapes:[{{type:'line',x0:0,x1:0,y0:0,y1:1,yref:'paper',line:{{color:'{YELLOW}',dash:'dot'}}}}]}}, {json.dumps(BG)}));
</script>
</html>"""
    out = "研究報告/research_short_covering_pressure.html"
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n報告已產出 {out} ({len(html):,} chars)", flush=True)


if __name__ == "__main__":
    main()
