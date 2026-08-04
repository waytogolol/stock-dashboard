# -*- coding: utf-8 -*-
"""台美隔夜題材連動實測: 昨晚美股題材報酬 → 今日台股同題材超額報酬(demean)
假說(使用者): 昨晚美股某題材大漲(如記憶體), 今日台股同題材上漲機率高;
             若型態好看(大漲+創52週新高), 短期表現應更強。日級/隔夜/題材對題材。
資料: us_daily_price(yfinance調整價,2015起) + fm_daily_price(close>0&money>0清洗)
      + index_daily(TAIEX/SPX)。題材對映=classification main_group台美同名。
設計重點:
  - 訊號日對映: 台股日t ← 最後一個美股交易日d(d<t), 只取fresh(d>=前一台股日,
    排除美股休市造成的陳舊訊號)。時區優勢: 美股收盤=台北清晨4-5點, 零前視。
  - 混淆拆解: 美股題材原始報酬 vs 超額報酬(減SPX同日), 拆「只是大盤連動」。
  - ADR污染: 美股側TSM/UMC/ASX為台廠ADR(機械性自我連動), 主檢定剔除, 附含ADR對照。
  - 可交易性: 台股側①開盤進場(9:00市價,真可執行) vs ②收盤對照(close_{t-1}錨,理想化),
    跳空=open_t/close_{t-1}-1, 誠實揭露跳空吃掉多少。
  - 控制: 台股題材自身動能(前5日demean累計)、SPX當日、雙分組+回歸。
  - 統計: 日群bootstrap CI、逐年穩健度、事件研究CAR(k=0/1/3/5/10)、n誠實揭露。
用法: python 研究腳本/題材動能/build_us_tw_overnight_link.py   (從專案根目錄執行)
輸出: stdout報表(不寫檔)。
"""
import sqlite3
import sys

import numpy as np
import pandas as pd

DB = "capital_flow.db"
START = "2015-01-01"
ADR_EXCLUDE = {"TSM", "UMC", "ASX"}  # 台廠ADR
MAPPED_THEMES = [
    "IC設計", "CPO/光通訊", "AI伺服器", "半導體設備", "記憶體", "晶圓代工",
    "功率半導體", "電力設備", "組裝代工(EMS)", "機器人/自動化", "半導體材料",
    "電池/儲能", "連接器", "網通設備", "綠能/太陽能", "封測(OSAT/測試)",
    "被動元件", "化合物半導體", "PCB/CCL", "電信",
]
MIN_TW_MEMBERS = 2   # 台股側當日至少n檔有效才算題材報酬
K_LIST = [1, 3, 5, 10]


def load_members(conn):
    us, tw = {}, {}
    for t in MAPPED_THEMES:
        us[t] = sorted({r[0] for r in conn.execute(
            "select distinct code from classification where country='美' and main_group=?", (t,))})
        tw[t] = sorted({r[0] for r in conn.execute(
            "select distinct code from classification where country='台' and main_group=?", (t,))})
    return us, tw


def pivot_px(df, val):
    return df.pivot_table(index="date", columns="code", values=val, aggfunc="first")


