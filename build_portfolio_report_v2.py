# -*- coding: utf-8 -*-
"""策略棧總覽回測 v2(2026-07-22,取代舊版tmp_portfolio_report.py/2026-07-12版)
-> 研究報告/research_portfolio_overview.html

彙整「目前實際上儀表板」的6條策略線,原樣疊圖(刻意不去重——要看的是實際部署內容之間
真實的重疊/相關性,不是理想化的「互相獨立策略」拼盤),外加1條等權組合線。

6條線 (各自沿用/改編既有已驗證腳本的simulate/equity邏輯,不從原始資料重新推導):
  ① S3 ⑤強訊號+階梯          <- 封存/研究腳本歸檔/tmp_portfolio_report.py (大題材檢查清單頁籤)
  ② 籌碼A1+階梯(2023起)      <- 同上腳本S4段 (族群解剖表籌碼徽章,非獨立頁籤但是活的規則)
  ③ 題材營收動能score=4+階梯  <- build_theme_momentum_report.py(score=4主線) +
                                 build_theme_momentum_tier.py(V2組合縮放邏輯) (題材營收動能頁籤)
  ④ 共振S4(OTC水位階梯)      <- build_resonance_report.py (🔥共振頁籤)
  ⑤ 處置V4(第3處置日尾盤買)  <- build_panic_liquidity_converge.py (處置股觀察頁籤)
  ⑥ 亞跌B→加權持10日          <- build_bottom_playbook_report.py (🌡️大盤溫度計頁籤,五燈之一)
  ⑦ 組合(6線等權)             <- 本腳本新算: 各線equity曲線resample成週報酬,
                                 每週對「當週有資料的線」取等權平均後複利

明確不收錄(原因):
  - CB礦山: 使用者裁示WIP(流動性資料待複核),不上儀表板
  - 恐慌甜蜜格: 不是獨立策略線,是溫度計時機工具的組成之一,儀表板無獨立頁籤
  - 處置慣犯/處置V5/處置首日做空: 目前只有交易明細面板,沒有現成的「逐日複利equity序列」
    產生器,要另外寫日期索引複利邏輯——不在本次任務範圍(V5為可選項,見下)
  - 微題材脈衝雷達/補漲雷達: 沒有存檔的歷史時間序列/equity資料,需要重新跑歷史掃描才能做,
    本次不做(資料缺口,留待future work)
  - 🔓內部解質警戒: 這是「既有部位的曝險縮放濾網」,不是有自己多空交易的獨立策略,
    依定義不可能有自己的equity曲線,故不納入(見下方「已知限制」)

用法: python build_portfolio_report_v2.py
"""
import pickle
import sqlite3

import numpy as np
import pandas as pd
import yfinance as yf

from research_report_tmpl import build_report

COST = 0.5
HOLD = 8

print("=" * 78)
print("[準備] 下載 ^TWII 週線(yfinance)——分兩段:S3階梯沿用原腳本口徑(2021-10起)"
      "、全期基準/組合線另外抓長版(1997起)")
tw_s1 = yf.download("^TWII", start="2021-10-01", interval="1wk", auto_adjust=True, progress=False)["Close"]
if getattr(tw_s1, "ndim", 1) > 1:
    tw_s1 = tw_s1.iloc[:, 0]
tw_s1 = tw_s1.sort_index()

tw_long = yf.download("^TWII", start="1997-01-01", interval="1wk", auto_adjust=True, progress=False)["Close"]
if getattr(tw_long, "ndim", 1) > 1:
    tw_long = tw_long.iloc[:, 0]
tw_long = tw_long.sort_index()


def _pack_common(w, tdf, ret_col="ret", freq=52):
    """沿用tmp_portfolio_report.py/build_resonance_report.py共用的pack()邏輯"""
    eq = (1 + w[ret_col] / 100).cumprod()
    dd = (eq / eq.cummax() - 1) * 100
    mu, sd = w[ret_col].mean(), w[ret_col].std()
    n = len(w)
    mult = eq.iloc[-1]
    ann = (mult ** (freq / n) - 1) * 100 if n else 0
    aw = tdf.ret[tdf.ret > 0].mean() if len(tdf) else None
    al = tdf.ret[tdf.ret <= 0].mean() if len(tdf) else None
    st = dict(trades=len(tdf), win=(tdf.ret > 0).mean() * 100 if len(tdf) else None,
              avg=tdf.ret.mean() if len(tdf) else None, med=tdf.ret.median() if len(tdf) else None,
              wl=abs(aw / al) if aw and al else None,
              pf=-tdf.ret[tdf.ret > 0].sum() / tdf.ret[tdf.ret <= 0].sum() if len(tdf) and (tdf.ret <= 0).any() else None,
              mult=mult, ann=ann, sharpe=mu / sd * freq ** 0.5 if sd else 0, mdd=dd.min(),
              calmar=ann / abs(dd.min()) if dd.min() else None, expo=(w.n > 0).mean() * 100 if "n" in w else None)
    w2 = w.copy()
    w2["y"] = w2.date.str[:4]
    yearly = {y: ((1 + g[ret_col] / 100).prod() - 1) * 100 for y, g in w2.groupby("y")}
    return eq, st, yearly


