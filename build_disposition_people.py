# -*- coding: utf-8 -*-
"""處置×「比例×人數」象限考卷(2026-07-25,大戶人數回補完成後首卷,使用者裁示開工)
問題: d4w(千張大戶持股%4週流向)已轉正(20分盤),但「比例↑」有兩種質地——
  A 普遍進場: 比例↑且千張人數↑ = 新大戶出現(多個獨立informed資金)
  B 鯨魚集中: 比例↑但人數平/↓ = 舊鯨魚吃更多(可能只是大股東護盤/主力自救)
主假說(預註冊): A優於B(需求更廣=更穩);雙尾測試,20分盤=主戰場(d4w正式層),5分盤同報僅參考。
先驗申報: TDCC水準/位階全死、流向獨活;本卷=流向質地細分,方向先驗中性偏A;弱結果不得敘事成正面。

設計(預註冊):
- 母體: 重用tmp_disposition_tdcc_panel.pkl(event_id口徑/v4_net/d4w/y/match_min,分層永不合併)
- 新特徵(tdcc_people表,口徑與d4w完全同構): cutoff=announce-3日曆日最新快照,距cutoff>21天作廢,
  idx>=4才算 => dn4w = n1000_now - n1000[idx-4](4週千張人數變化,整數);
  dn4w_rel = dn4w/max(n1000[idx-4],1)(敏感度用); n800版=次要敏感度
- 分析: ①四象限V4(A/B/C/D=d4w>0×dn4w>0雙二元)中位/勝率
  ②主考題 A vs B(皆d4w>0)差值LOTO+年群bootstrap(B=10000,seed=42)
  ③dn4w>0 vs <=0 全池(不管d4w)+2×2增量檢查(dn4w是否只是d4w影子)
  ④出關後post10同切(不截斷) ⑤冗餘: Spearman(dn4w,d4w)/dn4w=0占比/dn4w_rel與n800敏感度
- sanity錨: 2330近週dn4w手算重現(回補驗收錨1,477人同源)
用法: python -X utf8 build_disposition_people.py
"""
import sqlite3
import sys
import time

import numpy as np
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DB = "capital_flow.db"
PANEL_IN = "tmp_disposition_tdcc_panel.pkl"
PANEL_OUT = "tmp_disposition_people_panel.pkl"
LAG_DAYS = 3
STALE_DAYS = 21
B_BOOT = 10000
SEED = 42


def read_sql_retry(sql, tries=8, wait=4):
    for i in range(tries):
        try:
            con = sqlite3.connect(DB, timeout=30)
            df = pd.read_sql(sql, con)
            con.close()
            return df
        except sqlite3.OperationalError as e:
            if "locked" in str(e) and i < tries - 1:
                print(f"  (db locked,{wait}s重試 {i + 1}/{tries})")
                time.sleep(wait)
            else:
                raise


def stat(x, lab):
    x = pd.Series(x).dropna()
    if len(x) < 15:
        print(f"    {lab}: n={len(x)}太少")
        return None
    print(f"    {lab}: 中位{x.median() * 100:+6.2f}% 均值{x.mean() * 100:+6.2f}% "
          f"勝率{(x > 0).mean() * 100:3.0f}% n={len(x):,}")
    return x


