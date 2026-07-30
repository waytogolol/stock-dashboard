# -*- coding: utf-8 -*-
"""
題材估值第二場: 龍頭PE定義 × 贏家指紋逆推 (2026-07-28使用者雙提案)
========================================================================
A考卷「龍頭定義」: 題材PE改用龍頭(近3月成交額前3大成員)的正PER中位定義,位階重算,複測便宜格。
  機制假說=法人先定價龍頭、龍頭PE最乾淨(流動性+分析師覆蓋,E的估計可靠);對照全成員中位版誰更利。
B考卷「成功案例逆推」: H1(2019-2022)取贏家(fwd2m前10%題材-月)做特徵指紋(標準化差=贏家中位-其餘中位/全體std),
  取最強前2特徵在H1凍結閾值(贏家中位數)→ H2(2023-2026)樣本外驗證。方法論同跌觸發贏家指紋(研究紀錄㉘),
  「先找後驗」防倒果為因變成事後諸葛;H2驗過才算數,H1內的指紋只是線索。
資料: tmp_valuation_panel.pkl(第一場面板)+per_daily+fm_daily_price成交額。警語沿用第一場(E修正/倖存者偏差/觀察層)。
用法: python build_valuation_leader.py   (先跑過 build_valuation_theme.py)
"""
import json
import sqlite3
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
DB = "capital_flow.db"
N_BOOT = 2000
rng = np.random.default_rng(20260728)


def boot(cell_vals_by_theme, base_vals_by_theme, themes):
    cg = {t: v for t, v in cell_vals_by_theme.items() if len(v)}
    if not cg:
        return np.nan, np.nan, np.nan
    obs = np.median(np.concatenate(list(cg.values()))) - \
        np.median(np.concatenate(list(base_vals_by_theme.values())))
    ds = []
    for _ in range(N_BOOT):
        pick = rng.choice(themes, len(themes), replace=True)
        ca = [cg[t] for t in pick if t in cg]
        if not ca:
            continue
        ca = np.concatenate(ca)
        if len(ca) < 5:
            continue
        ds.append(np.median(ca) - np.median(np.concatenate(
            [base_vals_by_theme[t] for t in pick if t in base_vals_by_theme])))
    lo, hi = np.percentile(ds, [2.5, 97.5]) if ds else (np.nan, np.nan)
    return obs, lo, hi


def cell_report(name, cell, base, R):
    if len(cell) < 20:
        print(f"{name}: n={len(cell)} 不足")
        R[name] = {"n": len(cell), "verdict": "n不足"}
        return
    themes = base.main_group.unique()
    out = {"n": len(cell), "fwd2m": round(float(cell.fwd2m.median()), 2),
           "win": round(float((cell.fwd2m > 0).mean() * 100), 0)}
    for col, tag in [("fwd2m", "abs"), ("fwd2x", "x")]:
        cv = {t: s[col].dropna().values for t, s in cell.groupby("main_group")}
        bv = {t: s[col].dropna().values for t, s in base.groupby("main_group")}
        o, lo, hi = boot(cv, bv, themes)
        out[f"diff_{tag}"] = round(float(o), 2)
        out[f"ci_{tag}"] = [round(float(lo), 2), round(float(hi), 2)]
    ys = []
    for y in sorted(cell.m.str[:4].unique()):
        c = cell[cell.m.str[:4] == y]
        b = base[base.m.str[:4] == y]
        if len(c) >= 3:
            ys.append(np.sign(c.fwd2m.median() - b.fwd2m.median()))
    out["yearly"] = f"{sum(1 for s in ys if s > 0)}/{len(ys)}年正"
    sa = "◄" if (out["ci_abs"][0] > 0 or out["ci_abs"][1] < 0) else " "
    sx = "◄" if (out["ci_x"][0] > 0 or out["ci_x"][1] < 0) else " "
    print(f"{name}: n={out['n']} 中位{out['fwd2m']:+.2f}%/勝{out['win']:.0f}% | "
          f"絕對{out['diff_abs']:+.2f}{out['ci_abs']}{sa} | 超額{out['diff_x']:+.2f}{out['ci_x']}{sx} | {out['yearly']}")
    R[name] = out


