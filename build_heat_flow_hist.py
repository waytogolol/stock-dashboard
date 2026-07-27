# -*- coding: utf-8 -*-
"""
題材量價狀態機 歷史延伸版(2019~,日資料重建;2026-07-27使用者追問「H3沒有2019年的嗎」)
========================================================================
背景: rankings五市場快照2025-04才開始,主研究(build_heat_flow.py)僅66週無熊市。
     台股腿的量可從fm_daily_price成交金額重建: share=題材成員週成交額/(TAIEX+TPEx大盤週成交額),
     價/RRG同主研究口徑 → H3(領先象限×量增價跌)拉回2019含2022熊市壓力測試。
⚠偏差聲明(掛頭條): classification是2025-26整理的=「今日題材定義」回測過去,成員因後來變大變熱
     才被收錄=倖存者偏差,絕對報酬偏高;H3 vs 基準為同宇宙相對比較,污染較小但仍要打折看。
     另「AI伺服器」等題材概念2019不存在,考的是「今日籃子在當年的量價行為」非當年市場認知。
驗證閘: 重疊期(2025-05後)本重建版 vs rankings版的H3/狀態數字需同向同量級,否則重建口徑不可信。
用法: python build_heat_flow_hist.py
"""
import json
import sqlite3
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
DB = "capital_flow.db"
MIN_MEMBERS = 3
RRG_SMA, RRG_ROC = 13, 4
N_BOOT = 2000
rng = np.random.default_rng(20260727)


def build_hist_panel():
    con = sqlite3.connect(DB)
    codes = [r[0] for r in con.execute(
        "SELECT DISTINCT code FROM classification WHERE country='台'")]
    cl = pd.read_sql("SELECT DISTINCT code, main_group FROM classification WHERE country='台'", con)
    px = pd.read_sql("SELECT code, date, close, money FROM fm_daily_price WHERE code IN (%s) "
                     "AND date>='2018-09-01'" % ",".join("?" * len(codes)), con, params=codes)
    idx = pd.read_sql("SELECT market, date, close, money FROM index_daily "
                      "WHERE market IN ('TAIEX','TPEx') AND date>='2018-09-01'", con)
    con.close()
    px["date"] = pd.to_datetime(px.date)
    idx["date"] = pd.to_datetime(idx.date)

    # 週化(W-FRI): 收盤取週最後一筆,金額取週加總
    px["wk"] = px.date.dt.to_period("W-FRI").dt.end_time.dt.normalize()
    wpx = px.sort_values("date").groupby(["code", "wk"]).agg(
        close=("close", "last"), money=("money", "sum")).reset_index()
    idx["wk"] = idx.date.dt.to_period("W-FRI").dt.end_time.dt.normalize()
    wtaiex = idx[idx.market == "TAIEX"].sort_values("date").groupby("wk").close.last()
    wmkt = idx.groupby("wk").money.sum()                     # TAIEX+TPEx大盤週成交額

    wide_c = wpx.pivot_table(index="wk", columns="code", values="close").sort_index()
    wide_m = wpx.pivot_table(index="wk", columns="code", values="money").sort_index()
    ret = wide_c.pct_change() * 100
    members = cl.groupby("main_group").code.apply(list).to_dict()
    tret = wtaiex.reindex(wide_c.index).pct_change() * 100
    mkt_money = wmkt.reindex(wide_c.index)

    rows = []
    for g, cs in members.items():
        cs = [c for c in cs if c in ret.columns]
        if len(cs) < MIN_MEMBERS:
            continue
        sub_r, sub_m = ret[cs], wide_m[cs]
        for wk in ret.index[1:]:
            v = sub_r.loc[wk].dropna()
            if len(v) < MIN_MEMBERS:
                continue
            share = float(sub_m.loc[wk].sum()) / float(mkt_money[wk]) * 100 \
                if mkt_money.get(wk, 0) and mkt_money[wk] > 0 else np.nan
            rows.append({"wk": wk, "main_group": g, "ret": float(v.median()),
                         "breadth": float((v > 0).mean() * 100), "hs_tw": share, "n_px": len(v)})
    pn = pd.DataFrame(rows).sort_values(["main_group", "wk"]).reset_index(drop=True)
    pn = pn[pn.wk >= "2018-12-01"]
    g = pn.groupby("main_group")
    pn["d_hs_tw"] = g.hs_tw.diff()
    for h in (1, 2, 4):
        pn[f"fwd{h}"] = sum(g.ret.shift(-k) for k in range(1, h + 1))

    q1, q2 = pn.ret.quantile([1 / 3, 2 / 3])
    pn["p_state"] = np.select([pn.ret <= q1, pn.ret >= q2], ["跌", "漲"], "平")
    pn["state"] = np.where(pn.d_hs_tw > 0, "增", "縮") + pn.p_state
    print(f"價三分位門檻(全史pooled): 跌≤{q1:.2f}% / 漲≥{q2:.2f}% (主研究66週版: -1.12/+1.97)")

    pn["rrg_ratio"], pn["rrg_mom"] = np.nan, np.nan
    for gname, sub in pn.groupby("main_group"):
        s = sub.sort_values("wk")
        theme_idx = (1 + s.ret / 100).cumprod()
        mkt_idx = (1 + tret.reindex(s.wk).fillna(0) / 100).cumprod().values
        rs = pd.Series(theme_idx.values / mkt_idx, index=s.index)
        ratio = 100 * rs / rs.rolling(RRG_SMA).mean()
        pn.loc[s.index, "rrg_ratio"] = ratio
        pn.loc[s.index, "rrg_mom"] = 100 * ratio / ratio.shift(RRG_ROC)
    conds = [(pn.rrg_ratio >= 100) & (pn.rrg_mom >= 100), (pn.rrg_ratio >= 100) & (pn.rrg_mom < 100),
             (pn.rrg_ratio < 100) & (pn.rrg_mom < 100), (pn.rrg_ratio < 100) & (pn.rrg_mom >= 100)]
    pn["quad"] = np.select(conds, ["領先", "轉弱", "落後", "轉強"], None)
    return pn


