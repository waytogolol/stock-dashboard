# -*- coding: utf-8 -*-
"""當沖×借券費率一年快看v2(2026-07-29,套13條思維自查後改版:
#9三問先驗攤開/#12逐日CAR k=1,2,3,5,10,20+可交易性T+1開盤版/#13絕對與demean並列/
#1市場層加總比率/#5款13制度鉤子註記。1年=2025-08~2026-07單regime,只判「有沒有料值得回補全史」。
三問先驗:
  D1 當沖比率水準: 誰被迫?沒有人=先驗偏空(雜訊/輪動),照測但別期待。
  D2 當沖暴增: 短線客突然湧入=擁擠新資訊,無被迫者=中性。
  D3 當沖客大賠(Sell<Buy): 有被迫者✓=尾盤強制回補/被迫留倉,本卷機制最強格;
     ⚠大賠日常在跌停/漲停附近→紙上版與T+1開盤版必列。
  L1 費率水準: 空方付高費率=informed short(文獻先驗負),無被迫。
  L2 費率跳升: 券源枯竭,若後續漲=軋空被迫回補✓=第二機制格。
  #5鉤子: 當沖佔比>60%=款13注意成分→處置加時12日(計時器v2資料源),獨立於本卷判決。"""
import glob
import sqlite3
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
KS = [1, 2, 3, 5, 10, 20]

_parts = [pd.read_pickle(f) for f in sorted(glob.glob("tmp_dtlend_p*.pkl"))]
_all = pd.concat(_parts, ignore_index=True)
dt = _all[_all.ds == "dt"].drop(columns=["ds"]).copy()
ln = _all[_all.ds == "ln"].dropna(subset=["fee_rate"]).copy()
dt["date"] = pd.to_datetime(dt.date)
ln["date"] = pd.to_datetime(ln.date)
dt = dt[(dt.stock_id.str.len() == 4) & (~dt.stock_id.str.startswith("00"))]
ln = ln[(ln.stock_id.str.len() == 4) & (~ln.stock_id.str.startswith("00"))]
codes = sorted(set(dt.stock_id) | set(ln.stock_id))

conn = sqlite3.connect("capital_flow.db", timeout=60)
ph = ",".join("?" * len(codes))
px = pd.read_sql(f"SELECT date, code, open, close, volume, money FROM fm_daily_price "
                 f"WHERE code IN ({ph}) AND date>='2025-06-01' AND close>0", conn,
                 params=codes, parse_dates=["date"])
tai = pd.read_sql("SELECT date, close FROM index_daily WHERE market='TAIEX' AND date>='2025-06-01' "
                  "ORDER BY date", conn, parse_dates=["date"]).set_index("date").close
conn.close()
close = px.pivot(index="date", columns="code", values="close")
op = px.pivot(index="date", columns="code", values="open")
vol = px.pivot(index="date", columns="code", values="volume")
money = px.pivot(index="date", columns="code", values="money")
amt20 = money.rolling(20).mean() / 1e8
fwd = {k: (close.shift(-k) / close - 1) * 100 for k in KS}
# T+1開盤進場版: 事件日t→t+1開盤買,持到t+1+k收盤
fwd_o = {k: (close.shift(-(k + 1)) / op.shift(-1) - 1) * 100 for k in KS}
uni = amt20 >= 0.3


def stats(evs, fwdmap, ks=KS, dm=True):
    """回傳{k: (raw_med, raw_win, dm_med, dm_win, n)}——#13絕對與demean並列。"""
    out = {}
    for k in ks:
        raws, dms = [], []
        for d, g in evs.groupby("date"):
            if d not in fwdmap[k].index:
                continue
            row = fwdmap[k].loc[d]
            u = uni.loc[d] if d in uni.index else None
            base = row[u.index[u.fillna(False)]].median() if (dm and u is not None) else np.nan
            for c in g.code:
                v = row.get(c)
                if pd.notna(v):
                    raws.append(v)
                    if pd.notna(base):
                        dms.append(v - base)
        r, dmv = pd.Series(raws), pd.Series(dms)
        out[k] = ((r.median(), (r > 0).mean() * 100) if len(r) else (None, None),
                  (dmv.median(), (dmv > 0).mean() * 100) if len(dmv) else (None, None), len(r))
    return out


