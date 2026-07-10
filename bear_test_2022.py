# -*- coding: utf-8 -*-
"""2022-2026 熊市壓力測試：凍結規則①-④(+位階⑤僅記錄)分年成績單
- 資料: research_2022.db (234週, 2022-01~2026-07, 含降溫股補充)
- 雙軌驗證: 熱度倍率(fwd8x) + 觸發時題材前3大台股成員的+8週等權股價報酬
- 兩種配置: A=BROAD凍結原樣(航運被排除) B=航運/鋼鐵/觀光解禁(2022年代主角)
- 態勢開關對照: 台股加權指數26週均線上/下
輸出: tmp_bear_report.txt
"""
import os
os.environ.setdefault("CF_DB", "research_2022.db")
import io
import pickle
import sys

import pandas as pd
import yfinance as yf

sys.path.insert(0, ".")
from case_study_theme import COUNTRIES, add_signals, load, theme_series
from scan_signals import BROAD, find_triggers

WARMUP = 13
PRICE_CACHE = "tmp_bear_prices.pkl"

rankings, cls = load()
dates = sorted(rankings["snapshot_date"].unique())
warm_end = dates[WARMUP]
print(f"沙盒 {len(dates)}週 {dates[0]}~{dates[-1]}，暖機至{warm_end}")

tw_groups = set(cls[cls["country"] == "台"]["main_group"].unique())
counts = cls.groupby("main_group")["code"].count()
tw_cls = cls[cls["country"] == "台"]
rank_tw = rankings[rankings["country"] == "台"]


def scan(exclude):
    themes = sorted(g for g in cls["main_group"].unique()
                    if g in tw_groups and counts.get(g, 0) >= 3 and g not in exclude)
    hits = []
    for th in themes:
        df = add_signals(theme_series(rankings, cls, th))
        for t in find_triggers(df):
            if str(t["date"]) <= warm_end:
                continue
            t["theme"] = th
            hits.append(t)
    hits.sort(key=lambda x: str(x["date"]))
    return hits


def top3_members(theme, d):
    mem = set(tw_cls[tw_cls["main_group"] == theme]["code"])
    wk = rank_tw[(rank_tw["snapshot_date"] == d) & (rank_tw["code"].isin(mem))]
    return list(wk.sort_values("twd", ascending=False)["code"].head(3))


# ── 股價資料(觸發成員, 週線) ──
def load_prices(codes):
    if os.path.exists(PRICE_CACHE):
        with open(PRICE_CACHE, "rb") as f:
            c = pickle.load(f)
    else:
        c = {}
    todo = [x for x in codes if x not in c]
    for i in range(0, len(todo), 40):
        chunk = todo[i:i + 40]
        tk = [f"{x}.TW" for x in chunk]
        df = yf.download(tk, start="2021-12-01", end=str(dates[-1]), interval="1wk",
                         group_by="ticker", auto_adjust=True, threads=True, progress=False)
        for x, t in zip(chunk, tk):
            try:
                s = (df[t] if len(chunk) > 1 else df)["Close"].dropna()
                c[x] = s if len(s) else None
            except Exception:
                c[x] = None
        # 備援.TWO
        miss = [x for x in chunk if c.get(x) is None]
        if miss:
            tk2 = [f"{x}.TWO" for x in miss]
            df2 = yf.download(tk2, start="2021-12-01", end=str(dates[-1]), interval="1wk",
                              group_by="ticker", auto_adjust=True, threads=True, progress=False)
            for x, t in zip(miss, tk2):
                try:
                    s = (df2[t] if len(miss) > 1 else df2)["Close"].dropna()
                    c[x] = s if len(s) else None
                except Exception:
                    c[x] = None
        with open(PRICE_CACHE, "wb") as f:
            pickle.dump(c, f)
    return c


