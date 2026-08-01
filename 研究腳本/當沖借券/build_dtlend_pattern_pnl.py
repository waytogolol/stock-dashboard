# -*- coding: utf-8 -*-
"""當沖客P&L proxy×價格型態contemporaneous驗證(2026-08-01,使用者拍板定案的新考卷):

⚠方法論刻意不同於本資料夾姊妹檔build_dtlend_report.py: 那份是forward-looking CAR事件研究
(型態發生後未來k日報酬),本卷是**同一天**的型態條件 vs **同一天**的結果——當沖資料只有「當日」
實現損益,天生只能做contemporaneous驗證,不是預測未來報酬。因此本卷不做事件gap去重(不像CAR研究
需要避免forward window重疊自相關),同一檔股票連續多天符合條件,每天都是獨立的當日觀察值。

研究目的: 用當沖資料回推「當沖客當日實現損益proxy」當結果標籤,交叉驗證兩個經典價格型態設定,
是否真的對應「當沖客賺錢的方向」——這兩型態原本是技術分析常見的「動能延續」/「過熱反轉」設定,
當沖資料剛好提供一個獨立於股價本身的結果標籤(當沖客集體當天是賺是賠)可以拿來對照驗證。

型態①跳空+新高(驗證「做多當沖」方向): 跳空開盤=今日open>昨日high(⚠刻意用high不用close,
真跳空無重疊定義,無%門檻); 創新高=今日close(主判讀)或high(穩健對照)>=過去20日最高(不含當日)。
假說=符合者當天收盤長紅+當沖P&L proxy顯著為正。
設計決策(新高用close還是high): 主判讀採**close版**——①與本卷結果標籤(今日收盤vs昨收方向)同一個
「收盤」口徑,型態定義與結果判讀內部一致;②close新高代表價格真正「站上」新高完成收盤確認,比較不會
被單根長上影線的盤中假突破汙染。high版(盤中觸及新高但可能收黑,含更多假突破/上影線案例)當**穩健性
對照組**並列,不作主要判讀依據。

型態②震幅擴大+開高(驗證「做空/反轉」方向): 開高(弱化版,不要求跳空)=今日open>昨日close;
震幅擴大=今日(high-low)/昨收,相對該股自身過去120日(主判讀)或240日(≈1年,穩健對照)震幅分布的
百分位>=80分位——百分位算法比照研究腳本/綜合策略/build_regime_weather_report.py的vp10寫法
(rolling(window).rank(pct=True)*100),差別是那份是市場指數的「全樣本」百分位(單一序列),
本卷是「每檔股票自己的rolling窗口」百分位(逐股逐日,pandas 2.x原生支援rolling(w).rank(pct=True)
逐欄位運算,已驗證與build_resonance_chip.py既有的rolling(240).rank(pct=True)寫法相容)。
假說=符合者當天收盤黑K+當沖P&L proxy顯著為負。
設計決策(120日 vs 240日窗口): 主判讀採**120日(約半年)**——個股層的波動regime比大盤指數層更容易在
數月內結構性改變(換手率/籌碼結構/題材熱度轉移都比大盤快),120日窗更貼近「近期常態」,對「擴大」的
判定更敏感;240日(≈1年)窗因為涵蓋更久遠、可能已經是不同波動regime的歷史,會稀釋當下擴大訊號的
極端度,故僅當穩健性對照,不作主判讀。

當沖客P&L proxy=(SellAmount-BuyAmount)/BuyAmount*100(逐股逐日),與scratch_dt_lend_quick.py
D3同一算法(pnl<=-3%代表大賠日),差別是那份拿pnl當「事件篩選門檻」抓大賠日,本卷拿pnl當「連續結果
變數」逐股逐日都算,不篩選只當結果標籤。邏輯=當沖多數是先買後賣的常規當沖(先賣後買比例極低,
BuyAfterSale統計已證實),故SellAmount>BuyAmount≈當沖客整體「買低賣高」賺錢、反之≈整體被套/賠錢。
⚠BuyAfterSale欄位本身不可用(已於前一輪驗證: 2025年那份pkl裡24萬多筆空值/僅8千多筆'Y'/6千多筆
編碼壞掉的亂碼),故本卷不用該欄位拆多空,直接沿用pnl proxy。

統計設計(誠實聲明: 「vs全樣本基準率」與「vs case-control同日對照組」是兩種不同嚴謹度的檢定,
並列呈現、不能互相替代——這正是本專案「思維筆記」#13條case-control基準率的具體實踐):
  a) vs全樣本基準率(使用者原始設計要求的主檢定): 全宇宙全樣本(同一套amt20>=0.3億∧四碼∧非00
     ETF宇宙,全部交易日)的長紅收尾比例/P&L proxy中位數當基準常數,事件組扣掉這個常數後
     (excess值)做月群bootstrap(2000次)算95%CI vs 0。
     ⚠此基準是純量常數(未按日調整),**未控制「事件湊巧發生在大盤當天普遍上漲/下跌的日子」這個
     混淆因子**——型態①(跳空+新高)本質上容易群聚在強勢多頭日(那天多數股票本來就收紅),
     若只看這個檢定,命中率偏高有可能只是反映「那天大盤/類股齊漲」而非型態本身的訊號力,
     故必須搭配(b)一起看,不能只看(a)就下結論。
  b) vs case-control同日對照組(補強檢定,控制當日效應): 逐事件日,從同一宇宙∧同一天排除當天所有
     符合該型態旗標的股票後,隨機抽同數量非事件股當對照組(複用build_dtlend_report.py的
     case_control()工具函式,固定種子求可重現),兩組同日比較,直接net掉「那天大盤/類股方向」
     這個混淆因子,是本卷判讀「型態本身是否真的有訊號」的更嚴謹依據。
  bootstrap月群重抽樣(仿build_dtlend_report.py的boot_diff_ci/boot_median_ci,n_iter=2000):
     pnl/當沖比率用中位數(與本專案CAR統計慣例一致,中位數對極端值穩健);命中率(0/1)用平均數
     (=比例本身),此為對(median版)工具函式的最小必要改寫,函式邏輯與月群重抽樣機制完全相同。

用法: python 研究腳本/當沖借券/build_dtlend_pattern_pnl.py  (從根目錄執行,鐵律)
產出: 研究報告/research_dtlend_pattern_pnl.html
"""
import json
import sqlite3
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "研究腳本/當沖借券")
import build_dtlend_report as R  # noqa: E402  (複用pkl讀取/合併/去重/amt20宇宙過濾/case_control)

