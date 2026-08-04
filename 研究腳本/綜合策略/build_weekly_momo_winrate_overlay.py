# -*- coding: utf-8 -*-
"""週級強者續強×自身滾動勝率水位疊加測試(2026-08-04,使用者:「觀察自己策略的勝率,是否也是一個辦法,
如果近期勝率逐步提升,代表行情很好,但逐步下降就該降低水位」)。

背景: `build_weekly_momo_regime_overlay.py`已測過大盤級regime(MA240趨勢/恐慌溫度計/長假前/融資維持率等)
全部失敗——核心診斷是基準版最差15週中0週在空頭regime觸發、僅3週在高波regime觸發,MDD元凶是「個股集中度
風險」(訊號週籃子只有1-3檔),不是大盤系統性風險,大盤級regime分類器天生偵測不到。本卷改用「策略自身」
層級的內生訊號: 拿策略最近N筆交易(或N個有觸發訊號的週)的勝率/均報酬當水位指標,勝率夠高才正常水位,
勝率偏低就減碼或空手。

零前視口徑: 任一entry週wk的訊號值,只使用「exit_week<=wk」的已實現交易(inclusive——這是「先結算本週到期
的舊倉位,再決定本週新倉位要不要進場」的自然執行順序,兩個動作用的是同一個週五收盤價,並不偷看未來;
更保守的exit_week<wk版本會使訊號更落後,不是本卷重點但方法論風險段有量化討論)。

**方法論風險(本卷刻意主動檢查,不是使用者要求才做)**:
①天生落後性: 用自身近期勝率當訊號,本質上要「已經虧了幾筆」才會知道要降水位——crash深挖段落逐週印出
  訊號值+基準報酬,具體算出訊號觸發前基準策略已經吃了多少%跌幅。
②窗口穩健性: 交易筆數窗口測10/20/30筆,活躍週窗口測4/8/12週,兩種操作化各自内部比較+互相比較,只有
  單一窗口有效就是過擬合警訊。
③同資料用兩次: 訊號本身是用策略自己的歷史報酬產生、又用來預測自己的未來報酬,理論上有自相關風險。
  除了沿用M模組的月群集群bootstrap CI外,本卷加做「case-control隨機安慰劑」——固定「關閉/減碼週數」
  跟真實規則相同,但改成隨機挑選要關閉的週(而非依勝率訊號挑),重複1000次建立分布,檢查真實規則的
  MDD/複利落在隨機分布的第幾百分位——如果贏不過隨機基準,代表訊號沒有真的提供資訊,只是「減少曝險
  本身」這個機械效果(任何隨機拿掉幾週都會讓MDD好看一些)。

實作: sys.path插入`研究腳本/綜合策略`後import build_weekly_momo_regime_overlay複用面板/交易建置/組合曲線/
統計函式(M.build_trades/M.portfolio_curve/M.stats_from_ret/M.trade_stats/M.bootstrap_ci)。20%門檻為主
(完整分析: 主表+門檻敏感度+均報酬版+三態加碼版+case-control安慰劑+崩盤深挖),15%門檻當精簡敏感度對照
(只跑主表+崩盤深挖)。

用法: python 研究腳本/綜合策略/build_weekly_momo_winrate_overlay.py (從根目錄執行,鐵律)
產出: 純console報告,無檔案輸出。
"""
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "研究腳本/綜合策略")
import build_weekly_momo_regime_overlay as M  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

WIN_LO = 0.40          # 主要「勝率偏低」門檻(基準單筆勝率~48%,週級勝率~57%,40%已明顯低於兩者)
WIN_HI = 0.55          # 三態加碼版用的「勝率偏高」門檻
TRADE_WINDOWS = [10, 20, 30]
WEEK_WINDOWS = [4, 8, 12]
N_PLACEBO = 1000
CRASH_WINDOWS = [("2025-04關稅崩盤", "2025-03-01", "2025-05-01"),
                  ("2026-07-24修正", "2026-06-01", "2026-08-04")]


# ══ 一、滾動訊號建置(零前視) ══════════════════════════════════
def build_rolling_trade_window(trades, n):
    """trailing N筆已實現交易(依exit_week排序,同週內按build_trades原順序)的win rate/mean ret,
    回傳index=exit_week、每個exit_week對應「該週所有交易結算後」的滾動值(該週最後一筆trade的位置)"""
    t = trades.sort_values(["exit_week"], kind="stable").reset_index(drop=True)
    win = t["net_ret"].gt(0).rolling(n, min_periods=n).mean()
    mean = t["net_ret"].rolling(n, min_periods=n).mean()
    t = t.assign(roll_win=win.values, roll_mean=mean.values)
    last = t.groupby("exit_week", sort=True).tail(1)[["exit_week", "roll_win", "roll_mean"]]
    return last.set_index("exit_week").sort_index()


