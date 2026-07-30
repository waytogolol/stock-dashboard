# -*- coding: utf-8 -*-
"""處置V4滾動勝率×大盤regime考卷(預註冊2026-07-28,使用者假說)
========================================================================
假說(使用者原話轉譯): 「處置股某短時期勝率開始下降,是否=大盤行情不好回檔中?」
觸發觀察: 最近的V4單子勝率偏低,且集中在成交值大的處置股。
預註冊四題(跑之前寫死):
  Q0 live掃描: 近6個月逐筆V4+逐月勝率+大小成交值分半對比(驗證使用者觀察是否屬實)
  Q1 同時性: 滾動近20筆勝率(以出場日蓋章,零前視) vs TAIEX同期20日報酬/距250日高 Spearman
  Q2 領先性: 勝率低日(<50%)vs高日(>=70%) → TAIEX fwd k5/10/20;另看勝率五分位單調性
  Q3 增量: 只取「站上季線」的日子,勝率低vs高還分得出fwd差嗎?(分不出=與季線開關冗餘,
     戰情板照舊看季線;分得出=候選新資訊)——house judgement: 絕對判上板/增量判真偽
  Q4 大成交值子組: 進場日成交值 前1/3 vs 後1/3 勝率,按regime(站上/跌破季線)×年度分層
口徑: V4=第3處置日收盤買→出關次日開盤賣,淨成本0.45%;disposition全事件(價格可對齊者);
  滾動勝率當日值=截至當日「已出場」的最近20筆(outcome僅在出場後可知,零前視);
  n小不bootstrap,LOTO逐年;先驗=多半是同時指標(冷regime處置池停滯),領先性成立才有新東西。
用法: python build_dispo_winrate_regime.py
"""
import sqlite3
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
DB = "capital_flow.db"
COST = 0.45


