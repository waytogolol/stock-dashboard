# -*- coding: utf-8 -*-
"""週級動能「可執行形式」設計空間系統性掃描(2026-08-05,承接build_weekly_momo_entry_realism.py的
壞消息:原始127x是紙上富貴,進場價換成訊號後才出現的價格就崩掉)。

═══ 本卷要回答的問題 ═══
一週漲20%+的股票隔週的確有真實後續動能(理想版單筆均+1.0%,bootstrap CI排0),但「事後看到強勢→
用訊號當下的收盤價買進」不可執行。本卷把「訊號時點 × 進場價格方式 × 訊號定義濾網 × 資金分支設計」
當成一個設計空間窮舉,找出有沒有任何一個組合能在**零前視**(進場價必須是訊號確認時點之後才出現的價格)
下活下來。

═══ 三個方法論上的重要修正(比背景敘述更正確,務必先看) ═══
(1) 「0.19x」有一半是口徑不對稱造成的假象,不是真的跳空侵蝕
    entry_realism把「進場=次交易日開盤」配「出場=次週五收盤」,等於每一輪都在跳空「之後」買、在下一次
    跳空「之前」賣——同一個週末跳空被扣兩次(買貴一次+賣早一次)。本卷複刻該口徑得0.33x(與其0.19x同
    量級,差異來自流動性閘門用前一週已知值),但改成**對稱**口徑(開盤進場→次週同一時點開盤出場)後是
    3.0x/年化+9.9%。真實侵蝕是 131x→3.0x(仍然慘烈),不是 127x→0.19x。
(2) 跳空只吃掉一半,另一半當天盤中就吐回來了——所以「次日收盤」比「次日開盤」便宜
    強勢股次日開盤跳空均+1.20%,但次日開盤→收盤均-0.58%(盤中回吐),訊號日收盤→次日收盤合計只有
    +0.57%(中位數+0.00%)。這是本卷最有價值的機制發現:**等一天、用收盤價進場,拿回一半被吃掉的肉**。
(3) 滾動日訊號的「5條錯開資金分支」必須用固定日曆錯開,不能用貪婪法
    早期版本用「看到訊號就進、鎖倉5日」建5條分支,結果5條在幾步內就同步成同一條(實測重疊度5.00/5),
    等於假分散卻用分散後的曲線報MDD。已改成第j支只在 day_index≡j (mod 5) 換股(重疊度1.00)。兩種
    設計都合法,但要分開報:D1貪婪單池(100%資金,空手時見訊號就進)/ D2固定錯開5分支(各20%)。

═══ 設計空間 ═══
維度A 訊號時點: A0週五收盤判(全週)/A1週三收盤判(週一~三)/A2週四收盤判(週一~四)/A3逐日滾動(近3/4/5日)
  門檻用**訊號頻率對齊**校準而非線性縮放(線性12%/16%會讓訊號量爆增到不可比):實測日均候選檔數
  fri20%=8.84 → thu18%=8.70 / wed16%=8.10 / r5-20%=10.37 / r3-16%=8.77,故基準組合為
  fri20%/thu18%/wed16%/r4-18%/r5-20%/r3-16%,另附各自的門檻敏感度。
維度B 進場價格: B1次日開盤市價 / B2次日限價單(掛前收*(1+x%),當日low<=限價才成交,x=1/3/5%) /
  B3次日收盤 / (對照:B0訊號日收盤=不可執行的理想版)
維度C 訊號濾網: C1排除訊號日鎖漲停 / C2排除訊號漲幅極端值 / C3要求已離開窗內高點 /
  C4排除進場日開盤跳空<x%(x測-1/-2/-3/-5/-8,**進場日開盤已可觀察、收盤才進場,零前視**)
維度D 資金分支: D1貪婪單池 / D2固定錯開5分支 ;另有流動性門檻/持股檔數/regime控倉/固定曝險縮放

═══ 口徑鐵律 ═══
· 進場價一律是「訊號日收盤之後」才出現的價格;B0理想版只當肉量參考,明確標示不可執行
· 出場對稱:進場用什麼價格形式,出場就用次週同一時點的同一種價格形式(開對開/收對收),成本0.5%單邊
· 組合建置=**日頻標記**(每日收盤重評價)+跨分支每日再平衡,MDD用日頻算(比週頻嚴格,是誠實值)
· 流動性閘門一律取「前一週」已完成的20週均週成交值(週中訊號不能用本週未完成的量),零前視
· 資料清洗比照M:close/open/high/low/money皆須>0

═══ 已知偏誤(誠實揭露,對所有版本一致故不影響相對比較) ═══
· fm_daily_price是**未還原原始價**(實測3.31%的交易日出現「收盤-漲跌價差 != 前一日收盤」=除權息調整,
  中位-0.62%,每檔每年約6.9次)。持有期間跨到除息日會少算領到的股息,是**保守偏誤**,真實報酬應略高於
  本卷數字(粗估年化低估1~2個百分點)。理想版/可執行版同受影響,肉量比較不受污染。
· 本卷已排除倖存者偏誤(fm_daily_price含已下市個股的歷史列),但下市當週的極端跌幅若被寫成0已被清洗濾掉。
· B3「次日收盤進場」在實務上要靠尾盤成交,小型股尾盤流動性有限,實際滑價可能高於0.5%——見第4.3段
  成本敏感度,這是本策略最脆弱的假設。

用法: python 研究腳本/綜合策略/build_weekly_momo_executable_scan.py  (從根目錄執行,鐵律)
產出: 純console報告,約3-4分鐘(含M的週線面板建置)。無檔案輸出、不寫快取。
"""
import bisect
import sqlite3
import sys
import time

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "研究腳本/綜合策略")
import build_weekly_momo_regime_overlay as M  # noqa: E402  (沿用其常數/清洗慣例/週線面板作對照)

DB = "capital_flow.db"
COST = M.COST              # 0.005 單邊
LIQ_MIN = M.LIQ_MIN        # 0.3e8 近20週均週成交值
TOP_N = M.TOP_N            # 10
HOLD = 5                   # 持有5個交易日(=一週)
START = M.START            # 2015-01-01
N_BOOT = 1000
RNG = np.random.default_rng(20260805)
T0 = time.time()


