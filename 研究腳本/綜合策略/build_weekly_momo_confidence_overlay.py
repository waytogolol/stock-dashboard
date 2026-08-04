# -*- coding: utf-8 -*-
"""週級強者續強×d4w個股信心層疊加測試(2026-08-04,使用者「三個新角度」第①題,優先度最高)。

背景: build_weekly_momo_regime_overlay.py已測過三種「市場級」regime開關(MA240趨勢/恐慌溫度計甜蜜格/
長假前減碼),全部失敗。最關鍵診斷: 基準版最差15週中0週在空頭regime觸發、僅3週在高波regime觸發——
MDD的元凶是「個股集中度風險」(訊號週籃子常常只有1-3檔股票),不是大盤系統性風險,大盤級regime分類器
天生偵測不到這種風險。本卷改測「個股層級」訊號: 把處置V4策略既有的d4w信心加碼層邏輯,套到週級動能
的個股選股上,看能不能對症下藥。

d4w定義(完全比照專案既有慣例,不重新發明,見build_disposition_tdcc.py.compute_tdcc_features()/
export_html.py的處置頁d4w欄): 「公告前最新集保快照的千張大戶%減4週前值」。這裡「公告」換成「週級動能
訊號觸發(entry_week週五收盤)」,cutoff=entry_week-3日曆日(LAG_DAYS=3,同既有慣例的發布延遲安全邊際,
避免用到「訊號週當週」尚未公布的集保快照,零前視);取cutoff當下最新快照(idx),若該快照距cutoff超過
21天(STALE_DAYS=21,同既有慣例)視為過期作廢;d4w=p1000[idx]-p1000[idx-4](需idx>=4,即至少有4份更早
快照可比較,即千張大戶持股比例4週流向,>0=大戶正在進)。

資料源: tdcc_weekly.p1000(2013-01-31~2026-07-09,凍結封存)UNION tdcc_holders.big1000_pct
(2026-07-09後接軌,同源零失真,見fetch_tdcc.py/export_html.py既有UNION口徑)——沒有filter code,取
全市場口徑,不像處置頁只查當事股票。

兩種用法(比照既有設計哲學「信心加碼層非硬濾網」,只加分不否決):
  a) 加權版: basket內d4w>0的股票給2倍權重,d4w<=0或缺值的股票維持基礎權重1倍(不排除任何股票,
     避免讓本來就偏薄的籃子更薄——這是使用者已確認過的核心風險)。
  b) 硬濾網版(對照組,故意違反既有設計哲學): 只買d4w>0的股票,基準籃子若因此變空則該週不進場。
     用來驗證「為什麼既有設計選擇不用硬濾網」這個判斷在週級動能上是否依然成立。
  缺值(不在tdcc/tdcc_holders裡查得到,或快照過期)一律視同「未確認大戶在進」——加權版給基礎權重
  (不加分不扣分),硬濾網版視同不合格(排除,因為它不滿足「>0」這個條件)。

方法論: import build_weekly_momo_regime_overlay.py複用面板建置(WIDE_C/WIDE_RET/LIQ_OK)/交易建置
(build_trades)/統計函式(stats_from_ret/trade_stats/bootstrap_ci/yearly_breakdown)。portfolio_curve
本身不支援「basket內逐檔不同權重」,故本卷另寫portfolio_curve_confidence()。

用法: python 研究腳本/綜合策略/build_weekly_momo_confidence_overlay.py (從根目錄執行,鐵律)
產出: 純console報告,無檔案輸出。
"""
import sqlite3
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "研究腳本/綜合策略")
sys.stdout.reconfigure(encoding="utf-8")

import build_weekly_momo_regime_overlay as M  # noqa: E402

DB = M.DB
LAG_DAYS = 3     # 訊號週entry_week - 3日曆日 = 快照cutoff(同build_disposition_tdcc.py慣例)
STALE_DAYS = 21  # 快照距cutoff超過21天 = 過期作廢(同慣例)
WEIGHT_MULT = 2.0
CRASH_WINDOWS = [("2025-04關稅崩盤", "2025-03-01", "2025-05-01"),
                  ("2026-07-24台股修正", "2026-06-01", "2026-08-04")]


