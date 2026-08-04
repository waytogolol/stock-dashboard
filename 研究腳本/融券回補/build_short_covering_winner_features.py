# -*- coding: utf-8 -*-
"""強制回補「贏家/輸家」逆向工程特徵×AUC case-control考卷(2026-08-04)。

背景/動機: build_short_covering_pressure.py主檢定(A段pre_dm_10全樣本)不顯著(CI含0),但B段
案例對照(同股配對安慰劑)顯著(事件窗pre_dm_10 vs 安慰劑窗,差+0.74pp CI排0),C段強度分層
(短占股本比/回補天數三分位)兩者皆無梯度。使用者看完提出關鍵質疑:「我感覺你沒有研究到回補的
力道有多強...波動度、型態、法人籌碼等等是否有都納入?另一種就是這個因子看起來不顯著,但我們可以
先找獲利的前10%以及後10%觀察有哪些差異性去研究看看」——即與其只測預先假設好的力道代理變數,
不如逆向工程: 先定義結果(誰是贏家/輸家),回頭挖掘公開特徵是否能區分。

方法論逐字比照build_earnings_winner_features.py(同批姊妹卷已驗證的AUC+case-control標準),
統計工具(calc_auc/boot_auc_ci/auc_line)複製自該卷(house既有慣例:這幾支純統計函式各winner_features
卷各自複製一份,不跨資料夾import,詳見該卷docstring說明);中位數/差值bootstrap則**直接import
同目錄的build_short_covering_pressure模組**(med_win/boot_med/boot_diff/loto/ci_tag/fmt/cell),
不重新發明——本卷與該卷同資料夾,sys.path[0]天然包含該模組,直接`import build_short_covering_pressure`
即可,不必跨資料夾複製。事件面板本身(susp/panels/build_events)也直接呼叫該模組的同名函式,
不重新抓取或重新定義last_cover錨點/去重規則,確保與已發布報告完全一致的事件母體。

【結果變數(outcome)怎麼選——重要決策,附實測證據】
任務原文建議「post-event報酬窗口(例如pre_dm_10...)」。但實測pickle(快取/tmp_short_suspend_panel.pkl)
發現post_dm_k(last_cover之後)有嚴重污染: 除權息桶(bucket='除權息',n=10,368)的post_dm_10中位數
-4.72%/勝率20.7%,股東會桶(n=12,791)僅-0.84%/43.2%——差距過大,幾乎可以確定是fm_daily_price
收盤價**未做股息/除權還原**(原報告限制⑤已載明)所致的機械性缺口,而非真實訊號,若拿post窗口
當結果變數,任何與「除權息規模」相關的特徵都會產生假陽性AUC。因此本卷改用**pre_dm_10**
(last_cover前10日demean報酬)當結果變數——這正是任務原文括號內給的例子,也是B段案例對照法已經
驗證過「顯著跑贏安慰劑」的同一個窗口,口徑與原報告完全銜接,且窗口本身結束於last_cover(強制回補
的最後一天),不受除權息還原問題汙染(除權息通常發生在start_date之後的停止融資融券期間內)。

【特徵窗口與outcome窗口的重疊規避】
outcome=pre_dm_10涵蓋[lc-10,lc]。若特徵也用會重疊/相鄰到這段的窗口(例如直接沿用既有的
pre_raw_20,其計算窗口[lc-20,lc]與pre_dm_10重疊10天),會產生機械性的自我相關(不是「特徵預測
結果」而是「結果的一部分就是特徵的一部分」),AUC會虛高。本卷所有「事件前特徵」一律取結束於
lc-11(即outcome窗口正式開始的前一天)的獨立回溯窗口,不重疊,乾淨的樣本外(pre-outcome)設計。

六個特徵角度(每角度主版本+穩健配對版本,配對機制逐字比照build_earnings_winner_features.py的
ROBUST_PAIRS): ①波動度: vol_ann20(20日年化波動)/amp_mean20(20日日均振幅%,穩健配對——同構念
不同運算元); ②型態-回撤: maxdd_pre20/maxdd_pre40(最大回撤%,不同視窗——「誘空後反彈」代理);
③型態-蓄勢: mom_pre20/mom_pre40(pre-outcome窗口本身的**絕對**報酬,非demean,呼應使用者原話
「pre_20絕對報酬本身當連續特徵」); ④型態-K棒: longbar_ratio20/40(單日|收盤/開盤-1|>=3%比例,
長紅長黑代理); ⑤法人籌碼: inst_pct20(外資+投信合計20日累計買超,240日canonical位階,逐字複用
theme卷S4算法)/inst_posday20(20日淨買超天數佔比,穩健配對,inst_flow僅2022-01起短歷史更友善);
⑥對照組(C段舊特徵複測,不因先前不顯著就跳過): short_pct_float/days_to_cover(直接沿用
build_short_covering_pressure.build_events()既有算法,lc-20既有部位,避開回補進行中污染)。

判準/門檻逐字比照build_earnings_winner_features.py: |AUC-0.5|>=0.08(即>=0.58或<=0.42)且月群
(ym=last_cover所在年月,沿用該batch單位)bootstrap 95%CI排除0.5,且win20(前20%,通用穩健版)同向
達>=0.05偏離,且定義配對版同向達>=0.05偏離,三者一致才算通過。通過特徵額外做「跨窗口(pre_dm_5/
pre_dm_20重新定義贏家)」複驗+翻譯成開盤前規則套回全樣本驗證(vs全樣本基準+vs同批case-control),
不只停在AUC層次——這是earnings卷的教訓,AUC有鑑別力不代表規則可交易。

用法: python 研究腳本/融券回補/build_short_covering_winner_features.py (從根目錄執行,鐵律)
產出: 研究報告/research_short_covering_winner_features.html
"""
import json
import sqlite3
import sys
import time

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

import build_short_covering_pressure as P  # 同目錄(python直接執行本檔時sys.path[0]即本目錄,不需額外
                                            # 手動加路徑): load/build_stock_panels/build_events/
                                            # med_win/boot_med/boot_diff/loto/ci_tag/fmt/cell

sys.stdout.reconfigure(encoding="utf-8")

DB = "capital_flow.db"
OUT = "研究報告/research_short_covering_winner_features.html"
rng = np.random.default_rng(20260804)