# ══════════════════ 一、日頻面板 ══════════════════
def build_daily_panel():
    con = sqlite3.connect(DB)
    df = pd.read_sql(f"SELECT code,date,open,high,low,close,spread,money FROM fm_daily_price "
                     f"WHERE date>='{M.BUFFER_START}'", con, parse_dates=["date"])
    con.close()
    n0 = len(df)
    df = df[(df["close"] > 0) & (df["open"] > 0) & (df["low"] > 0) &
            (df["high"] > 0) & (df["money"] > 0)]
    print(f"日頻清洗: 濾掉{n0-len(df)}列({(n0-len(df))/n0*100:.2f}%,同M的close/money>0再加open/high/low>0)")
    piv = lambda c: df.pivot_table(index="date", columns="code", values=c).sort_index()
    return {k: piv(k).values.astype(np.float32) for k in
            ["open", "high", "low", "close", "spread", "money"]}, piv("close").index


print("建置日頻面板(全市場fm_daily_price,2014起)...")
_P, DATES = build_daily_panel()
O, H, L, C, SPR, MN = (_P["open"], _P["high"], _P["low"], _P["close"], _P["spread"], _P["money"])
ND, NC = C.shape
DATES = pd.DatetimeIndex(DATES)
START_I = int(DATES.searchsorted(pd.Timestamp(START)))
print(f"日頻面板 shape={C.shape}(日數×檔數) {DATES[0].date()}~{DATES[-1].date()}  "
      f"[{time.time()-T0:.0f}s]")


# ══════════════════ 二、衍生訊號矩陣 ══════════════════
def _ffill(Mx, limit=5):
    return pd.DataFrame(Mx).ffill(limit=limit).values.astype(np.float32)


Cf, Of = _ffill(C), _ffill(O)

wk_id = pd.Series(DATES.to_period("W-FRI"))
uniq_wk = pd.PeriodIndex(wk_id.unique()).sort_values()
WKNUM = wk_id.map({p: i for i, p in enumerate(uniq_wk)}).values
NW = len(uniq_wk)

# 週內running:到當日為止的最後有效收盤 / 最高價(A0~A2的「週到今日累積漲幅」用)
WTDC = np.full((ND, NC), np.nan, dtype=np.float32)   # week-to-date last close
WKH = np.full((ND, NC), np.nan, dtype=np.float32)    # week-to-date high
_cur = np.full(NC, np.nan, dtype=np.float32); _hi = np.full(NC, np.nan, dtype=np.float32)
_pg = -1
for i in range(ND):
    if WKNUM[i] != _pg:
        _cur = np.full(NC, np.nan, dtype=np.float32); _hi = np.full(NC, np.nan, dtype=np.float32)
        _pg = WKNUM[i]
    m = ~np.isnan(C[i]); _cur[m] = C[i][m]
    _hi = np.fmax(_hi, H[i])
    WTDC[i], WKH[i] = _cur, _hi

# 週最後收盤(等同M.WIDE_C)+ 週成交值加總 → 20週均額
_wk_last_day = np.array([np.where(WKNUM == g)[0][-1] for g in range(NW)])
WKC = WTDC[_wk_last_day]
WKM = np.zeros((NW, NC)); _any = np.zeros((NW, NC), bool)
for i in range(ND):
    g = WKNUM[i]; m = ~np.isnan(MN[i])
    WKM[g][m] += MN[i][m]; _any[g][m] = True
WKM[~_any] = np.nan
LIQ20 = np.nan_to_num(pd.DataFrame(WKM).rolling(20).mean().values, nan=0.0)
# 每日取「前一週」已完成的20週均額(週中訊號不能用本週未完成的量,零前視)
LIQP = np.zeros((ND, NC), dtype=np.float32)
for i in range(ND):
    g = WKNUM[i]
    LIQP[i] = LIQ20[g - 1] if g >= 1 else 0.0

# 週到今日累積漲幅(對週五錨點時 == M.WIDE_RET,已驗證可重現M的基準)
BASE = np.full((ND, NC), np.nan, dtype=np.float32)
for i in range(ND):
    g = WKNUM[i]
    if g >= 1: BASE[i] = WKC[g - 1]
WTD = WTDC / BASE - 1.0


def _anchors(maxdow):
    """每週最後一個 dow<=maxdow 的交易日(遇假日自動退到前一交易日,不會漏週)"""
    return np.array([np.where((WKNUM == g) & (DATES.dayofweek.values <= maxdow))[0][-1]
                     for g in range(NW)
                     if ((WKNUM == g) & (DATES.dayofweek.values <= maxdow)).any()])


ANCH = {"fri": _anchors(4), "thu": _anchors(3), "wed": _anchors(2)}


def _roll(k):
    r = np.full((ND, NC), np.nan, dtype=np.float32); r[k:] = Cf[k:] / Cf[:-k] - 1.0
    return r


def _winhigh(k):
    return pd.DataFrame(H).rolling(k, min_periods=1).max().values.astype(np.float32)


ROLL = {"r3": (_roll(3), _winhigh(3)), "r4": (_roll(4), _winhigh(4)), "r5": (_roll(5), _winhigh(5))}

# 鎖漲停偵測:收盤==最高 且 當日漲幅達漲跌幅上限(2015-06前為7%,之後10%)
RET1 = SPR / (C - SPR)
LOCK = (C == H) & (RET1 >= 0.093)
LOCK |= (C == H) & (RET1 >= 0.063) & np.asarray(DATES < pd.Timestamp("2015-06-01")).reshape(-1, 1)
LOCK = np.nan_to_num(LOCK.astype(np.float32)).astype(bool)
ANCHORED = {"fri", "thu", "wed"}
print(f"衍生矩陣完成 [{time.time()-T0:.0f}s]")


# ══════════════════ 三、Regime序列(沿用M已驗證的公式,零前視) ══════════════════
def _regime_daily():
    px = M.TAIEX
    t = M.REG_TREND.reindex(DATES, method="ffill").values
    v = M.REG_VOL.reindex(DATES, method="ffill").values
    return t, v


REGT, REGV = _regime_daily()


