# -*- coding: utf-8 -*-
"""當沖客贏家日逆向工程特徵case-control考卷+可交易性回測(2026-08-01,使用者指定套用本專案
「頂部無指紋定理」既有方法論:逆向工程一律配對照組+AUC鑑別力檢定,不得看到贏家長相就下結論)。

背景/動機: 之前幾份當沖考卷(build_dtlend_report.py四題、build_dtlend_pattern_pnl.py兩型態)都是
「先射箭再畫靶」式的假說驅動設計(研究者先想好一個型態,再去測它)。本卷反過來做「逆向工程」:
先定義「當沖客贏家日」這個結果(P&L proxy全宇宙排名前10%),再去看贏家日當天的一大批價格/籌碼
特徵長什麼樣子,但嚴格比照本專案tmp_top_feat9_cc.py(頂部第九特徵case-control)的既有紀律:
  ①單邊觀察不算數,每個特徵都要有同日case-control對照組(排除當天所有贏家後隨機抽樣),算AUC而非
    只看「贏家組平均值比較高」這種敘述性比較;
  ②AUC門檻參考頂部無指紋定理先例(八特徵全部只有0.44-0.59,判定「無鑑別力」)——本卷比照,只有
    |AUC-0.5|>=0.08(即AUC>=0.58或<=0.42)且bootstrap 95%CI排除0.5才算通過,比先例的0.65門檻略寬鬆
    (先例是找"頂部警戒燈"這種高風險應用,本卷是探索性掃描,但仍要求CI排0這個硬門檻不放寬);
  ③特徵數量不少(逆向工程掃描本質上就是多重比較),誠實揭露multiple comparison風險:全部30個特徵
    版本的點估計AUC均完整列出(不是只列贏家),且要求同一特徵在close版/high版、120日/240日、或
    前10%/前5%窗口寬鬆版三選一的「穩健版本」也要同向且達標,才算「通過穩健度門檻」,不是單一版本
    達標就照單全收。

⚠兩階段設計刻意分離,不可混為一談(使用者原話「這是本卷方法論的核心」):
  第一階段=同日(contemporaneous)描述性驗證——今天的特徵 vs 今天的P&L proxy結果,回答「贏家日
    長什麼樣子」,不涉及能否交易(跳空/新高/震幅都是今天盤中/收盤才能確定的資訊)。
  第二階段=正向可交易性回測——只能用「昨天收盤前就已確定」的資訊(昨日K棒方向/昨日當沖比率/
    昨日P&L proxy/乖離均線用昨收算/大盤regime用昨日算)建構「開盤前就能篩出候選股」的規則,
    驗證規則篩出的股票當天P&L proxy是否顯著優於基準/case-control對照組。如果第一階段的強特徵
    多為「當日才知道」型,第二階段能用的前置特徵注定變少,誠實報告,不硬拗。

資料/複用(比照姊妹檔,不重新設計): import build_dtlend_report as R(load_dtlend/load_price/
dedup/event_stats/boot_diff_ci/boot_median_ci/case_control/HTML色票BG)+
import build_dtlend_pattern_pnl as P(load_price_full含high/low/防呆/masked_values/lookup_at/
mask_to_evs/boot_mean_ci/boot_diff_mean_ci/boot_line的多key相容寫法)。P&L proxy定義與宇宙過濾
(amt20>=0.3億∧四碼∧非00開頭ETF)與兩份姊妹檔完全一致。

大盤regime(ts=vol10/vol60、vp10百分位)算法比照build_regime_weather_report.py的vol_series()口徑
(TAIEX日報酬10日std,2006起全樣本rank(pct=True)*100)。regime是市場層純量,同一天全部股票共享同一
值,故不能用同日case-control測regime本身的AUC(對子的regime值必然相同,AUC恆為0.5的偽命題)——
regime只能當「特徵組合是否跨regime穩健一致」的分組變數,不是被測特徵本身,此為刻意的方法論決定
(而非疏漏)。

三問機制(本專案既有的訊號可信度追加篩檢,套用在所有通過AUC門檻的特徵上):
  ①誰被迫交易?(背後是否有強制行為者,或純粹自願雜訊) ②資訊是新的嗎?(是否已被市場消化)
  ③為何別人沒吃掉它?(這麼簡單的訊號為何沒被套利掉)——不是要推翻通過AUC的特徵,是誠實討論機制
  可信度,由使用者自行判斷。

工程教訓(已讀過姊妹檔build_dtlend_pattern_pnl.py的bootstrap key mismatch坑,本卷刻意避開):
  凡是呈現pp/中位差類的bootstrap一律直接呼叫P.boot_line()(它已內建"stat"/"diff"/"med"三種key的
  相容搜尋),不重寫一個新的呈現函式;AUC類bootstrap的回傳key統一固定為"auc",另外寫一個獨立的
  auc_line()呈現函式,兩種呈現邏輯不混用、不共用同一個dict schema。

用法: python 研究腳本/當沖借券/build_dtlend_winner_features.py  (從根目錄執行,鐵律)
產出: 研究報告/research_dtlend_winner_features.html
"""
import json
import sqlite3
import sys
import time

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "研究腳本/當沖借券")
import build_dtlend_report as R  # noqa: E402  (load_dtlend/dedup/event_stats/boot_*/case_control/BG)
import build_dtlend_pattern_pnl as P  # noqa: E402  (load_price_full/masked_values/lookup_at/mask_to_evs/boot_mean_ci/boot_diff_mean_ci/boot_line)

DB = "capital_flow.db"
OUT = "研究報告/research_dtlend_winner_features.html"
rng = np.random.default_rng(20260801)

GREEN, RED, BLUE, YELLOW, GRAY = R.GREEN, R.RED, R.BLUE, R.YELLOW, R.GRAY
BG = R.BG

AUC_PRESCREEN = 0.03   # 點估計|AUC-0.5|超過此值才值得花算力做bootstrap CI(全樣本掃描本身不設門檻)
AUC_PASS_DEV = 0.08    # 最終判定門檻: |AUC-0.5|>=0.08(即AUC>=0.58或<=0.42),比照頂部無指紋定理先例
N_ITER_AUC = 600       # AUC月群bootstrap迭代數(比中位數CI的2000次少,因單次rank運算成本高於單次median)
MIN_POOL = 30          # 每日排名所需最少同宇宙股票數(比照build_dtlend_report.py題④五分位門檻)


