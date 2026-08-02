# -*- coding: utf-8 -*-
"""底部確認訊號組合×加權指數擇時回測(2026-08-01,使用者:「把這次驗證過的幾個底部訊號組合起來,
拿加權指數做回測,看能不能提早準備接近底部/避開真正的崩跌延續」)。

背景: 本場對話驗證過四個訊號,本卷把它們組成一套「底部確認」進場規則,回測標的=加權指數(TAIEX):
  ①00631L(元大台灣50正2)融資使用率(margin_flow.fin_use)相對自身252日滾動百分位——
    百分位異常偏高=恐慌時有人加槓桿抄底(2025-04-08單日餘額暴增66%,使用率25.24→33.67%)。
  ②00632R(元大台灣50反1)融資使用率同一表——百分位異常偏低=反向部位恐慌時被獲利了結
    (2025-04-08單日餘額97,336→71,781張)。
  ③殺出深度總水位(margin_total.today_balance WHERE name='MarginPurchaseMoney',(今日/245日內
    最大值-1)*100,口徑抄export_html.py的_depth6/_depth_zone6,分帶: ≤-30乾淨格/≤-20過渡段/
    ≤-10死亡谷/否則淺段)——確認這不是單純融資ETF雜訊,而是全市場真的在殺融資。
  ④SPX起火點確認(過濾器): 台股(加權/櫃買)vp10先破80分位後,20日內SPX vp10是否也跟著破80
    分位——邏輯抄build_regime_weather_report.py既有的vp10/upcross/spx_fire_after算法(但為避免
    載入該檔沉重的price_panel(),本卷獨立複製這段輕量邏輯,不import整支重跑腳本)。

⚠️樣本量務必誠實: margin_flow逐股資料僅2022-01起,00631L/00632R這兩軸能回測的窗口只有
  約4.5年,期間「殺出深度觸及過渡段以上(≤-20%)」且兩ETF同時異常的獨立事件只有n=2
  (2022-07-05修正段、2025-04-08關稅崩盤);放寬深度門檻到死亡谷(≤-10%)可多納入
  2024-08-06(全球降息交易/日圓套利平倉閃崩)共n=3。這是案例研究(case study)層級,
  不是統計驗證層級——bootstrap象徵性附上但信賴區間寬到不可靠,不包裝成「已驗證策略」。

用法: python 研究腳本/綜合策略/build_index_timing_etf_signal.py  (從根目錄,鐵律)
產出: 研究報告/research_index_timing_etf_signal.html
"""
import json
import sqlite3
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

DB = "capital_flow.db"
OUT = "研究報告/research_index_timing_etf_signal.html"

# ── 參數(可調門檻,理由見報告內文) ──────────────────────────
PCT_WIN, PCT_MIN = 252, 120      # 00631L/00632R使用率滾動百分位視窗(min_periods放寬供2022年暖身)
PL_TH = 80                       # 00631L使用率百分位≥80=恐慌加槓桿抄底
PR_TH = 20                       # 00632R使用率百分位≤20=反向部位恐慌了結
DEPTH_TH = -20                   # 殺出深度主口徑=過渡段以上(export_html._depth_zone6同口徑)
DEPTH_TH_LOOSE = -10             # 敏感度用寬鬆口徑=死亡谷以上
RECOVERY_TH = -10                # 深度回到「淺段」=修復完成出場
VP_START = "2006-01-01"          # vp10全樣本起點(與build_regime_weather_report.py一致)
QUIET = 21                       # 起火點安靜期(比照R6)
SPX_WINDOW_DAYS = 20             # 台股起火錨定後檢查SPX是否跟進的天數窗(比照R6 spx_fire_after)
SPX_LOOKBACK_DAYS = 40           # 台股起火錨定日距今幾天內仍視為「現正進行中」的容忍窗
MIN_GAP_DAYS = 60                # 觸發日群聚→視為同一事件的最大日曆日間隔
EVENT_GAP_DAYS = 60

GREEN, RED, BLUE, YELLOW, GRAY, PURPLE = "#7ec97e", "#e06c5a", "#6bb7e3", "#c3a55a", "#8a8878", "#b393d3"


# ── 資料載入 ──────────────────────────────────────────────
def load_index():
    con = sqlite3.connect(DB)
    idx = {m: pd.read_sql("SELECT date, close FROM index_daily WHERE market=? ORDER BY date",
                          con, params=(m,), parse_dates=["date"]).set_index("date").close
           for m in ("TAIEX", "TPEx", "SPX")}
    con.close()
    return idx


IDX = load_index()
TAIEX = IDX["TAIEX"]


def vp10(px, start=VP_START):
    r = px.pct_change() * 100
    v10 = r.rolling(10).std().dropna()
    v10 = v10[v10.index >= start]
    return v10.rank(pct=True) * 100


VP = {m: vp10(IDX[m]) for m in ("TAIEX", "TPEx", "SPX")}


def load_margin_flow():
    con = sqlite3.connect(DB)
    out = {}
    for code in ("00631L", "00632R"):
        s = pd.read_sql("SELECT date, fin_use FROM margin_flow WHERE code=? ORDER BY date",
                        con, params=(code,), parse_dates=["date"]).set_index("date").fin_use
        out[code] = s
    con.close()
    return out


MF = load_margin_flow()
PCTL = {code: MF[code].rolling(PCT_WIN, min_periods=PCT_MIN).rank(pct=True) * 100 for code in MF}


