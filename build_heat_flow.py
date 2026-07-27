# -*- coding: utf-8 -*-
"""
題材量價狀態機 × 輪動象限(RRG) × 熱度Δ預測力體檢 (2026-07-27,使用者提案系列)
========================================================================
研究目標(三層,由低到高):
  ①描述地圖: 每題材在生命週期哪一段(上攻/洗盤/回檔/退潮)——大盤有溫度計,題材沒有,補這格
  ②條件層: 特定「象限×狀態」格是否顯著改變前瞻報酬 → 給既有訊號當題材環境係數
  ③預測力判決: 熱度Δ(量佔比)到底有沒有領先性(IC/跨市場),沒有也是重要答案(降級為事後儀表)

預註冊四假說格(fwd2週報酬,vs全面板基準,其餘格皆描述性):
  H1 轉強×量增價平 > 基準 (埋伏格)      H2 領先×量增價漲 > 基準 (主升段)
  H3 領先×量增價跌 < 基準 (出貨警)      H4 轉弱×量縮價跌 < 基準 (退潮確認)

口徑:
  量Δ = 題材成交金額佔比變化,雙口徑——台股腿(主,可單獨live)/五市場全球(輔,對照答「台股夠不夠」)
  價  = 台股成員週報酬中位數(絕對口徑=使用者裁示狀態機用絕對;超額版另存對照欄)
  狀態 = 量2(Δ>0增/≤0縮) × 價3(全樣本三分位切漲/平/跌,門檻印出供live)
  RRG = X:RS比率(題材指數/TAIEX,13週SMA正規化×100) Y:RS動能(RS比率4週ROC×100);
        象限: 領先(≥100,≥100)/轉弱(≥100,<100)/落後(<100,<100)/轉強(<100,≥100)
  廣度 = 題材內上漲成員比例(洗盤vs出貨的裁判欄,描述用)

警語: 面板僅~66週(2025-04起,無完整熊市;RRG燒13+4週後約49週),三分位門檻全樣本算=輕微前視(研究可,
      live用印出的固定門檻);全部結論觀察層起步;共振/位階節=探索性。
用法: python build_heat_flow.py   (產 tmp_heat_flow_panel.pkl + 研究報告/research_heat_flow.html)
"""
import json
import pickle
import sqlite3
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
DB = "capital_flow.db"
MARKETS = ["台", "美", "日", "韓", "陸"]
MIN_MEMBERS = 3          # 題材該週有價成員數下限
RRG_SMA, RRG_ROC = 13, 4
N_BOOT = 2000
rng = np.random.default_rng(20260727)


# ────────────────────────── 1. 快照與熱度(量) ──────────────────────────
def load_heat(conn):
    rk = pd.read_sql("SELECT snapshot_date, country, code, amount, amount_unit FROM rankings", conn)
    fx = pd.read_sql("SELECT snapshot_date, currency, twd_per_unit FROM fx_rates", conn)
    cl = pd.read_sql("SELECT country, code, main_group FROM classification", conn).drop_duplicates()
    cur_map = {"TWD": "TWD", "KRW": "KRW", "JPY_million": "JPY", "CNY": "CNY", "USD": "USD"}
    rk["currency"] = rk.amount_unit.map(cur_map)
    rk["base"] = np.where(rk.amount_unit == "JPY_million", rk.amount * 1e6, rk.amount)
    rk = rk.merge(fx, on=["snapshot_date", "currency"], how="left")
    rk["twd_yi"] = rk.base * rk.twd_per_unit.fillna(1.0) / 1e8

    # 快照去重: 與前一快照差<4天=同週補抓,保留較晚者(如2026-07-05/07-06)
    snaps = sorted(rk.snapshot_date.unique())
    keep = []
    for s in snaps:
        if keep and (pd.Timestamp(s) - pd.Timestamp(keep[-1])).days < 4:
            keep[-1] = s
        else:
            keep.append(s)
    rk = rk[rk.snapshot_date.isin(keep)]
    print(f"快照 {len(snaps)}→去重後 {len(keep)} ({keep[0]}~{keep[-1]})")

    tot = rk.groupby(["snapshot_date", "country"]).twd_yi.sum().rename("tot")
    th = (rk.merge(cl, on=["country", "code"])
            .drop_duplicates(["snapshot_date", "main_group", "country", "code"])
            .groupby(["snapshot_date", "main_group", "country"]).twd_yi.sum().rename("amt")
            .reset_index().merge(tot, on=["snapshot_date", "country"]))
    th["share"] = th.amt / th.tot * 100                       # 該題材佔該市場成交%
    piv = th.pivot_table(index=["snapshot_date", "main_group"], columns="country",
                         values="share", fill_value=0.0)
    for m in MARKETS:
        if m not in piv.columns:
            piv[m] = 0.0
    heat = pd.DataFrame({"hs_g": piv[MARKETS].sum(axis=1), "hs_tw": piv["台"]})
    for m in MARKETS:
        heat[f"leg_{m}"] = piv[m]
    return heat.reset_index(), keep, cl


