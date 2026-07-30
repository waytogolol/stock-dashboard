# -*- coding: utf-8 -*-
"""大盤回落起點的特徵逆向工程(使用者2026-07-15提案,case-control探索——產生假說用,
通過的特徵須再走預註冊驗證,不可直接當訊號)。

案例定義(主測):TAIEX創20日新高的日子(episode去重,取每叢集最後一天=實際頂點候選),
  case=其後20日內自該點最大回撤<=-5%(真回落) / control=回撤>=-2%(續漲),中間排除(銳化對比)。
次測(決策相關版):TAIEX跌破20MA的日子,true=其後20日再跌>=3% / false=再跌<1.5%(假摔)。

特徵battery(全部日t已知,無look-ahead):
  otc_rel20   = OTC/TAIEX比值20日變化%(中小型相對強弱)
  otc_weak    = OTC自身在20MA下(大盤創高/破線時櫃買已弱?)
  leader_b20  = 龍頭(前20日成交金額前20大)破自身20MA廣度(前一日)
  mkt_breadth = 全宇宙(1,520檔)站上自身20MA比例
  breadth_chg = mkt_breadth vs 10日前變化(頂背離?)
  mm_pos      = 融資維持率240日位階
  conc        = 前20大成交金額占全宇宙比重(擁擠度)
  vol10       = TAIEX 10日日報酬標準差
用法: python build_pullback_case.py (依賴tmp_revenue_price_cache/tmp_twii_long/tmp_margin_maintenance)
"""
import os
import pickle

import pandas as pd

# ---- 指數 ----
px = pd.read_pickle("tmp_twii_long.pkl")
px.index = pd.to_datetime(px.index).tz_localize(None)
if os.path.exists("tmp_otc_daily.pkl"):
    otc = pd.read_pickle("tmp_otc_daily.pkl")
else:
    import yfinance as yf
    otc = yf.download("^TWOII", start="2000-06-01", auto_adjust=True, progress=False)["Close"]
    if hasattr(otc, "columns"):
        otc = otc.iloc[:, 0]
    otc.to_pickle("tmp_otc_daily.pkl")
otc.index = pd.to_datetime(otc.index).tz_localize(None)

# ---- 個股宇宙特徵 ----
with open("tmp_revenue_price_cache.pkl", "rb") as f:
    cache = pickle.load(f)
closes, turns = {}, {}
for code, df in cache.items():
    c, v = df["Close"], df["Volume"]
    if hasattr(c, "columns"):
        c, v = c.iloc[:, 0], v.iloc[:, 0]
    if len(c) >= 100:
        closes[code] = c
        turns[code] = c * v
C = pd.DataFrame(closes).sort_index()
T = pd.DataFrame(turns).sort_index()
above20 = (C >= C.rolling(20).mean())
mkt_breadth = above20.mean(axis=1)
turn20 = T.rolling(20, min_periods=10).mean().shift(1)
lead_b20, conc = {}, {}
for i, d in enumerate(C.index):
    if i < 40:
        continue
    tv = turn20.iloc[i].dropna()
    if len(tv) < 100:
        continue
    leaders = tv.nlargest(20).index
    lead_b20[d] = (~above20.iloc[i][leaders]).mean()
    tot = T.iloc[i].sum()
    conc[d] = T.iloc[i][leaders].sum() / tot if tot else None

mm = pd.read_pickle("tmp_margin_maintenance.pkl")

F = pd.DataFrame({"P": px}).join(otc.rename("OTC"), how="inner")
F["ratio"] = F.OTC / F.P
F["otc_rel20"] = F.ratio.pct_change(20) * 100
F["otc_weak"] = F.OTC < F.OTC.rolling(20).mean()
F["p_ma20"] = F.P.rolling(20).mean()
F["vol10"] = F.P.pct_change().rolling(10).std() * 100
F = F.join(pd.Series(lead_b20, name="leader_b20"))
F = F.join(mkt_breadth.rename("mkt_breadth"))
F["breadth_chg"] = F.mkt_breadth - F.mkt_breadth.shift(10)
F = F.join(conc and pd.Series(conc, name="conc"))
F = F.join(mm["pos"].rename("mm_pos"))
F["leader_b20"] = F.leader_b20.shift(1)  # 用前一日,保守
F = F[F.index >= "2022-03-01"].copy()

FEATS = ["otc_rel20", "otc_weak", "leader_b20", "mkt_breadth", "breadth_chg", "mm_pos", "conc", "vol10"]


def contrast(cases, controls, label):
    print(f"\n===== {label}: case n={len(cases)} / control n={len(controls)} =====")
    print(f"{'特徵':<14}{'case中位':>10}{'ctrl中位':>10}  方向一致率(case>ctrl日比例)")
    for f in FEATS:
        a, b = F.loc[cases, f].dropna(), F.loc[controls, f].dropna()
        if a.dtype == bool:
            a, b = a.astype(float), b.astype(float)
        if not len(a) or not len(b):
            continue
        # 粗AUC: case值在合併分布中的平均百分位
        both = pd.concat([a, b])
        auc = both.rank(pct=True)[a.index].mean()
        print(f"{f:<14}{a.median():>10.2f}{b.median():>10.2f}   AUC≈{auc:.2f}"
              + ("  ←" if abs(auc - .5) >= .15 else ""))


# ---- 主測: 20日新高日 case-control ----
is_high = F.P >= F.P.rolling(20).max()
fwd_dd = (F.P.shift(-1).rolling(20).min().shift(-19) / F.P - 1) * 100  # 未來20日最低 vs 今日
highs = F.index[is_high & fwd_dd.notna()]
# 叢集去重: 相鄰<=5日視為同叢集,取最後一天
clusters, cur = [], [highs[0]]
for d in highs[1:]:
    if (F.index.get_loc(d) - F.index.get_loc(cur[-1])) <= 5:
        cur.append(d)
    else:
        clusters.append(cur[-1])
        cur = [d]
clusters.append(cur[-1])
cases = [d for d in clusters if fwd_dd[d] <= -5]
ctrls = [d for d in clusters if fwd_dd[d] >= -2]
contrast(cases, ctrls, "主測:20日新高後20日內回撤<=-5% vs >=-2%")
print("  case日期: " + ", ".join(str(d.date()) for d in cases))

# ---- 次測: 跌破20MA真假摔 ----
healthy = F.P > F.p_ma20
cross = F.index[healthy.shift(1, fill_value=False) & ~healthy]
fwd_more = (F.P.shift(-1).rolling(20).min().shift(-19) / F.P - 1) * 100
tr = [d for d in cross if pd.notna(fwd_more[d]) and fwd_more[d] <= -3]
fa = [d for d in cross if pd.notna(fwd_more[d]) and fwd_more[d] >= -1.5]
contrast(tr, fa, "次測:跌破20MA後再跌>=3%(真回檔) vs <1.5%(假摔)")
print("  真回檔日期: " + ", ".join(str(d.date()) for d in tr))
