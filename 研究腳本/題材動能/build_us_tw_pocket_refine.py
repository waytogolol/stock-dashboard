# -*- coding: utf-8 -*-
"""台美隔夜題材連動·第二輪:題材獨漲口袋組合精煉+可執行組合模擬+正式HTML報告(2026-08-05)。

承接: build_us_tw_overnight_link.py(首輪考卷,commit ac221a4,結論只在console)。首輪判決:
  主檢定分層單調顯著且獨立於大盤;開盤追買被跳空過衝殺死;活口=①尾盤進場持5日+0.57%十二年全正(薄,tilt)
  ②題材獨漲口袋(美題材原始>2%且SPX<0,~85題材日/年)開盤進5日+0.68%/10日+1.15%,12年11正
  ③創新高交乘單調增強(→+0.78%)僅多日持有有價值。
本卷=使用者交辦的後續: 口袋×創新高×強題材子集組合精煉,並補產正式HTML報告上index。

═══ 本卷四個問題(寫程式前預先註冊) ═══
Q1 口袋定義敏感度: 門檻(原始>2/2.5/3%)×SPX條件(<0 / <-0.5%),肉量與n的權衡,不掃參數只看穩不穩。
Q2 口袋×創新高交乘: hi_frac(美股側當日創52週新高成員佔比)=0 / >0 / >=50%三層,首輪已見單調,口袋內複驗。
Q3 口袋×強題材子集: (a)使用者指定四題材[記憶體/CPO/PCB/被動元件](首輪全樣本挑的,in-sample要誠實標註)
   (b)防過擬合對照: 用前半段(2015-2020)口袋表現排名取前4題材,只在後半段(2021-)評估=split-half準OOS。
   兩版並列,若(a)只贏在前半段=過擬合警訊。
Q4 可執行組合模擬(成員層,錢的視角): 口袋事件日開盤買進題材全成員等權(排除開盤跳空>=+9%≈漲停鎖死
   買不到的,誠實計數),持有至第5個交易日收盤,重疊事件日頻等權再平衡,空手期0%。
   輸出=年化/MDD/夏普/PF/賺賠比/逐年/曝險率,成本情境0%/0.5%/1.0%來回。
   目標函數依展望理論排序: MDD小>賺賠比大>報酬/MDD大>逐期穩定>絕對報酬(feedback第17條)。

═══ 口徑鐵律(沿用首輪+第12/18條) ═══
· 訊號=最後一個美股交易日d(d<t)收盤,美股收盤=台北清晨4-5點,台股開盤9:00前已完全確認,零前視;
  只取fresh(d>=前一台股日),陳舊訊號日剔除。
· 進場錨=開盤(9:00市價,口袋子集首輪已驗證跳空不過衝);事件研究輸出k=1,2,3,5,7,10,15,20逐日CAR。
· 統計=月群bootstrap 95%CI(多日CAR窗重疊,月群比日群嚴);逐年穩健度必列;n誠實揭露。
· 台股側demean=減TAIEX同口徑(研究工具);組合模擬報絕對報酬(使用者目標函數,feedback第13條)。
· ADR剔除(TSM/UMC/ASX);台股側fm_daily_price以close>0 AND money>0清洗(2026-08-05鐵律)。

已知限制: fm_daily_price未做除權息還原(持有窗跨除息日會少算股息=保守偏誤);題材報酬=成員等權
(theme層與成員層組合各自誠實計算);首輪四強題材屬全樣本內挑選,Q3(b)為其防過擬合對照。

用法: python 研究腳本/題材動能/build_us_tw_pocket_refine.py   (從根目錄執行,鐵律)
產出: 研究報告/research_us_tw_overnight.html + console報表
"""
import json
import sqlite3
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

DB = "capital_flow.db"
OUT = "研究報告/research_us_tw_overnight.html"
START = "2015-01-01"
ADR_EXCLUDE = {"TSM", "UMC", "ASX"}
MAPPED_THEMES = [
    "IC設計", "CPO/光通訊", "AI伺服器", "半導體設備", "記憶體", "晶圓代工",
    "功率半導體", "電力設備", "組裝代工(EMS)", "機器人/自動化", "半導體材料",
    "電池/儲能", "連接器", "網通設備", "綠能/太陽能", "封測(OSAT/測試)",
    "被動元件", "化合物半導體", "PCB/CCL", "電信",
]
USER4 = ["記憶體", "CPO/光通訊", "PCB/CCL", "被動元件"]   # 使用者指定四題材(in-sample,誠實標註)
MIN_TW_MEMBERS = 2
K_LIST = [1, 2, 3, 5, 7, 10, 15, 20]
HOLD = 5                     # 組合模擬持有交易日數(開盤進→第HOLD日收盤出,=首輪car_o5口徑)
LOCK_GAP = 0.09              # 成員開盤跳空>=+9%≈漲停鎖死買不到代理,組合模擬排除並計數
COST_SIDES = [0.0, 0.0025, 0.005]   # 單邊成本情境(來回=0%/0.5%/1.0%)
SPLIT_DATE = "2021-01-01"    # split-half分界(Q3b)
rng = np.random.default_rng(20260805)

GREEN, RED, BLUE, YELLOW, GRAY = "#7ec97e", "#e06c5a", "#6bb7e3", "#c3a55a", "#8a8878"
BG = {"paper_bgcolor": "#1a1a19", "plot_bgcolor": "#22221f",
      "font": {"color": "#ddd", "size": 12}, "margin": {"t": 42, "l": 52, "r": 18, "b": 40},
      "legend": {"orientation": "h"}}


# ======================================================================
# 1. 面板建置(逐字沿用build_us_tw_overnight_link.py的訊號/對映/CAR機制,加member層)
# ======================================================================
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


