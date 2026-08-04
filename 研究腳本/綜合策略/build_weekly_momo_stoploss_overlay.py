# -*- coding: utf-8 -*-
"""週級強者續強×籃子內個股週中各自停損測試(2026-08-04,使用者:「持有一週不一定要全部都持有到結束,如果
某一檔表現太差也能停損,其他股票就繼續持有」)。

背景: 目前策略設計是進場後固定持有到下週收盤,完全不管中途漲跌。`build_weekly_momo_regime_overlay.py`已
證實MDD的元凶是「個股集中度風險」(訊號週籃子只有1-3檔),大盤級regime開關全部失敗。本卷改成籃子內
「每一檔個股各自監控」——若某檔股票在持有期間(進場後次一交易日到下週五共約5個交易日)任何一天的盤中
或收盤跌幅觸及停損門檻,就在觸發當天(或次一交易日開盤)出場,該基金位置的資金騰出來(視為現金,不
重新投入),但不影響同一籃子裡其他股票(其他股票繼續照原計畫抱到週五)。

零前視/資料清洗: 從capital_flow.db.fm_daily_price撈「進場後次一交易日~下週五」逐日OHLC(不是週線面板,
另外撈日頻),比照M模組同樣的close>0/money>0清洗,額外要求low>0(此三個條件同時成立時,實測close>0&
money>0已隱含low>0,只有open偶爾單獨=0,已個別guard)。週標籤(W-FRI Friday label)可能不是真交易日(遇假
日),用『市場層級當週最後交易日』(dpx.groupby('wk').date.max(),與M模組weekly panel同一套groupby-last
邏輯)換算成真實日期,再用該真實日期界定「entry實際日<日期<=exit實際日」的持有窗,避免與週線面板的
「Friday標籤未必是真交易日」產生零星錯位。

技術口徑(兩個維度各測,4×2=8+4個next_open組合):
  觸發判定(trigger_mode): close=用當日收盤價跌幅判斷 / intraday_low=用當日盤中最低價跌幅判斷(較敏感,
                          intraday_low永遠 >= close觸發頻率,因為low<=close當日恆成立)
  出場價(exit_mode): same_close=觸發當天收盤價出場(同一天結算,使用者原話口徑) /
                     next_open=次一交易日開盤出場(更保守但更可執行;若觸發日已是資料查詢範圍內最後一天,
                     往後最多搜MAX_OPEN_SEARCH個交易日找有效open,找不到才退回same_close當備援)
  停損門檻(threshold): -5%/-8%/-10%/-15%,對entry_price(=進場週收盤)的累積跌幅

成本說明: 原策略COST=0.5%單邊扣一次(非來回各0.5%),涵蓋1次進場+1次出場。停損只是改變「出場的時間點/
價格」,並沒有讓交易次數變成2次(沒有停損就不交易,有停損也還是恰好1次進場+1次出場)——所以嚴格說在這個
「一週固定一輪、資金騰出後不重新部署」的設計下,停損不會疊加「額外一筆」交易成本,跟直覺(「每次停損等於
多一次進出場成本」)不同。但為了誠實回應這個疑慮,額外做一個「悲觀雙重成本」情境(對有觸發停損的交易
額外多扣一次COST),當作保守下界對照。

比較: ①原始無停損版(基準,直接沿用M.build_trades/M.portfolio_curve結果) ②close/same_close四門檻
③intraday_low/same_close四門檻(較敏感版對照) ④next_open出場版(2個代表門檻×2種觸發判定) ⑤悲觀雙重
成本版。MDD/複利/年化/夏普/Calmar/勝率/賺賠比/觸發率完整對照,並對2025-04/2026-07-24兩次真實重挫週
逐檔個股層級查驗(該週basket裡最慘的股票,停損有沒有真的接住)。

用法: python 研究腳本/綜合策略/build_weekly_momo_stoploss_overlay.py (從根目錄執行,鐵律)
產出: 純console報告,無檔案輸出(日頻查詢約10-20秒,全部門檻×模式組合跑完約1-2分鐘)
"""
import sys
import sqlite3

import numpy as np
import pandas as pd

sys.path.insert(0, "研究腳本/綜合策略")
import build_weekly_momo_regime_overlay as M  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

SL_THRESHOLDS = [-0.05, -0.08, -0.10, -0.15]
MAX_OPEN_SEARCH = 5
CRASH_WINDOWS = [("2025-04關稅崩盤", "2025-03-01", "2025-05-01"),
                  ("2026-07-24修正", "2026-06-01", "2026-08-04")]