# ======================================================================
# 0. 自我檢查: 手算AUC(Mann-Whitney U等價式) vs sklearn.roc_auc_score
# ======================================================================
def calc_auc(a_vals, b_vals):
    """a=case(label1)/b=control(label0),回傳AUC點估計。用rank-sum法(Mann-Whitney U等價式,
    非本專案tmp_top_feat9_cc.py那種「case平均百分位」粗略版——那版本身有偏誤,見自我檢查print)。"""
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
    """AUC月群bootstrap(仿R.boot_diff_ci的月群重抽樣風格,統計量換成calc_auc)。
    回傳key固定用"auc"(不與boot_line()共用的"stat"/"diff"/"med"混淆),呈現一律走auc_line()。"""
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
        return f"<li>{label}: n太小,觀察層(未達bootstrap最低樣本門檻n>={MIN_POOL})</li>"
    sig = "<b>✓排0(顯著偏離0.5)</b>" if r["sig"] else "含0.5(不顯著)"
    passed = " <b>且達0.58/0.42門檻</b>" if abs(r["auc"] - 0.5) >= AUC_PASS_DEV and r["sig"] else ""
    return f"<li>{label}: AUC={r['auc']:.3f} 95%CI[{r['lo']:.3f},{r['hi']:.3f}] {sig}{passed}</li>"


# ======================================================================
# 1. 資料載入
# ======================================================================
def load_data():
    dt, _ln = R.load_dtlend()
    codes = sorted(dt.code.unique())
    print(f"[main] 當沖宇宙 {len(codes)} 檔(四碼∧非00開頭ETF,load_dtlend階段已過濾)")

    op, high, low, close, vol, money = P.load_price_full(codes, "2013-01-01")
    op, high, low, vol, money = (f.reindex(index=close.index, columns=close.columns) for f in (op, high, low, vol, money))
    op = op.where(op > 0)  # 防呆: 開盤價<=0視為資料異常(理論不應出現,少量邊界股票保險起見排除)

    amt20 = money.rolling(20, min_periods=15).mean() / 1e8
    uni = amt20 >= 0.3
    print(f"[main] 宇宙(amt20>=0.3億)股-日數={int(uni.sum().sum()):,} / 全表格{uni.size:,}格")

    dtp = dt.pivot_table(index="date", columns="code", values="Volume", aggfunc="sum").reindex(
        index=close.index, columns=close.columns)
    buyp = dt.pivot_table(index="date", columns="code", values="BuyAmount", aggfunc="sum").reindex(
        index=close.index, columns=close.columns)
    sellp = dt.pivot_table(index="date", columns="code", values="SellAmount", aggfunc="sum").reindex(
        index=close.index, columns=close.columns)
    ratio = (dtp / vol).clip(0, 1)
    pnl = (sellp - buyp) / buyp.replace(0, np.nan) * 100
    print(f"[main] pnl proxy覆蓋: {pnl.notna().sum().sum():,}格; "
          f"p1={np.nanpercentile(pnl.values, 1):.2f}% p50={np.nanmedian(pnl.values):.2f}% "
          f"p99={np.nanpercentile(pnl.values, 99):.2f}%")
    return dict(op=op, high=high, low=low, close=close, vol=vol, money=money, uni=uni, ratio=ratio, pnl=pnl)


def load_regime():
    """TAIEX ts=vol10/vol60 + vp10百分位,口徑比照build_regime_weather_report.py的vol_series()。"""
    conn = sqlite3.connect(DB, timeout=60)
    px = pd.read_sql("SELECT date, close FROM index_daily WHERE market='TAIEX' ORDER BY date",
                     conn, parse_dates=["date"]).set_index("date").close
    conn.close()
    r = px.pct_change(fill_method=None) * 100
    v10 = r.rolling(10).std()
    v60 = r.rolling(60).std()
    ts = v10 / v60
    vp10 = v10[v10.index >= "2006-01-01"].dropna().rank(pct=True) * 100
    print(f"[main] regime載入: ts可用{ts.notna().sum():,}日, vp10可用{vp10.notna().sum():,}日"
          f"(2006起), 最新ts={ts.iloc[-1]:.2f} vp10={vp10.iloc[-1]:.0f}")
    return ts, vp10


# ======================================================================
# 2. 防呆比較工具(NaN比較在pandas靜默回傳False而非NaN,故顯式交集notna(),
#    比照build_dtlend_pattern_pnl.py eval_setup()同款防呆註記)
# ======================================================================
def safe_cmp(a, b, op):
    out = op(a, b).astype(float)
    return out.where(a.notna() & b.notna())


# ======================================================================
# 3. 第一階段特徵(同日/當日層級,含少數只服務第二階段的lag版本)
# ======================================================================
def build_features(D):
    op, high, low, close, vol = D["op"], D["high"], D["low"], D["close"], D["vol"]
    ratio, pnl = D["ratio"], D["pnl"]
    close_l1 = close.shift(1)
    high_l1 = high.shift(1)
    low_l1 = low.shift(1)
    F = {}

    # ---- 跳空% + 真跳空方向 ----
    F["gap_pct"] = (op / close_l1 - 1) * 100
    F["gap_dir_up"] = safe_cmp(op, high_l1, lambda a, b: a > b)      # 真跳空向上(op>昨高)
    F["gap_dir_down"] = safe_cmp(op, low_l1, lambda a, b: a < b)     # 真跳空向下(op<昨低)

    # ---- 震幅 + 自身120/240日震幅百分位(百分位算法比照build_dtlend_pattern_pnl.py) ----
    rng_day = high - low
    amp = rng_day / close_l1 * 100
    F["amp_raw"] = amp
    F["amp_pct120"] = amp.rolling(120, min_periods=60).rank(pct=True) * 100
    F["amp_pct240"] = amp.rolling(240, min_periods=120).rank(pct=True) * 100

    # ---- 新高/新低狀態(5/10/20/60日窗,close版跟high/low版) ----
    for w in (5, 10, 20, 60):
        F[f"nh_close_{w}"] = safe_cmp(close, close_l1.rolling(w).max(), lambda a, b: a >= b)
        F[f"nh_high_{w}"] = safe_cmp(high, high_l1.rolling(w).max(), lambda a, b: a >= b)
        F[f"nl_close_{w}"] = safe_cmp(close, close_l1.rolling(w).min(), lambda a, b: a <= b)
        F[f"nl_low_{w}"] = safe_cmp(low, low_l1.rolling(w).min(), lambda a, b: a <= b)

    # ---- 量能倍數(主判讀20日均,60日均當穩健對照) ----
    F["volmult20"] = vol / vol.rolling(20, min_periods=15).mean()
    F["volmult60"] = vol / vol.rolling(60, min_periods=30).mean()

    # ---- 當沖比率本身(今日,contemporaneous;lag版留給第二階段) ----
    F["ratio_today"] = ratio.copy()

    # ---- 乖離均線(今日收盤版,今日層級用) ----
    for w in (5, 20, 60):
        F[f"bias{w}"] = (close / close.rolling(w).mean() - 1) * 100

    # ---- 前一日特徵(連續性;同時也是第二階段開盤前可用特徵) ----
    ret1 = close.pct_change(fill_method=None) * 100
    ret1_l1 = ret1.shift(1)
    F["y_dir"] = (ret1_l1 > 0).astype(float).where(ret1_l1.notna())
    F["y_ratio"] = ratio.shift(1)
    F["y_pnl"] = pnl.shift(1)

    # ---- 乖離均線lag版(用昨收算,只給第二階段用,不進第一階段掃描表) ----
    for w in (5, 20, 60):
        F[f"bias{w}_lag"] = (close_l1 / close_l1.rolling(w).mean() - 1) * 100

    return F