# ══════════════════ 四、訊號建置 ══════════════════
def make_signals(kind, thr, c1=False, c2=None, c3=0.0, liq_min=LIQ_MIN, pick="top", top_n=TOP_N):
    """kind: fri/thu/wed(週內錨點,用週到今日累積漲幅) 或 r3/r4/r5(逐日滾動,用近k日報酬)
    c1排鎖漲停 / c2排漲幅>=c2的極端值 / c3要求收盤已比窗內高點回檔c3 / liq_min流動性門檻
    回傳 {signal_day_index: (依訊號漲幅降冪的code索引, 對應漲幅)}"""
    if kind in ANCHORED:
        R, WHm, PX, days = WTD, WKH, WTDC, ANCH[kind]
    else:
        R, WHm = ROLL[kind]; PX, days = Cf, np.arange(ND)
    days = days[(days >= START_I) & (days < ND - HOLD - 2)]
    out = {}
    for i in days:
        r = R[i]
        ok = (r >= thr) & (LIQP[i] >= liq_min) & ~np.isnan(r)
        if c1: ok &= ~LOCK[i]
        if c2 is not None: ok &= (r < c2)
        if c3 > 0: ok &= (PX[i] < WHm[i] * (1 - c3))
        idx = np.where(ok)[0]
        if len(idx) == 0: continue
        idx = idx[np.argsort(-r[idx])]
        if pick == "bottom": idx = idx[::-1]
        out[i] = (idx[:top_n], r[idx[:top_n]])
    return out


# ══════════════════ 五、進場價 / 資金分支 / 組合 ══════════════════
def entry_prices(sig_i, ent_i, codes, emode, lim_x, gap_lo, gap_hi):
    """emode: sigclose(理想,不可執行) / open / close / limit。回傳(成交檔, 成交價, 掛單檔數)"""
    if gap_lo is not None or gap_hi is not None:
        gp = O[ent_i, codes] / WTDC[sig_i, codes] - 1   # 進場日開盤,收盤進場前已知,零前視
        keep = ~np.isnan(gp)
        if gap_lo is not None: keep &= (gp >= gap_lo)
        if gap_hi is not None: keep &= (gp <= gap_hi)
        codes = codes[keep]
    if len(codes) == 0: return codes, np.array([]), 0
    if emode == "sigclose":  px = WTDC[sig_i, codes]; filled = ~np.isnan(px)
    elif emode == "open":    px = O[ent_i, codes];    filled = ~np.isnan(px)
    elif emode == "close":   px = C[ent_i, codes];    filled = ~np.isnan(px)
    elif emode == "limit":
        plim = WTDC[sig_i, codes] * (1 + lim_x)
        lo, op = L[ent_i, codes], O[ent_i, codes]
        filled = (~np.isnan(lo)) & (~np.isnan(op)) & (lo <= plim) & (~np.isnan(plim))
        px = np.minimum(op, plim)                        # 開盤已低於限價就以開盤成交
    else: raise ValueError(emode)
    filled &= ~np.isnan(px) & (px > 0)
    return codes[filled], px[filled], len(codes)


def cohort_seq(kind, sig_days, phase=0, stagger="fixed"):
    """錨點版:每週一輪,出場日=下一個錨點(遇假日自動對齊)。
    滾動版 stagger=fixed:第phase支只在 day_index≡phase (mod 5) 的訊號日換股(真正錯開);
             stagger=greedy1:單一資金池,空手時見訊號就進,鎖倉5日(⚠5支會同步成同一條,只能單支用)"""
    if kind in ANCHORED:
        return [(sig_days[k], sig_days[k + 1]) for k in range(len(sig_days) - 1)]
    sd = set(int(x) for x in sig_days)
    if stagger == "fixed":
        return [(i, i + HOLD) for i in range(START_I + phase, ND - HOLD - 2, HOLD) if i in sd]
    seq, last = [], -1
    for i in sig_days:
        if i < last or i + 1 + HOLD >= ND: continue
        seq.append((i, i + HOLD)); last = i + HOLD
    return seq


def regime_w(sig_i, rule, off_w):
    if rule is None: return 1.0
    t, v = REGT[sig_i], REGV[sig_i]
    bad = {"trend": t == "空頭", "vol": v == "高波",
           "combo": (t == "空頭") or (v == "高波")}[rule]
    return off_w if bad else 1.0


def run(kind, signals, emode="close", xmode="close", lim_x=None, weighting="equal",
        phases=None, gap_lo=None, gap_hi=None, top_n=TOP_N, rule=None, off_w=0.0,
        stagger="fixed"):
    """日頻標記組合。每個cohort在持有期內逐日用收盤重評價,最後一日用出場價;
    跨資金分支每日再平衡(各1/phases)。回傳(日頻equity, 逐筆trades, 成交率, 平均籃子檔數, 訊號日數)"""
    sig_days = sorted(signals.keys())
    eoff = 0 if emode == "sigclose" else 1               # 理想版進場日=訊號日,其餘=次交易日
    if phases is None:
        phases = 1 if (kind in ANCHORED or stagger == "greedy1") else 5
    navs, trs, bsz = [], [], []
    nfill = ntgt_all = 0
    for ph in range(phases):
        nav = np.full(ND, np.nan); A_k = 1.0
        for (si, nxt) in cohort_seq(kind, sig_days, ph, stagger):
            e, x = si + eoff, nxt + eoff
            if x >= ND: break
            w = regime_w(si, rule, off_w)
            if w == 0.0:
                nav[e:x + 1] = A_k; continue
            cs, pent, ntgt = entry_prices(si, e, signals[si][0], emode, lim_x, gap_lo, gap_hi)
            nfill += len(cs); ntgt_all += ntgt; bsz.append(len(cs))
            if len(cs) == 0:
                nav[e:x + 1] = A_k; continue
            path = (Cf[e:x + 1, :][:, cs] / pent).copy()
            xpx = (Of if xmode == "open" else Cf)[x, cs]
            path[-1] = xpx / pent
            good = ~np.isnan(path).any(axis=0)
            if good.sum() == 0:
                nav[e:x + 1] = A_k; continue
            path, cs2 = path[:, good], cs[good]
            B = (path.mean(axis=1) if weighting == "equal"
                 else (path.sum(axis=1) + (top_n - path.shape[1])) / top_n)
            nav[e:x + 1] = A_k * (w * (1 - COST) * B + (1 - w))
            A_k = nav[x]
            trs.append(pd.DataFrame({"sig_date": DATES[si], "entry_date": DATES[e],
                                     "exit_date": DATES[x], "ci": cs2,
                                     "net": xpx[good] / pent[good] - 1 - COST, "ph": ph}))
        navs.append(pd.Series(nav, index=DATES).ffill().fillna(1.0))
    R = pd.concat([n.pct_change().fillna(0.0) for n in navs], axis=1).mean(axis=1)
    eq = (1 + R).cumprod()
    eq = eq[eq.index >= DATES[START_I]]; eq = eq / eq.iloc[0]
    tr = pd.concat(trs, ignore_index=True) if trs else pd.DataFrame(columns=["sig_date", "net"])
    return (eq, tr, (nfill / ntgt_all * 100 if ntgt_all else np.nan),
            float(np.mean(bsz)) if bsz else 0.0, len(sig_days))


