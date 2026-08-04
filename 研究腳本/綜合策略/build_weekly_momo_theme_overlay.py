# -*- coding: utf-8 -*-
"""週級強者續強×題材/籌碼訊號選股輔助測試(2026-08-05,使用者:「我們明明有研究這麼多指標、題材營收動能、
共振、大題材檢查等等,這些都能考慮到10檔裡面,為何都不去研究?可能可以提高勝率以及賺賠比」)。

⚠與今天d4w regime開關系列的關鍵差異: 本卷不是「進出場時機開關」(那個方向已測過大量失敗案例,任何讓籃子
變薄的機制都會讓MDD惡化),是**選股層面的輔助**——在既有10檔籃子「內部」做權重調整,或在籃子太薄時用題材
訊號「遞補」,不做硬性排除。

兩個既有訊號,逐字複用其計算邏輯(不重新發明):
  a) 題材月營收動能score=4(`研究腳本/題材動能/build_theme_score_topn.py::build_score`函式,
     live已上板規則基底)。score(theme,月m)由mom_score(近3個已公布月連續MoM>0streak)+trend_yoy3
     (近3已公布月YoY均值>0)組成,0~4分,score=4=近3月MoM連續為正且YoY趨勢確認。
     可用日期(零前視,已用tmp_theme_momentum_v2_panel.pkl entry_day欄位100%驗證還原公式):
     score(theme,m)在「m月15號起首個交易日」才視為當下已知(該日之前revenue for m-1已公告完畢,
     score本身只用到m-1/m-2/m-3已公布月資料,15號進場=已上板現行規則,早進場的更早可行版本另有
     build_score4_early_entry.py研究過,本卷沿用「已上板」版本口徑,不用更激進版本)。
  b) 多週期題材共振(`build_resonance_theme.py`,watch狀態候選,尚未上板)。題材共振週定義=同main_group
     裡當週>=2檔個股同時「日線爆量創高(單日+4%且量>=2倍20日均量)+週線同步創12週高」——直接讀取已快取的
     `快取/tmp_resonance_theme_events.pkl`(未經episode去重的原始週次事件表,才能反映「當週」而非「波段
     首週」的狀態),不重新計算。

兩者都用同一套classification表main_group當題材分類(與score/resonance計算來源同一張表,taxonomy一致)。

方法論(比照今天融券回補贏家/輸家逆向工程AUC考卷的兩階段設計,避免只做AUC就下結論):
  第一階段: 週級動能候選股票(通過20%漲幅門檻+0.3億流動性門檻,取「候選」全集,不是已進場top10)
           按次週報酬分組,計算score4/resonance旗標與次週報酬的AUC(rank-sum,月群bootstrap CI)。
           |AUC-0.5|>=0.05且CI排除0.5才算有鑑別力,通過才進第二階段。
  第二階段(僅通過的訊號才做): ①加權版=籃子內成員若屬於當週訊號題材給更高basket權重(不做硬濾網,
           比照今天「加權不用硬濾網」的教訓);②籃子擴充版=當週純price momentum訊號股籃子<5檔時,
           從該訊號當週活躍題材的成員裡(即使沒過20%門檻)按自身當週報酬由高到低遞補湊滿5檔,
           對症「籃子太薄=MDD元凶」這個病根。全樣本回測(20%門檻主/15%門檻敏感度對照)。

沿用M模組(build_weekly_momo_regime_overlay.py)面板/交易/組合曲線/統計函式,不重新發明。

⚠已知限制(務必誠實揭露,先驗證coverage再解讀AUC): classification表country='台'僅306檔個股、43個
main_group題材分類,相對全市場fm_daily_price(2031檔)覆蓋率很窄(多為中大型/主流題材股,週動能候選常見
的中小型飆股大機率不在分類表內)。本卷coverage診斷會先誠實列出候選池裡有分類覆蓋的比例,覆蓋率若過低,
AUC統計力天生受限,是資料限制而非訊號本身無效的證明,會在結論裡明確區分兩者。

用法: python 研究腳本/綜合策略/build_weekly_momo_theme_overlay.py (從根目錄執行,鐵律)
產出: 純console報告,無檔案輸出。
"""
import sqlite3
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "研究腳本/綜合策略")
import build_weekly_momo_regime_overlay as M  # noqa: E402
sys.path.insert(0, "研究腳本/題材動能")
from build_theme_score_topn import build_score, MIN_MEMBERS  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

