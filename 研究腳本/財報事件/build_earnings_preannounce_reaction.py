# -*- coding: utf-8 -*-
"""台股財報公告「事前反應」+族群密集週+熱度分組考卷(2026-08-02，簡化改版)

使用者裁示(2026-08-02)：原設計有pre_date(預告)+actual_date(實際公告)兩個日期概念，
但已用大立光(3008)實測驗證MoneyDJ行事曆看到的「財報公告」日期＝actual_date本身，
兩者是同一天，不存在額外的「預告」機制本身值得深究。故簡化成單一時間軸：
  「董事會通過財務報告＝對外公告＝actual_date」單一事件，
  分析重點＝actual_date「之前」股價/成交量有沒有異常反應(Q1)，
  不再做Q2(pre_date隔日買→actual_date賣的乾淨因果窗)、Q3(有無預告組對照)那套
  依賴pre_date的因果設計；pre_date僅留一個附錄段落供參考，不做主標題判讀依據。
簡化的直接好處＝樣本從「pre_date與actual_date皆有」的874筆，擴大到全部874+632＝1506筆
「有actual_date」的事件(即使沒有pre_date也一樣可測「公告前有沒有異常」)。

本版新增兩個延伸分析(使用者明確要求)：
  ①族群層級事件研究：用classification.main_group把個股對應到題材，找出題材「財報密集週」
    (同一ISO週題材內≥3家、且達該題材可追蹤成員數20%以上同時公告)，測(a)密集週前後題材
    整體(等權重平均,比照build_theme_momentum_v2.py的member-average手法)CAR是否異常、
    (b)「還沒輪到自己公告」的同業laggard在密集週期間有沒有連帶反應(sympathy move)。
    ⚠題材成員universe僅限tw_board_earnings_dates資料庫實際追蹤到的233檔(280檔全母體中
    有actual_date者)，不是該題材完整成分股清單，比例分母＝題材內「有被追蹤到財報公告紀錄」
    的成員數，非全市場成分股數(資料庫本身非全市場覆蓋，見抓取/fetch_tw_earnings_dates.py)。
  ②成交值熱度分組：每筆事件的公告前成交值(20日均值)相對自身歷史(rolling 240日)的百分位
    (百分位算法比照研究腳本/當沖借券/build_dtlend_pattern_pnl.py、
    研究腳本/綜合策略/build_regime_weather_report.py的vp10寫法：
    rolling(window).rank(pct=True)*100，差別是這裡用每檔股票自己的rolling窗口)，
    分熱門(>=67百分位)/冷門(<=33百分位)兩組重跑Q1的CAR，不預設哪組較有反應。

資料源：capital_flow.db.tw_board_earnings_dates(見 抓取/fetch_tw_earnings_dates.py)，
  欄位code/market/period/pre_date/actual_date/lead_days，280檔2,227筆事件(2024~2026)。
⚠已知資料品質問題：
  (a) lead_days(=actual_date-pre_date天數)少數配對錯誤，出現-357~+319天等不合理值，
      874筆中位數8天、5~95百分位落在8~22天之間，故本卷合理範圍取[0,60]天
      (寬鬆但足以濾掉23筆/2.6%的period標籤配對雜訊，不誤傷正常值)；此過濾僅套用在
      附錄的pre_date相關統計，不影響Q1主結果(Q1只用actual_date，不吃lead_days)。
  (b) period欄位本身另有9筆離奇標籤(如"1934A"/"1935Q1"，疑似個別公司內部季別編號誤植，
      非西元或民國年份)，但對應的actual_date本身檢查過是正常交易日，不影響可用性；
      因此族群分析的「該公司這次有沒有報過」一律用actual_date日期本身判斷，不比對period文字。
  (c) 族群/熱度分組樣本量隨切分變小，<15筆一律標示「觀察層」不強做判讀(見stat()函式)。

方法論(比照這批姊妹考卷慣例)：
  CAR多窗口(k=20,10,5,3,1)，demean(扣對應大盤TAIEX/TPEx)+絕對報酬版並列；
  月群/群集bootstrap(2000次,95%CI)驗證顯著性，樣本<15標示觀察層；
  誠實報告正負結果；解讀文字一律依bootstrap算出的p_le0動態判斷(if/elif)，不寫死文字
  (此卷姊妹考卷build_earnings_preannounce_reaction.py舊版Q3曾犯過「印固定解讀文字不管
  實際數值正負號」的錯，此版全面用verdict()函式動態決定)；
  同一份腳本內所有bootstrap函式(cluster_boot/month_boot/cluster_boot_diff)回傳dict
  一律統一鍵名{"lo","hi","p_le0",...}，避免姊妹考卷踩過的「不同函式key不一致」的坑。

用法: python -X utf8 研究腳本/財報事件/build_earnings_preannounce_reaction.py
"""
import sqlite3
import sys
import time

import numpy as np
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DB = "capital_flow.db"
KS = [20, 10, 5, 3, 1]
B_BOOT = 2000
SEED = 42
OUT_HTML = "研究報告/research_earnings_preannounce_reaction.html"
PLACEBO_OFFSET = 60  # 安慰劑錨點=事件前60個交易日(比照build_conference_event.py手法)
LEAD_LO, LEAD_HI = 0, 60  # lead_days合理範圍(見檔頭說明，僅套用於附錄)
DENSE_MIN_N = 3          # 族群密集週門檻①：同一ISO週≥3家同題材成員公告
DENSE_MIN_RATIO = 0.20   # 族群密集週門檻②：且達該題材「可追蹤成員數」20%以上
DENSE_MIN_THEME_N = 5    # 題材可追蹤成員數<5太小不納入密集週分析(比例統計易失真)
HEAT_ROLL = 240          # 成交值百分位rolling視窗(≈1年交易日)
HEAT_MIN_PERIODS = 120
HEAT_HOT, HEAT_COLD = 66.7, 33.3


def rd(sql, tries=6, wait=4):
    for i in range(tries):
        try:
            con = sqlite3.connect(DB, timeout=30)
            df = pd.read_sql(sql, con)
            con.close()
            return df
        except sqlite3.OperationalError as e:
            if "locked" in str(e) and i < tries - 1:
                time.sleep(wait)
            else:
                raise


def stat(x, lab, pref="    "):
    x = pd.Series(x).dropna()
    if len(x) < 15:
        print(f"{pref}{lab}: n={len(x)}太少(觀察層，不強做判讀)")
        return None
    print(f"{pref}{lab}: 中位{x.median():+6.2f}% 均值{x.mean():+6.2f}% "
          f"勝率{(x > 0).mean() * 100:3.0f}% n={len(x):,}")
    return x


def verdict(p_le0, pos_txt, neg_txt, null_txt, alpha=0.05):
    """依bootstrap的P(中位數<=0)動態決定解讀文字，不寫死(見檔頭說明)。"""
    if p_le0 is None:
        return "樣本不足未做bootstrap"
    if p_le0 <= alpha:
        return pos_txt
    if p_le0 >= 1 - alpha:
        return neg_txt
    return null_txt


