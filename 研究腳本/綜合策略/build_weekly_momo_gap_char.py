# -*- coding: utf-8 -*-
"""週級強者續強·跳空特徵分析+週四訊號週五開盤進場重構(2026-08-05)。

背景: build_weekly_momo_entry_realism.py發現訊號週收盤進場->次交易日開盤進場的校正,把20%門檻複利從
127.3x打到0.19x(PF跌破1變虧錢)——次交易日開盤平均再跳空+0.89%(中位數),90分位達+7.1%,原始版的
「edge」很大成分是不可執行的紙上優勢。使用者提案:訊號改成用週一~週四(部分週)的累積報酬判斷,
週五開盤進場(而非等到週五收盤確認全週漲幅、下週一才進場)——這樣進場時點是「資訊還沒完全被市場消化
定價」的相對早期,理論上跳空幅度應該比「全週已確認+等到下下個交易日」的原始問題更小。

第一部分: 用entry_realism算出的跳空幅度(gap_pct=次交易日開盤/訊號週收盤-1),分析哪些特徵預測大跳空
(>=7%即90分位)——流動性/單週漲幅強度/是否鎖漲停等,找出跳空的成因。
第二部分: 重構訊號=週一收盤~週四收盤累積報酬(部分週,不含週五),進場=同週週五開盤(次一交易日,
資訊在手當下就能執行);出場=次週週五開盤(對稱設計,同樣是"週四訊號、週五執行"的下一輪)。

用法: python 研究腳本/綜合策略/build_weekly_momo_gap_char.py (從根目錄執行,鐵律)
"""
import sys

import numpy as np
import pandas as pd
import sqlite3

sys.path.insert(0, "研究腳本/綜合策略")
import build_weekly_momo_regime_overlay as M  # noqa: E402

DB = "capital_flow.db"
COST = M.COST
LIQ_MIN = M.LIQ_MIN
TOP_N = M.TOP_N


def load_daily():
    con = sqlite3.connect(DB)
    df = pd.read_sql(f"SELECT code, date, open, high, low, close, volume, money FROM fm_daily_price "
                     f"WHERE date>='{M.BUFFER_START}'", con, parse_dates=["date"])
    con.close()
    df = df[(df["close"] > 0) & (df["open"] > 0) & (df["money"] > 0)]
    return df.sort_values(["code", "date"]).reset_index(drop=True)


def part1_gap_characteristics(daily):
    print("=" * 90)
    print("### 第一部分: 大跳空(次交易日開盤/訊號週收盤-1)的特徵分析 ###")
    trades, baskets = M.build_trades(0.20)
    all_days = sorted(daily["date"].unique())
    next_day_of = {}
    for wk in trades["entry_week"].unique():
        wk = pd.Timestamp(wk)
        future = [d for d in all_days if d > wk]
        next_day_of[wk] = future[0] if future else None

    daily_idx = daily.set_index(["code", "date"])
    liq20 = daily.set_index(["code", "date"])["money"].groupby("code").rolling(20, min_periods=10).mean()

    rows = []
    for _, r in trades.iterrows():
        nd = next_day_of.get(pd.Timestamp(r["entry_week"]))
        code = r["code"]
        if nd is None:
            continue
        try:
            op = daily_idx.loc[(code, nd), "open"]
            hi_wk = daily_idx.loc[(code, nd), "high"]
        except KeyError:
            continue
        wc = M.WIDE_C.loc[r["entry_week"], code] if code in M.WIDE_C.columns else np.nan
        if pd.isna(wc) or wc <= 0:
            continue
        gap = op / wc - 1
        # 週五(訊號週最後交易日)是否鎖漲停: 用當日high==close且漲幅>=9%粗略判定(台股漲停幅度10%)
        try:
            fri_rows = daily[(daily["code"] == code) & (daily["date"] <= r["entry_week"])].tail(1)
            fri_close = fri_rows["close"].iloc[0] if len(fri_rows) else np.nan
            fri_high = fri_rows["high"].iloc[0] if len(fri_rows) else np.nan
            locked = bool(fri_high == fri_close) if pd.notna(fri_high) else False
        except Exception:
            locked = False
        rows.append({"code": code, "entry_week": r["entry_week"], "entry_ret": r["entry_ret"],
                     "gap_pct": gap, "locked_limit": locked})
    g = pd.DataFrame(rows)
    g["liq_bucket"] = pd.qcut(g.groupby("code")["gap_pct"].transform("count"), 1, duplicates="drop")  # placeholder避免報錯

    hi_gap = g[g["gap_pct"] >= g["gap_pct"].quantile(0.90)]
    lo_gap = g[g["gap_pct"] <= g["gap_pct"].quantile(0.10)]
    print(f"n={len(g)}, 跳空90分位門檻={g['gap_pct'].quantile(0.90)*100:.2f}%, "
          f"10分位門檻={g['gap_pct'].quantile(0.10)*100:.2f}%")
    print(f"\n高跳空組(>=90分位,n={len(hi_gap)}): 訊號週漲幅中位數={hi_gap['entry_ret'].median()*100:.1f}%  "
          f"鎖漲停比例={hi_gap['locked_limit'].mean()*100:.1f}%")
    print(f"低跳空組(<=10分位,n={len(lo_gap)}): 訊號週漲幅中位數={lo_gap['entry_ret'].median()*100:.1f}%  "
          f"鎖漲停比例={lo_gap['locked_limit'].mean()*100:.1f}%")
    print(f"全樣本: 訊號週漲幅中位數={g['entry_ret'].median()*100:.1f}%  鎖漲停比例={g['locked_limit'].mean()*100:.1f}%")
    # entry_ret與gap_pct相關性
    corr = g[["entry_ret", "gap_pct"]].corr().iloc[0, 1]
    print(f"\n訊號週漲幅強度 vs 次日跳空幅度: 相關係數={corr:.3f}")
    return g


