# -*- coding: utf-8 -*-
"""法說會「事前埋伏」考卷(2026-07-26,使用者提案:偷看答案法——先看法說前上漲的股票長什麼樣,
再把特徵變規則驗證;並補前一卷漏掉的大小型分層)
背景: build_conference_event.py已判=法說後10日賣方窗(-0.84pp安慰劑後);本卷看「前」段。
使用者領域知識: 大型權值股法說會提前很久公告,中小型約前5天才公告=埋伏窗依規模不同。
設計(預註冊):
- 埋伏窗=D-6收盤買→D-1收盤賣(5交易日,中小型公告窗口徑),扣0.45%
- 規模分組=金流三分位(D-25~D-6的20日均成交值,刻意避開埋伏窗自身,無前視)
- Q1: 埋伏窗全體+分組(金流/自辦/線上/市場/位階)可交易報酬
- Q2: 偷看答案case-control——H1(2025-08~2026-01)內pre5前四分位=贏家,比對特徵指紋
  (金流/位階/量能爬升vr=D-11~D-6量/D-25~D-6量/自辦/線上/上櫃);由H1指紋挑前2強特徵拼規則,
  H2(2026-02~)樣本外驗證。特徵清單就這6個,寫死,不加新的。
- Q3: 埋伏強度×事後x10(等權超額)——埋伏漲多的法說後是否跌更兇(sell-the-news劑量)
- 限制: 單一regime 11個月,H1/H2皆多頭;判決上限=觀察層候選
用法: python -X utf8 build_conference_pre.py
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
B_BOOT = 10000
SEED = 42
H_SPLIT = "2026-02-01"


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
        print(f"{pref}{lab}: n={len(x)}太少")
        return None
    print(f"{pref}{lab}: 中位{x.median():+6.2f}% 均值{x.mean():+6.2f}% "
          f"勝率{(x > 0).mean() * 100:3.0f}% n={len(x):,}")
    return x


def month_boot(df, col, label, b=B_BOOT, seed=SEED):
    d = df.dropna(subset=[col]).copy()
    d["mo"] = d.date.dt.to_period("M").astype(str)
    mos = sorted(d.mo.unique())
    if len(mos) < 5 or len(d) < 60:
        print(f"      [{label}] 月份/樣本不足,略過")
        return
    mm = d.groupby("mo")[col].median()
    print(f"      逐月中位為正: {(mm > 0).sum()}/{len(mos)}月 (最差{mm.idxmin()}={mm.min():+.2f}%)")
    rng = np.random.default_rng(seed)
    groups = {m: d.loc[d.mo == m, col].values for m in mos}
    meds = []
    for _ in range(b):
        pick = rng.choice(mos, size=len(mos), replace=True)
        meds.append(np.median(np.concatenate([groups[m] for m in pick])))
    meds = np.array(meds)
    lo, hi = np.percentile(meds, [2.5, 97.5])
    print(f"      月群bootstrap: 中位CI95=[{lo:+.2f},{hi:+.2f}]% P(<=0)={(meds <= 0).mean():.4f}")


def main():
    conf = rd("SELECT code, date, time, market, place, information FROM conference")
    conf["date"] = pd.to_datetime(conf.date)
    conf = conf[conf.code.str.fullmatch(r"\d{4}")]
    conf = conf.sort_values(["code", "date", "time"]).drop_duplicates(["code", "date"])
    px = rd("SELECT code, date, open, close, money FROM fm_daily_price ORDER BY code, date")
    px["date"] = pd.to_datetime(px.date)
    stocks = {c: g.sort_values("date").reset_index(drop=True) for c, g in px.groupby("code")}
    piv = px[px.close > 0].pivot_table(index="date", columns="code", values="close")
    ew_ret = piv.pct_change(fill_method=None).mean(axis=1).fillna(0.0)
    ew_idx = (1 + ew_ret).cumprod()
    ew_dts, ew_cls = ew_idx.index.values, ew_idx.values

    rows = []
    for r in conf.itertuples():
        g = stocks.get(r.code)
        if g is None:
            continue
        dts = g.date.values
        n = len(g)
        i = int(np.searchsorted(dts, np.datetime64(r.date)))
        if i < 26 or i + 10 >= n:
            continue
        o_, c_, m_ = g.open.values, g.close.values, g.money.values
        if c_[i - 6] <= 0 or c_[i - 1] <= 0:
            continue
        base_m = m_[i - 25:i - 5]
        base_m = base_m[base_m > 0]
        if len(base_m) < 10:
            continue
        amt20 = float(np.mean(base_m)) / 1e8
        late_m = m_[i - 11:i - 5]
        late_m = late_m[late_m > 0]
        vr = float(np.mean(late_m)) / (float(np.mean(base_m))) if len(late_m) >= 3 else np.nan
        w = c_[max(0, i - 241):i - 6]
        w = w[w > 0]
        ptile = (w <= c_[i - 6]).mean() * 100 if len(w) >= 120 else np.nan
        pre5 = (c_[i - 1] / c_[i - 6] - 1) * 100 - COST
        rec = {"code": r.code, "date": r.date, "market": r.market,
               "own": "召開" in str(r.information) and "參加" not in str(r.information),
               "online": any(k in (str(r.place) + str(r.information)) for k in ("線上", "視訊", "電話", "網路")),
               "amt20": amt20, "vr": vr, "ptile": ptile, "pre5": pre5}
        # 事後x10(等權超額,D+1開→D+10收)
        if i + 1 < n and o_[i + 1] > 0 and i + 10 < n and c_[i + 10] > 0:
            raw = (c_[i + 10] / o_[i + 1] - 1) * 100 - COST
            ei = int(np.searchsorted(ew_dts, dts[i + 1]))
            ej = int(np.searchsorted(ew_dts, dts[i + 10], side="right") - 1)
            if 0 <= ei < len(ew_cls) and 0 <= ej < len(ew_cls) and ei < ej:
                rec["x10"] = raw - (ew_cls[ej] / ew_cls[ei] - 1) * 100
        rows.append(rec)
    ev = pd.DataFrame(rows)
    ev["size_ter"] = pd.qcut(ev.amt20.rank(method="first"), 3, labels=["小", "中", "大"])
    ev.to_pickle("tmp_conference_pre_panel.pkl")
    print(f"可測事件: {len(ev):,} ({ev.date.min().date()}~{ev.date.max().date()}); "
          f"金流三分位切點: {ev.amt20.quantile(1 / 3):.2f}/{ev.amt20.quantile(2 / 3):.2f}億")
    print("⚠限制: 單一regime;H1找特徵/H2驗規則皆多頭市場\n")

    print("== Q1: 埋伏窗(D-6收→D-1收,扣0.45%)可交易報酬 ==")
    stat(ev.pre5, "全體")
    month_boot(ev, "pre5", "全體pre5")
    for ter in ["小", "中", "大"]:
        stat(ev.loc[ev.size_ter == ter, "pre5"], f"金流{ter}")
    for mask, lab in [(ev.own, "自辦"), (~ev.own, "受邀"), (ev.online, "線上"), (~ev.online, "實體"),
                      (ev.market == "TWO", "上櫃"), (ev.market == "TW", "上市"),
                      (ev.ptile >= 80, "高位階"), (ev.ptile <= 50, "低位階")]:
        stat(ev.loc[mask, "pre5"], f"{lab}")

    print("\n== Q2: 偷看答案 case-control (H1=~2026-01找特徵, H2=2026-02~驗規則) ==")
    h1 = ev[ev.date < H_SPLIT].copy()
    h2 = ev[ev.date >= H_SPLIT].copy()
    q75 = h1.pre5.quantile(0.75)
    h1["win"] = h1.pre5 >= q75
    print(f"  H1 n={len(h1):,} (贏家門檻pre5>={q75:+.2f}%), H2 n={len(h2):,}")
    print("  H1 贏家 vs 其餘特徵指紋:")
    feats = []
    for col, lab, kind in [("amt20", "金流億(中位)", "med"), ("vr", "量能爬升vr(中位)", "med"),
                           ("ptile", "位階(中位)", "med"), ("own", "自辦%", "pct"),
                           ("online", "線上%", "pct")]:
        wv = h1.loc[h1.win, col]
        rv = h1.loc[~h1.win, col]
        if kind == "med":
            a, b = wv.median(), rv.median()
            print(f"    {lab}: 贏家{a:8.2f} vs 其餘{b:8.2f}")
            feats.append((col, a, b))
        else:
            a, b = wv.mean() * 100, rv.mean() * 100
            print(f"    {lab}: 贏家{a:7.1f}% vs 其餘{b:7.1f}%")
    two = h1.groupby("market").win.mean() * 100
    print(f"    上櫃贏家率 vs 上市: " + "  ".join(f"{k}={v:.1f}%" for k, v in two.items()))
    # 連續特徵中位差距最大的前2個(標準化差) => 拼H2規則
    ranked = []
    for col, a, b in feats:
        sd = h1[col].std()
        if sd and np.isfinite(sd) and sd > 0:
            ranked.append((abs(a - b) / sd, col, a > b))
    ranked.sort(reverse=True)
    print(f"  H1特徵強度排序: {[(c, round(s, 3), '贏家較高' if hi else '贏家較低') for s, c, hi in ranked]}")
    f1, f2 = ranked[0], ranked[1]
    print(f"  => H2規則(預先由H1定): {f1[1]}{'高' if f1[2] else '低'}半 ∧ {f2[1]}{'高' if f2[2] else '低'}半")
    m1 = h2[f1[1]] >= h1[f1[1]].median() if f1[2] else h2[f1[1]] <= h1[f1[1]].median()
    m2 = h2[f2[1]] >= h1[f2[1]].median() if f2[2] else h2[f2[1]] <= h1[f2[1]].median()
    a = stat(h2.loc[m1 & m2, "pre5"], "H2 規則命中組 pre5")
    b = stat(h2.loc[~(m1 & m2), "pre5"], "H2 其餘 pre5")
    if a is not None and b is not None:
        print(f"      H2中位差={a.median() - b.median():+.2f}pp (正且明顯=特徵可外推)")
        month_boot(h2[m1 & m2], "pre5", "H2規則組")

    print("\n== Q3: 埋伏強度×事後x10(sell-the-news劑量) ==")
    ev["pre_q"] = pd.qcut(ev.pre5.rank(method="first"), 4, labels=["Q1弱", "Q2", "Q3", "Q4強"])
    for q in ["Q1弱", "Q2", "Q3", "Q4強"]:
        stat(ev.loc[ev.pre_q == q, "x10"], f"事前{q} -> 事後x10")
    print("\n== 補: 前一卷漏的大小型分層(事後x10等權超額) ==")
    for ter in ["小", "中", "大"]:
        stat(ev.loc[ev.size_ter == ter, "x10"], f"金流{ter} x10")


if __name__ == "__main__":
    main()