PHASE1_FEATURES = (
    ["gap_pct", "gap_dir_up", "gap_dir_down", "amp_raw", "amp_pct120", "amp_pct240"]
    + [f"nh_close_{w}" for w in (5, 10, 20, 60)] + [f"nh_high_{w}" for w in (5, 10, 20, 60)]
    + [f"nl_close_{w}" for w in (5, 10, 20, 60)] + [f"nl_low_{w}" for w in (5, 10, 20, 60)]
    + ["volmult20", "volmult60", "ratio_today", "bias5", "bias20", "bias60", "y_dir", "y_ratio", "y_pnl"]
)

ROBUST_PAIRS = {
    "amp_pct120": "amp_pct240", "amp_pct240": "amp_pct120",
    "volmult20": "volmult60", "volmult60": "volmult20",
}
for _w in (5, 10, 20, 60):
    ROBUST_PAIRS[f"nh_close_{_w}"] = f"nh_high_{_w}"
    ROBUST_PAIRS[f"nh_high_{_w}"] = f"nh_close_{_w}"
    ROBUST_PAIRS[f"nl_close_{_w}"] = f"nl_low_{_w}"
    ROBUST_PAIRS[f"nl_low_{_w}"] = f"nl_close_{_w}"

FEATURE_LABEL = {
    "gap_pct": "跳空%(open/昨收-1)", "gap_dir_up": "真跳空向上(op>昨高)", "gap_dir_down": "真跳空向下(op<昨低)",
    "amp_raw": "震幅(high-low)/昨收", "amp_pct120": "震幅120日自身百分位", "amp_pct240": "震幅240日自身百分位",
    "volmult20": "量能倍數(vol/20日均)", "volmult60": "量能倍數(vol/60日均)",
    "ratio_today": "當沖比率(今日)", "bias5": "乖離5日均%", "bias20": "乖離20日均%", "bias60": "乖離60日均%",
    "y_dir": "昨日漲跌方向(紅=1)", "y_ratio": "昨日當沖比率", "y_pnl": "昨日P&L proxy",
}
for _w in (5, 10, 20, 60):
    FEATURE_LABEL[f"nh_close_{_w}"] = f"創{_w}日新高(close版)"
    FEATURE_LABEL[f"nh_high_{_w}"] = f"創{_w}日新高(high版)"
    FEATURE_LABEL[f"nl_close_{_w}"] = f"創{_w}日新低(close版)"
    FEATURE_LABEL[f"nl_low_{_w}"] = f"創{_w}日新低(low版)"


# ======================================================================
# 4. 贏家/輸家日定義 + 同日case-control對照組
# ======================================================================
def evs_to_mask(evs, like):
    m = pd.DataFrame(False, index=like.index, columns=like.columns)
    if len(evs):
        ridx = like.index.get_indexer(evs.date)
        cidx = like.columns.get_indexer(evs.code)
        ok = (ridx >= 0) & (cidx >= 0)
        if ok.any():
            m.values[ridx[ok], cidx[ok]] = True
    return m


def build_groups(D):
    uni, pnl = D["uni"], D["pnl"]
    pnl_u = pnl.where(uni)
    pool_n = pnl_u.notna().sum(axis=1)
    valid_day = pool_n >= MIN_POOL
    valid_frame = pd.DataFrame(np.repeat(valid_day.values[:, None], pnl_u.shape[1], axis=1),
                               index=pnl_u.index, columns=pnl_u.columns)
    rnk = pnl_u.rank(axis=1, pct=True)

    win10_mask = (rnk >= 0.90) & valid_frame
    win5_mask = (rnk >= 0.95) & valid_frame
    lose10_mask = (rnk <= 0.10) & valid_frame

    print(f"[groups] 有效交易日(池>={MIN_POOL})={int(valid_day.sum()):,} / 全部{len(valid_day):,}日; "
          f"win10={int(win10_mask.sum().sum()):,} win5={int(win5_mask.sum().sum()):,} "
          f"lose10={int(lose10_mask.sum().sum()):,}")

    groups = {}
    for name, mask, seed in (("win10", win10_mask, 20260801), ("win5", win5_mask, 20260802),
                             ("lose10", lose10_mask, 20260803)):
        evs = P.mask_to_evs(mask)
        ctrl = R.case_control(evs, uni, mask, seed=seed)
        ctrl_mask = evs_to_mask(ctrl, uni)
        groups[name] = {"mask": mask, "ctrl_mask": ctrl_mask, "n": int(mask.sum().sum()), "n_ctrl": len(ctrl)}
        print(f"[groups] {name}: 事件{groups[name]['n']:,} / 對照組{groups[name]['n_ctrl']:,}")
    return groups


# ======================================================================
# 5. 第一階段: 全特徵點估計掃描(誠實列出全部,不是只列贏家) + 候選bootstrap
# ======================================================================
def scan_point_estimates(F, groups):
    rows = []
    for name in PHASE1_FEATURES:
        frame = F[name]
        rec = {"feature": name}
        for gname in ("win10", "win5", "lose10"):
            g = groups[gname]
            cv, cd = P.masked_values(frame, g["mask"])
            kv, kd = P.masked_values(frame, g["ctrl_mask"])
            auc = calc_auc(cv, kv)
            rec[gname] = {"auc": auc, "n": len(cv), "vals": (cv, cd, kv, kd)}
        rows.append(rec)
    return rows


