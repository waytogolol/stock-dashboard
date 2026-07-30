# -*- coding: utf-8 -*-
"""大盤融資維持率(B估計版)×大盤位階：管線+三假說判決(設計預註冊於2026-07-14,使用者核准開工)。

資料:
  - FinMind TaiwanStockTotalMarginPurchaseShortSale(免費層):全市場融資金額餘額M_t,2001起(上市)
  - TAIEX(^TWII)日線當融資擔保市值形狀proxy

估計器(玩股網式,自建):
  V_t = V_{t-1}×(P_t/P_{t-1}) + max(ΔM,0)/0.6 + min(ΔM,0)×(V_{t-1}/M_{t-1})
  維持率_t = V_t/M_t×100 ; V_0=M_0/0.6(=166.7%起始,burn-in一年後才進樣本)
  已知限制:融資族群≠TAIEX成分(散戶偏中小型),絕對水準有proxy誤差,位階版較可靠。

三假說(單一參數組,不掃參數):
  H0 機械同期sanity:維持率分子=市值,同期相關高是恆等式,只驗管線不算發現
  H1 急降→回檔低點:事件=240日位階首次≤20且前60日內曾≥80(去重60日);另絕對版跌破150/140
     判準=事件後5/10/20/60日TAIEX報酬 vs 全樣本無條件drift
  H2 高檔鈍化:位階≥80連續≥20日的狀態日,前瞻20/60日報酬與波動 vs 其他日
用法: python build_margin_maintenance.py  (快取tmp_margin_total.pkl/tmp_twii_long.pkl)
"""
import os
import pickle
import time

import pandas as pd
import requests

CACHE_M = "tmp_margin_total.pkl"
CACHE_P = "tmp_twii_long.pkl"


def fetch_margin_total():
    if os.path.exists(CACHE_M):
        return pd.read_pickle(CACHE_M)
    token = open("finmind_token.txt").read().strip()
    frames = []
    for y0 in range(2001, 2027, 3):
        for attempt in range(3):
            try:
                r = requests.get("https://api.finmindtrade.com/api/v4/data",
                                 params={"dataset": "TaiwanStockTotalMarginPurchaseShortSale",
                                         "start_date": f"{y0}-01-01", "end_date": f"{y0 + 2}-12-31",
                                         "token": token}, timeout=60)
                df = pd.DataFrame(r.json().get("data", []))
                if len(df):
                    frames.append(df)
                print(f"  {y0}-{y0 + 2}: {len(df)}筆")
                break
            except Exception as e:
                print(f"  {y0} retry {attempt}: {e}")
                time.sleep(5)
    out = pd.concat(frames).drop_duplicates(subset=["date", "name"])
    out.to_pickle(CACHE_M)
    return out


def fetch_twii():
    if os.path.exists(CACHE_P):
        return pd.read_pickle(CACHE_P)
    import yfinance as yf
    px = yf.download("^TWII", start="2000-06-01", auto_adjust=True, progress=False)["Close"]
    if hasattr(px, "columns"):
        px = px.iloc[:, 0]
    px.to_pickle(CACHE_P)
    return px


def fwd_ret(px, days):
    return (px.shift(-days) / px - 1) * 100