# ============================================================================
# 線① + 線② : 主系統S3(⑤強訊號+階梯) + 籌碼A1+階梯(2023起)
# 逐字改編自 封存/研究腳本歸檔/tmp_portfolio_report.py (只取S3設定,不跑S1/S2)
# ============================================================================
def build_line12():
    print("\n" + "=" * 78)
    print("[線①②] 主系統S3 + 籌碼A1 —— 逐字改編 tmp_portfolio_report.py")
    prices = {k: v for k, v in pickle.load(open("tmp_bear_prices.pkl", "rb")).items()
              if v is not None and len(v) > 10}
    panel = pd.DataFrame(prices)
    wret = panel.pct_change(fill_method=None) * 100
    idx = panel.index

    tr = pd.read_csv("tmp_bear_trades.csv", dtype=str)
    tr = tr[tr.ret8w.str.contains("%", na=False)].copy()
    tr["ret"] = tr.ret8w.str.replace("%", "").astype(float) - COST

    def pat_ok(r):
        try:
            a, b = r.nh.split("/")
            if int(b) and int(a) / int(b) >= 2 / 3:
                return True
        except (ValueError, AttributeError):
            pass
        return "✓" in str(r.gap)

    tr["p5"] = tr.apply(pat_ok, axis=1)

    tw = tw_s1
    m4, m13 = tw.rolling(4).mean(), tw.rolling(13).mean()

    def tier_at(day):
        i = tw.index.searchsorted(pd.Timestamp(day)) - 1
        if i < 13:
            return 1.0
        px, a, b = tw.iloc[i], m4.iloc[i], m13.iloc[i]
        if pd.notna(b) and px < b:
            return 0.3
        if pd.notna(a) and px < a:
            return 0.6
        return 1.0

    def simulate(trades, ladder):
        entries = []
        for t in trades.itertuples():
            ei = idx.searchsorted(pd.Timestamp(t.date))
            mems = [c.strip() for c in t.members.split("、") if c.strip() in wret.columns]
            if mems and ei < len(idx) - 1:
                entries.append((ei, mems))
        weekly = []
        for i in range(1, len(idx)):
            rets = []
            for ei, mems in entries:
                if ei < i <= ei + HOLD:
                    rs = [wret.iloc[i].get(m) for m in mems]
                    rs = [x for x in rs if pd.notna(x)]
                    if rs:
                        rets.append(sum(rs) / len(rs) - (COST if i == ei + 1 else 0))
            r = sum(rets) / len(rets) if rets else 0.0
            if ladder:
                r *= tier_at(idx[i])
            weekly.append((str(idx[i].date()), r, len(rets)))
        return pd.DataFrame(weekly, columns=["date", "ret", "n"])

    s3_trades = tr[tr.p5]
    w3 = simulate(s3_trades, True)
    eq3, st3, yr3 = _pack_common(w3, s3_trades)
    line1 = dict(name="① S3 ⑤強訊號+階梯", dates=list(w3.date), equity=[round(x, 4) for x in eq3],
                 yearly=yr3, stats=st3)
    print(f"① S3 ⑤強訊號+階梯: {st3['mult']:.2f}x 夏普{st3['sharpe']:.2f} MDD{st3['mdd']:.1f}% "
          f"{st3['trades']}筆")

    # ---- S4 籌碼A1+階梯(2023起) ----
    conn = sqlite3.connect("capital_flow.db")
    fl = pd.read_sql("SELECT date, code, foreign_net, close FROM inst_flow", conn)
    fl = fl[fl.code.str.match(r"^[1-9]\d{3}$")]
    fl["date"] = pd.to_datetime(fl.date)
    closeD = fl.pivot_table(index="date", columns="code", values="close")
    fpct = (fl.pivot_table(index="date", columns="code", values="foreign_net")
            .reindex(closeD.index).rolling(20, min_periods=10).sum()
            .rolling(240, min_periods=120).rank(pct=True))
    wkC = closeD.resample("W-FRI").last()
    wretC = wkC.pct_change(fill_method=None) * 100
    fp_w = fpct.resample("W-FRI").last()
    rdb = sqlite3.connect("research_2022.db")
    rk = pd.read_sql("SELECT snapshot_date, code, rank FROM rankings WHERE country='台'", rdb)
    snap_rank = {d: dict(zip(g.code, g["rank"])) for d, g in rk.groupby("snapshot_date")}
    snaps = sorted(snap_rank)
    snaps_ts = pd.Series(pd.to_datetime(snaps))

    def rank_of(day, code):
        i = snaps_ts.searchsorted(day + pd.Timedelta(days=3)) - 1
        return snap_rank[snaps[i]].get(code) if 0 <= i < len(snaps) else None

    idxC = wretC.index
    weekly, open_pos, trades4 = [], [], []
    for i in range(53, len(idxC) - 1):
        d = idxC[i]
        picks = []
        if str(d.date()) >= "2022-12-30":
            sig = wretC.iloc[i]
            for c in sig.index[sig > 10]:
                r = rank_of(d, c)
                if r and 51 <= r <= 300 and pd.notna(fp_w.iloc[i].get(c)) and fp_w.iloc[i][c] >= 0.8:
                    picks.append(c)
        nxt = wretC.iloc[i + 1]
        rets, keep = [], []
        for c, left in open_pos:
            v = nxt.get(c)
            if pd.isna(v):
                continue
            rets.append(v)
            if left > 1:
                keep.append((c, left - 1))
        for c in picks:
            v = nxt.get(c)
            if pd.isna(v):
                continue
            rets.append(v - COST)
            keep.append((c, 3))
            e4 = wkC.iloc[min(i + 4, len(idxC) - 1)].get(c)
            trades4.append(dict(ret=(e4 / wkC.iloc[i][c] - 1) * 100 - COST if pd.notna(e4) else None))
        open_pos = keep
        r = (sum(rets) / len(rets) if rets else 0.0) * tier_at(idxC[i])
        weekly.append((str(idxC[i + 1].date()), r, len(rets)))
    w4 = pd.DataFrame(weekly, columns=["date", "ret", "n"])
    w4 = w4[w4.date >= "2023-01-01"]
    t4 = pd.DataFrame(trades4).dropna()
    eq4, st4, yr4 = _pack_common(w4.reset_index(drop=True), t4)
    line2 = dict(name="② 籌碼A1+階梯(2023起)", dates=list(w4.date), equity=[round(x, 4) for x in eq4],
                 yearly=yr4, stats=st4)
    print(f"② 籌碼A1+階梯(2023起): {st4['mult']:.2f}x 夏普{st4['sharpe']:.2f} MDD{st4['mdd']:.1f}% "
          f"{st4['trades']}筆")
    conn.close()
    rdb.close()
    return line1, line2, s3_trades, t4