def load_depth():
    con = sqlite3.connect(DB)
    b = pd.read_sql("SELECT date, today_balance v FROM margin_total "
                    "WHERE name='MarginPurchaseMoney' ORDER BY date",
                    con, parse_dates=["date"]).set_index("date").v
    con.close()
    return (b / b.rolling(245, min_periods=200).max() - 1) * 100


DEPTH = load_depth()


def depth_zone(v):
    if pd.isna(v):
        return "—"
    return "乾淨格" if v <= -30 else "過渡段" if v <= -20 else "死亡谷" if v <= -10 else "淺段"


# ── SPX起火點確認過濾器(邏輯抄build_regime_weather_report.py既有vp10算法,輕量複製不重import) ──
def upcross(vp, quiet=QUIET):
    hot = vp > 80
    out = []
    for i, d in enumerate(vp.index):
        if hot.iloc[i] and (i == 0 or not hot.iloc[max(0, i - quiet):i].any()):
            out.append(d)
    return out


TW_FIRE_ANCHORS = sorted(set(upcross(VP["TAIEX"])) | set(upcross(VP["TPEx"])))


def spx_danger_at(t, anchors=TW_FIRE_ANCHORS, spx_vp=VP["SPX"],
                   lookback_days=SPX_LOOKBACK_DAYS, window_days=SPX_WINDOW_DAYS):
    """t=決策日(收盤後已知,零前視)。True=危險(近期台股起火且SPX已在起火後20日內跟進),
    False=安全(近期無台股起火,或起火後SPX至今仍未跟進)。"""
    relevant = [a for a in anchors if a <= t and (t - a).days <= lookback_days]
    for a in relevant:
        end = min(t, a + pd.Timedelta(days=window_days))
        win = spx_vp[(spx_vp.index >= a) & (spx_vp.index <= end)]
        if (win > 80).any():
            return True
    return False


def kret(d, k):
    i = TAIEX.index.searchsorted(d)
    if i >= len(TAIEX) or i + k >= len(TAIEX):
        return np.nan
    return float(TAIEX.iloc[i + k] / TAIEX.iloc[i] - 1) * 100


def recovery_exit(entry, recov_th=RECOVERY_TH):
    """深度回到淺段(>recov_th)視為修復完成;回傳(出場日, 持有交易日數, 報酬%)。尚未修復回傳(None,None,None)。"""
    d = DEPTH[DEPTH.index > entry]
    rec = d[d > recov_th]
    if len(rec) == 0:
        return None, None, None
    rd = rec.index[0]
    i0, i1 = TAIEX.index.searchsorted(entry), TAIEX.index.searchsorted(rd)
    return rd, int(i1 - i0), float(TAIEX.iloc[i1] / TAIEX.iloc[i0] - 1) * 100


# ── 訊號面板 ──────────────────────────────────────────────
def build_signal_frame():
    common = TAIEX.index[TAIEX.index >= MF["00631L"].index.min()]
    df = pd.DataFrame(index=common)
    df["close"] = TAIEX.reindex(common)
    df["depth"] = DEPTH.reindex(common).ffill()
    df["pl"] = PCTL["00631L"].reindex(common).ffill()
    df["pr"] = PCTL["00632R"].reindex(common).ffill()
    df["fin_use_l"] = MF["00631L"].reindex(common).ffill()
    df["fin_use_r"] = MF["00632R"].reindex(common).ffill()
    df["spx_vp10"] = VP["SPX"].reindex(common).ffill()
    df["tw_vp10"] = VP["TAIEX"].reindex(common).ffill()
    df["otc_vp10"] = VP["TPEx"].reindex(common).ffill()
    df["spx_danger"] = [spx_danger_at(t) for t in common]
    return df


SIG = build_signal_frame()
STUDY_START = SIG.dropna(subset=["pl", "pr"]).index.min()
print(f"訊號面板: {len(SIG)}日 {SIG.index.min().date()}~{SIG.index.max().date()}"
      f"｜百分位暖身完成起點={STUDY_START.date()}")


def combo_mask(df, depth_th=DEPTH_TH, pl_th=PL_TH, pr_th=PR_TH, use_spx=False):
    base = (df.depth <= depth_th) & (df.pl >= pl_th) & (df.pr <= pr_th)
    if use_spx:
        return base & (~df.spx_danger)
    return base


def extract_events(mask, min_gap_days=MIN_GAP_DAYS):
    """觸發日群聚(同一場崩跌連續數日符合條件)只取每群第一天=進場日,避免同一事件重複計數。"""
    days = mask.index[mask.values]
    events, last = [], None
    for d in days:
        if last is None or (d - last).days > min_gap_days:
            events.append(d)
        last = d
    return events


# ── 事件研究 ──────────────────────────────────────────────
def event_row(d):
    r = SIG.loc[d]
    rd, ndays, rret = recovery_exit(d)
    return {
        "date": d, "depth": float(r.depth), "zone": depth_zone(r.depth),
        "fin_use_l": float(r.fin_use_l), "pl": float(r.pl),
        "fin_use_r": float(r.fin_use_r), "pr": float(r.pr),
        "tw_vp10": float(r.tw_vp10), "otc_vp10": float(r.otc_vp10),
        "spx_vp10": float(r.spx_vp10), "spx_danger": bool(r.spx_danger),
        "k5": kret(d, 5), "k10": kret(d, 10), "k20": kret(d, 20),
        "k40": kret(d, 40), "k60": kret(d, 60),
        "recov_date": rd, "recov_days": ndays, "recov_ret": rret,
    }


