# -*- coding: utf-8 -*-
"""漲停後拉回買點考卷(使用者2026-07-15提案:多日K棒+量+漲停前科→拉回找短線買點)
必須正面處理的前車之鑑: ⑤加碼假說判決=等回檔系統性錯過最強飆股(A10有29%等不到)
→ 本卷核心=「等拉回」vs「隔日直接追」的完整帳,含等不到的機會成本。

設計(預註冊,單一設定不掃參數):
- 事件: 首根收盤鎖漲停(前10交易日無lu_close),全宇宙1379檔,2019-07~2026-05。
- 進場變體(皆次日開盤價,現實=漲停戰法以開盤參與):
  E1 隔日開盤直接追(基準);排除隔日一價鎖死(買不到)
  E2 縮量拉回: 漲停後3日內出現[收盤<漲停日收盤 且 量<漲停日量50%] → 再次日開盤買
  E3 N字過高: 漲停後10日內先有回檔日(收盤<漲停日收盤)再出現收盤>漲停日最高 → 再次日開盤買
- 持有: 10交易日收盤出(主口徑);5/20日次要。超額=扣同期TWII;淨額=再扣來回成本0.45%。
- 帳本: 觸發率/未觸發事件的E1對照報酬(機會成本)/淨超額/勝率。
- 分層(階層式非掃描): 鎖死vs收盤鎖、大盤月線上vs下(TWII>20日MA)、量能倍數(漲停日量/20日均量>=3)、
  題材score=4當月(classification映射,覆蓋僅~300檔標註即可)。
- 周轉評分: 每月事件數×觸發率=頻率;單筆淨期望×頻率=月貢獻估計。
注意: 未調整價(股利噪音~1%/年);TWII基準用進出場日收盤近似;快篩未bootstrap。
用法: python build_limitup_pullback.py  (需tmp_limit_flags.pkl+fm_daily_price)
"""
import sqlite3

import numpy as np
import pandas as pd

from build_score4_early_entry import build_score_panel

HOLD = 10
COST = 0.45


