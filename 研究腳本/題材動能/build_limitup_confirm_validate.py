# -*- coding: utf-8 -*-
"""漲停點火確認候選的晉升驗證(LOTO+cluster bootstrap,流程比照build_theme_momentum_validate)
候選: score=4題材-月,族群內近20日有成員收盤鎖漲停(anyLU) vs 無 → 組合超額差
觀測值(2026-07-15): 有LU中位+3.03/59%(n=75) vs 無LU -0.03/50%(n=119),劑量單調,score<=2對照無效
驗證: ①LOTO(逐題材剔除看最壞) ②題材群cluster bootstrap(B=10000,seed=42)中位差CI+p
判準: LOTO最壞仍為正+CI不含0 → 晉級候選可提使用者裁示;否則降觀察層
用法: python build_limitup_confirm_validate.py
"""
import numpy as np
import pandas as pd

B = 10000
SEED = 42


def main():
    df = pd.read_pickle("tmp_limitup_gap_panel.pkl")
    tm = df[df.score == 4].groupby(["industry", "sigT"]).agg(
        ex=("ex", "mean"), anylu=("lu", "any")).reset_index()
    a, b = tm[tm.anylu], tm[~tm.anylu]
    obs = a.ex.median() - b.ex.median()
    print(f"score=4題材-月: 有LU n={len(a)} / 無LU n={len(b)}, 觀測中位差={obs:+.2f}pp")

    print("\n== LOTO(逐題材剔除) ==")
    rows = []
    for ind in tm.industry.unique():
        sub = tm[tm.industry != ind]
        aa, bb = sub[sub.anylu], sub[~sub.anylu]
        if len(aa) >= 5 and len(bb) >= 5:
            rows.append((ind, aa.ex.median() - bb.ex.median(), len(aa)))
    rows.sort(key=lambda x: x[1])
    for ind, d, n in rows[:3]:
        print(f"  最壞{ind}: 剔除後中位差{d:+.2f}pp (LU組剩n={n})")
    print(f"  全部{len(rows)}個剔除情境中位差範圍: {rows[0][1]:+.2f} ~ {rows[-1][1]:+.2f}, "
          f"為正比例{sum(1 for _, d, _ in rows if d > 0) / len(rows) * 100:.0f}%")

    print("\n== 題材群cluster bootstrap ==")
    rng = np.random.default_rng(SEED)
    themes = tm.industry.unique()
    groups = {t: tm[tm.industry == t] for t in themes}
    stats = []
    for _ in range(B):
        pick = rng.choice(themes, size=len(themes), replace=True)
        boot = pd.concat([groups[t] for t in pick])
        aa, bb = boot[boot.anylu], boot[~boot.anylu]
        if len(aa) >= 5 and len(bb) >= 5:
            stats.append(aa.ex.median() - bb.ex.median())
    stats = np.array(stats)
    lo, hi = np.percentile(stats, [2.5, 97.5])
    p = (stats <= 0).mean()
    print(f"  有效replicate={len(stats)}, 中位差CI95=[{lo:+.2f}, {hi:+.2f}], P(<=0)={p:.4f}")

    print("\n== 劑量>=2家 vs 0家(次要) ==")
    tm2 = df[df.score == 4].groupby(["industry", "sigT"]).agg(
        ex=("ex", "mean"), nlu=("lu", "sum")).reset_index()
    hi2, z = tm2[tm2.nlu >= 2], tm2[tm2.nlu == 0]
    print(f"  >=2家中位{hi2.ex.median():+.2f}(n={len(hi2)}) vs 0家{z.ex.median():+.2f}(n={len(z)})")

    verdict = "晉級候選(提使用者裁示)" if rows[0][1] > 0 and lo > 0 else "未過,降觀察層"
    print(f"\n判準結果: LOTO最壞{rows[0][1]:+.2f} / CI下緣{lo:+.2f} → {verdict}")


if __name__ == "__main__":
    main()