DB = "capital_flow.db"
OUT = "研究報告/research_dtlend_pattern_pnl.html"
rng = np.random.default_rng(20260801)

GREEN, RED, BLUE, YELLOW, GRAY = R.GREEN, R.RED, R.BLUE, R.YELLOW, R.GRAY
BG = R.BG


# ======================================================================
# 1. 資料載入(複用build_dtlend_report.py的load_dtlend,只取dt列;ln借券本卷不需要)
# ======================================================================
def load_price_full(codes, date_lo):
    """比照R.load_price,但多取high/low(震幅型態需要),四碼過濾已於load_dtlend階段完成。"""
    conn = sqlite3.connect(DB, timeout=60)
    ph = ",".join("?" * len(codes))
    px = pd.read_sql(
        f"SELECT code, date, open, high, low, close, volume, money FROM fm_daily_price "
        f"WHERE code IN ({ph}) AND date>=? AND close>0",
        conn, params=codes + [date_lo], parse_dates=["date"])
    conn.close()
    n0 = len(px)
    px = px[px.high >= px.low]  # 資料品質防呆: high<low理論不可能,實測251列(<0.01%)屬髒資料,剔除
    print(f"[load] fm_daily_price: {n0:,}列 → high>=low防呆後{len(px):,}列(剔除{n0 - len(px):,}列), "
          f"{px.code.nunique()}檔, {px.date.min().date()}~{px.date.max().date()}")
    idx = px.pivot(index="date", columns="code", values="open"), \
        px.pivot(index="date", columns="code", values="high"), \
        px.pivot(index="date", columns="code", values="low"), \
        px.pivot(index="date", columns="code", values="close"), \
        px.pivot(index="date", columns="code", values="volume"), \
        px.pivot(index="date", columns="code", values="money")
    return idx


