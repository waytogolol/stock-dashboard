# -*- coding: utf-8 -*-
"""微題材脈衝規則 2022-2026 沙盒回測（裸版=①脈衝≥2.5x+②排名跳升中位≥+35,無毛利分級）
驗證: 熱度sustain(後4週均/前4週均) + 觸發時前3大成員+8週實際股價報酬
輸出: tmp_micro_bear.txt
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
from case_study_theme import load
from micro_themes import MICRO_THEMES

WARMUP = 13
PRICE_CACHE = "tmp_bear_prices.pkl"

rankings, cls = load()
dates = sorted(rankings["snapshot_date"].unique())
tw = rankings[rankings["country"] == "台"].copy()
tw_tot = tw.groupby("snapshot_date")["twd"].sum().to_dict()   # 春節週台股休市=無該週資料
import sqlite3
_conn = sqlite3.connect(os.environ["CF_DB"])
subp = pd.read_sql("SELECT code, sub_product FROM classification WHERE country='台'", _conn)
_conn.close()
subp = subp.drop_duplicates()
subp = subp.groupby("code")["sub_product"].apply(lambda s: " ".join(str(x) for x in s if pd.notna(x)))

# 微題材成員(與正式版同法: sub_product關鍵字, 排除巨頭)
members = {}
for name, cfg in MICRO_THEMES.items():
    kws, excl = cfg["kws"], set(cfg.get("exclude", []))
    m = set(c for c, t in subp.items() if any(k.lower() in t.lower() for k in kws)) - excl
    if len(m) >= 3:
        members[name] = m
print(f"微題材 {len(members)} 個(成員>=3)")

tw_idx = tw.set_index(["snapshot_date", "code"])
score_cache, rank_cache = {}, {}
for name, mem in members.items():
    sc, rk = [], []
    for d in dates:
        wk = tw[(tw["snapshot_date"] == d) & (tw["code"].isin(mem))]
        tot = tw_tot.get(d, 0)
        sc.append(float(wk["twd"].sum() / tot * 100) if tot > 0 else 0.0)
        rk.append(dict(zip(wk["code"], wk["rank"])))
    score_cache[name] = sc
    rank_cache[name] = rk

with open(PRICE_CACHE, "rb") as f:
    pc = pickle.load(f)


def ensure_prices(codes):
    todo = [c for c in codes if c not in pc]
    for i in range(0, len(todo), 40):
        chunk = todo[i:i + 40]
        for sfx in (".TW", ".TWO"):
            rem = [c for c in chunk if pc.get(c) is None or c not in pc]
            if not rem:
                break
            df = yf.download([f"{c}{sfx}" for c in rem], start="2021-12-01", end=str(dates[-1]),
                             interval="1wk", group_by="ticker", auto_adjust=True,
                             threads=True, progress=False)
            for c in rem:
                try:
                    s = (df[f"{c}{sfx}"] if len(rem) > 1 else df)["Close"].dropna()
                    if len(s):
                        pc[c] = s
                except Exception:
                    pass
        for c in chunk:
            pc.setdefault(c, None)
    with open(PRICE_CACHE, "wb") as f2:
        pickle.dump(pc, f2)


def px_ret8(code, d):
    s = pc.get(code)
    if s is None:
        return None
    d0 = pd.Timestamp(d)
    base = s[s.index <= d0]
    fwd = s[s.index <= d0 + pd.Timedelta(weeks=8)]
    if not len(base) or not len(fwd) or base.iloc[-1] <= 0:
        return None
    if d0 + pd.Timedelta(weeks=8) > s.index[-1]:
        return None
    return float(fwd.iloc[-1] / base.iloc[-1] - 1)


# 觸發掃描
hits = []
for name, mem in members.items():
    sc = score_cache[name]
    rk = rank_cache[name]
    last = -99
    for t in range(WARMUP, len(dates)):
        med4 = float(np.median(sc[t - 4:t]))
        if med4 <= 0 or sc[t] / med4 < 2.5:
            continue
        jumps = [rk[t - 1][c] - rk[t][c] for c in rk[t] if c in rk[t - 1]]
        if not jumps or float(np.median(jumps)) < 35:
            continue
        if t - last < 4:
            last = t
            continue
        last = t
        post = sc[t + 1:t + 5]
        pre = sc[t - 4:t]
        sustain = (float(np.mean(post)) / float(np.mean(pre))) if post and np.mean(pre) > 0 else None
        top3 = sorted(rk[t], key=lambda c: rk[t][c])[:3]
        hits.append({"theme": name, "date": dates[t], "sustain": sustain, "members": top3})

need = sorted(set(c for h in hits for c in h["members"]))
ensure_prices(need)
for h in hits:
    rs = [px_ret8(c, h["date"]) for c in h["members"]]
    rs = [r for r in rs if r is not None]
    h["pret8"] = (sum(rs) / len(rs) - 0.005) if rs else None

# ── 型態濾網(與大題材同定義, 共用日線快取) ──
DAILY_CACHE = "tmp_bear_daily.pkl"
with open(DAILY_CACHE, "rb") as f:
    dc = pickle.load(f)


def ensure_daily(codes):
    todo = [c for c in codes if c not in dc]
    for i in range(0, len(todo), 40):
        chunk = todo[i:i + 40]
        rem = list(chunk)
        for sfx in (".TW", ".TWO"):
            if not rem:
                break
            df0 = yf.download([f"{c}{sfx}" for c in rem], start="2021-10-01", end=str(dates[-1]),
                              interval="1d", group_by="ticker", auto_adjust=True,
                              threads=True, progress=False)
            got = []
            for c in rem:
                try:
                    sub = (df0[f"{c}{sfx}"] if len(rem) > 1 else df0)[["High", "Low", "Close"]].dropna()
                    if len(sub):
                        dc[c] = sub
                        got.append(c)
                except Exception:
                    pass
            rem = [c for c in rem if c not in got]
        for c in chunk:
            dc.setdefault(c, None)
    with open(DAILY_CACHE, "wb") as f2:
        pickle.dump(dc, f2)


def new_high_90d(code, d):
    df0 = dc.get(code)
    if df0 is None:
        return False
    d0 = pd.Timestamp(d)
    cur = df0[df0.index <= d0]
    if len(cur) < 30:
        return False
    px = float(cur["Close"].iloc[-1])
    win = df0[(df0.index < cur.index[-1]) & (df0.index >= d0 - pd.Timedelta(days=90))]
    return len(win) >= 20 and px > float(win["Close"].max())


def gap_newhigh_week(code, d):
    df0 = dc.get(code)
    if df0 is None:
        return False
    d0 = pd.Timestamp(d)
    win = df0[df0.index <= d0].tail(8)
    for i in range(1, len(win)):
        di = win.index[i]
        if di < d0 - pd.Timedelta(days=6):
            continue
        if float(win["Low"].iloc[i]) <= float(win["High"].iloc[i - 1]):
            continue
        prior = df0[(df0.index < di) & (df0.index >= di - pd.Timedelta(days=60))]
        if len(prior) >= 15 and float(win["Close"].iloc[i]) > float(prior["Close"].max()):
            return True
    return False


ensure_daily(need)
for h in hits:
    h["nh"] = sum(1 for m in h["members"] if new_high_90d(m, h["date"]))
    h["gnh"] = sum(1 for m in h["members"] if gap_newhigh_week(m, h["date"]))

out = io.open("tmp_micro_bear.txt", "w", encoding="utf-8")
df = pd.DataFrame(hits)
out.write(f"微題材裸版脈衝觸發 {len(df)} 次(234週,無毛利分級)\n\n")

def stat_block(sub, label):
    pr = sub["pret8"].dropna()
    if not len(pr):
        out.write(f"[{label}] 0筆\n")
        return
    wins, losses = pr[pr > 0], pr[pr <= 0]
    rr = (wins.mean() / abs(losses.mean())) if len(wins) and len(losses) else float("nan")
    yr_neg = sub[sub["date"].str[:4] == "2022"]["pret8"].dropna()
    out.write(f"[{label}] {len(sub)}筆 勝率{(pr > 0).mean():.0%} 中位{pr.median():+.1%} "
              f"平均賺{wins.mean() if len(wins) else 0:+.1%}/賠{losses.mean() if len(losses) else 0:+.1%} "
              f"賺賠比{rr:.2f}；2022年{len(yr_neg)}筆中位{yr_neg.median() if len(yr_neg) else float('nan'):+.1%}\n")

out.write("== 型態濾網對照(同一批觸發) ==\n")
stat_block(df, "裸版(無濾網)")
stat_block(df[df["nh"] >= 2], "＋90日新高(≥2/3成員)")
stat_block(df[df["nh"] >= 1], "＋90日新高(≥1成員)")
stat_block(df[df["gnh"] >= 1], "＋突破跳空(≥1成員)")
out.write("\n")
if len(df):
    df["yr"] = df["date"].str[:4]
    out.write(f"{'年':<6}{'觸發':>4}{'sustain>1.5':>11}{'股價+8週中位':>11}{'股價勝率':>8}\n")
    for yr, g in df.groupby("yr"):
        su = g["sustain"].dropna()
        pr = g["pret8"].dropna()
        out.write(f"{yr:<6}{len(g):>4}{(su > 1.5).mean() if len(su) else float('nan'):>11.0%}"
                  f"{pr.median() if len(pr) else float('nan'):>11.1%}"
                  f"{(pr > 0).mean() if len(pr) else float('nan'):>8.0%}\n")
    pr = df["pret8"].dropna()
    wins = pr[pr > 0]
    losses = pr[pr <= 0]
    out.write(f"\n全期: {len(df)}次 股價勝率{(pr > 0).mean():.0%} 中位{pr.median():+.1%} "
              f"平均賺{wins.mean() if len(wins) else 0:+.1%} 平均賠{losses.mean() if len(losses) else 0:+.1%} "
              f"賺賠比{(wins.mean()/abs(losses.mean())) if len(wins) and len(losses) else float('nan'):.2f}\n\n")
    out.write("逐筆(依日期):\n")
    for _, r in df.sort_values("date").iterrows():
        out.write(f"  {r['date']} {r['theme']:<12} sustain{r['sustain'] if pd.notna(r['sustain']) else 0:>5.2f} "
                  f"股價{format(r['pret8'], '+.1%') if pd.notna(r['pret8']) else '  - '} {'、'.join(r['members'])}\n")
out.close()
print("done -> tmp_micro_bear.txt")
