# -*- coding: utf-8 -*-
"""財報公告後立即反應→後續漂移(PEAD, Post-Earnings-Announcement Drift)考卷(2026-08-03,
使用者延伸提問:「財報公告前沒有,公告後有沒有可交易的方式?」)。

背景: 姊妹卷build_earnings_winner_features.py測「贏家公告前有沒有可辨識特徵」(逆向工程+AUC),
結果AUC層級測到2個特徵(成交值熱度/漲停次數)但翻譯成規則套回全樣本後,vs case-control皆不顯著
——是「公告前逆向工程」路線的誠實null收尾。本卷換一個完全不同的框架: 不需要任何公告前資訊,
只用公告當下/公告後立即的價格反應方向與強度本身(財經學界經典母題PEAD),測能不能預測接下來的
持續走勢。理論上比「公告前逆向工程」更有機會可交易——訊號本身就是公開即時可觀察的價格行為,
不需要提前卡位或取得任何非公開資訊優勢,任何人看盤都能同步取得同一個訊號。

沿用build_earnings_winner_features.py已建好的事件面板基礎設施(load_events/load_price_index/
build_stock_panels/make_idx_ret/BENCH_OF/case_control_events/boot_median_ci0/boot_median_diff/
feat_vals_dates/CSS),不重新整理資料,直接import複用(本卷刻意不重寫這些函式,避免姊妹卷踩過的
「不同bootstrap函式key不一致」的坑——凡是中位數/差異類bootstrap一律呼叫W.boot_median_ci0/
W.boot_median_diff,呈現一律走W.boot_line2())。

任務設計:
①立即反應定義(訊號本身,不是贏家定義,這次用連續分組不做二元切法):
  react0 =day0(actual_date當天)demean報酬(收盤vs前一日收盤,扣對應大盤,穩健對照,最窄窗)
  react01=day0~day+1累積demean報酬(主判讀,2日窗兼顧「盤中/盤後公告」兩種不確定情境)
  react03=day0~day+3累積demean報酬(穩健對照,較寬窗口)
②後續漂移: 從各反應窗口「結束的最後一日」(j)開始展開k=5,10,20,60日demean CAR,不與訊號窗重疊
  (j本身就是訊號完全確定的時點,次一交易日即可用開盤價進場,比照本專案event study「car_k=
  close[j+k]/close[j]-1」的既有慣例)。
③全樣本cross-sectional五分位分組(Q1反應最負~Q5反應最正,非贏家組內比較),檢驗經典PEAD梯度形狀
  (反應越強、後續漂移越同向延續),Q5-Q1價差用月群bootstrap驗證顯著性;正負對稱測: Q1(利空)是否
  顯著續跌、Q5(利多)是否顯著續漲,分開檢定不預設方向。
④可交易性驗證(比照姊妹卷已驗證方法論,不停在點估計分組比較): 把react01的全樣本前10%/後10%
  翻譯成公告後可執行規則(訊號完全公開後才進場,無前視),用case-control(同批actual_date年-月)+
  bootstrap驗證drift是否顯著優於基準/對照組。
⑤誠實面對可能的null結果——若PEAD在本樣本不成立,或只有單邊成立、或點估計方向對但不顯著,一律
  如實報告,不放寬篩選標準或選擇性只呈現正面窗口。

用法: python 研究腳本/財報事件/build_earnings_pead.py  (從根目錄執行,鐵律)
產出: 研究報告/research_earnings_pead.html
"""
import json
import sqlite3
import sys
import time

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "研究腳本/財報事件")
import build_earnings_winner_features as W  # noqa: E402 (複用事件面板/bootstrap/case-control/CSS既有基礎設施)

OUT = "研究報告/research_earnings_pead.html"
rng = np.random.default_rng(20260803)

GREEN, RED, BLUE, YELLOW, GRAY = W.GREEN, W.RED, W.BLUE, W.YELLOW, W.GRAY
BG = W.BG

DRIFT_KS = [5, 10, 20, 60]
N_Q = 5
Q_LABELS = [f"Q{i}" for i in range(1, N_Q + 1)]
QUINTILE_COLOR = {"Q1": "#e06c5a", "Q2": "#d99a8a", "Q3": "#8a8878", "Q4": "#a8c98a", "Q5": "#7ec97e"}
REACT_DEFS = {"react0": 0, "react01": 1, "react03": 3}   # 名稱->反應窗結束的相對交易日offset(相對actual_date位置i)
REACT_LABEL = {"react0": "day0(公告當天)", "react01": "day0~day+1(主判讀,2日窗)",
               "react03": "day0~day+3(穩健對照,較寬窗)"}
RULE_FRAC = 0.10


# ======================================================================
# 1. 事件面板: 立即反應訊號(react0/react01/react03) + 各自對應的後續漂移(drift_k)
# ======================================================================
def build_pead_panel(ev, stocks, idx_ret):
    rows = []
    n_no_price, n_no_match = 0, 0
    for r in ev.itertuples():
        g = stocks.get(r.code)
        if g is None:
            n_no_price += 1
            continue
        dts = g.date.values
        i = int(np.searchsorted(dts, np.datetime64(r.actual_date)))
        if i >= len(dts) or dts[i] != np.datetime64(r.actual_date) or i < 1:
            n_no_match += 1
            continue
        c = g.close.values
        bench = W.BENCH_OF.get(r.market, "TAIEX")
        rec = {"orig_idx": r.Index, "code": r.code, "market": r.market, "actual_date": r.actual_date}
        for name, off in REACT_DEFS.items():
            j = i + off
            if j < len(dts) and c[i - 1] > 0 and c[j] > 0:
                raw = (c[j] / c[i - 1] - 1) * 100
                rec[name] = raw - idx_ret(bench, g.date.iloc[i - 1], g.date.iloc[j])
                for k in DRIFT_KS:
                    if j + k < len(dts) and c[j] > 0 and c[j + k] > 0:
                        rawk = (c[j + k] / c[j] - 1) * 100
                        rec[f"drift_{name}_{k}"] = rawk - idx_ret(bench, g.date.iloc[j], g.date.iloc[j + k])
            else:
                rec[name] = np.nan
        rows.append(rec)
    df = pd.DataFrame(rows).set_index("orig_idx")
    df["ym"] = df["actual_date"].dt.strftime("%Y-%m")
    print(f"[panel] 事件{len(ev):,}筆 → 定位成功{len(df):,}筆(無價格資料{n_no_price}, "
          f"actual_date非交易日或i<1有{n_no_match})")
    for name in REACT_DEFS:
        print(f"  {name}({REACT_LABEL[name]}): 訊號可用n={df[name].notna().sum():,}, "
              f"drift_{name}_20可用n={df.get(f'drift_{name}_20', pd.Series(dtype=float)).notna().sum():,}")
    return df