# ======================================================================
# 2. 型態旗標與結果標籤
# ======================================================================
def build_flags(op, high, low, close, uni):
    """回傳型態①②(主判讀+穩健對照)旗標,以及結果標籤(bull/bear/strict版)。"""
    # ---- 型態① 跳空+新高 ----
    gap_up = op > high.shift(1)
    nh_close = close >= close.shift(1).rolling(20).max()
    nh_high = high >= high.shift(1).rolling(20).max()
    setup1_close = gap_up & nh_close & uni
    setup1_high = gap_up & nh_high & uni
    print(f"[flags] 型態①跳空日(op>昨high)股-日數={int(gap_up.reindex_like(uni).fillna(False).sum().sum()):,} "
          f"→ ∧close新高∧uni={int(setup1_close.sum().sum()):,} ∧high新高∧uni={int(setup1_high.sum().sum()):,}")

    # ---- 型態② 震幅擴大+開高 ----
    gap_open = op > close.shift(1)
    rng_day = (high - low)
    amp = (rng_day / close.shift(1) * 100)
    amp_pct120 = amp.rolling(120, min_periods=60).rank(pct=True) * 100
    amp_pct240 = amp.rolling(240, min_periods=120).rank(pct=True) * 100
    setup2_120 = gap_open & (amp_pct120 >= 80) & uni
    setup2_240 = gap_open & (amp_pct240 >= 80) & uni
    print(f"[flags] 型態②開高日(op>昨close)股-日數={int(gap_open.reindex_like(uni).fillna(False).sum().sum()):,} "
          f"→ ∧震幅120日p80∧uni={int(setup2_120.sum().sum()):,} ∧震幅240日p80∧uni={int(setup2_240.sum().sum()):,}")

    # ---- 結果標籤 ----
    ret_c = (close / close.shift(1) - 1) * 100
    bull = ret_c > 0
    bear = ret_c < 0
    pos_in_range = ((close - low) / rng_day.replace(0, np.nan))
    strict_bull = bull & (close >= op) & (pos_in_range >= 0.7)   # 嚴格長紅: 方向對+實體不倒縮+收在當日上緣
    strict_bear = bear & (close <= op) & (pos_in_range <= 0.3)   # 嚴格黑K: 方向對+實體不倒縮+收在當日下緣

    return {"setup1_close": setup1_close, "setup1_high": setup1_high,
            "setup2_120": setup2_120, "setup2_240": setup2_240,
            "ret_c": ret_c, "bull": bull, "bear": bear,
            "strict_bull": strict_bull, "strict_bear": strict_bear}


# ======================================================================
# 3. 統計工具: 遮罩取值(向量化) + bootstrap(比例版=均值, pnl/ratio版=中位數複用R)
# ======================================================================
def masked_values(frame, mask):
    """向量化取出mask為真處的frame數值(自動丟NaN),回傳(values array, dates array)。"""
    m = mask.reindex_like(frame).fillna(False)
    s = frame.where(m).stack()
    if len(s) == 0:
        return np.array([]), np.array([])
    return s.values.astype(float), s.index.get_level_values(0).values


def lookup_at(frame, evs):
    """逐(date,code)清單取值(loop版,case-control對照組用,寫法比照R.event_stats)。"""
    vals, dates = [], []
    for d, g in evs.groupby("date"):
        if d not in frame.index:
            continue
        row = frame.loc[d]
        for c in g.code:
            v = row.get(c)
            if pd.notna(v):
                vals.append(v)
                dates.append(d)
    return vals, dates


def mask_to_evs(mask):
    """布林遮罩→(date,code)事件表,僅供case_control()呼叫用。"""
    s = mask.stack()
    s = s[s]
    if len(s) == 0:
        return pd.DataFrame(columns=["date", "code"])
    return pd.DataFrame({"date": s.index.get_level_values(0), "code": s.index.get_level_values(1)})


def boot_mean_ci(vals, dates, n_iter=2000, min_n=15):
    """單組月群bootstrap: 均值(比例)vs 0 的95%CI——仿R.boot_median_ci,median改mean(比例/命中率用)。"""
    a = pd.Series(vals, index=pd.to_datetime(dates), dtype=float).dropna() if len(vals) else pd.Series(dtype=float)
    if len(a) < min_n:
        return None
    am = a.groupby(a.index.strftime("%Y-%m")).apply(list)
    means = []
    for _ in range(n_iter):
        av = np.concatenate([am.iloc[i] for i in rng.integers(0, len(am), len(am))])
        means.append(np.mean(av))
    m0 = float(a.mean())
    lo, hi = float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))
    return {"stat": m0, "lo": lo, "hi": hi, "sig": bool(lo > 0 or hi < 0), "n": len(a)}


def boot_diff_mean_ci(vals_a, dates_a, vals_b, dates_b, n_iter=2000, min_n=15):
    """雙組月群bootstrap: 均值差(比例差)95%CI——仿R.boot_diff_ci,median改mean。"""
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
        diffs.append(np.mean(av) - np.mean(bv))
    d0 = float(a.mean() - b.mean())
    lo, hi = float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))
    return {"diff": d0, "lo": lo, "hi": hi, "sig": bool(lo > 0 or hi < 0), "na": len(a), "nb": len(b)}


