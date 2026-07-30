# -*- coding: utf-8 -*-
"""反彈領導權考卷(2026-07-30,使用者核心提問:「上半年多頭排列的權值題材好股回檔到年線,
止穩反彈時是它們彈比較多,還是共振/營收等新訊號的新面孔漲更多?找歷史類似時期」)。

episode定義(零前視):
  修正=指數距120日高回檔<=-10%;t0止穩日=修正中首個「低點>前5日最低」日(P6家族口徑);
  t0後120交易日內不重複開episode。加權/櫃買各自跑(本波=OTC型修正,兩邊都要)。
五組cohort(全部只用t0當天可知資訊;流動性門檻tv20>=0.5億):
  A舊將回檔組: 前120日多頭排列(月>季>年線)占比>=50% 且 現價距年線±7%內
  D抗跌舊將組: 多頭排列占比>=50% 且 自身回檔深度在舊將群最淺1/3(率先走出修正者)
  B新兵組:     多頭排列占比<=30%(修正前非主流) 且 現價仍貼近60日高(>=95%,修正中逆勢強)
  C對照組:     其餘全部
  E贏家解剖:   事後k60前10%,回頭看t0特徵(bull占比/回檔深度/相對指數/流動性排名),
               跨episode重複出現才算候選特徵(防多重比較)
觀測: k20/k60中位+勝率,逐episode表+彙總;流動性排名前150=權值proxy(tv20排名,全年代可用)。
"""
import sqlite3
import numpy as np
import pandas as pd

DB = "capital_flow.db"


def load_pivots():
    con = sqlite3.connect(DB)
    px = pd.read_sql("SELECT code, date, close, money FROM fm_daily_price", con)
    con.close()
    px["date"] = pd.to_datetime(px["date"])
    close = px.pivot_table(index="date", columns="code", values="close", aggfunc="last")
    money = px.pivot_table(index="date", columns="code", values="money", aggfunc="last")
    close = close.where(close > 0)
    return close, money


def find_episodes(market):
    con = sqlite3.connect(DB)
    idx = pd.read_sql("SELECT date, low, close FROM index_daily WHERE market=? ORDER BY date",
                      con, params=(market,))
    con.close()
    idx["date"] = pd.to_datetime(idx["date"])
    idx = idx.set_index("date")
    c, l = idx["close"], idx["low"]
    dd = c / c.rolling(120).max() - 1
    in_corr = dd <= -0.10
    stab = l > l.shift(1).rolling(5).min()
    sig = in_corr.shift(1).rolling(5, min_periods=1).max().astype(bool) & stab
    t0s, last = [], None
    for d in idx.index[sig.fillna(False)]:
        if last is None or (d - last).days > 170:   # ≈120交易日
            t0s.append(d); last = d
    return t0s, dd


