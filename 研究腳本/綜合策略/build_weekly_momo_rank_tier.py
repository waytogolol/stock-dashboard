# -*- coding: utf-8 -*-
"""週級強者續強×排名分層測試(2026-08-05,使用者:「為何是前10名,有沒有可能11-20名反而更好?」)。

核心假說: 最頂端漲幅(可能是消息面爆炒/軋空完成/一次性跳空)反而比次強動能更容易反轉,11-20名可能代表
「持續有量能推升但還沒噴到最極端」的更健康動能。

設計: 通過門檻篩選(20%主/15%敏感度)+流動性篩選(0.3億,沿用M模組既有門檻,不另外設計)後的候選股票,
按單週漲幅由高到低排序,分三層獨立回測: rank1-10(現行版本)/rank11-20/rank21-30。

⚠關鍵方法論陷阱(務必誠實揭露): rank2-3層要求「候選股數>=分層上限」才進場(不足20/30檔的週,該分層
自然空手,不勉強湊數,比照使用者原話)。但這代表rank11-20/21-30只會在「候選股票數本來就很多」的週進場
——候選數多,幾乎必然對應大盤/全市場動能同時爆發的強勢週(廣度夠寬),等於間接變成一種「隱性regime濾網」
(只挑候選夠多的強勢週交易),而rank1-10在候選僅1檔時也照樣進場。若rank11-20/21-30的MDD/夏普看起來比
rank1-10好,不能直接歸因於「排名本身」,必須先做「同一批週」的配對比較(rank1-10限定在rank11-20有效的
那些週上重算)才能把「排名效果」和「候選數過濾出的regime效果」分開,本卷同時做全樣本版+配對版兩種比較。

沿用M模組(build_weekly_momo_regime_overlay.py)面板/交易/組合曲線/統計函式,不重新發明。

用法: python 研究腳本/綜合策略/build_weekly_momo_rank_tier.py (從根目錄執行,鐵律)
產出: 純console報告,無檔案輸出。
"""
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "研究腳本/綜合策略")
import build_weekly_momo_regime_overlay as M  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

TIERS = [(1, 10, "rank1-10(現行)"), (11, 20, "rank11-20"), (21, 30, "rank21-30")]
THRESHOLDS = [(0.20, "20%"), (0.15, "15%")]


def build_trades_ranktier(threshold, lo, hi):
    """lo/hi: 1-indexed排名區間(含端點)。lo=1時沿用現行「有幾檔算幾檔,上限hi」邏輯;
    lo>1時嚴格要求候選數>=hi才進場(不足則該週空手,不湊數,比照使用者原話)。"""
    weeks = M.WIDE_RET.index
    start_i = weeks.searchsorted(pd.Timestamp(M.START))
    trades, weekly_baskets, cand_n_series = [], {}, {}
    for i in range(max(start_i, 1), len(weeks) - 1):
        wk = weeks[i]
        ret_i = M.WIDE_RET.iloc[i]
        liq_i = M.LIQ_OK.iloc[i].reindex(ret_i.index).fillna(False)
        cand = ret_i[(ret_i >= threshold) & liq_i].dropna().sort_values(ascending=False)
        n = len(cand)
        cand_n_series[wk] = n
        if lo == 1:
            if n == 0:
                continue
            sel = cand.iloc[:min(n, hi)]
        else:
            if n < hi:
                continue
            sel = cand.iloc[lo - 1:hi]
        exit_ret = M.WIDE_RET.iloc[i + 1]
        rows = []
        for c in sel.index:
            er = exit_ret.get(c, np.nan)
            if pd.isna(er):
                continue
            rows.append({"entry_week": wk, "exit_week": weeks[i + 1], "code": c,
                         "entry_ret": float(sel[c]), "exit_ret": float(er),
                         "net_ret": float(er) - M.COST})
        if rows:
            df = pd.DataFrame(rows)
            weekly_baskets[wk] = df
            trades.extend(rows)
    trades = pd.DataFrame(trades)
    cand_n = pd.Series(cand_n_series)
    return trades, weekly_baskets, cand_n


def full_stats(baskets, grid):
    ret, exec_trades = M.portfolio_curve(baskets, grid, mode="baseline", weighting="equal")
    st = M.stats_from_ret(ret)
    tr = M.trade_stats(exec_trades)
    ci = M.bootstrap_ci(exec_trades)
    yr = M.yearly_breakdown(ret)
    return {**st, "tr_n": tr["n"], "tr_win": tr["win"], "tr_pf": tr["pf"], "tr_mean": tr["mean"],
            "ci_lo": ci[0], "ci_hi": ci[1], "n_pos_year": int((yr > 0).sum()), "n_year": len(yr)}


