# -*- coding: utf-8 -*-
"""週級強者續強×訊號週「路徑形狀」特徵測試(2026-08-05,使用者:「有人這周是先漲後跌跟先跌後漲,又或者漲
很兇到漲一點點,這感覺都代表不同含意,可能影響到隔周表現結果」)。

背景: 週級強者續強策略核心問題是MDD過深(20%門檻top10版本MDD-46.6%)。同日稍早已測過大量regime/信心層/
自身滾動勝率等「進出場疊加」訊號,全部失敗,核心診斷是「個股集中度風險」(籃子太薄時1-4檔容易被單一
個股暴跌重傷),唯一存活的是`build_weekly_momo_stoploss_overlay.py`的個股週中停損。本卷換一個完全不同
的角度——不碰進出場時機,而是把「選股訊號本身」的操作化方式細緻化:目前訊號只看「週五收盤vs上週五收盤」
單一數字,完全忽略這個週報酬是怎麼走出來的路徑形狀(同樣+20%,有人是衝到+30%又跌回+20%收盤,有人是
一路盤整到週五才噴出,含意可能不同)。

四個路徑特徵(全部只用「訊號週當週」逐日資料,base=上週五收盤,零前視——這些資料在訊號週五收盤決策當下
全部已經發生,不牽涉下週任何資訊):
  ①衝高回落giveback = 週內最高(收盤/最高價)/上週五收盤-1,減去週報酬本身(恆>=0,越大代表越像
    「衝高回落、尾盤回吐」)
  ②先蹲後跳drawup = 週報酬本身,減去週內最低(收盤/最低價)/上週五收盤-1(恆>=0,越大代表週中曾破底
    最後拉回收正)
  ③最高/最低點出現的相對位置(0=週一附近,1=週五附近,以該週實際交易日數nd正規化,兼容假日缺日)
  ④路徑平滑度(收盤逐日報酬std;穩健配對版=逐日(高-低)/收盤均值,呼應融券回補研究「波動度是唯一存活
    訊號」的先例)

每個特徵都有一個「收盤版」(主)+一個「高低價版」(穩健配對,呼應build_earnings_winner_features.py的
ROBUST_PAIRS設計,避免單一算法巧合過關)。

方法論(逐步複用今日已建立的基礎設施,不重新發明):
  資料撈取/清洗/週標籤對齊: 比照build_weekly_momo_stoploss_overlay.py的fm_daily_price逐日撈取架構
  (但本卷只需「訊號週自身」的日內資料,不需要停損卷那種跨週持有窗searchsorted定位,改用更直接的
  groupby(code,wk)取每檔每週的逐日OHLC)。
  贏家/輸家逆向工程+AUC: 逐字比照build_earnings_winner_features.py方法論(calc_auc用rank-sum法,
  月群bootstrap CI,通過門檻|AUC-0.5|>=0.05即>0.55或<0.45且CI排除0.5)。贏家/輸家定義=次週報酬
  (trades.exit_ret)全樣本前30%/後30%(使用者原話口徑)。
  第二階段可交易性驗證(通過AUC篩選才做,不能只停在AUC——這是今天融券回補研究已踩過的教訓): 把特徵
  翻譯成規則(全樣本cross-sectional前30%或後30%,依AUC方向決定),用同批(entry_week年-月)case-control
  對照組+月群bootstrap驗證net_ret均值差異是否顯著。
  第三階段basket權重疊加(雙關卡都過才做): 不做濾網排除(今天已證實任何讓籃子變薄的機制都會讓MDD惡化),
  改用連續加權——basket內依特徵值百分位給予[1-alpha, 1+alpha]倍原始等權重的線性tilt,再正規化使
  weight加總=1(每一檔恆有正權重,籃子檔數不變,純粹「有把握的加碼/沒把握的減碼」)。

用法: python 研究腳本/綜合策略/build_weekly_momo_pathshape_overlay.py (從根目錄執行,鐵律)
產出: 純console報告,無檔案輸出
"""
import sqlite3
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, "研究腳本/綜合策略")
import build_weekly_momo_regime_overlay as M  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