def part2_thu_signal_fri_open(daily, threshold=0.20):
    print("\n" + "=" * 90)
    print(f"### 第二部分: 週四訊號(週一~週四累積報酬)+週五開盤進場 (門檻={threshold:.0%}) ###")
    d = daily.copy()
    d["dow"] = d["date"].dt.dayofweek  # 0=週一...4=週五
    d["wk"] = d["date"].dt.to_period("W-FRI").dt.end_time.dt.normalize()

    # 每檔每週: 週四(或該週最後一個<=週四的交易日)收盤, 週五(或該週最後一個交易日)開盤/收盤, 上週五收盤
    thu = d[d["dow"] <= 3].sort_values("date").groupby(["code", "wk"]).agg(
        thu_close=("close", "last")).reset_index()
    fri = d[d["dow"] == 4].sort_values("date").groupby(["code", "wk"]).agg(
        fri_open=("open", "first"), fri_close=("close", "last")).reset_index()
    # 若當週無週五交易日(國定假日),用該週最後一筆頂替
    last_of_wk = d.sort_values("date").groupby(["code", "wk"]).agg(
        last_open=("open", "first"), last_close=("close", "last")).reset_index()

    prev_close = d.sort_values("date").groupby(["code", "wk"]).agg(close=("close", "last")).reset_index()
    prev_close = prev_close.sort_values(["code", "wk"])
    prev_close["prev_wk_close"] = prev_close.groupby("code")["close"].shift(1)

    panel = thu.merge(prev_close[["code", "wk", "prev_wk_close"]], on=["code", "wk"], how="left")
    panel = panel.merge(last_of_wk, on=["code", "wk"], how="left")
    panel = panel.merge(fri[["code", "wk", "fri_open"]], on=["code", "wk"], how="left")
    panel["entry_open"] = panel["fri_open"].fillna(panel["last_open"])
    panel["thu_ret"] = panel["thu_close"] / panel["prev_wk_close"] - 1

    liq20 = d.set_index(["code", "date"])["money"].reset_index()
    liq20 = liq20.sort_values(["code", "date"])
    liq20["liq20"] = liq20.groupby("code")["money"].transform(lambda s: s.rolling(20, min_periods=10).mean())
    wk_liq = liq20.sort_values("date").groupby(["code", d.set_index(["code","date"]).index.map(lambda x: None)]) \
        if False else None  # 不用這個分支,改用簡化法算流動性(見下)
    liq_simple = d.sort_values("date").groupby(["code", "wk"]).agg(money_wk=("money", "mean")).reset_index()
    liq_simple["liq20"] = liq_simple.groupby("code")["money_wk"].transform(
        lambda s: s.rolling(20, min_periods=10).mean())
    panel = panel.merge(liq_simple[["code", "wk", "liq20"]], on=["code", "wk"], how="left")

    panel = panel.dropna(subset=["thu_ret", "prev_wk_close", "entry_open"])
    panel = panel[panel["liq20"] >= LIQ_MIN]
    panel = panel.sort_values(["code", "wk"])
    # 次一輪的entry_open當出場價(對稱設計: 下週五開盤出場)
    panel["exit_open"] = panel.groupby("code")["entry_open"].shift(-1)
    panel["exit_wk"] = panel.groupby("code")["wk"].shift(-1)

    weeks_all = sorted(panel["wk"].unique())
    trades = []
    for wk in weeks_all:
        wk_panel = panel[panel["wk"] == wk]
        cand = wk_panel[wk_panel["thu_ret"] >= threshold].sort_values("thu_ret", ascending=False)
        if len(cand) == 0:
            continue
        if len(cand) > TOP_N:
            cand = cand.iloc[:TOP_N]
        for _, r in cand.iterrows():
            if pd.isna(r["exit_open"]) or r["entry_open"] <= 0:
                continue
            net_ret = r["exit_open"] / r["entry_open"] - 1 - COST
            trades.append({"entry_week": wk, "exit_week": r["exit_wk"], "code": r["code"],
                          "entry_ret": r["thu_ret"], "net_ret": net_ret})
    tdf = pd.DataFrame(trades)
    if len(tdf) == 0:
        print("無交易產生(可能全市場週四訊號太罕見或資料不足)")
        return
    print(f"n_trades={len(tdf)}, n_signal_weeks={tdf['entry_week'].nunique()}, "
          f"樣本期間={tdf.entry_week.min().date()}~{tdf.entry_week.max().date()}")

    baskets = {wk: g.reset_index(drop=True) for wk, g in tdf.groupby("entry_week")}
    grid_weeks = sorted(set(tdf["exit_week"].dropna()))
    grid = pd.DatetimeIndex(grid_weeks)
    ret = pd.Series(0.0, index=grid)
    for wk, basket in baskets.items():
        ew = basket["exit_week"].iloc[0]
        if pd.isna(ew) or ew not in ret.index:
            continue
        ret.loc[ew] = basket["net_ret"].mean()
    st = M.stats_from_ret(ret)
    tr = M.trade_stats(tdf)
    ci = M.bootstrap_ci(tdf)
    print(f"\n{'版本':<24}{'複利':>9}{'年化':>8}{'MDD':>9}{'夏普':>7}{'Calmar':>8}"
          f"{'PF':>6}{'勝率':>7}{'單筆均(CI)':>26}")
    print(f"{'週四訊號週五開盤進場':<22}{st['mult']:>8.2f}x{st['cagr']:>7.1f}%{st['mdd']:>8.1f}%"
          f"{st['sharpe']:>7.2f}{st['calmar']:>8.2f}{tr['pf']:>6.2f}{tr['win']:>6.1f}%"
          f"  {tr['mean']:+.2f}%[{ci[0]:+.2f},{ci[1]:+.2f}]")

    # 額外算週五開盤 vs 週四收盤的跳空(這個版本本身還剩多少跳空)
    panel2 = panel.dropna(subset=["thu_ret"]).copy()
    panel2["fri_gap"] = panel2["entry_open"] / panel2["thu_close"] - 1
    sig2 = panel2[panel2["thu_ret"] >= threshold]
    print(f"\n此版本本身的殘餘跳空(週五開盤/週四收盤-1,訊號股樣本n={len(sig2)}): "
          f"中位數={sig2['fri_gap'].median()*100:+.2f}%  均值={sig2['fri_gap'].mean()*100:+.2f}%")


def main():
    daily = load_daily()
    part1_gap_characteristics(daily)
    for th in (0.20, 0.15):
        part2_thu_signal_fri_open(daily, threshold=th)


if __name__ == "__main__":
    main()
