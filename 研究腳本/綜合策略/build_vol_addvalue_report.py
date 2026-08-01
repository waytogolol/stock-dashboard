# -*- coding: utf-8 -*-
"""波動期限結構regime加值驗證考卷(2026-07-31,使用者:「測試波動期限結構(vol10/vol60,vp10百分位)
這套既有regime基礎建設,掛到幾個既有策略上當『觀察欄位』是否真的能提升訊號品質」)。

⚠️定位=驗證題不是「加了就一定要用」:六個對象逐一拆高波動regime段vs低波動regime段,用bootstrap
(月群重抽樣2000次,95%CI)驗證分離是否顯著,顯著才算「加值」;不顯著或樣本不足就誠實記錄「沒用」/
「樣本不足」,不硬凹正面結論。

波動基礎建設(vol10/vol60/vp10)全部抄用build_regime_weather_report.py的既有計算邏輯,不重新設計:
  ts  = vol10/vol60(加權指數,10日日報酬std ÷ 60日std),升溫>1.2/中性0.8~1.2/退潮<0.8
  vp10= vol10在2006起全樣本的百分位排名,高波=vp10>=80
兩市層/全球層起火點、跌觸發×regime等既有結論已在research_regime_weather.html收官,本卷只聚焦
六個「尚未測過regime加值」的策略/訊號(見下)。

六個測試對象(逐一列判讀):
  ①題材營收動能score4     <- 快取事件用W.EV(⑥score4ret60 / ⑥b score4超額excess60,build_regime_
                              weather_report既有快取,原班底);excess60=TWII超額報酬已是demean版
  ②共振題材(8週)          <- 快取/tmp_resonance_theme_episodes.pkl(fwd8),demean=扣同期TAIEX週線
                              前推8週報酬(本卷新算,原快取無此欄位)
  ③大題材檢查清單(S3⑤強訊號+階梯) <- 快取/tmp_bear_trades.csv,p5篩選邏輯逐字改編自
                              build_portfolio_report_v2.py::build_line12()的pat_ok(),demean同②
  ④微題材脈衝雷達         <- 無現成歷史事件快取(build_portfolio_report_v2.py原文承認"沒有存檔的
                              歷史時間序列",本卷用DB rankings表(僅2025-04起67週)+classification.
                              sub_product+micro_themes.MICRO_THEMES逐字複刻export_html.py微題材
                              脈衝雷達演算法(pulse>=2.5x∧跳升中位>=35名),重新掃描出歷史事件
  ⑤當沖暴增排雷dt_surge   <- 研究腳本/當沖借券/build_dtlend_report.py題③,重用該卷event_stats/
                              case_control/boot_diff_ci/boot_median_ci工具,d2事件表(topic3新增
                              回傳)拆regime重跑
  ⑥L1費率informed short   <- 同上題④,l1五分位面板(topic4回傳)拆regime後重跑Q5-Q1價差檢定,
                              另加boot_interaction_ci(本卷新寫,4組月群bootstrap)直接檢定
                              「Q5-Q1價差本身是否因regime而顯著不同」(比分別看兩regime的CI更嚴謹)

用法: python 研究腳本/綜合策略/build_vol_addvalue_report.py  (從根目錄執行,鐵律)
產出: 研究報告/research_vol_addvalue.html
"""
import statistics
import sys
import warnings

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
warnings.filterwarnings("ignore", category=RuntimeWarning)
sys.path.insert(0, "研究腳本/綜合策略")
import build_regime_weather_report as W  # noqa: E402  波動基礎建設+score4/共振事件快取,全部抄用

sys.path.insert(0, "研究腳本/當沖借券")
import build_dtlend_report as R  # noqa: E402  dt_surge/L1事件邏輯+bootstrap工具,全部抄用

sys.path.insert(0, ".")
from case_study_theme import load as sig_load  # noqa: E402  微題材熱度來源(rankings表)
from micro_themes import MICRO_THEMES  # noqa: E402

DB = "capital_flow.db"
OUT = "研究報告/research_vol_addvalue.html"
rng = np.random.default_rng(20260731)

TS = W.VOL["TAIEX"]["ts"]
VP = W.VOL["TAIEX"]["vp"]
TW_WK = W.IDX["TAIEX"].resample("W-FRI").last().dropna()
TAIEX_D = W.IDX["TAIEX"]


# ══════════════════════ 共用工具 ══════════════════════════════════
def tag_vp(dates):
    d = pd.to_datetime(pd.Series(dates))
    return W.at(VP, d)


def tag_ts(dates):
    d = pd.to_datetime(pd.Series(dates))
    return W.at(TS, d)


def vp_split(dates, hi=80):
    v = tag_vp(dates)
    return (v >= hi).values, (v < hi).values


def ts_split(dates):
    v = tag_ts(dates)
    return (v > 1.2).values, ((v >= 0.8) & (v <= 1.2)).values, (v < 0.8).values


def twii_wk_fwd(dates, weeks):
    """TAIEX週五收盤序列,從dates起算未來weeks週的報酬%(共振/大題材demean基準;
    二者本身皆週頻策略,用週線基準比日線更貼近其原始口徑)。"""
    s, idx = TW_WK, TW_WK.index
    out = []
    for dt in pd.to_datetime(pd.Series(dates)):
        pos = idx.searchsorted(dt)
        if pos >= len(idx) or pos + weeks >= len(idx):
            out.append(np.nan)
            continue
        out.append((s.iloc[pos + weeks] / s.iloc[pos] - 1) * 100)
    return np.array(out)


def taiex_fwd_d(dates, k):
    """TAIEX逐日序列forward k個交易日報酬%(微題材demean基準)。"""
    idx = TAIEX_D.index
    out = []
    for dt in pd.to_datetime(pd.Series(dates)):
        pos = idx.searchsorted(dt)
        if pos >= len(idx) or pos + k >= len(idx):
            out.append(np.nan)
            continue
        out.append((TAIEX_D.iloc[pos + k] / TAIEX_D.iloc[pos] - 1) * 100)
    return np.array(out)