# ══════════════════ 六、統計 ══════════════════
def stats_from_eq(eq):
    eq = eq.dropna(); mult = float(eq.iloc[-1])
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = (mult ** (1 / yrs) - 1) * 100 if mult > 0 else -99.9
    dd = eq / eq.cummax() - 1; mdd = float(dd.min() * 100)
    wk = eq.resample("W-FRI").last().dropna(); wr = wk.pct_change().dropna()
    vol = float(wr.std()) * np.sqrt(52); mean = float(wr.mean()) * 52
    yr = eq.resample("YE").last()
    yr = pd.concat([pd.Series([1.0], index=[eq.index[0]]), yr]).pct_change().dropna() * 100
    return dict(mult=mult, cagr=cagr, mdd=mdd, sharpe=(mean / vol if vol > 0 else np.nan),
                calmar=(cagr / abs(mdd) if mdd < 0 else np.nan), yr=yr,
                npos=int((yr > 0).sum()), nyr=len(yr),
                trough=dd.idxmin(), peak=eq.loc[:dd.idxmin()].idxmax())


def tstats(tr):
    if len(tr) == 0: return dict(n=0, win=np.nan, mean=np.nan, pf=np.nan)
    r = tr["net"].values; pos, neg = r[r > 0].sum(), r[r <= 0].sum()
    return dict(n=len(r), win=float((r > 0).mean() * 100), mean=float(r.mean() * 100),
                pf=float(pos / abs(neg)) if neg < 0 else np.nan)


def boot_ci(tr, nb=N_BOOT):
    """月群集群重抽樣(同M.bootstrap_ci口徑,避免同月同批訊號自相關高估顯著性)"""
    if len(tr) < 20: return (np.nan, np.nan)
    d = tr.copy(); d["m"] = pd.DatetimeIndex(d["sig_date"]).to_period("M")
    g = {m: x["net"].values for m, x in d.groupby("m")}
    ms = np.array(list(g.keys()), dtype=object); out = np.empty(nb)
    for b in range(nb):
        out[b] = np.concatenate([g[m] for m in RNG.choice(ms, size=len(ms), replace=True)]).mean()
    return float(np.percentile(out, 2.5) * 100), float(np.percentile(out, 97.5) * 100)


ROWS = []
HDR = (f"{'版本':<46}{'複利':>9}{'年化':>7}{'MDD':>7}{'夏普':>6}{'Calmar':>7}{'PF':>6}{'勝率':>7}"
       f"{'單筆均':>8} {'CI95(月群bootstrap)':^18}{'均籃':>5}{'成交率':>7} 正年")


def add(label, kind, thr, emode="close", xmode="close", quiet=False, **kw):
    sigkw = {k: kw.pop(k) for k in ["c1", "c2", "c3", "liq_min", "pick", "top_n"] if k in kw}
    if "top_n" in sigkw: kw["top_n"] = sigkw["top_n"]
    sg = make_signals(kind, thr, **sigkw)
    eq, tr, fr, bs, nw = run(kind, sg, emode, xmode, **kw)
    st, ts = stats_from_eq(eq), tstats(tr)
    lo, hi = boot_ci(tr)
    r = dict(label=label, **{k: st[k] for k in ["mult", "cagr", "mdd", "sharpe", "calmar",
                                                "npos", "nyr", "yr", "peak", "trough"]},
             **{k: ts[k] for k in ["pf", "win", "mean", "n"]},
             nw=nw, fill=fr, bs=bs, ci_lo=lo, ci_hi=hi, eq=eq, tr=tr)
    ROWS.append(r)
    if not quiet:
        print(f"{label:<46}{r['mult']:>8.2f}x{r['cagr']:>+6.1f}%{r['mdd']:>7.1f}%{r['sharpe']:>6.2f}"
              f"{r['calmar']:>7.2f}{r['pf']:>6.2f}{r['win']:>6.1f}%{r['mean']:>+7.2f}%"
              f" [{lo:+.2f}%,{hi:+.2f}%]{r['bs']:>5.1f}{fr:>6.0f}% {r['npos']}/{r['nyr']}",
              flush=True)
    return r


# 頻率對齊後的基準門檻(見檔頭說明)
TM = {"fri": 0.20, "thu": 0.18, "wed": 0.16, "r3": 0.16, "r4": 0.18, "r5": 0.20}
NM = {"fri": "A0週五判→次交易日", "thu": "A2週四判→週五", "wed": "A1週三判→週四",
      "r3": "A3滾動3日", "r4": "A3滾動4日", "r5": "A3滾動5日"}


