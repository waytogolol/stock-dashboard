# -*- coding: utf-8 -*-
"""週級強者續強×融資維持率警戒帶regime疊加測試(2026-08-04,使用者「三個新角度」第②題)。

背景: build_weekly_momo_regime_overlay.py已測過MA240趨勢/波動regime,build_panic_liquidity相關考卷
測過恐慌溫度計甜蜜格並發數,全部失敗(乾淨負結果),因為那些訊號在真崩盤週的讀數是0(要等崩完才會亮,
是抄底訊號不是預警訊號)。本卷測第三個候選: 融資維持率警戒帶,沿用既有考卷
research_margin_band.html(build_margin_otc_band.py)的判決結論——「E3獨立增量: 真發現,兩市同破
(n=5)k20+10.30%/k60+11.12%/勝80%=強出清買點」,注意這本身就是「出清後偏反彈」的訊號(跟溫度計同類),
本卷誠實檢查它套到週級動能regime開關上會不會一樣是「已經崩完才亮」的落後訊號。

門檻定義(完全比照build_margin_otc_band.py既有口徑,不重新發明): WARN=150(官方維持率150%警戒線,
沿用該卷/儀表板既有慣例)。「兩市同破」регime=上市margin_maintenance_official.ratio<150 且同時
上櫃margin_maintenance_otc.ratio<150(當日,ffill到訊號週五收盤,零前視,同build_weekly_momo_regime_
overlay.py的REG_TREND/REG_VOL慣例——用截至當下已知的最新一筆值,不使用未來資料)。敏感度對照:
「官方版單獨<150」(不要求上櫃同步破)。未採用「單日/週跌幅劇烈」版本,因為該候選在專案裡沒有已驗證
的門檻可援引,會變成臨時發明新規則,不符合本卷「複用既有基礎設施」的方法論要求;「兩市同破」則直接
繼承research_margin_band.html已完成統計檢定的E3發現,口徑最乾淨。

方法論: import build_weekly_momo_regime_overlay.py複用面板建置/交易建置/portfolio_curve(switch/
reduce_capital兩種模式,與市場級趨勢/波動regime同一套介面)/統計函式。

用法: python 研究腳本/綜合策略/build_weekly_momo_margin_overlay.py (從根目錄執行,鐵律)
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
WARN = 150.0
CRASH_WINDOWS = [("2025-04關稅崩盤", "2025-03-01", "2025-05-01"),
                  ("2026-07-24台股修正", "2026-06-01", "2026-08-04")]


# ══ 一、融資維持率regime序列(零前視) ══════════════════════════════
def load_margin_ratios():
    con = sqlite3.connect(DB)
    off = pd.read_sql("SELECT date, ratio FROM margin_maintenance_official ORDER BY date",
                       con, parse_dates=["date"]).set_index("date")["ratio"]
    otc = pd.read_sql("SELECT date, ratio FROM margin_maintenance_otc ORDER BY date",
                       con, parse_dates=["date"]).set_index("date")["ratio"]
    con.close()
    return off, otc


OFF, OTC = load_margin_ratios()
print(f"上市維持率: {len(OFF)}日 {OFF.index.min().date()}~{OFF.index.max().date()}")
print(f"上櫃維持率: {len(OTC)}日 {OTC.index.min().date()}~{OTC.index.max().date()}")

_both = pd.concat([OFF.rename("off"), OTC.rename("otc")], axis=1).sort_index().ffill()
REG_BOTH = pd.Series(np.where((_both["off"] < WARN) & (_both["otc"] < WARN), "兩市同破", "正常"),
                      index=_both.index)
REG_OFF_ONLY = pd.Series(np.where(OFF < WARN, "上市單獨破", "正常"), index=OFF.index)

n_both_days = int((REG_BOTH == "兩市同破").sum())
print(f"「兩市同破」regime全期觸發: {n_both_days}/{len(REG_BOTH)}天"
      f"({n_both_days / len(REG_BOTH) * 100:.1f}%),{'0' if n_both_days == 0 else '見下方episode'}")
n_off_days = int((REG_OFF_ONLY == "上市單獨破").sum())
print(f"「上市單獨<150」regime全期觸發: {n_off_days}/{len(REG_OFF_ONLY)}天"
      f"({n_off_days / len(REG_OFF_ONLY) * 100:.1f}%)")


def make_favorable_lookup(baskets, series, bad_label):
    wks = list(baskets.keys())
    tags = M.tag_at(series, wks).values
    fav = {w: (t != bad_label) for w, t in zip(wks, tags)}
    return lambda w: fav[w]


# ══ 二、主流程 ══════════════════════════════════════════
def run_threshold(threshold, label):
    print("\n" + "=" * 100)
    print(f"### 門檻={label} top{M.TOP_N} × 融資維持率警戒帶regime ###")
    trades, baskets = M.build_trades(threshold)
    weeks = M.WIDE_RET.index
    start_i = weeks.searchsorted(pd.Timestamp(M.START))
    grid = weeks[start_i:]
    print(f"n_trades={len(trades)}  n_signal_weeks={len(baskets)}/{len(grid)}")

    fav_both = make_favorable_lookup(baskets, REG_BOTH, "兩市同破")
    fav_off = make_favorable_lookup(baskets, REG_OFF_ONLY, "上市單獨破")
    n_unfav_both = sum(1 for w in baskets if not fav_both(w))
    n_unfav_off = sum(1 for w in baskets if not fav_off(w))
    print(f"訊號週落在「兩市同破」regime的週數={n_unfav_both}/{len(baskets)}  "
          f"落在「上市單獨破」regime的週數={n_unfav_off}/{len(baskets)}")

    variants = {"基準(全押)": (None, "baseline")}
    for rname, fav in (("兩市同破·關", fav_both), ("上市單獨破·關(敏感度)", fav_off)):
        variants[f"{rname}開關版"] = (fav, "switch")
        variants[f"{rname}減碼50%版"] = (fav, "reduce_capital")

    rows = []
    for name, (fav, mode) in variants.items():
        r, ex = M.portfolio_curve(baskets, grid, favorable_fn=fav, mode=mode, weighting="equal")
        st = M.stats_from_ret(r)
        tr = M.trade_stats(ex)
        ci = M.bootstrap_ci(ex)
        yr = M.yearly_breakdown(r)
        rows.append({"variant": name, **st, **{f"tr_{k}": v for k, v in tr.items()},
                     "ci_lo": ci[0], "ci_hi": ci[1],
                     "n_pos_year": int((yr > 0).sum()), "n_year": len(yr),
                     "exposure": st["n_weeks_active"] / st["n_weeks_total"] * 100})

    print("\n-- 基準 vs 融資維持率regime控倉版 全比較表 --")
    hdr = (f"{'版本':<28}{'複利':>9}{'年化':>8}{'MDD':>8}{'夏普':>6}{'報酬/MDD':>9}"
           f"{'PF':>6}{'勝率':>6}{'單筆均':>8}{'CI':>20}{'曝險':>6}{'正年':>7}")
    print(hdr)
    for row in rows:
        ci_txt = f"[{row['ci_lo']:+.2f}%,{row['ci_hi']:+.2f}%]"
        print(f"{row['variant']:<28}{row['mult']:>8.1f}x{row['cagr']:>7.1f}%{row['mdd']:>7.1f}%"
              f"{row['sharpe']:>6.2f}{row['calmar']:>9.2f}{row['tr_pf']:>6.2f}{row['tr_win']:>5.0f}%"
              f"{row['tr_mean']:>7.2f}%{ci_txt:>20}{row['exposure']:>5.0f}%{row['n_pos_year']:>4d}/{row['n_year']:<3d}")
    print(f"\n  基準版MDD episode: {rows[0]['dd_peak'].date()} ~ {rows[0]['dd_trough'].date()}")

    return trades, baskets, grid, rows


def crash_deep_dive():
    print("\n" + "=" * 100)
    print("### 兩次真實重挫週: 融資維持率regime讀數是否提前示警 ###")
    taiex_wk = M.TAIEX.resample("W-FRI").last()
    taiex_wret = taiex_wk.pct_change(fill_method=None) * 100
    for label, s, e in CRASH_WINDOWS:
        print(f"\n--- {label}({s}~{e}) ---")
        print(f"{'週(W-FRI)':<12}{'TAIEX週報酬':>12}{'上市維持率':>12}{'上櫃維持率':>12}  regime(兩市同破?)")
        for wk in taiex_wret.loc[s:e].index:
            t = M.tag_at(REG_BOTH, [wk]).iloc[0]
            off_v = OFF.reindex([wk], method="ffill").iloc[0]
            otc_v = OTC.reindex([wk], method="ffill").iloc[0]
            print(f"{str(wk.date()):<12}{taiex_wret[wk]:>+11.2f}%{off_v:>11.1f}%{otc_v:>11.1f}%    {t}")

    print("\n-- 逐日細看兩次窗內是否曾經跌破(不受週五取樣掩蓋) --")
    for label, s, e in CRASH_WINDOWS:
        seg = _both.loc[s:e]
        breach = seg[(seg["off"] < WARN) & (seg["otc"] < WARN)]
        print(f"  {label}: 窗內逐日兩市同破天數={len(breach)}/{len(seg)}"
              f"{'' if len(breach) == 0 else '  日期=' + ','.join(str(d.date()) for d in breach.index)}")
        print(f"    窗內最低點: 上市={seg['off'].min():.1f}%({seg['off'].idxmin().date()})  "
              f"上櫃={seg['otc'].min():.1f}%({seg['otc'].idxmin().date()})")


def main():
    run_threshold(0.20, "20%")
    run_threshold(0.15, "15%")
    crash_deep_dive()
    print("\n" + "=" * 100)
    print("跑完。以上為console探索報告,無檔案輸出。")


if __name__ == "__main__":
    main()
