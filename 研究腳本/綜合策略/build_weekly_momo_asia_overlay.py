# -*- coding: utf-8 -*-
"""週級強者續強×亞跌五分型「B純亞跌」regime疊加測試(2026-08-04,使用者「三個新角度」第③題)。

背景: build_weekly_momo_regime_overlay.py測過MA240趨勢/波動regime,build_weekly_momo_margin_
overlay.py測過融資維持率警戒帶,皆負結果(要嘛觸發率太低/太晚,要嘛是「已經崩完才亮」的抄底訊號)。
本卷測第三個候選: 亞跌五分型系統(research_bottom_playbook.html/build_bottom_playbook_report.py),
核心邏輯=「非資訊性賣壓才有反彈」——B純亞跌型的既有判決是k10+3.12%/勝78%(偏多訊號,非風險警示),
本卷誠實檢查套到週級動能regime開關上,方向是否一樣「反過來」(B觸發後市場其實偏反彈,拿來當減碼開關
可能是錯誤方向),還是週級動能的個股集中度風險剛好跟B型觸發時點重疊而意外有用——不預設立場,直接跑。

B純亞跌定義(完全比照build_bottom_playbook_report.py既有口徑,不重新發明):
  asia = 當日N225日報酬<=-2% 且 當日KOSPI日報酬<=-2%(日/韓同步重跌)
  B = asia 且 當日SPX「前一夜」(即台股當日開盤前最近一次美股收盤)日報酬 > -1%(美股沒事,非資訊性
      賣壓,單純亞洲區域性重跌)。休市日對應市場當日報酬為NaN,NaN比較恆False,不會誤觸發(嚴格版,
      同原報告口徑)。
週級regime化(零前視): 訊號週(entry_week,W-FRI週五收盤)的B旗標=「該訊號週(週一至週五)內任一交易日
曾觸發B」——週內每一天都<=進場當週週五收盤,不用到未來資訊。敏感度對照: 「近5個交易日內曾觸發B」的
持續性版本(捕捉B觸發後續1週左右的餘波,而非只看訊號週當週本身)。

方法論: import build_weekly_momo_regime_overlay.py複用面板建置/交易建置/portfolio_curve(switch/
reduce_capital)/統計函式,亞股報酬直接查index_daily(N225/KOSPI/SPX/TAIEX,與原報告同資料源)。

用法: python 研究腳本/綜合策略/build_weekly_momo_asia_overlay.py (從根目錄執行,鐵律)
產出: 純console報告,無檔案輸出。
"""
import sqlite3
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "研究腳本/綜合策略")
sys.stdout.reconfigure(encoding="utf-8")

import build_weekly_momo_regime_overlay as M  # noqa: E402

DB = M.DB
CRASH_WINDOWS = [("2025-04關稅崩盤", "2025-03-01", "2025-05-01"),
                  ("2026-07-24台股修正", "2026-06-01", "2026-08-04")]


# ══ 一、B純亞跌日級判定(比照build_bottom_playbook_report.py) ══════════════════
def load_asia_panel():
    con = sqlite3.connect(DB)

    def load(mkt):
        return pd.read_sql("SELECT date, open, close FROM index_daily WHERE market=? ORDER BY date",
                           con, params=(mkt,), parse_dates=["date"]).set_index("date")
    tw = load("TAIEX")
    n2 = load("N225").close.pct_change() * 100
    ko = load("KOSPI").close.pct_change() * 100
    sp = load("SPX").close.pct_change() * 100
    con.close()

    twr = tw.close.pct_change() * 100
    df = pd.DataFrame({"tw": twr}).dropna()
    df = df[df.index >= "1999-02-01"]
    df["n225"] = n2.reindex(df.index)      # 嚴格版: 休市=NaN不觸發(同原報告)
    df["kospi"] = ko.reindex(df.index)
    si = sp.dropna()
    pos = si.index.searchsorted(df.index) - 1
    df["us"] = [si.iloc[p] if p >= 0 else np.nan for p in pos]   # 前一夜SPX收盤報酬,零前視
    return df


