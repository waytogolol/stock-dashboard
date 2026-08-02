# -*- coding: utf-8 -*-
"""題材觸發後「題材內挑股/加權」能否勝過等權全買?(2026-08-02,使用者提案延伸研究)

背景: 既有「題材月營收動能」策略(build_theme_momentum_v2.py/build_theme_momentum_report.py)
baseline=score=4(連3月MoM正+近3月YoY均值正)觸發後,題材全成員等權買、次月15號進場、持60交易日
(115個題材-月事件,828筆成員-事件,27題材,超額報酬60日+2.6%,2025年顯著/2024年偏負)。
本卷問: 觸發當下,能不能在題材內部依成員特徵挑股/加權,打敗等權全買?

事件/報酬資料完全重用build_theme_momentum_v2.py的產出快取(快取/tmp_theme_momentum_v2_panel.pkl),
不重新設計訊號本身,只鎖定score=4子集(115事件/828列),在成員層級疊加6個特徵角度,全部只用
「觸發當下已公開」的資訊(revenue用shift(1)口徑同score本身;價格用進場日收盤或更早;外資/TDCC用
嚴格早於進場日的最近快照)。

六個特徵角度(理論依據見各自函式docstring):
  ①價格相對強勢: 進場日收盤的trailing 20日/60日報酬(題材內排名即天然反映相對同儕/相對大盤,
    因同題材同月成員的進場日高度重疊,TWII同期成分幾乎共同抵銷)
  ②個股營收YoY相對突出: own_yoy3=個股自身近3個月YoY均值(shift(1)口徑,逐字比照題材trend_yoy3
    定義但用個股取代加總),題材內排名切；另測「月營收創近12個月新高」二元旗標(兩切法都測)
  ③外資20日位階: 逐字複用封存/研究腳本歸檔/tmp_chip_bt.py的canonical S4算法
    (foreign_net→rolling(20,min10).sum()→rolling(240,min120).rank(pct=True)*100),取嚴格早於
    進場日的最近一筆
  ④個股佔題材營收比重的YoY變化: share(t)=個股營收/題材(classification全成員)加總營收,
    delta=share(period_last)-share(period_last-12月),單位pp(是否正在變成該題材的核心成員)
  ⑤TDCC大戶持股比例趨勢: 逐字複用build_resonance_tdcc.py的d4w_1000規約(cutoff=進場日-3日曆日
    的最新tdcc_weekly快照,距cutoff>21天視為過期,d4w_1000=p1000本期-p1000前4期)
  ⑥(加測)成交值熱度百分位: 比照本專案vp10/S4外資位階等「rolling(240,min120).rank(pct=True)*100
    自身歷史百分位」的既有算法慣例,套用在個股自身20日均額(用Close×Volume近似money)上,
    取進場日「前一交易日」(嚴格早於進場,避免用到進場當日才確定的量能資訊)

方法論(比照本批姊妹考卷build_vol_addvalue_report.py/build_dtlend_winner_features.py既有紀律):
  - 每個特徵在事件內(題材-月)把有效成員分前1/3(top)vs後1/3(bottom)(n<3的事件跳過;
    二元旗標改用「有此屬性」vs「無此屬性」,兩邊都要有成員才計入);
  - 絕對報酬層: top/bottom兩組成員層級pooled的ret60中位/均值/勝率(是否本身為正且穩定);
  - 相對baseline層: 每個事件算top_demean=top組均值-該事件全成員均值(=等權全買baseline)、
    bottom_demean同理、diff=top均值-bottom均值——這是「事件層配對」設計,直接控制掉題材當月的
    共同成分,比本專案build_theme_momentum_validate.py的「題材-月cluster bootstrap」(整群重抽樣
    後pool成員值算中位數)更貼近「選股是否優於等權baseline」這個問題,兩者結論方向通常一致但
    本卷這個設計對「配對」問題更嚴謹,報告中會註明差異;
  - 顯著性: 事件數>=15用事件層bootstrap(對每事件一個彙總值,resample事件本身,B=2000,95%CI,
    排0視為顯著);事件數<15改用sign-flip置換檢定(對每事件配對差的正負號做隨機翻轉,任意n有效,
    p僅供方向線索參考,不宣稱嚴格顯著)——比照build_vol_addvalue_report.py的perm_diff_test精神,
    這裡改用sign-flip版本因為本卷的檢定單位本身已經是「配對差」而非兩獨立組,翻轉配對差正負號
    才是正確的虛無假設操作化;
  - 全程統一回傳dict schema({"method","stat","lo","hi","p","sig","n"}),避免姊妹考卷踩過的
    「不同bootstrap函式key不一致」的坑,呈現一律走同一個fmt_stat()。

用法: python 研究腳本/題材動能/build_theme_member_selection.py  (從根目錄執行,鐵律)
產出: 研究報告/research_theme_member_selection.html
"""
import re
import sqlite3
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

DB = "capital_flow.db"
V2_PANEL = "快取/tmp_theme_momentum_v2_panel.pkl"
PRICE_CACHE = "快取/tmp_revenue_price_cache.pkl"
OUT_PANEL = "快取/tmp_theme_member_selection_panel.pkl"
OUT_HTML = "研究報告/research_theme_member_selection.html"

TOP_FRAC = 1 / 3
MIN_EVENT_MEMBERS = 3      # 連續特徵tertile切法門檻
MIN_EVENT_MEMBERS_FLAG = 2  # 二元旗標切法門檻(至少一邊各1)
BOOT_MIN_N = 15             # 事件數門檻:>=用bootstrap,否則sign-flip置換
N_BOOT = 2000
N_PERM = 5000
SEED = 20260802
TDCC_LAG_DAYS = 3
TDCC_STALE_DAYS = 21
LIMITUP_THRESH = 9.5     # 寬鬆漲停判定門檻(收盤相對前一日收盤漲幅%),留誤差空間給10.00%理論值捨入
LIMITUP_MIN20 = 15       # 20日窗至少要有15個有效交易日才計數,避免用截斷窗口
LIMITUP_MIN60 = 45       # 60日窗至少要有45個有效交易日
rng_global = np.random.default_rng(SEED)

GREEN, RED, YELLOW, GRAY = "#7ec97e", "#e06c5a", "#c3a55a", "#8a8878"


# ══════════════════════ 0. 統計工具(統一dict schema) ══════════════════
def boot_mean_ci(vals, n_iter=N_BOOT, min_n=BOOT_MIN_N, seed=SEED):
    """對一組「事件層彙總值」(如每事件的top_demean)做古典bootstrap(逐事件已是獨立單位,
    直接resample陣列本身即可,不需再依日期分群——事件本身就是本卷的cluster)。"""
    v = pd.Series(vals, dtype=float).dropna()
    if len(v) < min_n:
        return None
    arr = v.values
    n = len(arr)
    rl = np.random.default_rng(seed)
    boots = np.empty(n_iter)
    for i in range(n_iter):
        boots[i] = arr[rl.integers(0, n, n)].mean()
    lo, hi = float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))
    m0 = float(arr.mean())
    return {"method": "bootstrap", "stat": m0, "lo": lo, "hi": hi, "p": None,
            "sig": bool(lo > 0 or hi < 0), "n": n}


def sign_flip_perm(vals, n_iter=N_PERM, seed=SEED):
    """事件數<15時的小樣本替代:對每事件的配對差做sign-flip置換檢定(虛無假設=配對差正負號
    隨機,任意n有效,檢定力隨n下降但方法本身不失效),p僅供方向線索參考。"""
    v = pd.Series(vals, dtype=float).dropna()
    n = len(v)
    if n == 0:
        return None
    arr = v.values
    obs = float(arr.mean())
    rl = np.random.default_rng(seed)
    signs = rl.choice(np.array([-1.0, 1.0]), size=(n_iter, n))
    means = (signs * arr).mean(axis=1)
    p = float((np.sum(np.abs(means) >= abs(obs) - 1e-12) + 1) / (n_iter + 1))
    return {"method": "permutation", "stat": obs, "lo": None, "hi": None, "p": p,
            "sig": bool(p < 0.10), "n": n}