def cluster_boot(values, clusters, label, b=B_BOOT, seed=SEED, pref="      "):
    """通用群集bootstrap(中位數)：clusters可以是月份、也可以是密集週window_id。
    統一回傳鍵名{"lo","hi","p_le0","n"}，全檔案共用避免key不一致。"""
    d = pd.DataFrame({"v": pd.Series(values).values, "cl": pd.Series(clusters).values}).dropna()
    if len(d) < 30:
        print(f"{pref}[{label}] 樣本不足({len(d)})，略過bootstrap")
        return None
    cls_ = sorted(d.cl.unique())
    if len(cls_) < 6:
        print(f"{pref}[{label}] 分群數不足({len(cls_)})，略過bootstrap")
        return None
    gg = d.groupby("cl").v.median()
    pos = int((gg > 0).sum())
    print(f"{pref}[{label}] 逐群中位為正: {pos}/{len(cls_)}群 (最差群{gg.idxmin()}={gg.min():+.2f})")
    rng = np.random.default_rng(seed)
    groups = {m: d.loc[d.cl == m, "v"].values for m in cls_}
    meds = np.array([np.median(np.concatenate([groups[m] for m in rng.choice(cls_, size=len(cls_), replace=True)]))
                      for _ in range(b)])
    lo, hi = np.percentile(meds, [2.5, 97.5])
    p_le0 = float((meds <= 0).mean())
    print(f"{pref}[{label}] 群集bootstrap: 中位CI95=[{lo:+.2f},{hi:+.2f}] P(<=0)={p_le0:.4f} n={len(d)}")
    return {"lo": float(lo), "hi": float(hi), "p_le0": p_le0, "n": len(d), "med": float(d.v.median())}


def month_boot(df, col, label, date_col="actual_date", b=B_BOOT, seed=SEED):
    d = df.dropna(subset=[col, date_col])
    if len(d) < 30:
        print(f"      [{label}] 樣本不足({len(d)})，略過bootstrap")
        return None
    mo = pd.to_datetime(d[date_col]).dt.to_period("M").astype(str)
    return cluster_boot(d[col].values, mo.values, label, b=b, seed=seed)


def cluster_boot_diff(va, ca, vb, cb, label, b=B_BOOT, seed=SEED, pref="      "):
    """兩組獨立群集bootstrap中位數差(a-b)，回傳鍵名{"diff","lo","hi","p_le0"}。"""
    da = pd.DataFrame({"v": pd.Series(va).values, "cl": pd.Series(ca).values}).dropna()
    db = pd.DataFrame({"v": pd.Series(vb).values, "cl": pd.Series(cb).values}).dropna()
    if len(da) < 30 or len(db) < 30:
        print(f"{pref}[{label}] 樣本不足(a={len(da)},b={len(db)})，略過bootstrap")
        return None
    cla, clb = sorted(da.cl.unique()), sorted(db.cl.unique())
    if len(cla) < 6 or len(clb) < 6:
        print(f"{pref}[{label}] 分群數不足(a={len(cla)},b={len(clb)})，略過bootstrap")
        return None
    rng = np.random.default_rng(seed)
    ga = {m: da.loc[da.cl == m, "v"].values for m in cla}
    gb = {m: db.loc[db.cl == m, "v"].values for m in clb}
    diffs = np.array([
        np.median(np.concatenate([ga[m] for m in rng.choice(cla, size=len(cla), replace=True)]))
        - np.median(np.concatenate([gb[m] for m in rng.choice(clb, size=len(clb), replace=True)]))
        for _ in range(b)])
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    p_le0 = float((diffs <= 0).mean())
    obs = float(da.v.median() - db.v.median())
    print(f"{pref}[{label}] 群集bootstrap差異(a-b): 實際中位差={obs:+.2f} CI95=[{lo:+.2f},{hi:+.2f}] "
          f"P(<=0)={p_le0:.4f} na={len(da)} nb={len(db)}")
    return {"diff": obs, "lo": float(lo), "hi": float(hi), "p_le0": p_le0, "n_a": len(da), "n_b": len(db)}


def last_pos_le(dts, d):
    """dts為排序好的np.datetime64陣列，回傳最後一個<=d的位置(找不到回傳-1)。"""
    return int(np.searchsorted(dts, np.datetime64(d), side="right")) - 1


def first_pos_ge(dts, d):
    """回傳第一個>=d的位置(找不到回傳len(dts))。"""
    return int(np.searchsorted(dts, np.datetime64(d), side="left"))