def build_panel():
    conn = sqlite3.connect(DB, timeout=60)
    us_mem, tw_mem = load_members(conn)
    all_tw = sorted({c for v in tw_mem.values() for c in v})
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

    # 美股側訊號
    us_close = pivot_px(usd, "close").sort_index()
    us_ret = us_close.pct_change(fill_method=None)
    roll_max = us_close.rolling(252, min_periods=126).max()
    us_hi = (us_close >= roll_max * 0.999).where(us_close.notna() & roll_max.notna())

    us_sig = {}
    for t in MAPPED_THEMES:
        cols = [c for c in us_mem[t] if c not in ADR_EXCLUDE and c in us_ret.columns]
        if not cols:
            continue
        r = us_ret[cols].mean(axis=1)
        n = us_ret[cols].notna().sum(axis=1)
        df = pd.DataFrame({"r_raw": r.where(n >= 1), "hi_frac": us_hi[cols].mean(axis=1)})
        df["r_ex"] = df["r_raw"] - spx_ret.reindex(df.index)
        us_sig[t] = df

    # 台股側(theme層+member層)
    tw_close = pivot_px(twd, "close").reindex(tai.index).sort_index()
    tw_open = pivot_px(twd, "open").reindex(tai.index).sort_index()
    tw_open = tw_open.where(tw_open > 0)
    cc = tw_close.pct_change(fill_method=None)
    oc = tw_close / tw_open - 1
    gap = tw_open / tw_close.shift(1) - 1
    car_o = {k: tw_close.shift(-k) / tw_open - 1 for k in K_LIST}

    tai_cc = tai["close"].pct_change()
    tai_oc = tai["close"] / tai["open"] - 1
    tai_gap = tai["open"] / tai["close"].shift(1) - 1
    tai_car_o = {k: tai["close"].shift(-k) / tai["open"] - 1 for k in K_LIST}

    def tw_theme(mat, members):
        cols = [c for c in members if c in mat.columns]
        m = mat[cols]
        n = m.notna().sum(axis=1)
        return m.mean(axis=1).where(n >= MIN_TW_MEMBERS), n

    # 日對映(fresh限定)
    us_dates = np.array(sorted(next(iter(us_sig.values())).index))
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
        map_rows.append((t, d, (prev is None) or (d >= prev)))
    dmap = pd.DataFrame(map_rows, columns=["t", "d", "fresh"]).set_index("t")

    recs = []
    for t in MAPPED_THEMES:
        if t not in us_sig:
            continue
        sig = us_sig[t]
        r_cc, n_tw = tw_theme(cc, tw_mem[t])
        r_oc, _ = tw_theme(oc, tw_mem[t])
        r_gap, _ = tw_theme(gap, tw_mem[t])
        cars_o = {k: tw_theme(car_o[k], tw_mem[t])[0] for k in K_LIST}
        for day, row in dmap.iterrows():
            d = row["d"]
            if not row["fresh"] or d not in sig.index or day not in r_cc.index:
                continue
            s = sig.loc[d]
            if pd.isna(s["r_raw"]) or pd.isna(r_cc.get(day, np.nan)):
                continue
            rec = {"theme": t, "t": day, "d": d,
                   "sig_raw": s["r_raw"], "sig_ex": s["r_ex"], "hi_frac": s["hi_frac"],
                   "spx": spx_ret.get(d, np.nan), "n_tw": n_tw.get(day, 0),
                   "tw_cc": r_cc[day] - tai_cc.get(day, np.nan),
                   "tw_oc": r_oc.get(day, np.nan) - tai_oc.get(day, np.nan),
                   "tw_gap": r_gap.get(day, np.nan) - tai_gap.get(day, np.nan)}
            for k in K_LIST:
                rec[f"car_o{k}"] = cars_o[k].get(day, np.nan) - tai_car_o[k].get(day, np.nan)
                rec[f"abs_o{k}"] = cars_o[k].get(day, np.nan)      # 絕對報酬版(第13條)
            recs.append(rec)
    P = pd.DataFrame(recs)          # t/d皆為ISO字串(lexicographic排序=時間排序)
    P["year"] = P["t"].str[:4]
    P["month"] = P["t"].str[:7]
    print(f"[panel] {len(P):,}筆題材×台股日, {P['theme'].nunique()}題材, "
          f"{P['t'].min()}~{P['t'].max()}")
    return P, tw_mem, tw_open, tw_close, tai


def boot_ci(sub, col, n_iter=1000, cluster="month"):
    v = sub[[cluster, col]].dropna()
    if len(v) < 10 or v[cluster].nunique() < 6:
        return (np.nan, np.nan)
    grp = {d: g[col].values for d, g in v.groupby(cluster)}
    keys = list(grp)
    means = []
    for _ in range(n_iter):
        pick = rng.choice(keys, size=len(keys), replace=True)
        means.append(np.mean(np.concatenate([grp[d] for d in pick])))
    return tuple(np.percentile(means, [2.5, 97.5]))


def ci_str(sub, col):
    lo, hi = boot_ci(sub, col)
    if pd.isna(lo):
        return "n太小"
    m = sub[col].mean()
    mark = "✓排0" if (lo > 0 or hi < 0) else "含0"
    return f"{m * 100:+.2f}% [{lo * 100:+.2f},{hi * 100:+.2f}]{mark}"


def car_curve(sub):
    return {k: sub[f"car_o{k}"].mean() * 100 for k in K_LIST}


def yearly_tbl(sub, col="car_o5"):
    out = []
    for yy, g in sub.groupby("year"):
        out.append((yy, len(g), g[col].mean() * 100))
    pos = sum(1 for _, _, v in out if v > 0)
    return out, pos, len(out)