def car_line(label, evs, fwdmap):
    st = stats(evs, fwdmap)
    n = st[KS[0]][2]
    raw = " ".join(f"k{k}{st[k][0][0]:+.2f}/{st[k][0][1]:.0f}%" if st[k][0][0] is not None
                   else f"k{k}—" for k in KS)
    dmv = " ".join(f"k{k}{st[k][1][0]:+.2f}" if st[k][1][0] is not None else f"k{k}—" for k in KS)
    print(f"  {label}(n={n})\n    絕對: {raw}\n    demean: {dmv}")
    return st


def dedup(evs, idx, gap=10):
    keep, last = [], {}
    pos = {d: i for i, d in enumerate(idx)}
    for r in evs.sort_values(["code", "date"]).itertuples():
        if r.date in pos and pos[r.date] - last.get(r.code, -99) >= gap:
            keep.append((r.date, r.code))
            last[r.code] = pos[r.date]
    return pd.DataFrame(keep, columns=["date", "code"])


dt_r = dt.rename(columns={"stock_id": "code"})
dtp = dt_r.pivot_table(index="date", columns="code", values="Volume", aggfunc="sum")
buyp = dt_r.pivot_table(index="date", columns="code", values="BuyAmount", aggfunc="sum")
sellp = dt_r.pivot_table(index="date", columns="code", values="SellAmount", aggfunc="sum")
ratio = (dtp / vol.reindex_like(dtp)).clip(0, 1)
pnl = (sellp - buyp) / buyp.replace(0, np.nan) * 100

# ===== #1 市場層加總比率 =====
print("=" * 64 + "\n[市場層] Σ當沖買進金額/Σ全市場成交額(加總後算比率)")
mkt_dt = buyp.sum(axis=1) / money.reindex_like(dtp).sum(axis=1) * 100
tai_fwd = {k: (tai.shift(-k) / tai - 1) * 100 for k in (5, 10, 20)}
q = pd.qcut(mkt_dt, 5, labels=False, duplicates="drop")
print(f"  佔比分布 p10={mkt_dt.quantile(.1):.1f}% p50={mkt_dt.median():.1f}% p90={mkt_dt.quantile(.9):.1f}%")
for qq in (0, 4):
    days_q = mkt_dt.index[q == qq]
    line = "  ".join(f"f{k} {tai_fwd[k].reindex(days_q).median():+.2f}%/"
                     f"{(tai_fwd[k].reindex(days_q) > 0).mean() * 100:.0f}%" for k in (5, 10, 20))
    print(f"  投機溫度{'最低' if qq == 0 else '最高'}20%日({len(days_q)}天)→大盤 {line}")

# ===== D1 =====
print("=" * 64 + "\n[D1] 當沖比率五分位(三問:無被迫者=先驗偏空)")
recs = []
for d in ratio.index:
    if d not in uni.index:
        continue
    u = uni.loc[d]
    r = ratio.loc[d][u.index[u.fillna(False)]].dropna()
    if len(r) < 50:
        continue
    qd = pd.qcut(r, 5, labels=False, duplicates="drop")
    recs.extend({"date": d, "code": c, "q": v} for c, v in qd.items())
d1 = pd.DataFrame(recs)
for qq in (0, 2, 4):
    car_line(f"Q{qq + 1}{'(低)' if qq == 0 else '(高當沖)' if qq == 4 else ''}",
             d1[d1.q == qq][["date", "code"]], fwd)

# ===== D2 =====
print("=" * 64 + "\n[D2] 當沖暴增(ratio≥30%∧比20日均+15pp,10日去重)")
ma20 = ratio.rolling(20, min_periods=15).mean()
spike = (ratio >= 0.3) & (ratio - ma20 >= 0.15) & uni.reindex_like(ratio)
ev = spike.stack()
ev = ev[ev].reset_index().rename(columns={"level_1": "code"})[["date", "code"]]
d2 = dedup(ev, ratio.index)
car_line("暴增事件", d2, fwd)