def main():
    flags = pd.read_pickle("tmp_limit_flags.pkl")
    conn = sqlite3.connect("capital_flow.db")
    px = pd.read_sql("SELECT code, date, open, high, low, close, volume FROM fm_daily_price", conn)
    conn.close()
    px["date"] = pd.to_datetime(px.date)
    twii = pd.read_pickle("tmp_twii_long.pkl").dropna()

    # 題材score映射(訊號月=sigT,成員=classification)
    panel, _ = build_score_panel()
    cls = pd.read_sql if False else None
    conn = sqlite3.connect("capital_flow.db")
    cmap = pd.read_sql("SELECT code, main_group FROM classification WHERE country='台'",
                       conn, dtype={"code": str}).drop_duplicates("code").set_index("code").main_group
    conn.close()
    s4set = set((r.industry, r.sigT.strftime("%Y-%m")) for _, r in panel[panel.score == 4].iterrows())

    flags = flags.sort_values(["code", "date"])
    ev_rows = []
    for code, g in px.groupby("code"):
        g = g.sort_values("date").reset_index(drop=True)
        f = flags[flags.code == code].reset_index(drop=True)
        if len(f) != len(g):
            f = f.set_index("date").reindex(g.date).reset_index()
        lu = f.lu_close.fillna(False).values
        lock = f.lu_lock.fillna(False).values
        n = len(g)
        vol20 = g.volume.rolling(20).mean().shift(1)
        for i in np.where(lu)[0]:
            if i < 20 or i + 1 + HOLD + 12 >= n:
                continue
            if lu[max(0, i - 10):i].any():  # 首根
                continue
            d0 = g.date[i]
            ind = cmap.get(code)
            ev = {"code": code, "d0": d0, "lock": bool(lock[i]),
                  "volx": g.volume[i] / vol20[i] if vol20[i] > 0 else np.nan,
                  "s4": (ind, d0.strftime("%Y-%m")) in s4set if ind else False}
            # E1: 隔日開盤(排除隔日一價鎖死)
            j = i + 1
            nxt_lock = bool(lock[j]) if j < n else True
            close_arr, open_arr = g.close.values, g.open.values
            def leg(entry_j):
                if entry_j is None or entry_j + HOLD >= n:
                    return None, None, None
                ent = open_arr[entry_j]
                ext = close_arr[entry_j + HOLD]
                if not (ent > 0 and ext > 0):  # 停牌/無成交日FinMind填0
                    return None, None, None
                tw = (twii.asof(g.date[entry_j + HOLD]) / twii.asof(g.date[entry_j]) - 1) * 100
                return (ext / ent - 1) * 100 - tw - COST, g.date[entry_j], ent
            if not nxt_lock:
                ev["e1"], _, _ = leg(j)
            # E2: 3日內縮量拉回
            t2 = None
            for k in range(i + 1, min(i + 4, n)):
                if close_arr[k] < close_arr[i] and g.volume[k] < g.volume[i] * 0.5:
                    t2 = k + 1
                    break
            ev["e2"], _, _ = leg(t2) if t2 else (None, None, None)
            ev["e2_trig"] = t2 is not None
            # E3: 10日內先回檔再過漲停日高
            t3, pulled = None, False
            for k in range(i + 1, min(i + 11, n)):
                if close_arr[k] < close_arr[i]:
                    pulled = True
                elif pulled and close_arr[k] > g.high[i]:
                    t3 = k + 1
                    break
            ev["e3"], _, _ = leg(t3) if t3 else (None, None, None)
            ev["e3_trig"] = t3 is not None
            ev_rows.append(ev)
    df = pd.DataFrame(ev_rows)
    print(f"首根鎖漲停事件: {len(df):,}筆 / {df.code.nunique()}檔 "
          f"({df.d0.min():%Y-%m}~{df.d0.max():%Y-%m}), 月均{len(df) / 83:.0f}件")

    def stat(x, lab):
        x = pd.Series(x).dropna()
        if len(x) < 10:
            print(f"  {lab}: n={len(x)}太少")
            return
        print(f"  {lab}: 淨超額中位{x.median():+6.2f}% 均{x.mean():+6.2f}% 勝率{(x > 0).mean() * 100:3.0f}% n={len(x):,}")

    print(f"\n== 三變體(持有{HOLD}日,已扣成本{COST}%) ==")
    stat(df.e1, "E1隔日開盤追")
    stat(df.e2, "E2縮量拉回  ")
    stat(df.e3, "E3 N字過高  ")
    print(f"\n觸發率: E1可執行{df.e1.notna().mean() * 100:.0f}% | E2 {df.e2_trig.mean() * 100:.0f}% | E3 {df.e3_trig.mean() * 100:.0f}%")
    print("機會成本(未觸發事件的E1報酬):")
    stat(df[~df.e2_trig].e1, "E2等不到的那批,E1拿到")
    stat(df[~df.e3_trig].e1, "E3等不到的那批,E1拿到")

    print("\n== 分層(E1為例) ==")
    stat(df[df.lock].e1, "一價鎖死    ")
    stat(df[~df.lock].e1, "收盤鎖(非鎖死)")
    tw20 = twii.rolling(20).mean()
    above = df.d0.map(lambda d: twii.asof(d) > tw20.asof(d))
    stat(df[above].e1, "大盤月線上  ")
    stat(df[~above].e1, "大盤月線下  ")
    stat(df[df.volx >= 3].e1, "爆量>=3x    ")
    stat(df[df.volx < 3].e1, "量能<3x     ")
    stat(df[df.s4].e1, "題材score=4 ")
    stat(df[~df.s4].e1, "非score=4   ")

    print("\n== 逐年(E1) ==")
    df["y"] = df.d0.dt.year
    for y, g in df.groupby("y"):
        stat(g.e1, str(y))

    df.to_pickle("tmp_limitup_pullback_panel.pkl")
    print("\n面板存 tmp_limitup_pullback_panel.pkl")


if __name__ == "__main__":
    main()