def baseline_fwd(start, k):
    p = TAIEX[TAIEX.index >= start]
    r = (p.shift(-k) / p - 1).dropna() * 100
    return {"mean": float(r.mean()), "median": float(r.median()), "win": float((r > 0).mean() * 100),
            "n": int(len(r))}


# ── 出場規則比較的權益曲線(零前視: position從進場日"隔日"起算,等同kret的口�s) ──────
def build_position(entry_exit_pairs, idx):
    pos = pd.Series(0.0, index=idx)
    for a, b in entry_exit_pairs:
        pos.loc[(idx > a) & (idx <= b)] = 1.0
    return pos


def curve_stats(entry_exit_pairs, idx, ret):
    pos = build_position(entry_exit_pairs, idx)
    sr = ret * pos
    eq = (1 + sr).cumprod()
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    mult = float(eq.iloc[-1])
    ann = (mult ** (1 / yrs) - 1) * 100
    mdd = float((eq / eq.cummax() - 1).min() * 100)
    active = sr[pos > 0]
    vol_ann = float(active.std()) * np.sqrt(252) * 100 if len(active) > 3 else 0.0
    sharpe = ann / vol_ann if vol_ann else 0.0
    return {"eq": eq, "mult": round(mult, 3), "ann": round(ann, 1), "mdd": round(mdd, 1),
            "expo": round(float((pos > 0).mean()) * 100, 1), "sharpe": round(sharpe, 2),
            "n_days": int((pos > 0).sum())}


def sensitivity_grid():
    rows = []
    for depth_th in (-10, -15, -20, -30):
        for pl_th, pr_th in ((70, 30), (80, 20), (90, 10)):
            m = combo_mask(SIG, depth_th=depth_th, pl_th=pl_th, pr_th=pr_th, use_spx=False)
            m_spx = combo_mask(SIG, depth_th=depth_th, pl_th=pl_th, pr_th=pr_th, use_spx=True)
            ev = extract_events(m)
            ev_spx = extract_events(m_spx)
            rows.append({"depth_th": depth_th, "pl_th": pl_th, "pr_th": pr_th,
                        "n_raw": len(ev), "n_spx": len(ev_spx),
                        "dates": "、".join(str(d.date()) for d in ev)})
    return rows


def bootstrap_context(events, k, reps=5000, seed=42):
    """象徵性: 若n個事件只是從全樣本隨機抽到的k日遠期報酬,分布長怎樣。n=2~3時CI極寬,僅供參考。"""
    if len(events) == 0:
        return None
    rng = np.random.default_rng(seed)
    pool = (TAIEX.shift(-k) / TAIEX - 1).dropna() * 100
    pool = pool[pool.index >= STUDY_START].values
    obs = np.array([kret(d, k) for d in events])
    obs = obs[~np.isnan(obs)]
    if len(obs) == 0 or len(pool) == 0:
        return None
    obs_mean = float(obs.mean())
    draws = rng.choice(pool, size=(reps, len(obs)), replace=True).mean(axis=1)
    pct = float((draws < obs_mean).mean() * 100)
    return {"obs_mean": obs_mean, "n": len(obs), "pool_n": len(pool),
            "boot_mean": float(draws.mean()), "boot_p5": float(np.percentile(draws, 5)),
            "boot_p95": float(np.percentile(draws, 95)), "pctile_of_obs": pct}


