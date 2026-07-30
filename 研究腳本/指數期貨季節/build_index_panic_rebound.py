# -*- coding: utf-8 -*-
"""指數急殺後止跌訊號考卷(2026-07-30,使用者提問「跳空長紅是不是短期止跌訊號?要不要等確認棒?」)。

考卷規格(使用者連續四則訊息定稿):
  急殺定義×3: D1=5日跌≤-5% / D2=10日跌≤-8% / D3=收盤距60日高≤-10%(主表用D_any=聯集)
  訊號×8+2變體:
    引爆型: P1跳空長紅(開盤≥前收+0.5%)/P1s真跳空(開>前高)/P2純長紅無跳空/
            P3連兩長紅(t0=第二根)/P4跳空長紅+次日不破低(t0=次日)
    打底型: P5縮量止跌(量≤急殺峰量一半+5日未創低)/P6橫盤打底(5日不創低+區間≤3%)/
            P7長下影(下影≥實體2倍+收上半部;P7v=爆量版)/P8二次探底不破(第二隻腳)
  分格: 年線上/年線下(熊市誘多=共同死敵,使用者同意分格判)
  判決三軸: 報酬(k5/10/20/60勝率+中位) + 安穩度(MAE20中位與p10尾部) + 等待成本(t0距急殺低點已反彈%)
  case-control: 同樣急殺狀態但無任何訊號的日子=基準(急殺後本來就會技術性反彈,不控全是假發現)
  外部驗證: SPX/N225/KOSPI 同參數跑P1/P4 headline(跨市場成立=市場現象非台股雜訊)
  零前視: 全部訊號收盤可判,進場=t0收盤;bootstrap 2000次;同訊號10日內去重

長紅定義(凍結不調參): 收盤較前收漲≥1.5% 且 收>開 且 實體/振幅≥0.6
"""
import sqlite3
import numpy as np
import pandas as pd

rng = np.random.default_rng(42)
DB = "capital_flow.db"
K_LIST = [5, 10, 20, 60]
DEDUP_GAP = 10   # 同訊號N日內只取第一次
BOOT_N = 2000


def load_index(market):
    con = sqlite3.connect(DB)
    df = pd.read_sql("SELECT date, open, high, low, close, volume FROM index_daily "
                     "WHERE market=? ORDER BY date", con, params=(market,))
    con.close()
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")


def build_features(df):
    c, o, h, l, v = df["close"], df["open"], df["high"], df["low"], df["volume"]
    f = pd.DataFrame(index=df.index)
    f["ret1"] = c.pct_change()
    f["ma240"] = c.rolling(240).mean()
    f["above_ma240"] = c >= f["ma240"]
    # 急殺三定義(收盤基準)
    f["d1"] = c / c.shift(5) - 1 <= -0.05
    f["d2"] = c / c.shift(10) - 1 <= -0.08
    f["d3"] = c / c.rolling(60).max() - 1 <= -0.10
    f["d_any"] = f[["d1", "d2", "d3"]].any(axis=1)
    # 急殺前置:訊號日t的前5日內(含t自身)曾處急殺狀態(反彈當天常已脫離急殺條件)
    f["pre_panic"] = f["d_any"].rolling(6, min_periods=1).max().astype(bool)
    rng_ = (h - l).replace(0, np.nan)
    body = c - o
    f["long_red"] = (c / c.shift(1) - 1 >= 0.015) & (c > o) & (body / rng_ >= 0.6)
    gap_mild = o >= c.shift(1) * 1.005
    gap_true = o > h.shift(1)
    f["p1"] = f["long_red"] & gap_mild
    f["p1s"] = f["long_red"] & gap_true
    f["p2"] = f["long_red"] & ~gap_mild
    f["p3"] = f["long_red"] & f["long_red"].shift(1, fill_value=False)
    # P4: 昨日P1成立且今日低點不破昨低,t0=今日(等一天的便宜確認)
    f["p4"] = f["p1"].shift(1, fill_value=False) & (l > l.shift(1))
    # P5 縮量止跌: 量≤前10日峰量一半 且 低點未創前5日新低
    f["p5"] = (v <= v.shift(1).rolling(10).max() * 0.5) & (l > l.shift(1).rolling(5).min())
    # P6 橫盤打底: 近5日低點都未創前一日低 且 5日收盤區間≤3%
    no_new_low5 = (l > l.shift(1).rolling(10).min()).rolling(5).min().astype(bool)
    box5 = c.rolling(5).max() / c.rolling(5).min() - 1 <= 0.03
    f["p6"] = no_new_low5 & box5
    # P7 長下影: 下影≥實體2倍 且 收在振幅上半部
    lower_sh = (np.minimum(o, c) - l)
    f["p7"] = (lower_sh >= body.abs() * 2) & ((c - l) / rng_ >= 0.5)
    f["p7v"] = f["p7"] & (v >= v.rolling(20).mean() * 1.5)
    # P8 二次探底不破: 前低(t-20~t-6)後曾反彈≥3%,今日回測至前低2%內但未破,收紅
    prior_low = l.shift(6).rolling(15).min()
    rebounded = c.shift(1).rolling(5).max() >= prior_low * 1.03
    f["p8"] = rebounded & (l <= prior_low * 1.02) & (l > prior_low) & (c > o)
    return f