def run_bootstrap_candidates(rows):
    """對win10點估計超過AUC_PRESCREEN偏離的特徵做bootstrap CI;若確認候選,追加win5(通用穩健版)
    與(若有定義配對)close/high或120/240版的win10 bootstrap,一併驗穩健度;另補lose10對稱檢定。"""
    boot = {}
    idx = {r["feature"]: r for r in rows}
    candidates = [r["feature"] for r in rows if abs(r["win10"]["auc"] - 0.5) >= AUC_PRESCREEN]
    print(f"[boot] 點估計偏離>=±{AUC_PRESCREEN}的候選特徵 {len(candidates)}/{len(rows)}: {candidates}")

    to_boot = set()
    for name in candidates:
        to_boot.add(("win10", name))
    for name in candidates:
        r = idx[name]
        if abs(r["win10"]["auc"] - 0.5) >= AUC_PASS_DEV:
            to_boot.add(("win5", name))       # 通用穩健版(前5%窗口)
            to_boot.add(("lose10", name))     # 對稱性檢定
            pair = ROBUST_PAIRS.get(name)
            if pair:
                to_boot.add(("win10", pair))  # 定義配對版(close/high或120/240)

    t0 = time.time()
    for i, (gname, name) in enumerate(sorted(to_boot)):
        cv, cd, kv, kd = idx[name][gname]["vals"]
        r = boot_auc_ci(cv, cd, kv, kd)
        boot[(gname, name)] = r
        if r is not None:
            print(f"[boot] ({gname},{name}) AUC={r['auc']:.3f} CI[{r['lo']:.3f},{r['hi']:.3f}] "
                  f"sig={r['sig']} ({i + 1}/{len(to_boot)}, 累計{time.time() - t0:.0f}s)")
        else:
            print(f"[boot] ({gname},{name}) n太小跳過 ({i + 1}/{len(to_boot)})")
    print(f"[boot] 全部候選bootstrap完成,耗時{time.time() - t0:.0f}s")
    return boot


def verdict_feature(name, rows_idx, boot):
    """回傳(通過與否bool, 說明字串)。通過條件: win10點估計|dev|>=0.08且CI排0.5;
    通用穩健版win5同向且|dev|>=0.05;若有定義配對,該配對win10版也需同向且|dev|>=0.05。"""
    r10 = boot.get(("win10", name))
    if r10 is None or abs(r10["auc"] - 0.5) < AUC_PASS_DEV or not r10["sig"]:
        return False, "win10未達0.58/0.42門檻或CI含0.5"
    same_dir = np.sign(r10["auc"] - 0.5)

    r5 = boot.get(("win5", name))
    win5_ok = r5 is not None and np.sign(r5["auc"] - 0.5) == same_dir and abs(r5["auc"] - 0.5) >= 0.05
    if not win5_ok:
        detail = f"win5 AUC={r5['auc']:.3f}" if r5 is not None else "win5未達bootstrap門檻"
        return False, f"win10通過但通用穩健版(前5%)不一致({detail})"

    pair = ROBUST_PAIRS.get(name)
    if pair:
        rp = boot.get(("win10", pair))
        pair_ok = rp is not None and np.sign(rp["auc"] - 0.5) == same_dir and abs(rp["auc"] - 0.5) >= 0.05
        if not pair_ok:
            detail = f"{pair} AUC={rp['auc']:.3f}" if rp is not None else f"{pair}未達bootstrap門檻"
            return False, f"win10+win5通過但定義配對版({FEATURE_LABEL.get(pair, pair)})不一致({detail})"
    return True, "win10+win5(+定義配對若有)三重一致,通過穩健度門檻"


# ======================================================================
# 6. Regime穩健性檢查(對已通過的特徵,分regime段複驗一致性;非測regime本身AUC)
# ======================================================================
def regime_breakdown(passed_names, F, groups, ts, vp10):
    """對每個通過的特徵,依市場regime(ts升溫/中性/退潮;vp10高波/低波)重算win10點估計AUC,
    檢查方向是否跨regime穩健一致(不是只在特定regime成立的巧合)。"""
    ts_al = ts.reindex(F[passed_names[0]].index) if passed_names else None
    vp_al = vp10.reindex(F[passed_names[0]].index) if passed_names else None
    out = {}
    for name in passed_names:
        frame = F[name]
        g = groups["win10"]
        rows = []
        bands = [("升溫ts>1.2", ts_al > 1.2), ("中性0.8~1.2", (ts_al >= 0.8) & (ts_al <= 1.2)),
                 ("退潮ts<0.8", ts_al < 0.8), ("高波vp10>=80", vp_al >= 80), ("低波vp10<80", vp_al < 80)]
        for label, cond in bands:
            cond_frame = pd.DataFrame(np.repeat(cond.values[:, None], frame.shape[1], axis=1),
                                       index=frame.index, columns=frame.columns)
            cv, _ = P.masked_values(frame, g["mask"] & cond_frame)
            kv, _ = P.masked_values(frame, g["ctrl_mask"] & cond_frame)
            auc = calc_auc(cv, kv) if len(cv) >= MIN_POOL and len(kv) >= MIN_POOL else np.nan
            rows.append((label, auc, len(cv)))
        out[name] = rows
        print(f"[regime] {name} 分regime AUC: " + ", ".join(f"{lb}={a:.3f}(n={n})" if pd.notna(a) else f"{lb}=n太小"
                                                           for lb, a, n in rows))
    return out


