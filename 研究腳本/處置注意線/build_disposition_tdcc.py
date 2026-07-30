# -*- coding: utf-8 -*-
"""處置 × 千張大戶位階(TDCC p1000)條件化研究(使用者2026-07-23提案,系統化考卷)
假說: 進處置時千張大戶持股%處於自身歷史高位階 => 處置洗籌洗掉散戶/投機客,大戶接近滿手不賣,
出關後籌碼賣壓小 => V4反彈/出關後表現應更好。
先驗警告: 本專案TDCC進場端已三度全滅——本題是「對已驗證策略做條件化」不是獨立進場訊號,
但先驗不利,證據門檻拉高,弱結果不得敘事成正面。

設計(預註冊):
- 母體: 重用tmp_disposition_exit_fade_panel.pkl(2,966事件,event_id口徑=disposition
  dropna(start,end).reset_index,已含post1/3/5/10/20+G1-G4型態標籤+v5_net);match_min '5'/'20'分層永不合併
- V4交易(panel無,自算): 口徑同build_panic_liquidity_report.v4_v5_dated_curves——
  第3處置交易日收盤買(c[s+2])→出關日開盤出(o[en+1]),6<=en-s<=25,剔reason含「人工管制」
  (現行DB=0筆no-op,照掛存證),扣0.45%成本(任務書寫0.3%但依house spec 0.45%為準)
- 特徵(無前視): 取date <= announce_date-3日曆日的最新tdcc_weekly快照(發布延遲安全邊際),
  快照距cutoff>21天=過期作廢;百分位規約=(窗內值<=當前值)比例*100,窗含當前快照
  (已用2454/8261軼事對重現鎖定: 2454@0506 PFULL=28.2/P52=94.2, 8261@0708 PFULL=99.3/P52=100.0)
  * P52: 對自身近52快照(~1年,house位階慣例240日類比);窗<26快照=NaN(不足報數量)
  * PFULL: 對自身全史;要求>=52個先前快照才合格
  * d4w: p1000當前-4快照前(大戶流向,與位階正交的次要特徵)
- 分析: ①V4按P52四分位(固定切點25/50/75)+house慣例P52>=80二元+PFULL同+d4w三分位(rank法),
  中位/均值/勝率/單調梯度;高vs其餘差值LOTO(逐年)+年群bootstrap(B=10000,seed=42)
  ②出關後post5/10/20同切分 ③與當日G1-G4型態組交互(組內P52中位切,n<15-20不硬跑bootstrap)
  ④機制一致性: 故事預測「高位階且d4w>=0(大戶沒跑)」應優於單看位階——P52高低×d4w正負交叉表
  ⑤冗餘檢查: P52/p1000與規模代理(處置前20交易日中位成交值)的Spearman;成交值三分位內的高vs餘差
- 覆蓋/存活偏差: tdcc_weekly 1,378檔 vs disposition ~1,484檔;逐年配對率+缺碼是否集中早年
  (若tdcc宇宙來自現行股票清單,已下市股缺=存活偏差);另查tdcc各碼最後快照日分布佐證
用法: python -X utf8 build_disposition_tdcc.py  (Windows終端機cp950易炸)
"""
import sqlite3
import sys
import time

import numpy as np
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DB = "capital_flow.db"
PANEL_IN = "tmp_disposition_exit_fade_panel.pkl"
PANEL_OUT = "tmp_disposition_tdcc_panel.pkl"
LAG_DAYS = 3          # announce_date - 3日曆日 = 快照cutoff(發布延遲安全邊際)
STALE_DAYS = 21       # 快照距cutoff超過21天 = 覆蓋中斷,特徵作廢
P52_WIN = 52
P52_MIN = 26          # 窗內至少26快照(半年)才算P52
PFULL_MIN_PRIOR = 52  # PFULL要求>=52個先前快照
HI_TH = 80.0          # house慣例高位階
V4_COST = 0.45
POST_KS = [5, 10, 20]
HL_COL = "grp_r8_a"   # exit_fade headline型態欄
B_BOOT = 10000
SEED = 42
SANITY = {
    ("2454", "2026-05-06"): {"snap": "2026-04-30", "p1000": 67.2, "pfull": 28, "p52": 94},
    ("8261", "2026-07-08"): {"snap": "2026-07-03", "p1000": 49.0, "pfull": 99, "p52": 100},
}