# ======================================================================
# 2. Q1 口袋定義敏感度
# ======================================================================
def q1_sensitivity(P):
    print("\n" + "=" * 80, "\nQ1 口袋定義敏感度(原始門檻×SPX條件)")
    rows = []
    for th in (0.02, 0.025, 0.03):
        for spx_th, spx_lab in ((0.0, "SPX<0"), (-0.005, "SPX<-0.5%")):
            sub = P[(P["sig_raw"] >= th) & (P["spx"] < spx_th)]
            n_per_yr = len(sub) / max(P["year"].nunique(), 1)
            r = {"lab": f"原始>{th * 100:.1f}%×{spx_lab}", "n": len(sub), "nyr": n_per_yr,
                 "gap": sub["tw_gap"].mean() * 100, "oc": sub["tw_oc"].mean() * 100,
                 "car5": sub["car_o5"].mean() * 100, "car10": sub["car_o10"].mean() * 100,
                 "ci5": ci_str(sub, "car_o5")}
            y, pos, tot = yearly_tbl(sub)
            r["yr"] = f"{pos}/{tot}"
            rows.append(r)
            print(f"  {r['lab']:<24} n={r['n']:>4}({n_per_yr:.0f}/年) 跳空{r['gap']:+.2f} "
                  f"oc{r['oc']:+.2f} CAR5={r['car5']:+.2f} CAR10={r['car10']:+.2f} "
                  f"CI5:{r['ci5']} 逐年{r['yr']}")
    return rows


# ======================================================================
# 3. Q2 口袋×創新高
# ======================================================================
def q2_newhigh(P):
    print("\n" + "=" * 80, "\nQ2 口袋×創新高交乘(hi_frac=美股側當日創52週新高成員佔比)")
    pkt = P[(P["sig_raw"] >= 0.02) & (P["spx"] < 0)].dropna(subset=["hi_frac"])
    rows = []
    for lab, mask in [("無人創新高(=0)", pkt["hi_frac"] == 0),
                      ("部分創新高(0~50%)", (pkt["hi_frac"] > 0) & (pkt["hi_frac"] < 0.5)),
                      ("過半創新高(>=50%)", pkt["hi_frac"] >= 0.5),
                      ("有人創新高(>0)合併", pkt["hi_frac"] > 0)]:
        s = pkt[mask]
        curve = car_curve(s)
        y, pos, tot = yearly_tbl(s)
        r = {"lab": lab, "n": len(s), "gap": s["tw_gap"].mean() * 100,
             "oc": s["tw_oc"].mean() * 100, "curve": curve, "ci5": ci_str(s, "car_o5"),
             "ci10": ci_str(s, "car_o10"), "yr": f"{pos}/{tot}"}
        rows.append(r)
        print(f"  {lab:<20} n={len(s):>4} 跳空{r['gap']:+.2f} oc{r['oc']:+.2f} "
              f"CAR: " + " ".join(f"k{k}={curve[k]:+.2f}" for k in (1, 3, 5, 10, 20)) +
              f"  CI5:{r['ci5']} 逐年{r['yr']}")
    return rows, pkt


# ======================================================================
# 4. Q3 口袋×強題材子集(a使用者四題材 b split-half準OOS)
# ======================================================================
def q3_subsets(P):
    print("\n" + "=" * 80, "\nQ3 口袋×強題材子集")
    pkt = P[(P["sig_raw"] >= 0.02) & (P["spx"] < 0)]

    # 分題材口袋成績(全樣本,n>=8才列)
    print("  【分題材口袋CAR5(全樣本)】")
    theme_rows = []
    for t, g in pkt.groupby("theme"):
        if len(g) < 8:
            continue
        theme_rows.append({"theme": t, "n": len(g), "car5": g["car_o5"].mean() * 100,
                           "car10": g["car_o10"].mean() * 100, "oc": g["tw_oc"].mean() * 100})
    theme_rows.sort(key=lambda x: -x["car5"])
    for r in theme_rows:
        star = "★" if r["theme"] in USER4 else " "
        print(f"   {star}{r['theme']:<14} n={r['n']:>3} oc={r['oc']:+.2f} "
              f"CAR5={r['car5']:+.2f} CAR10={r['car10']:+.2f}")

    # (a) 使用者四題材(in-sample)
    sub_a = pkt[pkt["theme"].isin(USER4)]
    # (b) split-half: 前半段排名取前4,後半段評估
    first = pkt[pkt["t"] < SPLIT_DATE]
    second = pkt[pkt["t"] >= SPLIT_DATE]
    rank1 = first.groupby("theme").agg(n=("car_o5", "size"), m=("car_o5", "mean"))
    rank1 = rank1[rank1["n"] >= 5].sort_values("m", ascending=False)
    top4_first = list(rank1.index[:4])
    sub_b = second[second["theme"].isin(top4_first)]
    print(f"  前半段(2015-2020)口袋排名前4題材(n>=5): {top4_first}")

    out = {}
    for lab, s in [("(a)使用者四題材[記憶體/CPO/PCB/被動元件](全樣本,in-sample)", sub_a),
                   ("(a')使用者四題材·僅後半段2021-(檢查是否只贏在前半)", sub_a[sub_a["t"] >= SPLIT_DATE]),
                   ("(b)前半段排名前4題材·僅後半段評估(split-half準OOS)", sub_b),
                   ("(全口袋當基準)", pkt)]:
        curve = car_curve(s)
        y, pos, tot = yearly_tbl(s)
        out[lab] = {"n": len(s), "gap": s["tw_gap"].mean() * 100, "oc": s["tw_oc"].mean() * 100,
                    "curve": curve, "ci5": ci_str(s, "car_o5"), "ci10": ci_str(s, "car_o10"),
                    "yr": f"{pos}/{tot}", "yearly": y,
                    "abs5": s["abs_o5"].mean() * 100, "abs10": s["abs_o10"].mean() * 100}
        r = out[lab]
        print(f"  {lab}\n    n={r['n']} 跳空{r['gap']:+.2f} oc{r['oc']:+.2f} "
              f"CAR: " + " ".join(f"k{k}={curve[k]:+.2f}" for k in (1, 3, 5, 10, 20)) +
              f"\n    CI5:{r['ci5']}  CI10:{r['ci10']}  逐年{r['yr']}  "
              f"絕對(未demean)CAR5={r['abs5']:+.2f}/CAR10={r['abs10']:+.2f}")
    return theme_rows, top4_first, out, pkt


