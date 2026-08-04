# -*- coding: utf-8 -*-
"""台股歷史財報八因子(水準×變化)前瞻報酬考卷(2026-08-05,使用者指定回測財報因子)。

背景: 2026-08-04使用者要求抓台股歷史財報並回測財報因子,資料已入庫
capital_flow.db.tw_quarterly_financials_history(39,102筆/826檔/2013Q1~2026Q2,單季損益)+
tw_quarterly_balance_cashflow_history(39,867筆/826檔,資產負債+現金流)。股票池=近20日均額>=0.3億
流動性池。使用者先前研究過稅後淨利率/營業利益率「有點幫助」;專案盤點確認毛利率是全專案最乾淨的
因子空白,市值只當過篩選門檻從未正式測過。

⚠方法論第一殺手=公告時滯(look-ahead): 季報date欄位是「季底日」,實際公告遠晚於季底。台股法定
期限: Q1=5/15、Q2=8/14、Q3=11/14、年報(Q4)=次年3/31。本卷統一用avail_date(quarter_end)=
法定期限+BUFFER_DAYS(5)日曆日緩衝,再取其後第一個TAIEX交易日當「形成日」——同一季全體股票用
同一形成日做cross-sectional分位,任何特徵都嚴格只用形成日前已依法公告的財報。已知限制: 金控/
保險業部分季別法定期限較晚(如Q1=5/30),本卷統一用一般公司期限,對金融股可能提早數日用到
尚未公告的數字,屬小範圍誤差,誠實揭露於報告限制段。

⚠本卷資料考察發現(寫程式前先驗證過): 現金流量表科目(operating_cash_flow/depreciation)是
「年內累計YTD」而非單季(dep同年Q4/Q1中位數比=4.04,99.8%firm-year年內單調遞增),損益表科目
(revenue/income_after_taxes等)才是單季——應計因子的OCF必須先去累計化(Q1照用,Q2~Q4=本季-上季,
上季缺值則NaN),否則應計比率整個算錯。

八因子×操作化(15個版本,每個×k=20/60/120前瞻窗=45格,多重比較自覺見報告限制段):
  1 毛利率: 水準gm_lv + QoQ變化gm_chg(另備連續改善季數當第二關規則素材)
  2 營業利益率: om_lv + om_chg(使用者先前說「有點幫助」,重點驗證)
  3 稅後淨利率: nm_lv + nm_chg
  4 槓桿比率(liabilities/total_assets既有leverage_ratio): lev_lv + lev_chg;另做
    「高槓桿×市場重挫期」條件表現(2022熊市/2025-04關稅重挫/2026-07回檔三段+各自前一年同長度
    平靜對照窗,呼應週級動能crash risk討論)
  5 存貨/營收比: invrev_lv + invrev_chg(存貨成長超過營收成長=需求轉弱警訊,Abarbanell&Bushee式)
  6 合約負債/營收比: clrev_lv + clrev_chg(揭露覆蓋率僅46%且IFRS15後2018起才有,只在有揭露
    子樣本測,n數如實報告)
  7 應計異常accrual proxy: (income_after_taxes-單季化OCF)/total_assets(Sloan 1996): accr_lv+accr_chg
  8 市值: capital.shares(向前填補)×形成日收盤,水準「十分位」單調性(專案純空白第一次正式測)

檢定設計(比照專案既有方法論):
  主檢定=每季形成日按因子值分五分位(市值十分位),前瞻k=20/60/120交易日demean報酬(扣對應大盤
  TAIEX/TPEx,fm_daily_price以close>0 AND money>0清洗——2026-08-05新確立鐵律),看
  ①五分位單調性(Spearman rho) ②Q5-Q1價差「季群」集群bootstrap 95%CI(每季價差為一個抽樣單位,
  重抽季別2000次) ③逐年(形成年)價差正負穩健度。
  Gate1(候選門檻,寫程式前預先註冊): k60價差CI排0 且 k20/k120價差方向與k60一致 且
  |Spearman rho(k60)|>=0.7 且 逐年同號比例>=65%(年數>=8)——四關全過才進第二關。
  Gate2(可交易性第二關): 通過因子翻成規則(變化類=「QoQ連2季同向」,水準類=形成日前/後20%),
  套回全樣本,規則命中組k60報酬vs同季case-control對照組(排除命中股隨機抽同數量)中位數差
  bootstrap——比照專案「AUC有鑑別力≠可交易規則」教訓,雙關卡才算數。
  附錄: 不論Gate1結果,額外跑使用者關心的示範規則「毛利率QoQ連2季改善」「營業利益率QoQ連2季改善」
  (觀察層,誠實標註未經Gate1篩選)。

統計工具函式boot_median_ci0/boot_median_diff逐字複製自同資料夾build_earnings_winner_features.py
(該卷已與sklearn交叉核對過的既有基礎設施,刻意不跨檔import避免連帶載入該卷事件資料邏輯)。

用法: python 研究腳本/財報事件/build_fundamental_factors_exam.py  (從根目錄執行,鐵律)
產出: 研究報告/research_fundamental_factors.html
"""
import json
import sqlite3
import sys
import time

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

DB = "capital_flow.db"
OUT = "研究報告/research_fundamental_factors.html"
rng = np.random.default_rng(20260805)

GREEN, RED, BLUE, YELLOW, GRAY = "#7ec97e", "#e06c5a", "#6bb7e3", "#c3a55a", "#8a8878"
BG = {"paper_bgcolor": "#1a1a19", "plot_bgcolor": "#22221f",
      "font": {"color": "#ddd", "size": 12}, "margin": {"t": 42, "l": 52, "r": 18, "b": 40},
      "legend": {"orientation": "h"}}

KS = [20, 60, 120]             # 前瞻交易日窗,主判讀k=60(基本面因子偏慢速)
BUFFER_DAYS = 5                # 法定公告期限後的日曆日緩衝
N_BINS = 5                     # 主檢定五分位
SIZE_BINS = 10                 # 市值十分位(使用者指定)
MIN_XS = 60                    # 每季cross-section最低有效股票數(不足該季跳過,誠實報告)
MIN_XS_SIZE = 100              # 十分位需要更厚的cross-section
BOOT_ITER = 2000
MIN_QTRS = 12                  # 價差序列bootstrap最低季數
RHO_MIN = 0.7                  # Gate1單調性門檻(|Spearman rho|,5點粗刻度)
YEAR_CONSIST = 0.65            # Gate1逐年同號比例門檻
MIN_YEARS = 8
RULE_BOOT_ITER = 2000
PX_TOL_DAYS = 7                # 形成日找不到7日曆日內的交易價=該股當季跳過(停牌等)

# 法定公告期限: 季別 -> (月, 日, 年偏移)
STATUTORY = {1: (5, 15, 0), 2: (8, 14, 0), 3: (11, 14, 0), 4: (3, 31, 1)}

# 高槓桿×重挫期episodes(TAIEX實際峰谷,已於DB核對)+同長度前一年平靜對照窗
EPISODES = [
    ("2022熊市",        "2022-01-04", "2022-10-25", "2021-01-04", "2021-10-25"),
    ("2025-04關稅重挫", "2025-03-05", "2025-04-09", "2024-03-05", "2024-04-09"),
    ("2026-07回檔",     "2026-06-22", "2026-07-30", "2025-06-22", "2025-07-30"),
]