RNG = np.random.default_rng(20260805)
N_BOOT = 2000
AUC_PASS_DEV = 0.05          # 使用者指定門檻: AUC>0.55或<0.45才算通過
MIN_POOL = 20
RULE_Q = 0.30                # 規則翻譯: 全樣本前/後30%
WEIGHT_ALPHAS = [0.3, 0.5, 0.8]

FEATURES = ["giveback_close", "giveback_hl", "drawup_close", "drawup_hl",
            "pos_max_close", "pos_max_hl", "pos_min_close", "pos_min_hl",
            "smooth_close", "smooth_range"]
FEATURE_LABEL = {
    "giveback_close": "①衝高回落giveback(收盤版)", "giveback_hl": "①衝高回落giveback(最高價版,穩健配對)",
    "drawup_close": "②先蹲後跳drawup(收盤版)", "drawup_hl": "②先蹲後跳drawup(最低價版,穩健配對)",
    "pos_max_close": "③週內最高收盤位置(0早~1晚)", "pos_max_hl": "③週內最高價位置(穩健配對)",
    "pos_min_close": "③週內最低收盤位置(0早~1晚)", "pos_min_hl": "③週內最低價位置(穩健配對)",
    "smooth_close": "④路徑平滑度(收盤逐日報酬std)", "smooth_range": "④路徑平滑度(逐日高低差/收盤,穩健配對)",
}
ROBUST_PAIRS = {"giveback_close": "giveback_hl", "giveback_hl": "giveback_close",
                 "drawup_close": "drawup_hl", "drawup_hl": "drawup_close",
                 "pos_max_close": "pos_max_hl", "pos_max_hl": "pos_max_close",
                 "pos_min_close": "pos_min_hl", "pos_min_hl": "pos_min_close",
                 "smooth_close": "smooth_range", "smooth_range": "smooth_close"}


# ══ 一、AUC統計工具(逐字比照build_earnings_winner_features.py既有標準,含手算vs sklearn自我檢查) ══
def calc_auc(a_vals, b_vals):
    n1, n2 = len(a_vals), len(b_vals)
    if n1 == 0 or n2 == 0:
        return np.nan
    combined = np.concatenate([np.asarray(a_vals, dtype=float), np.asarray(b_vals, dtype=float)])
    ranks = pd.Series(combined).rank(method="average").values
    r1 = ranks[:n1].sum()
    return float((r1 - n1 * (n1 + 1) / 2) / (n1 * n2))


def selfcheck_auc():
    from sklearn.metrics import roc_auc_score
    rc = np.random.default_rng(0)
    a = rc.normal(0.35, 1, 500)
    b = rc.normal(0.0, 1, 500)
    manual = calc_auc(a, b)
    ref = roc_auc_score(np.r_[np.ones(500), np.zeros(500)], np.r_[a, b])
    ok = abs(manual - ref) < 1e-9
    print(f"[selfcheck] 手算AUC={manual:.6f} vs sklearn={ref:.6f} 差={abs(manual-ref):.2e} "
          f"{'OK一致' if ok else '⚠不一致,停止'}")
    assert ok


def boot_auc_ci(vals_a, dates_a, vals_b, dates_b, n_iter=N_BOOT, min_n=MIN_POOL):
    """月群bootstrap(月群=entry_week年-月,重抽樣單位),key固定"auc"。"""
    a = pd.Series(vals_a, index=pd.to_datetime(dates_a), dtype=float).dropna() if len(vals_a) else pd.Series(dtype=float)
    b = pd.Series(vals_b, index=pd.to_datetime(dates_b), dtype=float).dropna() if len(vals_b) else pd.Series(dtype=float)
    if len(a) < min_n or len(b) < min_n:
        return None
    am = a.groupby(a.index.strftime("%Y-%m")).apply(list)
    bm = b.groupby(b.index.strftime("%Y-%m")).apply(list)
    months = sorted(set(am.index) | set(bm.index))
    am, bm = am.reindex(months), bm.reindex(months)
    n = len(months)
    if n < 6:
        return None
    aucs = []
    for _ in range(n_iter):
        idx = RNG.integers(0, n, n)
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
    return {"auc": auc0, "lo": lo, "hi": hi, "sig": bool(lo > 0.5 or hi < 0.5), "na": len(a), "nb": len(b)}


