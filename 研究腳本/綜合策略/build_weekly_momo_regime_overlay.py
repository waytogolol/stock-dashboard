# -*- coding: utf-8 -*-
"""週級強者續強×Regime控倉疊加測試(2026-08-04,使用者:「用既有regime天氣線矩陣方法論,測試regime條件式
控倉能不能把MDD壓下來」)。

背景: 週級強者續強廣宇宙複測(全市場fm_daily_price,2015起,0.3億20週均額流動性過濾,top10持股上限)
20%門檻版本方向確認為真但風險特徵明顯變差,MDD遠高於原133檔動能宇宙研究(-27.8%),疑似動能股系統性crash
risk,兩次最大回撤(2025-04關稅崩盤/2026-07-24修正)皆對應真實大盤重挫。`build_regime_weather_report.py`
已證實九個既有策略在不同regime下表現差很多,但週級動能還沒被排進這張矩陣——本卷補上,並測試regime條件式
控倉(開關/減碼)能否把MDD壓下來。

規模說明(探索腳本,原scratchpad版已清空,本卷依同樣邏輯重新建置,數字會與會談當下口頭報告的88.58x/
MDD-52.7%有出入,原因見下方「與背景數字的落差」——不強求逐位重現,重點是同一套邏輯下regime控倉有沒有用):

Regime口徑(比照`build_strategy_regime_matrix.py`R1斜率版+`build_regime_weather_report.py`R3波動軸,
兩者都已在原regime矩陣考卷驗證過,直接沿用公式不重新發明規則,只調整波動軸的計算方式避免前視):
  趨勢regime(3態,零前視,逐日可判): 多頭=收盤>年線(MA240)且年線20日斜率(diff20)>0;
                                  空頭=收盤<年線且斜率<0;盤整=其餘
  波動regime(2態): vp10=加權指數日報酬10日std,在2006起樣本內排百分位;高波=vp10>=80,低波=vp10<80
  ⚠與原report的差異: build_regime_weather_report.py的vp10用全樣本一次性rank(pct=True),等於用到了
  「未來」的分佈資訊,對描述性盤點報告可以接受,但本卷是要拿regime標籤做進出場開關,必須零前視——
  這裡改用expanding causal rank(每一天只用<=當天已發生的樣本做排名),這是本卷唯一偏離原報告口徑之處,
  趨勢regime公式/vp10高波門檻(80)都原樣照搬。

週級動能訊號建置(同2026-08-04廣宇宙複測邏輯): 全市場fm_daily_price(2015起訊號,2014起抓資料留20週流動性
緩衝),週化比照`build_heat_flow_hist.py`慣例(W-FRI週化,close取週最後一筆,money取週加總);
訊號=當週報酬>=門檻(測20%為主/15%當敏感度)且近20週均週成交值>=0.3億;每週訊號股>10檔時取當週最強前10檔
(比照持有10檔目標);進場=訊號週收盤,出場=次週收盤(固定持有一週);成本=0.5%/筆(單邊扣一次,非來回各0.5%)。
持倉權重=basket內個股等權平均(比照`build_strategy_regime_matrix.strat_sweetspot`等既有基金籃子慣例,
「取決於當週實際觸發幾檔」而非強制稀釋成固定10槽——見下方權重口徑穩健性檢查,固定槽版本另附)。
regime標籤一律取「訊號週」當下已知值(reindex+ffill,不會用到訊號週之後才知道的資訊)。

資料清洗(⚠新發現,務必記錄): fm_daily_price有約1.25%的列close<=0或money<=0(2014起3,776,052列中
47,121列,涉及903檔),是掛零的壞列(多半是當天量極少/停牌被寫成0而非NaN),若不濾掉會製造出「單週漲幅=inf」
「單週跌幅=-100%」的偽事件(親自抓到一例: 5287某週收盤真實值247附近,但因鄰週被寫成0.0,造出entry_ret=inf
的假訊號+次週淨-100%的假崩盤,是整條回測早期版本MDD失真的最大原因)。本卷在建週線面板前用
`close>0 & money>0`過濾,兩門檻表格程式建議之後若有全市場fm_daily_price相關考卷都比照加這道清洗。

與背景數字的落差: 本卷reproduce的基準版(20%門檻+top10,等權)複利~127x/年化~52%/MDD~-47%/夏普~1.12,
量級跟會談口頭報告的88.58x/47.2%/-52.7%/1.20接近但非逐位相同,合理推測差異來自(a)上述資料清洗(原探索
版可能沒抓到這個bug,也可能已抓到,無從對照)(b)持倉權重口徑選擇(等權vs固定10槽,兩者MDD結構差很多,
見下方測試)。這不影響本卷核心任務(regime控倉的相對比較),兩版本在同一套資料/邏輯下做基準vs開關vs減碼
的內部比較才是重點。

用法: python 研究腳本/綜合策略/build_weekly_momo_regime_overlay.py  (從根目錄執行,鐵律)
產出: 純console報告(探索階段,不產出HTML,不寫快取,每次重跑約1-2分鐘)
"""
import bisect
import sqlite3
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