def build_rolling_week_window(baskets, n):
    """trailing N個「有觸發訊號」週的portfolio週報酬(等權,同baseline口徑)win rate/mean ret,index=exit_week"""
    wk_ret = pd.Series({b["exit_week"].iloc[0]: float(b["net_ret"].mean())
                        for b in baskets.values()}).sort_index()
    win = wk_ret.gt(0).rolling(n, min_periods=n).mean()
    mean = wk_ret.rolling(n, min_periods=n).mean()
    return pd.DataFrame({"roll_win": win, "roll_mean": mean})


def make_aligned(signal_df, grid):
    """把exit_week索引的訊號值ffill對齊到完整entry週grid——reindex+ffill天生就是
    「entry週wk只看得到exit_week<=wk的已實現交易」的asof語意,零前視"""
    return signal_df.reindex(grid, method="ffill")


def make_fav(aligned, win_lo, use_col="roll_win", cmp="ge"):
    """訊號值<門檻(或mean<0)=不利;warmup期(NaN,還沒累積滿N筆/N週)一律視為有利(不減碼)"""
    def fav(entry_week):
        v = aligned[use_col].get(entry_week, np.nan)
        if pd.isna(v):
            return True
        return (v >= win_lo) if cmp == "ge" else (v > win_lo)
    return fav


def tristate_curve(baskets, grid, aligned, win_lo, win_hi, boost, cut, use_col="roll_win"):
    """三態版: 勝率<win_lo減碼cut倍、>=win_hi加碼boost倍、warmup或介於中間維持正常1.0倍(M.portfolio_curve
    只支援二態,這裡另寫一個輕量版本,邏輯/欄位口徑與M.portfolio_curve一致方便直接餵M.stats_from_ret等函式)"""
    ret = pd.Series(0.0, index=grid)
    exec_list = []
    for wk, basket in baskets.items():
        exit_wk = basket["exit_week"].iloc[0]
        if exit_wk not in ret.index:
            continue
        v = aligned[use_col].get(wk, np.nan)
        if pd.isna(v):
            w, state = 1.0, "warmup"
        elif v < win_lo:
            w, state = cut, "cut"
        elif v >= win_hi:
            w, state = boost, "boost"
        else:
            w, state = 1.0, "normal"
        pr = float(basket["net_ret"].mean()) * w
        ret.loc[exit_wk] = pr
        exec_list.append(basket.assign(weight=w, state=state))
    exec_trades = pd.concat(exec_list, ignore_index=True)
    return ret, exec_trades


# ══ 二、case-control隨機安慰劑(同資料用兩次的檢查) ══════════════════
def precompute_rows(baskets, grid):
    grid_pos = {d: i for i, d in enumerate(grid)}
    wk_keys, gi, mr = [], [], []
    for wk, basket in baskets.items():
        exit_wk = basket["exit_week"].iloc[0]
        if exit_wk not in grid_pos:
            continue
        wk_keys.append(wk)
        gi.append(grid_pos[exit_wk])
        mr.append(float(basket["net_ret"].mean()))
    return wk_keys, np.array(gi), np.array(mr)


def placebo_test(baskets, grid, n_off, mode, reduce_frac=0.5, n_sims=N_PLACEBO, seed=99):
    """固定「關閉/減碼週數」=n_off,但改成隨機挑週(而非依勝率訊號),重複n_sims次建立MDD/複利分布"""
    wk_keys, gi, mr = precompute_rows(baskets, grid)
    n = len(wk_keys)
    rng = np.random.default_rng(seed)
    out = np.empty((n_sims, 3))  # mult, mdd, sharpe
    for b in range(n_sims):
        w = np.ones(n)
        if n_off > 0:
            off_idx = rng.choice(n, size=min(n_off, n), replace=False)
            w[off_idx] = 0.0 if mode == "switch" else reduce_frac
        ret = np.zeros(len(grid))
        ret[gi] = mr * w
        st = M.stats_from_ret(pd.Series(ret, index=grid))
        out[b] = (st["mult"], st["mdd"], st["sharpe"])
    return pd.DataFrame(out, columns=["mult", "mdd", "sharpe"])