RESONANCE_PKL = "快取/tmp_resonance_theme_events.pkl"
THRESHOLDS = [(0.20, "20%"), (0.15, "15%")]
AUC_PRESCREEN_DEV = 0.05     # |AUC-0.5|判定門檻(融券回補卷用0.08但那是winner_features多特徵掃描,
                              # 本卷只有2個訊號預先指定、非data-mining篩選,門檻放寬到0.05較合理)
N_BOOT = 1000
RNG = np.random.default_rng(20260805)
EXPAND_TARGET_N = 5
WEIGHT_MULT_PRIMARY = 2.0
WEIGHT_MULT_ALT = 3.0


# ══ 一、AUC統計工具(rank-sum,與sklearn.roc_auc_score等價;house既有慣例:純統計函式各卷各自複製) ══
def calc_auc(a_vals, b_vals):
    n1, n2 = len(a_vals), len(b_vals)
    if n1 == 0 or n2 == 0:
        return np.nan
    combined = np.concatenate([np.asarray(a_vals, dtype=float), np.asarray(b_vals, dtype=float)])
    ranks = pd.Series(combined).rank(method="average").values
    r1 = ranks[:n1].sum()
    return float((r1 - n1 * (n1 + 1) / 2) / (n1 * n2))


def boot_auc_ci(a_df, b_df, outcome_col="net_ret", cluster_col="cluster_month",
                 n_boot=N_BOOT, min_n=30):
    a = a_df[[outcome_col, cluster_col]].dropna()
    b = b_df[[outcome_col, cluster_col]].dropna()
    if len(a) < min_n or len(b) < min_n:
        return None
    am = a.groupby(cluster_col)[outcome_col].apply(list)
    bm = b.groupby(cluster_col)[outcome_col].apply(list)
    months = sorted(set(am.index) | set(bm.index))
    am, bm = am.reindex(months), bm.reindex(months)
    n = len(months)
    if n < 6:
        return None
    aucs = []
    for _ in range(n_boot):
        idx = RNG.integers(0, n, n)
        av_parts = [am.iloc[i] for i in idx if isinstance(am.iloc[i], list)]
        bv_parts = [bm.iloc[i] for i in idx if isinstance(bm.iloc[i], list)]
        av = np.concatenate(av_parts) if av_parts else np.array([])
        bv = np.concatenate(bv_parts) if bv_parts else np.array([])
        if len(av) < 5 or len(bv) < 5:
            continue
        aucs.append(calc_auc(av, bv))
    if len(aucs) < n_boot * 0.5:
        return None
    auc0 = calc_auc(a[outcome_col].values, b[outcome_col].values)
    lo, hi = float(np.percentile(aucs, 2.5)), float(np.percentile(aucs, 97.5))
    return {"auc": auc0, "lo": lo, "hi": hi, "sig": bool(lo > 0.5 or hi < 0.5),
            "na": len(a), "nb": len(b), "n_boot": len(aucs)}


def auc_verdict(r):
    if r is None:
        return False, "樣本不足(n<30或月群<6),無法判定,保守不進第二階段"
    passed = abs(r["auc"] - 0.5) >= AUC_PRESCREEN_DEV and r["sig"]
    txt = (f"AUC={r['auc']:.3f} 95%CI[{r['lo']:.3f},{r['hi']:.3f}] na={r['na']} nb={r['nb']} "
           f"{'✓通過(|AUC-0.5|>=0.05且CI排除0.5)' if passed else '未通過'}")
    return passed, txt


# ══ 二、題材分類/theme mapping ══════════════════════════════════
def load_theme_maps():
    con = sqlite3.connect(M.DB)
    cls = pd.read_sql("SELECT code, main_group FROM classification WHERE country='台'",
                       con, dtype={"code": str}).drop_duplicates()
    con.close()
    code2themes = cls.groupby("code")["main_group"].apply(list).to_dict()
    theme2codes = cls.groupby("main_group")["code"].apply(list).to_dict()
    return code2themes, theme2codes, cls