# ======================================================================
# 7. 第二階段: 開盤前可交易性規則(只用昨日或更早的資訊)
# ======================================================================
def eval_rule(label, mask, pnl, uni, seed):
    """比照build_dtlend_pattern_pnl.py eval_setup()風格,但outcome直接=P&L proxy(不轉price方向),
    回傳結構完全複用R/P既有bootstrap函式,呈現一律走P.boot_line()(已內建多key相容搜尋)。"""
    mask = mask & pnl.notna()
    evs = P.mask_to_evs(mask)
    n = len(evs)
    if n == 0:
        print(f"[rule] {label}: n=0,跳過")
        return None

    pnl_vals, pnl_dates = P.masked_values(pnl, mask)
    # 防呆: (pnl>0)對NaN靜默回傳False,顯式.where(pnl.notna())還原NaN,避免case_control()抽到的
    # 對照組股票若當天pnl缺值被誤記為「未命中(0)」而非「未定義」(比照P.eval_setup()docstring同款提醒)
    hit_frame = (pnl > 0).astype(float).where(pnl.notna())
    hit_vals, hit_dates = P.masked_values(hit_frame, mask)

    base_pop = uni & pnl.notna()
    base_pnl_vals, _ = P.masked_values(pnl, base_pop)
    base_hit_vals, _ = P.masked_values(hit_frame, base_pop)
    base_pnl = float(np.median(base_pnl_vals)) if len(base_pnl_vals) else np.nan
    base_hit_frac = float(np.mean(base_hit_vals)) if len(base_hit_vals) else np.nan  # 0~1尺度,供bootstrap用
    base_hit = base_hit_frac * 100 if pd.notna(base_hit_frac) else np.nan            # 0~100尺度,供顯示用

    boot_pnl_base = R.boot_median_ci(list(np.array(pnl_vals) - base_pnl), pnl_dates)
    boot_hit_base = P.boot_mean_ci((np.array(hit_vals) - base_hit_frac) * 100, hit_dates)

    ctrl = R.case_control(evs, uni, mask, seed=seed)
    ctrl_pnl_vals, ctrl_pnl_dates = P.lookup_at(pnl, ctrl)
    ctrl_hit_vals, ctrl_hit_dates = P.lookup_at(hit_frame, ctrl)

    boot_pnl_ctrl = R.boot_diff_ci(pnl_vals, pnl_dates, ctrl_pnl_vals, ctrl_pnl_dates)
    boot_hit_ctrl = P.boot_diff_mean_ci(np.array(hit_vals) * 100, hit_dates,
                                        np.array(ctrl_hit_vals) * 100, ctrl_hit_dates)

    print(f"[rule] {label}: n={n:,} pnl中位{np.median(pnl_vals):+.2f}%(基準{base_pnl:+.2f}%) "
          f"命中率{np.mean(hit_vals) * 100:.1f}%(基準{base_hit:.1f}%) 對照組n={len(ctrl):,}")

    return {"label": label, "n": n, "n_ctrl": len(ctrl),
            "pnl_med": float(np.median(pnl_vals)), "hit_rate": float(np.mean(hit_vals)) * 100,
            "base_pnl": base_pnl, "base_hit": base_hit,
            "boot_pnl_base": boot_pnl_base, "boot_hit_base": boot_hit_base,
            "boot_pnl_ctrl": boot_pnl_ctrl, "boot_hit_ctrl": boot_hit_ctrl}


def build_phase2_rules(F, D):
    uni, pnl = D["uni"], D["pnl"]

    def day_topq(frame, q, min_pool=MIN_POOL):
        fu = frame.where(uni)
        pool_n = fu.notna().sum(axis=1)
        valid = pool_n >= min_pool
        vf = pd.DataFrame(np.repeat(valid.values[:, None], fu.shape[1], axis=1), index=fu.index, columns=fu.columns)
        rnk = fu.rank(axis=1, pct=True)
        return (rnk >= q) & vf, (rnk <= 1 - q) & vf  # (高分位遮罩, 低分位遮罩)

    y_pnl_hi, y_pnl_lo = day_topq(F["y_pnl"], 0.80)
    y_ratio_hi, y_ratio_lo = day_topq(F["y_ratio"], 0.80)
    bias20_hi, bias20_lo = day_topq(F["bias20_lag"], 0.80)

    rules = {}
    rules["昨日P&L proxy前20%(延續假說)"] = eval_rule("昨日P&L proxy前20%", y_pnl_hi, pnl, uni, seed=20260811)
    rules["昨日P&L proxy後20%(延續假說·輸家)"] = eval_rule("昨日P&L proxy後20%", y_pnl_lo, pnl, uni, seed=20260812)
    rules["昨日當沖比率前20%(關注度延續)"] = eval_rule("昨日當沖比率前20%", y_ratio_hi, pnl, uni, seed=20260813)
    rules["昨日漲(y_dir=1)"] = eval_rule("昨日收紅", (F["y_dir"] == 1) & uni, pnl, uni, seed=20260814)
    rules["昨收乖離20日均前20%(追高)"] = eval_rule("昨收乖離20日均前20%", bias20_hi, pnl, uni, seed=20260815)
    rules["昨收乖離20日均後20%(超跌)"] = eval_rule("昨收乖離20日均後20%", bias20_lo, pnl, uni, seed=20260816)

    # 若「昨日P&L proxy前20%」與「昨日當沖比率前20%」同向(pnl中位皆優於基準),測交集複合規則
    r_pnl, r_ratio = rules["昨日P&L proxy前20%(延續假說)"], rules["昨日當沖比率前20%(關注度延續)"]
    if r_pnl and r_ratio and r_pnl["pnl_med"] > r_pnl["base_pnl"] and r_ratio["pnl_med"] > r_ratio["base_pnl"]:
        combo_mask = y_pnl_hi & y_ratio_hi
        rules["複合:昨日P&L前20%∧昨日當沖比率前20%"] = eval_rule(
            "複合(pnl∧ratio前20%)", combo_mask, pnl, uni, seed=20260817)

    return rules


# ======================================================================
# 8. HTML 呈現
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

THREE_Q = {
    "gap": ("跳空/創新高/創新低/震幅擴大類(價格型態)",
            "誰被迫交易?——這類特徵背後常見兩種行為者:主動追價的FOMO買盤(自願)以及觸及停損/"
            "維持率警戒的斷頭賣壓(被迫)。當沖客若能在此類日子賺錢,較可能是提供流動性(逢極端價差"
            "撮合)賺價差,而非掌握內部資訊。",
            "資訊是新的嗎?——跳空/新高/新低/震幅本身是收盤才能完全確認的公開技術資訊,全市場同步"
            "可見,不是任何一方獨有的新資訊,理論上該被市場快速消化。",
            "為何別人沒吃掉它?——當沖需要券商當沖資格/保證金與極短線盯盤能力,一般投資人參與門檻高、"
            "反應慢,當沖客本身可能就是這類價格波動的「吸收方」,留有制度性摩擦空間;但也要留意"
            "P&L proxy與這些特徵同樣源自「今天的價格行為」,不能排除純粹的機械共變(見已知限制)。"),
    "vol": ("量能倍數/當沖比率本身",
            "誰被迫交易?——量能異常放大常伴隨籌碼換手(大戶出貨/散戶追高),當沖比率本身升高代表"
            "當沖客自己活躍度提高,強制性行為者不明顯,較偏自願參與。",
            "資訊是新的嗎?——成交量是最公開的市場資訊之一,理論上無資訊優勢可言。",
            "為何別人沒吃掉它?——⚠當沖比率與P&L proxy由同一批當沖成交量/金額構成,兩者高相關可能"
            "只是定義上的耦合(當沖比率高的股票=當沖客集中交易的股票,而P&L proxy正是這群當沖客的"
            "損益),此為循環論證風險,通過AUC不代表存在可套利的獨立訊號,見已知限制詳述。"),
    "bias": ("乖離均線",
             "誰被迫交易?——乖離過大常伴隨獲利了結賣壓或均值回歸程式單進場,不必然是強制行為者。",
             "資訊是新的嗎?——乖離率是公開可算的古典技術指標,理論上早已被市場充分消化。",
             "為何別人沒吃掉它?——當沖客的P&L proxy若與乖離相關,較可能反映「當沖客本身就是執行"
             "均值回歸策略的角色之一」(用當沖工具去吃乖離收斂的價差),而非發現了被市場忽略的訊號。"),
    "lag": ("前一日特徵(連續性/lag)",
            "誰被迫交易?——連續數日的同向當沖行為,較可能反映特定當沖主力鎖定同一檔股票操作"
            "(自我延續),而非普遍市場的強制行為。",
            "資訊是新的嗎?——昨日的當沖比率/損益等明細資料在一般免費資料源上通常有時間落差"
            "(例如FinMind與官方公告的T+1甚至更久延遲),對散戶而言昨日當沖細節並非即時公開,"
            "存在資訊取得的時間差,但機構/券商內部應可即時取得。",
            "為何別人沒吃掉它?——若真有效,較可能是資料取得成本(散戶難以即時取得逐股當沖細項)"
            "撐住這個空間,而非市場真的看不懂;也可能只是同一批當沖主力自己延續操作造成的統計慣性,"
            "而非可獨立套利的訊號,務必留意。"),
}