# ======================================================================
# 4. 逐型態評估(命中率+P&L proxy+當沖比率,vs全樣本基準 + vs case-control對照組)
# ======================================================================
def eval_setup(label, mask, direction, ret_c, strict_frame, pnl, ratio, uni, seed):
    # 防呆: NaN比較(如ret_c>0)在pandas會靜默回傳False而非NaN,故顯式交集ret_c.notna(),
    # 避免停牌/無收盤資料的格子被誤記為「結果=False(非命中)」而非「結果未定義」
    mask = mask & ret_c.notna()
    evs = mask_to_evs(mask)
    n = len(evs)
    if n == 0:
        print(f"[eval] {label}: n=0,跳過")
        return None

    hitflag = (ret_c > 0) if direction == "bull" else (ret_c < 0)
    base_pop = uni & ret_c.notna()

    hit_vals, hit_dates = masked_values(hitflag.astype(float), mask)
    strict_vals, strict_dates = masked_values(strict_frame.astype(float), mask)
    pnl_vals, pnl_dates = masked_values(pnl, mask)
    ratio_vals, ratio_dates = masked_values(ratio, mask)

    # ---- 全樣本基準(純量常數: 同一宇宙全部交易日) ----
    base_hit_vals, _ = masked_values(hitflag.astype(float), base_pop)
    base_strict_vals, _ = masked_values(strict_frame.astype(float), base_pop)
    base_pnl_vals, _ = masked_values(pnl, uni & pnl.notna())
    base_ratio_vals, _ = masked_values(ratio, uni & ratio.notna())
    base_hit = float(np.mean(base_hit_vals)) if len(base_hit_vals) else np.nan
    base_strict = float(np.mean(base_strict_vals)) if len(base_strict_vals) else np.nan
    base_pnl = float(np.median(base_pnl_vals)) if len(base_pnl_vals) else np.nan
    base_ratio = float(np.median(base_ratio_vals)) if len(base_ratio_vals) else np.nan

    # 命中率/嚴格命中率的hit_vals是0/1指示變數,乘100讓boot_line的unit="pp"標籤名實相符
    # (否則印出來的數字會是0-1小數尺度,讀者會誤以為效果只有標籤數字的1/100大)。
    boot_hit_base = boot_mean_ci((np.array(hit_vals) - base_hit) * 100, hit_dates)
    boot_strict_base = boot_mean_ci((np.array(strict_vals) - base_strict) * 100, strict_dates)
    boot_pnl_base = R.boot_median_ci(list(np.array(pnl_vals) - base_pnl), pnl_dates)
    boot_ratio_base = R.boot_median_ci(list(np.array(ratio_vals) - base_ratio), ratio_dates)

    # ---- case-control同日對照組(排除當天所有符合本型態的股票後隨機抽同數量) ----
    ctrl = R.case_control(evs, uni, mask, seed=seed)
    ctrl_hit_vals, ctrl_hit_dates = lookup_at(hitflag.astype(float), ctrl)
    ctrl_pnl_vals, ctrl_pnl_dates = lookup_at(pnl, ctrl)
    ctrl_ratio_vals, ctrl_ratio_dates = lookup_at(ratio, ctrl)

    boot_hit_ctrl = boot_diff_mean_ci(np.array(hit_vals) * 100, hit_dates,
                                       np.array(ctrl_hit_vals) * 100, ctrl_hit_dates)
    boot_pnl_ctrl = R.boot_diff_ci(list(pnl_vals), pnl_dates, ctrl_pnl_vals, ctrl_pnl_dates)
    boot_ratio_ctrl = R.boot_diff_ci(list(ratio_vals), ratio_dates, ctrl_ratio_vals, ctrl_ratio_dates)

    # 年度分布(診斷: 事件是否集中在特定年份/regime)
    yr = pd.Series(hit_vals, index=pd.to_datetime(hit_dates)).groupby(lambda d: d.year).count() if len(hit_vals) else pd.Series(dtype=float)

    print(f"[eval] {label}: n事件={n:,} 命中率(基準{base_hit * 100:.1f}%)="
          f"{np.mean(hit_vals) * 100 if len(hit_vals) else float('nan'):.1f}% "
          f"P&L proxy中位數(基準{base_pnl:+.2f}%)={np.median(pnl_vals) if len(pnl_vals) else float('nan'):+.2f}% "
          f"(n_pnl={len(pnl_vals):,}) 對照組n={len(ctrl):,}")

    return {
        "label": label, "n": n, "n_pnl": len(pnl_vals), "n_ctrl": len(ctrl),
        "hit_rate": float(np.mean(hit_vals)) * 100 if len(hit_vals) else None,
        "strict_rate": float(np.mean(strict_vals)) * 100 if len(strict_vals) else None,
        "pnl_med": float(np.median(pnl_vals)) if len(pnl_vals) else None,
        "ratio_med": float(np.median(ratio_vals)) if len(ratio_vals) else None,
        "base_hit": base_hit * 100, "base_strict": base_strict * 100,
        "base_pnl": base_pnl, "base_ratio": base_ratio,
        "boot_hit_base": boot_hit_base, "boot_strict_base": boot_strict_base,
        "boot_pnl_base": boot_pnl_base, "boot_ratio_base": boot_ratio_base,
        "boot_hit_ctrl": boot_hit_ctrl, "boot_pnl_ctrl": boot_pnl_ctrl, "boot_ratio_ctrl": boot_ratio_ctrl,
        "yr": yr,
    }


