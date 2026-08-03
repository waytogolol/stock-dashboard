# -*- coding: utf-8 -*-
"""財報公告後噴出贏家逆向工程特徵×case-control考卷(2026-08-03,使用者指定逆向工程設計)。

背景/動機: 前一版build_earnings_preannounce_reaction.py測「公告前普遍有沒有反應」,結果是null/弱負
(全樣本互相抵銷——多空事件混在一起平均,訊號被自己人抵銷掉)。使用者看完後提出更對的框架(比照本批
姊妹考卷build_dtlend_winner_features.py的逆向工程既有方法論,直接抄同一套做法,不重新設計):
不能全部一起做,應該反過來——先定義財報公告「後」真的噴出的贏家(結果),回頭看這些贏家公告「前」
有什麼共同特徵(逆向工程),每個特徵都配case-control對照組算AUC,不是看到贏家長怎樣就下結論。

資料(2026-08-01已擴大備妥): capital_flow.db.tw_board_earnings_dates,3,847列原始列數,但僅
actual_date非空的3,097筆可用(不確定/未公告的排除),296檔,2019-02-15~2026-08-01。欄位
code/market/period/pre_date/actual_date/lead_days;lead_days/period離奇標籤的處理方式沿用
build_earnings_preannounce_reaction.py既有結論(lead_days只影響附錄式pre_date統計,本卷完全
不用pre_date,不受影響;period文字標籤離奇不影響actual_date本身的可用性)。另有4列(code,actual_date)
重複(同一天公告涵蓋兩種period標籤,如annual+Q4同天),drop_duplicates後3,093筆。

⚠population與姊妹卷build_theme_member_selection.py不同,不能直接套用該卷null結論: 那份僅限
「題材月營收動能訊號觸發」子集(score=4,約115個題材-月事件/828筆成員-事件,2022-2026),本卷是
全部財報公告事件(不限定題材月營收動能有沒有觸發),樣本大7倍以上、時間跨度長3倍(涵蓋2020疫情崩盤/
2022熊市/近期多頭),故重新測,但特徵定義算法(TDCC大戶趨勢d4w_1000規約/外資位階canonical算法/
成交值熱度百分位/漲停次數)逐字複用該卷或build_earnings_preannounce_reaction.py既有寫法,不重新設計。

任務設計:
①贏家/輸家定義(逆向工程起點): 用fm_daily_price算每筆事件actual_date「後」k=5/10/20交易日累積報酬
  (demean扣對應大盤TAIEX/TPEx),主判讀=k20(中期噴出),win10=car20排名前10%,win20=前20%(穩健
  對照,比照build_dtlend_winner_features.py的win10/win5設計,這裡因樣本量較小改用前20%當寬鬆版),
  lose10=後10%(對稱性檢定)。另建win10_k5/win10_k10(用k=5/10窗口重新定義贏家)供「贏家定義本身」
  的跨窗口穩健性複驗,比照該卷regime_breakdown的精神(只是這裡複驗的是「窗口長度」而非「regime」)。
②六個特徵角度(每個都有(主版本,穩健配對版本)兩支,配對版本邏輯比照build_dtlend_winner_features.py
  的ROBUST_PAIRS機制):
  1.大戶持股比例趨勢(tdcc_weekly.p1000,4週變化vs8週變化,d4w_1000規約逐字複用
    build_theme_member_selection.py: cutoff=actual_date-3日曆日,距cutoff>21天視為過期)
  2.外資+投信合計買賣超(inst_flow,20日累計位階百分位[canonical S4算法逐字複用] vs 20日淨買超天數
    佔比[同一構念的替代操作化,見設計理由])
  3.股價動能(公告前20日/60日累積報酬,前一支考卷已在「題材觸發」子集上測過不顯著,這次在全樣本重測)
  4.成交值熱度百分位(公告前20日均額相對自身240日/120日歷史百分位,算法逐字複用
    build_earnings_preannounce_reaction.py的heat_pctl寫法)
  5.短期漲停次數(公告前20日/60日內觸及漲停次數,寬鬆門檻收盤漲幅>=9.5%,逐字複用
    build_theme_member_selection.py compute_limitup_features的判定邏輯,但改用連續計數而非
    二元切法——AUC框架可直接吃連續變數,不需要像該卷tertile切法那樣硬分組)
  6.個股營收動能(own_yoy3/own_yoy6,近3/6個月YoY均值,逐字比照theme卷own_yoy3定義但period_last
    改用「actual_date往前45日曆日」的安全緩衝——月營收依法10日內公告,45天緩衝遠超此要求,確保
    這是公告前已公開資訊,不是用了未公告的月營收去「預測」財報)
  所有特徵一律取「嚴格早於actual_date」的最近快照/窗口(momentum/heat/limitup用announcement前一
  交易日i-1當基準點,不含公告當日本身,避免公告日價格反應本身混進特徵——這點是本卷與
  build_dtlend_winner_features.py第一階段「同日型態」特徵最大的方法論差異: 那份第一階段本來就是
  contemporaneous驗證,本卷因為要做「開盤前逆向工程規則」,設計上直接全部特徵都用pre-event資訊,
  不再區分兩階段)。
③方法論(逐字比照build_dtlend_winner_features.py既有標準):
  - AUC=rank-sum法(Mann-Whitney U等價式),對每個(特徵版本,win10/win20/lose10)算case同批
    (case-control用「actual_date所在年-月」當批次單位,取代dtlend卷「同日」的批次概念——因為財報
    公告事件本身比當沖交易日稀疏很多,同月批次仍有充足密度(3千餘事件/約90個月≈平均每月40+筆)
    做隨機抽樣,此為刻意的方法論調整而非疏漏,詳見已知限制)。
  - 通過門檻: win10點估計|AUC-0.5|>=0.08且月群bootstrap 95%CI排除0.5;且win20同向且|dev|>=0.05;
    且(若有定義配對)配對版本(4週/8週、20日/60日、240日/120日、canonical/天數比例)同向且
    |dev|>=0.05——三者皆一致才算通過穩健度門檻,不是單一版本達標就照單全收。lose10僅報告對稱性,
    不納入通過判定。
  - 通過AUC篩選的特徵,追加三問機制討論;嘗試翻譯成開盤前(公告前)規則,驗證規則篩出的股票公告後
    k20報酬是否對baseline/case-control顯著更好(bootstrap,而非只在贏家組裡自我循環驗證)。
④誠實面對可能的null結果: 若多數/全部特徵不顯著,誠實報告(不放寬篩選標準/不多測角度硬湊);若
  population變大後真的浮現顯著性(題材觸發子集樣本太小測不出來),也如實報告。

工程教訓(已讀過姊妹卷踩過的坑,本卷刻意避開): AUC類bootstrap統一回傳key="auc"(不與median/mean
diff類bootstrap的"diff"/"med"混淆,呈現分開走auc_line()與boot_line());pp/百分比數字一律確認
量級(0-1比例乘100才是pp顯示尺度,見hit_rate/posday相關计算的×100註記);判讀文字一律依bootstrap
實際正負號動態生成(verdict_feature()/rule判讀皆用if/elif,不寫死方向)。

用法: python 研究腳本/財報事件/build_earnings_winner_features.py  (從根目錄執行,鐵律)
產出: 研究報告/research_earnings_winner_features.html
"""
import json
import sqlite3
import sys
import time

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

sys.stdout.reconfigure(encoding="utf-8")

DB = "capital_flow.db"
OUT = "研究報告/research_earnings_winner_features.html"
rng = np.random.default_rng(20260803)

GREEN, RED, BLUE, YELLOW, GRAY = "#7ec97e", "#e06c5a", "#6bb7e3", "#c3a55a", "#8a8878"
BG = {"paper_bgcolor": "#1a1a19", "plot_bgcolor": "#22221f",
      "font": {"color": "#ddd", "size": 12}, "margin": {"t": 42, "l": 52, "r": 18, "b": 40},
      "legend": {"orientation": "h"}}

