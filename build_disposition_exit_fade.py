# -*- coding: utf-8 -*-
"""處置出關前「拉高再重挫」= 主力提早下車? 研究(使用者2026-07-23由8261現場觀察提案)
現象: 8261(富鼎)處置窗2026-07-09~07-24(5分盤),325跌到07-20收229,隨後連二日反彈
(07-21 +6.3%/07-22 +4.3%,累積~+10.9%),07-23(出關前倒數第2日)開在高點卻收殺-7.5%,
幾乎吐光整段反彈。假說: 出關前的「反彈→重吐」= 主力趁出關前流動性恢復預期提早獲利下車,
預測出關後走勢差(避開/否決訊號,與同日earlier的candle_fade「吐回黑K續跌」判決方向一致)。

設計(預註冊,依工程場定稿執行):
- 母體: disposition全事件對到fm_daily_price者(與tmp_disposition_candle_panel.pkl同一事件集,
  event_id口徑一致可直接對併);match_min '5'/'20'(TEXT)分層,永不合併
- 價格: 自算close-based報酬(spread欄位在處置轉換日不可信,candle_fade已現場核對)
- 事件級分類(每事件一標籤),看窗內最後5個交易日(day_idx_from_end<=4):
  * Run-up: 存在2日或3日連續交易日的累積close-to-close漲幅>=門檻,且該段「結束」落在最後5日內;
    門檻變體+6%/+8%(headline)/+10%
  * Giveback: run-up峰值收盤之後(窗末日前,含末日),(a)單日ret_cc<=-5%(headline)
    或(b)自峰值收盤累積回落>=run-up幅度的60%
  * G1=run-up且giveback(目標型態) G2=run-up無giveback(反彈守到出關)
    G3=無run-up但最後3窗日內有單日<=-5%(單純弱勢收尾) G4=其餘(基準)
- 結果: 主要=窗內最後一日收盤起算出關後k=1,3,5,10,20交易日forward return(價格自然延伸);
  次要=G1的giveback日收盤起算同k(=「看到吐回就跑」的人之後經歷)+吐回日→窗末日(窗內剩餘失血)
- 比較(house rule,對照組不對零): G1vsG2(關鍵:資訊在giveback還是任何出關前反彈都差?)
  G1vsG4(vs普通出關) G3vsG4(單純弱勢是否也差=G1是不是「弱勢」換皮)
- 驗證: LOTO逐年+年群bootstrap(B=10000,seed=42)於headline的G1-G2/G1-G4差值,n<15-20不硬跑
- 量能指紋(描述性): G1的run-up段與giveback日量能/該事件窗內中位量能比;主力出貨故事預測兩段都放量
- V5否決應用: V5=倒數第3日收盤買→出關日開盤出,扣0.45%(口徑同build_panic_liquidity_report.py
  v4_v5_dated_curves,窗長6<=en-s<=25;「人工管制」剔除在現行DB reason字串比對為0筆=no-op,照掛存證);
  G1 vs 非G1的V5報酬,否決刪幾筆/剩餘池改善多少;另拆giveback發生在V5進場前(事前可否決)vs後(只能停損)
用法: python -X utf8 build_disposition_exit_fade.py  (Windows終端機cp950易炸)
"""
import sqlite3
import sys

import numpy as np
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DB = "capital_flow.db"
PANEL_OUT = "tmp_disposition_exit_fade_panel.pkl"
CANDLE_PANEL = "tmp_disposition_candle_panel.pkl"
RUNUP_TH = {"r6": 0.06, "r8": 0.08, "r10": 0.10}
GB_VARIANTS = ["a", "b"]
HEADLINE = ("r8", "a")
GB_SINGLE_DAY = -0.05
GB_RETRACE = 0.60
LAST_N = 4     # day_idx_from_end<=4 = 最後5個窗內交易日
G3_LAST_N = 2  # 最後3日
POST_KS = [1, 3, 5, 10, 20]
B_BOOT = 10000
SEED = 42
MAX_WIN_LEN = 30
V5_COST = 0.45


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
    p_le0 = (diffs <= 0).mean()
    p_ge0 = (diffs >= 0).mean()
    print(f"      差值cluster bootstrap(B={len(diffs)}): 差值中位數CI95=[{lo * 100:+.2f}, {hi * 100:+.2f}]pp, "
          f"P(差<=0)={p_le0:.4f} P(差>=0)={p_ge0:.4f}")