# ══ 一、日頻資料建置(比照M模組資料清洗慣例) ══════════════════════════
def build_daily_panel(codes):
    con = sqlite3.connect(M.DB)
    q = (f"SELECT code,date,open,close,low,money FROM fm_daily_price "
         f"WHERE date>='{M.START}' AND code IN ({','.join('?' * len(codes))})")
    dpx = pd.read_sql(q, con, params=codes, parse_dates=["date"])
    con.close()
    n0 = len(dpx)
    dpx = dpx[(dpx["close"] > 0) & (dpx["money"] > 0) & (dpx["low"] > 0)]
    print(f"日頻資料清洗: 濾掉close<=0/money<=0/low<=0共{n0 - len(dpx)}列(佔{(n0 - len(dpx)) / n0 * 100:.2f}%)"
          f",最終{len(dpx)}列,涵蓋{dpx['code'].nunique()}檔")
    dpx = dpx.sort_values(["code", "date"]).reset_index(drop=True)
    dpx["wk"] = dpx["date"].dt.to_period("W-FRI").dt.end_time.dt.normalize()
    return dpx


def build_label_to_actual(dpx):
    """週期標籤(可能非真交易日)→ 該週最後一個真實交易日(market-wide,同M模組weekly panel的groupby-last邏輯)"""
    return dpx.groupby("wk")["date"].max()


def build_code_daily_index(dpx):
    """code -> 該股所有交易日(date/open/close/low) ndarray,依date排序"""
    out = {}
    for code, g in dpx.groupby("code", sort=False):
        g = g.sort_values("date")
        out[code] = {"date": g["date"].values, "open": g["open"].values.astype(float),
                     "close": g["close"].values.astype(float), "low": g["low"].values.astype(float)}
    return out


# ══ 二、逐筆停損模擬 ══════════════════════════════════════════
def simulate_stoploss(trades, code_daily, label_to_actual, sl, trigger_mode="close", exit_mode="same_close"):
    out = trades.copy().reset_index(drop=True)
    n = len(out)
    net_sl = np.empty(n)
    triggered = np.zeros(n, dtype=bool)
    trig_dow = np.full(n, -1)
    fallback_cnt = 0
    codes = out["code"].values
    entry_weeks = out["entry_week"].values
    exit_weeks = out["exit_week"].values
    for i in range(n):
        code = codes[i]
        entry_wk = pd.Timestamp(entry_weeks[i])
        exit_wk = pd.Timestamp(exit_weeks[i])
        entry_price = M.WIDE_C.at[entry_wk, code] if code in M.WIDE_C.columns else np.nan
        cd = code_daily.get(code)
        entry_actual = label_to_actual.get(entry_wk)
        exit_actual = label_to_actual.get(exit_wk)
        if cd is None or pd.isna(entry_price) or entry_actual is None or exit_actual is None:
            net_sl[i] = out.at[i, "net_ret"]
            continue
        dates = cd["date"]
        lo = np.searchsorted(dates, np.datetime64(entry_actual), side="right")
        hi = np.searchsorted(dates, np.datetime64(exit_actual), side="right")
        if lo >= hi:
            net_sl[i] = out.at[i, "net_ret"]
            continue
        exit_price = None
        for j in range(lo, hi):
            c, l = cd["close"][j], cd["low"][j]
            chk = c if trigger_mode == "close" else l
            if chk <= 0:
                continue
            r = chk / entry_price - 1
            if r <= sl:
                triggered[i] = True
                trig_dow[i] = pd.Timestamp(dates[j]).isoweekday()
                if exit_mode == "same_close":
                    exit_price = c
                else:
                    ep = None
                    for k in range(j + 1, min(j + 1 + MAX_OPEN_SEARCH, len(dates))):
                        if cd["open"][k] > 0:
                            ep = cd["open"][k]
                            break
                    if ep is None:
                        ep = c
                        fallback_cnt += 1
                    exit_price = ep
                break
        if exit_price is None:
            net_sl[i] = out.at[i, "net_ret"]
        else:
            net_sl[i] = exit_price / entry_price - 1 - M.COST
    out["net_ret_sl"] = net_sl
    out["triggered"] = triggered
    out["trig_dow"] = trig_dow
    return out, fallback_cnt


