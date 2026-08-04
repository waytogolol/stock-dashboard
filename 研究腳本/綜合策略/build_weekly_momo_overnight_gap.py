# -*- coding: utf-8 -*-
"""週級強者續強·隔夜缺口版(隔日沖型態)測試(2026-08-05,使用者洞察)。

使用者推理: entry_realism考卷發現「訊號週收盤進場」127.3x vs「次日開盤進場」0.19x,兩者的差=
週五收盤→下一交易日開盤的隔夜跳空(中位+0.89%/均值+1.43%)——整條策略的肉集中在那個隔夜缺口,
後面持有一整週反而虧。那反過來「只吃缺口」:週五收盤(收盤前尾盤判斷訊號+掛單進場)買進,下一交易日
開盤就出場——隔日沖型態,觀察4-5天資料,收盤持有隔天出場。
這正是專案backlog記載的「隔夜vs盤中報酬拆解(overnight/intraday decomposition)」的具體應用。

可執行性誠實聲明(本卷務必如實揭露的三個現實摩擦):
①訊號在收盤前最後一盤(13:25-13:30試撮)才最終確定,尾盤買進的前提=13:00~13:25盤中預判當週累積漲幅
  達標並掛單進試撮——絕大多數情況13:00時累積漲幅已離門檻很遠(達標與否幾乎確定),此假設比「精準買在
  收盤價」務實得多,但仍有邊緣案例(最後半小時才衝過門檻/跌出門檻)會造成執行誤差,本卷用收盤價近似。
②漲停鎖死的股票尾盤買不到(買單排隊),本卷提供「排除訊號日收盤=漲停」的過濾版當可執行主口徑。
  漲停判定=當日close>=前日close*1.095(台股10%漲停留餘裕)。
③成本:隔日沖持有<1天,來回成本佔比極高。本卷用與系列一致的0.5%單邊×1次=0.5%總成本當基準,另附
  0.8%敏感度(現實當沖/隔日沖稅費若無當沖稅減半優惠,來回約0.585%+滑價)。

用法: python 研究腳本/綜合策略/build_weekly_momo_overnight_gap.py (從根目錄執行,鐵律)
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
    df = pd.read_sql(f"SELECT code, date, open, close FROM fm_daily_price WHERE date>='{M.BUFFER_START}'",
                      con, parse_dates=["date"])
    con.close()
    df = df[(df["close"] > 0) & (df["open"] > 0)]
    return df.sort_values(["code", "date"]).reset_index(drop=True)


def run(threshold, label, daily, cost, exclude_limit_lock):
    trades, baskets = M.build_trades(threshold)
    all_days = sorted(daily["date"].unique())
    daily_idx = daily.set_index(["code", "date"])

    # 前日收盤(判斷漲停用)
    daily_sorted = daily.sort_values(["code", "date"])
    daily_sorted["prev_close"] = daily_sorted.groupby("code")["close"].shift(1)
    prev_idx = daily_sorted.set_index(["code", "date"])["prev_close"]

    next_day_of = {}
    for wk in trades["entry_week"].unique():
        wk = pd.Timestamp(wk)
        future = [d for d in all_days if d > wk]
        next_day_of[wk] = future[0] if future else None

    rows = []
    n_limit_locked = 0
    for _, r in trades.iterrows():
        code = r["code"]
        wk = pd.Timestamp(r["entry_week"])
        nd = next_day_of.get(wk)
        if nd is None:
            continue
        wc = M.WIDE_C.loc[r["entry_week"], code] if code in M.WIDE_C.columns else np.nan
        if pd.isna(wc) or wc <= 0:
            continue
        # 訊號日(訊號週最後交易日)是否漲停鎖死: close>=prev_close*1.095
        if exclude_limit_lock:
            # 找訊號週最後一個實際交易日
            sub = daily[(daily["code"] == code) & (daily["date"] <= wk)]
            if len(sub) == 0:
                continue
            last_row = sub.iloc[-1]
            pc = prev_idx.get((code, last_row["date"]), np.nan)
            if pd.notna(pc) and pc > 0 and last_row["close"] >= pc * 1.095:
                n_limit_locked += 1
                continue
        try:
            op = daily_idx.loc[(code, nd), "open"]
        except KeyError:
            continue
        net = op / wc - 1 - cost
        rows.append({"entry_week": wk, "exit_week": nd, "code": code,
                     "entry_ret": r["entry_ret"], "net_ret": net})
    tdf = pd.DataFrame(rows)
    if len(tdf) == 0:
        print(f"  [{label}] 無交易")
        return

    # 週級組合: 每個entry_week一個basket,等權,報酬記在出場日
    ret_by_week = tdf.groupby("entry_week")["net_ret"].mean().sort_index()
    eq = (1 + ret_by_week).cumprod()
    yrs = (ret_by_week.index[-1] - ret_by_week.index[0]).days / 365.25
    mult = float(eq.iloc[-1])
    cagr = (mult ** (1 / yrs) - 1) * 100 if mult > 0 else np.nan
    dd = eq / eq.cummax() - 1
    mdd = float(dd.min() * 100)
    vol = ret_by_week.std() * np.sqrt(52)
    sharpe = (ret_by_week.mean() * 52) / vol if vol > 0 else np.nan
    calmar = cagr / abs(mdd) if mdd < 0 else np.nan
    tr = M.trade_stats(tdf)
    ci = M.bootstrap_ci(tdf)
    sig = "✓排0" if (ci[0] > 0 or ci[1] < 0) else "含0"

    lock_note = f" 排除漲停鎖死{n_limit_locked}筆" if exclude_limit_lock else ""
    print(f"  [{label}]{lock_note}")
    print(f"    n={len(tdf)} 週數={tdf['entry_week'].nunique()}  複利={mult:.2f}x 年化={cagr:+.1f}% "
          f"MDD={mdd:.1f}% 夏普={sharpe:.2f} Calmar={calmar:.2f}")
    print(f"    勝率={tr['win']:.1f}% PF={tr['pf']:.2f} 單筆均={tr['mean']:+.2f}% "
          f"單筆中位={tr['median']:+.2f}% CI[{ci[0]:+.2f},{ci[1]:+.2f}] {sig}")
    yearly = tdf.set_index("entry_week").groupby(pd.Grouper(freq="YE"))["net_ret"].mean() * 100
    pos_years = int((yearly.dropna() > 0).sum())
    print(f"    逐年單筆均正年數: {pos_years}/{yearly.dropna().shape[0]}  "
          f"({ {y.year: round(v,2) for y,v in yearly.dropna().items()} })")


def main():
    daily = load_daily()
    for threshold, tl in [(0.20, "20%"), (0.15, "15%")]:
        print(f"\n{'='*95}\n### 門檻={tl}: 隔夜缺口版(訊號週收盤買進→次交易日開盤出場,隔日沖型態) ###")
        for cost, cl in [(0.005, "成本0.5%"), (0.008, "成本0.8%敏感度")]:
            run(threshold, f"{cl}·含漲停鎖死(理想化上限)", daily, cost, exclude_limit_lock=False)
            run(threshold, f"{cl}·排除漲停鎖死(可執行主口徑)", daily, cost, exclude_limit_lock=True)


if __name__ == "__main__":
    main()