# ────────────────────────── 2. 價(台股成員週報酬) ──────────────────────────
def load_price(conn, keep, cl):
    wc = pd.read_sql("SELECT code, snapshot_date, close FROM weekly_close WHERE country='台'", conn)
    wc = wc[wc.snapshot_date.isin(keep)]
    px = wc.pivot_table(index="snapshot_date", columns="code", values="close").sort_index()
    ret = px.pct_change() * 100                               # 週報酬%(相鄰保留快照)
    tw_members = cl[cl.country == "台"].groupby("main_group").code.apply(list).to_dict()

    idx = pd.read_sql("SELECT date, close FROM index_daily WHERE market='TAIEX' ORDER BY date", conn)
    idx["date"] = pd.to_datetime(idx.date)
    snap_ts = pd.to_datetime(pd.Series(keep))
    tix = pd.Series([idx[idx.date <= s].close.iloc[-1] if (idx.date <= s).any() else np.nan
                     for s in snap_ts], index=keep)
    tret = tix.pct_change() * 100

    rows = []
    for g, codes in tw_members.items():
        cs = [c for c in codes if c in ret.columns]
        if len(cs) < MIN_MEMBERS:
            continue
        sub = ret[cs]
        for d in ret.index[1:]:
            v = sub.loc[d].dropna()
            if len(v) < MIN_MEMBERS:
                continue
            rows.append({"snapshot_date": d, "main_group": g,
                         "ret": float(v.median()), "exc": float(v.median() - tret[d]),
                         "breadth": float((v > 0).mean() * 100), "n_px": len(v)})
    return pd.DataFrame(rows), tix, tret


# ────────────────────────── 3. 面板組裝+狀態+RRG ──────────────────────────
def build_panel(heat, price, tix):
    pn = price.merge(heat, on=["snapshot_date", "main_group"], how="left").sort_values(
        ["main_group", "snapshot_date"]).reset_index(drop=True)
    g = pn.groupby("main_group")
    for col in ["hs_g", "hs_tw"] + [f"leg_{m}" for m in MARKETS]:
        pn[f"d_{col}"] = g[col].diff()
    pn["fwd1"] = g.ret.shift(-1)
    pn["fwd2"] = g.ret.shift(-1) + g.ret.shift(-2)            # 兩週相加(百分比近似)
    pn["ret_t1"] = g.ret.shift(-1)
    pn["ret_t2"] = g.ret.shift(-2)
    # 長水平前瞻(2026-07-27使用者追問「拉長會不會有領先性」): 1月≈4週/2月≈8週/3月≈12週
    for h in (4, 8, 12):
        pn[f"fwd{h}"] = sum(g.ret.shift(-k) for k in range(1, h + 1))
    # 4週平滑訊號(單週Δ太吵,月級傳導假說用月級訊號)
    for col in ["hs_tw", "hs_g"] + [f"leg_{m}" for m in MARKETS]:
        pn[f"d4_{col}"] = g[col].diff(4)

    # 價三分位(全樣本pooled,門檻印出)
    q1, q2 = pn.ret.quantile([1 / 3, 2 / 3])
    pn["p_state"] = np.select([pn.ret <= q1, pn.ret >= q2], ["跌", "漲"], "平")
    print(f"價三分位門檻: 跌≤{q1:.2f}% / 平 / 漲≥{q2:.2f}%")
    for tag, col in [("tw", "d_hs_tw"), ("g", "d_hs_g")]:
        pn[f"v_state_{tag}"] = np.where(pn[col] > 0, "增", "縮")
        pn[f"state_{tag}"] = pn[f"v_state_{tag}"] + pn.p_state

    # RRG(以題材報酬累乘指數 vs TAIEX)
    pn["rrg_ratio"] = np.nan
    pn["rrg_mom"] = np.nan
    tix_ret = tix.pct_change() * 100
    for gname, sub in pn.groupby("main_group"):
        s = sub.sort_values("snapshot_date")
        theme_idx = (1 + s.ret / 100).cumprod()
        mkt_idx = (1 + tix_ret.reindex(s.snapshot_date).fillna(0) / 100).cumprod().values
        rs = theme_idx.values / mkt_idx
        rs = pd.Series(rs, index=s.index)
        ratio = 100 * rs / rs.rolling(RRG_SMA).mean()
        mom = 100 * ratio / ratio.shift(RRG_ROC)
        pn.loc[s.index, "rrg_ratio"] = ratio
        pn.loc[s.index, "rrg_mom"] = mom
    conds = [(pn.rrg_ratio >= 100) & (pn.rrg_mom >= 100),
             (pn.rrg_ratio >= 100) & (pn.rrg_mom < 100),
             (pn.rrg_ratio < 100) & (pn.rrg_mom < 100),
             (pn.rrg_ratio < 100) & (pn.rrg_mom >= 100)]
    pn["quad"] = np.select(conds, ["領先", "轉弱", "落後", "轉強"], None)
    return pn