# ── 主流程 ──────────────────────────────────────────────
def main():
    mask_primary = combo_mask(SIG, depth_th=DEPTH_TH, use_spx=False)
    mask_primary_spx = combo_mask(SIG, depth_th=DEPTH_TH, use_spx=True)
    mask_loose = combo_mask(SIG, depth_th=DEPTH_TH_LOOSE, use_spx=False)
    mask_loose_spx = combo_mask(SIG, depth_th=DEPTH_TH_LOOSE, use_spx=True)
    mask_flowonly = (SIG.pl >= PL_TH) & (SIG.pr <= PR_TH)   # 不含深度確認,用來對照「雜訊有多少」

    ev_primary = extract_events(mask_primary)
    ev_primary_spx = extract_events(mask_primary_spx)
    ev_loose = extract_events(mask_loose)
    ev_loose_spx = extract_events(mask_loose_spx)
    ev_flowonly = extract_events(mask_flowonly)

    print("=" * 90)
    print(f"主口徑(深度≤{DEPTH_TH}%)事件: {[str(d.date()) for d in ev_primary]}")
    print(f"主口徑+SPX濾網 事件: {[str(d.date()) for d in ev_primary_spx]}")
    print(f"寬鬆口徑(深度≤{DEPTH_TH_LOOSE}%)事件: {[str(d.date()) for d in ev_loose]}")
    print(f"寬鬆口徑+SPX濾網 事件: {[str(d.date()) for d in ev_loose_spx]}")
    print(f"僅兩ETF訊號(不含深度確認)事件群數: {len(ev_flowonly)} -> {[str(d.date()) for d in ev_flowonly]}")

    rows_primary = [event_row(d) for d in ev_primary]
    rows_loose = [event_row(d) for d in ev_loose]
    extra_loose = [r for r in rows_loose if r["date"] not in ev_primary]

    for r in rows_primary + extra_loose:
        print(f"  {r['date'].date()} depth={r['depth']:.1f}%({r['zone']}) "
              f"00631L用率{r['fin_use_l']:.1f}%/百分位{r['pl']:.0f} "
              f"00632R用率{r['fin_use_r']:.1f}%/百分位{r['pr']:.0f} "
              f"SPXvp10={r['spx_vp10']:.0f} danger={r['spx_danger']} "
              f"k20={r['k20']:+.2f}% k60={r['k60']:+.2f}% "
              f"修復={r['recov_date'].date() if r['recov_date'] is not None else '尚未'}"
              f"({r['recov_days']}日,{r['recov_ret']:+.2f}%)" if r['recov_date'] is not None else "尚未修復")

    base20 = baseline_fwd(STUDY_START, 20)
    base60 = baseline_fwd(STUDY_START, 60)
    print(f"基期(全樣本{STUDY_START.date()}起未條件化) k20: 均{base20['mean']:+.2f}% 中位{base20['median']:+.2f}% "
          f"勝率{base20['win']:.0f}% n={base20['n']}")
    print(f"基期 k60: 均{base60['mean']:+.2f}% 中位{base60['median']:+.2f}% 勝率{base60['win']:.0f}% n={base60['n']}")

    # ── 權益曲線(study window: 百分位暖身完成起~最新) ──
    p = TAIEX[TAIEX.index >= STUDY_START]
    ret = p.pct_change().fillna(0)

    def fixed_windows(entries, k):
        out = []
        for e in entries:
            i0 = TAIEX.index.searchsorted(e)
            i1 = min(i0 + k, len(TAIEX) - 1)
            out.append((TAIEX.index[i0], TAIEX.index[i1]))
        return out

    def recovery_windows(entries):
        out = []
        for e in entries:
            rd, _, _ = recovery_exit(e)
            if rd is not None:
                out.append((e, rd))
            else:
                out.append((e, TAIEX.index[-1]))   # 尚未修復,持有至資料末端(誠實揭露)
        return out

    variants = {
        "買進持有": [(p.index[0], p.index[-1])],
        "固定持有20日(主口徑2事件)": fixed_windows(ev_primary, 20),
        "固定持有60日(主口徑2事件)": fixed_windows(ev_primary, 60),
        "深度修復出場(主口徑2事件)": recovery_windows(ev_primary),
        "深度修復出場(寬鬆口徑3事件)": recovery_windows(ev_loose),
    }
    curves = {name: curve_stats(pairs, p.index, ret) for name, pairs in variants.items()}
    for name, c in curves.items():
        print(f"  {name}: {c['mult']}x({(c['mult']-1)*100:+.1f}%) 年化{c['ann']}% MDD{c['mdd']}% "
              f"曝險{c['expo']}% 粗夏普{c['sharpe']}")

    sens = sensitivity_grid()
    boot20_p = bootstrap_context(ev_primary, 20)
    boot60_p = bootstrap_context(ev_primary, 60)
    boot20_l = bootstrap_context(ev_loose, 20)
    boot60_l = bootstrap_context(ev_loose, 60)

    # 當下讀數(2026-08-01前情提要用)
    last = SIG.index[-1]
    cur = SIG.loc[last]
    print("=" * 90)
    print(f"當下({last.date()}): depth={cur.depth:.1f}%({depth_zone(cur.depth)}) "
          f"00631L百分位={cur.pl:.0f} 00632R百分位={cur.pr:.0f} SPXvp10={cur.spx_vp10:.0f} "
          f"danger={cur.spx_danger} 組合觸發={bool(mask_primary.loc[last])}")

    html = build_html(rows_primary, extra_loose, base20, base60, curves, p, sens,
                      (boot20_p, boot60_p, boot20_l, boot60_l),
                      ev_flowonly, cur, last, mask_primary.loc[last])
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"已產出 {OUT} ({len(html):,} chars)")


# ── HTML ──────────────────────────────────────────────────
CSS = """
body{background:#1a1a19;color:#fff;font-family:"Noto Sans TC",sans-serif;margin:24px;max-width:1180px}
h1{font-size:20px} h2{font-size:15px;color:#c3c2b7;margin-top:30px;border-bottom:1px solid #333;padding-bottom:4px}
h3{font-size:13.5px;color:#a8a79a;margin:16px 0 4px}
table{border-collapse:collapse;font-size:12.5px;font-variant-numeric:tabular-nums;margin:8px 0}
td,th{border:1px solid #333;padding:4px 9px;text-align:right} th{text-align:left;color:#c3c2b7}
.note{color:#8a8878;font-size:12.5px;line-height:1.8} .good{color:#7ec97e} .bad{color:#e06c5a}
.warn{color:#c3a55a} .hl{background:#2b3a2b} .sub{color:#777;font-size:11px}
.scroll{max-height:420px;overflow-y:auto;display:inline-block}
.banner{background:#3a2a1a;border:1px solid #c3a55a;border-radius:6px;padding:14px 18px;margin:16px 0;
        color:#f0dfa8;font-size:13.5px;line-height:1.8}
"""
BG = {"paper_bgcolor": "#1a1a19", "plot_bgcolor": "#22221f",
      "font": {"color": "#ddd", "size": 12}, "margin": {"t": 40, "l": 55, "r": 20, "b": 40}}


def fmtpp(v, digits=2):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "—"
    return f"{v:+.{digits}f}%"


