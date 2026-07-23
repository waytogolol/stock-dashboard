# -*- coding: utf-8 -*-
"""共振 × TDCC大戶流向(d4w)條件化研究(2026-07-24,預註冊;本批考卷的期末考)
假說(使用者核定): 共振題材成員股中,TDCC大戶4週流向(千張/800張持股%的4週變化,d4w)強者,
在共振house持有期(8週,兼看4週)應優於流向弱者。
先驗背景: FLOW特徵已在處置脈絡三連過(mm5 +2.87pp/mm20 +3.68pp/TWSE-2022+複驗+3.46pp,
LOTO+bootstrap全乾淨);LEVEL/位階特徵在該脈絡全滅 => 本題問flow能否轉移到共振脈絡。
附加動機: TDCC涵蓋上市+上櫃(共振成員2022+ 226/226全在,含53檔inst_flow看不到的上櫃碼),
可補剛上板「外資確認」層的盲區(全上櫃事件只能標「—無法判定」)。

設計(預註冊,分析結構鏡射build_resonance_chip.py的層次以直接可比):
- 事件母體: 重用tmp_resonance_chip_panel.pkl(2,882 member-event,2005-2026,fwd4/8/12自帶)
  => 前向報酬與外資版逐bit相同,不重算;merge後逐列驗row count=2,882且fwd8 bit-identical
- 特徵(無前視,發布延遲規約=build_disposition_tdcc.py): cutoff=事件週五-3日曆日的最新tdcc_weekly
  快照,快照距cutoff>21天=過期作廢;
  * d4w_1000(主) = p1000當前-4快照前;4快照前不存在=NaN
  * d4w_800(變體) = 同法p800
  * p52_1000(反證控制) = p1000對自身近52快照百分位((窗<=now)比例*100,窗含now,>=26快照才算)
    —— 先驗說LEVEL該死;若它乾淨通過=大聲標註意外
- sanity: ①手驗對(2376/3324@2024-02-02週,見SANITY,±0.02/±0.5) ②panel row/fwd8 bit-identity
- 有效窗: 2013+(TDCC起點)≈14個年群 => LOTO功率遠優於外資版的4.5年
- 分析(每特徵三層,聚合層次不是市場分層):
  ①成員級: d4w前1/3(rank法三分位,比照處置慣例,於有效樣本內算) vs 其餘,fwd4/fwd8,
    中位/均值/勝率+四分位梯度單調性+LOTO(逐年)+年群bootstrap(B=10000,seed=42);
    主特徵另附逐年符號表+(code,week)去重複驗
  ②事件內對照(最有資訊量的一格): 同episode內高流成員均值-低流成員均值,逐事件差,
    差值中位+單樣本LOTO+bootstrap —— 外資版這格FAIL;flow若也fail=又是事件品質標記非選股,
    flow若PASS=比外資版更強且不同的主張
  ③事件級: 有>=1高流成員 vs 全無,事件均值fwd4/8+LOTO+bootstrap;劑量梯度(高流成員占比
    無/部分/全)
  ④上櫃盲區子組: in_inst=False的member-event(53碼群+2022前未涵蓋)——成員級+全上櫃事件級,
    決定本層能否當「—無法判定」事件的備援鏡頭
  ⑤與外資確認層交互(2022-07+,fpc存在窗): 事件外資狀態(✓=任一成員fpc>=80/✗=有值皆<80/
    無法判定=全無值)×flow強弱(任一成員d4w前1/3),格中位+n,兩格皆n>=20才bootstrap
用法: python -X utf8 build_resonance_tdcc.py  (Windows終端機cp950易炸)
"""
import sqlite3
import sys
import time