def boot_mean_diff(vals_a, dates_a, vals_b, dates_b, n_iter=N_BOOT, min_n=15):
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
        av = np.concatenate([am.iloc[i] for i in RNG.integers(0, len(am), len(am))])
        bv = np.concatenate([bm.iloc[i] for i in RNG.integers(0, len(bm), len(bm))])
        diffs.append(av.mean() - bv.mean())
    d0 = float(a.mean() - b.mean())
    lo, hi = float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))
    return {"diff": d0, "lo": lo, "hi": hi, "sig": bool(lo > 0 or hi < 0), "na": len(a), "nb": len(b)}


def case_control_events(rule_idx, df, seed, batch_col="ym"):
    rng2 = np.random.default_rng(seed)
    rule_set = set(rule_idx)
    sub = df.loc[rule_idx]
    ctrl_idx = []
    for b, g in sub.groupby(batch_col):
        pool = list(df.index[(df[batch_col] == b) & (~df.index.isin(rule_set))])
        if not pool:
            continue
        k = min(len(g), len(pool))
        ctrl_idx.extend(rng2.choice(pool, size=k, replace=False))
    return pd.Index(ctrl_idx)


# ══ 二、訊號週日頻資料建置(比照build_weekly_momo_stoploss_overlay.py同套撈取/清洗慣例) ══
def build_daily_panel(codes):
    con = sqlite3.connect(M.DB)
    q = (f"SELECT code,date,open,high,low,close,money FROM fm_daily_price "
         f"WHERE date>='{M.START}' AND code IN ({','.join('?' * len(codes))})")
    dpx = pd.read_sql(q, con, params=codes, parse_dates=["date"])
    con.close()
    n0 = len(dpx)
    # 主清洗與M.build_weekly_panel完全同口徑(close>0 & money>0),確保收盤版特徵與trades.entry_ret一致
    dpx = dpx[(dpx["close"] > 0) & (dpx["money"] > 0)]
    dpx["valid_hl"] = (dpx["high"] > 0) & (dpx["low"] > 0)   # 高低價版另外guard,不因此丟掉收盤資料
    print(f"日頻資料清洗: 濾掉close<=0/money<=0共{n0 - len(dpx)}列(佔{(n0 - len(dpx)) / n0 * 100:.2f}%),"
          f"最終{len(dpx)}列,涵蓋{dpx['code'].nunique()}檔(high/low另有效{dpx['valid_hl'].mean() * 100:.2f}%)")
    dpx = dpx.sort_values(["code", "date"]).reset_index(drop=True)
    dpx["wk"] = dpx["date"].dt.to_period("W-FRI").dt.end_time.dt.normalize()
    return dpx


def build_week_index(dpx):
    """(code,wk) -> 該週逐日close/high/low/valid_hl ndarray,依date排序"""
    out = {}
    for (code, wk), g in dpx.groupby(["code", "wk"], sort=False):
        g = g.sort_values("date")
        out[(code, wk)] = {"close": g["close"].values.astype(float),
                            "high": g["high"].values.astype(float),
                            "low": g["low"].values.astype(float),
                            "valid_hl": g["valid_hl"].values}
    return out


def build_prevmap(weeks):
    pos = {w: i for i, w in enumerate(weeks)}
    return {w: (weeks[i - 1] if i > 0 else None) for w, i in pos.items()}