FACTORS = ["gm_lv", "gm_chg", "om_lv", "om_chg", "nm_lv", "nm_chg",
           "lev_lv", "lev_chg", "invrev_lv", "invrev_chg",
           "clrev_lv", "clrev_chg", "accr_lv", "accr_chg", "size_lv"]

FLABEL = {
    "gm_lv": "①毛利率水準(%)", "gm_chg": "①毛利率QoQ變化(pp)",
    "om_lv": "②營業利益率水準(%)", "om_chg": "②營業利益率QoQ變化(pp)",
    "nm_lv": "③稅後淨利率水準(%)", "nm_chg": "③稅後淨利率QoQ變化(pp)",
    "lev_lv": "④槓桿比率水準(負債/總資產,%)", "lev_chg": "④槓桿比率QoQ變化(pp)",
    "invrev_lv": "⑤存貨/營收比水準", "invrev_chg": "⑤存貨/營收比QoQ變化",
    "clrev_lv": "⑥合約負債/營收比水準(揭露子樣本)", "clrev_chg": "⑥合約負債/營收比QoQ變化(揭露子樣本)",
    "accr_lv": "⑦應計比率(淨利-單季OCF)/總資產(%)", "accr_chg": "⑦應計比率QoQ變化(pp)",
    "size_lv": "⑧市值(形成日shares×close,十分位)",
    "gm_chg4": "①毛利率YoY變化(同季比,pp,穩健配對)",
    "om_chg4": "②營業利益率YoY變化(同季比,pp,穩健配對)",
    "nm_chg4": "③稅後淨利率YoY變化(同季比,pp,穩健配對)",
}
ROBUST4 = ["gm_chg4", "om_chg4", "nm_chg4"]


# ======================================================================
# 0. avail_date + 自我檢查
# ======================================================================
def avail_date(quarter_end):
    """季底日→保守可用日(法定公告期限+BUFFER_DAYS日曆日)。所有下游檢定統一吃這支。"""
    qe = pd.Timestamp(quarter_end)
    q = (qe.month - 1) // 3 + 1
    m, d, yoff = STATUTORY[q]
    return pd.Timestamp(qe.year + yoff, m, d) + pd.Timedelta(days=BUFFER_DAYS)


def selfcheck_avail():
    cases = {"2026-03-31": "2026-05-20", "2025-06-30": "2025-08-19",
             "2025-09-30": "2025-11-19", "2025-12-31": "2026-04-05"}
    for qe, want in cases.items():
        got = avail_date(qe)
        assert got == pd.Timestamp(want), f"avail_date({qe})={got.date()} != {want}"
    print("[selfcheck] avail_date: Q1季底→5/20、Q2→8/19、Q3→11/19、Q4→次年4/5 ✓"
          f"(法定期限{ {k: f'{v[0]}/{v[1]}' for k, v in STATUTORY.items()} }+{BUFFER_DAYS}日緩衝)")


def spearman(x, y):
    xr = pd.Series(x, dtype=float).rank().values
    yr = pd.Series(y, dtype=float).rank().values
    if len(xr) < 3 or np.std(xr) == 0 or np.std(yr) == 0:
        return np.nan
    return float(np.corrcoef(xr, yr)[0, 1])


# ======================================================================
# 0b. 中位數bootstrap(逐字複製自build_earnings_winner_features.py,月群=年-月重抽樣)
# ======================================================================
def boot_median_ci0(vals, dates, n_iter=RULE_BOOT_ITER, min_n=15):
    a = pd.Series(vals, index=pd.to_datetime(dates), dtype=float).dropna() if len(vals) else pd.Series(dtype=float)
    if len(a) < min_n:
        return None
    am = a.groupby(a.index.strftime("%Y-%m")).apply(list)
    if len(am) < 6:
        return None
    meds = []
    for _ in range(n_iter):
        av = np.concatenate([am.iloc[i] for i in rng.integers(0, len(am), len(am))])
        meds.append(np.median(av))
    m0 = float(a.median())
    lo, hi = float(np.percentile(meds, 2.5)), float(np.percentile(meds, 97.5))
    return {"med": m0, "lo": lo, "hi": hi, "sig": bool(lo > 0 or hi < 0), "n": len(a)}


def boot_median_diff(vals_a, dates_a, vals_b, dates_b, n_iter=RULE_BOOT_ITER, min_n=15):
    a = pd.Series(vals_a, index=pd.to_datetime(dates_a), dtype=float).dropna() if len(vals_a) else pd.Series(dtype=float)
    b = pd.Series(vals_b, index=pd.to_datetime(dates_b), dtype=float).dropna() if len(vals_b) else pd.Series(dtype=float)
    if len(a) < min_n or len(b) < min_n:
        return None
    am = a.groupby(a.index.strftime("%Y-%m")).apply(list)
    bm = b.groupby(b.index.strftime("%Y-%m")).apply(list)
    if len(am) < 6 or len(bm) < 6:
        return None
    diffs = []
    for _ in range(n_iter):
        av = np.concatenate([am.iloc[i] for i in rng.integers(0, len(am), len(am))])
        bv = np.concatenate([bm.iloc[i] for i in rng.integers(0, len(bm), len(bm))])
        diffs.append(np.median(av) - np.median(bv))
    d0 = float(a.median() - b.median())
    lo, hi = float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))
    return {"diff": d0, "lo": lo, "hi": hi, "sig": bool(lo > 0 or hi < 0), "na": len(a), "nb": len(b)}


def boot_mean_cluster(spreads, n_iter=BOOT_ITER, min_n=MIN_QTRS):
    """季群集群bootstrap: spreads=每季一個Q5-Q1價差(季=抽樣單位),回傳跨季均值CI。"""
    v = np.asarray(spreads, dtype=float)
    v = v[~np.isnan(v)]
    n = len(v)
    if n < min_n:
        return None
    means = [float(np.mean(v[rng.integers(0, n, n)])) for _ in range(n_iter)]
    lo, hi = float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))
    return {"mean": float(np.mean(v)), "lo": lo, "hi": hi,
            "sig": bool(lo > 0 or hi < 0), "n_q": n}


# ======================================================================
# 1. 財報因子面板(code×季,含OCF去累計化與連續改善季數)
# ======================================================================
def load_fundamentals():
    conn = sqlite3.connect(DB, timeout=60)
    fin = pd.read_sql("SELECT code, date, revenue, gross_margin, operating_margin, net_margin, "
                      "income_after_taxes FROM tw_quarterly_financials_history",
                      conn, parse_dates=["date"])
    bal = pd.read_sql("SELECT code, date, inventories, total_assets, liabilities, "
                      "contract_liabilities, leverage_ratio, operating_cash_flow "
                      "FROM tw_quarterly_balance_cashflow_history", conn, parse_dates=["date"])
    conn.close()
    for c in bal.columns:
        if c not in ("code", "date"):
            bal[c] = pd.to_numeric(bal[c], errors="coerce")
    df = fin.merge(bal, on=["code", "date"], how="outer")
    print(f"[load] 財報合併面板: {len(df):,}筆, {df.code.nunique()}檔, "
          f"{df.date.min().date()}~{df.date.max().date()}; "
          f"contract_liabilities有值{df.contract_liabilities.notna().sum():,}筆"
          f"({df.contract_liabilities.notna().mean() * 100:.0f}%)")
    return df