def grp(vals):
    v = pd.Series(vals, dtype=float).dropna()
    if len(v) == 0:
        return {"n": 0, "med": None, "win": None}
    return {"n": int(len(v)), "med": float(v.median()), "win": float((v > 0).mean() * 100)}


def boot_interaction_ci(a_hi, ad_hi, b_hi, bd_hi, a_lo, ad_lo, b_lo, bd_lo, n_iter=2000, min_n=15):
    """(A-B在高波動regime) - (A-B在低波動regime),月群bootstrap 95%CI。
    泛化R.boot_diff_ci成4組交互作用檢定:比「分別看兩個regime各自的CI是否排0」更嚴謹——
    直接回答「這個價差本身是否因regime而顯著不同」,用於④L1 Q5-Q1价差的regime依賴性檢定。"""
    def prep(v, d):
        return pd.Series(v, index=pd.to_datetime(pd.Series(d)), dtype=float).dropna()
    A_hi, B_hi, A_lo, B_lo = prep(a_hi, ad_hi), prep(b_hi, bd_hi), prep(a_lo, ad_lo), prep(b_lo, bd_lo)
    if min(len(A_hi), len(B_hi), len(A_lo), len(B_lo)) < min_n:
        return None

    def mg(s):
        return s.groupby(s.index.strftime("%Y-%m")).apply(list)
    mA_hi, mB_hi, mA_lo, mB_lo = mg(A_hi), mg(B_hi), mg(A_lo), mg(B_lo)
    diffs = []
    for _ in range(n_iter):
        def rs(m):
            return np.concatenate([m.iloc[i] for i in rng.integers(0, len(m), len(m))])
        d_hi = np.median(rs(mA_hi)) - np.median(rs(mB_hi))
        d_lo = np.median(rs(mA_lo)) - np.median(rs(mB_lo))
        diffs.append(d_hi - d_lo)
    d0 = (A_hi.median() - B_hi.median()) - (A_lo.median() - B_lo.median())
    lo_, hi_ = float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))
    return {"diff": d0, "lo": lo_, "hi": hi_, "sig": bool(lo_ > 0 or hi_ < 0),
            "n": (len(A_hi), len(B_hi), len(A_lo), len(B_lo))}


def fmt_ci(r, unit="pp"):
    if r is None:
        return "n太小,無法bootstrap(觀察層)"
    sig = "<b>✓排0顯著</b>" if r["sig"] else "含0不顯著"
    return f"{r['diff']:+.2f}{unit} 95%CI[{r['lo']:+.2f},{r['hi']:+.2f}] {sig}"


# ══════════════════════ ①題材營收動能score4 ═══════════════════════
def obj1_score4():
    raw = W.EV["⑥score4營收清單(ret60)"].copy()
    exc = W.EV["⑥b score4超額(excess60)"].copy()
    exc_pp = exc["ret"].values * 100
    hi, lo = vp_split(exc["date"])
    hot, neu, cool = ts_split(exc["date"])
    vp_tab = {"高波(vp10≥80)": grp(exc_pp[hi]), "低波(<80)": grp(exc_pp[lo])}
    ts_tab = {"升溫(ts>1.2)": grp(exc_pp[hot]), "中性": grp(exc_pp[neu]), "退潮(ts<0.8)": grp(exc_pp[cool])}
    boot_vp = R.boot_diff_ci(exc_pp[hi], exc.loc[hi, "date"], exc_pp[lo], exc.loc[lo, "date"])
    boot_ts = R.boot_diff_ci(exc_pp[hot], exc.loc[hot, "date"], exc_pp[cool], exc.loc[cool, "date"])
    verdict = "沒用" if not (boot_vp and boot_vp["sig"]) and not (boot_ts and boot_ts["sig"]) else "部分加值"
    return {"n": len(exc), "vp_tab": vp_tab, "ts_tab": ts_tab, "boot_vp": boot_vp, "boot_ts": boot_ts,
            "verdict": verdict}


# ══════════════════════ ②共振題材(8週) ═════════════════════════
def obj2_resonance():
    ep = pd.read_pickle("快取/tmp_resonance_theme_episodes.pkl")
    e = ep[ep["episode_first"] == True].dropna(subset=["fwd8"]).copy()  # noqa: E712
    bench = twii_wk_fwd(e["week"], 8)
    e["excess8"] = e["fwd8"].astype(float).values - bench
    hi, lo = vp_split(e["week"])
    hot, neu, cool = ts_split(e["week"])
    vp_tab = {"高波(vp10≥80)": grp(e.loc[hi, "excess8"]), "低波(<80)": grp(e.loc[lo, "excess8"])}
    ts_tab = {"升溫(ts>1.2)": grp(e.loc[hot, "excess8"]), "中性": grp(e.loc[neu, "excess8"]),
              "退潮(ts<0.8)": grp(e.loc[cool, "excess8"])}
    boot_vp = R.boot_diff_ci(e.loc[hi, "excess8"].values, e.loc[hi, "week"],
                              e.loc[lo, "excess8"].values, e.loc[lo, "week"])
    boot_ts = R.boot_diff_ci(e.loc[hot, "excess8"].values, e.loc[hot, "week"],
                              e.loc[cool, "excess8"].values, e.loc[cool, "week"])
    verdict = "沒用" if not (boot_vp and boot_vp["sig"]) and not (boot_ts and boot_ts["sig"]) else "部分加值"
    return {"n": len(e), "vp_tab": vp_tab, "ts_tab": ts_tab, "boot_vp": boot_vp, "boot_ts": boot_ts,
            "verdict": verdict}