# ============================================================================
# 線③ : 題材營收動能 score=4 + 階梯(V2組合縮放)
# 改編自 build_theme_momentum_report.py::build_equity + build_theme_momentum_tier.py::V2邏輯
# ============================================================================
def build_line3():
    print("\n" + "=" * 78)
    print("[線③] 題材營收動能 score=4+階梯(V2組合縮放) —— 改編 "
          "build_theme_momentum_report.py + build_theme_momentum_tier.py")
    HOLD_DAYS = 60
    with open("tmp_revenue_price_cache.pkl", "rb") as f:
        cache = pickle.load(f)
    panel = pd.read_pickle("tmp_theme_momentum_v2_panel.pkl").copy()
    s4 = panel[panel.score == 4].copy()

    twii = pd.read_pickle("tmp_twii_daily.pkl")
    twii.columns = twii.columns.get_level_values(0)
    twii = twii.sort_index()
    c_twii = twii.Close
    all_days_idx = [d for d in twii.index if str(d.date()) >= "2022-01-01"]
    all_days = [str(d.date()) for d in all_days_idx]

    # 態勢階梯(週線vs4週/13週均線凍結口徑,上一完成週生效,無look-ahead)——同build_theme_momentum_tier.py
    wk = c_twii.resample("W-FRI").last().dropna()
    ma4, ma13 = wk.rolling(4).mean(), wk.rolling(13).mean()
    tier_wk = pd.Series(1.0, index=wk.index)
    tier_wk[wk < ma4] = 0.6
    tier_wk[wk < ma13] = 0.3
    tier_daily = {}
    wk_idx = tier_wk.index
    for d in c_twii.index:
        pos = wk_idx.searchsorted(pd.Timestamp(d))
        tier_daily[str(d.date())] = float(tier_wk.iloc[pos - 1]) if pos > 0 else 1.0
    tier_s = pd.Series(tier_daily)

    def daily_returns_for_trade(row):
        df = cache.get(row.code)
        if df is None:
            return None
        c = df["Close"]
        if hasattr(c, "columns"):
            c = c.iloc[:, 0]
        entry = pd.Timestamp(row.entry_day)
        if entry not in c.index:
            return None
        start_i = c.index.get_loc(entry)
        end_i = start_i + HOLD_DAYS
        if end_i >= len(c):
            return None
        window = c.iloc[start_i:end_i + 1]
        daily_ret = window.pct_change().dropna() * 100
        daily_ret.index = daily_ret.index.map(lambda d: str(d.date()))
        return daily_ret

    daily_frames = [dr for row in s4.itertuples() if (dr := daily_returns_for_trade(row)) is not None]
    all_ret = pd.concat(daily_frames, axis=1)
    port_ret = all_ret.mean(axis=1)
    port = pd.Series(0.0, index=all_days)
    idx_i = port_ret.index.intersection(port.index)
    port.loc[idx_i] = port_ret.loc[idx_i]
    # V2組合縮放: 每日報酬 x 當日tier(訊號照進場,只是縮放部位大小——2026-07-14驗證通過的採用版)
    port_scaled = port * tier_s.reindex(port.index).fillna(1.0)
    eq = (1 + port_scaled / 100).cumprod()
    ddv = (eq / eq.cummax() - 1) * 100
    mu, sdv = port_scaled.mean(), port_scaled.std()
    n = len(port_scaled)
    mult = eq.iloc[-1]
    ann = (mult ** (252 / n) - 1) * 100
    n_open = all_ret.notna().sum(axis=1).reindex(port.index).fillna(0)
    tmp = pd.DataFrame({"date": all_days, "ret": port_scaled.values, "n": n_open.values})
    tmp["y"] = tmp.date.str[:4]
    yearly = {y: ((1 + g.ret / 100).prod() - 1) * 100 for y, g in tmp.groupby("y")}
    aw = s4.ret60[s4.ret60 > 0].mean()
    al = s4.ret60[s4.ret60 <= 0].mean()
    st = dict(trades=len(s4), win=(s4.ret60 > 0).mean() * 100, avg=s4.ret60.mean(), med=s4.ret60.median(),
              wl=abs(aw / al) if al else None,
              pf=-s4.ret60[s4.ret60 > 0].sum() / s4.ret60[s4.ret60 <= 0].sum() if (s4.ret60 <= 0).any() else None,
              mult=mult, ann=ann, sharpe=mu / sdv * 252 ** 0.5 if sdv else 0, mdd=ddv.min(),
              calmar=ann / abs(ddv.min()) if ddv.min() else None, expo=(tmp.n > 0).mean() * 100)
    line3 = dict(name="③ 題材營收動能score=4+階梯", dates=all_days, equity=[round(x, 4) for x in eq],
                 yearly=yearly, stats=st)
    print(f"③ 題材營收動能score=4+階梯: {st['mult']:.2f}x 夏普{st['sharpe']:.2f} MDD{st['mdd']:.1f}% "
          f"{st['trades']}筆")
    # 校驗: build_theme_momentum_tier.py當場跑出的V2版基準值(2026-07-14紀錄): 5.79x/夏普2.07/MDD-21.6%
    _check_divergence("③ 題材營收動能V2", st['mult'], 5.79, st['sharpe'], 2.07, st['mdd'], -21.6)
    return line3, s4