# ────────────────────────── 4. 統計工具 ──────────────────────────
def boot_diff_median(cell, base, col="fwd2"):
    """cluster bootstrap(按題材重抽)比較cell中位-基準中位,回傳(diff, lo, hi)"""
    themes = base.main_group.unique()
    obs = cell[col].median() - base[col].median()
    diffs = []
    for _ in range(N_BOOT):
        pick = rng.choice(themes, len(themes), replace=True)
        cs = pd.concat([cell[cell.main_group == t] for t in pick if (cell.main_group == t).any()])
        bs = pd.concat([base[base.main_group == t] for t in pick])
        if len(cs) < 5:
            continue
        diffs.append(cs[col].median() - bs[col].median())
    lo, hi = (np.percentile(diffs, [2.5, 97.5]) if diffs else (np.nan, np.nan))
    return obs, lo, hi, len(diffs)


def loto_sign(cell, base, col="fwd2"):
    """逐題材剔除,cell-基準中位差的符號一致率"""
    themes = cell.main_group.unique()
    if len(themes) < 3:
        return None
    signs = []
    for t in themes:
        c2, b2 = cell[cell.main_group != t], base[base.main_group != t]
        if len(c2) >= 5:
            signs.append(np.sign(c2[col].median() - b2[col].median()))
    pos = sum(1 for s in signs if s > 0)
    return f"{pos}/{len(signs)}正"


def weekly_ic(pn, sig_col, ret_col, block=1):
    """逐週跨題材Spearman,回傳(平均IC, 正週占比, 週數, bootstrap CI)。
    block>1=移動區塊bootstrap(前瞻窗重疊時IC序列自相關,普通bootstrap信心會虛胖)"""
    ics = []
    for d, sub in pn.groupby("snapshot_date"):
        v = sub[[sig_col, ret_col]].dropna()
        if len(v) >= 10:
            ics.append(v[sig_col].corr(v[ret_col], method="spearman"))
    if len(ics) < 10:
        return None
    ics = np.array(ics)
    n = len(ics)
    if block <= 1:
        bs = [rng.choice(ics, n, replace=True).mean() for _ in range(N_BOOT)]
    else:
        nblk = max(1, int(np.ceil(n / block)))
        starts_all = np.arange(0, n - block + 1)
        bs = []
        for _ in range(N_BOOT):
            picks = rng.choice(starts_all, nblk, replace=True)
            sample = np.concatenate([ics[s:s + block] for s in picks])[:n]
            bs.append(sample.mean())
    lo, hi = np.percentile(bs, [2.5, 97.5])
    return {"ic": ics.mean(), "pos": (ics > 0).mean(), "n": len(ics), "lo": lo, "hi": hi}