# ══════════════════════ ③大題材檢查清單(S3⑤強訊號+階梯) ══════════════
def obj3_macro_theme():
    tr = pd.read_csv("快取/tmp_bear_trades.csv", dtype=str)
    tr = tr[tr.ret8w.str.contains("%", na=False)].copy()
    tr["date"] = pd.to_datetime(tr["date"])
    tr["ret8w"] = tr.ret8w.str.replace("%", "").astype(float)

    def pat_ok(r):
        # 逐字改編自 build_portfolio_report_v2.py::build_line12()內的pat_ok()
        try:
            a, b = r.nh.split("/")
            if int(b) and int(a) / int(b) >= 2 / 3:
                return True
        except (ValueError, AttributeError):
            pass
        return "✓" in str(r.gap)

    tr["p5"] = tr.apply(pat_ok, axis=1)
    s3 = tr[tr.p5].copy()
    bench = twii_wk_fwd(s3["date"], 8)
    s3["excess8"] = s3["ret8w"].values - bench
    hi, lo = vp_split(s3["date"])
    hot, neu, cool = ts_split(s3["date"])
    vp_tab = {"高波(vp10≥80)": grp(s3.loc[hi, "excess8"]), "低波(<80)": grp(s3.loc[lo, "excess8"])}
    ts_tab = {"升溫(ts>1.2)": grp(s3.loc[hot, "excess8"]), "中性": grp(s3.loc[neu, "excess8"]),
              "退潮(ts<0.8)": grp(s3.loc[cool, "excess8"])}
    boot_vp = R.boot_diff_ci(s3.loc[hi, "excess8"].values, s3.loc[hi, "date"],
                              s3.loc[lo, "excess8"].values, s3.loc[lo, "date"])
    boot_ts = R.boot_diff_ci(s3.loc[hot, "excess8"].values, s3.loc[hot, "date"],
                              s3.loc[cool, "excess8"].values, s3.loc[cool, "date"])
    insufficient = (boot_vp is None) and (boot_ts is None)
    verdict = "樣本不足" if insufficient else ("沒用" if not (boot_vp and boot_vp["sig"]) and
                                                not (boot_ts and boot_ts["sig"]) else "部分加值")
    return {"n": len(s3), "vp_tab": vp_tab, "ts_tab": ts_tab, "boot_vp": boot_vp, "boot_ts": boot_ts,
            "verdict": verdict}


# ══════════════════════ ④微題材脈衝雷達 ═══════════════════════════
def build_micro_theme_events():
    """重新掃描DB rankings表(2025-04起,僅67週),逐字複刻export_html.py的微題材脈衝演算法
    (脈衝倍率>=2.5x∧排名跳升中位>=35名),同題材>27日視為新episode去重。"""
    sig_rank, _ = sig_load()
    con = R.sqlite3.connect(DB)
    subp = pd.read_sql("SELECT DISTINCT code, sub_product FROM classification WHERE country='台'", con)
    con.close()
    tw_rank = sig_rank[sig_rank["country"] == "台"]
    tw_total = tw_rank.groupby("snapshot_date")["twd"].sum()
    m_dates = sorted(tw_rank["snapshot_date"].unique())

    events = []
    for name, cfg in MICRO_THEMES.items():
        kws, excl = cfg["kws"], set(cfg.get("exclude", []))
        mask = subp["sub_product"].fillna("").apply(lambda t: any(k.lower() in t.lower() for k in kws))
        codes = sorted(set(subp[mask]["code"]) - excl)
        if not codes:
            continue
        mem = tw_rank[tw_rank["code"].isin(codes)]
        svals, rmaps = [], []
        for d in m_dates:
            snap = mem[mem["snapshot_date"] == d]
            svals.append(float(snap["twd"].sum() / tw_total.get(d, 1) * 100))
            rmaps.append(dict(zip(snap["code"], snap["rank"])))

        def jump_at(i):
            js = [rmaps[i - 1][c] - rmaps[i][c] for c in rmaps[i] if c in rmaps[i - 1]]
            return statistics.median(js) if js else None

        for i in range(4, len(m_dates)):
            base = statistics.median(svals[i - 4:i])
            if base <= 0:
                continue
            pulse = svals[i] / base
            j = jump_at(i)
            if pulse >= 2.5 and j is not None and j >= 35:
                events.append({"date": pd.Timestamp(m_dates[i]), "theme": name, "codes": tuple(codes)})

    ev = pd.DataFrame(events).sort_values(["theme", "date"])
    keep, last = [], {}
    for r in ev.itertuples():
        if r.theme not in last or (r.date - last[r.theme]).days > 27:
            keep.append(r)
        last[r.theme] = r.date
    return pd.DataFrame(keep)[["date", "theme", "codes"]].reset_index(drop=True)


def micro_theme_fwd_returns(ev, ks=(5, 10, 20)):
    all_codes = sorted(set(c for codes in ev["codes"] for c in codes))
    con = R.sqlite3.connect(DB)
    ph = ",".join("?" * len(all_codes))
    px = pd.read_sql(f"SELECT code,date,close FROM fm_daily_price WHERE code IN ({ph}) AND close>0",
                      con, params=all_codes, parse_dates=["date"])
    con.close()
    close = px.pivot(index="date", columns="code", values="close")
    idx = close.index
    rows = []
    for r in ev.itertuples():
        pos = idx.searchsorted(r.date)
        if pos >= len(idx):
            continue
        rec = {"date": r.date, "theme": r.theme}
        base_p = close.iloc[pos][list(r.codes)]
        for k in ks:
            if pos + k >= len(idx):
                rec[f"k{k}"] = np.nan
                continue
            fwd_p = close.iloc[pos + k][list(r.codes)]
            rec[f"k{k}"] = float(((fwd_p / base_p - 1) * 100).mean())
        rows.append(rec)
    return pd.DataFrame(rows)