def stat_test(vals, min_n=BOOT_MIN_N):
    v = pd.Series(vals, dtype=float).dropna()
    if len(v) >= min_n:
        return boot_mean_ci(vals, min_n=min_n)
    return sign_flip_perm(vals)


def fmt_stat(r, unit="pp"):
    if r is None:
        return "n=0,無法檢定"
    if r["method"] == "bootstrap":
        sig = "<b>✓排0顯著</b>" if r["sig"] else "含0不顯著"
        return f"{r['stat']:+.2f}{unit} 事件層bootstrap 95%CI[{r['lo']:+.2f},{r['hi']:+.2f}] {sig}(n事件={r['n']})"
    tag = "有方向線索(p&lt;0.10)" if r["sig"] else "無法區辨於雜訊(p≥0.10)"
    return f"{r['stat']:+.2f}{unit} sign-flip置換檢定p={r['p']:.3f} {tag}(n事件={r['n']})"


def pooled_desc(sub):
    """成員層級pooled絕對報酬描述性統計(ret60,單位%)。"""
    v = pd.Series(sub, dtype=float).dropna()
    if len(v) == 0:
        return {"n": 0, "median": None, "mean": None, "win": None}
    return {"n": int(len(v)), "median": float(v.median()), "mean": float(v.mean()),
            "win": float((v > 0).mean() * 100)}


# ══════════════════════ 1. 讀取score=4事件-成員panel(重用v2既有產出) ═══
def load_score4_panel():
    panel = pd.read_pickle(V2_PANEL).copy()
    s4 = panel[panel.score == 4].copy()
    s4["entry_day_ts"] = pd.to_datetime(s4["entry_day"])
    s4["period_last"] = s4["month_start"] - pd.DateOffset(months=1)  # score/trend_yoy3用的最後已公布月
    n_ev = s4.groupby(["industry", "year_month"]).ngroups
    print(f"[load] score=4子集: {len(s4)}筆成員-事件, {n_ev}個題材-月事件, "
          f"{s4.code.nunique()}檔個股, {s4.industry.nunique()}個題材, "
          f"{s4.year_month.min()}~{s4.year_month.max()}")
    return s4


# ══════════════════════ 2. 特徵②④:個股營收YoY/12月新高/佔題材營收比重趨勢 ═══
def compute_revenue_features(s4):
    conn = sqlite3.connect(DB)
    rev = pd.read_sql("SELECT code, date, revenue FROM fm_month_rev", conn, dtype={"code": str})
    cls = pd.read_sql("SELECT code, main_group FROM classification WHERE country='台'", conn,
                       dtype={"code": str}).drop_duplicates()
    conn.close()
    rev["m"] = pd.to_datetime(rev.date)
    rev_wide = rev.pivot_table(index="m", columns="code", values="revenue", aggfunc="first").sort_index()

    themes = s4.industry.unique()
    theme_tot = {}   # industry -> 題材(classification全成員)加總營收序列
    for ind in themes:
        codes = [c for c in cls.loc[cls.main_group == ind, "code"].unique() if c in rev_wide.columns]
        if not codes:
            continue
        theme_tot[ind] = rev_wide[codes].sum(axis=1, min_count=1)

    own_yoy3, rev12m_high, share_delta = [], [], []
    for row in s4.itertuples():
        code, ind, pl = row.code, row.industry, row.period_last
        own = rev_wide[code] if code in rev_wide.columns else None
        if own is None:
            own_yoy3.append(np.nan); rev12m_high.append(np.nan); share_delta.append(np.nan)
            continue

        # ②own_yoy3 = 個股自身近3個月YoY均值(shift(1)口徑,逐字比照題材trend_yoy3定義)
        yoys, ok = [], True
        for lag in (0, 1, 2):
            p = pl - pd.DateOffset(months=lag)
            p_prev = p - pd.DateOffset(months=12)
            v_now, v_prev = own.get(p, np.nan), own.get(p_prev, np.nan)
            if pd.isna(v_now) or pd.isna(v_prev) or v_prev == 0:
                ok = False
                break
            yoys.append(v_now / v_prev - 1)
        own_yoy3.append(float(np.mean(yoys)) * 100 if ok else np.nan)

        # ②b 月營收創近12個月新高(至少9/12個月有資料才判定,避免稀疏資料誤判)
        win_vals = [own.get(pl - pd.DateOffset(months=m), np.nan) for m in range(12)]
        valid = [v for v in win_vals if pd.notna(v)]
        if len(valid) >= 9 and pd.notna(win_vals[0]):
            rev12m_high.append(bool(win_vals[0] >= max(valid)))
        else:
            rev12m_high.append(np.nan)

        # ④佔題材營收比重的YoY變化(pp)
        tot = theme_tot.get(ind)
        if tot is None:
            share_delta.append(np.nan)
            continue
        tot_now, tot_prev = tot.get(pl, np.nan), tot.get(pl - pd.DateOffset(months=12), np.nan)
        v_now, v_prev = own.get(pl, np.nan), own.get(pl - pd.DateOffset(months=12), np.nan)
        share_now = v_now / tot_now if pd.notna(tot_now) and tot_now != 0 and pd.notna(v_now) else np.nan
        share_prev = v_prev / tot_prev if pd.notna(tot_prev) and tot_prev != 0 and pd.notna(v_prev) else np.nan
        share_delta.append((share_now - share_prev) * 100 if pd.notna(share_now) and pd.notna(share_prev) else np.nan)

    return pd.DataFrame({"own_yoy3": own_yoy3, "rev12m_high": rev12m_high,
                          "share_delta_yoy_pp": share_delta}, index=s4.index)


# ══════════════════════ 3. 特徵①價格相對強勢 + ⑥成交值熱度百分位 ══════════
def compute_price_features(s4):
    import pickle
    with open(PRICE_CACHE, "rb") as f:
        cache = pickle.load(f)
    codes = s4.code.unique()
    per_code = {}
    for code in codes:
        c = cache.get(code)
        if c is None:
            continue
        close, vol = c["Close"], c["Volume"]
        if hasattr(close, "columns"):
            close = close.iloc[:, 0]
        if hasattr(vol, "columns"):
            vol = vol.iloc[:, 0]
        turnover = close * vol   # Close×Volume近似成交值(cache無money欄位,用此近似)
        amt20 = turnover.rolling(20, min_periods=15).mean()
        heat = amt20.rolling(240, min_periods=120).rank(pct=True) * 100
        per_code[code] = (close, heat)

    mom20, mom60, turn_pct = [], [], []
    for row in s4.itertuples():
        pack = per_code.get(row.code)
        if pack is None:
            mom20.append(np.nan); mom60.append(np.nan); turn_pct.append(np.nan)
            continue
        close, heat = pack
        entry = row.entry_day_ts
        if entry not in close.index:
            mom20.append(np.nan); mom60.append(np.nan); turn_pct.append(np.nan)
            continue
        pos = close.index.get_loc(entry)
        mom20.append((close.iloc[pos] / close.iloc[pos - 20] - 1) * 100 if pos >= 20 else np.nan)
        mom60.append((close.iloc[pos] / close.iloc[pos - 60] - 1) * 100 if pos >= 60 else np.nan)
        # 熱度百分位取pos-1(嚴格早於進場日),避免用到進場當日才確定的量能資訊
        turn_pct.append(heat.iloc[pos - 1] if pos >= 1 else np.nan)
    return pd.DataFrame({"mom20": mom20, "mom60": mom60, "turn_pct": turn_pct}, index=s4.index)