GREEN, RED, BLUE, YELLOW, GRAY = "#7ec97e", "#e06c5a", "#6bb7e3", "#c3a55a", "#8a8878"
BG = {"paper_bgcolor": "#1a1a19", "plot_bgcolor": "#22221f",
      "font": {"color": "#ddd", "size": 12}, "margin": {"t": 42, "l": 52, "r": 18, "b": 40},
      "legend": {"orientation": "h"}}

OUTCOME = "pre_dm_10"           # last_cover前10日demean報酬,B段已驗證(vs安慰劑顯著)的窗口
FEAT_END_GAP = 11               # 特徵窗口結束於lc-11(outcome窗口[lc-10,lc]開始的前一天),避免重疊
LONGBAR_TH = 3.0                # 長紅/長黑判定門檻(%),|收盤/開盤-1|
AUC_PRESCREEN = 0.03
AUC_PASS_DEV = 0.08
ROBUST_DEV = 0.05
N_ITER_AUC = 600
MIN_POOL = 30
INST_LAG_DAYS_BUF = 15          # inst_flow cutoff calendar緩衝(見compute_inst_flow_feature註記)
INST_STALE_DAYS = 10
RULE_BOOT_ITER = 2000


# ======================================================================
# 0. AUC統計工具(逐字複製自build_earnings_winner_features.py,house既有慣例:純統計函式
#    各winner_features卷各自複製,不跨資料夾import;已核對與sklearn.roc_auc_score完全一致)
# ======================================================================
def calc_auc(a_vals, b_vals):
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


def boot_auc_ci(df, idx_a, idx_b, col, n_iter=N_ITER_AUC, min_n=MIN_POOL):
    """AUC月群bootstrap,批次單位=ym(沿用build_short_covering_pressure既有的last_cover所在年月
    欄位,與本卷其餘中位數bootstrap同一個batch定義,不另外重新derive)。a=case/b=control。"""
    a = df.loc[idx_a, [col, "ym"]].dropna(subset=[col])
    b = df.loc[idx_b, [col, "ym"]].dropna(subset=[col])
    if len(a) < min_n or len(b) < min_n:
        return None
    am = a.groupby("ym")[col].apply(list)
    bm = b.groupby("ym")[col].apply(list)
    months = sorted(set(am.index) | set(bm.index))
    am, bm = am.reindex(months), bm.reindex(months)
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
    auc0 = calc_auc(a[col].values, b[col].values)
    lo, hi = float(np.percentile(aucs, 2.5)), float(np.percentile(aucs, 97.5))
    return {"auc": auc0, "lo": lo, "hi": hi, "sig": bool(lo > 0.5 or hi < 0.5),
            "na": len(a), "nb": len(b), "n_boot": len(aucs)}


def auc_line(label, r):
    if r is None:
        return f"<li>{label}: n太小或分群不足,觀察層(未達bootstrap最低樣本門檻n>={MIN_POOL})</li>"
    sig = "<b>✓排0(顯著偏離0.5)</b>" if r["sig"] else "含0.5(不顯著)"
    passed = " <b>且達0.58/0.42門檻</b>" if abs(r["auc"] - 0.5) >= AUC_PASS_DEV and r["sig"] else ""
    return f"<li>{label}: AUC={r['auc']:.3f} 95%CI[{r['lo']:.3f},{r['hi']:.3f}] {sig}{passed}</li>"


def boot_line2(label, r, key, unit="pp"):
    if r is None:
        return f"<li>{label}: n太小或分群不足,觀察層(未達bootstrap最低樣本門檻)</li>"
    sig = "<b>✓排0(顯著)</b>" if (r["lo"] > 0 or r["hi"] < 0) else "含0(不顯著)"
    return f"<li>{label}: {r[key]:+.2f}{unit} 95%CI[{r['lo']:+.2f},{r['hi']:+.2f}] {sig}</li>"


# ======================================================================
# 1. 事件面板: 直接呼叫build_short_covering_pressure既有函式(不重新定義事件)
# ======================================================================
def load_events_panel():
    susp, px, mf, mfo, idx, mkt_map = P.load()
    panels = P.build_stock_panels(px, idx, mkt_map, mf, mfo)
    df = P.build_events(susp, panels)
    df = df.drop(columns=["_shp_raw", "_shp_dm"])  # 本卷不用CAR形狀矩陣,及早釋放記憶體
    return df, panels, idx, mkt_map


# ======================================================================
# 2. 額外OHLC價格面板(build_short_covering_pressure.load()的px只選了close/volume/money,
#    波動度/型態特徵需要open/high/low,故另外查詢——filter條件(close>0,ORDER BY code,date)與
#    P.load()完全一致,保證與P.build_events()產生的_lc位置索引positionally對齊)
# ======================================================================
def load_ohlc_panels(idx, mkt_map):
    conn = sqlite3.connect(DB, timeout=60)
    px = pd.read_sql("SELECT code, date, open, high, low, close, volume, money "
                     "FROM fm_daily_price WHERE close>0 ORDER BY code, date",
                     conn, parse_dates=["date"])
    conn.close()
    idx_s = {m: g.sort_values("date").set_index("date")["close"] for m, g in idx.groupby("market")}
    panels = {}
    for code, g in px.groupby("code"):
        mkt = mkt_map.get(code)
        if mkt not in ("上市", "上櫃"):
            continue
        g = g.sort_values("date")
        idx_series = idx_s.get("TAIEX" if mkt == "上市" else "TPEx")
        if idx_series is None:
            continue
        idxc = idx_series.reindex(g.date, method="ffill").values
        if np.isnan(idxc).all():
            continue
        close = g.close.values
        opn = g.open.values
        # 長紅/長黑旗標(單日,收盤/開盤): |close/open-1|>=LONGBAR_TH%,open<=0時留NaN
        with np.errstate(invalid="ignore", divide="ignore"):
            body_pct = np.where(opn > 0, np.abs(close / opn - 1) * 100, np.nan)
        longflag = (body_pct >= LONGBAR_TH).astype(float)
        longflag[np.isnan(body_pct)] = np.nan
        panels[code] = {"date": g.date.values, "close": close, "open": opn,
                        "high": g.high.values, "low": g.low.values, "longflag": longflag}
    print(f"[ohlc] OHLC面板建立: {len(panels):,}檔", flush=True)
    return px, panels


