# -*- coding: utf-8 -*-
"""一字鎖死型漲停「後續反而落後」的發現——脫離題材觸發窄框架,全市場全歷史樣本外複驗(2026-08-03)。

背景: 研究腳本/題材動能/build_theme_member_selection.py的⑦c在「題材月營收動能score4觸發」這個窄
情境裡發現「個股過去60日內出現過一字鎖死型漲停(high=low=close且收盤漲幅>=9.5%)」的成員,後續60日
反而顯著落後同事件等權baseline(diff-7.82pp,95%CI[-14.98,-1.32]排0顯著),但n僅20個題材-月事件,
且是⑦漲停次數家族裡最極端/覆蓋率最低的子版本,原報告已誠實標註「多重比較風險,需要獨立樣本外
複驗」。這個假說本身('曾出現極端一字鎖死型漲停預示後續走勢落後')不需要綁在題材觸發情境下,本卷
拿掉「必須是score4觸發成員」的限制,改在全市場、全歷史獨立測試。

宇宙: fm_daily_price,code限四碼且非00開頭ETF(GLOB '[1-9][0-9][0-9][0-9]'),amt20(20日均成交值)
>=0.3億元——沿用研究腳本/當沖借券/build_dtlend_report.py既有慣例的流動性門檻,不重新設計。

一字鎖死判定: 逐字沿用build_theme_member_selection.py::compute_limitup_features()的嚴格版定義
(收盤相對前一日收盤漲幅>=9.5% 且 當日high==low==close),不重新設計算法。

方法(對每一天每一檔股票判定):
  had_lockup60(t) = 過去60個交易日(t-60~t-1,不含當天)內是否出現過至少一次一字鎖死型漲停
    (至少要有45個有效交易日的回溯窗才判定,不足視為無效)
  fwd60(t) = 該股從t到t+60個交易日的收盤對收盤報酬%
  demean60(t) = fwd60(t) - 當日(t)全宇宙(uni且fwd60有效者)fwd60的截面中位數
    (此為本卷的case-control設計: 用當日全宇宙中位數當對照組,比隨機抽樣子集的case-control更強,
    因為它用的是當天"全部"合格股票,不是抽樣子集)
  比較had_lockup60=True vs False兩組的demean60,絕對層(原始fwd60)與相對層(demean60)分開報告。

顯著性: 月群bootstrap(逐字沿用build_dtlend_report.py::boot_diff_ci的統計設計——月群重抽樣、
中位差、95%CI、n_iter=2000),但因為本卷全市場全歷史daily panel規模達百萬列量級,原版
groupby().apply(list)的python list building在這個規模會太慢,改用numpy陣列重寫加速(boot_diff_ci_fast,
統計邏輯逐項比對與原版相同,純粹效能優化,非方法論偏離)。

已知限制(誠實揭露,不迴避): had_lockup60本身是60日滾動窗,同一檔股票在同一次鎖死事件後會連續
最多60個交易日都標記為True(高度自相關/偽重複),daily panel的「n列數」不能讀成「n個獨立觀察」;
月群bootstrap只能部分緩解(月群長度~21個交易日,60日窗跨約3個月群,只捕捉到部分自相關結構)。
為此本卷同時做「dedup事件版」當穩健對照: 只取每次鎖死事件生效的第一天(had_lockup60從False翻
成True的那一天)當「case」,對照組仍是全部有效的had_lockup60=False天數池——這個版本的case樣本數
更接近真正的獨立事件數,是本卷用來下結論的主要依據;完整daily panel版本當描述性規模參考。

用法: python 研究腳本/綜合策略/build_limitup_lockdown_validate.py  (從根目錄執行,鐵律)
產出: 研究報告/research_limitup_lockdown_validate.html
"""
import sqlite3
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

DB = "capital_flow.db"
OUT = "研究報告/research_limitup_lockdown_validate.html"
LOCK_THRESH = 9.5
FWD_K = 60
LOOKBACK_K = 60
MIN_LOOKBACK = 45
UNI_AMT20 = 0.3
N_BOOT = 2000
SEED = 20260803

GREEN, RED, YELLOW, GRAY = "#7ec97e", "#e06c5a", "#c3a55a", "#8a8878"