def feature_category(name):
    if name.startswith(("gap_", "amp_", "nh_", "nl_")):
        return "gap"
    if name.startswith("volmult") or name == "ratio_today":
        return "vol"
    if name.startswith("bias"):
        return "bias"
    if name.startswith("y_"):
        return "lag"
    return "gap"


def write_report(rows, boot, groups, passed, regime_out, rules, n_days_used):
    idx = {r["feature"]: r for r in rows}

    # ---- 全特徵點估計掃描表(誠實列出全部) ----
    scan_rows_html = []
    for r in sorted(rows, key=lambda x: -abs(x["win10"]["auc"] - 0.5)):
        name = r["feature"]
        flag = "✅" if name in passed else ("🔬" if abs(r["win10"]["auc"] - 0.5) >= AUC_PRESCREEN else "")
        scan_rows_html.append(
            f"<tr><th>{flag}{FEATURE_LABEL.get(name, name)}</th>"
            f"<td>{r['win10']['auc']:.3f}(n={r['win10']['n']:,})</td>"
            f"<td>{r['win5']['auc']:.3f}(n={r['win5']['n']:,})</td>"
            f"<td>{r['lose10']['auc']:.3f}(n={r['lose10']['n']:,})</td></tr>")
    scan_table = ("<table><tr><th>特徵(✅=通過穩健度門檻,🔬=進入bootstrap候選但未通過)</th>"
                  "<th>win10(前10%) AUC</th><th>win5(前5%) AUC</th><th>lose10(後10%) AUC</th></tr>"
                  + "".join(scan_rows_html) + "</table>")

    # ---- 候選bootstrap明細 ----
    boot_lines = []
    seen = set()
    for r in rows:
        name = r["feature"]
        for gname, glabel in (("win10", "前10%贏家"), ("win5", "前5%贏家(穩健版)"), ("lose10", "後10%輸家(對稱檢定)")):
            key = (gname, name)
            if key in boot and key not in seen:
                seen.add(key)
                boot_lines.append(auc_line(f"{FEATURE_LABEL.get(name, name)} · {glabel} vs 同日case-control",
                                           boot[key]))
    boot_html = "<ul>" + "".join(boot_lines) + "</ul>" if boot_lines else "<div class='note'>無候選特徵進入bootstrap(全部點估計|AUC-0.5|<0.03)。</div>"

    # ---- 通過清單 + 三問 ----
    if passed:
        pass_rows = []
        for name in passed:
            r10 = boot[("win10", name)]
            r5 = boot.get(("win5", name))
            pass_rows.append(
                f"<tr><th>{FEATURE_LABEL.get(name, name)}</th>"
                f"<td class='good'>{r10['auc']:.3f} [{r10['lo']:.3f},{r10['hi']:.3f}]</td>"
                f"<td>{r5['auc']:.3f} [{r5['lo']:.3f},{r5['hi']:.3f}]</td></tr>")
        pass_table = ("<table><tr><th>特徵</th><th>win10 AUC[95%CI]</th><th>win5穩健版AUC[95%CI]</th></tr>"
                      + "".join(pass_rows) + "</table>")
        cats = sorted({feature_category(n) for n in passed})
        q_blocks = []
        for cat in cats:
            title, q1, q2, q3 = THREE_Q[cat]
            names_in_cat = [FEATURE_LABEL.get(n, n) for n in passed if feature_category(n) == cat]
            q_blocks.append(f"<h3>{title}(通過特徵: {', '.join(names_in_cat)})</h3>"
                           f"<ul><li>{q1}</li><li>{q2}</li><li>{q3}</li></ul>")
        three_q_html = "".join(q_blocks)
        regime_rows = []
        for name in passed:
            bands = regime_out.get(name, [])
            cells = "".join(f"<td>{a:.3f}(n={n})</td>" if pd.notna(a) else "<td>n太小</td>" for _, a, n in bands)
            regime_rows.append(f"<tr><th>{FEATURE_LABEL.get(name, name)}</th>{cells}</tr>")
        regime_head = "".join(f"<th>{lb}</th>" for lb, _, _ in (regime_out.get(passed[0], []) if passed else []))
        regime_table = (f"<table><tr><th>特徵</th>{regime_head}</tr>" + "".join(regime_rows) + "</table>") if passed else ""
        p1_verdict_cls, p1_verdict_txt = "v-good", f"✅第一階段有{len(passed)}個特徵通過AUC+穩健度門檻(見下表)"
    else:
        pass_table = "<div class='note'>無特徵通過。</div>"
        three_q_html = "<div class='note'>無通過特徵,略過三問討論。</div>"
        regime_table = ""
        p1_verdict_cls, p1_verdict_txt = "v-warn", "🟡第一階段無特徵通過0.58/0.42門檻+穩健度要求(比照頂部無指紋定理,判定為描述性層級無強鑑別力特徵,或僅有弱/不穩健訊號)"

    # ---- 第二階段規則表 ----
    rule_rows = []
    for label, r in rules.items():
        if r is None:
            continue
        rule_rows.append(
            f"<tr><th>{label}(n={r['n']:,})</th>"
            f"<td>{r['pnl_med']:+.2f}%<br><span class='sub'>基準{r['base_pnl']:+.2f}%</span></td>"
            f"<td>{r['hit_rate']:.1f}%<br><span class='sub'>基準{r['base_hit']:.1f}%</span></td></tr>")
    rule_table = ("<table><tr><th>開盤前規則</th><th>今日P&L proxy中位數(基準版)</th>"
                  "<th>今日命中率(基準版)</th></tr>" + "".join(rule_rows) + "</table>")

    rule_boot_html = []
    for label, r in rules.items():
        if r is None:
            continue
        rule_boot_html.append(f"<h3>{label}</h3><ul>"
            + P.boot_line("P&L proxy中位數 vs全樣本基準(excess)", r["boot_pnl_base"], unit="%")
            + P.boot_line("命中率 vs全樣本基準(excess比例)", r["boot_hit_base"])
            + P.boot_line("P&L proxy中位數 vs case-control同日對照組", r["boot_pnl_ctrl"], unit="%", key="diff")
            + P.boot_line("命中率 vs case-control同日對照組", r["boot_hit_ctrl"], key="diff")
            + "</ul>")
    rule_boot = "".join(rule_boot_html)

    any_rule_sig_good = any(
        r is not None and r["boot_pnl_ctrl"] is not None and r["boot_pnl_ctrl"]["sig"] and r["boot_pnl_ctrl"]["diff"] > 0
        for r in rules.values())
    if any_rule_sig_good:
        p2_cls, p2_txt = "v-good", "✅第二階段找到至少一個開盤前規則,其P&L proxy(vs case-control)顯著優於對照組"
    elif passed and all(feature_category(n) in ("gap",) for n in passed):
        p2_cls, p2_txt = "v-bad", "❌第二階段未能建構出顯著有效的開盤前規則——第一階段通過的特徵多為「當日才知道」型(跳空/新高/震幅),本質上無法逆推成開盤前可用規則,此為方法論上的必然限制而非執行失誤"
    else:
        p2_cls, p2_txt = "v-warn", "🟡第二階段規則測試完成,但均未達case-control顯著,見下方逐項數字"

    # ---- 圖表資料 ----
    def bar_payload(labels, vals, colors):
        return {"labels": labels, "vals": [round(v, 3) if v is not None and pd.notna(v) else None for v in vals],
                 "colors": colors}

    top_by_dev = sorted(rows, key=lambda x: -abs(x["win10"]["auc"] - 0.5))[:12]
    c1 = bar_payload([FEATURE_LABEL.get(r["feature"], r["feature"]) for r in top_by_dev],
                     [r["win10"]["auc"] for r in top_by_dev],
                     [GREEN if r["feature"] in passed else (YELLOW if abs(r["win10"]["auc"] - 0.5) >= AUC_PRESCREEN else GRAY)
                      for r in top_by_dev])
    c2 = bar_payload(list(rules.keys()),
                     [(r["pnl_med"] - r["base_pnl"]) if r else None for r in rules.values()],
                     [BLUE] * len(rules))
    payload = {"c1": c1, "c2": c2}
    payload_json = json.dumps(payload, ensure_ascii=False)

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>當沖客贏家日逆向工程特徵case-control考卷(2026-08-01)</title>
<script src="plotly.min.js"></script><style>{CSS}</style></head><body>
<h1>📊 當沖客贏家日逆向工程特徵×AUC case-control考卷 + 開盤前可交易性回測</h1>
<div class="note">方法論比照本專案<code>tmp_top_feat9_cc.py</code>(頂部第九特徵case-control,八特徵AUC
0.44-0.59判定「無鑑別力」)同等嚴謹標準:任何逆向工程出的特徵都必須有同日case-control對照組(排除
當天所有贏家後從同宇宙隨機抽同數量非贏家股票),算AUC而非只看「贏家組數值比較高」。判準:
|AUC-0.5|&gt;={AUC_PASS_DEV}(即AUC&gt;=0.58或&lt;=0.42)且月群bootstrap 95%CI排除0.5,且通用穩健版
(前5%贏家窗口)同向達≥0.05偏離,若特徵有明確定義配對(close/high版、120/240日窗)則該配對也需同向達
≥0.05偏離,三者皆一致才算「通過穩健度門檻」——不是單一版本達標就照單全收。資料=複用
<code>build_dtlend_report.py</code>(load_dtlend/case_control/boot_diff_ci/boot_median_ci)+
<code>build_dtlend_pattern_pnl.py</code>(load_price_full/masked_values/boot_mean_ci等)兩份姊妹檔的
資料讀取與工具函式,宇宙=amt20(20日均成交值)&gt;=0.3億∧四碼股票∧非00開頭ETF,P&amp;L proxy=
(SellAmount-BuyAmount)/BuyAmount×100(逐股逐日)。有效交易日(同宇宙池&gt;={MIN_POOL}檔)共
{n_days_used:,}日。</div>