def event_dates(f, col, extra_mask=None):
    m = f[col] & f["pre_panic"]
    if extra_mask is not None:
        m = m & extra_mask
    dates = list(f.index[m])
    out, last = [], None
    for d in dates:
        if last is None or (d - last).days > DEDUP_GAP * 1.6:  # 交易日≈日曆日*1.4,粗放去重
            out.append(d)
            last = d
    return out


def fwd_stats(df, dates, label):
    """t0收盤進場,k日後收盤報酬 + MAE20 + 等待成本(距近20日低點)"""
    c, l = df["close"], df["low"]
    pos = {d: i for i, d in enumerate(df.index)}
    rows = []
    for d in dates:
        i = pos[d]
        if i + 60 >= len(df) or i < 250:
            continue
        entry = c.iloc[i]
        r = {"date": d}
        for k in K_LIST:
            r[f"k{k}"] = c.iloc[i + k] / entry - 1
        r["mae20"] = l.iloc[i + 1:i + 21].min() / entry - 1
        r["wait_cost"] = entry / l.iloc[max(0, i - 20):i + 1].min() - 1
        r["above_ma240"] = bool(df["close"].iloc[i] >= df["close"].rolling(240).mean().iloc[i])
        rows.append(r)
    return pd.DataFrame(rows)


def summarize(ev, label):
    if len(ev) == 0:
        return None
    s = {"訊號": label, "n": len(ev)}
    for k in K_LIST:
        s[f"k{k}中位%"] = round(ev[f"k{k}"].median() * 100, 2)
    s["k20勝率%"] = round((ev["k20"] > 0).mean() * 100, 0)
    s["k60勝率%"] = round((ev["k60"] > 0).mean() * 100, 0)
    s["MAE20中位%"] = round(ev["mae20"].median() * 100, 2)
    s["MAE20尾部p10%"] = round(ev["mae20"].quantile(0.10) * 100, 2)
    s["等待成本中位%"] = round(ev["wait_cost"].median() * 100, 2)
    return s


def boot_diff(a, b, col="k20"):
    """bootstrap平均差CI95: a-b"""
    if len(a) < 5 or len(b) < 5:
        return (np.nan, np.nan)
    av, bv = a[col].values, b[col].values
    diffs = [rng.choice(av, len(av)).mean() - rng.choice(bv, len(bv)).mean() for _ in range(BOOT_N)]
    return (np.percentile(diffs, 2.5) * 100, np.percentile(diffs, 97.5) * 100)


SIGNALS = [("P1跳空長紅", "p1"), ("P1s真跳空長紅", "p1s"), ("P2純長紅", "p2"),
           ("P3連兩長紅", "p3"), ("P4跳空長紅+次日不破低", "p4"),
           ("P5縮量止跌", "p5"), ("P6橫盤打底", "p6"),
           ("P7長下影", "p7"), ("P7v爆量長下影", "p7v"), ("P8二次探底不破", "p8")]