KS = [5, 10, 20]              # 公告後累積報酬窗口(demean),主判讀k=20
AUC_PRESCREEN = 0.03           # 點估計偏離超過此值才值得花算力做bootstrap CI
AUC_PASS_DEV = 0.08            # 最終判定門檻(比照build_dtlend_winner_features.py既有先例)
ROBUST_DEV = 0.05              # win20/定義配對版的較寬鬆穩健度門檻(同上先例)
N_ITER_AUC = 600
MIN_POOL = 30                  # bootstrap最低樣本門檻
TDCC_LAG_DAYS = 3              # 大戶特徵cutoff=actual_date-3日曆日(逐字複用theme卷規約)
TDCC_STALE_DAYS = 21
INST_LAG_DAYS = 1              # 外資/投信特徵cutoff=actual_date-1日曆日(日頻資料,隔夜前即可取得)
INST_STALE_DAYS = 10
LIMITUP_THRESH = 9.5           # 寬鬆漲停判定門檻(%),留誤差空間給10.00%理論值捨入
LIMITUP_MIN20, LIMITUP_MIN60 = 15, 45
REV_BUFFER_DAYS = 45           # 月營收特徵安全緩衝(法定10日公告期遠小於此,確保公告前已公開)
RULE_BOOT_ITER = 2000


# ======================================================================
# 0. 自我檢查: 手算AUC(Mann-Whitney U等價式) vs sklearn.roc_auc_score
#    (calc_auc/boot_auc_ci/auc_line三支函式逐字複製自build_dtlend_winner_features.py,
#     刻意不用跨資料夾import——那份考卷的模組會連帶匯入當沖借券域的DB讀取邏輯,與本卷財報事件
#     資料無關,直接複製這幾支純統計工具函式比import整個模組更乾淨,且已核對過完全一致)
# ======================================================================
def calc_auc(a_vals, b_vals):
    """a=case(label1)/b=control(label0),回傳AUC點估計(rank-sum法,非case平均百分位粗略版)。"""
    n1, n2 = len(a_vals), len(b_vals)
    if n1 == 0 or n2 == 0:
        return np.nan
    combined = np.concatenate([np.asarray(a_vals, dtype=float), np.asarray(b_vals, dtype=float)])
    ranks = pd.Series(combined).rank(method="average").values
    r1 = ranks[:n1].sum()
    return float((r1 - n1 * (n1 + 1) / 2) / (n1 * n2))


def selfcheck_auc():
    rc = np.random.default_rng(0)
    a = rc.normal(0.35, 1, 800)
    b = rc.normal(0.0, 1, 800)
    manual = calc_auc(a, b)
    ref = roc_auc_score(np.r_[np.ones(800), np.zeros(800)], np.r_[a, b])
    ok = abs(manual - ref) < 1e-9
    print(f"[selfcheck] 手算AUC(rank-sum)={manual:.6f} vs sklearn.roc_auc_score={ref:.6f} "
          f"差={abs(manual - ref):.2e} {'✓一致' if ok else '⚠不一致,停止執行請檢查calc_auc()'}")
    assert ok, "calc_auc()與sklearn.roc_auc_score不一致,停止執行"


def boot_auc_ci(vals_a, dates_a, vals_b, dates_b, n_iter=N_ITER_AUC, min_n=MIN_POOL):
    """AUC月群bootstrap(月群=實際日期的年-月,重抽樣單位),回傳key固定"auc",呈現一律走auc_line()。"""
    a = pd.Series(vals_a, index=pd.to_datetime(dates_a), dtype=float).dropna() if len(vals_a) else pd.Series(dtype=float)
    b = pd.Series(vals_b, index=pd.to_datetime(dates_b), dtype=float).dropna() if len(vals_b) else pd.Series(dtype=float)
    if len(a) < min_n or len(b) < min_n:
        return None
    am = a.groupby(a.index.strftime("%Y-%m")).apply(list)
    bm = b.groupby(b.index.strftime("%Y-%m")).apply(list)
    months = sorted(set(am.index) | set(bm.index))
    am = am.reindex(months)
    bm = bm.reindex(months)
    n = len(months)
    if n < 6:
        return None
    aucs = []
    for _ in range(n_iter):
        idx = rng.integers(0, n, n)
        av_parts = [am.iloc[i] for i in idx if isinstance(am.iloc[i], list)]
        bv_parts = [bm.iloc[i] for i in idx if isinstance(bm.iloc[i], list)]
        av = np.concatenate(av_parts) if av_parts else np.array([])
        bv = np.concatenate(bv_parts) if bv_parts else np.array([])
        if len(av) < 5 or len(bv) < 5:
            continue
        aucs.append(calc_auc(av, bv))
    if len(aucs) < n_iter * 0.5:
        return None
    auc0 = calc_auc(a.values, b.values)
    lo, hi = float(np.percentile(aucs, 2.5)), float(np.percentile(aucs, 97.5))
    return {"auc": auc0, "lo": lo, "hi": hi, "sig": bool(lo > 0.5 or hi < 0.5),
            "na": len(a), "nb": len(b), "n_boot": len(aucs)}


def auc_line(label, r):
    if r is None:
        return f"<li>{label}: n太小或分群不足,觀察層(未達bootstrap最低樣本門檻n>={MIN_POOL})</li>"
    sig = "<b>✓排0(顯著偏離0.5)</b>" if r["sig"] else "含0.5(不顯著)"
    passed = " <b>且達0.58/0.42門檻</b>" if abs(r["auc"] - 0.5) >= AUC_PASS_DEV and r["sig"] else ""
    return f"<li>{label}: AUC={r['auc']:.3f} 95%CI[{r['lo']:.3f},{r['hi']:.3f}] {sig}{passed}</li>"


# ======================================================================
# 0b. 中位數/均值月群bootstrap(第二階段規則驗證用,獨立回傳key,不與AUC類混用)
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


def boot_line2(label, r, key, unit="pp"):
    if r is None:
        return f"<li>{label}: n太小或分群不足,觀察層(未達bootstrap最低樣本門檻)</li>"
    sig = "<b>✓排0(顯著)</b>" if r["sig"] else "含0(不顯著)"
    return f"<li>{label}: {r[key]:+.2f}{unit} 95%CI[{r['lo']:+.2f},{r['hi']:+.2f}] {sig}</li>"


# ======================================================================
# 1. 事件/價格/指數載入
# ======================================================================
def load_events():
    conn = sqlite3.connect(DB, timeout=60)
    ev_all = pd.read_sql("SELECT code, market, period, pre_date, actual_date, lead_days "
                         "FROM tw_board_earnings_dates", conn, parse_dates=["pre_date", "actual_date"])
    ev = pd.read_sql("SELECT code, market, period, pre_date, actual_date, lead_days "
                     "FROM tw_board_earnings_dates WHERE actual_date IS NOT NULL",
                     conn, parse_dates=["pre_date", "actual_date"])
    conn.close()
    n0 = len(ev)
    ev = ev.drop_duplicates(subset=["code", "actual_date"], keep="first").reset_index(drop=True)
    print(f"[load] tw_board_earnings_dates全表{len(ev_all):,}列(含未公告/僅pre_date排定者); "
          f"actual_date非空{n0:,}筆 → 去重(code,actual_date)後{len(ev):,}筆"
          f"(移除{n0 - len(ev)}筆同日重複標籤,如annual+單季同天公告)")
    print(f"[load] {ev.actual_date.min().date()}~{ev.actual_date.max().date()}, "
          f"{ev.code.nunique()}檔, market分布={dict(ev.market.value_counts())}")
    ev.attrs["n_raw"] = len(ev_all)
    ev.attrs["n_notnull"] = n0
    return ev


def load_price_index(codes):
    conn = sqlite3.connect(DB, timeout=60)
    ph = ",".join("?" * len(codes))
    px = pd.read_sql(f"SELECT code, date, open, high, low, close, volume, money FROM fm_daily_price "
                     f"WHERE code IN ({ph}) AND close>0", conn, params=codes, parse_dates=["date"])
    idx = pd.read_sql("SELECT market, date, close FROM index_daily WHERE market IN ('TAIEX','TPEx') "
                      "ORDER BY date", conn, parse_dates=["date"])
    conn.close()
    print(f"[load] fm_daily_price: {len(px):,}列, {px.code.nunique()}/{len(codes)}檔有資料, "
          f"{px.date.min().date()}~{px.date.max().date()}")
    return px, idx


# ======================================================================
# 2. 逐股price-based面板(動能/熱度/漲停,手法比照build_earnings_preannounce_reaction.py的
#    stocks字典+searchsorted定位,同一批姊妹卷已驗證過的既有寫法)
# ======================================================================
def build_stock_panels(px):
    stocks = {}
    for code, g in px.groupby("code"):
        g = g.sort_values("date").reset_index(drop=True)
        g["ret1"] = g.close.pct_change() * 100
        g["m20"] = g.money.rolling(20, min_periods=15).mean()
        g["heat240"] = g.m20.rolling(240, min_periods=120).rank(pct=True) * 100
        g["heat120"] = g.m20.rolling(120, min_periods=60).rank(pct=True) * 100
        g["loose"] = g.ret1 >= LIMITUP_THRESH
        g["limitup20"] = g.loose.rolling(20, min_periods=LIMITUP_MIN20).sum()
        g["limitup60"] = g.loose.rolling(60, min_periods=LIMITUP_MIN60).sum()
        stocks[code] = g
    return stocks


