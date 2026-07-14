# -*- coding: utf-8 -*-
"""⑫題材動能×大盤態勢階梯疊加測試(使用者2026-07-14問「有沒有測過部位縮放」→補測)。
態勢口徑=系統凍結版(bear_test_2022.py/export_html.py同款,單一參數組不調參):
  TWII週線 vs 4週均(月線)/13週均(季線) → 月線上=1.0/月線下=0.6/季線下=0.3
look-ahead防護:每日的tier由「上一個已完成週線收盤」決定(週五收盤後下週生效),
不用當日/當週未完成資料。
變體(全部預先指定,無參數掃描):
  V0 對照=score4滿倉(判決版報告同款)
  V1 進場門檻=只在tier=1.0時進場,其餘訊號跳過(「多頭才啟用」)
  V2 組合縮放=每日組合報酬×當日tier(bear_test階梯同款,對整本書縮放)
  V3 = V1+V2 併用
用法: python build_theme_momentum_tier.py
"""
import pickle

import numpy as np
import pandas as pd

HOLD_DAYS = 60

with open("tmp_revenue_price_cache.pkl", "rb") as f:
    cache = pickle.load(f)

panel = pd.read_pickle("tmp_theme_momentum_v2_panel.pkl")
s4 = panel[panel.score == 4].copy()

twii = pd.read_pickle("tmp_twii_daily.pkl")
twii.columns = twii.columns.get_level_values(0)
twii = twii.sort_index()
c_twii = twii.Close
all_days_idx = [d for d in twii.index if str(d.date()) >= "2022-01-01"]
all_days = [str(d.date()) for d in all_days_idx]

# 週線tier(上一完成週生效)
wk = c_twii.resample("W-FRI").last().dropna()
ma4, ma13 = wk.rolling(4).mean(), wk.rolling(13).mean()
tier_wk = pd.Series(1.0, index=wk.index)
tier_wk[wk < ma4] = 0.6
tier_wk[wk < ma13] = 0.3
# 對齊到日:當日tier=最近一個「已完成」週線(index嚴格<當日)的tier
tier_daily = {}
wk_idx = tier_wk.index
for d in c_twii.index:
    pos = wk_idx.searchsorted(pd.Timestamp(d))  # 第一個>=d的週五
    tier_daily[str(d.date())] = float(tier_wk.iloc[pos - 1]) if pos > 0 else 1.0
tier_s = pd.Series(tier_daily)


def daily_returns_for_trade(row):
    df = cache.get(row.code)
    if df is None:
        return None
    c = df["Close"]
    if hasattr(c, "columns"):
        c = c.iloc[:, 0]
    entry = pd.Timestamp(row.entry_day)
    if entry not in c.index:
        return None
    start_i = c.index.get_loc(entry)
    end_i = start_i + HOLD_DAYS
    if end_i >= len(c):
        return None
    window = c.iloc[start_i:end_i + 1]
    dr = window.pct_change().dropna() * 100
    dr.index = dr.index.map(lambda d: str(d.date()))
    return dr


def build_equity(tdf, scale_by_tier=False):
    frames = [dr for row in tdf.itertuples() if (dr := daily_returns_for_trade(row)) is not None]
    all_ret = pd.concat(frames, axis=1)
    port_ret = all_ret.mean(axis=1)
    port = pd.Series(0.0, index=all_days)
    idx = port_ret.index.intersection(port.index)
    port.loc[idx] = port_ret.loc[idx]
    if scale_by_tier:
        port = port * tier_s.reindex(port.index).fillna(1.0)
    eq = (1 + port / 100).cumprod()
    ddv = (eq / eq.cummax() - 1) * 100
    mu, sdv = port.mean(), port.std()
    mult = eq.iloc[-1]
    ann = (mult ** (252 / len(port)) - 1) * 100
    tmp = pd.DataFrame({"date": all_days, "ret": port.values})
    tmp["y"] = tmp.date.str[:4]
    yearly = {y: ((1 + g.ret / 100).prod() - 1) * 100 for y, g in tmp.groupby("y")}
    return dict(trades=len(tdf), mult=mult, ann=ann,
                sharpe=mu / sdv * 252 ** 0.5 if sdv else 0,
                mdd=ddv.min(), calmar=ann / abs(ddv.min()), yearly=yearly)


s4["tier_at_entry"] = s4.entry_day.map(lambda d: tier_s.get(str(pd.Timestamp(d).date()), 1.0))
print(f"score=4共{len(s4)}筆;進場日tier分布: "
      f"{s4.tier_at_entry.value_counts().sort_index(ascending=False).to_dict()}")

variants = [
    ("V0 滿倉對照", s4, False),
    ("V1 進場門檻(tier=1才進)", s4[s4.tier_at_entry >= 1.0], False),
    ("V2 組合縮放(日報酬×tier)", s4, True),
    ("V3 門檻+縮放併用", s4[s4.tier_at_entry >= 1.0], True),
]
rows = []
for name, tdf, sc in variants:
    r = build_equity(tdf, scale_by_tier=sc)
    rows.append((name, r))
    yr = "  ".join(f"{y}:{v:+.1f}%" for y, v in r["yearly"].items())
    print(f"\n{name}: {r['trades']}筆 複利{r['mult']:.2f}x 年化{r['ann']:+.1f}% "
          f"夏普{r['sharpe']:.2f} MDD{r['mdd']:.1f}% Calmar{r['calmar']:.2f}")
    print(f"  逐年: {yr}")

# 被V1擋掉的訊號單筆品質(檢查門檻擋的是好單還壞單)
blocked = s4[s4.tier_at_entry < 1.0]
kept = s4[s4.tier_at_entry >= 1.0]
print(f"\n被門檻擋掉{len(blocked)}筆: 原始中位{blocked.ret60.median():+.2f}%/勝率{(blocked.ret60 > 0).mean() * 100:.0f}% "
      f"超額中位{blocked.excess60.median():+.2f}%")
print(f"保留{len(kept)}筆: 原始中位{kept.ret60.median():+.2f}%/勝率{(kept.ret60 > 0).mean() * 100:.0f}% "
      f"超額中位{kept.excess60.median():+.2f}%")
