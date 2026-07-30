# -*- coding: utf-8 -*-
"""處置期間長紅/長黑接續研究(使用者2026-07-23由8261現場觀察提案)
現象: 8261處置期間(2026-07-09~07-24,5分盤)07-20收229→07-21收243.5(+6.3%)→07-22收254(+4.3%)
連二日反彈,07-23開259.5(接近當日高)卻打回收235.0(-7.5%),幾乎吐光兩日反彈。
與build_tx_tail_report.py「長紅日尾盤五天全負=回吐是常態」(台指期,不同資產同機制家族)呼應。

假說: 處置期間分盤撮合+斷頭/認賠壓力主導,價格是「被迫的」而非資訊性的——
①長紅日缺乏續航力(fade訊號,賣/避開) ②長紅後直接長黑=真正的「吐回」,可能觸底反彈(rebuy訊號)。

設計(預註冊,與使用者討論定案):
- 母體: disposition表全部事件,依match_min(5/20分盤)拆兩個母體分開報告,不合併
- 價格: fm_daily_price,自算close-based報酬(spread欄位不可信,已現場核對,見下方SPOT CHECK)
- 視窗: 每筆處置事件只在[start_date, end_date]內做長紅/長黑分類;forward return可延伸到
  end_date後(用該股完整價格序列自然延伸,無額外截斷,足以覆蓋k=8)
- 定義A(收盤對收盤): ret_cc=close_t/close_{t-1}-1,長紅>=+5%,長黑<=-5%
- 定義B(當日振幅+收盤位置): range_pct=(high-low)/close_{t-1};門檻0.06/0.08(headline)/0.10;
  達門檻才算「長棒」,長紅=收盤在[low,high]頂30%,長黑=收盤在底30%
- 訊號1(fade,賣出測試): 長紅日收盤起算k=1,2,3,5遠期報酬,對照組=該母體處置窗內「全部日」
  (unconditional baseline,house rule:永遠對照組不對零)
- 訊號2(rebuy,買進測試): 長黑且t-1=長紅(吐回) vs 長黑且t-1非長紅(對照組,單純破底無前段可吐),
  k=1,2,3,5,8;比較兩組+差值
- 統計驗證: LOTO(逐年剔除看正負是否穩定)+年群bootstrap(B=10000,seed=42),CI95+P(<=0)/P(>=0),
  原始報酬與case-control差值都做;n<15-20不強行跑bootstrap
用法: python build_disposition_candle_fade.py (Windows終端機cp950易炸,建議 python -X utf8 ...)
"""
import sqlite3
import sys

import numpy as np
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DB = "capital_flow.db"
RET_CC_THRESH = 0.05
CLOSE_POS_THRESH = 0.30  # 頂/底30%
RANGE_THRESH = {"B06": 0.06, "B08": 0.08, "B10": 0.10}
DEF_NAMES = ["A", "B06", "B08", "B10"]
FWD_KS = [1, 2, 3, 5, 8]
B_BOOT = 10000
SEED = 42
MAX_WIN_LEN = 30  # 事件窗口天數上限(sanity,實際多為~10日)


def stat(x, lab):
    x = pd.Series(x).dropna()
    if len(x) < 15:
        print(f"    {lab}: n={len(x)}太少")
        return None
    print(f"    {lab}: 中位{x.median() * 100:+6.2f}% 均值{x.mean() * 100:+6.2f}% "
          f"勝率{(x > 0).mean() * 100:3.0f}% n={len(x):,}")
    return x