# ======================================================================
# 5. Q2×Q3 組合精煉(交乘格,n誠實)
# ======================================================================
def q_combo(P):
    print("\n" + "=" * 80, "\n組合精煉交乘格(口袋×四題材×創新高,n會很薄,誠實列)")
    pkt = P[(P["sig_raw"] >= 0.02) & (P["spx"] < 0)]
    combos = [
        ("口袋(基準)", pkt),
        ("口袋×hi>0", pkt[pkt["hi_frac"] > 0]),
        ("口袋×四題材", pkt[pkt["theme"].isin(USER4)]),
        ("口袋×四題材×hi>0", pkt[pkt["theme"].isin(USER4) & (pkt["hi_frac"] > 0)]),
        ("口袋×原始>3%", pkt[pkt["sig_raw"] >= 0.03]),
        ("口袋×原始>3%×四題材", pkt[(pkt["sig_raw"] >= 0.03) & pkt["theme"].isin(USER4)]),
    ]
    rows = []
    for lab, s in combos:
        curve = car_curve(s)
        y, pos, tot = yearly_tbl(s)
        r = {"lab": lab, "n": len(s), "nyr": len(s) / max(P["year"].nunique(), 1),
             "oc": s["tw_oc"].mean() * 100, "gap": s["tw_gap"].mean() * 100, "curve": curve,
             "ci5": ci_str(s, "car_o5"), "ci10": ci_str(s, "car_o10"), "yr": f"{pos}/{tot}",
             "abs5": s["abs_o5"].mean() * 100, "abs10": s["abs_o10"].mean() * 100}
        rows.append(r)
        print(f"  {lab:<22} n={r['n']:>4}({r['nyr']:.0f}/年) oc{r['oc']:+.2f} "
              f"CAR5={curve[5]:+.2f} CAR10={curve[10]:+.2f} CI5:{r['ci5']} 逐年{r['yr']}")
    return rows


# ======================================================================
# 6. Q4 可執行組合模擬(成員層)
# ======================================================================
def simulate(P, tw_mem, tw_open, tw_close, tai, event_mask, lab, cost_side, hold=HOLD):
    """口袋事件日開盤買題材全成員等權,排除開盤跳空>=LOCK_GAP,持有至第hold日收盤。
    日頻等權再平衡,空手=0%。回傳指標dict。"""
    ev = P[event_mask]
    dates = list(tw_close.index)
    dpos = {d: i for i, d in enumerate(dates)}
    closef = tw_close.ffill(limit=5)
    n_lock, n_pos = 0, 0
    # positions[(code, t_idx)] = (entry_i, exit_i, entry_price)
    seen = set()
    daily_ret = {}          # i -> list of position daily returns
    ev_rets = []            # 事件-成員層總報酬(成本後)
    for r in ev.itertuples():
        i0 = dpos.get(r.t)
        if i0 is None or i0 + hold >= len(dates):
            continue
        for c in tw_mem[r.theme]:
            if c not in tw_open.columns or (c, i0) in seen:
                continue
            seen.add((c, i0))
            op = tw_open.iat[i0, tw_open.columns.get_loc(c)]
            pc = tw_close.iat[i0 - 1, tw_close.columns.get_loc(c)] if i0 >= 1 else np.nan
            if pd.isna(op) or pd.isna(pc) or pc <= 0:
                continue
            if op / pc - 1 >= LOCK_GAP:
                n_lock += 1
                continue
            col = closef.columns.get_loc(c)
            path = closef.iloc[i0:i0 + hold + 1, col].values
            if pd.isna(path).any():
                continue
            n_pos += 1
            # 逐日報酬: day0=open->close, day1..hold=close->close;進場日扣買側,出場日扣賣側
            rets = np.empty(hold + 1)
            rets[0] = path[0] / op - 1 - cost_side
            rets[1:] = path[1:] / path[:-1] - 1
            rets[hold] -= cost_side
            for j in range(hold + 1):
                daily_ret.setdefault(i0 + j, []).append(rets[j])
            tot = (1 - cost_side) * path[hold] / op * (1 - cost_side) - 1
            ev_rets.append((r.t, tot))
    if not daily_ret:
        return None
    # NAV
    idx_all = sorted(daily_ret)
    nav_dates, navs = [], []
    nav = 1.0
    peak, mdd = 1.0, 0.0
    rs = []
    span = range(idx_all[0], idx_all[-1] + 1)
    for i in span:
        r_day = np.mean(daily_ret[i]) if i in daily_ret else 0.0
        nav *= (1 + r_day)
        rs.append(r_day)
        peak = max(peak, nav)
        mdd = min(mdd, nav / peak - 1)
        nav_dates.append(dates[i])
        navs.append(nav)
    rs = np.array(rs)
    n_days = len(rs)
    yrs = n_days / 252
    ann = nav ** (1 / yrs) - 1 if yrs > 0.5 else np.nan
    shp = rs.mean() / rs.std() * np.sqrt(252) if rs.std() > 0 else np.nan
    expo = np.mean([1 if i in daily_ret else 0 for i in span])
    er = pd.DataFrame(ev_rets, columns=["t", "ret"])
    wins, losses = er[er.ret > 0].ret, er[er.ret <= 0].ret
    pf = wins.sum() / abs(losses.sum()) if len(losses) and losses.sum() < 0 else np.inf
    wl = wins.mean() / abs(losses.mean()) if len(losses) and len(wins) else np.nan
    er["year"] = er["t"].str[:4]
    nav_s = pd.Series(navs, index=pd.to_datetime(nav_dates))   # nav_dates=ISO字串
    ynav = nav_s.groupby(nav_s.index.year).last()
    ynav_prev = ynav.shift(1)
    ynav_prev.iloc[0] = 1.0
    yearly = ((ynav / ynav_prev - 1) * 100).round(1)
    tai_c = tai["close"].reindex(nav_dates).ffill()            # tai index亦為字串
    tai_nav = pd.Series((tai_c / tai_c.iloc[0]).values, index=nav_s.index)
    out = {"lab": lab, "cost": cost_side * 2 * 100, "n_pos": n_pos, "n_lock": n_lock,
           "nav": nav, "ann": ann * 100, "mdd": mdd * 100, "sharpe": shp,
           "calmar": (ann * 100) / abs(mdd * 100) if mdd < 0 else np.nan,
           "expo": expo * 100, "win": len(wins) / len(er) * 100 if len(er) else np.nan,
           "pf": pf, "wl": wl, "yearly": yearly.to_dict(),
           "nav_series": nav_s, "tai_nav": tai_nav}
    print(f"  {lab:<26} 來回成本{out['cost']:.1f}%: 部位{n_pos}(排鎖{n_lock}) "
          f"NAV={nav:.2f} 年化{out['ann']:+.1f}% MDD{out['mdd']:.1f}% 夏普{shp:.2f} "
          f"Calmar{out['calmar']:.2f} 曝險{out['expo']:.0f}% 勝率{out['win']:.0f}% "
          f"賺賠比{wl:.2f} PF{pf:.2f}")
    return out