# ══════════════════════ 1. 資料載入與panel建構 ══════════════════════
def load_prices():
    conn = sqlite3.connect(DB)
    px = pd.read_sql(
        "SELECT code, date, high, low, close, money FROM fm_daily_price "
        "WHERE code GLOB '[1-9][0-9][0-9][0-9]'",
        conn, parse_dates=["date"])
    conn.close()
    print(f"[load] fm_daily_price(四碼非00開頭ETF): {len(px):,}列, {px.code.nunique():,}檔, "
          f"{px.date.min().date()}~{px.date.max().date()}")
    return px


def build_wide(px):
    close = px.pivot(index="date", columns="code", values="close").sort_index()
    high = px.pivot(index="date", columns="code", values="high").reindex_like(close)
    low = px.pivot(index="date", columns="code", values="low").reindex_like(close)
    money = px.pivot(index="date", columns="code", values="money").reindex_like(close)

    ret = close.pct_change() * 100
    lock = ((ret >= LOCK_THRESH) & (high == low) & (high == close)).fillna(False)

    amt20 = money.rolling(20, min_periods=15).mean() / 1e8
    uni = amt20 >= UNI_AMT20

    lock_roll = lock.astype(float).rolling(LOOKBACK_K, min_periods=MIN_LOOKBACK).sum().shift(1)
    had_lockup = lock_roll >= 1
    had_valid = lock_roll.notna()
    is_new_event = had_lockup & ~had_lockup.shift(1).fillna(False)  # dedup: 剛從False翻True的那一天

    fwd = (close.shift(-FWD_K) / close - 1) * 100

    n_lock_raw = int(lock.sum().sum())
    print(f"[panel] 一字鎖死原始次數(全市場全歷史,寬鬆前置四碼過濾後): {n_lock_raw:,}次")
    return dict(close=close, ret=ret, lock=lock, uni=uni, had_lockup=had_lockup,
                had_valid=had_valid, is_new_event=is_new_event, fwd=fwd, n_lock_raw=n_lock_raw)


def build_long(ctx, case_mask_key="had_lockup"):
    """把wide格式攤平成long格式,eligible=uni且fwd有效且had_lockup回溯窗有效。
    case_mask_key: 'had_lockup'=完整daily panel版; 'is_new_event'=dedup事件版(見上方docstring)。"""
    uni, fwd, had_valid = ctx["uni"], ctx["fwd"], ctx["had_valid"]
    case_mask = ctx[case_mask_key]
    control_mask = ~ctx["had_lockup"]  # 對照組固定=從未在回溯窗內出現過鎖死(不論哪個case版本)

    eligible = uni & fwd.notna() & had_valid
    fwd_elig = fwd.where(eligible)
    day_median = fwd_elig.median(axis=1)  # 同日全宇宙截面中位數(demean基準=case-control)
    demean = fwd.sub(day_median, axis=0)

    group_mask = eligible & (case_mask | control_mask)  # 只保留case或control兩組,排除中間過渡狀態
    is_case = case_mask.where(group_mask)

    fwd_l = fwd.where(group_mask).stack()
    demean_l = demean.where(group_mask).stack()
    case_l = is_case.stack()
    long_df = pd.DataFrame({"fwd60": fwd_l, "demean60": demean_l, "is_case": case_l}).reset_index()
    long_df.columns = ["date", "code", "fwd60", "demean60", "is_case"]
    return long_df