def main():
    pn = pd.read_pickle("快取/tmp_valuation_panel.pkl")
    con = sqlite3.connect(DB)
    cl = pd.read_sql("SELECT DISTINCT code, main_group FROM classification WHERE country='台'", con)
    codes = sorted(cl.code.unique())
    ph = ",".join("?" * len(codes))
    money = pd.read_sql(f"SELECT code, date, money FROM fm_daily_price WHERE code IN ({ph}) "
                        "AND date>='2017-06-01'", con, params=codes)
    per = pd.read_sql(f"SELECT code, date, per FROM per_daily WHERE code IN ({ph})", con, params=codes)
    con.close()

    # ── A考卷: 龍頭PE(近3月成交額前3成員) ──
    money["m"] = money.date.str[:7]
    mm = money.groupby(["code", "m"]).money.sum().reset_index()
    mm = mm.sort_values(["code", "m"])
    mm["amt3m"] = mm.groupby("code").money.transform(lambda s: s.rolling(3, min_periods=2).mean())
    mm = mm.merge(cl, on="code")
    per["m"] = per.date.str[:7]
    pem = per.sort_values("date").groupby(["code", "m"]).per.last().reset_index()
    pem.loc[pem.per <= 0, "per"] = np.nan
    j = mm.merge(pem, on=["code", "m"], how="left")
    lead_rows = []
    for (g, m), s in j.groupby(["main_group", "m"]):
        top3 = s.nlargest(3, "amt3m")
        v = top3.per.dropna()
        if len(v) >= 2:
            lead_rows.append({"main_group": g, "m": m, "leader_pe": float(v.median())})
    ld = pd.DataFrame(lead_rows).sort_values(["main_group", "m"])
    ld["leader_pctl"] = ld.groupby("main_group").leader_pe.transform(
        lambda s: s.expanding(18).rank(pct=True) * 100)
    pn = pn.merge(ld, on=["main_group", "m"], how="left")
    pn.to_pickle("快取/tmp_valuation_panel.pkl")

    base = pn.dropna(subset=["fwd2m", "fwd2x", "pe_pctl", "yoy"])
    baseL = base.dropna(subset=["leader_pctl"])
    corr = base[["pe_pctl", "leader_pctl"]].dropna().corr().iloc[0, 1]
    print(f"A考卷: 龍頭PE覆蓋{len(ld)}題材-月; 龍頭位階vs全員位階相關={corr:.2f}")
    R = {"corr_leader_full": round(float(corr), 2)}
    print("\n便宜格對決(全員中位版 vs 龍頭版):")
    cell_report("全員版_位階<=10", base[base.pe_pctl <= 10], base, R)
    cell_report("龍頭版_位階<=10", baseL[baseL.leader_pctl <= 10], baseL, R)
    cell_report("全員版_位階<=20", base[base.pe_pctl <= 20], base, R)
    cell_report("龍頭版_位階<=20", baseL[baseL.leader_pctl <= 20], baseL, R)
    # 分歧格(描述): 龍頭便宜但全員不便宜=法人只買龍頭? / 全員便宜但龍頭不便宜
    dv = baseL[(baseL.leader_pctl <= 20) & (baseL.pe_pctl > 40)]
    cell_report("分歧_龍頭便宜全員不便宜(描述)", dv, baseL, R)

    # ── B考卷: 贏家指紋(H1找/H2驗) ──
    print("\nB考卷: 贏家指紋逆推(H1=2019-2022找, H2=2023-2026驗)")
    feats = ["pe_pctl", "dpe3", "yoy", "acc", "leader_pctl"]
    fb = pn.dropna(subset=["fwd2m"]).copy()
    h1 = fb[fb.m < "2023-01"]
    h2 = fb[fb.m >= "2023-01"]
    thr = h1.fwd2m.quantile(0.9)
    win1 = h1[h1.fwd2m >= thr]
    rest1 = h1[h1.fwd2m < thr]
    print(f"H1贏家門檻fwd2m>={thr:.1f}% 贏家n={len(win1)}")
    fp = []
    for f in feats:
        w, r_, a = win1[f].dropna(), rest1[f].dropna(), h1[f].dropna()
        if len(w) < 30 or a.std() == 0:
            continue
        sd = (w.median() - r_.median()) / a.std()
        fp.append((f, sd, w.median(), r_.median()))
    fp.sort(key=lambda x: -abs(x[1]))
    R["fingerprint"] = [{"feat": f, "std_diff": round(float(sd), 3),
                         "win_med": round(float(wm), 2), "rest_med": round(float(rm), 2)}
                        for f, sd, wm, rm in fp]
    for f, sd, wm, rm in fp:
        print(f"  {f:14s} 標準化差{sd:+.3f} (贏家中位{wm:.1f} vs 其餘{rm:.1f})")

    # 凍結規則: 取前2特徵,閾值=H1贏家中位數方向側 → H2驗證
    print("\nH2樣本外驗證(規則=H1凍結,通過才算數):")
    for f, sd, wm, rm in fp[:2]:
        side = ">=" if sd > 0 else "<="
        rule = (h2[f] >= wm) if sd > 0 else (h2[f] <= wm)
        cell = h2[rule.fillna(False)]
        cell_report(f"H2驗_{f}{side}{wm:.1f}", cell, h2, R)

    with open("快取/tmp_valuation_leader_results.json", "w", encoding="utf-8") as f:
        json.dump(R, f, ensure_ascii=False, indent=1, default=str)
    print("\n完成: tmp_valuation_leader_results.json (面板已加leader_pe/leader_pctl欄)")


if __name__ == "__main__":
    main()