def make_idx_ret(idx):
    idx_map = {m: g.set_index("date").close for m, g in idx.groupby("market")}

    def idx_ret(bench, d0, d1):
        s = idx_map.get(bench)
        if s is None:
            return np.nan
        try:
            c0, c1 = s.asof(d0), s.asof(d1)
            if pd.isna(c0) or pd.isna(c1) or c0 <= 0:
                return np.nan
            return (c1 / c0 - 1) * 100
        except Exception:
            return np.nan
    return idx_ret


BENCH_OF = {"sii": "TAIEX", "otc": "TPEx"}


def compute_event_panel(ev, stocks, idx_ret):
    """逐事件: 定位actual_date在該股價格序列的位置i,算公告後car5/10/20(demean),
    以及公告前(嚴格用i-1當基準點,不含公告當日本身)的動能/熱度/漲停次數。"""
    rows = []
    n_no_price, n_no_match = 0, 0
    for r in ev.itertuples():
        g = stocks.get(r.code)
        if g is None:
            n_no_price += 1
            continue
        dts = g.date.values
        i = int(np.searchsorted(dts, np.datetime64(r.actual_date)))
        if i >= len(dts) or dts[i] != np.datetime64(r.actual_date):
            n_no_match += 1
            continue
        c = g.close.values
        bench = BENCH_OF.get(r.market, "TAIEX")
        rec = {"orig_idx": r.Index, "code": r.code, "market": r.market, "period": r.period,
               "actual_date": r.actual_date}
        for k in KS:
            if i + k < len(dts) and c[i] > 0 and c[i + k] > 0:
                raw = (c[i + k] / c[i] - 1) * 100
                rec[f"car{k}"] = raw - idx_ret(bench, g.date.iloc[i], g.date.iloc[i + k])
        if i >= 1:
            im1 = i - 1
            rec["mom20"] = (c[im1] / c[im1 - 20] - 1) * 100 if im1 >= 20 and c[im1 - 20] > 0 else np.nan
            rec["mom60"] = (c[im1] / c[im1 - 60] - 1) * 100 if im1 >= 60 and c[im1 - 60] > 0 else np.nan
            rec["heat240"] = float(g.heat240.iloc[im1]) if pd.notna(g.heat240.iloc[im1]) else np.nan
            rec["heat120"] = float(g.heat120.iloc[im1]) if pd.notna(g.heat120.iloc[im1]) else np.nan
            rec["limitup20"] = float(g.limitup20.iloc[im1]) if pd.notna(g.limitup20.iloc[im1]) else np.nan
            rec["limitup60"] = float(g.limitup60.iloc[im1]) if pd.notna(g.limitup60.iloc[im1]) else np.nan
        rows.append(rec)
    df = pd.DataFrame(rows).set_index("orig_idx")
    print(f"[panel] 事件{len(ev):,}筆 → 價格序列存在且定位成功{len(df):,}筆 "
          f"(無價格資料{n_no_price}筆, actual_date非交易日或找不到{n_no_match}筆)")
    for k in KS:
        print(f"  car{k}(demean)可用n={df[f'car{k}'].notna().sum():,}")
    return df


# ======================================================================
# 3. 額外特徵: TDCC大戶趨勢(逐字複用theme卷d4w_1000規約) + 外資/投信合計買賣超 + 個股營收動能
# ======================================================================
def compute_tdcc_feature(ev):
    conn = sqlite3.connect(DB, timeout=60)
    tw = pd.read_sql("SELECT date, code, p1000 FROM tdcc_weekly", conn, parse_dates=["date"])
    conn.close()
    wide = tw.pivot_table(index="date", columns="code", values="p1000").sort_index()
    d4w = (wide - wide.shift(4)).stack().rename_axis(["date", "code"]).reset_index(name="d4w").sort_values("date")
    d8w = (wide - wide.shift(8)).stack().rename_axis(["date", "code"]).reset_index(name="d8w").sort_values("date")

    evx = pd.DataFrame({"code": ev["code"].values,
                        "cutoff": ev["actual_date"].values - pd.Timedelta(days=TDCC_LAG_DAYS),
                        "orig_idx": ev.index}).sort_values("cutoff").reset_index(drop=True)
    m4 = pd.merge_asof(evx, d4w, left_on="cutoff", right_on="date", by="code",
                       direction="backward", tolerance=pd.Timedelta(days=TDCC_STALE_DAYS))
    m8 = pd.merge_asof(evx, d8w, left_on="cutoff", right_on="date", by="code",
                       direction="backward", tolerance=pd.Timedelta(days=TDCC_STALE_DAYS))
    m4 = m4.set_index("orig_idx").reindex(ev.index)
    m8 = m8.set_index("orig_idx").reindex(ev.index)
    out = pd.DataFrame({"tdcc_d4w": m4["d4w"], "tdcc_d8w": m8["d8w"]}, index=ev.index)
    print(f"[feature] TDCC大戶趨勢: d4w可用{out.tdcc_d4w.notna().sum():,} d8w可用{out.tdcc_d8w.notna().sum():,}")
    return out


def compute_inst_flow_feature(ev):
    """外資+投信合計淨買超: 主版本=canonical位階百分位(逐字複用theme卷S4算法,
    rolling(20,min10).sum→rolling(240,min120).rank(pct=True)*100); 穩健配對版本=同一構念的
    替代操作化(20日淨買超天數佔比,不依賴240日暖機,對inst_flow僅2022起的短歷史更友善)。"""
    conn = sqlite3.connect(DB, timeout=60)
    fl = pd.read_sql("SELECT date, code, foreign_net, trust_net FROM inst_flow", conn, parse_dates=["date"])
    conn.close()
    fl["combo"] = fl.foreign_net + fl.trust_net
    wide = fl.pivot_table(index="date", columns="code", values="combo").sort_index()
    roll20 = wide.rolling(20, min_periods=10).sum()
    pct240 = (roll20.rolling(240, min_periods=120).rank(pct=True) * 100)
    valid = wide.notna()
    posday20 = ((wide > 0) & valid).rolling(20, min_periods=15).sum() / valid.rolling(20, min_periods=15).sum() * 100

    long_pct = pct240.stack().rename_axis(["date", "code"]).reset_index(name="pct").sort_values("date")
    long_pos = posday20.stack().rename_axis(["date", "code"]).reset_index(name="pos").sort_values("date")

    evx = pd.DataFrame({"code": ev["code"].values,
                        "cutoff": ev["actual_date"].values - pd.Timedelta(days=INST_LAG_DAYS),
                        "orig_idx": ev.index}).sort_values("cutoff").reset_index(drop=True)
    m_pct = pd.merge_asof(evx, long_pct, left_on="cutoff", right_on="date", by="code",
                          direction="backward", tolerance=pd.Timedelta(days=INST_STALE_DAYS))
    m_pos = pd.merge_asof(evx, long_pos, left_on="cutoff", right_on="date", by="code",
                          direction="backward", tolerance=pd.Timedelta(days=INST_STALE_DAYS))
    m_pct = m_pct.set_index("orig_idx").reindex(ev.index)
    m_pos = m_pos.set_index("orig_idx").reindex(ev.index)
    out = pd.DataFrame({"inst_pct20": m_pct["pct"], "inst_posday20": m_pos["pos"]}, index=ev.index)
    print(f"[feature] 外資+投信合計買賣超: pct20(canonical位階)可用{out.inst_pct20.notna().sum():,} "
          f"posday20(天數佔比)可用{out.inst_posday20.notna().sum():,}"
          f"(inst_flow僅2022-01起,2022年中以前事件此特徵天生NaN)")
    return out