DB = "capital_flow.db"
COST = 0.005                  # 單邊成本0.5%,扣一次(非來回各0.5%)
LIQ_MIN = 0.3e8                # 近20週均週成交值門檻
TOP_N = 10
START = "2015-01-01"           # 回測起點(訊號週)
BUFFER_START = "2014-01-01"    # 面板抓取起點(留20週流動性緩衝)
VOL_BASE = "2006-01-01"        # 波動regime排百分位的起算點(同原report)
N_BOOT = 2000
RNG = np.random.default_rng(20260804)


# ══ 一、Regime序列(零前視) ══════════════════════════════════
def load_taiex():
    con = sqlite3.connect(DB)
    s = pd.read_sql("SELECT date, close FROM index_daily WHERE market='TAIEX' ORDER BY date",
                     con, parse_dates=["date"]).set_index("date")["close"]
    con.close()
    return s


def trend_regime(px):
    """比照build_strategy_regime_matrix.regime_series: 收盤vs年線×年線20日斜率,MA/斜率皆為落後窗,零前視"""
    ma240 = px.rolling(240).mean()
    slope = ma240.diff(20)
    reg = pd.Series("盤整", index=px.index)
    reg[(px > ma240) & (slope > 0)] = "多頭"
    reg[(px < ma240) & (slope < 0)] = "空頭"
    return reg


def causal_vp10(px, base=VOL_BASE):
    """vp10因果版percentile: 對每一天只用<=當天已發生樣本做rank,避免用到未來分佈資訊
    (原report用全樣本一次rank,本卷唯一偏離原報告口徑之處,見檔頭說明)"""
    r = px.pct_change() * 100
    v10 = r.rolling(10).std()
    v10 = v10[v10.index >= base].dropna()
    sorted_vals, out = [], []
    for v in v10.values:
        i = bisect.bisect_left(sorted_vals, v)
        out.append(i / len(sorted_vals) * 100 if sorted_vals else np.nan)
        bisect.insort(sorted_vals, v)
    return pd.Series(out, index=v10.index)


TAIEX = load_taiex()
REG_TREND = trend_regime(TAIEX)
REG_VP = causal_vp10(TAIEX)
REG_VOL = REG_VP.map(lambda x: "高波" if x >= 80 else "低波")


def tag_at(series, dates):
    """事件日→series最近<=該日的標籤(reindex+ffill,零前視,同build_regime_weather_report.at())"""
    d = pd.to_datetime(pd.Series(dates).values)
    return pd.Series(series.reindex(d, method="ffill").values, index=range(len(d)))


# ══ 二、週級動能面板 ══════════════════════════════════════
def build_weekly_panel():
    con = sqlite3.connect(DB)
    px = pd.read_sql(f"SELECT code, date, close, money FROM fm_daily_price WHERE date>='{BUFFER_START}'",
                      con, parse_dates=["date"])
    con.close()
    n0 = len(px)
    px = px[(px["close"] > 0) & (px["money"] > 0)]      # 資料清洗(見檔頭說明)
    print(f"資料清洗: 濾掉close<=0/money<=0共{n0 - len(px)}列(佔{(n0 - len(px)) / n0 * 100:.2f}%)")
    px["wk"] = px["date"].dt.to_period("W-FRI").dt.end_time.dt.normalize()
    w = px.sort_values("date").groupby(["code", "wk"]).agg(
        close=("close", "last"), money=("money", "sum")).reset_index()
    wide_c = w.pivot_table(index="wk", columns="code", values="close").sort_index()
    wide_m = w.pivot_table(index="wk", columns="code", values="money").sort_index()
    return wide_c, wide_m