# ======================================================================
# 3. 波動度/型態特徵(全部price-based,窗口結束於lc-FEAT_END_GAP,不與outcome窗口重疊)
#    同時回傳cutoff_date(供inst_flow merge_asof用,=該截止索引當天的實際交易日期)
# ======================================================================
def compute_price_features(df, ohlc_panels):
    names = ["vol_ann20", "amp_mean20", "maxdd_pre20", "maxdd_pre40",
             "mom_pre20", "mom_pre40", "longbar_ratio20", "longbar_ratio40"]
    out = {n: np.full(len(df), np.nan) for n in names}
    cutoff_date = np.full(len(df), np.datetime64("NaT"), dtype="datetime64[ns]")
    n_no_panel = 0
    codes_arr = df["code"].values
    lc_arr = df["_lc"].values  # itertuples()會把"_lc"重新命名(namedtuple不接受底線開頭欄位),
                                # 故改用array直接位置對齊迭代,避免屬性名稱衝突
    for pos in range(len(df)):
        pan = ohlc_panels.get(codes_arr[pos])
        if pan is None:
            n_no_panel += 1
            continue
        lc = int(lc_arr[pos])
        close, high, low = pan["close"], pan["high"], pan["low"]
        n = len(close)
        end = lc - FEAT_END_GAP
        if end < 0 or end >= n:
            continue
        cutoff_date[pos] = pan["date"][end]

        def window(win_n):
            s = end - win_n + 1
            if s < 0:
                return None
            return s, end + 1  # [s, e) 半開區間

        # ① 波動度: vol_ann20(20日年化波動,std of log return) / amp_mean20(20日日均振幅%,穩健配對)
        w = window(20)
        if w is not None:
            s, e = w
            c = close[s:e]
            hi, lo = high[s:e], low[s:e]
            if len(c) == 20 and np.all(c > 0):
                r = np.diff(np.log(c))
                if len(r) >= 10:
                    out["vol_ann20"][pos] = float(np.std(r, ddof=1) * np.sqrt(252) * 100)
                amp = np.where((c > 0) & np.isfinite(hi) & np.isfinite(lo), (hi - lo) / c * 100, np.nan)
                if np.isfinite(amp).sum() >= 10:
                    out["amp_mean20"][pos] = float(np.nanmean(amp))

        # ② 型態-回撤: maxdd_pre20/40(最大回撤%,「誘空後反彈」代理——回撤越深,若後續有反彈張力越大)
        for win_n, key in ((20, "maxdd_pre20"), (40, "maxdd_pre40")):
            w = window(win_n)
            if w is None:
                continue
            s, e = w
            c = close[s:e]
            if len(c) == win_n and np.all(c > 0):
                runmax = np.maximum.accumulate(c)
                dd = (c / runmax - 1) * 100
                out[key][pos] = float(dd.min())

        # ③ 型態-蓄勢: mom_pre20/40(pre-outcome窗口本身的絕對報酬,非demean,呼應使用者原話)
        for win_n, key in ((20, "mom_pre20"), (40, "mom_pre40")):
            s = end - win_n
            if s < 0:
                continue
            c_end, c_start = close[end], close[s]
            if c_start > 0:
                out[key][pos] = float((c_end / c_start - 1) * 100)

        # ④ 型態-K棒: longbar_ratio20/40(單日|收盤/開盤-1|>=3%比例,%)
        longflag = pan["longflag"]
        for win_n, key in ((20, "longbar_ratio20"), (40, "longbar_ratio40")):
            w = window(win_n)
            if w is None:
                continue
            s, e = w
            f = longflag[s:e]
            if np.isfinite(f).sum() >= win_n * 0.7:
                out[key][pos] = float(np.nanmean(f) * 100)

    for n in names:
        df[n] = out[n]
    df["_feat_cutoff"] = cutoff_date
    print(f"[feature] 價格類特徵(①波動度②回撤③蓄勢④K棒): 無OHLC面板略過{n_no_panel}筆")
    for n in names:
        print(f"  {n}: 可用n={df[n].notna().sum():,}")
    return df


# ======================================================================
# 4. 法人籌碼特徵(外資+投信合計淨買超,逐字複用build_earnings_winner_features.py的
#    compute_inst_flow_feature S4 canonical算法,cutoff改用每筆事件實際的_feat_cutoff交易日
#    ——比用固定日曆天數更精確,避開連假造成的cutoff落在outcome窗口內的邊界風險)
# ======================================================================
def compute_inst_flow_feature(df):
    conn = sqlite3.connect(DB, timeout=60)
    fl = pd.read_sql("SELECT date, code, foreign_net, trust_net FROM inst_flow", conn, parse_dates=["date"])
    conn.close()
    fl["combo"] = fl.foreign_net + fl.trust_net
    wide = fl.pivot_table(index="date", columns="code", values="combo").sort_index()
    roll20 = wide.rolling(20, min_periods=10).sum()
    pct240 = roll20.rolling(240, min_periods=120).rank(pct=True) * 100
    valid = wide.notna()
    posday20 = ((wide > 0) & valid).rolling(20, min_periods=15).sum() / \
        valid.rolling(20, min_periods=15).sum() * 100

    long_pct = pct240.stack().rename_axis(["date", "code"]).reset_index(name="pct").sort_values("date")
    long_pos = posday20.stack().rename_axis(["date", "code"]).reset_index(name="pos").sort_values("date")

    evx = pd.DataFrame({"code": df["code"].values, "cutoff": df["_feat_cutoff"].values,
                        "orig_idx": df.index}).dropna(subset=["cutoff"]).sort_values("cutoff")
    m_pct = pd.merge_asof(evx, long_pct, left_on="cutoff", right_on="date", by="code",
                          direction="backward", tolerance=pd.Timedelta(days=INST_STALE_DAYS))
    m_pos = pd.merge_asof(evx, long_pos, left_on="cutoff", right_on="date", by="code",
                          direction="backward", tolerance=pd.Timedelta(days=INST_STALE_DAYS))
    m_pct = m_pct.set_index("orig_idx").reindex(df.index)
    m_pos = m_pos.set_index("orig_idx").reindex(df.index)
    df["inst_pct20"] = m_pct["pct"]
    df["inst_posday20"] = m_pos["pos"]
    print(f"[feature] ⑤法人籌碼(外資+投信合計): inst_pct20(canonical位階)可用"
          f"{df.inst_pct20.notna().sum():,} inst_posday20(天數佔比)可用{df.inst_posday20.notna().sum():,}"
          f"(inst_flow僅2022-01起,更早期事件此特徵天生NaN)")
    return df