DF = load_asia_panel()
ASIA = (DF["n225"] <= -2) & (DF["kospi"] <= -2)
B_DAY = (ASIA & (DF["us"] > -1)).fillna(False)
print(f"B純亞跌日級判定: {int(B_DAY.sum())}個觸發日 / {len(B_DAY)}個交易日"
      f"({DF.index.min().date()}~{DF.index.max().date()})")

# 週級聚合(比照WIDE_C的W-FRI週化慣例,週內任一天觸發即整週旗標=True,零前視)
_wk_of = B_DAY.index.to_series().dt.to_period("W-FRI").dt.end_time.dt.normalize()
B_WEEK_FLAG = B_DAY.groupby(_wk_of).max()   # index=W-FRI週五, bool
print(f"週級聚合後(任一天觸發=整週旗標): {int(B_WEEK_FLAG.sum())}個觸發週 / {len(B_WEEK_FLAG)}週")

# 持續性版本(近5個交易日內曾觸發,含當日,零前視) -> 轉為regime Series供M.tag_at()查詢
B_PERSIST5 = B_DAY.rolling(5, min_periods=1).max().astype(bool)
REG_B_PERSIST = pd.Series(np.where(B_PERSIST5, "近5日觸發B", "正常"), index=B_DAY.index)


def fav_week_lookup(baskets):
    """主規則: 訊號週(entry_week)當週內是否觸發B。"""
    fav = {}
    for wk in baskets:
        fav[wk] = not bool(B_WEEK_FLAG.get(wk, False))
    return lambda w: fav[w]


def fav_persist_lookup(baskets):
    """敏感度規則: 近5個交易日內(含entry_week當日)是否曾觸發B,用tag_at ffill查詢。"""
    wks = list(baskets.keys())
    tags = M.tag_at(REG_B_PERSIST, wks).values
    fav = {w: (t != "近5日觸發B") for w, t in zip(wks, tags)}
    return lambda w: fav[w]


# ══ 二、主流程 ══════════════════════════════════════════
def run_threshold(threshold, label):
    print("\n" + "=" * 100)
    print(f"### 門檻={label} top{M.TOP_N} × B純亞跌regime ###")
    trades, baskets = M.build_trades(threshold)
    weeks = M.WIDE_RET.index
    start_i = weeks.searchsorted(pd.Timestamp(M.START))
    grid = weeks[start_i:]
    print(f"n_trades={len(trades)}  n_signal_weeks={len(baskets)}/{len(grid)}")

    fav_wk = fav_week_lookup(baskets)
    fav_p5 = fav_persist_lookup(baskets)
    n_unfav_wk = sum(1 for w in baskets if not fav_wk(w))
    n_unfav_p5 = sum(1 for w in baskets if not fav_p5(w))
    print(f"訊號週落在「當週觸發B」regime的週數={n_unfav_wk}/{len(baskets)}  "
          f"落在「近5日觸發B」regime的週數={n_unfav_p5}/{len(baskets)}")

    variants = {"基準(全押)": (None, "baseline")}
    for rname, fav in (("當週觸發B·關", fav_wk), ("近5日觸發B·關(敏感度)", fav_p5)):
        variants[f"{rname}開關版"] = (fav, "switch")
        variants[f"{rname}減碼50%版"] = (fav, "reduce_capital")

    rows = []
    for name, (fav, mode) in variants.items():
        r, ex = M.portfolio_curve(baskets, grid, favorable_fn=fav, mode=mode, weighting="equal")
        st = M.stats_from_ret(r)
        tr = M.trade_stats(ex)
        ci = M.bootstrap_ci(ex)
        yr = M.yearly_breakdown(r)
        rows.append({"variant": name, **st, **{f"tr_{k}": v for k, v in tr.items()},
                     "ci_lo": ci[0], "ci_hi": ci[1],
                     "n_pos_year": int((yr > 0).sum()), "n_year": len(yr),
                     "exposure": st["n_weeks_active"] / st["n_weeks_total"] * 100})

    print("\n-- 基準 vs B型regime控倉版 全比較表 --")
    hdr = (f"{'版本':<28}{'複利':>9}{'年化':>8}{'MDD':>8}{'夏普':>6}{'報酬/MDD':>9}"
           f"{'PF':>6}{'勝率':>6}{'單筆均':>8}{'CI':>20}{'曝險':>6}{'正年':>7}")
    print(hdr)
    for row in rows:
        ci_txt = f"[{row['ci_lo']:+.2f}%,{row['ci_hi']:+.2f}%]"
        print(f"{row['variant']:<28}{row['mult']:>8.1f}x{row['cagr']:>7.1f}%{row['mdd']:>7.1f}%"
              f"{row['sharpe']:>6.2f}{row['calmar']:>9.2f}{row['tr_pf']:>6.2f}{row['tr_win']:>5.0f}%"
              f"{row['tr_mean']:>7.2f}%{ci_txt:>20}{row['exposure']:>5.0f}%{row['n_pos_year']:>4d}/{row['n_year']:<3d}")
    print(f"\n  基準版MDD episode: {rows[0]['dd_peak'].date()} ~ {rows[0]['dd_trough'].date()}")

    # -- 基準版最差15週逐一核對: 該entry週有沒有觸發B(有觸發=B型有機會擋掉這週) --
    ret_base = M.portfolio_curve(baskets, grid, mode="baseline")[0]
    worst = ret_base.sort_values().head(15)
    entry_of = {b["exit_week"].iloc[0]: wk for wk, b in baskets.items()}
    print("\n-- 基準版最差15週: entry週是否觸發B(當週/近5日) --")
    print(f"{'exit週':<12}{'portret':>9}{'entry週':<12}{'n':>3}  當週觸發B  近5日觸發B")
    for exit_wk, r in worst.items():
        entry_wk = entry_of.get(exit_wk)
        if entry_wk is None:
            continue
        b = baskets[entry_wk]
        wk_b = "是" if not fav_wk(entry_wk) else "—"
        p5_b = "是" if not fav_p5(entry_wk) else "—"
        print(f"{str(exit_wk.date()):<12}{r*100:>+8.1f}%{str(entry_wk.date()):<12}{len(b):>3}"
              f"      {wk_b}          {p5_b}")

    return trades, baskets, grid, rows


