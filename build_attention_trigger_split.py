# -*- coding: utf-8 -*-
"""跌觸發子組再細分:純第一款(單一累積跌幅) vs 混合觸發(同時踩到其他款)
使用者提問(2026-07-21):跌觸發子組(trade10中位+5.79%/勝率67%,已晉級候選)裡,
單獨踩第一款(累積跌幅)跟同時踩多款(價跌+量增/週轉/券商集中度)走法有沒有差。

延伸: 跌觸發內單一款也有非第一款的(triggers='3'/'4'/'5',代表「跌幅+量增」/「跌幅+週轉」/
「跌幅+券商集中度」的官方複合條件,本身就不是純價格觸發),一併拆開比較。
用法: python build_attention_trigger_split.py
"""
import numpy as np
import pandas as pd

B = 10000
SEED = 42


def stat(x, lab):
    x = pd.Series(x).dropna()
    if len(x) < 15:
        print(f"  {lab}: n={len(x)}太少")
        return None
    print(f"  {lab}: 中位{x.median():+6.2f}% 均值{x.mean():+6.2f}% 勝率{(x > 0).mean() * 100:3.0f}% n={len(x):,}")
    return x


def loto_bootstrap(sub, label):
    sub = sub.dropna(subset=["trade10"])
    if len(sub) < 30 or sub.y.nunique() < 3:
        print(f"  [{label}] 樣本或年份數不足,略過LOTO/bootstrap")
        return
    rows = []
    for yr in sorted(sub.y.unique()):
        s2 = sub[sub.y != yr]
        if len(s2) >= 15:
            rows.append((yr, s2.trade10.median(), len(s2)))
    if not rows:
        return
    rows.sort(key=lambda x: x[1])
    print(f"  LOTO最壞: 剔除{rows[0][0]}年後中位{rows[0][1]:+.2f}% (剩n={rows[0][2]}), "
          f"為正比例{sum(1 for _, m, _ in rows if m > 0) / len(rows) * 100:.0f}%")

    rng = np.random.default_rng(SEED)
    years = sub.y.unique()
    groups = {yr: sub[sub.y == yr] for yr in years}
    abs_stats = []
    for _ in range(B):
        pick = rng.choice(years, size=len(years), replace=True)
        boot = pd.concat([groups[yr] for yr in pick])
        if len(boot) >= 15:
            abs_stats.append(boot.trade10.median())
    abs_stats = np.array(abs_stats)
    alo, ahi = np.percentile(abs_stats, [2.5, 97.5])
    p_abs = (abs_stats <= 0).mean()
    print(f"  cluster bootstrap(年群,B={len(abs_stats)}): CI95=[{alo:+.2f}, {ahi:+.2f}], P(<=0)={p_abs:.4f}")


def main():
    df = pd.read_pickle("tmp_attention_event_panel.pkl")
    ep = df[df.episode_first].copy()
    down = ep[ep.direction == "跌觸發"].dropna(subset=["trade10"]).copy()
    print(f"跌觸發子組總n={len(down)}\n")

    down["n_triggers"] = down.triggers.str.split(",").str.len()
    down["is_pure1"] = down.triggers == "1"
    down["is_multi"] = down.n_triggers > 1

    print("== 觸發款別組成 ==")
    print(down.triggers.value_counts().to_string())

    print("\n== A. 純第一款(單一累積跌幅) vs 混合觸發(同時踩多款) ==")
    pure1 = down[down.is_pure1]
    multi = down[down.is_multi]
    stat(pure1.trade10, "純第一款(triggers='1')      ")
    stat(multi.trade10, "混合觸發(triggers含多款,逗號)")
    if len(pure1) >= 15 and len(multi) >= 15:
        print(f"  中位差(混合-純1) = {multi.trade10.median() - pure1.trade10.median():+.2f}pp")

    print("\n  -- 純第一款 LOTO+bootstrap --")
    loto_bootstrap(pure1, "純第一款")
    print("\n  -- 混合觸發 LOTO+bootstrap --")
    loto_bootstrap(multi, "混合觸發")

    print("\n== B. 單一款細看(非第一款的單一觸發款:3=跌幅+量增/4=跌幅+週轉/5=跌幅+券商集中度) ==")
    for trig in ["1", "3", "4", "5"]:
        sub = down[down.triggers == trig]
        stat(sub.trade10, f"triggers='{trig}'")

    print("\n== C. 純款1 vs 純款3/4/5(單一但非價格單純觸發) vs 混合 三分類 ==")
    other_single = down[(down.n_triggers == 1) & (~down.is_pure1)]
    stat(pure1.trade10, "純款1(價格單一)      ")
    stat(other_single.trade10, "純款3/4/5(單一複合款)")
    stat(multi.trade10, "混合(2款以上)         ")

    print("\n== 逐年檢查(純款1 vs 混合,trade10中位) ==")
    for y in sorted(down.y.unique()):
        p = pure1[pure1.y == y].trade10
        m = multi[multi.y == y].trade10
        p_s = f"{p.median():+.2f}%(n={len(p)})" if len(p) >= 3 else f"n={len(p)}太少"
        m_s = f"{m.median():+.2f}%(n={len(m)})" if len(m) >= 3 else f"n={len(m)}太少"
        print(f"  {y}: 純款1={p_s}  混合={m_s}")


if __name__ == "__main__":
    main()
