# -*- coding: utf-8 -*-
"""
題材估值考卷第一場: PE位階 × 營收動能 (2026-07-27使用者裁示開工,fetch_per.py資料當日回補完成)
========================================================================
機制假說(使用者原話轉譯,跑之前預先登記,只考這三張):
  V1 法人PE先行: 題材PE近3月擴張(dpe3高) ∧ 營收還沒動(yoy低中) → 未來2月跑贏基準
     (「營收還沒動但他們默默上調目標價=PE開始往上看」)
  V2 合理價介入: 營收強(yoy前1/3) ∧ PE位階低(<40) → 跑贏「營收強∧PE位階高(>60)」及基準
     (「營收很好的股價修正到PE合理位置他們會想介入」)
  V3 過熱出貨: 題材PE位階>=90 → 未來1-2月轉弱(與款6估值毒性/解質高位階同賣方家族)
口徑:
  月頻面板2018-01~2026-05(fwd需+2月);題材PE=成員正PER中位(PER<=0=虧損當缺值,全體22.9%),
  題材月有效成員>=5才計;PE位階=題材自身expanding百分位(min18月);營收=fm_month_rev題材成員
  合計YoY(**滯後1月用**避免公佈日前視;口徑近似,非儀表板題材營收動能score原版);
  前瞻=成員次1/2月報酬中位(絕對)+超額(減TAIEX)雙軌;判準=絕對判上板/超額判真偽/年度分層/
  LOTO逐題材/cluster bootstrap(按題材)。
警語: ①E修正混淆--PE漲可能是E被砍不是P被買(V1天生噪音,通過也要標) ②虧損股不在PE面板
  ③分類表2025-26整理=倖存者偏差,絕對報酬偏高,相對差較可信 ④全部觀察層起步。
用法: python build_valuation_theme.py
"""
import json
import sqlite3
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
DB = "capital_flow.db"
N_BOOT = 2000
MIN_PE_MEMBERS = 5
rng = np.random.default_rng(20260727)


def build_panel():
    con = sqlite3.connect(DB)
    cl = pd.read_sql("SELECT DISTINCT code, main_group FROM classification WHERE country='台'", con)
    codes = sorted(cl.code.unique())
    ph = ",".join("?" * len(codes))
    per = pd.read_sql(f"SELECT code, date, per FROM per_daily WHERE code IN ({ph})",
                      con, params=codes)
    rev = pd.read_sql(f"SELECT code, date, revenue FROM fm_month_rev WHERE code IN ({ph})",
                      con, params=codes)
    px = pd.read_sql(f"SELECT code, date, close FROM fm_daily_price WHERE code IN ({ph}) "
                     "AND date>='2017-06-01'", con, params=codes)
    tx = pd.read_sql("SELECT date, close FROM index_daily WHERE market='TAIEX' "
                     "AND date>='2017-06-01' ORDER BY date", con)
    con.close()

    # 月末PE(每檔每月最後一筆;<=0=虧損缺值)
    per["m"] = per.date.str[:7]
    per = per.sort_values("date").groupby(["code", "m"]).per.last().reset_index()
    per.loc[per.per <= 0, "per"] = np.nan
    per = per.merge(cl, on="code")
    gpe = (per.groupby(["main_group", "m"])
           .agg(pe_med=("per", "median"), n_pe=("per", lambda s: s.notna().sum()))
           .reset_index())
    gpe.loc[gpe.n_pe < MIN_PE_MEMBERS, "pe_med"] = np.nan

    # 題材營收YoY(滯後1月使用)
    rev["m"] = rev.date.str[:7]
    rev = rev.merge(cl, on="code")
    grev = rev.groupby(["main_group", "m"]).revenue.sum().reset_index()
    grev = grev.sort_values(["main_group", "m"])
    g = grev.groupby("main_group")
    grev["yoy"] = (grev.revenue / g.revenue.shift(12) - 1) * 100
    grev["acc"] = grev.yoy - g.yoy.shift(3)
    grev["m_use"] = (pd.to_datetime(grev.m + "-01") + pd.DateOffset(months=1)).dt.strftime("%Y-%m")

    # 月頻價格: 成員月報酬 -> 題材次1/2月中位
    px["m"] = px.date.str[:7]
    pxm = px.sort_values("date").groupby(["code", "m"]).close.last().reset_index()
    wide = pxm.pivot_table(index="m", columns="code", values="close").sort_index()
    mret = wide.pct_change() * 100
    tx["m"] = tx.date.str[:7]
    txm = tx.sort_values("date").groupby("m").close.last()
    tret = txm.pct_change() * 100
    members = cl.groupby("main_group").code.apply(list).to_dict()

    rows = []
    ms = list(mret.index)
    for gname, cs in members.items():
        cs = [c for c in cs if c in mret.columns]
        if len(cs) < MIN_PE_MEMBERS:
            continue
        sub = mret[cs]
        for i, m in enumerate(ms):
            if i + 2 >= len(ms):
                continue
            r1 = sub.iloc[i + 1].dropna()
            r2 = ((1 + sub.iloc[i + 1] / 100) * (1 + sub.iloc[i + 2] / 100) - 1) * 100
            r2 = r2.dropna()
            if len(r1) < MIN_PE_MEMBERS:
                continue
            t2 = ((1 + tret.iloc[i + 1] / 100) * (1 + tret.iloc[i + 2] / 100) - 1) * 100 \
                if i + 2 < len(tret) else np.nan
            rows.append({"main_group": gname, "m": m,
                         "fwd1m": float(r1.median()), "fwd2m": float(r2.median()),
                         "fwd2x": float(r2.median()) - float(t2)})
    pn = pd.DataFrame(rows)
    pn = pn.merge(gpe[["main_group", "m", "pe_med", "n_pe"]], on=["main_group", "m"], how="left")
    pn = pn.merge(grev[["main_group", "m_use", "yoy", "acc"]].rename(columns={"m_use": "m"}),
                  on=["main_group", "m"], how="left")
    pn = pn.sort_values(["main_group", "m"]).reset_index(drop=True)
    gg = pn.groupby("main_group")
    pn["pe_pctl"] = gg.pe_med.transform(lambda s: s.expanding(18).rank(pct=True) * 100)
    pn["dpe3"] = gg.pe_med.transform(lambda s: s.pct_change(3) * 100)
    pn = pn[pn.m >= "2018-01"]
    return pn


