# -*- coding: utf-8 -*-
"""型態共振探勘 v1 — 嚴格樣本內(2022-2024)，保留集(2025-2026)本輪不碰
三路線: A)預註冊型態庫12種 B)連續特徵三分位掃描 C)價格路徑形狀聚類(numpy kmeans)
防過擬合: 候選定義先寫死於本檔(pre-register)；晉級=樣本內逐年一致+改善；輸出全部結果含失敗
輸出: tmp_pattern_mine.txt
"""
import os
os.environ.setdefault("CF_DB", "research_2022.db")
import io
import pickle
import sys

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, ".")
from case_study_theme import add_signals, load, theme_series
from scan_signals import BROAD, find_triggers

WARMUP = 13
TRAIN_END = "2024-12-31"          # 樣本內截止；之後為保留集，本輪不評估
PRICE_CACHE = "tmp_bear_prices.pkl"
DAILY_CACHE = "tmp_mine_daily.pkl"   # 含Volume的新快取

rankings, cls = load()
dates = sorted(rankings["snapshot_date"].unique())
tw = rankings[rankings["country"] == "台"]

# ── 觸發掃描(與bear_test配置B一致) ──
BROAD_B = BROAD - {"航運", "造船", "品牌3C"}
tw_groups = set(cls[cls["country"] == "台"]["main_group"].unique())
counts = cls.groupby("main_group")["code"].count()
themes = sorted(g for g in cls["main_group"].unique()
                if g in tw_groups and counts.get(g, 0) >= 3 and g not in BROAD_B)
hits = []
for th in themes:
    df = add_signals(theme_series(rankings, cls, th))
    for t in find_triggers(df):
        if str(t["date"]) <= dates[WARMUP]:
            continue
        t["theme"] = th
        hits.append(t)
hits.sort(key=lambda x: str(x["date"]))

tw_cls = cls[cls["country"] == "台"]


def top3(theme, d):
    mem = set(tw_cls[tw_cls["main_group"] == theme]["code"])
    wk = tw[(tw["snapshot_date"] == d) & (tw["code"].isin(mem))]
    return list(wk.sort_values("twd", ascending=False)["code"].head(3))


for h in hits:
    h["members"] = top3(h["theme"], str(h["date"]))

with open(PRICE_CACHE, "rb") as f:
    pc = pickle.load(f)


def px_ret8(code, d):
    s = pc.get(code)
    if s is None:
        return None
    d0 = pd.Timestamp(d)
    a = s[s.index <= d0]
    b = s[s.index <= d0 + pd.Timedelta(weeks=8)]
    if not len(a) or not len(b) or a.iloc[-1] <= 0:
        return None
    if d0 + pd.Timedelta(weeks=8) > s.index[-1]:
        return None
    return float(b.iloc[-1] / a.iloc[-1] - 1)


for h in hits:
    rs = [px_ret8(m, str(h["date"])) for m in h["members"]]
    rs = [r for r in rs if r is not None]
    h["pret8"] = sum(rs) / len(rs) if rs else None

train = [h for h in hits if str(h["date"]) <= TRAIN_END and h["pret8"] is not None]
print(f"觸發全樣本{len(hits)}，樣本內(<={TRAIN_END}) {len(train)} 筆——本輪只用這些")

# ── 日線(含量) ──
need = sorted(set(m for h in train for m in h["members"]))
if os.path.exists(DAILY_CACHE):
    with open(DAILY_CACHE, "rb") as f:
        dc = pickle.load(f)
else:
    dc = {}
todo = [c for c in need if c not in dc]
for i in range(0, len(todo), 40):
    chunk = todo[i:i + 40]
    rem = list(chunk)
    for sfx in (".TW", ".TWO"):
        if not rem:
            break
        df0 = yf.download([f"{c}{sfx}" for c in rem], start="2021-08-01", end="2025-03-01",
                          interval="1d", group_by="ticker", auto_adjust=True,
                          threads=True, progress=False)
        got = []
        for c in rem:
            try:
                sub = (df0[f"{c}{sfx}"] if len(rem) > 1 else df0)[["Open", "High", "Low", "Close", "Volume"]].dropna()
                if len(sub) > 50:
                    dc[c] = sub
                    got.append(c)
            except Exception:
                pass
        rem = [c for c in rem if c not in got]
    for c in chunk:
        dc.setdefault(c, None)
    with open(DAILY_CACHE, "wb") as f:
        pickle.dump(dc, f)
