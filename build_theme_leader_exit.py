# -*- coding: utf-8 -*-
"""題材內龍頭破線→退出該題材?(使用者2026-07-15點名,市場級龍頭破線否定後的窄版變體)
假說:持有題材時,題材內龍頭(前3大成交金額)破線=該題材行情將盡,應退出——
市場級的「輪動」擋箭牌在題材內不適用(同題材內龍頭弱=題材本身弱?)。

定義(單一參數組,不掃):
  題材宇宙=classification台股×價格快取,>=5檔有資料的題材
  題材指數=成員等權日報酬累積;龍頭=題材內前20日平均成交金額前3大(shift(1))
  龍頭破線=3檔中>=2檔收盤<自身20日MA
  健康期=題材指數在自身20日MA之上(還在行情中,退出判斷才有意義)
測試:健康期內,龍頭破線 vs 未破線的題材前瞻10/20日等權報酬(題材指數);逐年;
  對照=題材指數自身跌破20MA(自然退出規則)的lead-lag預警價值。
用法: python build_theme_leader_exit.py
"""
import pickle
import sqlite3

import pandas as pd

with open("tmp_revenue_price_cache.pkl", "rb") as f:
    cache = pickle.load(f)
conn = sqlite3.connect("capital_flow.db")
cls = pd.read_sql("SELECT code, main_group FROM classification WHERE country='台'",
                  conn, dtype={"code": str}).drop_duplicates()

closes, turns = {}, {}
for code, df in cache.items():
    c, v = df["Close"], df["Volume"]
    if hasattr(c, "columns"):
        c, v = c.iloc[:, 0], v.iloc[:, 0]
    if len(c) >= 100:
        closes[code] = c
        turns[code] = c * v
C = pd.DataFrame(closes).sort_index()
RET = C.pct_change()
T = pd.DataFrame(turns).sort_index()
turn20 = T.rolling(20, min_periods=10).mean().shift(1)
above20 = C >= C.rolling(20).mean()

rows = []
for g, mem in cls.groupby("main_group"):
    codes = [c for c in mem.code if c in C.columns]
    if len(codes) < 5:
        continue
    r = RET[codes].mean(axis=1)                      # 題材等權日報酬
    idx = (1 + r.fillna(0)).cumprod()
    idx_ma = idx.rolling(20).mean()
    healthy = idx > idx_ma
    f10 = (idx.shift(-10) / idx - 1) * 100
    f20 = (idx.shift(-20) / idx - 1) * 100
    tt = turn20[codes]
    ab = above20[codes]
    for i, d in enumerate(idx.index):
        if i < 40 or pd.isna(idx_ma.iloc[i]):
            continue
        tv = tt.iloc[i].dropna()
        if len(tv) < 3:
            continue
        top3 = tv.nlargest(3).index
        broken = (~ab.iloc[i][top3]).sum() >= 2
        rows.append({"theme": g, "date": d, "healthy": healthy.iloc[i],
                     "broken": broken, "f10": f10.iloc[i], "f20": f20.iloc[i]})

P = pd.DataFrame(rows)
P["y"] = P.date.dt.year
h = P[P.healthy].dropna(subset=["f20"])
print(f"panel: {P.theme.nunique()}題材 × {P.date.nunique()}日 = {len(P)}列; "
      f"健康期題材-日 {len(h)} (龍頭破線占{h.broken.mean() * 100:.0f}%)")

print("\n===== 健康期(題材在自身20MA上): 龍頭破線 vs 未破線 的題材前瞻 =====")
for lab, g in [("龍頭破線(>=2/3)", h[h.broken]), ("龍頭未破線", h[~h.broken])]:
    print(f"  {lab}: 10日中位{g.f10.median():+.2f}%/勝率{(g.f10 > 0).mean() * 100:.0f}% "
          f" 20日中位{g.f20.median():+.2f}%/勝率{(g.f20 > 0).mean() * 100:.0f}% (n={len(g)})")
print("\n--- 逐年(20日前瞻中位) ---")
for y in sorted(h.y.unique()):
    a = h[(h.y == y) & h.broken].f20
    b = h[(h.y == y) & ~h.broken].f20
    print(f"  {y}: 破線{a.median():+.2f}%(n={len(a)})  未破{b.median():+.2f}%(n={len(b)})")

# 事件版:健康期首次出現龍頭破線(去重20日),之後題材20日報酬
print("\n--- 事件版(健康期首日轉為破線,去重20交易日) ---")
evs = []
for g, gg in P.groupby("theme"):
    gg = gg.sort_values("date").reset_index(drop=True)
    st = gg.healthy & gg.broken
    enter = st & ~st.shift(1, fill_value=False)
    last = -99
    for j in gg.index[enter]:
        if j - last > 20:
            evs.append(gg.loc[j])
            last = j
E = pd.DataFrame(evs).dropna(subset=["f20"])
print(f"  n={len(E)}: 10日中位{E.f10.median():+.2f}%/勝率{(E.f10 > 0).mean() * 100:.0f}%  "
      f"20日中位{E.f20.median():+.2f}%/勝率{(E.f20 > 0).mean() * 100:.0f}%")
base = P[P.healthy].dropna(subset=["f20"])
print(f"  對照(全部健康期題材-日): 10日{base.f10.median():+.2f}% 20日{base.f20.median():+.2f}%")
