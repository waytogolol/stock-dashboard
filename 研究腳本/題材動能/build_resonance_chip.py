# -*- coding: utf-8 -*-
"""共振 × 外資20日位階(籌碼A1配對)條件化研究(2026-07-24,預註冊)
假說(使用者選定配對): 已驗證的籌碼A1規則(中小型突破+外資20日累計位階>=80,持4週=+3~6pp/4週,
「小票外資腳印=informed money」)應可轉移到共振事件——共振題材成員股中,事件週外資位階高(>=80)者,
在共振house持有期(8週,兼看4週)應優於位階低者。機制: 動能突破家族(共振)×知情資金家族(外資布局)
=兩層獨立確認,正是本專案在籌碼A1本身驗證過的多層確認設計哲學。先驗有利,但誠實檢定。

關鍵覆蓋警告(先量化再分析): inst_flow只有上市(TWSE,v1從未涵蓋上櫃),共振宇宙偏中小型且含大量上櫃
(其最佳階梯變體就是OTC指數!);inst_flow始於2022-01(位階需240日窗min120=>首個有效值~2022-06)
=> 有效檢定窗2022-2026(~4.5年),共振2005-2021事件全數落出,且2025-26正是共振最熱的regime
=> 檢定窗regime偏斜,結論必須註記;覆蓋率<~50%或嚴重偏斜=部分宇宙結果,要醒目標示,
並檢查有位階vs無位階成員的基線fwd是否本來就不同(選擇效應)。

設計(預註冊):
- 事件母體: tmp_resonance_theme_events.pkl取episode_first=True(house主事件口徑=每波第一週),
  逐列對齊tmp_resonance_theme_episodes.pkl檢查;成員前向報酬fwd4/fwd8(+fwd12存panel)自算,
  口徑完全比照build_resonance_theme.fwd_ret(tmp_resonance_weekly_panel.pkl週收盤,dropna後
  位置索引pos+k,收盤對收盤,未扣成本),並以「逐episode成員平均==儲存的fwd8」全量複驗管線
- 特徵: 外資位階規約=canonical S4(封存/研究腳本歸檔/tmp_portfolio_report.py逐行照抄):
  code過濾^[1-9]\\d{3}$ → pivot foreign_net → reindex(closeD.index) → rolling(20,min10).sum()
  → rolling(240,min120).rank(pct=True) → resample('W-FRI').last() → 事件週取值×100;高=>=80(house慣例)
- sanity: 對dashboard chip徽章(export_html.py data['chip'],chip_date=2026-07-17)重現f值±2;券資比s值同
- 分析(兩個聚合層——S5教訓=個股級vs題材級口徑會改組合結論,兩層都報):
  ①成員級: (episode,member)配valid位階,>=80 vs 其餘,fwd4/fwd8中位/均值/勝率+四分位梯度
    (固定切點25/50/75,單調性)+逐年符號(僅~5年,LOTO薄)+LOTO+年群bootstrap(B=10000,seed=42);
    (code,week)去重複驗(同碼同週可掛多題材)
  ②題材事件級(house口徑): 同episode內>=80成員均值-<80成員均值(事件內對照,完全控制題材/時點),
    差值中位+單樣本年群bootstrap+LOTO;補充: 有>=80成員的事件vs全無的事件(事件級fwd,題材選擇角度)
  ③次要(便宜順做): margin_flow.short_fin_ratio位階(rolling240 rank,無20日sum,比照chip徽章s),同切分
- A1重疊: >=80成員中事件週週漲>10%(近似A1;rank51-300閘門因rankings表2025前歷史缺無法重建,已註記
  限制)的比例 => 這個配對是抓新股票,還是重貼A1在共振窗內的名單
用法: python -X utf8 build_resonance_chip.py  (Windows終端機cp950易炸)
"""
import sqlite3
import sys
import time