def read_sql_retry(sql, conn_path=DB, tries=4, wait=3):
    """另一agent可能同時在讀DB;transient locked就重試。"""
    for i in range(tries):
        try:
            conn = sqlite3.connect(conn_path, timeout=30)
            df = pd.read_sql(sql, conn)
            conn.close()
            return df
        except sqlite3.OperationalError as e:
            if "locked" in str(e) and i < tries - 1:
                print(f"  (database locked,{wait}s後重試 {i + 1}/{tries})")
                time.sleep(wait)
            else:
                raise


def stat(x, lab):
    x = pd.Series(x).dropna()
    if len(x) < 15:
        print(f"    {lab}: n={len(x)}太少")
        return None
    print(f"    {lab}: 中位{x.median() * 100:+6.2f}% 均值{x.mean() * 100:+6.2f}% "
          f"勝率{(x > 0).mean() * 100:3.0f}% n={len(x):,}")
    return x


def loto_bootstrap_diff(sig_df, ctl_df, val_col, year_col, label, b=B_BOOT, seed=SEED):
    sig = sig_df.dropna(subset=[val_col])
    ctl = ctl_df.dropna(subset=[val_col])
    if len(sig) < 15 or len(ctl) < 15:
        print(f"      [{label}] 訊號組或對照組樣本不足(訊號n={len(sig)},對照n={len(ctl)}),略過差值LOTO/bootstrap")
        return
    years = sorted(set(sig[year_col].unique()) | set(ctl[year_col].unique()))
    if len(years) < 3:
        print(f"      [{label}] 年份數不足({len(years)}),略過差值LOTO/bootstrap")
        return
    rows = []
    for yr in years:
        s2 = sig[sig[year_col] != yr]
        c2 = ctl[ctl[year_col] != yr]
        if len(s2) >= 10 and len(c2) >= 10:
            rows.append((yr, s2[val_col].median() - c2[val_col].median()))
    if rows:
        rows.sort(key=lambda r: r[1])
        pos_ratio = sum(1 for _, d in rows if d > 0) / len(rows) * 100
        print(f"      差值LOTO最壞: 剔除{rows[0][0]}年後差={rows[0][1] * 100:+.2f}pp, "
              f"逐年差為正比例{pos_ratio:.0f}%(共{len(rows)}年可測)")
    rng = np.random.default_rng(seed)
    sig_groups = {yr: sig.loc[sig[year_col] == yr, val_col].values for yr in sig[year_col].unique()}
    ctl_groups = {yr: ctl.loc[ctl[year_col] == yr, val_col].values for yr in ctl[year_col].unique()}
    diffs = []
    for _ in range(b):
        pick = rng.choice(years, size=len(years), replace=True)
        sarr = np.concatenate([sig_groups[yr] for yr in pick if yr in sig_groups]) if any(
            yr in sig_groups for yr in pick) else np.array([])
        carr = np.concatenate([ctl_groups[yr] for yr in pick if yr in ctl_groups]) if any(
            yr in ctl_groups for yr in pick) else np.array([])
        if len(sarr) >= 10 and len(carr) >= 10:
            diffs.append(np.median(sarr) - np.median(carr))
    diffs = np.array(diffs)
    if len(diffs) < 200:
        print(f"      [{label}] 差值bootstrap有效樣本太少({len(diffs)}),結果不可靠")
        return
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    print(f"      差值cluster bootstrap(B={len(diffs)}): 差值中位數CI95=[{lo * 100:+.2f}, {hi * 100:+.2f}]pp, "
          f"P(差<=0)={(diffs <= 0).mean():.4f} P(差>=0)={(diffs >= 0).mean():.4f}")