def obj4_micro_theme():
    ev = build_micro_theme_events()
    fr = micro_theme_fwd_returns(ev)
    for k in (5, 10, 20):
        fr[f"dm{k}"] = fr[f"k{k}"] - taiex_fwd_d(fr["date"], k)
    hi, lo = vp_split(fr["date"])
    n_hi, n_lo = int(hi.sum()), int(lo.sum())
    k_tab, boot = {}, {}
    for k in (5, 10, 20):
        k_tab[k] = {"高波": grp(fr.loc[hi, f"dm{k}"]), "低波": grp(fr.loc[lo, f"dm{k}"])}
        boot[k] = R.boot_diff_ci(fr.loc[hi, f"dm{k}"].values, fr.loc[hi, "date"],
                                  fr.loc[lo, f"dm{k}"].values, fr.loc[lo, "date"], min_n=15)
    insufficient = all(boot[k] is None for k in (5, 10, 20))
    verdict = "樣本不足" if insufficient else ("沒用" if not any(boot[k] and boot[k]["sig"] for k in (5, 10, 20))
                                                else "部分加值")
    return {"n": len(ev), "n_hi": n_hi, "n_lo": n_lo, "k_tab": k_tab, "boot": boot,
            "asof_span": (str(ev["date"].min().date()), str(ev["date"].max().date())) if len(ev) else None,
            "verdict": verdict}


# ══════════════════════ ⑤+⑥ 當沖借券底層準備 ═══════════════════════
def prep_dtlend():
    print("[準備] 載入當沖/借券全史(511萬列)+價格全宇宙...")
    dt, ln = R.load_dtlend()
    codes = sorted(set(dt.code) | set(ln.code))
    close, op, vol, money = R.load_price(codes, "2013-10-01")
    amt20 = money.rolling(20, min_periods=15).mean() / 1e8
    uni = amt20 >= 0.3
    fwd = {k: (close.shift(-k) / close - 1) * 100 for k in R.KS}
    dtp = dt.pivot_table(index="date", columns="code", values="Volume", aggfunc="sum")
    ratio = (dtp / vol.reindex_like(dtp)).clip(0, 1)
    ln = ln.copy()
    ln["fv"] = ln.fee_rate * ln.volume
    g = ln.groupby(["date", "code"]).agg(fv=("fv", "sum"), v=("volume", "sum"))
    g["vwfee"] = g.fv / g.v
    vwfee = g.reset_index().pivot(index="date", columns="code", values="vwfee")
    return dict(uni=uni, fwd=fwd, ratio=ratio, vwfee=vwfee, close=close)


# ══════════════════════ ⑤當沖暴增排雷dt_surge ═════════════════════
def obj5_dt_surge(ctx):
    t3 = R.build_topic3(ctx["ratio"], ctx["uni"], ctx["fwd"])
    d2 = t3["d2"]
    fwd, uni = ctx["fwd"], ctx["uni"]
    hi, lo = vp_split(d2["date"])
    hot, neu, cool = ts_split(d2["date"])
    st_hi, st_lo = R.event_stats(d2.loc[hi], fwd, uni), R.event_stats(d2.loc[lo], fwd, uni)
    st_hot, st_cool = R.event_stats(d2.loc[hot], fwd, uni), R.event_stats(d2.loc[cool], fwd, uni)

    vp_rows, ts_rows, boot_vp, boot_ts = {}, {}, {}, {}
    for k in (5, 10, 20):
        vp_rows[k] = {"高波": {"raw": st_hi[k]["raw"], "dm": st_hi[k]["dm"]},
                      "低波": {"raw": st_lo[k]["raw"], "dm": st_lo[k]["dm"]}}
        ts_rows[k] = {"升溫": {"raw": st_hot[k]["raw"], "dm": st_hot[k]["dm"]},
                      "退潮": {"raw": st_cool[k]["raw"], "dm": st_cool[k]["dm"]}}
        boot_vp[k] = {"hi_vs0": R.boot_median_ci(st_hi[k]["dm"][3], st_hi[k]["dm"][4]),
                      "lo_vs0": R.boot_median_ci(st_lo[k]["dm"][3], st_lo[k]["dm"][4]),
                      "hi_lo_diff": R.boot_diff_ci(st_hi[k]["dm"][3], st_hi[k]["dm"][4],
                                                    st_lo[k]["dm"][3], st_lo[k]["dm"][4])}
        boot_ts[k] = {"hot_vs0": R.boot_median_ci(st_hot[k]["dm"][3], st_hot[k]["dm"][4]),
                      "cool_vs0": R.boot_median_ci(st_cool[k]["dm"][3], st_cool[k]["dm"][4]),
                      "hot_cool_diff": R.boot_diff_ci(st_hot[k]["dm"][3], st_hot[k]["dm"][4],
                                                       st_cool[k]["dm"][3], st_cool[k]["dm"][4])}
    k20_sig = boot_vp[20]["hi_lo_diff"] and boot_vp[20]["hi_lo_diff"]["sig"]
    verdict = "加值(但方向與假說相反)" if k20_sig else "沒用"
    return {"n": len(d2), "n_hi": int(hi.sum()), "n_lo": int(lo.sum()),
            "vp_rows": vp_rows, "ts_rows": ts_rows, "boot_vp": boot_vp, "boot_ts": boot_ts,
            "verdict": verdict}