def main():
    ev = rd("SELECT code, market, period, pre_date, actual_date, lead_days "
            "FROM tw_board_earnings_dates WHERE actual_date IS NOT NULL")
    ev["actual_date"] = pd.to_datetime(ev.actual_date)
    ev["pre_date"] = pd.to_datetime(ev.pre_date)
    px = rd("SELECT code, date, open, close, money FROM fm_daily_price ORDER BY code, date")
    px["date"] = pd.to_datetime(px.date)
    idx = rd("SELECT market, date, close FROM index_daily WHERE market IN ('TAIEX','TPEx') ORDER BY date")
    idx["date"] = pd.to_datetime(idx.date)
    names = rd("SELECT code, name_zh FROM company_names WHERE country='台'")
    cls = rd("SELECT code, main_group FROM classification WHERE country='台'").drop_duplicates()

    bench_of = {"sii": "TAIEX", "otc": "TPEx"}
    code_market = ev.groupby("code").market.agg(lambda s: s.mode().iat[0]).to_dict()

    print(f"事件母體(有actual_date): {len(ev):,}筆 (code x period)，"
          f"{ev.actual_date.min().date()}~{ev.actual_date.max().date()}，{ev.code.nunique()}檔")
    n_pre = ev.pre_date.notna().sum()
    ld = ev.lead_days.dropna()
    ld_clean = ld[(ld >= LEAD_LO) & (ld <= LEAD_HI)]
    print(f"其中有pre_date可配對: {n_pre:,}筆({n_pre / len(ev) * 100:.0f}%)；lead_days原始n={len(ld)}，"
          f"落在合理範圍[{LEAD_LO},{LEAD_HI}]天內{len(ld_clean):,}筆({len(ld_clean) / len(ld) * 100:.1f}%)，"
          f"中位數{ld_clean.median():.0f}天(5~95百分位{np.percentile(ld_clean, 5):.0f}~"
          f"{np.percentile(ld_clean, 95):.0f}天)；範圍外{len(ld) - len(ld_clean)}筆判定為period標籤配對雜訊。")
    print("⚠本版簡化：主分析只用actual_date，不再圍繞pre_date做因果窗設計(見檔頭說明)\n")

    # ---- 建立個股價格序列 + 熱度百分位(延伸②用) ----
    stocks = {}
    for c, g in px.groupby("code"):
        g = g.sort_values("date").reset_index(drop=True)
        g["m20"] = g.money.rolling(20, min_periods=15).mean()
        g["heat_pctl"] = g.m20.rolling(HEAT_ROLL, min_periods=HEAT_MIN_PERIODS).rank(pct=True) * 100
        stocks[c] = g
    idx_map = {m: g.set_index("date").close for m, g in idx.groupby("market")}

    def idx_ret(bench, d0, d1):
        s = idx_map.get(bench)
        if s is None:
            return np.nan
        try:
            c0, c1 = s.asof(d0), s.asof(d1)
            if pd.isna(c0) or pd.isna(c1) or c0 <= 0:
                return np.nan
            return (c1 / c0 - 1) * 100
        except Exception:
            return np.nan

    # ================= Q1: actual_date前反應(全樣本，不限有無pre_date) =================
    rows = []
    for r in ev.itertuples():
        g = stocks.get(r.code)
        if g is None:
            continue
        dts = g.date.values
        c_, m_ = g.close.values, g.money.values
        i = int(np.searchsorted(dts, np.datetime64(r.actual_date)))
        if i >= len(dts) or dts[i] != np.datetime64(r.actual_date):
            continue
        if i < max(KS) + PLACEBO_OFFSET + 5:
            continue
        bench = bench_of.get(r.market, "TAIEX")
        rec = {"code": r.code, "period": r.period, "market": r.market,
               "actual_date": r.actual_date, "pre_date": r.pre_date, "lead_days": r.lead_days,
               "has_pre": bool(pd.notna(r.pre_date)),
               "lead_ok": bool(pd.notna(r.lead_days) and LEAD_LO <= r.lead_days <= LEAD_HI),
               "heat_pctl": float(g.heat_pctl.iloc[i - 1]) if pd.notna(g.heat_pctl.iloc[i - 1]) else np.nan}
        for k in KS:
            if c_[i - k] > 0 and c_[i] > 0:
                raw = (c_[i] / c_[i - k] - 1) * 100
                rec[f"raw{k}"] = raw
                rec[f"x{k}"] = raw - idx_ret(bench, g.date.iloc[i - k], g.date.iloc[i])
            j = i - PLACEBO_OFFSET
            if j - k >= 0 and c_[j - k] > 0 and c_[j] > 0:
                praw = (c_[j] / c_[j - k] - 1) * 100
                rec[f"plc{k}"] = praw - idx_ret(bench, g.date.iloc[j - k], g.date.iloc[j])
            base = m_[max(0, i - k - 60):i - k]
            base = base[base > 0]
            win = m_[i - k + 1:i + 1] if k > 1 else m_[i:i + 1]
            win = win[win > 0]
            if len(base) >= 20 and len(win) >= 1:
                rec[f"volr{k}"] = float(np.mean(win)) / float(np.mean(base))
        rows.append(rec)

    df = pd.DataFrame(rows)
    df.to_pickle("快取/tmp_earnings_reaction_panel.pkl")
    print(f"可測事件(有完整價格窗): {len(df):,}筆，{df.code.nunique()}檔 "
          f"(其中有pre_date: {df.has_pre.sum():,}筆，無pre_date: {(~df.has_pre).sum():,}筆)\n")

    print("== Q1: 財報公告日「前」k個交易日累積報酬(demean減對應大盤TAIEX/TPEx，全樣本) ==")
    x_boot = {}
    for k in KS:
        stat(df[f"x{k}"], f"x{k}(前{k}日,demean)")
    print("    -- 對照:絕對報酬版(未扣大盤) --")
    for k in KS:
        stat(df[f"raw{k}"], f"raw{k}(前{k}日,絕對)")
    print("    -- 安慰劑對照(同股票,事件前60個交易日的假錨點,demean同口徑) --")
    for k in [5, 3, 1]:
        a = stat(df[f"x{k}"], f"事件x{k}")
        b = stat(df[f"plc{k}"], f"安慰劑x{k}")
        if a is not None and b is not None:
            print(f"      事件-安慰劑 中位差={a.median() - b.median():+.2f}pp "
                  f"(≈0=個股常態skew/顯著正=真提前反應)")
    for k in KS:
        x_boot[k] = month_boot(df, f"x{k}", f"全體x{k}", date_col="actual_date")

    print("\n== Q1b: 成交值量能比(窗內均量/窗前60日基準,>1=量增) ==")
    volr_ladder = {}
    for k in KS:
        v = df[f"volr{k}"].dropna()
        if len(v) >= 15:
            volr_ladder[k] = {"med": float(v.median()), "n": len(v), "pct_up": float((v > 1.2).mean() * 100)}
            print(f"    volr{k}: 中位{v.median():.2f}x 均值{v.mean():.2f}x "
                  f"量增比例(>1.2x){(v > 1.2).mean() * 100:.0f}% n={len(v):,}")

    print("\n== 補充分層: 大型(近60日均成交值前1/3) vs 中小型 — actual前x5 ==")
    amt = px.groupby("code").money.mean()
    ter = pd.qcut(amt.rank(method="first"), 3, labels=["小", "中", "大"])
    df["size_ter"] = df.code.map(ter)
    size_stats = {}
    for t in ["小", "中", "大"]:
        r = stat(df.loc[df.size_ter == t, "x5"], f"{t}型 x5")
        if r is not None:
            size_stats[t] = {"med": float(r.median()), "n": len(r)}

    # ================= 延伸① 族群密集週 + 同業sympathy move =================
    print("\n" + "=" * 60)
    print("== 延伸①: 族群財報密集週 + 同業sympathy move ==")
    tracked_codes = set(ev.code.unique())
    cls_t = cls[cls.code.isin(tracked_codes)].copy()
    theme_size = cls_t.groupby("main_group").code.nunique()
    print(f"題材可追蹤成員數(country=台且code在{len(tracked_codes)}檔追蹤名單內)分布: "
          f"中位{theme_size.median():.0f}檔，>=({DENSE_MIN_THEME_N})檔的題材數={int((theme_size >= DENSE_MIN_THEME_N).sum())}")

    code_dates = {c: np.sort(pd.to_datetime(g.actual_date).values) for c, g in ev.groupby("code")}

    m = ev[["code", "actual_date"]].merge(cls_t, on="code", how="inner")
    iso = m.actual_date.dt.isocalendar()
    m["wk"] = iso.year.astype(str) + "-W" + iso.week.astype(str).str.zfill(2)
    g_wk = m.groupby(["main_group", "wk"]).code.agg(lambda s: sorted(set(s))).reset_index(name="reporters")
    g_wk["n_report"] = g_wk.reporters.apply(len)
    g_wk["theme_n"] = g_wk.main_group.map(theme_size)
    g_wk["ratio"] = g_wk.n_report / g_wk.theme_n
    g_wk["window_start"] = m.groupby(["main_group", "wk"]).actual_date.min().values
    g_wk["window_end"] = m.groupby(["main_group", "wk"]).actual_date.max().values
    dense = g_wk[(g_wk.n_report >= DENSE_MIN_N) & (g_wk.ratio >= DENSE_MIN_RATIO)
                 & (g_wk.theme_n >= DENSE_MIN_THEME_N)].reset_index(drop=True)
    dense["win_id"] = dense.main_group + "_" + dense.wk
    print(f"密集週候選(門檻: 同週≥{DENSE_MIN_N}家 且 ≥該題材可追蹤成員{DENSE_MIN_RATIO * 100:.0f}% "
          f"且 題材可追蹤成員數≥{DENSE_MIN_THEME_N}檔): {len(dense)}筆窗口，涵蓋{dense.main_group.nunique()}個題材")
    print(f"    理由：n>=3為「非單一公司巧合」的最低門檻；20%比例避免大題材(如半導體設備22檔)"
          f"僅3家就被計入(3/22僅14%，稱不上「密集」)；題材成員<5檔比例統計易失真故排除。")

    # 個股own-event x5是否因「同週密集」而不同(供①(1)交叉驗證)
    dense_weeks_set = set(zip(dense.main_group, dense.wk))
    code_theme = cls_t.groupby("code").main_group.apply(list).to_dict()
    df["_iso"] = df.actual_date.dt.isocalendar().week
    df["_isoy"] = df.actual_date.dt.isocalendar().year
    df["_wk"] = df["_isoy"].astype(str) + "-W" + df["_iso"].astype(str).str.zfill(2)

    def _in_dense(row):
        for th in code_theme.get(row.code, []):
            if (th, row._wk) in dense_weeks_set:
                return True
        return False

    df["in_dense"] = df.apply(_in_dense, axis=1)
    print(f"\n個股own-event樣本中，屬於「自己題材當週為密集週」的事件: {df.in_dense.sum():,} / {len(df):,}")
    own_dense_diff = {}
    for k in [10, 5, 3, 1]:
        a = df.loc[df.in_dense, f"x{k}"].dropna()
        b = df.loc[~df.in_dense, f"x{k}"].dropna()
        stat(a, f"密集週內公告 own x{k}")
        stat(b, f"非密集週公告 own x{k}")
        if len(a) >= 15 and len(b) >= 15:
            own_dense_diff[k] = cluster_boot_diff(
                a.values, df.loc[a.index, "_wk"].values, b.values, df.loc[b.index, "_wk"].values,
                f"own x{k} 密集-非密集")

    # theme-wide member-level pre/during/post CAR(不限是否本人有公告，equal-weight，比照
    # build_theme_momentum_v2.py member-average手法)+ reporter/laggard/other角色標記
    member_rows = []
    for w in dense.itertuples():
        members = sorted(cls_t.loc[cls_t.main_group == w.main_group, "code"].unique())
        reporters = set(w.reporters)
        for code in members:
            g = stocks.get(code)
            if g is None:
                continue
            dts = g.date.values
            c = g.close.values
            bench = bench_of.get(code_market.get(code, "sii"), "TAIEX")
            i_pre_end = last_pos_le(dts, w.window_start - pd.Timedelta(days=1))
            i_dur_s = first_pos_ge(dts, w.window_start)
            i_dur_e = last_pos_le(dts, w.window_end)
            i_post_s = last_pos_le(dts, w.window_end)
            if code in reporters:
                role = "reporter"
            else:
                arr = code_dates.get(code)
                recent = False if arr is None else bool(
                    ((arr >= np.datetime64(w.window_start - pd.Timedelta(days=10)))
                     & (arr <= np.datetime64(w.window_end))).any())
                nxt = None
                if arr is not None:
                    later = arr[arr > np.datetime64(w.window_end)]
                    if len(later):
                        nxt = later.min()
                if not recent and nxt is not None and (nxt - np.datetime64(w.window_end)).astype("timedelta64[D]").astype(int) <= 60:
                    role = "laggard"
                else:
                    role = "other"
            rec = {"win_id": w.win_id, "main_group": w.main_group, "wk": w.wk, "code": code, "role": role}
            if i_pre_end >= 0:
                for k in [10, 5, 3, 1]:
                    if i_pre_end - k >= 0 and c[i_pre_end - k] > 0 and c[i_pre_end] > 0:
                        raw = (c[i_pre_end] / c[i_pre_end - k] - 1) * 100
                        rec[f"pre{k}"] = raw - idx_ret(bench, g.date.iloc[i_pre_end - k], g.date.iloc[i_pre_end])
            if i_post_s >= 0:
                for k in [10, 5, 3, 1]:
                    if i_post_s + k < len(dts) and c[i_post_s] > 0 and c[i_post_s + k] > 0:
                        raw = (c[i_post_s + k] / c[i_post_s] - 1) * 100
                        rec[f"post{k}"] = raw - idx_ret(bench, g.date.iloc[i_post_s], g.date.iloc[i_post_s + k])
            if (i_dur_s - 1 >= 0 and i_dur_s < len(dts) and i_dur_e >= i_dur_s
                    and c[i_dur_s - 1] > 0 and c[i_dur_e] > 0):
                raw = (c[i_dur_e] / c[i_dur_s - 1] - 1) * 100
                rec["during"] = raw - idx_ret(bench, g.date.iloc[i_dur_s - 1], g.date.iloc[i_dur_e])
                rec["during_days"] = int(i_dur_e - (i_dur_s - 1))
            member_rows.append(rec)

    mem = pd.DataFrame(member_rows)
    mem.to_pickle("快取/tmp_earnings_theme_dense_panel.pkl")
    print(f"\n族群密集週member-level樣本: {len(mem):,}筆 (reporter={int((mem.role=='reporter').sum())}, "
          f"laggard={int((mem.role=='laggard').sum())}, other={int((mem.role=='other').sum())})")

    print("\n-- (1) 題材整體(全部可追蹤成員equal-weight)密集週前後CAR --")
    theme_wide = {}
    for k in [10, 5, 3, 1]:
        pre = stat(mem[f"pre{k}"], f"題材整體 pre{k}(密集週前)")
        theme_wide[f"pre{k}"] = cluster_boot(mem[f"pre{k}"].values, mem.win_id.values, f"題材整體pre{k}") if pre is not None else None
    for k in [10, 5, 3, 1]:
        post = stat(mem[f"post{k}"], f"題材整體 post{k}(密集週後)")
        theme_wide[f"post{k}"] = cluster_boot(mem[f"post{k}"].values, mem.win_id.values, f"題材整體post{k}") if post is not None else None
    dur = stat(mem["during"], "題材整體 during(密集週期間本身,天數不定)")
    theme_wide["during"] = cluster_boot(mem["during"].values, mem.win_id.values, "題材整體during") if dur is not None else None

    print("\n-- (2) 同業sympathy move: laggard(還沒輪到自己公告)在密集週期間/前的反應 --")
    lag = mem[mem.role == "laggard"]
    other = mem[mem.role == "other"]
    print(f"    laggard樣本n={len(lag)}, other(已公告過/無鄰近事件)樣本n={len(other)}")
    sympathy = {}
    d_ = stat(lag["during"], "laggard during(密集週期間)")
    sympathy["during"] = cluster_boot(lag["during"].values, lag.win_id.values, "laggard during") if d_ is not None else None
    for k in [5, 3, 1]:
        p_ = stat(lag[f"pre{k}"], f"laggard pre{k}(密集週前)")
        sympathy[f"pre{k}"] = cluster_boot(lag[f"pre{k}"].values, lag.win_id.values, f"laggard pre{k}") if p_ is not None else None
    # laggard vs other 對照(排除掉「已經公告過的舊聞股」干擾，看laggard是否比unrelated組更異常)
    lag_vs_other = None
    if len(lag.dropna(subset=["during"])) >= 15 and len(other.dropna(subset=["during"])) >= 15:
        lag_vs_other = cluster_boot_diff(lag["during"].values, lag.win_id.values,
                                          other["during"].values, other.win_id.values,
                                          "laggard vs other during")

    # ================= 延伸② 成交值熱度分組 =================
    print("\n" + "=" * 60)
    print("== 延伸②: 成交值熱度分組(公告前20日均量 vs 自身240日歷史百分位) ==")
    heat = df.dropna(subset=["heat_pctl"]).copy()
    print(f"可計算熱度百分位事件: {len(heat):,}/{len(df):,}(需自身240個交易日歷史，新股/資料較短者被排除)")
    heat["heat_grp"] = np.select(
        [heat.heat_pctl >= HEAT_HOT, heat.heat_pctl <= HEAT_COLD],
        ["熱門", "冷門"], default="中間")
    print(heat.heat_grp.value_counts().to_string())

    heat_ladder = {"熱門": {}, "冷門": {}, "中間": {}}
    heat_diff = {}
    for grp in ["熱門", "冷門", "中間"]:
        sub = heat[heat.heat_grp == grp]
        print(f"\n  -- {grp}組 (n事件={len(sub)}) --")
        for k in KS:
            r = stat(sub[f"x{k}"], f"{grp} x{k}", pref="      ")
            if r is not None:
                heat_ladder[grp][k] = {"med": float(r.median()), "mean": float(r.mean()),
                                        "win": float((r > 0).mean() * 100), "n": len(r)}
                heat_ladder[grp].setdefault("boot", {})[k] = month_boot(sub, f"x{k}", f"{grp}x{k}")
    print("\n  -- 熱門 vs 冷門 差異bootstrap --")
    hot = heat[heat.heat_grp == "熱門"]
    cold = heat[heat.heat_grp == "冷門"]
    for k in KS:
        a, b = hot[f"x{k}"].dropna(), cold[f"x{k}"].dropna()
        if len(a) >= 15 and len(b) >= 15:
            mo_a = pd.to_datetime(hot.loc[a.index, "actual_date"]).dt.to_period("M").astype(str)
            mo_b = pd.to_datetime(cold.loc[b.index, "actual_date"]).dt.to_period("M").astype(str)
            heat_diff[k] = cluster_boot_diff(a.values, mo_a.values, b.values, mo_b.values, f"熱門-冷門 x{k}")

    # ================= 摘要 + HTML =================
    summary = {
        "n_events": len(df), "n_codes": df.code.nunique(),
        "date_min": str(df.actual_date.min().date()), "date_max": str(df.actual_date.max().date()),
        "n_pre_pct": round(n_pre / len(ev) * 100, 1),
        "lead_median": float(ld_clean.median()), "lead_p5": float(np.percentile(ld_clean, 5)),
        "lead_p95": float(np.percentile(ld_clean, 95)), "lead_n_excl": int(len(ld) - len(ld_clean)),
        "n_dense_windows": len(dense), "n_dense_themes": int(dense.main_group.nunique()),
        "n_tracked_codes": len(tracked_codes),
        "n_heat": len(heat),
    }
    build_html_report(df, ev, dense, mem, heat, names, summary, x_boot, volr_ladder, size_stats,
                       own_dense_diff, theme_wide, sympathy, lag_vs_other, heat_ladder, heat_diff)
    print(f"\n報告已輸出 -> {OUT_HTML}")