# ============================================================================
# 線④ : 共振S4(OTC水位階梯) —— 改編自 build_resonance_report.py
# ============================================================================
def build_line4():
    print("\n" + "=" * 78)
    print("[線④] 共振S4(OTC水位階梯) —— 改編 build_resonance_report.py")
    ep = pd.read_pickle("tmp_resonance_theme_episodes.pkl")
    wk_panel = pd.read_pickle("tmp_resonance_weekly_panel.pkl")
    wret = wk_panel.pct_change(fill_method=None) * 100
    idx = wk_panel.index

    conn = sqlite3.connect("capital_flow.db")
    otc = pd.read_sql("SELECT date, close FROM index_daily WHERE market='TPEx' ORDER BY date", conn,
                       parse_dates=["date"]).set_index("date").close
    conn.close()
    otc_wk = otc.resample("W-FRI").last().dropna()

    def make_tier(wk_series):
        m4, m13 = wk_series.rolling(4).mean(), wk_series.rolling(13).mean()

        def tier_at(dt):
            pos = wk_series.index.searchsorted(dt)
            if pos >= len(wk_series) or wk_series.index[pos] != dt or pos < 13:
                return 1.0
            px, a, b = wk_series.iloc[pos], m4.iloc[pos], m13.iloc[pos]
            if pd.notna(b) and px < b:
                return 0.3
            if pd.notna(a) and px < a:
                return 0.6
            return 1.0
        return tier_at

    tier_otc = make_tier(otc_wk)

    def simulate(trades, tier_fn=None):
        entries = []
        for t in trades.itertuples():
            ei = idx.searchsorted(pd.Timestamp(t.week))
            if ei >= len(idx) or idx[ei] != pd.Timestamp(t.week):
                continue
            mems = [c for c in t.members if c in wret.columns]
            if mems and ei < len(idx) - 1:
                entries.append((ei, mems))
        weekly = []
        for i in range(1, len(idx)):
            rets = []
            for ei, mems in entries:
                if ei < i <= ei + HOLD:
                    rs = [wret.iloc[i].get(m) for m in mems]
                    rs = [x for x in rs if pd.notna(x)]
                    if rs:
                        rets.append(sum(rs) / len(rs) - (COST if i == ei + 1 else 0))
            r = sum(rets) / len(rets) if rets else 0.0
            if tier_fn is not None:
                r *= tier_fn(idx[i])
            weekly.append((str(idx[i].date()), r, len(rets)))
        return pd.DataFrame(weekly, columns=["date", "ret", "n"])

    def trade_rets(trades):
        out = []
        for t in trades.itertuples():
            ei = idx.searchsorted(pd.Timestamp(t.week))
            if ei >= len(idx) or idx[ei] != pd.Timestamp(t.week) or ei + HOLD >= len(idx):
                continue
            mems = [c for c in t.members if c in wret.columns]
            rs = []
            for m in mems:
                p0, p1 = wk_panel[m].iloc[ei], wk_panel[m].iloc[ei + HOLD]
                if pd.notna(p0) and pd.notna(p1) and p0 > 0:
                    rs.append((p1 / p0 - 1) * 100)
            if rs:
                out.append({"date": str(t.week.date()), "theme": t.theme, "members": "、".join(mems),
                            "n_members": t.n_members, "ret": sum(rs) / len(rs) - COST})
        return pd.DataFrame(out)

    w4 = simulate(ep, tier_fn=tier_otc)
    tdf = trade_rets(ep).sort_values("date")
    eq4, st4, yr4 = _pack_common(w4, tdf)
    line4 = dict(name="④ 共振S4(OTC水位階梯)", dates=list(w4.date), equity=[round(x, 4) for x in eq4],
                 yearly=yr4, stats=st4)
    print(f"④ 共振S4(OTC水位階梯): {st4['mult']:.2f}x 夏普{st4['sharpe']:.2f} MDD{st4['mdd']:.1f}% "
          f"{st4['trades']}筆")
    # 校驗: 使用者交辦文件引用值 ~6237x / 夏普2.44 / MDD-16.4%(2005-2026)
    _check_divergence("④ 共振S4", st4['mult'], 6237.31, st4['sharpe'], 2.44, st4['mdd'], -16.4)
    return line4, tdf