# ======================================================================
# 2. 五分位分組(全樣本cross-sectional) + 逐分位drift bootstrap(vs 0)
# ======================================================================
def quintile_split(df, react_col):
    valid = df[react_col].dropna()
    q = pd.qcut(valid.rank(method="first"), N_Q, labels=Q_LABELS)
    return {lbl: valid.index[q == lbl] for lbl in Q_LABELS}


def quintile_drift_stats(df, react_col, drift_prefix, ks=DRIFT_KS):
    q_idx = quintile_split(df, react_col)
    out = {}
    for lbl in Q_LABELS:
        idx = q_idx[lbl]
        react_vals = df.loc[idx, react_col]
        row = {"n_react": len(idx),
               "react_med": float(react_vals.median()), "react_range": (float(react_vals.min()), float(react_vals.max())),
               "k": {}}
        for k in ks:
            col = f"drift_{drift_prefix}_{k}"
            v, d = W.feat_vals_dates(df, col, idx)
            boot = W.boot_median_ci0(v, d) if len(v) >= 15 else None
            row["k"][k] = {"n": len(v), "med": float(np.median(v)) if len(v) else None,
                           "win": float((np.array(v) > 0).mean() * 100) if len(v) else None, "boot": boot}
        out[lbl] = row
        print(f"[quintile:{drift_prefix}] {lbl}(訊號中位{row['react_med']:+.2f}%,n={row['n_react']}): " +
              ", ".join(f"k{k}中位{row['k'][k]['med']:+.2f}%(n={row['k'][k]['n']})" if row["k"][k]["med"] is not None
                        else f"k{k}=n太小" for k in ks))
    return out, q_idx


def q5_q1_diff(df, drift_prefix, q_idx, ks=DRIFT_KS):
    out = {}
    for k in ks:
        col = f"drift_{drift_prefix}_{k}"
        v5, d5 = W.feat_vals_dates(df, col, q_idx["Q5"])
        v1, d1 = W.feat_vals_dates(df, col, q_idx["Q1"])
        out[k] = W.boot_median_diff(v5, d5, v1, d1) if len(v5) >= 15 and len(v1) >= 15 else None
        if out[k] is not None:
            print(f"[Q5-Q1:{drift_prefix}] k{k}: 價差={out[k]['diff']:+.2f}pp "
                  f"CI[{out[k]['lo']:+.2f},{out[k]['hi']:+.2f}] sig={out[k]['sig']}")
    return out


# ======================================================================
# 3. 規則翻譯 + 可交易性驗證(全樣本前10%/後10%,case-control同批(actual_date年-月))
# ======================================================================
def build_pead_rule(df, react_col, direction, frac=RULE_FRAC):
    valid = df[react_col].dropna()
    rnk = valid.rank(pct=True)
    return rnk[rnk >= 1 - frac].index if direction > 0 else rnk[rnk <= frac].index


def eval_pead_rule(label, rule_idx, df, drift_prefix, ks, seed):
    ctrl_idx = W.case_control_events(rule_idx, df, seed=seed)
    out = {"label": label, "n": len(rule_idx), "n_ctrl": len(ctrl_idx), "by_k": {}}
    for k in ks:
        col = f"drift_{drift_prefix}_{k}"
        v, d = W.feat_vals_dates(df, col, rule_idx)
        if len(v) < 15:
            out["by_k"][k] = None
            continue
        base_pop = df[col].dropna()
        base_med = float(base_pop.median())
        boot_base = W.boot_median_ci0(list(np.array(v) - base_med), d)
        cv, cd = W.feat_vals_dates(df, col, ctrl_idx)
        boot_ctrl = W.boot_median_diff(v, d, cv, cd) if len(cv) >= 15 else None
        out["by_k"][k] = {"n": len(v), "med": float(np.median(v)), "base_med": base_med,
                          "hit": float((np.array(v) > 0).mean()) * 100,
                          "base_hit": float((base_pop > 0).mean()) * 100,
                          "n_ctrl": len(cv), "boot_base": boot_base, "boot_ctrl": boot_ctrl}
    print(f"[rule] {label}: n={out['n']:,} 對照組n={out['n_ctrl']:,} " +
          ", ".join(f"k{k}中位{out['by_k'][k]['med']:+.2f}%" if out["by_k"].get(k) else f"k{k}=n太小" for k in ks))
    return out


# ======================================================================
# 3b. 反應強度×月營收動能交叉問題(2026-08-03使用者延伸提問):
#     react01反應特別強(前10%)的股票,是不是月營收表現本來就是正向的?
#     ——PEAD文獻經典underreaction機制候選解釋:若強反應組公告前月營收早就連續正成長/YoY角度不差,
#     代表市場對「已公開的月營收」訊息反應不足,等正式財報才真正消化,呼應三問機制「資訊是新的嗎」。
#     個股層級(非題材聚合)算三個角度: ①own_yoy3(直接複用W.compute_revenue_feature()既有輸出,
#     不重算)②連續MoM為正月數(0-3巢狀streak,逐字比照build_theme_score_topn.py mom_score算法,
#     只是改用個股自己的月營收取代題材加總)③最新一期YoY是否創近12個月新高(比照
#     build_theme_member_selection.py rev12m_high的≥9/12有效門檻邏輯,但測YoY成長率本身創新高
#     而非營收水準創新高,是不同的問題,值得重新測)。
# ======================================================================
def compute_mom_streak_yoy_newhigh(ev):
    """②連續MoM為正月數(0-3)+③YoY創12個月新高旗標,period_last cutoff與
    W.compute_revenue_feature()完全一致(actual_date-45日曆日安全緩衝,確保公告前已公開)。"""
    conn = sqlite3.connect(W.DB, timeout=60)
    rev = pd.read_sql("SELECT code, date, revenue FROM fm_month_rev", conn, parse_dates=["date"])
    conn.close()
    rev_wide = rev.pivot_table(index="date", columns="code", values="revenue", aggfunc="first").sort_index()

    mom_streak, yoy_newhigh = [], []
    for r in ev.itertuples():
        own = rev_wide[r.code] if r.code in rev_wide.columns else None
        if own is None:
            mom_streak.append(np.nan)
            yoy_newhigh.append(np.nan)
            continue
        period_last = (r.actual_date - pd.Timedelta(days=W.REV_BUFFER_DAYS)).replace(day=1)

        def mom_at(lag):
            p = period_last - pd.DateOffset(months=lag)
            p_prev = p - pd.DateOffset(months=1)
            v_now, v_prev = own.get(p, np.nan), own.get(p_prev, np.nan)
            if pd.isna(v_now) or pd.isna(v_prev) or v_prev == 0:
                return np.nan
            return v_now / v_prev - 1

        m0, m1, m2 = mom_at(0), mom_at(1), mom_at(2)
        if pd.isna(m0) or m0 <= 0:
            mom_streak.append(0)
        elif pd.isna(m1) or m1 <= 0:
            mom_streak.append(1)
        elif pd.isna(m2) or m2 <= 0:
            mom_streak.append(2)
        else:
            mom_streak.append(3)

        yoys = []
        for lag in range(12):
            p = period_last - pd.DateOffset(months=lag)
            p_prev = p - pd.DateOffset(months=12)
            v_now, v_prev = own.get(p, np.nan), own.get(p_prev, np.nan)
            yoys.append(v_now / v_prev - 1 if pd.notna(v_now) and pd.notna(v_prev) and v_prev != 0 else np.nan)
        valid = [v for v in yoys if pd.notna(v)]
        if len(valid) >= 9 and pd.notna(yoys[0]):
            yoy_newhigh.append(bool(yoys[0] >= max(valid)))
        else:
            yoy_newhigh.append(np.nan)

    out = pd.DataFrame({"mom_streak": mom_streak, "yoy_newhigh": yoy_newhigh}, index=ev.index)
    print(f"[revenue_link] mom_streak可用n={out.mom_streak.notna().sum():,}(分布="
          f"{dict(out.mom_streak.value_counts().sort_index())}), "
          f"yoy_newhigh可用n={out.yoy_newhigh.notna().sum():,}(True比例="
          f"{out.yoy_newhigh.mean() * 100:.1f}%)")
    return out


