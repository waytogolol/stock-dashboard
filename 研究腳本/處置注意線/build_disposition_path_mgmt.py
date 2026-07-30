# -*- coding: utf-8 -*-
"""處置V4持有窗內路徑管理考卷(使用者2026-07-25提案):
「走勢偏離標準走勢該停損還是加碼攤平?有沒有加減碼機制讓損益更平滑?」

先驗誠實申報(不利攤平):
  - 加碼假說(tmp_addon_sim.py)=否定,day0滿倉最優,等回檔=系統性少賺飆股
  - 處置窗內「回吐長黑買回」5分盤反向否定(考卷1,繼續流血)
  - 分級bail已知: 5分盤持有中遇回吐日尾盤跑+0.78pp;20分盤抱到出關,跑反而差
  預期: 停損在5分盤有機會加分、20分盤干預有害、攤平兩級別皆不利——弱結果不得敘事成正面。

設計(預註冊):
- 母體: V4口徑(第3處置日收盤買c[s+2]→出關次日開盤賣o[en+1],6<=en-s<=25,成本0.45%/單位往返),
  match_min 5/20分層永不合併;觸發一律「當日收盤觀察、同收盤執行」(樂觀假設,與candle fade考卷同慣例)
- 分析0(核心診斷): 首次跌破cum<=-X%後「剩餘段」(觸發收盤→出關開盤)條件報酬——
  負=停損對/正=攤平對/≈0=都無所謂;正向+X%同表(強勢延續性)
- 規則家族(每筆與baseline配對差;headline=X:-10%事前指定,其餘網格=劑量反應描述):
  F1 固定停損: cum<=-X%收盤出場, X∈{5,8,10,15}
  F2 攤平加碼: cum<=-X%加碼1單位持有到出關,報已投入資本加權報酬, X∈{5,8,10,15}
  F3 停利減碼: cum>=+X%出一半, X∈{8,15}
  F4 偏離bail: 每日(own cum - cohort同k日中位)<=-X pp收盤出場, X∈{5,8,10}
     (cohort路徑=全樣本中位=輕度前視,標註;與F1對照看「相對偏離」是否優於「絕對虧損」)
  F5 強勢加碼(對照): cum>=+3%首日加碼1單位——與F2對決「加在強vs加在弱」
- 驗證: headline規則配對差(rule-base)均值 年群cluster bootstrap+LOTO(均值口徑:未觸發筆差=0,
  中位數會退化為0不可用,預先聲明);觸發子集內另報中位差
- 平滑度: 單筆std/P5尾部/依進場日時序單利equity的MDD與年度Σ——使用者目標=損益平滑,
  允許「中位小輸但尾部大砍」的結論
- 標準走勢輸出: 每match_min逐k日cohort中位/P25/P75(k=0..20)存tmp_disposition_path_cohort.pkl
  (供K棒檢視器/未來live比對用)
用法: python -X utf8 build_disposition_path_mgmt.py
"""
import sqlite3
import sys
import time

import numpy as np
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DB = "capital_flow.db"
COST = 0.45
PANEL_OUT = "快取/tmp_disposition_path_panel.pkl"
COHORT_OUT = "快取/tmp_disposition_path_cohort.pkl"
STOP_XS = [5, 8, 10, 15]
TAKE_XS = [8, 15]
DEV_XS = [5, 8, 10]
HEAD_X = 10          # headline停損/攤平門檻(事前指定)
ADD_STRONG = 3       # F5強勢加碼門檻
B_BOOT = 10000
SEED = 42


def read_sql_retry(sql, tries=4, wait=3):
    for i in range(tries):
        try:
            conn = sqlite3.connect(DB, timeout=30)
            df = pd.read_sql(sql, conn)
            conn.close()
            return df
        except sqlite3.OperationalError as e:
            if "locked" in str(e) and i < tries - 1:
                time.sleep(wait)
            else:
                raise


def dstat(x, lab, pref="    "):
    x = pd.Series(x).dropna()
    if len(x) < 10:
        print(f"{pref}{lab}: n={len(x)}太少")
        return None
    print(f"{pref}{lab}: 中位{x.median():+6.2f}% 均值{x.mean():+6.2f}% 勝率{(x > 0).mean() * 100:3.0f}% "
          f"std{x.std():5.2f} P5={x.quantile(0.05):+6.2f}% n={len(x):,}")
    return x