def compute_revenue_feature(ev):
    """own_yoy3/own_yoy6: 個股自身近3/6個月YoY均值,period_last=actual_date往前45日曆日的月份
    (月營收依法10日內公告,45天緩衝遠超此要求,確保用到的月份在公告前已公開,逐字比照
    build_theme_member_selection.py own_yoy3定義,只是period_last改用日曆日緩衝而非題材月營收
    訊號本身的shift(1)口徑——因為本卷沒有題材月營收觸發事件月份可以借用)。"""
    conn = sqlite3.connect(DB, timeout=60)
    rev = pd.read_sql("SELECT code, date, revenue FROM fm_month_rev", conn, parse_dates=["date"])
    conn.close()
    rev_wide = rev.pivot_table(index="date", columns="code", values="revenue", aggfunc="first").sort_index()

    def yoy_mean(own, period_last, n_months):
        yoys = []
        for lag in range(n_months):
            p = period_last - pd.DateOffset(months=lag)
            p_prev = p - pd.DateOffset(months=12)
            v_now, v_prev = own.get(p, np.nan), own.get(p_prev, np.nan)
            if pd.isna(v_now) or pd.isna(v_prev) or v_prev == 0:
                return np.nan
            yoys.append(v_now / v_prev - 1)
        return float(np.mean(yoys)) * 100

    own_yoy3, own_yoy6 = [], []
    for r in ev.itertuples():
        own = rev_wide[r.code] if r.code in rev_wide.columns else None
        if own is None:
            own_yoy3.append(np.nan); own_yoy6.append(np.nan)
            continue
        period_last = (r.actual_date - pd.Timedelta(days=REV_BUFFER_DAYS)).replace(day=1)
        own_yoy3.append(yoy_mean(own, period_last, 3))
        own_yoy6.append(yoy_mean(own, period_last, 6))
    out = pd.DataFrame({"own_yoy3": own_yoy3, "own_yoy6": own_yoy6}, index=ev.index)
    print(f"[feature] 個股營收動能: own_yoy3可用{out.own_yoy3.notna().sum():,} "
          f"own_yoy6可用{out.own_yoy6.notna().sum():,}")
    return out


# ======================================================================
# 4. 贏家/輸家分組 + 同批(actual_date年-月)case-control對照組
#    (批次單位比照build_dtlend_winner_features.py的「同日」case-control精神,但因財報公告事件本身
#     遠比當沖交易日稀疏,改用「同批=actual_date所在年-月」取代「同日」,批次密度足夠隨機抽樣,
#     此為刻意的方法論調整,非疏漏,詳見報告已知限制)
# ======================================================================
def case_control_events(win_idx, df, seed):
    rng2 = np.random.default_rng(seed)
    win_set = set(win_idx)
    sub = df.loc[win_idx]
    ctrl_idx = []
    for ym, g in sub.groupby("ym"):
        pool = df.index[(df["ym"] == ym) & (~df.index.isin(win_set))]
        pool = list(pool)
        if not pool:
            continue
        k = min(len(g), len(pool))
        chosen = rng2.choice(pool, size=k, replace=False)
        ctrl_idx.extend(chosen)
    return pd.Index(ctrl_idx)


def build_groups(df):
    df = df.copy()
    df["ym"] = df["actual_date"].dt.strftime("%Y-%m")
    groups = {}

    valid20 = df["car20"].dropna()
    rnk20 = valid20.rank(pct=True)
    defs = {"win10": rnk20 >= 0.90, "win20": rnk20 >= 0.80, "lose10": rnk20 <= 0.10}
    seeds = {"win10": 20260803, "win20": 20260804, "lose10": 20260805}
    for name, cond in defs.items():
        idx = rnk20[cond].index
        ctrl = case_control_events(idx, df, seed=seeds[name])
        groups[name] = {"idx": idx, "ctrl_idx": ctrl, "n": len(idx), "n_ctrl": len(ctrl)}
        print(f"[groups] {name}(car20分位定義): 事件{len(idx):,} / 對照組{len(ctrl):,}")

    for k in (5, 10):
        validk = df[f"car{k}"].dropna()
        rnkk = validk.rank(pct=True)
        idx = rnkk[rnkk >= 0.90].index
        ctrl = case_control_events(idx, df, seed=20260806 + k)
        groups[f"win10_k{k}"] = {"idx": idx, "ctrl_idx": ctrl, "n": len(idx), "n_ctrl": len(ctrl)}
        print(f"[groups] win10_k{k}(跨窗口贏家定義穩健性用): 事件{len(idx):,} / 對照組{len(ctrl):,}")

    return df, groups


# ======================================================================
# 5. 特徵清單 + 全特徵點估計掃描 + 候選bootstrap + 通過判定
# ======================================================================
FEATURES = ["tdcc_d4w", "tdcc_d8w", "inst_pct20", "inst_posday20", "mom20", "mom60",
            "heat240", "heat120", "limitup20", "limitup60", "own_yoy3", "own_yoy6"]

FEATURE_LABEL = {
    "tdcc_d4w": "①大戶(千張)持股比例4週變化(pp)", "tdcc_d8w": "①大戶(千張)持股比例8週變化(pp,穩健配對)",
    "inst_pct20": "②外資+投信20日累計買超位階(canonical,百分位)",
    "inst_posday20": "②外資+投信20日淨買超天數佔比(%,穩健配對)",
    "mom20": "③公告前20日累積報酬(%)", "mom60": "③公告前60日累積報酬(%,穩健配對)",
    "heat240": "④成交值熱度240日自身百分位", "heat120": "④成交值熱度120日自身百分位(穩健配對)",
    "limitup20": "⑤公告前20日觸及漲停次數(收盤漲幅≥9.5%)", "limitup60": "⑤公告前60日觸及漲停次數(穩健配對)",
    "own_yoy3": "⑥個股營收YoY動能(近3月均值%)", "own_yoy6": "⑥個股營收YoY動能(近6月均值%,穩健配對)",
}
ROBUST_PAIRS = {"tdcc_d4w": "tdcc_d8w", "tdcc_d8w": "tdcc_d4w",
                "inst_pct20": "inst_posday20", "inst_posday20": "inst_pct20",
                "mom20": "mom60", "mom60": "mom20",
                "heat240": "heat120", "heat120": "heat240",
                "limitup20": "limitup60", "limitup60": "limitup20",
                "own_yoy3": "own_yoy6", "own_yoy6": "own_yoy3"}


def feat_vals_dates(df, col, idx):
    sub = df.loc[idx, [col, "actual_date"]].dropna(subset=[col])
    return sub[col].values.astype(float), sub["actual_date"].values


def scan_point_estimates(df, groups):
    rows = []
    for name in FEATURES:
        rec = {"feature": name}
        for gname in ("win10", "win20", "lose10"):
            g = groups[gname]
            cv, cd = feat_vals_dates(df, name, g["idx"])
            kv, kd = feat_vals_dates(df, name, g["ctrl_idx"])
            auc = calc_auc(cv, kv)
            rec[gname] = {"auc": auc, "n": len(cv), "n_ctrl": len(kv), "vals": (cv, cd, kv, kd)}
        rows.append(rec)
    return rows


def run_bootstrap_candidates(rows):
    boot = {}
    idx = {r["feature"]: r for r in rows}
    candidates = [r["feature"] for r in rows if pd.notna(r["win10"]["auc"])
                  and abs(r["win10"]["auc"] - 0.5) >= AUC_PRESCREEN]
    print(f"[boot] 點估計偏離>=±{AUC_PRESCREEN}的候選特徵 {len(candidates)}/{len(rows)}: {candidates}")

    to_boot = set()
    for name in candidates:
        to_boot.add(("win10", name))
    for name in candidates:
        r = idx[name]
        if abs(r["win10"]["auc"] - 0.5) >= AUC_PASS_DEV:
            to_boot.add(("win20", name))
            to_boot.add(("lose10", name))
            pair = ROBUST_PAIRS.get(name)
            if pair:
                to_boot.add(("win10", pair))

    t0 = time.time()
    for i, (gname, name) in enumerate(sorted(to_boot)):
        cv, cd, kv, kd = idx[name][gname]["vals"]
        r = boot_auc_ci(cv, cd, kv, kd)
        boot[(gname, name)] = r
        if r is not None:
            print(f"[boot] ({gname},{name}) AUC={r['auc']:.3f} CI[{r['lo']:.3f},{r['hi']:.3f}] "
                  f"sig={r['sig']} ({i + 1}/{len(to_boot)}, 累計{time.time() - t0:.0f}s)")
        else:
            print(f"[boot] ({gname},{name}) n或分群數不足跳過 ({i + 1}/{len(to_boot)})")
    print(f"[boot] 全部候選bootstrap完成,耗時{time.time() - t0:.0f}s")
    return boot