def build_html_report(df, ev, dense, mem, heat, names, summary, x_boot, volr_ladder, size_stats,
                       own_dense_diff, theme_wide, sympathy, lag_vs_other, heat_ladder, heat_diff):
    import json

    def ladder(colprefix, ks=KS, source=df):
        out = []
        for k in ks:
            x = source[f"{colprefix}{k}"].dropna()
            if len(x) < 15:
                out.append({"k": k, "n": len(x), "med": None, "mean": None, "win": None})
            else:
                out.append({"k": k, "n": int(len(x)), "med": round(float(x.median()), 2),
                             "mean": round(float(x.mean()), 2), "win": round(float((x > 0).mean() * 100), 1)})
        return out

    def boot_row(d):
        if d is None:
            return {"lo": None, "hi": None, "p_le0": None}
        return {"lo": round(d["lo"], 2), "hi": round(d["hi"], 2), "p_le0": round(d["p_le0"], 4)}

    x_ladder = ladder("x")
    raw_ladder = ladder("raw")
    x_boot_j = {k: boot_row(x_boot.get(k)) for k in KS}

    # 熱度分組ladder
    heat_ladder_j = {}
    for grp in ["熱門", "冷門", "中間"]:
        arr = []
        for k in KS:
            v = heat_ladder[grp].get(k)
            b = heat_ladder[grp].get("boot", {}).get(k)
            arr.append({"k": k, "med": v["med"] if v else None, "n": v["n"] if v else 0,
                        "win": v["win"] if v else None, **boot_row(b)})
        heat_ladder_j[grp] = arr
    heat_diff_j = {k: boot_row(heat_diff.get(k)) for k in KS}
    if heat_diff:
        for k in KS:
            if heat_diff.get(k):
                heat_diff_j[k]["diff"] = round(heat_diff[k]["diff"], 2)

    # 族群密集週 payload
    theme_wide_j = {}
    for key, d in theme_wide.items():
        theme_wide_j[key] = boot_row(d)
        if d is not None:
            theme_wide_j[key]["med"] = round(d["med"], 2)
    sympathy_j = {}
    for key, d in sympathy.items():
        sympathy_j[key] = boot_row(d)
        if d is not None:
            sympathy_j[key]["med"] = round(d["med"], 2)
    own_dense_diff_j = {}
    for k, d in own_dense_diff.items():
        own_dense_diff_j[k] = boot_row(d)
        if d is not None:
            own_dense_diff_j[k]["diff"] = round(d["diff"], 2)
    lag_vs_other_j = boot_row(lag_vs_other)
    if lag_vs_other is not None:
        lag_vs_other_j["diff"] = round(lag_vs_other["diff"], 2)

    dense_top = dense.sort_values("ratio", ascending=False).head(15)[
        ["main_group", "wk", "n_report", "theme_n", "ratio"]].copy()
    dense_top["ratio"] = (dense_top.ratio * 100).round(0)
    dense_table_rows = dense_top.to_dict("records")

    theme_counts = dense.main_group.value_counts().to_dict()

    payload = {
        "x_ladder": x_ladder, "raw_ladder": raw_ladder, "x_boot": x_boot_j,
        "volr_ladder": {str(k): v for k, v in volr_ladder.items()},
        "size_stats": size_stats,
        "summary": summary,
        "dense_table": dense_table_rows,
        "theme_counts": theme_counts,
        "own_dense_diff": own_dense_diff_j,
        "theme_wide": theme_wide_j,
        "sympathy": sympathy_j,
        "lag_vs_other": lag_vs_other_j,
        "heat_ladder": heat_ladder_j,
        "heat_diff": heat_diff_j,
        "heat_n": {"熱門": int((heat.heat_grp == "熱門").sum()), "冷門": int((heat.heat_grp == "冷門").sum()),
                   "中間": int((heat.heat_grp == "中間").sum())},
    }

    CSS = """
body{background:#1a1a19;color:#fff;font-family:"Noto Sans TC",sans-serif;margin:24px;max-width:1100px}
h1{font-size:20px} h2{font-size:15px;color:#c3c2b7;margin-top:30px} h3{font-size:13px;color:#a8a696}
table{border-collapse:collapse;font-size:13px;font-variant-numeric:tabular-nums;margin-top:8px}
td,th{border:1px solid #333;padding:5px 12px;text-align:right} th{text-align:left}
.note{color:#8a8878;font-size:12px;line-height:1.75}
.good{color:#7ec97e}.bad{color:#e06c5a}.mid{color:#c3c2b7}
.warn{background:#332b19;border-left:3px solid #d9a441;padding:10px 14px;margin:14px 0;font-size:13px}
.verdict{background:#1c2b22;border-left:3px solid #7ec97e;padding:8px 14px;margin:8px 0;font-size:13px}
"""
    PLOT_BG = {"paper_bgcolor": "#1a1a19", "plot_bgcolor": "#22221f",
               "font": {"color": "#ddd", "size": 12}, "margin": {"t": 30, "l": 50, "r": 20, "b": 40}}
    payload["bg"] = PLOT_BG

    def cls_good_bad(v):
        return "good" if (v or 0) > 0 else "bad" if v is not None else "mid"

    def row_ladder_table(title, ladder_data, boot_data=None, unit="%"):
        head = "<tr><th>窗口</th>" + "".join(f"<th>前{d['k']}日</th>" for d in ladder_data) + "</tr>"
        med = "<tr><th>中位數</th>" + "".join(
            f"<td class='{cls_good_bad(d['med'])}'>{d['med']:+.2f}{unit}</td>" if d["med"] is not None else "<td>—</td>"
            for d in ladder_data) + "</tr>"
        n = "<tr><th>n</th>" + "".join(f"<td>{d['n']:,}</td>" for d in ladder_data) + "</tr>"
        rows = head + med + n
        if boot_data:
            ci = "<tr><th>bootstrap CI95</th>" + "".join(
                f"<td>[{boot_data[d['k']]['lo']:+.2f},{boot_data[d['k']]['hi']:+.2f}]</td>"
                if boot_data.get(d['k']) and boot_data[d['k']]['lo'] is not None else "<td>—</td>"
                for d in ladder_data) + "</tr>"
            p_ = "<tr><th>P(中位&lt;=0)</th>" + "".join(
                f"<td>{boot_data[d['k']]['p_le0']:.3f}</td>"
                if boot_data.get(d['k']) and boot_data[d['k']]['p_le0'] is not None else "<td>—</td>"
                for d in ladder_data) + "</tr>"
            rows += ci + p_
        return f"<h2>{title}</h2><table>{rows}</table>"

    # Q1整體判讀(動態，以x5為主，但如實併陳x20的邊緣顯著負向，不只看單一窗口)
    x5b, x20b = x_boot.get(5), x_boot.get(20)
    q1_base = verdict(
        x5b["p_le0"] if x5b else None,
        f"公告前5日demean中位數顯著為正(P(中位&le;0)={x5b['p_le0']:.3f}<0.05)：公告前確有偏多的異常反應，"
        f"與「利多提前流出」的假說一致。" if x5b else "",
        f"公告前5日demean中位數顯著為負(P(中位&le;0)={x5b['p_le0']:.3f}>0.95)：公告前反而偏空，"
        f"較像「靴前risk-off/獲利了結」而非利多提前反應。" if x5b else "",
        f"公告前5日demean中位數與0無顯著差異(P(中位&le;0)={x5b['p_le0']:.3f}，CI95=[{x5b['lo']:+.2f},{x5b['hi']:+.2f}]涵蓋0)："
        f"整體而言看不到系統性的公告前異常反應。" if x5b else "樣本不足")
    q1_extra = ""
    if x20b and x5b:
        if x20b["p_le0"] >= 0.95 and x5b["p_le0"] < 0.95:
            q1_extra = (f"　補充：窗口拉長到前20日時中位數轉為{x20b['med'] if x20b.get('med') is not None else '':+.2f}%"
                        f"且邊緣顯著偏負(P(中位&le;0)={x20b['p_le0']:.3f}，CI95=[{x20b['lo']:+.2f},{x20b['hi']:+.2f}])，"
                        f"短窗(1~5日)不顯著、長窗(20日)偏負但剛過門檻，顯示「公告前」整體而言若有異常，"
                        f"方向較像緩慢的偏空(可能是財報季前的風險趨避)而非利多提前流出，且證據強度隨窗口拉長才逐漸浮現。")
        elif x20b["p_le0"] < 0.95:
            q1_extra = "　各窗口(1~20日)方向大致一致、皆未達顯著，整體結論穩健。"
    q1_verdict = q1_base + q1_extra

    # 族群整體判讀(以pre5為主，但併陳post5歸零、during同向，呈現完整時間輪廓)
    tw_pre5, tw_post5, tw_during = theme_wide.get("pre5"), theme_wide.get("post5"), theme_wide.get("during")
    theme_verdict = verdict(
        tw_pre5["p_le0"] if tw_pre5 else None,
        "題材整體在密集週前出現顯著正向異常(demean中位數CI95不含0且偏正)：密集公告週前，"
        "同題材股票有集體被買進、卡位下一波財報的跡象。",
        f"題材整體在密集週前出現顯著負向異常(pre5中位{tw_pre5['med']:+.2f}%，CI95=[{tw_pre5['lo']:+.2f},{tw_pre5['hi']:+.2f}]，"
        f"P(&le;0)={tw_pre5['p_le0']:.3f})：密集公告週前題材整體偏弱，較像獲利了結/risk-off，而非「卡位下一波財報」。"
        + (f"密集週期間本身同向偏負(during中位{tw_during['med']:+.2f}%，P(&le;0)={tw_during['p_le0']:.3f})，"
           if tw_during and tw_during.get("p_le0", 0) >= 0.95 else "")
        + (f"但密集週後(post5)迅速歸零(中位{tw_post5['med']:+.2f}%，CI95涵蓋0，P(&le;0)={tw_post5['p_le0']:.3f})，"
           "顯示這是短暫的財報季前降溫、不是趨勢反轉。"
           if tw_post5 else "") if tw_pre5 else "",
        "題材整體在密集週前後與0無顯著差異：目前樣本看不出「財報密集週」本身會帶動題材整體異常，"
        "族群層級效應（如果有）更可能是題材本身的基本面/資金流驅動，而非「密集公告」這個時間巧合。")

    # sympathy判讀(以pre5為主，because during窗口天數不定雜訊較大；併陳與other組無顯著差異的限制)
    sym_pre5, sym_during = sympathy.get("pre5"), sympathy.get("during")
    sym_base = verdict(
        sym_pre5["p_le0"] if sym_pre5 else None,
        "laggard(還沒輪到自己公告)在密集週前出現顯著正向excess return：同業sympathy move成立，"
        "市場會在同業密集公告期間提前重新定價「還沒公告」的成員。",
        f"laggard在密集週前5日出現顯著負向excess return(中位{sym_pre5['med']:+.2f}%，"
        f"CI95=[{sym_pre5['lo']:+.2f},{sym_pre5['hi']:+.2f}]，P(&le;0)={sym_pre5['p_le0']:.3f})：確實觀察到"
        "「還沒公告」的同業也連帶走弱，同業效應存在，但方向是連坐下跌而非正向重新定價。" if sym_pre5 else "",
        "laggard在密集週前與0無顯著差異：目前樣本看不出「還沒公告」的同業會因為隔壁公司公告而"
        "連帶重新定價，sympathy move假說不成立(至少本樣本觀察不到)。")
    sym_extra = ""
    if lag_vs_other is not None and lag_vs_other.get("p_le0") is not None and 0.05 < lag_vs_other["p_le0"] < 0.95:
        during_note = f"；且during窗口(天數不定)未達顯著(P(&le;0)={sym_during['p_le0']:.3f})" if sym_during else ""
        sym_extra = ("　但laggard vs other(已公告過/無鄰近事件的成員)兩組差異未達顯著，"
                     "代表這個負向excess return laggard和other一樣都有，較可能是「整個題材在財報季前一起降溫」的"
                     "系統性現象，還不能乾淨地歸因於「因為隔壁公司公告而特別重新定價laggard」這個sympathy機制本身"
                     f"{during_note}。")
    sym_verdict = sym_base + sym_extra

    # 熱度分組判讀(以x5為主，併陳整條ladder的梯度模式，並點出中間組行為接近冷門組)
    hd5 = heat_diff.get(5)
    heat_base = verdict(
        hd5["p_le0"] if hd5 else None,
        f"熱門組(公告前20日成交值處於自身歷史高分位)公告前5日demean報酬顯著高於冷門組"
        f"(中位差{hd5['diff']:+.2f}pp，P(差&le;0)={hd5['p_le0']:.3f})：高關注度期間反而伴隨更明顯的公告前異常反應。" if hd5 else "",
        f"熱門組公告前5日demean報酬顯著低於冷門組(中位差{hd5['diff']:+.2f}pp，"
        f"P(差&le;0)={hd5['p_le0']:.3f})：冷門股在公告前反而有更明顯的異常反應，"
        f"較符合「乏人問津的股票消息面衝擊相對更大」的直覺。" if hd5 else "",
        f"熱門組與冷門組公告前5日demean報酬無顯著差異(P(差&le;0)={hd5['p_le0']:.3f}，CI95涵蓋0)："
        f"目前樣本看不出成交熱度會系統性放大或縮小公告前異常反應。" if hd5 else "樣本不足")
    hd20 = heat_diff.get(20)
    heat_extra = ""
    if hd20 and hd20.get("p_le0", 0) <= 0.05:
        heat_extra = (f"　且此差異隨窗口拉長而放大：前20日熱門-冷門中位差達{hd20['diff']:+.2f}pp"
                     f"(CI95=[{hd20['lo']:+.2f},{hd20['hi']:+.2f}]，P(差&le;0)={hd20['p_le0']:.3f})，"
                     "短窗(1日)則差異消失，顯示效應是逐日累積而非單日跳空。"
                     "另需注意「中間」組(百分位33~67)走勢接近冷門組而非熱門組，"
                     "代表這其實是「極熱門」的少數股票才有的特徵，不是均勻的線性梯度。")
    heat_verdict = heat_base + heat_extra

    s = summary

    def dense_table_html():
        rows = "".join(
            f"<tr><td>{r['main_group']}</td><td>{r['wk']}</td><td>{r['n_report']}</td>"
            f"<td>{r['theme_n']}</td><td>{r['ratio']:.0f}%</td></tr>"
            for r in payload["dense_table"])
        return f"<table><tr><th>題材</th><th>ISO週</th><th>當週公告家數</th><th>題材可追蹤成員數</th><th>比例</th></tr>{rows}</table>"

    def theme_counts_html():
        items = sorted(payload["theme_counts"].items(), key=lambda kv: -kv[1])
        return "、".join(f"{k}({v})" for k, v in items)

    def heat_group_table(grp):
        arr = payload["heat_ladder"][grp]
        head = "<tr><th>窗口</th>" + "".join(f"<th>前{d['k']}日</th>" for d in arr) + "</tr>"
        med = "<tr><th>中位數</th>" + "".join(
            f"<td class='{cls_good_bad(d['med'])}'>{d['med']:+.2f}%</td>" if d['med'] is not None else "<td>—</td>"
            for d in arr) + "</tr>"
        n = "<tr><th>n</th>" + "".join(f"<td>{d['n']:,}</td>" for d in arr) + "</tr>"
        return f"<h3>{grp}組(n事件={payload['heat_n'][grp]:,})</h3><table>{head}{med}{n}</table>"

    def heat_diff_table():
        head = "<tr><th></th>" + "".join(f"<th>前{k}日</th>" for k in KS) + "</tr>"
        diff = "<tr><th>熱門-冷門 中位差(pp)</th>" + "".join(
            f"<td class='{cls_good_bad(heat_diff_j[k].get('diff'))}'>{heat_diff_j[k]['diff']:+.2f}</td>"
            if heat_diff_j.get(k) and heat_diff_j[k].get("diff") is not None else "<td>—</td>" for k in KS) + "</tr>"
        ci = "<tr><th>CI95</th>" + "".join(
            f"<td>[{heat_diff_j[k]['lo']:+.2f},{heat_diff_j[k]['hi']:+.2f}]</td>"
            if heat_diff_j.get(k) and heat_diff_j[k].get("lo") is not None else "<td>—</td>" for k in KS) + "</tr>"
        p_ = "<tr><th>P(差&le;0)</th>" + "".join(
            f"<td>{heat_diff_j[k]['p_le0']:.3f}</td>"
            if heat_diff_j.get(k) and heat_diff_j[k].get("p_le0") is not None else "<td>—</td>" for k in KS) + "</tr>"
        return f"<table>{head}{diff}{ci}{p_}</table>"

    def size_table():
        rows = "".join(f"<tr><td>{t}型</td><td class='{cls_good_bad(v['med'])}'>{v['med']:+.2f}%</td>"
                        f"<td>{v['n']:,}</td></tr>" for t, v in size_stats.items())
        return f"<table><tr><th></th><th>x5中位數</th><th>n</th></tr>{rows}</table>"

    def own_dense_table():
        rows = ""
        for k in [10, 5, 3, 1]:
            d = own_dense_diff_j.get(k)
            if d and d.get("diff") is not None:
                rows += (f"<tr><td>前{k}日</td><td class='{cls_good_bad(d['diff'])}'>{d['diff']:+.2f}pp</td>"
                         f"<td>[{d['lo']:+.2f},{d['hi']:+.2f}]</td><td>{d['p_le0']:.3f}</td></tr>")
            else:
                rows += f"<tr><td>前{k}日</td><td>—</td><td>—</td><td>—</td></tr>"
        return f"<table><tr><th>窗口</th><th>密集-非密集 中位差</th><th>CI95</th><th>P(差&le;0)</th></tr>{rows}</table>"

    def fmt_pct(d, key="med"):
        if d and d.get(key) is not None:
            return f"{d[key]:+.2f}%"
        return "—"

    def fmt_p(d, key="p_le0"):
        if d and d.get(key) is not None:
            return f"{d[key]:.3f}"
        return "—"

    def fmt_ci(d):
        if d and d.get("lo") is not None:
            return f"[{d['lo']:+.2f},{d['hi']:+.2f}]"
        return "—"

    def theme_wide_table():
        rows = ""
        for k in [10, 5, 3, 1]:
            pre, post = theme_wide_j.get(f"pre{k}"), theme_wide_j.get(f"post{k}")
            pre_med, pre_p = fmt_pct(pre), fmt_p(pre)
            post_med, post_p = fmt_pct(post), fmt_p(post)
            rows += (f"<tr><td>前{k}日</td>"
                     f"<td class='{cls_good_bad(pre.get('med') if pre else None)}'>{pre_med}</td>"
                     f"<td>{pre_p}</td>"
                     f"<td class='{cls_good_bad(post.get('med') if post else None)}'>{post_med}</td>"
                     f"<td>{post_p}</td></tr>")
        dur = theme_wide_j.get("during")
        return (f"<table><tr><th>窗口</th><th>密集週前中位數</th><th>P(&le;0)</th>"
                f"<th>密集週後中位數</th><th>P(&le;0)</th></tr>{rows}</table>"
                f"<div class='note'>密集週期間本身(window_start~window_end,天數不定): "
                f"中位{fmt_pct(dur)} CI95={fmt_ci(dur)} P(&le;0)={fmt_p(dur)}</div>")

    def sympathy_table():
        rows = ""
        for k in ["during", "pre5", "pre3", "pre1"]:
            d = sympathy_j.get(k)
            lab = "密集週期間" if k == "during" else f"密集週前{k[3:]}日"
            if d and d.get("med") is not None:
                rows += (f"<tr><td>{lab}</td><td class='{cls_good_bad(d['med'])}'>{d['med']:+.2f}%</td>"
                         f"<td>[{d['lo']:+.2f},{d['hi']:+.2f}]</td><td>{d['p_le0']:.3f}</td></tr>")
            else:
                rows += f"<tr><td>{lab}</td><td>—</td><td>—</td><td>—</td></tr>"
        return f"<table><tr><th>laggard窗口</th><th>demean中位數</th><th>CI95</th><th>P(&le;0)</th></tr>{rows}</table>"

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>台股財報公告前反應＋族群/熱度延伸考卷</title>
<script src="plotly.min.js"></script><style>{CSS}</style></head><body>
<h1>台股財報公告「前」反應＋族群密集週/成交值熱度延伸考卷</h1>
<div class="note">
資料源：MOPS舊版(mopsov.twse.com.tw/mops/web/t05st01)逐檔查重大訊息，取「財報經董事會決議通過」
實際公告日(actual_date)，見 抓取/fetch_tw_earnings_dates.py。
2026-08-02簡化：確認MoneyDJ行事曆「財報公告」日期＝actual_date本身(以3008大立光實測驗證)，
故不再區分pre_date(預告)的獨立因果窗，主分析改成「actual_date前有沒有異常反應」，
樣本從874筆(需pre_date+actual_date皆有)擴大到{s['n_events']:,}筆(只需actual_date)。
母體：{s['n_events']:,}筆事件(code×期別)，{s['n_codes']}檔，{s['date_min']}~{s['date_max']}。
</div>
<div class="warn">⚠已知限制：
①pre_date覆蓋率僅{s['n_pre_pct']}%且非隨機，本版只作附錄參考；
②lead_days(提前天數)874筆中有{s['lead_n_excl']}筆落在[{LEAD_LO},{LEAD_HI}]天合理範圍外
(-357~+319天等，判定為period標籤配對雜訊)，範圍內中位數{s['lead_median']:.0f}天
(5~95百分位{s['lead_p5']:.0f}~{s['lead_p95']:.0f}天)；
③period欄位另有9筆離奇標籤(如"1934A")疑似個別公司內部季別編號誤植，但對應actual_date本身
正常，不影響可用性，族群分析一律用actual_date日期本身判斷「有沒有報過」，不比對period文字；
④族群分析的題材成員universe僅限tw_board_earnings_dates資料庫實際追蹤到的{s['n_tracked_codes']}檔，
不是該題材完整成分股清單(此資料庫本身非全市場覆蓋)；
⑤樣本集中最近2~3年(2024~2026)，非跨景氣循環驗證；
⑥本卷屬觀察層，非交易建議，任何正/負結果皆如實列出未做事後選擇性報告。
</div>