# ======================================================================
# 5. HTML 呈現小工具
# ======================================================================
def pct_txt(v):
    return "—" if v is None or (isinstance(v, float) and np.isnan(v)) else f"{v:+.2f}pp" if abs(v) < 1000 else f"{v:.0f}"


def boot_line(label, r, unit="pp", key="stat"):
    if r is None:
        return f"<li>{label}: n太小,觀察層(未達bootstrap最低樣本門檻n>=15)</li>"
    # 本地boot_mean_ci用"stat"、本地boot_diff_mean_ci與R.boot_diff_ci用"diff"、
    # R.boot_median_ci(build_dtlend_report.py)用"med"——三種都要認得,依序找第一個存在的key。
    k = next((cand for cand in (key, "diff", "med", "stat") if cand in r), key)
    sig = "<b>✓排0(顯著)</b>" if r["sig"] else "含0(不顯著)"
    return f"<li>{label}: {r[k]:+.2f}{unit} 95%CI[{r['lo']:+.2f},{r['hi']:+.2f}] {sig}</li>"


def setup_block(res_list):
    """回傳(表格html, bootstrap清單html, 判讀css/txt)給單一型態(含主判讀+穩健對照多列)。"""
    rows = []
    for r in res_list:
        if r is None:
            continue
        rows.append(
            f"<tr><th>{r['label']}(n={r['n']:,})</th>"
            f"<td>{r['hit_rate']:.1f}%<br><span class='sub'>基準{r['base_hit']:.1f}%</span></td>"
            f"<td>{r['strict_rate']:.1f}%<br><span class='sub'>基準{r['base_strict']:.1f}%</span></td>"
            f"<td>{r['pnl_med']:+.2f}%<br><span class='sub'>基準{r['base_pnl']:+.2f}%(n={r['n_pnl']:,})</span></td>"
            f"<td>{r['ratio_med']:.3f}<br><span class='sub'>基準{r['base_ratio']:.3f}</span></td></tr>")
    head = ("<tr><th>設定</th><th>命中率(基準版)</th><th>嚴格命中率(基準版)</th>"
            "<th>P&L proxy中位數(基準版,%)</th><th>當沖比率中位數</th></tr>")
    return f"<table>{head}{''.join(rows)}</table>"


def boot_section(r, label_prefix):
    if r is None:
        return "<div class='note'>n太小,觀察層。</div>"
    items = [
        boot_line(f"{label_prefix} 命中率 vs全樣本基準(excess比例)", r["boot_hit_base"]),
        boot_line(f"{label_prefix} 嚴格命中率 vs全樣本基準(excess比例)", r["boot_strict_base"]),
        boot_line(f"{label_prefix} P&L proxy中位數 vs全樣本基準(excess,%)", r["boot_pnl_base"], unit="%"),
        boot_line(f"{label_prefix} 當沖比率中位數 vs全樣本基準(excess)", r["boot_ratio_base"], unit=""),
        boot_line(f"{label_prefix} 命中率 vs case-control同日對照組(比例差)", r["boot_hit_ctrl"], key="diff"),
        boot_line(f"{label_prefix} P&L proxy中位數 vs case-control同日對照組(中位差,%)", r["boot_pnl_ctrl"], unit="%", key="diff"),
        boot_line(f"{label_prefix} 當沖比率中位數 vs case-control同日對照組(中位差)", r["boot_ratio_ctrl"], key="diff", unit=""),
    ]
    return f"<ul>{''.join(items)}</ul>"