# ===== D3 =====
print("=" * 64 + "\n[D3] 當沖客大賠日(機制最強格:有人被迫;⚠常在漲跌停附近→兩版並列)")
loss = (pnl <= -3) & (ratio >= 0.2) & uni.reindex_like(ratio)
ev3 = loss.stack()
ev3 = ev3[ev3].reset_index().rename(columns={"level_1": "code"})[["date", "code"]]
print(" 紙上版(事件日收盤進):")
car_line("大賠日", ev3, fwd)
print(" 可交易版(T+1開盤進,持到T+1+k收):")
car_line("大賠日T+1開", ev3, fwd_o)
win3 = (pnl >= 3) & (ratio >= 0.2) & uni.reindex_like(ratio)
evw = win3.stack()
evw = evw[evw].reset_index().rename(columns={"level_1": "code"})[["date", "code"]]
print(" 對照·大賺日(紙上):")
car_line("大賺日", evw, fwd)

# ===== 借券 =====
ln_r = ln.rename(columns={"stock_id": "code"})
ln_r["fv"] = ln_r.fee_rate * ln_r.volume
g = ln_r.groupby(["date", "code"]).agg(fv=("fv", "sum"), v=("volume", "sum"))
g["vwfee"] = g.fv / g.v
vwfee = g.reset_index().pivot(index="date", columns="code", values="vwfee")
print("=" * 64 + f"\n[L1] 借券費率五分位(informed short先驗=高費率偏負) "
      f"費率p50={np.nanmedian(vwfee):.2f}% p90={np.nanquantile(vwfee.values, .9):.2f}%")
recs = []
for d in vwfee.index:
    if d not in uni.index:
        continue
    u = uni.loc[d]
    cand = [c for c in u.index[u.fillna(False)] if c in vwfee.columns]
    r = vwfee.loc[d][cand].dropna()
    if len(r) < 30:
        continue
    qd = pd.qcut(r.rank(method="first"), 5, labels=False, duplicates="drop")
    recs.extend({"date": d, "code": c, "q": v} for c, v in qd.items())
l1 = pd.DataFrame(recs)
for qq in (0, 4):
    car_line(f"Q{qq + 1}{'(低費率)' if qq == 0 else '(hard-to-borrow)'}",
             l1[l1.q == qq][["date", "code"]], fwd)

print("=" * 64 + "\n[L2] 費率跳升(vs自身20日中位+2pp∧≥3%,10日去重;軋空假說=被迫回補✓)")
med20 = vwfee.rolling(20, min_periods=10).median()
jump = (vwfee - med20 >= 2) & (vwfee >= 3) & uni.reindex_like(vwfee)
evj = jump.stack()
evj = evj[evj].reset_index().rename(columns={"level_1": "code"})[["date", "code"]]
l2 = dedup(evj, vwfee.index)
car_line("費率跳升", l2, fwd)
# L2×價格方向: 跳升時已跌(空方壓制) vs 已漲(軋空中)
ret20 = (close / close.shift(20) - 1) * 100
l2m = l2.merge(l2.apply(lambda r: ret20.loc[r.date, r.code]
                        if r.date in ret20.index else np.nan, axis=1).rename("r20"),
               left_index=True, right_index=True)
car_line("跳升∧已漲(r20>+10)", l2m[l2m.r20 > 10][["date", "code"]], fwd)
car_line("跳升∧已跌(r20<-10)", l2m[l2m.r20 < -10][["date", "code"]], fwd)

print("=" * 64 + "\n[#5鉤子註記] 當沖佔比>60%股-日數(款13注意成分,餵計時器v2):",
      int(((ratio > 0.6) & uni.reindex_like(ratio)).sum().sum()))

# ===== H-A 題材波段因子(使用者假說:熱門股當沖高→當沖=抓題材波段的因子?) =====
# #1加總後算比率(題材Σ當沖金額/Σ成交額)+#2細分題材(main_group)+成員>=3(#3)
print("=" * 64 + "\n[H-A] 題材層當沖佔比→題材fwd(加總後算比率,成員>=3)")
_c = sqlite3.connect("capital_flow.db", timeout=60)
cls = pd.read_sql("SELECT DISTINCT code, main_group FROM classification WHERE country='台'", _c)
_c.close()
grp = {}
for r in cls.itertuples():
    grp.setdefault(str(r.code), []).append(r.main_group)