def find_runs(rets, W, th):
    """回傳所有合格run-up: (cum, j_end, L)。2或3個連續窗內交易日,結束日dfe<=LAST_N,累積>=th。"""
    runs = []
    for L in (2, 3):
        for j in range(L - 1, W):
            if (W - 1 - j) > LAST_N:
                continue
            cum = float(np.prod(1.0 + rets[j - L + 1:j + 1]) - 1.0)
            if cum >= th:
                runs.append((cum, j, L))
    return runs


def find_giveback(closes_w, rets, W, run):
    """run結束日之後(窗內)找giveback: 回傳(gb_a首個單日<=-5%的idx, gb_b首個回落>=60%run幅度的idx)。"""
    cum, j, L = run
    peak = closes_w[j]
    gb_a = None
    gb_b = None
    for m in range(j + 1, W):
        if gb_a is None and rets[m] <= GB_SINGLE_DAY:
            gb_a = m
        if gb_b is None and peak > 0 and (closes_w[m] / peak - 1.0) <= -GB_RETRACE * cum:
            gb_b = m
        if gb_a is not None and gb_b is not None:
            break
    return gb_a, gb_b


def build_events(disp, stocks):
    rows = []
    for ev_id, e in disp.iterrows():
        g = stocks.get(e.code)
        if g is None:
            continue
        dts = g["date"].values
        n = len(g)
        s = int(np.searchsorted(dts, np.datetime64(e.start_date)))
        en = int(np.searchsorted(dts, np.datetime64(e.end_date), side="right") - 1)
        if s < 1 or en < s or s >= n or en - s > MAX_WIN_LEN:
            continue
        c_ = g["close"].values
        o_ = g["open"].values
        v_ = g["volume"].values
        if not np.all(c_[s - 1:en + 1] > 0):
            continue
        W = en - s + 1
        closes_w = c_[s:en + 1]
        rets = closes_w / c_[s - 1:en] - 1.0
        vols_w = v_[s:en + 1].astype(float)
        med_vol = np.nanmedian(vols_w) if np.isfinite(vols_w).any() else np.nan
        truncated = pd.Timestamp(e.end_date) > pd.Timestamp(dts[-1])

        row = {"event_id": ev_id, "code": e.code, "market": e.market,
               "match_min": str(e.match_min), "y": e.start_date.year,
               "start_date": e.start_date, "end_date": e.end_date,
               "win_len": W, "truncated": truncated, "reason": str(e.reason)}

        # 主要結果: 窗末日收盤起算出關後k日(資料不足=NaN,自然掉出統計)
        for k in POST_KS:
            j = en + k
            row[f"post{k}"] = (c_[j] / c_[en] - 1.0) if (j < n and c_[j] > 0) else np.nan

        # ---- run-up / giveback 分類(全部6組變體) ----
        runs_detail = {}
        for tn, th in RUNUP_TH.items():
            runs_detail[tn] = [(r,) + find_giveback(closes_w, rets, W, r) for r in find_runs(rets, W, th)]
        has_weak_finish = any(rets[m] <= GB_SINGLE_DAY and (W - 1 - m) <= G3_LAST_N for m in range(W))

        for tn in RUNUP_TH:
            detail = runs_detail[tn]
            for gi, gv in enumerate(GB_VARIANTS, start=1):
                if detail:
                    with_gb = [d for d in detail if d[gi] is not None]
                    if with_gb:
                        grp = "G1"
                        chosen = max(with_gb, key=lambda d: (d[0][0], d[0][1]))
                    else:
                        grp = "G2"
                        chosen = max(detail, key=lambda d: (d[0][0], d[0][1]))
                else:
                    grp = "G3" if has_weak_finish else "G4"
                    chosen = None
                row[f"grp_{tn}_{gv}"] = grp

                if (tn, gv) != HEADLINE:
                    continue
                # ---- headline變體的細節欄位 ----
                if chosen is not None:
                    (cum, j, L), gb_a, gb_b = chosen
                    row["run_cum"] = cum
                    row["run_len"] = L
                    row["run_end_dfe"] = W - 1 - j
                    if med_vol and med_vol > 0:
                        row["run_vol_ratio"] = float(np.nanmedian(vols_w[j - L + 1:j + 1]) / med_vol)
                    gb = gb_a if gv == "a" else gb_b
                    if grp == "G1" and gb is not None:
                        gb_abs = s + gb
                        row["gb_dfe"] = W - 1 - gb
                        row["gb_ret"] = rets[gb]
                        row["gb_date"] = pd.Timestamp(dts[gb_abs])
                        if med_vol and med_vol > 0:
                            row["gb_vol_ratio"] = float(vols_w[gb] / med_vol)
                        row["gb_to_exit"] = c_[en] / c_[gb_abs] - 1.0
                        for k in POST_KS:
                            jj = gb_abs + k
                            row[f"gbfwd{k}"] = (c_[jj] / c_[gb_abs] - 1.0) if (jj < n and c_[jj] > 0) else np.nan
                        row["gb_before_v5entry"] = bool(gb_abs <= en - 2)

        # ---- V5交易(口徑同build_panic_liquidity_report.v4_v5_dated_curves) ----
        v5_ok = (6 <= en - s <= 25) and (en + 1 < n) and o_[en + 1] > 0 and c_[en - 2] > 0
        row["v5_valid"] = bool(v5_ok)
        if v5_ok:
            row["v5_net"] = (o_[en + 1] / c_[en - 2] - 1.0) * 100 - V5_COST
            row["pre_path"] = (c_[en - 3] / c_[s] - 1.0) * 100 if (en - 3 > s and c_[s] > 0) else np.nan
            if row.get("gb_dfe") is not None and not row.get("gb_before_v5entry", True):
                gb_abs = s + (W - 1 - int(row["gb_dfe"]))
                row["v5_bail_net"] = (c_[gb_abs] / c_[en - 2] - 1.0) * 100 - V5_COST
        rows.append(row)
    df = pd.DataFrame(rows)
    return df.sort_values("event_id").reset_index(drop=True)