def compute_v4(disp, stocks):
    """口徑同build_panic_liquidity_report.v4_v5_dated_curves,逐event_id回傳v4_net(%)。"""
    out = {}
    poison = disp.reason.astype(str).str.contains("人工管制")
    for ev_id, e in disp.iterrows():
        if poison.loc[ev_id]:
            continue  # 毒格剔除(現行DB=0筆no-op)
        g = stocks.get(e.code)
        if g is None:
            continue
        dts = g["date"].values
        n = len(g)
        s = int(np.searchsorted(dts, np.datetime64(e.start_date)))
        en = int(np.searchsorted(dts, np.datetime64(e.end_date), side="right") - 1)
        if s >= n or en <= s or en - s > 25 or en - s < 6 or en + 1 >= n:
            continue
        c_, o_ = g["close"].values, g["open"].values
        if o_[en + 1] <= 0 or c_[s + 2] <= 0:
            continue
        out[ev_id] = (o_[en + 1] / c_[s + 2] - 1.0) * 100 - V4_COST
    return out, int(poison.sum())


def compute_pre_turnover(disp, stocks):
    """規模代理: start_date前20交易日中位成交值(close*volume,不含窗內=無前視)。"""
    out = {}
    for ev_id, e in disp.iterrows():
        g = stocks.get(e.code)
        if g is None:
            continue
        dts = g["date"].values
        s = int(np.searchsorted(dts, np.datetime64(e.start_date)))
        if s < 5:
            continue
        w = g.iloc[max(0, s - 20):s]
        tv = (w["close"] * w["volume"]).median()
        if np.isfinite(tv) and tv > 0:
            out[ev_id] = float(tv)
    return out


def compute_tdcc_features(panel, tdcc):
    """每事件: cutoff=announce-3日曆日的最新快照 → p1000/P52/PFULL/d4w(百分位規約=(窗<=now)比例,窗含now)。"""
    series = {}
    for code, g in tdcc.groupby("code"):
        g = g.sort_values("date")
        series[code] = (g["date"].values.astype("datetime64[D]"), g["p1000"].values.astype(float))
    rows = []
    for r in panel.itertuples():
        rec = {"event_id": r.event_id, "snap_date": pd.NaT, "snap_lag": np.nan, "p1000": np.nan,
               "p52": np.nan, "p52_n": 0, "pfull": np.nan, "pfull_n": 0, "d4w": np.nan}
        sv = series.get(r.code)
        if sv is not None and pd.notna(r.announce_date):
            dts, vals = sv
            cutoff = np.datetime64((r.announce_date - pd.Timedelta(days=LAG_DAYS)).date())
            idx = int(np.searchsorted(dts, cutoff, side="right") - 1)
            if idx >= 0:
                lag = int((cutoff - dts[idx]).astype(int))
                rec["snap_date"] = pd.Timestamp(dts[idx])
                rec["snap_lag"] = lag
                if lag <= STALE_DAYS:
                    now = vals[idx]
                    rec["p1000"] = now
                    w = vals[max(0, idx - P52_WIN + 1):idx + 1]
                    rec["p52_n"] = len(w)
                    if len(w) >= P52_MIN:
                        rec["p52"] = (w <= now).mean() * 100
                    hist = vals[:idx + 1]
                    rec["pfull_n"] = len(hist)
                    if idx >= PFULL_MIN_PRIOR:
                        rec["pfull"] = (hist <= now).mean() * 100
                    if idx >= 4:
                        rec["d4w"] = now - vals[idx - 4]
        rows.append(rec)
    return pd.DataFrame(rows)