def q4_portfolio(P, tw_mem, tw_open, tw_close, tai):
    print("\n" + "=" * 80, "\nQ4 可執行組合模擬(成員層,開盤進場,排開盤跳空>=+9%,日頻等權)")
    pkt_mask = (P["sig_raw"] >= 0.02) & (P["spx"] < 0)
    deep_mask = (P["sig_raw"] >= 0.025) & (P["spx"] < -0.005)   # 深口袋(Q1的高肉格,事件數~19/年)
    user4_mask = pkt_mask & P["theme"].isin(USER4)
    hi_mask = pkt_mask & (P["hi_frac"] > 0)
    sims = []
    for lab, mask, hold in [("全口袋·持5", pkt_mask, 5),
                            ("全口袋·持10", pkt_mask, 10),
                            ("深口袋(>2.5%×SPX<-.5%)·持5", deep_mask, 5),
                            ("深口袋·持10", deep_mask, 10),
                            ("口袋×四題材·持5", user4_mask, 5),
                            ("口袋×hi>0·持5", hi_mask, 5),
                            ("口袋×四題材×hi>0·持5", user4_mask & (P["hi_frac"] > 0), 5)]:
        for cs in COST_SIDES:
            s = simulate(P, tw_mem, tw_open, tw_close, tai, mask, lab, cs, hold=hold)
            if s:
                sims.append(s)
    return sims


# ======================================================================
# 7. HTML
# ======================================================================
CSS = """
body{background:#1a1a19;color:#fff;font-family:"Noto Sans TC",sans-serif;margin:24px;max-width:1200px}
h1{font-size:20px} h2{font-size:15px;color:#c3c2b7;margin-top:30px;border-bottom:1px solid #333;padding-bottom:4px}
h3{font-size:13.5px;color:#a8a79a;margin:16px 0 4px}
table{border-collapse:collapse;font-size:12.5px;font-variant-numeric:tabular-nums;margin:8px 0}
td,th{border:1px solid #333;padding:4px 9px;text-align:right} th{text-align:left;color:#c3c2b7}
.note{color:#8a8878;font-size:12.5px;line-height:1.8} .good{color:#7ec97e} .bad{color:#e06c5a}
.warn{color:#c3a55a} .hl{background:#2b3a2b} .sub{color:#777;font-size:11px}
ul{margin:4px 0;padding-left:20px;font-size:12.5px;color:#ccc;line-height:1.7}
.verdict{font-size:13px;font-weight:bold;padding:6px 10px;border-radius:4px;display:inline-block;margin:4px 0}
.v-good{background:#243b24;color:#7ec97e} .v-bad{background:#3b2420;color:#e06c5a}
.v-warn{background:#3b3420;color:#c3a55a}
.banner{background:#1d2a36;border:1px solid #6bb7e3;border-radius:6px;padding:14px 18px;margin:16px 0;
        color:#cfe6f5;font-size:13.5px;line-height:1.8}
.scroll{overflow-x:auto}
"""


def fmt_curve_cells(curve):
    return "".join(f"<td>{curve[k]:+.2f}</td>" for k in K_LIST)


