# -*- coding: utf-8 -*-
"""一週大賺股逆向工程 + 拉回進場規則對決(2026-08-08,使用者指定方法論:先定義結果再挖特徵)。

使用者目標: **持有一週(5交易日)、勝率高、賺賠比>=1.5**。專案現況缺口=既有活口全是20-40日中慢線,
週級動能是勝率46-49%的肥右尾(與目標相反)。本卷從零開始建這條線。

═══ 兩階段設計(預先註冊) ═══
【階段一 逆向工程(不預設型態)】
  母體: 20日均額>=0.3億流動池;抽樣=每5個交易日一次(fwd5窗不重疊,避免自相關灌水)。
  結果變數: fwd5 = **次日收盤進場 → 第5個交易日收盤出場**(可執行口徑,零前視)。
  贏家=同日橫斷面fwd5前5%;輸家=後5%;對照=同日全池。
  特徵(全部t日收盤已知): ①位置(距20/60/126日高) ②近期動能(ret5/ret20) ③當日K棒(實體/上下影)
  ④型態史(近20日有無漲停/長紅、距最近長紅天數) ⑤拉回結構(從20日高回檔幅度、距5/10/20日均線)
  ⑥量能(當日量/20日均量、5日均量/20日均量、20日均額=熱門度) ⑦波動(20日年化) ⑧題材(成員/題材20日動能)
  ⑨營收(兩月連創) ⑩籌碼(千張大戶4週變化)。
  輸出=贏家畫像(特徵中位數 vs 全池)+每個特徵的同日五分位fwd5階梯(看單調性,比AUC好讀)。
【階段二 規則對決(把畫像翻成可執行策略)】
  R1長紅/漲停後拉回到5日線 / R2新高後淺回(<=3%) / R3深回檔接刀(>=8%) / R4純追高(對照,不等拉回)
  / R5題材成員×拉回 / R6熱門股(均額>=3億)×拉回。每條: 勝率/賺賠比/期望值/逐年/扣0.3%與0.5%成本。
  **判準: 賺賠比>=1.5 且 勝率>=50% 且 成本後期望值>0 才算達標(使用者目標,預先註冊)。**
用法: python 研究腳本/綜合策略/build_week_winner_anatomy.py  (從根目錄執行,鐵律)
產出: 研究報告/research_week_winner.html + console
"""
import sys
import sqlite3

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

DB = "capital_flow.db"
OUT = "研究報告/research_week_winner.html"
LIQ_MIN = 0.3e8
SAMPLE_EVERY = 5           # 每5交易日抽樣(fwd5不重疊)
HOLD = 5
rng = np.random.default_rng(20260808)