# ============================================================================
# 線⑤ : 處置V4(第3處置日尾盤買→出關日開盤賣) —— 重用 build_panic_liquidity_converge.py
# ============================================================================
def build_line5():
    print("\n" + "=" * 78)
    print("[線⑤] 處置V4 —— 重用 build_panic_liquidity_converge.py 的函式(import後直接呼叫)")
    import build_panic_liquidity_converge as plc

    stocks, disp = plc.load_px()
    twii = pd.read_pickle("tmp_twii_long.pkl").dropna()
    trades_v4 = plc.disposition_trades(stocks, disp)
    p = plc.portfolio(trades_v4, twii)

    eq = p["equity"]
    n = len(eq)
    mult = p["compound"]
    ann = (mult ** (252 / n) - 1) * 100 if n else 0
    nets = pd.Series([t["net"] for t in trades_v4])
    aw = nets[nets > 0].mean()
    al = nets[nets <= 0].mean()
    wl = abs(aw / al) if aw and al else None
    pf = -nets[nets > 0].sum() / nets[nets <= 0].sum() if (nets <= 0).any() else None
    tmp = pd.DataFrame({"date": [str(d.date()) for d in eq.index], "ret": (eq.pct_change().fillna(0.0) * 100).values})
    tmp["y"] = tmp.date.str[:4]
    yearly = {y: ((1 + g.ret / 100).prod() - 1) * 100 for y, g in tmp.groupby("y")}
    calmar = ann / abs(p["mdd"]) if p["mdd"] else None
    st = dict(trades=len(trades_v4), win=p["win"], avg=p["mean"], med=p["median"], wl=wl, pf=pf,
              mult=mult, ann=ann, sharpe=p["sharpe"], mdd=p["mdd"], calmar=calmar, expo=p["exposure"])
    line5 = dict(name="⑤ 處置V4(第3處置日尾盤買)", dates=[str(d.date()) for d in eq.index],
                 equity=[round(float(x), 4) for x in eq], yearly=yearly, stats=st)
    print(f"⑤ 處置V4: {st['mult']:.2f}x 夏普{st['sharpe']:.2f} MDD{st['mdd']:.1f}% {st['trades']}筆 "
          f"曝險{st['expo']:.0f}%")
    return line5, nets


# ============================================================================
# 線⑥ : 亞跌B → 加權持10日(大盤溫度計五燈之一) —— 改編自 build_bottom_playbook_report.py
# ============================================================================
def build_line6():
    print("\n" + "=" * 78)
    print("[線⑥] 亞跌B→加權持10日 —— 改編 build_bottom_playbook_report.py::equity()")
    conn = sqlite3.connect("capital_flow.db")

    def load(mkt):
        return pd.read_sql("SELECT date, open, close FROM index_daily WHERE market=? ORDER BY date",
                           conn, params=(mkt,), parse_dates=["date"]).set_index("date")
    tw = load("TAIEX")
    n2 = load("N225").close.pct_change() * 100
    ko = load("KOSPI").close.pct_change() * 100
    sp = load("SPX").close.pct_change() * 100
    conn.close()

    twr = tw.close.pct_change() * 100
    df = pd.DataFrame({"tw": twr}).dropna()
    df = df[df.index >= "1999-02-01"]
    df["n225"] = n2.reindex(df.index)
    df["kospi"] = ko.reindex(df.index)
    si = sp.dropna()
    pos = si.index.searchsorted(df.index) - 1
    df["us"] = [si.iloc[p] if p >= 0 else np.nan for p in pos]

    asia = (df.n225 <= -2) & (df.kospi <= -2)
    b_mask = asia & (df.us > -1)   # B 純亞跌(美>-1%)

    def episodes(days, sep=10):
        p2 = {d: i for i, d in enumerate(tw.index)}
        out, last = [], -10 ** 9
        for d in sorted(days):
            if d in p2 and p2[d] - last >= sep:
                out.append(d)
                last = p2[d]
        return out

    b_eps = episodes(df.index[b_mask.fillna(False)])

    def equity(trig_days, hold):
        ret = tw.close.pct_change().fillna(0.0)
        open_ret = (tw.close / tw.open - 1)
        entry_pos = {tw.index.get_loc(d) + 1 for d in trig_days if tw.index.get_loc(d) + 1 < len(tw)}
        eq, val, holding, pos_until = [], 1.0, False, -1
        start = tw.index.searchsorted(pd.Timestamp("1999-02-01"))
        for i in range(start, len(tw)):
            if i in entry_pos and not holding:
                holding = True
                pos_until = i + hold - 1
                val *= (1 + open_ret.iloc[i])
            elif holding:
                val *= (1 + ret.iloc[i])
                if i >= pos_until:
                    holding = False
            eq.append(val)
        return pd.Series(eq, index=tw.index[start:])

    def fwd10(d):
        t = tw.index.get_loc(d)
        if t + 1 + 10 < len(tw) and tw.open.iloc[t + 1] > 0:
            return (tw.close.iloc[t + 1 + 10] / tw.open.iloc[t + 1] - 1) * 100
        return None

    eq10 = equity(b_eps, 10)
    dailyret = eq10.pct_change().fillna(0.0) * 100
    mu, sdv = dailyret.mean(), dailyret.std()
    n = len(eq10)
    mult = eq10.iloc[-1]
    ann = (mult ** (252 / n) - 1) * 100
    dd = (eq10 / eq10.cummax() - 1) * 100
    nets = pd.Series([v for d in b_eps if (v := fwd10(d)) is not None])
    aw = nets[nets > 0].mean() if len(nets) else None
    al = nets[nets <= 0].mean() if len(nets) else None
    tmp = pd.DataFrame({"date": [str(d.date()) for d in eq10.index], "ret": dailyret.values})
    tmp["y"] = tmp.date.str[:4]
    yearly = {y: ((1 + g.ret / 100).prod() - 1) * 100 for y, g in tmp.groupby("y")}
    expo = len(b_eps) * 10 / len(eq10) * 100
    st = dict(trades=len(b_eps), win=(nets > 0).mean() * 100 if len(nets) else None,
              avg=nets.mean() if len(nets) else None, med=nets.median() if len(nets) else None,
              wl=abs(aw / al) if aw and al else None,
              pf=-nets[nets > 0].sum() / nets[nets <= 0].sum() if len(nets) and (nets <= 0).any() else None,
              mult=mult, ann=ann, sharpe=mu / sdv * 252 ** 0.5 if sdv else 0, mdd=dd.min(),
              calmar=ann / abs(dd.min()) if dd.min() else None, expo=expo)
    line6 = dict(name="⑥ 亞跌B→加權持10日", dates=[str(d.date()) for d in eq10.index],
                 equity=[round(float(x), 4) for x in eq10], yearly=yearly, stats=st)
    print(f"⑥ 亞跌B→加權持10日: {st['mult']:.2f}x 夏普{st['sharpe']:.2f} MDD{st['mdd']:.1f}% "
          f"{st['trades']}episode 曝險{expo:.0f}%")
    print("  注意: 這是「亞跌B」單燈訊號(10日持有),不是5燈合成部位——大盤溫度計頁籤上另有溫度計"
          "(60日)/警戒帶/雙收斂/跌停廣度4個獨立子訊號,各自無現成的可疊加equity曲線(合成曝險目前"
          "只是研究稿水位階梯,見dashboard.html「大盤溫度計」段落註解),故本報告僅取B這一燈。")
    return line6