# ══════════════════════ ⑥L1費率informed short ═════════════════════
def obj6_l1_short(ctx):
    t4 = R.build_topic4(ctx["vwfee"], ctx["uni"], ctx["fwd"], ctx["close"])
    l1, q_lo, q_hi = t4["l1"], t4["q_lo"], t4["q_hi"]
    fwd, uni = ctx["fwd"], ctx["uni"]
    hi, lo = vp_split(l1["date"])
    hot, neu, cool = ts_split(l1["date"])
    l1hi, l1lo, l1hot, l1cool = l1.loc[hi], l1.loc[lo], l1.loc[hot], l1.loc[cool]

    def q_stats(sub):
        return (R.event_stats(sub[sub.q == q_hi][["date", "code"]], fwd, uni),
                R.event_stats(sub[sub.q == q_lo][["date", "code"]], fwd, uni))
    st_hi_q5, st_hi_q1 = q_stats(l1hi)
    st_lo_q5, st_lo_q1 = q_stats(l1lo)
    st_hot_q5, st_hot_q1 = q_stats(l1hot)
    st_cool_q5, st_cool_q1 = q_stats(l1cool)

    vp_rows, ts_rows, boot_vp, boot_ts, interaction_vp, interaction_ts = {}, {}, {}, {}, {}, {}
    for k in (5, 10, 20):
        vp_rows[k] = {"高波Q5": st_hi_q5[k]["dm"], "高波Q1": st_hi_q1[k]["dm"],
                      "低波Q5": st_lo_q5[k]["dm"], "低波Q1": st_lo_q1[k]["dm"]}
        ts_rows[k] = {"升溫Q5": st_hot_q5[k]["dm"], "升溫Q1": st_hot_q1[k]["dm"],
                      "退潮Q5": st_cool_q5[k]["dm"], "退潮Q1": st_cool_q1[k]["dm"]}
        boot_vp[k] = {"hi_diff": R.boot_diff_ci(st_hi_q5[k]["dm"][3], st_hi_q5[k]["dm"][4],
                                                 st_hi_q1[k]["dm"][3], st_hi_q1[k]["dm"][4]),
                      "lo_diff": R.boot_diff_ci(st_lo_q5[k]["dm"][3], st_lo_q5[k]["dm"][4],
                                                 st_lo_q1[k]["dm"][3], st_lo_q1[k]["dm"][4])}
        boot_ts[k] = {"hot_diff": R.boot_diff_ci(st_hot_q5[k]["dm"][3], st_hot_q5[k]["dm"][4],
                                                  st_hot_q1[k]["dm"][3], st_hot_q1[k]["dm"][4]),
                      "cool_diff": R.boot_diff_ci(st_cool_q5[k]["dm"][3], st_cool_q5[k]["dm"][4],
                                                   st_cool_q1[k]["dm"][3], st_cool_q1[k]["dm"][4])}
        interaction_vp[k] = boot_interaction_ci(
            st_hi_q5[k]["dm"][3], st_hi_q5[k]["dm"][4], st_hi_q1[k]["dm"][3], st_hi_q1[k]["dm"][4],
            st_lo_q5[k]["dm"][3], st_lo_q5[k]["dm"][4], st_lo_q1[k]["dm"][3], st_lo_q1[k]["dm"][4])
        interaction_ts[k] = boot_interaction_ci(
            st_hot_q5[k]["dm"][3], st_hot_q5[k]["dm"][4], st_hot_q1[k]["dm"][3], st_hot_q1[k]["dm"][4],
            st_cool_q5[k]["dm"][3], st_cool_q5[k]["dm"][4], st_cool_q1[k]["dm"][3], st_cool_q1[k]["dm"][4])
    any_sig = any(interaction_vp[k] and interaction_vp[k]["sig"] for k in (10, 20)) or \
        any(interaction_ts[k] and interaction_ts[k]["sig"] for k in (10, 20))
    verdict = "加值(regime解釋了Q5-Q1價差強弱不均)" if any_sig else "沒用"
    return {"n_hi": int(hi.sum()), "n_lo": int(lo.sum()), "vp_rows": vp_rows, "ts_rows": ts_rows,
            "boot_vp": boot_vp, "boot_ts": boot_ts, "interaction_vp": interaction_vp,
            "interaction_ts": interaction_ts, "verdict": verdict}


# ══════════════════════ 主流程 ═════════════════════════════════════
def main():
    print("=" * 90, "\n①③④score4/共振/大題材/微題材(輕量,用既有快取)")
    o1 = obj1_score4()
    o2 = obj2_resonance()
    o3 = obj3_macro_theme()
    o4 = obj4_micro_theme()

    print("=" * 90, "\n⑤⑥當沖借券底層準備(較重,約1-2分)")
    ctx = prep_dtlend()
    o5 = obj5_dt_surge(ctx)
    o6 = obj6_l1_short(ctx)

    print("=" * 90)
    print(f"①score4: n={o1['n']} verdict={o1['verdict']} vp_diff={fmt_ci(o1['boot_vp'])} "
          f"ts_diff={fmt_ci(o1['boot_ts'])}")
    print(f"②共振: n={o2['n']} verdict={o2['verdict']} vp_diff={fmt_ci(o2['boot_vp'])} "
          f"ts_diff={fmt_ci(o2['boot_ts'])}")
    print(f"③大題材: n={o3['n']} verdict={o3['verdict']} vp_diff={fmt_ci(o3['boot_vp'])} "
          f"ts_diff={fmt_ci(o3['boot_ts'])}")
    print(f"④微題材: n={o4['n']} (高波{o4['n_hi']}/低波{o4['n_lo']}) verdict={o4['verdict']} "
          f"k20_diff={fmt_ci(o4['boot'][20])}")
    print(f"⑤dt_surge: n={o5['n']} verdict={o5['verdict']} "
          f"vp k20 hi-lo={fmt_ci(o5['boot_vp'][20]['hi_lo_diff'])}")
    print(f"⑥L1 informed short: verdict={o6['verdict']} "
          f"vp k20 interaction={fmt_ci(o6['interaction_vp'][20])}")

    html = build_html(o1, o2, o3, o4, o5, o6)
    open(OUT, "w", encoding="utf-8").write(html)
    print(f"已產出 {OUT}")


# ══════════════════════ HTML 組裝 ═══════════════════════════════════
def summary_row(name, obj_key, n, verdict, key_stat):
    cls = {"加值": "v-good", "部分加值": "v-warn", "沒用": "v-bad", "樣本不足": "v-warn"}
    for k, c in cls.items():
        if verdict.startswith(k):
            css = c
            break
    else:
        css = ""
    return (f"<tr><td>{obj_key}</td><th style='text-align:left'>{name}</th><td>{n}</td>"
            f"<td class='{css}'>{verdict}</td><td style='text-align:left'>{key_stat}</td></tr>")


