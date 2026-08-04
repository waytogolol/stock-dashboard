# -*- coding: utf-8 -*-
"""週級強者續強·進場可執行性校正(2026-08-05,使用者連續追問進場價假設是否切實可行)。

問題: 原始版本(build_weekly_momo_regime_overlay.py)entry_ret=訊號週自己的收盤報酬,net_ret的成本
基礎其實是「訊號週自己的收盤價」——比使用者猜測的「隔週開盤價」更理想化(隔週開盤價至少理論上看到
週五收盤後可以掛單等下週一開盤成交,訊號週自己收盤價則是假設能精準買在還沒收盤確認的那個價位)。

本卷測真正可執行版本: 進場價=訊號觸發後下一個交易日(通常是下週一,遇假日順延)的開盤價,取代訊號週
自己的收盤價。出場端維持原設計(次週五收盤),之後如有需要再另外測出場端校正。

用法: python 研究腳本/綜合策略/build_weekly_momo_entry_realism.py (從根目錄執行,鐵律)
"""
import sys

import numpy as np
import pandas as pd
import sqlite3

sys.path.insert(0, "研究腳本/綜合策略")
import build_weekly_momo_regime_overlay as M  # noqa: E402

DB = "capital_flow.db"


def load_daily():
    con = sqlite3.connect(DB)
    df = pd.read_sql(f"SELECT code, date, open, close, money FROM fm_daily_price "
                     f"WHERE date>='{M.BUFFER_START}'", con, parse_dates=["date"])
    con.close()
    df = df[(df["close"] > 0) & (df["open"] > 0) & (df["money"] > 0)]
    return df.sort_values(["code", "date"])


def main():
    daily = load_daily()
    all_days = sorted(daily["date"].unique())
    day_idx = {d: i for i, d in enumerate(all_days)}

    print("建置交易明細(20%/15%門檻)...")
    for threshold, label in [(0.20, "20%"), (0.15, "15%")]:
        trades, baskets = M.build_trades(threshold)
        weeks = M.WIDE_RET.index
        start_i = weeks.searchsorted(pd.Timestamp(M.START))
        grid = weeks[start_i:]

        # 找每個entry_week(週五)後的下一個交易日
        next_day_of = {}
        for wk in trades["entry_week"].unique():
            wk = pd.Timestamp(wk)
            future = [d for d in all_days if d > wk]
            next_day_of[wk] = future[0] if future else None

        # 逐檔查下一交易日開盤價
        daily_idx = daily.set_index(["code", "date"])
        entry_open_px, week_close_px = [], []
        for _, r in trades.iterrows():
            nd = next_day_of.get(pd.Timestamp(r["entry_week"]))
            code = r["code"]
            try:
                op = daily_idx.loc[(code, nd), "open"] if nd is not None else np.nan
            except KeyError:
                op = np.nan
            # 訊號週自己收盤價(還原用,從WIDE_C查)
            wc = M.WIDE_C.loc[r["entry_week"], code] if code in M.WIDE_C.columns else np.nan
            entry_open_px.append(op)
            week_close_px.append(wc)
        trades = trades.copy()
        trades["next_open"] = entry_open_px
        trades["week_close"] = week_close_px
        trades["gap_pct"] = trades["next_open"] / trades["week_close"] - 1  # 開盤跳空幅度

        # 出場價維持原設計(次週五收盤),用WIDE_C查
        exit_close = []
        for _, r in trades.iterrows():
            code = r["code"]
            ew = r["exit_week"]
            try:
                ec = M.WIDE_C.loc[ew, code] if code in M.WIDE_C.columns else np.nan
            except KeyError:
                ec = np.nan
            exit_close.append(ec)
        trades["exit_close"] = exit_close

        valid = trades.dropna(subset=["next_open", "exit_close"]).copy()
        n_dropped = len(trades) - len(valid)
        valid["net_ret_realistic"] = valid["exit_close"] / valid["next_open"] - 1 - M.COST

        print(f"\n{'='*90}\n### 門檻={label}: 原始版(訊號週收盤進場) vs 可執行版(次交易日開盤進場) ###")
        print(f"總交易數={len(trades)}, 缺開盤價無法校正筆數={n_dropped}"
              f"({n_dropped/len(trades)*100:.1f}%,多為停牌/上市未滿一年等邊緣情況,校正版樣本略縮水)")
        print(f"平均跳空幅度(次日開盤/訊號週收盤-1): 中位數={valid['gap_pct'].median()*100:+.2f}%  "
              f"均值={valid['gap_pct'].mean()*100:+.2f}%  "
              f"[10%,90%分位]=[{valid['gap_pct'].quantile(.1)*100:+.2f}%,{valid['gap_pct'].quantile(.9)*100:+.2f}%]")

        # 用可執行版net_ret重建weekly_baskets做portfolio_curve
        valid["net_ret"] = valid["net_ret_realistic"]
        new_baskets = {}
        for wk, g in valid.groupby("entry_week"):
            new_baskets[wk] = g.sort_values("entry_ret", ascending=False).reset_index(drop=True)

        ret_orig, exec_orig = M.portfolio_curve(baskets, grid, mode="baseline", weighting="equal")
        ret_real, exec_real = M.portfolio_curve(new_baskets, grid, mode="baseline", weighting="equal")
        st_o, st_r = M.stats_from_ret(ret_orig), M.stats_from_ret(ret_real)
        tr_o, tr_r = M.trade_stats(exec_orig), M.trade_stats(exec_real)
        ci_o, ci_r = M.bootstrap_ci(exec_orig), M.bootstrap_ci(exec_real)

        print(f"\n{'版本':<20}{'複利':>9}{'年化':>8}{'MDD':>9}{'夏普':>7}{'Calmar':>8}"
              f"{'PF':>6}{'勝率':>7}{'單筆均(CI)':>26}")
        for name, st, tr, ci in [("原始(訊號週收盤)", st_o, tr_o, ci_o),
                                  ("可執行版(次日開盤)", st_r, tr_r, ci_r)]:
            print(f"{name:<20}{st['mult']:>8.2f}x{st['cagr']:>7.1f}%{st['mdd']:>8.1f}%"
                  f"{st['sharpe']:>7.2f}{st['calmar']:>8.2f}{tr['pf']:>6.2f}{tr['win']:>6.1f}%"
                  f"  {tr['mean']:+.2f}%[{ci[0]:+.2f},{ci[1]:+.2f}]")

        decay = (st_o['mult'] - st_r['mult']) / st_o['mult'] * 100 if st_o['mult'] > 0 else np.nan
        print(f"\n報酬侵蝕: 複利倍數縮水{decay:.1f}%({st_o['mult']:.1f}x -> {st_r['mult']:.1f}x)")


if __name__ == "__main__":
    main()
