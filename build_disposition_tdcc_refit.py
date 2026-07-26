# -*- coding: utf-8 -*-
"""d4w(處置×千張4週流向)轉正複驗(2026-07-25,待辦#4)
原考卷build_disposition_tdcc.py判決=✅候選: d4w最高三分位vs其餘 V4中位差5分+2.87pp/20分+3.68pp,
LOTO 8/8+年群bootstrap過+上市子樣本+3.46pp。保留=覆蓋64%有倖存者偏差(tdcc宇宙缺已下市股,
早年配對率低)+三分位切點在全池內擬合。
本複驗(預註冊):
  A. 2019-2023 refit: 只用早窗事件重新擬合d4w三分位切點,窗內測T3vs其餘(LOTO+年群bootstrap)
     ——若效應只是2024-26覆蓋完整期的產物,早窗應消失
  B. 2024-2026偽樣本外: 用A擬合的凍結切點套晚窗事件,測T3vs其餘——切點可轉移性
  C. 免參數正負號版: d4w>0(大戶4週淨增) vs d4w<=0,兩窗分測——完全無擬合切點,抗過擬最強
  D. 上市子樣本: 早窗內重測(原第三關是全池上市)
  E. 次要: post10出關後同切分兩窗點估計
轉正判準(預先寫死):
  主判準=A過(早窗T3-餘>0,LOTO年份多數為正+bootstrap CI95下緣>0或P(<=0)<0.05)
         且B同向(晚窗點估計>0,不強求顯著=n較小年份少)
  輔助=C兩窗同向。A過B反向=切點不穩,維持候選;A不過=效應集中晚窗,降級觀察(誠實報告)。
母體口徑與原考卷完全一致: match_min分層永不合併, v4_valid & p52有效 & d4w有效。
用法: python -X utf8 build_disposition_tdcc_refit.py
"""
import sys

import numpy as np
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PANEL = "tmp_disposition_tdcc_panel.pkl"
EARLY_YRS = (2019, 2023)
LATE_YRS = (2024, 2026)
B_BOOT = 10000
SEED = 42


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
        print(f"      [{label}] 年份數不足({len(years)}),略過")
        return None
    rows = []
    for yr in years:
        s2, c2 = sig[sig[year_col] != yr], ctl[ctl[year_col] != yr]
        if len(s2) >= 10 and len(c2) >= 10:
            rows.append((yr, s2[val_col].median() - c2[val_col].median()))
    if rows:
        rows.sort(key=lambda r: r[1])
        pos = sum(1 for _, d in rows if d > 0)
        print(f"      差值LOTO最壞: 剔{rows[0][0]}後差={rows[0][1] * 100:+.2f}pp, "
              f"為正{pos}/{len(rows)}年")
    rng = np.random.default_rng(seed)
    sg = {yr: sig.loc[sig[year_col] == yr, val_col].values for yr in sig[year_col].unique()}
    cg = {yr: ctl.loc[ctl[year_col] == yr, val_col].values for yr in ctl[year_col].unique()}
    diffs = []
    for _ in range(b):
        pick = rng.choice(years, size=len(years), replace=True)
        sarr = [sg[yr] for yr in pick if yr in sg]
        carr = [cg[yr] for yr in pick if yr in cg]
        if sarr and carr:
            sa, ca = np.concatenate(sarr), np.concatenate(carr)
            if len(sa) >= 10 and len(ca) >= 10:
                diffs.append(np.median(sa) - np.median(ca))
    diffs = np.array(diffs)
    if len(diffs) < 200:
        print(f"      [{label}] bootstrap有效樣本太少({len(diffs)})")
        return None
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    p_le = (diffs <= 0).mean()
    print(f"      差值bootstrap(B={len(diffs)}): CI95=[{lo * 100:+.2f},{hi * 100:+.2f}]pp "
          f"P(差<=0)={p_le:.4f}")
    return {"ci_lo": lo, "ci_hi": hi, "p_le": p_le,
            "diff": sig[val_col].median() - ctl[val_col].median()}


def two_group(pop, mask, val, lab, formal=True):
    hi, rest = pop[mask], pop[~mask]
    a = stat(hi[val], f"{lab} 高組")
    b = stat(rest[val], f"{lab} 其餘")
    d = None
    if a is not None and b is not None:
        d = a.median() - b.median()
        print(f"      中位差(高-餘): {d * 100:+.2f}pp")
    if formal:
        r = loto_bootstrap_diff(hi, rest, val, "y", lab)
        return d, r
    return d, None