print("建置週線面板(全市場fm_daily_price,2014起)...")
WIDE_C, WIDE_M = build_weekly_panel()
WIDE_RET = WIDE_C.pct_change(fill_method=None)
LIQ20 = WIDE_M.rolling(20).mean()
LIQ_OK = LIQ20 >= LIQ_MIN
print(f"面板shape={WIDE_C.shape}(週數×檔數)")


def build_trades(threshold, top_n=TOP_N):
    """回傳(trades逐筆表, weekly_baskets={entry_week: DataFrame已依entry_ret降冪排序,cap<=top_n})"""
    weeks = WIDE_RET.index
    start_i = weeks.searchsorted(pd.Timestamp(START))
    trades, weekly_baskets = [], {}
    for i in range(max(start_i, 1), len(weeks) - 1):
        wk = weeks[i]
        ret_i = WIDE_RET.iloc[i]
        liq_i = LIQ_OK.iloc[i].reindex(ret_i.index).fillna(False)
        cand = ret_i[(ret_i >= threshold) & liq_i].dropna().sort_values(ascending=False)
        if len(cand) == 0:
            continue
        if len(cand) > top_n:
            cand = cand.iloc[:top_n]
        exit_ret = WIDE_RET.iloc[i + 1]
        rows = []
        for c in cand.index:
            er = exit_ret.get(c, np.nan)
            if pd.isna(er):
                continue
            rows.append({"entry_week": wk, "exit_week": weeks[i + 1], "code": c,
                         "entry_ret": float(cand[c]), "exit_ret": float(er),
                         "net_ret": float(er) - COST})
        if rows:
            df = pd.DataFrame(rows)
            weekly_baskets[wk] = df
            trades.extend(rows)
    trades = pd.DataFrame(trades)
    trades["reg_trend"] = tag_at(REG_TREND, trades["entry_week"]).values
    trades["reg_vol"] = tag_at(REG_VOL, trades["entry_week"]).values
    trades["vp10"] = tag_at(REG_VP, trades["entry_week"]).values
    return trades, weekly_baskets


# ══ 三、Portfolio建置(等權/固定10槽兩種口徑) ══════════════════
def portfolio_curve(weekly_baskets, grid, favorable_fn=None, mode="baseline",
                     reduce_frac=0.5, reduce_topn=5, weighting="equal"):
    """
    favorable_fn(entry_week)->True(有利,正常進場)/False(不利regime)
    mode: baseline(不分regime全押) / switch(不利週完全不進場) /
          reduce_capital(不利週資金減半) / reduce_count(不利週只取basket前reduce_topn檔,權重不變)
    weighting: equal(等權=basket內個股平均,取決於當週實際觸發檔數) /
               slot(固定10槽,未滿倉位視為現金0%——權重穩健性檢查用)
    回傳: (ret_series對齊grid, executed_trades明細含weight/favorable欄位)
    """
    ret = pd.Series(0.0, index=grid)
    exec_list = []
    for wk, basket in weekly_baskets.items():
        exit_wk = basket["exit_week"].iloc[0]
        if exit_wk not in ret.index:
            continue
        fav = True if favorable_fn is None else favorable_fn(wk)
        if mode == "baseline":
            use, cap_w = basket, 1.0
        elif mode == "switch":
            if fav:
                use, cap_w = basket, 1.0
            else:
                continue
        elif mode == "reduce_capital":
            use, cap_w = basket, (1.0 if fav else reduce_frac)
        elif mode == "reduce_count":
            use, cap_w = (basket if fav else basket.iloc[:reduce_topn]), 1.0
        else:
            raise ValueError(mode)
        if weighting == "equal":
            pr = float(use["net_ret"].mean()) * cap_w
        elif weighting == "slot":
            pr = float(use["net_ret"].sum()) / TOP_N * cap_w
        else:
            raise ValueError(weighting)
        ret.loc[exit_wk] = pr
        exec_list.append(use.assign(weight=cap_w, favorable=fav))
    exec_trades = pd.concat(exec_list, ignore_index=True) if exec_list else pd.DataFrame(
        columns=list(next(iter(weekly_baskets.values())).columns) + ["weight", "favorable"])
    return ret, exec_trades