def loto_bootstrap(sub, val_col, year_col, label, b=B_BOOT, seed=SEED):
    sub = sub.dropna(subset=[val_col])
    if len(sub) < 20 or sub[year_col].nunique() < 3:
        print(f"      [{label}] 樣本或年份數不足(n={len(sub)},年數={sub[year_col].nunique()}),略過LOTO/bootstrap")
        return
    rows = []
    for yr in sorted(sub[year_col].unique()):
        s2 = sub[sub[year_col] != yr]
        if len(s2) >= 15:
            rows.append((yr, s2[val_col].median(), len(s2)))
    if rows:
        rows.sort(key=lambda r: r[1])
        pos_ratio = sum(1 for _, m, _ in rows if m > 0) / len(rows) * 100
        print(f"      LOTO最壞: 剔除{rows[0][0]}年後中位{rows[0][1] * 100:+.2f}%(剩n={rows[0][2]}), "
              f"逐年中位為正比例{pos_ratio:.0f}%(共{len(rows)}年可測)")
    rng = np.random.default_rng(seed)
    years = sub[year_col].unique()
    groups = {yr: sub.loc[sub[year_col] == yr, val_col].values for yr in years}
    boots = []
    for _ in range(b):
        pick = rng.choice(years, size=len(years), replace=True)
        arr = np.concatenate([groups[yr] for yr in pick])
        if len(arr) >= 15:
            boots.append(np.median(arr))
    boots = np.array(boots)
    if len(boots) < 200:
        print(f"      [{label}] bootstrap有效樣本太少({len(boots)}),結果不可靠")
        return
    lo, hi = np.percentile(boots, [2.5, 97.5])
    p_le0 = (boots <= 0).mean()
    print(f"      cluster bootstrap(年群,B={len(boots)}): 中位CI95=[{lo * 100:+.2f}, {hi * 100:+.2f}]%, "
          f"P(<=0)={p_le0:.4f}")


def loto_bootstrap_diff(sig_df, ctl_df, val_col, year_col, label, b=B_BOOT, seed=SEED):
    sig = sig_df.dropna(subset=[val_col])
    ctl = ctl_df.dropna(subset=[val_col])
    if len(sig) < 15 or len(ctl) < 15:
        print(f"      [{label}] 訊號組或對照組樣本不足(訊號n={len(sig)},對照n={len(ctl)}),略過差值LOTO/bootstrap")
        return
    years = sorted(set(sig[year_col].unique()) | set(ctl[year_col].unique()))
    if len(years) < 3:
        print(f"      [{label}] 年份數不足({len(years)}),略過差值LOTO/bootstrap")
        return
    rows = []
    for yr in years:
        s2 = sig[sig[year_col] != yr]
        c2 = ctl[ctl[year_col] != yr]
        if len(s2) >= 10 and len(c2) >= 10:
            rows.append((yr, s2[val_col].median() - c2[val_col].median()))
    if rows:
        rows.sort(key=lambda r: r[1])
        pos_ratio = sum(1 for _, d in rows if d > 0) / len(rows) * 100
        print(f"      差值LOTO最壞: 剔除{rows[0][0]}年後差={rows[0][1] * 100:+.2f}pp, "
              f"逐年差為正比例{pos_ratio:.0f}%(共{len(rows)}年可測)")
    rng = np.random.default_rng(seed)
    sig_groups = {yr: sig.loc[sig[year_col] == yr, val_col].values for yr in sig[year_col].unique()}
    ctl_groups = {yr: ctl.loc[ctl[year_col] == yr, val_col].values for yr in ctl[year_col].unique()}
    diffs = []
    for _ in range(b):
        pick = rng.choice(years, size=len(years), replace=True)
        sarr = np.concatenate([sig_groups[yr] for yr in pick if yr in sig_groups]) if any(
            yr in sig_groups for yr in pick) else np.array([])
        carr = np.concatenate([ctl_groups[yr] for yr in pick if yr in ctl_groups]) if any(
            yr in ctl_groups for yr in pick) else np.array([])
        if len(sarr) >= 10 and len(carr) >= 10:
            diffs.append(np.median(sarr) - np.median(carr))
    diffs = np.array(diffs)
    if len(diffs) < 200:
        print(f"      [{label}] 差值bootstrap有效樣本太少({len(diffs)}),結果不可靠")
        return
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    p_le0 = (diffs <= 0).mean()
    p_ge0 = (diffs >= 0).mean()
    print(f"      差值cluster bootstrap(B={len(diffs)}): 差值中位數CI95=[{lo * 100:+.2f}, {hi * 100:+.2f}]pp, "
          f"P(差<=0)={p_le0:.4f} P(差>=0)={p_ge0:.4f}")


def classify_A(ret_cc):
    if ret_cc >= RET_CC_THRESH:
        return "red"
    if ret_cc <= -RET_CC_THRESH:
        return "black"
    return None


def classify_B(range_pct, close_pos, thresh):
    if range_pct < thresh or not np.isfinite(close_pos):
        return None
    if close_pos >= 1 - CLOSE_POS_THRESH:
        return "red"
    if close_pos <= CLOSE_POS_THRESH:
        return "black"
    return None