# ══════════════════════ 2. 統計工具(月群bootstrap,效能優化版) ══════════════
def boot_diff_ci_fast(vals_a, dates_a, vals_b, dates_b, n_iter=N_BOOT, seed=SEED, min_n=15):
    """統計設計逐項比對build_dtlend_report.py::boot_diff_ci(月群重抽樣/中位差/95%CI),
    因本卷daily panel規模達百萬列量級,原版groupby().apply(list)的python list building太慢,
    改用numpy陣列重寫加速——純效能優化,非方法論偏離。"""
    a = pd.Series(vals_a, dtype=float)
    a.index = pd.to_datetime(pd.Series(dates_a)).values
    b = pd.Series(vals_b, dtype=float)
    b.index = pd.to_datetime(pd.Series(dates_b)).values
    a, b = a.dropna(), b.dropna()
    if len(a) < min_n or len(b) < min_n:
        return None
    ma, mb = a.index.strftime("%Y-%m"), b.index.strftime("%Y-%m")
    a_by_month = [g.values for _, g in a.groupby(ma)]
    b_by_month = [g.values for _, g in b.groupby(mb)]
    na, nb = len(a_by_month), len(b_by_month)
    rng = np.random.default_rng(seed)
    diffs = np.empty(n_iter)
    for i in range(n_iter):
        av = np.concatenate([a_by_month[j] for j in rng.integers(0, na, na)])
        bv = np.concatenate([b_by_month[j] for j in rng.integers(0, nb, nb)])
        diffs[i] = np.median(av) - np.median(bv)
    d0 = float(a.median() - b.median())
    lo, hi = float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))
    return {"method": "bootstrap", "stat": d0, "lo": lo, "hi": hi, "p": None,
            "sig": bool(lo > 0 or hi < 0), "n": (len(a), len(b)), "n_month": (na, nb)}


def fmt_stat(r, unit="pp"):
    if r is None:
        return "n太小,無法檢定"
    sig = "<b>✓排0顯著</b>" if r["sig"] else "含0不顯著"
    return (f"{r['stat']:+.2f}{unit} 月群bootstrap 95%CI[{r['lo']:+.2f},{r['hi']:+.2f}] {sig}"
            f"(n={r['n'][0]:,}v{r['n'][1]:,}, 月群{r['n_month'][0]}v{r['n_month'][1]})")


def pooled_desc(x):
    v = pd.Series(x, dtype=float).dropna()
    if len(v) == 0:
        return {"n": 0, "median": None, "mean": None, "win": None}
    return {"n": int(len(v)), "median": float(v.median()), "mean": float(v.mean()),
            "win": float((v > 0).mean() * 100)}


def analyze(long_df, label):
    a = long_df[long_df.is_case == True]   # noqa: E712
    b = long_df[long_df.is_case == False]  # noqa: E712
    res = {
        "label": label, "n_a": len(a), "n_b": len(b),
        "abs_a": pooled_desc(a.fwd60), "abs_b": pooled_desc(b.fwd60),
        "demean_a": pooled_desc(a.demean60), "demean_b": pooled_desc(b.demean60),
        "boot": boot_diff_ci_fast(a.demean60.values, a.date, b.demean60.values, b.date),
    }
    return res


# ══════════════════════ 主流程 ══════════════════════════════════════
def main():
    px = load_prices()
    ctx = build_wide(px)

    print("\n[分析①] 完整daily panel版(對每一天每一檔股票判定,描述性規模參考)...")
    long_full = build_long(ctx, case_mask_key="had_lockup")
    res_full = analyze(long_full, "完整daily panel版")
    print(f"  case(had_lockup=True) n={res_full['n_a']:,} / control n={res_full['n_b']:,}")
    print(f"  絕對層: case中位{res_full['abs_a']['median']:+.2f}% 勝率{res_full['abs_a']['win']:.0f}% | "
          f"control中位{res_full['abs_b']['median']:+.2f}% 勝率{res_full['abs_b']['win']:.0f}%")
    print(f"  相對層(demean vs 同日全宇宙中位數): case中位{res_full['demean_a']['median']:+.2f}pp | "
          f"control中位{res_full['demean_b']['median']:+.2f}pp")
    print(f"  差值bootstrap: {fmt_stat(res_full['boot'])}")

    print("\n[分析②] dedup事件版(只取鎖死事件生效第一天,避免60日滾動窗自相關/偽重複,主要結論依據)...")
    long_dedup = build_long(ctx, case_mask_key="is_new_event")
    res_dedup = analyze(long_dedup, "dedup事件版")
    print(f"  case(新鎖死事件生效首日) n={res_dedup['n_a']:,} / control n={res_dedup['n_b']:,}")
    print(f"  絕對層: case中位{res_dedup['abs_a']['median']:+.2f}% 勝率{res_dedup['abs_a']['win']:.0f}% | "
          f"control中位{res_dedup['abs_b']['median']:+.2f}% 勝率{res_dedup['abs_b']['win']:.0f}%")
    print(f"  相對層(demean vs 同日全宇宙中位數): case中位{res_dedup['demean_a']['median']:+.2f}pp | "
          f"control中位{res_dedup['demean_b']['median']:+.2f}pp")
    print(f"  差值bootstrap: {fmt_stat(res_dedup['boot'])}")

    orig_finding = {"n": 20, "diff": -7.82, "lo": -14.98, "hi": -1.32}
    print(f"\n[比對] 原題材觸發情境n=20發現: diff{orig_finding['diff']:+.2f}pp "
          f"95%CI[{orig_finding['lo']:+.2f},{orig_finding['hi']:+.2f}]")
    same_dir_full = res_full["boot"] and (res_full["boot"]["stat"] < 0) == (orig_finding["diff"] < 0)
    same_dir_dedup = res_dedup["boot"] and (res_dedup["boot"]["stat"] < 0) == (orig_finding["diff"] < 0)
    print(f"  完整panel版方向同向: {same_dir_full}; dedup事件版方向同向: {same_dir_dedup}")

    build_html(ctx, res_full, res_dedup, orig_finding)
    print(f"\n已產出 {OUT}")