def verdict_feature(name, boot):
    r10 = boot.get(("win10", name))
    if r10 is None or abs(r10["auc"] - 0.5) < AUC_PASS_DEV or not r10["sig"]:
        return False, "win10未達0.58/0.42門檻或CI含0.5"
    same_dir = np.sign(r10["auc"] - 0.5)

    r20 = boot.get(("win20", name))
    win20_ok = r20 is not None and np.sign(r20["auc"] - 0.5) == same_dir and abs(r20["auc"] - 0.5) >= ROBUST_DEV
    if not win20_ok:
        detail = f"win20 AUC={r20['auc']:.3f}" if r20 is not None else "win20未達bootstrap門檻"
        return False, f"win10通過但通用穩健版(前20%)不一致({detail})"

    pair = ROBUST_PAIRS.get(name)
    if pair:
        rp = boot.get(("win10", pair))
        pair_ok = rp is not None and np.sign(rp["auc"] - 0.5) == same_dir and abs(rp["auc"] - 0.5) >= ROBUST_DEV
        if not pair_ok:
            detail = f"{pair} AUC={rp['auc']:.3f}" if rp is not None else f"{pair}未達bootstrap門檻"
            return False, f"win10+win20通過但定義配對版({FEATURE_LABEL.get(pair, pair)})不一致({detail})"
    return True, "win10+win20(+定義配對)三重一致,通過穩健度門檻"


# ======================================================================
# 6. 跨窗口(k=5/10)贏家定義穩健性複驗(僅通過特徵,點估計層級,比照
#    build_dtlend_winner_features.py regime_breakdown的精神,這裡複驗的是「贏家定義窗口長度」)
# ======================================================================
def window_consistency(passed_names, df, groups):
    out = {}
    for name in passed_names:
        rows = []
        for gname, glabel in (("win10", "car20主判讀"), ("win10_k5", "car5窗定義"), ("win10_k10", "car10窗定義")):
            g = groups[gname]
            cv, _ = feat_vals_dates(df, name, g["idx"])
            kv, _ = feat_vals_dates(df, name, g["ctrl_idx"])
            auc = calc_auc(cv, kv) if len(cv) >= MIN_POOL and len(kv) >= MIN_POOL else np.nan
            rows.append((glabel, auc, len(cv)))
        out[name] = rows
        print(f"[window] {name} 跨窗口定義AUC: " + ", ".join(
            f"{lb}={a:.3f}(n={n})" if pd.notna(a) else f"{lb}=n太小" for lb, a, n in rows))
    return out


# ======================================================================
# 7. 規則翻譯 + 驗證(僅通過特徵; 全樣本cross-sectional rank>=90%或<=10%當開盤前規則,
#    驗證規則篩出股票的car20是否顯著優於全樣本基準+同批(年-月)case-control對照組;
#    不在訓練用的贏家組裡自我循環驗證,而是套回全樣本重新篩選)
# ======================================================================
def build_rule(name, direction, df):
    """direction=+1表特徵值越大越可能是贏家(規則=取全樣本前10%),-1表反向(規則=取後10%)。"""
    valid = df[name].dropna()
    rnk = valid.rank(pct=True)
    rule_idx = rnk[rnk >= 0.90].index if direction > 0 else rnk[rnk <= 0.10].index
    return rule_idx


def eval_rule(label, rule_idx, df, seed):
    n = len(rule_idx)
    car_vals, car_dates = feat_vals_dates(df, "car20", rule_idx)
    if len(car_vals) < 15:
        print(f"[rule] {label}: n太小(car20可用n={len(car_vals)}),跳過")
        return None

    base_pop = df["car20"].dropna()
    base_med = float(base_pop.median())
    boot_vs_base = boot_median_ci0(list(car_vals - base_med), car_dates)

    ctrl = case_control_events(rule_idx, df, seed=seed)
    ctrl_vals, ctrl_dates = feat_vals_dates(df, "car20", ctrl)
    boot_vs_ctrl = boot_median_diff(car_vals, car_dates, ctrl_vals, ctrl_dates)

    hit_rate = float((car_vals > 0).mean()) * 100
    base_hit = float((base_pop > 0).mean()) * 100

    print(f"[rule] {label}: n={n:,}(car20可用{len(car_vals):,}) car20中位{np.median(car_vals):+.2f}%"
          f"(全樣本基準{base_med:+.2f}%) 命中率{hit_rate:.1f}%(基準{base_hit:.1f}%) 對照組n={len(ctrl_vals):,}")

    return {"label": label, "n": n, "n_valid": len(car_vals), "n_ctrl": len(ctrl_vals),
            "med": float(np.median(car_vals)), "base_med": base_med,
            "hit_rate": hit_rate, "base_hit": base_hit,
            "boot_vs_base": boot_vs_base, "boot_vs_ctrl": boot_vs_ctrl}


def build_phase2_rules(passed, boot, df):
    rules = {}
    for name in passed:
        r10 = boot[("win10", name)]
        direction = 1 if r10["auc"] > 0.5 else -1
        dir_txt = "前10%(數值越大越像贏家)" if direction > 0 else "後10%(數值越小越像贏家)"
        rule_idx = build_rule(name, direction, df)
        label = f"{FEATURE_LABEL.get(name, name)} {dir_txt}"
        rules[name] = eval_rule(label, rule_idx, df, seed=20260810 + hash(name) % 1000)
    return rules


# ======================================================================
# 8. 三問機制文字(比照build_dtlend_winner_features.py THREE_Q設計,依特徵類別套用)
# ======================================================================
THREE_Q = {
    "tdcc": ("大戶持股比例趨勢",
             "誰被迫交易?——大戶(千張以上)持股比例上升多半反映主動加碼(自願行為),下降則可能是"
             "主動獲利了結或大股東質押斷頭等被迫性賣壓;財報公告前的大戶持股變化若有鑑別力,較可能"
             "反映「大戶提前知道/預期到即將公告的財報內容而先行布局」,而非純粹隨機雜訊。",
             "資訊是新的嗎?——tdcc_weekly是集保週資料,對外公告本身有落後(約一週後才看得到當週"
             "快照),若大戶真的搶先卡位,散戶看到這批資料時布局動作可能已完成大半,存在資訊時間差。",
             "為何別人沒吃掉它?——若這個訊號存在且可預測,理論上該被市場快速套利掉;可能的解釋是"
             "①集保資料本身有落後,一般投資人難以即時反應,②大戶持股變化的驅動力本身多樣(不只財報"
             "預期,也包含籌碼調度/認購權證履約等雜訊),訊號淨值可能被這些雜訊稀釋。"),
    "inst": ("外資/投信合計買賣超",
             "誰被迫交易?——外資/投信是機構法人,交易多為主動性研究驅動(自願),但部分被動指數"
             "基金的申贖/成分股調整可能屬於「非資訊驅動」的機械性交易,兩者混在同一個net欄位裡,"
             "無法從資料本身區分。",
             "資訊是新的嗎?——外資/投信買賣超是T+1即可取得的高頻公開資訊,是全市場最被密切關注的"
             "籌碼指標之一,理論上早已被市場充分消化,不太可能是「未被發現的新資訊」。",
             "為何別人沒吃掉它?——若此特徵仍通過AUC門檻,較可能反映的是「法人買賣超本身與後續股價"
             "表現的動能延續性(法人買什麼漲什麼的動能效應)」,而非法人真的預先看穿財報內容,此為"
             "經典動能因子的變形,不必然是「財報特有」的訊號。"),
    "mom": ("股價動能",
            "誰被迫交易?——動能延續常見於追價買盤(自願)與程式化動能策略,強制性行為者不明顯。",
            "資訊是新的嗎?——過去20/60日累積報酬是最公開的公開資訊,全市場同步可見。",
            "為何別人沒吃掉它?——動能因子是學術上有大量文獻支持的經典異常現象(momentum anomaly),"
            "若在財報公告這個子集上也成立,較可能是動能因子本身的展現,而非財報事件特有的訊號;"
            "前一版build_theme_member_selection.py在題材觸發子集(n=115)上測不出這個效果,本卷"
            "若在全樣本(n更大)上測出,需誠實討論是樣本量差異、population差異(不限題材觸發)、"
            "還是純粹統計雜訊導致的不一致。"),
    "heat": ("成交值熱度百分位",
             "誰被迫交易?——成交熱度上升代表關注度提高,可能來自主動買盤湧入或放空回補等多種"
             "自願性行為,強制性行為者不明顯。",
             "資訊是新的嗎?——成交值是最公開的市場資訊,理論上無資訊優勢可言。",
             "為何別人沒吃掉它?——若熱度與後續公告後表現有關,較可能反映「市場已經預期到即將"
             "公告的財報可能有驚喜,提前湧入交易」這種自我實現的注意力效應,而非發現了被市場忽略"
             "的獨立訊號,此類效應通常較難穩定套利(注意力本身難以事前精準預測)。"),
    "limitup": ("短期漲停次數",
                "誰被迫交易?——短期內多次觸及漲停,常伴隨軋空回補(空單被迫回補)與散戶追價"
                "FOMO(自願)兩種力量交織,較難單純歸為某一方。",
                "資訊是新的嗎?——漲停本身是最公開的價格行為,全市場同步可見。",
                "為何別人沒吃掉它?——若漲停次數與公告後表現有關,較可能反映「急拉後續有慣性"
                "(動能延續)」或反向的「急拉已提前透支未來的利多消化,公告後反而降溫」兩種相反"
                "機制,需依實際點估計方向判讀,不能預設方向;此類極端事件樣本天生稀少(多數股票"
                "20/60日內漲停次數為0),多重比較風險需誠實揭露。"),
    "rev": ("個股營收動能",
            "誰被迫交易?——營收動能本身是基本面資訊而非交易行為,不涉及「被迫交易」概念,但"
            "知道營收動能的知情者(公司內部人/往來供應鏈)可能提前布局,屬於潛在資訊不對稱來源。",
            "資訊是新的嗎?——月營收依法10日內須公告,本卷特徵已用45天緩衝確保用到的月份在公告"
            "前早已公開,故不是「新」資訊,是否仍有鑑別力取決於市場是否已充分把月營收動能定價進"
            "股價(理論上應該已經定價,除非財報公告本身包含月營收看不到的額外資訊如業外損益/毛利率"
            "結構,才會讓「營收動能高」與「財報公告後噴出」產生額外的邊際關聯)。",
            "為何別人沒吃掉它?——月營收是所有投資人都能取得的公開資訊,若營收動能與公告後表現"
            "仍有鑑別力,較可能反映「財報公告時把月營收動能趨勢確認成完整財報數字」這個確認效應"
            "本身帶來的邊際資訊(毛利率/業外等月營收看不到的部分),而非資訊本身是新的。"),
}