# ══════════════════════ 4. 特徵③外資20日位階(canonical S4,逐字複用) ═══════
def compute_foreign_feature(s4):
    conn = sqlite3.connect(DB)
    fl = pd.read_sql("SELECT date, code, foreign_net FROM inst_flow", conn, parse_dates=["date"])
    conn.close()
    fl = fl[fl.code.str.fullmatch(r"[1-9]\d{3}")]
    fn = fl.pivot_table(index="date", columns="code", values="foreign_net").sort_index()
    fpct = fn.rolling(20, min_periods=10).sum().rolling(240, min_periods=120).rank(pct=True) * 100
    long = fpct.stack().rename_axis(["date", "code"]).reset_index(name="fpc")
    long = long.sort_values("date").reset_index(drop=True)

    ev = pd.DataFrame({"code": s4["code"].values, "entry_day": s4["entry_day_ts"].values,
                        "orig_idx": s4.index})
    ev = ev.sort_values("entry_day").reset_index(drop=True)
    merged = pd.merge_asof(ev, long, left_on="entry_day", right_on="date", by="code",
                            direction="backward", allow_exact_matches=False)
    merged = merged.set_index("orig_idx").reindex(s4.index)
    return merged["fpc"]


# ══════════════════════ 5. 特徵⑤TDCC大戶持股比例趨勢(d4w_1000,逐字複用) ═══
def compute_tdcc_feature(s4):
    conn = sqlite3.connect(DB)
    tw = pd.read_sql("SELECT date, code, p1000 FROM tdcc_weekly", conn, parse_dates=["date"])
    conn.close()
    wide = tw.pivot_table(index="date", columns="code", values="p1000").sort_index()
    d4w = wide - wide.shift(4)
    long = d4w.stack().rename_axis(["date", "code"]).reset_index(name="d4w_1000")
    long = long.sort_values("date").reset_index(drop=True)

    ev = pd.DataFrame({"code": s4["code"].values,
                        "cutoff": s4["entry_day_ts"].values - pd.Timedelta(days=TDCC_LAG_DAYS),
                        "orig_idx": s4.index})
    ev = ev.sort_values("cutoff").reset_index(drop=True)
    merged = pd.merge_asof(ev, long, left_on="cutoff", right_on="date", by="code",
                            direction="backward", tolerance=pd.Timedelta(days=TDCC_STALE_DAYS))
    merged = merged.set_index("orig_idx").reindex(s4.index)
    return merged["d4w_1000"]


# ══════════════════════ 5b. 特徵⑦漲停次數(短期極端跳躍/軋空味,2026-08-03使用者追加) ═══
def compute_limitup_features(s4):
    """⑦題材觸發前短時間內個股漲停次數——概念上與①的平滑trailing報酬不同,抓的是「短期內
    多次觸及漲停」這種極端跳躍式注意力/軋空味,不是平滑動能。直接用fm_daily_price原始價格
    (不用yfinance調整價cache,漲停判定必須看真實成交價,調整價的除權息平移會誤判)。
    寬鬆判定=收盤相對前一日收盤漲幅>=9.5%(留誤差空間給理論漲停價10.00%的小數捨入);
    嚴格對照=寬鬆條件成立且當日high==low==close(一字鎖死型)。
    計數窗口=進場日「之前」20/60個交易日(不含進場日當天本身,窗口需至少15/45個有效交易日
    才計數,避免用截斷窗口算出不可靠的次數)。"""
    codes = sorted(s4.code.unique())
    conn = sqlite3.connect(DB)
    ph = ",".join("?" * len(codes))
    px = pd.read_sql(f"SELECT code, date, high, low, close FROM fm_daily_price WHERE code IN ({ph})",
                      conn, params=codes, parse_dates=["date"])
    conn.close()
    px = px.sort_values(["code", "date"])
    px["prev_close"] = px.groupby("code")["close"].shift(1)
    px["ret"] = (px["close"] / px["prev_close"] - 1) * 100
    px["loose"] = px["ret"] >= LIMITUP_THRESH
    px["strict"] = px["loose"] & (px["high"] == px["low"]) & (px["high"] == px["close"])

    # 逐股票用「自己實際交易日」的序列做rolling(不透過shared calendar pivot——避免掛牌較晚的
    # 個股把「尚未掛牌」的日子誤當成「已交易但無漲停」的0值,拉高min_periods覆蓋率的假象)
    per_code = {}
    for code, g in px.groupby("code"):
        g = g.sort_values("date")
        loose_s = pd.Series(g["loose"].values, index=pd.DatetimeIndex(g["date"].values))
        strict_s = pd.Series(g["strict"].values, index=pd.DatetimeIndex(g["date"].values))
        per_code[code] = (
            loose_s.rolling(20, min_periods=LIMITUP_MIN20).sum(),
            loose_s.rolling(60, min_periods=LIMITUP_MIN60).sum(),
            strict_s.rolling(20, min_periods=LIMITUP_MIN20).sum(),
            strict_s.rolling(60, min_periods=LIMITUP_MIN60).sum(),
        )

    l20, l60, s20, s60 = [], [], [], []
    for row in s4.itertuples():
        pack = per_code.get(row.code)
        if pack is None:
            l20.append(np.nan); l60.append(np.nan); s20.append(np.nan); s60.append(np.nan)
            continue
        loose_roll20, loose_roll60, strict_roll20, strict_roll60 = pack
        idx = loose_roll20.index  # 該股自己的實際交易日索引(loose/strict四個series共用同一組index)
        entry = row.entry_day_ts
        pos = idx.searchsorted(entry)  # idx[:pos]皆嚴格早於entry
        if pos < 1:
            l20.append(np.nan); l60.append(np.nan); s20.append(np.nan); s60.append(np.nan)
            continue
        prev_pos = pos - 1  # 進場日前一個交易日的位置,該位置的rolling(w).sum()=之前w日計數(不含entry當天)
        l20.append(loose_roll20.iloc[prev_pos])
        l60.append(loose_roll60.iloc[prev_pos])
        s20.append(strict_roll20.iloc[prev_pos])
        s60.append(strict_roll60.iloc[prev_pos])

    return pd.DataFrame({"limitup20": l20, "limitup60": l60,
                          "limitup20_strict": s20, "limitup60_strict": s60}, index=s4.index)


def limitup_dist_stats(s4):
    """回傳漲停次數分布(0次/1次/>=2次占比),供報告文字與分組決策使用。"""
    out = {}
    for col in ("limitup20", "limitup60", "limitup20_strict", "limitup60_strict"):
        v = s4[col].dropna()
        if len(v) == 0:
            out[col] = None
            continue
        out[col] = {"n": int(len(v)), "p0": float((v == 0).mean() * 100),
                     "p1": float((v == 1).mean() * 100), "p2plus": float((v >= 2).mean() * 100)}
    return out