def print_row(label, r):
    if r is None:
        print(f"{label:<26}  無有效交易週,略過")
        return
    ci_txt = f"[{r['ci_lo']:+.2f}%,{r['ci_hi']:+.2f}%]"
    print(f"{label:<26}{r['n_weeks_active']:>5d}/{r['n_weeks_total']:<5d}"
          f"{r['mult']:>8.1f}x{r['cagr']:>7.1f}%{r['mdd']:>7.1f}%{r['sharpe']:>6.2f}{r['calmar']:>7.2f}"
          f"{r['tr_win']:>5.0f}%{r['tr_pf']:>6.2f}{r['tr_mean']:>7.2f}%{ci_txt:>20}{r['n_pos_year']:>4d}/{r['n_year']:<3d}")


HDR = (f"{'版本':<26}{'訊號週':>11}{'複利':>8}{'年化':>8}{'MDD':>8}{'夏普':>6}{'Calmar':>7}"
       f"{'勝率':>6}{'PF':>6}{'單筆均':>8}{'CI':>20}{'正年':>7}")


def run_threshold(threshold, label):
    print("\n" + "=" * 112)
    print(f"### 排名分層測試  動能門檻={label} ###")
    weeks = M.WIDE_RET.index
    start_i = weeks.searchsorted(pd.Timestamp(M.START))
    grid = weeks[start_i:]

    tier_data = {}
    for lo, hi, name in TIERS:
        trades, baskets, cand_n = build_trades_ranktier(threshold, lo, hi)
        tier_data[(lo, hi)] = {"name": name, "trades": trades, "baskets": baskets, "cand_n": cand_n}

    print(f"\n-- 候選股數分佈(通過門檻+流動性篩選、尚未分層前,全樣本{len(grid)}週) --")
    cand_n = tier_data[(1, 10)]["cand_n"]
    print(f"  候選數: 中位{cand_n.median():.0f} 平均{cand_n.mean():.1f} "
          f">=10檔的週佔{(cand_n >= 10).mean() * 100:.0f}% >=20檔的週佔{(cand_n >= 20).mean() * 100:.0f}% "
          f">=30檔的週佔{(cand_n >= 30).mean() * 100:.0f}% 最大值{cand_n.max():.0f}")

    print(f"\n-- 各分層全樣本回測(各自獨立訊號週,未配對) --")
    print(HDR)
    full_results = {}
    for lo, hi, name in TIERS:
        baskets = tier_data[(lo, hi)]["baskets"]
        r = full_stats(baskets, grid) if len(baskets) else None
        full_results[(lo, hi)] = r
        basket_sizes = pd.Series({wk: len(b) for wk, b in baskets.items()}) if baskets else pd.Series(dtype=float)
        bsz = f"籃子中位{basket_sizes.median():.0f}(min{basket_sizes.min():.0f})" if len(basket_sizes) else "n/a"
        print_row(f"{name}", r)
        print(f"  {' ' * 0}└ {bsz}")

    # -- 配對比較: 把rank1-10限定在rank11-20/21-30「有效」的那些週上重算,拆解排名效果vs候選數regime效果 --
    print(f"\n-- 配對比較(同一批週,拆解「排名本身」vs「候選數多=隱性強勢regime濾網」的效果) --")
    for lo, hi, name in TIERS[1:]:
        target_weeks = set(tier_data[(lo, hi)]["baskets"].keys())
        if not target_weeks:
            print(f"  {name}: 完全無有效週,無法配對比較")
            continue
        r1_paired_baskets = {wk: b for wk, b in tier_data[(1, 10)]["baskets"].items() if wk in target_weeks}
        r1_paired = full_stats(r1_paired_baskets, grid) if r1_paired_baskets else None
        r_tier = full_results[(lo, hi)]
        print(f"\n  [限定在{name}有效的{len(target_weeks)}週上比較]")
        print("  " + HDR)
        print("  " + "-" * len(HDR))
        print("  ", end="")
        print_row(f"rank1-10(同批週)", r1_paired)
        print("  ", end="")
        print_row(f"{name}(本身)", r_tier)

    return tier_data, full_results


def main():
    for threshold, label in THRESHOLDS:
        run_threshold(threshold, label)
    print("\n" + "=" * 112)
    print("跑完。以上為console探索報告,無檔案輸出。")


if __name__ == "__main__":
    main()