def crash_deep_dive():
    print("\n" + "=" * 100)
    print("### 兩次真實重挫週: B型regime讀數是否提前示警 ###")
    taiex_wk = M.TAIEX.resample("W-FRI").last()
    taiex_wret = taiex_wk.pct_change(fill_method=None) * 100
    for label, s, e in CRASH_WINDOWS:
        print(f"\n--- {label}({s}~{e}) ---")
        print(f"{'週(W-FRI)':<12}{'TAIEX週報酬':>12}  當週觸發B?  近5日觸發B(週五讀數)?")
        for wk in taiex_wret.loc[s:e].index:
            wk_b = bool(B_WEEK_FLAG.get(wk, False))
            p5_tag = M.tag_at(REG_B_PERSIST, [wk]).iloc[0]
            print(f"{str(wk.date()):<12}{taiex_wret[wk]:>+11.2f}%      {'B' if wk_b else '—':<10}"
                  f"  {'B' if p5_tag == '近5日觸發B' else '—'}")

    print("\n-- 逐日細看兩次窗內B型觸發明細(asia兩市/美股前夜讀數) --")
    for label, s, e in CRASH_WINDOWS:
        seg = DF.loc[s:e]
        trig = seg[B_DAY.reindex(seg.index).fillna(False)]
        print(f"  {label}: 窗內B型觸發天數={len(trig)}/{len(seg)}")
        if len(trig):
            for d, r in trig.iterrows():
                print(f"    {d.date()}: n225={r['n225']:+.2f}% kospi={r['kospi']:+.2f}% "
                      f"us(前夜)={r['us']:+.2f}% tw(同日)={r['tw']:+.2f}%")
        asia_trig = seg[ASIA.reindex(seg.index).fillna(False)]
        print(f"    (對照: asia同步重跌但非B型的天數={len(asia_trig) - len(trig)},"
              f"代表當天美股前夜也重挫,屬A型美亞同跌非B型)")


def main():
    run_threshold(0.20, "20%")
    run_threshold(0.15, "15%")
    crash_deep_dive()
    print("\n" + "=" * 100)
    print("跑完。以上為console探索報告,無檔案輸出。")


if __name__ == "__main__":
    main()
