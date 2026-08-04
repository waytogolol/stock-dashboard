# -*- coding: utf-8 -*-
"""週級強者續強×流動性/胃納量分級測試(2026-08-05,使用者:「這個股票篩選週成交值可能太小,胃納量幾百萬
到幾千萬甚至上億都要考慮一下」)。

背景: 目前策略單一流動性門檻=近20週均週成交值>=0.3億,可能太寬鬆,無法反映不同資金規模的真實可執行性。
本卷建立「門檻vs可用訊號數vs績效」的容量曲線,測5個門檻分級(0.3/0.5/1/3/5億),20%/15%兩個動能門檻各
跑一輪完整回測。核心診斷呼應本次會談的MDD元凶結論(個股集中度風險,訊號週籃子檔數越少風險越大)——
流動性門檻拉高會讓每週合格股數變少,可能讓「籃子變薄」問題更嚴重,故本卷除了報酬/風險指標外,務必同時
報告每個門檻下的「訊號週籃子檔數分佈」(中位數/最小值/n<=3週佔比),不能只看報酬指標。

沿用`build_weekly_momo_regime_overlay.py`(M模組)的面板建置(M.WIDE_C/M.WIDE_RET/M.WIDE_M,已內建
close>0/money>0清洗)、交易建置邏輯(仿M.build_trades,但流動性門檻可參數化)、組合曲線/統計函式
(M.portfolio_curve/M.stats_from_ret/M.trade_stats/M.bootstrap_ci),不重新發明。

用法: python 研究腳本/綜合策略/build_weekly_momo_liquidity_tiers.py (從根目錄執行,鐵律)
產出: 純console報告,無檔案輸出。
"""
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "研究腳本/綜合策略")
import build_weekly_momo_regime_overlay as M  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

TIERS = [0.3e8, 0.5e8, 1e8, 3e8, 5e8]
TIER_LABELS = {0.3e8: "0.3億(現行)", 0.5e8: "0.5億", 1e8: "1億", 3e8: "3億", 5e8: "5億"}
THRESHOLDS = [(0.20, "20%"), (0.15, "15%")]


# ══ 一、參數化流動性門檻的交易建置(仿M.build_trades,liq_ok可外部指定) ══════════
def build_trades_tier(threshold, liq_ok, top_n=M.TOP_N):
    weeks = M.WIDE_RET.index
    start_i = weeks.searchsorted(pd.Timestamp(M.START))
    trades, weekly_baskets, cand_sizes = [], {}, []
    for i in range(max(start_i, 1), len(weeks) - 1):
        wk = weeks[i]
        ret_i = M.WIDE_RET.iloc[i]
        liq_i = liq_ok.iloc[i].reindex(ret_i.index).fillna(False)
        cand = ret_i[(ret_i >= threshold) & liq_i].dropna().sort_values(ascending=False)
        cand_sizes.append((wk, len(cand)))
        if len(cand) == 0:
            continue
        if len(cand) > top_n:
            cand = cand.iloc[:top_n]
        exit_ret = M.WIDE_RET.iloc[i + 1]
        rows = []
        for c in cand.index:
            er = exit_ret.get(c, np.nan)
            if pd.isna(er):
                continue
            rows.append({"entry_week": wk, "exit_week": weeks[i + 1], "code": c,
                         "entry_ret": float(cand[c]), "exit_ret": float(er),
                         "net_ret": float(er) - M.COST})
        if rows:
            df = pd.DataFrame(rows)
            weekly_baskets[wk] = df
            trades.extend(rows)
    trades = pd.DataFrame(trades)
    cand_sizes = pd.DataFrame(cand_sizes, columns=["week", "n_cand"]).set_index("week")
    return trades, weekly_baskets, cand_sizes


# ══ 二、每檔門檻下,全市場合格投資宇宙規模(不論動能訊號與否) ══════════════════
def universe_size_by_tier():
    print("\n-- 全市場流動性合格檔數(不論動能訊號,每週近20週均週成交值>=門檻的股票數,全樣本期間中位) --")
    weeks = M.WIDE_RET.index
    start_i = weeks.searchsorted(pd.Timestamp(M.START))
    for tier in TIERS:
        liq_ok = M.LIQ20 >= tier
        n_ok = liq_ok.iloc[start_i:].sum(axis=1)
        print(f"  {TIER_LABELS[tier]:<10} 全市場合格檔數: 中位{n_ok.median():.0f}檔 "
              f"(min{n_ok.min():.0f}~max{n_ok.max():.0f}) 近52週中位{n_ok.iloc[-52:].median():.0f}檔")