# ────────────────────────── 5. 主流程 ──────────────────────────
def main():
    conn = sqlite3.connect(DB)
    heat, keep, cl = load_heat(conn)
    price, tix, tret = load_price(conn, keep, cl)
    conn.close()
    pn = build_panel(heat, price, tix)
    pn["state_next"] = pn.groupby("main_group").state_tw.shift(-1)
    pn["state_prev"] = pn.groupby("main_group").state_tw.shift(1)
    pn.to_pickle("tmp_heat_flow_panel.pkl")
    base = pn.dropna(subset=["fwd2"])
    print(f"面板: {len(pn)}題材-週 / {pn.main_group.nunique()}題材 / {pn.snapshot_date.nunique()}週; "
          f"有fwd2={len(base)}")
    R = {"asof": str(pn.snapshot_date.max()), "n_panel": len(pn),
         "n_theme": int(pn.main_group.nunique()), "n_week": int(pn.snapshot_date.nunique()),
         "p_thr": [round(float(pn.ret.quantile(1 / 3)), 2), round(float(pn.ret.quantile(2 / 3)), 2)]}

    # --- ①六狀態前瞻報酬(雙量口徑) ---
    for tag in ("tw", "g"):
        rows = []
        for st, sub in base.groupby(f"state_{tag}"):
            rows.append({"state": st, "n": len(sub),
                         "fwd1中位": round(sub.fwd1.median(), 2),
                         "fwd2中位": round(sub.fwd2.median(), 2),
                         "fwd2勝率": round((sub.fwd2 > 0).mean() * 100, 0),
                         "廣度中位": round(sub.breadth.median(), 0)})
        R[f"states_{tag}"] = sorted(rows, key=lambda r: -r["fwd2中位"])
        print(f"\n狀態×前瞻(量口徑={tag}):")
        for r in R[f"states_{tag}"]:
            print("  ", r)

    # --- ②轉移矩陣+兩步序列(主口徑tw) ---
    tm = pd.crosstab(pn.state_tw, pn.state_next, normalize="index").round(2)
    R["transition"] = tm.to_dict()
    seq = (base.dropna(subset=["state_prev"])
           .groupby(["state_prev", "state_tw"])
           .agg(n=("fwd2", "size"), fwd2=("fwd2", "median"), win=("fwd2", lambda s: (s > 0).mean() * 100))
           .reset_index())
    seq = seq[seq.n >= 25].sort_values("fwd2", ascending=False).round(2)
    R["sequences"] = seq.to_dict("records")
    print("\n兩步序列(n≥25):")
    print(seq.to_string(index=False))

    # --- ③RRG象限+預註冊四假說格 ---
    rq = base.dropna(subset=["quad"])
    R["quads"] = [{"quad": q, "n": len(s), "fwd2中位": round(s.fwd2.median(), 2),
                   "勝率": round((s.fwd2 > 0).mean() * 100, 0)}
                  for q, s in rq.groupby("quad")]
    print("\nRRG象限×前瞻:", R["quads"])
    HYP = [("H1埋伏", "轉強", "增平", ">"), ("H2主升", "領先", "增漲", ">"),
           ("H3出貨警", "領先", "增跌", "<"), ("H4退潮", "轉弱", "縮跌", "<")]
    R["hyp"] = []
    for name, q, st, side in HYP:
        cell = rq[(rq.quad == q) & (rq.state_tw == st)]
        if len(cell) < 8:
            R["hyp"].append({"name": name, "n": len(cell), "verdict": "n不足"})
            print(f"{name}: n={len(cell)} 不足")
            continue
        obs, lo, hi, _ = boot_diff_median(cell, rq)
        loto = loto_sign(cell, rq)
        ok = (lo > 0) if side == ">" else (hi < 0)
        R["hyp"].append({"name": name, "cell": f"{q}×{st}", "n": len(cell),
                         "fwd2中位": round(cell.fwd2.median(), 2),
                         "diff": round(obs, 2), "ci": [round(lo, 2), round(hi, 2)],
                         "loto": loto, "verdict": "✅過" if ok else ("同向不顯著" if (obs > 0) == (side == ">") else "反向")})
        print(f"{name} {q}×{st}: n={len(cell)} fwd2={cell.fwd2.median():.2f}% "
              f"diff={obs:+.2f}pp CI[{lo:.2f},{hi:.2f}] LOTO={loto} → {R['hyp'][-1]['verdict']}")

    # --- ③a 四假說格×持有期網格(2026-07-27使用者追問;⚠預註冊只有fwd2,其餘水平=事後探索) ---
    # 判讀(66週牛市段): H3超額集中頭兩週(fwd2唯一CI排0,長水平絕對報酬大但基準也墊高=只剩beta);
    # H2領先x增漲 fwd1負(別追週)但fwd4/8/12跑贏基準≈中期動能仍在→「別追」管進場時點,「領先象限」管題材選擇
    R["hyp_grid"] = []
    for name, q, st, _ in HYP:
        cell_all = rq[(rq.quad == q) & (rq.state_tw == st)]
        row = {"格": f"{name}({q}x{st})", "n": len(cell_all)}
        for h in (1, 2, 4, 8, 12):
            c = cell_all[f"fwd{h}"].dropna()
            b = rq[f"fwd{h}"].dropna()
            row[f"fwd{h}w"] = (f"{c.median():+.1f}%/{(c > 0).mean() * 100:.0f}%"
                               f"(基準{b.median():+.1f}%)") if len(c) >= 8 else "n<8"
        R["hyp_grid"].append(row)

    # --- ③b H3格深掘(2026-07-27使用者裁示:要明細+權益曲線;成員級K棒檢視器=待辦另開) ---
    h3 = rq[(rq.quad == "領先") & (rq.state_tw == "增跌")].sort_values("snapshot_date")
    R["h3_events"] = h3[["snapshot_date", "main_group", "ret", "d_hs_tw", "breadth",
                         "rrg_ratio", "rrg_mom", "fwd1", "fwd2", "fwd4", "n_px"]] \
        .round(2).to_dict("records")
    R["h3_equity"] = {"date": h3.snapshot_date.tolist(),
                      "cum": h3.fwd2.cumsum().round(1).tolist(),
                      "label": [f"{r.main_group}" for r in h3.itertuples()]}
    R["h3_yearly"] = [{"年": y, "n": len(s), "fwd2中位": round(float(s.fwd2.median()), 2),
                       "勝率": round(float((s.fwd2 > 0).mean() * 100), 0)}
                      for y, s in h3.groupby(h3.snapshot_date.str[:4])]
    print(f"\nH3格明細: {len(h3)}事件 逐年={R['h3_yearly']}")

    # --- ④IC體檢(lag0/1/2)+台股vs全球對決 ---
    R["ic"] = {}
    for sig in ["d_hs_tw", "d_hs_g"]:
        for k, rc in [(0, "ret"), (1, "ret_t1"), (2, "ret_t2")]:
            r = weekly_ic(base.dropna(subset=[sig]), sig, rc)
            if r:
                R["ic"][f"{sig}_lag{k}"] = {kk: round(float(vv), 3) for kk, vv in r.items()}
    print("\nIC體檢:", json.dumps(R["ic"], ensure_ascii=False, indent=1))

    # --- ⑤跨市場領先矩陣(各腿Δ→台股題材下1/2週) ---
    R["leadlag"] = {}
    for m in MARKETS:
        for k, rc in [(1, "ret_t1"), (2, "ret_t2")]:
            r = weekly_ic(base.dropna(subset=[f"d_leg_{m}"]), f"d_leg_{m}", rc)
            if r:
                R["leadlag"][f"{m}_lag{k}"] = {kk: round(float(vv), 3) for kk, vv in r.items()}
    print("\n跨市場領先矩陣:", json.dumps(R["leadlag"], ensure_ascii=False, indent=1))

    # --- ⑤b長水平領先(2026-07-27使用者追問): 4週平滑訊號×前瞻4/8/12週,block bootstrap ---
    # ⚠功率警語: 面板64週,fwd8/fwd12重疊窗有效獨立樣本僅~7/~4個,12週結果僅供方向參考
    R["leadlag_long"] = {}
    sigs = [("台smooth", "d4_leg_台"), ("美smooth", "d4_leg_美"), ("日smooth", "d4_leg_日"),
            ("韓smooth", "d4_leg_韓"), ("陸smooth", "d4_leg_陸"), ("全球smooth", "d4_hs_g")]
    for lab, sc in sigs:
        for h in (2, 4, 8, 12):
            sub = pn.dropna(subset=[sc, f"fwd{h}"])
            r = weekly_ic(sub, sc, f"fwd{h}", block=h)
            if r:
                R["leadlag_long"][f"{lab}_fwd{h}w"] = {kk: round(float(vv), 3) for kk, vv in r.items()}
    print("\n長水平領先矩陣(4週平滑訊號,block bootstrap):",
          json.dumps(R["leadlag_long"], ensure_ascii=False, indent=1))

    # --- ⑥位階擁擠度(探索): 熱度位階(trailing≥26週百分位)三分位×fwd2 ---
    pn["hs_pctl"] = (pn.groupby("main_group").hs_g
                     .transform(lambda s: s.expanding(26).rank(pct=True) * 100))
    ex = pn.dropna(subset=["hs_pctl", "fwd2"])
    R["pctl"] = []
    if len(ex) >= 60:
        ex = ex.copy()
        ex["pb"] = pd.cut(ex.hs_pctl, [0, 33, 67, 100], labels=["低位階", "中位階", "高位階"])
        for b, s in ex.groupby("pb", observed=True):
            R["pctl"].append({"位階": str(b), "n": len(s), "fwd2中位": round(s.fwd2.median(), 2),
                              "勝率": round((s.fwd2 > 0).mean() * 100, 0)})
        print("\n位階擁擠度(探索):", R["pctl"])

    # --- ⑦共振事件×熱度Δ分層(探索) ---
    R["reso"] = []
    try:
        ev = pd.read_pickle("tmp_resonance_theme_events.pkl")
        ev = ev[ev.episode_first]
        ev["week"] = pd.to_datetime(ev.week)
        snap_ts = pd.to_datetime(pn.snapshot_date.unique())
        ev["snap"] = ev.week.map(
            lambda w: next((str(s.date()) for s in sorted(snap_ts) if 0 <= (s - w).days <= 4), None))
        j = ev.dropna(subset=["snap"]).merge(
            pn, left_on=["theme", "snap"], right_on=["main_group", "snapshot_date"])
        j = j.dropna(subset=["fwd2", "d_hs_tw"])
        if len(j) >= 20:
            for lab, sub in [("熱度Δ>0", j[j.d_hs_tw > 0]), ("熱度Δ≤0", j[j.d_hs_tw <= 0])]:
                R["reso"].append({"組": lab, "n": len(sub), "fwd2中位": round(sub.fwd2.median(), 2),
                                  "勝率": round((sub.fwd2 > 0).mean() * 100, 0)})
        R["reso_note"] = f"窗內episode_first事件join成功{len(j)}筆"
        print("\n共振×熱度Δ(探索):", R["reso"], R.get("reso_note"))
    except Exception as e:
        R["reso_note"] = f"共振join失敗: {e}"
        print(R["reso_note"])

    # --- 最新一期地圖(儀表板候選) ---
    last = pn[pn.snapshot_date == pn.snapshot_date.max()].dropna(subset=["quad"])
    R["latest"] = last[["main_group", "quad", "state_tw", "ret", "d_hs_tw", "d_hs_g",
                        "breadth", "rrg_ratio", "rrg_mom"]].round(2).to_dict("records")
    print(f"\n最新一期({R['asof']}) {len(last)}題材地圖已存")

    with open("tmp_heat_flow_results.json", "w", encoding="utf-8") as f:
        json.dump(R, f, ensure_ascii=False, indent=1, default=str)
    render_report(pn, R)
    print("\n完成: tmp_heat_flow_panel.pkl / tmp_heat_flow_results.json / 研究報告/research_heat_flow.html")


