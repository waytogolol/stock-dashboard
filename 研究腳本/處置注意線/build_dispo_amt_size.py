# -*- coding: utf-8 -*-
"""處置V4×成交值選件加分考卷(預註冊2026-07-28深夜,使用者裁示「要多驗證或其他組合?」)
========================================================================
來源: winrate考卷Q4探索格「站上季線×大成交值=+4.77%/65%(n=905)」未預註冊→本卷正式驗。
預先聲明的混淆(跑之前寫死,全部要控):
  A 大成交值↔20分盤相關(第二次處置=熱票)→分盤內部各自看梯度
  B 絕對億數非平稳(市場8年變大,晚期單子天然大→混年份效應)→年內三分位重驗
  C 與市場別(上櫃小票多)相關→市場內重驗
預註冊測試(主測+四控+穩健):
  主測: 2019-22找形狀(五分位梯度) → 2023-26凍結驗(大1/3−小1/3中位差,月cluster bootstrap CI)
  控A: 5分盤內/20分盤內三分位差   控B: 年內三分位差(逐年)   控C: 上市內/上櫃內
  控D: regime交互=站上/跌破季線×三分位(預期:梯度主要在多頭側,跌破側弱=前卷已見)
  穩健: 換口徑amt20(公告前20日均額,規則卡同源)同向才算數
判準: 凍結段CI排0 ∧ 分盤內同向 ∧ 年內版仍在 → 晉級「選件加分層」候選(上板=處置頁加排序提示);
  任何一關反向→降級描述性。n大可bootstrap(月cluster);死格對照=跌破季線側梯度預期弱。
用法: python build_dispo_amt_size.py
"""
import sqlite3
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
DB = "capital_flow.db"
COST = 0.45
rng = np.random.default_rng(20260728)


def build_trades():
    conn = sqlite3.connect(DB)
    disp = pd.read_sql("SELECT * FROM disposition", conn)
    px = pd.read_sql("SELECT code, date, open, close, money FROM fm_daily_price "
                     "WHERE close>0 ORDER BY code, date", conn)
    tw = pd.read_sql("SELECT date, close FROM index_daily WHERE market='TAIEX' ORDER BY date",
                     conn, parse_dates=["date"]).set_index("date").close
    conn.close()
    for c in ("start_date", "end_date"):
        disp[c] = pd.to_datetime(disp[c], errors="coerce")
    disp = disp.dropna(subset=["start_date", "end_date"])
    px["date"] = pd.to_datetime(px.date)
    stocks = {c: g.sort_values("date").reset_index(drop=True) for c, g in px.groupby("code")}
    ma60 = tw.rolling(60).mean()
    rows = []
    for _, e in disp.iterrows():
        g = stocks.get(e.code)
        if g is None:
            continue
        dts = g.date.values
        n = len(g)
        s = int(np.searchsorted(dts, np.datetime64(e.start_date)))
        en = int(np.searchsorted(dts, np.datetime64(e.end_date), side="right") - 1)
        if s >= n or en <= s or en - s > 25 or en - s < 6 or en + 1 >= n:
            continue
        ei = s + 2
        if ei >= n or g.close.iloc[ei] <= 0 or g.open.iloc[en + 1] <= 0:
            continue
        d0 = g.date.iloc[ei]
        amt20 = g.money.iloc[max(0, s - 20):s].mean() / 1e8 if s > 0 else np.nan
        i_tw = tw.index.searchsorted(d0, side="right") - 1
        rows.append({"code": e.code, "d": d0, "y": d0.year, "m": d0.strftime("%Y-%m"),
                     "mins": str(e.match_min), "mkt": e.market,
                     "ret": (g.open.iloc[en + 1] / g.close.iloc[ei] - 1) * 100 - COST,
                     "amt": float(g.money.iloc[ei] or 0) / 1e8, "amt20": amt20,
                     "above60": bool(tw.iloc[i_tw] > ma60.iloc[i_tw]) if i_tw >= 60 else None})
    return pd.DataFrame(rows)