# ══════════════════════ 5c. 特徵⑧個股自身波動度(2026-08-03使用者追加) ═══════
def compute_volatility_features(s4):
    """⑧個股自身波動度——⚠與build_vol_addvalue_report.py/build_vol_updown_explore.py測的問題
    不同: 那兩支姊妹卷問的是「大盤/題材整體波動regime要不要疊加當開關」(結論=不加值);本卷問的是
    「題材觸發後,題材內部各成員『自己』的波動水準/好壞波動分解,拿來橫向挑成員/加權有沒有用」——
    是成員層級的橫向比較,不是市場層級的regime判斷,方法論完全不同,不要混為一談。

    算法逐字複用build_vol_updown_explore.py::vol_updown(),只是把輸入從大盤/題材指數換成個股
    自己的收盤價序列(不重新設計):
      vol_std_w = 該函式回傳的std_w(rolling w日日報酬標準差,ddof=1),與本專案vol10/vol60/ts/vp10
        既有regime系統同一套算法——選這個當波動度水準主口徑,因為它是這批姊妹卷共同的既有基準指標,
        不另外設計新的ATR或其他量尺;該函式同時回傳的rv_w(平方和開根號版)與std_w高度相關(同一組
        r^2的不同聚合方式),不重複列。
      vol_bshare_w = 該函式回傳的bshare_w(壞波動占比%=負報酬日平方和/總平方和×100),逐字沿用。
    取pos-1(進場日前一交易日),避免用到進場當日才確定的報酬/波動資訊(比照⑥成交值熱度百分位的
    convention)。用20日/60日兩個窗口,比照①價格動能已測過的窗口組合方便對照。"""
    import pickle
    if "研究腳本/綜合策略" not in sys.path:
        sys.path.insert(0, "研究腳本/綜合策略")
    import build_vol_updown_explore as VUmod  # noqa: E402  vol_updown()逐字複用,不重新設計

    with open(PRICE_CACHE, "rb") as f:
        cache = pickle.load(f)
    codes = s4.code.unique()
    per_code = {}
    for code in codes:
        c = cache.get(code)
        if c is None:
            continue
        close = c["Close"]
        if hasattr(close, "columns"):
            close = close.iloc[:, 0]
        # 不覆寫windows參數: vol_updown()內部固定要用std10算ts/vp10,若只傳(20,60)會KeyError;
        # 用預設WINDOWS=(10,20,60)呼叫,本卷只取用std20/std60/bshare20/bshare60,ts/vp10不使用。
        per_code[code] = VUmod.vol_updown(close)

    std20, std60, bshare20, bshare60 = [], [], [], []
    for row in s4.itertuples():
        vu = per_code.get(row.code)
        if vu is None:
            std20.append(np.nan); std60.append(np.nan); bshare20.append(np.nan); bshare60.append(np.nan)
            continue
        idx = vu["r"].index
        entry = row.entry_day_ts
        pos = idx.searchsorted(entry)
        if pos < 1:
            std20.append(np.nan); std60.append(np.nan); bshare20.append(np.nan); bshare60.append(np.nan)
            continue
        prev_pos = pos - 1
        std20.append(vu["std20"].iloc[prev_pos])
        std60.append(vu["std60"].iloc[prev_pos])
        bshare20.append(vu["bshare20"].iloc[prev_pos])
        bshare60.append(vu["bshare60"].iloc[prev_pos])

    return pd.DataFrame({"vol_std20": std20, "vol_std60": std60,
                          "vol_bshare20": bshare20, "vol_bshare60": bshare60}, index=s4.index)


def volatility_desc_stats(s4):
    """描述性統計(中位數/均值),供報告文字脈絡用——不是分組判讀本身。"""
    out = {}
    for col in ("vol_std20", "vol_std60", "vol_bshare20", "vol_bshare60"):
        v = s4[col].dropna()
        out[col] = {"n": int(len(v)), "median": float(v.median()), "mean": float(v.mean())} if len(v) else None
    return out


# ══════════════════════ 6. 事件內分組(top/bottom third,或flag) + 彙總 ══════
def split_continuous(s4, feat, top_frac=TOP_FRAC, min_members=MIN_EVENT_MEMBERS):
    """連續特徵:事件內依feat排序,取前1/3(top)、後1/3(bottom)。回傳(事件層df, top成員df, bottom成員df)。"""
    ev_rows, tops, bottoms = [], [], []
    for (ind, ym), g in s4.groupby(["industry", "year_month"]):
        gv = g.dropna(subset=[feat])
        n = len(gv)
        if n < min_members:
            continue
        k = max(1, int(np.ceil(n * top_frac)))
        gs = gv.sort_values(feat, ascending=False)
        top, bottom = gs.iloc[:k], gs.iloc[-k:]
        all_mean = gv.ret60.mean()
        top_mean, bottom_mean = top.ret60.mean(), bottom.ret60.mean()
        ev_rows.append(dict(industry=ind, year_month=ym, n=n, n_top=len(top), n_bottom=len(bottom),
                             all_mean=all_mean, top_mean=top_mean, bottom_mean=bottom_mean,
                             diff=top_mean - bottom_mean, top_demean=top_mean - all_mean,
                             bottom_demean=bottom_mean - all_mean))
        tops.append(top); bottoms.append(bottom)
    ev_df = pd.DataFrame(ev_rows)
    top_df = pd.concat(tops) if tops else pd.DataFrame(columns=s4.columns)
    bottom_df = pd.concat(bottoms) if bottoms else pd.DataFrame(columns=s4.columns)
    return ev_df, top_df, bottom_df


def split_flag(s4, feat, min_members=MIN_EVENT_MEMBERS_FLAG):
    """二元旗標特徵:事件內分「有此屬性(top)」vs「無此屬性(bottom)」,雙邊都要有成員才計入。"""
    ev_rows, tops, bottoms = [], [], []
    for (ind, ym), g in s4.groupby(["industry", "year_month"]):
        gv = g.dropna(subset=[feat])
        n = len(gv)
        if n < min_members:
            continue
        top, bottom = gv[gv[feat] == True], gv[gv[feat] == False]  # noqa: E712
        if len(top) == 0 or len(bottom) == 0:
            continue
        all_mean = gv.ret60.mean()
        top_mean, bottom_mean = top.ret60.mean(), bottom.ret60.mean()
        ev_rows.append(dict(industry=ind, year_month=ym, n=n, n_top=len(top), n_bottom=len(bottom),
                             all_mean=all_mean, top_mean=top_mean, bottom_mean=bottom_mean,
                             diff=top_mean - bottom_mean, top_demean=top_mean - all_mean,
                             bottom_demean=bottom_mean - all_mean))
        tops.append(top); bottoms.append(bottom)
    ev_df = pd.DataFrame(ev_rows)
    top_df = pd.concat(tops) if tops else pd.DataFrame(columns=s4.columns)
    bottom_df = pd.concat(bottoms) if bottoms else pd.DataFrame(columns=s4.columns)
    return ev_df, top_df, bottom_df


def analyze_feature(s4, feat, kind="cont", label=""):
    if kind == "cont":
        ev_df, top_df, bottom_df = split_continuous(s4, feat)
    else:
        ev_df, top_df, bottom_df = split_flag(s4, feat)
    if len(ev_df) == 0:
        return {"feat": feat, "label": label, "n_ev": 0}
    res = {
        "feat": feat, "label": label, "n_ev": len(ev_df),
        "top_abs": pooled_desc(top_df.ret60), "bottom_abs": pooled_desc(bottom_df.ret60),
        "diff_test": stat_test(ev_df["diff"].values),
        "top_demean_test": stat_test(ev_df["top_demean"].values),
        "bottom_demean_test": stat_test(ev_df["bottom_demean"].values),
        "ev_df": ev_df,
    }
    return res


# ══════════════════════ 7. 特徵組合測試(使用者指定範例: 外資高+佔比升) ══════
def analyze_combo(s4, feat_a, feat_b, top_frac=TOP_FRAC, min_members=MIN_EVENT_MEMBERS):
    ev_rows, combos = [], []
    for (ind, ym), g in s4.groupby(["industry", "year_month"]):
        gv = g.dropna(subset=[feat_a, feat_b])
        n = len(gv)
        if n < min_members:
            continue
        k = max(1, int(np.ceil(n * top_frac)))
        top_a = set(gv.sort_values(feat_a, ascending=False).iloc[:k].code)
        top_b = set(gv.sort_values(feat_b, ascending=False).iloc[:k].code)
        combo_codes = top_a & top_b
        if not combo_codes:
            continue
        combo = gv[gv.code.isin(combo_codes)]
        all_mean = gv.ret60.mean()
        combo_mean = combo.ret60.mean()
        ev_rows.append(dict(industry=ind, year_month=ym, n=n, n_combo=len(combo),
                             all_mean=all_mean, combo_mean=combo_mean, combo_demean=combo_mean - all_mean))
        combos.append(combo)
    ev_df = pd.DataFrame(ev_rows)
    combo_df = pd.concat(combos) if combos else pd.DataFrame(columns=s4.columns)
    if len(ev_df) == 0:
        return {"n_ev": 0}
    return {"n_ev": len(ev_df), "n_events_all": s4.groupby(["industry", "year_month"]).ngroups,
            "combo_abs": pooled_desc(combo_df.ret60),
            "demean_test": stat_test(ev_df["combo_demean"].values), "ev_df": ev_df}