def paired_test(df, diff_col, label, b=B_BOOT, seed=SEED):
    """配對差(rule-base)均值: LOTO逐年+年群cluster bootstrap。未觸發筆diff=0屬設計內。"""
    d = df.dropna(subset=[diff_col])
    years = sorted(d.y.unique())
    if len(d) < 30 or len(years) < 3:
        print(f"      [{label}] n={len(d)}或年份不足,略過")
        return
    rows = []
    for yr in years:
        s2 = d[d.y != yr]
        if len(s2) >= 20:
            rows.append((yr, s2[diff_col].mean()))
    rows.sort(key=lambda r: r[1])
    pos = sum(1 for _, v in rows if v > 0)
    print(f"      配對差均值LOTO最壞: 剔{rows[0][0]}後{rows[0][1]:+.2f}pp, 為正{pos}/{len(rows)}年")
    rng = np.random.default_rng(seed)
    groups = {yr: d.loc[d.y == yr, diff_col].values for yr in years}
    means = []
    for _ in range(b):
        pick = rng.choice(years, size=len(years), replace=True)
        arr = np.concatenate([groups[yr] for yr in pick])
        if len(arr) >= 20:
            means.append(arr.mean())
    means = np.array(means)
    lo, hi = np.percentile(means, [2.5, 97.5])
    print(f"      配對差均值bootstrap(B={len(means)}): CI95=[{lo:+.2f},{hi:+.2f}]pp "
          f"P(<=0)={(means <= 0).mean():.4f} P(>=0)={(means >= 0).mean():.4f}")


def equity_smooth(df, col, lab):
    """依進場日時序單利equity: 總和/最深回撤/年度Σ波動。"""
    d = df.dropna(subset=[col]).sort_values("entry_date")
    eq = d[col].cumsum()
    mdd = (eq - eq.cummax()).min()
    yr_sum = d.groupby("y")[col].sum()
    print(f"    {lab}: Σ={eq.iloc[-1]:+8.1f}pp  equityMDD={mdd:+7.1f}pp  "
          f"年Σ std={yr_sum.std():6.1f}  最差年={yr_sum.min():+7.1f}({yr_sum.idxmin()})")