def cell_stats(cell, base, col="fwd2"):
    """cluster bootstrap(按題材重抽),numpy陣列版(pandas concat版跑24格會超時)"""
    themes = base.main_group.unique()
    cg = {t: g[col].values for t, g in cell.groupby("main_group")}
    bg = {t: g[col].values for t, g in base.groupby("main_group")}
    obs = np.median(cell[col].values) - np.median(base[col].values)
    diffs = []
    for _ in range(N_BOOT):
        pick = rng.choice(themes, len(themes), replace=True)
        ca = [cg[t] for t in pick if t in cg]
        if not ca:
            continue
        ca = np.concatenate(ca)
        if len(ca) < 5:
            continue
        ba = np.concatenate([bg[t] for t in pick])
        diffs.append(np.median(ca) - np.median(ba))
    lo, hi = np.percentile(diffs, [2.5, 97.5]) if diffs else (np.nan, np.nan)
    return obs, lo, hi


def main():
    pn = build_hist_panel()
    pn.to_pickle("tmp_heat_flow_hist_panel.pkl")
    base = pn.dropna(subset=["fwd2", "quad"])
    print(f"歷史面板: {len(pn)}題材-週 / {pn.main_group.nunique()}題材 / "
          f"{pn.wk.nunique()}週 ({pn.wk.min().date()}~{pn.wk.max().date()})")

    # --- 六狀態全史 ---
    print("\n六狀態×fwd2(全史2019~):")
    for st, sub in sorted(base.groupby("state"), key=lambda x: -x[1].fwd2.median()):
        print(f"  {st}: n={len(sub):5d} fwd2中位{sub.fwd2.median():+6.2f}% 勝率{(sub.fwd2 > 0).mean() * 100:3.0f}%")

    # --- H3全史+逐年 ---
    h3 = base[(base.quad == "領先") & (base.state == "增跌")]
    obs, lo, hi = cell_stats(h3, base)
    print(f"\nH3(領先×增跌)全史: n={len(h3)} fwd2中位{h3.fwd2.median():+.2f}% "
          f"勝率{(h3.fwd2 > 0).mean() * 100:.0f}% diff={obs:+.2f}pp CI[{lo:+.2f},{hi:+.2f}]"
          f"{' ◄排0' if lo > 0 else ''}")
    print("H3逐年(年度分層=家規):")
    for y, s in h3.groupby(h3.wk.dt.year):
        b = base[base.wk.dt.year == y]
        print(f"  {y}: n={len(s):3d} fwd2中位{s.fwd2.median():+6.2f}% 勝率{(s.fwd2 > 0).mean() * 100:3.0f}% "
              f"(基準{b.fwd2.median():+.2f}%) diff={s.fwd2.median() - b.fwd2.median():+.2f}pp")

    # --- 「別追增漲」逐年 ---
    print("\n增漲格(別追)逐年 fwd2中位 vs 基準:")
    zz = base[base.state == "增漲"]
    for y, s in zz.groupby(zz.wk.dt.year):
        b = base[base.wk.dt.year == y]
        print(f"  {y}: n={len(s):4d} {s.fwd2.median():+6.2f}% vs 基準{b.fwd2.median():+6.2f}% "
              f"diff={s.fwd2.median() - b.fwd2.median():+.2f}pp")

    # --- 驗證閘: 重疊期vs rankings版 ---
    ov = base[base.wk >= "2025-05-01"]
    h3o = ov[(ov.quad == "領先") & (ov.state == "增跌")]
    print(f"\n驗證閘(重疊期2025-05~,rankings版H3=+5.59%/81%/n21): "
          f"重建版H3 n={len(h3o)} fwd2中位{h3o.fwd2.median():+.2f}% 勝率{(h3o.fwd2 > 0).mean() * 100:.0f}%")
    zzo = ov[ov.state == "增漲"]
    print(f"  重建版增漲(rankings版=-0.37%/47%): n={len(zzo)} {zzo.fwd2.median():+.2f}%/{(zzo.fwd2 > 0).mean() * 100:.0f}%")

    # --- 季線regime條件化(2026-07-27使用者假說「破月線/季線表現可能不一樣」,提出於看結果前=準預註冊) ---
    # 判決: 季線是H3的開關--站上季線+1.40%/67% diff+1.22pp CI[+0.74,+2.37]排0且逐年7/8正(2022年內部也成立);
    #       跌破季線-0.83%/42% diff-1.61pp CI[-2.37,-0.85]排0反向=接刀確認;月線分割較弱(CI含0)。
    #       「別追增漲」regime化後也不成立(跌破季線反而+0.77pp)=正式撤銷。
    con2 = sqlite3.connect(DB)
    tx = pd.read_sql("SELECT date, close FROM index_daily WHERE market='TAIEX' ORDER BY date", con2)
    con2.close()
    tx["date"] = pd.to_datetime(tx.date)
    tx["ma60"] = tx.close.rolling(60).mean()
    tx["wkk"] = tx.date.dt.to_period("W-FRI").dt.end_time.dt.normalize()
    wreg = tx.sort_values("date").groupby("wkk").last()
    wreg["above60"] = wreg.close > wreg.ma60
    base2 = base.merge(wreg[["above60"]], left_on="wk", right_index=True, how="left").dropna(subset=["above60"])
    h3r = base2[(base2.quad == "領先") & (base2.state == "增跌")]
    print("\n季線regime條件化(基準=同regime面板;使用者假說準預註冊):")
    reg_out = {}
    for lab, cond in [("站上季線", base2.above60.astype(bool)), ("跌破季線", ~base2.above60.astype(bool))]:
        c = h3r[cond.reindex(h3r.index).fillna(False)]
        b = base2[cond]
        obs2, lo2, hi2 = cell_stats(c, b)
        reg_out[lab] = {"n": len(c), "fwd2": round(float(c.fwd2.median()), 2),
                        "win": round(float((c.fwd2 > 0).mean() * 100), 0),
                        "diff": round(float(obs2), 2), "ci": [round(float(lo2), 2), round(float(hi2), 2)]}
        print(f"  {lab}: n={len(c)} fwd2中位{c.fwd2.median():+.2f}% 勝率{(c.fwd2 > 0).mean() * 100:.0f}% "
              f"diff={obs2:+.2f}pp CI[{lo2:+.2f},{hi2:+.2f}]{' ◄排0' if lo2 > 0 or hi2 < 0 else ''}")
        for y, s in c.groupby(c.wk.dt.year):
            byr = b[b.wk.dt.year == y]
            if len(s) >= 3:
                print(f"    {y}: n={len(s):3d} diff={s.fwd2.median() - byr.fwd2.median():+.2f}pp")

    # --- 全24格×季線探索掃描(2026-07-27使用者「舉一反三有H5H6?」;⚠48檢定預期2-3假陽性,掛起標籤) ---
    # 判決: 9格CI排0>>雜訊期望,且方向連貫=regime輪動地圖--多頭買領先回檔(H3)/空頭領先全毒、
    #       買落後轉漲: H5候選=落後x增漲x跌破季線(+3.64%/78%,diff+2.86pp,6/7年正,前後段+2.54/+3.15,
    #       fwd4遞增+3.53pp)、H6候選=轉強x縮漲x跌破(+2.60%/79%,diff+1.82pp,6/7年正,2週甜蜜點);
    #       H1/H2/H4皆無季線開關(CI全含0)。
    scan_out = []
    for q in ["領先", "轉強", "轉弱", "落後"]:
        for st in ["增漲", "增平", "增跌", "縮漲", "縮平", "縮跌"]:
            for lab, cond in [("站上", base2.above60.astype(bool)), ("跌破", ~base2.above60.astype(bool))]:
                b = base2[cond]
                c = b[(b.quad == q) & (b.state == st)]
                if len(c) < 30:
                    continue
                obs3, lo3, hi3 = cell_stats(c, b)
                if lo3 > 0 or hi3 < 0:
                    scan_out.append({"cell": f"{q}x{st}x{lab}季線", "n": len(c),
                                     "fwd2": round(float(c.fwd2.median()), 2),
                                     "win": round(float((c.fwd2 > 0).mean() * 100), 0),
                                     "diff": round(float(obs3), 2),
                                     "ci": [round(float(lo3), 2), round(float(hi3), 2)]})
    print("\n全格×季線掃描CI排0(探索,掛起):")
    for r in sorted(scan_out, key=lambda r: -abs(r["diff"])):
        print(f"  {r['cell']}: n={r['n']} {r['fwd2']:+.2f}%/{r['win']:.0f}% diff{r['diff']:+.2f}pp CI{r['ci']}")

    out = {"h3_all": {"n": len(h3), "fwd2": round(float(h3.fwd2.median()), 2),
                      "win": round(float((h3.fwd2 > 0).mean() * 100), 0),
                      "diff": round(float(obs), 2), "ci": [round(float(lo), 2), round(float(hi), 2)]},
           "h3_regime": reg_out, "scan_flagged": scan_out}
    with open("tmp_heat_flow_hist_results.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    print("\n完成: tmp_heat_flow_hist_panel.pkl / tmp_heat_flow_hist_results.json")


if __name__ == "__main__":
    main()