def verdict_for(r, expect_positive):
    """核心假說判讀: 命中率vs基準 + P&L vs case-control 都要看,兩者若矛盾以case-control為準(較嚴謹)。
    ⚠"未達顯著"與"顯著但方向相反"是兩種不同結論(後者是更強的「假說被推翻」證據),不可混為一談。"""
    if r is None:
        return "v-warn", "🟡n太小,觀察層"
    hb, pc = r["boot_hit_base"], r["boot_pnl_ctrl"]
    hit_ok_base = hb is not None and hb["sig"] and (hb["stat"] > 0) == expect_positive
    hit_wrong_base = hb is not None and hb["sig"] and (hb["stat"] > 0) != expect_positive
    pnl_ok_ctrl = pc is not None and pc["sig"] and (pc["diff"] > 0) == expect_positive
    pnl_wrong_ctrl = pc is not None and pc["sig"] and (pc["diff"] > 0) != expect_positive
    if hit_ok_base and pnl_ok_ctrl:
        return "v-good", "✅命中率(vs全樣本基準)+P&L proxy(vs case-control對照組)雙雙排0,方向與假說一致"
    if pnl_wrong_ctrl:
        return "v-bad", "⛔P&L proxy(較嚴謹的case-control版)顯著排0,但方向與假說相反——不是「未驗證」而是資料顯著推翻原假說方向"
    if pnl_ok_ctrl:
        return "v-warn", "🟡P&L proxy(較嚴謹的case-control版)排0且方向對,但命中率vs基準未達顯著或方向不符"
    if hit_wrong_base:
        return "v-bad", "⛔命中率vs全樣本基準顯著排0,但方向與假說相反(P&L proxy未達顯著,無法交叉確認)"
    if hit_ok_base and not pnl_ok_ctrl:
        return "v-warn", "🟡命中率vs全樣本基準排0,但case-control控制當日效應後P&L proxy未顯著——⚠可能是日期群聚假訊號"
    return "v-bad", "❌命中率與P&L proxy(case-control版)均未達顯著方向,型態假說本資料不成立"


# ======================================================================
# 6. main
# ======================================================================
def main():
    dt, _ln = R.load_dtlend()
    codes = sorted(dt.code.unique())
    print(f"[main] 當沖宇宙 {len(codes)} 檔(四碼∧非00開頭ETF,load_dtlend階段已過濾)")

    op, high, low, close, vol, money = load_price_full(codes, "2013-01-01")
    # 全部對齊到close的index/columns,避免後續mask reindex時因來源不同產生的邊界差異
    op, high, low, vol, money = (f.reindex(index=close.index, columns=close.columns) for f in (op, high, low, vol, money))

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
    print(f"[main] pnl proxy覆蓋: {pnl.notna().sum().sum():,}格(有效BuyAmount>0);"
          f" pnl分布p1={np.nanpercentile(pnl.values, 1):.2f}% p50={np.nanmedian(pnl.values):.2f}%"
          f" p99={np.nanpercentile(pnl.values, 99):.2f}%")

    flags = build_flags(op, high, low, close, uni)

    print("=" * 60, "\n[main] 型態① 跳空+新高(驗證做多當沖)")
    r1_close = eval_setup("跳空+新高(close版,主判讀)", flags["setup1_close"], "bull",
                          flags["ret_c"], flags["strict_bull"], pnl, ratio, uni, seed=20260801)
    r1_high = eval_setup("跳空+新高(high版,穩健對照)", flags["setup1_high"], "bull",
                         flags["ret_c"], flags["strict_bull"], pnl, ratio, uni, seed=20260802)

    print("=" * 60, "\n[main] 型態② 震幅擴大+開高(驗證做空/反轉)")
    r2_120 = eval_setup("震幅120日p80+開高(主判讀)", flags["setup2_120"], "bear",
                        flags["ret_c"], flags["strict_bear"], pnl, ratio, uni, seed=20260803)
    r2_240 = eval_setup("震幅240日p80+開高(穩健對照)", flags["setup2_240"], "bear",
                        flags["ret_c"], flags["strict_bear"], pnl, ratio, uni, seed=20260804)

    print("=" * 60, "\n[main] 組裝報告")
    write_report(r1_close, r1_high, r2_120, r2_240)