th_rows = []
for d in ratio.index:
    if d not in money.index:
        continue
    buy_d, mon_d = buyp.loc[d], money.loc[d]
    agg = {}
    for c in buy_d.index:
        if pd.isna(buy_d[c]) or c not in grp:
            continue
        m = mon_d.get(c)
        if pd.isna(m) or m <= 0:
            continue
        for g_ in grp[c]:
            a = agg.setdefault(g_, [0.0, 0.0, 0])
            a[0] += buy_d[c]
            a[1] += m
            a[2] += 1
    for g_, (b, m, n) in agg.items():
        if n >= 3:
            th_rows.append({"date": d, "theme": g_, "dtpct": b / m * 100})
th = pd.DataFrame(th_rows)
# 題材fwd = 成員中位fwd(等權口徑);挑10/20日
th_fwd = {}
for k in (10, 20):
    rows = {}
    for d in ratio.index:
        if d not in fwd[k].index:
            continue
        row = fwd[k].loc[d]
        rows[d] = {g_: np.nanmedian([row.get(c) for c in cls[cls.main_group == g_].code
                                     if pd.notna(row.get(c))] or [np.nan])
                   for g_ in th[th.date == d].theme.unique()}
    th_fwd[k] = rows
th["rk"] = th.groupby("date").dtpct.rank(pct=True)
for lab, m_ in (("當沖佔比前20%題材", th.rk >= 0.8), ("後20%題材", th.rk <= 0.2)):
    sub = th[m_]
    for k in (10, 20):
        vals = [th_fwd[k].get(r.date, {}).get(r.theme) for r in sub.itertuples()]
        vals = pd.Series([v for v in vals if v is not None and pd.notna(v)])
        alln = [v for d_, dd in th_fwd[k].items() for v in dd.values() if pd.notna(v)]
        base = np.median(alln)
        if len(vals):
            print(f"  {lab} f{k}: 絕對{vals.median():+.2f}%/{(vals > 0).mean() * 100:.0f}%"
                  f" demean{vals.median() - base:+.2f}pp (題材-日n={len(vals)})")
# Δ版: 題材當沖佔比5日均-20日均(加速)前20%
thp = th.pivot_table(index="date", columns="theme", values="dtpct")
dacc = thp.rolling(5).mean() - thp.rolling(20).mean()
th2 = dacc.stack().rename("acc").reset_index().rename(columns={"level_1": "theme"})
th2["rk"] = th2.groupby("date").acc.rank(pct=True)
sub = th2[th2.rk >= 0.8]
for k in (10, 20):
    vals = [th_fwd[k].get(r.date, {}).get(r.theme) for r in sub.itertuples()]
    vals = pd.Series([v for v in vals if v is not None and pd.notna(v)])
    alln = [v for d_, dd in th_fwd[k].items() for v in dd.values() if pd.notna(v)]
    if len(vals):
        print(f"  當沖加速前20%題材 f{k}: 絕對{vals.median():+.2f}%/{(vals > 0).mean() * 100:.0f}%"
              f" demean{vals.median() - np.median(alln):+.2f}pp (n={len(vals)})")

# ===== H-A2 題材層借券聚合(使用者補充:借券也合計到產業層,跨產業比較) =====
print("=" * 64 + "\n[H-A2] 題材層借券(成員量加權費率+借券量/成交量,成員>=3,跨題材rank)")
lnj = ln_r.copy()
lnj["gs"] = lnj.code.map(lambda c: grp.get(c))
lnj = lnj.explode("gs").dropna(subset=["gs"])
tha = lnj.groupby(["date", "gs"]).agg(fv=("fv", "sum"), v=("volume", "sum"),
                                      nmem=("code", "nunique")).reset_index()
tha = tha[tha.nmem >= 3]
tha["vwfee"] = tha.fv / tha.v
# 借券量/題材成交量
mon_th = {}
for r in tha.itertuples():
    d = r.date
    if d not in vol.index:
        continue
    mems = [c for c in cls[cls.main_group == r.gs].code if c in vol.columns]
    tv = vol.loc[d, mems].sum()
    mon_th[(d, r.gs)] = r.v * 1000 / tv if tv > 0 else np.nan