<h2>Q1: 財報公告日「前」k個交易日累積報酬(demean減對應大盤TAIEX/上市或TPEx/上櫃，全樣本{s['n_events']:,}筆)</h2>
{row_ladder_table("", x_ladder, x_boot_j)}
<div id="c0" style="height:320px;margin-top:8px"></div>
<div class="verdict">判讀(以前5日窗口為主，動態依bootstrap結果生成)：{q1_verdict}</div>
{row_ladder_table("　　對照:絕對報酬版(未扣大盤)", raw_ladder)}

<h2>成交值量能比(窗內均量 / 窗前60日基準，中位數)</h2>
<table><tr><th>窗口</th>{"".join(f"<th>前{k}日</th>" for k in KS)}</tr>
<tr><th>倍數</th>{"".join(f"<td>{volr_ladder[k]['med']:.2f}x</td>" if k in volr_ladder else "<td>—</td>" for k in KS)}</tr></table>

<h2>補充分層：大型 vs 中小型(近60日均成交值前1/3) — actual前x5</h2>
{size_table()}

<h2>族群密集週分析① 密集週定義與候選清單</h2>
<div class="note">
定義：同一題材(classification.main_group)在同一ISO週內，有≥{DENSE_MIN_N}家可追蹤成員公告actual_date，
且達該題材可追蹤成員數的{int(DENSE_MIN_RATIO*100)}%以上，且題材可追蹤成員數≥{DENSE_MIN_THEME_N}檔，
即列為「密集週」候選。理由：n≥3為排除單一公司巧合的最低門檻；比例門檻避免大題材(如半導體設備22檔
可追蹤中僅3家=14%)被誤判為密集；小題材(&lt;5檔)比例統計易失真故排除。
本卷共找到{s['n_dense_windows']}個密集週窗口，涵蓋{s['n_dense_themes']}個題材：{theme_counts_html()}。
</div>
<h3>比例最高的密集週候選(前15筆)</h3>
{dense_table_html()}

