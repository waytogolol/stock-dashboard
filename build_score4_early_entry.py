# -*- coding: utf-8 -*-
"""⑫延伸:「score=4訊號其實在進場前一個月已知,月初買進+公告開獎後決定去留,是否優於現行15號進場?」
(使用者2026-07-15提案)

背景事實(本次已核實):
- 凍結口徑: 營收月r收口score → r+1月10號前公告 → 進場r+2月15號。FinMind回補約在公告後1-11天
  (2330 create_time樣本:4/21,5/8,6/10,7/13),故訊號最晚在r+1月下旬已知 = 比現行進場早2-3週。
  「月初買進」不需要預測下期score,訊號是已知的——要測的是提前那段有沒有超額。
- 持續性(2026-07-15先算): P(4→4)=51.7%(n=207); 關鍵是P(訊號月新公布的營收月MoM>0|score=4)
  =53.1% ≈ 無條件基準54.2% → 開獎方向無預測力,搶跑的價值只能來自持有段本身或反應不對稱。

設計(預註冊,單一設定不掃參數):
- 事件: score=4的題材-訊號月T(score口徑=build_theme_score_topn全體版,公告月index,
  row T用shift(1)=資料至公告月T-1=營收月T-2 → T即進場月,與凍結口徑一致)。
  範圍2022-02~2026-06(受日價快取限制)。題材宇宙=tmp_theme_score.pkl(凍結live宇宙)。
- 成員: 進場時已知的前5大(公告月T-12..T-1的12月平均營收排名,同build_theme_score_topn),
  需>=3檔有日價,等權。
- 日期切點(TWII交易日曆):
  d0=T月首個交易日(月初進場,收盤價) d1=T月10號後首個交易日(公告開獎完畢)
  d2=T月15號起首個交易日(現行進場點) d3=T+1月15號起首個交易日(現行出場/換手點)
- 段落(皆收盤到收盤,扣同期TWII=超額):
  S_A=d0→d1(公告窗) S_B=d1→d2(間隙) S_C=d2→d3(現行策略段=baseline)
- 策略對照(每事件一筆):
  ①現行15號進場: S_C
  ②月初進場抱滿: d0→d3
  ③月初進場+開獎差走人(使用者提案): d0→d1後,新公布月(營收月T-1)題材MoM>0→續抱至d3,否則出場
  ④月初進場公告後一律走人: d0→d1
- 判準: ②③的超額中位/勝率顯著優於① → 提前進場有肉; ③>② → 開獎反應有篩選價值。
注意: 快取價格為yfinance調整價(除息日略有噪音);樣本30題材聚類,未做bootstrap=快篩性質。
用法: python build_score4_early_entry.py
"""
import pickle
import sqlite3

import numpy as np
import pandas as pd

PRICE_CACHE = "tmp_revenue_price_cache.pkl"
TWII_PKL = "tmp_twii_long.pkl"
MIN_MEMBERS = 3


def build_score_panel():
    """公告月index的score面板(口徑=build_theme_score_topn全體版,已三段驗證100%一致)"""
    conn = sqlite3.connect("capital_flow.db")
    rev = pd.read_sql("SELECT code, date, revenue FROM fm_month_rev", conn, dtype={"code": str})
    rev["m"] = pd.to_datetime(rev.date)
    cls = pd.read_sql("SELECT code, main_group industry FROM classification WHERE country='台'",
                      conn, dtype={"code": str}).drop_duplicates()
    conn.close()
    themes = sorted(pd.read_pickle("tmp_theme_score.pkl").industry.unique())
    panels, top5map = [], {}
    for ind in themes:
        codes = cls[cls.industry == ind].code.unique()
        g = rev[rev.code.isin(codes)]
        if g.code.nunique() < MIN_MEMBERS:
            continue
        wide = g.pivot_table(index="m", columns="code", values="revenue", aggfunc="first").sort_index()
        tot = wide.sum(axis=1, min_count=1)
        mom = tot.pct_change() * 100
        yoy = tot.pct_change(12) * 100
        s1, s2, s3 = mom.shift(1).gt(0), mom.shift(2).gt(0), mom.shift(3).gt(0)
        msc = np.where(~s1, 0, np.where(~s2, 1, np.where(~s3, 2, 3)))
        sc = msc + yoy.shift(1).rolling(3).mean().gt(0).astype(int)
        df = pd.DataFrame({"score": sc, "mom_new": mom, "industry": ind}, index=wide.index)
        panels.append(df)
        # 進場時已知的前5大: 公告月T-12..T-1平均營收排名
        trail = wide.shift(1).rolling(12, min_periods=3).mean()
        top5map[ind] = {m: list(trail.loc[m].dropna().sort_values(ascending=False).head(5).index)
                        for m in wide.index}
    return pd.concat(panels).rename_axis("sigT").reset_index(), top5map


def seg_dates(cal, T):
    """T=Timestamp(月首)。回傳d0,d1,d2,d3(TWII交易日),任一缺→None"""
    m0, m1 = T, T + pd.offsets.MonthBegin(1)
    try:
        d0 = cal[cal >= m0][0]
        d1 = cal[cal > T + pd.Timedelta(days=9)][0]           # 10號後首個交易日
        d2 = cal[cal >= T + pd.Timedelta(days=14)][0]         # 15號起首個交易日
        d3 = cal[cal >= m1 + pd.Timedelta(days=14)][0]        # 次月15號起首個交易日
    except IndexError:
        return None
    if not (d0 < d1 < d2 < d3 and d1.month == T.month and d2.month == T.month):
        return None
    return d0, d1, d2, d3


