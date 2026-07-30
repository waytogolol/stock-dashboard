# -*- coding: utf-8 -*-
"""處置 × 外資位階(S4外資流20日累計percentile)條件化研究(2026-07-24預註冊;本批配對測試最終題)
假說: V4處置交易(第3處置日收盤買→出關日開盤出,已驗證+3.78%/62%)在進場時該股「外資位階」高
=> 表現更好。機制: 處置=監理沖洗投機客;外資/知情資金在沖洗中持續買超=聰明錢確認——
與處置週期本身是獨立機制族。相鄰證據(昨日): TDCC千張大戶4週流向d4w最高三分位雙層通過
(+2.87pp mm5 / +3.68pp mm20, LOTO 8/8+bootstrap);TDCC LEVEL百分位全滅。外資位階本質是
「流向百分位」(20日累計外資買賣超 vs 自身240日歷史),站在flow那一側——但誠實測,不預設。

設計(預註冊):
- 母體: 重用tmp_disposition_tdcc_panel.pkl(2,966事件,event_id口徑=disposition
  dropna(start,end).reset_index;已含v4_net/v4_valid/d4w/pre_turnover/post5-20);
  match_min '5'/'20'分層永不合併
- 特徵: inst_flow(TWSE上市限定,2022-01+)照S4正典規約(封存/研究腳本歸檔/tmp_portfolio_report.py):
  code限^[1-9]\\d{3}$ → pivot foreign_net → rolling(20,min10).sum() → rolling(240,min120).rank(pct)*100
- 取樣(無前視): 進場日=第3處置交易日(V4買點,c[s+2]同日),取「嚴格早於進場日」的最後一個
  特徵日(=前一TWSE交易日);進場日晚於特徵資料末日=作廢(資料未完整,不硬湊)
- sanity: 儀表板chip徽章錨點(2026-07-17: 2603≈92 / 2324≈65 / 8462≈100,容差±2)
- 覆蓋優先: inst_flow=上市限定2022+,處置宇宙上櫃為主 => 先報逐層逐年覆蓋率+選擇效應檢查
  (同窗覆蓋vs未覆蓋的V4基線),覆蓋子樣本小或偏斜就對應封頂結論
- 分析: ①V4按位階四分位(固定切點25/50/75)+>=80二元,LOTO(2022+約5年群,報逐年符號)
  +年群bootstrap(B=10000,seed=42) ②出關後post5/10/20同切分 ③與d4w冗餘(關鍵題):
  覆蓋子樣本內Spearman(位階,d4w)+2x2(位階高低×d4w最高三分位)V4中位——外資位階對d4w
  是加成、冗餘、還是支配? ④與規模冗餘: Spearman(位階, log處置前20日中位成交值)+規模三分位內差
用法: python -X utf8 build_disposition_foreign.py  (Windows終端機cp950易炸)
"""
import sqlite3
import sys
import time

import numpy as np
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DB = "capital_flow.db"
PANEL_IN = "tmp_disposition_tdcc_panel.pkl"      # 已含v4_net/v4_valid/d4w/pre_turnover/post5-20
PANEL_XCHK = "tmp_disposition_exit_fade_panel.pkl"  # post欄位交叉驗證用
PANEL_OUT = "tmp_disposition_foreign_panel.pkl"
HI_TH = 80.0          # house慣例高位階
B_BOOT = 10000
SEED = 42
POST_KS = [5, 10, 20]
SANITY_DATE = "2026-07-17"
SANITY_TOL = 2.0
SANITY = {"2603": 92.0, "2324": 65.0, "8462": 100.0}  # 儀表板chip f值錨點
QS = ["Q1", "Q2", "Q3", "Q4"]


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
    yr_parts = []  # 逐年within差(任務書要求報逐年符號)
    for yr in years:
        sy = sig.loc[sig[year_col] == yr, val_col]
        cy = ctl.loc[ctl[year_col] == yr, val_col]
        if len(sy) >= 5 and len(cy) >= 5:
            yr_parts.append(f"{yr}:{(sy.median() - cy.median()) * 100:+.2f}pp(n={len(sy)}/{len(cy)})")
        else:
            yr_parts.append(f"{yr}:n不足({len(sy)}/{len(cy)})")
    print("      逐年within差: " + "  ".join(yr_parts))
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


