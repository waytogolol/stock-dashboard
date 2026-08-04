# -*- coding: utf-8 -*-
"""週級強者續強×長假減碼精修+安慰劑對照(2026-08-04,接續build_weekly_momo_holiday_overlay.py)。

使用者要求兩件事:
①減碼版(reduce_capital)取代開關版(switch),比照regime考卷的既有發現(減碼常比開關保留更多報酬)
②安慰劑/反向對照:「如果我們剛覺得要減碼的反而不減碼,不該減碼的反而減碼,這樣效果會更好嗎?」
  ——這是很扎實的方法論檢查:如果隨便減碼任何一批同樣大小的週(不管跟假期有沒有關係)也能讓MDD
  一樣改善,代表這個效果只是「減碼曝險」本身的訊號,不是「長假」這個機制真的在起作用。

三組對照設計:
- H_reduce: 長假收手週減碼50%(正確假說版)
- H_inverse: 反過來,長假收手週維持全倉、非假期週減碼50%(邏輯顛倒版,若這個也能改善MDD就說明機制不成立)
- H_random×200: 隨機抽跟長假週數量相同的週減碼50%,重複200次看分佈,長假版的MDD改善要顯著優於
  隨機分佈的中位數才算通過安慰劑檢定
另外測窄版長假定義(僅春節等9天以上長假,不含清明/端午等常規4-5天連假)的減碼版當敏感度對照。

用法: python 研究腳本/綜合策略/build_weekly_momo_holiday_overlay2.py (從根目錄執行,鐵律)
依賴: import build_weekly_momo_regime_overlay.py(面板/交易建置)同build_weekly_momo_holiday_overlay.py
"""
import sys

import numpy as np
import pandas as pd
import sqlite3

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "研究腳本/綜合策略")

import build_weekly_momo_regime_overlay as M  # noqa: E402

DB = "capital_flow.db"
RNG = np.random.default_rng(20260804)
N_RANDOM = 200


def load_long_holidays(min_gap=4):
    con = sqlite3.connect(DB)
    df = pd.read_sql("select date from index_daily where market='TAIEX' order by date",
                      con, parse_dates=["date"])
    con.close()
    df["gap"] = df["date"].diff().dt.days
    out = []
    for i in df.index[df["gap"] >= min_gap]:
        out.append((df.loc[i - 1, "date"], df.loc[i, "date"]))
    return out


def crosses_holiday(entry_week, exit_week, holidays):
    for before, after in holidays:
        if before <= exit_week and after >= entry_week:
            return True
    return False


def report(name, ret, tr_exec):
    st = M.stats_from_ret(ret)
    tr = M.trade_stats(tr_exec)
    ci = M.bootstrap_ci(tr_exec)
    print(f"{name:<18}{st['mult']:>9.2f}x{st['cagr']:>7.1f}%{st['mdd']:>8.1f}%"
          f"{st['sharpe']:>7.2f}{st['calmar']:>8.2f}{tr['pf']:>6.2f}{tr['win']:>6.1f}%"
          f"  {tr['mean']:+.2f}%[{ci[0]:+.2f},{ci[1]:+.2f}]")
    return st