def sanity_pair(panel):
    print("=" * 70)
    print("SANITY CHECK: 軼事對(2454@2026-05-06 / 8261@2026-07-08)四個百分位重現(±1)")
    print("=" * 70)
    all_ok = True
    for (code, ann), exp in SANITY.items():
        hit = panel[(panel.code == code) & (panel.announce_date == ann)]
        if len(hit) != 1:
            print(f"  !! {code}@{ann} 找到{len(hit)}筆(預期1),FAIL")
            all_ok = False
            continue
        r = hit.iloc[0]
        ok = (str(r.snap_date.date()) == exp["snap"] and abs(r.p1000 - exp["p1000"]) <= 0.1 and
              abs(r.pfull - exp["pfull"]) <= 1 and abs(r.p52 - exp["p52"]) <= 1)
        print(f"  {code}@{ann}: snap={r.snap_date.date()}(exp {exp['snap']}) p1000={r.p1000:.1f}(exp {exp['p1000']}) "
              f"PFULL={r.pfull:.1f}(exp {exp['pfull']}) P52={r.p52:.1f}(exp {exp['p52']}) "
              f"=> {'PASS' if ok else 'FAIL'}")
        all_ok = all_ok and ok
    if all_ok:
        print("  >> PASS: 管線重現軼事對,可跑全母體。\n")
    else:
        print("  >> FAIL: 特徵管線與軼事現場不一致,下方結果不可信任!\n")
    return all_ok


def bucket_table(pop, bcol, order, vcols, title):
    print(f"  -- {title} --")
    med_track = {v: [] for v in vcols}
    for b in order:
        sub = pop[pop[bcol] == b]
        parts = [f"{b}: n={len(sub):4d}"]
        for v in vcols:
            x = sub[v].dropna()
            if len(x) >= 10:
                parts.append(f"{v} 中位{x.median() * 100:+6.2f}%/勝{(x > 0).mean() * 100:3.0f}%(n={len(x)})")
                med_track[v].append(x.median())
            else:
                parts.append(f"{v} n={len(x)}太少")
                med_track[v].append(np.nan)
        print("    " + "  ".join(parts))
    for v in vcols:
        m = [x for x in med_track[v] if pd.notna(x)]
        if len(m) == len(order):
            inc = all(m[i] <= m[i + 1] for i in range(len(m) - 1))
            dec = all(m[i] >= m[i + 1] for i in range(len(m) - 1))
            tag = "遞增" if inc else ("遞減" if dec else "非單調")
            print(f"    {v} 中位數梯度: {tag} ({' -> '.join(f'{x * 100:+.2f}' for x in m)})")


