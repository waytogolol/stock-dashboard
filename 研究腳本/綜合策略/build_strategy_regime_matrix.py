# -*- coding: utf-8 -*-
"""策略×Regime矩陣考卷(2026-07-30晚,使用者問「每種大盤時期哪個策略突出?目前只知道處置股相對穩定」)。

Regime定義(加權指數,零前視,收盤可判):
  多頭 = 收盤>年線 且 年線20日斜率>0
  空頭 = 收盤<年線 且 年線20日斜率<0
  盤整 = 其餘

策略事件源(全部用各自考卷的正式快取/資料表,不重新發明規則):
  ①處置出關+1持10日: disposition表end_date隔日收盤進場,k10(V4口徑近似,持有期=二進宮考卷高原中點)
  ②甜蜜格並發>=20: sweetspot事件日並發數>=20的日子,籃子=當日事件股,k20(溫度計第5燈口徑)
  ③共振題材: resonance episodes(episode_first),題材層fwd8週
  ④跌觸發注意股: attention_full面板down=1且ep_first,個股t10
  ⑤深跌選股: bottom_xsection七個climax episode,每ep取dd52最深1/3,ret20
注意: 各策略持有期不同(k10/k20/8週),矩陣只比「同策略跨regime」,不比策略間絕對值。

判讀: 每策略×regime格=n/勝率/中位/平均;突出度=該regime中位-全期中位;n<8的格子只列不判。
"""
import sqlite3
import numpy as np
import pandas as pd

DB = "capital_flow.db"


def regime_series():
    con = sqlite3.connect(DB)
    idx = pd.read_sql("SELECT date, close FROM index_daily WHERE market='TAIEX' ORDER BY date", con)
    con.close()
    idx["date"] = pd.to_datetime(idx["date"])
    idx = idx.set_index("date")
    ma = idx["close"].rolling(240).mean()
    slope = ma.diff(20)
    reg = pd.Series("盤整", index=idx.index)
    reg[(idx["close"] > ma) & (slope > 0)] = "多頭"
    reg[(idx["close"] < ma) & (slope < 0)] = "空頭"
    return reg


REG = regime_series()


def tag(dates):
    """事件日→regime(取<=該日的最近交易日標籤)"""
    d = pd.to_datetime(pd.Series(dates))
    return pd.Series(REG.reindex(d, method="ffill").values, index=d.index)


def price_panel():
    con = sqlite3.connect(DB)
    px = pd.read_sql("SELECT code, date, open, close, money FROM fm_daily_price", con)
    con.close()
    px["date"] = pd.to_datetime(px["date"])
    pv = {c: px.pivot_table(index="date", columns="code", values=c, aggfunc="last")
          for c in ("open", "close", "money")}
    return pv


def fwd_ret(pv, code, d, k):
    if code not in pv["close"].columns:
        return np.nan
    s = pv["close"][code].dropna()
    s = s[s > 0]
    i = s.index.searchsorted(d)
    if i >= len(s) or (s.index[i] - d).days > 5 or i + k >= len(s):
        return np.nan
    return s.iloc[i + k] / s.iloc[i] - 1


def strat_dispo_v4(pv):
    """V4正式口徑(dispo_equity_overview同款): 池=窗6-25交易日∧tv3>=0.3億,
    第3處置日尾盤買→出關日(end後首個交易日)開盤出, net成本0.45%"""
    con = sqlite3.connect(DB)
    d = pd.read_sql("SELECT code, start_date, end_date FROM disposition", con)
    con.close()
    d["start_date"] = pd.to_datetime(d["start_date"]); d["end_date"] = pd.to_datetime(d["end_date"])
    d = d.dropna()
    rows = []
    for code, s0, s1 in d.itertuples(index=False):
        if code not in pv["close"].columns:
            continue
        c = pv["close"][code].dropna(); c = c[c > 0]
        o = pv["open"][code]; m = pv["money"][code]
        win = c.loc[s0:s1]
        if not (6 <= len(win) <= 25) or len(win) < 3:
            continue
        entry_d = win.index[2]                      # 第3處置日
        tv3 = m.loc[:entry_d].dropna().tail(3).mean() / 1e8
        if not tv3 >= 0.3:
            continue
        after = c.loc[c.index > s1]
        if len(after) == 0:
            continue
        exit_d = after.index[0]
        if pd.isna(o.get(exit_d)) or o.get(exit_d, 0) <= 0:
            continue
        rows.append({"date": entry_d, "ret": o[exit_d] / c[entry_d] - 1 - 0.0045})
    return pd.DataFrame(rows)