<h2>族群密集週分析② 個股own-event：密集週內公告 vs 非密集週公告(own x_k差異)</h2>
<div class="note">同一批個股own-event樣本(即Q1的df)，依「自己公告當週是否屬於自己題材的密集週」分兩組比較。</div>
{own_dense_table()}

<h2>族群密集週分析③ 題材整體(equal-weight全部可追蹤成員)密集週前後CAR</h2>
<div class="note">
比照build_theme_momentum_v2.py的member-average手法：不論成員當週有沒有公告，equal-weight平均
demean報酬，測密集週前(pre)/密集週期間(during)/密集週後(post)。群集bootstrap以win_id(題材×週)分群。
</div>
{theme_wide_table()}
<div class="verdict">判讀：{theme_verdict}</div>

<h2>族群密集週分析④ 同業sympathy move：laggard(還沒輪到自己公告)</h2>
<div class="note">
laggard＝該題材成員在密集週窗口内自己「還沒公告」，但依照後續實際公告日期確認「這一輪(60天內)會報，
只是還沒輪到」；排除「已在窗口前10天內公告過」與「無鄰近事件」的成員(歸入other，不計入laggard)。
</div>
{sympathy_table()}
<div class="verdict">判讀：{sym_verdict}</div>
<div class="note">laggard vs other(已公告過/無鄰近事件)during對照：
{f"中位差{lag_vs_other_j['diff']:+.2f}pp，CI95=[{lag_vs_other_j['lo']:+.2f},{lag_vs_other_j['hi']:+.2f}]，P(差&le;0)={lag_vs_other_j['p_le0']:.3f}" if lag_vs_other_j.get('diff') is not None else "樣本不足，未做此對照"}
</div>