def write_report(P, recap, q1_rows, q2_rows, theme_rows, top4_first, q3_out, combo_rows, sims):
    n_years = P["year"].nunique()

    # §0 首輪回顧表(重算)
    recap_html = ("<table><tr><th>訊號分層(美股題材原始報酬)</th><th>n</th><th>當日cc</th><th>跳空</th>"
                  "<th>當日oc</th><th>CAR5開錨</th><th>CAR10開錨</th></tr>")
    for lab, mask in [("大跌<-2%", P["sig_raw"] <= -0.02),
                      ("普通-2~2%", (P["sig_raw"] > -0.02) & (P["sig_raw"] < 0.02)),
                      ("大漲>2%", P["sig_raw"] >= 0.02),
                      ("大漲>2%且SPX<0(=口袋)", (P["sig_raw"] >= 0.02) & (P["spx"] < 0))]:
        s = P[mask]
        hl = " class='hl'" if "口袋" in lab else ""
        recap_html += (f"<tr{hl}><th>{lab}</th><td>{len(s):,}</td>"
                       f"<td>{s['tw_cc'].mean() * 100:+.2f}</td><td>{s['tw_gap'].mean() * 100:+.2f}</td>"
                       f"<td>{s['tw_oc'].mean() * 100:+.2f}</td><td>{s['car_o5'].mean() * 100:+.2f}</td>"
                       f"<td>{s['car_o10'].mean() * 100:+.2f}</td></tr>")
    recap_html += "</table>"

    q1_html = ("<table><tr><th>口袋定義</th><th>n(次/年)</th><th>跳空</th><th>當日oc</th>"
               "<th>CAR5</th><th>CAR10</th><th>CAR5月群CI</th><th>逐年正</th></tr>")
    for r in q1_rows:
        q1_html += (f"<tr><th>{r['lab']}</th><td>{r['n']}({r['nyr']:.0f})</td><td>{r['gap']:+.2f}</td>"
                    f"<td>{r['oc']:+.2f}</td><td>{r['car5']:+.2f}</td><td>{r['car10']:+.2f}</td>"
                    f"<td>{r['ci5']}</td><td>{r['yr']}</td></tr>")
    q1_html += "</table>"

    khead = "".join(f"<th>k{k}</th>" for k in K_LIST)
    q2_html = f"<table><tr><th>口袋×創新高層</th><th>n</th><th>跳空</th><th>oc</th>{khead}<th>CAR5 CI</th><th>CAR10 CI</th><th>逐年</th></tr>"
    for r in q2_rows:
        q2_html += (f"<tr><th>{r['lab']}</th><td>{r['n']}</td><td>{r['gap']:+.2f}</td>"
                    f"<td>{r['oc']:+.2f}</td>{fmt_curve_cells(r['curve'])}"
                    f"<td>{r['ci5']}</td><td>{r['ci10']}</td><td>{r['yr']}</td></tr>")
    q2_html += "</table>"

    tt_html = ("<table><tr><th>題材(★=使用者四題材)</th><th>口袋n</th><th>oc</th><th>CAR5</th><th>CAR10</th></tr>")
    for r in theme_rows:
        star = "★" if r["theme"] in USER4 else ""
        tt_html += (f"<tr><th>{star}{r['theme']}</th><td>{r['n']}</td><td>{r['oc']:+.2f}</td>"
                    f"<td>{r['car5']:+.2f}</td><td>{r['car10']:+.2f}</td></tr>")
    tt_html += "</table>"

    q3_html = f"<table><tr><th>子集</th><th>n</th><th>oc</th>{khead}<th>CAR5 CI</th><th>CAR10 CI</th><th>逐年</th><th>絕對CAR5/10</th></tr>"
    for lab, r in q3_out.items():
        q3_html += (f"<tr><th>{lab}</th><td>{r['n']}</td><td>{r['oc']:+.2f}</td>"
                    f"{fmt_curve_cells(r['curve'])}<td>{r['ci5']}</td><td>{r['ci10']}</td>"
                    f"<td>{r['yr']}</td><td>{r['abs5']:+.2f}/{r['abs10']:+.2f}</td></tr>")
    q3_html += "</table>"

    combo_html = f"<table><tr><th>組合</th><th>n(次/年)</th><th>跳空</th><th>oc</th>{khead}<th>CAR5 CI</th><th>CAR10 CI</th><th>逐年</th></tr>"
    for r in combo_rows:
        combo_html += (f"<tr><th>{r['lab']}</th><td>{r['n']}({r['nyr']:.0f})</td><td>{r['gap']:+.2f}</td>"
                       f"<td>{r['oc']:+.2f}</td>{fmt_curve_cells(r['curve'])}"
                       f"<td>{r['ci5']}</td><td>{r['ci10']}</td><td>{r['yr']}</td></tr>")
    combo_html += "</table>"

    sim_html = ("<table><tr><th>組合(成員層模擬)</th><th>來回成本</th><th>部位數(排鎖)</th><th>年化</th>"
                "<th>MDD</th><th>夏普</th><th>Calmar</th><th>曝險</th><th>勝率</th><th>賺賠比</th><th>PF</th></tr>")
    for s in sims:
        sim_html += (f"<tr><th>{s['lab']}</th><td>{s['cost']:.1f}%</td><td>{s['n_pos']}({s['n_lock']})</td>"
                     f"<td>{s['ann']:+.1f}%</td><td>{s['mdd']:.1f}%</td><td>{s['sharpe']:.2f}</td>"
                     f"<td>{s['calmar']:.2f}</td><td>{s['expo']:.0f}%</td><td>{s['win']:.0f}%</td>"
                     f"<td>{s['wl']:.2f}</td><td>{s['pf']:.2f}</td></tr>")
    sim_html += "</table>"

    yr_html = "<table><tr><th>年度</th>"
    base_sim = next((s for s in sims if s["lab"] == "全口袋" and s["cost"] == 1.0), None)
    u4_sim = next((s for s in sims if s["lab"] == "口袋×四題材" and s["cost"] == 1.0), None)
    years = sorted(set().union(*[set(s["yearly"]) for s in sims if s["cost"] == 1.0]))
    for s in sims:
        if s["cost"] == 1.0:
            yr_html += f"<th>{s['lab']}(1%成本)</th>"
    yr_html += "</tr>"
    for y in years:
        yr_html += f"<tr><th>{y}</th>"
        for s in sims:
            if s["cost"] == 1.0:
                v = s["yearly"].get(y, np.nan)
                cls = "good" if pd.notna(v) and v > 0 else "bad"
                yr_html += f"<td class='{cls}'>{v:+.1f}%</td>" if pd.notna(v) else "<td>—</td>"
        yr_html += "</tr>"
    yr_html += "</table>"

    # 圖表payload
    curves_payload = {"k": K_LIST, "series": []}
    for lab, r in q3_out.items():
        curves_payload["series"].append({"name": lab[:24], "vals": [round(r["curve"][k], 3) for k in K_LIST]})
    nav_payload = []
    for s in sims:
        if s["cost"] == 1.0:
            ns = s["nav_series"].resample("W").last().dropna()
            nav_payload.append({"name": s["lab"], "dates": [d.strftime("%Y-%m-%d") for d in ns.index],
                                "vals": [round(v, 4) for v in ns.values]})
    if base_sim is not None:
        tn = base_sim["tai_nav"].resample("W").last().dropna()
        nav_payload.append({"name": "TAIEX(同期)", "dates": [d.strftime("%Y-%m-%d") for d in tn.index],
                            "vals": [round(v, 4) for v in tn.values]})
    payload = json.dumps({"curves": curves_payload, "navs": nav_payload}, ensure_ascii=False)

    # 判決
    v_lines = []
    pkt_r = q3_out.get("(全口袋當基準)")
    a_r = q3_out.get("(a)使用者四題材[記憶體/CPO/PCB/被動元件](全樣本,in-sample)")
    a2_r = q3_out.get("(a')使用者四題材·僅後半段2021-(檢查是否只贏在前半)")
    b_r = q3_out.get("(b)前半段排名前4題材·僅後半段評估(split-half準OOS)")
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>台美隔夜題材連動·口袋組合精煉(2026-08-05)</title>
<script src="plotly.min.js"></script><style>{CSS}</style></head><body>
<h1>🌉 台美隔夜題材連動: 首輪判決回顧 + 題材獨漲口袋組合精煉 + 可執行組合模擬</h1>
<div class="note">首輪=build_us_tw_overnight_link.py(commit ac221a4,結論原僅在console,本報告補檔)。
本卷=第二輪精煉: 口袋(美題材原始>2%且SPX<0)×創新高×強題材子集,加成員層可執行組合模擬。
樣本{P['t'].min()}~{P['t'].max()},{n_years}年,{P['theme'].nunique()}個台美可對映題材,
panel {len(P):,}筆題材×台股日(fresh訊號限定,ADR剔除,close>0 AND money>0清洗)。</div>