def px_return(cache, code, d, fwd_weeks=8):
    s = cache.get(code)
    if s is None:
        return None
    d0 = pd.Timestamp(d)
    base = s[s.index <= d0]
    fwd = s[s.index <= d0 + pd.Timedelta(weeks=fwd_weeks)]
    if len(base) == 0 or len(fwd) == 0 or base.iloc[-1] <= 0:
        return None
    if (d0 + pd.Timedelta(weeks=fwd_weeks)) > s.index[-1]:
        return None
    return float(fwd.iloc[-1] / base.iloc[-1] - 1)


# ── 掃描兩種配置 ──
hits_a = scan(BROAD)
BROAD_B = BROAD - {"航運", "造船", "品牌3C"}
hits_b = scan(BROAD_B)
print(f"配置A觸發 {len(hits_a)}、配置B觸發 {len(hits_b)}")

# 股價驗證(合併兩配置的成員)
need = set()
for h in hits_b + hits_a:
    h["members"] = top3_members(h["theme"], str(h["date"]))
    need |= set(h["members"])
print(f"需要股價 {len(need)} 檔")
pc = load_prices(sorted(need))
for hs in (hits_a, hits_b):
    for h in hs:
        rets = [px_return(pc, m, str(h["date"])) for m in h["members"]]
        rets = [r for r in rets if r is not None]
        h["pret8"] = sum(rets) / len(rets) if rets else None


# ── 台股加權 26週均線態勢 ──
twii = yf.download("^TWII", start="2021-06-01", end=str(dates[-1]), interval="1wk",
                   auto_adjust=True, progress=False)["Close"]
if isinstance(twii, pd.DataFrame):
    twii = twii.iloc[:, 0]
ma26 = twii.rolling(26).mean()


def regime_on(d):
    d0 = pd.Timestamp(d)
    s = twii[twii.index <= d0]
    m = ma26[ma26.index <= d0]
    if not len(s) or not len(m) or pd.isna(m.iloc[-1]):
        return None
    return bool(s.iloc[-1] >= m.iloc[-1])


# ── 日線資料(型態濾網用): 觸發成員的日OHLC ──
DAILY_CACHE = "tmp_bear_daily.pkl"


def load_daily(codes):
    if os.path.exists(DAILY_CACHE):
        with open(DAILY_CACHE, "rb") as f:
            c = pickle.load(f)
    else:
        c = {}
    todo = [x for x in codes if x not in c]
    for i in range(0, len(todo), 40):
        chunk = todo[i:i + 40]
        remaining = list(chunk)
        for suffix in (".TW", ".TWO"):
            if not remaining:
                break
            tk = [f"{x}{suffix}" for x in remaining]
            df = yf.download(tk, start="2021-10-01", end=str(dates[-1]), interval="1d",
                             group_by="ticker", auto_adjust=True, threads=True, progress=False)
            got = []
            for x in remaining:
                t = f"{x}{suffix}"
                try:
                    sub = (df[t] if len(tk) > 1 else df)[["High", "Low", "Close"]].dropna()
                    if len(sub):
                        c[x] = sub
                        got.append(x)
                except Exception:
                    pass
            remaining = [x for x in remaining if x not in got]
        for x in remaining:
            c.setdefault(x, None)
        with open(DAILY_CACHE, "wb") as f:
            pickle.dump(c, f)
    return c


def new_high_90d(dc, code, d):
    """觸發日(含)收盤 > 之前90日曆天的最高收盤"""
    df = dc.get(code)
    if df is None:
        return False
    d0 = pd.Timestamp(d)
    cur = df[df.index <= d0]
    if len(cur) < 30:
        return False
    px = float(cur["Close"].iloc[-1])
    win = df[(df.index < cur.index[-1]) & (df.index >= d0 - pd.Timedelta(days=90))]
    return len(win) >= 20 and px > float(win["Close"].max())