def event_table_html(rows, base20, base60):
    body = ""
    for r in rows:
        recov = (f"{r['recov_date'].date()}({r['recov_days']}日) "
                 f"<span class='{'good' if r['recov_ret']>=0 else 'bad'}'>{r['recov_ret']:+.2f}%</span>"
                 if r["recov_date"] is not None else "<span class='warn'>尚未修復(資料至今)</span>")
        danger_txt = "<span class='bad'>危險(否決)</span>" if r["spx_danger"] else "<span class='good'>安全(放行)</span>"
        body += (f"<tr><th>{r['date'].date()}</th>"
                 f"<td>{r['depth']:.1f}%<br><span class='sub'>{r['zone']}</span></td>"
                 f"<td>{r['fin_use_l']:.1f}%<br><span class='sub'>百分位{r['pl']:.0f}</span></td>"
                 f"<td>{r['fin_use_r']:.1f}%<br><span class='sub'>百分位{r['pr']:.0f}</span></td>"
                 f"<td>加權{r['tw_vp10']:.0f}/櫃買{r['otc_vp10']:.0f}<br>"
                 f"<span class='sub'>SPX {r['spx_vp10']:.0f}</span></td>"
                 f"<td>{danger_txt}</td>"
                 f"<td class='{'good' if r['k5']>=0 else 'bad'}'>{fmtpp(r['k5'])}</td>"
                 f"<td class='{'good' if r['k20']>=0 else 'bad'}'>{fmtpp(r['k20'])}</td>"
                 f"<td class='{'good' if r['k60']>=0 else 'bad'}'>{fmtpp(r['k60'])}</td>"
                 f"<td>{recov}</td></tr>")
    return (f"<table><tr><th>觸發日</th><th>殺出深度</th><th>00631L使用率</th><th>00632R使用率</th>"
            f"<th>vp10(加權/櫃買/SPX)</th><th>SPX確認</th><th>k5</th><th>k20</th><th>k60</th>"
            f"<th>深度修復出場</th></tr>{body}"
            f"<tr><th colspan=6>基期(未條件化,{'k5'}略)k20/k60</th>"
            f"<td>—</td><td>均{base20['mean']:+.2f}%<br>中位{base20['median']:+.2f}%/勝{base20['win']:.0f}%"
            f"<br><span class='sub'>n={base20['n']}</span></td>"
            f"<td>均{base60['mean']:+.2f}%<br>中位{base60['median']:+.2f}%/勝{base60['win']:.0f}%"
            f"<br><span class='sub'>n={base60['n']}</span></td><td>—</td></tr></table>")


def sens_table_html(sens):
    body = ""
    for r in sens:
        body += (f"<tr><th>深度≤{r['depth_th']}%</th><th>00631L≥{r['pl_th']}／00632R≤{r['pr_th']}</th>"
                 f"<td>{r['n_raw']}</td><td>{r['n_spx']}</td>"
                 f"<td style='text-align:left;font-size:11px'>{r['dates'] or '—'}</td></tr>")
    return ("<table><tr><th>深度門檻</th><th>百分位門檻</th><th>事件數(不含SPX濾網)</th>"
            f"<th>事件數(含SPX濾網)</th><th>觸發日期</th></tr>{body}</table>")


def boot_row(label, b):
    if b is None:
        return f"<tr><th>{label}</th><td colspan=5>n=0,無法計算</td></tr>"
    return (f"<tr><th>{label}</th><td>{b['n']}</td><td>{b['obs_mean']:+.2f}%</td>"
            f"<td>{b['boot_mean']:+.2f}%</td><td>[{b['boot_p5']:+.2f}%, {b['boot_p95']:+.2f}%]</td>"
            f"<td>{b['pctile_of_obs']:.0f}分位</td></tr>")


def build_html(rows_primary, extra_loose, base20, base60, curves, p, sens, boots, ev_flowonly,
               cur, last, triggered_now):
    boot20_p, boot60_p, boot20_l, boot60_l = boots
    n_primary, n_loose = len(rows_primary), len(rows_primary) + len(extra_loose)

    ev_table_primary = event_table_html(rows_primary, base20, base60)
    ev_table_loose_extra = event_table_html(extra_loose, base20, base60) if extra_loose else "<div class='note'>(無額外事件)</div>"
    sens_html = sens_table_html(sens)

    curve_rows = "".join(
        f"<tr><th>{n}</th><td>{c['mult']}x({(c['mult']-1)*100:+.1f}%)</td><td>{c['ann']:+.1f}%</td>"
        f"<td>{c['mdd']}%</td><td>{c['expo']}%</td><td>{c['sharpe']}</td></tr>"
        for n, c in curves.items())

    spx_verdict_n = sum(1 for r in rows_primary if r["spx_danger"]) + sum(1 for r in extra_loose if r["spx_danger"])
    spx_verdict_total = n_loose

    payload = {
        "eq": {n: {"d": [str(d.date()) for d in c["eq"].index[::2]],
                   "v": [round(float(x), 4) for x in c["eq"].values[::2]]}
               for n, c in curves.items()},
        "depth": {"d": [str(d.date()) for d in SIG.index], "v": [round(float(x), 1) if pd.notna(x) else None for x in SIG.depth]},
        "pl": {"d": [str(d.date()) for d in SIG.index], "v": [round(float(x), 1) if pd.notna(x) else None for x in SIG.pl]},
        "pr": {"d": [str(d.date()) for d in SIG.index], "v": [round(float(x), 1) if pd.notna(x) else None for x in SIG.pr]},
        "events": [str(r["date"].date()) for r in rows_primary] + [str(r["date"].date()) for r in extra_loose],
    }

    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>底部確認訊號組合×加權指數擇時回測(2026-08-01)</title>