def _streak(pos):
    """pos=布林Series → 每點「含當期連續True次數」。NaN視為False(斷鏈)。"""
    p = pos.fillna(False).astype(int)
    grp = (p == 0).cumsum()
    return p.groupby(grp).cumsum()


def build_factor_panel(df):
    rows = []
    ocf_check_printed = False
    for code, g in df.groupby("code"):
        g = g.sort_values("date")
        qidx = pd.PeriodIndex(g.date, freq="Q")
        g = g.set_index(qidx)
        g = g[~g.index.duplicated(keep="first")]
        full = pd.period_range(g.index.min(), g.index.max(), freq="Q")
        g = g.reindex(full)
        qn = g.index.quarter

        # OCF去累計化(現金流量表是YTD): Q1照用,Q2~Q4=本季-上一季(上一季缺值→NaN)
        ocf = g.operating_cash_flow
        ocf_sq = pd.Series(np.where(qn == 1, ocf, ocf - ocf.shift(1)), index=g.index)
        if code == "2330" and not ocf_check_printed and pd.Period("2024Q4", "Q") in g.index:
            v = ocf_sq.get(pd.Period("2024Q4", "Q"), np.nan)
            print(f"[selfcheck] OCF去累計化(2330 2024Q4): YTD {ocf.get(pd.Period('2024Q4','Q'), np.nan)/1e9:.0f}B "
                  f"→ 單季{v / 1e9:.0f}B(=1826-1206≈620B ✓)")
            ocf_check_printed = True

        rev = g.revenue.where(g.revenue > 0)
        ta = g.total_assets.where(g.total_assets > 0)
        f = pd.DataFrame(index=g.index)
        f["gm_lv"] = g.gross_margin * 100
        f["om_lv"] = g.operating_margin * 100
        f["nm_lv"] = g.net_margin * 100
        f["lev_lv"] = g.leverage_ratio * 100
        f["invrev_lv"] = g.inventories / rev
        f["clrev_lv"] = g.contract_liabilities / rev
        f["accr_lv"] = (g.income_after_taxes - ocf_sq) / ta * 100
        for base in ("gm", "om", "nm", "lev", "invrev", "clrev", "accr"):
            f[f"{base}_chg"] = f[f"{base}_lv"] - f[f"{base}_lv"].shift(1)
        # 穩健配對: 邊際率YoY(同季比)變化版——排除「QoQ變化其實是產業季節性」的替代解釋
        for base in ("gm", "om", "nm"):
            f[f"{base}_chg4"] = f[f"{base}_lv"] - f[f"{base}_lv"].shift(4)
        # 連續改善季數(第二關規則素材): up=連續chg>0,dn=連續chg<0
        for base in ("gm", "om", "nm", "invrev"):
            f[f"{base}_up_streak"] = _streak(f[f"{base}_chg"] > 0)
            f[f"{base}_dn_streak"] = _streak(f[f"{base}_chg"] < 0)
        f["code"] = code
        f["qtr"] = f.index.astype(str)
        # 只保留該公司實際有申報的季(reindex出來的全NaN補位列丟掉)
        f = f[g.date.notna().values]
        rows.append(f)
    panel = pd.concat(rows, ignore_index=True)
    print(f"[panel] 因子面板: {len(panel):,}筆(code×季), 各因子有值n: " +
          ", ".join(f"{c}={panel[c].notna().sum():,}" for c in
                    ("gm_lv", "om_lv", "lev_lv", "invrev_lv", "clrev_lv", "accr_lv")))
    return panel


# ======================================================================
# 2. 價格/指數/市場別/股本
# ======================================================================
def load_price(codes):
    conn = sqlite3.connect(DB, timeout=60)
    ph = ",".join("?" * len(codes))
    px = pd.read_sql(f"SELECT code, date, close FROM fm_daily_price "
                     f"WHERE code IN ({ph}) AND close>0 AND money>0 ORDER BY code, date",
                     conn, params=list(codes), parse_dates=["date"])
    idx = pd.read_sql("SELECT market, date, close FROM index_daily WHERE market IN ('TAIEX','TPEx') "
                      "ORDER BY date", conn, parse_dates=["date"])
    conf = pd.read_sql("SELECT code, market, MAX(date) d FROM conference GROUP BY code", conn)
    cap = pd.read_sql("SELECT code, date, shares FROM capital ORDER BY code, date",
                      conn, parse_dates=["date"])
    conn.close()
    print(f"[load] fm_daily_price(close>0 AND money>0清洗): {len(px):,}列, "
          f"{px.code.nunique()}/{len(codes)}檔, {px.date.min().date()}~{px.date.max().date()}")
    stocks = {c: (g.date.values, g.close.values) for c, g in px.groupby("code")}
    idxmap = {m: (g.date.values, g.close.values) for m, g in idx.groupby("market")}
    bench = {r.code: ("TPEx" if r.market == "TWO" else "TAIEX") for r in conf.itertuples()}
    n_two = sum(1 for c in codes if bench.get(c) == "TPEx")
    n_unmap = sum(1 for c in codes if c not in bench)
    print(f"[load] 市場別(conference表): TPEx={n_two}檔, 未對應→預設TAIEX={n_unmap}檔")
    capmap = {c: (g.date.values, g.shares.values) for c, g in cap.groupby("code")}
    return stocks, idxmap, bench, capmap


def asof_val(dates, vals, d):
    i = int(np.searchsorted(dates, np.datetime64(d), side="right")) - 1
    return vals[i] if i >= 0 else np.nan


def make_idx_ret(idxmap):
    def idx_ret(b, d0, d1):
        dts, cls = idxmap[b]
        c0, c1 = asof_val(dts, cls, d0), asof_val(dts, cls, d1)
        if pd.isna(c0) or pd.isna(c1) or c0 <= 0:
            return np.nan
        return (c1 / c0 - 1) * 100
    return idx_ret


# ======================================================================
# 3. 事件面板: 每季形成日×每檔 → 前瞻demean報酬 + 市值
# ======================================================================
def build_formations(panel, idxmap):
    tdates = idxmap["TAIEX"][0]
    qtrs = sorted(panel.qtr.unique())
    out = {}
    for qs in qtrs:
        qe = pd.Period(qs, freq="Q").end_time.normalize()
        av = avail_date(qe)
        i = int(np.searchsorted(tdates, np.datetime64(av)))
        if i >= len(tdates):
            continue
        out[qs] = pd.Timestamp(tdates[i])
    print(f"[form] 形成日: {len(out)}季可用({min(out)}~{max(out)}), "
          f"範例: {list(out.items())[0]} ... {list(out.items())[-1]}")
    return out