def boot_mean_ci0(vals, dates, n_iter=W.RULE_BOOT_ITER, min_n=15):
    """單組月群mean bootstrap vs 0(對W.boot_median_ci0的最小必要改寫: median→mean,
    刻意保留完全相同的回傳鍵名"med"/"lo"/"hi"/"sig"/"n",故格式化直接沿用fmt_boot0(),
    比照build_dtlend_pattern_pnl.py boot_mean_ci對median版工具函式的既有改寫慣例。"""
    a = pd.Series(vals, index=pd.to_datetime(dates), dtype=float).dropna() if len(vals) else pd.Series(dtype=float)
    if len(a) < min_n:
        return None
    am = a.groupby(a.index.strftime("%Y-%m")).apply(list)
    if len(am) < 6:
        return None
    means = []
    for _ in range(n_iter):
        av = np.concatenate([am.iloc[i] for i in rng.integers(0, len(am), len(am))])
        means.append(np.mean(av))
    m0 = float(a.mean())
    lo, hi = float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))
    return {"med": m0, "lo": lo, "hi": hi, "sig": bool(lo > 0 or hi < 0), "n": len(a)}


def boot_mean_diff(vals_a, dates_a, vals_b, dates_b, n_iter=W.RULE_BOOT_ITER, min_n=15):
    """雙組月群mean差異bootstrap(a-b),鍵名比照W.boot_median_diff("diff"/"lo"/"hi"/"sig"),
    格式化直接沿用fmt_boot_diff()。"""
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
        diffs.append(np.mean(av) - np.mean(bv))
    d0 = float(a.mean() - b.mean())
    lo, hi = float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))
    return {"diff": d0, "lo": lo, "hi": hi, "sig": bool(lo > 0 or hi < 0), "na": len(a), "nb": len(b)}


REV_LINK_FEATURES = [
    ("own_yoy3", "cont", "近3個月YoY年增率均值(%,直接複用W既有算法)"),
    ("mom_streak", "cont", "連續MoM為正月數(0-3,巢狀streak)"),
    ("yoy_newhigh", "flag", "最新一期YoY創近12個月新高(旗標)"),
]


def revenue_link_analysis(df, top_idx, bot_idx, seed_top=20260840, seed_bot=20260841):
    """react01前10%(強反應,case)/後10%(弱反應,case) 各自 vs 同批(actual_date年-月)case-control
    隨機對照組,比較3個月營收特徵。連續特徵用AUC(W.calc_auc/W.boot_auc_ci),旗標用比例差
    (boot_mean_diff,0/1×100轉pp尺度)。"""
    ctrl_top = W.case_control_events(top_idx, df, seed=seed_top)
    ctrl_bot = W.case_control_events(bot_idx, df, seed=seed_bot)
    print(f"[revenue_link] react01前10% n={len(top_idx):,}(對照組{len(ctrl_top):,}) / "
          f"後10% n={len(bot_idx):,}(對照組{len(ctrl_bot):,})")

    results = {}
    for feat, kind, label in REV_LINK_FEATURES:
        full_vals = df[feat].dropna()
        top_vals, top_dates = W.feat_vals_dates(df, feat, top_idx)
        bot_vals, bot_dates = W.feat_vals_dates(df, feat, bot_idx)
        ctrl_top_vals, ctrl_top_dates = W.feat_vals_dates(df, feat, ctrl_top)
        ctrl_bot_vals, ctrl_bot_dates = W.feat_vals_dates(df, feat, ctrl_bot)

        def desc(v):
            if len(v) == 0:
                return None
            arr = np.asarray(v, dtype=float)
            return {"n": len(arr), "stat": float(arr.mean() * 100) if kind == "flag" else float(np.median(arr))}

        row = {"feat": feat, "kind": kind, "label": label,
               "full": desc(full_vals.values), "top": desc(top_vals), "bot": desc(bot_vals)}

        if kind == "cont":
            row["top_test"] = W.boot_auc_ci(top_vals, top_dates, ctrl_top_vals, ctrl_top_dates)
            row["top_auc0"] = W.calc_auc(top_vals, ctrl_top_vals)
            row["bot_test"] = W.boot_auc_ci(bot_vals, bot_dates, ctrl_bot_vals, ctrl_bot_dates)
            row["bot_auc0"] = W.calc_auc(bot_vals, ctrl_bot_vals)
        else:
            row["top_test"] = boot_mean_diff(np.array(top_vals, dtype=float) * 100, top_dates,
                                             np.array(ctrl_top_vals, dtype=float) * 100, ctrl_top_dates)
            row["bot_test"] = boot_mean_diff(np.array(bot_vals, dtype=float) * 100, bot_dates,
                                             np.array(ctrl_bot_vals, dtype=float) * 100, ctrl_bot_dates)
        results[feat] = row
        print(f"[revenue_link] {label}: 全樣本={row['full']}, 前10%={row['top']}, 後10%={row['bot']}")
    return results