<script src="plotly.min.js"></script><style>{CSS}</style></head><body>
<h1>🎯 底部確認訊號組合×加權指數擇時回測——00631L/00632R融資+殺出深度+SPX起火點確認(2026-08-01)</h1>
<div class="note">本卷把同一場對話裡驗證過的四個「底部訊號」組合成一套進場規則,回測標的=加權指數(TAIEX,
用指數報酬本身模擬,不模擬台指期轉倉/基差/保證金)。姊妹卷:研究報告/research_regime_weather.html
的R9已測過「天氣儀」regime訊號直接擇時大盤,結論=均線開關降MDD不增報酬、蹺蹺板擇時大盤=爛,
本卷用完全不同的訊號家族(個股ETF融資+總水位+全球起火點)重新檢驗同一個問題。</div>

<div class="banner">⚠️<b>樣本量限制,請先讀這段:</b>margin_flow逐股資料僅2022-01起,本卷可回測窗口只有
約4.5年。「殺出深度觸及過渡段以上(≤-20%)」且00631L/00632R同時異常的<b>獨立事件僅n={n_primary}</b>
(2022-07修正段、2025-04關稅崩盤);放寬深度門檻到死亡谷(≤-10%)可多納入2024-08(全球降息交易閃崩)
共<b>n={n_loose}</b>。這個樣本數做正式統計顯著性檢定沒有意義(bootstrap信賴區間會寬到不可靠),
<b>本卷定位=案例研究(把每次觸發攤開來給你看),不是「已驗證策略」</b>。如果讀完後結論是「這訊號
只降MDD不增報酬」甚至「連MDD都沒降」,會照實寫,不會為了交差硬凹正面結論。</div>

<h2>📋 訊號定義與門檻理由</h2>
<table>
<tr><th>訊號</th><th>門檻</th><th>理由</th></tr>
<tr><td>00631L(正2)融資使用率百分位</td><td>≥80(相對自身252日滾動,min_periods=120)</td>
<td>本場對話驗證: 全樣本(2022-2026)與加權指數20日報酬相關-0.44;用「相對自己歷史」的百分位
而非絕對水位,因為ETF規模持續成長,絕對使用率本身有趨勢,百分位排除了這個趨勢污染</td></tr>
<tr><td>00632R(反1)融資使用率百分位</td><td>≤20(同上滾動視窗)</td>
<td>驗證: 相關+0.408(方向相反);百分位偏低=反向部位在恐慌時被停損/獲利了結,與00631L訊號互為
獨立確認(兩者相關性不是1:1複製,見下方訊號共現分析)</td></tr>
<tr><td>殺出深度總水位</td><td>≤-20%(過渡段以上,export_html._depth_zone6同口徑)</td>
<td>確認全市場真的在殺融資,不是ETF自己的槓桿操作雜訊;不含此條件時,單靠兩ETF訊號一年出現
好幾群「假警報」(見下方對照),深度確認是拿掉雜訊的關鍵一道閥門</td></tr>
<tr><td>SPX起火點確認</td><td>近期(40日內)台股vp10破80分位者,20日內SPX vp10未破80分位=安全</td>
<td>邏輯抄build_regime_weather_report.py既有vp10/upcross/spx_fire_after算法;動機=避免誤觸
真正的全球系統性風暴(該報告R6發現「櫃買先爆但SPX也跟著著火」的案例後續表現差)</td></tr>
</table>

<h2>①主口徑事件表(深度≤-20%,n={n_primary})——這是本卷核心,逐筆攤開</h2>
{ev_table_primary}
<div class="note">k5/k20/k60=觸發日收盤起算的加權指數遠期報酬(與build_regime_weather_report.py
的kret()同口徑:收盤已知訊號,report的是「之後k個交易日」的報酬,不外加額外一日延遲——
這與本卷權益曲線用的position(t)=1[t∈(entry, exit]]完全等價,兩者都是從進場日「隔日」起算報酬,
無前視)。基期列=同一研究窗內未條件化的全樣本遠期報酬平均,供比對「觸發後是不是真的比較好」。</div>

<h3>寬鬆口徑(深度≤-10%)多納入的事件</h3>
{ev_table_loose_extra}
<div class="note">2024-08事件=全球央行降息交易/日圓套利平倉閃崩(該事件深度只探到約-14.5%,
未達主口徑-20%門檻,故只在寬鬆口徑下出現)。</div>

<h2>②SPX起火點確認過濾器——本卷最重要的發現</h2>
<div class="banner">
<b>結果:{spx_verdict_n}/{spx_verdict_total}個候選事件,SPX確認過濾器全部判定「危險」(否決進場)。</b>
逐一檢查觸發當下SPX vp10實際讀數:2022-07-05為86.3分位、2024-08-06為85.0分位、2025-04-08為
95.9分位——三次事件觸發的當下,SPX本身都已經在高波動狀態。<br><br>
<b>誠實解讀:這不是程式錯誤,是這個樣本的結構性特徵。</b>「殺出深度≤-20%」這個條件本身已經要求
一場夠深的全市場真實重挫,而近四年半台股夠深的重挫,剛好每一次都同時是全球性事件
(2022聯準會暴力升息、2024日圓套利平倉、2025對等關稅)——三個都是全球市場同步共振的行情,
不是純台股孤立的地方性事件。也就是說,在<b>本卷這個小樣本裡</b>,「深度確認的本土底部訊號」
與「SPX同步在燒」幾乎是同一件事的兩面,疊加SPX確認過濾器不是多一層安全網,而是幾乎必然否決
掉每一次真正夠深的進場機會——<b>套用嚴格版SPX過濾器=0筆交易</b>。這與build_regime_weather_report.py
R6用「起火點階梯」框架下「櫃買先爆×SPX安靜=正格劇本」的發現並不矛盾(那裡的樣本包含很多
沒有觸發深度確認的較小規模事件,兩市層n=~20+),差別在於:一旦额外疊加「深度已經很深」這個
高門檻條件,能通過的事件本身就都是大到會牽動SPX的等級,SPX過濾器在這個交集裡失去鑑別力。
</div>