def run_market(market, name):
    df = load_index(market)
    f = build_features(df)
    print(f"\n{'='*100}\n=== {name} ({df.index[0].date()}~{df.index[-1].date()}, {len(df)}日) ===")
    # control: 急殺狀態但當日無任何訊號
    sig_any = f[[c for _, c in SIGNALS]].any(axis=1)
    ctrl_dates = event_dates(f.assign(_ctrl=f["d_any"] & ~sig_any), "_ctrl")
    ctrl = fwd_stats(df, ctrl_dates, "control")
    all_ev = {}
    for label, col in SIGNALS:
        ev = fwd_stats(df, event_dates(f, col), label)
        all_ev[col] = ev
    rows = [summarize(ctrl, "[基準]急殺無訊號")] + [summarize(all_ev[c], lbl) for lbl, c in SIGNALS]
    tab = pd.DataFrame([r for r in rows if r])
    print("\n--- 全樣本(急殺前置內) ---")
    print(tab.to_string(index=False))
    # 年線上下分格
    for regime, flag in [("年線上", True), ("年線下", False)]:
        rws = [summarize(ctrl[ctrl["above_ma240"] == flag], "[基準]急殺無訊號")]
        for lbl, c in SIGNALS:
            ev = all_ev[c]
            rws.append(summarize(ev[ev["above_ma240"] == flag] if len(ev) else ev, lbl))
        t = pd.DataFrame([r for r in rws if r])
        print(f"\n--- {regime} ---")
        print(t.to_string(index=False))
    # bootstrap: 每訊號vs基準的k20差
    print("\n--- 訊號-基準 k20平均差 bootstrap CI95 (排0=真訊號) ---")
    for lbl, c in SIGNALS:
        lo, hi = boot_diff(all_ev[c], ctrl)
        mark = "✅排0" if (not np.isnan(lo)) and lo > 0 else ("❌反向" if (not np.isnan(hi)) and hi < 0 else "含0")
        print(f"  {lbl:24s} n={len(all_ev[c]):3d}  CI=[{lo:+.2f}, {hi:+.2f}]pp  {mark}")
    # P1逐年(勝率穩定度)
    ev1 = all_ev["p1"]
    if len(ev1):
        ev1 = ev1.copy(); ev1["yr"] = ev1["date"].dt.year
        g = ev1.groupby("yr").agg(n=("k20", "size"), k20中位=("k20", "median"), 勝率=("k20", lambda x: (x > 0).mean()))
        g["k20中位"] = (g["k20中位"] * 100).round(2); g["勝率"] = (g["勝率"] * 100).round(0)
        print("\n--- P1跳空長紅 逐年 ---")
        print(g.to_string())
    return all_ev, ctrl


def main():
    tw = {}
    for market, name in [("TAIEX", "加權指數"), ("TPEx", "櫃買指數")]:
        tw[market] = run_market(market, name)
    # 跨市場外部驗證: P1/P4 headline
    print(f"\n{'='*100}\n=== 跨市場外部驗證 P1/P4 (同參數,只看headline) ===")
    for market in ["SPX", "N225", "KOSPI"]:
        df = load_index(market)
        f = build_features(df)
        for lbl, c in [("P1", "p1"), ("P4", "p4")]:
            ev = fwd_stats(df, event_dates(f, c), lbl)
            s = summarize(ev, lbl)
            if s:
                print(f"  {market:6s} {lbl}: n={s['n']:3d} k20中位{s['k20中位%']:+.2f}% 勝率{s['k20勝率%']:.0f}% "
                      f"k60中位{s['k60中位%']:+.2f}% MAE20中位{s['MAE20中位%']:.2f}%")
    # 事件存快取供後續考卷(反彈領導權t0)重用
    out = {m: {c: ev for c, ev in evs[0].items()} | {"control": evs[1]} for m, evs in tw.items()}
    pd.to_pickle(out, "快取/tmp_index_panic_rebound_events.pkl")
    print("\n事件已存 快取/tmp_index_panic_rebound_events.pkl (領導權考卷t0用)")


if __name__ == "__main__":
    main()