print(f"日線(含量)覆蓋 {sum(1 for c in need if dc.get(c) is not None)}/{len(need)}")


def hist(code, d, n=130):
    df0 = dc.get(code)
    if df0 is None:
        return None
    out = df0[df0.index <= pd.Timestamp(d)]
    return out.tail(n) if len(out) >= 65 else None


# ══ 路線A: 預註冊型態庫(定義寫死) ══
def pat_volume_bar(w):
    """A1 帶量長紅: 週內有日 漲幅>=4% 且 量>=20日均量2倍"""
    d10 = w.tail(6)
    for i in range(1, len(d10)):
        chg = d10["Close"].iloc[i] / d10["Close"].iloc[i - 1] - 1
        v20 = w["Volume"].tail(26).head(20).mean()
        if chg >= 0.04 and v20 > 0 and d10["Volume"].iloc[i] >= 2 * v20:
            return True
    return False


def pat_new_high(w, days):
    """A2-4 N日新高: 最新收盤>之前N日曆天最高收盤"""
    px = float(w["Close"].iloc[-1])
    cutoff = w.index[-1] - pd.Timedelta(days=days)
    prior = w[(w.index < w.index[-1]) & (w.index >= cutoff)]
    return len(prior) >= 15 and px > float(prior["Close"].max())


def pat_gap_nh(w):
    """A5 突破跳空: 週內某日 低>昨高 且 收盤創60日新高(已驗對照)"""
    tail = w.tail(6)
    for i in range(1, len(tail)):
        di = tail.index[i]
        if float(tail["Low"].iloc[i]) <= float(tail["High"].iloc[i - 1]):
            continue
        prior = w[(w.index < di) & (w.index >= di - pd.Timedelta(days=60))]
        if len(prior) >= 15 and float(tail["Close"].iloc[i]) > float(prior["Close"].max()):
            return True
    return False


def pat_ma_bull(w):
    """A6 均線多頭排列: 收>MA5>MA20>MA60"""
    c = w["Close"]
    if len(c) < 60:
        return False
    m5, m20, m60 = c.tail(5).mean(), c.tail(20).mean(), c.tail(60).mean()
    return float(c.iloc[-1]) > m5 > m20 > m60


def pat_squeeze_break(w):
    """A7 波動壓縮後突破: 近20日報酬std/近60日std<=0.7 且 收盤創20日新高"""
    r = w["Close"].pct_change().dropna()
    if len(r) < 60:
        return False
    if r.tail(20).std() / r.tail(60).std() > 0.7:
        return False
    return float(w["Close"].iloc[-1]) >= float(w["Close"].tail(20).max())


def pat_higher_low(w):
    """A8 回踩不破: 近10日最低>前30日(不含近10日)最低 且 收>MA20"""
    if len(w) < 45:
        return False
    lo10 = float(w["Low"].tail(10).min())
    lo_prior = float(w["Low"].tail(40).head(30).min())
    return lo10 > lo_prior and float(w["Close"].iloc[-1]) > w["Close"].tail(20).mean()


def pat_rs(w, twii_ret):
    """A9 相對強度: 近65交易日報酬 > 大盤同期"""
    c = w["Close"]
    if len(c) < 65:
        return False
    return float(c.iloc[-1] / c.iloc[-65] - 1) > twii_ret


def pat_engulf(w):
    """A10 週線吞噬: 以日線重組週K，本週紅K實體吞噬前週實體"""
    wk = w.resample("W-SUN").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last"}).dropna()
    if len(wk) < 2:
        return False
    a, b = wk.iloc[-2], wk.iloc[-1]
    return (b["Close"] > b["Open"] and b["Open"] <= min(a["Open"], a["Close"])
            and b["Close"] >= max(a["Open"], a["Close"]))


def pat_above_ma20(w):
    """A12 站上月線: 收>MA20"""
    return len(w) >= 20 and float(w["Close"].iloc[-1]) > w["Close"].tail(20).mean()