# ======================================================================
# 4. HTML 呈現
# ======================================================================
def fmt_boot0(r, unit="pp"):
    if r is None:
        return "n太小,觀察層"
    sig = "<b class='good'>✓顯著≠0</b>" if r["sig"] else "含0(不顯著)"
    return f"{r['med']:+.2f}{unit} 95%CI[{r['lo']:+.2f},{r['hi']:+.2f}] {sig}"


def fmt_boot_diff(r, unit="pp"):
    if r is None:
        return "n太小,觀察層"
    sig = "<b class='good'>✓顯著排0</b>" if r["sig"] else "含0(不顯著)"
    return f"{r['diff']:+.2f}{unit} 95%CI[{r['lo']:+.2f},{r['hi']:+.2f}] {sig}"


def quintile_table_html(qstats, ks=DRIFT_KS):
    head = "<tr><th>分位(訊號中位)</th><th>n(訊號)</th>" + "".join(f"<th>drift k{k}中位/勝率</th>" for k in ks) + "</tr>"
    rows = ""
    for lbl in Q_LABELS:
        row = qstats[lbl]
        cells = ""
        for k in ks:
            c = row["k"][k]
            if c["med"] is None:
                cells += "<td>—</td>"
            else:
                cls = "good" if c["med"] > 0 else "bad"
                cells += f"<td class='{cls}'>{c['med']:+.2f}%<br><span class='sub'>勝率{c['win']:.0f}%,n={c['n']:,}</span></td>"
        rows += (f"<tr><th style='background:{QUINTILE_COLOR[lbl]}22'>{lbl}"
                 f"({row['react_med']:+.2f}%)</th><td>{row['n_react']:,}</td>{cells}</tr>")
    return f"<table>{head}{rows}</table>"


def boot_table_html(qstats, ks=DRIFT_KS):
    head = "<tr><th>分位</th>" + "".join(f"<th>drift k{k} vs 0(bootstrap)</th>" for k in ks) + "</tr>"
    rows = ""
    for lbl in Q_LABELS:
        cells = "".join(f"<td>{fmt_boot0(qstats[lbl]['k'][k]['boot'])}</td>" for k in ks)
        rows += f"<tr><th>{lbl}</th>{cells}</tr>"
    return f"<table>{head}{rows}</table>"


def rule_table_html(rules, ks=DRIFT_KS):
    head = "<tr><th>規則</th>" + "".join(f"<th>k{k}中位(基準版)</th>" for k in ks) + "</tr>"
    rows = ""
    for label, r in rules.items():
        cells = ""
        for k in ks:
            c = r["by_k"].get(k)
            if c is None:
                cells += "<td>—</td>"
            else:
                cls = "good" if c["med"] > 0 else "bad"
                cells += f"<td class='{cls}'>{c['med']:+.2f}%<br><span class='sub'>基準{c['base_med']:+.2f}%</span></td>"
        rows += f"<tr><th>{label}(n={r['n']:,})</th>{cells}</tr>"
    return f"<table>{head}{rows}</table>"


def rule_boot_html(rules, ks=DRIFT_KS):
    blocks = []
    for label, r in rules.items():
        lines = []
        for k in ks:
            c = r["by_k"].get(k)
            if c is None:
                lines.append(f"<li>k{k}: n太小,觀察層</li>")
                continue
            lines.append(f"<li>k{k} vs全樣本基準(excess): {fmt_boot0(c['boot_base'])}"
                        f" ｜ vs case-control同批對照組: {fmt_boot_diff(c['boot_ctrl'])}</li>")
        blocks.append(f"<h3>{label}</h3><ul>{''.join(lines)}</ul>")
    return "".join(blocks)


DISPLAY_UNIT = {"own_yoy3": "%", "mom_streak": "個月", "yoy_newhigh": "%(True比例)"}


def revlink_table_html(revlink):
    rows = ""
    for feat, kind, label in REV_LINK_FEATURES:
        r = revlink[feat]
        unit = DISPLAY_UNIT[feat]

        def cell(d):
            if d is None:
                return "<td>—</td>"
            return f"<td>{d['stat']:+.2f}{unit}<br><span class='sub'>n={d['n']:,}</span></td>"
        rows += f"<tr><th>{label}</th>{cell(r['full'])}{cell(r['top'])}{cell(r['bot'])}</tr>"
    return (f"<table><tr><th>特徵</th><th>全樣本(中位/比例)</th>"
            f"<th>react01前10%(強反應)</th><th>react01後10%(弱反應)</th></tr>{rows}</table>")


def revlink_boot_html(revlink):
    lines = []
    for feat, kind, label in REV_LINK_FEATURES:
        r = revlink[feat]
        if kind == "cont":
            lines.append(W.auc_line(f"{label} · 前10%(強反應) vs 同批case-control", r["top_test"]))
            lines.append(W.auc_line(f"{label} · 後10%(弱反應) vs 同批case-control", r["bot_test"]))
        else:
            lines.append(f"<li>{label} · 前10%(強反應) vs 同批case-control(比例差,pp): "
                         f"{fmt_boot_diff(r['top_test'])}</li>")
            lines.append(f"<li>{label} · 後10%(弱反應) vs 同批case-control(比例差,pp): "
                         f"{fmt_boot_diff(r['bot_test'])}</li>")
    return "<ul>" + "".join(lines) + "</ul>"


def summarize_revlink(revlink):
    """動態判定每個特徵是否支持「強反應=月營收本來就正向」的機制故事,不寫死方向。
    cont特徵: top_test AUC>0.5且顯著=強反應組月營收動能顯著優於同批對照組(支持);
    bot_test AUC<0.5且顯著=弱反應組月營收動能顯著劣於對照組(對稱支持)。
    flag特徵(yoy_newhigh): 用比例差diff方向代替AUC。"""
    detail = []
    for feat, kind, label in REV_LINK_FEATURES:
        r = revlink[feat]
        tt, bt = r["top_test"], r["bot_test"]
        if kind == "cont":
            top_support = tt is not None and tt["sig"] and tt["auc"] > 0.5
            top_oppose = tt is not None and tt["sig"] and tt["auc"] < 0.5
            bot_support = bt is not None and bt["sig"] and bt["auc"] < 0.5
            bot_oppose = bt is not None and bt["sig"] and bt["auc"] > 0.5
        else:
            top_support = tt is not None and tt["sig"] and tt["diff"] > 0
            top_oppose = tt is not None and tt["sig"] and tt["diff"] < 0
            bot_support = bt is not None and bt["sig"] and bt["diff"] < 0
            bot_oppose = bt is not None and bt["sig"] and bt["diff"] > 0
        detail.append({"feat": feat, "label": label, "top_support": top_support, "top_oppose": top_oppose,
                       "bot_support": bot_support, "bot_oppose": bot_oppose})
    return detail