# ======================================================================
# 5. 贏家/輸家分組 + 同批(ym=last_cover所在年月,沿用既有欄位)case-control對照組
# ======================================================================
def case_control_events(win_idx, df, seed):
    rng2 = np.random.default_rng(seed)
    win_set = set(win_idx)
    sub = df.loc[win_idx]
    ctrl_idx = []
    for ym, g in sub.groupby("ym"):
        pool = list(df.index[(df["ym"] == ym) & (~df.index.isin(win_set))])
        if not pool:
            continue
        k = min(len(g), len(pool))
        chosen = rng2.choice(pool, size=k, replace=False)
        ctrl_idx.extend(chosen)
    return pd.Index(ctrl_idx)


def build_groups(df):
    groups = {}
    valid = df[OUTCOME].dropna()
    rnk = valid.rank(pct=True)
    defs = {"win10": rnk >= 0.90, "win20": rnk >= 0.80, "lose10": rnk <= 0.10}
    seeds = {"win10": 20260804, "win20": 20260805, "lose10": 20260806}
    for name, cond in defs.items():
        idx = rnk[cond].index
        ctrl = case_control_events(idx, df, seed=seeds[name])
        groups[name] = {"idx": idx, "ctrl_idx": ctrl, "n": len(idx), "n_ctrl": len(ctrl)}
        print(f"[groups] {name}({OUTCOME}分位定義): 事件{len(idx):,} / 對照組{len(ctrl):,}")

    # 跨窗口(pre_dm_5/pre_dm_20)贏家定義穩健性複驗,比照earnings卷win10_k5/k10精神
    for alt_k, alt_col in ((5, "pre_dm_5"), (20, "pre_dm_20")):
        validk = df[alt_col].dropna()
        rnkk = validk.rank(pct=True)
        idx = rnkk[rnkk >= 0.90].index
        ctrl = case_control_events(idx, df, seed=20260807 + alt_k)
        groups[f"win10_pre{alt_k}"] = {"idx": idx, "ctrl_idx": ctrl, "n": len(idx), "n_ctrl": len(ctrl)}
        print(f"[groups] win10_pre{alt_k}(跨窗口贏家定義穩健性用): 事件{len(idx):,} / 對照組{len(ctrl):,}")
    return groups


# ======================================================================
# 6. 特徵清單 + 全特徵點估計掃描 + 候選bootstrap + 通過判定
# ======================================================================
FEATURES = ["vol_ann20", "amp_mean20", "maxdd_pre20", "maxdd_pre40", "mom_pre20", "mom_pre40",
            "longbar_ratio20", "longbar_ratio40", "inst_pct20", "inst_posday20",
            "short_pct_float", "days_to_cover"]

FEATURE_LABEL = {
    "vol_ann20": "①20日年化波動(%)", "amp_mean20": "①20日日均振幅%(穩健配對)",
    "maxdd_pre20": "②型態-20日最大回撤%(誘空代理)", "maxdd_pre40": "②型態-40日最大回撤%(穩健配對)",
    "mom_pre20": "③型態-pre窗口前20日絕對報酬%(蓄勢)", "mom_pre40": "③型態-前40日絕對報酬%(穩健配對)",
    "longbar_ratio20": "④型態-20日長紅長黑比例%(K棒)", "longbar_ratio40": "④型態-40日長紅長黑比例%(穩健配對)",
    "inst_pct20": "⑤外資+投信20日買超位階(canonical,百分位)", "inst_posday20": "⑤外資+投信20日淨買超天數佔比%(穩健配對)",
    "short_pct_float": "⑥對照組-短占股本比%(C段舊特徵)", "days_to_cover": "⑥對照組-回補天數(C段舊特徵,穩健配對)",
}
ROBUST_PAIRS = {"vol_ann20": "amp_mean20", "amp_mean20": "vol_ann20",
                "maxdd_pre20": "maxdd_pre40", "maxdd_pre40": "maxdd_pre20",
                "mom_pre20": "mom_pre40", "mom_pre40": "mom_pre20",
                "longbar_ratio20": "longbar_ratio40", "longbar_ratio40": "longbar_ratio20",
                "inst_pct20": "inst_posday20", "inst_posday20": "inst_pct20",
                "short_pct_float": "days_to_cover", "days_to_cover": "short_pct_float"}


def feat_vals(df, col, idx):
    return df.loc[idx, col].dropna().values.astype(float)


def scan_point_estimates(df, groups):
    rows = []
    for name in FEATURES:
        rec = {"feature": name}
        for gname in ("win10", "win20", "lose10"):
            g = groups[gname]
            cv = feat_vals(df, name, g["idx"])
            kv = feat_vals(df, name, g["ctrl_idx"])
            auc = calc_auc(cv, kv)
            rec[gname] = {"auc": auc, "n": len(cv), "n_ctrl": len(kv)}
        rows.append(rec)
    return rows


def run_bootstrap_candidates(rows, df, groups):
    boot = {}
    idx = {r["feature"]: r for r in rows}
    candidates = [r["feature"] for r in rows if pd.notna(r["win10"]["auc"])
                  and abs(r["win10"]["auc"] - 0.5) >= AUC_PRESCREEN]
    print(f"[boot] 點估計偏離>=±{AUC_PRESCREEN}的候選特徵 {len(candidates)}/{len(rows)}: {candidates}")

    to_boot = set((("win10", name) for name in candidates))
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
        g = groups[gname]
        r = boot_auc_ci(df, g["idx"], g["ctrl_idx"], name)
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
# 7. 跨窗口(pre_dm_5/pre_dm_20)贏家定義穩健性複驗(僅通過特徵,點估計層級)
# ======================================================================
def window_consistency(passed_names, df, groups):
    out = {}
    for name in passed_names:
        rows = []
        for gname, glabel in (("win10", "pre_dm_10主判讀"), ("win10_pre5", "pre_dm_5窗定義"),
                              ("win10_pre20", "pre_dm_20窗定義")):
            g = groups[gname]
            cv = feat_vals(df, name, g["idx"])
            kv = feat_vals(df, name, g["ctrl_idx"])
            auc = calc_auc(cv, kv) if len(cv) >= MIN_POOL and len(kv) >= MIN_POOL else np.nan
            rows.append((glabel, auc, len(cv)))
        out[name] = rows
        print(f"[window] {name} 跨窗口定義AUC: " + ", ".join(
            f"{lb}={a:.3f}(n={n})" if pd.notna(a) else f"{lb}=n太小" for lb, a, n in rows))
    return out