# ══ 三、a)題材月營收動能score=4 週對齊面板(零前視,見檔頭entry_day公式驗證說明) ══
def build_score_by_theme(cls):
    con = sqlite3.connect(M.DB)
    rev = pd.read_sql("SELECT code, date, revenue FROM fm_month_rev", con, dtype={"code": str})
    con.close()
    rev["m"] = pd.to_datetime(rev.date)
    themes = sorted(cls["main_group"].dropna().unique())
    score_by_theme = {}
    for ind in themes:
        codes = cls[cls["main_group"] == ind]["code"].unique()
        g = rev[rev.code.isin(codes)]
        if g.code.nunique() < MIN_MEMBERS:
            continue
        wide = g.pivot_table(index="m", columns="code", values="revenue", aggfunc="first").sort_index()
        full = build_score(wide, "full")
        score_by_theme[ind] = full["score_full"].dropna()
    print(f"[score4] 有效題材(FinMind營收覆蓋>={MIN_MEMBERS}檔): {len(score_by_theme)}個")
    return score_by_theme


def load_trading_calendar():
    con = sqlite3.connect(M.DB)
    cal = pd.read_sql("SELECT DISTINCT date FROM index_daily WHERE market='TAIEX' ORDER BY date",
                       con, parse_dates=["date"])["date"]
    con.close()
    return cal


def entry_day_for_month(m, cal_values):
    target = np.datetime64(m + pd.Timedelta(days=14))
    pos = np.searchsorted(cal_values, target)
    return cal_values[pos] if pos < len(cal_values) else np.datetime64("NaT")


def build_weekly_score_panel(score_by_theme, cal, week_index):
    cal_values = cal.values
    out = {}
    for theme, s in score_by_theme.items():
        avail_idx = [entry_day_for_month(m, cal_values) for m in s.index]
        avail_series = pd.Series(s.values, index=pd.to_datetime(avail_idx))
        avail_series = avail_series[~avail_series.index.isna()]
        if len(avail_series) == 0:
            continue
        avail_series = avail_series[~avail_series.index.duplicated(keep="last")].sort_index()
        combined_idx = avail_series.index.union(week_index)
        full = avail_series.reindex(combined_idx).ffill()
        out[theme] = full.reindex(week_index).to_dict()
    return out  # dict theme -> {week_timestamp: score(可能NaN=尚未有任何可用score)}


# ══ 四、b)多週期題材共振 週對齊面板(直接讀快取,不重算) ══════════════
def build_theme_resonance_weeks():
    ev = pd.read_pickle(RESONANCE_PKL)
    d = {}
    for theme, g in ev.groupby("theme"):
        d[theme] = set(g["week"])
    print(f"[resonance] 有效題材(曾出現>=2檔同振事件): {len(d)}個,原始事件{len(ev)}筆"
          f"({ev.week.min().date()}~{ev.week.max().date()})")
    return d


# ══ 五、flag查詢函式 ══════════════════════════════════════════
def make_flag_fn_score4(weekly_score_panel, code2themes):
    def fn(wk, code):
        for t in code2themes.get(code, []):
            d = weekly_score_panel.get(t)
            if d is not None:
                v = d.get(wk, np.nan)
                if pd.notna(v) and v == 4:
                    return True
        return False
    return fn


def make_flag_fn_resonance(theme_resonance_weeks, code2themes):
    def fn(wk, code):
        for t in code2themes.get(code, []):
            if wk in theme_resonance_weeks.get(t, ()):
                return True
        return False
    return fn


def make_theme_active_fn_score4(weekly_score_panel):
    def fn(theme, wk):
        d = weekly_score_panel.get(theme)
        if d is None:
            return False
        v = d.get(wk, np.nan)
        return bool(pd.notna(v) and v == 4)
    return fn


def make_theme_active_fn_resonance(theme_resonance_weeks):
    def fn(theme, wk):
        return wk in theme_resonance_weeks.get(theme, ())
    return fn