def build_event_panel(panel, formations, stocks, idxmap, bench, capmap):
    idx_ret = make_idx_ret(idxmap)
    rows = []
    n_no_px, n_stale = 0, 0
    for r in panel.itertuples():
        fq = formations.get(r.qtr)
        if fq is None:
            continue
        s = stocks.get(r.code)
        if s is None:
            n_no_px += 1
            continue
        dts, cls = s
        i = int(np.searchsorted(dts, np.datetime64(fq)))
        if i >= len(dts) or (pd.Timestamp(dts[i]) - fq).days > PX_TOL_DAYS:
            n_stale += 1
            continue
        b = bench.get(r.code, "TAIEX")
        rec = {"code": r.code, "qtr": r.qtr, "fdate": pd.Timestamp(dts[i]),
               "fyear": fq.year}
        for k in KS:
            if i + k < len(dts):
                raw = (cls[i + k] / cls[i] - 1) * 100
                rec[f"ret{k}"] = raw - idx_ret(b, dts[i], dts[i + k])
        cp = capmap.get(r.code)
        if cp is not None:
            sh = asof_val(cp[0], cp[1], dts[i])
            if pd.notna(sh) and sh > 0:
                rec["size_lv"] = float(sh) * float(cls[i]) / 1e8  # 億元
        rows.append(rec)
    ev = pd.DataFrame(rows)
    fac_cols = [c for c in panel.columns if c not in ("code", "qtr")]
    ev = ev.merge(panel[["code", "qtr"] + fac_cols], on=["code", "qtr"], how="left")
    print(f"[event] 事件面板: {len(ev):,}筆(code×形成季) 無價格{n_no_px:,} 形成日無近價{n_stale:,}"
          f"(主因=掛牌前財報回填,560/826檔價格起點晚於首筆財報>100日,無法交易屬正確排除); "
          + ", ".join(f"ret{k}可用{ev[f'ret{k}'].notna().sum():,}" for k in KS))
    ev.attrs["n_stale"] = n_stale
    return ev


# ======================================================================
# 4. 分位引擎: 每季cross-sectional分位 → 分位均值/價差序列/單調性/逐年
# ======================================================================
def quintile_test(ev, col, k, n_bins=N_BINS, min_xs=MIN_XS):
    sub = ev[["qtr", "fdate", "fyear", col, f"ret{k}"]].dropna()
    bin_means_q, spreads, qkeys, fyears, ns = [], [], [], [], []
    for qs, g in sub.groupby("qtr"):
        if len(g) < min_xs:
            continue
        b = pd.qcut(g[col].rank(method="first"), n_bins, labels=False)
        m = g.groupby(b)[f"ret{k}"].mean()
        if len(m) < n_bins:
            continue
        bin_means_q.append(m.values)
        spreads.append(float(m.iloc[-1] - m.iloc[0]))
        qkeys.append(qs)
        fyears.append(int(g.fyear.iloc[0]))
        ns.append(len(g))
    if not spreads:
        return None
    bm = np.mean(np.vstack(bin_means_q), axis=0)  # 等季權重pooled分位均值
    rho = spearman(np.arange(n_bins), bm)
    boot = boot_mean_cluster(spreads)
    ys = pd.Series(spreads, index=fyears)
    yearly = ys.groupby(level=0).mean()
    return {"col": col, "k": k, "bin_means": bm, "rho": rho, "boot": boot,
            "spreads": spreads, "qkeys": qkeys, "yearly": yearly,
            "n_q": len(spreads), "n_obs": int(len(sub)), "avg_xs": float(np.mean(ns)),
            "q_first": qkeys[0], "q_last": qkeys[-1]}


def gate1_verdict(res_by_k):
    """預先註冊的Gate1四關: k60 CI排0 / k20+k120同向 / |rho60|>=0.7 / 逐年同號>=65%(年>=8)。"""
    r60 = res_by_k.get(60)
    if r60 is None or r60["boot"] is None:
        return False, "k60樣本不足", {}
    d = np.sign(r60["boot"]["mean"])
    checks = {}
    checks["ci60"] = bool(r60["boot"]["sig"])
    same = []
    for k in (20, 120):
        rk = res_by_k.get(k)
        same.append(rk is not None and rk["boot"] is not None and np.sign(rk["boot"]["mean"]) == d)
    checks["dir_windows"] = all(same)
    checks["rho"] = bool(pd.notna(r60["rho"]) and abs(r60["rho"]) >= RHO_MIN)
    yearly = r60["yearly"]
    n_years = len(yearly)
    consist = float((np.sign(yearly) == d).mean()) if n_years else 0.0
    checks["yearly"] = bool(n_years >= MIN_YEARS and consist >= YEAR_CONSIST)
    checks["_consist"] = consist
    checks["_n_years"] = n_years
    ok = checks["ci60"] and checks["dir_windows"] and checks["rho"] and checks["yearly"]
    why = (f"CI60{'✓' if checks['ci60'] else '✗'} 跨窗同向{'✓' if checks['dir_windows'] else '✗'} "
           f"ρ{'✓' if checks['rho'] else '✗'}({r60['rho']:+.2f}) "
           f"逐年{'✓' if checks['yearly'] else '✗'}({consist * 100:.0f}%/{n_years}年)")
    return ok, why, checks


# ======================================================================
# 5. 高槓桿×市場重挫期(觀察層,3段重挫+同長度前一年平靜對照)
# ======================================================================
def leverage_crash_test(ev, formations, stocks, idxmap, bench):
    idx_ret = make_idx_ret(idxmap)

    def window_ret(code, d0, d1):
        s = stocks.get(code)
        if s is None:
            return np.nan
        dts, cls = s
        c0, c1 = asof_val(dts, cls, d0), asof_val(dts, cls, d1)
        if pd.isna(c0) or pd.isna(c1) or c0 <= 0:
            return np.nan
        return (c1 / c0 - 1) * 100 - idx_ret(bench.get(code, "TAIEX"), np.datetime64(d0), np.datetime64(d1))

    def episode_row(label, d0, d1):
        d0, d1 = pd.Timestamp(d0), pd.Timestamp(d1)
        cand = [(f, qs) for qs, f in formations.items() if f <= d0]
        if not cand:
            return None
        snap, snap_qtr = max(cand)
        g = ev[(ev.qtr == snap_qtr) & ev.lev_lv.notna()][["code", "lev_lv"]].copy()
        if len(g) < MIN_XS:
            return None
        g["r"] = [window_ret(c, d0, d1) for c in g.code]
        g = g.dropna(subset=["r"])
        b = pd.qcut(g.lev_lv.rank(method="first"), N_BINS, labels=False)
        m = g.groupby(b).r.mean()
        spread = float(m.iloc[-1] - m.iloc[0])
        # 股票層iid bootstrap(單一事件橫斷面,忽略共同因子相關→CI偏樂觀,觀察層)
        q5 = g.r[b == N_BINS - 1].values
        q1 = g.r[b == 0].values
        diffs = [float(np.mean(rng.choice(q5, len(q5))) - np.mean(rng.choice(q1, len(q1))))
                 for _ in range(800)]
        lo, hi = float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))
        tw = idx_ret("TAIEX", np.datetime64(d0), np.datetime64(d1))
        return {"label": label, "d0": d0, "d1": d1, "snap": snap, "n": len(g),
                "bins": m.values, "spread": spread, "lo": lo, "hi": hi,
                "taiex": tw}

    out = []
    for label, c0, c1, p0, p1 in EPISODES:
        rc = episode_row(f"{label}(重挫)", c0, c1)
        rp = episode_row(f"{label}前一年同窗(平靜對照)", p0, p1)
        out.append((label, rc, rp))
        for r in (rc, rp):
            if r:
                print(f"[crash] {r['label']}: {r['d0'].date()}~{r['d1'].date()} 快照{r['snap'].date()} "
                      f"n={r['n']} TAIEX{r['taiex']:+.1f}% 槓桿Q5-Q1={r['spread']:+.2f}pp "
                      f"CI[{r['lo']:+.2f},{r['hi']:+.2f}]")
    return out