# ══════════════════════ HTML 組裝 ═══════════════════════════════════
def verdict_text(res):
    if res["boot"] is None:
        return "樣本不足,無法檢定", GRAY
    sig, stat = res["boot"]["sig"], res["boot"]["stat"]
    if sig and stat < 0:
        return "顯著複現(方向同向: 有鎖死組落後)", RED
    if sig and stat > 0:
        return "顯著但方向相反(有鎖死組反而領先)", GREEN
    return "無法區辨於雜訊(未複現)", GRAY


def fmt_grp(g, unit="%"):
    if not g or g.get("n", 0) == 0 or g.get("median") is None:
        return "<td>0</td><td>—</td><td>—</td>"
    cls = "good" if g["median"] > 0 else "bad"
    return f"<td>{g['n']:,}</td><td class='{cls}'>{g['median']:+.2f}{unit}</td><td>{g['win']:.0f}%</td>"


def build_html(ctx, res_full, res_dedup, orig_finding):
    css = """
body{background:#1a1a19;color:#fff;font-family:"Noto Sans TC",sans-serif;margin:24px;max-width:1180px}
h1{font-size:20px} h2{font-size:15px;color:#c3c2b7;margin-top:34px;border-bottom:1px solid #333;padding-bottom:4px}
h3{font-size:13.5px;color:#a8a79a;margin:16px 0 4px}
table{border-collapse:collapse;font-size:12.5px;font-variant-numeric:tabular-nums;margin:8px 0}
td,th{border:1px solid #333;padding:4px 9px;text-align:right} th{text-align:left;color:#c3c2b7}
.note{color:#8a8878;font-size:12.5px;line-height:1.8} .good{color:#7ec97e} .bad{color:#e06c5a}
.warn{color:#c3a55a} .v-good{color:#7ec97e;font-weight:600} .v-bad{color:#e06c5a;font-weight:600}
.v-warn{color:#c3a55a;font-weight:600} .sub{color:#777;font-size:11px}
.flex{display:flex;gap:24px;flex-wrap:wrap} .flex>div{flex:1;min-width:300px}
"""
    v_full, c_full = verdict_text(res_full)
    v_dedup, c_dedup = verdict_text(res_dedup)

    def block(res, verdict, color, extra_note=""):
        return f"""
<div class="note">case n={res['n_a']:,} / control n={res['n_b']:,}。
<b style="color:{color}">判讀: {verdict}</b></div>
<div class="flex">
<div><h3>絕對報酬層(原始fwd60,是否本身為正)</h3>
<table><tr><th>組別</th><th>n</th><th>中位</th><th>勝率</th></tr>
<tr><th>case(曾出現一字鎖死)</th>{fmt_grp(res['abs_a'])}</tr>
<tr><th>control(未出現)</th>{fmt_grp(res['abs_b'])}</tr></table></div>
<div><h3>相對層(demean vs 同日全宇宙中位數)</h3>
<table><tr><th>組別</th><th>n</th><th>中位</th><th>勝率</th></tr>
<tr><th>case</th>{fmt_grp(res['demean_a'], 'pp')}</tr>
<tr><th>control</th>{fmt_grp(res['demean_b'], 'pp')}</tr></table>
<div class="note">差值bootstrap: {fmt_stat(res['boot'])}</div></div>
</div>{extra_note}"""

    same_dir_full = "同向" if (res_full["boot"] and (res_full["boot"]["stat"] < 0)) else "反向或無法判斷"
    same_dir_dedup = "同向" if (res_dedup["boot"] and (res_dedup["boot"]["stat"] < 0)) else "反向或無法判斷"

    dedup_boot = res_dedup["boot"]
    replicated = bool(dedup_boot and dedup_boot["sig"] and dedup_boot["stat"] < 0)
    if replicated:
        conclusion_text = (
            "全市場全歷史樣本外複驗(去除題材觸發窄框架後,dedup事件版)方向與原本題材觸發情境下的"
            f"-7.82pp同向且顯著: 差值{dedup_boot['stat']:+.2f}pp 95%CI[{dedup_boot['lo']:+.2f},"
            f"{dedup_boot['hi']:+.2f}],樣本數大幅增加({dedup_boot['n'][0]:,}個獨立鎖死事件對照"
            f"{dedup_boot['n'][1]:,}個控制天數,遠超原本20個題材-月事件)——這<b>提升</b>了原發現的"
            "可信度,不再只是題材觸發窄框架裡的孤立小樣本巧合。")
    elif dedup_boot and dedup_boot["stat"] < 0:
        conclusion_text = (
            f"全市場全歷史樣本外複驗(dedup事件版)方向同向(差值{dedup_boot['stat']:+.2f}pp)但"
            f"95%CI[{dedup_boot['lo']:+.2f},{dedup_boot['hi']:+.2f}]未排0,不算顯著複現——方向線索"
            "算是對原發現的弱支持,但不足以視為獨立確認,原本n=20的多重比較疑慮仍應保留。")
    else:
        conclusion_text = (
            "全市場全歷史樣本外複驗(dedup事件版)並未複現原本題材觸發情境下的顯著落後(方向不同向或"
            "無法判斷)——這<b>沒有提升</b>原發現(n=20)的可信度,反而支持原本的多重比較疑慮"
            "(⑦c很可能是這批考卷裡多次檢定中運氣使然的假陽性之一,不建議當作可交易訊號採信)。")

    html = f"""<!DOCTYPE html><html lang="zh-Hant"><head><meta charset="utf-8">
<title>一字鎖死型漲停後續表現——全市場樣本外複驗</title><style>{css}</style></head><body>
<h1>「一字鎖死型漲停後續60日反而落後」——脫離題材觸發窄框架,全市場全歷史樣本外複驗</h1>
<div class="note">背景: 研究腳本/題材動能/build_theme_member_selection.py的⑦c在題材月營收動能score=4
觸發情境下發現,曾出現一字鎖死型漲停(high=low=close且收盤漲幅≥9.5%)的成員,後續60日反而顯著落後
同事件等權baseline(diff-7.82pp,95%CI[-14.98,-1.32]排0顯著),但n僅20個題材-月事件、覆蓋率最低(~6%),
原報告已標註「多重比較風險,需要獨立樣本外複驗」。這個假說不需要綁在題材觸發情境,本卷拿掉「必須是
score4觸發成員」的限制,在全市場、全歷史(fm_daily_price,四碼非00開頭ETF,amt20≥0.3億元既有流動性
慣例宇宙)獨立測試,判定邏輯與門檻逐字沿用⑦c的定義,不重新設計。</div>

<h2>總覽</h2>
<table><tr><th>版本</th><th>case n</th><th>control n</th><th>判讀</th><th>核心數字</th></tr>
<tr><th style="text-align:left">①完整daily panel版(每一天每一檔股票)</th><td>{res_full['n_a']:,}</td>
<td>{res_full['n_b']:,}</td><td style="color:{c_full};font-weight:600">{v_full}</td>
<td style="text-align:left">{fmt_stat(res_full['boot'])}</td></tr>
<tr><th style="text-align:left">②dedup事件版(僅取鎖死事件生效首日,主要結論依據)</th>
<td>{res_dedup['n_a']:,}</td><td>{res_dedup['n_b']:,}</td>
<td style="color:{c_dedup};font-weight:600">{v_dedup}</td>
<td style="text-align:left">{fmt_stat(res_dedup['boot'])}</td></tr>
<tr><th style="text-align:left">原題材觸發情境(score=4子集,⑦c,參考)</th><td>~48(成員數)</td><td>~145(成員數)</td>
<td>n事件=20,顯著</td><td style="text-align:left">{orig_finding['diff']:+.2f}pp 95%CI
[{orig_finding['lo']:+.2f},{orig_finding['hi']:+.2f}] ✓排0顯著</td></tr>
</table>
<div class="note">原市場層級發現的方向=「有鎖死組落後」(diff為負)。全市場複驗:①完整daily panel版方向
{same_dir_full};②dedup事件版(較無自相關疑慮,視為主要依據)方向{same_dir_dedup}。</div>

<h2>①完整daily panel版(對每一天每一檔股票判定,描述性規模參考)</h2>
<div class="note warn">⚠已知限制: had_lockup60是60日滾動窗,同一檔股票在同一次鎖死事件後會連續最多
60個交易日都標記為case,這裡的n列數不能讀成n個獨立觀察,自相關嚴重;月群bootstrap只能部分緩解
(月群長度~21個交易日,60日窗跨約3個月群)。此版本僅供「規模參考」,不當主要結論依據,見下方②。</div>
{block(res_full, v_full, c_full)}

<h2>②dedup事件版(僅取鎖死事件生效首日,主要結論依據)</h2>
<div class="note">只保留had_lockup60從False翻True的那一天當case(即每次鎖死事件生效影響期的起點),
避免60日滾動窗內連續多天重複計入同一次事件;對照組仍是全部從未出現過鎖死的天數池
(全宇宙amt20≥0.3億元流動性門檻內)。這個版本的case數更接近真正獨立事件數,是本卷用來下結論的
主要依據。</div>
{block(res_dedup, v_dedup, c_dedup)}

<h2>結論: 對原本n=20發現的可信度影響</h2>
<div class="note">{conclusion_text}</div>

<h2>方法論與限制</h2>
<div class="note">
① 宇宙: fm_daily_price四碼非00開頭ETF(GLOB過濾),amt20(20日均成交值)≥0.3億元,逐字沿用
build_dtlend_report.py既有流動性門檻慣例。<br>
② 一字鎖死判定逐字沿用build_theme_member_selection.py::compute_limitup_features()的嚴格版定義
(收盤相對前一日收盤漲幅≥9.5% 且 當日high==low==close),不重新設計。<br>
③ demean基準=同日全宇宙(amt20合格且fwd60有效者)截面中位數,此為本卷的case-control設計——用當天
「全部」合格股票當對照組,比隨機抽樣子集的case-control更完整。<br>
④ 顯著性檢定=月群bootstrap,統計設計逐項比對build_dtlend_report.py::boot_diff_ci(月群重抽樣/
中位差/95%CI/n_iter=2000),因本卷全市場全歷史daily panel規模達百萬列量級,原版groupby().apply(list)
的python list building太慢,改用numpy陣列重寫加速(boot_diff_ci_fast),純效能優化非方法論偏離。<br>
⑤ 完整daily panel版(①)存在嚴重自相關(同一鎖死事件的60日影響期內每天都重複計入case),n列數
不能讀成獨立觀察數,僅供規模參考;dedup事件版(②,只取每次事件生效首日)大幅緩解此問題,是本卷
下結論的主要依據,但仍不是完全去相關(同一檔股票可能在不同年份多次出現鎖死事件,個股層級仍有
弱相關,未做個股層級的cluster,這是本卷相對於嚴謹到底的方法論仍存在的簡化)。<br>
⑥ fwd60=60交易日收盤對收盤報酬,未扣持有成本;本卷測的是「訊號存在與否」的事後對照,不是一個
可直接執行的交易策略(未定義明確的進出場機制,只是驗證原假說在更大樣本下是否複現)。
</div>
</body></html>"""
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)


if __name__ == "__main__":
    main()