def stats_from_ret(ret_series):
    r = ret_series.dropna()
    eq = (1 + r).cumprod()
    mult = float(eq.iloc[-1])
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = (mult ** (1 / yrs) - 1) * 100 if mult > 0 else np.nan
    dd = eq / eq.cummax() - 1
    mdd = float(dd.min() * 100)
    vol_ann = float(r.std()) * np.sqrt(52)
    mean_ann = float(r.mean()) * 52
    sharpe = mean_ann / vol_ann if vol_ann > 0 else np.nan
    calmar = cagr / abs(mdd) if mdd < 0 else np.nan
    trough = dd.idxmin()
    peak = eq.loc[:trough].idxmax()
    return {"mult": mult, "cagr": cagr, "mdd": mdd, "sharpe": sharpe, "calmar": calmar,
            "n_weeks_active": int((r != 0).sum()), "n_weeks_total": len(r),
            "dd_peak": peak, "dd_trough": trough}


def trade_stats(exec_trades):
    if len(exec_trades) == 0:
        return {"n": 0, "win": np.nan, "mean": np.nan, "median": np.nan, "pf": np.nan}
    r = exec_trades["net_ret"].values
    win = float((r > 0).mean() * 100)
    pos, neg = r[r > 0].sum(), r[r <= 0].sum()
    pf = float(pos / abs(neg)) if neg < 0 else np.nan
    return {"n": len(r), "win": win, "mean": float(np.mean(r)) * 100,
            "median": float(np.median(r)) * 100, "pf": pf}


def bootstrap_ci(exec_trades, n_boot=N_BOOT):
    """月群集群重抽樣bootstrap CI(對單筆net_ret均值),避免同月同批訊號的自相關高估顯著性"""
    if len(exec_trades) < 10:
        return (np.nan, np.nan)
    d = exec_trades.copy()
    d["month"] = d["entry_week"].dt.to_period("M")
    grouped = {m: g["net_ret"].values for m, g in d.groupby("month")}
    months = np.array(list(grouped.keys()), dtype=object)
    means = np.empty(n_boot)
    for b in range(n_boot):
        samp = RNG.choice(months, size=len(months), replace=True)
        vals = np.concatenate([grouped[m] for m in samp])
        means[b] = vals.mean()
    return float(np.percentile(means, 2.5)) * 100, float(np.percentile(means, 97.5)) * 100


def yearly_breakdown(ret_series):
    r = ret_series.dropna()
    yr = r.groupby(r.index.year).apply(lambda x: (1 + x).prod() - 1) * 100
    return yr


# ══ 四、regime有利/不利規則定義 ══════════════════════════════
def rule_trend_bear_off(entry_week):
    return tag_at(REG_TREND, [entry_week]).iloc[0] != "空頭"


def rule_vol_hot_off(entry_week):
    return tag_at(REG_VOL, [entry_week]).iloc[0] != "高波"


def rule_combo_off(entry_week):
    t = tag_at(REG_TREND, [entry_week]).iloc[0]
    v = tag_at(REG_VOL, [entry_week]).iloc[0]
    return not (t == "空頭" or v == "高波")


# 為了效能,批次算好entry_week→favorable的對照表(避免每次tag_at都reindex一次)
def make_favorable_lookup(weekly_baskets, rule):
    wks = list(weekly_baskets.keys())
    if rule == "trend":
        tags = tag_at(REG_TREND, wks).values
        fav = {w: (t != "空頭") for w, t in zip(wks, tags)}
    elif rule == "vol":
        tags = tag_at(REG_VOL, wks).values
        fav = {w: (t != "高波") for w, t in zip(wks, tags)}
    elif rule == "combo":
        tt = tag_at(REG_TREND, wks).values
        vv = tag_at(REG_VOL, wks).values
        fav = {w: not (t == "空頭" or v == "高波") for w, t, v in zip(wks, tt, vv)}
    else:
        raise ValueError(rule)
    return lambda w: fav[w]