<h2>③出場規則比較(權益曲線,{p.index[0].date()}~{p.index[-1].date()})</h2>
<table><tr><th>版本</th><th>倍數(累積報酬)</th><th>年化</th><th>MDD</th><th>曝險天數占比</th>
<th>粗夏普(僅曝險期)</th></tr>{curve_rows}</table>
<div id="c1" style="height:440px"></div>
<div class="note">
<b>誠實結論:任何一種出場規則,累積報酬都遠遠輸給買進持有</b>——原因不是「訊號抓錯方向」
(下面會看到觸發後續報酬多半優於基期),而是<b>曝險率太低</b>:主口徑只有2次事件、寬鬆口徑3次,
研究窗內大半時間台股走的是2023~2026強力結構性多頭(AI/半導體),策略絕大多數時間在場外
(曝險僅~4~40%視出場規則而定),完全錯過場外那段期間的複利——這正是「精準抄底但整體跑輸大盤」
的經典市場擇時稅(market timing tax)。<br>
<b>出場規則本身的比較有意義</b>:「深度修復出場」(耐心持有到殺出深度回到淺段>-10%)遠優於
固定20日/60日持有——2022年那次固定60日持有反而是負報酬(k60=-6.15%,見①事件表,2022是緩跌熊市
不是V轉),固定20日持有雖然正但幅度很小;深度修復出場則能吃到完整的修復段(2025-04事件耐心
持有到2025-10底部訊號解除,報酬遠優於固定天數版)。<b>MDD全數優於買進持有</b>(-18.1% vs -28.7%),
與R9「均線開關買的是MDD不是報酬」結論同一個模式再現一次——不同訊號家族,同一個結論。
</div>

<h2>④參數敏感度(事件數量隨門檻變化;n太小無法判斷績效優劣,只列事件數誠實揭露)</h2>
{sens_html}
<div class="note">不論深度門檻或百分位門檻怎麼調,事件數都停在個位數——這不是找到了「太嚴格」的
參數該放寬,而是這四年半台股夠格稱為「大盤重挫」的獨立事件本來就只有這幾次。放寬百分位門檻
(70/30)不會顯著增加事件數,代表主要瓶頸是「殺出深度」這道閥門(它本身依賴的是全市場融資水位
從未創新高的持續時間,是校事件層級的粗變數,不是能被百分位微調解決的雜訊問題)。</div>

<h2>⑤象徵性bootstrap(⚠n=2~3,信賴區間寬到不可靠,僅供參考不代表統計顯著)</h2>
<table><tr><th>版本</th><th>事件數n</th><th>實際觀察均值</th><th>隨機抽樣均值</th>
<th>隨機抽樣5~95分位區間</th><th>觀察值落在隨機分布第幾分位</th></tr>
{boot_row("主口徑 k20", boot20_p)}
{boot_row("主口徑 k60", boot60_p)}
{boot_row("寬鬆口徑 k20", boot20_l)}
{boot_row("寬鬆口徑 k60", boot60_l)}
</table>
<div class="note">方法: 從研究窗內全樣本「隨機一天」的k日遠期報酬中,有放回抽樣n次(n=事件數)取均值,
重複5000次,得到「如果訊號跟亂猜一樣」的均值分布;觀察值落在這個分布的高分位,方向上支持
「訊號挑的日子後續報酬確實比隨機好」,<b>但n=2~3時這個分布本身極寬、抽樣誤差極大,不能當成
正式的統計顯著性證據,只能當「方向參考」</b>——這正是為什麼本卷從頭到尾定位是案例研究而非
驗證過的策略。</div>

<h2>⑥兩ETF訊號若不搭配深度確認,雜訊有多少</h2>
<div class="note">單靠00631L百分位≥80且00632R百分位≤20(不要求深度確認)的觸發日群數={len(ev_flowonly)},
遠多於通過深度確認的{n_primary}~{n_loose}次——例如2024-01-18、2024-11-22~12-20那一長串,
當時殺出深度僅約-4~-5%(遠未觸及死亡谷),對照TAIEX走勢也沒有發生實質重挫,顯示兩ETF訊號單獨
使用時對市場性質不夠敏感的雜訊不少,深度確認這道閥門確實在做有意義的過濾工作。</div>

