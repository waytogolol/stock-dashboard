# -*- coding: utf-8 -*-
"""恐慌流動性研究線收斂: 甜蜜格+處置V4的組合模擬+cluster bootstrap(報告前定稿數字)
- 組合模擬(口徑同⑫慣例): 逐日展開,同日多部位等權,無部位日=空手;複利/夏普(252年化)/MDD/
  曝險率;單利對照=每筆固定1單位Σ
- bootstrap: 月份群抽樣B=10000,seed=42,單筆淨中位CI
產出: tmp_panic_converge_results.pkl (報告產生器讀取)
用法: python build_panic_liquidity_converge.py
"""
import pickle
import sqlite3

import numpy as np
import pandas as pd

COST = 0.45
B = 10000


def load_px():
    conn = sqlite3.connect("capital_flow.db")
    px = pd.read_sql("SELECT code, date, open, close, money FROM fm_daily_price ORDER BY code, date", conn)
    disp = pd.read_sql("SELECT * FROM disposition", conn)
    conn.close()
    px["date"] = pd.to_datetime(px.date)
    for c in ("start_date", "end_date"):
        disp[c] = pd.to_datetime(disp[c], errors="coerce")
    return {c: g.sort_values("date").reset_index(drop=True) for c, g in px.groupby("code")}, \
        disp.dropna(subset=["start_date", "end_date"])


def sweetspot_trades(stocks):
    """甜蜜格: 近40日漲20%×回檔>=20%×當日跌(-9,-6]×成交值>1億, T收進T+2開出"""
    trades = []
    for code, g in stocks.items():
        c, o = g.close, g.open
        tv = g.money / 1e8
        c1 = c.shift(1)
        dd = 100 * (c / c1 - 1)
        pull = 100 * (1 - c / c.rolling(10).max())
        rr = c.rolling(15).max() / c.rolling(40).min()
        sig = (dd <= -6) & (dd > -9) & (pull >= 20) & (rr > 1.2) & (tv > 1)
        for i in np.where(sig.fillna(False))[0]:
            if i + 2 >= len(g) or not (c[i] > 0 and o[i + 2] > 0 and c[i + 1] > 0):
                continue
            legs = [(g.date[i + 1], c[i + 1] / c[i] - 1),
                    (g.date[i + 2], o[i + 2] / c[i + 1] - 1)]
            trades.append({"code": code, "d0": g.date[i], "legs": legs,
                           "net": (o[i + 2] / c[i] - 1) * 100 - COST})
    return trades


def disposition_trades(stocks, disp):
    """處置V4: 第3處置日尾盤買→出關日開盤出"""
    trades = []
    for _, e in disp.iterrows():
        g = stocks.get(e.code)
        if g is None:
            continue
        dts = g.date
        s = np.searchsorted(dts.values, np.datetime64(e.start_date))
        en = np.searchsorted(dts.values, np.datetime64(e.end_date), side="right") - 1
        if s >= len(g) or en <= s or en - s > 25 or en - s < 6:
            continue
        c_, o_ = g.close.values, g.open.values
        i3 = s + 2
        if en + 1 >= len(g) or not (c_[i3] > 0 and o_[en + 1] > 0):
            continue
        legs = []
        ok = True
        for j in range(i3 + 1, en + 1):
            if c_[j] <= 0 or c_[j - 1] <= 0:
                ok = False
                break
            legs.append((dts[j], c_[j] / c_[j - 1] - 1))
        if not ok:
            continue
        legs.append((dts[en + 1], o_[en + 1] / c_[en] - 1))
        trades.append({"code": e.code, "d0": dts[i3], "legs": legs,
                       "net": (o_[en + 1] / c_[i3] - 1) * 100 - COST})
    return trades


def portfolio(trades, twii):
    daily = {}
    for t in trades:
        nlegs = len(t["legs"])
        cost_per_leg = COST / 100 / nlegs  # 成本攤入各腿
        for d, r in t["legs"]:
            daily.setdefault(d, []).append(r - cost_per_leg)
    days = sorted(daily)
    ser = pd.Series({d: np.mean(daily[d]) for d in days})
    cal = twii.index[(twii.index >= ser.index.min()) & (twii.index <= ser.index.max())]
    ser = ser.reindex(cal).fillna(0.0)
    eq = (1 + ser).cumprod()
    peak = eq.cummax()
    mdd = ((eq / peak) - 1).min() * 100
    sharpe = ser.mean() / ser.std() * np.sqrt(252) if ser.std() > 0 else np.nan
    nets = pd.Series([t["net"] for t in trades])
    return {"equity": eq, "sharpe": sharpe, "mdd": mdd,
            "exposure": (ser != 0).mean() * 100, "compound": eq.iloc[-1],
            "simple_sum": nets.sum(), "n": len(trades),
            "median": nets.median(), "win": (nets > 0).mean() * 100, "mean": nets.mean()}


def boot_ci(trades, seed=42):
    df = pd.DataFrame({"m": [t["d0"].strftime("%Y-%m") for t in trades],
                       "net": [t["net"] for t in trades]})
    months = df.m.unique()
    groups = {m: df[df.m == m].net.values for m in months}
    rng = np.random.default_rng(seed)
    meds = []
    for _ in range(B):
        pick = rng.choice(months, size=len(months), replace=True)
        pool = np.concatenate([groups[m] for m in pick])
        meds.append(np.median(pool))
    meds = np.array(meds)
    return np.percentile(meds, 2.5), np.percentile(meds, 97.5), (meds <= 0).mean()


def main():
    stocks, disp = load_px()
    twii = pd.read_pickle("tmp_twii_long.pkl").dropna()
    out = {}
    for name, trades in [("sweetspot", sweetspot_trades(stocks)),
                         ("dispo_v4", disposition_trades(stocks, disp))]:
        p = portfolio(trades, twii)
        lo, hi, pval = boot_ci(trades)
        p.update({"ci_lo": lo, "ci_hi": hi, "p": pval})
        out[name] = p
        print(f"== {name} ==")
        print(f"  n={p['n']:,} 單筆淨中位{p['median']:+.2f}% 均{p['mean']:+.2f}% 勝率{p['win']:.0f}%")
        print(f"  月群bootstrap中位CI95=[{lo:+.2f},{hi:+.2f}] P(<=0)={pval:.4f}")
        print(f"  組合: 複利{p['compound']:.2f}x 夏普{p['sharpe']:.2f} MDD{p['mdd']:.1f}% "
              f"曝險{p['exposure']:.0f}% 單利Σ{p['simple_sum']:+.0f}%")
    with open("tmp_panic_converge_results.pkl", "wb") as f:
        pickle.dump(out, f)
    print("\n結果存 tmp_panic_converge_results.pkl")


if __name__ == "__main__":
    main()