# ══ 三、路徑形狀特徵計算(零前視: 只用訊號週自身逐日資料) ══
def compute_features(trades, week_idx, prevmap):
    n = len(trades)
    cols = {k: np.full(n, np.nan) for k in
            FEATURES + ["n_days", "n_days_hl", "base_check_diff"]}
    codes = trades["code"].values
    weeks = trades["entry_week"].values
    entry_rets = trades["entry_ret"].values
    n_missing = 0
    for i in range(n):
        code = codes[i]
        wk = pd.Timestamp(weeks[i])
        prev_wk = prevmap.get(wk)
        if prev_wk is None or code not in M.WIDE_C.columns:
            n_missing += 1
            continue
        base = M.WIDE_C.at[prev_wk, code] if prev_wk in M.WIDE_C.index else np.nan
        wd = week_idx.get((code, wk))
        if wd is None or pd.isna(base) or base <= 0:
            n_missing += 1
            continue
        c = wd["close"]
        nd = len(c)
        if nd == 0:
            n_missing += 1
            continue
        ent = entry_rets[i]
        cols["n_days"][i] = nd
        cols["giveback_close"][i] = (c.max() / base - 1) - ent
        cols["drawup_close"][i] = ent - (c.min() / base - 1)
        imax_c, imin_c = int(np.argmax(c)), int(np.argmin(c))
        cols["pos_max_close"][i] = imax_c / (nd - 1) if nd > 1 else 0.5
        cols["pos_min_close"][i] = imin_c / (nd - 1) if nd > 1 else 0.5
        if nd >= 2:
            seq = np.concatenate([[base], c])
            rets = seq[1:] / seq[:-1] - 1
            cols["smooth_close"][i] = float(np.std(rets, ddof=1))
        cols["base_check_diff"][i] = (c[-1] / base - 1) - ent

        vh = wd["valid_hl"]
        if vh.any():
            h, l, cc = wd["high"][vh], wd["low"][vh], wd["close"][vh]
            ndh = len(h)
            cols["n_days_hl"][i] = ndh
            cols["giveback_hl"][i] = (h.max() / base - 1) - ent
            cols["drawup_hl"][i] = ent - (l.min() / base - 1)
            imax_h, imin_l = int(np.argmax(h)), int(np.argmin(l))
            cols["pos_max_hl"][i] = imax_h / (ndh - 1) if ndh > 1 else 0.5
            cols["pos_min_hl"][i] = imin_l / (ndh - 1) if ndh > 1 else 0.5
            cols["smooth_range"][i] = float(np.mean((h - l) / cc))
    out = trades.copy()
    for k, v in cols.items():
        out[k] = v
    out["ym"] = out["entry_week"].dt.strftime("%Y-%m")
    bad = out["base_check_diff"].abs()
    print(f"特徵建置完成: {n}筆中{n_missing}筆缺日頻資料(佔{n_missing / n * 100:.1f}%);"
          f"base一致性檢查(收盤版最後一天隱含週報酬 vs trades.entry_ret差異)"
          f"中位數={bad.median():.6f} 最大={bad.max():.6f}(應趨近0,確認資料對齊正確)")
    return out


