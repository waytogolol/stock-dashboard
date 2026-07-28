# -*- coding: utf-8 -*-
"""上櫃融資維持率警戒帶考卷(預註冊2026-07-28,使用者裁示「上市上櫃維持率開個研究做驗證補充」)
========================================================================
背景: 上櫃維持率公式版2026-07-28上板(margin_maintenance_otc,2011起回補中)。上市警戒帶判決
  (<150%=斷頭水位,9事件k60+14.4%/78%)是用「上市」數列考的;上櫃基線系統性較低
  (2026-07樣本:上櫃155 vs 上市173),150門檻直接移植很可能太鬆=意義不同,必須自考。
預註冊四題(跑之前寫死,不加題不改門檻):
  E1 門檻移植: 上櫃mm<150首破episode(60交易日去重)→TPEx k5/10/20/60。
     對照組=同法上市帶(2011起同窗)→TAIEX。先驗警語: 若上櫃事件頻率>2次/年=門檻不適用直接判死。
  E2 自身位階版: 上櫃mm expanding位階<=5(最少3年暖機)→TPEx k20/60。解決基線不同步,
     「它自己的極端」才是跨市場可比的口徑。
  E3 獨立增量: E2觸發日 ∧ 上市當日mm>=150(上市不在帶內)→ 仍正報酬?=獨立資訊vs上市影子;
     另列「兩市同窗」vs「上櫃單獨」對照。
  E4 剪刀差(探索層,不預設方向): spread=上市mm-上櫃mm 的240日位階>=95(中小型槓桿相對受傷極端)
     →次20日 TPEx-TAIEX 相對報酬。
判準(house style): episode化去重/逐事件明細表/預期n<15不做bootstrap→最高只到觀察層;
  絕對判上板、相對(減基準)判真偽;死格對照=上市2008與2022慢熊帶內失效模式是否重現。
資料完整度閘: margin_maintenance_otc覆蓋<95%(vs index_daily交易日曆2011起)→拒跑,先等回補。
用法: python build_margin_otc_band.py
"""
import sqlite3
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
DB = "capital_flow.db"
KS = [5, 10, 20, 60]


def fwd(px, d, k):
    if d not in px.index:
        return None
    t = px.index.get_loc(d)
    if t + k >= len(px):
        return None
    return (px.iloc[t + k] / px.iloc[t] - 1) * 100


def episodes(dates, cal, sep=60):
    pos = {d: i for i, d in enumerate(cal)}
    out, last = [], -10**9
    for d in sorted(dates):
        if d in pos and pos[d] - last >= sep:
            out.append(d)
            last = pos[d]
    return out


def table(name, evs, px, base_px=None):
    print(f"\n  {name} (n={len(evs)})")
    if not evs:
        return
    hdr = "    事件日        " + "".join(f"{'k' + str(k):>9}" for k in KS)
    print(hdr + ("   (相對=減對照指數)" if base_px is not None else ""))
    allv = {k: [] for k in KS}
    for d in evs:
        cells = []
        for k in KS:
            v = fwd(px, d, k)
            if v is not None and base_px is not None:
                b = fwd(base_px, d, k)
                v = v - b if b is not None else None
            cells.append(f"{v:>+9.2f}" if v is not None else f"{'—':>9}")
            if v is not None:
                allv[k].append(v)
        print(f"    {str(d.date()):<12}" + "".join(cells))
    med = "    中位          " + "".join(
        f"{np.median(allv[k]):>+9.2f}" if allv[k] else f"{'—':>9}" for k in KS)
    win = "    勝率%         " + "".join(
        f"{np.mean(np.array(allv[k]) > 0) * 100:>9.0f}" if allv[k] else f"{'—':>9}" for k in KS)
    print(med)
    print(win)