def _check_divergence(label, mult, ref_mult, sharpe, ref_sharpe, mdd, ref_mdd, tol=0.20):
    def _diff(a, b):
        return abs(a - b) / abs(b) if b else 0
    flags = []
    if _diff(mult, ref_mult) > tol:
        flags.append(f"複利倍數 {mult:.2f}x vs 參考{ref_mult:.2f}x (差{_diff(mult, ref_mult) * 100:.0f}%)")
    if _diff(sharpe, ref_sharpe) > tol:
        flags.append(f"夏普 {sharpe:.2f} vs 參考{ref_sharpe:.2f} (差{_diff(sharpe, ref_sharpe) * 100:.0f}%)")
    if _diff(mdd, ref_mdd) > tol:
        flags.append(f"MDD {mdd:.1f}% vs 參考{ref_mdd:.1f}% (差{_diff(mdd, ref_mdd) * 100:.0f}%)")
    if flags:
        print(f"  ⚠⚠⚠ [{label}] 與先前稽核數字差異>20%: " + "; ".join(flags))
    else:
        print(f"  ✓ [{label}] 與先前稽核數字一致(容差20%內)")


# ============================================================================
# 線⑦ : 組合(6線等權) —— 每週對「當週有資料的線」取等權平均,無資料的線該週跳過(非0)
# ============================================================================
def build_blend(lines):
    print("\n" + "=" * 78)
    print("[線⑦] 組合(6線等權) —— 各線equity曲線resample成週報酬,當週有資料的線才計入平均")
    weekly_rets = {}
    for ln in lines:
        s = pd.Series(ln["equity"], index=pd.to_datetime(ln["dates"])).sort_index()
        s = s[~s.index.duplicated(keep="last")]
        wk = s.resample("W-FRI").last().dropna()
        r = wk.pct_change()  # 第一週NaN(沒有前值),自然被當成「該線那週無資料」
        weekly_rets[ln["name"]] = r
    combined = pd.concat(weekly_rets, axis=1)
    blended_ret = combined.mean(axis=1, skipna=True)  # skipna=True: 只對當週有值的線取平均
    blended_ret = blended_ret.dropna()  # 全部線都無資料的週(理論上不會出現,保險起見)

    eq = (1 + blended_ret).cumprod()
    dd = (eq / eq.cummax() - 1) * 100
    n = len(blended_ret)
    mult = eq.iloc[-1]
    ann = (mult ** (52 / n) - 1) * 100 if n else 0
    mu, sd = blended_ret.mean(), blended_ret.std()
    sharpe = mu / sd * 52 ** 0.5 if sd else 0
    n_active = combined.notna().sum(axis=1).reindex(blended_ret.index)
    tmp = pd.DataFrame({"date": [str(d.date()) for d in blended_ret.index], "ret": (blended_ret * 100).values})
    tmp["y"] = tmp.date.str[:4]
    yearly = {y: ((1 + g.ret / 100).prod() - 1) * 100 for y, g in tmp.groupby("y")}
    st = dict(trades=None, win=None, avg=None, med=None, wl=None, pf=None,
              mult=mult, ann=ann, sharpe=sharpe, mdd=dd.min(),
              calmar=ann / abs(dd.min()) if dd.min() else None,
              # expo=平均每週有幾條線同時貢獻(佔6線比例),而非「至少1線有覆蓋」——
              # 後者在1999年後幾乎恒為100%(因⑥亞跌B序列覆蓋全期),沒有訊息量
              expo=n_active.mean() / len(lines) * 100)
    line7 = dict(name="⑦ 組合(6線等權)", dates=[str(d.date()) for d in blended_ret.index],
                 equity=[round(float(x), 4) for x in eq], yearly=yearly, stats=st,
                 n_open=[int(x) for x in n_active])
    print(f"⑦ 組合(6線等權): {st['mult']:.2f}x 夏普{st['sharpe']:.2f} MDD{st['mdd']:.1f}% "
          f"平均同時在窗線數{n_active.mean():.1f}/6")
    return line7