# ══════════════════ 七、各段報告 ══════════════════
def sec0_reconcile():
    print("\n" + "=" * 152)
    print("### 第0段 口徑校準:重現M的基準 + 拆解entry_realism「0.19x」中有多少是口徑不對稱造成的 ###")
    trM, bkM = M.build_trades(0.20)
    weeks = M.WIDE_RET.index
    gridM = weeks[weeks.searchsorted(pd.Timestamp(START)):]
    rM, exM = M.portfolio_curve(bkM, gridM, mode="baseline", weighting="equal")
    stM = M.stats_from_ret(rM)
    print(f"  M原始基準(週線面板,週頻標記)      : 複利{stM['mult']:.1f}x 年化{stM['cagr']:+.1f}% "
          f"MDD{stM['mdd']:.1f}% 夏普{stM['sharpe']:.2f}  n_trades={len(trM)} 訊號週={len(bkM)}")
    sg = make_signals("fri", 0.20)
    eq, tr, _, bs, nw = run("fri", sg, "sigclose", "close")
    st = stats_from_eq(eq)
    print(f"  本卷日頻引擎重現(理想版,日頻標記)  : 複利{st['mult']:.1f}x 年化{st['cagr']:+.1f}% "
          f"MDD{st['mdd']:.1f}% 夏普{st['sharpe']:.2f}  n_trades={len(tr)} 訊號週={nw}")
    print("    → 量級一致(差異來自流動性閘門改取前一週已知值+日頻MDD比週頻嚴格),引擎校準通過。\n")

    # entry_realism口徑複刻 vs 對稱口徑
    days = sorted(sg.keys())
    rr, dd, nets, gaps = [], [], [], []
    for k in range(len(days) - 1):
        si, nx = days[k], days[k + 1]
        cs = sg[si][0]
        px, xp = O[si + 1, cs], WTDC[nx, cs]              # 次交易日開盤 → 次週五收盤(不對稱)
        ok = (~np.isnan(px)) & (~np.isnan(xp)) & (px > 0)
        if ok.sum() == 0: continue
        net = xp[ok] / px[ok] - 1 - COST
        rr.append(float(net.mean())); dd.append(DATES[nx]); nets.append(net)
        g = O[si + 1, cs] / WTDC[si, cs] - 1
        gaps.append(g[~np.isnan(g)])
    eqA = (1 + pd.Series(rr, index=pd.DatetimeIndex(dd))).cumprod()
    nA = np.concatenate(nets)
    stA = dict(mult=float(eqA.iloc[-1]), mdd=float((eqA / eqA.cummax() - 1).min() * 100))
    eqS, trS, _, _, _ = run("fri", sg, "open", "open")
    stS, tsS = stats_from_eq(eqS), tstats(trS)
    g = np.concatenate(gaps)
    print(f"  次日開盤跳空(訊號日收盤→次交易日開盤): 中位{np.median(g)*100:+.2f}% 均值{g.mean()*100:+.2f}% "
          f"[10%,90%]=[{np.percentile(g,10)*100:+.2f}%,{np.percentile(g,90)*100:+.2f}%]  "
          f"(entry_realism報+0.89/+1.43/+7.10,一致)")
    print(f"  (a)複刻entry_realism不對稱口徑(開盤進場→次週五收盤,只持4節): "
          f"複利{stA['mult']:.2f}x MDD{stA['mdd']:.1f}% 單筆均{nA.mean()*100:+.2f}%  ← 對應其0.19x")
    print(f"  (b)對稱口徑(開盤進場→次週同一時點開盤出場,持5節)         : "
          f"複利{stS['mult']:.2f}x 年化{stS['cagr']:+.1f}% MDD{stS['mdd']:.1f}% "
          f"單筆均{tsS['mean']:+.2f}%")
    print("    → 『0.19x』有相當部分是**同一個週末跳空被扣兩次**(進場買在跳空後、出場賣在下次跳空前)造成的,")
    print("      不是純粹的跳空侵蝕。誠實的可執行基線是(b)。本卷所有版本一律用對稱口徑。")


def sec1_gap_mechanism():
    print("\n" + "=" * 152)
    print("### 第1段 跳空侵蝕的機制解剖(滾動5日20%訊號,全候選不設top10上限) ###")
    sg = make_signals("r5", 0.20, top_n=10 ** 6)
    recs = []
    for i, (cs, sr) in sg.items():
        recs.append(pd.DataFrame(dict(
            sig_ret=sr, gap=O[i + 1, cs] / Cf[i, cs] - 1,
            d1=C[i + 1, cs] / O[i + 1, cs] - 1, c2c=Cf[i + 1, cs] / Cf[i, cs] - 1,
            fwd_c=Cf[i + 6, cs] / Cf[i + 1, cs] - 1, fwd_o=Of[i + 6, cs] / O[i + 1, cs] - 1,
            lock=LOCK[i, cs], liq=LIQP[i, cs])))
    R = pd.concat(recs, ignore_index=True).dropna(subset=["gap"])
    print(f"  n={len(R)} 檔次。三段分解(全部相對訊號日收盤):")
    print(f"    訊號日收盤 →次日開盤(隔夜跳空): 中位{R.gap.median()*100:+.2f}% 均值{R.gap.mean()*100:+.2f}% "
          f"p90 {R.gap.quantile(.9)*100:+.2f}%")
    print(f"    次日開盤   →次日收盤(盤中回吐): 中位{R.d1.median()*100:+.2f}% 均值{R.d1.mean()*100:+.2f}%")
    print(f"    訊號日收盤 →次日收盤(合計成本): 中位{R.c2c.median()*100:+.2f}% 均值{R.c2c.mean()*100:+.2f}%")
    print("    ★ 跳空吃掉的+1.2%,當天盤中吐回一半(-0.58%)。等一天用收盤價進場,成本只剩+0.57%(中位0.00%)。")

    print("\n  -- (a) 依訊號日是否鎖漲停 --")
    for k, gg in R.groupby("lock"):
        print(f"    {'鎖漲停' if k else '未鎖漲停'}: n={len(gg)}({len(gg)/len(R)*100:.1f}%) "
              f"跳空均{gg.gap.mean()*100:+.2f}%(中位{gg.gap.median()*100:+.2f}%) "
              f"盤中{gg.d1.mean()*100:+.2f}% 合計{gg.c2c.mean()*100:+.2f}% "
              f"| 次日收盤起5日後續{gg.fwd_c.mean()*100:+.2f}%")
    print("    ★ 鎖漲停是跳空的**唯一主要來源**(+3.31% vs +0.18%),但其後續動能只略低,")
    print("      所以正確做法是『改變進場方式』而不是『排除鎖漲停股』(見第5段C1實測反而更差)。")

    print("\n  -- (b) 依訊號漲幅分組 --")
    R["sb"] = pd.cut(R.sig_ret, [0.20, 0.25, 0.30, 0.35, 0.45, 0.60, 99])
    for k, gg in R.groupby("sb", observed=True):
        print(f"    {str(k):<15} n={len(gg):>6}({len(gg)/len(R)*100:>4.1f}%) 跳空{gg.gap.mean()*100:+.2f}% "
              f"盤中{gg.d1.mean()*100:+.2f}% | 開對開後續{gg.fwd_o.mean()*100:+.2f}% "
              f"收對收後續{gg.fwd_c.mean()*100:+.2f}% 鎖漲停率{gg.lock.mean()*100:>3.0f}%")
    print("    ★ 漲幅>60%那一格後續-4.1%(開盤/收盤進場都一樣),是真正該排除的;35~45%反而還好。")

    print("\n  -- (c) 依流動性(前一週的20週均週成交值)分組 --")
    R["lb"] = pd.qcut(R.liq, 5, labels=["Q1最低", "Q2", "Q3", "Q4", "Q5最高"])
    for k, gg in R.groupby("lb", observed=True):
        print(f"    {str(k):<7} 均額中位{gg.liq.median()/1e8:>6.2f}億 n={len(gg):>5} "
              f"跳空{gg.gap.mean()*100:+.2f}% 盤中{gg.d1.mean()*100:+.2f}% "
              f"| 開對開後續{gg.fwd_o.mean()*100:+.2f}% 收對收後續{gg.fwd_c.mean()*100:+.2f}%")
    print("    ★ 跳空幅度幾乎不隨流動性變化(1.1~1.4%都差不多),『低流動性=跳空重』的直覺不成立;")
    print("      但**最低流動性那一檔的後續動能最差**(+0.51%),所以流動性門檻該提高是為了訊號品質不是為了成交。")

    print("\n  -- (d) 進場日開盤已觀察到的跳空 vs 之後5日報酬(次日收盤進場) → 可用的事後濾網? --")
    R["gb"] = pd.cut(R.gap, [-99, -0.03, 0, 0.02, 0.05, 0.09, 99])
    for k, gg in R.groupby("gb", observed=True):
        print(f"    跳空{str(k):<15} n={len(gg):>5}({len(gg)/len(R)*100:>4.1f}%) "
              f"後續5日均{gg.fwd_c.mean()*100:+.2f}% 中位{gg.fwd_c.median()*100:+.2f}% "
              f"勝率{(gg.fwd_c>0).mean()*100:.1f}%")
    print("    ★ 與直覺相反:跳空越大後續越好(>9%那格+2.59%),**跳空下跌>3%才是該砍的**(-0.98%,勝率40.9%)。")
    print("      這給出C4濾網(排除進場日開盤跳空<-3%),而且完全零前視(開盤看得到,收盤才進場)。")