# ======================================================================
# 7. 報告組裝
# ======================================================================
def write_report(r1c, r1h, r2a, r2b):
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
    v1_cls, v1_txt = verdict_for(r1c, expect_positive=True)
    v2_cls, v2_txt = verdict_for(r2a, expect_positive=False)

    t1_table = setup_block([r1c, r1h])
    t2_table = setup_block([r2a, r2b])

    t1_boot = boot_section(r1c, "close版") + boot_section(r1h, "high版")
    t2_boot = boot_section(r2a, "120日版") + boot_section(r2b, "240日版")

    # ---- 年度分布圖(診斷: 事件是否集中特定年份/regime,呼應case-control的日期群聚提醒) ----
    def year_payload(r):
        if r is None or r["yr"].empty:
            return {"labels": [], "vals": []}
        yr = r["yr"].sort_index()
        return {"labels": [str(y) for y in yr.index], "vals": [int(v) for v in yr.values]}

    c1 = year_payload(r1c)
    c2 = year_payload(r2a)

    def bar_payload(labels, vals, colors):
        return {"labels": labels, "vals": [round(v, 2) if v is not None else None for v in vals], "colors": colors}

    c3 = bar_payload(
        ["命中率(基準)", "命中率(事件組)", f"P&L基準{r1c['base_pnl']:+.2f}%", f"P&L事件組{r1c['pnl_med']:+.2f}%"],
        [r1c["base_hit"], r1c["hit_rate"], r1c["base_pnl"], r1c["pnl_med"]],
        [GRAY, GREEN, GRAY, GREEN]) if r1c else None
    c4 = bar_payload(
        ["命中率(基準)", "命中率(事件組)", f"P&L基準{r2a['base_pnl']:+.2f}%", f"P&L事件組{r2a['pnl_med']:+.2f}%"],
        [r2a["base_hit"], r2a["hit_rate"], r2a["base_pnl"], r2a["pnl_med"]],
        [GRAY, RED, GRAY, RED]) if r2a else None

    payload = {"c1": c1, "c2": c2, "c3": c3, "c4": c4}
    payload_json = json.dumps(payload, ensure_ascii=False)

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>當沖客P&L proxy×價格型態contemporaneous驗證(2026-08-01)</title>
<script src="plotly.min.js"></script><style>{css}</style></head><body>
<h1>📊 當沖客P&amp;L proxy×價格型態Contemporaneous驗證</h1>
<div class="note">⚠方法論提醒: 本卷是「同一天」型態條件 vs 「同一天」結果的contemporaneous驗證,
<b>不是</b>本資料夾姊妹檔build_dtlend_report.py那種forward-looking CAR事件研究,型態發生當天的收盤
方向與當沖客P&amp;L proxy就是結果,不看未來。資料=根目錄tmp_dtlend_h2014~h2025.pkl(全史)+
暫存/快取/tmp_dtlend_p1~p6.pkl(近一年,經檢查無重疊,merge去重),複用build_dtlend_report.py的
load_dtlend()。宇宙=amt20(20日均成交值)>=0.3億∧四碼股票∧非00開頭ETF。
P&amp;L proxy=(SellAmount-BuyAmount)/BuyAmount×100(逐股逐日,BuyAfterSale欄位已驗證不可用,
故不拆多空,只當連續結果變數)。</div>

<h2>📋 兩型態判讀總表</h2>
<table>
<tr><th>型態</th><th>核心假說</th><th>判讀</th></tr>
<tr><th>①跳空+新高</th><td>驗證「做多當沖」: 當天收長紅+當沖客P&amp;L proxy顯著為正</td>
<td><span class="verdict {v1_cls}">{v1_txt}</span></td></tr>
<tr><th>②震幅擴大+開高</th><td>驗證「做空/反轉」: 當天收黑K+當沖客P&amp;L proxy顯著為負</td>
<td><span class="verdict {v2_cls}">{v2_txt}</span></td></tr>
</table>

<h2>① 跳空+新高(驗證做多當沖)</h2>
<div class="note">跳空開盤=今日open>昨日high(真跳空無重疊,無%門檻);創新高=今日close(主判讀)
或high(穩健對照)>=過去20日最高(不含當日)。設計決策: close版與本卷結果標籤同一收盤口徑、
排除單根長上影線假突破,故為主判讀;high版納入盤中觸及新高但收黑的案例,當穩健性對照。</div>
{t1_table}
<h3>bootstrap顯著性(月群重抽樣n_iter=2000,95%CI;含vs全樣本基準與vs case-control同日對照組兩版)</h3>
{t1_boot}

<h2>② 震幅擴大+開高(驗證做空/反轉)</h2>
<div class="note">開高(弱化版,不要求跳空)=今日open>昨日close;震幅擴大=今日(high-low)/昨收,
相對該股自身過去120日(主判讀)或240日≈1年(穩健對照)震幅分布的百分位>=80(百分位算法比照
build_regime_weather_report.py的vp10寫法,rolling(window).rank(pct=True)×100,差別是逐股自身
rolling窗口而非市場指數全樣本)。設計決策: 個股波動regime比大盤指數更易數月內結構性改變,
120日窗更貼近近期常態、對「擴大」更敏感,240日窗因涵蓋更久遠歷史會稀釋當下訊號,故僅當對照。</div>
{t2_table}
<h3>bootstrap顯著性(月群重抽樣n_iter=2000,95%CI;含vs全樣本基準與vs case-control同日對照組兩版)</h3>
{t2_boot}