def sanity_check_8261(ev, disp, stocks):
    print("=" * 70)
    print("SANITY CHECK: 8261(富鼎) 2026-07處置窗 是否分類為G1(headline: run-up+8%/單日-5%吐回)")
    print("=" * 70)
    hit = ev[(ev.code == "8261") & (ev.start_date == "2026-07-09")]
    if hit.empty:
        print("  !! 找不到8261 2026-07事件,面板建置有問題,不可信任全母體結果")
        return
    r = hit.iloc[0]
    g = stocks["8261"]
    dts = g["date"].values
    s = int(np.searchsorted(dts, np.datetime64(r.start_date)))
    en = int(np.searchsorted(dts, np.datetime64(r.end_date), side="right") - 1)
    c_ = g["close"].values
    print("  窗內逐日(觀測到的資料;窗名目結束2026-07-24但價格資料只到07-23=窗被截斷):")
    for i in range(s, en + 1):
        ret = c_[i] / c_[i - 1] - 1
        print(f"    {str(dts[i])[:10]} close={c_[i]:8.1f} ret_cc={ret * 100:+6.2f}% dfe={en - i}")
    print(f"\n  分類={r.grp_r8_a}  run_cum={r.run_cum * 100 if pd.notna(r.run_cum) else float('nan'):+.2f}% "
          f"(len={r.run_len}, 結束dfe={r.run_end_dfe})  "
          f"gb_ret={r.gb_ret * 100 if pd.notna(r.gb_ret) else float('nan'):+.2f}% (gb日dfe={r.gb_dfe})")
    posts = [r[f"post{k}"] for k in POST_KS]
    all_nan = all(pd.isna(p) for p in posts)
    ok = (r.grp_r8_a == "G1") and pd.notna(r.run_cum) and r.run_cum >= 0.08 and \
         pd.notna(r.gb_ret) and r.gb_ret <= -0.05
    print(f"  truncated旗標={r.truncated} (end_date=07-24尚未交易)  "
          f"post1..20全NaN? {'是' if all_nan else '否!!'}  v5_valid={r.v5_valid}(截斷窗en+1不存在,應為False)")
    print(f"  預期run-up 07-21~22累積+10.9%(觀測dfe=1結束)/giveback 07-23 -7.5%(觀測dfe=0);"
          f"任務書寫dfe=2/1是按名目日曆(含07-24),資料截斷使觀測dfe各-1,分類不受影響")
    if ok and all_nan and not r.v5_valid:
        print("  >> PASS: 分類=G1、無出關後資料時優雅退出(全NaN不入統計、不當機、不誤標)。可信任全母體結果。\n")
    else:
        print("  >> FAIL: 檢查分類邏輯/截斷處理,不可信任下方結果!\n")