<h2>📋 兩階段判讀總表</h2>
<table>
<tr><th>階段</th><th>核心問題</th><th>判讀</th></tr>
<tr><th>①第一階段:同日特徵逆向工程</th><td>贏家日(P&amp;L proxy前10%)當天特徵是否有鑑別力(vs同日
case-control)</td><td><span class="verdict {p1_verdict_cls}">{p1_verdict_txt}</span></td></tr>
<tr><th>②第二階段:開盤前可交易性</th><td>只用昨日或更早資訊建構的規則,能否篩出今日P&amp;L proxy
顯著優於基準的候選股</td><td><span class="verdict {p2_cls}">{p2_txt}</span></td></tr>
</table>

<h2>① 全特徵點估計AUC掃描(誠實列出全部{len(rows)}個特徵版本,不是只列贏家)</h2>
<div class="note">win10=P&amp;L proxy當日排名前10%(主判讀);win5=前5%(穩健對照,窗口更嚴格);
lose10=後10%(對稱性檢定,若win10某方向顯著,lose10理論上應顯著偏向相反方向)。AUC=0.5代表無鑑別力,
&gt;0.5代表特徵值越大越可能是當日贏家,&lt;0.5代表相反。🔬=點估計|AUC-0.5|&gt;={AUC_PRESCREEN}進入
bootstrap候選;✅=最終通過穩健度門檻(見下方明細)。</div>
{scan_table}

<h2>② 候選特徵bootstrap明細(月群重抽樣n_iter={N_ITER_AUC},95%CI)</h2>
{boot_html}

<h2>③ 通過穩健度門檻的特徵</h2>
{pass_table}