# ══ 一、d4w資料源(全市場,零前視) ══════════════════════════════
def load_tdcc_map():
    """tdcc_weekly.p1000 UNION tdcc_holders.big1000_pct(同export_html.py既有接軌口徑),
    回傳 {code: (dates ndarray[datetime64[D]], vals ndarray[float])} 每碼依日期升冪排序。"""
    con = sqlite3.connect(DB)
    df = pd.read_sql(
        "SELECT code, date, p1000 FROM tdcc_weekly "
        "UNION SELECT code, date, big1000_pct FROM tdcc_holders",
        con, parse_dates=["date"])
    con.close()
    df = df.drop_duplicates(["code", "date"]).sort_values(["code", "date"])
    tmap = {}
    for code, g in df.groupby("code"):
        tmap[code] = (g["date"].values.astype("datetime64[D]"), g["p1000"].values.astype(float))
    return tmap


TDCC_MAP = load_tdcc_map()
print(f"tdcc地圖建置完成: {len(TDCC_MAP):,}檔(tdcc_weekly+tdcc_holders接軌,全市場)")


def d4w_lookup(code, entry_week):
    """單筆查詢: 回傳(in_tdcc, d4w_or_nan, snap_lag_or_nan)。cutoff=entry_week-LAG_DAYS,零前視。"""
    sv = TDCC_MAP.get(code)
    if sv is None:
        return False, np.nan, np.nan
    dts, vals = sv
    cutoff = np.datetime64((entry_week - pd.Timedelta(days=LAG_DAYS)).date())
    idx = int(np.searchsorted(dts, cutoff, side="right") - 1)
    if idx < 0:
        return True, np.nan, np.nan
    lag = int((cutoff - dts[idx]).astype(int))
    if lag > STALE_DAYS or idx < 4:
        return True, np.nan, float(lag)
    return True, float(vals[idx] - vals[idx - 4]), float(lag)


def compute_d4w_for_trades(trades):
    """為trades(每列=entry_week+code)逐筆算d4w,回傳新增三欄的trades副本。"""
    rows = [d4w_lookup(r.code, r.entry_week) for r in trades.itertuples()]
    trades = trades.copy()
    trades["in_tdcc"] = [r[0] for r in rows]
    trades["d4w"] = [r[1] for r in rows]
    trades["snap_lag"] = [r[2] for r in rows]
    return trades


def attach_d4w_to_baskets(baskets, trades):
    """把trades算好的d4w對照回weekly_baskets(build_trades回傳的是獨立DataFrame,非同一物件)。
    用dict((entry_week,code)->值)查表,避開MultiIndex.loc單列/多列回傳型別不一致的陷阱。"""
    d4w_lut = dict(zip(zip(trades["entry_week"], trades["code"]), trades["d4w"]))
    tdcc_lut = dict(zip(zip(trades["entry_week"], trades["code"]), trades["in_tdcc"]))
    out = {}
    for wk, b in baskets.items():
        b = b.copy()
        b["d4w"] = [d4w_lut.get((wk, c), np.nan) for c in b["code"]]
        b["in_tdcc"] = [tdcc_lut.get((wk, c), False) for c in b["code"]]
        out[wk] = b
    return out


# ══ 二、加權/硬濾網 portfolio建置 ══════════════════════════════
def portfolio_curve_confidence(baskets, grid, mode, weight_mult=WEIGHT_MULT):
    """mode: baseline(等權,不看d4w) / weighted(d4w>0給weight_mult倍權重,其餘/缺值1倍,非排除性) /
    hard_filter(只留d4w>0,籃子因此變空則該週不進場)。回傳(ret對齊grid, exec_trades, n_skipped_empty)。"""
    ret = pd.Series(0.0, index=grid)
    exec_list, n_skipped_empty = [], 0
    for wk, basket in baskets.items():
        exit_wk = basket["exit_week"].iloc[0]
        if exit_wk not in ret.index:
            continue
        if mode == "baseline":
            use = basket
            w = np.ones(len(use))
        elif mode == "weighted":
            use = basket
            d4 = use["d4w"].values.astype(float)
            w = np.where(np.nan_to_num(d4, nan=-1.0) > 0, weight_mult, 1.0)
        elif mode == "hard_filter":
            use = basket[basket["d4w"] > 0]  # NaN>0恆False,缺值自動排除(同硬濾網定義)
            if len(use) == 0:
                n_skipped_empty += 1
                continue
            w = np.ones(len(use))
        else:
            raise ValueError(mode)
        pr = float(np.average(use["net_ret"].values, weights=w))
        ret.loc[exit_wk] = pr
        exec_list.append(use.assign(weight_applied=w))
    exec_trades = pd.concat(exec_list, ignore_index=True) if exec_list else pd.DataFrame(
        columns=list(next(iter(baskets.values())).columns) + ["weight_applied"])
    return ret, exec_trades, n_skipped_empty