import numpy as np
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DB = "capital_flow.db"
PANEL_IN = "tmp_resonance_chip_panel.pkl"
PANEL_OUT = "tmp_resonance_tdcc_panel.pkl"
LAG_DAYS = 3          # 事件週五-3日曆日=快照cutoff(發布延遲規約=build_disposition_tdcc.py)
STALE_DAYS = 21       # 快照距cutoff>21天=覆蓋中斷,特徵作廢
P52_WIN = 52
P52_MIN = 26
HI_FPC = 80.0         # 外資確認層house慣例
B_BOOT = 10000
SEED = 42
FEATS = ["d4w_1000", "d4w_800", "p52_1000"]
# 手驗對(console手算鎖定): d4w=now-4快照前, p52=(近52快照<=now)比例*100
SANITY = {
    ("2376", "2024-02-02"): {"snap": "2024-01-26", "d4w_1000": 2.51, "d4w_800": 2.67, "p52_1000": 32.7},
    ("3324", "2024-02-02"): {"snap": "2024-01-26", "d4w_1000": 0.29, "d4w_800": 3.24, "p52_1000": 59.6},
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
    print(f"    {lab}: 中位{x.median():+6.2f}% 均值{x.mean():+6.2f}% "
          f"勝率{(x > 0).mean() * 100:3.0f}% n={len(x):,}")
    return x


def loto_bootstrap_diff(sig_df, ctl_df, val_col, year_col, label, b=B_BOOT, seed=SEED):
    """兩組中位差: 逐年LOTO+年群cluster bootstrap(值單位=%,印pp)。比照build_resonance_chip.py。"""
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
    """四分位/分箱表+單調梯度(值單位=%)。比照build_resonance_chip.py。"""
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


def compute_tdcc_features(pairs, tdcc):
    """每(code,week): cutoff=週五-3日曆日最新快照 → d4w_1000/d4w_800/p52_1000(+診斷欄)。"""
    series = {}
    for code, g in tdcc.groupby("code"):
        g = g.sort_values("date")
        series[code] = (g["date"].values.astype("datetime64[D]"),
                        g["p1000"].values.astype(float), g["p800"].values.astype(float))
    out = {}
    for code, week in pairs:
        rec = {"snap_date": pd.NaT, "snap_lag": np.nan, "span4_days": np.nan,
               "d4w_1000": np.nan, "d4w_800": np.nan, "p52_1000": np.nan}
        sv = series.get(code)
        if sv is not None:
            dts, v1000, v800 = sv
            cutoff = np.datetime64((week - pd.Timedelta(days=LAG_DAYS)).date())
            idx = int(np.searchsorted(dts, cutoff, side="right") - 1)
            if idx >= 0:
                lag = int((cutoff - dts[idx]).astype(int))
                rec["snap_date"] = pd.Timestamp(dts[idx])
                rec["snap_lag"] = lag
                if lag <= STALE_DAYS:
                    if idx >= 4:
                        rec["d4w_1000"] = v1000[idx] - v1000[idx - 4]
                        rec["d4w_800"] = v800[idx] - v800[idx - 4]
                        rec["span4_days"] = int((dts[idx] - dts[idx - 4]).astype(int))
                    w = v1000[max(0, idx - P52_WIN + 1):idx + 1]
                    if len(w) >= P52_MIN:
                        rec["p52_1000"] = (w <= v1000[idx]).mean() * 100
        out[(code, week)] = rec
    return out


def sanity_pins(pan):
    print("=" * 70)
    print("SANITY CHECK 1: 手驗對重現(console手算鎖定,d4w±0.02 / p52±0.5)")
    print("=" * 70)
    all_ok = True
    for (code, wk), exp in SANITY.items():
        hit = pan[(pan.code == code) & (pan.week == wk)].drop_duplicates(["code", "week"])
        if len(hit) != 1:
            print(f"  !! {code}@{wk} 去重後找到{len(hit)}筆(預期1),FAIL")
            all_ok = False
            continue
        r = hit.iloc[0]
        ok = (str(r.snap_date.date()) == exp["snap"]
              and abs(r.d4w_1000 - exp["d4w_1000"]) <= 0.02
              and abs(r.d4w_800 - exp["d4w_800"]) <= 0.02
              and abs(r.p52_1000 - exp["p52_1000"]) <= 0.5)
        print(f"  {code}@{wk}: snap={r.snap_date.date()}(exp {exp['snap']}) "
              f"d4w_1000={r.d4w_1000:+.2f}(exp {exp['d4w_1000']:+.2f}) "
              f"d4w_800={r.d4w_800:+.2f}(exp {exp['d4w_800']:+.2f}) "
              f"p52={r.p52_1000:.1f}(exp {exp['p52_1000']}) => {'PASS' if ok else 'FAIL'}")
        all_ok = all_ok and ok
    print(f"  >> {'PASS: 特徵管線重現手算' if all_ok else 'FAIL: 特徵管線與手算不一致,下方結果不可信任!'}\n")
    return all_ok


def member_level(pop, feat, full_detail=False):
    """分析層①成員級: 四分位梯度+前1/3 vs 其餘+LOTO/bootstrap(+主特徵逐年表與去重複驗)。"""
    print(f"  [層①成員級] n={len(pop):,} ({pop.week.min().date()}~{pop.week.max().date()}, "
          f"{pop.y.nunique()}個年份)")
    bucket_table(pop, "q", ["Q1", "Q2", "Q3", "Q4"], ["fwd4", "fwd8"],
                 f"{feat}四分位(rank法,有效樣本內)")
    print("  -- 前1/3(T3) vs 其餘(二元, LOTO+年群bootstrap) --")
    hi, rest = pop[pop.hi], pop[~pop.hi]
    for k in (4, 8):
        a = stat(hi[f"fwd{k}"], f"fwd{k} {feat}前1/3")
        b = stat(rest[f"fwd{k}"], f"fwd{k} 其餘")
        if a is not None and b is not None:
            print(f"      中位差(高-餘): {(a.median() - b.median()):+.2f}pp")
        loto_bootstrap_diff(hi, rest, f"fwd{k}", "y", f"成員級fwd{k} {feat}前1/3-餘")
    if not full_detail:
        return
    print("  -- 逐年符號(高-餘中位差,主特徵攤開) --")
    for y, g in pop.groupby("y"):
        h, r_ = g[g.hi], g[~g.hi]
        for k in (8,):
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
        a = stat(hi2[f"fwd{k}"], f"fwd{k} 前1/3")
        b = stat(rest2[f"fwd{k}"], f"fwd{k} 其餘")
        if a is not None and b is not None:
            print(f"      中位差(高-餘): {(a.median() - b.median()):+.2f}pp")
        loto_bootstrap_diff(hi2, rest2, f"fwd{k}", "y", f"去重成員級fwd{k} {feat}")


def within_event(pop, feat):
    """分析層②事件內對照: 同episode高流均值-低流均值(最有資訊量的一格)。回傳事件表供層③用。"""
    ev_rows = []
    for (theme, week), g in pop.groupby(["theme", "week"]):
        rec = {"theme": theme, "week": week, "y": week.year,
               "n_hi": int(g.hi.sum()), "n_valid": len(g)}
        for k in (4, 8):
            hv = g.loc[g.hi, f"fwd{k}"].dropna()
            lv = g.loc[~g.hi, f"fwd{k}"].dropna()
            rec[f"d{k}"] = hv.mean() - lv.mean() if len(hv) and len(lv) else np.nan
            rec[f"ev_fwd{k}"] = g[f"fwd{k}"].mean()
        ev_rows.append(rec)
    evl = pd.DataFrame(ev_rows)
    print(f"  [層②事件內對照] 有>=1有效{feat}成員的事件: {len(evl)} / "
          f"其中同事件內有高+低成員(可內對照,fwd8): {evl.d8.notna().sum()}")
    for k in (4, 8):
        x = stat(evl[f"d{k}"], f"事件內差d{k}(高流成員均值-低流成員均值)")
        if x is not None:
            print(f"      差>0的事件比例: {(x > 0).mean() * 100:.0f}%")
        loto_bootstrap_one(evl, f"d{k}", "y", f"事件內差d{k} {feat}")
    return evl


def event_level(evl, feat):
    """分析層③事件級: 有>=1高流成員 vs 全無 + 劑量梯度(無/部分/全)。"""
    has_hi, no_hi = evl[evl.n_hi > 0], evl[evl.n_hi == 0]
    print(f"  [層③事件級] 有高流成員={len(has_hi)}事件 / 全無={len(no_hi)}事件")
    for k in (4, 8):
        a = stat(has_hi[f"ev_fwd{k}"], f"ev_fwd{k} 有高流成員")
        b = stat(no_hi[f"ev_fwd{k}"], f"ev_fwd{k} 全無")
        if a is not None and b is not None:
            print(f"      中位差: {(a.median() - b.median()):+.2f}pp")
        loto_bootstrap_diff(has_hi, no_hi, f"ev_fwd{k}", "y", f"事件級fwd{k} {feat}有高-全無")
    evl = evl.copy()
    share = evl.n_hi / evl.n_valid
    evl["dose"] = np.select([share == 0, share == 1], ["無高流", "全高流"], default="部分高流")
    bucket_table(evl, "dose", ["無高流", "部分高流", "全高流"], ["ev_fwd4", "ev_fwd8"],
                 "劑量梯度(高流成員占比)")


def main():
    # ---------- 資料 ----------
    pan = pd.read_pickle(PANEL_IN)
    orig_fwd8 = pan.fwd8.values.copy()
    n_orig = len(pan)
    tdcc = read_sql_retry("SELECT code, date, p800, p1000 FROM tdcc_weekly ORDER BY code, date")
    tdcc["date"] = pd.to_datetime(tdcc.date)
    print(f"事件母體: {n_orig:,}筆member-event(重用{PANEL_IN},前向報酬不重算=與外資版逐bit同源); "
          f"tdcc_weekly: {len(tdcc):,}列 {tdcc.code.nunique():,}檔 "
          f"{tdcc.date.min().date()}~{tdcc.date.max().date()}")

    # ---------- 特徵掛載(逐(code,week)唯一對算一次,map回panel保序保量) ----------
    pairs = list(dict.fromkeys(zip(pan.code, pan.week)))
    feat = compute_tdcc_features(pairs, tdcc)
    for col in ["snap_date", "snap_lag", "span4_days", "d4w_1000", "d4w_800", "p52_1000"]:
        pan[col] = [feat[(c, w)][col] for c, w in zip(pan.code, pan.week)]
    pan.to_pickle(PANEL_OUT)

    # SANITY 2: row count + fwd8 bit-identity(merge沒動到母體)
    same_n = len(pan) == n_orig == 2882
    bit_ok = np.array_equal(pan.fwd8.values, orig_fwd8, equal_nan=True)
    print(f"SANITY CHECK 2: panel merge保量保值: row={len(pan):,}(預期2,882)={'PASS' if same_n else 'FAIL'}; "
          f"fwd8 bit-identical={'PASS' if bit_ok else 'FAIL'}; 面板存 {PANEL_OUT}\n")
    if not (same_n and bit_ok):
        sys.exit(1)
    ok = sanity_pins(pan)

    # ---------- 覆蓋診斷 ----------
    print("=" * 70)
    print("覆蓋診斷(TDCC 2013-01起,上市+上櫃全覆蓋 => 對照外資版的部分宇宙警告,本版無此問題)")
    print("=" * 70)
    codes_all = pan.code.nunique()
    codes_td = pan[pan.d4w_1000.notna()].code.nunique()
    print(f"  member-event全史={len(pan):,}筆; d4w_1000有效={pan.d4w_1000.notna().sum():,}筆 "
          f"d4w_800有效={pan.d4w_800.notna().sum():,}筆 p52_1000有效={pan.p52_1000.notna().sum():,}筆; "
          f"涉及codes {codes_td}/{codes_all}")
    stale = pan[pan.snap_lag.notna() & (pan.snap_lag > STALE_DAYS)]
    sp = pan.span4_days.dropna()
    print(f"  快照過期(> {STALE_DAYS}天)作廢={len(stale)}筆; 快照lag中位={pan.snap_lag.median():.0f}天; "
          f"4快照跨距中位={sp.median():.0f}天 p95={sp.quantile(0.95):.0f}天 >42天(有缺週)={int((sp > 42).sum())}筆")
    print("  逐年: n=member-event / d4w有效% / p52有效% / 上櫃(不在inst_flow)%")
    p13 = pan[pan.week >= "2013-01-01"]
    for y, g in p13.groupby("y"):
        print(f"    {y}: n={len(g):5,d}  d4w{g.d4w_1000.notna().mean() * 100:6.1f}%  "
              f"p52{g.p52_1000.notna().mean() * 100:6.1f}%  上櫃{(~g.in_inst).mean() * 100:5.1f}%")
    n_pre = (pan.week < "2013-01-01").sum()
    print(f"  2013前(TDCC覆蓋外,不可檢定)={n_pre:,}筆member-event\n")
    if not ok:
        print("!! sanity FAIL,不跑分析")
        sys.exit(1)

    # ---------- 特徵旗標(rank法三分位/四分位,於各自有效樣本內;切點印出存證) ----------
    pops = {}
    for f in FEATS:
        pop = pan[pan[f].notna()].copy()
        rk = pop[f].rank(pct=True)
        pop["hi"] = rk > 2 / 3
        pop["q"] = pd.cut(rk, bins=[-0.01, 0.25, 0.5, 0.75, 1.01], labels=["Q1", "Q2", "Q3", "Q4"])
        pops[f] = pop
        e = pop[f]
        print(f"  {f}: 有效n={len(pop):,} 前1/3切點≈{e.quantile(2 / 3):+.2f} "
              f"四分位切點{e.quantile(0.25):+.2f}/{e.quantile(0.5):+.2f}/{e.quantile(0.75):+.2f}"
              f"{'(pp)' if f.startswith('d4w') else '(百分位)'}")
    print()

    # ---------- 三層分析 × 三特徵 ----------
    evls = {}
    for f in FEATS:
        pop = pops[f]
        tag = {"d4w_1000": "主特徵", "d4w_800": "變體", "p52_1000": "反證控制(先驗=LEVEL該死;乾淨通過=意外要大聲標)"}[f]
        print("#" * 70)
        print(f"## 特徵 {f} ({tag})")
        print("#" * 70)
        member_level(pop, f, full_detail=(f == "d4w_1000"))
        print()
        evls[f] = within_event(pop, f)
        print()
        event_level(evls[f], f)
        print()
    # p52補house慣例>=80二元(與處置版可比)
    pop = pops["p52_1000"]
    hi80, rest80 = pop[pop.p52_1000 >= 80], pop[pop.p52_1000 < 80]
    print("  -- p52_1000補充: house慣例>=80二元(與處置版口徑可比) --")
    for k in (4, 8):
        a = stat(hi80[f"fwd{k}"], f"fwd{k} p52>=80")
        b = stat(rest80[f"fwd{k}"], f"fwd{k} 其餘")
        if a is not None and b is not None:
            print(f"      中位差(高-餘): {(a.median() - b.median()):+.2f}pp")
        loto_bootstrap_diff(hi80, rest80, f"fwd{k}", "y", f"成員級fwd{k} p52>=80高-餘")
    print()

    # ---------- 分析④: 上櫃盲區子組(in_inst=False;旗標沿用全域三分位=部署時的單一定義) ----------
    print("#" * 70)
    print("## 分析④: 上櫃盲區子組(code不在inst_flow;外資確認層看不到的宇宙)")
    print("#" * 70)
    pop = pops["d4w_1000"]
    otc = pop[~pop.in_inst]
    print(f"  成員級: 上櫃member-event n={len(otc):,}(其中前1/3高流={otc.hi.sum():,}) "
          f"[旗標=全域三分位,部署口徑]")
    hi, rest = otc[otc.hi], otc[~otc.hi]
    for k in (4, 8):
        a = stat(hi[f"fwd{k}"], f"fwd{k} 上櫃∧前1/3")
        b = stat(rest[f"fwd{k}"], f"fwd{k} 上櫃∧其餘")
        if a is not None and b is not None:
            print(f"      中位差(高-餘): {(a.median() - b.median()):+.2f}pp")
        loto_bootstrap_diff(hi, rest, f"fwd{k}", "y", f"上櫃成員級fwd{k}")
    otc22 = otc[otc.week >= "2022-01-01"]
    print(f"  -- 2022+子窗(部署窗,n={len(otc22):,}) --")
    hi, rest = otc22[otc22.hi], otc22[~otc22.hi]
    for k in (4, 8):
        a = stat(hi[f"fwd{k}"], f"fwd{k} 上櫃2022+∧前1/3")
        b = stat(rest[f"fwd{k}"], f"fwd{k} 上櫃2022+∧其餘")
        if a is not None and b is not None:
            print(f"      中位差(高-餘): {(a.median() - b.median()):+.2f}pp")
        loto_bootstrap_diff(hi, rest, f"fwd{k}", "y", f"上櫃2022+成員級fwd{k}")
    # 全上櫃事件(=外資確認層標「—無法判定」的那種事件)
    allotc_keys = pop.groupby(["theme", "week"]).in_inst.max()
    allotc_keys = set(allotc_keys[~allotc_keys].index)  # max(in_inst)=False => 全員上櫃
    evl = evls["d4w_1000"]
    evl_otc = evl[[tuple(x) in allotc_keys for x in zip(evl.theme, evl.week)]]
    has_hi, no_hi = evl_otc[evl_otc.n_hi > 0], evl_otc[evl_otc.n_hi == 0]
    print(f"  -- 全上櫃事件級(外資確認層只能標「—無法判定」的事件): n={len(evl_otc)} "
          f"(有高流{len(has_hi)}/全無{len(no_hi)}) --")
    for k in (4, 8):
        a = stat(has_hi[f"ev_fwd{k}"], f"ev_fwd{k} 全上櫃∧有高流")
        b = stat(no_hi[f"ev_fwd{k}"], f"ev_fwd{k} 全上櫃∧全無")
        if a is not None and b is not None:
            print(f"      中位差: {(a.median() - b.median()):+.2f}pp")
        loto_bootstrap_diff(has_hi, no_hi, f"ev_fwd{k}", "y", f"全上櫃事件級fwd{k}")
    print()

    # ---------- 分析⑤: 與外資確認層交互(2022-07+,fpc存在窗) ----------
    print("#" * 70)
    print("## 分析⑤: 與外資確認層交互(2022-07+;事件外資狀態×flow強弱;年群僅~5,結果視為描述性)")
    print("#" * 70)
    sub = pan[(pan.week >= "2022-07-01") & pan.d4w_1000.notna()].copy()
    th = pops["d4w_1000"].d4w_1000.quantile(2 / 3)  # 全域三分位切點(部署口徑)
    sub["hi"] = sub.d4w_1000 > th
    ev_rows = []
    for (theme, week), g in sub.groupby(["theme", "week"]):
        fvalid = g.fpc.notna()
        fstat = "無法判定" if not fvalid.any() else ("外資✓" if (g.fpc >= HI_FPC).any() else "外資✗")
        ev_rows.append({"theme": theme, "week": week, "y": week.year, "fstat": fstat,
                        "flow": "flow強" if g.hi.any() else "flow弱",
                        "ev_fwd4": g.fwd4.mean(), "ev_fwd8": g.fwd8.mean()})
    ix = pd.DataFrame(ev_rows)
    print(f"  事件n={len(ix)}(2022-07+,>=1有效d4w成員;flow強=任一成員d4w>全域前1/3切點{th:+.2f}pp)")
    for fs in ["外資✓", "外資✗", "無法判定"]:
        cells = {}
        for fl in ["flow強", "flow弱"]:
            cc = ix[(ix.fstat == fs) & (ix.flow == fl)]
            cells[fl] = cc
            x4, x8 = cc.ev_fwd4.dropna(), cc.ev_fwd8.dropna()
            m4 = f"{x4.median():+6.2f}%" if len(x4) else "  n/a"
            m8 = f"{x8.median():+6.2f}%" if len(x8) else "  n/a"
            w8 = f"{(x8 > 0).mean() * 100:3.0f}%" if len(x8) else "n/a"
            print(f"    {fs} × {fl}: n={len(cc):3d}  fwd4中位{m4}  fwd8中位{m8}  fwd8勝率{w8}")
        if len(cells["flow強"]) >= 20 and len(cells["flow弱"]) >= 20:
            loto_bootstrap_diff(cells["flow強"], cells["flow弱"], "ev_fwd8", "y",
                                f"{fs}內flow強-弱 fwd8")
        else:
            print(f"      ({fs}內flow強/弱有格n<20,不bootstrap,只報描述)")
    print()
    print("完成。註記: 前向報酬與外資版(build_resonance_chip.py)逐bit同源可直接對表;"
          "檢定窗2013-2026(14年群)遠厚於外資版4.5年;TDCC週頻=訊號延遲~1週,粗於外資日頻。")


if __name__ == "__main__":
    main()