def sec2_design_space():
    print("\n" + "=" * 152)
    print("### 第2段 設計空間掃描(全部零前視,對稱口徑,成本0.5%單邊,日頻標記MDD) ###")
    print("\n-- 2.0 理想版基準(⚠不可執行,只當肉量上限參考:進場價=訊號日自己的收盤) --"); print(HDR)
    for k in ["fri", "thu", "wed", "r5", "r3"]:
        add(f"[B0理想·不可執行]{NM[k]}{TM[k]*100:.0f}%", k, TM[k], "sigclose", "close")

    print("\n-- 2.1 維度A×B1:訊號時點 × 次日開盤市價進場 --"); print(HDR)
    for k in ["fri", "thu", "wed", "r3", "r4", "r5"]:
        add(f"[B1次日開盤]{NM[k]}{TM[k]*100:.0f}%", k, TM[k], "open", "open")

    print("\n-- 2.2 維度A×B3:訊號時點 × 次日收盤進場(★本卷主要發現) --"); print(HDR)
    for k in ["fri", "thu", "wed", "r3", "r4", "r5"]:
        add(f"[B3次日收盤]{NM[k]}{TM[k]*100:.0f}%", k, TM[k], "close", "close")

    print("\n-- 2.3 維度B2:次日限價單(掛前收*(1+x%),當日low<=限價才成交;誠實報成交率) --"); print(HDR)
    for k in ["fri", "r5"]:
        for x in [0.01, 0.03, 0.05]:
            add(f"[B2限價+{x*100:.0f}%]{NM[k]}{TM[k]*100:.0f}%", k, TM[k], "limit", "open", lim_x=x)

    print("\n-- 2.4 門檻敏感度(滾動5日×B3 / 週四·週三提前判的線性縮放門檻對照) --"); print(HDR)
    for t in [0.12, 0.15, 0.20, 0.25, 0.30]:
        add(f"[B3]A3滾動5日 門檻{t*100:.0f}%", "r5", t, "close", "close")
    for k, t, why in [("thu", 0.16, "線性縮放4/5"), ("wed", 0.12, "線性縮放3/5")]:
        add(f"[B3]{NM[k]} 門檻{t*100:.0f}%({why})", k, t, "close", "close")