def compute_entry_dates(disp, px_dates):
    """V4進場日=第3處置交易日(口徑同compute_v4的c[s+2]),逐event_id回傳日期。"""
    out = {}
    for ev_id, e in disp.iterrows():
        dts = px_dates.get(e.code)
        if dts is None:
            continue
        s = int(np.searchsorted(dts, np.datetime64(e.start_date)))
        if s + 2 < len(dts):
            out[ev_id] = pd.Timestamp(dts[s + 2])
    return out


def compute_foreign_feature(panel, fpct):
    """每事件: 取嚴格早於entry_date的最後特徵日的外資位階(=前一TWSE交易日,無前視)。"""
    dts = fpct.index.values.astype("datetime64[D]")
    cols = {c: fpct[c].values for c in fpct.columns}
    rows = []
    for r in panel.itertuples():
        rec = {"event_id": r.event_id, "fp_date": pd.NaT, "fp_lag": np.nan,
               "fpr": np.nan, "fp_reason": ""}
        if pd.isna(r.entry_date):
            rec["fp_reason"] = "無進場日"
        elif r.code not in cols:
            rec["fp_reason"] = "非上市宇宙"
        else:
            ent = np.datetime64(r.entry_date.date())
            if ent > dts[-1]:
                rec["fp_reason"] = "特徵資料末日之後"
            else:
                idx = int(np.searchsorted(dts, ent, side="left") - 1)
                if idx < 0:
                    rec["fp_reason"] = "特徵起始日之前"
                else:
                    rec["fp_date"] = pd.Timestamp(dts[idx])
                    rec["fp_lag"] = int((ent - dts[idx]).astype(int))
                    v = cols[r.code][idx]
                    if np.isfinite(v):
                        rec["fpr"] = float(v)
                        rec["fp_reason"] = "ok"
                    else:
                        rec["fp_reason"] = "歷史不足NaN"
        rows.append(rec)
    return pd.DataFrame(rows)


def sanity_chip(fpct):
    print("=" * 70)
    print(f"SANITY CHECK: 儀表板chip錨點({SANITY_DATE}: 2603≈92 / 2324≈65 / 8462≈100, ±{SANITY_TOL:.0f})")
    print("=" * 70)
    all_ok = True
    for code, exp in SANITY.items():
        try:
            v = float(fpct.loc[SANITY_DATE, code])
        except KeyError:
            print(f"  !! {code}@{SANITY_DATE} 查無值,FAIL")
            all_ok = False
            continue
        ok = np.isfinite(v) and abs(v - exp) <= SANITY_TOL
        print(f"  {code}@{SANITY_DATE}: 位階={v:.1f} (exp {exp:.0f}) => {'PASS' if ok else 'FAIL'}")
        all_ok = all_ok and ok
    if all_ok:
        print("  >> PASS: S4正典規約重現儀表板徽章,可跑全母體。\n")
    else:
        print("  >> FAIL: 特徵管線與儀表板不一致,下方結果不可信任!\n")
    return all_ok


