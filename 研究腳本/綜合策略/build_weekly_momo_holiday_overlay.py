# -*- coding: utf-8 -*-
"""週級強者續強×長假收手疊加測試(2026-08-04,使用者提案:「如果遇到長假,可以嘗試長假前收手」)。

動機: 今天稍早週級動能regime控倉考卷(build_weekly_momo_regime_overlay.py)找出兩次最大回撤(2025-04
關稅崩盤/2026-07-24修正)都對應真實系統性重挫,但regime開關測試全部失敗(元凶診斷為個股集中度風險非
系統性風險)。使用者提案改個角度:不是預測regime,而是單純避開「持倉期間橫跨長假」這個結構性風險——
長假期間國際市場照常波動但台股不能反應,重開盤補跌/補漲的缺口是已知現象。

意外驗證: 查了一下2025-04關稅崩盤的確切日期,發現2025-04-02(上一交易日)到2025-04-07(下一交易日)
剛好是清明連假(交易日間隔5天)!全球「解放日」關稅衝擊剛好發生在台股放假期間,04-07開盤直接跳空補跌
(TAIEX約21,298->19,232附近)。這正是使用者提案要防的那種缺口風險,不是巧合。

規則設計: 長假定義=index_daily(TAIEX)相鄰交易日間隔>=4個日曆天(涵蓋春節/清明/端午/中秋/國慶等,
2015起共87次)。若某筆交易的「持有期」(entry_week收盤進場~exit_week收盤出場,即訊號週結束到次週結束
這整整7-8個日曆天)與某次長假的[假期前最後交易日, 假期後第一個交易日]區間有重疊,判定為「跨長假」交易。
測試: switch(跨長假週完全不進場) vs baseline(全押,沿用regime考卷同一套零前視/清洗/成本設定)。

用法: python 研究腳本/綜合策略/build_weekly_momo_holiday_overlay.py (從根目錄執行,鐵律)
依賴: import自build_weekly_momo_regime_overlay.py複用其面板/成本/清洗邏輯,不重新建置,不重複造輪子。
產出: 純console報告,不寫檔案不動既有檔案。
"""
import sys

import numpy as np
import pandas as pd
import sqlite3

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "研究腳本/綜合策略")

import build_weekly_momo_regime_overlay as M  # noqa: E402  複用面板/交易建置/成本/清洗

DB = "capital_flow.db"


def load_long_holidays():
    """回傳[(假期前最後交易日, 假期後第一個交易日), ...],間隔>=4日曆天(2015起)"""
    con = sqlite3.connect(DB)
    df = pd.read_sql("select date from index_daily where market='TAIEX' order by date",
                      con, parse_dates=["date"])
    con.close()
    df["gap"] = df["date"].diff().dt.days
    out = []
    for i in df.index[df["gap"] >= 4]:
        out.append((df.loc[i - 1, "date"], df.loc[i, "date"]))
    return out


def crosses_holiday(entry_week, exit_week, holidays):
    """entry_week收盤進場~exit_week收盤出場這段持有期,是否與任一長假[before,after]區間重疊"""
    for before, after in holidays:
        if before <= exit_week and after >= entry_week:
            return True
    return False


def main():
    holidays = load_long_holidays()
    print(f"長假清單: 共{len(holidays)}次(2015起,交易日間隔>=4天)")

    for threshold, label in [(0.20, "20%"), (0.15, "15%")]:
        print("\n" + "=" * 100)
        print(f"### 門檻={label} top{M.TOP_N} — 長假收手測試 ###")
        trades, baskets = M.build_trades(threshold)
        weeks = M.WIDE_RET.index
        start_i = weeks.searchsorted(pd.Timestamp(M.START))
        grid = weeks[start_i:]

        cross_flag = {}
        for wk, basket in baskets.items():
            exit_wk = basket["exit_week"].iloc[0]
            cross_flag[wk] = crosses_holiday(wk, exit_wk, holidays)
        n_cross = sum(cross_flag.values())
        print(f"n_signal_weeks={len(baskets)}, 跨長假週數={n_cross}"
              f"({n_cross / max(len(baskets), 1) * 100:.1f}%)")

        def favorable(wk):
            return not cross_flag[wk]

        ret_base, exec_base = M.portfolio_curve(baskets, grid, mode="baseline", weighting="equal")
        st_base = M.stats_from_ret(ret_base)
        tr_base = M.trade_stats(exec_base)
        ci_base = M.bootstrap_ci(exec_base)

        ret_sw, exec_sw = M.portfolio_curve(baskets, grid, favorable_fn=favorable,
                                            mode="switch", weighting="equal")
        st_sw = M.stats_from_ret(ret_sw)
        tr_sw = M.trade_stats(exec_sw)
        ci_sw = M.bootstrap_ci(exec_sw)

        print(f"\n{'版本':<14}{'複利':>9}{'年化':>8}{'MDD':>9}{'夏普':>7}{'Calmar':>8}"
              f"{'PF':>6}{'勝率':>7}{'單筆均(CI)':>26}")
        for name, st, tr, ci in [("基準(全押)", st_base, tr_base, ci_base),
                                  ("長假收手·開關", st_sw, tr_sw, ci_sw)]:
            print(f"{name:<14}{st['mult']:>8.2f}x{st['cagr']:>7.1f}%{st['mdd']:>8.1f}%"
                  f"{st['sharpe']:>7.2f}{st['calmar']:>8.2f}{tr['pf']:>6.2f}{tr['win']:>6.1f}%"
                  f"  {tr['mean']:+.2f}%[{ci[0]:+.2f},{ci[1]:+.2f}]")

        # 逐年對照
        print("\n-- 逐年報酬對照(基準 vs 長假收手) --")
        yb, ys = M.yearly_breakdown(ret_base), M.yearly_breakdown(ret_sw)
        for yr in sorted(set(yb.index) | set(ys.index)):
            print(f"  {yr}: 基準{yb.get(yr, 0):+7.2f}%  收手{ys.get(yr, 0):+7.2f}%")

        # 直接驗證2025-04崩盤週有沒有被抓到、抓到後救了多少
        print("\n-- 2025-04關稅崩盤週逐週明細對照 --")
        for wk in sorted(baskets.keys()):
            if pd.Timestamp("2025-03-20") <= wk <= pd.Timestamp("2025-04-20"):
                exit_wk = baskets[wk]["exit_week"].iloc[0]
                n_stk = len(baskets[wk])
                cr = cross_flag[wk]
                base_r = ret_base.get(exit_wk, np.nan)
                sw_r = ret_sw.get(exit_wk, np.nan) if not cr else 0.0
                print(f"  entry={wk.date()} exit={exit_wk.date()} n={n_stk} "
                      f"跨長假={cr}  基準報酬={base_r * 100:+.2f}%  收手版報酬={sw_r * 100:+.2f}%")


if __name__ == "__main__":
    main()