# ══ 六、候選池建置(uncapped,「候選」全集非已進場top10) ══════════════
def build_all_candidates(threshold):
    weeks = M.WIDE_RET.index
    start_i = weeks.searchsorted(pd.Timestamp(M.START))
    rows = []
    for i in range(max(start_i, 1), len(weeks) - 1):
        wk = weeks[i]
        ret_i = M.WIDE_RET.iloc[i]
        liq_i = M.LIQ_OK.iloc[i].reindex(ret_i.index).fillna(False)
        cand = ret_i[(ret_i >= threshold) & liq_i].dropna()
        if len(cand) == 0:
            continue
        exit_ret = M.WIDE_RET.iloc[i + 1]
        for c in cand.index:
            er = exit_ret.get(c, np.nan)
            if pd.isna(er):
                continue
            rows.append({"entry_week": wk, "exit_week": weeks[i + 1], "code": c,
                         "entry_ret": float(cand[c]), "exit_ret": float(er),
                         "net_ret": float(er) - M.COST})
    df = pd.DataFrame(rows)
    df["cluster_month"] = df["entry_week"].dt.to_period("M").astype(str)
    return df


# ══ 七、第一階段: coverage診斷 + AUC贏家/輸家初篩 ══════════════════
def stage1_auc(threshold, label, code2themes, score4_fn, reso_fn):
    print("\n" + "=" * 108)
    print(f"### 第一階段 AUC初篩  動能門檻={label}(候選全集,非top10) ###")
    cand = build_all_candidates(threshold)
    cand["has_theme"] = cand["code"].map(lambda c: len(code2themes.get(c, [])) > 0)
    cand["score4"] = [score4_fn(wk, c) for wk, c in zip(cand.entry_week, cand.code)]
    cand["resonance"] = [reso_fn(wk, c) for wk, c in zip(cand.entry_week, cand.code)]

    n_tot = len(cand)
    n_theme = int(cand["has_theme"].sum())
    print(f"候選總筆數={n_tot:,} | 有classification題材覆蓋={n_theme:,}({n_theme / n_tot * 100:.1f}%) | "
          f"score4旗標數={int(cand.score4.sum()):,}({cand.score4.mean() * 100:.2f}%) | "
          f"resonance旗標數={int(cand.resonance.sum()):,}({cand.resonance.mean() * 100:.2f}%)")

    # -- 贏家(前30%)/輸家(後30%)次週報酬分組,旗標比率對照(描述性,呼應使用者原話) --
    valid = cand.dropna(subset=["net_ret"])
    q70, q30 = valid.net_ret.quantile([0.7, 0.3])
    winners = valid[valid.net_ret >= q70]
    losers = valid[valid.net_ret <= q30]
    print(f"\n次週淨報酬前30%(贏家,n={len(winners):,},門檻>={q70 * 100:.1f}%) vs "
          f"後30%(輸家,n={len(losers):,},門檻<={q30 * 100:.1f}%):")
    for col, cname in (("score4", "題材score=4"), ("resonance", "題材共振中")):
        wr, lr = winners[col].mean() * 100, losers[col].mean() * 100
        print(f"  {cname}旗標比率: 贏家組{wr:.2f}% vs 輸家組{lr:.2f}% (差{wr - lr:+.2f}pp)")

    results = {}
    for col, cname in (("score4", "題材score4"), ("resonance", "題材共振")):
        print(f"\n-- {cname} AUC(全候選池,含未分類=旗標False) --")
        a_df = cand[cand[col]]
        b_df = cand[~cand[col]]
        r_all = boot_auc_ci(a_df, b_df)
        p_all, t_all = auc_verdict(r_all)
        print(f"  框架A(全候選池): {t_all}")

        print(f"-- {cname} AUC(僅限有題材覆蓋子集,旗標=1 vs 同題材覆蓋但旗標=0,排除「有無分類」本身的干擾) --")
        cov = cand[cand["has_theme"]]
        a_df2 = cov[cov[col]]
        b_df2 = cov[~cov[col]]
        r_cov = boot_auc_ci(a_df2, b_df2)
        p_cov, t_cov = auc_verdict(r_cov)
        print(f"  框架B(限題材覆蓋子集): {t_cov}")

        passed = p_all or p_cov
        results[col] = {"passed": passed, "r_all": r_all, "r_cov": r_cov, "cname": cname}
        print(f"  => {cname} 第一階段判定: {'✓通過(框架A或B任一顯現鑑別力),進第二階段' if passed else '✗未通過,不進第二階段(誠實null)'}")

    return results, cand