def main():
    panel = pd.read_pickle(PANEL)
    panel["v4d"] = panel.v4_net / 100
    verdicts = {}
    for mm in ["5", "20"]:
        pop = panel[(panel.match_min == mm) & panel.v4_valid
                    & panel.p52.notna() & panel.d4w.notna()].copy()
        early = pop[(pop.y >= EARLY_YRS[0]) & (pop.y <= EARLY_YRS[1])].copy()
        late = pop[(pop.y >= LATE_YRS[0]) & (pop.y <= LATE_YRS[1])].copy()
        print("#" * 72)
        print(f"## match_min={mm}: 全池n={len(pop):,} 早窗2019-23 n={len(early):,} "
              f"晚窗2024-26 n={len(late):,}")
        print("##  早窗逐年n: " + "  ".join(f"{y}={n}" for y, n in early.groupby('y').size().items()))
        print("#" * 72)

        # A. 早窗refit: 切點只用早窗值擬合(值域切,非rank,才能凍結轉移)
        q1, q2 = early.d4w.quantile(1 / 3), early.d4w.quantile(2 / 3)
        print(f"\n== A. 2019-2023 refit(切點只用早窗擬合: q1={q1:+.3f} q2={q2:+.3f} pp of p1000) ==")
        e_t3 = early.d4w > q2
        print(f"  早窗T3(d4w>{q2:+.3f}) n={e_t3.sum()} / 其餘 n={(~e_t3).sum()}")
        dA, rA = two_group(early, e_t3, "v4d", f"{mm}分早窗 d4wT3高-餘")

        # B. 晚窗偽樣本外: 凍結早窗切點
        print(f"\n== B. 2024-2026偽樣本外(凍結早窗切點 q2={q2:+.3f}) ==")
        l_t3 = late.d4w > q2
        print(f"  晚窗T3 n={l_t3.sum()} / 其餘 n={(~l_t3).sum()}")
        dB, rB = two_group(late, l_t3, "v4d", f"{mm}分晚窗(凍結切點) d4wT3高-餘")

        # C. 免參數正負號版
        print("\n== C. 免參數正負號版(d4w>0 vs <=0,無任何擬合) ==")
        dC_e, _ = two_group(early, early.d4w > 0, "v4d", f"{mm}分早窗 d4w>0-餘")
        dC_l, _ = two_group(late, late.d4w > 0, "v4d", f"{mm}分晚窗 d4w>0-餘")

        # D. 早窗上市子樣本
        print("\n== D. 早窗上市子樣本(twse) ==")
        etw = early[early.market == "twse"]
        if len(etw) >= 40:
            dD, _ = two_group(etw, etw.d4w > q2, "v4d", f"{mm}分早窗上市 d4wT3高-餘")
        else:
            dD = None
            print(f"    n={len(etw)}不足40,只報數量不測")

        # E. 次要: post10(不截斷)
        print("\n== E. 次要: 出關後post10同切分(點估計) ==")
        for tag, sub in (("早窗", early), ("晚窗", late)):
            s2 = sub[~sub.truncated]
            hi, rest = s2[s2.d4w > q2], s2[~(s2.d4w > q2)]
            a = stat(hi.post10, f"{tag} T3 post10")
            b = stat(rest.post10, f"{tag} 餘 post10")
            if a is not None and b is not None:
                print(f"      中位差: {(a.median() - b.median()) * 100:+.2f}pp")

        # 判準彙整
        a_pass = rA is not None and rA["diff"] > 0 and rA["p_le"] < 0.05
        b_dir = dB is not None and dB > 0
        c_dir = (dC_e is not None and dC_e > 0, dC_l is not None and dC_l > 0)
        verdicts[mm] = dict(a_pass=a_pass, b_dir=b_dir, c_dir=c_dir, dA=dA, dB=dB,
                            dC_e=dC_e, dC_l=dC_l, dD=dD)
        print()

    print("=" * 72)
    print("預註冊判準彙整")
    print("=" * 72)
    for mm, v in verdicts.items():
        fmt = lambda d: "NA" if d is None else f"{d * 100:+.2f}pp"
        print(f"  {mm}分盤: A早窗refit {'PASS' if v['a_pass'] else 'FAIL'}({fmt(v['dA'])}) "
              f"| B晚窗同向 {'YES' if v['b_dir'] else 'NO'}({fmt(v['dB'])}) "
              f"| C正負號版 早{'+' if v['c_dir'][0] else '-'}({fmt(v['dC_e'])})/"
              f"晚{'+' if v['c_dir'][1] else '-'}({fmt(v['dC_l'])}) "
              f"| D早窗上市 {fmt(v['dD'])}")
        if v["a_pass"] and v["b_dir"]:
            print("    => 轉正條件達成(A過+B同向)")
        elif v["a_pass"]:
            print("    => A過但B反向=切點不穩,維持候選")
        else:
            print("    => A不過=效應集中晚窗或不穩,維持候選/降觀察")


if __name__ == "__main__":
    main()