# ══════════════════════ 8. 加權測試(bonus): 線性排序加權 vs 等權 ═══════════
def analyze_weighting(s4, feat, min_members=MIN_EVENT_MEMBERS):
    rows = []
    for (ind, ym), g in s4.groupby(["industry", "year_month"]):
        gv = g.dropna(subset=[feat])
        n = len(gv)
        if n < min_members:
            continue
        ranks = gv[feat].rank(method="average")  # 1=最小...n=最大
        w = ranks / ranks.sum()
        weighted_ret = float((w * gv.ret60).sum())
        equal_ret = float(gv.ret60.mean())
        rows.append(dict(industry=ind, year_month=ym, n=n, weighted_ret=weighted_ret,
                          equal_ret=equal_ret, diff=weighted_ret - equal_ret))
    ev_df = pd.DataFrame(rows)
    if len(ev_df) == 0:
        return {"n_ev": 0}
    return {"n_ev": len(ev_df), "diff_test": stat_test(ev_df["diff"].values),
            "weighted_abs": pooled_desc(ev_df.weighted_ret), "equal_abs": pooled_desc(ev_df.equal_ret),
            "ev_df": ev_df}


# ══════════════════════ 主流程 ═══════════════════════════════════════
FEATURES = [
    ("mom20", "cont", "①價格相對強勢(進場前20日trailing報酬)"),
    ("mom60", "cont", "①價格相對強勢(進場前60日trailing報酬)"),
    ("own_yoy3", "cont", "②個股自身YoY相對突出(近3月YoY均值,題材內排名)"),
    ("rev12m_high", "flag", "②b月營收創近12個月新高(旗標)"),
    ("fpc", "cont", "③外資20日累計位階(canonical S4)"),
    ("share_delta_yoy_pp", "cont", "④佔題材營收比重的YoY變化(pp)"),
    ("d4w_1000", "cont", "⑤TDCC大戶(千張)持股比例4週變化(pp)"),
    ("turn_pct", "cont", "⑥成交值熱度百分位(自身240日,Close×Volume近似)"),
    ("limitup20_any", "flag", "⑦漲停次數(進場前20日≥1次 vs 0次,寬鬆門檻收盤漲幅≥9.5%)"),
    ("limitup60_any", "flag", "⑦漲停次數(進場前60日≥1次 vs 0次)"),
    ("limitup20_dose2", "flag", "⑦b漲停次數dose-response(20日≥2次 vs 0次,1次視為中間組排除)"),
    ("limitup60_dose2", "flag", "⑦b漲停次數dose-response(60日≥2次 vs 0次,1次視為中間組排除)"),
    ("limitup60_strict_any", "flag", "⑦c穩健對照:一字鎖死型漲停(60日≥1次 vs 0次,high=low=close)"),
    ("vol_std20", "cont", "⑧個股自身波動度(20日std,高vs低)"),
    ("vol_std60", "cont", "⑧個股自身波動度(60日std,高vs低)"),
    ("vol_bshare20", "cont", "⑧b個股好壞波動分解(bshare20,壞波動占比高vs低)"),
    ("vol_bshare60", "cont", "⑧b個股好壞波動分解(bshare60,壞波動占比高vs低,穩健對照)"),
]


def main():
    import os
    if os.path.exists(OUT_PANEL):
        s4 = pd.read_pickle(OUT_PANEL)
        print(f"[load] 沿用既有特徵面板 {OUT_PANEL} (2026-08-03使用者指示不重蓋六角度既有資料): "
              f"{len(s4)}筆, {s4.groupby(['industry', 'year_month']).ngroups}事件")
    else:
        s4 = load_score4_panel()
        print("\n[特徵計算] ②④個股營收特徵...")
        rev_feat = compute_revenue_features(s4)
        print("[特徵計算] ①⑥價格動能/成交值熱度...")
        price_feat = compute_price_features(s4)
        print("[特徵計算] ③外資20日位階...")
        foreign_feat = compute_foreign_feature(s4)
        print("[特徵計算] ⑤TDCC大戶持股趨勢...")
        tdcc_feat = compute_tdcc_feature(s4)
        s4 = pd.concat([s4, rev_feat, price_feat], axis=1)
        s4["fpc"] = foreign_feat
        s4["d4w_1000"] = tdcc_feat

    print("\n[特徵計算] ⑦漲停次數(短期極端跳躍/軋空味,2026-08-03新增角度)...")
    limitup_feat = compute_limitup_features(s4)
    s4 = pd.concat([s4.drop(columns=[c for c in limitup_feat.columns if c in s4.columns]), limitup_feat], axis=1)

    # 依實際分布決定分組切法(見limitup_dist_stats印出的比例):
    #   0次比例高(20日窗77%/60日窗52%),不適合硬湊tertile,主判讀改用「≥1次 vs 0次」二分;
    #   ≥2次占比20日8.5%/60日24.8%不算太稀薄,另做dose-response版「≥2次 vs 0次」(1次視為中間組排除)
    #   當劑量梯度穩健性對照;一字鎖死型嚴格版60日≥1次僅6%、20日僅1.6%(20日太稀疏,只描述性提及不正式檢定)。
    s4["limitup20_any"] = s4["limitup20"].apply(lambda v: np.nan if pd.isna(v) else v >= 1)
    s4["limitup60_any"] = s4["limitup60"].apply(lambda v: np.nan if pd.isna(v) else v >= 1)
    s4["limitup20_dose2"] = s4["limitup20"].apply(lambda v: np.nan if pd.isna(v) or v == 1 else v >= 2)
    s4["limitup60_dose2"] = s4["limitup60"].apply(lambda v: np.nan if pd.isna(v) or v == 1 else v >= 2)
    s4["limitup60_strict_any"] = s4["limitup60_strict"].apply(lambda v: np.nan if pd.isna(v) else v >= 1)

    dist = limitup_dist_stats(s4)
    print("[漲停次數分布] (0次/1次/>=2次占比,%):")
    for col, d in dist.items():
        if d is None:
            print(f"  {col}: 無有效樣本")
        else:
            print(f"  {col}: n={d['n']} 0次={d['p0']:.1f}% 1次={d['p1']:.1f}% >=2次={d['p2plus']:.1f}%")

    print("\n[特徵計算] ⑧個股自身波動度/好壞波動分解(2026-08-03新增角度,個股層級橫向比較,"
          "非市場regime判斷)...")
    vol_feat = compute_volatility_features(s4)
    s4 = pd.concat([s4.drop(columns=[c for c in vol_feat.columns if c in s4.columns]), vol_feat], axis=1)
    vol_dist = volatility_desc_stats(s4)
    print("[波動度描述性統計] (中位數/均值):")
    for col, d in vol_dist.items():
        if d is None:
            print(f"  {col}: 無有效樣本")
        else:
            print(f"  {col}: n={d['n']} 中位{d['median']:.2f} 均{d['mean']:.2f}")

    print("\n[覆蓋率] 各特徵非空筆數 / 總筆數({}):".format(len(s4)))
    for feat, kind, label in FEATURES:
        print(f"  {feat}: {s4[feat].notna().sum()}")

    s4.to_pickle(OUT_PANEL)
    print(f"\n已存特徵面板(含⑦漲停次數+⑧波動度) -> {OUT_PANEL}")

    print("\n" + "=" * 90)
    results = {}
    for feat, kind, label in FEATURES:
        r = analyze_feature(s4, feat, kind, label)
        results[feat] = r
        if r["n_ev"] == 0:
            print(f"{label}: 無足夠事件")
            continue
        print(f"\n{label} (事件數={r['n_ev']})")
        print(f"  top組絕對: n={r['top_abs']['n']} 中位{r['top_abs']['median']:+.2f}% "
              f"均{r['top_abs']['mean']:+.2f}% 勝率{r['top_abs']['win']:.0f}%")
        print(f"  bottom組絕對: n={r['bottom_abs']['n']} 中位{r['bottom_abs']['median']:+.2f}% "
              f"均{r['bottom_abs']['mean']:+.2f}% 勝率{r['bottom_abs']['win']:.0f}%")
        print(f"  top-bottom配對差: {fmt_stat(r['diff_test'])}")
        print(f"  top對等權baseline增量: {fmt_stat(r['top_demean_test'])}")
        print(f"  bottom對等權baseline增量: {fmt_stat(r['bottom_demean_test'])}")

    print("\n" + "=" * 90 + "\n[特徵組合] 外資位階高 ∧ 佔題材營收比重上升(使用者指定範例)")
    combo = analyze_combo(s4, "fpc", "share_delta_yoy_pp")
    results["combo_fpc_share"] = combo
    if combo["n_ev"]:
        print(f"  雙重篩選事件數={combo['n_ev']}/{combo['n_events_all']} "
              f"組合組絕對: n={combo['combo_abs']['n']} 中位{combo['combo_abs']['median']:+.2f}% "
              f"勝率{combo['combo_abs']['win']:.0f}%")
        print(f"  對等權baseline增量: {fmt_stat(combo['demean_test'])}")
    else:
        print("  無足夠事件(雙重篩選後太稀疏)")

    print("\n" + "=" * 90 + "\n[加權測試] 線性排序加權 vs 等權(挑選單一特徵效果最清楚者測試)")
    best_feat = max(
        (f for f, k, l in FEATURES if results[f]["n_ev"] > 0),
        key=lambda f: abs(results[f]["diff_test"]["stat"]) if results[f]["diff_test"] else 0,
        default=None,
    )
    weighting = {}
    if best_feat:
        print(f"  挑選特徵: {best_feat} (top-bottom配對差點估計絕對值最大)")
        weighting = analyze_weighting(s4, best_feat)
        if weighting["n_ev"]:
            print(f"  加權-等權差: {fmt_stat(weighting['diff_test'])}")
    results["weighting_feat"] = best_feat
    results["weighting"] = weighting
    results["limitup_dist"] = dist
    results["vol_dist"] = vol_dist

    build_html(s4, results)
    print(f"\n已產出 {OUT_HTML}")