def percentile_of(actual, dist, higher_is_better=True):
    """actual在dist分布中打敗了幾%(higher_is_better=False用於MDD,越不負越好即越大越好,
    這裡MDD本身是負值,「越大(越接近0)」代表風險越小,所以MDD也是higher_is_better=True的邏輯"""
    return float((dist <= actual).mean() * 100) if higher_is_better else float((dist >= actual).mean() * 100)


# ══ 三、崩盤深挖(訊號觸發時傷害是否已發生大半) ══════════════════
def crash_lag_report(variant_name, aligned, win_lo, baskets, grid, ret_base, use_col="roll_win"):
    entry_of_exit = {b["exit_week"].iloc[0]: wk for wk, b in baskets.items()}
    for label, s, e in CRASH_WINDOWS:
        s_ext = pd.Timestamp(s) - pd.Timedelta(weeks=8)
        e_ts = pd.Timestamp(e)
        wks_in_range = [w for w in grid if s_ext <= w <= e_ts]
        print(f"\n  --- {variant_name} × {label}(往前多印8週看訊號走勢) ---")
        rows = []
        for wk in wks_in_range:
            basket = baskets.get(wk)
            n = len(basket) if basket is not None else 0
            v = aligned[use_col].get(wk, np.nan)
            fav = True if pd.isna(v) else (v >= win_lo)
            exit_wk = weeks_next(grid, wk)
            base_ret = ret_base.get(exit_wk, np.nan) if exit_wk is not None else np.nan
            rows.append((wk, exit_wk, n, v, fav, base_ret, wk >= pd.Timestamp(s)))
        for wk, exit_wk, n, v, fav, base_ret, in_official in rows:
            sig_txt = f"{v * 100:.0f}%" if pd.notna(v) else "warmup"
            mark = "*" if in_official else " "
            br_txt = f"{base_ret * 100:+.1f}%" if pd.notna(base_ret) else "  n/a"
            print(f"   {mark}entry{wk.date()} n={n:>2} 滾動勝率={sig_txt:>7} "
                  f"{'不利(降水位)' if not fav else '正常  ':<10} 基準當週報酬={br_txt}")
        # 官方窗口內(標*)的損失切分: 訊號首次轉不利之前 vs 之後
        official_rows = [r for r in rows if r[6]]
        base_seq = [r[5] for r in official_rows if pd.notna(r[5])]
        cum_total = float(np.prod([1 + x for x in base_seq]) - 1) if base_seq else np.nan
        first_off = next((r[0] for r in official_rows if not r[4]), None)
        if first_off is not None:
            idx = [r[0] for r in official_rows].index(first_off)
            pre = [r[5] for r in official_rows[:idx] if pd.notna(r[5])]
            cum_pre = float(np.prod([1 + x for x in pre]) - 1) if pre else 0.0
            pct = (cum_pre / cum_total * 100) if cum_total not in (0, np.nan) and not np.isnan(cum_total) else np.nan
            print(f"   => 官方窗口內訊號首次轉'不利'於entry {first_off.date()};在此之前基準策略已累計"
                  f"{cum_pre * 100:+.1f}%,佔官方窗口總累計{cum_total * 100:+.1f}%的{pct:.0f}%")
        else:
            print(f"   => 官方窗口內訊號從未轉為'不利',完全沒有預警(官方窗口基準累計報酬{cum_total * 100:+.1f}%)")

        # 直接檢查: 窗口內最慘的3週(單週基準報酬最負),訊號到底有沒有真的保護到——比「首次轉不利」更貼近
        # 使用者原問法「成功避開重挫的機率有多高」,因為訊號可能中途又跳回'正常'而漏接後面更慘的週
        worst3 = sorted((r for r in official_rows if pd.notna(r[5])), key=lambda r: r[5])[:3]
        n_protected = sum(1 for r in worst3 if not r[4])
        avoided = sum(-r[5] for r in worst3 if not r[4])
        missed = sum(-r[5] for r in worst3 if r[4])
        print(f"   => 窗口內最慘3週逐一檢查:")
        for r in worst3:
            wk, exit_wk, n, v, fav, base_ret, _ = r
            status = "有被保護(開關版=當週直接不進場)" if not fav else "沒被保護(全額承受這週虧損)"
            print(f"        entry{wk.date()} 基準報酬{base_ret * 100:+.1f}% → {status}")
        print(f"   => 最慘3週中{n_protected}/3被保護到;若全被保護理論上可避開{avoided * 100:.1f}pp跌幅,"
              f"實際仍全額承受了{missed * 100:.1f}pp(來自沒被保護到的最慘週)")