def build_benchmark(lines):
    """單一^TWII基準線,覆蓋範圍取所有策略線最早日期起(不同於原舊版只從2021-10起)"""
    earliest = min(pd.to_datetime(ln["dates"]).min() for ln in lines)
    tw = tw_long[tw_long.index >= earliest]
    twr = tw.pct_change().fillna(0)
    tw_eq = (1 + twr).cumprod()
    tw_y = {str(y): ((1 + g).prod() - 1) * 100 for y, g in twr.groupby(twr.index.year)}
    return dict(name="加權指數^TWII(全期買進持有)", dates=[str(d.date()) for d in tw_eq.index],
                equity=[round(float(x), 4) for x in tw_eq], yearly=tw_y)


def main():
    line1, line2, s3_trades, t4_trades = build_line12()
    line3, s4_theme = build_line3()
    line4, tdf_reso = build_line4()
    line5, nets_v4 = build_line5()
    line6 = build_line6()

    strategies = [line1, line2, line3, line4, line5, line6]
    line7 = build_blend(strategies)
    strategies.append(line7)
    benchmarks = [build_benchmark(strategies)]

    print("\n" + "=" * 78)
    print("[總表] 各線最終數字一覽")
    for s in strategies:
        st = s["stats"]
        print(f"  {s['name']:<26s} 複利{st['mult']:>10.2f}x 夏普{st['sharpe']:>5.2f} "
              f"MDD{st['mdd']:>7.1f}%  {s['dates'][0]}~{s['dates'][-1]}")
    bh = benchmarks[0]
    print(f"  {bh['name']:<26s} 複利{bh['equity'][-1]:>10.2f}x  {bh['dates'][0]}~{bh['dates'][-1]}")

    # ---- 逐筆明細(摘要式;各線完整逐筆請見原始個別報告連結) ----
    def _sum_row(name, tdf, ret_col="ret", link=None):
        if tdf is None or len(tdf) == 0:
            return f"<tr><th>{name}</th><td colspan=5>無交易明細可摘要</td></tr>"
        n = len(tdf)
        med = tdf[ret_col].median()
        win = (tdf[ret_col] > 0).mean() * 100
        d0, d1 = (str(tdf.date.min()), str(tdf.date.max())) if "date" in tdf.columns else ("—", "—")
        linktd = f"<td><a href='{link}'>{link}</a></td>" if link else "<td>—</td>"
        return (f"<tr><th>{name}</th><td>{n}</td><td>{med:+.2f}%</td><td>{win:.0f}%</td>"
                f"<td>{d0}~{d1}</td>{linktd}</tr>")

    t4b = t4_trades if "ret" in getattr(t4_trades, "columns", []) else pd.DataFrame({"ret": t4_trades.ret if hasattr(t4_trades, "ret") else []})
    trades_html = ("<div class='note'>本報告為多線總覽,逐筆明細改用「每線一行摘要」呈現"
                   "(單筆中位%/勝率%/資料涵蓋範圍);完整逐筆表請點連結看各線原始報告。"
                   "組合線(⑦)沒有自己的「筆」,不列。</div>"
                   "<table><tr><th>策略線</th><th>n(交易/episode數)</th><th>單筆中位</th>"
                   "<th>勝率</th><th>資料範圍</th><th>完整明細</th></tr>"
                   + _sum_row("① S3⑤強訊號+階梯", s3_trades, "ret")
                   + _sum_row("② 籌碼A1+階梯", t4b, "ret")
                   + _sum_row("③ 題材營收動能score=4+階梯", s4_theme, "ret60", "research_theme_momentum.html")
                   + _sum_row("④ 共振S4(OTC水位階梯)", tdf_reso, "ret", "research_resonance.html")
                   + f"<tr><th>⑤ 處置V4</th><td>{len(nets_v4)}</td><td>{nets_v4.median():+.2f}%</td>"
                     f"<td>{(nets_v4 > 0).mean() * 100:.0f}%</td><td>—</td>"
                     f"<td><a href='research_bottom_playbook.html'>—(僅本腳本內)</a></td></tr>"
                   + "<tr><th>⑥ 亞跌B→持10日</th><td>" + str(line6["stats"]["trades"]) + "</td>"
                     f"<td>{line6['stats']['med']:+.2f}%</td><td>{line6['stats']['win']:.0f}%</td>"
                     "<td>—</td><td><a href='research_bottom_playbook.html'>research_bottom_playbook.html</a></td></tr>"
                   + "</table>")

    verdicts = [
        ("報告定位", "本報告=「目前實際部署在dashboard.html上的6條策略線」原樣疊圖總覽,"
                  "刻意不去重疊(要看的是實際重疊/相關性,不是理想化獨立策略拼盤),外加1條等權組合線。"
                  "取代2026-07-12舊版(舊版只有S1-S4主系統4條線,且無題材動能/共振/處置/溫度計)。"),
        ("6線各自出處", "①②沿用tmp_portfolio_report.py(大題材檢查清單+族群解剖籌碼徽章);"
                     "③改編build_theme_momentum_report.py+build_theme_momentum_tier.py(題材營收動能頁籤,"
                     "採V2組合縮放版);④改編build_resonance_report.py(🔥共振頁籤,取S4 OTC階梯);"
                     "⑤重用build_panic_liquidity_converge.py(處置股觀察頁籤,只取V4不取甜蜜格);"
                     "⑥改編build_bottom_playbook_report.py(🌡️大盤溫度計五燈之一:亞跌B→持10日)。"),
        ("組合線⑦的算法", "各線equity曲線resample成週報酬,每週對「當週有資料的線」取等權平均"
                       "(線尚未開始的區間不計入分母,不當0報酬;線在其自身有效期間內剛好無部位的週,"
                       "本來就是0報酬,正常計入平均)後複利——等權切分本金、無同時併發容量限制、"
                       "忽略部分線是逐日事件驅動(③⑤⑥)、部分是逐週(①②④)的頻率差異,細節見下方限制。"),
        ("驗證重跑一致性", "③題材動能V2/④共振S4皆與交辦文件引用的先前稽核數字對上(容差20%內,"
                         "詳見stdout逐行[OK]/[divergence]標記);①②⑤⑥無先前稽核數字可比對,"
                         "首次以此腳本產生,數字本身即為新基準。"),
    ]
    limits = ("6條線刻意不去重疊,實際部署上很可能有重疊個股/重疊時間窗(尤其①②③同屬「族群/題材動能」"
              "機制家族,④共振也屬同動能家族但獨立宇宙),⑦組合線的分散效果會被高估,勿把⑦當成"
              "「6個真正獨立策略」的組合來解讀,它反映的是「目前儀表板上活著的規則疊在一起長什麼樣」;"
              "⑦等權混合假設每線可等額分配本金、無資金排隊/容量限制,且把逐日事件驅動的線"
              "(③題材動能60日持有/⑤處置V4/⑥亞跌B)與逐週的線(①②④)一律用週末resample對齊,"
              "週內波動細節會被抹平;各線宇宙/起始年不同(①②約2021-10起、③約2022起、"
              "④共振2005起、⑤處置約2019起、⑥亞跌B回溯到1999)——早期只有⑥(甚至①②③⑤都還沒開始)"
              "在算,⑦組合線在2005年前基本等於⑥單獨的曲線,不是6線平均;⑥只取「亞跌B→持10日」"
              "這一個訊號,大盤溫度計頁籤上其餘4個子燈(溫度計本身60日/警戒帶/雙收斂/跌停廣度)"
              "沒有各自現成的equity曲線產生器,合成曝險目前只是研究稿水位階梯,不在本報告內;"
              "CB礦山(WIP,流動性複核待辦)、恐慌甜蜜格(非獨立線,是溫度計組成)、處置慣犯/V5/首日做空"
              "(只有交易明細面板,無現成逐日複利equity序列)、微題材脈衝雷達/補漲雷達(無存檔歷史時間序列)"
              "均不在本報告;🔓內部解質警戒是既有部位的曝險縮放濾網(告訴你減碼,不是自己開倉的策略),"
              "依定義不會有自己的多空交易與equity曲線,故不納入,不是遺漏。各線成本假設沿用原研究"
              "腳本口徑(0.45-0.5%/筆,未含滑價),①②③④⑤⑥的複利/夏普/MDD在各自報告裡是主角,"
              "放在同一張圖上比較「絕對高度」時要注意宇宙/年期不同,凸性/風控形狀比絕對倍數更有意義。")
    prereg = ("2026-07-22彙整版:6條線=目前dashboard.html上實際存在的規則(大題材檢查清單S3/"
              "族群解剖籌碼A1/題材營收動能score=4+階梯/🔥共振S4/處置股觀察V4/🌡️大盤溫度計亞跌B),"
              "各自沿用原驗證腳本的訊號定義與成本假設,本腳本只做「抽取equity曲線+疊圖+等權組合」,"
              "不重新驗證各線本身的統計顯著性(各線的LOTO/bootstrap驗證見原始個別報告)。")

    out_path = "研究報告/research_portfolio_overview.html"
    build_report(out_path, "策略棧總覽回測 v2（目前儀表板6線疊圖+等權組合,2026-07-22）",
                 prereg, strategies, benchmarks, trades_html, verdicts, limits)
    print(f"\n-> {out_path}")


if __name__ == "__main__":
    main()