# ══ 五、主流程 ══════════════════════════════════════════
def run_threshold(threshold, label):
    print("\n" + "=" * 100)
    print(f"### 門檻={label} top{TOP_N} ###")
    trades, baskets = build_trades(threshold)
    weeks = WIDE_RET.index
    start_i = weeks.searchsorted(pd.Timestamp(START))
    grid = weeks[start_i:]
    print(f"n_trades={len(trades)}  n_signal_weeks={len(baskets)}/{len(grid)}  "
          f"樣本期間={trades.entry_week.min().date()}~{trades.entry_week.max().date()}")

    # -- regime診斷表(cross-section, 全部基準trades) --
    print("\n-- 逐筆net_ret × 趨勢regime(訊號週當下標籤) --")
    for g, sub in trades.groupby("reg_trend"):
        print(f"  {g}: n={len(sub)} 佔比{len(sub) / len(trades) * 100:.0f}% "
              f"mean={sub.net_ret.mean() * 100:+.2f}% median={sub.net_ret.median() * 100:+.2f}% "
              f"win={((sub.net_ret > 0).mean() * 100):.1f}%")
    print("-- 逐筆net_ret × 波動regime(訊號週當下標籤) --")
    for g, sub in trades.groupby("reg_vol"):
        print(f"  {g}: n={len(sub)} 佔比{len(sub) / len(trades) * 100:.0f}% "
              f"mean={sub.net_ret.mean() * 100:+.2f}% median={sub.net_ret.median() * 100:+.2f}% "
              f"win={((sub.net_ret > 0).mean() * 100):.1f}%")

    # -- 基準版(等權) --
    ret_base, exec_base = portfolio_curve(baskets, grid, mode="baseline", weighting="equal")
    st_base = stats_from_ret(ret_base)
    tr_base = trade_stats(exec_base)
    ci_base = bootstrap_ci(exec_base)

    # -- worst 15週明細(找出MDD真正驅動者,確認是系統性還是個股集中risk) --
    worst = ret_base.sort_values().head(15)
    entry_of = {b["exit_week"].iloc[0]: wk for wk, b in baskets.items()}
    print("\n-- 基準版最差15週(exit週報酬/當週basket檔數n/訊號週regime標籤) --")
    print(f"{'exit週':<12}{'portret':>9}{'entry週':<12}{'n':>3}  趨勢  波動  vp10")
    for exit_wk, r in worst.items():
        entry_wk = entry_of.get(exit_wk)
        if entry_wk is None:
            continue
        b = baskets[entry_wk]
        t = tag_at(REG_TREND, [entry_wk]).iloc[0]
        v = tag_at(REG_VOL, [entry_wk]).iloc[0]
        vp = tag_at(REG_VP, [entry_wk]).iloc[0]
        print(f"{str(exit_wk.date()):<12}{r * 100:>+8.1f}%{str(entry_wk.date()):<12}{len(b):>3}  "
              f"{t}  {v}  {vp:.0f}")
    n_worst_bear = sum(1 for exit_wk in worst.index
                       if entry_of.get(exit_wk) and tag_at(REG_TREND, [entry_of[exit_wk]]).iloc[0] == "空頭")
    n_worst_hot = sum(1 for exit_wk in worst.index
                      if entry_of.get(exit_wk) and tag_at(REG_VOL, [entry_of[exit_wk]]).iloc[0] == "高波")
    print(f"  最差15週中: 訊號週已在空頭regime={n_worst_bear}/15、已在高波regime={n_worst_hot}/15")

    # -- regime開關/減碼版本比較 --
    variants = {"基準(全押)": (None, "baseline", "equal")}
    for rname, rule in (("趨勢(空頭關)", "trend"), ("波動(高波關)", "vol"), ("趨勢∪波動(任一不利關)", "combo")):
        fav = make_favorable_lookup(baskets, rule)
        variants[f"{rname}·開關版"] = (fav, "switch", "equal")
        variants[f"{rname}·減碼50%版"] = (fav, "reduce_capital", "equal")
    fav_combo = make_favorable_lookup(baskets, "combo")
    variants["趨勢∪波動·減碼top5版"] = (fav_combo, "reduce_count", "equal")

    rows = []
    for name, (fav, mode, wgt) in variants.items():
        r, ex = portfolio_curve(baskets, grid, favorable_fn=fav, mode=mode, weighting=wgt)
        st = stats_from_ret(r)
        tr = trade_stats(ex)
        ci = bootstrap_ci(ex) if mode != "baseline" else ci_base
        yr = yearly_breakdown(r)
        rows.append({"variant": name, **st, **{f"tr_{k}": v for k, v in tr.items()},
                     "ci_lo": ci[0], "ci_hi": ci[1],
                     "n_pos_year": int((yr > 0).sum()), "n_year": len(yr),
                     "exposure": st["n_weeks_active"] / st["n_weeks_total"] * 100})

    print("\n-- 基準 vs Regime控倉版 全比較表(等權口徑) --")
    hdr = (f"{'版本':<24}{'複利':>8}{'年化':>8}{'MDD':>8}{'夏普':>6}{'報酬/MDD':>9}"
           f"{'PF':>6}{'勝率':>6}{'單筆均':>8}{'CI':>20}{'曝險':>6}{'正年':>7}")
    print(hdr)
    for row in rows:
        ci_txt = f"[{row['ci_lo']:+.2f}%,{row['ci_hi']:+.2f}%]"
        print(f"{row['variant']:<24}{row['mult']:>7.1f}x{row['cagr']:>7.1f}%{row['mdd']:>7.1f}%"
              f"{row['sharpe']:>6.2f}{row['calmar']:>9.2f}{row['tr_pf']:>6.2f}{row['tr_win']:>5.0f}%"
              f"{row['tr_mean']:>7.2f}%{ci_txt:>20}{row['exposure']:>5.0f}%{row['n_pos_year']:>4d}/{row['n_year']:<3d}")

    # -- 固定10槽權重口徑穩健性檢查(基準版+最佳regime版) --
    print("\n-- 權重口徑穩健性檢查(固定10槽,未滿倉位視為現金0%) --")
    r_slot, _ = portfolio_curve(baskets, grid, mode="baseline", weighting="slot")
    st_slot = stats_from_ret(r_slot)
    print(f"  基準(固定10槽): 複利{st_slot['mult']:.1f}x 年化{st_slot['cagr']:+.1f}% "
          f"MDD{st_slot['mdd']:.1f}% 夏普{st_slot['sharpe']:.2f} "
          f"MDD episode {st_slot['dd_peak'].date()}~{st_slot['dd_trough'].date()}")
    fav_combo2 = make_favorable_lookup(baskets, "combo")
    r_slot_sw, _ = portfolio_curve(baskets, grid, favorable_fn=fav_combo2, mode="switch", weighting="slot")
    st_slot_sw = stats_from_ret(r_slot_sw)
    print(f"  趨勢∪波動開關版(固定10槽): 複利{st_slot_sw['mult']:.1f}x 年化{st_slot_sw['cagr']:+.1f}% "
          f"MDD{st_slot_sw['mdd']:.1f}% 夏普{st_slot_sw['sharpe']:.2f}")

    print(f"\n  基準版(等權)MDD episode: {st_base['dd_peak'].date()} ~ {st_base['dd_trough'].date()} "
          f"({st_base['mdd']:.1f}%)")

    return trades, baskets, grid, rows