<h3>Regime穩健性複驗(僅通過特徵;檢查方向是否跨市場regime一致,而非測regime本身AUC——regime是
市場層純量,同日case-control對子必然同值,故不能直接測其AUC,此為刻意的方法論設計而非疏漏)</h3>
{regime_table if passed else "<div class='note'>無通過特徵可供regime複驗。</div>"}

<h2>④ 三問機制討論(誰被迫交易?/資訊是新的嗎?/為何別人沒吃掉它?)</h2>
{three_q_html}

<h2>⑤ 第二階段:開盤前可交易性規則(只用昨日或更早資訊)</h2>
<div class="note">規則全部只用「今日開盤前已確定」的資訊(昨日K棒方向/昨日當沖比率/昨日P&amp;L proxy/
乖離均線用昨收算),驗證篩出候選股當天P&amp;L proxy是否顯著優於基準(全樣本常數)與同日case-control
對照組(排除當天所有規則命中股後隨機抽同數量,net掉當天大盤/類股方向這個混淆因子)。</div>
{rule_table}
<h3>bootstrap顯著性(vs全樣本基準 + vs case-control同日對照組)</h3>
{rule_boot}

<h2>📈 圖表</h2>
<div class="note">c1=win10 AUC點估計偏離0.5最大的前12個特徵版本(綠=通過穩健度門檻,黃=進入bootstrap
候選但未通過,灰=未進候選);c2=第二階段各規則今日P&amp;L proxy中位數excess(vs全樣本基準)。</div>
<div id="c1" style="height:380px"></div>
<div id="c2" style="height:320px"></div>

<h2>已知限制與方法論不確定處(誠實聲明)</h2>
<div class="note">
①<b>Multiple comparison</b>:本卷同時掃描{len(rows)}個特徵版本(win10+win5+lose10三組×約
{len(PHASE1_FEATURES)}個特徵),即使全部特徵都是純雜訊,依95%CI規則預期仍會有約
{len(rows) * 0.05:.0f}個「碰巧」顯著排0的個案;本卷已用「通用穩健版(win5)+定義配對版(若有)三重一致」
作為實質上的多重比較管控門檻(比單看單一版本CI排0嚴格),但仍建議將本卷結論視為「候選假說」而非
「已驗證定律」,正式上板前應再用近期樣本外資料複驗;<br>
②<b>當沖比率/量能類特徵的內生性/循環論證風險</b>:P&amp;L proxy由當沖BuyAmount/SellAmount定義,
與「當沖比率」共用同一批當沖成交資料,兩者若顯示AUC鑑別力,不能排除是定義上的機械共變(當沖客集中
交易的股票本身當沖比率高,而P&amp;L proxy正是這群當沖客自己的損益),未必代表存在可獨立套利的訊號,
此點已在三問討論中明確提醒;<br>
③<b>震幅/新高新低類特徵的「今日才知道」限制</b>:第一階段這類特徵多數要等到當日收盤(或至少盤中
大幅波動後)才能完全確認,即使AUC通過,也<b>不能</b>直接當「今天要不要做這檔當沖」的開盤前依據,
本卷第二階段已刻意不使用這類特徵建構開盤前規則,只用昨日或更早資訊;<br>
④case-control對照組使用固定亂數種子(20260801系列)以求可重現,但仍是單一次抽樣非窮舉,重新抽樣
會有小幅波動;<br>
⑤AUC月群bootstrap迭代數(n_iter={N_ITER_AUC})低於本專案中位數CI慣用的2000次,是計算成本的取捨
(單次rank運算成本高於單次median),CI精度可能略遜於其他考卷的中位數CI,但仍足以判斷是否排除0.5;<br>
⑥regime穩健性複驗只做點估計(未逐regime段bootstrap),樣本切細後n可能偏小,結論僅供參考方向是否
一致,不是正式的分段顯著性檢定;<br>
⑦所有數字為觀察層/盤點層,不涉及交易成本、滑價、實際下單可執行性,亦不預設上板。
</div>
<div class="note">維運: python 研究腳本/當沖借券/build_dtlend_winner_features.py(從根目錄執行,鐵律)。
姊妹檔: build_dtlend_report.py(全史四題正式考卷)、build_dtlend_pattern_pnl.py(型態×P&amp;L proxy
contemporaneous驗證)、封存/研究腳本歸檔/tmp_top_feat9_cc.py(本卷比照的AUC門檻先例)。</div>

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
bar('c1', '① win10 AUC點估計(|偏離0.5|前12名)', D.c1, 'AUC', 0.5);
bar('c2', '⑤ 第二階段規則: 今日P&L proxy中位數 excess(vs全樣本基準,pp)', D.c2, 'excess(%)', 0);
</script>
</body></html>"""
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[report] 已輸出 {OUT}")


# ======================================================================
# 9. main
# ======================================================================
def main():
    t0 = time.time()
    selfcheck_auc()

    D = load_data()
    ts, vp10 = load_regime()
    F = build_features(D)
    groups = build_groups(D)
    n_days_used = int((D["uni"].sum(axis=1) >= MIN_POOL).sum())

    print("=" * 60, "\n[main] 第一階段: 全特徵點估計掃描")
    rows = scan_point_estimates(F, groups)
    for r in sorted(rows, key=lambda x: -abs(x["win10"]["auc"] - 0.5))[:15]:
        print(f"  {r['feature']:<16} win10={r['win10']['auc']:.3f}(n={r['win10']['n']:,}) "
              f"win5={r['win5']['auc']:.3f} lose10={r['lose10']['auc']:.3f}")

    print("=" * 60, "\n[main] 候選特徵bootstrap")
    boot = run_bootstrap_candidates(rows)

    print("=" * 60, "\n[main] 判定通過清單")
    passed = []
    for r in rows:
        name = r["feature"]
        if ("win10", name) in boot:
            ok, why = verdict_feature(name, rows, boot)
            print(f"  {name}: {'✅通過' if ok else '❌未通過'} — {why}")
            if ok:
                passed.append(name)
    print(f"[main] 最終通過穩健度門檻特徵數 = {len(passed)}: {passed}")

    print("=" * 60, "\n[main] Regime穩健性複驗")
    regime_out = regime_breakdown(passed, F, groups, ts, vp10) if passed else {}

    print("=" * 60, "\n[main] 第二階段: 開盤前可交易性規則")
    rules = build_phase2_rules(F, D)

    print("=" * 60, "\n[main] 組裝報告")
    write_report(rows, boot, groups, passed, regime_out, rules, n_days_used)
    print(f"[main] 全部完成,總耗時{time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