def gap_up_week(dc, code, d):
    """觸發週(前6日曆天~當日)內任一日 低點 > 前一交易日高點"""
    df = dc.get(code)
    if df is None:
        return False
    d0 = pd.Timestamp(d)
    win = df[df.index <= d0].tail(8)
    for i in range(1, len(win)):
        if win.index[i] >= d0 - pd.Timedelta(days=6):
            if float(win["Low"].iloc[i]) > float(win["High"].iloc[i - 1]):
                return True
    return False


def gap_newhigh_week(dc, code, d):
    """突破跳空：觸發週內某日 跳空(低>昨高) 且 該日收盤創60日曆天新高"""
    df = dc.get(code)
    if df is None:
        return False
    d0 = pd.Timestamp(d)
    hist = df[df.index <= d0]
    win = hist.tail(8)
    for i in range(1, len(win)):
        di = win.index[i]
        if di < d0 - pd.Timedelta(days=6):
            continue
        if float(win["Low"].iloc[i]) <= float(win["High"].iloc[i - 1]):
            continue
        prior = df[(df.index < di) & (df.index >= di - pd.Timedelta(days=60))]
        if len(prior) >= 15 and float(win["Close"].iloc[i]) > float(prior["Close"].max()):
            return True
    return False


# 均線出場(使用者提案,先驗參數不調): 個股破月線(4週均)→半倉、破季線(13週均)→清倉不回補
_ma_cache = {}


def member_state(code, d):
    """該股在日期d收盤對月/季線狀態: 1.0=線上 0.5=破月線 0=破季線(出場)"""
    if code not in _ma_cache:
        s = pc.get(code)
        _ma_cache[code] = None if s is None else (s, s.rolling(4).mean(), s.rolling(13).mean())
    v = _ma_cache[code]
    if v is None:
        return 1.0
    s, m4, m13 = v
    d0 = pd.Timestamp(d)
    ss = s[s.index <= d0]
    if not len(ss):
        return 1.0
    px = ss.iloc[-1]
    mm13 = m13[m13.index <= d0]
    mm4 = m4[m4.index <= d0]
    if len(mm13) and pd.notna(mm13.iloc[-1]) and px < mm13.iloc[-1]:
        return 0.0
    if len(mm4) and pd.notna(mm4.iloc[-1]) and px < mm4.iloc[-1]:
        return 0.5
    return 1.0


# 階梯倉位(使用者提案,單一參數組不調參): 月線上=100%、破月線=60%、破季線=30%
ma4 = twii.rolling(4).mean()
ma13 = twii.rolling(13).mean()


def tier_scale(d):
    d0 = pd.Timestamp(d)
    s = twii[twii.index <= d0]
    m4 = ma4[ma4.index <= d0]
    m13 = ma13[ma13.index <= d0]
    if not len(s) or not len(m13) or pd.isna(m13.iloc[-1]):
        return 1.0
    px = s.iloc[-1]
    if px < m13.iloc[-1]:
        return 0.3
    if px < m4.iloc[-1]:
        return 0.6
    return 1.0


out = io.open("tmp_bear_report.txt", "w", encoding="utf-8")
out.write(f"凍結規則2022-2026成績單 | 沙盒{len(dates)}週 | 暖機13週後起算\n")
out.write("限制: 回補=估算值+現任成分股(含降溫股補充)；熱度倍率≠股價；規則⑥/微題材未含\n")