# ══════════════════════ HTML 組裝 ═══════════════════════════════════
def verdict_from_tests(diff_test, top_demean_test):
    """依實際數值正負號+顯著性動態生成判讀文字,不寫死方向。"""
    if diff_test is None:
        return "樣本不足", GRAY
    diff_sig = diff_test["sig"]
    diff_dir = diff_test["stat"] > 0
    demean_sig = top_demean_test["sig"] if top_demean_test else False
    demean_dir = top_demean_test["stat"] > 0 if top_demean_test else False
    if diff_sig and diff_dir and demean_sig and demean_dir:
        return "挑股有效(top顯著贏過baseline)", GREEN
    if diff_sig and diff_dir:
        return "top顯著贏bottom,但對baseline增量不顯著", YELLOW
    if diff_sig and not diff_dir:
        return "方向與假說相反(bottom顯著贏top)", RED
    return "無法區辨於雜訊", GRAY


def fmt_grp(g):
    if not g or g.get("n", 0) == 0 or g.get("median") is None:
        return "<td>0</td><td>—</td><td>—</td>"
    cls = "good" if g["median"] > 0 else "bad"
    return f"<td>{g['n']}</td><td class='{cls}'>{g['median']:+.2f}%</td><td>{g['win']:.0f}%</td>"