def main():
    close, money = load_pivots()
    ma20, ma60, ma240 = (close.rolling(k).mean() for k in (20, 60, 240))
    bull = (ma20 > ma60) & (ma60 > ma240)
    bull_frac = bull.rolling(120).mean()
    dd120 = close / close.rolling(120).max() - 1
    hi60 = close / close.rolling(60).max()
    tv20 = money.rolling(20).mean() / 1e8
    near_yl = (close / ma240 - 1).abs() <= 0.07

    for market, mname in [("TAIEX", "加權"), ("TPEx", "櫃買")]:
        t0s, idx_dd = find_episodes(market)
        print(f"\n{'='*112}\n=== {mname}修正episodes: {len(t0s)}個 ===")
        pooled = {g: [] for g in "ABCD"}
        e_profiles = []
        for t0 in t0s:
            if t0 not in close.index:
                continue
            i = close.index.get_loc(t0)
            if i + 60 >= len(close.index) or i < 250:
                print(f"  {t0.date()} (前後樣本不足,跳過)")
                continue
            snap = pd.DataFrame({
                "bf": bull_frac.iloc[i], "dd": dd120.iloc[i], "hi60": hi60.iloc[i],
                "tv": tv20.iloc[i], "nyl": near_yl.iloc[i],
                "k20": close.iloc[i + 20] / close.iloc[i] - 1,
                "k60": close.iloc[i + 60] / close.iloc[i] - 1,
            }).dropna(subset=["bf", "dd", "tv", "k60"])
            u = snap[snap["tv"] >= 0.5].copy()
            if len(u) < 100:
                continue
            oldg = u["bf"] >= 0.5
            shallow_cut = u.loc[oldg, "dd"].quantile(2 / 3) if oldg.sum() >= 9 else np.nan
            u["grp"] = "C"
            u.loc[oldg & u["nyl"], "grp"] = "A"
            if not np.isnan(shallow_cut):
                u.loc[oldg & (u["dd"] >= shallow_cut), "grp"] = "D"   # D優先於A(抗跌者常不在年線邊)
            u.loc[(u["bf"] <= 0.3) & (u["hi60"] >= 0.95), "grp"] = "B"
            idd = float(idx_dd.get(t0, np.nan))
            parts = []
            for g in "ABDC":
                r = u.loc[u["grp"] == g, "k60"]
                parts.append(f"{g}:n={len(r)} 中位{r.median()*100:+.1f}%" if len(r) >= 5 else f"{g}:n={len(r)} —")
                if len(r) >= 5:
                    pooled[g].append(r)
            print(f"  {t0.date()} 指數dd{idd*100:.0f}%  " + "  ".join(parts))
            # E贏家解剖
            win = u[u["k60"] >= u["k60"].quantile(0.9)]
            e_profiles.append({
                "ep": t0, "w_bf": win["bf"].median() - u["bf"].median(),
                "w_dd": win["dd"].median() - u["dd"].median(),
                "w_hi60": win["hi60"].median() - u["hi60"].median(),
                "w_tvrank": win["tv"].rank(pct=True).median(),
                "w_big150": (win["tv"].rank(ascending=False) <= 150).mean() if len(win) else np.nan,
                "w_inB": (win["grp"] == "B").mean(), "w_inA": (win["grp"] == "A").mean(),
                "w_inD": (win["grp"] == "D").mean(),
                "base_B": (u["grp"] == "B").mean(), "base_A": (u["grp"] == "A").mean(),
                "base_D": (u["grp"] == "D").mean(),
            })
        print(f"\n  --- {mname} 彙總(逐episode中位的中位,episode數) ---")
        for g, desc in [("A", "舊將回檔到年線"), ("D", "抗跌舊將(最淺1/3)"), ("B", "新兵(非主流仍貼60日高)"), ("C", "其餘")]:
            if pooled[g]:
                meds = [r.median() for r in pooled[g]]
                allr = pd.concat(pooled[g])
                print(f"  {g}{desc:16s}: ep數={len(meds):2d}  ep中位k60={np.median(meds)*100:+.2f}%  "
                      f"全事件中位={allr.median()*100:+.2f}% 勝率{(allr>0).mean()*100:.0f}% n={len(allr)}")
        ep_df = pd.DataFrame(e_profiles)
        if len(ep_df):
            print(f"\n  --- {mname} E組贏家解剖(k60前10% vs 全池, 跨{len(ep_df)}個episode) ---")
            print(f"  贏家多頭排列占比差(中位): {ep_df['w_bf'].median():+.3f}  正的episode: {(ep_df['w_bf']>0).mean()*100:.0f}%")
            print(f"  贏家回檔深度差:           {ep_df['w_dd'].median():+.3f}  贏家跌更深的ep: {(ep_df['w_dd']<0).mean()*100:.0f}%")
            print(f"  贏家貼近60日高差:         {ep_df['w_hi60'].median():+.3f}  正的episode: {(ep_df['w_hi60']>0).mean()*100:.0f}%")
            print(f"  贏家流動性分位(中位):      {ep_df['w_tvrank'].median():.2f}  (0.5=中等,越大越大型)")
            print(f"  贏家落在前150大占比:       {ep_df['w_big150'].median()*100:.0f}%")
            print(f"  贏家中B組占比 vs 池底率:   {ep_df['w_inB'].median()*100:.0f}% vs {ep_df['base_B'].median()*100:.0f}%")
            print(f"  贏家中A組占比 vs 池底率:   {ep_df['w_inA'].median()*100:.0f}% vs {ep_df['base_A'].median()*100:.0f}%")
            print(f"  贏家中D組占比 vs 池底率:   {ep_df['w_inD'].median()*100:.0f}% vs {ep_df['base_D'].median()*100:.0f}%")
    print("\n完成。")


if __name__ == "__main__":
    main()