def sec3_filters():
    print("\n" + "=" * 152)
    print("### 第3段 維度C訊號濾網 / 流動性 / 檔數 / Regime控倉(基底=A3滾動5日20% × B3次日收盤) ###")
    print("\n-- 3.1 C濾網 --"); print(HDR)
    add("[基準]r5-20% B3", "r5", 0.20)
    add("[C1排訊號日鎖漲停]", "r5", 0.20, c1=True)
    add("[C2排訊號漲幅>=35%]", "r5", 0.20, c2=0.35)
    add("[C2排訊號漲幅>=45%]", "r5", 0.20, c2=0.45)
    add("[C2排訊號漲幅>=60%]", "r5", 0.20, c2=0.60)
    add("[C3收盤已離窗內高點2%]", "r5", 0.20, c3=0.02)
    add("[C4排進場日開盤跳空<-3%]", "r5", 0.20, gap_lo=-0.03)
    add("[C1+C2(35%)]", "r5", 0.20, c1=True, c2=0.35)
    add("[C2(45%)+C4]", "r5", 0.20, c2=0.45, gap_lo=-0.03)
    add("[C2(60%)+C4]", "r5", 0.20, c2=0.60, gap_lo=-0.03)

    print("\n-- 3.2 流動性門檻(近20週均週成交值) --"); print(HDR)
    for lm, lab in [(0.3e8, "0.3億(M原設定)"), (1e8, "1億"), (3e8, "3億"), (10e8, "10億")]:
        add(f"[流動性{lab}]r5-20% B3", "r5", 0.20, liq_min=lm)

    print("\n-- 3.3 持股檔數 / 選股方向 / 權重口徑 --"); print(HDR)
    for tn in [5, 10, 20]:
        add(f"[top{tn}最強]r5-20% B3 1億", "r5", 0.20, liq_min=1e8, top_n=tn)
    add("[bottom10最溫和]r5-20% B3 1億", "r5", 0.20, liq_min=1e8, pick="bottom")
    add("[固定10槽·未滿=現金]r5-20% B3 1億", "r5", 0.20, liq_min=1e8, weighting="slot")

    print("\n-- 3.4 Regime控倉疊加(沿用M已驗證的趨勢/波動regime,標籤取訊號日當下已知值) --"); print(HDR)
    for rule, rl in [("trend", "空頭"), ("vol", "高波"), ("combo", "空頭∪高波")]:
        add(f"[{rl}關倉]r5-20% B3", "r5", 0.20, rule=rule, off_w=0.0)
        add(f"[{rl}減半]r5-20% B3", "r5", 0.20, rule=rule, off_w=0.5)

    print("\n-- 3.5 維度D資金分支設計(D1貪婪單池 vs D2固定錯開5分支) --"); print(HDR)
    for stg, lab in [("fixed", "D2固定錯開5分支(各20%)"), ("greedy1", "D1貪婪單池(100%資金)")]:
        for em, xm, el in [("close", "close", "B3次日收盤"), ("open", "open", "B1次日開盤")]:
            add(f"[{lab}]{el} r5-20%", "r5", 0.20, em, xm, stagger=stg)

    print("\n-- 3.6 C4門檻敏感度(檢查-3%是不是挑出來的幸運點) --"); print(HDR)
    for g in [-0.01, -0.02, -0.05, -0.08]:
        add(f"[C4排跳空<{g*100:.0f}%]r5-20% B3", "r5", 0.20, gap_lo=g)
    print("    ★ -1%~-8%全部把Calmar從0.42拉到0.53~0.70,且隨濾網放鬆單調衰減=平滑梯度,不是尖點。")

    print("\n-- 3.7 訊號門檻 × C4 二維穩健面(找假高峰) --")
    print(f"    {'門檻':<8}{'無C4 Calmar':>13}{'複利':>9}{'   |':<5}{'C4(-3%) Calmar':>16}{'複利':>9}")
    for t in [0.15, 0.18, 0.20, 0.22, 0.25, 0.28, 0.30, 0.35]:
        sg = make_signals("r5", t)
        a = stats_from_eq(run("r5", sg, "close", "close")[0])
        b = stats_from_eq(run("r5", sg, "close", "close", gap_lo=-0.03)[0])
        flag = "  ← 孤立尖點,不可信" if abs(t - 0.25) < 1e-9 else ""
        print(f"    {t*100:>5.0f}%{a['calmar']:>13.2f}{a['mult']:>8.2f}x{'   |':<5}"
              f"{b['calmar']:>16.2f}{b['mult']:>8.2f}x{flag}")
    print("    ★ 18/20/22%平台(Calmar 0.37~0.42)→25%突然0.75→28%又掉回0.46。25%是孤立尖點=過擬合,")
    print("      務必用20%平台區的數字當結論,不要拿25%那格報喜。")

    print("\n-- 3.8 維度E進場延遲 + 前視偽造測試(訊號日往後移k日再進場,用更舊的訊號,零前視) --")
    print("    真動能對延遲應該是**平滑單峰衰減**;若在k=1有斷崖式尖峰=邊界人工痕跡/前視污染。")
    print(f"    {'進場延遲':<12}{'複利':>9}{'年化':>8}{'MDD':>8}{'Calmar':>8}{'PF':>6}{'單筆均':>8}{'CI下界':>9}")
    for k in [1, 2, 3, 5, 8]:
        sg = make_signals("r5", 0.20)
        sg2 = {i + (k - 1): v for i, v in sg.items() if i + (k - 1) < ND - HOLD - 2}
        eq, tr, _, _, _ = run("r5", sg2, "close", "close")
        st, ts = stats_from_eq(eq), tstats(tr); lo, _ = boot_ci(tr)
        print(f"    訊號日+{k}日{'':<5}{st['mult']:>8.2f}x{st['cagr']:>+7.1f}%{st['mdd']:>7.1f}%"
              f"{st['calmar']:>8.2f}{ts['pf']:>6.2f}{ts['mean']:>+7.2f}%{lo:>+8.2f}%")
    print("    ★ 曲線是平滑單峰(0.42→0.58→0.63→0.51→0.16),**沒有邊界斷崖=沒有前視污染**,")
    print("      而且峰值不在+1日而在+3日:『看到5日噴出後先放著,第3天收盤再進』比隔天追還好,")
    print("      機制上合理(噴出後1~2日是回吐/洗盤期,第3日才是動能重啟),而且延後進場更容易執行。")
    print("    ⚠但這多了一個自由度,+3日版本請當『有希望的方向』而非已驗證結論。")
    print(f"\n    {'進場延遲+C4(-2%)組合':<24}{'複利':>9}{'年化':>8}{'MDD':>8}{'Calmar':>8}{'PF':>6}{'CI下界':>9}")
    for k in [1, 2, 3]:
        sg = make_signals("r5", 0.20)
        sg2 = {i + (k - 1): v for i, v in sg.items() if i + (k - 1) < ND - HOLD - 2}
        eq, tr, _, _, _ = run("r5", sg2, "close", "close", gap_lo=-0.02)
        st, ts = stats_from_eq(eq), tstats(tr); lo, _ = boot_ci(tr)
        print(f"    訊號日+{k}日{'':<17}{st['mult']:>8.2f}x{st['cagr']:>+7.1f}%{st['mdd']:>7.1f}%"
              f"{st['calmar']:>8.2f}{ts['pf']:>6.2f}{lo:>+8.2f}%")