# ══ 三、主流程 ══════════════════════════════════════════
def run_threshold(threshold, label):
    print("\n" + "=" * 100)
    print(f"### 門檻={label} top{M.TOP_N} × d4w信心層 ###")
    trades, baskets = M.build_trades(threshold)
    trades = compute_d4w_for_trades(trades)
    baskets = attach_d4w_to_baskets(baskets, trades)
    weeks = M.WIDE_RET.index
    start_i = weeks.searchsorted(pd.Timestamp(M.START))
    grid = weeks[start_i:]

    # -- 覆蓋率 --
    n_total = len(trades)
    n_in_tdcc = int(trades["in_tdcc"].sum())
    n_valid = int(trades["d4w"].notna().sum())
    n_pos = int((trades["d4w"] > 0).sum())
    codes_total = trades["code"].nunique()
    codes_in_tdcc = trades.loc[trades["in_tdcc"], "code"].nunique()
    print(f"n_trades={n_total}  n_signal_weeks={len(baskets)}/{len(grid)}")
    print(f"覆蓋率(交易筆數): 碼在tdcc地圖裡出現過={n_in_tdcc}/{n_total}({n_in_tdcc/n_total*100:.1f}%) "
          f"  d4w有效(非過期非缺4週前值)={n_valid}/{n_total}({n_valid/n_total*100:.1f}%)"
          f"  其中d4w>0={n_pos}/{n_valid}({n_pos/n_valid*100 if n_valid else np.nan:.1f}%)")
    print(f"覆蓋率(不重複股票數): 出現過的股票={codes_total}檔  在tdcc地圖裡有資料={codes_in_tdcc}檔"
          f"({codes_in_tdcc/codes_total*100:.1f}%)")

    # -- 三版本比較 --
    variants = {}
    for name, mode in (("基準(等權,不看d4w)", "baseline"), ("加權版(d4w>0給2倍權重)", "weighted"),
                        ("硬濾網版(只買d4w>0)", "hard_filter")):
        r, ex, n_skip = portfolio_curve_confidence(baskets, grid, mode)
        st = M.stats_from_ret(r)
        tr = M.trade_stats(ex)
        ci = M.bootstrap_ci(ex)
        yr = M.yearly_breakdown(r)
        variants[name] = {"ret": r, "exec": ex, "n_skip": n_skip, **st,
                           **{f"tr_{k}": v for k, v in tr.items()}, "ci_lo": ci[0], "ci_hi": ci[1],
                           "n_pos_year": int((yr > 0).sum()), "n_year": len(yr),
                           "exposure": st["n_weeks_active"] / st["n_weeks_total"] * 100}

    print(f"\n硬濾網版: 因d4w>0後籃子變空而整週不進場的週數={variants['硬濾網版(只買d4w>0)']['n_skip']}"
          f"(原本{len(baskets)}訊號週)")

    print("\n-- 基準 vs 加權版 vs 硬濾網版 全比較表 --")
    hdr = (f"{'版本':<26}{'複利':>9}{'年化':>8}{'MDD':>8}{'夏普':>6}{'報酬/MDD':>9}"
           f"{'PF':>6}{'勝率':>6}{'單筆均':>8}{'CI':>20}{'曝險':>6}{'正年':>7}")
    print(hdr)
    for name, row in variants.items():
        ci_txt = f"[{row['ci_lo']:+.2f}%,{row['ci_hi']:+.2f}%]"
        print(f"{name:<26}{row['mult']:>8.1f}x{row['cagr']:>7.1f}%{row['mdd']:>7.1f}%"
              f"{row['sharpe']:>6.2f}{row['calmar']:>9.2f}{row['tr_pf']:>6.2f}{row['tr_win']:>5.0f}%"
              f"{row['tr_mean']:>7.2f}%{ci_txt:>20}{row['exposure']:>5.0f}%{row['n_pos_year']:>4d}/{row['n_year']:<3d}")
    print(f"\n  基準版MDD episode: {variants['基準(等權,不看d4w)']['dd_peak'].date()} ~ "
          f"{variants['基準(等權,不看d4w)']['dd_trough'].date()}")
    print(f"  加權版MDD episode: {variants['加權版(d4w>0給2倍權重)']['dd_peak'].date()} ~ "
          f"{variants['加權版(d4w>0給2倍權重)']['dd_trough'].date()}")
    print(f"  硬濾網版MDD episode: {variants['硬濾網版(只買d4w>0)']['dd_peak'].date()} ~ "
          f"{variants['硬濾網版(只買d4w>0)']['dd_trough'].date()}")

    # -- 基準版最差15週: d4w有沒有可能篩掉元凶? --
    ret_base = variants["基準(等權,不看d4w)"]["ret"]
    worst = ret_base.sort_values().head(15)
    entry_of = {b["exit_week"].iloc[0]: wk for wk, b in baskets.items()}
    print("\n-- 基準版最差15週: 該週basket的d4w組成 + 三版本該週報酬對照 --")
    print(f"{'exit週':<12}{'基準':>8}{'加權':>8}{'硬濾網':>10}{'entry週':<12}{'n':>3}{'d4w>0':>6}{'d4w<=0/缺':>9}")
    for exit_wk, r in worst.items():
        entry_wk = entry_of.get(exit_wk)
        if entry_wk is None:
            continue
        b = baskets[entry_wk]
        n_pos_wk = int((b["d4w"] > 0).sum())
        n_rest_wk = len(b) - n_pos_wk
        w_arr = np.where(np.nan_to_num(b["d4w"].values.astype(float), nan=-1.0) > 0, WEIGHT_MULT, 1.0)
        rw = float(np.average(b["net_ret"].values, weights=w_arr))
        hb = b[b["d4w"] > 0]
        rh_txt = "跳過(空籃)" if len(hb) == 0 else f"{float(hb['net_ret'].mean())*100:+8.1f}%"
        print(f"{str(exit_wk.date()):<12}{r*100:>+7.1f}%{rw*100:>+7.1f}%{rh_txt:>10}"
              f"{str(entry_wk.date()):<12}{len(b):>3}{n_pos_wk:>6}{n_rest_wk:>9}")

    # -- 兩次真實重挫週深挖 --
    print("\n-- 兩次真實重挫週: 訊號週basket的d4w讀數(有沒有提前示警) --")
    for label2, s, e in CRASH_WINDOWS:
        print(f"\n  ▼ {label2}({s}~{e}) --")
        for wk, b in sorted(baskets.items()):
            exit_wk = b["exit_week"].iloc[0]
            if not (pd.Timestamp(s) <= exit_wk <= pd.Timestamp(e)):
                continue
            n_pos_wk = int((b["d4w"] > 0).sum())
            n_val_wk = int(b["d4w"].notna().sum())
            mean_d4 = b["d4w"].mean()
            base_r = float(b["net_ret"].mean())
            w_arr = np.where(np.nan_to_num(b["d4w"].values.astype(float), nan=-1.0) > 0, WEIGHT_MULT, 1.0)
            w_r = float(np.average(b["net_ret"].values, weights=w_arr))
            hb = b[b["d4w"] > 0]
            h_r = float(hb["net_ret"].mean()) if len(hb) else np.nan
            print(f"    entry{wk.date()}→exit{exit_wk.date()}: n={len(b):>2} d4w有效={n_val_wk} "
                  f"d4w>0={n_pos_wk} d4w均={mean_d4:+.2f}  基準ret={base_r*100:+.2f}% "
                  f"加權ret={w_r*100:+.2f}% 硬濾網ret={'跳過(空籃)' if len(hb)==0 else f'{h_r*100:+.2f}%'}")

    return variants


def main():
    for threshold, label in ((0.20, "20%"), (0.15, "15%")):
        run_threshold(threshold, label)
    print("\n" + "=" * 100)
    print("跑完。以上為console探索報告,無檔案輸出。")


if __name__ == "__main__":
    main()