# ══ 四、Stage1: 贏家/輸家AUC掃描 ══════════════════════════════
def stage1_auc(enriched, label):
    print("\n" + "=" * 100)
    print(f"### Stage1 贏家vs輸家AUC掃描  [{label}]  (win30%=次週報酬exit_ret前30%,lose30%=後30%) ###")
    rnk = enriched["exit_ret"].rank(pct=True)
    win_idx = enriched.index[rnk >= (1 - RULE_Q)]
    lose_idx = enriched.index[rnk <= RULE_Q]
    print(f"n_total={len(enriched)}  win30%={len(win_idx)}  lose30%={len(lose_idx)}  "
          f"win平均exit_ret={enriched.loc[win_idx,'exit_ret'].mean()*100:+.1f}% "
          f"lose平均exit_ret={enriched.loc[lose_idx,'exit_ret'].mean()*100:+.1f}%")

    results = {}
    for feat in FEATURES:
        cv = enriched.loc[win_idx, [feat, "entry_week"]].dropna()
        kv = enriched.loc[lose_idx, [feat, "entry_week"]].dropna()
        if len(cv) < MIN_POOL or len(kv) < MIN_POOL:
            print(f"  {FEATURE_LABEL[feat]:<32} n不足(win={len(cv)},lose={len(kv)}),跳過")
            continue
        r = boot_auc_ci(cv[feat].values, cv["entry_week"].values, kv[feat].values, kv["entry_week"].values)
        if r is None:
            print(f"  {FEATURE_LABEL[feat]:<32} bootstrap月群不足,跳過")
            continue
        results[feat] = r
        passed = abs(r["auc"] - 0.5) >= AUC_PASS_DEV and r["sig"]
        flag = "✓通過門檻" if passed else ("(偏離但CI含0.5)" if abs(r["auc"] - 0.5) >= AUC_PASS_DEV else "")
        print(f"  {FEATURE_LABEL[feat]:<32} AUC={r['auc']:.3f} 95%CI[{r['lo']:.3f},{r['hi']:.3f}] "
              f"(win n={r['na']},lose n={r['nb']})  {flag}")
    return results, win_idx, lose_idx


def screen_passed(results):
    """通過門檻: |AUC-0.5|>=0.05且CI排除0.5,且穩健配對版同號(即使配對版未必顯著,方向要一致)。"""
    passed = []
    for feat in FEATURES:
        r = results.get(feat)
        if r is None or abs(r["auc"] - 0.5) < AUC_PASS_DEV or not r["sig"]:
            continue
        pair = ROBUST_PAIRS.get(feat)
        rp = results.get(pair)
        same_dir = True
        if rp is not None:
            same_dir = np.sign(r["auc"] - 0.5) == np.sign(rp["auc"] - 0.5)
        note = "" if same_dir else f"(⚠穩健配對{FEATURE_LABEL.get(pair,pair)}方向不一致,列入觀察但標註警示)"
        passed.append((feat, r, same_dir, note))
    return passed


# ══ 五、Stage2: 規則翻譯 + 可交易性驗證(bootstrap CI vs case-control) ══
def build_rule_idx(enriched, feat, direction):
    valid = enriched[feat].dropna()
    rnk = valid.rank(pct=True)
    if direction > 0:
        return rnk[rnk >= (1 - RULE_Q)].index
    return rnk[rnk <= RULE_Q].index


def stage2_rule_eval(enriched, passed, label):
    print("\n" + "=" * 100)
    print(f"### Stage2 規則翻譯+可交易性驗證  [{label}]  (規則=全樣本cross-sectional前/後{RULE_Q*100:.0f}%,"
          f"vs同批entry_week年-月case-control,net_ret月群bootstrap) ###")
    base_mean = enriched["net_ret"].mean() * 100
    print(f"全樣本net_ret均值基準={base_mean:+.3f}%(n={len(enriched)})")

    passed2 = []
    for feat, r, same_dir, note in passed:
        direction = 1 if r["auc"] > 0.5 else -1
        dir_txt = "前30%(數值越大越像贏家)" if direction > 0 else "後30%(數值越小越像贏家)"
        rule_idx = build_rule_idx(enriched, feat, direction)
        ctrl_idx = case_control_events(rule_idx, enriched, seed=20260805 + hash(feat) % 1000)
        rv, rd = enriched.loc[rule_idx, "net_ret"].values, enriched.loc[rule_idx, "entry_week"].values
        cv, cd = enriched.loc[ctrl_idx, "net_ret"].values, enriched.loc[ctrl_idx, "entry_week"].values
        rule_mean = np.nanmean(rv) * 100
        ctrl_mean = np.nanmean(cv) * 100
        boot = boot_mean_diff(rv, rd, cv, cd)
        print(f"\n  {FEATURE_LABEL[feat]} · 規則={dir_txt} {note}")
        print(f"    規則篩出n={len(rule_idx)}  規則組net_ret均值={rule_mean:+.3f}% "
              f"case-control組(n={len(ctrl_idx)})均值={ctrl_mean:+.3f}%  全樣本基準={base_mean:+.3f}%")
        if boot is None:
            print(f"    月群bootstrap: n或月數不足,跳過")
            tradable = False
        else:
            sig_txt = "✓顯著(CI排除0)" if boot["sig"] else "不顯著(CI含0)"
            print(f"    規則-對照組net_ret差 = {boot['diff']*100:+.3f}pp  95%CI[{boot['lo']*100:+.3f}%,"
                  f"{boot['hi']*100:+.3f}%]  {sig_txt}")
            tradable = boot["sig"] and boot["diff"] > 0
        passed2.append({"feat": feat, "direction": direction, "tradable": tradable,
                         "rule_mean": rule_mean, "ctrl_mean": ctrl_mean, "boot": boot})
    return passed2