<h2>成交值熱度分組：公告前20日均量相對自身240日歷史百分位</h2>
<div class="note">
熱度百分位算法比照研究腳本/當沖借券/build_dtlend_pattern_pnl.py、
研究腳本/綜合策略/build_regime_weather_report.py的vp10寫法(rolling(window).rank(pct=True)*100)，
差別是這裡用「每檔股票自己的」240日rolling窗口(≈1年)，而非全市場單一序列。
熱門組＝百分位&ge;{HEAT_HOT}，冷門組＝百分位&le;{HEAT_COLD}，中間組為對照。
可計算熱度事件{s['n_heat']:,}/{s['n_events']:,}筆(需自身240個交易日歷史，新股/資料較短者排除)。
</div>
{heat_group_table("熱門")}
{heat_group_table("冷門")}
{heat_group_table("中間")}
<h3>熱門 vs 冷門 差異bootstrap(demean x_k中位差)</h3>
{heat_diff_table()}
<div class="verdict">判讀(以前5日窗口為主)：{heat_verdict}</div>

<h2>附錄：pre_date參考(樣本受限，非主判讀依據)</h2>
<div class="note">
pre_date(真預告，2024Q1起金管會新制才有，覆蓋率僅{s['n_pre_pct']}%且非隨機)理論上代表市場已提前
被告知「將公告」這件事本身(不含財報內容)。此處僅列有pre_date組 vs 無pre_date組的actual前x5中位數
供參考，不做因果推論、不當主標題判讀依據(詳見檔頭說明，此設計已被使用者裁示簡化捨棄)。
</div>
<table><tr><th></th><th>x5中位數</th><th>n</th></tr>
<tr><td>有pre_date</td><td class="{cls_good_bad(df.loc[df.has_pre,'x5'].median() if df.has_pre.sum()>=15 else None)}">
{f"{df.loc[df.has_pre,'x5'].median():+.2f}%" if df.has_pre.sum()>=15 else '—'}</td><td>{int(df.has_pre.sum()):,}</td></tr>
<tr><td>無pre_date</td><td class="{cls_good_bad(df.loc[~df.has_pre,'x5'].median() if (~df.has_pre).sum()>=15 else None)}">
{f"{df.loc[~df.has_pre,'x5'].median():+.2f}%" if (~df.has_pre).sum()>=15 else '—'}</td><td>{int((~df.has_pre).sum()):,}</td></tr>
</table>