def crash_deep_dive():
    print("\n" + "=" * 100)
    print("### 2025-04關稅崩盤 / 2026-07-24修正 深挖(訊號週regime標籤是否提前示警) ###")
    taiex_wk = TAIEX.resample("W-FRI").last()
    taiex_wret = taiex_wk.pct_change(fill_method=None) * 100
    for label, s, e in (("2025-04-02~10關稅崩盤(全球股災)", "2025-03-01", "2025-05-01"),
                        ("2026-07-24~30台股-12%修正", "2026-06-01", "2026-08-04")):
        print(f"\n--- {label} ---")
        print(f"{'週(W-FRI)':<12}{'TAIEX週報酬':>12}  趨勢regime  波動regime  vp10")
        for wk in taiex_wret.loc[s:e].index:
            t = tag_at(REG_TREND, [wk]).iloc[0]
            v = tag_at(REG_VOL, [wk]).iloc[0]
            vp = tag_at(REG_VP, [wk]).iloc[0]
            print(f"{str(wk.date()):<12}{taiex_wret[wk]:>+11.2f}%    {t}      {v}     {vp:>5.0f}")

    print("\n-- 整體佔比對照(2015起vs2026年初起,判斷高波regime在近期是否已經常態化) --")
    for start, label in (("2015-01-01", "2015起全樣本"), ("2026-01-01", "2026年迄今")):
        seg_v = REG_VOL[REG_VOL.index >= start]
        seg_t = REG_TREND[REG_TREND.index >= start]
        print(f"  {label}: 高波佔比={float((seg_v == '高波').mean() * 100):.1f}%  "
              f"空頭佔比={float((seg_t == '空頭').mean() * 100):.1f}%")


def main():
    run_threshold(0.20, "20%")
    run_threshold(0.15, "15%")
    crash_deep_dive()
    print("\n" + "=" * 100)
    print("跑完。以上為console探索報告,無檔案輸出。")


if __name__ == "__main__":
    main()