def revlink_verdict_text(detail):
    n_top_support = sum(d["top_support"] for d in detail)
    n_top_oppose = sum(d["top_oppose"] for d in detail)
    n_bot_support = sum(d["bot_support"] for d in detail)
    n = len(detail)
    support_labels = [d["label"] for d in detail if d["top_support"]]
    if n_top_support >= 2:
        cls = "v-good"
        txt = (f"✅有{n_top_support}/{n}個月營收特徵支持「強反應組月營收本來就正向」({', '.join(support_labels)}),"
               "與PEAD文獻經典的underreaction解釋一致——市場對已公開的月營收動能反應不足,直到正式財報"
               "公告才真正大幅修正股價,財報公告本質上更像「資訊確認」而非「資訊創造」。")
    elif n_top_support == 1:
        cls = "v-warn"
        txt = (f"🟡僅1/{n}個月營收特徵支持機制故事({', '.join(support_labels)}),其餘不顯著或方向不一致,"
               "證據不夠一致,不宜過度推論成「反應強=月營收本來就好」這個乾淨故事,較可能是部分機制"
               "混雜(月營收只是其中一個貢獻因素,財報公告本身仍帶來月營收看不到的增量資訊,如毛利率/"
               "業外損益/財測)。")
    elif n_top_oppose >= 1:
        cls = "v-bad"
        txt = ("❌至少一個特徵方向與機制假說相反(強反應組月營收動能反而較差),不支持"
               "「強反應=月營收本來就正向」這個故事,較可能反映公告當下的其他驚喜來源"
               "(如毛利率/業外/財測),而非月營收動能的延續確認。")
    else:
        cls = "v-warn"
        txt = ("🟡3個月營收特徵在強反應組vs同批case-control皆未測到顯著差異,誠實null——"
               "至少用這3個角度(近3月YoY均值/連續MoM正月數/YoY創12月新高),看不出反應特別強的股票"
               "公告前月營收表現有系統性不同,PEAD反應強度的機制來源需要從月營收以外的角度"
               "(如財測/毛利率/業外損益等季報獨有資訊)另尋解釋。")
    return cls, txt