def ter(s):
    return pd.qcut(s.rank(method="first"), 3, labels=["小", "中", "大"])


def cellstr(g):
    return f"{g.ret.median():+.2f}%/{(g.ret > 0).mean() * 100:.0f}%(n={len(g)})"


def terline(df, lab, col="amt"):
    if len(df) < 60:
        print(f"  {lab}: n={len(df)}太少")
        return None
    d = df.copy()
    d["t"] = ter(d[col])
    parts = [f"{t}:{cellstr(g)}" for t, g in d.groupby("t", observed=True)]
    big = d[d.t == "大"].ret.median() - d[d.t == "小"].ret.median()
    print(f"  {lab}: " + " | ".join(parts) + f"  大−小={big:+.2f}pp")
    return big


def boot_diff(df, col="amt", n_boot=2000):
    """月cluster bootstrap: 大1/3−小1/3中位差CI"""
    d = df.copy()
    d["t"] = ter(d[col])
    months = d.m.unique()
    obs = d[d.t == "大"].ret.median() - d[d.t == "小"].ret.median()
    ds = []
    for _ in range(n_boot):
        pick = rng.choice(months, len(months), replace=True)
        sub = pd.concat([d[d.m == mm] for mm in pick])
        a, b = sub[sub.t == "大"].ret, sub[sub.t == "小"].ret
        if len(a) > 10 and len(b) > 10:
            ds.append(a.median() - b.median())
    lo, hi = np.percentile(ds, [2.5, 97.5])
    return obs, lo, hi


def main():
    tr = build_trades()
    print(f"V4交易 {len(tr)}筆 {tr.d.min().date()}~{tr.d.max().date()}")

    print("\n═══ 主測: 全樣本五分位梯度(進場日成交值) ═══")
    tr["q5"] = pd.qcut(tr.amt.rank(method="first"), 5, labels=False)
    for q, g in tr.groupby("q5"):
        print(f"  Q{q + 1}({g.amt.median():.2f}億): {cellstr(g)}")

    print("\n═══ 主測: 切樣本 2019-22找 → 2023-26凍結驗 ═══")
    early, late = tr[tr.y <= 2022], tr[tr.y >= 2023]
    terline(early, "2019-22(找)")
    obs, lo, hi = boot_diff(late)
    terline(late, "2023-26(凍結驗)")
    print(f"  凍結段 大−小={obs:+.2f}pp 月cluster bootstrap CI95=[{lo:+.2f},{hi:+.2f}] "
          f"{'✅排0' if lo > 0 else '❌含0'}")

    print("\n═══ 控A: 分盤內部 ═══")
    for mn, g in tr.groupby("mins"):
        terline(g, f"{mn}分盤內")

    print("\n═══ 控B: 年內三分位(殺非平稳) ═══")
    diffs = []
    for y, g in tr.groupby("y"):
        b = terline(g, f"{y}")
        if b is not None:
            diffs.append(b)
    print(f"  逐年大−小: {sum(1 for d_ in diffs if d_ > 0)}/{len(diffs)}年為正")

    print("\n═══ 控C: 市場內 ═══")
    for mk, g in tr.groupby("mkt"):
        terline(g, f"{mk}內")

    print("\n═══ 控D: regime交互 ═══")
    for reg, g in tr.dropna(subset=["above60"]).groupby("above60"):
        terline(g, "站上季線" if reg else "跌破季線")

    print("\n═══ 穩健: 換口徑amt20(公告前20日均額) ═══")
    terline(tr.dropna(subset=["amt20"]), "全樣本amt20口徑", col="amt20")
    obs2, lo2, hi2 = boot_diff(late.dropna(subset=["amt20"]), col="amt20")
    print(f"  凍結段amt20口徑 大−小={obs2:+.2f}pp CI95=[{lo2:+.2f},{hi2:+.2f}]")

    print("\n預註冊判準: 凍結CI排0∧分盤內同向∧年內仍在∧換口徑同向→選件加分層候選;任一反向→描述性。")


if __name__ == "__main__":
    main()