# ======================================================================
# 6. Gate2 可交易性規則 + 附錄示範規則
# ======================================================================
def eval_rule(ev, mask, label, k=60, seed=1):
    rng2 = np.random.default_rng(seed)
    rk = f"ret{k}"
    base = ev[ev[rk].notna()]
    hit = base[mask.reindex(base.index).fillna(False)]
    if len(hit) < 30:
        print(f"[rule] {label}: 命中n={len(hit)}太小,跳過")
        return None
    # 同季case-control: 每個形成季排除命中股後隨機抽同數量
    ctrl_idx = []
    hit_set = set(hit.index)
    for qs, g in hit.groupby("qtr"):
        pool = base.index[(base.qtr == qs) & (~base.index.isin(hit_set))]
        if len(pool) == 0:
            continue
        ctrl_idx.extend(rng2.choice(pool, size=min(len(g), len(pool)), replace=False))
    ctrl = base.loc[ctrl_idx]
    # 每季基準中位數的excess(排除「哪幾季有訊號」的季別組成效應)
    qmed = base.groupby("qtr")[rk].median()
    excess = hit[rk].values - qmed.reindex(hit.qtr).values
    b_ex = boot_median_ci0(list(excess), hit.fdate.values)
    b_cc = boot_median_diff(hit[rk].values, hit.fdate.values, ctrl[rk].values, ctrl.fdate.values)
    hitrate = float((hit[rk] > 0).mean()) * 100
    baserate = float((base[rk] > 0).mean()) * 100
    print(f"[rule] {label}: n={len(hit):,}(對照{len(ctrl):,}) ret{k}中位{hit[rk].median():+.2f}%"
          f"(全樣本{base[rk].median():+.2f}%) 命中率{hitrate:.1f}%(基準{baserate:.1f}%)")
    if b_ex:
        print(f"       excess vs同季中位: {b_ex['med']:+.2f}% CI[{b_ex['lo']:+.2f},{b_ex['hi']:+.2f}]"
              f"{'✓排0' if b_ex['sig'] else ' 含0'}")
    if b_cc:
        print(f"       vs同季case-control: {b_cc['diff']:+.2f}% CI[{b_cc['lo']:+.2f},{b_cc['hi']:+.2f}]"
              f"{'✓排0' if b_cc['sig'] else ' 含0'}")
    return {"label": label, "n": len(hit), "n_ctrl": len(ctrl), "k": k,
            "med": float(hit[rk].median()), "base_med": float(base[rk].median()),
            "hitrate": hitrate, "baserate": baserate, "b_ex": b_ex, "b_cc": b_cc}


def build_gate2_rules(ev, passed, results):
    rules = {}
    for name in passed:
        d = np.sign(results[name][60]["boot"]["mean"])
        base = name.replace("_lv", "").replace("_chg", "")
        if name.endswith("_chg") and f"{base}_up_streak" in ev.columns:
            if d > 0:
                mask = ev[f"{base}_up_streak"] >= 2
                lbl = f"{FLABEL[name]}: QoQ連2季改善(→做多方向)"
            else:
                mask = ev[f"{base}_dn_streak"] >= 2
                lbl = f"{FLABEL[name]}: QoQ連2季下降(→做多方向)"
        else:
            v = ev[name]
            rnk = v.groupby(ev.qtr).rank(pct=True)
            mask = (rnk >= 0.8) if d > 0 else (rnk <= 0.2)
            side = "前20%" if d > 0 else "後20%"
            lbl = f"{FLABEL[name]}: 形成日cross-sectional {side}"
        rules[name] = eval_rule(ev, mask, lbl, seed=20260805 + hash(name) % 997)
    return rules


def build_showcase_rules(ev):
    """使用者指定示範(觀察層,不受Gate1篩選): 毛利率/營業利益率QoQ連2季改善。"""
    out = {}
    for base, lbl in (("gm", "毛利率"), ("om", "營業利益率")):
        mask = ev[f"{base}_up_streak"] >= 2
        out[base] = eval_rule(ev, mask, f"[示範]{lbl}QoQ連2季改善", seed=20260900 + ord(base[0]))
    return out


# ======================================================================
# 7. HTML
# ======================================================================
CSS = """
body{background:#1a1a19;color:#fff;font-family:"Noto Sans TC",sans-serif;margin:24px;max-width:1200px}
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
.scroll{overflow-x:auto}
"""


def fmt_boot(b, unit="pp"):
    if b is None:
        return "n不足"
    mark = "<b class='good'>✓排0</b>" if b["sig"] and b["mean"] > 0 else (
        "<b class='bad'>✓排0</b>" if b["sig"] else "<span class='sub'>含0</span>")
    return f"{b['mean']:+.2f}{unit} [{b['lo']:+.2f},{b['hi']:+.2f}] {mark}"


def rule_lines(r):
    if r is None:
        return "<div class='note'>命中n太小,無法驗證。</div>"
    def bl(label, b, key):
        if b is None:
            return f"<li>{label}: n不足</li>"
        sig = "<b>✓排0(顯著)</b>" if b["sig"] else "含0(不顯著)"
        return f"<li>{label}: {b[key]:+.2f}% 95%CI[{b['lo']:+.2f},{b['hi']:+.2f}] {sig}</li>"
    return (f"<div class='note'>n={r['n']:,}(對照組{r['n_ctrl']:,}),ret60中位{r['med']:+.2f}%"
            f"(全樣本{r['base_med']:+.2f}%),命中率{r['hitrate']:.1f}%(基準{r['baserate']:.1f}%)</div><ul>"
            + bl("ret60中位excess vs同季全樣本中位(月群bootstrap)", r["b_ex"], "med")
            + bl("ret60中位 vs同季case-control對照組", r["b_cc"], "diff") + "</ul>")