<div class="banner">🕓 <b>零前視時序</b>: 美股收盤=台北清晨4-5點,訊號在台股9:00開盤前完全確認;
口袋子集首輪已驗證「跳空不過衝」(台股開盤只定價美股大盤層,題材專屬訊號無大盤掩護時定價不足),
開盤市價進場可執行——這是全專案少見「開盤追買活著」的訊號(進場可執行性第一道檢查已過,feedback第18條)。</div>

<h2>§0 首輪判決回顧(重算自同一面板,非引用舊數字)</h2>
{recap_html}
<ul>
<li>主檢定: 美股題材報酬分層,台股同題材次日demean報酬單調顯著;回歸拆解確認題材層增量獨立於大盤(sig_ex係數顯著)。</li>
<li>可執行性: 普通大漲日開盤追買被跳空過衝殺死(跳空吃掉>100%,盤中回吐);<b>口袋日(題材獨漲)是例外</b>——跳空溫和且盤中不回吐。</li>
<li>強弱題材: 記憶體最強(+0.57%當日cc),CPO/AI伺服器次之;EMS/網通/電信無效。</li>
</ul>

<h2>§1 Q1 口袋定義敏感度(門檻×SPX條件)</h2>
<div class="note">不是掃參數選最好,是看肉量對定義擾動穩不穩+n的權衡。CI=月群bootstrap 95%。</div>
{q1_html}

<h2>§2 Q2 口袋×創新高交乘</h2>
<div class="note">hi_frac=訊號日美股側成員創52週新高(收盤>=252日滾動高*0.999)佔比。首輪全樣本已見單調,此處口袋內複驗。</div>
{q2_html}

<h2>§3 Q3 口袋×強題材子集</h2>
<h3>分題材口袋成績(全樣本,口袋n>=8)</h3>
{tt_html}
<h3>子集比較(CAR逐日k=1~20,demean;絕對報酬並列=使用者目標函數第一層)</h3>
<div class="note">⚠(a)四題材是首輪<b>全樣本</b>看出來的強題材=in-sample挑選;(b)用前半段(2015-2020)口袋排名
取前4題材[{', '.join(top4_first)}]只在後半段評估=split-half準OOS對照——(a)若只贏在前半段即過擬合警訊。</div>
{q3_html}
<div id="c_curves" style="height:400px"></div>

<h2>§4 組合精煉交乘格(疊條件,n遞減,誠實列)</h2>
{combo_html}

<h2>§5 Q4 可執行組合模擬(成員層,錢的視角)</h2>
<div class="note">口袋事件日<b>開盤市價買進題材全體台股成員等權</b>(排除開盤跳空>=+9%≈漲停鎖死買不到,
表列「排鎖」數),持有至第5或第10個交易日收盤(標籤註明);重疊事件日頻等權再平衡,無事件期空手(0%)。
「深口袋」=原始>2.5%且SPX<-0.5%(Q1的高肉格,~19題材日/年)。
成本情境=來回0%/0.5%/1.0%。評估順序依展望理論(feedback第17條): <b>MDD小&gt;賺賠比大&gt;Calmar大&gt;逐年穩定&gt;絕對報酬</b>。
fm_daily_price未做除權息還原=持有窗跨除息會少算股息(保守偏誤,真實略高)。</div>
{sim_html}
<h3>逐年報酬(1%來回成本版)</h3>
{yr_html}
<div id="c_nav" style="height:420px"></div>