def boot(cell, base, col="fwd2m"):
    themes = base.main_group.unique()
    cg = {t: s[col].dropna().values for t, s in cell.groupby("main_group")}
    bg = {t: s[col].dropna().values for t, s in base.groupby("main_group")}
    cg = {t: v for t, v in cg.items() if len(v)}
    obs = np.median(np.concatenate(list(cg.values()))) - np.median(base[col].dropna().values)
    ds = []
    for _ in range(N_BOOT):
        pick = rng.choice(themes, len(themes), replace=True)
        ca = [cg[t] for t in pick if t in cg]
        if not ca:
            continue
        ca = np.concatenate(ca)
        if len(ca) < 5:
            continue
        ds.append(np.median(ca) - np.median(np.concatenate([bg[t] for t in pick if t in bg])))
    lo, hi = np.percentile(ds, [2.5, 97.5]) if ds else (np.nan, np.nan)
    return obs, lo, hi


def report_cell(name, cell, base, R):
    if len(cell) < 20:
        print(f"{name}: n={len(cell)} 不足")
        R[name] = {"n": len(cell), "verdict": "n不足"}
        return
    o_abs, lo_a, hi_a = boot(cell, base, "fwd2m")
    o_x, lo_x, hi_x = boot(cell, base, "fwd2x")
    ys = []
    for y in sorted(cell.m.str[:4].unique()):
        c = cell[cell.m.str[:4] == y]
        b = base[base.m.str[:4] == y]
        if len(c) >= 3:
            ys.append(np.sign(c.fwd2m.median() - b.fwd2m.median()))
    ystr = f"{sum(1 for s in ys if s > 0)}/{len(ys)}年正"
    med = cell.fwd2m.median()
    win = (cell.fwd2m > 0).mean() * 100
    sig_a = "◄排0" if (lo_a > 0 or hi_a < 0) else "含0"
    sig_x = "◄排0" if (lo_x > 0 or hi_x < 0) else "含0"
    print(f"{name}: n={len(cell)} fwd2m中位{med:+.2f}%/勝{win:.0f}% | "
          f"絕對diff{o_abs:+.2f}pp CI[{lo_a:+.2f},{hi_a:+.2f}]{sig_a} | "
          f"超額diff{o_x:+.2f}pp CI[{lo_x:+.2f},{hi_x:+.2f}]{sig_x} | {ystr}")
    R[name] = {"n": len(cell), "fwd2m": round(float(med), 2), "win": round(float(win), 0),
               "diff_abs": round(float(o_abs), 2), "ci_abs": [round(float(lo_a), 2), round(float(hi_a), 2)],
               "diff_x": round(float(o_x), 2), "ci_x": [round(float(lo_x), 2), round(float(hi_x), 2)],
               "yearly": ystr}