def main():
    conn = sqlite3.connect(DB)
    disp = pd.read_sql("SELECT * FROM disposition", conn)
    px = pd.read_sql("SELECT code, date, open, close, volume FROM fm_daily_price ORDER BY code, date", conn)
    conn.close()

    for c in ("announce_date", "start_date", "end_date"):
        disp[c] = pd.to_datetime(disp[c], errors="coerce")
    disp = disp.dropna(subset=["start_date", "end_date"]).reset_index(drop=True)  # event_id口徑=candle panel
    px["date"] = pd.to_datetime(px["date"])
    stocks = {c: g.sort_values("date").reset_index(drop=True) for c, g in px.groupby("code")}

    n_ctrl = disp.reason.astype(str).str.contains("人工管制").sum()
    print(f"處置事件母體: {len(disp):,}筆 (5分盤{(disp.match_min == '5').sum():,}/20分盤{(disp.match_min == '20').sum():,}); "
          f"reason含「人工管制」={n_ctrl}筆(現行DB字串下V5毒格剔除為no-op,照口徑掛上存證)")

    ev = build_events(disp, stocks)
    ev.to_pickle(PANEL_OUT)
    n_trunc = ev.truncated.sum()
    print(f"事件面板: {len(ev):,}筆事件對到價格 (存{PANEL_OUT}); 窗被截斷(end_date超出現有價格,進行中/下市)={n_trunc}筆"
          f"→分類為暫定、不入統計")

    # 與candle panel事件集一致性
    try:
        cp = pd.read_pickle(CANDLE_PANEL)
        cset, mset = set(cp.event_id.unique()), set(ev.event_id)
        print(f"與{CANDLE_PANEL}事件集一致性: candle={len(cset):,} 本面板={len(mset):,} "
              f"交集={len(cset & mset):,} (預期完全一致)")
        gb_black = cp[(cp.class_A == "black") & (cp.prev_class_A == "red")]
        gb_black_days = set(zip(gb_black.event_id, pd.to_datetime(gb_black.date)))
        gb_black_events = set(gb_black.event_id)
    except FileNotFoundError:
        print(f"!! 找不到{CANDLE_PANEL},略過一致性/重疊分析")
        gb_black_days, gb_black_events = set(), set()
    print()

    sanity_check_8261(ev, disp, stocks)

    evc = ev[~ev.truncated].copy()  # 完整窗才入統計

    # ================= 各變體分組計數 =================
    print("=" * 70)
    print("分組計數(G1/G2/G3/G4,排除截斷窗;G1<30旗標⚠)")
    print("=" * 70)
    for mm in ["5", "20"]:
        pop = evc[evc.match_min == mm]
        print(f"-- match_min={mm} (事件n={len(pop):,}) --")
        for tn in RUNUP_TH:
            for gv in GB_VARIANTS:
                col = f"grp_{tn}_{gv}"
                vc = pop[col].value_counts()
                n1 = vc.get("G1", 0)
                flag = " ⚠G1<30" if n1 < 30 else ""
                hl = " <== HEADLINE" if (tn, gv) == HEADLINE else ""
                print(f"  {tn}/{gv}: G1={n1:4d} G2={vc.get('G2', 0):4d} G3={vc.get('G3', 0):4d} "
                      f"G4={vc.get('G4', 0):4d}{flag}{hl}")
    print()

    # ================= headline 主分析 =================
    hl_col = f"grp_{HEADLINE[0]}_{HEADLINE[1]}"
    for mm in ["5", "20"]:
        pop = evc[evc.match_min == mm]
        g1 = pop[pop[hl_col] == "G1"]
        g2 = pop[pop[hl_col] == "G2"]
        g3 = pop[pop[hl_col] == "G3"]
        g4 = pop[pop[hl_col] == "G4"]
        print("#" * 70)
        print(f"## HEADLINE(run-up>=+8%,單日-5%吐回) match_min={mm}  "
              f"G1={len(g1)} G2={len(g2)} G3={len(g3)} G4={len(g4)}")
        print("#" * 70)

        print("\n== 出關後forward return(窗末日收盤起算) ==")
        for k in POST_KS:
            col = f"post{k}"
            print(f"  k={k}:")
            s1 = stat(g1[col], "G1 拉高再重挫")
            s2 = stat(g2[col], "G2 反彈守住  ")
            s3 = stat(g3[col], "G3 單純弱勢  ")
            s4 = stat(g4[col], "G4 基準      ")
            if s1 is not None and s2 is not None:
                print(f"      中位差 G1-G2: {(s1.median() - s2.median()) * 100:+.2f}pp")
            if s1 is not None and s4 is not None:
                print(f"      中位差 G1-G4: {(s1.median() - s4.median()) * 100:+.2f}pp")
            if s3 is not None and s4 is not None:
                print(f"      中位差 G3-G4: {(s3.median() - s4.median()) * 100:+.2f}pp")

        print("\n== 差值LOTO+年群bootstrap(headline) ==")
        for k in (5, 10, 20):
            print(f"    [G1-G2 post{k}]")
            loto_bootstrap_diff(g1, g2, f"post{k}", "y", f"{mm}分盤G1-G2 k{k}")
            print(f"    [G1-G4 post{k}]")
            loto_bootstrap_diff(g1, g4, f"post{k}", "y", f"{mm}分盤G1-G4 k{k}")
        for k in (5, 10):
            print(f"    [G3-G4 post{k}]")
            loto_bootstrap_diff(g3, g4, f"post{k}", "y", f"{mm}分盤G3-G4 k{k}")

        print("\n== 結構檢查: run結束日dfe分布(G2含「run收在末日,結構上不可能再吐回」的天生偏差) ==")
        for lab, gg in (("G1", g1), ("G2", g2)):
            if len(gg):
                d = gg.run_end_dfe.value_counts().sort_index()
                print(f"    {lab} run_end_dfe: " + "  ".join(f"dfe{int(i)}={v}" for i, v in d.items()))
        if len(g1):
            d = g1.gb_dfe.value_counts().sort_index()
            print("    G1 giveback日dfe: " + "  ".join(f"dfe{int(i)}={v}" for i, v in d.items()))

        print("\n== 次要(可交易性): G1吐回日收盤起算forward(=看到吐回立刻跑的人之後看到什麼) ==")
        stat(g1["gb_to_exit"], "吐回日收盤→窗末日收盤(窗內剩餘段,含gb=末日的0)")
        stat(g1.loc[g1.gb_dfe > 0, "gb_to_exit"], "同上但僅gb非末日(gb_dfe>0,真有剩餘段)  ")
        for k in POST_KS:
            stat(g1[f"gbfwd{k}"], f"吐回日收盤起算k={k}")

        print("\n== 量能指紋(相對該事件窗內中位量;主力出貨故事預測兩段都>1) ==")
        for lab, x in (("G1 run-up段量比", g1.run_vol_ratio), ("G1 吐回日量比", g1.gb_vol_ratio),
                       ("G2 run-up段量比(對照)", g2.run_vol_ratio)):
            xx = pd.Series(x).dropna()
            if len(xx) >= 10:
                print(f"    {lab}: 中位{xx.median():.2f}x 均值{xx.mean():.2f}x >1佔比{(xx > 1).mean() * 100:.0f}% n={len(xx)}")
            else:
                print(f"    {lab}: n={len(xx)}太少")
        print()

    # ================= 門檻變體穩健性 =================
    print("=" * 70)
    print("門檻變體穩健性: G1-G2 / G1-G4 中位差(pp) @k5,k10 (n過小標n/a)")
    print("=" * 70)
    for mm in ["5", "20"]:
        pop = evc[evc.match_min == mm]
        print(f"-- match_min={mm} --")
        for tn in RUNUP_TH:
            for gv in GB_VARIANTS:
                col = f"grp_{tn}_{gv}"
                out = [f"{tn}/{gv}: nG1={len(pop[pop[col] == 'G1']):4d}"]
                for k in (5, 10):
                    kc = f"post{k}"
                    a = pop.loc[pop[col] == "G1", kc].dropna()
                    b = pop.loc[pop[col] == "G2", kc].dropna()
                    c = pop.loc[pop[col] == "G4", kc].dropna()
                    d12 = f"{(a.median() - b.median()) * 100:+6.2f}" if len(a) >= 10 and len(b) >= 10 else "   n/a"
                    d14 = f"{(a.median() - c.median()) * 100:+6.2f}" if len(a) >= 10 and len(c) >= 10 else "   n/a"
                    out.append(f"k{k}: G1-G2={d12} G1-G4={d14}")
                print("  " + "  |  ".join(out))
    print()

    # ================= V5否決應用 =================
    print("=" * 70)
    print("V5否決應用(V5=倒數第3日收盤買→出關開盤出,-0.45%;headline分組)")
    print("=" * 70)
    for mm in ["5", "20"]:
        pop = evc[(evc.match_min == mm) & evc.v5_valid].copy()
        pop["is_g1"] = pop[hl_col] == "G1"
        g1v = pop[pop.is_g1]
        rest = pop[~pop.is_g1]
        print(f"-- match_min={mm} (V5可交易事件n={len(pop):,}) --")
        a = stat(g1v.v5_net / 100, "G1事件的V5交易   ")
        b = stat(rest.v5_net / 100, "非G1事件的V5交易 ")
        if a is not None and b is not None:
            print(f"      中位差(G1-非G1): {(a.median() - b.median()) * 100:+.2f}pp")
        loto_bootstrap_diff(g1v.assign(v=g1v.v5_net / 100), rest.assign(v=rest.v5_net / 100),
                            "v", "y", f"{mm}分盤V5 G1-非G1")
        allp = stat(pop.v5_net / 100, "否決前全池       ")
        surv = stat(rest.v5_net / 100, "否決後剩餘池     ")
        if allp is not None and surv is not None:
            print(f"      否決刪除{len(g1v)}筆({len(g1v) / len(pop) * 100:.1f}%),"
                  f"剩餘池中位改善{(surv.median() - allp.median()) * 100:+.2f}pp,"
                  f"勝率{(allp > 0).mean() * 100:.0f}%→{(surv > 0).mean() * 100:.0f}%")
        sub = pop[pop.pre_path <= -5]
        sub_g1, sub_rest = sub[sub.is_g1], sub[~sub.is_g1]
        print("    [pre_path<=-5%子組(V5原加分層)]")
        a = stat(sub_g1.v5_net / 100, "G1的V5(前段跌)   ")
        b = stat(sub_rest.v5_net / 100, "非G1的V5(前段跌) ")
        if a is not None and b is not None:
            print(f"      中位差(G1-非G1): {(a.median() - b.median()) * 100:+.2f}pp")
        # 事前可執行性: giveback在V5進場(倒數第3日收盤)之前=買之前就看得到,可真否決
        # (上面的G1 vs 非G1含事後資訊: 吐回若發生在進場後,分類完成時已持倉,只能停損不能否決)
        if len(g1v):
            pre = g1v.gb_before_v5entry.eq(True)  # NaN視為False,避免fillna downcast警告
            g1_pre, g1_post = g1v[pre], g1v[~pre]
            print(f"    可執行性: G1中吐回發生在V5進場前(事前可否決)={len(g1_pre)}筆 / "
                  f"進場後(只能改停損)={len(g1_post)}筆")
            stat(g1_pre.v5_net / 100, "  進場前已吐回(事前可否決)的V5 ")
            stat(g1_post.v5_net / 100, "  進場後才吐回(不可否決)的V5   ")
            exante_surv = pop[~pop.event_id.isin(g1_pre.event_id)]
            sv = exante_surv.v5_net / 100
            print(f"    事前可執行版否決(只刪吐回在進場前的{len(g1_pre)}筆): "
                  f"剩餘池 中位{sv.median() * 100:+.2f}% 勝率{(sv > 0).mean() * 100:.0f}% n={len(sv):,}")
            bail = g1v.v5_bail_net.dropna() / 100
            hold = g1v.loc[g1v.v5_bail_net.notna(), "v5_net"] / 100
            if len(bail) >= 10:
                print(f"    進場後才吐回者: 吐回日收盤停損 中位{bail.median() * 100:+.2f}% vs "
                      f"抱到出關開盤 中位{hold.median() * 100:+.2f}% (n={len(bail)}) "
                      f"=> 停損{'較好' if bail.median() > hold.median() else '較差'}")
        print()

    # ================= 與candle_fade吐回黑K訊號的重疊 =================
    if gb_black_days:
        print("=" * 70)
        print("與earlier candle_fade「吐回長黑」日訊號(class_A黑且前日紅)的重疊(headline G1)")
        print("=" * 70)
        for mm in ["5", "20"]:
            pop = evc[evc.match_min == mm]
            g1 = pop[pop[hl_col] == "G1"]
            if not len(g1):
                continue
            in_ev = g1.event_id.isin(gb_black_events)
            gb_is_candle = g1.apply(lambda r: (r.event_id, r.gb_date) in gb_black_days
                                    if pd.notna(r.gb_date) else False, axis=1)
            ev_all = set(pop.event_id)
            candle_ev_here = gb_black_events & ev_all
            g1set = set(g1.event_id)
            print(f"-- match_min={mm} --")
            print(f"    G1事件n={len(g1)}: 窗內含candle吐回黑K日={in_ev.mean() * 100:.0f}%  "
                  f"G1的gb日本身就是candle吐回黑K日={gb_is_candle.mean() * 100:.0f}%")
            if candle_ev_here:
                print(f"    反向: 含candle吐回黑K日的事件n={len(candle_ev_here)},其中被本研究標G1="
                      f"{len(candle_ev_here & g1set) / len(candle_ev_here) * 100:.0f}%"
                      f" (兩訊號重疊度;G1另要求run-up>=+8%結束在末5日,candle訊號只要求前日>=+5%)")


if __name__ == "__main__":
    main()