def loto_bootstrap_diff(sig, ctl, val_col, year_col, label, b=B_BOOT, seed=SEED):
    sig = sig.dropna(subset=[val_col])
    ctl = ctl.dropna(subset=[val_col])
    if len(sig) < 15 or len(ctl) < 15:
        print(f"      [{label}] 樣本不足(訊號n={len(sig)},對照n={len(ctl)}),略過")
        return None
    years = sorted(set(sig[year_col].unique()) | set(ctl[year_col].unique()))
    if len(years) < 3:
        print(f"      [{label}] 年份數不足,略過")
        return None
    rows = []
    for yr in years:
        s2, c2 = sig[sig[year_col] != yr], ctl[ctl[year_col] != yr]
        if len(s2) >= 10 and len(c2) >= 10:
            rows.append((yr, s2[val_col].median() - c2[val_col].median()))
    if rows:
        rows.sort(key=lambda r: r[1])
        pos = sum(1 for _, d in rows if d > 0)
        print(f"      差值LOTO最壞: 剔{rows[0][0]}後{rows[0][1] * 100:+.2f}pp, 為正{pos}/{len(rows)}年")
    rng = np.random.default_rng(seed)
    sg = {yr: sig.loc[sig[year_col] == yr, val_col].values for yr in sig[year_col].unique()}
    cg = {yr: ctl.loc[ctl[year_col] == yr, val_col].values for yr in ctl[year_col].unique()}
    diffs = []
    for _ in range(b):
        pick = rng.choice(years, size=len(years), replace=True)
        sa = [sg[y] for y in pick if y in sg]
        ca = [cg[y] for y in pick if y in cg]
        if sa and ca:
            sa, ca = np.concatenate(sa), np.concatenate(ca)
            if len(sa) >= 10 and len(ca) >= 10:
                diffs.append(np.median(sa) - np.median(ca))
    diffs = np.array(diffs)
    if len(diffs) < 200:
        print(f"      [{label}] bootstrap有效樣本太少({len(diffs)})")
        return None
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    print(f"      差值bootstrap(B={len(diffs)}): CI95=[{lo * 100:+.2f},{hi * 100:+.2f}]pp "
          f"P(差<=0)={(diffs <= 0).mean():.4f} P(差>=0)={(diffs >= 0).mean():.4f}")
    return {"lo": lo, "hi": hi, "p_le": (diffs <= 0).mean()}