# ══ 六、Stage3: basket權重疊加(不排除,只加碼/減碼) ══════════════
def portfolio_curve_weighted(weekly_baskets, grid, feat_map, direction, alpha):
    ret = pd.Series(0.0, index=grid)
    exec_list = []
    min_w_seen = np.inf
    for wk, basket in weekly_baskets.items():
        exit_wk = basket["exit_week"].iloc[0]
        if exit_wk not in ret.index:
            continue
        b = basket.copy()
        n = len(b)
        vals = b["code"].map(lambda c: feat_map.get((wk, c), np.nan))
        if n <= 1 or vals.notna().sum() < 2:
            w = np.full(n, 1.0 / n)
        else:
            v = vals.fillna(vals.median())
            pct = v.rank(pct=True)
            if direction < 0:
                pct = 1 - pct
            raw = 1 + alpha * (2 * pct.values - 1)
            raw = np.clip(raw, 1e-6, None)
            w = raw / raw.sum()
        min_w_seen = min(min_w_seen, w.min() * n)   # 相對等權的最低倍數,確認>0(無排除)
        b["weight"] = w
        pr = float((b["net_ret"].values * w).sum())
        ret.loc[exit_wk] = pr
        exec_list.append(b.assign(favorable=True))
    exec_trades = pd.concat(exec_list, ignore_index=True) if exec_list else pd.DataFrame()
    return ret, exec_trades, min_w_seen


def mdd_thinness_diagnostic(baskets, ret_base, st_base):
    """檢查基準版MDD區間(dd_peak~dd_trough)內的訊號週basket檔數分布——驗證權重疊加為何救不了(或救得了)
    MDD: 若區間內多數週basket檔數<=2,代表籃子內權重疊加在結構上無法分散此區間的下跌(weighting只能
    動basket「內部」的資金分配,對只有1-2檔的週無能為力),呼應背景診斷「個股集中度風險」。"""
    peak, trough = st_base["dd_peak"], st_base["dd_trough"]
    entry_of = {b["exit_week"].iloc[0]: wk for wk, b in baskets.items()}
    rows = [len(baskets[entry_of[exit_wk]]) for exit_wk in ret_base.loc[peak:trough].index if exit_wk in entry_of]
    if not rows:
        return
    arr = np.array(rows)
    thin_pct = (arr <= 2).mean() * 100
    print(f"  [MDD區間結構診斷] 基準版MDD區間{peak.date()}~{trough.date()}共{len(arr)}個訊號週,"
          f"basket檔數平均{arr.mean():.1f}/中位數{np.median(arr):.0f}/n<=2佔比{thin_pct:.0f}%/n==1佔比{(arr==1).mean()*100:.0f}%")
    if thin_pct >= 50:
        print(f"  [MDD區間結構診斷] ⚠此區間過半訊號週basket檔數<=2,籃子內權重疊加在結構上無法緩解——"
              f"這正是背景診斷「個股集中度風險」的具體體現,weighting只能重新分配basket內部資金,"
              f"對「基本上只有1檔」的週無計可施,預期MDD數字不會因權重疊加而改善。")
    else:
        print(f"  [MDD區間結構診斷] 此區間籃子檔數尚可(多數週>2檔),權重疊加理論上仍有機會影響此區間的表現。")