def main():
    conn = sqlite3.connect(DB, timeout=120)
    px = pd.read_sql("SELECT code,date,open,high,low,close,volume,money FROM fm_daily_price "
                     "WHERE date>='2014-06-01' AND close>0 AND money>0 AND open>0", conn)
    tai = pd.read_sql("SELECT date,close FROM index_daily WHERE market='TAIEX' AND date>='2014-06-01' "
                      "ORDER BY date", conn)
    rev = pd.read_sql("SELECT code,date,revenue FROM fm_month_rev", conn, parse_dates=["date"])
    td = pd.read_sql("SELECT code,date,p1000 FROM tdcc_weekly", conn, parse_dates=["date"])
    cls = pd.read_sql("SELECT code,main_group FROM classification WHERE country='台'", conn)
    conn.close()

    piv = lambda c: px.pivot_table(index="date", columns="code", values=c, aggfunc="first").sort_index()
    C, O, H, L, V, MN = piv("close"), piv("open"), piv("high"), piv("low"), piv("volume"), piv("money")
    Cf = C.ffill(limit=3)
    tai = tai.set_index("date")["close"].reindex(C.index).ffill()
    dates = list(C.index)
    print(f"[panel] {C.shape[0]}日×{C.shape[1]}檔 {dates[0]}~{dates[-1]}")

    # ---- 特徵矩陣(全部t日收盤可知) ----
    F = {}
    F["dist20"] = (C / C.rolling(20, min_periods=15).max() - 1) * 100
    F["dist60"] = (C / C.rolling(60, min_periods=45).max() - 1) * 100
    F["dist126"] = (C / C.rolling(126, min_periods=100).max() - 1) * 100
    F["ret5"] = (C / C.shift(5) - 1) * 100
    F["ret20"] = (C / C.shift(20) - 1) * 100
    F["body"] = (C / O - 1) * 100
    rng_hl = (H - L).replace(0, np.nan)
    F["upwick"] = ((H - np.maximum(C, O)) / rng_hl * 100)
    F["lowick"] = ((np.minimum(C, O) - L) / rng_hl * 100)
    chg = C.pct_change() * 100
    limitup = (chg >= 9.0)
    longbar = (chg >= 5.0)
    F["n_limitup20"] = limitup.rolling(20, min_periods=10).sum()
    F["n_longbar20"] = longbar.rolling(20, min_periods=10).sum()
    # 距最近長紅天數(0=今天就是)
    idx_arr = np.arange(len(C))[:, None] * np.ones((1, C.shape[1]))
    last_lb = pd.DataFrame(np.where(longbar.values, idx_arr, np.nan), index=C.index, columns=C.columns).ffill()
    F["days_since_longbar"] = pd.DataFrame(idx_arr, index=C.index, columns=C.columns) - last_lb
    ma5, ma10, ma20 = (C.rolling(w, min_periods=w - 2).mean() for w in (5, 10, 20))
    F["ma5_dist"] = (C / ma5 - 1) * 100
    F["ma10_dist"] = (C / ma10 - 1) * 100
    F["ma20_dist"] = (C / ma20 - 1) * 100
    v20 = V.rolling(20, min_periods=15).mean()
    F["vol_ratio"] = V / v20
    F["vol_trend"] = V.rolling(5, min_periods=4).mean() / v20
    F["money20"] = MN.rolling(20, min_periods=15).mean() / 1e8      # 億元(熱門度)
    F["vol20_ann"] = C.pct_change().rolling(20, min_periods=15).std() * np.sqrt(252) * 100
    F["amp20"] = ((H - L) / C).rolling(20, min_periods=15).mean() * 100

    theme_of = cls.groupby("code").main_group.first().to_dict()
    is_theme = pd.DataFrame(np.tile([[1.0 if c in theme_of else 0.0 for c in C.columns]], (len(C), 1)),
                            index=C.index, columns=C.columns)
    F["is_theme"] = is_theme
    tm = {}
    for t in set(theme_of.values()):
        mem = [c for c in theme_of if theme_of[c] == t and c in C.columns]
        if len(mem) >= 2:
            s = C[mem].mean(axis=1)
            tm[t] = (s / s.shift(20) - 1) * 100
    theme_mom = pd.DataFrame(index=C.index, columns=C.columns, dtype=float)
    for t, s in tm.items():
        mem = [c for c in theme_of if theme_of[c] == t and c in C.columns]
        for c in mem:
            theme_mom[c] = s
    F["theme_mom"] = theme_mom

    rev_w = rev.pivot_table(index="date", columns="code", values="revenue", aggfunc="first").sort_index()
    hi_rev = ((rev_w >= rev_w.rolling(12, min_periods=12).max()) & rev_w.notna()).astype(float)
    r1_m = (hi_rev * hi_rev.shift(1))                       # 兩月連創
    r1_daily = r1_m.copy()
    r1_daily.index = [(m + pd.DateOffset(months=1) + pd.Timedelta(days=11)) for m in r1_m.index]
    F["rev_r1"] = r1_daily.reindex(pd.to_datetime(C.index), method="ffill").set_axis(C.index).reindex(
        columns=C.columns)
    td_w = td.pivot_table(index="date", columns="code", values="p1000", aggfunc="first").sort_index()
    d4w = (td_w - td_w.shift(4))
    F["d4w"] = d4w.reindex(pd.to_datetime(C.index), method="ffill").set_axis(C.index).reindex(columns=C.columns)

    # ---- 結果變數: 次日收盤進 → +5日收盤出 ----
    entry = Cf.shift(-1)
    exit_ = Cf.shift(-(1 + HOLD))
    fwd5 = (exit_ / entry - 1) * 100
    tai_e = tai.shift(-1)
    tai_x = tai.shift(-(1 + HOLD))
    fwd5_bench = (tai_x / tai_e - 1) * 100
    fwd5_dm = fwd5.sub(fwd5_bench, axis=0)

    pool = (MN.rolling(20, min_periods=15).mean().shift(1) >= LIQ_MIN) & C.notna() & entry.notna() & exit_.notna()
    start_i = int(np.searchsorted(np.array(dates), "2015-01-01"))
    samp = list(range(start_i, len(dates) - HOLD - 2, SAMPLE_EVERY))
    print(f"[sample] 抽樣日{len(samp)}個(每{SAMPLE_EVERY}交易日)")

    recs = []
    feat_names = list(F.keys())
    for i in samp:
        m = pool.iloc[i].values
        if m.sum() < 50:
            continue
        codes = C.columns[m].to_numpy()      # ⚠必須轉ndarray: 否則下方isinstance判斷失效,
        d = dates[i]                          #   code欄會被填成重複的Index物件(v3/v4貼回時報unhashable)
        row = {"d": d, "ym": d[:7], "yr": d[:4], "code": codes,
               "fwd5": fwd5.iloc[i].values[m], "fwd5dm": fwd5_dm.iloc[i].values[m]}
        for fn in feat_names:
            row[fn] = F[fn].iloc[i].values[m]
        recs.append(row)
    D = pd.concat([pd.DataFrame({k: (v if isinstance(v, np.ndarray) else [v] * len(r["code"]))
                                 for k, v in r.items()}) for r in recs], ignore_index=True)
    D = D.dropna(subset=["fwd5"])
    print(f"[data] 樣本{len(D):,}筆 ({D.d.nunique()}個抽樣日); "
          f"fwd5均{D.fwd5.mean():+.2f}% 中位{D.fwd5.median():+.2f}% 勝率{(D.fwd5 > 0).mean() * 100:.0f}%")

    # ══ v2(2026-08-08使用者兩項修正) ══
    # ①胃納量: 小成交值股要剔除(0.3億池太寬,實務吃不到量)——改用1億/3億/5億三檔母體對決
    # ②出發點改基本面: 先限定「月營收表現好」再看型態,而非全池撈型態
    print("\n" + "=" * 100)
    print("【v2-①胃納量】母體成交值門檻對決(同一組規則,只換池)")
    liq_bands = [("A 0.3億(原池)", 0.3), ("B 1億", 1.0), ("C 3億", 3.0), ("D 5億", 5.0)]
    base_rules = {
        "R7漲停後拉回": (D.n_limitup20 >= 1) & (D.days_since_longbar.between(1, 5)) & (D.ma5_dist < 2),
        "R1長紅後拉回5日線": (D.n_longbar20 >= 1) & (D.days_since_longbar.between(1, 5)) &
                        (D.ma5_dist.between(-3, 1)),
        "R5題材×淺回": (D.is_theme == 1) & (D.dist20 >= -3) & (D.dist20 < 0) & (D.theme_mom > 0),
        "(基準)全池": pd.Series(True, index=D.index),
    }
    liq_res = []
    for lab_r, mask_r in base_rules.items():
        for lab_l, th in liq_bands:
            sub = D[mask_r.fillna(False) & (D.money20 >= th)]
            if len(sub) < 300:
                continue
            w, l = sub.fwd5[sub.fwd5 > 0], sub.fwd5[sub.fwd5 <= 0]
            wl = (w.mean() / abs(l.mean())) if len(w) and len(l) else np.nan
            liq_res.append({"rule": lab_r, "liq": lab_l, "n": len(sub), "mean": sub.fwd5.mean(),
                            "win": (sub.fwd5 > 0).mean() * 100, "wl": wl,
                            "c05": sub.fwd5.mean() - 0.5})
            print(f"  {lab_r:<18}{lab_l:<12} n={len(sub):>7,} 均{sub.fwd5.mean():+.2f}% "
                  f"勝率{(sub.fwd5 > 0).mean() * 100:.0f}% 賺賠{wl:.2f} 扣0.5%{sub.fwd5.mean() - 0.5:+.2f}%")

    print("\n【v2-②基本面出發點】先限定月營收表現好,再看型態")
    D["rev_ok"] = (D.rev_r1 == 1)
    fund_res = []
    fund_sets = [
        ("F0 全池(對照)", pd.Series(True, index=D.index)),
        ("F1 營收兩月連創高", D.rev_ok),
        ("F2 營收連創×均額>=1億", D.rev_ok & (D.money20 >= 1.0)),
        ("F3 營收連創×均額>=3億", D.rev_ok & (D.money20 >= 3.0)),
        ("F4 營收連創×題材成員", D.rev_ok & (D.is_theme == 1)),
        ("F5 營收連創×題材動能正", D.rev_ok & (D.theme_mom > 0)),
        ("F6 營收連創×淺回(dist20 -3~0)", D.rev_ok & (D.dist20 >= -3) & (D.dist20 < 0)),
        ("F7 營收連創×長紅後拉回", D.rev_ok & (D.n_longbar20 >= 1) &
         (D.days_since_longbar.between(1, 5)) & (D.ma5_dist.between(-3, 1))),
        ("F8 營收連創×題材動能×淺回", D.rev_ok & (D.theme_mom > 0) & (D.dist20 >= -3) & (D.dist20 < 0)),
        ("F9 營收連創×均額1億×淺回", D.rev_ok & (D.money20 >= 1.0) & (D.dist20 >= -3) & (D.dist20 < 0)),
        ("F10 營收連創×均額1億×長紅拉回", D.rev_ok & (D.money20 >= 1.0) & (D.n_longbar20 >= 1) &
         (D.days_since_longbar.between(1, 5)) & (D.ma5_dist.between(-3, 1))),
        # v2-④ 依贏家畫像追加: 題材動能是唯一「贏家>輸家」的特徵;波動度反而「贏家<輸家」
        ("F11 F10×題材動能正", D.rev_ok & (D.money20 >= 1.0) & (D.n_longbar20 >= 1) &
         (D.days_since_longbar.between(1, 5)) & (D.ma5_dist.between(-3, 1)) & (D.theme_mom > 0)),
        ("F12 F11×波動<中位(排除過熱)", D.rev_ok & (D.money20 >= 1.0) & (D.n_longbar20 >= 1) &
         (D.days_since_longbar.between(1, 5)) & (D.ma5_dist.between(-3, 1)) & (D.theme_mom > 0) &
         (D.vol20_ann < 55)),
        ("F13 F10×波動<55(不加題材)", D.rev_ok & (D.money20 >= 1.0) & (D.n_longbar20 >= 1) &
         (D.days_since_longbar.between(1, 5)) & (D.ma5_dist.between(-3, 1)) & (D.vol20_ann < 55)),
        ("F14 營收連創×1億×漲停後拉回", D.rev_ok & (D.money20 >= 1.0) & (D.n_limitup20 >= 1) &
         (D.days_since_longbar.between(1, 5)) & (D.ma5_dist < 2)),
    ]
    for lab, mask in fund_sets:
        sub = D[mask.fillna(False)]
        if len(sub) < 200:
            print(f"  {lab:<32} n={len(sub)} 不足")
            continue
        w, l = sub.fwd5[sub.fwd5 > 0], sub.fwd5[sub.fwd5 <= 0]
        wl = (w.mean() / abs(l.mean())) if len(w) and len(l) else np.nan
        winr = (sub.fwd5 > 0).mean() * 100
        exp0 = sub.fwd5.mean()
        y = sub.groupby("yr").fwd5.mean()
        ok = (wl >= 1.5) and (winr >= 50) and (exp0 - 0.3 > 0)
        fund_res.append({"lab": lab, "n": len(sub), "per_yr": len(sub) / 11.5, "mean": exp0,
                         "dm": sub.fwd5dm.mean(), "win": winr, "wl": wl, "c03": exp0 - 0.3,
                         "c05": exp0 - 0.5, "yr": f"{int((y > 0).sum())}/{len(y)}", "pass": ok})
        print(f"  {'✅' if ok else '  '}{lab:<32} n={len(sub):>6,}({len(sub)/11.5:.0f}/年) "
              f"均{exp0:+.2f}%/dm{sub.fwd5dm.mean():+.2f}% 勝率{winr:.0f}% 賺賠{wl:.2f} "
              f"扣0.5%{exp0 - 0.5:+.2f}% 逐年{y.gt(0).sum()}/{len(y)}")

    # ══ v3(2026-08-08使用者提問): 絕對門檻(1億)換成「佔市場成交值%」相對門檻,並分上市/上櫃 ══
    print("\n" + "=" * 100)
    print("【v3 相對流動性門檻 × 分市場】絕對1億 vs 佔市場成交值% vs 市場內分位")
    try:
        mkt_csv = pd.read_csv("tw_all_listed.csv", dtype=str).dropna(subset=["code"])
        mkt_of = dict(zip(mkt_csv.code, mkt_csv.market.fillna("")))
        is_otc_arr = np.array([("櫃" in mkt_of.get(c, "")) for c in C.columns])
        is_sii_arr = np.array([(mkt_of.get(c, "") == "上市") for c in C.columns])
        mn20 = MN.rolling(20, min_periods=15).mean()
        tot_sii = mn20.loc[:, is_sii_arr].sum(axis=1)
        tot_otc = mn20.loc[:, is_otc_arr].sum(axis=1)
        share = pd.DataFrame(index=mn20.index, columns=mn20.columns, dtype=float)
        share.loc[:, is_sii_arr] = mn20.loc[:, is_sii_arr].div(tot_sii, axis=0) * 10000   # 基點(bp)
        share.loc[:, is_otc_arr] = mn20.loc[:, is_otc_arr].div(tot_otc, axis=0) * 10000
        # 市場內橫斷面分位(0-1)
        rank_sii = mn20.loc[:, is_sii_arr].rank(axis=1, pct=True)
        rank_otc = mn20.loc[:, is_otc_arr].rank(axis=1, pct=True)
        rank_all = pd.DataFrame(index=mn20.index, columns=mn20.columns, dtype=float)
        rank_all.loc[:, is_sii_arr] = rank_sii
        rank_all.loc[:, is_otc_arr] = rank_otc
        # 貼回抽樣樣本
        code_pos = {c: i for i, c in enumerate(C.columns)}
        D["share_bp"] = [share.at[d, c] if (d in share.index and c in share.columns) else np.nan
                         for d, c in zip(D.d, D.code)]
        D["liq_rank"] = [rank_all.at[d, c] if (d in rank_all.index and c in rank_all.columns) else np.nan
                         for d, c in zip(D.d, D.code)]
        D["mkt"] = [("上櫃" if is_otc_arr[code_pos[c]] else ("上市" if is_sii_arr[code_pos[c]] else "其他"))
                    for c in D.code]
        print(f"  佔市場成交值(bp)分布: 中位{D.share_bp.median():.1f}bp "
              f"(P75={D.share_bp.quantile(.75):.1f}/P90={D.share_bp.quantile(.9):.1f}/"
              f"P95={D.share_bp.quantile(.95):.1f}); 上市{int((D.mkt == '上市').sum()):,}筆/"
              f"上櫃{int((D.mkt == '上櫃').sum()):,}筆")
        base = D.rev_ok & (D.n_longbar20 >= 1) & (D.days_since_longbar.between(1, 5)) & \
            (D.ma5_dist.between(-3, 1)) & (D.theme_mom > 0)      # =F11去掉流動性條件
        liq_defs = [
            ("L0 無流動性門檻", pd.Series(True, index=D.index)),
            ("L1 絕對>=1億(現用)", D.money20 >= 1.0),
            ("L2 絕對>=3億", D.money20 >= 3.0),
            ("L3 佔市場>=3bp(0.03%)", D.share_bp >= 3),
            ("L4 佔市場>=5bp(0.05%)", D.share_bp >= 5),
            ("L5 佔市場>=10bp(0.1%)", D.share_bp >= 10),
            ("L6 市場內分位>=70%", D.liq_rank >= 0.70),
            ("L7 市場內分位>=85%", D.liq_rank >= 0.85),
        ]
        v3 = []
        for lab, lm in liq_defs:
            sub = D[(base & lm).fillna(False)]
            if len(sub) < 120:
                print(f"  {lab:<24} n={len(sub)} 不足")
                continue
            w, l = sub.fwd5[sub.fwd5 > 0], sub.fwd5[sub.fwd5 <= 0]
            wl = (w.mean() / abs(l.mean())) if len(w) and len(l) else np.nan
            winr = (sub.fwd5 > 0).mean() * 100
            m = sub.fwd5.mean()
            ok = (wl >= 1.5) and (winr >= 50) and (m - 0.3 > 0)
            v3.append({"lab": lab, "n": len(sub), "mean": m, "win": winr, "wl": wl,
                       "c05": m - 0.5, "pass": ok, "seg": "全體"})
            print(f"  {'✅' if ok else '  '}{lab:<24} n={len(sub):>5,}({len(sub)/11.5:.0f}/年) "
                  f"均{m:+.2f}% 勝率{winr:.0f}% 賺賠{wl:.2f} 扣0.5%{m - 0.5:+.2f}%")
        print("\n  分市場(用最佳相對門檻L6市場內分位>=70% 與 現用L1絕對1億 對照)")
        for seg in ("上市", "上櫃"):
            for lab, lm in (("L1絕對1億", D.money20 >= 1.0), ("L6分位>=70%", D.liq_rank >= 0.70),
                            ("L4佔市場>=5bp", D.share_bp >= 5)):
                sub = D[(base & lm & (D.mkt == seg)).fillna(False)]
                if len(sub) < 80:
                    print(f"    {seg}×{lab:<16} n={len(sub)} 不足")
                    continue
                w, l = sub.fwd5[sub.fwd5 > 0], sub.fwd5[sub.fwd5 <= 0]
                wl = (w.mean() / abs(l.mean())) if len(w) and len(l) else np.nan
                winr = (sub.fwd5 > 0).mean() * 100
                m = sub.fwd5.mean()
                ok = (wl >= 1.5) and (winr >= 50) and (m - 0.3 > 0)
                v3.append({"lab": f"{seg}×{lab}", "n": len(sub), "mean": m, "win": winr, "wl": wl,
                           "c05": m - 0.5, "pass": ok, "seg": seg})
                print(f"    {'✅' if ok else '  '}{seg}×{lab:<16} n={len(sub):>5,} 均{m:+.2f}% "
                      f"勝率{winr:.0f}% 賺賠{wl:.2f} 扣0.5%{m - 0.5:+.2f}%")
    except Exception as e:
        print(f"  [v3] 計算失敗({e})")
        v3 = []

    # ══ v4(2026-08-08使用者:「基本面爛的呢?全方位分組找寶藏」) ══
    # 基本面三分: 好(兩月連創高) / 中(有營收資料但未連創) / 爛(近3月營收YoY<0) / 無資料
    print("\n" + "=" * 100)
    print("【v4 全方位分組】基本面好/中/爛/無 × 型態(長紅拉回/淺回/追高) —— 找反向寶藏")
    try:
        yoy3_m = (rev_w.rolling(3).sum() / rev_w.shift(12).rolling(3).sum() - 1) * 100
        yoy3_d = yoy3_m.copy()
        yoy3_d.index = [(m + pd.DateOffset(months=1) + pd.Timedelta(days=11)) for m in yoy3_m.index]
        yoy3_daily = yoy3_d.reindex(pd.to_datetime(C.index), method="ffill").set_axis(C.index).reindex(
            columns=C.columns)
        D["yoy3"] = [yoy3_daily.at[d, c] if (d in yoy3_daily.index and c in yoy3_daily.columns) else np.nan
                     for d, c in zip(D.d, D.code)]
        fund_grades = [
            ("好(兩月連創高)", D.rev_ok),
            ("中(有營收未連創,YoY>=0)", (~D.rev_ok) & (D.yoy3 >= 0)),
            ("爛(近3月YoY<0)", D.yoy3 < 0),
            ("很爛(YoY<-20%)", D.yoy3 < -20),
            ("無營收資料", D.yoy3.isna()),
        ]
        patterns = [
            ("長紅後拉回5日線", (D.n_longbar20 >= 1) & (D.days_since_longbar.between(1, 5)) &
             (D.ma5_dist.between(-3, 1))),
            ("淺回(dist20 -3~0)", (D.dist20 >= -3) & (D.dist20 < 0)),
            ("深回檔(<=-8%)", D.dist20 <= -8),
            ("純追高(貼20日高)", D.dist20 >= -0.5),
            ("(不限型態)", pd.Series(True, index=D.index)),
        ]
        liqm = D.money20 >= 1.0
        v4 = []
        print(f"  {'基本面':<22}{'型態':<20}{'n':>7}{'均':>8}{'勝率':>7}{'賺賠':>7}{'扣0.5%':>9}")
        for fl, fm in fund_grades:
            for pl, pm in patterns:
                sub = D[(fm & pm & liqm).fillna(False)]
                if len(sub) < 150:
                    continue
                w, l = sub.fwd5[sub.fwd5 > 0], sub.fwd5[sub.fwd5 <= 0]
                wl = (w.mean() / abs(l.mean())) if len(w) and len(l) else np.nan
                winr = (sub.fwd5 > 0).mean() * 100
                m = sub.fwd5.mean()
                ok = (wl >= 1.5) and (winr >= 50) and (m - 0.3 > 0)
                v4.append({"fund": fl, "pat": pl, "n": len(sub), "mean": m, "win": winr,
                           "wl": wl, "c05": m - 0.5, "pass": ok})
                print(f"  {'✅' if ok else '  '}{fl:<20}{pl:<20}{len(sub):>7,}{m:>+8.2f}"
                      f"{winr:>6.0f}%{wl:>7.2f}{m - 0.5:>+9.2f}")
        # 反向寶藏檢查: 基本面爛 × 各型態 的最差格(是否有做空價值/或要避開的格)
        bad = [x for x in v4 if x["fund"].startswith(("爛", "很爛"))]
        if bad:
            worst = min(bad, key=lambda x: x["mean"])
            best_bad = max(bad, key=lambda x: x["wl"])
            print(f"\n  基本面爛組: 最差格={worst['fund']}×{worst['pat']} 均{worst['mean']:+.2f}%/"
                  f"勝率{worst['win']:.0f}%(=要避開或反向候選); "
                  f"賺賠最高格={best_bad['fund']}×{best_bad['pat']} 賺賠{best_bad['wl']:.2f}")
    except Exception as e:
        print(f"  [v4] 計算失敗({e})")
        v4 = []

    # ══ v5(2026-08-08使用者): F11在「長紅拉回」裡抓到幾成?剩下的贏家有什麼特徵? ══
    print("\n" + "=" * 100)
    print("【v5-A 覆蓋率】長紅拉回母體(均額>=1億)中,F11條件抓到多少?贏家的召回率?")
    LB = (D.n_longbar20 >= 1) & (D.days_since_longbar.between(1, 5)) & (D.ma5_dist.between(-3, 1)) & \
         (D.money20 >= 1.0)
    M = D[LB.fillna(False)].copy()
    M["rk"] = M.groupby("d").fwd5.rank(pct=True)
    f11 = M.rev_ok & (M.theme_mom > 0)
    n_all, n_f11 = len(M), int(f11.sum())
    win_all = M[M.rk >= 0.9]
    n_win_f11 = int((win_all.rev_ok & (win_all.theme_mom > 0)).sum())
    print(f"  長紅拉回母體 n={n_all:,}; F11(營收連創×題材動能正)命中 {n_f11:,} = {n_f11/n_all*100:.1f}%(精選度)")
    print(f"  母體贏家(同日fwd5前10%) n={len(win_all):,}; 其中F11佔 {n_win_f11:,} = "
          f"{n_win_f11/len(win_all)*100:.1f}%(**召回率**) → 約 {100-n_win_f11/len(win_all)*100:.0f}% 的贏家被F11漏掉")
    rest = M[~f11.fillna(False)]
    w, l = rest.fwd5[rest.fwd5 > 0], rest.fwd5[rest.fwd5 <= 0]
    print(f"  被漏掉的其餘 n={len(rest):,} 均{rest.fwd5.mean():+.2f}% 勝率{(rest.fwd5>0).mean()*100:.0f}% "
          f"賺賠{(w.mean()/abs(l.mean())):.2f} ← 這裡面還有沒有寶?下面找")

    def cell(sub, lab, out=None, indent="  "):
        if len(sub) < 120:
            print(f"{indent}{lab:<30} n={len(sub)} 不足")
            return None
        w2, l2 = sub.fwd5[sub.fwd5 > 0], sub.fwd5[sub.fwd5 <= 0]
        wl2 = (w2.mean() / abs(l2.mean())) if len(w2) and len(l2) else np.nan
        winr = (sub.fwd5 > 0).mean() * 100
        m2 = sub.fwd5.mean()
        ok = (wl2 >= 1.5) and (winr >= 50) and (m2 - 0.3 > 0)
        r = {"lab": lab, "n": len(sub), "mean": m2, "win": winr, "wl": wl2, "c05": m2 - 0.5, "pass": ok}
        if out is not None:
            out.append(r)
        print(f"{indent}{'✅' if ok else '  '}{lab:<28} n={len(sub):>6,} 均{m2:+.2f}% "
              f"勝率{winr:.0f}% 賺賠{wl2:.2f} 扣0.5%{m2-0.5:+.2f}%")
        return r

    print("\n【v5-B 日曆效應】長紅拉回 × 月內日期(營收10日公布/月底作帳等)")
    v5b = []
    dom = pd.to_datetime(M.d).dt.day
    for lab, mask in [("月初1-5日", dom <= 5), ("營收公布期6-12日", dom.between(6, 12)),
                      ("月中13-20日", dom.between(13, 20)), ("月底21日以後", dom >= 21)]:
        cell(M[mask.values], lab, v5b)
    print("  (交乘: F11 × 日期)")
    for lab, mask in [("F11×營收公布期6-12日", f11.values & dom.between(6, 12).values),
                      ("F11×其他日期", f11.values & ~dom.between(6, 12).values)]:
        cell(M[mask], lab, v5b)

    print("\n【v5-C 大盤環境】長紅拉回 × TAIEX近5日報酬(集體大跌後的長紅?)")
    v5c = []
    tai_r5 = (tai / tai.shift(5) - 1) * 100
    M["tai5"] = [tai_r5.get(d, np.nan) for d in M.d]
    for lab, mask in [("大盤近5日<=-3%(急殺後)", M.tai5 <= -3), ("大盤-3~0%", M.tai5.between(-3, 0)),
                      ("大盤0~3%", M.tai5.between(0, 3)), ("大盤>3%(追漲期)", M.tai5 > 3)]:
        cell(M[mask.fillna(False)], lab, v5c)
    print("  (交乘: F11 × 大盤環境)")
    for lab, mask in [("F11×大盤急殺(<=-3%)", f11.fillna(False) & (M.tai5 <= -3)),
                      ("F11×大盤正常(>-3%)", f11.fillna(False) & (M.tai5 > -3))]:
        cell(M[mask.fillna(False)], lab, v5c)

    print("\n【v5-D 事件疊加】財報季/法說會/庫藏股宣告")
    v5d = []
    try:
        conn2 = sqlite3.connect(DB, timeout=60)
        conf = pd.read_sql("SELECT code, date FROM conference WHERE date>='2014-06-01'", conn2)
        bb2 = pd.read_sql("SELECT code, board_date FROM tw_buyback", conn2)
        conn2.close()
        conf_set = set(zip(conf.code, conf.date))
        conf_by_code = {}
        for c, d in zip(conf.code, conf.date):
            conf_by_code.setdefault(c, []).append(d)
        for c in conf_by_code:
            conf_by_code[c] = sorted(conf_by_code[c])

        def near_conf(code, d, back=10, fwd=3):
            lst = conf_by_code.get(code)
            if not lst:
                return False
            i2 = np.searchsorted(lst, d)
            for j in range(max(0, i2 - 1), min(len(lst), i2 + 1)):
                dd = (pd.Timestamp(lst[j]) - pd.Timestamp(d)).days
                if -back <= dd <= fwd:
                    return True
            return False

        M["near_conf"] = [near_conf(c, d) for c, d in zip(M.code, M.d)]
        bb_by_code = {}
        for c, d in zip(bb2.code, bb2.board_date):
            if d:
                bb_by_code.setdefault(c, []).append(d)
        M["near_bb"] = [any(0 <= (pd.Timestamp(d) - pd.Timestamp(x)).days <= 20
                            for x in bb_by_code.get(c, [])) for c, d in zip(M.code, M.d)]
        mth = pd.to_datetime(M.d).dt.month
        fin_season = mth.isin([3, 5, 8, 11]).values & (dom <= 20).values
        cell(M[M.near_conf], "法說會前後(前10~後3日)", v5d)
        cell(M[~M.near_conf], "非法說會期", v5d)
        cell(M[fin_season], "財報公布季(3/5/8/11月上中旬)", v5d)
        cell(M[~fin_season], "非財報季", v5d)
        cell(M[M.near_bb], "庫藏股宣告後20日內", v5d)
        print("  (交乘: F11 × 事件)")
        cell(M[f11.fillna(False) & M.near_conf], "F11×法說會期", v5d)
        cell(M[f11.fillna(False) & pd.Series(fin_season, index=M.index)], "F11×財報季", v5d)
    except Exception as e:
        print(f"  [v5-D] 失敗({e})")

    print("\n【v5-E 剩餘贏家畫像】非F11的長紅拉回中,贏家vs輸家還有什麼差異?")
    v5e = []
    if len(rest) > 3000:
        R = rest.copy()
        R["rk2"] = R.groupby("d").fwd5.rank(pct=True)
        rw, rl = R[R.rk2 >= 0.9], R[R.rk2 <= 0.1]
        prof3 = []
        for fn in feat_names + ["tai5"]:
            if fn not in R.columns:
                continue
            a, b, c = rw[fn].median(), R[fn].median(), rl[fn].median()
            if pd.isna(a) or pd.isna(b):
                continue
            prof3.append({"f": fn, "win": a, "all": b, "lose": c, "gap": a - b, "wl_gap": a - c})
        prof3.sort(key=lambda x: -abs(x["wl_gap"]))
        print(f"  (n={len(R):,}; 贏家前10%均{rw.fwd5.mean():+.1f}% vs 輸家後10%{rl.fwd5.mean():+.1f}%; "
              f"按「贏家−輸家」差距排序)")
        for p in prof3[:10]:
            print(f"    {p['f']:<18} 贏家{p['win']:>8.2f} | 全{p['all']:>8.2f} | 輸家{p['lose']:>8.2f} "
                  f"| 贏−輸{p['wl_gap']:+.2f}")
        v5e = prof3[:10]

    print("\n【v5-F 依v5發現重組】長紅拉回 × {大盤環境/日曆/財報季/題材動能/波動} 最佳組合搜尋")
    v5f = []
    dom_M = pd.to_datetime(M.d).dt.day
    mth_M = pd.to_datetime(M.d).dt.month
    fin_M = mth_M.isin([3, 5, 8, 11]).values & (dom_M <= 20).values
    tm_pos = (M.theme_mom > 0).fillna(False)
    not_early = (dom_M > 5).values
    crash = (M.tai5 <= -3).fillna(False)
    lowvol = (M.vol20_ann < 60).fillna(False)
    combos = [
        ("G0 長紅拉回(母體)", pd.Series(True, index=M.index)),
        ("G1 ×大盤急殺後", crash),
        ("G2 ×題材動能正", tm_pos),
        ("G3 ×排除月初1-5日", pd.Series(not_early, index=M.index)),
        ("G4 ×財報季", pd.Series(fin_M, index=M.index)),
        ("G5 題材正×排除月初", tm_pos & pd.Series(not_early, index=M.index)),
        ("G6 題材正×排除月初×低波動", tm_pos & pd.Series(not_early, index=M.index) & lowvol),
        ("G7 題材正×大盤急殺", tm_pos & crash),
        ("G8 題材正×財報季", tm_pos & pd.Series(fin_M, index=M.index)),
        ("G9 題材正×排除月初×財報季", tm_pos & pd.Series(not_early & fin_M, index=M.index)),
        ("G10 營收連創×題材正×排除月初(F11+)", M.rev_ok.fillna(False) & tm_pos &
         pd.Series(not_early, index=M.index)),
        ("G11 題材正×排除月初×排除追漲期", tm_pos & pd.Series(not_early, index=M.index) &
         (M.tai5 <= 3).fillna(False)),
    ]
    for lab, mask in combos:
        cell(M[mask.fillna(False)], lab, v5f)

    print("\n【v2-③贏家畫像·限定基本面池】(營收連創×均額>=1億內,再比贏家vs輸家)")
    P = D[D.rev_ok & (D.money20 >= 1.0)].copy()
    if len(P) > 2000:
        P["rk"] = P.groupby("d").fwd5.rank(pct=True)
        pw, pl = P[P.rk >= 0.9], P[P.rk <= 0.1]
        prof2 = []
        for fn in feat_names:
            a, b, c = pw[fn].median(), P[fn].median(), pl[fn].median()
            if pd.isna(a) or pd.isna(b):
                continue
            prof2.append({"f": fn, "win": a, "all": b, "lose": c, "gap": a - b})
        prof2.sort(key=lambda x: -abs(x["gap"]))
        print(f"  (池內n={len(P):,}; 贏家前10%平均{pw.fwd5.mean():+.1f}% vs 輸家後10%{pl.fwd5.mean():+.1f}%)")
        for p in prof2[:12]:
            print(f"    {p['f']:<18} 贏家{p['win']:>8.2f} | 池{p['all']:>8.2f} | 輸家{p['lose']:>8.2f} "
                  f"| 贏−池{p['gap']:+.2f}")
    else:
        prof2 = []

    # ---- 階段一: 贏家畫像 ----
    D["rank"] = D.groupby("d").fwd5.rank(pct=True)
    win = D[D["rank"] >= 0.95]
    lose = D[D["rank"] <= 0.05]
    print(f"\n階段一 贏家畫像(同日fwd5前5%,n={len(win):,}; 平均報酬{win.fwd5.mean():+.1f}%) "
          f"vs 輸家(後5%,{lose.fwd5.mean():+.1f}%)")
    prof = []
    for fn in feat_names:
        w, l, a = win[fn].median(), lose[fn].median(), D[fn].median()
        if pd.isna(w) or pd.isna(a):
            continue
        prof.append({"f": fn, "win": w, "lose": l, "all": a, "gap": w - a})
    prof.sort(key=lambda x: -abs(x["gap"]))
    for p in prof:
        print(f"  {p['f']:<18} 贏家{p['win']:>8.2f} | 全池{p['all']:>8.2f} | 輸家{p['lose']:>8.2f} "
              f"| 贏-全池{p['gap']:+.2f}")

    # ---- 特徵五分位階梯(同日橫斷面) ----
    print("\n階段一b 特徵五分位 → fwd5均值/勝率/賺賠比(同日橫斷面分位)")
    ladders = {}
    for fn in feat_names:
        sub = D[["d", fn, "fwd5"]].dropna()
        if len(sub) < 5000:
            continue
        q = sub.groupby("d")[fn].transform(lambda x: pd.qcut(x.rank(method="first"), 5, labels=False)
                                           if x.notna().sum() >= 25 else np.nan)
        sub = sub.assign(q=q).dropna(subset=["q"])
        rows = []
        for qq, g in sub.groupby("q"):
            w, l = g.fwd5[g.fwd5 > 0], g.fwd5[g.fwd5 <= 0]
            rows.append({"q": int(qq) + 1, "mean": g.fwd5.mean(), "win": (g.fwd5 > 0).mean() * 100,
                         "wl": (w.mean() / abs(l.mean())) if len(w) and len(l) else np.nan, "n": len(g)})
        ladders[fn] = rows
        spread = rows[-1]["mean"] - rows[0]["mean"]
        print(f"  {fn:<18} Q1{rows[0]['mean']:+.2f} Q3{rows[2]['mean']:+.2f} Q5{rows[-1]['mean']:+.2f} "
              f"價差{spread:+.2f}pp | Q5勝率{rows[-1]['win']:.0f}%/賺賠{rows[-1]['wl']:.2f}")

    # ---- 階段二: 規則對決 ----
    print("\n階段二 拉回進場規則對決(次日收盤進,持5日;判準=賺賠比>=1.5且勝率>=50%且成本後>0)")
    D["hot"] = D.money20 >= 3.0
    rules = {
        "R1長紅後拉回5日線": (D.n_longbar20 >= 1) & (D.days_since_longbar.between(1, 5)) &
                        (D.ma5_dist.between(-3, 1)),
        "R2新高後淺回(<=3%)": (D.dist20 >= -3) & (D.dist20 < 0) & (D.ret20 > 0),
        "R3深回檔接刀(>=8%)": (D.dist20 <= -8) & (D.ret20 > 0),
        "R4純追高(對照)": (D.dist20 >= -0.5) & (D.ret5 > 0),
        "R5題材成員×淺回": (D.is_theme == 1) & (D.dist20 >= -3) & (D.dist20 < 0) & (D.theme_mom > 0),
        "R6熱門股×淺回": D.hot & (D.dist20 >= -3) & (D.dist20 < 0) & (D.ret20 > 0),
        "R7漲停後拉回": (D.n_limitup20 >= 1) & (D.days_since_longbar.between(1, 5)) & (D.ma5_dist < 2),
        "R8淺回×大戶增": (D.dist20 >= -3) & (D.dist20 < 0) & (D.d4w > 0),
        "R9淺回×營收連創": (D.dist20 >= -3) & (D.dist20 < 0) & (D.rev_r1 == 1),
        "(全池基準)": pd.Series(True, index=D.index),
    }
    res = []
    for lab, mask in rules.items():
        sub = D[mask.fillna(False)]
        if len(sub) < 200:
            print(f"  {lab:<22} n={len(sub)} 不足")
            continue
        w, l = sub.fwd5[sub.fwd5 > 0], sub.fwd5[sub.fwd5 <= 0]
        wl = (w.mean() / abs(l.mean())) if len(w) and len(l) else np.nan
        winr = (sub.fwd5 > 0).mean() * 100
        exp0 = sub.fwd5.mean()
        y = sub.groupby("yr").fwd5.mean()
        ok = (wl >= 1.5) and (winr >= 50) and (exp0 - 0.3 > 0)
        r = {"lab": lab, "n": len(sub), "per_yr": len(sub) / 11.5, "mean": exp0,
             "dm": sub.fwd5dm.mean(), "win": winr, "wl": wl,
             "c03": exp0 - 0.3, "c05": exp0 - 0.5,
             "yr": f"{int((y > 0).sum())}/{len(y)}", "pass": ok}
        res.append(r)
        print(f"  {'✅' if ok else '  '}{lab:<22} n={r['n']:>7,}({r['per_yr']:.0f}/年) "
              f"均{exp0:+.2f}%/demean{r['dm']:+.2f}% 勝率{winr:.0f}% 賺賠{wl:.2f} "
              f"扣0.3%{r['c03']:+.2f}% 扣0.5%{r['c05']:+.2f}% 逐年{r['yr']}")

    # ---- HTML ----
    CSS = """
body{background:#1a1a19;color:#fff;font-family:"Noto Sans TC",sans-serif;margin:24px;max-width:1150px}
h1{font-size:20px} h2{font-size:15px;color:#c3c2b7;margin-top:26px;border-bottom:1px solid #333;padding-bottom:4px}
table{border-collapse:collapse;font-size:12.5px;font-variant-numeric:tabular-nums;margin:8px 0}
td,th{border:1px solid #333;padding:4px 9px;text-align:right} th{text-align:left;color:#c3c2b7}
.note{color:#8a8878;font-size:12.5px;line-height:1.8} .good{color:#7ec97e} .bad{color:#e06c5a}
.hl{background:#2b3a2b} .scroll{overflow-x:auto}
ul{margin:4px 0;padding-left:20px;font-size:12.5px;color:#ccc;line-height:1.7}
"""
    prof_html = ("<table><tr><th>特徵</th><th>贏家中位</th><th>全池中位</th><th>輸家中位</th><th>贏−全池</th></tr>"
                 + "".join(f"<tr><th>{p['f']}</th><td>{p['win']:.2f}</td><td>{p['all']:.2f}</td>"
                           f"<td>{p['lose']:.2f}</td><td class='{'good' if p['gap'] > 0 else 'bad'}'>"
                           f"{p['gap']:+.2f}</td></tr>" for p in prof) + "</table>")
    lad_html = ""
    for fn, rows in ladders.items():
        cells = "".join(f"<td>{r['mean']:+.2f}<br><span style='color:#777;font-size:10.5px'>"
                        f"{r['win']:.0f}%/{r['wl']:.2f}</span></td>" for r in rows)
        lad_html += f"<tr><th>{fn}</th>{cells}<td>{rows[-1]['mean'] - rows[0]['mean']:+.2f}</td></tr>"
    lad_html = ("<div class='scroll'><table><tr><th>特徵</th><th>Q1(最低)</th><th>Q2</th><th>Q3</th>"
                "<th>Q4</th><th>Q5(最高)</th><th>Q5−Q1</th></tr>" + lad_html + "</table></div>"
                "<div class='note'>格內第二行=勝率/賺賠比。</div>")
    rule_html = ("<div class='scroll'><table><tr><th>規則</th><th>n(次/年)</th><th>fwd5均值</th>"
                 "<th>demean</th><th>勝率</th><th>賺賠比</th><th>扣0.3%</th><th>扣0.5%</th>"
                 "<th>逐年</th><th>達標</th></tr>"
                 + "".join(f"<tr{' class=hl' if r['pass'] else ''}><th>{r['lab']}</th>"
                           f"<td>{r['n']:,}({r['per_yr']:.0f})</td><td>{r['mean']:+.2f}%</td>"
                           f"<td>{r['dm']:+.2f}%</td><td>{r['win']:.0f}%</td>"
                           f"<td class='{'good' if r['wl'] >= 1.5 else ''}'>{r['wl']:.2f}</td>"
                           f"<td>{r['c03']:+.2f}%</td><td>{r['c05']:+.2f}%</td><td>{r['yr']}</td>"
                           f"<td>{'✅' if r['pass'] else '—'}</td></tr>" for r in res) + "</table></div>")

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>一週大賺股逆向工程(2026-08-08)</title><style>{CSS}</style></head><body>
<h1>🎯 一週大賺股逆向工程 + 拉回進場規則對決</h1>
<div class="note">使用者目標: <b>持有一週(5交易日)、勝率高、賺賠比>=1.5</b>。方法=先定義結果(同日fwd5前5%)
再回頭挖特徵,不預設型態。口徑: 次日收盤進場→第5個交易日收盤出場(可執行,零前視);
池=20日均額>=0.3億;每5交易日抽樣(fwd5窗不重疊);2015起,樣本{len(D):,}筆。
判準(預先註冊)=<b>賺賠比>=1.5 且 勝率>=50% 且 扣0.3%成本後期望值>0</b>。</div>
<h2>階段一 贏家畫像(前5% vs 全池 vs 後5%)</h2>
{prof_html}
<h2>階段一b 特徵五分位階梯(同日橫斷面)</h2>
{lad_html}
<h2>階段二 拉回進場規則對決</h2>
{rule_html}
<h2>⚖️ 判決(2026-08-08首輪)</h2>
<ul>
<li><span style="background:#3b2420;color:#e06c5a;padding:6px 10px;border-radius:4px;font-weight:bold">
①最重要的發現: <b>一週尺度的大賺股與大賠股,事前長得幾乎一模一樣</b></span>
贏家(前5%,平均+13.8%)vs 輸家(後5%)的事前特徵中位數: ret20 <b>5.67 vs 7.16(輸家更高)</b>、
ma20_dist 2.37 vs <b>2.92(輸家更高)</b>、amp20 4.21 vs 4.46、vol_ratio 0.81 vs 0.88——
<b>兩端都是高動能、高波動、貼近均線上方的同一批股票</b>,只是硬幣的兩面。
這是「頂部無指紋定理」的短線版: <b>一週尺度沒有指紋</b>,你能篩出「會大幅波動的股票」,
但篩不出「往哪邊波動」。</li>
<li><span style="background:#3b3420;color:#c3a55a;padding:6px 10px;border-radius:4px;font-weight:bold">
②所有特徵的五分位階梯都極平: 最大價差僅0.53pp</span>
最強的是題材動能(theme_mom Q5−Q1=+0.53pp/Q5賺賠1.36)與題材成員(+0.50pp),
其餘位置/動能/量能/波動/籌碼/營收全在±0.4pp內;<b>Q5賺賠比天花板1.13~1.36,沒有任何單一特徵能推到1.5</b>。
使用者提到的「熱門成交值大」在資料上幾乎無效(money20 Q5−Q1僅+0.17pp)。
一個有用的細節: days_since_longbar <b>Q1(剛長紅)+0.43 vs Q5(很久沒長紅)+0.17</b>=
「事件剛發生」比「安靜很久」好——與壓縮爆發卷結論一致。</li>
<li><span style="background:#3b3420;color:#c3a55a;padding:6px 10px;border-radius:4px;font-weight:bold">
③規則對決: 拉回確實勝過追高,但<b>全部沒達標</b>(賺賠比>=1.5×勝率>=50%×成本後>0)</span>
最好三條: <b>R7漲停後拉回(+0.90%/勝率48%/賺賠1.42/扣0.5%後+0.40%)</b>、
R1長紅後拉回5日線(+0.82%/49%/1.40/+0.32%)、R5題材成員×淺回(+0.52%/<b>勝率50%</b>/1.35/+0.02%);
對照組: 純追高R4僅+0.42%、全池基準+0.27%(扣0.3%成本即為負)——
<b>「等拉回」是對的(R7/R1 是基準的3倍),但賺賠比天花板在1.4</b>,離1.5差一步、勝率也上不了50%。
深回檔接刀(R3)與大戶增(R8)無效。</li>
<li><span style="background:#243b24;color:#7ec97e;padding:6px 10px;border-radius:4px;font-weight:bold">
④v2翻盤(使用者兩項修正): 換成「基本面出發+胃納量門檻」後<b>達標了</b></span>
使用者指正: (a)母體要剔除小成交值(胃納量) (b)出發點改成先篩月營收好再看型態。結果:
<b>F11 = 營收兩月連創高 × 20日均額≥1億 × 長紅後拉回5日線 × 題材動能正</b>:
<b>均+1.86% / demean+1.59% / 勝率52% / 賺賠比1.56 / 扣0.5%成本後+1.36% / 逐年8/9</b>(n=418,~36次/年)
——<b>三項判準全過(賺賠≥1.5✓、勝率≥50%✓、成本後>0✓)</b>,是全卷唯一達標的組合;
F13(同上但用低波動取代題材動能)賺賠1.52/勝率50%也達標;F14(漲停版)+1.49%/1.47接近。
對照: 純型態版天花板1.42、全池基準1.22——<b>基本面當出發點是關鍵那一步</b>。</li>
<li><b>⑤胃納量門檻幾乎零成本</b>: 同一組規則把池子從0.3億拉到5億(R7: +0.90%→+0.96%、
R1: +0.82%→+0.96%、R5: +0.52%→+0.67%),<b>報酬不降反升、勝率+1pp、賺賠比僅微降0.05</b>
——<b>剔除小成交值股不會傷害策略</b>,實務可執行性直接提升(使用者的胃納量顧慮解除)。</li>
<li><b>⑥贏家畫像在基本面池內出現兩個新線索</b>(全池版被雜訊蓋住):
①<b>題材動能是唯一「贏家>輸家」的特徵</b>(3.97 vs 2.75,池2.36)→ 成為F11的關鍵條件;
②<b>波動度反而「贏家<輸家」</b>(55.5 vs 60.2)=過熱股是輸家而非贏家→ F13用低波動也能達標。
③days_since_longbar 贏家7 vs 池10=「剛長紅」仍是共同前提。</li>
<li><span style="background:#243b24;color:#7ec97e;padding:6px 10px;border-radius:4px;font-weight:bold">
⑦v3(使用者問「換成佔大盤成交量%、分上市櫃會不會更好」): <b>八種流動性定義全部達標,差異在雜訊內</b></span>
L0無門檻+1.83/1.52、L1絕對1億+1.86/<b>1.56</b>、L2絕對3億+1.64/<b>1.58</b>(賺賠最高)、
L3~L5佔市場3/5/10bp +1.74~1.82/1.51~1.55、L6~L7市場內分位70%/85% +1.73~1.77/1.52——
<b>因為「營收連創×題材動能正×長紅拉回」本身已經濾掉小股,流動性門檻幾乎沒事可做</b>。
實務建議: <b>改用相對定義(市場內分位>=70% 或 佔市場>=5bp)當live規則</b>——數字一樣好,
但<b>跨時代穩定</b>(大盤量能成長時不用改參數,絕對門檻會慢慢失效)。
<b>分市場: 上市(n=288)+1.88%/賺賠1.57 vs 上櫃(n=130)+1.81%/1.53,兩市都達標且差異極小</b>——
這與「上櫃極端族群是陷阱」的舊教訓不衝突: <b>基本面門檻把爛的濾掉後,上櫃也變得可用</b>。</li>
<li><span style="background:#243b24;color:#7ec97e;padding:6px 10px;border-radius:4px;font-weight:bold">
⑧v4(使用者問「基本面爛的呢?全方位分組找寶藏」): <b>基本面是連續梯度,而且沒有反向寶藏</b></span>
長紅後拉回在各基本面等級的表現: <b>好(兩月連創)+1.38%/賺賠1.46 &gt; 中(YoY≥0未連創)+1.10%/1.41
&gt; 爛(YoY&lt;0)+0.66%/1.37 &gt; 很爛(YoY&lt;-20%)+0.60%/1.37 &gt;&gt; 無營收資料+0.07%/1.22</b>——
單調遞減,<b>基本面不是二元開關而是放大器</b>;<b>「無營收資料」比「營收很爛」還糟(第五次重現的鐵律)</b>。
<b>沒有找到反向寶藏</b>: 基本面爛的組沒有任何格出現超額反轉(最差格=很爛×淺回僅+0.12%/勝率48%,
深回檔在很爛組+0.52%但賺賠僅1.24=超跌反彈但不夠肥)。
<b>另一個發現: 型態的普適性大於基本面</b>——長紅後拉回在<b>每一個</b>基本面等級都是該等級最好的型態,
而淺回在基本面差的組直接崩掉(+0.17%/+0.12%)=<b>淺回需要基本面撐,長紅拉回自己就能站</b>。</li>
<li><span style="background:#3b2420;color:#e06c5a;padding:6px 10px;border-radius:4px;font-weight:bold">
⑨v5(使用者問「F11抓到幾成?其餘贏家的特徵?」): <b>F11只抓到4%的贏家,96%被漏掉</b></span>
長紅拉回母體(均額≥1億)n=14,280,F11只命中418筆(2.9%精選度);母體贏家(同日fwd5前10%)1,735筆中
F11只佔69筆=<b>召回率僅4.0%</b>。被漏掉的13,862筆均+0.75%/勝率49%/賺賠1.35(仍優於全池基準+0.27%)
——<b>F11是「高精選、低召回」的過濾器,不是唯一入口</b>。</li>
<li><span style="background:#243b24;color:#7ec97e;padding:6px 10px;border-radius:4px;font-weight:bold">
⑩其餘贏家躲在三個地方(全部是使用者猜的方向)</span>
<b>(a)大盤環境是最大變數</b>: 長紅拉回×大盤近5日≤-3%(急殺後)<b>+2.39%/勝率59%/賺賠1.47</b>
vs 大盤近5日>3%(追漲期)<b>-0.08%/勝率44%(負)</b>——同一個型態在兩種環境差2.5pp;
<b>(b)日曆: 月初1-5日是死亡區</b>(-0.37%/勝率42%/扣成本-0.87%),月中13-20日最好(+1.33%/勝率53%),
營收公布期6-12日+1.18%;<b>(c)財報季(3/5/8/11月上中旬)+1.49%/勝率55% vs 非財報季+0.56%/47%</b>;
法說會前後(前10~後3日)+1.56%/1.49也優於非法說期。
剩餘贏家畫像(非F11池): <b>題材動能仍是最強區分</b>(贏家3.94 vs 輸家1.59)、
波動<b>贏家更低</b>(62.0 vs 67.5)、<b>漲太多反而是輸家</b>(ret20 10.4 vs 11.8)、下影線贏家較長。</li>
<li><span style="background:#243b24;color:#7ec97e;padding:6px 10px;border-radius:4px;font-weight:bold">
⑪重組後的最終配方(v5-F): 不需要營收連創,而且更好</span>
<b>★G5 = 長紅後拉回5日線 × 題材動能正 × 排除月初1-5日</b>:
<b>n=3,336(290次/年)/均+1.61%/勝率52%/賺賠1.59/扣0.5%後+1.11%</b>
——樣本是F11的<b>8倍</b>而賺賠更高(1.59 vs 1.56)=<b>「營收連創」大幅砍樣本卻沒加值,可以拿掉</b>;
<b>★★G7 = 上式×大盤近5日急殺≤-3%: n=157(14次/年)/均+5.07%/勝率66%/賺賠2.13/扣0.5%後+4.57%</b>
=全卷最強格,<b>遠超使用者目標</b>但機會稀少(⚠n=157,樣本小,候選層);
其他達標: G10(G5+營收連創)1.63、G9(G5×財報季)+2.13%/勝率56%/1.54、G11(G5×排除追漲期)1.59、
G8(題材正×財報季)+1.80%/1.57、G6(G5×低波動)1.50。</li>
<li><b>⑫實務配方(候選層)</b>: <b>主線=G5</b>(長紅後拉回×題材動能正×避開月初1-5日,290次/年可持續操作);
<b>大盤急殺後(近5日≤-3%)出現的訊號重押</b>(G7勝率66%/賺賠2.13);
<b>避開: 月初1-5日、大盤追漲期(近5日>3%)</b>;財報季/法說會期是加分項。</li>
<li><b>⑬下一步(仍然是出場端)</b>: G5/G7的賺賠已達標但靠的是進場品質;
出場仍是固定5日的鈍刀。下一張卷用F11當母體掃出場矩陣(目標價停利/移動停損/首日不利即出),
<b>賺賠比有機會再往上一階</b>。另F11每年僅~36次=需與其他線並行才夠分散。</li>
</ul>
<div class="note">維運: python 研究腳本/綜合策略/build_week_winner_anatomy.py(從根目錄執行)。</div>
</body></html>"""
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n[report] 已輸出 {OUT}")


if __name__ == "__main__":
    main()