# ══ 八、第二階段: 加權版 + 籃子擴充版(僅第一階段通過的訊號才跑) ══════════════
def weighted_portfolio_curve(weekly_baskets, grid, flag_fn, w_flag=WEIGHT_MULT_PRIMARY):
    ret = pd.Series(0.0, index=grid)
    exec_list = []
    for wk, basket in weekly_baskets.items():
        exit_wk = basket["exit_week"].iloc[0]
        if exit_wk not in ret.index:
            continue
        flags = np.array([flag_fn(wk, c) for c in basket["code"]])
        w = np.where(flags, w_flag, 1.0)
        w = w / w.sum()
        pr = float((basket["net_ret"].values * w).sum())
        ret.loc[exit_wk] = pr
        b2 = basket.copy()
        b2["weight"], b2["flag"] = w, flags
        exec_list.append(b2)
    cols = list(next(iter(weekly_baskets.values())).columns) + ["weight", "flag"]
    exec_trades = pd.concat(exec_list, ignore_index=True) if exec_list else pd.DataFrame(columns=cols)
    return ret, exec_trades


def expand_baskets(baskets, active_fn, theme2codes, target_n=EXPAND_TARGET_N):
    idx = M.WIDE_RET.index
    new_baskets = {}
    n_expanded_weeks = n_added_total = 0
    for wk, basket in baskets.items():
        if len(basket) >= target_n:
            new_baskets[wk] = basket
            continue
        i = idx.get_loc(wk)
        if i + 1 >= len(idx):
            new_baskets[wk] = basket
            continue
        have = set(basket["code"])
        pool_codes = set()
        for theme, codes in theme2codes.items():
            if active_fn(theme, wk):
                pool_codes.update(c for c in codes if c not in have)
        if not pool_codes:
            new_baskets[wk] = basket
            continue
        ret_i, liq_i, exit_ret = M.WIDE_RET.iloc[i], M.LIQ_OK.iloc[i], M.WIDE_RET.iloc[i + 1]
        cand_rows = []
        for c in pool_codes:
            r0 = ret_i.get(c, np.nan)
            if pd.isna(r0) or not liq_i.get(c, False):
                continue
            r1 = exit_ret.get(c, np.nan)
            if pd.isna(r1):
                continue
            cand_rows.append((c, float(r0), float(r1)))
        if not cand_rows:
            new_baskets[wk] = basket
            continue
        cand_rows.sort(key=lambda x: -x[1])
        need = target_n - len(basket)
        picked = cand_rows[:need]
        add_df = pd.DataFrame([{"entry_week": wk, "exit_week": idx[i + 1], "code": c,
                                "entry_ret": r0, "exit_ret": r1, "net_ret": r1 - M.COST}
                               for c, r0, r1 in picked])
        new_baskets[wk] = pd.concat([basket, add_df], ignore_index=True)
        n_expanded_weeks += 1
        n_added_total += len(picked)
    print(f"  籃子擴充: {n_expanded_weeks}週被擴充,共遞補{n_added_total}筆(目標籃子>={target_n}檔)")
    return new_baskets


def print_stats_row(label, st, tr, ci):
    ci_txt = f"[{ci[0]:+.2f}%,{ci[1]:+.2f}%]"
    print(f"{label:<28}{st['mult']:>8.1f}x{st['cagr']:>7.1f}%{st['mdd']:>7.1f}%{st['sharpe']:>6.2f}"
          f"{st['calmar']:>7.2f}{tr['win']:>5.0f}%{tr['pf']:>6.2f}{tr['mean']:>7.2f}%{ci_txt:>20}")


