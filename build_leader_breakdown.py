# -*- coding: utf-8 -*-
"""龍頭破線=高點降部位訊號?(使用者2026-07-15盤中觀察,case-first預註冊)
觀察:大盤高點回落休息前,帶動族群的龍頭先破線(5/10/20日)——「將軍先陣亡」。
機制:龍頭=行情引擎+法人出貨先出領導股→領導力瓦解可能領先大盤自身均線訊號。

定義(單一參數組,不掃):
  龍頭=每日「前20日平均成交值」前20大(shift(1)無look-ahead,宇宙=快取1,525檔)
  破線廣度=龍頭中收盤<自身20日MA的比例(5/10日版只做描述性參考)
  門檻=廣度>=50%(沿用規則②廣度50%語彙)
測試:
  A) 大盤仍在20日MA上(健康期)時: 龍頭破線廣度>=50% vs <50% 的前瞻5/10/20/60日大盤報酬
  B) 高點框架: 大盤距240日高<3% × 廣度>=50% (事件版去重20日) vs 高點×廣度<50%
  C) lead-lag: 大盤每次跌破20MA前,廣度>=50%領先幾天(有沒有預警價值)
判準:A的差距要有實質意義(不只統計)才值得進態勢階梯當第四輸入。
用法: python build_leader_breakdown.py
"""
import pickle

import pandas as pd

with open("tmp_revenue_price_cache.pkl", "rb") as f:
    cache = pickle.load(f)

closes, turns = {}, {}
for code, df in cache.items():
    c = df["Close"]
    v = df["Volume"]
    if hasattr(c, "columns"):
        c = c.iloc[:, 0]
        v = v.iloc[:, 0]
    if len(c) < 100:
        continue
    closes[code] = c
    turns[code] = c * v

C = pd.DataFrame(closes).sort_index()
T = pd.DataFrame(turns).sort_index()
print(f"宇宙: {C.shape[1]}檔 × {C.shape[0]}日 ({C.index.min().date()}~{C.index.max().date()})")

turn20 = T.rolling(20, min_periods=10).mean().shift(1)
ma20 = C.rolling(20).mean()
below20 = C < ma20
below10 = C < C.rolling(10).mean()
below5 = C < C.rolling(5).mean()

rows = []
for i, d in enumerate(C.index):
    if i < 40:
        continue
    tv = turn20.iloc[i].dropna()
    if len(tv) < 100:
        continue
    leaders = tv.nlargest(20).index
    rows.append({"date": d,
                 "b20": below20.iloc[i][leaders].mean(),
                 "b10": below10.iloc[i][leaders].mean(),
                 "b5": below5.iloc[i][leaders].mean()})
B = pd.DataFrame(rows).set_index("date")

px = pd.read_pickle("tmp_twii_long.pkl")
px.index = pd.to_datetime(px.index).tz_localize(None)
B = B.join(px.rename("P"), how="inner")
B["p_ma20"] = B.P.rolling(20).mean()
B["healthy"] = B.P > B.p_ma20
B["near_high"] = B.P >= B.P.rolling(240, min_periods=120).max() * 0.97
for k in (5, 10, 20, 60):
    B[f"f{k}"] = (B.P.shift(-k) / B.P - 1) * 100
B = B.dropna(subset=["b20", "p_ma20"])
print(f"分析樣本: {len(B)}日 | 龍頭破20MA廣度>=50%的日子占{(B.b20 >= .5).mean() * 100:.0f}%"
      f" (5MA:{(B.b5 >= .5).mean() * 100:.0f}% 10MA:{(B.b10 >= .5).mean() * 100:.0f}%)")

def stats(g, k):
    v = g[f"f{k}"].dropna()
    return f"{k}日中位{v.median():+.2f}%/勝率{(v > 0).mean() * 100:.0f}%(n={len(v)})"

print("\n===== A) 大盤仍在20MA上(健康期)的分流 =====")
h = B[B.healthy]
for lab, g in [("龍頭破線廣度>=50%", h[h.b20 >= .5]), ("龍頭破線廣度<50%", h[h.b20 < .5])]:
    print(f"  {lab}: " + "  ".join(stats(g, k) for k in (5, 10, 20, 60)))
print("  (5MA版參考) 廣度>=50%: " + "  ".join(stats(h[h.b5 >= .5], k) for k in (10, 20)))
print("  (10MA版參考)廣度>=50%: " + "  ".join(stats(h[h.b10 >= .5], k) for k in (10, 20)))

print("\n===== B) 高點框架(距240日高<3%) =====")
nh = B[B.near_high]
for lab, g in [("高點×龍頭破線>=50%", nh[nh.b20 >= .5]), ("高點×龍頭破線<50%", nh[nh.b20 < .5])]:
    print(f"  {lab}: " + "  ".join(stats(g, k) for k in (5, 10, 20, 60)))
# 事件版(首日進入狀態,去重20日)
st = (B.near_high & (B.b20 >= .5))
enter = st & ~st.shift(1, fill_value=False)
evs = []
for d in B.index[enter]:
    if not evs or (B.index.get_loc(d) - B.index.get_loc(evs[-1])) > 20:
        evs.append(d)
print(f"  事件版n={len(evs)}: " + "  ".join(
    f"{k}日中位{B.loc[evs, f'f{k}'].dropna().median():+.2f}%/勝率{(B.loc[evs, f'f{k}'].dropna() > 0).mean() * 100:.0f}%"
    for k in (5, 10, 20, 60)))
print("  事件日: " + ", ".join(str(d.date()) for d in evs))

print("\n===== C) lead-lag: 大盤跌破20MA前,龍頭廣度>=50%領先幾天 =====")
cross = B.healthy.shift(1, fill_value=False) & ~B.healthy  # 今日跌破
leads = []
for d in B.index[cross]:
    i = B.index.get_loc(d)
    win = B.b20.iloc[max(0, i - 15):i]
    hit = win[win >= .5]
    leads.append((d, i - B.index.get_loc(hit.index[0]) if len(hit) else None))
led = [x for _, x in leads if x is not None]
print(f"  大盤跌破20MA共{len(leads)}次,其中前15日內龍頭廣度曾>=50%的有{len(led)}次"
      f" ({len(led) / len(leads) * 100:.0f}%),領先天數中位{pd.Series(led).median():.0f}天")
noled = [d for d, x in leads if x is None]
print(f"  無預警直接跌破的日子: " + ", ".join(str(d.date()) for d in noled[:12]))