# ────────────────────────── 6. 報告 ──────────────────────────
def render_report(pn, R):
    import plotly.graph_objects as go
    from plotly.offline import plot as pplot

    # RRG圖: 最新一期,點=題材,尾巴=近6週軌跡,顏色=量價狀態
    last_d = pn.snapshot_date.max()
    tail_ds = sorted(pn.snapshot_date.unique())[-6:]
    cmap = {"增漲": "#e74c3c", "增平": "#f39c12", "增跌": "#8e44ad",
            "縮漲": "#f1a9a0", "縮平": "#95a5a6", "縮跌": "#3498db"}
    fig = go.Figure()
    for g, sub in pn[pn.snapshot_date.isin(tail_ds)].groupby("main_group"):
        s = sub.dropna(subset=["rrg_ratio"]).sort_values("snapshot_date")
        if not len(s) or s.snapshot_date.iloc[-1] != last_d:
            continue
        fig.add_trace(go.Scatter(x=s.rrg_ratio, y=s.rrg_mom, mode="lines",
                                 line=dict(color="#666", width=1), showlegend=False,
                                 hoverinfo="skip"))
        e = s.iloc[-1]
        fig.add_trace(go.Scatter(
            x=[e.rrg_ratio], y=[e.rrg_mom], mode="markers+text", text=[g],
            textposition="top center", textfont=dict(size=10),
            marker=dict(size=9, color=cmap.get(e.state_tw, "#888")),
            name=f"{g} {e.state_tw}", showlegend=False,
            hovertemplate=(f"{g}<br>象限入座標(%{{x:.1f}},%{{y:.1f}})<br>狀態{e.state_tw} "
                           f"週報酬{e.ret:.1f}% 熱度Δtw{e.d_hs_tw:+.2f} 廣度{e.breadth:.0f}%")))
    fig.add_hline(y=100, line_color="#999", line_width=1)
    fig.add_vline(x=100, line_color="#999", line_width=1)
    for x, y, t in [(0.98, 0.98, "領先"), (0.98, 0.02, "轉弱"), (0.02, 0.02, "落後"), (0.02, 0.98, "轉強")]:
        fig.add_annotation(xref="paper", yref="paper", x=x, y=y, text=t, showarrow=False,
                           font=dict(size=16, color="#bbb"))
    fig.update_layout(title=f"題材輪動象限RRG({R['asof']},尾巴=近6週;點色=量價狀態: "
                            "紅=增漲/橙=增平(洗盤候選)/紫=增跌/藍=縮跌)",
                      xaxis_title="RS比率(>100=強於大盤)", yaxis_title="RS動能(>100=加速)",
                      template="plotly_dark", height=680)
    rrg_html = pplot(fig, output_type="div", include_plotlyjs="cdn")

    def tbl(rows, cols=None):
        if not rows:
            return "<p>(無)</p>"
        cols = cols or list(rows[0].keys())
        h = "".join(f"<th>{c}</th>" for c in cols)
        b = "".join("<tr>" + "".join(f"<td>{r.get(c, '')}</td>" for c in cols) + "</tr>" for r in rows)
        return f"<table><tr>{h}</tr>{b}</table>"

    hyp_html = tbl(R["hyp"])
    eqf = go.Figure()
    eqf.add_trace(go.Scatter(x=R["h3_equity"]["date"], y=R["h3_equity"]["cum"],
                             mode="lines+markers", text=R["h3_equity"]["label"],
                             hovertemplate="%{x} %{text}<br>累計%{y}pp",
                             line=dict(color="#e74c3c", width=2), name="H3累計fwd2"))
    eqf.update_layout(title="H3格權益曲線(逐事件fwd2累加,pp;點=事件,hover看題材)",
                      template="plotly_dark", height=380,
                      xaxis_title="事件週", yaxis_title="累計報酬(pp)")
    h3_eq_html = pplot(eqf, output_type="div", include_plotlyjs=False)
    html = f"""<!DOCTYPE html><html lang="zh-Hant"><head><meta charset="utf-8">
<title>題材量價狀態機×輪動象限 研究報告</title><style>
body{{background:#0c1118;color:#dde;font-family:'Microsoft JhengHei',sans-serif;max-width:1100px;margin:auto;padding:20px}}
table{{border-collapse:collapse;margin:10px 0;font-size:13px}}td,th{{border:1px solid #345;padding:4px 10px}}
th{{background:#19253a}}h2{{color:#6cf;border-bottom:1px solid #345;padding-top:14px}}
.warn{{color:#fa5;font-size:13px}}.note{{color:#9ab;font-size:13px;line-height:1.7}}</style></head><body>
<h1>題材量價狀態機 × 輪動象限(RRG) × 熱度Δ預測力體檢</h1>
<p class="note">產出 {R['asof']}|面板 {R['n_panel']} 題材-週 / {R['n_theme']} 題材 / {R['n_week']} 週(2025-04起)|
使用者提案:「熱度只看量,補上價,組合狀態看主流走勢階段」+「輪動象限一起觀察」。<br>
研究目標三層:①描述地圖(本頁RRG+狀態表) ②條件層(象限×狀態格) ③熱度Δ預測力判決(IC/跨市場領先)。<br>
<span class="warn">⚠僅~66週、無完整熊市;價三分位門檻(跌≤{R['p_thr'][0]}%/漲≥{R['p_thr'][1]}%)全樣本切=輕微前視;
四假說格以外皆描述性未預註冊;全部結論觀察層起步。</span></p>
<h2>一、輪動象限地圖(最新一期)</h2>{rrg_html}
<h2>二、預註冊四假說格判決(fwd2週 vs 全面板基準,cluster bootstrap×{N_BOOT}+LOTO)</h2>{hyp_html}
<h3>持有期網格(1/2/4/8/12週;⚠預註冊只有fwd2,其餘=事後探索)</h3>
<p class="note">判讀:H3超額集中頭兩週(fwd2唯一diff CI排0;長水平絕對報酬變大但66週牛市段基準也墊高=只剩市場beta);
H2領先×增漲fwd1負(=別追週)但fwd4/8/12跑贏基準≈強題材中期動能仍在——<b>「別追」管進場時點(1-2週戰術),「領先象限」管題材選擇(1-3月配置),兩條不衝突</b>。</p>
{tbl(R['hyp_grid'])}
<h2>二a、⚠歷史延伸判決(2026-07-27夜,build_heat_flow_hist.py,日資料重建2019~)</h2>
<p class="note"><b>H3與「別追增漲」都被歷史降級為regime相依</b>:台股腿量從fm_daily_price重建(share=成員週成交額/大盤週成交額,
393週/12,798題材-週)——H3全史n=255僅+0.03%/51%(diff-0.29pp CI[-0.85,+0.46]含0),
<b>2022趨勢熊市反向(-1.79%/勝32%,diff-1.05pp=強勢題材放量回檔在熊市是接刀)</b>,有效年集中2024(+1.58pp)/2026(+6.35pp)=恐慌修復年;
增漲格全史+0.41%≈基準=「別追」亦非恆常。驗證閘:重疊期重建版H3+2.14%/68%(rankings版+5.59%/81%)同向但較弱=口徑差+部分運氣。
<span class="warn">⚠倖存者偏差聲明:classification為2025-26整理,回測過去=「今日題材籃子在當年的行為」,絕對報酬偏高,相對差較可信。
結論:下方66週結果=2025-26修復期區域現象。</span><br>
<b>季線regime條件化(使用者假說,提出於看結果前=準預註冊,同日夜考)——H3的開關找到了</b>:
大盤<b>站上季線</b>時H3=+1.40%/勝67%,同regime基準diff+1.22pp CI[+0.74,+2.37]排0,<b>2019-2026逐年7/8正、含2022熊市中站上季線的窗</b>;
<b>跌破季線</b>時同格=-0.83%/42%,diff-1.61pp CI[-2.37,-0.85]排0<b>反向=接刀確認</b>;月線分割較弱(CI含0),季線是主開關。
「別追增漲」regime化後仍不成立(跌破季線反而+0.77pp)=正式撤銷。
<span class="warn">最終口徑=「大盤站上季線 ∧ RRG領先象限 ∧ 量增價跌 → 觀察買點,持有2週」觀察層候選(n=86,倖存者偏差打折,升格待live);儀表板紫點格已掛季線開關徽章。</span><br>
<b>雙開關×持有期網格(使用者裁示補考,詳build_heat_flow_hist.py輸出dual_switch)</b>:
H3主開關=季線(月線CI含0),持有2~4週顯著(2w+1.22◄/4w+1.72◄,6週後失顯著);
H5(落後×增漲×熊市)雙開關皆通且<b>1~8週全水平顯著遞增</b>(季線版1w+1.31→8w+4.85pp,深熊月線版8w+8.18pp=可以抱著騎);
H6(轉強×縮漲×熊市)主開關=季線,1~2週快打(4週後死)。⚠6/8週重疊窗CI偏樂觀,H5單調性是主要依據。</p>
<h2>二b、H3格深掘:領先象限×量增價跌=「強勢題材放量回檔是買點」(原假說「出貨警」完全反向;⚠見二a歷史降級)</h2>
<p class="note">「被洗越慘反彈越肥」定理第五度重現、首次在題材層。逐年分割:{json.dumps(R['h3_yearly'], ensure_ascii=False)}<br>
<span class="warn">⚠n={len(R['h3_events'])}小樣本;權益曲線=逐事件fwd2累加(概念曲線,未做資金加權/併發控制);
成員級K棒檢視器(比照處置股research_disposition_trades.html)=待辦。</span></p>
{h3_eq_html}
<h3>H3事件明細(進場口徑=訊號週收盤確認後次週,持有2週)</h3>
{tbl(R['h3_events'])}
<h2>三、六狀態×前瞻報酬</h2>
<h3>量口徑=台股腿(主)</h3>{tbl(R['states_tw'])}
<h3>量口徑=五市場全球(輔)</h3>{tbl(R['states_g'])}
<h2>四、兩步序列(n≥25,描述性)</h2>{tbl(R['sequences'])}
<h2>五、RRG象限×前瞻</h2>{tbl(R['quads'])}
<h2>六、IC體檢+跨市場領先矩陣(逐週跨題材Spearman均值,CI=週bootstrap)</h2>
<p class="note">判決:單週Δ無領先(lag1/lag2≈0)=事後儀表;但<b>4週平滑熱度趨勢在2-4週水平有溫和領先
(台fwd4w IC+0.091/美fwd2w+0.075正週72%/全球fwd4w+0.093,CI排0;日韓無;8-12週衰減)=月級傾斜因子候選</b>。
<span class="warn">⚠IC~0.06-0.09只夠當傾斜不夠當獨立訊號;重疊窗block bootstrap仍偏樂觀;24格多重比較下型態連貫性(台美全球一致)是主要依據。</span></p>
<pre class="note">{json.dumps(R['ic'], ensure_ascii=False, indent=1)}</pre>
<h3>單週Δ領先(原考)</h3>
<pre class="note">{json.dumps(R['leadlag'], ensure_ascii=False, indent=1)}</pre>
<h3>4週平滑×長水平(2/4/8/12週,使用者追問加考)</h3>
<pre class="note">{json.dumps(R['leadlag_long'], ensure_ascii=False, indent=1)}</pre>
<h2>七、探索節(未預註冊)</h2>
<h3>熱度位階擁擠度</h3>{tbl(R['pctl'])}
<h3>共振事件×熱度Δ</h3>{tbl(R['reso'])}<p class="note">{R.get('reso_note', '')}</p>
<h2>八、最新一期全題材狀態表</h2>
{tbl(R['latest'], ['main_group', 'quad', 'state_tw', 'ret', 'd_hs_tw', 'd_hs_g', 'breadth'])}
</body></html>"""
    with open("研究報告/research_heat_flow.html", "w", encoding="utf-8") as f:
        f.write(html)


if __name__ == "__main__":
    main()