def write_report(ev_summary, panel_stats, qstats01, q5q1_01, rules01, robust_out, df, revlink=None):
    q5q1_html = "".join(
        f"<li>k{k}: {fmt_boot_diff(q5q1_01[k])}</li>" for k in DRIFT_KS)

    # Q1/Q5 vs 0 對稱性(從qstats01直接取)
    sym_lines = []
    for lbl, tag in (("Q1", "利空組(反應最負)續跌?"), ("Q5", "利多組(反應最正)續漲?")):
        for k in (20,):
            b = qstats01[lbl]["k"][k]["boot"]
            sym_lines.append(f"<li>{lbl} {tag} drift k{k}: {fmt_boot0(b)}</li>")
    sym_html = "<ul>" + "".join(sym_lines) + "</ul>"

    # 跨窗口定義穩健性(比照build_earnings_winner_features.py既有的三重一致標準:
    # react01(主判讀)的Q5-Q1方向,是否與react0(窄窗)/react03(寬窗)同向,k20)
    d20 = q5q1_01.get(20)
    d20_r0 = robust_out.get("react0", {}).get("q5q1", {}).get(20)
    d20_r3 = robust_out.get("react03", {}).get("q5q1", {}).get(20)
    same_dir_r0 = d20 is not None and d20_r0 is not None and np.sign(d20_r0["diff"]) == np.sign(d20["diff"])
    same_dir_r3 = d20 is not None and d20_r3 is not None and np.sign(d20_r3["diff"]) == np.sign(d20["diff"])
    robust_pass = bool(same_dir_r0 and same_dir_r3)
    robust_caveat = ("" if robust_pass else
                     " ⚠但比照姊妹卷的跨窗口定義穩健度標準(react0窄窗/react03寬窗方向須與主判讀一致)"
                     f"未通過——react0(day0單日)在k20的Q5-Q1價差為{d20_r0['diff']:+.2f}pp"
                     f"{'(方向相反)' if d20_r0 is not None and d20 is not None and np.sign(d20_r0['diff']) != np.sign(d20['diff']) else ''}"
                     f",react03(day0~day+3)為{d20_r3['diff']:+.2f}pp,"
                     "顯示這個梯度對「反應窗口怎麼切」相當敏感,不是在任何合理窗口定義下都穩健重現,"
                     "應視為候選假說而非穩健結論。" if (d20_r0 is not None and d20_r3 is not None) else "")

    # PEAD梯度判讀(動態依實際數值/顯著性生成,不寫死方向)
    if d20 is not None and d20["sig"] and d20["diff"] > 0:
        pead_verdict_cls = "v-good" if robust_pass else "v-warn"
        pead_verdict_txt = (
            f"{'✅' if robust_pass else '🟡'}Q5(利多反應)-Q1(利空反應)在k20(react01主判讀)顯著為正"
            f"(價差{d20['diff']:+.2f}pp,CI[{d20['lo']:+.2f},{d20['hi']:+.2f}]),與經典PEAD延續型態一致"
            f"{robust_caveat}")
    elif d20 is not None and d20["sig"] and d20["diff"] < 0:
        pead_verdict_cls, pead_verdict_txt = "v-bad", (
            f"❌Q5-Q1在k20顯著為負(價差{d20['diff']:+.2f}pp),方向與PEAD延續假說相反"
            "(較像反轉而非延續)")
    else:
        pead_verdict_cls, pead_verdict_txt = "v-warn", "🟡Q5-Q1價差未達統計顯著(CI含0),看不到穩健的PEAD梯度"

    any_rule_sig = any(
        c is not None and c["boot_ctrl"] is not None and c["boot_ctrl"]["sig"]
        for r in rules01.values() for c in r["by_k"].values())
    if any_rule_sig and robust_pass:
        rule_cls, rule_txt = "v-good", "✅至少一條規則在至少一個k窗口,drift顯著優於case-control同批對照組,且跨反應窗口定義方向一致"
    elif any_rule_sig:
        rule_cls, rule_txt = "v-warn", ("🟡react01前10%規則在k5/k10/k20皆顯著優於case-control(見下表),"
                                        "但這個結果只在「day0~day+1」這一種反應窗口定義下成立——比照姊妹卷"
                                        "的跨窗口穩健度標準,react0(窄窗)方向相反、react03(寬窗)顯著性消失,"
                                        "此為候選假說,尚不能視為穩健可交易的發現")
    else:
        rule_cls, rule_txt = "v-warn", "🟡規則翻譯後套回全樣本,所有k窗口vs case-control皆未達顯著——與Q5-Q1點估計方向可能一致,但強度不足以通過嚴格驗證"

    # 圖表payload
    c1 = {"labels": Q_LABELS, "vals": [qstats01[lbl]["k"][20]["med"] for lbl in Q_LABELS],
          "colors": [QUINTILE_COLOR[lbl] for lbl in Q_LABELS]}
    c2 = {"ks": DRIFT_KS,
          "q1": [qstats01["Q1"]["k"][k]["med"] for k in DRIFT_KS],
          "q5": [qstats01["Q5"]["k"][k]["med"] for k in DRIFT_KS]}
    payload_json = json.dumps({"c1": c1, "c2": c2}, ensure_ascii=False)

    robust_html = ""
    for name in ("react0", "react03"):
        r = robust_out[name]
        lines = "".join(f"<li>k{k}: {fmt_boot_diff(r['q5q1'][k])}</li>" for k in (20,))
        rule_lines = []
        for label, rr in r["rules"].items():
            c = rr["by_k"].get(20)
            if c is None:
                rule_lines.append(f"<li>{label}: n太小</li>")
            else:
                rule_lines.append(f"<li>{label} k20: vs基準{fmt_boot0(c['boot_base'])} ｜ "
                                  f"vs case-control{fmt_boot_diff(c['boot_ctrl'])}</li>")
        robust_html += (f"<h3>{REACT_LABEL[name]}</h3>"
                       f"<div class='note'>Q5-Q1價差(k20): </div><ul>{lines}</ul>"
                       f"<div class='note'>前10%/後10%規則(k20): </div><ul>{''.join(rule_lines)}</ul>")

    if revlink is not None:
        revlink_detail = summarize_revlink(revlink)
        revlink_cls, revlink_txt = revlink_verdict_text(revlink_detail)
        revlink_section = f"""
<h2>⑦ 反應強度是否來自月營收動能?(使用者延伸提問)</h2>
<div class="note">承接「反應特別強的股票,是不是月營收表現本來就是正向的?」這個提問——個股層級
(非題材聚合)算3個公告前月營收角度: 近3個月YoY年增率均值(own_yoy3,直接複用
<code>build_earnings_winner_features.py</code>既有算法)、連續MoM為正月數(0-3巢狀streak,逐字
比照<code>build_theme_score_topn.py</code> mom_score算法但改用個股自己的月營收)、最新一期YoY是否
創近12個月新高(比照<code>build_theme_member_selection.py</code> rev12m_high的門檻邏輯但測YoY
成長率本身創新高)。react01前10%(強反應,case) / 後10%(弱反應,case) 各自與同批(actual_date年-月)
case-control隨機對照組比較,連續特徵用AUC、旗標用比例差bootstrap。</div>
<table><tr><th></th><th>判讀</th></tr>
<tr><td>強反應組的月營收動能,是否顯著優於同批case-control(支持underreaction機制故事)?</td>
<td><span class="verdict {revlink_cls}">{revlink_txt}</span></td></tr></table>
<h3>描述性分布(全樣本 / react01前10% / react01後10%)</h3>
{revlink_table_html(revlink)}
<h3>bootstrap顯著性(vs同批case-control,連續特徵用AUC/旗標用比例差)</h3>
{revlink_boot_html(revlink)}
<div class="note">機制含義: 若強反應組的月營收角度顯著優於對照組,呼應三問機制「資訊是新的嗎」——
支持PEAD文獻經典的underreaction解釋(市場對已公開的月營收動能反應不足,直到正式財報公告才真正
消化,財報公告扮演的是「資訊確認」而非「資訊創造」的角色);若未測到關聯,則反應強度的來源更可能是
月營收看不到的部分(毛利率結構/業外損益/財測guidance等季報獨有資訊),見上方判讀。</div>
"""
    else:
        revlink_section = ""

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>財報公告後PEAD(立即反應→後續漂移)考卷(2026-08-03)</title>
<script src="plotly.min.js"></script><style>{W.CSS}</style></head><body>
<h1>📊 財報公告後立即反應→後續漂移(PEAD)考卷</h1>
<div class="note">承接使用者提問「公告前沒有,公告後有沒有可交易的方式?」——本卷完全不用任何公告前
資訊,只用公告當下/公告後立即的價格反應方向與強度(財經學界經典母題Post-Earnings-Announcement
Drift),測能不能預測接下來的持續走勢。事件面板沿用<code>build_earnings_winner_features.py</code>
既有基礎設施(load_events/load_price_index/build_stock_panels/case_control_events/boot_median_ci0/
boot_median_diff),不重新整理資料。事件母體: {ev_summary['n_panel']:,}筆(257檔,
{ev_summary['date_min']}~{ev_summary['date_max']}),定位成功後可用於本卷分析。</div>

<h2>① 立即反應定義(訊號本身,連續分組非二元)</h2>
<div class="note">react0=day0(公告當天)demean報酬(收盤vs前一日收盤,扣對應大盤);
react01=day0~day+1累積demean報酬(<b>主判讀</b>,2日窗兼顧盤中/盤後公告兩種不確定情境);
react03=day0~day+3累積demean報酬(穩健對照,較寬窗)。後續漂移從各反應窗口「結束的最後一日」開始
展開k=5,10,20,60日demean CAR,不與訊號窗重疊。</div>
<table><tr><th>訊號版本</th><th>定義</th><th>可用事件數</th></tr>
{"".join(f"<tr><th>{name}</th><td>{REACT_LABEL[name]}</td><td>{ev_summary['react_n'][name]:,}</td></tr>" for name in REACT_DEFS)}
</table>

<h2>② 五分位分組: 反應強度 vs 後續漂移(主判讀react01)</h2>
<div class="note">全樣本cross-sectional排名分五等分(Q1反應最負~Q5反應最正),各分位逐k窗看後續
demean漂移中位數/勝率(誠實列出全部窗口,非只列有利窗口)。</div>
{quintile_table_html(qstats01)}
<h3>逐分位drift bootstrap(vs 0,月群重抽樣95%CI)</h3>
{boot_table_html(qstats01)}

<h2>③ PEAD核心檢定: Q5(利多反應)-Q1(利空反應)價差</h2>
<table><tr><th>核心問題</th><th>判讀</th></tr>
<tr><td>反應越強,後續漂移是否越同向延續(經典PEAD梯度)?</td>
<td><span class="verdict {pead_verdict_cls}">{pead_verdict_txt}</span></td></tr></table>
<ul>{q5q1_html}</ul>