def main():
    disp = read_sql_retry("SELECT * FROM disposition")
    px = read_sql_retry("SELECT code, date, open, close, volume FROM fm_daily_price ORDER BY code, date")
    tdcc = read_sql_retry("SELECT code, date, p1000 FROM tdcc_weekly ORDER BY code, date")
    for c in ("announce_date", "start_date", "end_date"):
        disp[c] = pd.to_datetime(disp[c], errors="coerce")
    disp = disp.dropna(subset=["start_date", "end_date"]).reset_index(drop=True)  # event_id口徑=exit_fade panel
    px["date"] = pd.to_datetime(px["date"])
    tdcc["date"] = pd.to_datetime(tdcc["date"])
    stocks = {c: g.sort_values("date").reset_index(drop=True) for c, g in px.groupby("code")}

    panel = pd.read_pickle(PANEL_IN)
    chk = panel[["event_id", "code", "start_date"]].merge(
        disp[["code", "start_date"]].reset_index().rename(columns={"index": "event_id"}),
        on="event_id", suffixes=("_p", "_d"))
    mism = ((chk.code_p != chk.code_d) | (chk.start_date_p != chk.start_date_d)).sum()
    print(f"事件面板: {len(panel):,}筆(重用{PANEL_IN}); event_id對齊disposition口徑檢查: 不一致={mism}筆"
          f"{'(PASS)' if mism == 0 else ' !!口徑錯位,中止'}")
    if mism:
        sys.exit(1)
    panel = panel.merge(disp[["announce_date"]].reset_index().rename(columns={"index": "event_id"}),
                        on="event_id", how="left")

    v4, n_poison = compute_v4(disp, stocks)
    panel["v4_net"] = panel.event_id.map(v4)
    panel["v4_valid"] = panel.v4_net.notna()
    print(f"V4交易(第3日收盤買→出關開盤出,-{V4_COST}%,6<=窗<=25,口徑=build_panic_liquidity_report): "
          f"可交易n={panel.v4_valid.sum():,}; reason含人工管制剔除={n_poison}筆(預期0=no-op存證)")

    panel["pre_turnover"] = panel.event_id.map(compute_pre_turnover(disp, stocks))

    feat = compute_tdcc_features(panel, tdcc)
    panel = panel.merge(feat, on="event_id", how="left")
    panel.to_pickle(PANEL_OUT)
    print(f"特徵面板存 {PANEL_OUT}\n")

    ok = sanity_pair(panel)
    if not ok:
        print("!! sanity FAIL,僅輸出覆蓋統計,不跑分析")

    # ================= 覆蓋/存活偏差 =================
    print("=" * 70)
    print("TDCC覆蓋與存活偏差診斷")
    print("=" * 70)
    tdcc_codes = set(tdcc.code.unique())
    panel["in_tdcc"] = panel.code.isin(tdcc_codes)
    n_in = panel.in_tdcc.sum()
    print(f"  事件層: {len(panel):,}事件中 code在tdcc_weekly={n_in:,}({n_in / len(panel) * 100:.1f}%); "
          f"P52有效={panel.p52.notna().sum():,} PFULL有效={panel.pfull.notna().sum():,} "
          f"d4w有效={panel.d4w.notna().sum():,}")
    stale = panel[panel.in_tdcc & panel.snap_lag.notna() & (panel.snap_lag > STALE_DAYS)]
    short52 = panel[panel.p52.notna() & (panel.p52_n < P52_WIN)]
    print(f"  作廢原因: 快照過期(>{STALE_DAYS}天)={len(stale)}筆; "
          f"P52窗不足52快照但>={P52_MIN}仍納入={len(short52)}筆(操作化選擇,已存證); "
          f"快照lag中位={panel.snap_lag.median():.0f}天")
    print("  逐年配對率(事件年=start年):")
    for y, g in panel.groupby("y"):
        print(f"    {y}: 事件n={len(g):4d} code在tdcc={g.in_tdcc.mean() * 100:5.1f}% "
              f"P52有效={g.p52.notna().mean() * 100:5.1f}% PFULL有效={g.pfull.notna().mean() * 100:5.1f}%")
    last_snap = tdcc.groupby("code").date.max()
    gmax = tdcc.date.max()
    n_ended = (last_snap < gmax - pd.Timedelta(days=60)).sum()
    print(f"  tdcc宇宙: {len(tdcc_codes):,}檔; 最後快照早於全域最新({gmax.date()})60天以上={n_ended}檔 "
          f"({'≈0=宇宙來自現行清單,已下市股缺席=存活偏差存在,早年配對率應偏低' if n_ended < 20 else '有歷史退場碼,存活偏差較輕'})")
    missing = panel[~panel.in_tdcc]
    if len(missing):
        yr_miss = missing.groupby("y").size()
        print("  缺碼事件的年份分布: " + "  ".join(f"{y}={n}" for y, n in yr_miss.items()))
    print()

    if not ok:
        sys.exit(1)

    # 高位階旗標/分箱(固定切點,百分位本身已標準化)
    panel["q52"] = pd.cut(panel.p52, bins=[-0.01, 25, 50, 75, 100.01],
                          labels=["Q1", "Q2", "Q3", "Q4"], right=False)
    panel["qfull"] = pd.cut(panel.pfull, bins=[-0.01, 25, 50, 75, 100.01],
                            labels=["Q1", "Q2", "Q3", "Q4"], right=False)
    panel["hi52"] = panel.p52 >= HI_TH
    panel["hifull"] = panel.pfull >= HI_TH
    panel["v4d"] = panel.v4_net / 100  # stat()吃小數

    evc = panel[~panel.truncated].copy()  # post端只用完整窗(v4_valid自帶en+1存在=不受截斷影響)
    QS = ["Q1", "Q2", "Q3", "Q4"]

    for mm in ["5", "20"]:
        pop = panel[(panel.match_min == mm) & panel.v4_valid & panel.p52.notna()].copy()
        popc = evc[(evc.match_min == mm) & evc.p52.notna()].copy()
        # d4w三分位(rank法處理0值大量並列,分層內自算)
        for df_ in (pop, popc):
            rk = df_.d4w.rank(pct=True)
            df_["d4w_ter"] = pd.cut(rk, bins=[-0.01, 1 / 3, 2 / 3, 1.01], labels=["T1低", "T2中", "T3高"])
        print("#" * 70)
        print(f"## match_min={mm}  V4可交易且P52有效 n={len(pop):,} / post端(不截斷)n={len(popc):,}")
        if len(pop):
            e = pop.d4w.dropna()
            print(f"##   d4w三分位切點(參考): {e.quantile(1 / 3):+.2f} / {e.quantile(2 / 3):+.2f} (pp of p1000)")
        print("#" * 70)

        print("\n== 分析1: V4條件化(主戰場) ==")
        bucket_table(pop, "q52", QS, ["v4d"], "P52四分位(固定切點25/50/75)")
        bucket_table(pop[pop.pfull.notna()], "qfull", QS, ["v4d"], "PFULL四分位(要求>=52先前快照)")
        bucket_table(pop[pop.d4w.notna()], "d4w_ter", ["T1低", "T2中", "T3高"], ["v4d"], "d4w三分位(4週大戶流向)")
        print("  -- 高vs其餘(二元, LOTO+年群bootstrap) --")
        for lab, hi_mask in (("P52>=80", pop.hi52), ("PFULL>=80", pop.hifull & pop.pfull.notna()),
                             ("d4w最高三分位", pop.d4w_ter == "T3高")):
            hi, rest = pop[hi_mask], pop[~hi_mask]
            a = stat(hi.v4d, f"{lab:12s} 高組")
            b = stat(rest.v4d, f"{lab:12s} 其餘")
            if a is not None and b is not None:
                print(f"      中位差(高-餘): {(a.median() - b.median()) * 100:+.2f}pp")
            loto_bootstrap_diff(hi, rest, "v4d", "y", f"{mm}分盤V4 {lab}高-餘")

        print("\n== 分析2: 出關後條件化(post5/10/20,窗末收盤起算) ==")
        pk = [f"post{k}" for k in POST_KS]
        bucket_table(popc, "q52", QS, pk, "P52四分位")
        bucket_table(popc[popc.pfull.notna()], "qfull", QS, pk, "PFULL四分位")
        bucket_table(popc[popc.d4w.notna()], "d4w_ter", ["T1低", "T2中", "T3高"], pk, "d4w三分位")
        print("  -- 高vs其餘(二元, LOTO+年群bootstrap) --")
        for lab, hi_mask in (("P52>=80", popc.hi52), ("PFULL>=80", popc.hifull & popc.pfull.notna()),
                             ("d4w最高三分位", popc.d4w_ter == "T3高")):
            hi, rest = popc[hi_mask], popc[~hi_mask]
            for k in POST_KS:
                a = stat(hi[f"post{k}"], f"{lab} 高組 post{k}")
                b = stat(rest[f"post{k}"], f"{lab} 其餘 post{k}")
                if a is not None and b is not None:
                    print(f"      中位差(高-餘): {(a.median() - b.median()) * 100:+.2f}pp")
                loto_bootstrap_diff(hi, rest, f"post{k}", "y", f"{mm}分盤post{k} {lab}高-餘")

        print("\n== 分析3: 與G1-G4型態組交互(headline grp_r8_a; 組內P52中位切,小n只報不bootstrap) ==")
        for grp in ["G1", "G3"]:
            gg = popc[popc[HL_COL] == grp]
            if len(gg) < 10:
                print(f"  {grp}: n={len(gg)}太少,略過")
                continue
            med = gg.p52.median()
            hi, lo = gg[gg.p52 >= med], gg[gg.p52 < med]
            print(f"  {grp}(n={len(gg)},組內P52中位={med:.0f}切): 高組n={len(hi)} 低組n={len(lo)}")
            for k in POST_KS:
                a = stat(hi[f"post{k}"], f"  {grp} P52高 post{k}")
                b = stat(lo[f"post{k}"], f"  {grp} P52低 post{k}")
                if a is not None and b is not None:
                    print(f"      中位差(高-低): {(a.median() - b.median()) * 100:+.2f}pp")
                if len(hi) >= 20 and len(lo) >= 20:
                    loto_bootstrap_diff(hi, lo, f"post{k}", "y", f"{mm}分盤{grp}內P52高-低 post{k}")

        print("\n== 分析4: 機制一致性(故事預測: 高位階∧d4w>=0(大戶沒跑)應最強) ==")
        sub = pop[pop.d4w.notna()].copy()
        sub["cell"] = np.where(sub.hi52, "高位階", "低位階") + np.where(sub.d4w >= 0, "∧沒跑", "∧在跑")
        for cell in ["高位階∧沒跑", "高位階∧在跑", "低位階∧沒跑", "低位階∧在跑"]:
            cc = sub[sub.cell == cell]
            stat(cc.v4d, f"V4 {cell}")
        subc = popc[popc.d4w.notna()].copy()
        subc["cell"] = np.where(subc.hi52, "高位階", "低位階") + np.where(subc.d4w >= 0, "∧沒跑", "∧在跑")
        for cell in ["高位階∧沒跑", "高位階∧在跑", "低位階∧沒跑", "低位階∧在跑"]:
            cc = subc[subc.cell == cell]
            stat(cc.post10, f"post10 {cell}")
        hh = sub[sub.cell == "高位階∧沒跑"]
        hall = sub[sub.hi52]
        if len(hh) >= 15 and len(hall) >= 15:
            print(f"    組合(高∧沒跑)V4中位 vs 單看高位階: "
                  f"{hh.v4d.median() * 100:+.2f}% vs {hall.v4d.median() * 100:+.2f}% "
                  f"(故事預測前者更好,差{(hh.v4d.median() - hall.v4d.median()) * 100:+.2f}pp)")

        print("\n== 分析5: 冗餘檢查(P52是不是規模換皮; 規模代理=處置前20日中位成交值) ==")
        rc = pop.dropna(subset=["pre_turnover"])
        if len(rc) >= 30:
            logtv = np.log10(rc.pre_turnover)
            for f in ["p52", "pfull", "p1000", "d4w"]:
                x = rc[[f]].join(logtv.rename("logtv")).dropna()
                if len(x) >= 30:
                    print(f"    Spearman({f}, log成交值) = {x[f].corr(x['logtv'], method='spearman'):+.3f} (n={len(x)})")
            rc = rc.copy()
            rc["size_ter"] = pd.cut(logtv.rank(pct=True), bins=[-0.01, 1 / 3, 2 / 3, 1.01],
                                    labels=["小", "中", "大"])
            print("    成交值三分位內 P52>=80高-餘 V4中位差(若效應是規模換皮,控規模後應消失):")
            for st in ["小", "中", "大"]:
                cc = rc[rc.size_ter == st]
                hi, rest = cc[cc.hi52], cc[~cc.hi52]
                if len(hi) >= 15 and len(rest) >= 15:
                    print(f"      {st}: 高{hi.v4d.median() * 100:+.2f}%(n={len(hi)}) "
                          f"餘{rest.v4d.median() * 100:+.2f}%(n={len(rest)}) "
                          f"差{(hi.v4d.median() - rest.v4d.median()) * 100:+.2f}pp")
                else:
                    print(f"      {st}: n不足(高{len(hi)}/餘{len(rest)})")
        print()


if __name__ == "__main__":
    main()