# ======================================================================
# 8. 規則翻譯 + 驗證(僅通過特徵;全樣本cross-sectional前10%/後10%當「開盤前規則」,
#    驗證規則篩出的股票outcome=pre_dm_10是否顯著優於全樣本基準+同批case-control,
#    中位數bootstrap直接複用build_short_covering_pressure.boot_med/boot_diff,不重新發明)
# ======================================================================
def build_rule(name, direction, df):
    valid = df[name].dropna()
    rnk = valid.rank(pct=True)
    return rnk[rnk >= 0.90].index if direction > 0 else rnk[rnk <= 0.10].index


def eval_rule(label, rule_idx, df, seed):
    n = len(rule_idx)
    sub = df.loc[rule_idx, [OUTCOME, "ym", "year"]].dropna(subset=[OUTCOME])
    if len(sub) < 15:
        print(f"[rule] {label}: n太小({OUTCOME}可用n={len(sub)}),跳過")
        return None

    base_pop = df[OUTCOME].dropna()
    base_med = float(base_pop.median())
    m_boot_vs_base = P.boot_med(sub.assign(value=sub[OUTCOME] - base_med))

    ctrl = case_control_events(rule_idx, df, seed=seed)
    ctrl_sub = df.loc[ctrl, [OUTCOME, "ym", "year"]].dropna(subset=[OUTCOME])
    diff = P.boot_diff(sub.assign(value=sub[OUTCOME]), ctrl_sub.assign(value=ctrl_sub[OUTCOME]))

    hit_rate = float((sub[OUTCOME] > 0).mean()) * 100
    base_hit = float((base_pop > 0).mean()) * 100
    pos, tot = P.loto(sub.assign(value=sub[OUTCOME]))

    print(f"[rule] {label}: n={n:,}({OUTCOME}可用{len(sub):,}) 中位{sub[OUTCOME].median():+.2f}%"
          f"(全樣本基準{base_med:+.2f}%) 命中率{hit_rate:.1f}%(基準{base_hit:.1f}%) "
          f"對照組n={len(ctrl_sub):,} 逐年{pos}/{tot}正")

    return {"label": label, "n": n, "n_valid": len(sub), "n_ctrl": len(ctrl_sub),
            "med": float(sub[OUTCOME].median()), "base_med": base_med,
            "hit_rate": hit_rate, "base_hit": base_hit, "loto": (pos, tot),
            "boot_vs_base": m_boot_vs_base, "boot_vs_ctrl": diff}


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
# 9. 三問機制文字(依特徵類別套用,逐項比照earnings卷格式)
# ======================================================================
THREE_Q = {
    "vol": ("波動度",
            "誰被迫交易?——波動度本身不是交易行為,是價格路徑的統計特徵;但高波動股常伴隨較大的"
            "多空交火(含融券部位進出),若高波動股在last_cover前更容易出現急拉,可能反映「波動本身"
            "放大了回補力道的價格衝擊(同樣的張數,流動性/慣性較弱的高波動股價格衝擊更大)」。",
            "資訊是新的嗎?——波動度是最公開的市場統計量,任何人皆可即時計算,無資訊優勢可言。",
            "為何別人沒吃掉它?——若高波動與後續pre窗口報酬有關,較可能反映的是「高波動股本身流動性"
            "較薄,同樣的被迫買盤造成的價格衝擊更難被套利抹平」,而非發現了獨立的新訊號;此類效應"
            "理論上難以穩定套利(進出成本本身也隨波動放大)。"),
    "pattern": ("型態(回撤/蓄勢/K棒)",
                "誰被迫交易?——型態特徵(回撤深度/前段報酬/長紅長黑比例)本身描述的是价格路徑,"
                "不直接對應特定被迫交易者;但深度回撤後的技術性反彈,常伴隨空單回補與逢低買盤"
                "交織,難以單純歸類。",
                "資訊是新的嗎?——股價路徑是最公開的資訊,任何人都能觀察到過去回撤/漲跌幅/K棒型態。",
                "為何別人沒吃掉它?——若型態特徵與pre窗口報酬有鑑別力,較可能反映「動能延續」或"
                "「均值回歸」這類經典且被廣泛研究的價格異常現象的變形,而非本卷特有的新機制;"
                "此類效應在學術文獻中已知普遍存在套利限制(反轉時機難以精準掌握)。"),
    "inst": ("法人籌碼(外資+投信合計買賣超)",
             "誰被迫交易?——外資/投信是機構法人,交易多為主動性研究驅動(自願),但部分被動指數"
             "基金的申贖/成分股調整屬於「非資訊驅動」的機械性交易,兩者混在同一個net欄位裡無法"
             "從資料本身區分。",
             "資訊是新的嗎?——外資/投信買賣超是T+1即可取得的高頻公開資訊,是全市場最被密切關注"
             "的籌碼指標之一,理論上早已被市場充分消化。",
             "為何別人沒吃掉它?——若此特徵仍通過AUC門檻,較可能反映的是法人買賣超本身與後續股價"
             "表現的動能延續性(法人買什麼漲什麼),而非法人真的預先看穿融券回補的時點與力道,"
             "此為經典動能因子的變形,不必然是「強制回補特有」的訊號。"),
    "short": ("對照組(短占股本比/回補天數,C段舊特徵)",
              "誰被迫交易?——這兩個特徵直接衡量融券未回補部位的規模,是本卷機制故事中「被迫買方」"
              "力道最直接的代理變數,若通過本卷更寬鬆的AUC門檻(相對C段三分位梯度檢定),代表換一種"
              "統計方法後仍能偵測到訊號。",
              "資訊是新的嗎?——margin_flow融券餘額資料是公開的(次日可查詢),理論上早已被市場充分"
              "消化,不是新資訊。",
              "為何別人沒吃掉它?——C段三分位梯度檢定已顯示這兩個特徵在原始設計下沒有梯度"
              "(CI含0),本段是用不同統計方法(AUC vs 三分位中位數比較)在同一批舊特徵上再測一次,"
              "若依然不顯著,兩種方法互相印證,對「融券強度本身無法預測pre窗口報酬」這個結論的"
              "信心應該提高;若出現不一致,需誠實檢討兩種方法的敏感度差異,不應選對自己有利的一種。"),
}


