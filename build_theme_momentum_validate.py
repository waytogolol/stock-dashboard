# -*- coding: utf-8 -*-
"""⑫題材月營收動能剩餘驗證(開工清單第2項):
(1) leave-one-theme-out:逐一剔除單一題材,看score=4的超額優勢是否被PCB/CCL等
    單一題材撐起(集中度檢查)。
(2) 題材-月cluster bootstrap:同題材-月內成員報酬高度相關,獨立單位=題材-月群。
    以群為單位重抽(B=10000),給score=4超額報酬中位數CI,以及
    score=4 vs score<4 中位數差的單尾p值。
用法: python build_theme_momentum_validate.py
"""
import numpy as np
import pandas as pd

B = 10000
SEED = 42


def main():
    panel = pd.read_pickle("tmp_theme_momentum_v2_panel.pkl").copy()
    panel["y"] = panel.year_month.str[:4]
    s4 = panel[panel.score == 4].copy()
    rest = panel[panel.score < 4].copy()
    print(f"score=4: {len(s4)}筆 / {s4.groupby(['industry','year_month']).ngroups}題材-月群 / "
          f"{s4.industry.nunique()}個題材")
    print(f"全樣本 score=4 超額: 中位{s4.excess60.median():+.2f}% 均{s4.excess60.mean():+.2f}% "
          f"勝率{(s4.excess60 > 0).mean() * 100:.0f}%")

    # ---------- (1) LOTO ----------
    share = s4.industry.value_counts()
    print("\n--- score=4 樣本題材集中度(前10) ---")
    for ind, n in share.head(10).items():
        print(f"  {ind}: {n}筆 ({n / len(s4) * 100:.0f}%)")

    print("\n--- leave-one-theme-out(剔除後的score=4超額中位/勝率) ---")
    rows = []
    for ind in share.index:
        ex = s4[s4.industry != ind].excess60
        rows.append((ind, share[ind], ex.median(), (ex > 0).mean() * 100))
    loto = pd.DataFrame(rows, columns=["剔除題材", "該題材n", "剩餘中位%", "剩餘勝率%"])
    loto = loto.sort_values("剩餘中位%")
    print("最傷的5個(剔除後中位掉最多):")
    print(loto.head(5).round(2).to_string(index=False))
    print("最撐的5個(剔除後中位反升=該題材在拖後腿):")
    print(loto.tail(5).round(2).to_string(index=False))
    worst = loto.iloc[0]
    print(f"→ 單一題材全剔除的最壞情況: 中位{worst['剩餘中位%']:+.2f}% "
          f"(全樣本{s4.excess60.median():+.2f}%)")

    # ---------- (2) 題材-月 cluster bootstrap ----------
    rng = np.random.default_rng(SEED)

    def cluster_arrays(df):
        return [g.excess60.values for _, g in df.groupby(["industry", "year_month"])]

    def boot_stat(clusters, fn):
        k = len(clusters)
        out = np.empty(B)
        for b in range(B):
            idx = rng.integers(0, k, k)
            out[b] = fn(np.concatenate([clusters[i] for i in idx]))
        return out

    c4 = cluster_arrays(s4)
    cr = cluster_arrays(rest)
    print(f"\n--- cluster bootstrap (B={B}, 群=題材-月, score=4群數{len(c4)}/其他群數{len(cr)}) ---")
    for fn, name in [(np.median, "中位數"), (np.mean, "均值")]:
        b4 = boot_stat(c4, fn)
        br = boot_stat(cr, fn)
        diff = b4 - br
        p = (diff <= 0).mean()
        print(f"score=4 超額{name}: 點估{fn(s4.excess60.values):+.2f}% "
              f"95%CI[{np.percentile(b4, 2.5):+.2f}, {np.percentile(b4, 97.5):+.2f}]")
        print(f"  vs score<4 差: 點估{fn(s4.excess60.values) - fn(rest.excess60.values):+.2f}pp "
              f"95%CI[{np.percentile(diff, 2.5):+.2f}, {np.percentile(diff, 97.5):+.2f}] "
              f"單尾p(差<=0)={p:.4f}")

    # 逐年版(只看多頭題材年是否仍站得住)
    print("\n--- cluster bootstrap 逐年(score=4超額中位數CI) ---")
    for y in sorted(s4.y.unique()):
        cy = cluster_arrays(s4[s4.y == y])
        if len(cy) < 5:
            print(f"  {y}: 群數{len(cy)}太少跳過")
            continue
        by = boot_stat(cy, np.median)
        pt = s4[s4.y == y].excess60.median()
        print(f"  {y}: 點估{pt:+.2f}% 95%CI[{np.percentile(by, 2.5):+.2f}, "
              f"{np.percentile(by, 97.5):+.2f}] 群數{len(cy)}")


if __name__ == "__main__":
    main()