<h2>⑦與R9舊regime訊號的誠實比較</h2>
<div class="note">R9(research_regime_weather.html,2006起,全樣本規則式持倉)結論:買進持有6.18x/
年化9.3%/MDD-58.3%,排列版開關3.34x/MDD-29.4%,斜率版開關4.35x/MDD-22.7%,蹺蹺板胃納張2.38x/
MDD-40.9%——判決「均線開關買的是MDD不是報酬,胃納(大小盤蹺蹺板)拿去擇時大盤=爛」。<br>
本卷訊號家族完全不同(個股ETF融資+總水位+全球起火點,樣本窗2022起),<b>結論方向一致:降MDD、
不增報酬</b>,而且本卷的曝險率遠低於R9(4~40% vs R9的排列/斜率版約50~95%),所以「跑輸買進持有」
的幅度比R9更劇烈。兩份研究用不同訊號、不同時間窗,得到同一個質性結論,<b>互相佐證這不是單一
訊號的偶然,而是「拿擇時訊號直接開關大盤」這件事本身的結構性限制</b>——與R9判詞「天氣儀是策略
選擇器不是大盤擇時器」呼應:底部確認訊號拿去精準挑選個別進場點也許有參考價值(每次事件後續
表現多優於基期),但拿來當「加權指數要不要持有」的總開關,代價是錯過場外的長期多頭,不划算。
兩份研究因時間窗不同(R9 since 2006 vs 本卷 since 2022),倍數/年化數字不能直接跨窗比較,
比較基準改用「同窗買進持有」——本卷已在③內完成。</div>

<h2>📍當下讀數({last.date()})</h2>
<table>
<tr><th>殺出深度</th><td>{cur.depth:+.1f}%({depth_zone(cur.depth)})</td></tr>
<tr><th>00631L使用率</th><td>{cur.fin_use_l:.1f}%(252日百分位{cur.pl:.0f})</td></tr>
<tr><th>00632R使用率</th><td>{cur.fin_use_r:.1f}%(252日百分位{cur.pr:.0f})</td></tr>
<tr><th>vp10</th><td>加權{cur.tw_vp10:.0f}／櫃買{cur.otc_vp10:.0f}／SPX{cur.spx_vp10:.0f}分位</td></tr>
<tr><th>主口徑組合是否已觸發</th><td>{"<span class='good'>是</span>" if triggered_now else "<span class='sub'>否(尚未同時滿足)</span>"}</td></tr>
</table>
<div class="note">{('⚠深度已於近日跌破-20%過渡段,持續觀察00631L/00632R是否跟上——若00631L百分位補上≥80,'
    '本卷主口徑訊號將正式觸發下一個獨立事件。') if cur.depth<=DEPTH_TH else ''}</div>

<h2>已知限制(誠實聲明)</h2>
<div class="note">
①<b>樣本量=案例研究層級</b>:margin_flow僅2022-01起,主口徑n=2、寬鬆口徑n=3,任何「勝率/顯著性」
語言都不適用,本卷全篇以「逐筆攤開」取代「統計驗證」;<br>
②<b>2022年事件的252日百分位暖身不足</b>:margin_flow從2022-01-03起算,2022-07-05事件當時歷史窗
只有約125個交易日(遠低於252日目標),百分位計算基礎比後續事件單薄,可信度較低;<br>
③<b>標的用指數報酬模擬,非台指期</b>:未計入轉倉/基差/保證金/交易成本,若真要用台指期執行,
實際報酬會因基差與保證金效率而有差異;<br>
④<b>SPX確認過濾器與深度確認條件在本樣本高度重疊</b>(見②),此發現本身只在n=2~3的小樣本下成立,
不代表兩條件在更大樣本或其他市場環境下也會如此重疊,值得未來資料更長時累積後重新檢驗;<br>
⑤<b>深度修復出場規則的2022年案例持有期長達235個交易日(近一年)</b>,實務上「無限期等修復」
的機會成本與紀律挑戰在本卷未納入評估(例如若當時提早放棄改做別的部位,機會成本如何);<br>
⑥<b>事件數過少無法拆分「進場點選得好」與「大盤剛好那段時間反彈」兩種解釋</b>——3個事件都發生在
之後市場出現顯著反彈的窗口,但這也可能只是「台股過去4年多次重挫後都有反彈」這個更廣泛現象的
子集,訊號本身的增量貢獻無法在n=2~3的樣本下被隔離出來。
</div>
<div class="note">維運: python 研究腳本/綜合策略/build_index_timing_etf_signal.py(從根目錄執行,
無外部快取依賴,重跑即可反映最新資料)。姊妹卷:research_regime_weather.html(R9指數層擇時)、
research_margin_exetf.html(ETF排除版維持率對照)。</div>

<script>
const D={json.dumps(payload, ensure_ascii=False)};
const BG={json.dumps(BG)};
const traces=[];
const colors={{"買進持有":"#8ab4f8","固定持有20日(主口徑2事件)":"#c3a55a",
  "固定持有60日(主口徑2事件)":"#e06c5a","深度修復出場(主口徑2事件)":"#7ec97e",
  "深度修復出場(寬鬆口徑3事件)":"#b393d3"}};
for (const name in D.eq) {{
  traces.push({{x:D.eq[name].d, y:D.eq[name].v, name:name,
    line:{{width:name==="買進持有"?1.3:2, dash:name==="買進持有"?"dot":"solid",
           color:colors[name]||"#fff"}}}});
}}
Plotly.newPlot('c1', traces, Object.assign({{title:'出場規則權益曲線比較(log,起點=1,零前視)',
  yaxis:{{type:'log'}},
  shapes:D.events.map(a=>({{type:'line',x0:a,x1:a,yref:'paper',y0:0,y1:1,
    line:{{color:'#c3a55a',width:1,dash:'dot'}}}}))}},BG));
</script></body></html>"""


if __name__ == "__main__":
    main()