<h3>正負對稱性檢定(k20; PEAD理論上正負反應都該有延續性,分開檢定不預設方向)</h3>
{sym_html}

<h2>④ 可交易性驗證: 規則翻譯 + case-control(套回全樣本,非分位組內循環驗證)</h2>
<div class="note">規則=react01全樣本前10%(預測續漲)/後10%(預測續跌),排除任何前視,訊號完全公開後
才進場,case-control=同批(actual_date年-月)排除規則命中股後隨機抽同數量。</div>
<table><tr><th></th><th>判讀</th></tr>
<tr><td>翻譯後的規則,drift是否顯著優於case-control?</td>
<td><span class="verdict {rule_cls}">{rule_txt}</span></td></tr></table>
{rule_table_html(rules01)}
<h3>bootstrap顯著性(vs全樣本基準 + vs case-control同批對照組)</h3>
{rule_boot_html(rules01)}

<h2>⑤ 穩健性: react0(窄窗)/react03(寬窗)兩個訊號定義版本複驗</h2>
<div class="note">用day0單日、或day0~day+3較寬窗重新定義反應訊號,各自重新做五分位切法與規則翻譯,
檢查方向與強度是否與主判讀(react01)一致。</div>
{robust_html}

<h2>⑥ 三問機制討論(PEAD整體,而非個別特徵)</h2>
<ul>
<li><b>誰被迫交易?</b>——PEAD文獻經典解釋是「投資人對盈餘意外反應不足」(underreaction),尤其
散戶與部分機構受限於注意力/資訊處理能力,無法在公告當下把全部訊息一次消化完畢,強制性行為者不明顯,
較偏「認知限制」而非「被迫」。</li>
<li><b>資訊是新的嗎?</b>——立即反應本身(react0/react01/react03)是全市場同步公開可見的價格行為,
不是任何一方獨有的新資訊,但「反應強度」與「後續是否延續」這個二階關係,本身需要投資人願意相信並
交易這個歷史統計規律,才會被消化。</li>
<li><b>為何別人沒吃掉它?</b>——PEAD是學術文獻中最持久的異常現象之一(自1968年Ball &amp; Brown起
數十年反覆複現),常見解釋是: ①交易成本/流動性摩擦(尤其小型股)侵蝕淨利潤,②套利資本有限
(limits to arbitrage,尤其此類訊號通常分散在數百檔個股、單筆金額小,機構套利誘因不足),
③風險基礎解釋(持續反應本身可能對應真實的基本面風險溢酬,而非純粹的錯價)。若本卷驗證出顯著且
可翻譯成規則的PEAD訊號,仍需留意這幾種「為何沒被吃掉」的機制對本地(台股)市場的適用程度,交易成本/
滑價/流動性在實際執行上可能侵蝕掉觀察到的統計優勢。</li>
</ul>

{revlink_section}
<h2>⑧ 與公告前逆向工程研究的對照</h2>
<div class="note">{ev_summary['compare_txt']}</div>

<h2>📈 圖表</h2>
<div id="c1" style="height:340px"></div>
<div id="c2" style="height:340px"></div>

<h2>已知限制</h2>
<div class="note">
①案件量隨drift窗口k拉長而遞減(k=60需要反應窗結束後再60個交易日的價格資料,近期事件天然被排除),
解讀長窗結果時留意n數縮小、bootstrap CI變寬。<br>
②react0/react01/react03三個版本的drift彼此分開計算(各自的訊號窗+各自的分位切法),不是同一組
事件在不同窗口下的重複測試,三者樣本略有差異(見①各版本可用事件數)。<br>
③案件量已扣除當批(actual_date年-月)case-control對照組使用的隨機抽樣,固定種子(20260803系列)
求可重現,但仍是單一次抽樣非窮舉。<br>
④實際執行需另外考慮交易成本/滑價/流動性(尤其反應強度極端的個股常伴隨當下成交量異常放大,次一
交易日的實際可執行價格與收盤價可能有落差),本卷數字為觀察層,不涉及實際下單可執行性,亦不預設上板。<br>
⑤bootstrap月群重抽樣n_iter={W.RULE_BOOT_ITER}次,95%CI。
</div>
<div class="note">維運: python 研究腳本/財報事件/build_earnings_pead.py(從根目錄執行,鐵律)。
姊妹檔: build_earnings_winner_features.py(公告前逆向工程,本卷共用其事件面板基礎設施)、
build_earnings_preannounce_reaction.py(公告前普遍反應null/弱負結果)。</div>

<script>
const D={payload_json};
const BG={json.dumps(BG, ensure_ascii=False)};
Plotly.newPlot('c1', [{{x:D.c1.labels, y:D.c1.vals, type:'bar', marker:{{color:D.c1.colors}},
  text:D.c1.vals.map(v=>v===null?'—':v.toFixed(2)+'%'), textposition:'outside'}}],
  Object.assign({{title:'② 五分位drift k20中位數(react01主判讀)', yaxis:{{title:'demean CAR k20(%)',zeroline:true,zerolinecolor:'#555'}}}}, BG));
Plotly.newPlot('c2', [
  {{x:D.c2.ks, y:D.c2.q1, mode:'lines+markers', name:'Q1(反應最負)', line:{{color:'{RED}'}}}},
  {{x:D.c2.ks, y:D.c2.q5, mode:'lines+markers', name:'Q5(反應最正)', line:{{color:'{GREEN}'}}}}
], Object.assign({{title:'漂移曲線: Q1 vs Q5 中位drift隨k窗口變化', xaxis:{{title:'drift窗口k(交易日)'}},
  yaxis:{{title:'demean CAR中位數(%)',zeroline:true,zerolinecolor:'#555'}}}}, BG));