def main():
    holidays_wide = load_long_holidays(min_gap=4)
    holidays_cny = load_long_holidays(min_gap=9)
    print(f"寬版長假(>=4天): {len(holidays_wide)}次 / 窄版長假(僅春節等>=9天): {len(holidays_cny)}次")

    for threshold, label in [(0.20, "20%"), (0.15, "15%")]:
        print("\n" + "=" * 100)
        print(f"### 門檻={label} top{M.TOP_N} — 減碼版+安慰劑對照 ###")
        trades, baskets = M.build_trades(threshold)
        weeks = M.WIDE_RET.index
        start_i = weeks.searchsorted(pd.Timestamp(M.START))
        grid = weeks[start_i:]
        wk_list = list(baskets.keys())

        cross_wide = {wk: crosses_holiday(wk, baskets[wk]["exit_week"].iloc[0], holidays_wide)
                      for wk in wk_list}
        cross_cny = {wk: crosses_holiday(wk, baskets[wk]["exit_week"].iloc[0], holidays_cny)
                     for wk in wk_list}
        n_wide = sum(cross_wide.values())
        n_cny = sum(cross_cny.values())
        print(f"n_signal_weeks={len(wk_list)}  寬版跨假期={n_wide}({n_wide/len(wk_list)*100:.1f}%)  "
              f"窄版跨假期={n_cny}({n_cny/len(wk_list)*100:.1f}%)")

        print(f"\n{'版本':<18}{'複利':>9}{'年化':>8}{'MDD':>9}{'夏普':>7}{'Calmar':>8}"
              f"{'PF':>6}{'勝率':>7}{'單筆均(CI)':>26}")

        ret_base, exec_base = M.portfolio_curve(baskets, grid, mode="baseline", weighting="equal")
        st_base = report("基準(全押)", ret_base, exec_base)

        # H_reduce: 寬版長假週減碼50%
        fav_wide = lambda wk: not cross_wide[wk]  # noqa: E731
        ret_hw, exec_hw = M.portfolio_curve(baskets, grid, favorable_fn=fav_wide,
                                            mode="reduce_capital", reduce_frac=0.5, weighting="equal")
        st_hw = report("寬版長假·減碼50%", ret_hw, exec_hw)

        # H_reduce窄版: 僅春節等長假週減碼50%
        fav_cny = lambda wk: not cross_cny[wk]  # noqa: E731
        ret_hc, exec_hc = M.portfolio_curve(baskets, grid, favorable_fn=fav_cny,
                                            mode="reduce_capital", reduce_frac=0.5, weighting="equal")
        st_hc = report("窄版(僅春節)減碼50%", ret_hc, exec_hc)

        # H_inverse: 邏輯顛倒,長假週維持全倉,非長假週減碼50%(安慰劑檢定用)
        fav_inv = lambda wk: cross_wide[wk]  # noqa: E731
        ret_inv, exec_inv = M.portfolio_curve(baskets, grid, favorable_fn=fav_inv,
                                              mode="reduce_capital", reduce_frac=0.5, weighting="equal")
        st_inv = report("反向(非假期減碼)", ret_inv, exec_inv)

        # H_random: 隨機抽跟寬版長假週數相同的週減碼50%,重複N_RANDOM次
        mdds, cagrs, sharpes = [], [], []
        for _ in range(N_RANDOM):
            picked = set(RNG.choice(wk_list, size=n_wide, replace=False))
            fav_r = lambda wk: wk not in picked  # noqa: E731
            ret_r, _ = M.portfolio_curve(baskets, grid, favorable_fn=fav_r,
                                         mode="reduce_capital", reduce_frac=0.5, weighting="equal")
            st_r = M.stats_from_ret(ret_r)
            mdds.append(st_r["mdd"])
            cagrs.append(st_r["cagr"])
            sharpes.append(st_r["sharpe"])
        mdds = np.array(mdds)
        print(f"\n隨機對照(N={N_RANDOM},每次隨機減碼{n_wide}週=50%,同長假週數量):")
        print(f"  MDD分佈: 中位數={np.median(mdds):.1f}%  [5%,95%分位]=[{np.percentile(mdds,5):.1f}%,"
              f"{np.percentile(mdds,95):.1f}%]  年化中位數={np.median(cagrs):.1f}%  "
              f"夏普中位數={np.median(sharpes):.2f}")
        pctile = (mdds < st_hw["mdd"]).mean() * 100  # 長假版MDD比幾%的隨機版更差(數值更負排名)
        better_pct = (mdds >= st_hw["mdd"]).mean() * 100
        print(f"  長假版MDD({st_hw['mdd']:.1f}%)在隨機分佈中的百分位: 贏過{better_pct:.0f}%的隨機版本"
              f"(50%=純巧合,越高越表示長假選週真的有精準度,不只是單純減碼曝險)")


if __name__ == "__main__":
    main()