def main():
    disp = read_sql_retry("SELECT * FROM disposition")
    px = read_sql_retry("SELECT code, date, open, close FROM fm_daily_price ORDER BY code, date")
    for c in ("start_date", "end_date"):
        disp[c] = pd.to_datetime(disp[c], errors="coerce")
    disp = disp.dropna(subset=["start_date", "end_date"]).reset_index(drop=True)
    px["date"] = pd.to_datetime(px["date"])
    stocks = {c: g.sort_values("date").reset_index(drop=True) for c, g in px.groupby("code")}

    # ---------- 建路徑面板 ----------
    rows = []
    for ev_id, e in disp.iterrows():
        g = stocks.get(e.code)
        if g is None:
            continue
        dts = g["date"].values
        n = len(g)
        s = int(np.searchsorted(dts, np.datetime64(e.start_date)))
        en = int(np.searchsorted(dts, np.datetime64(e.end_date), side="right") - 1)
        if s >= n or en <= s or en - s > 25 or en - s < 6 or en + 1 >= n:
            continue
        c_, o_ = g["close"].values, g["open"].values
        entry_i = s + 2
        if c_[entry_i] <= 0 or o_[en + 1] <= 0:
            continue
        closes = c_[entry_i:en + 1].astype(float)
        tradable = closes > 0  # 無成交日close=0: 不可觀察也不可執行
        ff = pd.Series(closes).replace(0, np.nan).ffill().values  # 前值填補只用於畫cum
        cum = (ff / ff[0] - 1.0) * 100  # k=0..K, k0=0
        rows.append({
            "event_id": ev_id, "code": e.code, "match_min": str(e.match_min),
            "y": int(pd.Timestamp(e.start_date).year), "entry_date": g["date"].iloc[entry_i],
            "entry_px": float(ff[0]), "exit_open": float(o_[en + 1]),
            "cum": cum, "closes": ff, "tradable": tradable, "K": len(cum) - 1,
        })
    pn = pd.DataFrame(rows)
    pn["base"] = (pn.exit_open / pn.entry_px - 1) * 100 - COST
    print(f"V4路徑面板: n={len(pn):,} (5分={len(pn[pn.match_min == '5']):,}/20分={len(pn[pn.match_min == '20']):,}); "
          f"baseline全池中位{pn.base.median():+.2f}%")

    # ---------- cohort標準走勢 ----------
    cohort = {}
    print("\n== 標準走勢(cohort逐k日cum%,k=交易日距進場) ==")
    for mm in ["5", "20"]:
        sub = pn[pn.match_min == mm]
        recs = []
        for k in range(0, 21):
            vals = np.array([r[k] for r in sub.cum if len(r) > k])
            if len(vals) >= 30:
                recs.append({"k": k, "n": len(vals), "med": np.median(vals),
                             "p25": np.percentile(vals, 25), "p75": np.percentile(vals, 75)})
        cf = pd.DataFrame(recs)
        cohort[mm] = cf
        line = " ".join(f"k{int(r.k)}:{r.med:+.1f}" for r in cf.itertuples() if r.k in (1, 2, 3, 5, 7, 10, 15, 20))
        print(f"  {mm}分盤 中位路徑: {line}")
        print(f"          P25路徑:  " + " ".join(
            f"k{int(r.k)}:{r.p25:+.1f}" for r in cf.itertuples() if r.k in (1, 2, 3, 5, 7, 10, 15, 20)))
    pd.to_pickle(cohort, COHORT_OUT)

    # ---------- 分析0: 偏離後剩餘段條件報酬 ----------
    print("\n" + "=" * 72)
    print("分析0(核心診斷): 首次觸及cum門檻後,剩餘段(觸發收盤→出關開盤)毛報酬")
    print("  判讀: 顯著負=停損對 / 顯著正=攤平有肉 / ≈0=砍不砍都行(資金效率決定)")
    print("=" * 72)
    for mm in ["5", "20"]:
        sub = pn[pn.match_min == mm]
        print(f"  -- {mm}分盤 (n={len(sub):,}, baseline中位{sub.base.median():+.2f}%) --")
        for x in [-5, -8, -10, -15, 3, 8, 15]:
            rem, trig_day = [], []
            for r in sub.itertuples():
                hit = None
                for k in range(1, r.K + 1):
                    if r.tradable[k] and ((x < 0 and r.cum[k] <= x) or (x > 0 and r.cum[k] >= x)):
                        hit = k
                        break
                if hit is not None:
                    rem.append((r.exit_open / r.closes[hit] - 1) * 100)
                    trig_day.append(hit)
            lab = f"cum{'<=' if x < 0 else '>='}{x:+d}%"
            if len(rem) >= 10:
                rr = pd.Series(rem)
                print(f"    {lab:12s}: 觸發{len(rem):4d}筆({len(rem) / len(sub) * 100:4.1f}%,中位觸發日k={int(np.median(trig_day))}) "
                      f"剩餘段 中位{rr.median():+6.2f}% 均值{rr.mean():+6.2f}% 勝率{(rr > 0).mean() * 100:3.0f}%")
            else:
                print(f"    {lab:12s}: 觸發{len(rem)}筆太少")

    # ---------- 規則模擬 ----------
    def simulate(sub, mm):
        out = {"base": sub.base.values}
        med_path = cohort[mm].set_index("k")["med"]
        f1 = {x: [] for x in STOP_XS}
        f2 = {x: [] for x in STOP_XS}
        f2b = {x: [] for x in STOP_XS}
        f2_trig = {x: [] for x in STOP_XS}
        f3 = {x: [] for x in TAKE_XS}
        f4 = {x: [] for x in DEV_XS}
        f5, f5_trig, combo = [], [], []
        for r in sub.itertuples():
            u1 = r.base

            def first_hit(cond):
                return next((k for k in range(1, r.K + 1) if r.tradable[k] and cond(k)), None)

            # F1/F2/F2b 同觸發點
            for x in STOP_XS:
                hit = first_hit(lambda k: r.cum[k] <= -x)
                if hit is None:
                    f1[x].append(u1)
                    f2[x].append(u1)
                    f2b[x].append(u1 / 2)  # 等本金: 預留的一半整趟閒置
                    f2_trig[x].append(False)
                else:
                    f1[x].append((r.closes[hit] / r.entry_px - 1) * 100 - COST)
                    u2 = (r.exit_open / r.closes[hit] - 1) * 100 - COST
                    f2[x].append((u1 + u2) / 2)
                    f2b[x].append((u1 + u2) / 2)
                    f2_trig[x].append(True)
            for x in TAKE_XS:
                hit = first_hit(lambda k: r.cum[k] >= x)
                if hit is None:
                    f3[x].append(u1)
                else:
                    take = (r.closes[hit] / r.entry_px - 1) * 100 - COST
                    f3[x].append(0.5 * take + 0.5 * u1)
            for x in DEV_XS:
                hit = first_hit(lambda k: k in med_path.index and (r.cum[k] - med_path.loc[k]) <= -x)
                if hit is None:
                    f4[x].append(u1)
                else:
                    f4[x].append((r.closes[hit] / r.entry_px - 1) * 100 - COST)
            hit = first_hit(lambda k: r.cum[k] >= ADD_STRONG)
            if hit is None:
                f5.append(u1)
                f5_trig.append(False)
            else:
                u2 = (r.exit_open / r.closes[hit] - 1) * 100 - COST
                f5.append((u1 + u2) / 2)
                f5_trig.append(True)
            # 探索性組合(未預註冊): +8%出一半 + -10%攤平一單位,各腿獨立結算
            hit_t = first_hit(lambda k: r.cum[k] >= 8)
            hit_a = first_hit(lambda k: r.cum[k] <= -10)
            legs = []
            if hit_t is None:
                legs.append(u1)
            else:
                legs.append(0.5 * ((r.closes[hit_t] / r.entry_px - 1) * 100 - COST) + 0.5 * u1)
            if hit_a is not None:
                legs.append((r.exit_open / r.closes[hit_a] - 1) * 100 - COST)
            combo.append(np.mean(legs))
        for x in STOP_XS:
            out[f"f1_{x}"] = np.array(f1[x])
            out[f"f2_{x}"] = np.array(f2[x])
            out[f"f2b_{x}"] = np.array(f2b[x])
            out[f"f2trig_{x}"] = np.array(f2_trig[x])
        for x in TAKE_XS:
            out[f"f3_{x}"] = np.array(f3[x])
        for x in DEV_XS:
            out[f"f4_{x}"] = np.array(f4[x])
        out["f5"] = np.array(f5)
        out["f5trig"] = np.array(f5_trig)
        out["combo"] = np.array(combo)
        return out

    for mm in ["5", "20"]:
        sub = pn[pn.match_min == mm].reset_index(drop=True)
        sim = simulate(sub, mm)
        for k, v in sim.items():
            if k != "base":
                sub[k] = v
        print("\n" + "#" * 72)
        print(f"## {mm}分盤 規則模擬 (n={len(sub):,})")
        print("#" * 72)
        dstat(sub.base, "baseline持有到出關")
        print("  -- F1 固定停損(收盤跌破-X%出場) --")
        for x in STOP_XS:
            dstat(sub[f"f1_{x}"], f"F1停損-{x}%")
        print("  -- F2 攤平加碼(跌破-X%加1單位,已投入資本加權;未觸發=單單位) --")
        for x in STOP_XS:
            tr = sim[f"f2trig_{x}"].mean() * 100
            dstat(sub[f"f2_{x}"], f"F2攤平-{x}%(觸發{tr:.0f}%)")
        print("  -- F2b 等本金版(day0半倉+觸發攤平到滿;未觸發=半倉閒置一半, 對照=day0滿倉baseline) --")
        for x in STOP_XS:
            dstat(sub[f"f2b_{x}"], f"F2b等本金-{x}%")
        print("  -- F3 停利減碼(漲過+X%出一半) --")
        for x in TAKE_XS:
            dstat(sub[f"f3_{x}"], f"F3停利+{x}%減半")
        print("  -- F4 偏離cohort中位bail(-X pp,全樣本路徑=輕度前視) --")
        for x in DEV_XS:
            dstat(sub[f"f4_{x}"], f"F4偏離-{x}pp出場")
        tr5 = sim["f5trig"].mean() * 100
        dstat(sub["f5"], f"F5強勢加碼+{ADD_STRONG}%(觸發{tr5:.0f}%,對照組)")

        dstat(sub["combo"], "組合[+8%出半∧-10%攤平](探索性未預註冊)")

        print(f"\n  == headline正式驗證(X={HEAD_X}事前指定, 配對差=規則-baseline, 均值口徑) ==")
        for rule in [f"f1_{HEAD_X}", f"f2_{HEAD_X}", f"f2b_{HEAD_X}", "f5"]:
            sub[f"d_{rule}"] = sub[rule] - sub.base
            trig = (sub[f"d_{rule}"].abs() > 1e-9)
            print(f"    [{rule}] 全體配對差均值{sub[f'd_{rule}'].mean():+.2f}pp; "
                  f"觸發子集(n={trig.sum()})內中位差{sub.loc[trig, f'd_{rule}'].median():+.2f}pp")
            paired_test(sub, f"d_{rule}", f"{mm}分 {rule}-base")

        print("\n  == 平滑度(時序單利equity, 1單位/筆) ==")
        equity_smooth(sub, "base", "baseline      ")
        equity_smooth(sub, f"f1_{HEAD_X}", f"F1停損-{HEAD_X}%    ")
        equity_smooth(sub, f"f2_{HEAD_X}", f"F2攤平-{HEAD_X}%    ")
        equity_smooth(sub, f"f2b_{HEAD_X}", f"F2b等本金-{HEAD_X}%  ")
        equity_smooth(sub, f"f3_{TAKE_XS[0]}", f"F3停利+{TAKE_XS[0]}%減半")
        equity_smooth(sub, "f5", "F5強勢加碼+3% ")
        equity_smooth(sub, "combo", "組合(探索)     ")
        sub.drop(columns=["cum", "closes"]).to_pickle(f"快取/tmp_disposition_pathmgmt_{mm}.pkl")

    pn.to_pickle(PANEL_OUT)
    print(f"\n路徑面板存{PANEL_OUT}; cohort路徑存{COHORT_OUT}")


if __name__ == "__main__":
    main()
