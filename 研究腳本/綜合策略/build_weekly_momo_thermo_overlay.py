# -*- coding: utf-8 -*-
"""週級強者續強×恐慌溫度計regime控倉(2026-08-04,使用者糾正:「你這個定義太晚了,為何不用大盤溫度計
觀察的研究去套用到這個週策略」)。

背景: 原regime控倉考卷(build_weekly_momo_regime_overlay.py)用MA240+20日斜率當趨勢regime,使用者
指出這對「每週換股」的策略而言反應太慢(MA240本身就是260天的落後窗,2025-04關稅崩盤幾天內就跌完,
年線斜率翻空頭時早就跌完了)。改用`研究腳本/底部溫度計/build_panic_gradient.py`的甜蜜格(sweet spot)
單日並發數當regime訊號——這是同日反應的市場層恐慌出清標記,不是落後移動平均。

溫度計定義(比照build_panic_thermometer_report.py既有口徑,不重新發明): 甜蜜格=個股當日同時滿足
「近40日曾漲20%(volhi)×已從高點拉回>=20%(pull)×當日再跌6-9%(dd)」;單日並發數=當天滿足此條件的
股票數。既有研究門檻>=20=7大恐慌日全命中零前視,但那是「進場買」的極端門檻,本卷是要當「週策略要不要
進場」的regime開關,並發數>=20一年可能只出現個位數次,太罕見無法當常態開關,改測較低的並發數門檻
(>=5/>=10)當regime分界,並比較訊號日當天vs近5個交易日內最高值(避免只看entry當天漏掉週中已經惡化
又稍微回穩的情況,但只用entry週五收盤前的資訊,零前視)。

用法: python 研究腳本/綜合策略/build_weekly_momo_thermo_overlay.py (從根目錄執行,鐵律)
依賴: import build_weekly_momo_regime_overlay.py複用面板/交易建置/成本設定,快取/tmp_panic_gradient_panel.pkl
"""
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "研究腳本/綜合策略")
import build_weekly_momo_regime_overlay as M  # noqa: E402

PANEL_PATH = "快取/tmp_panic_gradient_panel.pkl"


def load_daily_panic_count():
    """回傳每日甜蜜格並發數的Series(index=交易日,零前視——只統計當天已知資訊)"""
    p = pd.read_pickle(PANEL_PATH)
    ss = p[(p["i1"] == "-6~-9") & (p["i2"] == ">=20%")]
    daily = ss.groupby("d0")["code"].nunique()
    return daily.sort_index()


def thermo_tag_asof(daily_count, entry_dates, lookback=5, threshold=5):
    """entry_dates(週五收盤)→過去lookback個交易日內(含當日)並發數最高值,判定是否>=threshold(高溫)"""
    idx = daily_count.index
    out = []
    for d in entry_dates:
        window = daily_count[daily_count.index <= d].tail(lookback)
        out.append(window.max() if len(window) else 0)
    s = pd.Series(out, index=range(len(entry_dates)))
    return s.fillna(0)


def main():
    daily_count = load_daily_panic_count()
    print(f"甜蜜格單日並發數: {len(daily_count)}個觸發日, 分佈p50={daily_count.median():.0f} "
          f"p90={daily_count.quantile(.9):.0f} p99={daily_count.quantile(.99):.0f} max={daily_count.max()}")
    # 補齊完整交易日(非觸發日=0),供近N日lookback正確計算
    con_dates = pd.read_sql("select distinct date from index_daily where market='TAIEX' order by date",
                            __import__("sqlite3").connect("capital_flow.db"), parse_dates=["date"])["date"]
    full_count = daily_count.reindex(con_dates, fill_value=0)

    weeks = M.WIDE_RET.index
    start_i = weeks.searchsorted(pd.Timestamp(M.START))
    grid = weeks[start_i:]

    for threshold in (3, 5, 8):
        print("\n" + "=" * 100)
        print(f"### 溫度計門檻: 近5交易日內並發數曾達>={threshold} 視為高溫regime ###")
        for th_sig, label in [(0.20, "20%"), (0.15, "15%")]:
            trades, baskets = M.build_trades(th_sig)
            wk_list = list(baskets.keys())
            tags = thermo_tag_asof(full_count, wk_list, lookback=5, threshold=threshold)
            hot = {wk: (tags.iloc[i] >= threshold) for i, wk in enumerate(wk_list)}
            n_hot = sum(hot.values())
            fav = lambda wk: not hot[wk]  # noqa: E731

            ret_base, exec_base = M.portfolio_curve(baskets, grid, mode="baseline", weighting="equal")
            st_base = M.stats_from_ret(ret_base)

            ret_sw, exec_sw = M.portfolio_curve(baskets, grid, favorable_fn=fav, mode="switch",
                                                weighting="equal")
            st_sw = M.stats_from_ret(ret_sw)
            tr_sw = M.trade_stats(exec_sw)
            ci_sw = M.bootstrap_ci(exec_sw)

            ret_rd, exec_rd = M.portfolio_curve(baskets, grid, favorable_fn=fav, mode="reduce_capital",
                                                reduce_frac=0.5, weighting="equal")
            st_rd = M.stats_from_ret(ret_rd)
            tr_rd = M.trade_stats(exec_rd)
            ci_rd = M.bootstrap_ci(exec_rd)

            print(f"\n門檻{label}: n_signal_weeks={len(wk_list)}  高溫週={n_hot}"
                  f"({n_hot/max(len(wk_list),1)*100:.1f}%)")
            print(f"  {'版本':<16}{'複利':>9}{'年化':>8}{'MDD':>9}{'夏普':>7}{'Calmar':>8}{'PF':>6}"
                  f"{'勝率':>7}")
            print(f"  {'基準(全押)':<16}{st_base['mult']:>8.2f}x{st_base['cagr']:>7.1f}%"
                  f"{st_base['mdd']:>8.1f}%{st_base['sharpe']:>7.2f}{st_base['calmar']:>8.2f}"
                  f"{'—':>6}{'—':>7}")
            print(f"  {'高溫開關':<16}{st_sw['mult']:>8.2f}x{st_sw['cagr']:>7.1f}%"
                  f"{st_sw['mdd']:>8.1f}%{st_sw['sharpe']:>7.2f}{st_sw['calmar']:>8.2f}"
                  f"{tr_sw['pf']:>6.2f}{tr_sw['win']:>6.1f}%")
            print(f"  {'高溫減碼50%':<16}{st_rd['mult']:>8.2f}x{st_rd['cagr']:>7.1f}%"
                  f"{st_rd['mdd']:>8.1f}%{st_rd['sharpe']:>7.2f}{st_rd['calmar']:>8.2f}"
                  f"{tr_rd['pf']:>6.2f}{tr_rd['win']:>6.1f}%")

            if threshold == 5:
                print("\n  -- 兩次真實重挫週,當下溫度計讀數 --")
                for wk in sorted(wk_list):
                    if (pd.Timestamp("2025-03-14") <= wk <= pd.Timestamp("2025-04-25")) or \
                       (pd.Timestamp("2026-07-10") <= wk <= pd.Timestamp("2026-08-04")):
                        i = wk_list.index(wk)
                        exit_wk = baskets[wk]["exit_week"].iloc[0]
                        base_r = ret_base.get(exit_wk, np.nan)
                        print(f"    entry={wk.date()} 溫度讀數(近5日內最高)={tags.iloc[i]:.0f} "
                              f"高溫={hot[wk]}  基準週報酬={base_r*100:+.2f}%")


if __name__ == "__main__":
    main()
