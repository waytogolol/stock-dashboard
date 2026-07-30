# -*- coding: utf-8 -*-
"""P5縮量×融資殺出深度交叉考卷(2026-07-31凌晨,使用者:「打底型完勝引爆型」跟融資殺到底研究能結合嗎?
還是倉位調整建議?)。

假說框架: 兩者量同一件事(賣壓出清)的不同維度——
  融資殺出深度(bal_dd240=餘額距240日高縮水%)=慢變數,籌碼清理程度,管「反彈的地基」
  P5縮量止跌=快變數,量能投降結束,管「進場的時機」
  → 自然結合=深度定倉位,P5定扳機。本卷驗證: P5事件×深度分帶的k20/k60是否有梯度。
深度帶(E5b口徑簡化,樣本少故三帶): 淺(>-10%)/死亡谷帶(-10~-25%)/乾淨帶(<=-25%)
  (E5b原判: 乾淨<=-30% f60+5.90%/71%,死亡谷-10~-20最毒,殺夠深才乾淨)
對照: 急殺基準全體×同深度帶(檢驗梯度是否獨立於P5存在=結合是否有加成)。
資料: margin_total(上市2001起)×TAIEX / margin_total_otc(2011起)×TPEx。
"""
import sqlite3
import numpy as np
import pandas as pd

from build_volume_dryup_deep import load_index, base_features, dryup_mask, dedup, stats

DB = "capital_flow.db"
BANDS = [("淺(>-10%)", -10, 999), ("死亡谷帶(-10~-25%)", -25, -10), ("乾淨帶(<=-25%)", -999, -25)]


def margin_depth(table):
    con = sqlite3.connect(DB)
    if table == "margin_total":
        sql = "SELECT date, today_balance AS bal FROM margin_total WHERE name='MarginPurchaseMoney' ORDER BY date"
    else:
        sql = "SELECT date, money_today AS bal FROM margin_total_otc ORDER BY date"
    m = pd.read_sql(sql, con)
    con.close()
    m["date"] = pd.to_datetime(m["date"])
    m = m.set_index("date")["bal"].astype(float)
    return (m / m.rolling(240, min_periods=200).max() - 1) * 100


def band_of(v):
    for lab, lo, hi in BANDS:
        if lo < v <= hi:
            return lab
    return None


def report(ev, depth, title):
    ev = ev.copy()
    ev["depth"] = [depth.asof(d) for d in ev["date"]]
    ev = ev.dropna(subset=["depth"])
    ev["band"] = ev["depth"].map(band_of)
    print(f"\n  {title} (n={len(ev)})")
    for lab, _, _ in BANDS:
        r = ev[ev["band"] == lab]
        if len(r) == 0:
            print(f"    {lab:20s} n=0"); continue
        star = " ⚠樣本薄" if len(r) < 8 else ""
        print(f"    {lab:20s} n={len(r):3d}  k20中位{r['k20'].median()*100:+.2f}% 勝{(r['k20']>0).mean()*100:.0f}%  "
              f"k60中位{r['k60'].median()*100:+.2f}% 勝{(r['k60']>0).mean()*100:.0f}%  "
              f"MAE20中位{r['mae20'].median()*100:.2f}%{star}")


def main():
    for market, name, mtab in [("TAIEX", "加權×上市融資", "margin_total"),
                               ("TPEx", "櫃買×上櫃融資", "margin_total_otc")]:
        df = load_index(market)
        f = base_features(df)
        depth = margin_depth(mtab)
        print(f"\n{'='*100}\n=== {name} (融資深度資料 {depth.dropna().index.min().date()}起) ===")
        base_ev = stats(df, dedup(list(f.index[f['pre_panic']])))
        p5_ev = stats(df, dedup(list(f.index[(dryup_mask(df, 10, 0.5, 5, 1) & f['pre_panic'])])))
        report(base_ev, depth, "[基準]急殺全體×深度帶")
        report(p5_ev, depth, "P5縮量止跌×深度帶")
        cur = depth.dropna()
        print(f"  當下深度讀數: {cur.iloc[-1]:+.1f}% ({cur.index[-1].date()})")


if __name__ == "__main__":
    main()