def main():
    conn = sqlite3.connect(DB)
    cal = pd.to_datetime([r[0] for r in conn.execute(
        "SELECT DISTINCT date FROM index_daily WHERE market='TAIEX' AND date>='2011-01-01' "
        "ORDER BY date")])
    otc = pd.read_sql("SELECT date, ratio FROM margin_maintenance_otc WHERE ratio>=100 "
                      "ORDER BY date", conn, parse_dates=["date"]).set_index("date").ratio
    twm = pd.read_sql("SELECT date, ratio FROM margin_maintenance_official WHERE ratio>=100 "
                      "ORDER BY date", conn, parse_dates=["date"]).set_index("date").ratio
    tpex = pd.read_sql("SELECT date, close FROM index_daily WHERE market='TPEx' ORDER BY date",
                       conn, parse_dates=["date"]).set_index("date").close
    taiex = pd.read_sql("SELECT date, close FROM index_daily WHERE market='TAIEX' ORDER BY date",
                        conn, parse_dates=["date"]).set_index("date").close
    conn.close()

    # ---- 完整度閘 ----
    cov = len(otc) / len(cal) * 100
    print(f"上櫃維持率覆蓋: {len(otc)}/{len(cal)}交易日 = {cov:.1f}% "
          f"({otc.index.min().date() if len(otc) else '—'} ~ "
          f"{otc.index.max().date() if len(otc) else '—'})")
    if cov < 95:
        print("⛔ 覆蓋<95%,回補未齊(fetch_margin_maintenance.py每run自動續350日),先不跑以免斷序假事件")
        return

    # ---- E1 門檻移植 ----
    print("\n═══ E1 門檻移植: 上櫃mm<150 首破episode → TPEx ═══")
    e1 = episodes(otc[otc < 150].index, cal)
    yrs = (cal[-1] - cal[0]).days / 365.25
    print(f"  事件頻率 {len(e1) / yrs:.2f}次/年 (預註冊: >2次/年=門檻不適用)")
    table("E1 上櫃帶(絕對)", e1, tpex)
    tw_e = episodes(twm[(twm < 150) & (twm.index >= cal[0])].index, cal)
    table("對照: 上市帶同法(2011起)→TAIEX", tw_e, taiex)

    # ---- E2 自身位階版 ----
    print("\n═══ E2 自身位階: 上櫃mm expanding位階<=5 (暖機>=750日) ═══")
    pctl = otc.expanding(750).apply(lambda s: (s <= s.iloc[-1]).mean() * 100, raw=False)
    e2 = episodes(pctl[pctl <= 5].index, cal)
    table("E2 位階極端(絕對)", e2, tpex)

    # ---- E3 獨立增量 ----
    print("\n═══ E3 獨立性: E2觸發 ∧ 上市當日>=150(不在帶內) ═══")
    twm_d = twm.reindex(otc.index).ffill()
    e3_only = [d for d in e2 if twm_d.get(d, np.nan) >= 150]
    e3_both = [d for d in e2 if twm_d.get(d, np.nan) < 150]
    table("E3a 上櫃單獨極端(上市健康)", e3_only, tpex)
    table("E3b 兩市同傷", e3_both, tpex)

    # ---- E4 剪刀差(探索層) ----
    print("\n═══ E4 剪刀差(探索): spread=上市-上櫃 240日位階>=95 → TPEx-TAIEX相對k20 ═══")
    both = pd.concat([twm.rename("tw"), otc.rename("otc")], axis=1).dropna()
    spread = both.tw - both.otc
    sp_pct = spread.rolling(240).rank(pct=True) * 100
    e4 = episodes(sp_pct[sp_pct >= 95].index, cal, sep=20)
    table("E4 剪刀差極端(TPEx相對TAIEX)", e4, tpex, base_px=taiex)

    print("\n判讀提醒(預註冊): n<15一律觀察層;E1若頻率超標→改用E2口徑;"
          "死格對照=帶內慢熊(上市2008/2022型)是否重現要逐事件人眼看明細表。")


if __name__ == "__main__":
    main()