def main():
    panel = pd.read_pickle(PANEL_IN)
    ppl = read_sql_retry("SELECT code, date, n600, n800, n1000 FROM tdcc_people ORDER BY code, date")
    ppl["date"] = pd.to_datetime(ppl.date)
    series = {}
    for code, g in ppl.groupby("code"):
        g = g.sort_values("date")
        series[code] = (g["date"].values.astype("datetime64[D]"),
                        g["n1000"].values.astype(float), g["n800"].values.astype(float))

    # sanity錨: 2330 千張人數近週(驗收錨1,477人所在序列)
    dts, n1k, _ = series["2330"]
    print(f"sanity錨 2330: 最新快照{dts[-1]} n1000={n1k[-1]:.0f} (驗收錨2026-07-17=1,477); "
          f"4週前={n1k[-5]:.0f} => dn4w={n1k[-1] - n1k[-5]:+.0f}")

    rows = []
    for r in panel.itertuples():
        rec = {"event_id": r.event_id, "dn4w": np.nan, "dn4w_rel": np.nan, "dn4w800": np.nan}
        sv = series.get(r.code)
        if sv is not None and pd.notna(r.announce_date):
            dts, n1k, n8h = sv
            cutoff = np.datetime64((r.announce_date - pd.Timedelta(days=LAG_DAYS)).date())
            idx = int(np.searchsorted(dts, cutoff, side="right") - 1)
            if idx >= 4 and int((cutoff - dts[idx]).astype(int)) <= STALE_DAYS:
                rec["dn4w"] = n1k[idx] - n1k[idx - 4]
                rec["dn4w_rel"] = rec["dn4w"] / max(n1k[idx - 4], 1.0)
                rec["dn4w800"] = n8h[idx] - n8h[idx - 4]
        rows.append(rec)
    feat = pd.DataFrame(rows)
    panel = panel.merge(feat, on="event_id", how="left")
    panel["v4d"] = panel.v4_net / 100
    panel.to_pickle(PANEL_OUT)

    both = panel[panel.v4_valid & panel.d4w.notna() & panel.dn4w.notna()]
    print(f"\n母體: V4可交易{panel.v4_valid.sum():,}; d4w+dn4w皆有效={len(both):,} "
          f"(dn4w=0占{(both.dn4w == 0).mean() * 100:.0f}%)")
    print(f"冗餘檢查: Spearman(dn4w, d4w)={both[['dn4w', 'd4w']].corr(method='spearman').iloc[0, 1]:+.3f} "
          f"(太高=同一個訊號換皮,低=有獨立資訊)")

    for mm in ["5", "20"]:
        pop = both[both.match_min == mm].copy()
        pop["cell"] = np.where(pop.d4w > 0, "比例↑", "比例↓") + np.where(pop.dn4w > 0, "人數↑", "人數↓")
        print("\n" + "#" * 70)
        print(f"## match_min={mm}  n={len(pop):,}  (主戰場={'是' if mm == '20' else '否(5分d4w僅候選)'})")
        print("#" * 70)

        print("== 分析1: 四象限 V4 ==")
        for cell, lab in [("比例↑人數↑", "A 普遍進場"), ("比例↑人數↓", "B 鯨魚集中"),
                          ("比例↓人數↑", "C 分散接手"), ("比例↓人數↓", "D 大戶撤退")]:
            stat(pop[pop.cell == cell].v4d, f"{lab}({cell})")

        print("== 分析2: 主考題 A vs B(皆d4w>0, LOTO+bootstrap) ==")
        A = pop[pop.cell == "比例↑人數↑"]
        Bb = pop[pop.cell == "比例↑人數↓"]
        a = stat(A.v4d, "A 普遍進場")
        b = stat(Bb.v4d, "B 鯨魚集中")
        if a is not None and b is not None:
            print(f"      中位差(A-B): {(a.median() - b.median()) * 100:+.2f}pp")
        loto_bootstrap_diff(A, Bb, "v4d", "y", f"{mm}分 A-B")

        print("== 分析3: 人數流向單獨(dn4w>0 vs <=0,全池)+2×2增量 ==")
        hi = pop[pop.dn4w > 0]
        rest = pop[pop.dn4w <= 0]
        a = stat(hi.v4d, "dn4w>0")
        b = stat(rest.v4d, "dn4w<=0")
        if a is not None and b is not None:
            print(f"      中位差: {(a.median() - b.median()) * 100:+.2f}pp")
        loto_bootstrap_diff(hi, rest, "v4d", "y", f"{mm}分 dn4w>0-餘(全池)")
        sub = pop[pop.d4w <= 0]
        a = stat(sub[sub.dn4w > 0].v4d, "d4w<=0∧dn4w>0(增量格C)")
        b = stat(sub[sub.dn4w <= 0].v4d, "d4w<=0∧dn4w<=0(D)")
        if a is not None and b is not None:
            print(f"      比例↓側中位差(C-D): {(a.median() - b.median()) * 100:+.2f}pp "
                  f"(顯著=人數有d4w以外的獨立資訊)")
        loto_bootstrap_diff(sub[sub.dn4w > 0], sub[sub.dn4w <= 0], "v4d", "y", f"{mm}分 C-D")

        print("== 分析4: 出關後post10(不截斷) ==")
        popc = pop[~pop.truncated]
        for cell, lab in [("比例↑人數↑", "A"), ("比例↑人數↓", "B")]:
            stat(popc[popc.cell == cell].post10, f"post10 {lab}")

        print("== 分析5: 敏感度 ==")
        A2 = pop[(pop.d4w > 0) & (pop.dn4w_rel > 0.05)]
        stat(A2.v4d, "A嚴格版(人數增>5%)")
        A8 = pop[(pop.d4w > 0) & (pop.dn4w800 > 0)]
        B8 = pop[(pop.d4w > 0) & (pop.dn4w800 <= 0)]
        a = stat(A8.v4d, "n800版 A")
        b = stat(B8.v4d, "n800版 B")
        if a is not None and b is not None:
            print(f"      n800版中位差(A-B): {(a.median() - b.median()) * 100:+.2f}pp (方向應與主測一致)")

    print(f"\n面板存{PANEL_OUT}")


if __name__ == "__main__":
    main()