twii = yf.download("^TWII", start="2021-08-01", end="2025-03-01", interval="1d",
                   auto_adjust=True, progress=False)["Close"]
if isinstance(twii, pd.DataFrame):
    twii = twii.iloc[:, 0]


def twii_ret65(d):
    s = twii[twii.index <= pd.Timestamp(d)]
    return float(s.iloc[-1] / s.iloc[-65] - 1) if len(s) >= 65 else 0.0


PATS = {
    "A1帶量長紅(≥1)": (pat_volume_bar, 1),
    "A2_60日新高(≥2)": (lambda w: pat_new_high(w, 60), 2),
    "A3_90日新高(≥2)*對照": (lambda w: pat_new_high(w, 90), 2),
    "A4_120日新高(≥2)": (lambda w: pat_new_high(w, 120), 2),
    "A5突破跳空(≥1)*對照": (pat_gap_nh, 1),
    "A6均線多頭排列(≥2)": (pat_ma_bull, 2),
    "A7波動壓縮突破(≥1)": (pat_squeeze_break, 1),
    "A8回踩不破(≥2)": (pat_higher_low, 2),
    "A10週線吞噬(≥1)": (pat_engulf, 1),
    "A12全員站上月線(3/3)": (pat_above_ma20, 3),
}

for h in train:
    ws = {m: hist(m, str(h["date"])) for m in h["members"]}
    tr = twii_ret65(str(h["date"]))
    for name, (fn, k) in PATS.items():
        cnt = sum(1 for m, w in ws.items() if w is not None and fn(w))
        h[name] = cnt >= k
    h["A9相對強度(≥2)"] = sum(1 for m, w in ws.items() if w is not None and pat_rs(w, tr)) >= 2
    # A11 成員離散度(低=共振): 近20日報酬 成員間std
    rets = [float(w["Close"].iloc[-1] / w["Close"].iloc[-20] - 1) for w in ws.values()
            if w is not None and len(w) >= 20]
    h["_disp"] = float(np.std(rets)) if len(rets) >= 2 else None
    # 連續特徵(路線B)
    feats = {}
    f_list = []
    for m, w in ws.items():
        if w is None or len(w) < 65:
            continue
        c = w["Close"]
        r = c.pct_change().dropna()
        hi60 = float(c.tail(60).max())
        f_list.append({
            "dist_high": float(c.iloc[-1]) / hi60 - 1,
            "squeeze": float(r.tail(20).std() / r.tail(60).std()) if r.tail(60).std() > 0 else 1,
            "vol_trend": float(w["Volume"].tail(10).mean() / w["Volume"].tail(60).mean()) if w["Volume"].tail(60).mean() > 0 else 1,
            "rs65": float(c.iloc[-1] / c.iloc[-65] - 1) - tr,
            "above_ma20": float(c.iloc[-1] / c.tail(20).mean() - 1),
            "ret20": float(c.iloc[-1] / c.iloc[-20] - 1),
        })
    for k2 in ["dist_high", "squeeze", "vol_trend", "rs65", "above_ma20", "ret20"]:
        h[f"F_{k2}"] = float(np.mean([x[k2] for x in f_list])) if f_list else None

ALL_PATS = list(PATS.keys()) + ["A9相對強度(≥2)"]
med_disp = float(np.median([h["_disp"] for h in train if h["_disp"] is not None]))
for h in train:
    h["A11成員低離散(共振)"] = h["_disp"] is not None and h["_disp"] < med_disp
ALL_PATS.append("A11成員低離散(共振)")

out = io.open("tmp_pattern_mine.txt", "w", encoding="utf-8")
out.write(f"型態探勘 樣本內(2022-04~2024-12) n={len(train)}；保留集未觸碰\n")
base = pd.Series([h["pret8"] for h in train])
out.write(f"基準(全部觸發): 勝率{(base > 0).mean():.0%} 中位{base.median():+.1%} 平均{base.mean():+.1%}\n\n")