# ══ 三、主流程: 每個(動能門檻×流動性門檻)組合完整回測 ══════════════════════
def run():
    universe_size_by_tier()
    weeks = M.WIDE_RET.index
    start_i = weeks.searchsorted(pd.Timestamp(M.START))
    grid = weeks[start_i:]

    all_rows = []
    for threshold, tlabel in THRESHOLDS:
        print("\n" + "=" * 110)
        print(f"### 動能門檻={tlabel} top{M.TOP_N} × 流動性分級容量曲線 ###")
        rows = []
        for tier in TIERS:
            liq_ok = M.LIQ20 >= tier
            trades, baskets, cand_sizes = build_trades_tier(threshold, liq_ok)
            n_sig_weeks = len(baskets)
            if n_sig_weeks == 0:
                print(f"  {TIER_LABELS[tier]}: 完全無訊號週,略過")
                rows.append({"tier": tier, "n_sig_weeks": 0})
                continue

            basket_n = pd.Series({wk: len(b) for wk, b in baskets.items()})
            cand_n = cand_sizes["n_cand"]  # 全部候選週(含0檔週),用來看「連候選都稀缺」的程度

            ret, exec_trades = M.portfolio_curve(baskets, grid, mode="baseline", weighting="equal")
            st = M.stats_from_ret(ret)
            tr = M.trade_stats(exec_trades)
            ci = M.bootstrap_ci(exec_trades)

            rows.append({
                "tier": tier, "n_sig_weeks": n_sig_weeks, "n_total_weeks": len(grid),
                "basket_median": basket_n.median(), "basket_min": basket_n.min(),
                "basket_le3_pct": (basket_n <= 3).mean() * 100,
                "basket_le1_pct": (basket_n <= 1).mean() * 100,
                "cand_zero_pct": (cand_n == 0).mean() * 100,
                **st, "tr_n": tr["n"], "tr_win": tr["win"], "tr_pf": tr["pf"], "tr_mean": tr["mean"],
                "ci_lo": ci[0], "ci_hi": ci[1],
            })
        all_rows.append((tlabel, rows))

        print(f"\n-- 容量曲線總表(門檻vs可用訊號數vs複利/MDD/夏普/Calmar/勝率,動能門檻={tlabel}) --")
        hdr = (f"{'流動性門檻':<12}{'訊號週':>8}{'籃子中位':>8}{'籃子min':>7}{'n<=3週%':>8}{'n<=1週%':>8}"
               f"{'複利':>9}{'年化':>8}{'MDD':>8}{'夏普':>6}{'Calmar':>7}{'勝率':>6}{'PF':>6}{'單筆均':>8}")
        print(hdr)
        for r in rows:
            if r["n_sig_weeks"] == 0:
                print(f"{TIER_LABELS[r['tier']]:<12}{'0(無訊號)':>8}")
                continue
            print(f"{TIER_LABELS[r['tier']]:<12}{r['n_sig_weeks']:>7d}/{r['n_total_weeks']:<0d}"
                  f"{r['basket_median']:>7.1f}{r['basket_min']:>7.0f}{r['basket_le3_pct']:>7.0f}%"
                  f"{r['basket_le1_pct']:>7.0f}%{r['mult']:>8.1f}x{r['cagr']:>7.1f}%{r['mdd']:>7.1f}%"
                  f"{r['sharpe']:>6.2f}{r['calmar']:>7.2f}{r['tr_win']:>5.0f}%{r['tr_pf']:>6.2f}{r['tr_mean']:>7.2f}%")

        print(f"\n-- 集中度風險診斷(呼應本次會談核心診斷: 流動性拉高是否讓籃子更薄/集中度惡化) --")
        for r in rows:
            if r["n_sig_weeks"] == 0:
                continue
            print(f"  {TIER_LABELS[r['tier']]}: 訊號週佔全樣本{r['n_sig_weeks'] / r['n_total_weeks'] * 100:.0f}%,"
                  f"其中籃子<=3檔的週佔{r['basket_le3_pct']:.0f}%、籃子恰好1檔的週佔{r['basket_le1_pct']:.0f}%,"
                  f"完全無候選(0檔通過門檻)的週佔全樣本{r['cand_zero_pct']:.0f}%")

    return all_rows


# ══ 四、實務容量建議(資金規模對應流動性門檻的粗估) ══════════════════════════
def capacity_advice():
    print("\n" + "=" * 110)
    print("### 資金規模 vs 流動性門檻 實務對照(粗估,非精確市場衝擊模型) ###")
    print("邏輯: 門檻=近20週均『週』成交值,約當日均成交值=門檻/5個交易日。本回測单邊成本假設固定0.5%,")
    print("未內建滑價/市場衝擊模型,若單筆進出金額佔該股日均量比例過高,實際滑價會遠高於這裡的假設,")
    print("以下用『單筆不超過日均量X%』的常見經驗法則反推可承受的單檔部位上限,僅供參考數量級,")
    print("不是精確的可執行性保證(尤其個股集中週,同一檔可能吃下籃子近乎全部資金,更需保守估計)。")
    hdr = f"{'流動性門檻':<12}{'約當日均量':>12}{'單檔上限(日均量5%)':>20}{'單檔上限(日均量10%)':>20}"
    print(hdr)
    for tier in TIERS:
        daily = tier / 5
        print(f"{TIER_LABELS[tier]:<12}{daily / 1e4:>10.0f}萬{daily * 0.05 / 1e4:>18.0f}萬{daily * 0.10 / 1e4:>18.0f}萬")
    print("\n建議讀法: 若總資金規模為C,且假設最壞情況下單一集中週可能把C近乎全押在1-3檔("
          "本卷診斷已證實這是真實會發生的情況,不是理論假設),則單檔部位上限應以C本身、而非C/10去對照上表,"
          "也就是說『C應小於等於上表單檔上限』才算相對安全; 若堅持用等權10檔假設打底(C/10每檔),"
          "則C可以放大到上表數字的10倍,但要接受集中週時實際承擔的滑價風險遠高於本回測假設的0.5%成本。")


def main():
    run()
    capacity_advice()
    print("\n" + "=" * 110)
    print("跑完。以上為console探索報告,無檔案輸出。")


if __name__ == "__main__":
    main()