def build_html(s4, results):
    css = """
body{background:#1a1a19;color:#fff;font-family:"Noto Sans TC",sans-serif;margin:24px;max-width:1180px}
h1{font-size:20px} h2{font-size:15px;color:#c3c2b7;margin-top:34px;border-bottom:1px solid #333;padding-bottom:4px}
h3{font-size:13.5px;color:#a8a79a;margin:16px 0 4px}
table{border-collapse:collapse;font-size:12.5px;font-variant-numeric:tabular-nums;margin:8px 0}
td,th{border:1px solid #333;padding:4px 9px;text-align:right} th{text-align:left;color:#c3c2b7}
.note{color:#8a8878;font-size:12.5px;line-height:1.8} .good{color:#7ec97e} .bad{color:#e06c5a}
.warn{color:#c3a55a} .v-good{color:#7ec97e;font-weight:600} .v-bad{color:#e06c5a;font-weight:600}
.v-warn{color:#c3a55a;font-weight:600} .sub{color:#777;font-size:11px}
.flex{display:flex;gap:24px;flex-wrap:wrap} .flex>div{flex:1;min-width:300px}
"""
    n_ev_total = s4.groupby(["industry", "year_month"]).ngroups
    n_all = len(s4)

    # ---- 總覽 ----
    summary_rows = ""
    for feat, kind, label in FEATURES:
        r = results[feat]
        if r["n_ev"] == 0:
            summary_rows += f"<tr><th style='text-align:left'>{label}</th><td colspan='3'>樣本不足,無法分析</td></tr>"
            continue
        verdict, color = verdict_from_tests(r["diff_test"], r["top_demean_test"])
        summary_rows += (
            f"<tr><th style='text-align:left'>{label}</th><td>{r['n_ev']}</td>"
            f"<td style='color:{color};font-weight:600'>{verdict}</td>"
            f"<td style='text-align:left'>top-bottom配對差{fmt_stat(r['diff_test'])}</td></tr>")

    # ---- 逐特徵細節 ----
    detail_html = ""
    for feat, kind, label in FEATURES:
        r = results[feat]
        if r["n_ev"] == 0:
            detail_html += f"<h2>{label}</h2><div class='note warn'>樣本不足,無法分析。</div>"
            continue
        verdict, color = verdict_from_tests(r["diff_test"], r["top_demean_test"])
        detail_html += f"""
<h2>{label}</h2>
<div class="note">事件數={r['n_ev']} / 全部score=4事件{n_ev_total}個。
<b style="color:{color}">判讀: {verdict}</b></div>
<div class="flex">
<div><h3>絕對報酬層(成員層級pooled,是否本身為正)</h3>
<table><tr><th>組別</th><th>n</th><th>中位ret60</th><th>勝率</th></tr>
<tr><th>top third</th>{fmt_grp(r['top_abs'])}</tr>
<tr><th>bottom third</th>{fmt_grp(r['bottom_abs'])}</tr></table></div>
<div><h3>相對baseline層(事件層配對,vs等權全買)</h3>
<ul>
<li>top-bottom配對差: {fmt_stat(r['diff_test'])}</li>
<li>top對等權baseline增量: {fmt_stat(r['top_demean_test'])}</li>
<li>bottom對等權baseline增量: {fmt_stat(r['bottom_demean_test'])}</li>
</ul></div>
</div>"""
        if feat == "limitup60_strict_any" and r["diff_test"] and r["diff_test"]["sig"]:
            detail_html += """
<div class="note warn">⚠這是⑦漲停次數家族裡覆蓋率最低(~6%)、事件數剛好貼著本卷bootstrap最低
門檻(n&gt;=15)的最極端子版本,寬鬆版(≥1次/dose-response≥2次)都不顯著,見上方⑦與⑦b。話雖如此,
從寬鬆到嚴格的子版本呈現大致一致的方向梯度(漲停次數越極端/越稀有,後續60日表現越傾向落後同事件的
等權baseline),可能反映「軋空式急拉已把短期漲幅提前兌現」的獲利了結/透支效應——這個跨子版本的方向
一致性讓這個發現比單一孤立的顯著結果稍微可信一點,但下方全報告多重比較提醒仍適用,不能單獨拿這一格
下定論。</div>"""

    # ---- 全報告多重比較誠實提醒(動態掃描FEATURES全部特徵,不侷限特定家族,新角度加進來
    #      會自動被納入這個統計,不需要每次追加角度都手改一段新文字) ----
    feat_label_map = dict((f, l) for f, k, l in FEATURES)
    all_valid = [(f, results[f]) for f, k, l in FEATURES if results.get(f, {}).get("n_ev", 0) > 0]
    sig_hits = [(f, r) for f, r in all_valid if r["diff_test"] and r["diff_test"]["sig"]]
    total_tests = (len(all_valid)
                   + (1 if results.get("combo_fpc_share", {}).get("n_ev") else 0)
                   + (1 if results.get("weighting", {}).get("n_ev") else 0))
    expected_false_pos = total_tests * 0.05
    if sig_hits:
        hit_lines = "".join(
            f"<li>{feat_label_map.get(k, k)}: 事件數={r['n_ev']}, top-bottom配對差{fmt_stat(r['diff_test'])}</li>"
            for k, r in sig_hits)
        detail_html += f"""
<div class="note warn"><b>⚠誠實提醒(多重比較風險,全報告層級): </b>本報告目前累計對{total_tests}個
獨立事件層檢定(各特徵角度+特徵組合+加權測試,含子版本各自計入)做了95%CI/置換檢定,在此標準下
純屬運氣就預期會出現約{expected_false_pos:.1f}個「顯著」的假陽性——目前排0顯著的共有{len(sig_hits)}個
(見下方清單),數量與運氣下的期望值同一量級,<b>不能單憑某個角度排0顯著就當作可交易訊號</b>,
每一個都需要獨立樣本外複驗才能升級為結論:<ul>{hit_lines}</ul></div>"""
    else:
        detail_html += f"""
<div class="note">多重比較提醒: 本報告目前累計對{total_tests}個獨立事件層檢定做了95%CI/置換檢定,
截至目前沒有任何一個排0顯著——在這個檢定數量下,若真的存在某個穩定的選股/加權訊號,理論上有機會
被抓到至少一個,持續全部落空本身也是一種(較弱的)證據,支持「等權全買在這個樣本裡很難被系統性打敗」
這個誠實結論。</div>"""

    # ---- 特徵組合 ----
    combo = results.get("combo_fpc_share", {})
    if combo.get("n_ev"):
        combo_html = f"""
<div class="note">雙重篩選(外資位階題材內前1/3 ∧ 佔比YoY變化題材內前1/3)事件數={combo['n_ev']}
/ 全部{combo.get('n_events_all', n_ev_total)}個(能同時滿足兩個條件的成員通常很少,樣本會比單一特徵小很多)。</div>
<table><tr><th>組別</th><th>n</th><th>中位ret60</th><th>勝率</th></tr>
<tr><th>雙重篩選組(絕對)</th>{fmt_grp(combo['combo_abs'])}</tr></table>
<div class="note">對等權baseline增量: {fmt_stat(combo['demean_test'])}</div>"""
    else:
        combo_html = "<div class='note warn'>雙重篩選後事件數過少,無法分析(樣本不足)。</div>"

    # ---- 加權測試 ----
    weighting = results.get("weighting", {})
    wfeat = results.get("weighting_feat")
    wfeat_label = dict((f, l) for f, k, l in FEATURES).get(wfeat, wfeat)
    if weighting.get("n_ev"):
        weight_html = f"""
<div class="note">挑選特徵: {wfeat_label}(單特徵top-bottom配對差點估計絕對值最大者)。
逐事件用該特徵題材內排名做線性加權(rank/Σrank)取代硬篩選子集,權重最高給予特徵值最大的成員,
與等權全買比較,事件數={weighting['n_ev']}。</div>
<table><tr><th>組別</th><th>n</th><th>中位事件報酬</th><th>勝率</th></tr>
<tr><th>線性加權</th>{fmt_grp(weighting['weighted_abs'])}</tr>
<tr><th>等權全買</th>{fmt_grp(weighting['equal_abs'])}</tr></table>
<div class="note">加權-等權差(事件層配對): {fmt_stat(weighting['diff_test'])}</div>"""
    else:
        weight_html = "<div class='note warn'>無法執行加權測試(樣本不足或無有效特徵)。</div>"

    coverage_rows = "".join(
        f"<tr><th style='text-align:left'>{label}</th><td>{s4[feat].notna().sum()}</td>"
        f"<td>{s4[feat].notna().sum() / n_all * 100:.0f}%</td></tr>"
        for feat, kind, label in FEATURES)

    prior_note = """
<div class="note">背景交叉參考: 2026-07-15曾有一版更輕量的探索(build_score4_member_select.py,
top5成員×yfinance調整價×次月15號出場≈20交易日持有,未bootstrap的快篩),當時發現「進場前20日動能
排名第1名 vs 其他」配對差中位僅+0.39pp、逐年正負不一(2022正/2023-2024負/2025轉正),MA20之上vs
之下的配對也與MA5版本方向相反——即該輕量版本已提示「價格動能排序」在題材內挑股上訊號不穩定。
本卷用baseline正式60日持有全宇宙panel重新嚴謹測試(含事件層bootstrap/置換檢定),見下方①的結論
是否與這個先驗一致。</div>"""

    dist = results.get("limitup_dist") or {}

    def dist_line(col, label):
        d = dist.get(col)
        if d is None:
            return f"{label}: 無有效樣本"
        return f"{label}: n={d['n']} 0次{d['p0']:.1f}% / 1次{d['p1']:.1f}% / ≥2次{d['p2plus']:.1f}%"

    limitup_note = f"""
<div class="note"><b>2026-08-03新增第⑦個角度(使用者追加):漲停次數——短期極端跳躍/軋空味,
與①價格相對強勢(mom20/mom60平滑trailing報酬)概念不同</b>,抓的是「短期內多次觸及漲停」這種
極端注意力訊號,不是平滑累積動能。沿用既有{n_all}筆特徵面板(v2 panel + 前6角度特徵不重算),
只新增這一欄。定義: 用<code>fm_daily_price</code>原始價格(非yfinance調整價cache,漲停判定需要
真實成交價,調整價的除權息平移會誤判)寬鬆門檻=收盤相對前一日收盤漲幅≥9.5%(留誤差空間給理論
漲停價10.00%的小數捨入),嚴格對照=寬鬆條件成立且當日high==low==close(一字鎖死型)。
計數窗口=進場日「之前」20/60個交易日(不含進場當天,窗口需至少15/45個有效交易日才計數)。</div>
<div class="note">漲停次數分布(決定分組切法的依據): {dist_line("limitup20", "20日窗寬鬆版")};
{dist_line("limitup60", "60日窗寬鬆版")}; {dist_line("limitup20_strict", "20日窗嚴格版(一字鎖死)")};
{dist_line("limitup60_strict", "60日窗嚴格版")}。0次比例偏高(20日窗約77%、60日窗約52%),不適合
硬湊tertile,主判讀改用「≥1次 vs 0次」二分;≥2次占比尚可(20日約8%、60日約25%),另做
dose-response版「≥2次 vs 0次」(1次視為中間組排除)當劑量梯度穩健性對照;一字鎖死型20日窗
過於稀疏(僅約1.6%),只在此描述性提及分布,不納入正式事件層檢定,60日窗嚴格版(約6%)則納入
當穩健對照。</div>"""

    vdist = results.get("vol_dist") or {}

    def vdist_line(col, label):
        d = vdist.get(col)
        if d is None:
            return f"{label}: 無有效樣本"
        return f"{label}: n={d['n']} 中位{d['median']:.2f} 均{d['mean']:.2f}"

    vol_note = f"""
<div class="note"><b>2026-08-03新增第⑧個角度(使用者追加):個股自身波動度/好壞波動分解——
⚠與build_vol_addvalue_report.py/build_vol_updown_explore.py測過的問題不同</b>: 那兩支姊妹卷問
「大盤/題材整體波動regime要不要疊加當開關」(結論=不加值,score4無用/好壞波動分解對動能型策略
判雜訊);本卷問的是「題材觸發後,題材內部各成員『自己』的波動水準,拿來橫向挑成員/加權有沒有用」
——是成員層級的橫向比較,不是市場層級的regime判斷,兩者結論互相獨立,不要混為一談。算法逐字複用
<code>build_vol_updown_explore.py::vol_updown()</code>,只是把輸入從大盤/題材指數換成個股自己的
收盤價序列: vol_std_w=該函式回傳的std_w(rolling w日日報酬標準差,ddof=1,與本專案vol10/vol60/ts/
vp10既有regime系統同一套算法)當波動度水準主口徑(選它是因為這是這批姊妹卷共同的既有基準指標,
不另外設計新量尺); vol_bshare_w=該函式回傳的bshare_w(壞波動占比%=負報酬日平方和/總平方和)逐字
沿用。兩者皆取pos-1(進場日前一交易日),20日/60日兩窗口比照①動能已測過的窗口。</div>
<div class="note">波動度描述性統計(中位數/均值,提供脈絡非判讀本身): {vdist_line("vol_std20", "20日std")};
{vdist_line("vol_std60", "60日std")}; {vdist_line("vol_bshare20", "bshare20")};
{vdist_line("vol_bshare60", "bshare60")}。std_w與bshare_w皆為連續變數,分組切法比照①②等連續特徵
採事件內前1/3(高)vs後1/3(低)。</div>"""

    html = f"""<!DOCTYPE html><html lang="zh-Hant"><head><meta charset="utf-8">
<title>題材內挑股/加權能否勝過等權全買</title><style>{css}</style></head><body>
<h1>題材觸發後「題材內挑股/加權」能否勝過等權全買?</h1>
<div class="note">baseline=題材月營收動能score=4(連3月MoM正+近3月YoY均值正),
題材全成員等權買、次月15號進場、持60交易日(build_theme_momentum_v2.py既有產出,重用不重算)。
本卷鎖定score=4子集({n_all}筆成員-事件,{n_ev_total}個題材-月事件),在成員層級測試多個特徵角度
能否挑出比等權全買更好的子集,或用連續加權取代硬篩選。所有特徵只用「進場當下已公開」的資訊
(revenue用shift(1)口徑同題材訊號本身;外資/TDCC取嚴格早於進場日的最近快照;漲停次數/波動度用
進場日之前、不含當天)。</div>
{prior_note}
{limitup_note}
{vol_note}

<h2>總覽:各特徵角度的判讀</h2>
<table><tr><th>特徵</th><th>事件數</th><th>判讀</th><th>核心數字</th></tr>{summary_rows}</table>
<div class="note">判讀分四類: <b style="color:{GREEN}">挑股有效</b>=top-bottom配對差顯著且方向正確,
且top組本身顯著贏過等權baseline; <b style="color:{YELLOW}">部分訊號</b>=僅top-bottom配對差顯著,
對baseline的增量不顯著(可能只是bottom組特別差,不代表挑top組能加分); <b style="color:{RED}">方向相反</b>;
<b style="color:{GRAY}">無法區辨於雜訊</b>=兩層檢定都不顯著。「絕對報酬層」問「這組本身賺不賺錢」,
「相對baseline層」問「比等權全買會不會更好」,兩層可能給出不同結論,分開陳述不要混為一談。</div>

<h2>特徵覆蓋率</h2>
<table><tr><th>特徵</th><th>非空筆數</th><th>覆蓋率</th></tr>{coverage_rows}</table>
<div class="note">覆蓋率不足100%的常見原因: ①外資位階需inst_flow累計240日暖機(2022-01起,
有效窗約2022-06+); ②TDCC需前4期快照且距cutoff不超過21天; ③個股營收YoY/12月新高需trailing
12-15個月的fm_month_rev資料,新掛牌或資料較短的個股會有缺值; ④價格動能需60個交易日以上的
cache歷史,2022年最早幾個月的事件可能不足。</div>

{detail_html}

<h2>特徵組合: 外資位階高 ∧ 佔題材營收比重上升(使用者指定範例)</h2>
{combo_html}

<h2>加權測試(bonus): 線性排序加權 vs 等權硬篩選</h2>
{weight_html}

<h2>方法論與限制</h2>
<div class="note">
① 分組方法: 事件內(題材-月)依特徵排序取前1/3(top)/後1/3(bottom)(連續特徵,n&lt;3的事件跳過);
二元旗標改用「有/無此屬性」,雙邊都要有成員才計入,事件數天生比連續特徵少。<br>
② 顯著性: 事件數(cluster)&gt;=15用事件層bootstrap(B=2000,對每事件一個彙總值直接resample,
不需再依日期分群,因為事件本身已經是本卷的獨立單位),95%CI排0視為顯著; 事件數&lt;15改用
sign-flip置換檢定(對每事件配對差的正負號隨機翻轉5000次,任意n有效,p僅供方向線索參考,
不宣稱嚴格統計顯著)。這個「事件層配對」bootstrap設計比build_theme_momentum_validate.py既有的
「題材-月cluster bootstrap」(整群重抽樣後pool成員值算中位數)更貼近「選股是否優於等權baseline」
這個問題本身(直接算配對差,天然控制掉題材當月的共同成分),兩者是互補而非互相取代的設計。<br>
③ 樣本量誠實提醒: score=4全樣本僅{n_ev_total}個題材-月事件({n_all}筆成員-事件),再依成員特徵
細分組別後,能同時滿足tertile切法門檻(&gt;=3個有效成員)的事件通常只剩70~100個左右,雙重篩選
(特徵組合)或旗標類特徵的有效事件數更少;凡事件數&lt;15律以置換檢定的p值僅供方向參考,
不等同於「已驗證顯著」。全樣本已知regime依賴(2025年顯著/2024年偏負),本卷未依regime再切分
(切下去樣本會更薄),讀者需自行考量這層限制。<br>
④ 特徵計算依賴的既有算法出處: ③外資20日位階=封存/研究腳本歸檔/tmp_chip_bt.py canonical S4
(rolling(20,min10).sum→rolling(240,min120).rank(pct=True)*100); ⑤TDCC d4w_1000規約=
build_resonance_tdcc.py(cutoff=進場日-3日曆日,距cutoff&gt;21天視為過期); ⑥成交值熱度百分位
的rolling(240,min120).rank(pct=True)*100算法比照同一套慣例(套用在Close×Volume近似成交值上,
非直接引用某一支既有腳本,是同一手法的新套用)。<br>
⑤ ①價格動能與2026-07-15較輕量的探索(build_score4_member_select.py,top5成員/yfinance調整價/
≈20交易日持有,未bootstrap)背景不同(本卷=v2全FinMind宇宙/60交易日持有/事件層bootstrap),
若結論方向不一致,以本卷(方法更嚴謹、宇宙更完整)為準,但兩者若方向一致則是額外的穩健性佐證。<br>
⑥ 個股層revenue YoY/12月新高/佔題材營收比重皆用period_last=進場月往前一個月(shift(1)口徑),
與題材本身score/trend_yoy3使用同一組已公布月份,不看到任何未公布的營收數字。<br>
⑦ (2026-08-03新增)漲停次數用<code>fm_daily_price</code>原始價格重新查詢計算(不是①動能用的
yfinance調整價cache),因為漲停判定必須用真實成交價,除權息調整價的平移會讓「收盤漲幅≥9.5%」
這個門檻誤判;分組切法(二分/dose-response)依實際次數分布動態決定而非硬湊tertile,理由與分布
數字見上方新增區塊。<br>
⑧ (2026-08-03新增)個股自身波動度/好壞波動分解與市場regime(vol10/vol60/ts/vp10、bshare20大盤版)
是兩個不同層級的問題——本卷只測「題材內部成員自己的波動水準橫向比較」,不重測市場regime要不要當
開關(那題另外兩支姊妹卷已有結論);算法(std_w/bshare_w)逐字複用<code>build_vol_updown_explore.py
::vol_updown()</code>套用到個股收盤價,不重新設計。<br>
⑨ 多重比較提醒已改為全報告動態掃描(見上方區塊),新增角度時這段文字與檢定計數會自動更新,
不需要每次手動改寫特定家族的文字。
</div>
</body></html>"""
    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)


if __name__ == "__main__":
    main()