tha["lvr"] = [mon_th.get((r.date, r.gs), np.nan) for r in tha.itertuples()]
for col, lab in (("vwfee", "題材加權借券費率"), ("lvr", "題材借券量/成交量")):
    tt = tha.dropna(subset=[col]).copy()
    tt["rk"] = tt.groupby("date")[col].rank(pct=True)
    for side, m_ in ((f"{lab}前20%", tt.rk >= 0.8), (f"{lab}後20%", tt.rk <= 0.2)):
        sub = tt[m_]
        for k in (10, 20):
            vals = [th_fwd[k].get(r.date, {}).get(r.gs) for r in sub.itertuples()]
            vals = pd.Series([v for v in vals if v is not None and pd.notna(v)])
            alln = [v for d_, dd in th_fwd[k].items() for v in dd.values() if pd.notna(v)]
            if len(vals) >= 30:
                print(f"  {side} f{k}: 絕對{vals.median():+.2f}%/{(vals > 0).mean() * 100:.0f}%"
                      f" demean{vals.median() - np.median(alln):+.2f}pp (n={len(vals)})")

# ===== H-B 飆股指紋(使用者假說:短期漲很兇的股票,當沖/借券切得出誰續漲?) =====
# 池=r20>=+40%∧amt20>=0.3億,20日去重;先驗=漲觸發排雷鐵律(追高全負),找的是池內分化
# =漲觸發「升級組事前切不開」的復活刀候選。#13絕對+demean並列;#12短天期CAR。
print("=" * 64 + "\n[H-B] 飆股池指紋(r20>=+40%∧amt>=0.3億,20日去重)")
r20全 = (close / close.shift(20) - 1) * 100
pool = (r20全 >= 40) & uni
evp = pool.stack()
evp = evp[evp].reset_index().rename(columns={"level_1": "code"})[["date", "code"]]
hb = dedup(evp, close.index, gap=20)
ratio5 = ratio.rolling(5).mean()
feat = []
for r in hb.itertuples():
    d, c = r.date, r.code
    f5 = ratio5.loc[d].get(c) if d in ratio5.index else np.nan
    f20m = ratio.rolling(20).mean().loc[d].get(c) if d in ratio.index else np.nan
    fee_recent = np.nan
    if c in vwfee.columns:
        s = vwfee[c].loc[:d].dropna().tail(5)
        fee_recent = s.iloc[-1] if len(s) else np.nan
    feat.append({"date": d, "code": c, "ratio5": f5,
                 "dratio": (f5 - f20m) if pd.notna(f5) and pd.notna(f20m) else np.nan,
                 "fee": fee_recent})
hbf = pd.DataFrame(feat)
print(f"  飆股事件n={len(hbf)} | 有當沖值{hbf.ratio5.notna().sum()} 有借券費率{hbf.fee.notna().sum()}")
base_st = car_line("飆股池全體(排雷鐵律基準)", hbf[["date", "code"]], fwd)
for col, cuts in (("ratio5", None), ("dratio", None), ("fee", None)):
    v = hbf[hbf[col].notna()]
    if len(v) < 30:
        print(f"  {col}: n={len(v)}太小跳過")
        continue
    t = v[col].quantile([1 / 3, 2 / 3]).values
    lo = v[v[col] <= t[0]]
    hi = v[v[col] >= t[1]]
    print(f" 池內{col}三分位(低{t[0]:.2f}/高{t[1]:.2f}):")
    car_line(f"  {col}低組", lo[["date", "code"]], fwd)
    car_line(f"  {col}高組", hi[["date", "code"]], fwd)
# 無借券成交組(冷門飆股)對照
nofee = hbf[hbf.fee.isna()]
if len(nofee) >= 20:
    car_line(" 無借券成交組(空方缺席)", nofee[["date", "code"]], fwd)
# 2x2: 當沖高×費率高
if hbf.ratio5.notna().sum() >= 60 and hbf.fee.notna().sum() >= 60:
    rmed = hbf.ratio5.median()
    fmed = hbf[hbf.fee.notna()].fee.median()
    both = hbf[(hbf.ratio5 > rmed) & (hbf.fee > fmed)]
    neither = hbf[(hbf.ratio5 <= rmed) & (hbf.fee.notna()) & (hbf.fee <= fmed)]
    print(" 2x2(#5疊加):")
    car_line("  當沖高∧費率高", both[["date", "code"]], fwd)
    car_line("  當沖低∧費率低", neither[["date", "code"]], fwd)