import numpy as np
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DB = "capital_flow.db"
EV_PKL = "tmp_resonance_theme_events.pkl"
EP_PKL = "tmp_resonance_theme_episodes.pkl"
WK_PKL = "tmp_resonance_weekly_panel.pkl"
PANEL_OUT = "tmp_resonance_chip_panel.pkl"
HI_TH = 80.0
B_BOOT = 10000
SEED = 42
CHIP_DATE = "2026-07-17"                                   # dashboard chip_date(export_html.py)
SANITY_F = {"2603": 92, "2324": 65, "2727": 32, "8462": 100}  # dashboard.html data['chip'][code]['f']
SANITY_S = {"2603": 37, "2324": 30}                           # data['chip'][code]['s']
A1_WRET = 10.0                                             # A1近似: 事件週週漲>10%


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
    print(f"    {lab}: 中位{x.median():+6.2f}% 均值{x.mean():+6.2f}% "
          f"勝率{(x > 0).mean() * 100:3.0f}% n={len(x):,}")
    return x


def loto_bootstrap_diff(sig_df, ctl_df, val_col, year_col, label, b=B_BOOT, seed=SEED):
    """兩組中位差: 逐年LOTO+年群cluster bootstrap(值單位=%,印pp)。比照build_disposition_tdcc.py。"""
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
        print(f"      差值LOTO最壞: 剔除{rows[0][0]}年後差={rows[0][1]:+.2f}pp, "
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
    print(f"      差值cluster bootstrap(B={len(diffs)}): 差值中位數CI95=[{lo:+.2f}, {hi:+.2f}]pp, "
          f"P(差<=0)={(diffs <= 0).mean():.4f} P(差>=0)={(diffs >= 0).mean():.4f}")


def loto_bootstrap_one(df, val_col, year_col, label, b=B_BOOT, seed=SEED):
    """單樣本中位數vs 0(事件內差值用): 逐年LOTO+年群cluster bootstrap(值單位=pp)。"""
    d = df.dropna(subset=[val_col])
    if len(d) < 15:
        print(f"      [{label}] n={len(d)}太少,略過LOTO/bootstrap")
        return
    years = sorted(d[year_col].unique())
    if len(years) < 3:
        print(f"      [{label}] 年份數不足({len(years)}),略過LOTO/bootstrap")
        return
    rows = []
    for yr in years:
        sub = d[d[year_col] != yr]
        if len(sub) >= 10:
            rows.append((yr, sub[val_col].median()))
    if rows:
        rows.sort(key=lambda r: r[1])
        pos_ratio = sum(1 for _, m in rows if m > 0) / len(rows) * 100
        print(f"      LOTO最壞: 剔除{rows[0][0]}年後中位={rows[0][1]:+.2f}pp, "
              f"為正比例{pos_ratio:.0f}%(共{len(rows)}年可測)")
    rng = np.random.default_rng(seed)
    groups = {yr: d.loc[d[year_col] == yr, val_col].values for yr in years}
    meds = []
    for _ in range(b):
        pick = rng.choice(years, size=len(years), replace=True)
        arr = np.concatenate([groups[yr] for yr in pick])
        if len(arr) >= 10:
            meds.append(np.median(arr))
    meds = np.array(meds)
    lo, hi = np.percentile(meds, [2.5, 97.5])
    print(f"      cluster bootstrap(年群,B={len(meds)}): 中位數CI95=[{lo:+.2f}, {hi:+.2f}]pp, "
          f"P(<=0)={(meds <= 0).mean():.4f}")


def bucket_table(pop, bcol, order, vcols, title):
    """四分位/分箱表+單調梯度(值單位=%)。比照build_disposition_tdcc.py。"""
    print(f"  -- {title} --")
    med_track = {v: [] for v in vcols}
    for b in order:
        sub = pop[pop[bcol] == b]
        parts = [f"{b}: n={len(sub):4d}"]
        for v in vcols:
            x = sub[v].dropna()
            if len(x) >= 10:
                parts.append(f"{v} 中位{x.median():+6.2f}%/勝{(x > 0).mean() * 100:3.0f}%(n={len(x)})")
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
            print(f"    {v} 中位數梯度: {tag} ({' -> '.join(f'{x:+.2f}' for x in m)})")


def sanity_chip(fpct_daily, spct_daily):
    """對dashboard chip徽章重現位階(±2點,任務書規格)。"""
    print("=" * 70)
    print(f"SANITY CHECK 1: dashboard chip徽章重現(chip_date={CHIP_DATE},容差±2)")
    print("=" * 70)
    ts = pd.Timestamp(CHIP_DATE)
    all_ok = True
    for code, exp in SANITY_F.items():
        try:
            v = fpct_daily.at[ts, code] * 100
        except KeyError:
            v = np.nan
        ok = pd.notna(v) and abs(v - exp) <= 2
        print(f"  外資f {code}: 算得{v:6.1f} vs 徽章{exp:3d} => {'PASS' if ok else 'FAIL'}")
        all_ok = all_ok and ok
    for code, exp in SANITY_S.items():
        try:
            v = spct_daily.at[ts, code] * 100
        except KeyError:
            v = np.nan
        ok = pd.notna(v) and abs(v - exp) <= 2
        print(f"  券資s {code}: 算得{v:6.1f} vs 徽章{exp:3d} => {'PASS' if ok else 'FAIL'}")
        all_ok = all_ok and ok
    print(f"  >> {'PASS: 位階規約與dashboard一致' if all_ok else 'FAIL: 位階規約重現失敗,下方結果不可信任!'}\n")
    return all_ok


def main():
    # ---------- 資料 ----------
    fl = read_sql_retry("SELECT date, code, foreign_net, close FROM inst_flow")
    mg = read_sql_retry("SELECT date, code, short_fin_ratio FROM margin_flow")
    fl = fl[fl.code.str.match(r"^[1-9]\d{3}$")]          # canonical S4逐行照抄
    fl["date"] = pd.to_datetime(fl.date)
    mg["date"] = pd.to_datetime(mg.date)
    closeD = fl.pivot_table(index="date", columns="code", values="close")
    fpct = (fl.pivot_table(index="date", columns="code", values="foreign_net")
            .reindex(closeD.index).rolling(20, min_periods=10).sum()
            .rolling(240, min_periods=120).rank(pct=True))
    fp_w = fpct.resample("W-FRI").last() * 100
    spct = (mg.pivot_table(index="date", columns="code", values="short_fin_ratio")
            .rolling(240, min_periods=120).rank(pct=True))    # chip徽章s口徑(無20日sum)
    sp_w = spct.resample("W-FRI").last() * 100
    first_valid = fpct.dropna(how="all").index.min()
    print(f"inst_flow: {fl.date.min().date()}~{fl.date.max().date()} {fl.code.nunique()}檔(上市only,4碼過濾後); "
          f"外資位階首個有效日={first_valid.date()}(240日窗min120)")

    ok = sanity_chip(fpct, spct)

    # ---------- 事件母體 ----------
    ev = pd.read_pickle(EV_PKL)
    ep = pd.read_pickle(EP_PKL)
    ev["week"] = pd.to_datetime(ev.week)
    epi = ev[ev.episode_first].reset_index(drop=True)
    align = (len(epi) == len(ep)
             and (epi.theme.values == ep.theme.values).all()
             and (epi.week.values == ep.week.values).all()
             and all(list(a) == list(b) for a, b in zip(epi.members, ep.members)))
    print(f"事件母體: events={len(ev):,}筆(theme×week) / episode_first={len(epi):,}筆(house主事件口徑); "
          f"episodes.pkl逐列對齊={'PASS' if align else 'FAIL,中止'}")
    if not align:
        sys.exit(1)
    ex = epi.iloc[0]
    print(f"  抽查事件: {ex.theme} @ {ex.week.date()} n={ex.n_members} members={ex.members}")

    # ---------- 成員級前向報酬(口徑=build_resonance_theme.fwd_ret) ----------
    wkp = pd.read_pickle(WK_PKL)
    ser = {}

    def wseries(code):
        if code not in ser:
            ser[code] = wkp[code].dropna() if code in wkp.columns else None
        return ser[code]

    rows = []
    for r in epi.itertuples():
        for c in r.members:
            rec = {"theme": r.theme, "week": r.week, "n_members": r.n_members, "code": c,
                   "fwd4": np.nan, "fwd8": np.nan, "fwd12": np.nan, "wret0": np.nan}
            s = wseries(c)
            if s is not None and len(s):
                pos = s.index.searchsorted(r.week)
                if pos < len(s) and s.index[pos] == r.week:
                    p0 = s.iloc[pos]
                    if p0 > 0:
                        for k in (4, 8, 12):
                            j = pos + k
                            if j < len(s) and s.iloc[j] > 0:
                                rec[f"fwd{k}"] = (s.iloc[j] / p0 - 1) * 100
                        if pos >= 1 and s.iloc[pos - 1] > 0:
                            rec["wret0"] = (p0 / s.iloc[pos - 1] - 1) * 100
            rows.append(rec)
    pan = pd.DataFrame(rows)
    pan["y"] = pan.week.dt.year

    # 管線複驗: 逐episode成員平均fwd8 == 儲存的ep.fwd8(全量)
    rep = pan.groupby(["theme", "week"]).fwd8.mean()
    key = pd.MultiIndex.from_frame(ep[["theme", "week"]])
    stored = pd.Series(ep.fwd8.values, index=key)
    both = rep.reindex(stored.index)
    mask = stored.notna() & both.notna()
    maxdiff = (both[mask] - stored[mask]).abs().max()
    nan_mismatch = int((stored.notna() != both.notna()).sum())
    print(f"SANITY CHECK 2: 成員fwd自算複驗(episode均值 vs 儲存fwd8): "
          f"可比{mask.sum():,}筆 max|diff|={maxdiff:.2e} NaN錯位={nan_mismatch} "
          f"=> {'PASS' if maxdiff < 1e-6 and nan_mismatch == 0 else 'FAIL,前向報酬口徑沒對齊!'}")
    if not (maxdiff < 1e-6 and nan_mismatch == 0):
        sys.exit(1)

    # ---------- 特徵掛載 ----------
    def attach(panel, wide, col):
        vals = np.full(len(panel), np.nan)
        m = panel.week.isin(wide.index).values & panel.code.isin(wide.columns).values
        sub = panel[m]
        vals[m] = wide.to_numpy()[wide.index.get_indexer(sub.week), wide.columns.get_indexer(sub.code)]
        panel[col] = vals

    attach(pan, fp_w, "fpc")
    attach(pan, sp_w, "spc")
    pan["in_inst"] = pan.code.isin(set(fl.code))
    pan.to_pickle(PANEL_OUT)
    print(f"成員級面板存 {PANEL_OUT} ({len(pan):,}筆member-event)\n")

    if not ok:
        print("!! chip sanity FAIL,僅輸出覆蓋統計,不跑分析")

    # ---------- 覆蓋/選擇效應(先量化再分析) ----------
    print("=" * 70)
    print("覆蓋診斷(inst_flow=上市only+2022起,共振宇宙含上櫃 => 部分宇宙檢定)")
    print("=" * 70)
    cov = pan[pan.week >= "2022-01-01"].copy()
    n_dupe = len(cov) - cov.drop_duplicates(["code", "week"]).shape[0]
    print(f"  member-event全史={len(pan):,}筆 / 2022+={len(cov):,}筆 "
          f"(同碼同週掛多題材重複={n_dupe}筆) / 2022+有效外資位階={cov.fpc.notna().sum():,}筆"
          f"({cov.fpc.notna().mean() * 100:.1f}%) 券資位階={cov.spc.notna().sum():,}筆")
    print("  逐年: n=member-event / 上市(在inst_flow)% / 外資位階有效% / 券資位階有效%")
    for y, g in cov.groupby("y"):
        print(f"    {y}: n={len(g):5,d}  上市{g.in_inst.mean() * 100:5.1f}%  "
              f"f有效{g.fpc.notna().mean() * 100:5.1f}%  s有效{g.spc.notna().mean() * 100:5.1f}%")
    miss_split = cov[~cov.fpc.notna()]
    n_otc = (~miss_split.in_inst).sum()
    print(f"  無f位階的{len(miss_split):,}筆中: 不在inst_flow(上櫃/興櫃等)={n_otc:,} / "
          f"在inst_flow但窗不足或當週無值={len(miss_split) - n_otc:,}")
    print("  選擇效應檢查(2022+,有f位階 vs 無f位階成員的基線前向報酬——若差很多,下面高低位階比較")
    print("  只能代表上市子宇宙,不能外推全共振宇宙):")
    for k in (4, 8):
        a = stat(cov[cov.fpc.notna()][f"fwd{k}"], f"fwd{k} 有位階(≈上市)")
        b = stat(cov[cov.fpc.isna()][f"fwd{k}"], f"fwd{k} 無位階(≈上櫃)")
        if a is not None and b is not None:
            print(f"      基線中位差(有-無): {(a.median() - b.median()):+.2f}pp")
    print()

    if not ok:
        sys.exit(1)

    # ---------- 分析1: 成員級 ----------
    pop = pan[pan.fpc.notna()].copy()
    pop["hi"] = pop.fpc >= HI_TH
    pop["q"] = pd.cut(pop.fpc, bins=[-0.01, 25, 50, 75, 100.01], labels=["Q1", "Q2", "Q3", "Q4"], right=False)
    print("#" * 70)
    print(f"## 分析1: 成員級 (episode,member)有效f位階 n={len(pop):,} "
          f"({pop.week.min().date()}~{pop.week.max().date()}, {pop.y.nunique()}個年份)")
    print("#" * 70)
    bucket_table(pop, "q", ["Q1", "Q2", "Q3", "Q4"], ["fwd4", "fwd8"], "外資位階四分位(固定切點25/50/75)")
    print("  -- 高(>=80) vs 其餘(二元, LOTO+年群bootstrap) --")
    hi, rest = pop[pop.hi], pop[~pop.hi]
    for k in (4, 8):
        a = stat(hi[f"fwd{k}"], f"fwd{k} f>=80")
        b = stat(rest[f"fwd{k}"], f"fwd{k} 其餘")
        if a is not None and b is not None:
            print(f"      中位差(高-餘): {(a.median() - b.median()):+.2f}pp")
        loto_bootstrap_diff(hi, rest, f"fwd{k}", "y", f"成員級fwd{k} f>=80高-餘")
    print("  -- 逐年符號(高-餘中位差,LOTO僅~5年故逐年攤開) --")
    for y, g in pop.groupby("y"):
        h, r_ = g[g.hi], g[~g.hi]
        for k in (4, 8):
            hv, rv = h[f"fwd{k}"].dropna(), r_[f"fwd{k}"].dropna()
            if len(hv) >= 5 and len(rv) >= 5:
                print(f"    {y} fwd{k}: 高{hv.median():+6.2f}%(n={len(hv):3d}) "
                      f"餘{rv.median():+6.2f}%(n={len(rv):4d}) 差{(hv.median() - rv.median()):+6.2f}pp")
            else:
                print(f"    {y} fwd{k}: n不足(高{len(hv)}/餘{len(rv)})")
    dd = pop.sort_values(["code", "week", "theme"]).drop_duplicates(["code", "week"])
    print(f"  -- 去重複驗((code,week)去重,n={len(dd):,}) --")
    hi2, rest2 = dd[dd.hi], dd[~dd.hi]
    for k in (4, 8):
        a = stat(hi2[f"fwd{k}"], f"fwd{k} f>=80")
        b = stat(rest2[f"fwd{k}"], f"fwd{k} 其餘")
        if a is not None and b is not None:
            print(f"      中位差(高-餘): {(a.median() - b.median()):+.2f}pp")
        loto_bootstrap_diff(hi2, rest2, f"fwd{k}", "y", f"去重成員級fwd{k}")
    print()

    # ---------- 分析2: 題材事件級(house口徑) ----------
    print("#" * 70)
    print("## 分析2: 題材事件級(事件內對照=同episode內 f>=80成員均值 - <80成員均值,完全控制題材/時點)")
    print("#" * 70)
    ev_rows = []
    for (theme, week), g in pop.groupby(["theme", "week"]):
        rec = {"theme": theme, "week": week, "y": week.year,
               "n_hi": int(g.hi.sum()), "n_lo": int((~g.hi).sum())}
        for k in (4, 8):
            hv = g.loc[g.hi, f"fwd{k}"].dropna()
            lv = g.loc[~g.hi, f"fwd{k}"].dropna()
            rec[f"d{k}"] = hv.mean() - lv.mean() if len(hv) and len(lv) else np.nan
            rec[f"ev_fwd{k}"] = g[f"fwd{k}"].mean()
        ev_rows.append(rec)
    evl = pd.DataFrame(ev_rows)
    n_events_cov = len(evl)
    n_within = evl.d8.notna().sum()
    print(f"  2022+有>=1有效位階成員的事件: {n_events_cov} / 其中事件內同時有高+低成員(可做內對照,fwd8): {n_within}")
    for k in (4, 8):
        x = stat(evl[f"d{k}"], f"事件內差d{k}(高成員均值-低成員均值)")
        if x is not None:
            print(f"      差>0的事件比例: {(x > 0).mean() * 100:.0f}%")
        loto_bootstrap_one(evl, f"d{k}", "y", f"事件內差d{k}")
    print("  -- 補充(題材選擇角度): 有f>=80成員的事件 vs 全無的事件(事件級等權fwd) --")
    has_hi, no_hi = evl[evl.n_hi > 0], evl[evl.n_hi == 0]
    for k in (4, 8):
        a = stat(has_hi[f"ev_fwd{k}"], f"ev_fwd{k} 有高位階成員")
        b = stat(no_hi[f"ev_fwd{k}"], f"ev_fwd{k} 全無")
        if a is not None and b is not None:
            print(f"      中位差: {(a.median() - b.median()):+.2f}pp")
        loto_bootstrap_diff(has_hi, no_hi, f"ev_fwd{k}", "y", f"事件級fwd{k} 有高-全無")
    print()

    # ---------- 分析3: 次要=券資比位階(chip徽章s口徑) ----------
    print("#" * 70)
    print("## 分析3(次要): 券資比位階同切分(margin_flow.short_fin_ratio,rolling240 rank,上市only)")
    print("#" * 70)
    pop_s = pan[pan.spc.notna()].copy()
    pop_s["hi_s"] = pop_s.spc >= HI_TH
    pop_s["q"] = pd.cut(pop_s.spc, bins=[-0.01, 25, 50, 75, 100.01], labels=["Q1", "Q2", "Q3", "Q4"], right=False)
    print(f"  n={len(pop_s):,}")
    bucket_table(pop_s, "q", ["Q1", "Q2", "Q3", "Q4"], ["fwd4", "fwd8"], "券資比位階四分位")
    hi_s, rest_s = pop_s[pop_s.hi_s], pop_s[~pop_s.hi_s]
    for k in (4, 8):
        a = stat(hi_s[f"fwd{k}"], f"fwd{k} s>=80")
        b = stat(rest_s[f"fwd{k}"], f"fwd{k} 其餘")
        if a is not None and b is not None:
            print(f"      中位差(高-餘): {(a.median() - b.median()):+.2f}pp")
        loto_bootstrap_diff(hi_s, rest_s, f"fwd{k}", "y", f"成員級fwd{k} s>=80高-餘")
    print()

    # ---------- 分析4: A1重疊 ----------
    print("#" * 70)
    print("## 分析4: A1重疊(近似=事件週週漲>10%;rank51-300閘門無法重建2025前歷史,已註記限制)")
    print("#" * 70)
    hh = pop[pop.hi & pop.wret0.notna()]
    n_a1ish = (hh.wret0 > A1_WRET).sum()
    print(f"  f>=80成員事件n={len(hh):,}(distinct codes={hh.code.nunique()}); "
          f"其中事件週週漲>10%(A1近似也會抓)={n_a1ish}({n_a1ish / max(len(hh), 1) * 100:.0f}%) / "
          f"週漲<=10%(配對新增,A1抓不到)={len(hh) - n_a1ish}({(len(hh) - n_a1ish) / max(len(hh), 1) * 100:.0f}%)")
    print(f"  參考: 全體有效位階成員的事件週週漲>10%比例={(pop.wret0 > A1_WRET).mean() * 100:.0f}% "
          f"(共振定義本身=日+4%爆量+週線創高,週漲>10%本來就常見)")
    for lab, sub in (("f>=80∧週漲>10(A1重疊區)", hh[hh.wret0 > A1_WRET]),
                     ("f>=80∧週漲<=10(配對新增區)", hh[hh.wret0 <= A1_WRET])):
        for k in (4, 8):
            stat(sub[f"fwd{k}"], f"{lab} fwd{k}")
    print()
    print("完成。regime註記: 有效窗2022-2026,2025-26占大宗(共振最熱年),2005-2021無法檢定——"
          "結論外推到其他regime要打折;上市only=部分宇宙結果。")


if __name__ == "__main__":
    main()