# ── 路線A報告: 逐年一致性 ──
out.write("== 路線A: 預註冊型態庫(通過=型態成立時進場) ==\n")
out.write(f"{'型態':<24}{'n':>4}{'勝率':>6}{'中位':>8}{'平均':>8}  22/23/24年中位\n")
resA = []
for name in ALL_PATS:
    sel = [h for h in train if h.get(name)]
    pr = pd.Series([h["pret8"] for h in sel])
    if len(pr) < 8:
        out.write(f"{name:<24}{len(pr):>4}  樣本不足\n")
        continue
    yrs = []
    ok_year = 0
    for y in ("2022", "2023", "2024"):
        g = pd.Series([h["pret8"] for h in sel if str(h["date"])[:4] == y])
        yrs.append(f"{g.median():+.0%}" if len(g) else "—")
        if len(g) and g.median() > base[[str(h['date'])[:4] == y for h in train]].median():
            ok_year += 1
    resA.append((name, len(pr), float((pr > 0).mean()), float(pr.median()), ok_year))
    out.write(f"{name:<24}{len(pr):>4}{(pr > 0).mean():>6.0%}{pr.median():>8.1%}{pr.mean():>8.1%}  {'/'.join(yrs)} 逐年勝出{ok_year}/3\n")

# ── 路線B報告: 特徵三分位 ──
out.write("\n== 路線B: 連續特徵三分位(樣本內, 檢查單調性) ==\n")
for f in ["dist_high", "squeeze", "vol_trend", "rs65", "above_ma20", "ret20"]:
    vals = [(h[f"F_{f}"], h["pret8"]) for h in train if h.get(f"F_{f}") is not None]
    if len(vals) < 30:
        continue
    vals.sort()
    n3 = len(vals) // 3
    terc = [vals[:n3], vals[n3:2 * n3], vals[2 * n3:]]
    stats = [(pd.Series([x[1] for x in t]).median(), (pd.Series([x[1] for x in t]) > 0).mean()) for t in terc]
    mono = "↑單調" if stats[0][0] < stats[1][0] < stats[2][0] else ("↓單調" if stats[0][0] > stats[1][0] > stats[2][0] else "非單調")
    out.write(f"{f:<12} 低/中/高三分位中位: " +
              " | ".join(f"{m:+.1%}(勝{w:.0%})" for m, w in stats) + f"  {mono}\n")

# ── 路線C: 形狀聚類(前60交易日路徑, z正規化, kmeans k=5) ──
out.write("\n== 路線C: 價格路徑形狀聚類(演算法自己找型態) ==\n")
paths, owners = [], []
for hi, h in enumerate(train):
    for m in h["members"]:
        w = hist(m, str(h["date"]), 130)
        if w is None or len(w) < 60:
            continue
        p = w["Close"].tail(60).values.astype(float)
        z = (p - p.mean()) / (p.std() + 1e-9)
        paths.append(z)
        owners.append(hi)
X = np.array(paths)
rng = np.random.default_rng(42)
K = 5
cent = X[rng.choice(len(X), K, replace=False)]
for _ in range(60):
    dist = ((X[:, None, :] - cent[None, :, :]) ** 2).sum(axis=2)
    lab = dist.argmin(axis=1)
    for k in range(K):
        if (lab == k).any():
            cent[k] = X[lab == k].mean(axis=0)
# 每筆觸發=成員多數決
trig_lab = {}
for hi, l in zip(owners, lab):
    trig_lab.setdefault(hi, []).append(l)
for hi in trig_lab:
    vals, cnts = np.unique(trig_lab[hi], return_counts=True)
    trig_lab[hi] = int(vals[cnts.argmax()])


def describe(c):
    s1 = c[19] - c[0]
    s2 = c[39] - c[20]
    s3 = c[59] - c[40]
    seg = lambda v: "升" if v > 0.5 else ("跌" if v < -0.5 else "平")
    return f"前段{seg(s1)}/中段{seg(s2)}/近段{seg(s3)}"


out.write(f"路徑{len(X)}條→{K}群(成員多數決指派觸發)\n")
for k in range(K):
    sel = [train[hi]["pret8"] for hi, l in trig_lab.items() if l == k]
    pr = pd.Series(sel)
    n_path = int((lab == k).sum())
    if len(pr):
        out.write(f"形狀{k}[{describe(cent[k])}] 路徑{n_path}條/觸發{len(pr)}筆: "
                  f"勝率{(pr > 0).mean():.0%} 中位{pr.median():+.1%}\n")
out.close()
print("done -> tmp_pattern_mine.txt")