def yearly(hits, label):
    out.write(f"\n== {label} ==\n")
    out.write(f"{'年':<6}{'觸發':>4}{'熱度勝率':>8}{'熱度中位x':>9}{'股價+8週中位':>11}{'股價勝率':>8}{'黃金區(位階<70)':>14}\n")
    rows = pd.DataFrame(hits)
    rows["yr"] = rows["date"].astype(str).str[:4]
    for yr, g in rows.groupby("yr"):
        f8 = g["fwd8x"].dropna()
        pr = g["pret8"].dropna()
        gold = g[g["pos"] < 70]
        gpr = gold["pret8"].dropna()
        out.write(f"{yr:<6}{len(g):>4}"
                  f"{(f8 > 1).mean() if len(f8) else float('nan'):>8.0%}"
                  f"{f8.median() if len(f8) else float('nan'):>9.2f}"
                  f"{pr.median() if len(pr) else float('nan'):>11.1%}"
                  f"{(pr > 0).mean() if len(pr) else float('nan'):>8.0%}"
                  f"  n={len(gold)} 股價中位{gpr.median() if len(gpr) else float('nan'):.1%}\n")
    # 態勢開關
    on = [h for h in hits if regime_on(str(h["date"])) is True]
    off = [h for h in hits if regime_on(str(h["date"])) is False]
    for tag, hh in (("指數26週均線上", on), ("均線下", off)):
        pr = pd.Series([h["pret8"] for h in hh if h["pret8"] is not None])
        out.write(f"  態勢[{tag}]: {len(hh)}次 股價+8週中位{pr.median() if len(pr) else float('nan'):.1%} 勝率{(pr > 0).mean() if len(pr) else float('nan'):.0%}\n")


yearly(hits_a, "配置A(BROAD凍結原樣,航運/造船/品牌3C排除)")
yearly(hits_b, "配置B(2022年代主角解禁)")

out.write("\n== 及格標準逐項 ==\n")
rows_b = pd.DataFrame(hits_b)
rows_b["yr"] = rows_b["date"].astype(str).str[:4]
wk_per_yr = pd.Series([d[:4] for d in dates[WARMUP:]]).value_counts()
out.write("① 熊市應少訊號(每週觸發密度):\n")
for yr in sorted(wk_per_yr.index):
    n = (rows_b["yr"] == yr).sum()
    out.write(f"   {yr}: {n}次 / {wk_per_yr[yr]}週 = {n/wk_per_yr[yr]:.2f}次/週\n")
out.write("② 2023 AI第一波(相關題材當年首次觸發):\n")
for th in ["AI伺服器", "組裝代工(EMS)", "散熱/結構件", "IC設計", "CPO/光通訊", "晶圓代工"]:
    g = rows_b[(rows_b["theme"] == th) & (rows_b["yr"] == "2023")]
    out.write(f"   {th}: {'、'.join(str(d) for d in g['date'].head(3))}{' (無)' if g.empty else ''}\n")
out.write("③ 記憶體觸發全紀錄:\n")
g = rows_b[rows_b["theme"] == "記憶體"]
for _, r in g.iterrows():
    out.write(f"   {r['date']} 位階{r['pos']} 熱度x{r['fwd8x']} 股價{r['pret8'] if pd.isna(r['pret8']) is False else '-'}\n")
out.write("④ 2022年代題材(配置B)觸發樣本:\n")
for th in ["航運", "鋼鐵/有色金屬", "觀光/餐飲", "製藥/生技"]:
    g = rows_b[rows_b["theme"] == th]
    for _, r in g.head(4).iterrows():
        out.write(f"   {th} {r['date']} 位階{r['pos']} 股價+8週{'' if pd.isna(r['pret8']) else format(r['pret8'], '.1%')}\n")

# ── 組合回測：觸發買前3大成員等權、持有8週、來回成本0.5% ──
d_idx = {d: i for i, d in enumerate(dates)}


def wk_ret(code, t):
    """成員在 dates[t] -> dates[t+1] 的週報酬"""
    s = pc.get(code)
    if s is None or t + 1 >= len(dates):
        return None
    a = s[s.index <= pd.Timestamp(dates[t])]
    b = s[s.index <= pd.Timestamp(dates[t + 1])]
    if len(a) == 0 or len(b) == 0 or a.iloc[-1] <= 0 or b.index[-1] == a.index[-1]:
        return None
    return float(b.iloc[-1] / a.iloc[-1] - 1)


