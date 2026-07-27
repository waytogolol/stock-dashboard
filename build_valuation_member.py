# -*- coding: utf-8 -*-
"""
題材估值第三場: 個股層同儕橫斷位階 (2026-07-28使用者裁示「個股對同儕的橫斷位階可以開」)
========================================================================
問題: 同一題材內,比同儕便宜的成員是否跑贏比同儕貴的成員?(法人挑股是在題材內部挑=使用者V2的個股層)
口徑: 成員月末PER在「同題材當月同儕」中的橫斷百分位(cs_pctl,低=比同儕便宜;同儕有效數>=5);
  結果變數=成員fwd2m「減同題材當月中位」(within-theme demeaned=純同儕相對alpha,題材效果全剝掉);
預註冊:
  C1 全域: 題材內最便宜1/3 vs 最貴1/3 的demeaned fwd2m差(假說=便宜貏贏)
  C2 營收強題材內(theme yoy前1/3): 同上(使用者「營收好的修正到合理PE法人介入」的個股版)
  C3 款6風味(描述性): 成員PER>60(官方款6門檻風味) 的demeaned fwd2m(注意股研究=極端估值有毒,這裡看常態情境)
判準: demeaned中位/勝率/cluster bootstrap(按題材)/年度分層。警語: E修正混淆/虧損股不在面板/觀察層。
用法: python build_valuation_member.py  (先跑過 build_valuation_theme.py)
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


def main():
    con = sqlite3.connect(DB)
    cl = pd.read_sql("SELECT DISTINCT code, main_group FROM classification WHERE country='台'", con)
    codes = sorted(cl.code.unique())
    ph = ",".join("?" * len(codes))
    per = pd.read_sql(f"SELECT code, date, per FROM per_daily WHERE code IN ({ph})", con, params=codes)
    px = pd.read_sql(f"SELECT code, date, close FROM fm_daily_price WHERE code IN ({ph}) "
                     "AND date>='2017-06-01'", con, params=codes)
    con.close()

    per["m"] = per.date.str[:7]
    pem = per.sort_values("date").groupby(["code", "m"]).per.last().reset_index()
    pem.loc[pem.per <= 0, "per"] = np.nan
    px["m"] = px.date.str[:7]
    pxm = px.sort_values("date").groupby(["code", "m"]).close.last().reset_index()
    wide = pxm.pivot_table(index="m", columns="code", values="close").sort_index()
    mret = wide.pct_change(fill_method=None) * 100
    fwd2 = ((1 + mret.shift(-1) / 100) * (1 + mret.shift(-2) / 100) - 1) * 100

    rows = []
    pem_j = pem.merge(cl, on="code")
    for (g, m), s in pem_j.groupby(["main_group", "m"]):
        v = s.dropna(subset=["per"])
        if len(v) < 5 or m not in fwd2.index:
            continue
        v = v.copy()
        v["cs_pctl"] = v.per.rank(pct=True) * 100      # 低=比同儕便宜
        fr = fwd2.loc[m]
        v["f2"] = v.code.map(fr)
        v = v.dropna(subset=["f2"])
        if len(v) < 5:
            continue
        med = v.f2.median()
        for r in v.itertuples():
            rows.append({"main_group": g, "m": m, "code": r.code, "per": r.per,
                         "cs_pctl": r.cs_pctl, "dm": r.f2 - med})
    mb = pd.DataFrame(rows)
    mb = mb[mb.m >= "2018-01"]
    mb.to_pickle("tmp_valuation_member_panel.pkl")
    print(f"成員面板: {len(mb):,}成員-月 / {mb.main_group.nunique()}題材 / {mb.m.nunique()}月 "
          f"({mb.m.min()}~{mb.m.max()})")
    R = {"n": len(mb)}

    def boot_diff(a, b, label):
        """a,b=兩組(成員-月rows), demeaned中位差, cluster bootstrap按題材"""
        themes = mb.main_group.unique()
        ag = {t: s.dm.values for t, s in a.groupby("main_group")}
        bg = {t: s.dm.values for t, s in b.groupby("main_group")}
        obs = np.median(a.dm.values) - np.median(b.dm.values)
        ds = []
        for _ in range(N_BOOT):
            pick = rng.choice(themes, len(themes), replace=True)
            aa = [ag[t] for t in pick if t in ag]
            bb = [bg[t] for t in pick if t in bg]
            if not aa or not bb:
                continue
            aa, bb = np.concatenate(aa), np.concatenate(bb)
            if len(aa) < 30 or len(bb) < 30:
                continue
            ds.append(np.median(aa) - np.median(bb))
        lo, hi = np.percentile(ds, [2.5, 97.5]) if ds else (np.nan, np.nan)
        ys = []
        for y in sorted(a.m.str[:4].unique()):
            ay, by = a[a.m.str[:4] == y], b[b.m.str[:4] == y]
            if len(ay) >= 30 and len(by) >= 30:
                ys.append(np.sign(np.median(ay.dm.values) - np.median(by.dm.values)))
        ystr = f"{sum(1 for s_ in ys if s_ > 0)}/{len(ys)}年正"
        sig = "◄排0" if (lo > 0 or hi < 0) else "含0"
        print(f"{label}: 便宜組n={len(a):,} demeaned中位{np.median(a.dm.values):+.2f}% / "
              f"貴組n={len(b):,} {np.median(b.dm.values):+.2f}% | diff={obs:+.2f}pp "
              f"CI[{lo:+.2f},{hi:+.2f}]{sig} | {ystr}")
        return {"n_cheap": len(a), "n_exp": len(b), "diff": round(float(obs), 2),
                "ci": [round(float(lo), 2), round(float(hi), 2)], "yearly": ystr}

    # C1 全域: 最便宜1/3 vs 最貴1/3
    R["C1"] = boot_diff(mb[mb.cs_pctl <= 33.3], mb[mb.cs_pctl >= 66.7], "C1全域_便宜1/3 vs 貴1/3")

    # C2 營收強題材內
    th = pd.read_pickle("tmp_valuation_panel.pkl")
    yq2 = th.dropna(subset=["yoy"]).yoy.quantile(2 / 3)
    strong = set(map(tuple, th[th.yoy >= yq2][["main_group", "m"]].values))
    mbs = mb[mb.apply(lambda r: (r.main_group, r.m) in strong, axis=1)]
    R["C2"] = boot_diff(mbs[mbs.cs_pctl <= 33.3], mbs[mbs.cs_pctl >= 66.7],
                        "C2營收強題材內_便宜1/3 vs 貴1/3")

    # C3 款6風味(描述): PER>60成員 vs 其餘
    R["C3"] = boot_diff(mb[mb.per > 60], mb[mb.per <= 60], "C3描述_PER>60 vs 其餘")

    # 五分位形狀(描述)
    print("\n同儕位階五分位×demeaned fwd2m(描述性):")
    R["quintiles"] = []
    for lo_, hi_ in [(0, 20), (20, 40), (40, 60), (60, 80), (80, 101)]:
        s = mb[(mb.cs_pctl >= lo_) & (mb.cs_pctl < hi_)]
        row = {"bin": f"{lo_}-{min(hi_, 100)}", "n": len(s),
               "dm": round(float(np.median(s.dm.values)), 2),
               "win": round(float((s.dm > 0).mean() * 100), 0)}
        R["quintiles"].append(row)
        print(f"  同儕位階{lo_:3d}-{min(hi_, 100):3d}: n={len(s):6,} demeaned{row['dm']:+6.2f}% 勝{row['win']:.0f}%")

    with open("tmp_valuation_member_results.json", "w", encoding="utf-8") as f:
        json.dump(R, f, ensure_ascii=False, indent=1, default=str)
    print("\n完成: tmp_valuation_member_panel.pkl / tmp_valuation_member_results.json")


if __name__ == "__main__":
    main()