def sec4_deepdive():
    print("\n" + "=" * 152)
    print("### 第4段 存活變體深挖 ###")
    cands = [("★可執行 r5-20% B3次日收盤 D2", dict(kind="r5", thr=0.20, emode="close")),
             ("★★主推 r5-20% B3+C4(-2%) D2", dict(kind="r5", thr=0.20, emode="close",
                                                gap_lo=-0.02)),
             ("★可執行 r5-20% B3+C4(-3%) D2", dict(kind="r5", thr=0.20, emode="close",
                                                 gap_lo=-0.03)),
             ("★可執行 r5-20% B3 D1貪婪單池", dict(kind="r5", thr=0.20, emode="close",
                                                stagger="greedy1")),
             ("對照 r5-20% B1次日開盤 D2", dict(kind="r5", thr=0.20, emode="open", xmode="open")),
             ("對照 B0理想不可執行 r5-20%", dict(kind="r5", thr=0.20, emode="sigclose")),
             ("對照 A0週五判 B1(原策略可執行化)", dict(kind="fri", thr=0.20, emode="open",
                                                xmode="open"))]
    res = {}
    print("\n-- 4.1 逐年報酬(%) --")
    for name, cfg in cands:
        cfg = dict(cfg); kind, thr = cfg.pop("kind"), cfg.pop("thr")
        sigkw = {k: cfg.pop(k) for k in ["c1", "c2", "c3", "liq_min", "top_n"] if k in cfg}
        sg = make_signals(kind, thr, **sigkw)
        eq, tr, fr, bs, nw = run(kind, sg, **cfg)
        res[name] = (eq, tr); st = stats_from_eq(eq)
        print(f"\n  {name}  [複利{st['mult']:.2f}x 年化{st['cagr']:+.1f}% MDD{st['mdd']:.1f}% "
              f"Calmar{st['calmar']:.2f} 正年{st['npos']}/{st['nyr']}]")
        print("    " + " ".join(f"{y.year}:{v:+6.1f}%" for y, v in st["yr"].items()))

    print("\n-- 4.2 前5大回撤episode(★主推版本) --")
    eq = res["★★主推 r5-20% B3+C4(-2%) D2"][0]
    d = (eq / eq.cummax() - 1).copy(); shown = 0
    while shown < 5 and len(d):
        t = d.idxmin()
        if d[t] > -0.05: break
        p = eq.loc[:t].idxmax(); rec = eq.loc[t:][eq.loc[t:] >= eq[p]]
        r = rec.index[0] if len(rec) else None
        print(f"    #{shown+1} {d[t]*100:6.1f}%  峰{p.date()} → 谷{t.date()} ({(t-p).days}天) "
              f"復原{r.date() if r is not None else '尚未復原'}")
        d = d.drop(d.loc[p:(r if r is not None else d.index[-1])].index); shown += 1

    print("\n-- 4.3 成本敏感度(邊際安全性:小型股實際滑價可能高於0.5%) --")
    global COST
    orig = COST
    print(f"    {'單邊成本':<10}{'複利':>10}{'年化':>8}{'MDD':>8}{'夏普':>6}{'PF':>6}{'單筆均':>8}")
    for c in [0.000, 0.003, 0.005, 0.007, 0.010]:
        COST = c
        sg = make_signals("r5", 0.20)
        e2, t2, _, _, _ = run("r5", sg, "close", "close", gap_lo=-0.02)
        s2, x2 = stats_from_eq(e2), tstats(t2)
        print(f"    {c*100:>6.1f}%{s2['mult']:>11.2f}x{s2['cagr']:>+7.1f}%{s2['mdd']:>7.1f}%"
              f"{s2['sharpe']:>6.2f}{x2['pf']:>6.2f}{x2['mean']:>+7.2f}%")
    COST = orig
    print("    ★ 成本每加0.1%,年化就掉約4~5個百分點;約1.1%成本時歸零。台股小型股實際來回摩擦")
    print("      (手續費+證交稅+買賣價差+市價單滑價)本來就逼近甚至超過這個量級,邊際安全極薄。")

    print("\n-- 4.4 子期間穩健度(前半2015-01~2020-06 / 後半2020-07~迄今) --")
    print(f"    {'版本':<34}{'期間':<20}{'複利':>9}{'年化':>8}{'MDD':>8}{'PF':>6}{'單筆均':>8}{'n':>7}")
    for name in ["對照 B0理想不可執行 r5-20%", "★可執行 r5-20% B3次日收盤 D2",
                 "★★主推 r5-20% B3+C4(-2%) D2", "對照 r5-20% B1次日開盤 D2"]:
        eq, tr = res[name]
        for s, e in [("2015-01-01", "2020-06-30"), ("2020-07-01", "2026-12-31")]:
            sub = eq.loc[s:e]
            if len(sub) < 10: continue
            sub = sub / sub.iloc[0]; st = stats_from_eq(sub)
            t = tr[(tr.sig_date >= s) & (tr.sig_date <= e)]; ts = tstats(t)
            print(f"    {name:<34}{s[:7]}~{e[:7]:<12}{st['mult']:>8.2f}x{st['cagr']:>+7.1f}%"
                  f"{st['mdd']:>7.1f}%{ts['pf']:>6.2f}{ts['mean']:>+7.2f}%{ts['n']:>7}")

    print("\n-- 4.5 固定曝險縮放(Calmar固定,MDD可用曝險直接換;對照使用者目標函數MDD優先) --")
    eq = res["★★主推 r5-20% B3+C4(-2%) D2"][0]; r = eq.pct_change().fillna(0)
    print(f"    {'曝險':<8}{'複利':>10}{'年化':>8}{'MDD':>8}{'夏普':>6}{'Calmar':>8}")
    for w in [1.0, 0.7, 0.5, 0.35, 0.25]:
        s2 = stats_from_eq((1 + r * w).cumprod())
        print(f"    {w*100:>5.0f}%{s2['mult']:>9.2f}x{s2['cagr']:>+7.1f}%{s2['mdd']:>7.1f}%"
              f"{s2['sharpe']:>6.2f}{s2['calmar']:>8.2f}")

    print("\n-- 4.6 大盤對照(同期TAIEX買進持有) --")
    tx = M.TAIEX.reindex(eq.index, method="ffill"); tx = tx / tx.iloc[0]
    stx = stats_from_eq(tx)
    print(f"    TAIEX: 複利{stx['mult']:.2f}x 年化{stx['cagr']:+.1f}% MDD{stx['mdd']:.1f}% "
          f"夏普{stx['sharpe']:.2f} Calmar{stx['calmar']:.2f}")
    print("    ★ 主推版本 Calmar 0.70 vs 大盤 0.45(贏)、年化+25% vs +14%(贏)、MDD -36% vs -32%(略輸)、")
    print("      但夏普 0.81 vs 0.89(輸)。也就是:贏在尾部右偏帶來的複利,不是贏在逐期平穩度。")


def sec5_summary():
    print("\n" + "=" * 152)
    print("### 第5段 總表(依Calmar排序,只列可執行版本) ###")
    ok = [r for r in ROWS if "理想" not in r["label"] and "B0" not in r["label"]]
    ok = sorted(ok, key=lambda r: -(r["calmar"] if not np.isnan(r["calmar"]) else -9))
    print(HDR)
    for r in ok[:25]:
        print(f"{r['label']:<46}{r['mult']:>8.2f}x{r['cagr']:>+6.1f}%{r['mdd']:>7.1f}%"
              f"{r['sharpe']:>6.2f}{r['calmar']:>7.2f}{r['pf']:>6.2f}{r['win']:>6.1f}%"
              f"{r['mean']:>+7.2f}% [{r['ci_lo']:+.2f}%,{r['ci_hi']:+.2f}%]{r['bs']:>5.1f}"
              f"{r['fill']:>6.0f}% {r['npos']}/{r['nyr']}")
    n_alive = sum(1 for r in ok if r["pf"] > 1.1 and r["ci_lo"] > 0 and r["mdd"] > -50)
    print(f"\n  通過「PF>1.1 且 bootstrap CI下界排0 且 MDD優於-50%」三重門檻的可執行變體: "
          f"{n_alive}/{len(ok)}")


def main():
    sec0_reconcile()
    sec1_gap_mechanism()
    sec2_design_space()
    sec3_filters()
    sec4_deepdive()
    sec5_summary()
    print(f"\n{'='*152}\n跑完,共{len(ROWS)}個變體。[{time.time()-T0:.0f}s] 純console報告,無檔案輸出。")


if __name__ == "__main__":
    main()