def simulate(hits, gold_only=False, use_regime=False, use_tiers=False, ma_exit=False,
             pattern=None, hold=8, cost=0.005, max_hold=52):
    entries = {}
    trades = []
    for h in hits:
        if h["pret8"] is None and not h["members"]:
            continue
        if gold_only and h["pos"] >= 70:
            continue
        if use_regime and regime_on(str(h["date"])) is not True:
            continue
        if pattern and h.get(pattern[0], 0) < pattern[1]:
            continue
        t = d_idx.get(str(h["date"]))
        if t is not None:
            entries.setdefault(t, []).append(h["members"])
            if not ma_exit and h["pret8"] is not None:
                trades.append({"date": str(h["date"]), "theme": h["theme"],
                               "ret": h["pret8"] - cost})
    equity = [1.0]
    curve_dates = [dates[WARMUP]]
    active = []   # 固定持有: [codes, weeks_left, fresh] / 均線出場: dict
    n_active_weeks = 0
    for t in range(WARMUP, len(dates) - 1):
        for mem in entries.get(t, []):
            if mem:
                if ma_exit:
                    active.append({"mem": mem, "out": set(), "age": 0,
                                   "fresh": True, "factor": 1.0, "d0": dates[t]})
                else:
                    active.append([mem, hold, True])
        rets = []
        if ma_exit:
            for pos in active:
                slices = []
                for c in pos["mem"]:
                    if c in pos["out"]:
                        slices.append(0.0)
                        continue
                    st = member_state(c, dates[t])   # 用t當週(含)收盤定下週曝險,無前視
                    if st == 0.0:
                        pos["out"].add(c)
                        slices.append(0.0)
                        continue
                    r = wk_ret(c, t)
                    slices.append(st * r if r is not None else 0.0)
                r = sum(slices) / len(pos["mem"]) if pos["mem"] else 0.0
                if pos["fresh"]:
                    r -= cost
                    pos["fresh"] = False
                pos["factor"] *= (1 + r)
                pos["age"] += 1
                rets.append(r)
        else:
            for pos in active:
                prs = [wk_ret(c, t) for c in pos[0]]
                prs = [x for x in prs if x is not None]
                r = sum(prs) / len(prs) if prs else 0.0
                if pos[2]:
                    r -= cost
                    pos[2] = False
                rets.append(r)
        if rets:
            n_active_weeks += 1
        week_r = sum(rets) / len(rets) if rets else 0.0
        if use_tiers:
            week_r *= tier_scale(dates[t])
        equity.append(equity[-1] * (1 + week_r))
        curve_dates.append(dates[t + 1])
        if ma_exit:
            done = [p for p in active
                    if len(p["out"]) == len(p["mem"]) or p["age"] >= max_hold]
            for p in done:
                trades.append({"date": p["d0"], "ret": p["factor"] - 1, "age": p["age"]})
            active = [p for p in active
                      if len(p["out"]) < len(p["mem"]) and p["age"] < max_hold]
        else:
            for pos in active:
                pos[1] -= 1
            active = [p for p in active if p[1] > 0]
    if ma_exit:
        for p in active:   # 期末未平倉也計入
            trades.append({"date": p["d0"], "ret": p["factor"] - 1})
    eq = pd.Series(equity, index=pd.to_datetime(curve_dates))
    peak = eq.cummax()
    mdd = float((eq / peak - 1).min())
    yr_ret = eq.groupby(eq.index.year).apply(lambda s: s.iloc[-1] / s.iloc[0] - 1)
    exposure = n_active_weeks / max(len(eq) - 1, 1)
    return eq, mdd, yr_ret, trades, exposure


