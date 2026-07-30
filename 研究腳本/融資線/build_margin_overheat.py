# -*- coding: utf-8 -*-
"""融資過熱→短線下跌?(使用者2026-07-14提問,H1警戒帶的鏡像:上緣有沒有「過熱線」)
預先聲明三訊號(單一參數組,不掃):
  S1 維持率240日位階≥95(水準極端)
  S2 維持率20日變化的240日位階≥95(急升=槓桿加速)
  S3 融資金額20日增速的240日位階≥95(散戶追價金流)
判準:狀態日前瞻3/5/10/20日 vs 全樣本基準;另做事件版(首日進入狀態,去重20日)避免重疊日灌水。
機制註記:下緣斷頭線有制度機制(強制賣壓),上緣無制度線→只用位階版;
H0已證維持率短線≈指數本身,S1/S2預期≈指數過熱測試(動能通常正drift),S3才有槓桿獨立資訊。
用法: python build_margin_overheat.py (依賴build_margin_maintenance.py的快取)
"""
import pandas as pd

df = pd.read_pickle("tmp_margin_maintenance.pkl")
raw = pd.read_pickle("tmp_margin_total.pkl")
m = raw[raw["name"] == "MarginPurchaseMoney"].copy()
m["date"] = pd.to_datetime(m["date"])
m = m.set_index("date").sort_index()["TodayBalance"].astype(float)
px = pd.read_pickle("tmp_twii_long.pkl")
px.index = pd.to_datetime(px.index).tz_localize(None)
df = df.join(px.rename("P"), how="inner").join(m.rename("M"), how="inner")

for k in (3, 5, 10, 20):
    df[f"f{k}"] = (df.P.shift(-k) / df.P - 1) * 100
base = {k: (df[f"f{k}"].median(), (df[f"f{k}"] > 0).mean() * 100) for k in (3, 5, 10, 20)}
print("無條件基準: " + "  ".join(f"{k}日中位{base[k][0]:+.2f}%/勝率{base[k][1]:.0f}%" for k in (3, 5, 10, 20)))

df["mm_chg20"] = df.mm.diff(20)
df["m_grow20"] = df.M.pct_change(20) * 100
sigs = {
    "S1 維持率位階≥95": df.pos >= 95,
    "S2 維持率20日急升位階≥95": df.mm_chg20.rolling(240).rank(pct=True).mul(100) >= 95,
    "S3 融資金額20日增速位階≥95": df.m_grow20.rolling(240).rank(pct=True).mul(100) >= 95,
}
for name, s in sigs.items():
    s = s.fillna(False)
    print(f"\n===== {name} | 狀態日{s.sum()}日({s.mean() * 100:.1f}%) =====")
    print("  狀態日: " + "  ".join(
        f"{k}日中位{df.loc[s, f'f{k}'].median():+.2f}%/勝率{(df.loc[s, f'f{k}'] > 0).mean() * 100:.0f}%"
        for k in (3, 5, 10, 20)))
    # 事件版:首日進入狀態,去重20交易日
    enter = s & ~s.shift(1, fill_value=False)
    evs = []
    for d in df.index[enter]:
        if not evs or (df.index.get_loc(d) - df.index.get_loc(evs[-1])) > 20:
            evs.append(d)
    vals = df.loc[evs]
    print(f"  事件版(n={len(evs)}): " + "  ".join(
        f"{k}日中位{vals[f'f{k}'].median():+.2f}%/勝率{(vals[f'f{k}'] > 0).mean() * 100:.0f}%"
        for k in (3, 5, 10, 20)))
    # 逐年狀態日20日前瞻(看是否某regime才有效)
    yr = df[s].groupby(df[s].index.year)["f20"].median()
    neg = {y: round(v, 1) for y, v in yr.items() if pd.notna(v) and v < 0}
    print(f"  20日前瞻為負的年份: {neg if neg else '無'}")