def main():
    conn = sqlite3.connect(DB)
    disp = pd.read_sql("SELECT * FROM disposition", conn)
    px = pd.read_sql("SELECT code, date, open, close, money FROM fm_daily_price "
                     "WHERE close>0 ORDER BY code, date", conn)
    tw = pd.read_sql("SELECT date, close FROM index_daily WHERE market='TAIEX' ORDER BY date",
                     conn, parse_dates=["date"]).set_index("date").close
    conn.close()
    for c in ("start_date", "end_date"):
        disp[c] = pd.to_datetime(disp[c], errors="coerce")
    disp = disp.dropna(subset=["start_date", "end_date"])
    px["date"] = pd.to_datetime(px.date)
    stocks = {c: g.sort_values("date").reset_index(drop=True) for c, g in px.groupby("code")}

    # ---- 重建V4交易(與檢視器同口徑) ----
    trades = []
    for _, e in disp.iterrows():
        g = stocks.get(e.code)
        if g is None:
            continue
        dts = g.date.values
        n = len(g)
        s = int(np.searchsorted(dts, np.datetime64(e.start_date)))
        en = int(np.searchsorted(dts, np.datetime64(e.end_date), side="right") - 1)
        if s >= n or en <= s or en - s > 25 or en - s < 6 or en + 1 >= n:
            continue
        entry_i = s + 2
        if entry_i >= n:
            continue
        pin, pout = g.close.iloc[entry_i], g.open.iloc[en + 1]
        if pin <= 0 or pout <= 0:
            continue
        trades.append({"code": e.code, "entry_d": g.date.iloc[entry_i],
                       "exit_d": g.date.iloc[en + 1],
                       "ret": (pout / pin - 1) * 100 - COST,
                       "amt_entry": float(g.money.iloc[entry_i] or 0) / 1e8})
    tr = pd.DataFrame(trades).sort_values("exit_d").reset_index(drop=True)
    tr["win"] = tr.ret > 0
    print(f"V4交易重建: {len(tr)}筆 {tr.entry_d.min().date()}~{tr.entry_d.max().date()} "
          f"全史淨中位{tr.ret.median():+.2f}%/勝率{tr.win.mean() * 100:.0f}%")

    # ---- Q0 live掃描: 近6個月 ----
    print("\n═══ Q0 live掃描(使用者觀察驗證) ═══")
    cut = tr.entry_d.max() - pd.Timedelta(days=183)
    rec = tr[tr.entry_d >= cut]
    print("逐月(依進場月):")
    for m, g in rec.groupby(rec.entry_d.dt.strftime("%Y-%m")):
        done = g[g.exit_d <= tr.exit_d.max()]
        print(f"  {m}: n={len(g)} 淨中位{g.ret.median():+.2f}% 勝率{g.win.mean() * 100:.0f}%")
    med_amt = tr.amt_entry.median()
    for lab, sub in (("近6月×大成交值(>全史中位)", rec[rec.amt_entry > med_amt]),
                     ("近6月×小成交值", rec[rec.amt_entry <= med_amt]),
                     ("全史×大成交值", tr[tr.amt_entry > med_amt]),
                     ("全史×小成交值", tr[tr.amt_entry <= med_amt])):
        if len(sub):
            print(f"  {lab}: n={len(sub)} 淨中位{sub.ret.median():+.2f}% 勝率{sub.win.mean() * 100:.0f}%")

    # ---- 滾動勝率日序列(出場日蓋章,零前視) ----
    cal = tw.index[(tw.index >= tr.exit_d.min()) & (tw.index <= tw.index.max())]
    exits = tr.set_index("exit_d")
    wr = {}
    for d in cal:
        done = tr[tr.exit_d <= d].tail(20)
        if len(done) == 20:
            wr[d] = done.win.mean() * 100
    wr = pd.Series(wr)
    print(f"\n滾動勝率序列: {len(wr)}日 {wr.index.min().date()}~{wr.index.max().date()} "
          f"現值{wr.iloc[-1]:.0f}%(全史中位{wr.median():.0f}%)")

    # ---- Q1 同時性 ----
    print("\n═══ Q1 同時性 ═══")
    tw_r20 = (tw / tw.shift(20) - 1) * 100
    tw_dd = (tw / tw.rolling(250).max() - 1) * 100
    a = pd.concat([wr.rename("wr"), tw_r20.rename("r20"), tw_dd.rename("dd")], axis=1).dropna()
    print(f"  Spearman(勝率, 大盤近20日報酬)={a.wr.corr(a.r20, method='spearman'):+.3f}")
    print(f"  Spearman(勝率, 距250日高)={a.wr.corr(a.dd, method='spearman'):+.3f}")

    # ---- Q2 領先性 ----
    print("\n═══ Q2 領先性: 勝率日→TAIEX前瞻 ═══")
    ma60 = tw.rolling(60).mean()

    def fwdk(d, k):
        i = tw.index.get_loc(d)
        if i + k >= len(tw):
            return None
        return (tw.iloc[i + k] / tw.iloc[i] - 1) * 100

    def cell(days, lab):
        if len(days) < 20:
            print(f"  {lab}: n={len(days)}太少略過")
            return
        outs = []
        for k in (5, 10, 20):
            v = pd.Series([x for d in days if (x := fwdk(d, k)) is not None])
            outs.append(f"k{k} {v.median():+.2f}%/{(v > 0).mean() * 100:.0f}%")
        print(f"  {lab}: n={len(days)} " + " | ".join(outs))

    low_d = wr[wr < 50].index
    high_d = wr[wr >= 70].index
    cell(list(wr.index), "全部日(基準)")
    cell(list(low_d), "勝率<50%日")
    cell(list(high_d), "勝率>=70%日")
    print("  五分位(勝率→fwd k20中位):")
    qs = pd.qcut(wr, 5, duplicates="drop")
    for q, g in wr.groupby(qs, observed=True):
        v = pd.Series([x for d in g.index if (x := fwdk(d, 20)) is not None])
        if len(v):
            print(f"    {q}: n={len(v)} {v.median():+.2f}%/{(v > 0).mean() * 100:.0f}%")
    # LOTO逐年(低vs全部差)
    diffs = []
    for y in sorted(set(wr.index.year)):
        ld = [d for d in low_d if d.year == y]
        ad = [d for d in wr.index if d.year == y]
        lv = pd.Series([x for d in ld if (x := fwdk(d, 20)) is not None])
        av = pd.Series([x for d in ad if (x := fwdk(d, 20)) is not None])
        if len(lv) >= 10 and len(av) >= 30:
            diffs.append((y, lv.median() - av.median(), len(lv)))
    print("  逐年(勝率<50%日k20中位 − 全部日): " +
          ", ".join(f"{y}:{d:+.2f}(n={n})" for y, d, n in diffs))

    # ---- Q3 增量(控制季線) ----
    print("\n═══ Q3 增量: 只看「站上季線」的日子 ═══")
    above = wr.index[tw.reindex(wr.index) > ma60.reindex(wr.index)]
    below = wr.index[tw.reindex(wr.index) <= ma60.reindex(wr.index)]
    cell([d for d in above], "站上季線全部日")
    cell([d for d in above if d in set(low_d)], "站上季線∧勝率<50%")
    cell([d for d in above if d in set(high_d)], "站上季線∧勝率>=70%")
    cell([d for d in below], "跌破季線全部日")
    cell([d for d in below if d in set(low_d)], "跌破季線∧勝率<50%")

    # ---- Q4 大成交值×regime ----
    print("\n═══ Q4 大成交值子組(進場日成交值三分位) ═══")
    tr["amt_ter"] = pd.qcut(tr.amt_entry, 3, labels=["小", "中", "大"])
    tr["above60"] = [tw.reindex([d], method="ffill").iloc[0] >
                     ma60.reindex([d], method="ffill").iloc[0] for d in tr.entry_d]
    for reg, gr in tr.groupby("above60"):
        lab = "站上季線" if reg else "跌破季線"
        row = []
        for t_, gg in gr.groupby("amt_ter", observed=True):
            row.append(f"{t_}:{gg.ret.median():+.2f}%/{gg.win.mean() * 100:.0f}%(n={len(gg)})")
        print(f"  {lab}: " + " | ".join(row))
    y26 = tr[tr.entry_d.dt.year == 2026]
    row = []
    for t_, gg in y26.groupby("amt_ter", observed=True):
        row.append(f"{t_}:{gg.ret.median():+.2f}%/{gg.win.mean() * 100:.0f}%(n={len(gg)})")
    print("  2026年: " + " | ".join(row))
    print("\n預註冊判準提醒: Q2單獨過≠上板;Q3增量不過=與季線冗餘,戰情板照舊;n小全部觀察層。")


if __name__ == "__main__":
    main()