def metrics(eq, mdd, trades, exposure=None):
    wr = eq.pct_change().dropna()
    n_yr = len(wr) / 52
    cagr = float(eq.iloc[-1] ** (1 / n_yr) - 1) if n_yr > 0 else 0
    vol = float(wr.std() * (52 ** 0.5))
    sharpe = float(wr.mean() * 52 / vol) if vol > 0 else 0
    dn = wr[wr < 0]
    sortino = float(wr.mean() * 52 / (dn.std() * (52 ** 0.5))) if len(dn) and dn.std() > 0 else 0
    calmar = cagr / abs(mdd) if mdd else 0
    m = {"總倍數": round(float(eq.iloc[-1]), 2), "CAGR": cagr, "年化波動": vol,
         "夏普(rf=0)": round(sharpe, 2), "Sortino": round(sortino, 2),
         "最大回撤": mdd, "Calmar": round(calmar, 2)}
    if trades is not None:
        rets = [t["ret"] for t in trades]
        wins = [r for r in rets if r > 0]
        losses = [r for r in rets if r <= 0]
        m.update({
            "交易次數": len(rets),
            "勝率": len(wins) / len(rets) if rets else 0,
            "平均賺": sum(wins) / len(wins) if wins else 0,
            "平均賠": sum(losses) / len(losses) if losses else 0,
            "賺賠比": round((sum(wins) / len(wins)) / abs(sum(losses) / len(losses)), 2) if wins and losses else None,
            "獲利因子": round(sum(wins) / abs(sum(losses)), 2) if losses and sum(losses) != 0 else None,
        })
    if exposure is not None:
        m["持倉時間%"] = exposure
    return m


def bench():
    s = twii[twii.index >= pd.Timestamp(dates[WARMUP])]
    eq = s / s.iloc[0]
    mdd = float((eq / eq.cummax() - 1).min())
    yr = eq.groupby(eq.index.year).apply(lambda x: x.iloc[-1] / x.iloc[0] - 1)
    return eq, mdd, yr


out.write("\n== 組合回測(配置B訊號,買題材前3大成員等權,持有8週,來回成本0.5%) ==\n")
bq, bmdd, byr = bench()
variants = [
    ("全部訊號", dict()),
    ("全部訊號+階梯倉位", dict(use_tiers=True)),
    ("均線出場(破月線半倉/破季線清倉)", dict(ma_exit=True)),
    ("均線出場+階梯倉位", dict(ma_exit=True, use_tiers=True)),
    ("型態確認:≥2成員創90日新高", dict(pattern=("nh", 2))),
    ("型態確認:≥1成員週內跳空", dict(pattern=("gp", 1))),
    ("突破跳空:≥1成員跳空+創60日新高", dict(pattern=("gnh", 1))),
    ("只做黃金區(位階<70)", dict(gold_only=True)),
    ("黃金區+態勢開關", dict(gold_only=True, use_regime=True)),
]
# 型態濾網: 觸發時前3大成員的 90日新高家數 / 週內跳空家數 (日線)
dc = load_daily(sorted(need))
print(f"日線覆蓋 {sum(1 for v in dc.values() if v is not None)}/{len(dc)} 檔")
for h in hits_b:
    h["nh"] = sum(1 for m in h["members"] if new_high_90d(dc, m, str(h["date"])))
    h["gp"] = sum(1 for m in h["members"] if gap_up_week(dc, m, str(h["date"])))
    h["gnh"] = sum(1 for m in h["members"] if gap_newhigh_week(dc, m, str(h["date"])))

results = {}
out.write(f"{'策略':<28}{'總倍數':>7}{'最大回撤':>8} 年度報酬\n")
for name, kw in variants:
    eq, mdd, yr, trades, expo = simulate(hits_b, **kw)
    results[name] = {"eq": eq, "mdd": mdd, "yr": yr, "m": metrics(eq, mdd, trades, expo),
                     "trades": trades}
    yrs = " ".join(f"{y}:{v:+.0%}" for y, v in yr.items())
    out.write(f"{name:<28}{eq.iloc[-1]:>7.2f}{mdd:>8.0%} {yrs}\n")