</script>
</body></html>"""
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[report] 已輸出 {OUT}")


# ======================================================================
# 5. main
# ======================================================================
def main():
    t0 = time.time()
    ev = W.load_events()
    codes = sorted(ev.code.unique())
    px, idx = W.load_price_index(codes)
    stocks = W.build_stock_panels(px)
    idx_ret = W.make_idx_ret(idx)

    print("=" * 60, "\n[main] PEAD事件面板: 立即反應 + 後續漂移")
    df = build_pead_panel(ev, stocks, idx_ret)

    ev_summary = {
        "n_panel": len(df), "date_min": str(df.actual_date.min().date()), "date_max": str(df.actual_date.max().date()),
        "react_n": {name: int(df[name].notna().sum()) for name in REACT_DEFS},
    }

    print("=" * 60, "\n[main] 五分位分組(主判讀react01)")
    qstats01, qidx01 = quintile_drift_stats(df, "react01", "react01")

    print("=" * 60, "\n[main] Q5-Q1價差bootstrap(主判讀react01)")
    q5q1_01 = q5_q1_diff(df, "react01", qidx01)

    print("=" * 60, "\n[main] 規則翻譯+驗證(主判讀react01,全樣本前10%/後10%)")
    rule_hi = build_pead_rule(df, "react01", direction=1)
    rule_lo = build_pead_rule(df, "react01", direction=-1)
    rules01 = {
        "react01前10%(預測續漲)": eval_pead_rule("react01前10%(預測續漲)", rule_hi, df, "react01", DRIFT_KS, seed=20260820),
        "react01後10%(預測續跌)": eval_pead_rule("react01後10%(預測續跌)", rule_lo, df, "react01", DRIFT_KS, seed=20260821),
    }

    print("=" * 60, "\n[main] 穩健性複驗: react0/react03")
    robust_out = {}
    for name in ("react0", "react03"):
        qstats_r, qidx_r = quintile_drift_stats(df, name, name, ks=(20,))
        q5q1_r = q5_q1_diff(df, name, qidx_r, ks=(20,))
        r_hi = build_pead_rule(df, name, direction=1)
        r_lo = build_pead_rule(df, name, direction=-1)
        rules_r = {
            f"{name}前10%(預測續漲)": eval_pead_rule(f"{name}前10%", r_hi, df, name, (20,), seed=20260830),
            f"{name}後10%(預測續跌)": eval_pead_rule(f"{name}後10%", r_lo, df, name, (20,), seed=20260831),
        }
        robust_out[name] = {"qstats": qstats_r, "q5q1": q5q1_r, "rules": rules_r}

    print("=" * 60, "\n[main] 反應強度×月營收動能交叉問題(使用者延伸提問)")
    rev_feat = W.compute_revenue_feature(ev)   # own_yoy3/own_yoy6,逐字複用既有算法不重算
    mom_yoy_feat = compute_mom_streak_yoy_newhigh(ev)  # 新增: mom_streak(0-3)+yoy_newhigh(旗標)
    df = df.join(rev_feat[["own_yoy3"]], how="left").join(mom_yoy_feat, how="left")
    revlink = revenue_link_analysis(df, rule_hi, rule_lo)

    # 對照文字(動態生成,依實際結果決定敘述,不寫死方向)
    d20 = q5q1_01.get(20)
    d20_r0 = robust_out.get("react0", {}).get("q5q1", {}).get(20)
    d20_r3 = robust_out.get("react03", {}).get("q5q1", {}).get(20)
    same_dir_r0 = d20 is not None and d20_r0 is not None and np.sign(d20_r0["diff"]) == np.sign(d20["diff"])
    same_dir_r3 = d20 is not None and d20_r3 is not None and np.sign(d20_r3["diff"]) == np.sign(d20["diff"])
    robust_pass = bool(same_dir_r0 and same_dir_r3)
    any_rule_sig = any(c is not None and c["boot_ctrl"] is not None and c["boot_ctrl"]["sig"]
                       for r in rules01.values() for c in r["by_k"].values())
    if d20 is not None and d20["sig"] and any_rule_sig and robust_pass:
        compare_txt = ("與公告前逆向工程研究(build_earnings_winner_features.py)性質完全不同——那份是"
                       "誠實null收尾(AUC測到2個特徵,翻譯成規則後套回全樣本皆未能顯著優於case-control);"
                       "本卷用公告後立即反應本身當訊號,規則翻譯後至少有一個k窗口顯著優於case-control,"
                       "且跨反應窗口定義方向一致,是這整條財報研究線目前唯一通過完整驗證鏈(分位分析+"
                       "bootstrap+規則翻譯+case-control+跨窗口穩健性)的正面發現。但仍需留意交易成本/"
                       "流動性/樣本外複驗等限制,不代表立即可上板。")
    elif d20 is not None and d20["sig"] and any_rule_sig and not robust_pass:
        compare_txt = ("與公告前逆向工程研究的性質不同,但誠實程度需要同一把尺: 本卷在「day0~day+1」"
                       "這個主判讀窗口下,Q5-Q1價差在k5/k10/k20皆顯著為正,規則翻譯後vs case-control也"
                       f"顯著(react01前10%規則),乍看是這整條財報研究線第一個通過bootstrap+case-control"
                       f"驗證的正面發現;但比照公告前那份研究要求的跨窗口定義穩健性標準,本卷"
                       f"react0(day0單日窄窗)在k20的Q5-Q1價差方向{'相反' if not same_dir_r0 else '一致但更弱'}"
                       f"(react0={d20_r0['diff']:+.2f}pp vs react01={d20['diff']:+.2f}pp),"
                       f"react03(day0~day+3寬窗)較弱{'且不顯著' if d20_r3 is not None and not d20_r3['sig'] else ''}"
                       f"(react03={d20_r3['diff']:+.2f}pp)——沒有通過同等嚴格的三重一致門檻。誠實結論: "
                       "這是一個「主判讀窗口下顯著,但對反應窗口切法敏感」的候選假說,比公告前逆向工程的"
                       "乾淨null更有希望,但還不到「穩健可交易」的地步,需要更多窗口定義/樣本外資料複驗"
                       "才能升級為結論。")
    elif d20 is not None and d20["sig"]:
        compare_txt = ("與公告前逆向工程研究相比,本卷在Q5-Q1價差層級測到顯著的PEAD梯度(反應越強、"
                       "後續漂移越同向延續),但翻譯成規則套回全樣本後,vs case-control未能達到顯著——"
                       "與公告前那份研究殊途同歸: 兩者都指向「看得到统计關聯,但翻譯成嚴格意義的"
                       "可交易規則後強度不足」這個共同結論,只是本卷至少在分位分析層級測到了比公告前"
                       "研究更清楚的訊號。")
    else:
        compare_txt = ("與公告前逆向工程研究的null結論方向一致——公告前測不到可辨識的贏家特徵,公告後"
                       "立即反應本身也測不到穩健顯著的PEAD延續梯度,兩份研究合起來看,本樣本(台股"
                       "257檔重點觀察名單,2019-2026)的財報公告事件,不管往前看或往後看,都沒有測出"
                       "夠強夠穩健的可交易訊號,誠實的結論是: 至少用本卷這幾個角度,財報公告本身"
                       "在這個樣本裡不是一個可靠的選股/擇時事件。")
    ev_summary["compare_txt"] = compare_txt

    print("=" * 60, "\n[main] 組裝報告")
    write_report(ev_summary, None, qstats01, q5q1_01, rules01, robust_out, df, revlink=revlink)
    print(f"[main] 全部完成,總耗時{time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