def feature_category(name):
    if name.startswith("vol") or name.startswith("amp"):
        return "vol"
    if name.startswith("maxdd") or name.startswith("mom_pre") or name.startswith("longbar"):
        return "pattern"
    if name.startswith("inst"):
        return "inst"
    return "short"


# ======================================================================
# 10. HTML 呈現(CSS/版型逐字比照build_earnings_winner_features.py深色主題)
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
.banner{background:#3a2a1a;border:1px solid #c3a55a;border-radius:6px;padding:14px 18px;margin:16px 0;
        color:#f0dfa8;font-size:13.5px;line-height:1.8}
"""


def write_report(df, ev_summary, rows, boot, groups, passed, window_out, rules, outcome_evidence):
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

    boot_lines, seen = [], set()
    for r in rows:
        name = r["feature"]
        for gname, glabel in (("win10", "前10%贏家(pre_dm_10)"), ("win20", "前20%贏家(穩健版)"),
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
        p1_cls, p1_txt = "v-warn", "🟡無特徵通過0.58/0.42門檻+穩健度要求(誠實null結果,與C段三分位梯度不顯著方向一致)"

    rule_rows_html, rule_boot_html = [], []
    any_rule_sig_good = False
    for name, r in rules.items():
        if r is None:
            rule_rows_html.append(f"<tr><th>{FEATURE_LABEL.get(name, name)}</th><td colspan='2'>n太小,無法驗證</td></tr>")
            continue
        rule_rows_html.append(
            f"<tr><th>{r['label']}(n={r['n']:,},{OUTCOME}可用{r['n_valid']:,})</th>"
            f"<td>{r['med']:+.2f}%<br><span class='sub'>基準{r['base_med']:+.2f}%</span></td>"
            f"<td>{r['hit_rate']:.1f}%<br><span class='sub'>基準{r['base_hit']:.1f}%,逐年{r['loto'][0]}/{r['loto'][1]}正</span></td></tr>")
        rule_boot_html.append(f"<h3>{r['label']}</h3><ul>"
            + boot_line2(f"{OUTCOME}中位數 vs全樣本基準(excess)", r["boot_vs_base"], "med", unit="%")
            + boot_line2(f"{OUTCOME}中位數 vs case-control同批對照組", r["boot_vs_ctrl"], "diff", unit="%")
            + "</ul>")
        if r["boot_vs_ctrl"] is not None and (r["boot_vs_ctrl"]["lo"] > 0 or r["boot_vs_ctrl"]["hi"] < 0) \
                and r["boot_vs_ctrl"]["diff"] > 0:
            any_rule_sig_good = True
    rule_table = (f"<table><tr><th>開盤前(last_cover前)規則</th><th>{OUTCOME}中位數(基準版)</th>"
                  f"<th>{OUTCOME}命中率(基準版)</th></tr>" + "".join(rule_rows_html) + "</table>") if rules else \
        "<div class='note'>無通過特徵,無規則可翻譯驗證。</div>"
    rule_boot = "".join(rule_boot_html)

    if not passed:
        p2_cls, p2_txt = "v-warn", "🟡第一階段無特徵通過,第二階段無規則可翻譯(誠實null結果)"
    elif any_rule_sig_good:
        p2_cls, p2_txt = "v-good", "✅至少一條開盤前規則,其pre_dm_10(vs case-control)顯著優於對照組"
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
    payload_json = json.dumps({"c1": c1, "c2": c2}, ensure_ascii=False)

    outcome_txt = (
        f"post_dm_10(last_cover之後10日demean報酬)全樣本中位{outcome_evidence['post_all']:+.2f}%,"
        f"但拆桶後除權息桶(n={outcome_evidence['post_ex_n']:,})中位{outcome_evidence['post_ex']:+.2f}%/"
        f"勝率{outcome_evidence['post_ex_win']:.1f}%,股東會桶(n={outcome_evidence['post_ag_n']:,})"
        f"中位{outcome_evidence['post_ag']:+.2f}%/勝率{outcome_evidence['post_ag_win']:.1f}%——"
        f"差距達{outcome_evidence['post_ex'] - outcome_evidence['post_ag']:+.2f}pp,遠超合理的機制解釋範圍,"
        "極可能是fm_daily_price收盤價未做除權息還原(原報告限制⑤已知)造成的機械性缺口,"
        "而非真實訊號——若拿post窗口當贏家/輸家的結果變數,任何與「除權息規模」相關的特徵"
        "都會產生假陽性AUC。故本卷改用已在B段驗證過的pre_dm_10當結果變數,詳見下方說明。")

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>強制回補贏家/輸家逆向工程特徵×AUC考卷(2026-08-04)</title>
<script src="plotly.min.js"></script><style>{CSS}</style></head><body>
<h1>🔍 強制回補「贏家/輸家」逆向工程特徵×AUC case-control考卷</h1>
<div class="note">承接<code>build_short_covering_pressure.py</code>(強制回補價格壓力考卷):
A段主檢定不顯著(pre_dm_10全樣本CI含0),B段案例對照顯著(vs同股安慰劑,+0.74pp CI排0),
C段強度分層(短占股本比/回補天數三分位)無梯度。使用者質疑「沒有研究到回補的力道有多強——
波動度/型態/法人籌碼是否都納入?」並建議逆向工程: 先找pre窗口報酬前10%/後10%的事件,回頭挖掘
公開特徵有無鑑別力。方法論逐字比照<code>build_earnings_winner_features.py</code>: AUC(rank-sum)+
月群(ym=last_cover所在年月)bootstrap+case-control,判準|AUC-0.5|&gt;={AUC_PASS_DEV}(即&gt;=0.58
或&lt;=0.42)且CI排除0.5,且win20穩健版與定義配對版同向達&gt;={ROBUST_DEV}偏離,三者一致才算通過。</div>

<div class="banner">⚠<b>結果變數(outcome)選擇的關鍵決策</b>: {outcome_txt}</div>

<h2>📋 資料覆蓋</h2>
<table><tr><th>項目</th><th>數字</th></tr>
<tr><th>事件面板(承接build_short_covering_pressure,last_cover錨點+去重後)</th>
<td>{ev_summary['n']:,}筆 / {ev_summary['n_codes']:,}檔 / {ev_summary['date_min']}~{ev_summary['date_max']}</td></tr>
<tr><th>outcome={OUTCOME}可用</th><td>{ev_summary['n_outcome']:,}筆</td></tr>
<tr><th>margin_flow強度特徵(short_pct_float/days_to_cover,2022-01起)</th><td>{ev_summary['n_margin']:,}筆</td></tr>
<tr><th>inst_flow法人特徵(2022-01起,另需240日暖機)</th><td>{ev_summary['n_inst']:,}筆</td></tr>
</table>

<h2>① 贏家/輸家定義</h2>
<div class="note">outcome={OUTCOME}(last_cover前10日demean報酬,B段已驗證顯著跑贏安慰劑的窗口)。
win10=全樣本排名前10%(主判讀贏家),win20=前20%(穩健對照),lose10=後10%(對稱性檢定);
另建win10_pre5/win10_pre20(用pre_dm_5/pre_dm_20重新定義贏家)供「贏家定義本身」跨窗口穩健性複驗。
特徵窗口一律結束於lc-{FEAT_END_GAP}(outcome窗口[lc-10,lc]開始的前一天),避免特徵與結果窗口重疊
產生機械性自我相關。</div>
<table><tr><th>組別</th><th>定義</th><th>事件數</th><th>對照組事件數</th></tr>
{"".join(f"<tr><th>{gname}</th><td>{glabel}</td><td>{groups[gname]['n']:,}</td><td>{groups[gname]['n_ctrl']:,}</td></tr>"
  for gname, glabel in (("win10", f"{OUTCOME}排名前10%(主判讀)"), ("win20", f"{OUTCOME}排名前20%(穩健對照)"),
                        ("lose10", f"{OUTCOME}排名後10%(對稱檢定)"),
                        ("win10_pre5", "pre_dm_5排名前10%(跨窗口穩健性用)"),
                        ("win10_pre20", "pre_dm_20排名前10%(跨窗口穩健性用)")))}
</table>

<h2>② 全特徵點估計AUC掃描(誠實列出全部{len(rows)}個特徵版本,不是只列贏家)</h2>
<div class="note">AUC=0.5代表無鑑別力,&gt;0.5代表特徵值越大越可能是贏家,&lt;0.5代表相反。
🔬=點估計|AUC-0.5|&gt;={AUC_PRESCREEN}進入bootstrap候選;✅=最終通過穩健度門檻。
⑥對照組(short_pct_float/days_to_cover)即C段已測過的兩個強度代理變數,本段用不同統計方法
(AUC vs 三分位中位數)再測一次,不因先前不顯著就跳過。</div>
{scan_table}

<h2>③ 候選特徵bootstrap明細(月群重抽樣n_iter={N_ITER_AUC},95%CI)</h2>
{boot_html}

<h2>④ 通過穩健度門檻的特徵</h2>
<table><tr><th>階段</th><th>核心問題</th><th>判讀</th></tr>
<tr><th>第一階段:逆向工程AUC篩選</th><td>贏家事件前特徵是否有鑑別力(vs同批case-control)</td>
<td><span class="verdict {p1_cls}">{p1_txt}</span></td></tr>
<tr><th>第二階段:規則翻譯+驗證</th><td>把通過特徵翻成事件前可用規則,套回全樣本驗證{OUTCOME}是否顯著優於
基準/case-control</td><td><span class="verdict {p2_cls}">{p2_txt}</span></td></tr></table>
{pass_table}

<h3>跨窗口(pre_dm_5/pre_dm_20)贏家定義穩健性複驗(僅通過特徵)</h3>
{window_table if passed else "<div class='note'>無通過特徵可供複驗。</div>"}

<h2>⑤ 三問機制討論(誰被迫交易?/資訊是新的嗎?/為何別人沒吃掉它?)</h2>
{three_q_html}

<h2>⑥ 第二階段: 規則翻譯 + 驗證(套回全樣本,非贏家組內自我循環驗證)</h2>
<div class="note">規則=通過特徵在「全樣本」cross-sectional排名前10%(或後10%,依AUC方向決定),
驗證規則篩出的事件,其{OUTCOME}是否顯著優於全樣本基準(常數)與同批case-control對照組
(排除規則命中事件後隨機抽同數量,net掉批次層的共同成分)。中位數bootstrap直接複用
build_short_covering_pressure.py既有的boot_med/boot_diff/loto函式。</div>
{rule_table}
<h3>bootstrap顯著性(vs全樣本基準 + vs case-control同批對照組)</h3>
{rule_boot}

<h2>📈 圖表</h2>
<div class="note">c1=win10 AUC點估計偏離0.5最大的前12個特徵版本(綠=通過穩健度門檻,黃=進入bootstrap
候選但未通過,灰=未進候選);c2=第二階段各規則{OUTCOME}中位數excess(vs全樣本基準,pp)。</div>
<div id="c1" style="height:380px"></div>
<div id="c2" style="height:320px"></div>

<h2>已知限制與方法論不確定處(誠實聲明)</h2>
<div class="note">
①<b>結果變數選擇</b>: 用pre_dm_10(last_cover前10日)而非任務原本建議字面上的「post-event」窗口,
理由見上方banner(post窗口被除權息未還原污染)。這代表本卷回答的問題其實是「哪些特徵能區分last_cover
前『漲得多的』vs『漲得少的』事件」,不是「哪些特徵能預測回補結束後接下來會不會續漲」——後者因資料
限制(股息未還原)本卷無法乾淨回答,是誠實的能力邊界,非迴避。<br>
②<b>Multiple comparison</b>: 本卷同時掃描{len(rows)}個特徵版本(win10+win20+lose10三組×
{len(FEATURES)}個特徵),即使全部特徵都是純雜訊,依95%CI規則預期仍會有約
{len(rows) * 0.05:.0f}個「碰巧」顯著排0的個案;已用「win20+定義配對版三重一致」作為實質多重比較
管控門檻,結論應視為「候選假說」而非「已驗證定律」。<br>
③<b>資料涵蓋期不對稱</b>: inst_pct20/inst_posday20/short_pct_float/days_to_cover僅margin_flow/
inst_flow覆蓋期(2022-01起)可算,樣本縮水為約{min(ev_summary['n_margin'], ev_summary['n_inst']):,}
~{max(ev_summary['n_margin'], ev_summary['n_inst']):,}筆(僅約4.5年單一regime),價格類特徵
(波動度/型態)則涵蓋2005年至今全樣本,兩類特徵的統計檢定力不對稱,解讀時需留意n數差異。<br>
④<b>特徵窗口與outcome窗口的分隔是lc-{FEAT_END_GAP}這條線,非絕對無漏洞</b>: 選擇lc-{FEAT_END_GAP}
是為了確保與outcome窗口[lc-10,lc]完全不重疊(留1個交易日緩衝),但這條線本身是研究者選擇,並非
market microstructure上的必然分界,不同的緩衝天數理論上可能得到略有差異的AUC點估計(未做緩衝天數
敏感度分析)。<br>
⑤<b>inst_flow特徵cutoff用逐筆事件實際交易日期</b>(非固定日曆天數),經merge_asof容忍
{INST_STALE_DAYS}天內的最近快照,若某事件前{INST_STALE_DAYS}天內inst_flow剛好缺資料(非交易日
外的資料缺漏),該筆特徵會是NaN,不會用更早的過期資料頂替。<br>
⑥<b>長紅長黑門檻(|收盤/開盤-1|&gt;={LONGBAR_TH}%)為研究者選定的寬鬆門檻</b>,未做門檻敏感度分析;
maxdd/longbar/mom類特徵之間彼此並非完全獨立(同源於同一段價格路徑),AUC若同時通過,不代表三個
是三個獨立的訊號來源。<br>
⑦所有數字為觀察層/盤點層,不涉及交易成本、滑價、實際下單可執行性,亦不預設上板;第二階段規則
驗證雖然用了與訓練無關的「全樣本重新篩選+case-control」設計,但仍是同一批歷史資料上的樣本內
(in-sample)驗證,非真正的樣本外(out-of-sample)前瞻測試。
</div>
<div class="note">維運: python 研究腳本/融券回補/build_short_covering_winner_features.py(從根目錄
執行,鐵律)。姊妹檔: build_short_covering_pressure.py(本卷承接的原始A/B/C/D段考卷,事件面板/
last_cover錨點/去重規則的唯一定義來源)、build_earnings_winner_features.py(本卷比照的AUC+
case-control方法論先例)。</div>

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
bar('c2', '⑥ 第二階段規則: {OUTCOME}中位數excess(vs全樣本基準,pp)', D.c2, 'excess(%)', 0);
</script>
</body></html>"""
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[report] 已輸出 {OUT}")


# ======================================================================
# 11. main
# ======================================================================
def main():
    t0 = time.time()
    selfcheck_auc()

    print("=" * 60, "\n[main] 事件面板(直接呼叫build_short_covering_pressure既有函式)")
    df, panels, idx, mkt_map = load_events_panel()

    # outcome選擇證據: post_dm_10除權息桶 vs 股東會桶差距(banner用)
    outcome_evidence = {
        "post_all": float(df["post_dm_10"].median()),
        "post_ex": float(df.loc[df.bucket == "除權息", "post_dm_10"].median()),
        "post_ex_win": float((df.loc[df.bucket == "除權息", "post_dm_10"] > 0).mean()) * 100,
        "post_ex_n": int(df.loc[df.bucket == "除權息", "post_dm_10"].notna().sum()),
        "post_ag": float(df.loc[df.bucket == "股東會", "post_dm_10"].median()),
        "post_ag_win": float((df.loc[df.bucket == "股東會", "post_dm_10"] > 0).mean()) * 100,
        "post_ag_n": int(df.loc[df.bucket == "股東會", "post_dm_10"].notna().sum()),
    }
    print(f"[outcome] post_dm_10 除權息桶中位{outcome_evidence['post_ex']:+.2f}% vs "
          f"股東會桶中位{outcome_evidence['post_ag']:+.2f}% (差{outcome_evidence['post_ex']-outcome_evidence['post_ag']:+.2f}pp"
          f",判定為除權息未還原的機械性缺口,故不用post窗口當outcome)")

    print("=" * 60, "\n[main] OHLC面板(波動度/型態特徵用)")
    _, ohlc_panels = load_ohlc_panels(idx, mkt_map)

    print("=" * 60, "\n[main] ①②③④ 價格類特徵計算")
    df = compute_price_features(df, ohlc_panels)

    print("=" * 60, "\n[main] ⑤ 法人籌碼特徵計算")
    df = compute_inst_flow_feature(df)

    ev_summary = {"n": len(df), "n_codes": df.code.nunique(),
                  "date_min": str(df.last_cover_date.min().date()), "date_max": str(df.last_cover_date.max().date()),
                  "n_outcome": int(df[OUTCOME].notna().sum()),
                  "n_margin": int(df["short_pct_float"].notna().sum()),
                  "n_inst": int(df["inst_pct20"].notna().sum())}
    print(f"[main] 特徵面板: {len(df):,}筆 x {df.shape[1]}欄")

    print("=" * 60, "\n[main] 贏家/輸家分組 + 同批case-control")
    groups = build_groups(df)

    print("=" * 60, "\n[main] 第一階段: 全特徵點估計掃描")
    rows = scan_point_estimates(df, groups)
    for r in sorted(rows, key=lambda x: -abs(x["win10"]["auc"] - 0.5) if pd.notna(x["win10"]["auc"]) else -1):
        a10 = r["win10"]["auc"]
        if pd.notna(a10):
            print(f"  {r['feature']:<18} win10={a10:.3f}(n={r['win10']['n']:,}) "
                  f"win20={r['win20']['auc']:.3f} lose10={r['lose10']['auc']:.3f}")
        else:
            print(f"  {r['feature']:<18} n太小/全NaN")

    print("=" * 60, "\n[main] 候選特徵bootstrap")
    boot = run_bootstrap_candidates(rows, df, groups)

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

    print("=" * 60, "\n[main] 跨窗口(pre_dm_5/pre_dm_20)贏家定義穩健性複驗")
    window_out = window_consistency(passed, df, groups) if passed else {}

    print("=" * 60, "\n[main] 第二階段: 規則翻譯 + 驗證")
    rules = build_phase2_rules(passed, boot, df) if passed else {}

    print("=" * 60, "\n[main] 組裝報告")
    write_report(df, ev_summary, rows, boot, groups, passed, window_out, rules, outcome_evidence)
    print(f"[main] 全部完成,總耗時{time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