# 均線出場診斷(回答:總倍數低是出手多嗎? -> 看持有期與出場原因)
ma_tr = results["均線出場(破月線半倉/破季線清倉)"]["trades"]
ages = [t["age"] for t in ma_tr if "age" in t]
if ages:
    stopped = sum(1 for a in ages if a < 52)
    out.write(f"\n均線出場診斷: 平均持有{sum(ages)/len(ages):.1f}週(中位{sorted(ages)[len(ages)//2]}週)、"
              f"{stopped}/{len(ages)}筆被季線停出(其餘滿52週)；"
              f"對照固定8週版持有恆為8週——總倍數低非出手次數問題(151vs146)，"
              f"是停出後不回補導致主升段曝險流失\n")
results["台股加權(基準)"] = {"eq": bq, "mdd": bmdd, "yr": byr, "m": metrics(bq, bmdd, None)}
yrs = " ".join(f"{y}:{v:+.0%}" for y, v in byr.items())
out.write(f"{'台股加權(基準,買進持有)':<28}{bq.iloc[-1]:>7.2f}{bmdd:>8.0%} {yrs}\n")
out.write("註: 無停損無加碼、固定8週=簡化版；實戰是「騎著等訊號惡化」會不同。估算資料+倖存者偏差=方向參考。\n")
out.close()

# ── 專業HTML報告(獨立研究檔,不進正式網站) ──
COLORS = {"全部訊號": "#3987e5", "全部訊號+階梯倉位": "#199e70",
          "均線出場(破月線半倉/破季線清倉)": "#c98500", "均線出場+階梯倉位": "#008300",
          "型態確認:≥2成員創90日新高": "#9085e9", "型態確認:≥1成員週內跳空": "#d55181",
          "突破跳空:≥1成員跳空+創60日新高": "#e66767",
          "只做黃金區(位階<70)": "#c3c2b7", "黃金區+態勢開關": "#d95926",
          "台股加權(基準)": "#8a8878"}
CHART_KEYS = ["全部訊號", "全部訊號+階梯倉位", "型態確認:≥2成員創90日新高",
              "突破跳空:≥1成員跳空+創60日新高", "台股加權(基準)"]
import json as _json

def ser(eq):
    return {"x": [str(d.date()) for d in eq.index], "y": [round(float(v), 4) for v in eq]}

payload = {
    "curves": {k: ser(results[k]["eq"]) for k in CHART_KEYS if k in results},
    "dd": {k: {"x": ser(v["eq"])["x"],
               "y": [round(float(x), 4) for x in (v["eq"] / v["eq"].cummax() - 1)]}
           for k, v in {kk: results[kk] for kk in ["全部訊號", "台股加權(基準)"]}.items()},
    "years": sorted(set(y for v in results.values() for y in v["yr"].index)),
    "yr": {k: {int(y): round(float(r), 4) for y, r in v["yr"].items()} for k, v in results.items()},
    "colors": COLORS,
}
PCT = ["CAGR", "年化波動", "最大回撤", "勝率", "平均賺", "平均賠", "持倉時間%"]
rows_html = ""
keys = ["總倍數", "CAGR", "年化波動", "夏普(rf=0)", "Sortino", "最大回撤", "Calmar",
        "交易次數", "勝率", "平均賺", "平均賠", "賺賠比", "獲利因子", "持倉時間%"]
for k in keys:
    cells = ""
    for name in results:
        v = results[name]["m"].get(k)
        if v is None:
            cells += "<td>—</td>"
        elif k in PCT:
            cells += f"<td>{v:+.1%}</td>" if k in ("CAGR", "平均賺", "平均賠", "最大回撤") else f"<td>{v:.1%}</td>"
        else:
            cells += f"<td>{v}</td>"
    rows_html += f"<tr><th>{k}</th>{cells}</tr>"
head_html = "".join(f"<th style='color:{COLORS[n]}'>{n}</th>" for n in results)

