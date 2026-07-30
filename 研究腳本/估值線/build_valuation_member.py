# -*- coding: utf-8 -*-
"""
題材估值第三場: 個股層同儕橫斷位階 (2026-07-28使用者裁示開工;同日追問「持有多久?1/2/3個月?」加掃持有期網格)
========================================================================
問題: 同一題材內,比同儕便宜的成員是否跑贏比同儕貴的成員?(法人挑股是在題材內部挑=使用者V2的個股層)
口徑: 成員月末PER在「同題材當月同儕」中的橫斷百分位(cs_pctl,低=比同儕便宜;同儕有效數>=5);
  結果變數=成員fwd「減同題材當月中位」(within-theme demeaned=純同儕相對alpha,題材效果全剝掉);
  持有期網格=1/2/3/6個月(2026-07-28加,原版只考2月)。
預註冊:
  C1 全域: 題材內最便宜1/3 vs 最貴1/3 的demeaned差(假說=便宜跑贏)
  C2 營收強題材內(theme yoy前1/3): 同上(使用者「營收好的修正到合理PE法人介入」的個股版)
  C3 款6風味(描述性): 成員PER>60 的demeaned(注意股研究=極端估值有毒,這裡看常態情境)
判準: demeaned中位/cluster bootstrap(按題材)/年度分層。警語: E修正混淆/虧損股不在面板/觀察層。
用法: python build_valuation_member.py  (先跑過 build_valuation_theme.py)
"""
import json
import sqlite3
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
DB = "capital_flow.db"
N_BOOT = 1500
HS = (1, 2, 3, 6)
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
    fwd = {}
    for h in HS:
        acc = None
        for k in range(1, h + 1):
            f = 1 + mret.shift(-k) / 100
            acc = f if acc is None else acc * f
        fwd[h] = (acc - 1) * 100

    rows = []
    pem_j = pem.merge(cl, on="code")
    for (g, m), s in pem_j.groupby(["main_group", "m"]):
        v = s.dropna(subset=["per"])
        if len(v) < 5 or m not in mret.index:
            continue
        v = v.copy()
        v["cs_pctl"] = v.per.rank(pct=True) * 100      # 低=比同儕便宜
        rec = {}
        ok = True
        for h in HS:
            fr = fwd[h].loc[m]
            vals = v.code.map(fr)
            if h == 2 and vals.dropna().shape[0] < 5:
                ok = False
                break
            med = vals.median()
            rec[h] = vals - med
        if not ok:
            continue
        for i, r in enumerate(v.itertuples()):
            row = {"main_group": g, "m": m, "code": r.code, "per": r.per, "cs_pctl": r.cs_pctl}
            for h in HS:
                row[f"dm{h}"] = rec[h].iloc[i]
            rows.append(row)
    mb = pd.DataFrame(rows)
    mb = mb[mb.m >= "2018-01"]
    mb.to_pickle("tmp_valuation_member_panel.pkl")
    print(f"成員面板: {len(mb):,}成員-月 / {mb.main_group.nunique()}題材 / {mb.m.nunique()}月 "
          f"({mb.m.min()}~{mb.m.max()})")
    R = {"n": len(mb)}

    def boot_diff(a, b, col, label):
        a2, b2 = a.dropna(subset=[col]), b.dropna(subset=[col])
        themes = mb.main_group.unique()
        ag = {t: s[col].values for t, s in a2.groupby("main_group")}
        bg = {t: s[col].values for t, s in b2.groupby("main_group")}
        obs = np.median(a2[col].values) - np.median(b2[col].values)
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
        for y in sorted(a2.m.str[:4].unique()):
            ay, by = a2[a2.m.str[:4] == y], b2[b2.m.str[:4] == y]
            if len(ay) >= 30 and len(by) >= 30:
                ys.append(np.sign(np.median(ay[col].values) - np.median(by[col].values)))
        ystr = f"{sum(1 for s_ in ys if s_ > 0)}/{len(ys)}年正"
        sig = "◄排0" if (lo > 0 or hi < 0) else "含0"
        print(f"  {label} {col}: diff={obs:+.2f}pp CI[{lo:+.2f},{hi:+.2f}]{sig} {ystr} "
              f"(便宜n={len(a2):,}/貴n={len(b2):,})")
        return {"diff": round(float(obs), 2), "ci": [round(float(lo), 2), round(float(hi), 2)],
                "yearly": ystr}

    print("\nC1 全域: 題材內便宜1/3 vs 貴1/3 (持有期網格):")
    R["C1"] = {f"dm{h}": boot_diff(mb[mb.cs_pctl <= 33.3], mb[mb.cs_pctl >= 66.7], f"dm{h}", "C1")
               for h in HS}

    th = pd.read_pickle("tmp_valuation_panel.pkl")
    yq2 = th.dropna(subset=["yoy"]).yoy.quantile(2 / 3)
    strong = set(map(tuple, th[th.yoy >= yq2][["main_group", "m"]].values))
    key = mb.main_group + "|" + mb.m
    skey = {f"{g}|{m}" for g, m in strong}
    mbs = mb[key.isin(skey)]
    print("\nC2 營收強題材內 (持有期網格):")
    R["C2"] = {f"dm{h}": boot_diff(mbs[mbs.cs_pctl <= 33.3], mbs[mbs.cs_pctl >= 66.7], f"dm{h}", "C2")
               for h in HS}

    print("\nC3 描述: PER>60 vs 其餘 (持有期網格):")
    R["C3"] = {f"dm{h}": boot_diff(mb[mb.per > 60], mb[mb.per <= 60], f"dm{h}", "C3")
               for h in HS}

    with open("tmp_valuation_member_results.json", "w", encoding="utf-8") as f:
        json.dump(R, f, ensure_ascii=False, indent=1, default=str)
    print("\n完成: tmp_valuation_member_panel.pkl / tmp_valuation_member_results.json")


if __name__ == "__main__":
    main()