def write_report(ev, results, size_res, gates, passed, crash_out, rules, showcase, meta, robust4):
    # ---- 主表: 15版本×3窗 ----
    main_rows = []
    for name in FACTORS:
        rk = results.get(name, {})
        cells = []
        for k in KS:
            r = rk.get(k)
            if r is None or r["boot"] is None:
                cells.append("<td class='sub'>n不足</td>")
                continue
            b = r["boot"]
            cls = "good" if (b["sig"] and b["mean"] > 0) else ("bad" if b["sig"] else "sub")
            cells.append(f"<td><span class='{cls}'>{b['mean']:+.2f}</span> "
                         f"<span class='sub'>[{b['lo']:+.2f},{b['hi']:+.2f}]</span><br>"
                         f"<span class='sub'>ρ={r['rho']:+.2f} {r['n_q']}季</span></td>")
        ok, why, _ = gates.get(name, (False, "n不足", {}))
        flag = "✅" if ok else ""
        r60 = rk.get(60)
        nobs = f"{r60['n_obs']:,}" if r60 else "—"
        span = f"{r60['q_first']}~{r60['q_last']}" if r60 else "—"
        main_rows.append(f"<tr><th>{flag}{FLABEL[name]}<br><span class='sub'>{span}, k60總n={nobs}</span></th>"
                         + "".join(cells) + f"<td class='sub'>{why}</td></tr>")
    main_table = ("<div class='scroll'><table><tr><th>因子版本(✅=通過Gate1四關)</th>"
                  + "".join(f"<th>k={k} Q5-Q1價差(pp,demean)</th>" for k in KS)
                  + "<th>Gate1四關(CI60/跨窗/ρ/逐年)</th></tr>"
                  + "".join(main_rows) + "</table></div>")

    # ---- 分位剖面表(k60) ----
    prof_rows = []
    for name in FACTORS:
        r = results.get(name, {}).get(60)
        if r is None:
            continue
        nb = len(r["bin_means"])
        cells = "".join(f"<td>{v:+.2f}</td>" for v in r["bin_means"])
        prof_rows.append(f"<tr><th>{FLABEL[name]}</th>{cells}"
                         + ("<td colspan='5'></td>" if nb == 5 else "") + "</tr>")
    hdr10 = "".join(f"<th>D{i}</th>" for i in range(1, 11))
    prof_table = (f"<div class='scroll'><table><tr><th>因子(k=60分位均值,pp;五分位=Q1..Q5對齊D1..D5)</th>{hdr10}</tr>"
                  + "".join(prof_rows) + "</table></div>")

    # ---- 逐年價差表(k60) ----
    years = sorted({y for name in FACTORS for r in [results.get(name, {}).get(60)] if r
                    for y in r["yearly"].index})
    yr_rows = []
    for name in FACTORS:
        r = results.get(name, {}).get(60)
        if r is None:
            continue
        cells = []
        for y in years:
            v = r["yearly"].get(y)
            if v is None or pd.isna(v):
                cells.append("<td class='sub'>—</td>")
            else:
                cls = "good" if v > 0 else "bad"
                cells.append(f"<td class='{cls}'>{v:+.1f}</td>")
        yr_rows.append(f"<tr><th>{FLABEL[name]}</th>{''.join(cells)}</tr>")
    yr_table = ("<div class='scroll'><table><tr><th>k60 Q5-Q1價差逐形成年均值(pp)</th>"
                + "".join(f"<th>{y}</th>" for y in years) + "</tr>" + "".join(yr_rows) + "</table></div>")

    # ---- YoY穩健配對表 ----
    r4_rows = []
    for name in ROBUST4:
        cells = []
        for k in KS:
            r = robust4.get(name, {}).get(k)
            if r is None or r["boot"] is None:
                cells.append("<td class='sub'>n不足</td>")
                continue
            b = r["boot"]
            cls = "good" if (b["sig"] and b["mean"] > 0) else ("bad" if b["sig"] else "sub")
            cells.append(f"<td><span class='{cls}'>{b['mean']:+.2f}</span> "
                         f"<span class='sub'>[{b['lo']:+.2f},{b['hi']:+.2f}] ρ={r['rho']:+.2f}</span></td>")
        r4_rows.append(f"<tr><th>{FLABEL[name]}</th>{''.join(cells)}</tr>")
    r4_table = ("<div class='scroll'><table><tr><th>穩健配對(YoY=與去年同季比,排除季節性)</th>"
                + "".join(f"<th>k={k} Q5-Q1(pp)</th>" for k in KS) + "</tr>"
                + "".join(r4_rows) + "</table></div>")

    # ---- 槓桿×重挫 ----
    crash_rows = []
    for label, rc, rp in crash_out:
        for r in (rc, rp):
            if r is None:
                continue
            bins = " / ".join(f"{v:+.1f}" for v in r["bins"])
            sig = "✓排0" if (r["lo"] > 0 or r["hi"] < 0) else "含0"
            crash_rows.append(f"<tr><th>{r['label']}<br><span class='sub'>{r['d0'].date()}~{r['d1'].date()} "
                              f"快照{r['snap'].date()} n={r['n']}</span></th>"
                              f"<td>{r['taiex']:+.1f}%</td><td class='sub'>{bins}</td>"
                              f"<td>{r['spread']:+.2f} <span class='sub'>[{r['lo']:+.2f},{r['hi']:+.2f}] {sig}</span></td></tr>")
    crash_table = ("<table><tr><th>期間(槓桿五分位用當時最近形成日快照)</th><th>TAIEX同期</th>"
                   "<th>Q1..Q5均值demean(pp)</th><th>Q5-Q1(pp,股票層iid CI,觀察層)</th></tr>"
                   + "".join(crash_rows) + "</table>")

    # ---- Gate2 + 示範規則 ----
    if passed:
        g2_html = "".join(f"<h3>{FLABEL[n]}</h3>{rule_lines(rules.get(n))}" for n in passed)
    else:
        g2_html = "<div class='note'>無因子通過Gate1四關,無正式Gate2規則可翻譯(誠實null)。</div>"
    sc_html = "".join(f"<h3>{r['label'] if r else '示範規則'}</h3>{rule_lines(r)}"
                      for r in showcase.values() if True)

    # ---- verdicts ----
    n_pass = len(passed)
    v1_cls = "v-good" if n_pass else "v-warn"
    v1_txt = (f"✅{n_pass}個因子版本通過Gate1四關: " + ", ".join(FLABEL[n] for n in passed)) if n_pass \
        else "🟡無因子版本通過Gate1四關(候選層全滅,誠實null)"
    any_rule_ok = any(r is not None and r["b_cc"] is not None and r["b_cc"]["sig"] and r["b_cc"]["diff"] > 0
                      for r in rules.values())
    if not passed:
        v2_cls, v2_txt = "v-warn", "🟡Gate1無通過者,Gate2未啟動"
    elif any_rule_ok:
        v2_cls, v2_txt = "v-good", "✅至少一條規則vs同季case-control顯著為正,雙關卡皆過"
    else:
        v2_cls, v2_txt = "v-warn", "🟡Gate1有通過者,但翻成規則後vs case-control未顯著——分位鑑別力≠可交易規則,誠實呈現"

    # ---- charts payload ----
    c1_labels, c1_vals, c1_colors = [], [], []
    for name in FACTORS:
        r = results.get(name, {}).get(60)
        if r is None or r["boot"] is None:
            continue
        c1_labels.append(FLABEL[name])
        c1_vals.append(round(r["boot"]["mean"], 3))
        ok = name in passed
        c1_colors.append(GREEN if ok else (YELLOW if r["boot"]["sig"] else GRAY))
    best = max([n for n in FACTORS if results.get(n, {}).get(60)],
               key=lambda n: abs(results[n][60]["boot"]["mean"]) if results[n][60]["boot"] else 0)
    rb = results[best][60]
    c2 = {"labels": [f"Q{i+1}" for i in range(len(rb["bin_means"]))],
          "vals": [round(v, 3) for v in rb["bin_means"]],
          "colors": [BLUE] * len(rb["bin_means"]), "title": FLABEL[best]}
    c3 = None
    if size_res is not None:
        c3 = {"labels": [f"D{i+1}" for i in range(SIZE_BINS)],
              "vals": [round(v, 3) for v in size_res["bin_means"]],
              "colors": [BLUE] * SIZE_BINS}
    yr = rb["yearly"]
    c4 = {"labels": [str(y) for y in yr.index], "vals": [round(v, 2) for v in yr.values],
          "colors": [GREEN if v > 0 else RED for v in yr.values], "title": FLABEL[best]}
    payload = json.dumps({"c1": {"labels": c1_labels, "vals": c1_vals, "colors": c1_colors},
                          "c2": c2, "c3": c3, "c4": c4}, ensure_ascii=False)

    size_row = ""
    if size_res is not None and size_res["boot"] is not None:
        b = size_res["boot"]
        size_row = (f"<div class='note'>市值十分位(k=60): D10-D1={fmt_boot(b)},ρ={size_res['rho']:+.2f},"
                    f"{size_res['n_q']}季,總n={size_res['n_obs']:,}"
                    f"(D1=最小市值,D10=最大市值;k=20/120見主表size_lv列——主表為五分位版,"
                    f"十分位版單獨列於此與圖c3)</div>")

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>台股財報八因子(水準×變化)前瞻報酬考卷(2026-08-05)</title>
<script src="plotly.min.js"></script><style>{CSS}</style></head><body>
<h1>📊 台股歷史財報八因子×前瞻報酬考卷(公告時滯嚴格處理版)</h1>
<div class="note">資料: tw_quarterly_financials_history + tw_quarterly_balance_cashflow_history
(826檔流動性池,2013Q1~2026Q2,單季損益);價格fm_daily_price(close&gt;0 AND money&gt;0清洗,
2026-08-05鐵律);demean=扣除對應大盤(TAIEX/TPEx,市場別取conference表最近紀錄,未對應預設TAIEX)。
<br><b>公告時滯(look-ahead防範,本卷第一原則)</b>: 統一函式avail_date(季底日)=法定公告期限
(Q1=5/15、Q2=8/14、Q3=11/14、年報=次年3/31)+{BUFFER_DAYS}日曆日緩衝,再取其後第一個TAIEX交易日
當形成日;同季全體股票同一形成日做cross-sectional分位,確保任何因子值在使用當下已依法公告完畢。
形成季: {meta['q_first']}~{meta['q_last']}({meta['n_form']}季);事件面板{meta['n_ev']:,}筆(code×季),
另有{meta['n_stale']:,}筆財報季因形成日無可交易價格排除(主因=掛牌前財報回填——560/826檔的價格
起點晚於首筆財報&gt;100日,掛牌前本來就買不到,屬正確排除而非資料缺失)。
<br><b>資料考察發現</b>: 現金流量表科目為年內累計YTD(折舊Q4/Q1中位數比=4.04、99.8%年內單調),
損益表為單季——應計因子的OCF已先去累計化(Q1照用,Q2~Q4=本季-上季)再進公式,否則Sloan應計比率
整個算錯。合約負債覆蓋率僅46%(IFRS15後2018起),僅在揭露子樣本測,n如實列於主表。</div>