def build_panel(disp, stocks):
    rows = []
    for ev_id, e in disp.iterrows():
        g = stocks.get(e.code)
        if g is None:
            continue
        dts = g["date"].values
        n = len(g)
        s = int(np.searchsorted(dts, np.datetime64(e.start_date)))
        en = int(np.searchsorted(dts, np.datetime64(e.end_date), side="right") - 1)
        if s < 1 or en < s or s >= n or en - s > MAX_WIN_LEN:
            continue
        c_ = g["close"].values
        h_ = g["high"].values
        l_ = g["low"].values
        if not np.all(c_[s - 1:en + 1] > 0):
            continue
        y = e.start_date.year
        for i in range(s, en + 1):
            close_t, close_prev = c_[i], c_[i - 1]
            high_t, low_t = h_[i], l_[i]
            if close_prev <= 0 or close_t <= 0:
                continue
            ret_cc = close_t / close_prev - 1
            range_pct = (high_t - low_t) / close_prev
            rng = high_t - low_t
            close_pos = (close_t - low_t) / rng if rng > 0 else np.nan
            row = {
                "event_id": ev_id, "code": e.code, "market": e.market,
                "match_min": str(e.match_min), "y": y, "date": g["date"].values[i],
                "day_idx": i - s, "day_idx_from_end": en - i,
                "ret_cc": ret_cc, "range_pct": range_pct, "close_pos": close_pos,
                "class_A": classify_A(ret_cc),
            }
            for dn, th in RANGE_THRESH.items():
                row[f"class_{dn}"] = classify_B(range_pct, close_pos, th)
            for k in FWD_KS:
                j = i + k
                row[f"fwd{k}"] = (c_[j] / close_t - 1) if (j < n and c_[j] > 0) else np.nan
            rows.append(row)
    df = pd.DataFrame(rows)
    df = df.sort_values(["event_id", "date"]).reset_index(drop=True)
    for dn in DEF_NAMES:
        df[f"prev_class_{dn}"] = df.groupby("event_id")[f"class_{dn}"].shift(1)
    return df


def sanity_check_8261(panel):
    print("=" * 70)
    print("SANITY CHECK: 8261(富鼎) 2026-07 處置窗手工核對")
    print("=" * 70)
    sub = panel[(panel.code == "8261") & (panel.date >= "2026-07-01")].sort_values("date")
    if sub.empty:
        print("  !! 找不到8261 2026-07窗的資料,面板建置有問題,需先修好再信任全母體結果")
        return
    cols = ["date", "ret_cc", "range_pct", "close_pos", "class_A", "class_B06", "class_B08", "class_B10"]
    show = sub[cols].copy()
    show["date"] = show["date"].astype(str).str[:10]
    show["ret_cc"] = (show["ret_cc"] * 100).round(2)
    show["range_pct"] = (show["range_pct"] * 100).round(2)
    show["close_pos"] = (show["close_pos"] * 100).round(1)
    print(show.to_string(index=False))
    d0721 = sub[sub.date.astype(str).str[:10] == "2026-07-21"]
    d0722 = sub[sub.date.astype(str).str[:10] == "2026-07-22"]
    d0723 = sub[sub.date.astype(str).str[:10] == "2026-07-23"]
    ok_red = (not d0721.empty and d0721.class_A.iloc[0] == "red") or \
             (not d0722.empty and d0722.class_A.iloc[0] == "red")
    ok_black = (not d0723.empty and d0723.class_A.iloc[0] == "black")
    print(f"\n  定義A: 07-21或07-22長紅? {'PASS' if ok_red else 'FAIL'} / 07-23長黑? {'PASS' if ok_black else 'FAIL'}")
    if ok_red and ok_black:
        print("  >> 複現成功,pipeline日期對齊與分類邏輯正確,可信任全母體結果。")
    else:
        print("  >> 複現失敗!需檢查日期對齊/searchsorted/分類門檻,不可信任下面全母體結果。")
    print()


