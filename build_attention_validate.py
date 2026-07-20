# -*- coding: utf-8 -*-
"""注意股票「跌觸發」子組晉升驗證(比照build_limitup_confirm_validate流程)
候選: attention事件方向分層中,reason含「跌幅」不含「漲幅」(跌觸發,官方13款中的累積跌幅/單日跌停等)
觀測值(build_attention_event.py): 跌觸發fwd10中位+4.64%/勝率63%/n=478,遠優於其餘中性+漲觸發組
機制假說: 與處置V4/恐慌梯度同一機制家族(被迫性下跌後的非資訊性賣壓回補),但注意階段無分盤無預收,
         純粹測是否光靠「官方公開揭露=跌幅異常」這個資訊本身就有反彈可交易性
驗證: ①LOTO(逐年剔除看最壞) ②月群cluster bootstrap(B=10000,seed=42,對trade10做絕對值CI與vs其餘組差值CI)
判準: LOTO最壞仍為正+絕對值CI下緣>0 → 晉級候選可提使用者裁示;否則降觀察層
用法: python build_attention_validate.py
"""
import numpy as np
import pandas as pd

B = 10000
SEED = 42


def main():
    df = pd.read_pickle("tmp_attention_event_panel.pkl")
    ep = df[df.episode_first].copy()

    # 面板僅存announce_date年份(y),樣本量小(n=478)不足以再切月群,cluster單位退一級用年群
    down = ep[ep.direction == "跌觸發"].dropna(subset=["trade10"])
    rest = ep[ep.direction != "跌觸發"].dropna(subset=["trade10"])
    print(f"跌觸發 n={len(down)} / 其餘(中性+漲觸發) n={len(rest)}")
    print(f"跌觸發 trade10: 中位{down.trade10.median():+.2f}% 均值{down.trade10.mean():+.2f}% "
          f"勝率{(down.trade10 > 0).mean() * 100:.0f}%")
    print(f"其餘   trade10: 中位{rest.trade10.median():+.2f}% 均值{rest.trade10.mean():+.2f}% "
          f"勝率{(rest.trade10 > 0).mean() * 100:.0f}%")
    obs_diff = down.trade10.median() - rest.trade10.median()
    print(f"觀測中位差 = {obs_diff:+.2f}pp")

    print("\n== LOTO(逐年剔除,跌觸發自身中位) ==")
    rows = []
    for yr in sorted(down.y.unique()):
        sub = down[down.y != yr]
        if len(sub) >= 15:
            rows.append((yr, sub.trade10.median(), len(sub)))
    rows.sort(key=lambda x: x[1])
    for yr, m, n in rows[:3]:
        print(f"  剔除{yr}年後最壞: 跌觸發中位{m:+.2f}% (剩n={n})")
    print(f"  全部{len(rows)}個剔除情境中位範圍: {rows[0][1]:+.2f} ~ {rows[-1][1]:+.2f}%, "
          f"為正比例{sum(1 for _, m, _ in rows if m > 0) / len(rows) * 100:.0f}%")

    print("\n== cluster bootstrap(以年為群,樣本量小改年群非月群) ==")
    rng = np.random.default_rng(SEED)
    years = down.y.unique()
    groups = {yr: down[down.y == yr] for yr in years}
    rest_years = rest.y.unique()
    rest_groups = {yr: rest[rest.y == yr] for yr in rest_years}
    abs_stats, diff_stats = [], []
    for _ in range(B):
        pick = rng.choice(years, size=len(years), replace=True)
        boot = pd.concat([groups[yr] for yr in pick])
        if len(boot) < 15:
            continue
        abs_stats.append(boot.trade10.median())
        pick_r = rng.choice(rest_years, size=len(rest_years), replace=True)
        boot_r = pd.concat([rest_groups[yr] for yr in pick_r])
        if len(boot_r) >= 15:
            diff_stats.append(boot.trade10.median() - boot_r.trade10.median())
    abs_stats = np.array(abs_stats)
    diff_stats = np.array(diff_stats)
    alo, ahi = np.percentile(abs_stats, [2.5, 97.5])
    dlo, dhi = np.percentile(diff_stats, [2.5, 97.5])
    p_abs = (abs_stats <= 0).mean()
    p_diff = (diff_stats <= 0).mean()
    print(f"  絕對值CI95=[{alo:+.2f}, {ahi:+.2f}], P(<=0)={p_abs:.4f}  (replicate={len(abs_stats)})")
    print(f"  差值CI95  =[{dlo:+.2f}, {dhi:+.2f}], P(<=0)={p_diff:.4f}  (replicate={len(diff_stats)})")

    print("\n== 觸發款別細看(跌觸發組的triggers組成) ==")
    print(down.triggers.value_counts().head(8))

    verdict = "晉級候選(提使用者裁示)" if rows[0][1] > 0 and alo > 0 else "未過,降觀察層"
    print(f"\n判準結果: LOTO最壞{rows[0][1]:+.2f}% / 絕對值CI下緣{alo:+.2f}% → {verdict}")


if __name__ == "__main__":
    main()