def strat_sweetspot(pv):
    """甜蜜格正式門檻(panic_liquidity_converge同款): 當日跌(-9,-6]×回檔>=20×近40日漲幅rr>1.2×
    成交值>1億; 並發>=20日=恐慌燈, 籃子k20"""
    ev = pd.read_pickle("快取/tmp_panic_sweetspot_events.pkl")
    q = ev[(ev["dd"] <= -6) & (ev["dd"] > -9) & (ev["pull"] >= 20) & (ev["rr"] > 1.2) & (ev["tv"] > 1)]
    cnt = q.groupby("d0").size()
    days = cnt[cnt >= 20].index
    rows = []
    for d0 in days:
        codes = q.loc[q["d0"] == d0, "code"].astype(str)
        rets = [fwd_ret(pv, c, pd.Timestamp(d0), 20) for c in codes]
        rets = [r for r in rets if not np.isnan(r)]
        if rets:
            rows.append({"date": pd.Timestamp(d0), "ret": float(np.mean(rets))})
    return pd.DataFrame(rows)


def strat_resonance():
    ep = pd.read_pickle("快取/tmp_resonance_theme_episodes.pkl")
    e = ep[ep["episode_first"] == True].dropna(subset=["fwd8"])
    r = e["fwd8"].astype(float)
    if r.abs().median() > 1:   # 面板存pp就轉小數
        r = r / 100.0
    return pd.DataFrame({"date": pd.to_datetime(e["week"]), "ret": r})


def strat_attention_down():
    a = pd.read_pickle("快取/tmp_attention_full_panel.pkl")
    e = a[(a["down"] == 1) & (a["ep_first"] == 1)].dropna(subset=["t10"])
    r = e["t10"].astype(float)
    if r.abs().median() > 1:  # 面板若存百分比就轉小數
        r = r / 100.0
    return pd.DataFrame({"date": pd.to_datetime(e["date"]), "ret": r})


def strat_bottom():
    b = pd.read_pickle("快取/tmp_bottom_xsection_panel.pkl")
    rows = []
    for ep, g in b.groupby("ep"):
        sel = g.nsmallest(max(3, len(g) // 3), "dd52")   # dd52最深(最負)1/3
        r = sel["ret20"].astype(float)
        if r.abs().median() > 1:
            r = r / 100.0
        rows.append({"date": pd.Timestamp(ep), "ret": float(r.mean())})
    return pd.DataFrame(rows)


def cell(r):
    if len(r) == 0:
        return "—"
    win = (r > 0).mean() * 100
    return f"n={len(r):d} 勝{win:.0f}% 中位{np.median(r)*100:+.2f}% 均{np.mean(r)*100:+.2f}%"


def main():
    pv = price_panel()
    strategies = [
        ("①處置V4(第3日尾盤→出關開盤,net)", strat_dispo_v4(pv)),
        ("②甜蜜格並發≥20籃子(k20)", strat_sweetspot(pv)),
        ("③共振題材(8週)", strat_resonance()),
        ("④跌觸發注意股(t10)", strat_attention_down()),
        ("⑤深跌選股climax(k20)", strat_bottom()),
    ]
    print("=" * 110)
    print("策略×Regime矩陣 (regime=加權年線位階+斜率; 各策略持有期不同,只比同列跨格)")
    print("=" * 110)
    verdict = []
    for name, ev in strategies:
        if len(ev) == 0:
            print(f"\n{name}: 無事件")
            continue
        ev = ev.copy()
        ev["regime"] = tag(ev["date"]).values
        row = {"策略": name, "全期": cell(ev["ret"])}
        med_all = np.median(ev["ret"])
        best = None
        for rg in ["多頭", "盤整", "空頭"]:
            r = ev.loc[ev["regime"] == rg, "ret"]
            row[rg] = cell(r)
            if len(r) >= 8:
                edge = np.median(r) - med_all
                if best is None or edge > best[1]:
                    best = (rg, edge)
        row["突出時期"] = f"{best[0]}(中位+{best[1]*100:.2f}pp vs 全期)" if best else "樣本不足"
        verdict.append(row)
        print(f"\n【{name}】  全期: {row['全期']}")
        for rg in ["多頭", "盤整", "空頭"]:
            print(f"   {rg}: {row[rg]}")
        print(f"   → 突出: {row['突出時期']}")
        yr = ev.groupby(ev["date"].dt.year)["ret"].agg(["size", "median"])
        neg_years = yr[yr["median"] < 0].index.tolist()
        print(f"   逐年中位<0的年份: {neg_years if neg_years else '無'}")
    # regime全史統計
    print("\n" + "=" * 110)
    seg = REG.dropna()
    print("Regime全史占比(2000~今):", {k: f"{v/len(seg)*100:.0f}%" for k, v in seg.value_counts().items()},
          " 當下:", seg.iloc[-1], f"({seg.index[-1].date()})")
    pd.to_pickle({"regime": REG}, "快取/tmp_regime_series.pkl")
    print("regime序列已存 快取/tmp_regime_series.pkl (領導權考卷/其他考卷共用)")


if __name__ == "__main__":
    main()