def spot_check_spread(conn):
    print("=" * 70)
    print("SPOT CHECK: fm_daily_price.spread 是否等於 close_t - close_{t-1}?")
    print("=" * 70)
    px = pd.read_sql("SELECT code, date, close, spread FROM fm_daily_price WHERE code='8261' "
                      "AND date>='2026-06-15' AND date<='2026-07-23' ORDER BY date", conn)
    px["my_diff"] = px["close"].diff()
    px["match"] = np.isclose(px["spread"], px["my_diff"], atol=0.05)
    print(px.to_string(index=False))
    n_bad = (~px["match"].fillna(True)).sum()
    print(f"\n  spread與自算close-diff不符的天數: {n_bad}/{len(px)} "
          f"(例: 07-09處置首日spread=0.0但實際close跌23元——spread不可信,已改用close自算ret_cc)")
    print()


def main():
    conn = sqlite3.connect(DB)
    disp = pd.read_sql("SELECT * FROM disposition", conn)
    px = pd.read_sql("SELECT code, date, open, high, low, close FROM fm_daily_price ORDER BY code, date", conn)

    spot_check_spread(conn)
    conn.close()

    for c in ("announce_date", "start_date", "end_date"):
        disp[c] = pd.to_datetime(disp[c], errors="coerce")
    disp = disp.dropna(subset=["start_date", "end_date"]).reset_index(drop=True)
    px["date"] = pd.to_datetime(px["date"])
    stocks = {c: g.sort_values("date").reset_index(drop=True) for c, g in px.groupby("code")}

    print(f"處置事件母體: {len(disp):,}筆 (match_min=5: {(disp.match_min == '5').sum():,} / "
          f"match_min=20: {(disp.match_min == '20').sum():,})")
    n_no_px = (~disp.code.isin(px.code.unique())).sum()
    print(f"代碼對不到fm_daily_price(權證/ETF/TDR等非普通股): {n_no_px:,}筆 (預期,fm_daily_price本就不涵蓋)")

    panel = build_panel(disp, stocks)
    panel.to_pickle("tmp_disposition_candle_panel.pkl")
    print(f"面板建置完成: {len(panel):,}筆日資料 / {panel.event_id.nunique():,}個處置事件對到價格 "
          f"(面板存tmp_disposition_candle_panel.pkl)\n")

    sanity_check_8261(panel)

    for mm in ["5", "20"]:
        pop = panel[panel.match_min == mm]
        print("#" * 70)
        print(f"## match_min = {mm}分盤  (事件數={pop.event_id.nunique():,}, 日資料數={len(pop):,})")
        print("#" * 70)

        print("\n== 母體基準線(unconditional baseline,窗內全部日,forward return) ==")
        baseline = {}
        for k in FWD_KS[:4]:  # k=1,2,3,5 (信號1只到5,基準線同步只算到5)
            baseline[k] = stat(pop[f"fwd{k}"], f"baseline k={k}")

        for dn in DEF_NAMES:
            th_note = f"(range_pct>={RANGE_THRESH[dn]:.2f})" if dn != "A" else "(ret_cc>=5%/<=-5%)"
            print(f"\n{'=' * 60}\n定義{dn} {th_note}\n{'=' * 60}")

            red_mask = pop[f"class_{dn}"] == "red"
            black_mask = pop[f"class_{dn}"] == "black"
            prev_red = pop[f"prev_class_{dn}"] == "red"
            giveback_mask = black_mask & prev_red
            control_black_mask = black_mask & (~prev_red)

            n_red, n_black = red_mask.sum(), black_mask.sum()
            n_give, n_ctlblk = giveback_mask.sum(), control_black_mask.sum()
            print(f"  n(長紅)={n_red}  n(長黑)={n_black}  "
                  f"n(長黑且t-1長紅=吐回)={n_give}  n(長黑對照組)={n_ctlblk}")

            # V4/V5 重疊(day_idx==2 為V4第3日, day_idx_from_end==2 為V5倒數第3日)
            if n_red > 0:
                v4ov = (pop.loc[red_mask, "day_idx"] == 2).mean() * 100
                v5ov = (pop.loc[red_mask, "day_idx_from_end"] == 2).mean() * 100
                print(f"  長紅日與V4(第3日)重疊率={v4ov:.1f}% / 與V5(倒數第3日)重疊率={v5ov:.1f}%")
            if n_give > 0:
                v4ov = (pop.loc[giveback_mask, "day_idx"] == 2).mean() * 100
                v5ov = (pop.loc[giveback_mask, "day_idx_from_end"] == 2).mean() * 100
                print(f"  吐回長黑日與V4(第3日)重疊率={v4ov:.1f}% / 與V5(倒數第3日)重疊率={v5ov:.1f}%")

            print("\n  -- 訊號1(fade,長紅賣出/避開) vs 母體基準線 --")
            for k in FWD_KS[:4]:
                sig = stat(pop.loc[red_mask, f"fwd{k}"], f"長紅組 k={k}")
                if sig is not None and baseline[k] is not None:
                    diff = sig.median() - baseline[k].median()
                    print(f"      中位差(長紅組-基準線) k={k}: {diff * 100:+.2f}pp")
            if n_red >= 15:
                print("    [長紅組原始報酬 k=3 LOTO+bootstrap]")
                loto_bootstrap(pop[red_mask], "fwd3", "y", f"{mm}分盤/{dn}/長紅k3")
                print("    [長紅組原始報酬 k=5 LOTO+bootstrap]")
                loto_bootstrap(pop[red_mask], "fwd5", "y", f"{mm}分盤/{dn}/長紅k5")
                print("    [長紅組 vs 基準線 差值 k=3 LOTO+bootstrap]")
                loto_bootstrap_diff(pop[red_mask], pop, "fwd3", "y", f"{mm}分盤/{dn}/長紅-基準k3")
                print("    [長紅組 vs 基準線 差值 k=5 LOTO+bootstrap]")
                loto_bootstrap_diff(pop[red_mask], pop, "fwd5", "y", f"{mm}分盤/{dn}/長紅-基準k5")
            else:
                print(f"    n(長紅)={n_red}太少(<15),不跑LOTO/bootstrap")

            print("\n  -- 訊號2(rebuy,吐回長黑買進) vs 對照組(非吐回長黑) --")
            for k in FWD_KS:
                sig = stat(pop.loc[giveback_mask, f"fwd{k}"], f"吐回長黑組 k={k}   ")
                ctl = stat(pop.loc[control_black_mask, f"fwd{k}"], f"對照長黑組 k={k}   ")
                if sig is not None and ctl is not None:
                    diff = sig.median() - ctl.median()
                    print(f"      中位差(吐回組-對照組) k={k}: {diff * 100:+.2f}pp")
            if n_give >= 15 and n_ctlblk >= 15:
                print("    [吐回長黑組原始報酬 k=1 LOTO+bootstrap]")
                loto_bootstrap(pop[giveback_mask], "fwd1", "y", f"{mm}分盤/{dn}/吐回k1")
                print("    [吐回長黑組原始報酬 k=5 LOTO+bootstrap]")
                loto_bootstrap(pop[giveback_mask], "fwd5", "y", f"{mm}分盤/{dn}/吐回k5")
                print("    [吐回組 vs 對照組 差值 k=1 LOTO+bootstrap]")
                loto_bootstrap_diff(pop[giveback_mask], pop[control_black_mask], "fwd1", "y",
                                     f"{mm}分盤/{dn}/吐回-對照k1")
                print("    [吐回組 vs 對照組 差值 k=5 LOTO+bootstrap]")
                loto_bootstrap_diff(pop[giveback_mask], pop[control_black_mask], "fwd5", "y",
                                     f"{mm}分盤/{dn}/吐回-對照k5")
            else:
                print(f"    n(吐回)={n_give} n(對照)={n_ctlblk},至少一組<15,不跑LOTO/bootstrap")

    print("\n" + "#" * 70)
    print("## 逐年細看(定義A,兩母體合併僅供參考走勢;正式判準以上方分母體為準)")
    print("#" * 70)
    for mm in ["5", "20"]:
        pop = panel[panel.match_min == mm]
        red_mask = pop["class_A"] == "red"
        give_mask = (pop["class_A"] == "black") & (pop["prev_class_A"] == "red")
        print(f"\n-- match_min={mm} --")
        for y in sorted(pop.y.unique()):
            r = pop.loc[red_mask & (pop.y == y), "fwd3"]
            g = pop.loc[give_mask & (pop.y == y), "fwd1"]
            r_s = f"{r.median() * 100:+.2f}%(n={len(r.dropna())})" if len(r.dropna()) >= 3 else f"n={len(r.dropna())}太少"
            g_s = f"{g.median() * 100:+.2f}%(n={len(g.dropna())})" if len(g.dropna()) >= 3 else f"n={len(g.dropna())}太少"
            print(f"  {y}: 長紅k3={r_s}  吐回長黑k1={g_s}")


if __name__ == "__main__":
    main()