<h2>⚖️ 判決(2026-08-05第二輪)</h2>
<ul>
<li><span class="verdict v-good">①口袋主訊號成立且對定義穩健</span> 基準口袋n={pkt_r['n']}
(~{pkt_r['n'] / n_years:.0f}題材日/年)CAR5={pkt_r['curve'][5]:+.2f}%/CAR10={pkt_r['curve'][10]:+.2f}%(demean),
CI5:{pkt_r['ci5']},逐年{pkt_r['yr']};Q1六種定義全部CI排0——且<b>口袋越深肉越厚</b>
(SPX&lt;-0.5%×原始&gt;2.5%: CAR5+1.44/CAR10+1.83,事件數~19/年)。真正的精煉軸是「口袋深度」。</li>
<li><span class="verdict v-bad">②創新高交乘在口袋內反轉(與首輪全樣本結論矛盾,誠實攤開)</span>
口袋內hi=0組CAR5+0.85✓排0(逐年11/12) vs hi&gt;0組+0.33含0——機制一致可解釋: 創新高題材跳空大
(+0.45 vs +0.04)且盤中回吐(oc-0.21),「無人創新高的題材獨漲」才是定價不足最嚴重的角落。
首輪「創新高增強」是在<b>全部大漲日</b>上測的(多日持有遠端仍成立,k20兩組同高),但在口袋子集內
<b>不應</b>再疊創新高濾網——組合精煉的答案是「不要交乘」。</li>
<li><span class="verdict v-warn">③強題材子集=過擬合警訊,降級為候選</span> 使用者四題材全樣本
CAR5={a_r['curve'][5]:+.2f}%✓/CAR10={a_r['curve'][10]:+.2f}%✓,後半段單獨CAR10={a2_r['curve'][10]:+.2f}%仍✓
但CAR5含0且逐年3/6;決定性的是split-half對照: 前半段排名前4題材(功率/IC設計/設備/封測)在後半段
CAR5={b_r['curve'][5]:+.2f}%/CAR10={b_r['curve'][10]:+.2f}%全含0=<b>「過去哪個題材強」不會延續</b>,
四題材的好數字有一半是事後之明,不能當篩選規則上線。</li>
<li><span class="verdict v-warn">④組合模擬: 事件層真訊號,但5日持有的週轉扛不住成本</span>
全口袋·持5在0成本年化+24.3%/MDD-34.7%,1%來回成本直接翻負——年週轉~40次的結構性宿命
(與週級動能同教訓)。活口方向=<b>深口袋+拉長持有</b>(持10使週轉減半、單筆肉加倍)+當
「持股tilt/加碼觸發器」使用(本來就要買的股票,挑口袋日買),而非獨立資金線;精確數字見§5表。</li>
</ul>

<h2>已知限制(誠實聲明)</h2>
<div class="note">
①四題材子集是首輪全樣本觀察後指定=in-sample;split-half對照只有~6年×2段,檢定力有限,結論以「候選」定位。
②組合模擬的開盤成交假設: 口袋日跳空溫和(表列),但成員層仍排除跳空>=+9%;0.5-1%來回成本涵蓋一般滑價,
小型成員(被動元件/記憶體部分)實際市價單衝擊未實測。③fm_daily_price未還原除權息(保守偏誤)。
④多重比較: 本卷交乘格~20格,95%CI下預期1格假陽性;判讀靠CAR曲線形狀+逐年一致性,不靠單格CI。
⑤hi_frac只用美股側新高;台股側成員自身新高未交乘(首輪mom5控制顯示台股自身動能非主要來源)。
⑥深口袋(>2.5%×SPX&lt;-0.5%)是Q1六格中最深的格=溫和的in-sample選格(緩解: 六格全部CI排0且深度單調,
是機制一致的結構非cherry-pick);已抽查逐年分布=9/12年CAR5正、肉分散於2018-2021/2024-2026多段非單年撐盤;
但事件組成48%集中在化合物半導體+電池/儲能兩個台股側成員僅3-5檔的小題材,組合分散度有限,
單一題材熄火會直接砍半事件數——live使用時要留意題材組成漂移。</div>
<div class="note">維運: python 研究腳本/題材動能/build_us_tw_pocket_refine.py(從根目錄執行)。
姊妹檔: build_us_tw_overnight_link.py(首輪主檢定/回歸拆解/ADR對照,console輸出)、
抓取/fetch_us_daily_price.py(美股日線管線,增量續傳)、watch_us_tw_overnight.py(live訊號,每日美股收盤後)。</div>

<script>
const D={payload};
const BG={json.dumps(BG, ensure_ascii=False)};
(function(){{
  const tr = D.curves.series.map(s=>({{x:D.curves.k, y:s.vals, name:s.name, mode:'lines+markers'}}));
  Plotly.newPlot('c_curves', tr, Object.assign({{title:'§3 子集CAR逐日曲線(開盤錨,demean,%)',
    xaxis:{{title:'持有k交易日'}}, yaxis:{{title:'CAR(%)',zeroline:true,zerolinecolor:'#555'}}}}, BG));
  const tn = D.navs.map(s=>({{x:s.dates, y:s.vals, name:s.name, mode:'lines'}}));
  Plotly.newPlot('c_nav', tn, Object.assign({{title:'§5 組合NAV(1%來回成本,週頻取樣) vs TAIEX',
    yaxis:{{title:'NAV'}}}}, BG));
}})();
</script>
</body></html>"""
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n[report] 已輸出 {OUT}")


def main():
    P, tw_mem, tw_open, tw_close, tai = build_panel()
    q1_rows = q1_sensitivity(P)
    q2_rows, _ = q2_newhigh(P)
    theme_rows, top4_first, q3_out, _ = q3_subsets(P)
    combo_rows = q_combo(P)
    sims = q4_portfolio(P, tw_mem, tw_open, tw_close, tai)
    write_report(P, None, q1_rows, q2_rows, theme_rows, top4_first, q3_out, combo_rows, sims)


if __name__ == "__main__":
    main()