def px_ret(close, a, b):
    """close=Series(日收盤); a→b報酬%,用<=該日的最後收盤(pad,無前視)"""
    s = close[close.index <= a]
    e = close[close.index <= b]
    if s.empty or e.empty or s.index[-1] < a - pd.Timedelta(days=7):
        return None
    return (e.iloc[-1] / s.iloc[-1] - 1) * 100


def main():
    panel, top5map = build_score_panel()
    prices = pickle.load(open(PRICE_CACHE, "rb"))
    def _close(v):
        c = v["Close"]
        if isinstance(c, pd.DataFrame):  # yfinance MultiIndex欄位(快取兩種格式混存)
            c = c.iloc[:, 0]
        return c.dropna()
    closes = {k: _close(v) for k, v in prices.items()}
    twii = pd.read_pickle(TWII_PKL).dropna()
    cal = twii.index[(twii.index >= "2022-01-01")]

    ev = panel[(panel.score == 4) & (panel.sigT >= "2022-02-01") & (panel.sigT <= "2026-06-01")].copy()
    rows = []
    for _, e in ev.iterrows():
        d = seg_dates(cal, e.sigT)
        if d is None:
            continue
        d0, d1, d2, d3 = d
        mem = [c for c in top5map[e.industry].get(e.sigT, []) if c in closes]
        if len(mem) < MIN_MEMBERS:
            continue
        segs = {}
        ok = True
        for name, (a, b) in {"SA": (d0, d1), "SB": (d1, d2), "SC": (d2, d3)}.items():
            rs = [px_ret(closes[c], a, b) for c in mem]
            rs = [r for r in rs if r is not None]
            if len(rs) < MIN_MEMBERS:
                ok = False
                break
            segs[name] = float(np.mean(rs))
            segs[name + "_twii"] = (twii.asof(b) / twii.asof(a) - 1) * 100
        if not ok:
            continue
        rows.append({"industry": e.industry, "sigT": e.sigT, "mom_new": e.mom_new, **segs})

    df = pd.DataFrame(rows)
    print(f"事件: {len(df)}筆 score=4題材-月 ({df.industry.nunique()}題材, "
          f"{df.sigT.min():%Y-%m}~{df.sigT.max():%Y-%m})")
    comp = lambda *xs: (np.prod([1 + x / 100 for x in xs]) - 1) * 100

    # 各策略每事件超額
    out = pd.DataFrame({
        "①現行15號(S_C)": df.SC - df.SC_twii,
        "②月初進場抱滿": df.apply(lambda r: comp(r.SA, r.SB, r.SC) - comp(r.SA_twii, r.SB_twii, r.SC_twii), axis=1),
        "③月初+開獎差走人": df.apply(lambda r: (comp(r.SA, r.SB, r.SC) - comp(r.SA_twii, r.SB_twii, r.SC_twii))
                             if r.mom_new > 0 else (r.SA - r.SA_twii), axis=1),
        "④月初公告後一律走": df.SA - df.SA_twii,
    })
    print("\n== 策略對照(TWII超額%) ==")
    print(f"{'策略':<24}{'中位':>8}{'平均':>8}{'勝率':>8}")
    for c in out.columns:
        print(f"{c:<24}{out[c].median():>8.2f}{out[c].mean():>8.2f}{(out[c] > 0).mean() * 100:>7.0f}%")

    print("\n== 段落分解(TWII超額%) ==")
    for name, lab in [("SA", "S_A 月初→公告後(搶跑段)"), ("SB", "S_B 公告後→15號(間隙)"), ("SC", "S_C 15號→次月15號(現行)")]:
        x = df[name] - df[name + "_twii"]
        print(f"{lab:<28} 中位{x.median():>7.2f} 平均{x.mean():>7.2f} 勝率{(x > 0).mean() * 100:>4.0f}%")

    print("\n== 開獎(新公布月MoM)對後段的篩選力 ==")
    for cond, lab in [(df.mom_new > 0, "MoM>0(續抱組)"), (df.mom_new <= 0, "MoM<=0(走人組)")]:
        g = df[cond]
        if len(g) == 0:
            continue
        rest = g.apply(lambda r: comp(r.SB, r.SC) - comp(r.SB_twii, r.SC_twii), axis=1)
        sa = g.SA - g.SA_twii
        print(f"{lab:<16} n={len(g):>3}  開獎段S_A超額中位{sa.median():>7.2f}  後段(d1→d3)超額中位{rest.median():>7.2f} 勝率{(rest > 0).mean() * 100:>4.0f}%")

    print("\n== 逐年(②月初抱滿 vs ①現行, 超額中位) ==")
    df["y"] = df.sigT.dt.year
    for y, g in df.groupby("y"):
        a = (g.SC - g.SC_twii).median()
        b = g.apply(lambda r: comp(r.SA, r.SB, r.SC) - comp(r.SA_twii, r.SB_twii, r.SC_twii), axis=1).median()
        print(f"  {y}: ①{a:>7.2f}  ②{b:>7.2f}  (n={len(g)})")

    df.to_pickle("tmp_score4_early_entry_panel.pkl")
    print("\n面板存 tmp_score4_early_entry_panel.pkl")


if __name__ == "__main__":
    main()