def main():
    conn = sqlite3.connect(DB)
    us_mem, tw_mem = load_members(conn)
    all_us = sorted({c for v in us_mem.values() for c in v})
    all_tw = sorted({c for v in tw_mem.values() for c in v})

    # ---------- 載入 ----------
    usd = pd.read_sql("select code,date,close from us_daily_price where date>=?",
                      conn, params=("2014-01-01",))
    twd = pd.read_sql(
        "select code,date,open,close from fm_daily_price "
        "where date>=? and close>0 and money>0 and code in (%s)" % ",".join("?" * len(all_tw)),
        conn, params=("2014-06-01", *all_tw))
    idx = pd.read_sql("select market,date,open,close from index_daily "
                      "where market in ('TAIEX','SPX') and date>='2014-01-01'", conn)
    conn.close()

    spx = idx[idx.market == "SPX"].set_index("date").sort_index()
    tai = idx[idx.market == "TAIEX"].set_index("date").sort_index()
    spx_ret = spx["close"].pct_change()

    # ---------- 美股側: 題材日報酬 + 52週新高比例 ----------
    us_close = pivot_px(usd, "close").sort_index()
    us_ret = us_close.pct_change(fill_method=None)
    roll_max = us_close.rolling(252, min_periods=126).max()
    us_hi = (us_close >= roll_max * 0.999)
    us_hi = us_hi.where(us_close.notna() & roll_max.notna())

    def us_theme_ret(members):
        cols = [c for c in members if c in us_ret.columns]
        if not cols:
            return None, None, 0
        r = us_ret[cols].mean(axis=1)
        n = us_ret[cols].notna().sum(axis=1)
        hi = us_hi[cols].mean(axis=1)
        return r.where(n >= 1), hi, len(cols)

    us_sig = {}   # theme -> DataFrame(us_date, r_raw, r_ex, hi_frac, n_us)
    for t in MAPPED_THEMES:
        mem_ex = [c for c in us_mem[t] if c not in ADR_EXCLUDE]
        r_ex_adr, hi, ncol = us_theme_ret(mem_ex)
        r_all, _, _ = us_theme_ret(us_mem[t])
        if r_ex_adr is None:
            continue
        df = pd.DataFrame({"r_raw": r_ex_adr, "r_withADR": r_all, "hi_frac": hi})
        df["r_ex"] = df["r_raw"] - spx_ret.reindex(df.index)
        df["n_us"] = ncol
        us_sig[t] = df

    # ---------- 台股側: 題材日報酬(cc/oc/gap + CAR) ----------
    cal = [d for d in tai.index if d >= START]              # 台股交易日曆
    tw_close = pivot_px(twd, "close").reindex(tai.index).sort_index()
    tw_open = pivot_px(twd, "open").reindex(tai.index).sort_index()
    tw_open = tw_open.where(tw_open > 0)
    cc = tw_close.pct_change(fill_method=None)              # close_{t-1}→close_t
    oc = tw_close / tw_open - 1                             # open_t→close_t (可執行)
    gap = tw_open / tw_close.shift(1) - 1                   # 跳空
    car_c = {k: tw_close.shift(-k) / tw_close.shift(1) - 1 for k in K_LIST}   # 收盤錨(理想)
    car_o = {k: tw_close.shift(-k) / tw_open - 1 for k in K_LIST}             # 開盤錨(9:00進)
    car_e = {k: tw_close.shift(-k) / tw_close - 1 for k in K_LIST}            # 當日收盤進場錨(尾盤進,亦可執行)

    tai_cc = tai["close"].pct_change()
    tai_oc = tai["close"] / tai["open"] - 1
    tai_gap = tai["open"] / tai["close"].shift(1) - 1
    tai_car_c = {k: tai["close"].shift(-k) / tai["close"].shift(1) - 1 for k in K_LIST}
    tai_car_o = {k: tai["close"].shift(-k) / tai["open"] - 1 for k in K_LIST}
    tai_car_e = {k: tai["close"].shift(-k) / tai["close"] - 1 for k in K_LIST}

    def tw_theme(mat, members):
        cols = [c for c in members if c in mat.columns]
        m = mat[cols]
        n = m.notna().sum(axis=1)
        return m.mean(axis=1).where(n >= MIN_TW_MEMBERS), n

    # ---------- 日對映: 台股日t ← 最後美股日d(d<t), fresh限定 ----------
    us_dates = np.array(sorted(us_sig[MAPPED_THEMES[0]].index))
    tai_dates = list(tai.index)
    map_rows = []
    for i, t in enumerate(tai_dates):
        if t < START:
            continue
        pos = np.searchsorted(us_dates, t) - 1
        if pos < 0:
            continue
        d = us_dates[pos]
        prev = tai_dates[i - 1] if i > 0 else None
        fresh = (prev is None) or (d >= prev)
        map_rows.append((t, d, fresh))
    dmap = pd.DataFrame(map_rows, columns=["t", "d", "fresh"]).set_index("t")
    n_stale = (~dmap["fresh"]).sum()

    # ---------- 組panel: theme × 台股日 ----------
    recs = []
    for t in MAPPED_THEMES:
        if t not in us_sig:
            continue
        sig = us_sig[t]
        r_cc, n_tw = tw_theme(cc, tw_mem[t])
        r_oc, _ = tw_theme(oc, tw_mem[t])
        r_gap, _ = tw_theme(gap, tw_mem[t])
        cars_c = {k: tw_theme(car_c[k], tw_mem[t])[0] for k in K_LIST}
        cars_o = {k: tw_theme(car_o[k], tw_mem[t])[0] for k in K_LIST}
        cars_e = {k: tw_theme(car_e[k], tw_mem[t])[0] for k in K_LIST}
        mom5 = (r_cc - tai_cc).rolling(5).sum().shift(1)    # 台股題材自身動能(前5日demean)
        for day, row in dmap.iterrows():
            d = row["d"]
            if d not in sig.index or day not in r_cc.index:
                continue
            s = sig.loc[d]
            if pd.isna(s["r_raw"]) or pd.isna(r_cc.get(day, np.nan)):
                continue
            rec = {"theme": t, "t": day, "d": d, "fresh": row["fresh"],
                   "sig_raw": s["r_raw"], "sig_ex": s["r_ex"], "sig_withADR": s["r_withADR"],
                   "hi_frac": s["hi_frac"], "n_us": s["n_us"], "spx": spx_ret.get(d, np.nan),
                   "n_tw": n_tw.get(day, 0),
                   "tw_cc": r_cc[day] - tai_cc.get(day, np.nan),
                   "tw_oc": r_oc.get(day, np.nan) - tai_oc.get(day, np.nan),
                   "tw_gap": r_gap.get(day, np.nan) - tai_gap.get(day, np.nan),
                   "mom5": mom5.get(day, np.nan)}
            for k in K_LIST:
                rec[f"car_c{k}"] = cars_c[k].get(day, np.nan) - tai_car_c[k].get(day, np.nan)
                rec[f"car_o{k}"] = cars_o[k].get(day, np.nan) - tai_car_o[k].get(day, np.nan)
                rec[f"car_e{k}"] = cars_e[k].get(day, np.nan) - tai_car_e[k].get(day, np.nan)
            recs.append(rec)
    P = pd.DataFrame(recs)
    P = P[P["fresh"]].copy()
    P["year"] = P["t"].str[:4]
    P["month"] = P["t"].str[:7]

    print("=" * 88)
    print("台美隔夜題材連動實測  (樣本: %s ~ %s)" % (P["t"].min(), P["t"].max()))
    print("=" * 88)
    print(f"panel: {len(P)}筆 題材×台股日 (剔除陳舊訊號日{n_stale}個台股日; "
          f"美股側剔ADR {sorted(ADR_EXCLUDE)})")
    print(f"題材數: {P['theme'].nunique()}  平均台股側成員數: {P['n_tw'].mean():.1f}")

    # ---------- 對映題材清單 ----------
    print("\n【台美可對映題材與兩側成員數】(美股側為剔ADR後)")
    for t in MAPPED_THEMES:
        if t not in us_sig:
            continue
        nus = us_sig[t]["n_us"].iloc[0]
        sub = P[P.theme == t]
        print(f"  {t}: 美{nus}檔 台{len(tw_mem[t])}檔  有效題材日{len(sub)}")

    # ---------- 工具 ----------
    def boot_ci(sub, col, n_iter=1000, seed=7, cluster="t"):
        # cluster="t"日群聚; 多日CAR窗重疊時用cluster="month"月群聚更嚴
        v = sub[[cluster, col]].dropna()
        if len(v) < 10:
            return (np.nan, np.nan)
        rng = np.random.default_rng(seed)
        days = v[cluster].unique()
        grp = {d: g[col].values for d, g in v.groupby(cluster)}
        means = []
        for _ in range(n_iter):
            pick = rng.choice(days, size=len(days), replace=True)
            means.append(np.mean(np.concatenate([grp[d] for d in pick])))
        return tuple(np.percentile(means, [2.5, 97.5]))

    def bucket_table(P, sigcol, title):
        print(f"\n【{title}】(台股題材報酬皆為demean=減TAIEX同口徑, 單位%)")
        print(f"{'訊號分層':<14}{'n':>6}{'當日cc':>8}{'跳空':>8}{'當日oc':>8}"
              f"{'CAR3收錨':>9}{'CAR3開錨':>9}{'CAR5開錨':>9}")
        edges = [("大跌<-2%", P[sigcol] <= -0.02),
                 ("普通-2~2%", (P[sigcol] > -0.02) & (P[sigcol] < 0.02)),
                 ("大漲2~3%", (P[sigcol] >= 0.02) & (P[sigcol] < 0.03)),
                 ("大漲>3%", P[sigcol] >= 0.03),
                 ("大漲>2%合併", P[sigcol] >= 0.02)]
        out = {}
        for name, mask in edges:
            sub = P[mask]
            if len(sub) == 0:
                continue
            row = [sub["tw_cc"].mean(), sub["tw_gap"].mean(), sub["tw_oc"].mean(),
                   sub["car_c3"].mean(), sub["car_o3"].mean(), sub["car_o5"].mean()]
            out[name] = (sub, row)
            print(f"{name:<14}{len(sub):>6}" + "".join(f"{x * 100:>8.2f}" if i < 3 else f"{x * 100:>9.2f}"
                                                       for i, x in enumerate(row)))
        return out

    # ---------- 主檢定 ----------
    A = bucket_table(P, "sig_raw", "主檢定A: 美股題材原始報酬分層(未拆大盤混淆)")
    B = bucket_table(P, "sig_ex", "主檢定B: 美股題材超額報酬分層(減SPX同日, 拆大盤混淆後)")

    # bootstrap CI for key buckets
    print("\n【關鍵格bootstrap 95%CI(日群聚, 1000次)】")
    for name, (sigcol, lo) in [("原始>2%", ("sig_raw", 0.02)), ("超額>2%", ("sig_ex", 0.02))]:
        sub = P[P[sigcol] >= lo]
        for col, lab in [("tw_cc", "當日cc"), ("tw_oc", "當日oc"), ("car_o5", "CAR5開錨")]:
            ci = boot_ci(sub, col)
            m = sub[col].mean()
            sig_mark = "*" if (ci[0] > 0 or ci[1] < 0) else " "
            print(f"  {name} {lab}: {m * 100:+.2f}%  CI[{ci[0] * 100:+.2f},{ci[1] * 100:+.2f}]{sig_mark} n={len(sub)}")

    # ---------- 混淆拆解: 雙分組 ----------
    print("\n【混淆拆解: 美股題材大漲(原始>2%)日, 按SPX當日漲跌分組】")
    big = P[P["sig_raw"] >= 0.02]
    for name, mask in [("SPX>1%(大盤同漲)", big["spx"] >= 0.01),
                       ("SPX 0~1%", (big["spx"] >= 0) & (big["spx"] < 0.01)),
                       ("SPX<0(題材獨漲)", big["spx"] < 0)]:
        sub = big[mask]
        print(f"  {name:<18} n={len(sub):>5} 當日cc={sub['tw_cc'].mean() * 100:+.2f}% "
              f"當日oc={sub['tw_oc'].mean() * 100:+.2f}% CAR5開錨={sub['car_o5'].mean() * 100:+.2f}%")

    # ---------- 對照: 台股自身動能 ----------
    print("\n【控制台股題材自身動能: 超額>2%訊號 × 前5日台股題材demean動能】")
    subB = P[P["sig_ex"] >= 0.02].dropna(subset=["mom5"])
    med = P["mom5"].median()
    for name, mask in [("台股動能弱(<中位)", subB["mom5"] < med),
                       ("台股動能強(>=中位)", subB["mom5"] >= med)]:
        s = subB[mask]
        print(f"  {name:<18} n={len(s):>5} 當日cc={s['tw_cc'].mean() * 100:+.2f}% "
              f"當日oc={s['tw_oc'].mean() * 100:+.2f}% CAR5開錨={s['car_o5'].mean() * 100:+.2f}%")

    # ---------- 回歸(pooled OLS, 日群bootstrap) ----------
    print("\n【pooled回歸: tw_cc(demean) ~ sig_ex + spx + mom5】(係數=1%訊號對應bp)")
    reg = P.dropna(subset=["sig_ex", "spx", "mom5", "tw_cc"])
    X = np.column_stack([np.ones(len(reg)), reg["sig_ex"], reg["spx"], reg["mom5"]])
    y = reg["tw_cc"].values
    beta = np.linalg.lstsq(X, y, rcond=None)[0]
    rng = np.random.default_rng(11)
    days = reg["t"].unique()
    bidx = {d: np.where(reg["t"].values == d)[0] for d in days}
    bs = []
    for _ in range(500):
        pick = rng.choice(days, size=len(days), replace=True)
        ii = np.concatenate([bidx[d] for d in pick])
        bs.append(np.linalg.lstsq(X[ii], y[ii], rcond=None)[0])
    bs = np.array(bs)
    for j, nm in enumerate(["截距", "sig_ex(美題材超額)", "spx(美大盤)", "mom5(台自身動能)"]):
        lo_, hi_ = np.percentile(bs[:, j], [2.5, 97.5])
        mark = "*" if (lo_ > 0 or hi_ < 0) else " "
        print(f"  {nm:<18} b={beta[j]:+.4f}  CI[{lo_:+.4f},{hi_:+.4f}]{mark}")
    # oc版
    y2 = reg["tw_oc"].values
    ok2 = ~np.isnan(y2)
    beta2 = np.linalg.lstsq(X[ok2], y2[ok2], rcond=None)[0]
    print(f"  (oc可執行版) sig_ex係數 b={beta2[1]:+.4f}")

    # ---------- 可交易性: 跳空侵蝕 + 三種進場錨 ----------
    print("\n【可交易性: 開盤跳空吃掉多少(超額>2%格)】")
    sub = P[P["sig_ex"] >= 0.02]
    base = P[(P["sig_ex"] > -0.02) & (P["sig_ex"] < 0.02)]   # 普通日基準(增量比較用)
    m_cc, m_gap, m_oc = sub["tw_cc"].mean(), sub["tw_gap"].mean(), sub["tw_oc"].mean()
    print(f"  當日總反應cc={m_cc * 100:+.2f}% = 跳空{m_gap * 100:+.2f}% + 盤中oc{m_oc * 100:+.2f}%"
          f"  → 跳空吃掉{m_gap / m_cc * 100 if m_cc != 0 else np.nan:.0f}% (過衝, 盤中回吐)")
    print("  多日CAR三錨對照(收盤錨=理想close_{t-1} / 開盤錨=9:00進 / 尾盤錨=當日收盤進,皆可執行後兩者):")
    print("   k:        " + "".join(f"{k:>9}" for k in K_LIST))
    print("   收盤錨:   " + "".join(f"{sub[f'car_c{k}'].mean() * 100:>+9.2f}" for k in K_LIST))
    print("   開盤錨:   " + "".join(f"{sub[f'car_o{k}'].mean() * 100:>+9.2f}" for k in K_LIST))
    print("   尾盤錨:   " + "".join(f"{sub[f'car_e{k}'].mean() * 100:>+9.2f}" for k in K_LIST))
    print("   尾盤錨基準(普通日): " + "".join(f"{base[f'car_e{k}'].mean() * 100:>+9.2f}" for k in K_LIST))
    print("   開盤錨基準(普通日): " + "".join(f"{base[f'car_o{k}'].mean() * 100:>+9.2f}" for k in K_LIST))
    for col, lab in [("car_o5", "開盤錨CAR5"), ("car_e5", "尾盤錨CAR5")]:
        ci = boot_ci(sub, col, cluster="month")
        mark = "*" if (ci[0] > 0 or ci[1] < 0) else " "
        print(f"  {lab} 月群bootstrap95%CI(重疊窗嚴格版): "
              f"{sub[col].mean() * 100:+.2f}% CI[{ci[0] * 100:+.2f},{ci[1] * 100:+.2f}]{mark}")

    # ---------- 口袋: 美股題材獨漲(SPX<0)日 ----------
    print("\n【口袋檢定: 題材獨漲日(原始>2%且SPX<0) —— 跳空不過衝的子集】")
    pkt = P[(P["sig_raw"] >= 0.02) & (P["spx"] < 0)]
    print(f"  n={len(pkt)} 跳空={pkt['tw_gap'].mean() * 100:+.2f}% 當日oc={pkt['tw_oc'].mean() * 100:+.2f}% "
          f"當日cc={pkt['tw_cc'].mean() * 100:+.2f}%")
    print("   k:        " + "".join(f"{k:>9}" for k in K_LIST))
    print("   開盤錨:   " + "".join(f"{pkt[f'car_o{k}'].mean() * 100:>+9.2f}" for k in K_LIST))
    print("   尾盤錨:   " + "".join(f"{pkt[f'car_e{k}'].mean() * 100:>+9.2f}" for k in K_LIST))
    for col in ["tw_oc", "car_o5"]:
        ci = boot_ci(pkt, col, cluster="month")
        mark = "*" if (ci[0] > 0 or ci[1] < 0) else " "
        print(f"  {col} 月群CI: {pkt[col].mean() * 100:+.2f}% CI[{ci[0] * 100:+.2f},{ci[1] * 100:+.2f}]{mark}")
    print("  逐年(口袋, 開盤錨CAR5):")
    for yy, g in pkt.groupby("year"):
        print(f"   {yy}: n={len(g):>4} oc={g['tw_oc'].mean() * 100:+.2f}% CAR5開錨={g['car_o5'].mean() * 100:+.2f}%")

    # ---------- 事件研究CAR ----------
    print("\n【事件研究逐日CAR(開盤錨, k=0當日oc)】")
    for name, mask in [("超額>2%", P["sig_ex"] >= 0.02), ("超額>3%", P["sig_ex"] >= 0.03),
                       ("普通-2~2%", (P["sig_ex"] > -0.02) & (P["sig_ex"] < 0.02)),
                       ("超額<-2%", P["sig_ex"] <= -0.02)]:
        sub = P[mask]
        vals = [sub["tw_oc"].mean()] + [sub[f"car_o{k}"].mean() for k in K_LIST]
        print(f"  {name:<10} n={len(sub):>5} " +
              " ".join(f"k{k}={v * 100:+.2f}%" for k, v in zip([0] + K_LIST, vals)))

    # ---------- 創新高交乘 ----------
    print("\n【使用者加碼條件: 大漲×美股側52週新高比例(當日創新高成員佔比)】")
    for sigcol, lab in [("sig_raw", "原始>2%"), ("sig_ex", "超額>2%")]:
        sub = P[(P[sigcol] >= 0.02)].dropna(subset=["hi_frac"])
        for name, mask in [("無人創新高(=0)", sub["hi_frac"] == 0),
                           ("部分創新高(0~50%)", (sub["hi_frac"] > 0) & (sub["hi_frac"] < 0.5)),
                           ("過半創新高(>=50%)", sub["hi_frac"] >= 0.5)]:
            s = sub[mask]
            if len(s) < 5:
                print(f"  [{lab}] {name:<16} n={len(s)} (樣本不足)")
                continue
            print(f"  [{lab}] {name:<16} n={len(s):>5} 當日cc={s['tw_cc'].mean() * 100:+.2f}% "
                  f"當日oc={s['tw_oc'].mean() * 100:+.2f}% CAR5開錨={s['car_o5'].mean() * 100:+.2f}% "
                  f"CAR5尾錨={s['car_e5'].mean() * 100:+.2f}%")

    # ---------- 逐年穩健度 ----------
    print("\n【逐年穩健度: 超額>2%格】")
    sub = P[P["sig_ex"] >= 0.02]
    for yy, g in sub.groupby("year"):
        print(f"  {yy}: n={len(g):>4} 當日cc={g['tw_cc'].mean() * 100:+.2f}% "
              f"當日oc={g['tw_oc'].mean() * 100:+.2f}% CAR5開錨={g['car_o5'].mean() * 100:+.2f}% "
              f"CAR5尾錨={g['car_e5'].mean() * 100:+.2f}%")

    # ---------- 分題材 ----------
    print("\n【分題材: 超額>2%格(n>=15才列)】")
    for t, g in sub.groupby("theme"):
        if len(g) < 15:
            continue
        print(f"  {t:<14} n={len(g):>4} 當日cc={g['tw_cc'].mean() * 100:+.2f}% "
              f"當日oc={g['tw_oc'].mean() * 100:+.2f}% CAR5開錨={g['car_o5'].mean() * 100:+.2f}%")

    # ---------- ADR對照 ----------
    print("\n【ADR對照: 含ADR訊號 vs 剔ADR訊號(僅受影響題材: CPO/晶圓代工/封測)】")
    aff = P[P.theme.isin(["CPO/光通訊", "晶圓代工", "封測(OSAT/測試)"])]
    for lab, col in [("剔ADR", "sig_raw"), ("含ADR", "sig_withADR")]:
        s = aff[aff[col] >= 0.02]
        print(f"  {lab}>2%: n={len(s):>4} 當日cc={s['tw_cc'].mean() * 100:+.2f}% "
              f"當日oc={s['tw_oc'].mean() * 100:+.2f}%")

    # ---------- 穩健度: 剔除美股側單檔題材 ----------
    print("\n【穩健度: 剔除美股側僅1檔的題材後, 超額>2%格】")
    multi = P[(P["n_us"] >= 2) & (P["sig_ex"] >= 0.02)]
    ci = boot_ci(multi, "tw_oc")
    print(f"  n={len(multi)} 當日cc={multi['tw_cc'].mean() * 100:+.2f}% "
          f"當日oc={multi['tw_oc'].mean() * 100:+.2f}% CI_oc[{ci[0] * 100:+.2f},{ci[1] * 100:+.2f}] "
          f"CAR5開錨={multi['car_o5'].mean() * 100:+.2f}%")


if __name__ == "__main__":
    main()