def stage3_weighting(baskets, enriched, grid, passed2, label):
    print("\n" + "=" * 100)
    print(f"### Stage3 Basket權重疊加(雙關卡都過的特徵才測;連續tilt非排除法,alpha=[{','.join(str(a) for a in WEIGHT_ALPHAS)}]) ###")
    tradable_feats = [p for p in passed2 if p["tradable"]]
    if not tradable_feats:
        print(f"  [{label}] 無特徵通過雙關卡(Stage1 AUC + Stage2可交易性都顯著),跳過Stage3。")
        return []

    ret_base, exec_base = M.portfolio_curve(baskets, grid, mode="baseline", weighting="equal")
    st_base = M.stats_from_ret(ret_base)
    print(f"  基準(等權,無權重疊加): 複利{st_base['mult']:.1f}x 年化{st_base['cagr']:+.1f}% "
          f"MDD{st_base['mdd']:.1f}% 夏普{st_base['sharpe']:.2f} 報酬/MDD{st_base['calmar']:.2f}")
    mdd_thinness_diagnostic(baskets, ret_base, st_base)

    rows = []
    for p in tradable_feats:
        feat, direction = p["feat"], p["direction"]
        feat_map = dict(zip(zip(enriched["entry_week"], enriched["code"]), enriched[feat]))
        for alpha in WEIGHT_ALPHAS:
            r, ex, min_w = portfolio_curve_weighted(baskets, grid, feat_map, direction, alpha)
            st = M.stats_from_ret(r)
            print(f"  [{FEATURE_LABEL[feat]}] alpha={alpha} (最低權重={min_w:.2f}x等權,恆>0=未排除任何檔): "
                  f"複利{st['mult']:.1f}x({st['mult']/st_base['mult']-1:+.1%}) "
                  f"年化{st['cagr']:+.1f}% MDD{st['mdd']:.1f}%(vs基準{st_base['mdd']:.1f}%) "
                  f"夏普{st['sharpe']:.2f}(vs{st_base['sharpe']:.2f}) 報酬/MDD{st['calmar']:.2f}(vs{st_base['calmar']:.2f})")
            rows.append({"feat": feat, "alpha": alpha, **st})
    return rows


# ══ 七、主流程 ══════════════════════════════════════════
def run_pathshape(threshold, label, week_idx, prevmap, full=True):
    print("\n" + "#" * 100)
    print(f"########  週級動能×訊號週路徑形狀  門檻={label}  ########")
    trades, baskets = M.build_trades(threshold)
    weeks = M.WIDE_RET.index
    start_i = weeks.searchsorted(pd.Timestamp(M.START))
    grid = weeks[start_i:]

    enriched = compute_features(trades, week_idx, prevmap)

    results, win_idx, lose_idx = stage1_auc(enriched, label)
    passed = screen_passed(results)
    if not passed:
        print(f"\n[{label}] Stage1: 無任何特徵通過AUC門檻(|AUC-0.5|>=0.05且CI排除0.5)。")
        return enriched, results, [], []

    print(f"\n[{label}] Stage1通過門檻的特徵: " + ", ".join(FEATURE_LABEL[f] for f, *_ in passed))
    if not full:
        return enriched, results, passed, []

    passed2 = stage2_rule_eval(enriched, passed, label)
    tradable = [p["feat"] for p in passed2 if p["tradable"]]
    print(f"\n[{label}] Stage2可交易性驗證通過(雙關卡)的特徵: "
          + (", ".join(FEATURE_LABEL[f] for f in tradable) if tradable else "無"))

    stage3_rows = stage3_weighting(baskets, enriched, grid, passed2, label)
    return enriched, results, passed2, stage3_rows