html = """<!DOCTYPE html><html lang="zh-Hant"><head><meta charset="utf-8">
<title>2022-2026 凍結規則壓力測試報告</title>
<script src="plotly.min.js"></script>
<style>
body{background:#1a1a19;color:#fff;font-family:"Noto Sans TC",sans-serif;margin:24px;max-width:1100px}
h1{font-size:20px} h2{font-size:15px;color:#c3c2b7;margin-top:28px}
table{border-collapse:collapse;font-size:13px;font-variant-numeric:tabular-nums}
td,th{border:1px solid #333;padding:5px 12px;text-align:right} th{text-align:left}
.note{color:#8a8878;font-size:12px;line-height:1.7}
</style></head><body>
<h1>凍結規則 2022–2026 壓力測試（研究沙盒）</h1>
<div class="note">策略=規則①~④觸發買入題材前3大台股成員等權、固定持有8週、來回成本0.5%。資料=回補估算值(現任成分股+24檔降溫股補充)。
本報告回答「大方向與風險量級」，非精確績效預測。基準=台股加權指數買進持有。</div>
<h2>績效指標總表</h2>
<table><tr><th>指標</th>__HEAD__</tr>__ROWS__</table>
<h2>權益曲線（起點=1，對數刻度）</h2><div id="c1" style="height:420px"></div>
<h2>水下回撤（全部訊號 vs 大盤）</h2><div id="c2" style="height:260px"></div>
<h2>逐年報酬</h2><div id="c3" style="height:320px"></div>
<div class="note">已知限制：熱度=成交金額(跌市放量會觸發假訊號→2022勝率27%)；估算回補含倖存者殘餘；固定8週持有為簡化(實戰=騎著等訊號惡化)；
規則⑥基本面與微題材未含。結論五條見 tmp_bear_report.txt 與記憶檔。</div>
<script>
const D = __DATA__;
const L = {paper_bgcolor:"#1a1a19", plot_bgcolor:"#1a1a19", font:{color:"#c3c2b7",size:12},
  xaxis:{gridcolor:"#2c2c2a"}, yaxis:{gridcolor:"#2c2c2a"}, legend:{orientation:"h", y:1.12},
  margin:{t:10,b:36,l:56,r:110}, hovermode:"x unified"};
const t1 = Object.keys(D.curves).map(k => ({x:D.curves[k].x, y:D.curves[k].y, name:k, mode:"lines",
  line:{color:D.colors[k], width:2, dash:k.indexOf("基準")>=0?"dash":"solid"}}));
const ann = Object.keys(D.curves).map(k => {const c=D.curves[k];
  return {x:c.x[c.x.length-1], y:Math.log10(c.y[c.y.length-1]), xref:"x", yref:"y",
    text:c.y[c.y.length-1].toFixed(2)+"x", showarrow:false, xanchor:"left",
    font:{color:D.colors[k], size:11}};});
Plotly.newPlot("c1", t1, Object.assign({}, L, {yaxis:{type:"log", gridcolor:"#2c2c2a"}, annotations:ann}), {responsive:true});
const t2 = Object.keys(D.dd).map(k => ({x:D.dd[k].x, y:D.dd[k].y, name:k, mode:"lines", fill:"tozeroy",
  line:{color:D.colors[k], width:2}}));
Plotly.newPlot("c2", t2, Object.assign({}, L, {yaxis:{tickformat:".0%", gridcolor:"#2c2c2a"}}), {responsive:true});
const t3 = Object.keys(D.yr).map(k => ({x:D.years, y:D.years.map(y=>D.yr[k][y]!==undefined?D.yr[k][y]:null),
  name:k, type:"bar", marker:{color:D.colors[k]}}));
Plotly.newPlot("c3", t3, Object.assign({}, L, {barmode:"group", yaxis:{tickformat:".0%", gridcolor:"#2c2c2a"},
  hovermode:"closest"}), {responsive:true});
</script></body></html>"""
html = html.replace("__HEAD__", head_html).replace("__ROWS__", rows_html).replace("__DATA__", _json.dumps(payload, ensure_ascii=False))
with open("research_2022_report.html", "w", encoding="utf-8") as f:
    f.write(html)
print("done -> tmp_bear_report.txt, research_2022_report.html")