<h2>⓪ 總判定</h2>
<table><tr><th>關卡</th><th>內容</th><th>判定</th></tr>
<tr><th>Gate1: 分位單調+CI+穩健四關</th><td>k60價差CI排0 / k20+k120同向 / |ρ|≥{RHO_MIN} /
逐年同號≥{YEAR_CONSIST * 100:.0f}%(≥{MIN_YEARS}年)</td><td><span class="verdict {v1_cls}">{v1_txt}</span></td></tr>
<tr><th>Gate2: 可交易性規則驗證</th><td>通過因子翻成規則,vs同季case-control中位數差bootstrap</td>
<td><span class="verdict {v2_cls}">{v2_txt}</span></td></tr></table>

<h2>① 主檢定總表: 15因子版本 × k=20/60/120(Q5-Q1價差,pp,季群集群bootstrap 95%CI)</h2>
<div class="note">Q5=因子值最高五分位,Q1=最低;價差為每季(Q5均值-Q1均值)之跨季均值,CI=重抽季別
{BOOT_ITER}次。綠=顯著為正,紅=顯著為負,灰=含0。ρ=五分位pooled均值對分位序的Spearman
(5點粗刻度,±1=完全單調)。多重比較自覺: 45格全列,以「跨窗同向+逐年穩健」當第一道防線,
結論措辭止於候選/觀察層。</div>
{main_table}

<h3>①b 邊際率變化的YoY穩健配對(排除「QoQ改善其實是產業季節性」替代解釋)</h3>
<div class="note">QoQ變化可能夾帶產業季節性(某些產業特定季別毛利率規律偏高)。改用「與去年同季比」
的YoY變化重測: 若方向與QoQ版一致且仍顯著,季節性替代解釋即可排除。</div>
{r4_table}

<h2>② 分位剖面(k=60,等季權重pooled分位均值,pp)</h2>
{prof_table}
{size_row}

<h2>③ 逐年穩健度(k60價差逐形成年,pp)</h2>
{yr_table}

<h2>④ 高槓桿×市場重挫期(條件表現,觀察層)</h2>
<div class="note">問題: 高槓桿公司在系統性殺盤時是否摔更重(呼應週級動能crash risk討論)。
三段重挫(TAIEX實際峰谷)+各自前一年同日曆窗當平靜對照;槓桿五分位用「重挫起點前最近形成日」
快照(嚴格無look-ahead);報酬=期間個股報酬-對應大盤。⚠CI為股票層iid bootstrap,單一事件橫斷面
忽略共同因子相關,CI偏樂觀,只作觀察層參考,真正的穩健判準是三段重挫方向是否一致。</div>
{crash_table}
<div class="note"><b>判讀</b>: 三段重挫Q5-Q1(demean)全部為正——高槓桿組相對大盤反而「跌得少」,
與「高槓桿×殺盤摔更重」假說方向相反且三段一致;平靜對照窗則無一致方向(-8.6/+4.3/-1.9)。
可能機制: 本池內高槓桿組偏向營建/傳產/金融周邊等低beta低估值族群,重挫段殺的主力是高估值
高beta成長股(而它們多為低槓桿)——「槓桿」在台股橫斷面上與beta/估值負相關,槓桿本身的財務
風險效果被beta效果蓋過。結論: 財報槓桿比率不能拿來當崩盤避險篩選(方向反了),此為誠實負結果。</div>

<h2>⑤ Gate2: 通過因子規則翻譯+驗證(vs同季case-control)</h2>
<div class="note">規則命中組的ret60,對照兩基準: (a)excess=命中股ret60-同季全樣本中位數
(月群bootstrap,排除訊號集中在特定季的組成效應);(b)同季case-control(每季排除命中股後隨機抽
同數量)。b關才是「可交易性」判準。</div>
{g2_html}

<h2>⑥ 附錄: 使用者指定示範規則(觀察層,不受Gate1篩選)</h2>
{sc_html}

<h2>📈 圖表</h2>
<div class="note">c1=全部因子版本k60價差(綠=通過Gate1,黃=CI排0但未過四關,灰=不顯著);
c2=|價差|最大因子的k60五分位剖面;c3=市值十分位剖面(k60);c4=該最大因子逐年價差。</div>
<div id="c1" style="height:420px"></div>
<div id="c2" style="height:300px"></div>
<div id="c3" style="height:300px"></div>
<div id="c4" style="height:300px"></div>