def main():
    raw = fetch_margin_total()
    m = raw[raw["name"] == "MarginPurchaseMoney"].copy()
    m["date"] = pd.to_datetime(m["date"])
    m = m.set_index("date").sort_index()["TodayBalance"].astype(float)
    px = fetch_twii()
    px.index = pd.to_datetime(px.index).tz_localize(None)
    df = pd.DataFrame({"M": m}).join(px.rename("P"), how="inner").dropna()
    print(f"合併樣本: {len(df)}日 {df.index.min().date()}~{df.index.max().date()} "
          f"融資金額最新{df.M.iloc[-1] / 1e8:.0f}億")

    # ---- 估計器 ----
    V = [df.M.iloc[0] / 0.6]
    for i in range(1, len(df)):
        r = df.P.iloc[i] / df.P.iloc[i - 1]
        dM = df.M.iloc[i] - df.M.iloc[i - 1]
        v = V[-1] * r
        if dM > 0:
            v += dM / 0.6
        else:
            v += dM * (V[-1] / df.M.iloc[i - 1])
        V.append(v)
    df["mm"] = pd.Series(V, index=df.index) / df.M * 100
    df = df.iloc[250:]  # burn-in一年
    print(f"維持率estimate: 全期中位{df.mm.median():.1f}% 最低{df.mm.min():.1f}%"
          f"({df.mm.idxmin().date()}) 最高{df.mm.max():.1f}%({df.mm.idxmax().date()}) 最新{df.mm.iloc[-1]:.1f}%")
    # 錨點sanity:歷史急殺日的估計值(公開報導維持率殺到130-150區間的日子)
    for d in ["2008-11-20", "2015-08-24", "2020-03-19", "2022-10-25", "2024-08-05", "2025-04-09"]:
        sub = df.mm[df.index <= d]
        if len(sub):
            print(f"  錨點{d}: {sub.iloc[-1]:.1f}%")

    df["pos"] = df.mm.rolling(240).rank(pct=True) * 100
    for k in (5, 10, 20, 60):
        df[f"f{k}"] = fwd_ret(df.P, k)

    print("\n===== H0 機械同期(sanity,不算發現) =====")
    print(f"維持率 vs TAIEX 水準同期r={df.mm.corr(df.P):.3f}; "
          f"日變化同期r={df.mm.diff().corr(df.P.pct_change()):.3f} (預期高=恆等式)")

    base = {k: (df[f"f{k}"].median(), df[f"f{k}"].mean(), (df[f"f{k}"] > 0).mean() * 100)
            for k in (5, 10, 20, 60)}
    print("\n無條件基準(全樣本drift): " + "  ".join(
        f"{k}日中位{base[k][0]:+.2f}%/勝率{base[k][2]:.0f}%" for k in (5, 10, 20, 60)))

    print("\n===== H1 急降→回檔低點(事件研究) =====")
    hi60 = df.pos.rolling(60).max().shift(1)
    ev = df.index[(df.pos <= 20) & (hi60 >= 80)]
    events = []
    for d in ev:
        if not events or (df.index.get_loc(d) - df.index.get_loc(events[-1])) > 60:
            events.append(d)
    print(f"位階版(80→20,去重60日): {len(events)}個事件")
    for d in events:
        row = df.loc[d]
        print(f"  {d.date()} 維持率{row.mm:.0f}% | " + "  ".join(
            f"{k}日{row[f'f{k}']:+.1f}%" if pd.notna(row[f"f{k}"]) else f"{k}日—" for k in (5, 10, 20, 60)))
    for k in (5, 10, 20, 60):
        vals = df.loc[events, f"f{k}"].dropna()
        if len(vals):
            print(f"  彙總{k}日: 中位{vals.median():+.2f}% 均{vals.mean():+.2f}% "
                  f"勝率{(vals > 0).mean() * 100:.0f}% (基準中位{base[k][0]:+.2f}%)")
    for th in (150, 140):
        below = df.mm < th
        evs = []
        for d in df.index[below]:
            if not evs or (df.index.get_loc(d) - df.index.get_loc(evs[-1])) > 120:
                evs.append(d)
        print(f"絕對版(<{th}%,去重120日): {len(evs)}個事件")
        for k in (20, 60):
            vals = df.loc[evs, f"f{k}"].dropna()
            if len(vals):
                print(f"  {k}日: 中位{vals.median():+.2f}% 勝率{(vals > 0).mean() * 100:.0f}% "
                      f"n={len(vals)} (基準{base[k][0]:+.2f}%)")

    print("\n===== H2 高檔鈍化(位階≥80連續≥20日的狀態日) =====")
    hot = df.pos >= 80
    streak = hot.groupby((~hot).cumsum()).cumcount() + 1
    state = hot & (streak >= 20)
    print(f"狀態日: {state.sum()}日({state.mean() * 100:.1f}%樣本)")
    for k in (20, 60):
        a, b = df.loc[state, f"f{k}"].dropna(), df.loc[~state, f"f{k}"].dropna()
        va = df.P.pct_change().rolling(k).std().shift(-k) * 100
        print(f"  {k}日前瞻: 鈍化日中位{a.median():+.2f}%/勝率{(a > 0).mean() * 100:.0f}% vs "
              f"其他日{b.median():+.2f}%/{(b > 0).mean() * 100:.0f}% | "
              f"未來{k}日日波動 鈍化{va[state].median():.2f}% vs 其他{va[~state].median():.2f}%")
    # 逐年狀態占比(看鈍化集中在哪些年)
    yr = state.groupby(df.index.year).mean() * 100
    print("  鈍化日占比逐年: " + "  ".join(f"{y}:{v:.0f}%" for y, v in yr.items() if v > 0))

    df[["mm", "pos"]].to_pickle("tmp_margin_maintenance.pkl")
    print("\n已存 tmp_margin_maintenance.pkl (維持率estimate+240日位階)")


if __name__ == "__main__":
    main()
