# -*- coding: utf-8 -*-
"""P5縮量止跌深挖考卷(2026-07-30深夜,使用者:「P5是MVP,要不要往這方向研究,說不定找到更好的方式」)。

紀律(防曲線擬合):
  主判=原版凍結參數(峰量窗10/縮量比0.5/不創低窗5/單日),鄰域36格只算「存活率」
  (k20中位>急殺基準的格子占比);兩段式只掛在凍結參數上測,不挑格。
變體軸:
  W峰量窗{10,15,20} × R縮量比{0.4,0.5,0.6} × L不創低窗{5,10} × C連續縮量日{1,2}
  兩段式: P5成立後5日內首根「漲≥1%且量≥縮量日1.2倍」的放量紅K收盤才進場
  (量縮=蹲,放量=起跳;比較立刻進場vs等確認的報酬/MAE/等待成本/漏單率)
基準: 急殺狀態日全體(10日去重)。外驗: 凍結參數跑KOSPI/N225/SPX。
"""
import sqlite3
import numpy as np
import pandas as pd

DB = "capital_flow.db"
DEDUP_GAP = 10


def load_index(market):
    con = sqlite3.connect(DB)
    df = pd.read_sql("SELECT date, open, high, low, close, volume FROM index_daily "
                     "WHERE market=? ORDER BY date", con, params=(market,))
    con.close()
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")


def base_features(df):
    c = df["close"]
    f = pd.DataFrame(index=df.index)
    f["d_any"] = ((c / c.shift(5) - 1 <= -0.05) | (c / c.shift(10) - 1 <= -0.08) |
                  (c / c.rolling(60).max() - 1 <= -0.10))
    f["pre_panic"] = f["d_any"].rolling(6, min_periods=1).max().astype(bool)
    f["above_ma240"] = c >= c.rolling(240).mean()
    return f


def dryup_mask(df, W, R, L, C):
    v, l = df["volume"], df["low"]
    vol_ok = v <= v.shift(1).rolling(W).max() * R
    if C > 1:
        vol_ok = vol_ok.rolling(C).min().astype(bool)
    return vol_ok & (l > l.shift(1).rolling(L).min())


def dedup(dates):
    out, last = [], None
    for d in dates:
        if last is None or (d - last).days > DEDUP_GAP * 1.6:
            out.append(d); last = d
    return out


def stats(df, dates, entry_override=None):
    """entry_override: dict date->實際進場日(兩段式用)"""
    c, l = df["close"], df["low"]
    pos = {d: i for i, d in enumerate(df.index)}
    rows = []
    for d in dates:
        ed = entry_override.get(d) if entry_override else d
        if ed is None:
            continue
        i = pos[ed]
        if i + 60 >= len(df) or i < 250:
            continue
        e = c.iloc[i]
        rows.append({"date": d,
                     "k20": c.iloc[i + 20] / e - 1, "k60": c.iloc[i + 60] / e - 1,
                     "mae20": l.iloc[i + 1:i + 21].min() / e - 1,
                     "wait": e / l.iloc[max(0, i - 25):i + 1].min() - 1})
    return pd.DataFrame(rows)


def row(ev, label):
    if len(ev) < 5:
        return f"{label:36s} n={len(ev):3d}  (樣本不足)"
    return (f"{label:36s} n={len(ev):3d}  k20中位{ev['k20'].median()*100:+.2f}% "
            f"勝{(ev['k20']>0).mean()*100:.0f}%  k60中位{ev['k60'].median()*100:+.2f}% "
            f"勝{(ev['k60']>0).mean()*100:.0f}%  MAE20中位{ev['mae20'].median()*100:.2f}% "
            f"等待{ev['wait'].median()*100:.2f}%")


def run_market(market, name, full=True):
    df = load_index(market)
    f = base_features(df)
    print(f"\n{'='*105}\n=== {name} ===")
    base_dates = dedup(list(f.index[f["pre_panic"]]))
    base = stats(df, base_dates)
    print(row(base, "[基準]急殺狀態全體"))
    # 凍結參數主判
    frozen = dryup_mask(df, 10, 0.5, 5, 1) & f["pre_panic"]
    fro_dates = dedup(list(f.index[frozen]))
    ev0 = stats(df, fro_dates)
    print(row(ev0, "P5凍結版(W10/R0.5/L5/C1)"))
    if not full:
        return
    # 年線分格
    for regime, flag in [("年線上", True), ("年線下", False)]:
        mask = [bool(f["above_ma240"].get(d, False)) == flag for d in ev0["date"]]
        print(row(ev0[pd.Series(mask, index=ev0.index)], f"  P5凍結版·{regime}"))
    # 鄰域存活率
    base_med = base["k20"].median()
    survive, cells = 0, []
    for W in (10, 15, 20):
        for R in (0.4, 0.5, 0.6):
            for L in (5, 10):
                for C in (1, 2):
                    m = dryup_mask(df, W, R, L, C) & f["pre_panic"]
                    ev = stats(df, dedup(list(f.index[m])))
                    if len(ev) >= 8:
                        ok = ev["k20"].median() > base_med
                        survive += ok
                        cells.append((W, R, L, C, len(ev), ev["k20"].median() * 100,
                                      (ev["k20"] > 0).mean() * 100, ok))
    print(f"\n  鄰域36格存活率(k20中位>基準{base_med*100:+.2f}%): {survive}/{len(cells)} = {survive/max(1,len(cells))*100:.0f}%")
    top = sorted(cells, key=lambda x: -x[5])[:5]
    for W, R, L, C, n, med, win, ok in top:
        print(f"    W{W}/R{R}/L{L}/C{C}: n={n} k20中位{med:+.2f}% 勝{win:.0f}% {'✅' if ok else ''}")
    # 兩段式(掛凍結參數)
    c, v = df["close"], df["volume"]
    pos = {d: i for i, d in enumerate(df.index)}
    override, missed = {}, 0
    for d in fro_dates:
        i = pos[d]
        ed = None
        for j in range(i + 1, min(i + 6, len(df))):
            if c.iloc[j] / c.iloc[j - 1] - 1 >= 0.01 and v.iloc[j] >= v.iloc[i] * 1.2:
                ed = df.index[j]; break
        if ed is None:
            missed += 1
        override[d] = ed
    ev2 = stats(df, fro_dates, entry_override=override)
    print(f"\n  兩段式(P5後5日內首根放量紅K才進):漏單{missed}/{len(fro_dates)}")
    print(row(ev2, "  P5→放量紅K確認進場"))


def main():
    run_market("TAIEX", "加權指數")
    run_market("TPEx", "櫃買指數")
    print(f"\n{'='*105}\n=== 外驗(凍結參數headline) ===")
    for mk in ("KOSPI", "N225", "SPX"):
        run_market(mk, mk, full=False)


if __name__ == "__main__":
    main()