def feature_category(name):
    if name.startswith("tdcc"):
        return "tdcc"
    if name.startswith("inst"):
        return "inst"
    if name.startswith("mom"):
        return "mom"
    if name.startswith("heat"):
        return "heat"
    if name.startswith("limitup"):
        return "limitup"
    if name.startswith("own_yoy"):
        return "rev"
    return "mom"


# ======================================================================
# 9. HTML 呈現
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
"""


def write_report(ev_summary, rows, boot, groups, passed, window_out, rules, df):
    idx = {r["feature"]: r for r in rows}

    scan_rows_html = []
    for r in sorted(rows, key=lambda x: -abs(x["win10"]["auc"] - 0.5) if pd.notna(x["win10"]["auc"]) else -1):
        name = r["feature"]
        auc10 = r["win10"]["auc"]
        flag = "✅" if name in passed else ("🔬" if pd.notna(auc10) and abs(auc10 - 0.5) >= AUC_PRESCREEN else "")
        def cell(g):
            a = r[g]["auc"]
            return f"{a:.3f}(n={r[g]['n']:,})" if pd.notna(a) else f"—(n={r[g]['n']:,})"
        scan_rows_html.append(
            f"<tr><th>{flag}{FEATURE_LABEL.get(name, name)}</th>"
            f"<td>{cell('win10')}</td><td>{cell('win20')}</td><td>{cell('lose10')}</td></tr>")
    scan_table = ("<table><tr><th>特徵(✅=通過穩健度門檻,🔬=進入bootstrap候選但未通過)</th>"
                  "<th>win10(前10%) AUC</th><th>win20(前20%) AUC</th><th>lose10(後10%) AUC</th></tr>"
                  + "".join(scan_rows_html) + "</table>")

    boot_lines = []
    seen = set()
    for r in rows:
        name = r["feature"]
        for gname, glabel in (("win10", "前10%贏家(car20)"), ("win20", "前20%贏家(穩健版)"),
                              ("lose10", "後10%輸家(對稱檢定)")):
            key = (gname, name)
            if key in boot and key not in seen:
                seen.add(key)
                boot_lines.append(auc_line(f"{FEATURE_LABEL.get(name, name)} · {glabel} vs 同批(年-月)case-control",
                                           boot[key]))
    boot_html = "<ul>" + "".join(boot_lines) + "</ul>" if boot_lines else \
        "<div class='note'>無候選特徵進入bootstrap(全部點估計|AUC-0.5|&lt;0.03)。</div>"

    if passed:
        pass_rows = []
        for name in passed:
            r10 = boot[("win10", name)]
            r20 = boot.get(("win20", name))
            pass_rows.append(
                f"<tr><th>{FEATURE_LABEL.get(name, name)}</th>"
                f"<td class='good'>{r10['auc']:.3f} [{r10['lo']:.3f},{r10['hi']:.3f}]</td>"
                f"<td>{r20['auc']:.3f} [{r20['lo']:.3f},{r20['hi']:.3f}]</td></tr>")
        pass_table = ("<table><tr><th>特徵</th><th>win10 AUC[95%CI]</th><th>win20穩健版AUC[95%CI]</th></tr>"
                      + "".join(pass_rows) + "</table>")
        cats = sorted({feature_category(n) for n in passed})
        q_blocks = []
        for cat in cats:
            title, q1, q2, q3 = THREE_Q[cat]
            names_in_cat = [FEATURE_LABEL.get(n, n) for n in passed if feature_category(n) == cat]
            q_blocks.append(f"<h3>{title}(通過特徵: {', '.join(names_in_cat)})</h3>"
                           f"<ul><li>{q1}</li><li>{q2}</li><li>{q3}</li></ul>")
        three_q_html = "".join(q_blocks)

        window_rows = []
        for name in passed:
            bands = window_out.get(name, [])
            cells = "".join(f"<td>{a:.3f}(n={n})</td>" if pd.notna(a) else "<td>n太小</td>" for _, a, n in bands)
            window_rows.append(f"<tr><th>{FEATURE_LABEL.get(name, name)}</th>{cells}</tr>")
        window_head = "".join(f"<th>{lb}</th>" for lb, _, _ in (window_out.get(passed[0], []) if passed else []))
        window_table = (f"<table><tr><th>特徵</th>{window_head}</tr>" + "".join(window_rows) + "</table>") if passed else ""
        p1_cls, p1_txt = "v-good", f"✅有{len(passed)}個特徵通過AUC+穩健度門檻(見下表)"
    else:
        pass_table = "<div class='note'>無特徵通過。</div>"
        three_q_html = "<div class='note'>無通過特徵,略過三問討論。</div>"
        window_table = ""
        p1_cls, p1_txt = "v-warn", "🟡無特徵通過0.58/0.42門檻+穩健度要求(與build_theme_member_selection.py題材觸發子集的null結果方向一致,詳見下方對照段落)"

    rule_rows_html = []
    rule_boot_html = []
    any_rule_sig_good = False
    for name, r in rules.items():
        if r is None:
            rule_rows_html.append(f"<tr><th>{FEATURE_LABEL.get(name, name)}</th><td colspan='2'>n太小,無法驗證</td></tr>")
            continue
        rule_rows_html.append(
            f"<tr><th>{r['label']}(n={r['n']:,},car20可用{r['n_valid']:,})</th>"
            f"<td>{r['med']:+.2f}%<br><span class='sub'>基準{r['base_med']:+.2f}%</span></td>"
            f"<td>{r['hit_rate']:.1f}%<br><span class='sub'>基準{r['base_hit']:.1f}%</span></td></tr>")
        rule_boot_html.append(f"<h3>{r['label']}</h3><ul>"
            + boot_line2("car20中位數 vs全樣本基準(excess)", r["boot_vs_base"], "med", unit="%")
            + boot_line2("car20中位數 vs case-control同批對照組", r["boot_vs_ctrl"], "diff", unit="%")
            + "</ul>")
        if r["boot_vs_ctrl"] is not None and r["boot_vs_ctrl"]["sig"] and r["boot_vs_ctrl"]["diff"] > 0:
            any_rule_sig_good = True
    rule_table = ("<table><tr><th>開盤前(公告前)規則</th><th>公告後car20中位數(基準版)</th>"
                  "<th>公告後car20命中率(基準版)</th></tr>" + "".join(rule_rows_html) + "</table>") if rules else \
        "<div class='note'>無通過特徵,無規則可翻譯驗證。</div>"
    rule_boot = "".join(rule_boot_html)

    if not passed:
        p2_cls, p2_txt = "v-warn", "🟡第一階段無特徵通過,第二階段無規則可翻譯(誠實null結果)"
    elif any_rule_sig_good:
        p2_cls, p2_txt = "v-good", "✅至少一條開盤前規則,其car20(vs case-control)顯著優於對照組"
    else:
        p2_cls, p2_txt = "v-warn", "🟡有特徵通過AUC門檻,但翻譯成規則後套回全樣本未能取得顯著優於case-control的結果——AUC鑑別力與可交易規則是兩回事,誠實呈現"

    def bar_payload(labels, vals, colors):
        return {"labels": labels, "vals": [round(v, 3) if v is not None and pd.notna(v) else None for v in vals],
                "colors": colors}

    valid_rows = [r for r in rows if pd.notna(r["win10"]["auc"])]
    top_by_dev = sorted(valid_rows, key=lambda x: -abs(x["win10"]["auc"] - 0.5))[:12]
    c1 = bar_payload([FEATURE_LABEL.get(r["feature"], r["feature"]) for r in top_by_dev],
                     [r["win10"]["auc"] for r in top_by_dev],
                     [GREEN if r["feature"] in passed else (YELLOW if abs(r["win10"]["auc"] - 0.5) >= AUC_PRESCREEN else GRAY)
                      for r in top_by_dev])
    rule_labels = [r["label"] for r in rules.values() if r is not None]
    rule_vals = [(r["med"] - r["base_med"]) for r in rules.values() if r is not None]
    c2 = bar_payload(rule_labels, rule_vals, [BLUE] * len(rule_labels))
    payload = {"c1": c1, "c2": c2}
    payload_json = json.dumps(payload, ensure_ascii=False)

    n_days_used = ev_summary["n_final"]

    if not passed:
        compare_txt = (
            "與該卷null結論一致,population變大(3千餘筆vs115筆)、時間跨度變長(7.5年vs4年)後,"
            "依然沒有測出穩健通過三重一致門檻的特徵——顯示「財報公告後噴出」這個結果本身,至少用"
            "本卷這幾個常見籌碼/動能/營收角度,可能真的很難從公告前的公開資訊逆向工程出來"
            "(與「頂部無指紋定理」的既有發現精神一致: 事後看起來噴出的股票,公告前並沒有留下"
            "好辨識的指紋)。")
    else:
        compare_txt = (
            f"與該卷null結論不完全一致——本卷population更大後,"
            f"{', '.join(FEATURE_LABEL.get(n, n) for n in passed)}通過了三重一致的穩健度門檻,"
            "可能反映題材觸發子集樣本量太小(n=115)測不出這個效果,全樣本(n更大)才有足夠檢定力"
            "偵測到;但仍需留意通過AUC篩選不等於找到可獲利的獨立訊號(見③三問機制討論與下方"
            "第二階段規則驗證結果,AUC鑑別力與翻譯後的可交易規則是否顯著,是兩個不同層次的問題)。")

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>財報公告後噴出贏家逆向工程特徵case-control考卷(2026-08-03)</title>
<script src="plotly.min.js"></script><style>{CSS}</style></head><body>
<h1>📊 財報公告後噴出贏家逆向工程特徵×AUC case-control考卷</h1>
<div class="note">方法論逐字比照<code>build_dtlend_winner_features.py</code>既有標準:任何逆向工程
出的特徵都必須有同批(actual_date所在年-月)case-control對照組(排除該批所有贏家後隨機抽同數量
非贏家事件),算AUC而非只看「贏家組數值比較高」。判準: |AUC-0.5|&gt;={AUC_PASS_DEV}(即AUC&gt;=0.58
或&lt;=0.42)且月群bootstrap 95%CI排除0.5,且通用穩健版(前20%贏家窗口)同向達≥{ROBUST_DEV}偏離,
若特徵有明確定義配對(4週/8週、20日/60日、240日/120日、canonical位階/天數佔比)則該配對也需同向達
≥{ROBUST_DEV}偏離,三者皆一致才算「通過穩健度門檻」。<br>
事件母體: tw_board_earnings_dates全表{ev_summary['n_raw']:,}列,actual_date非空
{ev_summary['n_notnull']:,}筆,去重(code,actual_date)後{ev_summary['n_dedup']:,}筆,
定位到價格序列後{n_days_used:,}筆可用於分析,{ev_summary['n_codes']}檔,
{ev_summary['date_min']}~{ev_summary['date_max']}。⚠population與build_theme_member_selection.py
(僅限題材月營收動能訊號觸發子集,約115事件)不同,本卷是全部財報公告事件,樣本大7倍以上、
時間跨度長3倍(涵蓋2020疫情崩盤/2022熊市/近期多頭多個regime)。</div>

<h2>① 贏家/輸家定義</h2>
<div class="note">用fm_daily_price算每筆事件actual_date「後」k日累積報酬(demean扣對應大盤
TAIEX/TPEx),主判讀k=20(中期噴出效果);win10=car20全樣本排名前10%(主判讀贏家),
win20=前20%(穩健對照),lose10=後10%(對稱性檢定);另建win10_k5/win10_k10(用car5/car10重新定義
贏家)供「贏家定義本身」的跨窗口穩健性複驗。</div>
<table><tr><th>組別</th><th>定義</th><th>事件數</th><th>對照組事件數</th></tr>
{"".join(f"<tr><th>{gname}</th><td>{glabel}</td><td>{groups[gname]['n']:,}</td><td>{groups[gname]['n_ctrl']:,}</td></tr>"
  for gname, glabel in (("win10","car20排名前10%(主判讀)"),("win20","car20排名前20%(穩健對照)"),
                        ("lose10","car20排名後10%(對稱檢定)"),
                        ("win10_k5","car5排名前10%(跨窗口穩健性用)"),("win10_k10","car10排名前10%(跨窗口穩健性用)")))}
</table>

<h2>② 全特徵點估計AUC掃描(誠實列出全部{len(rows)}個特徵版本,不是只列贏家)</h2>
<div class="note">AUC=0.5代表無鑑別力,&gt;0.5代表特徵值越大越可能是贏家,&lt;0.5代表相反。
🔬=點估計|AUC-0.5|&gt;={AUC_PRESCREEN}進入bootstrap候選;✅=最終通過穩健度門檻。</div>
{scan_table}

<h2>③ 候選特徵bootstrap明細(月群重抽樣n_iter={N_ITER_AUC},95%CI)</h2>
{boot_html}

<h2>④ 通過穩健度門檻的特徵</h2>
<table><tr><th>階段</th><th>核心問題</th><th>判讀</th></tr>
<tr><th>第一階段:逆向工程AUC篩選</th><td>贏家公告前特徵是否有鑑別力(vs同批case-control)</td>
<td><span class="verdict {p1_cls}">{p1_txt}</span></td></tr>
<tr><th>第二階段:規則翻譯+驗證</th><td>把通過特徵翻成公告前可用規則,套回全樣本驗證car20是否顯著優於
基準/case-control</td><td><span class="verdict {p2_cls}">{p2_txt}</span></td></tr></table>
{pass_table}

<h3>跨窗口(k=5/10)贏家定義穩健性複驗(僅通過特徵;檢查方向是否跨「贏家定義窗口長度」一致)</h3>
{window_table if passed else "<div class='note'>無通過特徵可供複驗。</div>"}

<h2>⑤ 三問機制討論(誰被迫交易?/資訊是新的嗎?/為何別人沒吃掉它?)</h2>
{three_q_html}

<h2>⑥ 第二階段: 規則翻譯 + 驗證(套回全樣本,非贏家組內自我循環驗證)</h2>
<div class="note">規則=通過特徵在「全樣本」(非僅贏家組)cross-sectional排名前10%(或後10%,依AUC方向
決定),驗證規則篩出的股票,其公告後car20是否顯著優於全樣本基準(常數)與同批case-control對照組
(排除規則命中股後隨機抽同數量,net掉批次層的共同成分)。</div>
{rule_table}
<h3>bootstrap顯著性(vs全樣本基準 + vs case-control同批對照組)</h3>
{rule_boot}

<h2>📈 圖表</h2>
<div class="note">c1=win10 AUC點估計偏離0.5最大的前12個特徵版本(綠=通過穩健度門檻,黃=進入bootstrap
候選但未通過,灰=未進候選);c2=第二階段各規則car20中位數excess(vs全樣本基準,pp)。</div>
<div id="c1" style="height:380px"></div>
<div id="c2" style="height:320px"></div>

<h2>⑦ 與build_theme_member_selection.py(題材觸發子集)null結果的對照</h2>
<div class="note">
build_theme_member_selection.py鎖定「題材月營收動能訊號觸發」子集(score=4,約115個題材-月事件/
828筆成員-事件,2022-2026),測過6個角度(價格動能20/60日、外資20日位階、TDCC大戶趨勢、個股營收
YoY、佔題材營收比重變化、漲停次數),結果全部不顯著(8個測試CI都含0,僅漲停次數家族中一個最嚴格
子版本點估計顯著但被判定為多重比較下的觀察線索,非定論)。<br>
本卷結果: {compare_txt}
</div>

<h2>已知限制與方法論不確定處(誠實聲明)</h2>
<div class="note">
①<b>Multiple comparison</b>: 本卷同時掃描{len(rows)}個特徵版本(win10+win20+lose10三組×
{len(FEATURES)}個特徵),即使全部特徵都是純雜訊,依95%CI規則預期仍會有約
{len(rows) * 0.05:.0f}個「碰巧」顯著排0的個案;已用「win20+定義配對版三重一致」作為實質多重比較
管控門檻,但仍建議將結論視為「候選假說」而非「已驗證定律」。<br>
②<b>case-control批次單位調整</b>: 本卷用「actual_date所在年-月」取代dtlend卷的「同日」當
case-control批次單位(財報公告事件遠比當沖交易日稀疏,同日密度不足以隨機抽樣),此為刻意的方法論
調整,批次內仍能有效控制「當時大盤regime/財報季共同氛圍」這個混淆因子,但控制精細度不如「同日」
版本(同月內仍可能有數週的regime漂移)。<br>
③<b>資料涵蓋期不對稱</b>: inst_flow僅2022-01起(2022年中以前需240日暖機的canonical位階特徵天生
NaN),tdcc_weekly/fm_month_rev/fm_daily_price涵蓋較長歷史,故inst_pct20/inst_posday20兩個特徵版本
的有效樣本數明顯小於其他特徵,通過門檻的難度較高(bootstrap CI較寬),解讀時需留意n數差異。<br>
④<b>公司內部人視角的因果不可得</b>: 本卷所有特徵皆為公開可得的市場/籌碼/營收資訊,無法測試「公司
內部人是否提前知道財報數字」這種真正的資訊不對稱,通過AUC篩選的特徵,其機制解讀應偏向「動能/
注意力延續」而非「內線消息外洩」,見③三問機制逐項討論。<br>
⑤<b>漲停判定用寬鬆門檻(收盤漲幅≥9.5%)</b>,未做嚴格版(一字鎖死型)區分,且多數股票公告前
20/60日內漲停次數為0,樣本高度右偏,AUC點估計對這種零膨脹分布的解讀需保守。<br>
⑥<b>營收動能45天緩衝屬保守估計</b>,實際上部分月營收可能提早公告或延遲公告,45天緩衝已遠超10日
法定公告期限,不至於誤用未公告資訊,但也犧牲了一些「更新鮮」的資訊(用的是1.5個月前的月營收動能,
非最新一期)。<br>
⑦<b>AUC月群bootstrap迭代數(n_iter={N_ITER_AUC})</b>低於本專案中位數CI慣用的2000次,是計算成本
的取捨,CI精度可能略遜,但仍足以判斷是否排除0.5。<br>
⑧所有數字為觀察層/盤點層,不涉及交易成本、滑價、實際下單可執行性(財報公告當天/次一交易日常有
跳空/流動性驟變,實際執行難度需另外評估),亦不預設上板。
</div>
<div class="note">維運: python 研究腳本/財報事件/build_earnings_winner_features.py(從根目錄執行,
鐵律)。姊妹檔: build_earnings_preannounce_reaction.py(全樣本「公告前普遍反應」null/弱負結果,
本卷是其逆向工程改版)、build_dtlend_winner_features.py(本卷比照的AUC+case-control方法論先例)、
build_theme_member_selection.py(題材觸發子集的null結果,population不同但特徵算法多有借用)。</div>

<script>
const D={payload_json};
const BG={json.dumps(BG, ensure_ascii=False)};
function bar(id, title, d, ytitle, refline) {{
  const traces = [{{x:d.labels, y:d.vals, type:'bar', marker:{{color:d.colors}},
    text:d.vals.map(v=>v===null?'—':v.toFixed(3)), textposition:'outside'}}];
  const layout = Object.assign({{title:title, yaxis:{{title:ytitle,zeroline:true,zerolinecolor:'#555'}},
    xaxis:{{tickangle:-30}}}}, BG);
  if (refline !== undefined) {{
    layout.shapes = [{{type:'line', x0:-0.5, x1:d.labels.length-0.5, y0:refline, y1:refline,
      line:{{color:'#888', dash:'dot', width:1}}}}];
  }}
  Plotly.newPlot(id, traces, layout);
}}
bar('c1', '② win10 AUC點估計(|偏離0.5|前12名)', D.c1, 'AUC', 0.5);
bar('c2', '⑥ 第二階段規則: 公告後car20中位數 excess(vs全樣本基準,pp)', D.c2, 'excess(%)', 0);
</script>
</body></html>"""
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[report] 已輸出 {OUT}")