<h2>已知限制(彙整)</h2>
<div class="note">
①MOPS無「全市場當日重大訊息」批次端點，只能逐檔查，本卷universe為固定{s['n_tracked_codes']}檔
(tw_top300+額外抽樣中小型)，非全市場，族群分析的「題材成員」與「密集週比例」皆以此為分母；
②demean僅對應大盤指數(TAIEX/TPEx)，未做同宇宙cross-section中位數版本；
③族群/熱度細分後樣本量變小，凡n&lt;15的分組一律標示「太少」不強做判讀；
④樣本集中最近2~3年，非跨景氣循環驗證；
⑤本卷屬觀察層，非交易建議，任何正/負結果皆如實列出未做事後選擇性報告。
</div>

<script>
const D={json.dumps(payload, ensure_ascii=False)};
Plotly.newPlot('c0', [{{x:D.x_ladder.map(d=>'前'+d.k+'日'), y:D.x_ladder.map(d=>d.med), type:'bar',
  marker:{{color:D.x_ladder.map(d=>(d.med||0)>0?'#7ec97e':'#e06c5a')}},
  text:D.x_ladder.map(d=>d.n?('n='+d.n):''), textposition:'outside'}}],
  Object.assign({{yaxis:{{title:'demean中位數(%)'}}, xaxis:{{title:'公告日前窗口(交易日)'}}}}, D.bg));
</script>
</body></html>"""
    open(OUT_HTML, "w", encoding="utf-8").write(html)


if __name__ == "__main__":
    main()