def rebuild_baskets(baskets, enriched, ret_col="net_ret_sl"):
    grouped = {wk: g for wk, g in enriched.groupby("entry_week")}
    new_baskets = {}
    for wk, basket in baskets.items():
        g = grouped.get(wk)
        if g is None:
            continue
        b2 = basket.copy()
        m = g.set_index("code")[ret_col]
        b2["net_ret"] = b2["code"].map(m).values
        new_baskets[wk] = b2
    return new_baskets


# ══ 三、崩盤週個股層級深挖 ══════════════════════════════════════
def find_worst_weeks_in_window(ret_base, baskets, s, e, top_k=2):
    entry_of_exit = {b["exit_week"].iloc[0]: wk for wk, b in baskets.items()}
    sub = ret_base.loc[s:e]
    worst = sub.sort_values().head(top_k)
    out = []
    for exit_wk, r in worst.items():
        entry_wk = entry_of_exit.get(exit_wk)
        if entry_wk is not None:
            out.append((entry_wk, exit_wk, float(r)))
    return out


def concentration_diagnostic(baskets, ret_base, enriched, label):
    """檢查停損的改善是不是廣泛分佈在「個股集中度風險」週(n<=3)——呼應本卷背景診斷(MDD元凶=個股集中度
    風險,大盤級regime開關偵測不到),而不是只靠單一離群週撐出來的假象"""
    rows = []
    for wk, basket in baskets.items():
        exit_wk = basket["exit_week"].iloc[0]
        base_ret = ret_base.get(exit_wk, np.nan)
        g = enriched[enriched["entry_week"] == wk]
        sl_ret = float(g["net_ret_sl"].mean()) if len(g) else np.nan
        rows.append((wk, len(basket), base_ret, sl_ret))
    df = pd.DataFrame(rows, columns=["entry_week", "n", "base_ret", "sl_ret"]).dropna()
    df["delta"] = df["sl_ret"] - df["base_ret"]
    concentrated = df[df["n"] <= 3]
    diversified = df[df["n"] > 3]
    print(f"  [{label}] 集中週(n<=3,共{len(concentrated)}週): 平均delta={concentrated['delta'].mean() * 100:+.3f}pp/週,"
          f"總計對複利貢獻的delta加總={concentrated['delta'].sum() * 100:+.1f}pp")
    print(f"  [{label}] 分散週(n>3,共{len(diversified)}週): 平均delta={diversified['delta'].mean() * 100:+.3f}pp/週,"
          f"總計={diversified['delta'].sum() * 100:+.1f}pp")
    top = df.sort_values("delta", ascending=False).head(5)
    print(f"  [{label}] 改善最多的5週(檢查是否只集中在單一離群週,還是廣泛分佈):")
    for _, r in top.iterrows():
        print(f"    entry{r['entry_week'].date()} n={int(r['n'])} base={r['base_ret'] * 100:+.1f}% "
              f"sl={r['sl_ret'] * 100:+.1f}% delta={r['delta'] * 100:+.2f}pp")
    n_top5_of_total = top["delta"].sum() / df[df["delta"] > 0]["delta"].sum() * 100 if df[df["delta"] > 0]["delta"].sum() > 0 else np.nan
    print(f"  [{label}] 前5大改善週佔全部正向delta總和的{n_top5_of_total:.0f}%(比例越高代表改善越依賴少數離群週,\n"
          f"   越不穩健;比例低代表改善廣泛分佈在許多集中度風險週,較符合本卷背景診斷的機制)")


def stock_deepdive(entry_wk, exit_wk, baseline_ret, baskets, enriched_by_sl, sl_list):
    basket = baskets[entry_wk]
    print(f"\n  entry{entry_wk.date()}→exit{exit_wk.date()} (n={len(basket)}, 基準週報酬={baseline_ret * 100:+.1f}%) "
          f"個股逐一檢查(*=該門檻有觸發停損):")
    hdr = f"    {'代號':<8}{'基準net_ret':>12}" + "".join(f"{'SL' + str(int(sl * 100)) + '%':>12}" for sl in sl_list)
    print(hdr)
    codes_sorted = basket.sort_values("net_ret")["code"].tolist()
    for code in codes_sorted:
        base_r = float(basket.loc[basket["code"] == code, "net_ret"].iloc[0])
        line = f"    {code:<8}{base_r * 100:>11.1f}%"
        for sl in sl_list:
            enr = enriched_by_sl[sl]
            row = enr[(enr["entry_week"] == entry_wk) & (enr["code"] == code)]
            if len(row):
                sl_r = float(row["net_ret_sl"].iloc[0])
                trig = bool(row["triggered"].iloc[0])
                mark = "*" if trig else " "
                line += f"{sl_r * 100:>10.1f}%{mark}"
            else:
                line += f"{'n/a':>12}"
        print(line)