def main():
    pn = build_panel()
    pn.to_pickle("tmp_valuation_panel.pkl")
    base = pn.dropna(subset=["fwd2m", "fwd2x", "pe_pctl", "yoy"])
    print(f"面板: {len(pn)}題材-月 / 有效考區(位階+營收+前瞻齊備)={len(base)} / "
          f"{base.main_group.nunique()}題材 / {base.m.nunique()}月 ({base.m.min()}~{base.m.max()})")
    print(f"基準: fwd2m中位{base.fwd2m.median():+.2f}% 超額中位{base.fwd2x.median():+.2f}%")
    R = {"n_panel": len(pn), "n_exam": len(base),
         "base_fwd2m": round(float(base.fwd2m.median()), 2)}

    dq1, dq2 = base.dpe3.quantile([1 / 3, 2 / 3])
    yq1, yq2 = base.yoy.quantile([1 / 3, 2 / 3])
    print(f"門檻: dpe3三分位[{dq1:.1f},{dq2:.1f}] yoy三分位[{yq1:.1f},{yq2:.1f}]%\n")

    # V1 法人PE先行: PE近3月擴張前1/3 ∧ 營收yoy不在前1/3(還沒反映)
    v1 = base[(base.dpe3 >= dq2) & (base.yoy < yq2)]
    report_cell("V1_PE先行(dpe3高∧營收未動)", v1, base, R)
    # V1對照: PE擴張∧營收也已強(=已反映組)
    report_cell("V1對照(dpe3高∧營收已強)", base[(base.dpe3 >= dq2) & (base.yoy >= yq2)], base, R)

    # V2 合理價介入: 營收強∧PE位階<40 vs 營收強∧PE位階>60
    v2a = base[(base.yoy >= yq2) & (base.pe_pctl < 40)]
    v2b = base[(base.yoy >= yq2) & (base.pe_pctl > 60)]
    report_cell("V2_營收強∧PE位階低", v2a, base, R)
    report_cell("V2對照_營收強∧PE位階高", v2b, base, R)
    if len(v2a) >= 20 and len(v2b) >= 20:
        d = v2a.fwd2m.median() - v2b.fwd2m.median()
        print(f"  V2低vs高PE位階直接差: {d:+.2f}pp")
        R["V2_low_vs_high"] = round(float(d), 2)

    # V3 過熱: PE位階>=90
    report_cell("V3_過熱(PE位階>=90)", base[base.pe_pctl >= 90], base, R)
    report_cell("V3對照_冷(PE位階<=10)", base[base.pe_pctl <= 10], base, R)

    # 描述性: PE位階五分位全景(非預註冊,畫形狀用)
    print("\nPE位階五分位×fwd2m(描述性):")
    R["pctl_quintiles"] = []
    for lo_, hi_ in [(0, 20), (20, 40), (40, 60), (60, 80), (80, 100)]:
        s = base[(base.pe_pctl >= lo_) & (base.pe_pctl < hi_ + (1 if hi_ == 100 else 0))]
        row = {"bin": f"{lo_}-{hi_}", "n": len(s),
               "fwd2m": round(float(s.fwd2m.median()), 2),
               "fwd2x": round(float(s.fwd2x.median()), 2),
               "win": round(float((s.fwd2m > 0).mean() * 100), 0)}
        R["pctl_quintiles"].append(row)
        print(f"  位階{lo_:3d}-{hi_:3d}: n={len(s):4d} 絕對{row['fwd2m']:+6.2f}% 超額{row['fwd2x']:+6.2f}% 勝{row['win']:.0f}%")

    # 冷格年份集中度(判決關鍵: 73%樣本在2022=本質是熊市工具,與H5同窗期重疊率待查)
    cold = base[base.pe_pctl <= 10]
    R["cold_yearly"] = [{"年": y, "n": len(s), "絕對": round(float(s.fwd2m.median()), 2),
                         "超額": round(float(s.fwd2x.median()), 2)}
                        for y, s in cold.groupby(cold.m.str[:4])]

    with open("tmp_valuation_results.json", "w", encoding="utf-8") as f:
        json.dump(R, f, ensure_ascii=False, indent=1, default=str)

    # 簡版報告
    def tbl(d):
        keys = [k for k in d if isinstance(d[k], dict) and "n" in d[k]]
        h = "<tr><th>考卷</th><th>n</th><th>fwd2m</th><th>勝率</th><th>絕對diff(CI)</th><th>超額diff(CI)</th><th>逐年</th></tr>"
        rs = ""
        for k in keys:
            v = d[k]
            if "fwd2m" not in v:
                rs += f"<tr><td>{k}</td><td>{v['n']}</td><td colspan=5>{v.get('verdict','')}</td></tr>"
                continue
            rs += (f"<tr><td>{k}</td><td>{v['n']}</td><td>{v['fwd2m']:+.2f}%</td><td>{v['win']:.0f}%</td>"
                   f"<td>{v['diff_abs']:+.2f} {v['ci_abs']}</td><td>{v['diff_x']:+.2f} {v['ci_x']}</td>"
                   f"<td>{v['yearly']}</td></tr>")
        return f"<table>{h}{rs}</table>"

    qt = "<tr><th>PE位階</th><th>n</th><th>絕對</th><th>超額</th><th>勝率</th></tr>" + "".join(
        f"<tr><td>{r['bin']}</td><td>{r['n']}</td><td>{r['fwd2m']:+.2f}%</td>"
        f"<td>{r['fwd2x']:+.2f}%</td><td>{r['win']:.0f}%</td></tr>" for r in R["pctl_quintiles"])
    html = f"""<!DOCTYPE html><html lang="zh-Hant"><head><meta charset="utf-8">
<title>題材估值考卷: PE位階×營收動能</title><style>
body{{background:#0c1118;color:#dde;font-family:'Microsoft JhengHei',sans-serif;max-width:1000px;margin:auto;padding:20px}}
table{{border-collapse:collapse;margin:10px 0;font-size:13px}}td,th{{border:1px solid #345;padding:4px 10px}}
th{{background:#19253a}}h2{{color:#6cf}}.warn{{color:#fa5;font-size:13px}}.note{{color:#9ab;font-size:13px;line-height:1.7}}</style></head><body>
<h1>題材估值考卷第一場: PE位階 × 營收動能</h1>
<p class="note">2026-07-27,使用者機制假說(法人PE先行/合理價介入/過熱出貨)預先登記三張主考卷。
面板={R['n_exam']}題材-月(2018~2026,含2022熊市);題材PE=成員正PER中位(虧損22.9%當缺值);
營收YoY滯後1月防前視;判準=絕對+超額雙軌/年度分層/cluster bootstrap。<br>
<span class="warn">⚠E修正混淆(PE漲可能是E被砍非P被買)/分類表倖存者偏差/觀察層起步。</span></p>
<h2>主考卷判決</h2>{tbl(R)}
<p class="note"><b>判決摘要</b>:V1「法人PE先行」❌題材層不成立(方向相反:PE擴張∧營收已強+1.68pp較好=PE跟隨不領先);
V2交互無加值(低vs高PE位階直接差-0.15pp,超額軌顯著是「便宜」單因子的影子);V3「過熱=賣訊」❌(貴端沒有懲罰=動能撐住)。
<b>真發現=便宜單因子</b>:題材PE位階≤10 → fwd2m+4.16%/勝69%,絕對+2.43pp與超額+2.36pp雙軌CI排0、出現年4/4正。</p>
<p class="warn">⚠便宜格樣本73%集中2022熊市(94/128),2024-26幾乎不觸發=<b>本質是熊市工具非常開訊號</b>,
且與H5(熊市買落後轉漲)同窗期——重疊率未查,兩者可能是同一條魚的兩種撈法;升格前必做:①與H5重疊率
②個股層內部檢驗(強題材內挑低PE成員=使用者「切入個股」路徑) ③觸發時點疊加共振/K棒。</p>
<h2>便宜格(位階≤10)逐年</h2>
<table><tr><th>年</th><th>n</th><th>絕對</th><th>超額</th></tr>{"".join(
    f"<tr><td>{r['年']}</td><td>{r['n']}</td><td>{r['絕對']:+.2f}%</td><td>{r['超額']:+.2f}%</td></tr>"
    for r in R['cold_yearly'])}</table>
<h2>PE位階五分位全景(描述性)</h2><table>{qt}</table>
<p class="note">形狀判讀:資訊全在<b>便宜端</b>(0-20位階絕對+2.88%/超額+0.94%/勝64%),40位階以上超額全負但貴端無單調懲罰
=「便宜有均值回歸拉、貴有動能撐」的不對稱——與款6研究(極端估值在注意股情境有毒)不衝突:那是個股極端值+官方公告情境,這裡是題材自身歷史位階。</p>
</body></html>"""
    with open("研究報告/research_valuation.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("\n完成: tmp_valuation_panel.pkl / tmp_valuation_results.json / 研究報告/research_valuation.html")


if __name__ == "__main__":
    main()