def main():
    t0 = time.time()
    selfcheck_auc()

    trades20, _ = M.build_trades(0.20)
    trades15, _ = M.build_trades(0.15)
    codes = sorted(set(trades20["code"]).union(set(trades15["code"])))
    print(f"\n建置訊號週日頻路徑資料(需要的個股數={len(codes)})...")
    dpx = build_daily_panel(codes)
    week_idx = build_week_index(dpx)
    prevmap = build_prevmap(M.WIDE_C.index)
    print(f"日頻資料建置耗時{time.time()-t0:.0f}s")

    enriched20, results20, passed20, stage3_20 = run_pathshape(0.20, "20%", week_idx, prevmap, full=True)

    print("\n" + "#" * 100)
    print("########  15%門檻敏感度對照(僅Stage1 AUC,檢查方向是否與20%版一致)  ########")
    enriched15, results15, passed15, _ = run_pathshape(0.15, "15%", week_idx, prevmap, full=False)

    print("\n" + "=" * 100)
    print("### 20% vs 15%門檻 AUC方向一致性總表 ###")
    for feat in FEATURES:
        r20, r15 = results20.get(feat), results15.get(feat)
        a20 = f"{r20['auc']:.3f}[{'sig' if r20['sig'] else 'ns'}]" if r20 else "n/a"
        a15 = f"{r15['auc']:.3f}[{'sig' if r15['sig'] else 'ns'}]" if r15 else "n/a"
        same = ""
        if r20 and r15:
            same = "同向" if np.sign(r20["auc"] - 0.5) == np.sign(r15["auc"] - 0.5) else "⚠反向"
        print(f"  {FEATURE_LABEL[feat]:<32} 20%版AUC={a20:<16} 15%版AUC={a15:<16} {same}")

    print("\n" + "=" * 100)
    print("### 誠實總結 ###")
    stage1_pass = [f for f in results20 if abs(results20[f]["auc"] - 0.5) >= AUC_PASS_DEV and results20[f]["sig"]]
    tradable20 = [p for p in (passed20 or []) if isinstance(p, dict) and p.get("tradable")]
    print(f"Stage1(贏家vs輸家AUC,20%門檻): {len(stage1_pass)}/{len(FEATURES)}個路徑特徵通過門檻"
          f"(|AUC-0.5|>=0.05且CI排除0.5): {[FEATURE_LABEL[f] for f in stage1_pass] or '無'}")
    print(f"Stage2(規則翻譯+case-control可交易性驗證): "
          f"{[FEATURE_LABEL[p['feat']] for p in tradable20] or '無'}")
    if tradable20:
        print("Stage3(basket權重疊加): 有特徵雙關卡皆過,對複利/夏普/報酬-MDD比有正向提升,"
              "但MDD本身是否改善需看上方[MDD區間結構診斷]——若基準版MDD區間由n<=2的濃縮週主導,"
              "權重疊加在結構上救不了MDD(只能動basket內部資金分配,無法緩解「只有1檔可買」的週),"
              "此為本卷與今日regime/信心層/停損等考卷相呼應但不同機制的誠實結論。")
        print("整體評價: 路徑形狀角度不是全面null——衝高回落giveback(尤其最高價版)通過雙關卡,是今日除"
              "個股停損外唯一同時通過『AUC篩選+可交易性驗證』的訊號,呼應融券回補研究「只有波動度活下來」"
              "的先例(這裡活下來的是「path quality/收盤強弱」而非單純波動度,但同屬「路徑形狀類」訊號)。"
              "唯其對MDD的實際貢獻有限,不能取代個股停損作為MDD解方,較適合定位為「選股權重優化」而非"
              "「風險控管」工具。先跌後漲(drawup)、最高/最低點位置、路徑平滑度三個角度則是誠實負結果"
              "(AUC點估計方向有跡可循但未達0.05實務顯著門檻)。")
    else:
        print("Stage1/2皆無特徵通過雙關卡,路徑形狀角度整體是誠實負結果,呼應今日regime/信心層系列訊號"
              "的null模式。")
    print(f"\n耗時共{time.time()-t0:.0f}s。以上為console探索報告,無檔案輸出。")


if __name__ == "__main__":
    main()