def main():
    disp = read_sql_retry("SELECT * FROM disposition")
    pxd = read_sql_retry("SELECT code, date FROM fm_daily_price ORDER BY code, date")
    fl = read_sql_retry("SELECT date, code, foreign_net FROM inst_flow")
    for c in ("announce_date", "start_date", "end_date"):
        disp[c] = pd.to_datetime(disp[c], errors="coerce")
    disp = disp.dropna(subset=["start_date", "end_date"]).reset_index(drop=True)  # event_id口徑
    pxd["date"] = pd.to_datetime(pxd["date"])
    px_dates = {c: g["date"].values for c, g in pxd.groupby("code")}

    panel = pd.read_pickle(PANEL_IN)
    chk = panel[["event_id", "code", "start_date"]].merge(
        disp[["code", "start_date"]].reset_index().rename(columns={"index": "event_id"}),
        on="event_id", suffixes=("_p", "_d"))
    mism = ((chk.code_p != chk.code_d) | (chk.start_date_p != chk.start_date_d)).sum()
    print(f"事件面板: {len(panel):,}筆(重用{PANEL_IN},保證V4/d4w數字與昨日tdcc考卷完全一致); "
          f"event_id對齊disposition口徑檢查: 不一致={mism}筆{'(PASS)' if mism == 0 else ' !!口徑錯位,中止'}")
    if mism:
        sys.exit(1)
    xf = pd.read_pickle(PANEL_XCHK)[["event_id", "post5", "post10", "post20"]]
    xm = panel[["event_id", "post5", "post10", "post20"]].merge(xf, on="event_id", suffixes=("", "_x"))
    bad = sum(int((~np.isclose(xm[f"post{k}"], xm[f"post{k}_x"], equal_nan=True)).sum()) for k in POST_KS)
    print(f"post5/10/20 vs {PANEL_XCHK} 交叉驗證: 不一致={bad}格{'(PASS)' if bad == 0 else ' !!中止'}")
    if bad:
        sys.exit(1)
    print(f"V4可交易n={panel.v4_valid.sum():,} (mm5={((panel.match_min == '5') & panel.v4_valid).sum():,} "
          f"/ mm20={((panel.match_min == '20') & panel.v4_valid).sum():,})")

    # 進場日(V4買點=第3處置交易日)
    panel["entry_date"] = panel.event_id.map(compute_entry_dates(disp, px_dates))
    n_noent = panel.entry_date.isna().sum()
    n_v4_noent = (panel.v4_valid & panel.entry_date.isna()).sum()
    print(f"進場日(第3處置交易日)可得n={panel.entry_date.notna().sum():,}; 缺={n_noent}"
          f"(其中v4_valid卻缺={n_v4_noent},預期0)")

    # S4正典外資位階(上市限定2022+)
    fl = fl[fl.code.str.match(r"^[1-9]\d{3}$")]
    fl["date"] = pd.to_datetime(fl.date)
    fpct = (fl.pivot_table(index="date", columns="code", values="foreign_net")
            .rolling(20, min_periods=10).sum()
            .rolling(240, min_periods=120).rank(pct=True) * 100)
    feat_start = fpct.dropna(how="all").index.min()
    print(f"inst_flow: {fl.date.min().date()}~{fl.date.max().date()} {fl.code.nunique():,}檔(4碼上市); "
          f"位階首個有效日={feat_start.date()}(rolling 20+240 min_periods暖機)\n")

    ok = sanity_chip(fpct)

    feat = compute_foreign_feature(panel, fpct)
    panel = panel.merge(feat, on="event_id", how="left")
    panel.to_pickle(PANEL_OUT)
    print(f"特徵面板存 {PANEL_OUT}\n")

    # ================= 覆蓋/選擇效應(先於一切分析) =================
    print("=" * 70)
    print("覆蓋診斷(inst_flow=上市限定2022+,處置宇宙上櫃為主 => 覆蓋先講清楚)")
    print("=" * 70)
    v4p = panel[panel.v4_valid]
    for mm in ["5", "20"]:
        t = v4p[v4p.match_min == mm]
        cov = t.fpr.notna()
        print(f"  match_min={mm}: V4可交易n={len(t):,} 特徵有效n={cov.sum():,}({cov.mean() * 100:.1f}%)")
        print("    逐年(事件start年): " + "  ".join(
            f"{y}:{g.fpr.notna().sum()}/{len(g)}({g.fpr.notna().mean() * 100:.0f}%)"
            for y, g in t.groupby("y")))
        rs = t.loc[~cov, "fp_reason"].value_counts()
        print("    未覆蓋原因: " + "  ".join(f"{k}={v}" for k, v in rs.items()))
        mk = t[cov].market.value_counts()
        print("    覆蓋事件市場別: " + "  ".join(f"{k}={v}" for k, v in mk.items()))
    # 選擇效應: 同窗(entry>=特徵首個有效日)覆蓋vs未覆蓋的V4基線
    print("  -- 選擇效應檢查(entry>=位階首個有效日的同窗比較;未覆蓋≈上櫃+歷史不足) --")
    elig = v4p[v4p.entry_date.notna() & (v4p.entry_date >= feat_start)].copy()
    elig["v4d"] = elig.v4_net / 100
    for mm in ["5", "20"]:
        t = elig[elig.match_min == mm]
        a = stat(t.loc[t.fpr.notna(), "v4d"], f"mm{mm} 同窗覆蓋(上市)")
        b = stat(t.loc[t.fpr.isna(), "v4d"], f"mm{mm} 同窗未覆蓋")
        if a is not None and b is not None:
            print(f"      基線差(覆蓋-未覆蓋): {(a.median() - b.median()) * 100:+.2f}pp "
                  f"(≠0=覆蓋子樣本有選擇偏差,條件化結論僅限上市2022+)")
        mk = t[t.fpr.isna()].market.value_counts()
        print("      同窗未覆蓋市場別: " + "  ".join(f"{k}={v}" for k, v in mk.items()))
    # 覆蓋事件的位階分布(處置股是不是天生外資高/低位階?)
    for mm in ["5", "20"]:
        f = panel[(panel.match_min == mm) & panel.v4_valid & panel.fpr.notna()].fpr
        if len(f):
            print(f"  mm{mm} 覆蓋事件位階分布: 中位{f.median():.0f} 均值{f.mean():.0f} "
                  f">=80占{(f >= HI_TH).mean() * 100:.0f}% <=20占{(f <= 20).mean() * 100:.0f}% (n={len(f)})")
    print()

    if not ok:
        print("!! sanity FAIL,僅輸出覆蓋統計,不跑分析")
        sys.exit(1)

    evc = panel[~panel.truncated].copy()  # post端只用完整窗
    for mm in ["5", "20"]:
        pop = panel[(panel.match_min == mm) & panel.v4_valid & panel.fpr.notna()].copy()
        popc = evc[(evc.match_min == mm) & evc.fpr.notna()].copy()
        for df_ in (pop, popc):
            df_["qf"] = pd.cut(df_.fpr, bins=[-0.01, 25, 50, 75, 100.01], labels=QS, right=False)
            df_["hif"] = df_.fpr >= HI_TH
            df_["v4d"] = df_.v4_net / 100
        print("#" * 70)
        print(f"## match_min={mm}  V4可交易且位階有效 n={len(pop):,} / post端(不截斷)n={len(popc):,}")
        print(f"##   (覆蓋=上市2022H2+,樣本{'小,結論封頂為候補觀察' if len(pop) < 100 else '尚可,仍僅限上市2022+口徑'})")
        print("#" * 70)

        print("\n== 分析1: V4條件化(主戰場) ==")
        stat(pop.v4d, "覆蓋子樣本V4基線")
        bucket_table(pop, "qf", QS, ["v4d"], "外資位階四分位(固定切點25/50/75)")
        print("  -- 高vs其餘(二元, LOTO+年群bootstrap) --")
        hi, rest = pop[pop.hif], pop[~pop.hif]
        a = stat(hi.v4d, "位階>=80 高組")
        b = stat(rest.v4d, "位階>=80 其餘")
        if a is not None and b is not None:
            print(f"      中位差(高-餘): {(a.median() - b.median()) * 100:+.2f}pp")
        loto_bootstrap_diff(hi, rest, "v4d", "y", f"{mm}分盤V4 位階>=80高-餘")

        print("\n== 分析2: 出關後條件化(post5/10/20,窗末收盤起算) ==")
        pk = [f"post{k}" for k in POST_KS]
        bucket_table(popc, "qf", QS, pk, "外資位階四分位")
        print("  -- 高vs其餘(二元, LOTO+年群bootstrap) --")
        hic, restc = popc[popc.hif], popc[~popc.hif]
        for k in POST_KS:
            a = stat(hic[f"post{k}"], f"位階>=80 高組 post{k}")
            b = stat(restc[f"post{k}"], f"位階>=80 其餘 post{k}")
            if a is not None and b is not None:
                print(f"      中位差(高-餘): {(a.median() - b.median()) * 100:+.2f}pp")
            loto_bootstrap_diff(hic, restc, f"post{k}", "y", f"{mm}分盤post{k} 位階>=80高-餘")

        print("\n== 分析3: 與d4w冗餘/交互(關鍵題: 加成、冗餘、還是支配?) ==")
        sub = pop[pop.d4w.notna()].copy()
        print(f"  覆蓋子樣本內d4w同時有效 n={len(sub)}")
        if len(sub) >= 30:
            print(f"    Spearman(外資位階, d4w) = {sub.fpr.corr(sub.d4w, method='spearman'):+.3f}")
            rk = sub.d4w.rank(pct=True)
            sub["d4w_t3"] = rk > 2 / 3
            # 先複驗d4w在此覆蓋子樣本是否仍有效(昨日結論是全tdcc宇宙2019+口徑)
            print("    -- 參照: d4w最高三分位效應在覆蓋子樣本(上市2022+)內複驗 --")
            a = stat(sub.loc[sub.d4w_t3, "v4d"], "d4w T3")
            b = stat(sub.loc[~sub.d4w_t3, "v4d"], "d4w 其餘")
            if a is not None and b is not None:
                print(f"      中位差: {(a.median() - b.median()) * 100:+.2f}pp")
            loto_bootstrap_diff(sub[sub.d4w_t3], sub[~sub.d4w_t3], "v4d", "y", f"{mm}分盤覆蓋內d4w T3-餘")
            print("    -- 2x2(位階>=80 × d4w最高三分位) V4 --")
            for fl_, fn in ((True, "位階高"), (False, "位階餘")):
                for dl, dn in ((True, "d4w T3"), (False, "d4w餘")):
                    stat(sub.loc[(sub.hif == fl_) & (sub.d4w_t3 == dl), "v4d"], f"{fn}∧{dn}")
            print("    -- 條件邊際(誰在誰之上仍有增量) --")
            for cond_mask, cond_lab in ((sub.d4w_t3, "d4w T3內"), (~sub.d4w_t3, "d4w餘內")):
                cc = sub[cond_mask]
                a = stat(cc.loc[cc.hif, "v4d"], f"{cond_lab} 位階高")
                b = stat(cc.loc[~cc.hif, "v4d"], f"{cond_lab} 位階餘")
                if a is not None and b is not None:
                    print(f"      中位差(位階高-餘|{cond_lab}): {(a.median() - b.median()) * 100:+.2f}pp")
                if (cc.hif.sum() >= 15) and ((~cc.hif).sum() >= 15):
                    loto_bootstrap_diff(cc[cc.hif], cc[~cc.hif], "v4d", "y", f"{mm}分盤{cond_lab}位階高-餘")
            for cond_mask, cond_lab in ((sub.hif, "位階高內"), (~sub.hif, "位階餘內")):
                cc = sub[cond_mask]
                a = stat(cc.loc[cc.d4w_t3, "v4d"], f"{cond_lab} d4w T3")
                b = stat(cc.loc[~cc.d4w_t3, "v4d"], f"{cond_lab} d4w餘")
                if a is not None and b is not None:
                    print(f"      中位差(d4w T3-餘|{cond_lab}): {(a.median() - b.median()) * 100:+.2f}pp")
                if (cc.d4w_t3.sum() >= 15) and ((~cc.d4w_t3).sum() >= 15):
                    loto_bootstrap_diff(cc[cc.d4w_t3], cc[~cc.d4w_t3], "v4d", "y", f"{mm}分盤{cond_lab}d4w T3-餘")
            # >=80格太小時的備援視角: 位階中位切2x2
            if sub.hif.sum() < 15:
                med = sub.fpr.median()
                sub["hif_med"] = sub.fpr >= med
                print(f"    -- 備援2x2(>=80格太小): 位階中位切{med:.0f} × d4w T3 --")
                for fl_, fn in ((True, f"位階>={med:.0f}"), (False, f"位階<{med:.0f}")):
                    for dl, dn in ((True, "d4w T3"), (False, "d4w餘")):
                        stat(sub.loc[(sub.hif_med == fl_) & (sub.d4w_t3 == dl), "v4d"], f"{fn}∧{dn}")
        else:
            print("    n<30,交互分析不可跑(僅報數)")

        print("\n== 分析4: 與規模冗餘(位階是不是胃納量換皮; 規模代理=處置前20日中位成交值) ==")
        rc = pop.dropna(subset=["pre_turnover"]).copy()
        if len(rc) >= 30:
            logtv = np.log10(rc.pre_turnover)
            print(f"    Spearman(外資位階, log成交值) = {rc.fpr.corr(logtv, method='spearman'):+.3f} (n={len(rc)})")
            rc["size_ter"] = pd.cut(logtv.rank(pct=True), bins=[-0.01, 1 / 3, 2 / 3, 1.01],
                                    labels=["小", "中", "大"])
            print("    成交值三分位內 位階>=80高-餘 V4中位差(若效應是規模換皮,控規模後應消失):")
            for st in ["小", "中", "大"]:
                cc = rc[rc.size_ter == st]
                hi_, rest_ = cc[cc.hif], cc[~cc.hif]
                if len(hi_) >= 15 and len(rest_) >= 15:
                    print(f"      {st}: 高{hi_.v4d.median() * 100:+.2f}%(n={len(hi_)}) "
                          f"餘{rest_.v4d.median() * 100:+.2f}%(n={len(rest_)}) "
                          f"差{(hi_.v4d.median() - rest_.v4d.median()) * 100:+.2f}pp")
                else:
                    print(f"      {st}: n不足(高{len(hi_)}/餘{len(rest_)})")
        else:
            print("    n<30,略過")
        print()


if __name__ == "__main__":
    main()