def weeks_next(grid, wk):
    pos = grid.searchsorted(wk)
    if pos + 1 < len(grid) and grid[pos] == wk:
        return grid[pos + 1]
    return None


# ══ 四、主流程 ══════════════════════════════════════════
def run_winrate_overlay(threshold, label, full=True):
    print("\n" + "=" * 100)
    print(f"### 週級動能×自身滾動勝率水位  門檻={label} top{M.TOP_N} ###")
    trades, baskets = M.build_trades(threshold)
    weeks = M.WIDE_RET.index
    start_i = weeks.searchsorted(pd.Timestamp(M.START))
    grid = weeks[start_i:]
    print(f"n_trades={len(trades)}  n_signal_weeks={len(baskets)}/{len(grid)}")

    ret_base, exec_base = M.portfolio_curve(baskets, grid, mode="baseline", weighting="equal")
    st_base = M.stats_from_ret(ret_base)
    tr_base = M.trade_stats(exec_base)
    ci_base = M.bootstrap_ci(exec_base)
    print(f"基準(無疊加): 複利{st_base['mult']:.1f}x 年化{st_base['cagr']:+.1f}% MDD{st_base['mdd']:.1f}% "
          f"夏普{st_base['sharpe']:.2f} 單筆勝率{tr_base['win']:.1f}% 週級勝率"
          f"{float((pd.Series({b['exit_week'].iloc[0]: float(b['net_ret'].mean()) for b in baskets.values()}) > 0).mean() * 100):.1f}%")

    # -- 建置所有滾動訊號 --
    trade_signals = {n: build_rolling_trade_window(trades, n) for n in TRADE_WINDOWS}
    week_signals = {n: build_rolling_week_window(baskets, n) for n in WEEK_WINDOWS}
    aligned_trade = {n: make_aligned(s, grid) for n, s in trade_signals.items()}
    aligned_week = {n: make_aligned(s, grid) for n, s in week_signals.items()}
    for n, s in trade_signals.items():
        print(f"  交易筆數窗N={n}: 首個有效訊號位於exit_week={s['roll_win'].dropna().index.min().date()}"
              f"(warmup期共{s['roll_win'].isna().sum()}筆交易)")
    for n, s in week_signals.items():
        print(f"  活躍週窗N={n}: 首個有效訊號位於exit_week={s['roll_win'].dropna().index.min().date()}"
              f"(warmup期共{s['roll_win'].isna().sum()}個訊號週)")

    # -- 主比較表 --
    rows = []

    def add_row(name, ret, ex, ci=None):
        st = M.stats_from_ret(ret)
        tr = M.trade_stats(ex)
        ci = ci if ci is not None else M.bootstrap_ci(ex)
        rows.append({"variant": name, **st, **{f"tr_{k}": v for k, v in tr.items()},
                     "ci_lo": ci[0], "ci_hi": ci[1],
                     "exposure": st["n_weeks_active"] / st["n_weeks_total"] * 100,
                     "dd_peak": st["dd_peak"], "dd_trough": st["dd_trough"]})

    add_row("基準(無疊加)", ret_base, exec_base, ci_base)

    variant_defs = {}  # name -> (aligned, mode)
    for n in TRADE_WINDOWS:
        fav = make_fav(aligned_trade[n], WIN_LO)
        variant_defs[f"交易窗N={n}·開關版"] = (fav, "switch")
        variant_defs[f"交易窗N={n}·減碼50%版"] = (fav, "reduce_capital")
    for n in WEEK_WINDOWS:
        fav = make_fav(aligned_week[n], WIN_LO)
        variant_defs[f"活躍週窗N={n}·開關版"] = (fav, "switch")
        variant_defs[f"活躍週窗N={n}·減碼50%版"] = (fav, "reduce_capital")

    variant_cache = {}
    for name, (fav, mode) in variant_defs.items():
        r, ex = M.portfolio_curve(baskets, grid, favorable_fn=fav, mode=mode, weighting="equal")
        add_row(name, r, ex)
        variant_cache[name] = (r, ex)

    print(f"\n-- 基準 vs 滾動勝率水位控倉版 全比較表(win_lo={WIN_LO*100:.0f}%,等權口徑) --")
    hdr = (f"{'版本':<26}{'複利':>8}{'年化':>8}{'MDD':>8}{'夏普':>6}{'報酬/MDD':>9}"
           f"{'PF':>6}{'勝率':>6}{'單筆均':>8}{'CI':>20}{'曝險':>6}")
    print(hdr)
    for row in rows:
        ci_txt = f"[{row['ci_lo']:+.2f}%,{row['ci_hi']:+.2f}%]"
        print(f"{row['variant']:<26}{row['mult']:>7.1f}x{row['cagr']:>7.1f}%{row['mdd']:>7.1f}%"
              f"{row['sharpe']:>6.2f}{row['calmar']:>9.2f}{row['tr_pf']:>6.2f}{row['tr_win']:>5.0f}%"
              f"{row['tr_mean']:>7.2f}%{ci_txt:>20}{row['exposure']:>5.0f}%")

    print("\n-- MDD區間診斷(全域最大回撤發生在哪個episode?——藏在2015年集中度風險期還是2025/2026真實crash期,\n"
          "   直接影響「這個變體的MDD改善/未改善」該歸功/歸咎於哪個事件,務必對照才能誠實解讀) --")
    for row in rows:
        in_2025 = pd.Timestamp("2025-01-01") <= row["dd_trough"] <= pd.Timestamp("2025-12-31")
        in_2026 = pd.Timestamp("2026-01-01") <= row["dd_trough"]
        tag = "2025年" if in_2025 else ("2026年" if in_2026 else "非2025/2026(多半是2015年集中度事件)")
        print(f"  {row['variant']:<26} MDD episode={row['dd_peak'].date()}~{row['dd_trough'].date()}  [{tag}]")

    if not full:
        # 15%門檻精簡版: 主表跑完後只做崩盤深挖(用交易窗N=20開關版當代表)即結束
        fav20 = make_fav(aligned_trade[20], WIN_LO)
        crash_lag_report("交易窗N=20·開關版", aligned_trade[20], WIN_LO, baskets, grid, ret_base)
        return rows

    # -- 門檻敏感度(win_lo=35%/45%,只跑開關版) --
    print(f"\n-- 門檻敏感度(win_lo=35% vs 40%(主表已有) vs 45%,開關版,只看MDD/複利/夏普/曝險判斷是否只有\n"
          f"   單一門檻+單一窗口才有效——若35/40/45三者方向不一致或忽好忽壞,是過擬合警訊) --")
    sens_rows = []
    for wlo in (0.35, 0.45):
        for n in TRADE_WINDOWS:
            fav = make_fav(aligned_trade[n], wlo)
            r, ex = M.portfolio_curve(baskets, grid, favorable_fn=fav, mode="switch", weighting="equal")
            st = M.stats_from_ret(r)
            sens_rows.append({"win_lo": wlo, "win_type": f"交易窗N={n}", "mult": st["mult"],
                               "mdd": st["mdd"], "sharpe": st["sharpe"], "exposure":
                               st["n_weeks_active"] / st["n_weeks_total"] * 100})
        for n in WEEK_WINDOWS:
            fav = make_fav(aligned_week[n], wlo)
            r, ex = M.portfolio_curve(baskets, grid, favorable_fn=fav, mode="switch", weighting="equal")
            st = M.stats_from_ret(r)
            sens_rows.append({"win_lo": wlo, "win_type": f"活躍週窗N={n}", "mult": st["mult"],
                               "mdd": st["mdd"], "sharpe": st["sharpe"], "exposure":
                               st["n_weeks_active"] / st["n_weeks_total"] * 100})
    print(f"{'win_lo':>8}{'窗口':<16}{'複利':>8}{'MDD':>8}{'夏普':>6}{'曝險':>6}")
    for r in sens_rows:
        print(f"{r['win_lo']*100:>7.0f}%{r['win_type']:<16}{r['mult']:>7.1f}x{r['mdd']:>7.1f}%"
              f"{r['sharpe']:>6.2f}{r['exposure']:>5.0f}%")

    # -- 均報酬版(roll_mean<0代替roll_win<40%,呼應使用者原話「勝率(或均報酬)」) --
    print("\n-- 均報酬版訊號(roll_mean<0%觸發降水位,而非win_rate<40%,兩種操作化互相對照) --")
    for n, aligned in ((20, aligned_trade[20]), (8, aligned_week[8])):
        fav = make_fav(aligned, 0.0, use_col="roll_mean", cmp="gt")
        r_sw, ex_sw = M.portfolio_curve(baskets, grid, favorable_fn=fav, mode="switch", weighting="equal")
        st = M.stats_from_ret(r_sw)
        wtype = "交易窗" if n == 20 and aligned is aligned_trade[20] else "活躍週窗"
        print(f"  {wtype}N={n}·均報酬<0開關版: 複利{st['mult']:.1f}x MDD{st['mdd']:.1f}% 夏普{st['sharpe']:.2f} "
              f"曝險{st['n_weeks_active'] / st['n_weeks_total'] * 100:.0f}%")

    # -- 三態版(低減碼/中正常/高加碼,呼應使用者原話「勝率提升甚至加碼」) --
    print(f"\n-- 三態版(<{WIN_LO*100:.0f}%減碼50% / {WIN_LO*100:.0f}~{WIN_HI*100:.0f}%正常1.0x / "
          f">={WIN_HI*100:.0f}%加碼1.3x) --")
    for n, aligned, wtype in ((20, aligned_trade[20], "交易窗"), (8, aligned_week[8], "活躍週窗")):
        r_tri, ex_tri = tristate_curve(baskets, grid, aligned, WIN_LO, WIN_HI, boost=1.3, cut=0.5)
        st = M.stats_from_ret(r_tri)
        tr = M.trade_stats(ex_tri)
        state_counts = ex_tri["state"].value_counts()
        print(f"  {wtype}N={n}·三態版: 複利{st['mult']:.1f}x MDD{st['mdd']:.1f}% 夏普{st['sharpe']:.2f} "
              f"單筆勝率{tr['win']:.1f}%  狀態分布(筆數)={state_counts.to_dict()}")

    # -- case-control隨機安慰劑(挑MDD改善最明顯的2個開關版變體驗證) --
    print(f"\n-- case-control隨機安慰劑(固定關閉週數=真實規則,但改隨機挑週,重複{N_PLACEBO}次;"
          f"看真實規則的MDD/複利打敗了隨機分布幾%——只有顯著贏過隨機基準,才代表訊號真的有資訊量,\n"
          f"   不是「拿掉任意幾週都會讓MDD好看」的機械效果) --")
    switch_rows = [r for r in rows if "開關版" in r["variant"]]
    switch_rows_sorted = sorted(switch_rows, key=lambda r: r["mdd"], reverse=True)  # mdd越大(越不負)排前面
    flagship = switch_rows_sorted[:2]
    for row in flagship:
        name = row["variant"]
        r_real, ex_real = variant_cache[name]
        n_off = len(baskets) - ex_real["entry_week"].nunique()  # 週數(非筆數)差=被關掉的週數
        dist = placebo_test(baskets, grid, n_off, mode="switch")
        pct_mdd = percentile_of(row["mdd"], dist["mdd"].values, higher_is_better=True)
        pct_mult = percentile_of(row["mult"], dist["mult"].values, higher_is_better=True)
        print(f"  {name}(關閉{n_off}/{len(baskets)}週,佔{n_off/len(baskets)*100:.0f}%): "
              f"真實MDD{row['mdd']:.1f}% 打敗隨機安慰劑分布的{pct_mdd:.0f}%百分位(隨機分布MDD"
              f"中位數={dist['mdd'].median():.1f}%,[{dist['mdd'].quantile(.05):.1f}%,"
              f"{dist['mdd'].quantile(.95):.1f}%]);真實複利{row['mult']:.1f}x打敗隨機分布"
              f"{pct_mult:.0f}%百分位(隨機中位數{dist['mult'].median():.1f}x)")

    # -- 崩盤深挖(用兩個旗艦變體: 表現最好的交易窗+活躍週窗開關版) --
    print("\n" + "-" * 100)
    print("### 崩盤深挖: 訊號觸發時傷害是否已發生大半(方法論風險①落後性量化) ###")
    trade_flag = next((r["variant"] for r in switch_rows_sorted if "交易窗" in r["variant"]), None)
    week_flag = next((r["variant"] for r in switch_rows_sorted if "活躍週窗" in r["variant"]), None)
    for name in (trade_flag, week_flag):
        if name is None:
            continue
        n_win = int(name.split("N=")[1].split("·")[0])
        aligned = aligned_trade[n_win] if "交易窗" in name else aligned_week[n_win]
        crash_lag_report(name, aligned, WIN_LO, baskets, grid, ret_base)

    return rows


def main():
    run_winrate_overlay(0.20, "20%", full=True)
    run_winrate_overlay(0.15, "15%", full=False)
    print("\n" + "=" * 100)
    print("跑完。以上為console探索報告,無檔案輸出。")


if __name__ == "__main__":
    main()