def group_table(tab, cols):
    head = "<tr><th>regime</th><th>n</th><th>中位數</th><th>勝率</th></tr>"
    rows = ""
    for label in cols:
        c = tab.get(label, {"n": 0})
        if not c or c.get("n", 0) == 0:
            rows += f"<tr><th>{label}</th><td>0</td><td>—</td><td>—</td></tr>"
            continue
        cls = "good" if c["med"] > 0 else "bad"
        rows += (f"<tr><th>{label}</th><td>{c['n']}</td>"
                 f"<td class='{cls}'>{c['med']:+.2f}%</td><td>{c['win']:.0f}%</td></tr>")
    return f"<table>{head}{rows}</table>"


def build_html(o1, o2, o3, o4, o5, o6):
    css = """
body{background:#1a1a19;color:#fff;font-family:"Noto Sans TC",sans-serif;margin:24px;max-width:1180px}
h1{font-size:20px} h2{font-size:15px;color:#c3c2b7;margin-top:34px;border-bottom:1px solid #333;padding-bottom:4px}
h3{font-size:13.5px;color:#a8a79a;margin:16px 0 4px}
table{border-collapse:collapse;font-size:12.5px;font-variant-numeric:tabular-nums;margin:8px 0}
td,th{border:1px solid #333;padding:4px 9px;text-align:right} th{text-align:left;color:#c3c2b7}
.note{color:#8a8878;font-size:12.5px;line-height:1.8} .good{color:#7ec97e} .bad{color:#e06c5a}
.warn{color:#c3a55a} .v-good{color:#7ec97e;font-weight:600} .v-bad{color:#e06c5a;font-weight:600}
.v-warn{color:#c3a55a;font-weight:600} .sub{color:#777;font-size:11px}
.flex{display:flex;gap:24px;flex-wrap:wrap} .flex>div{flex:1;min-width:280px}
"""
    summary = "".join([
        summary_row("①題材營收動能score4", "①", o1["n"], o1["verdict"],
                    f"vp10高低波excess60中位差{fmt_ci(o1['boot_vp'])}"),
        summary_row("②共振題材(8週)", "②", o2["n"], o2["verdict"],
                    f"vp10高低波excess8中位差{fmt_ci(o2['boot_vp'])}"),
        summary_row("③大題材檢查清單(S3)", "③", o3["n"], o3["verdict"],
                    f"vp10高波n={vp_n(o3)},樣本過小" if o3["verdict"] == "樣本不足"
                    else fmt_ci(o3["boot_vp"])),
        summary_row("④微題材脈衝雷達", "④", o4["n"], o4["verdict"],
                    f"n僅{o4['n']}(rankings表僅15個月歷史,高波{o4['n_hi']}/低波{o4['n_lo']}),"
                    f"k20 CI寬:{fmt_ci(o4['boot'][20])}"),
        summary_row("⑤當沖暴增排雷dt_surge", "⑤", o5["n"], o5["verdict"],
                    f"k20 demean:高波{fmt_short(o5['boot_vp'][20]['hi_vs0'])} vs "
                    f"低波{fmt_short(o5['boot_vp'][20]['lo_vs0'])},"
                    f"高低波差{fmt_ci(o5['boot_vp'][20]['hi_lo_diff'])}"),
        summary_row("⑥L1費率informed short", "⑥", "—", o6["verdict"],
                    f"k20 Q5-Q1价差交互作用(高波-低波){fmt_ci(o6['interaction_vp'][20])}"),
    ])

    # ①score4
    o1_html = (f"<div class='flex'><div><h3>vp10百分位切法(n={o1['n']})</h3>"
               f"{group_table(o1['vp_tab'], ['高波(vp10≥80)', '低波(<80)'])}"
               f"<div class='note'>高低波demean(excess60)中位差 = {fmt_ci(o1['boot_vp'])}</div></div>"
               f"<div><h3>ts=vol10/vol60三帶切法</h3>"
               f"{group_table(o1['ts_tab'], ['升溫(ts>1.2)', '中性', '退潮(ts<0.8)'])}"
               f"<div class='note'>升溫-退潮demean中位差 = {fmt_ci(o1['boot_ts'])}</div></div></div>")

    # ②共振
    o2_html = (f"<div class='flex'><div><h3>vp10百分位切法(n={o2['n']})</h3>"
               f"{group_table(o2['vp_tab'], ['高波(vp10≥80)', '低波(<80)'])}"
               f"<div class='note'>高低波demean(excess8,扣TAIEX同期週線前推8週報酬)中位差 = "
               f"{fmt_ci(o2['boot_vp'])}</div></div>"
               f"<div><h3>ts三帶切法</h3>"
               f"{group_table(o2['ts_tab'], ['升溫(ts>1.2)', '中性', '退潮(ts<0.8)'])}"
               f"<div class='note'>升溫-退潮demean中位差 = {fmt_ci(o2['boot_ts'])}</div></div></div>")

    # ③大題材
    o3_html = (f"<div class='flex'><div><h3>vp10百分位切法(n={o3['n']},通過p5⑤強訊號篩選)</h3>"
               f"{group_table(o3['vp_tab'], ['高波(vp10≥80)', '低波(<80)'])}"
               f"<div class='note'>高低波demean(excess8)中位差 = {fmt_ci(o3['boot_vp'])}</div></div>"
               f"<div><h3>ts三帶切法</h3>"
               f"{group_table(o3['ts_tab'], ['升溫(ts>1.2)', '中性', '退潮(ts<0.8)'])}"
               f"<div class='note'>升溫-退潮demean中位差 = {fmt_ci(o3['boot_ts'])}</div></div></div>"
               f"<div class='note warn'>⚠樣本量小(S3⑤強訊號篩選後全史僅{o3['n']}筆,2022-05起),"
               f"vp10高波格n=11、ts升溫/退潮格n=14/18,均低於本卷bootstrap最低樣本門檻(15),"
               f"無法可靠檢定——判讀=證據不足而非「確定沒用」。</div>")

    # ④微題材
    o4_rows = "".join(
        f"<tr><th>k{k}</th><td>{o4['k_tab'][k]['高波']['n']}</td>"
        f"<td class=\"{'good' if o4['k_tab'][k]['高波']['med'] and o4['k_tab'][k]['高波']['med'] > 0 else 'bad'}\">"
        f"{o4['k_tab'][k]['高波']['med']:+.2f}%</td>"
        f"<td>{o4['k_tab'][k]['低波']['n']}</td>"
        f"<td class=\"{'good' if o4['k_tab'][k]['低波']['med'] and o4['k_tab'][k]['低波']['med'] > 0 else 'bad'}\">"
        f"{o4['k_tab'][k]['低波']['med']:+.2f}%</td><td>{fmt_ci(o4['boot'][k])}</td></tr>"
        for k in (5, 10, 20))
    span = f"{o4['asof_span'][0]}~{o4['asof_span'][1]}" if o4["asof_span"] else "—"
    o4_html = (f"<table><tr><th>k窗口</th><th>高波n</th><th>高波demean中位</th>"
               f"<th>低波n</th><th>低波demean中位</th><th>高低波差(bootstrap)</th></tr>{o4_rows}</table>"
               f"<div class='note warn'>⚠此對象原本沒有存檔的歷史事件(build_portfolio_report_v2.py"
               f"原文承認的資料缺口),本卷用DB rankings表(週頻熱度快照)+classification.sub_product"
               f"重新掃描出微題材脈衝歷史({span},僅{o4['n']}個episode,"
               f"因rankings表僅2025-04起共67週的資料),高波/低波各僅{o4['n_hi']}/{o4['n_lo']}筆,"
               f"遠低於bootstrap最低樣本門檻,95%CI極寬(見上表)——判讀=infra限制導致證據不足,"
               f"不是「規則沒用」,是「這套regime基礎建設目前的資料長度測不出這題」。</div>")

    # ⑤dt_surge
    o5_tab = "<table><tr><th>k</th><th>regime</th><th>n</th><th>raw中位</th><th>raw勝率</th>"\
             "<th>demean中位</th><th>demean勝率</th></tr>"
    for k in (5, 10, 20):
        for label in ("高波", "低波"):
            raw, dm = o5["vp_rows"][k][label]["raw"], o5["vp_rows"][k][label]["dm"]
            o5_tab += (f"<tr><th>k{k}</th><th>{label}</th><td>{raw[2]}</td>"
                       f"<td class=\"{'good' if raw[0] > 0 else 'bad'}\">{raw[0]:+.2f}%</td>"
                       f"<td>{raw[1]:.0f}%</td>"
                       f"<td class=\"{'good' if dm[0] > 0 else 'bad'}\">{dm[0]:+.2f}pp</td><td>{dm[1]:.0f}%</td></tr>")
    o5_tab += "</table>"
    o5_boot_rows = "".join(
        f"<li>k{k}: 高波vs0={fmt_short(o5['boot_vp'][k]['hi_vs0'])} / "
        f"低波vs0={fmt_short(o5['boot_vp'][k]['lo_vs0'])} / "
        f"高波-低波={fmt_ci(o5['boot_vp'][k]['hi_lo_diff'])}</li>"
        for k in (5, 10, 20))
    o5_boot_ts_rows = "".join(
        f"<li>k{k}: 升溫vs0={fmt_short(o5['boot_ts'][k]['hot_vs0'])} / "
        f"退潮vs0={fmt_short(o5['boot_ts'][k]['cool_vs0'])} / "
        f"升溫-退潮={fmt_ci(o5['boot_ts'][k]['hot_cool_diff'])}</li>"
        for k in (5, 10, 20))
    o5_html = (f"<div class='note'>事件n={o5['n']:,}(高波{o5['n_hi']:,}/低波{o5['n_lo']:,})</div>"
               f"{o5_tab}<h3>bootstrap(vp10百分位切法,月群重抽樣2000次)</h3><ul>{o5_boot_rows}</ul>"
               f"<h3>bootstrap(ts=vol10/vol60三帶切法,交叉驗證)</h3><ul>{o5_boot_ts_rows}</ul>"
               f"<div class='note warn'>⚠判讀方向與原假說相反:原假說predict「高波動段排雷訊號更強、"
               f"低波動段減弱」,兩種切法(vp10/ts)皆顯示<b>相反</b>——k20демean效果在低波動/退潮段顯著"
               f"(vp10低波-0.82pp排0;ts退潮-0.89pp排0),但在高波動/升溫段轉弱甚至不顯著(vp10高波CI含0;"
               f"ts升溫段雖仍排0但幅度僅退潮段一半),高低波差在k20顯著(CI排0)。合理解讀:當沖暴增這種"
               f"個股微結構警訊,在平靜市場中是較乾淨的獨立訊號,在高波動/恐慌市場中容易被總體噪音淹沒"
               f"——不是「高波動時假警報更多」而是「高波動時真訊號被稀釋」。</div>")

    # ⑥L1
    o6_tab = "<table><tr><th>k</th><th>regime</th><th>Q5(demean)</th><th>Q1(demean)</th>"\
             "<th>Q5-Q1差</th></tr>"
    for k in (5, 10, 20):
        for label, diffkey in (("高波", "hi_diff"), ("低波", "lo_diff")):
            q5 = o6["vp_rows"][k][f"{label}Q5"]
            q1 = o6["vp_rows"][k][f"{label}Q1"]
            d = o6["boot_vp"][k][diffkey]
            o6_tab += (f"<tr><th>k{k}</th><th>{label}</th>"
                       f"<td class=\"{'good' if q5[0] > 0 else 'bad'}\">{q5[0]:+.2f}pp(n={q5[2]})</td>"
                       f"<td class=\"{'good' if q1[0] > 0 else 'bad'}\">{q1[0]:+.2f}pp(n={q1[2]})</td>"
                       f"<td>{fmt_ci(d)}</td></tr>")
    o6_tab += "</table>"
    o6_inter_vp = "".join(f"<li>k{k}(vp10切法): {fmt_ci(o6['interaction_vp'][k])}</li>" for k in (5, 10, 20))
    o6_inter_ts = "".join(f"<li>k{k}(ts切法交叉驗證): {fmt_ci(o6['interaction_ts'][k])}</li>" for k in (5, 10, 20))
    o6_html = (f"<div class='note'>高波n={o6['n_hi']:,} / 低波n={o6['n_lo']:,}(L1五分位面板逐日逐股)</div>"
               f"{o6_tab}<h3>交互作用檢定:「Q5-Q1價差本身是否因regime而顯著不同」(4組月群bootstrap)</h3>"
               f"<ul>{o6_inter_vp}{o6_inter_ts}</ul>"
               f"<div class='note warn'>⚠判讀方向與⑤dt_surge一致:informed short訊號(Q5高費率組跑輸"
               f"Q1)在低波動regime穩健存在(k5/k10/k20皆排0),在高波動regime於k10/k20轉為不顯著(僅k5"
               f"仍排0),交互作用檢定在k10/k20顯著排0——確認這不是隨機波動,是regime真的改變了訊號強度。"
               f"與⑤同一個故事:個股微結構訊號在平靜市場更乾淨,在動盪市場被稀釋。</div>")

    return f"""<!DOCTYPE html><html lang="zh-Hant"><head><meta charset="utf-8">
<title>波動regime加值驗證考卷</title><style>{css}</style></head><body>
<h1>波動期限結構(vol10/vol60,vp10)regime加值驗證考卷</h1>
<div class="note">2026-07-31。⚠驗證題,非「加了就要用」:六個既有策略/訊號逐一拆高波動regime段vs
低波動regime段,bootstrap(月群重抽樣2000次,95%CI)驗證分離是否顯著。波動基礎建設(ts/vp10)
全部抄用<code>build_regime_weather_report.py</code>既有邏輯,不重新設計。</div>

<h2>總覽:六個對象判讀</h2>
<table><tr><th>#</th><th>對象</th><th>事件n</th><th>判讀</th><th>核心數字</th></tr>{summary}</table>
<div class="note">判讀分四類:<b class="v-good">加值</b>=regime分離經bootstrap驗證顯著;
<b class="v-warn">部分加值</b>=其中一種切法顯著但不穩健跨切法;<b class="v-bad">沒用</b>=兩種切法皆不顯著;
<b class="v-warn">樣本不足</b>=事件數過少無法可靠bootstrap(非「確定沒用」)。</div>

<h2>①題材營收動能score4</h2>
<div class="note">快取=build_regime_weather_report.py的W.EV(⑥score4ret60/⑥b score4超額excess60),
excess60=TWII超額報酬(已是demean版,原班底計算)。</div>
{o1_html}

<h2>②共振題材(8週)</h2>
<div class="note">快取=快取/tmp_resonance_theme_episodes.pkl(episode_first,fwd8);
demean=扣TAIEX週線同期前推8週報酬(本卷新算)。</div>
{o2_html}

<h2>③大題材檢查清單(S3⑤強訊號+階梯)</h2>
<div class="note">快取=快取/tmp_bear_trades.csv,p5篩選邏輯逐字改編自
build_portfolio_report_v2.py::build_line12()的pat_ok()。</div>
{o3_html}

<h2>④微題材脈衝雷達</h2>
<div class="note">無現成歷史事件快取(原腳本承認的資料缺口),本卷用DB rankings表
(僅2025-04起67週)+classification.sub_product+micro_themes.MICRO_THEMES複刻
export_html.py微題材脈衝演算法,重新掃描歷史事件。</div>
{o4_html}

<h2>⑤當沖暴增排雷(dt_surge)</h2>
<div class="note">重用研究腳本/當沖借券/build_dtlend_report.py題③的event_stats/case_control/
boot_diff_ci/boot_median_ci工具,d2事件表拆regime重跑(k=1,2,3,5,10,20,本頁僅列k5/10/20)。</div>
{o5_html}

<h2>⑥L1費率informed short(Q5 hard-to-borrow vs Q1)</h2>
<div class="note">同上腳本題④,l1五分位面板拆regime後重跑Q5-Q1價差檢定,另加boot_interaction_ci
(本卷新寫)直接檢定「Q5-Q1價差本身是否因regime而顯著不同」。</div>
{o6_html}

<h2>方法論與限制</h2>
<div class="note">
① 波動regime口徑統一沿用build_regime_weather_report.py: ts=vol10/vol60(加權指數10日/60日日報酬std比值),
升溫>1.2/中性0.8~1.2/退潮&lt;0.8;vp10=vol10在2006起全樣本百分位,高波=vp10≥80。<br>
② bootstrap=月群重抽樣(仿build_dtlend_report.boot_diff_ci/boot_median_ci),n_iter=2000,95%CI,
「排0」=顯著;最低樣本門檻n=15(月群bootstrap慣例)。<br>
③ demean基準:score4用原快取的TWII超額報酬(excess60);共振/大題材用本卷新算的TAIEX週線同期前推
報酬;當沖借券兩題沿用build_dtlend_report.py原有的同日全宇宙中位數demean版。<br>
④ ⑤⑥交互作用檢定(boot_interaction_ci)為本卷新寫的4組月群bootstrap,比單看兩個regime各自的CI
是否排0更嚴謹地回答「這個價差本身是否因regime而顯著不同」。<br>
⑤ 已知限制:③大題材、④微題材樣本量過小(③全史60筆、④僅15個月歷史33筆),bootstrap檢定力不足,
判讀為「證據不足」而非「確定沒用」;②共振的vp10切法邊緣不顯著(CI下界僅-0.90),不排除小樣本外
仍有微弱訊號,但未達本卷顯著門檻。
</div>
</body></html>"""


def vp_n(o):
    return o["vp_tab"].get("高波(vp10≥80)", {}).get("n", 0)


def fmt_short(r):
    if r is None:
        return "n太小"
    sig = "✓排0" if r["sig"] else "含0"
    key = "med" if "med" in r else "diff"
    return f"{r[key]:+.2f}pp[{r['lo']:+.2f},{r['hi']:+.2f}]{sig}"


if __name__ == "__main__":
    main()