# ======================================================================
# 10. main
# ======================================================================
def main():
    t0 = time.time()
    selfcheck_auc()

    ev = load_events()
    n_raw_events, n_notnull_events = ev.attrs["n_raw"], ev.attrs["n_notnull"]
    codes = sorted(ev.code.unique())
    px, idx = load_price_index(codes)
    stocks = build_stock_panels(px)
    idx_ret = make_idx_ret(idx)

    print("=" * 60, "\n[main] 事件面板: 公告後car5/10/20 + 公告前價格類特徵")
    panel = compute_event_panel(ev, stocks, idx_ret)

    print("=" * 60, "\n[main] 額外特徵: TDCC大戶趨勢")
    tdcc_feat = compute_tdcc_feature(ev)
    print("[main] 額外特徵: 外資+投信合計買賣超")
    inst_feat = compute_inst_flow_feature(ev)
    print("[main] 額外特徵: 個股營收動能")
    rev_feat = compute_revenue_feature(ev)

    df = panel.join(tdcc_feat, how="left").join(inst_feat, how="left").join(rev_feat, how="left")
    print(f"[main] 合併特徵面板: {len(df):,}筆 x {df.shape[1]}欄")

    ev_summary = {"n_raw": n_raw_events, "n_notnull": n_notnull_events, "n_dedup": len(ev),
                  "n_final": len(df), "n_codes": df.code.nunique() if len(df) else 0,
                  "date_min": str(df.actual_date.min().date()) if len(df) else "-",
                  "date_max": str(df.actual_date.max().date()) if len(df) else "-"}

    print("=" * 60, "\n[main] 贏家/輸家分組 + 同批case-control")
    df, groups = build_groups(df)

    print("=" * 60, "\n[main] 第一階段: 全特徵點估計掃描")
    rows = scan_point_estimates(df, groups)
    for r in sorted(rows, key=lambda x: -abs(x["win10"]["auc"] - 0.5) if pd.notna(x["win10"]["auc"]) else -1):
        a10 = r["win10"]["auc"]
        print(f"  {r['feature']:<16} win10={a10:.3f}(n={r['win10']['n']:,}) "
              f"win20={r['win20']['auc']:.3f} lose10={r['lose10']['auc']:.3f}" if pd.notna(a10) else
              f"  {r['feature']:<16} n太小/全NaN")

    print("=" * 60, "\n[main] 候選特徵bootstrap")
    boot = run_bootstrap_candidates(rows)

    print("=" * 60, "\n[main] 判定通過清單")
    passed = []
    for r in rows:
        name = r["feature"]
        if ("win10", name) in boot:
            ok, why = verdict_feature(name, boot)
            print(f"  {name}: {'✅通過' if ok else '❌未通過'} — {why}")
            if ok:
                passed.append(name)
    print(f"[main] 最終通過穩健度門檻特徵數 = {len(passed)}: {passed}")

    print("=" * 60, "\n[main] 跨窗口(k=5/10)贏家定義穩健性複驗")
    window_out = window_consistency(passed, df, groups) if passed else {}

    print("=" * 60, "\n[main] 第二階段: 規則翻譯 + 驗證")
    rules = build_phase2_rules(passed, boot, df) if passed else {}

    print("=" * 60, "\n[main] 組裝報告")
    write_report(ev_summary, rows, boot, groups, passed, window_out, rules, df)
    print(f"[main] 全部完成,總耗時{time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