<h2>📈 圖表</h2>
<div class="note">c1/c2=事件年度分布(診斷是否集中特定年份/regime,呼應case-control的「日期群聚」
提醒);c3/c4=命中率與P&amp;L proxy基準版vs事件組(主判讀設定)。</div>
<div id="c1" style="height:280px"></div>
<div id="c2" style="height:280px"></div>
<div id="c3" style="height:300px"></div>
<div id="c4" style="height:300px"></div>

<h2>已知限制與資料品質問題(誠實聲明)</h2>
<div class="note">
①<b>vs全樣本基準率是純量常數比較,未按日調整,無法控制「型態湊巧集中在大盤當天普遍上漲/下跌的
日子」這個混淆因子</b>——型態①(跳空+新高)本質上容易群聚在強勢多頭階段,此時多數股票當天本來就
收紅,若只看這個檢定容易高估型態本身的訊號力;本卷已用case-control同日對照組(排除當天所有符合
該型態的股票後,從同宇宙隨機抽同數量非事件股)補強,判讀以兩者一致(尤其case-control排0)為準,
若兩者矛盾已在判讀欄位明白寫出「可能是日期群聚假訊號」;<br>
②P&amp;L proxy在當沖量極小的股票-日會出現極端值(分母BuyAmount很小時比率被放大),
本卷全程採中位數(對極端值穩健)而非平均數,惟仍提醒此proxy在薄量日雜訊較大;<br>
③本卷刻意不做事件gap去重(不同於build_dtlend_report.py等CAR研究),因為每天的觀察值都是獨立的
「當日」型態-結果配對,不像forward return有重疊視窗的自相關疑慮,但同一檔股票連續多日符合條件時,
這些天的當沖生態(籌碼/題材熱度)可能不是互相獨立的,月群bootstrap的月度分塊部分緩解但非完美;<br>
④宇宙/基準母體=capital_flow.db的fm_daily_price與當沖pkl聯集限制在dt資料曾出現過的1980檔
(四碼∧非00 ETF∧amt20>=0.3億),未涵蓋從未被日內沖銷過的極冷門股,但此類股票本身多半不滿足
amt20門檻,影響有限;<br>
⑤資料品質: fm_daily_price原始撈取中high&lt;low的髒列已剔除(見下方主控台輸出列印,佔比&lt;0.01%);
BuyAfterSale欄位仍確認不可用(空值/亂碼比例過高,見前一輪驗證與本檔docstring);<br>
⑥所有數字為觀察層/盤點層,不涉及交易成本、隔日可交易性驗證,不預設上板。
</div>
<div class="note">維運: python 研究腳本/當沖借券/build_dtlend_pattern_pnl.py(從根目錄執行,鐵律)。
姊妹檔: build_dtlend_report.py(全史正式考卷,forward-looking CAR版)、根目錄scratch_dt_lend_quick.py
(一年快看v2,pnl proxy算法出處)。</div>

<script>
const D={payload_json};
const BG={json.dumps(BG, ensure_ascii=False)};
function bar(id, title, labels, vals, colors, ytitle) {{
  Plotly.newPlot(id, [{{x:labels, y:vals, type:'bar', marker:{{color:colors}},
    text:vals.map(v=>v===null?'—':(typeof v==='number'?v.toFixed(2):v)), textposition:'outside'}}],
    Object.assign({{title:title, yaxis:{{title:ytitle,zeroline:true,zerolinecolor:'#555'}}}}, BG));
}}
bar('c1', '型態①(close版)事件年度分布', D.c1.labels, D.c1.vals, '{BLUE}', '事件股-日數');
bar('c2', '型態②(120日版)事件年度分布', D.c2.labels, D.c2.vals, '{RED}', '事件股-日數');
if (D.c3) bar('c3', '型態①: 命中率(左2)+P&L proxy中位數(右2) 基準vs事件組', D.c3.labels, D.c3.vals, D.c3.colors, '%');
if (D.c4) bar('c4', '型態②: 命中率(左2)+P&L proxy中位數(右2) 基準vs事件組', D.c4.labels, D.c4.vals, D.c4.colors, '%');
</script>
</body></html>"""
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[report] 已輸出 {OUT}")


if __name__ == "__main__":
    main()