# ══ 四、主流程 ══════════════════════════════════════════
def run_stoploss_overlay(threshold, label, code_daily, label_to_actual, full=True):
    print("\n" + "=" * 100)
    print(f"### 週級動能×籃子內個股週中停損  門檻={label} top{M.TOP_N} ###")
    trades, baskets = M.build_trades(threshold)
    weeks = M.WIDE_RET.index
    start_i = weeks.searchsorted(pd.Timestamp(M.START))
    grid = weeks[start_i:]

    ret_base, exec_base = M.portfolio_curve(baskets, grid, mode="baseline", weighting="equal")
    st_base = M.stats_from_ret(ret_base)
    tr_base = M.trade_stats(exec_base)
    ci_base = M.bootstrap_ci(exec_base)
    print(f"基準(無停損): 複利{st_base['mult']:.1f}x 年化{st_base['cagr']:+.1f}% MDD{st_base['mdd']:.1f}% "
          f"夏普{st_base['sharpe']:.2f} 賺賠比{tr_base['pf']:.2f} 勝率{tr_base['win']:.1f}% "
          f"MDD episode={st_base['dd_peak'].date()}~{st_base['dd_trough'].date()}")

    rows = []

    def add_row(name, ret, ex, ci=None, extra=""):
        st = M.stats_from_ret(ret)
        tr = M.trade_stats(ex)
        ci = ci if ci is not None else M.bootstrap_ci(ex)
        rows.append({"variant": name, **st, **{f"tr_{k}": v for k, v in tr.items()},
                     "ci_lo": ci[0], "ci_hi": ci[1], "extra": extra})

    add_row("基準(無停損)", ret_base, exec_base, ci_base)

    enriched_close = {}
    enriched_low = {}
    for sl in SL_THRESHOLDS:
        enr_c, _ = simulate_stoploss(trades, code_daily, label_to_actual, sl, "close", "same_close")
        enriched_close[sl] = enr_c
        bC = rebuild_baskets(baskets, enr_c)
        rC, exC = M.portfolio_curve(bC, grid, mode="baseline", weighting="equal")
        pct_trig = enr_c["triggered"].mean() * 100
        add_row(f"收盤觸發/同日出場 SL{sl * 100:.0f}%", rC, exC, extra=f"觸發率{pct_trig:.1f}%")

        enr_l, _ = simulate_stoploss(trades, code_daily, label_to_actual, sl, "intraday_low", "same_close")
        enriched_low[sl] = enr_l
        bL = rebuild_baskets(baskets, enr_l)
        rL, exL = M.portfolio_curve(bL, grid, mode="baseline", weighting="equal")
        pct_trig_l = enr_l["triggered"].mean() * 100
        add_row(f"盤中低點觸發/同日出場 SL{sl * 100:.0f}%", rL, exL, extra=f"觸發率{pct_trig_l:.1f}%")

    print(f"\n-- 基準 vs 個股停損版 全比較表(收盤觸發+盤中低點觸發兩種判定,同日收盤出場) --")
    hdr = (f"{'版本':<32}{'複利':>8}{'年化':>8}{'MDD':>8}{'夏普':>6}{'報酬/MDD':>9}"
           f"{'PF':>6}{'勝率':>6}{'單筆均':>8}{'CI':>20}{'觸發率':>10}")
    print(hdr)
    for row in rows:
        ci_txt = f"[{row['ci_lo']:+.2f}%,{row['ci_hi']:+.2f}%]"
        print(f"{row['variant']:<32}{row['mult']:>7.1f}x{row['cagr']:>7.1f}%{row['mdd']:>7.1f}%"
              f"{row['sharpe']:>6.2f}{row['calmar']:>9.2f}{row['tr_pf']:>6.2f}{row['tr_win']:>5.0f}%"
              f"{row['tr_mean']:>7.2f}%{ci_txt:>20}{row['extra']:>10}")

    print("\n-- MDD區間診斷 --")
    for row in rows:
        in_2025 = pd.Timestamp("2025-01-01") <= row["dd_trough"] <= pd.Timestamp("2025-12-31")
        in_2026 = pd.Timestamp("2026-01-01") <= row["dd_trough"]
        tag = "2025年" if in_2025 else ("2026年" if in_2026 else "非2025/2026")
        print(f"  {row['variant']:<32} MDD episode={row['dd_peak'].date()}~{row['dd_trough'].date()}  [{tag}]")

    print("\n-- 改善集中度診斷(收盤觸發SL-10%版為代表,檢查改善是否廣泛分佈在集中度風險週,還是靠單一離群週撐出來) --")
    concentration_diagnostic(baskets, ret_base, enriched_close[-0.10], "收盤觸發SL-10%")

    if not full:
        return rows, enriched_close, enriched_low, baskets, ret_base

    # -- next_open出場版(2個代表門檻×2種觸發判定,更保守/可執行的版本) --
    print("\n-- 次一交易日開盤出場版(更保守但更可執行,對照同日收盤出場版差多少) --")
    for sl in (-0.08, -0.10):
        for tmode, tname in (("close", "收盤觸發"), ("intraday_low", "盤中低點觸發")):
            enr, fb = simulate_stoploss(trades, code_daily, label_to_actual, sl, tmode, "next_open")
            b = rebuild_baskets(baskets, enr)
            r, ex = M.portfolio_curve(b, grid, mode="baseline", weighting="equal")
            st = M.stats_from_ret(r)
            tr = M.trade_stats(ex)
            pct_trig = enr["triggered"].mean() * 100
            print(f"  {tname}/次日開盤出場 SL{sl * 100:.0f}%: 複利{st['mult']:.1f}x MDD{st['mdd']:.1f}% "
                  f"夏普{st['sharpe']:.2f} PF{tr['pf']:.2f} 勝率{tr['win']:.1f}% 觸發率{pct_trig:.1f}% "
                  f"(開盤搜尋失敗退回收盤{fb}筆)")

    # -- 悲觀雙重成本情境(觸發停損的交易額外多扣一次COST,檢驗交易成本疊加侵蝕) --
    print(f"\n-- 悲觀雙重成本情境(有觸發停損的交易,額外再扣一次COST={M.COST * 100:.1f}%,模擬「停損=多一次進出場」\n"
          f"   的保守假設下界——注意本卷主口徑認為這不成立,見檔頭成本說明,這裡只當敏感度測試) --")
    for sl in SL_THRESHOLDS:
        enr = enriched_close[sl].copy()
        enr["net_ret_sl2"] = enr["net_ret_sl"] - np.where(enr["triggered"], M.COST, 0.0)
        b2 = rebuild_baskets(baskets, enr, ret_col="net_ret_sl2")
        r2, ex2 = M.portfolio_curve(b2, grid, mode="baseline", weighting="equal")
        st2 = M.stats_from_ret(r2)
        print(f"  收盤觸發/同日出場 SL{sl * 100:.0f}%·雙重成本: 複利{st2['mult']:.1f}x MDD{st2['mdd']:.1f}% "
              f"夏普{st2['sharpe']:.2f}(vs 單一成本複利{[r['mult'] for r in rows if f'SL{sl*100:.0f}%' in r['variant'] and '收盤' in r['variant']][0]:.1f}x)")

    # -- 崩盤週個股層級深挖 --
    print("\n" + "-" * 100)
    print("### 崩盤週個股層級深挖(該週basket裡最慘個股,停損有沒有真的接住) ###")
    for wlabel, s, e in CRASH_WINDOWS:
        worst = find_worst_weeks_in_window(ret_base, baskets, s, e, top_k=2)
        print(f"\n  === {wlabel}: 窗口內最慘2週 ===")
        for entry_wk, exit_wk, r in worst:
            stock_deepdive(entry_wk, exit_wk, r, baskets, enriched_close, SL_THRESHOLDS)

    return rows, enriched_close, enriched_low, baskets, ret_base


def main():
    trades20, _ = M.build_trades(0.20)
    trades15, _ = M.build_trades(0.15)
    codes = sorted(set(trades20["code"]).union(set(trades15["code"])))
    print(f"\n建置日頻停損面板(需要的個股數={len(codes)})...")
    dpx = build_daily_panel(codes)
    label_to_actual = build_label_to_actual(dpx)
    code_daily = build_code_daily_index(dpx)

    run_stoploss_overlay(0.20, "20%", code_daily, label_to_actual, full=True)
    run_stoploss_overlay(0.15, "15%", code_daily, label_to_actual, full=False)
    print("\n" + "=" * 100)
    print("跑完。以上為console探索報告,無檔案輸出。")


if __name__ == "__main__":
    main()