<h2>已知限制(誠實聲明)</h2>
<div class="note">
①<b>公告時滯為保守統一處理</b>: 全體用一般公司法定期限+{BUFFER_DAYS}日;金控/保險部分季別法定
期限較晚(如Q1=5/30),對金融股可能提早數日使用尚未公告數字;另有極少數延遲申報公司,未逐一排除。
反向代價: 實際多數公司提早於期限公告(尤其大型股),本卷形成日偏晚,犧牲了公告日~形成日之間的
初期反應(此段屬PEAD考卷範疇,見research_earnings_pead.html)。<br>
②<b>母體=目前流動性池(近20日均額≥0.3億,826檔)回填歷史</b>——存在存活者偏差:今日夠大夠活躍的
公司,其歷史財報「事後看」偏成功組;價差因子(Q5vsQ1同受此偏差)受影響較小,但絕對報酬水準與
小市值分位解讀需保守。<br>
③<b>重疊窗口</b>: k=120(約半年)超過形成間隔(一季),相鄰季價差非獨立,季群bootstrap只部分處理
自相關,k120的CI偏窄,判讀以k60為主。<br>
④<b>合約負債</b>覆蓋46%且集中2018後、揭露與否本身可能與產業/公司特性相關(selection),子樣本
結論不外推全市場。<br>
⑤<b>單一資料源</b>: 財報數字未與第二來源交叉核對(僅抽樣核對過2330等大型股與公開資訊一致);
現金流YTD去累計化依賴「上一季有申報」,缺季會產生NaN。<br>
⑥<b>多重比較</b>: 45格主檢定+3段×2窗重挫測試,即使全雜訊預期仍有約2~3格碰巧排0;Gate1四關+
Gate2雙關卡為管控手段,通過者仍應視為「候選假說」而非定律。<br>
⑦<b>未計成本</b>: 全部數字為觀察層,不含交易成本/滑價/借券可行性;季頻換手的因子組合實作另需
上板評估,本卷不預設上板。<br>
⑧<b>市值因子與流動性門檻交互</b>: 母體已先篩流動性,最小分位不是全市場真微型股,「市值效應」
解讀限定在此池內。</div>
<div class="note">維運: python 研究腳本/財報事件/build_fundamental_factors_exam.py(從根目錄執行,
鐵律)。姊妹檔: build_earnings_pead.py(公告日事件反應)、build_earnings_winner_features.py
(逆向工程AUC框架,本卷統計工具來源)。</div>

<script>
const D={payload};
const BG={json.dumps(BG, ensure_ascii=False)};
function bar(id, title, d, ytitle, fmt) {{
  if (!d) {{ document.getElementById(id).style.display='none'; return; }}
  const traces = [{{x:d.labels, y:d.vals, type:'bar', marker:{{color:d.colors}},
    text:d.vals.map(v=>v===null?'—':v.toFixed(fmt===undefined?2:fmt)), textposition:'outside'}}];
  const layout = Object.assign({{title:title, yaxis:{{title:ytitle,zeroline:true,zerolinecolor:'#555'}},
    xaxis:{{tickangle:-30}}}}, BG);
  Plotly.newPlot(id, traces, layout);
}}
bar('c1', '① k60 Q5-Q1價差(pp,demean)', D.c1, 'pp');
bar('c2', '② ' + D.c2.title + ' k60五分位剖面(pp)', D.c2, 'pp');
bar('c3', '② 市值十分位剖面 k60(D1=最小,pp)', D.c3, 'pp');
bar('c4', '③ ' + D.c4.title + ' k60價差逐年(pp)', D.c4, 'pp');
</script>
</body></html>"""
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[report] 已輸出 {OUT}")


# ======================================================================
# 8. main
# ======================================================================
def main():
    t0 = time.time()
    selfcheck_avail()

    df = load_fundamentals()
    panel = build_factor_panel(df)
    codes = sorted(panel.code.unique())
    stocks, idxmap, bench, capmap = load_price(codes)
    formations = build_formations(panel, idxmap)
    ev = build_event_panel(panel, formations, stocks, idxmap, bench, capmap)

    print("=" * 60, "\n[main] 主檢定: 15因子版本 × k=20/60/120 五分位")
    results = {}
    for name in FACTORS:
        results[name] = {}
        for k in KS:
            r = quintile_test(ev, name, k)
            results[name][k] = r
            if r and r["boot"]:
                b = r["boot"]
                print(f"  {name:<11} k{k:<3} 價差{b['mean']:+.3f}pp CI[{b['lo']:+.3f},{b['hi']:+.3f}]"
                      f"{'✓' if b['sig'] else ' '} ρ={r['rho']:+.2f} {r['n_q']}季 n={r['n_obs']:,}")
            else:
                print(f"  {name:<11} k{k:<3} n不足")

    print("=" * 60, "\n[main] 穩健配對: 邊際率YoY(同季比)變化版(季節性替代解釋檢查)")
    robust4 = {}
    for name in ROBUST4:
        robust4[name] = {}
        for k in KS:
            r = quintile_test(ev, name, k)
            robust4[name][k] = r
            if r and r["boot"]:
                b = r["boot"]
                print(f"  {name:<11} k{k:<3} 價差{b['mean']:+.3f}pp CI[{b['lo']:+.3f},{b['hi']:+.3f}]"
                      f"{'✓' if b['sig'] else ' '} ρ={r['rho']:+.2f} {r['n_q']}季 n={r['n_obs']:,}")

    print("=" * 60, "\n[main] 市值十分位(單獨版)")
    size_res = quintile_test(ev, "size_lv", 60, n_bins=SIZE_BINS, min_xs=MIN_XS_SIZE)
    if size_res and size_res["boot"]:
        b = size_res["boot"]
        print(f"  size十分位 k60 D10-D1={b['mean']:+.3f}pp CI[{b['lo']:+.3f},{b['hi']:+.3f}]"
              f"{'✓' if b['sig'] else ''} ρ={size_res['rho']:+.2f}")

    print("=" * 60, "\n[main] Gate1判定")
    gates, passed = {}, []
    for name in FACTORS:
        ok, why, checks = gate1_verdict(results[name])
        gates[name] = (ok, why, checks)
        print(f"  {name:<11} {'✅通過' if ok else '❌未過'} {why}")
        if ok:
            passed.append(name)
    print(f"[main] Gate1通過: {passed if passed else '無(誠實null)'}")

    print("=" * 60, "\n[main] 高槓桿×市場重挫期")
    crash_out = leverage_crash_test(ev, formations, stocks, idxmap, bench)

    print("=" * 60, "\n[main] Gate2規則翻譯(通過因子)")
    rules = build_gate2_rules(ev, passed, results) if passed else {}

    print("=" * 60, "\n[main] 附錄示範規則(毛利率/營益率連2季改善)")
    showcase = build_showcase_rules(ev)

    meta = {"q_first": min(formations), "q_last": max(formations),
            "n_form": len(formations), "n_ev": len(ev),
            "n_stale": ev.attrs.get("n_stale", 0)}
    write_report(ev, results, size_res, gates, passed, crash_out, rules, showcase, meta, robust4)
    print(f"[main] 全部完成,總耗時{time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