STATS_HDR = f"{'版本':<28}{'複利':>9}{'年化':>8}{'MDD':>8}{'夏普':>6}{'Calmar':>7}{'勝率':>6}{'PF':>6}{'單筆均':>8}{'CI':>20}"


def stage2_backtest(signal_name, threshold, label, baskets, grid, flag_fn, active_fn, theme2codes):
    print(f"\n-- 第二階段全樣本回測  訊號={signal_name}  動能門檻={label} --")
    print(STATS_HDR)
    ret0, ex0 = M.portfolio_curve(baskets, grid, mode="baseline", weighting="equal")
    st0, tr0, ci0 = M.stats_from_ret(ret0), M.trade_stats(ex0), M.bootstrap_ci(ex0)
    print_stats_row("基準(純price momentum,無疊加)", st0, tr0, ci0)

    for w_mult, wname in ((WEIGHT_MULT_PRIMARY, "2x"), (WEIGHT_MULT_ALT, "3x")):
        retw, exw = weighted_portfolio_curve(baskets, grid, flag_fn, w_flag=w_mult)
        stw, trw, ciw = M.stats_from_ret(retw), M.trade_stats(exw), M.bootstrap_ci(exw)
        print_stats_row(f"①加權版(訊號成員權重x{wname})", stw, trw, ciw)

    exp_baskets = expand_baskets(baskets, active_fn, theme2codes)
    rete, exe = M.portfolio_curve(exp_baskets, grid, mode="baseline", weighting="equal")
    ste, tre, cie = M.stats_from_ret(rete), M.trade_stats(exe), M.bootstrap_ci(exe)
    print_stats_row("②籃子擴充版(<5檔時遞補至5檔)", ste, tre, cie)


# ══ 九、主流程 ══════════════════════════════════════════
def main():
    code2themes, theme2codes, cls = load_theme_maps()
    print(f"分類覆蓋: classification表country='台' 共{cls.code.nunique()}檔個股 / "
          f"{cls['main_group'].nunique()}個main_group題材")

    score_by_theme = build_score_by_theme(cls)
    cal = load_trading_calendar()
    weekly_score_panel = build_weekly_score_panel(score_by_theme, cal, M.WIDE_C.index)
    theme_resonance_weeks = build_theme_resonance_weeks()

    score4_fn = make_flag_fn_score4(weekly_score_panel, code2themes)
    reso_fn = make_flag_fn_resonance(theme_resonance_weeks, code2themes)
    score4_active_fn = make_theme_active_fn_score4(weekly_score_panel)
    reso_active_fn = make_theme_active_fn_resonance(theme_resonance_weeks)

    weeks = M.WIDE_RET.index
    start_i = weeks.searchsorted(pd.Timestamp(M.START))
    grid = weeks[start_i:]

    overall_verdict = {}
    for threshold, label in THRESHOLDS:
        results, cand = stage1_auc(threshold, label, code2themes, score4_fn, reso_fn)
        overall_verdict[label] = results

        if threshold != 0.20:
            continue  # 第二階段僅在20%主門檻跑(15%只當第一階段敏感度對照,比照house慣例:20%為主)

        trades, baskets = M.build_trades(threshold)
        if results["score4"]["passed"]:
            stage2_backtest("題材score4", threshold, label, baskets, grid, score4_fn, score4_active_fn, theme2codes)
        else:
            print(f"\n[題材score4] 第一階段未通過,依協定不進第二階段(誠實null,不硬做)")
        if results["resonance"]["passed"]:
            stage2_backtest("題材共振", threshold, label, baskets, grid, reso_fn, reso_active_fn, theme2codes)
        else:
            print(f"\n[題材共振] 第一階段未通過,依協定不進第二階段(誠實null,不硬做)")

    print("\n" + "=" * 108)
    print("### 總結判定 ###")
    for label, results in overall_verdict.items():
        for col, r in results.items():
            print(f"  動能門檻{label} × {r['cname']}: {'✓第一階段通過' if r['passed'] else '✗第一階段未通過'}")
    print("\n跑完。以上為console探索報告,無檔案輸出。")


if __name__ == "__main__":
    main()
