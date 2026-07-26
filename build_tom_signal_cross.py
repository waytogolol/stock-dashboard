# -*- coding: utf-8 -*-
"""TOM窗×既有策略訊號交叉考卷(2026-07-26,使用者提案:「現有訊號在月底月初觸發的是否表現較好?」)
背景: build_index_tom.py已判=25日~次月5日窗指數層真實(全球TOM資金流,非月營收埋伏),
  量級每日+0.03~0.10%,TAIEX後半已衰減、TPEx殘留。
先驗(誠實申報): 策略持有期8~60日,TOM窗只覆蓋前幾天,效應應被稀釋;預期多數家族不顯著,
  弱結果不得敘事成正面;多家族多重檢定,單一家族壓線過不採。
設計(預註冊):
- 窗判定: 進場日曆日>=25或<=5=in(近似W窗,交易日邊界誤差1-2日容忍)
- 家族與口徑(全部用既有面板既有報酬欄,不重算策略):
  F1 處置V4(base%,5/20分層永不合併)——n夠跑正式驗證(in-out差LOTO逐年+年群bootstrap)
  F2 注意股跌觸發(episode_first∧direction=down,trade10)——正式驗證
  F3 共振episode(2019+子集,成員等權,episode週末次日收盤買持40交易日,減等權市場)——描述+bootstrap
  F4 規則①-⑤(151筆ret8w)——n小僅描述
- 判準: 家族in-out差需LOTO多數年同向+年群bootstrap CI排0;全家族方向計數當meta觀察
用法: python -X utf8 build_tom_signal_cross.py
"""
import sqlite3
import sys
import time

import numpy as np
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DB = "capital_flow.db"
B_BOOT = 10000
SEED = 42


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


def in_tom(d):
    return (d.dt.day >= 25) | (d.dt.day <= 5)


def stat(x, lab, pref="    "):
    x = pd.Series(x).dropna()
    if len(x) < 12:
        print(f"{pref}{lab}: n={len(x)}太少")
        return None
    print(f"{pref}{lab}: 中位{x.median():+6.2f}% 均值{x.mean():+6.2f}% "
          f"勝率{(x > 0).mean() * 100:3.0f}% n={len(x):,}")
    return x


def loto_boot(sig, ctl, val, ycol, label, b=B_BOOT, seed=SEED):
    sig, ctl = sig.dropna(subset=[val]), ctl.dropna(subset=[val])
    if len(sig) < 15 or len(ctl) < 15:
        print(f"      [{label}] n不足({len(sig)}/{len(ctl)}),不測")
        return
    years = sorted(set(sig[ycol]) | set(ctl[ycol]))
    rows = []
    for yr in years:
        s2, c2 = sig[sig[ycol] != yr], ctl[ctl[ycol] != yr]
        if len(s2) >= 10 and len(c2) >= 10:
            rows.append((yr, s2[val].median() - c2[val].median()))
    if rows:
        rows.sort(key=lambda r: r[1])
        pos = sum(1 for _, d in rows if d > 0)
        print(f"      LOTO最壞: 剔{rows[0][0]}後{rows[0][1]:+.2f}pp, 為正{pos}/{len(rows)}年")
    rng = np.random.default_rng(seed)
    sg = {yr: sig.loc[sig[ycol] == yr, val].values for yr in sig[ycol].unique()}
    cg = {yr: ctl.loc[ctl[ycol] == yr, val].values for yr in ctl[ycol].unique()}
    diffs = []
    for _ in range(b):
        pick = rng.choice(years, size=len(years), replace=True)
        sa = [sg[y] for y in pick if y in sg]
        ca = [cg[y] for y in pick if y in cg]
        if sa and ca:
            sa, ca = np.concatenate(sa), np.concatenate(ca)
            if len(sa) >= 10 and len(ca) >= 10:
                diffs.append(np.median(sa) - np.median(ca))
    diffs = np.array(diffs)
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    print(f"      bootstrap差值CI95=[{lo:+.2f},{hi:+.2f}]pp P(<=0)={(diffs <= 0).mean():.4f}")


def fam(df, val, ycol, label, formal=True):
    df = df.copy()
    df["tom"] = in_tom(df["_d"])
    a = stat(df.loc[df.tom, val], f"{label} TOM窗內")
    b = stat(df.loc[~df.tom, val], f"{label} 窗外")
    d = None
    if a is not None and b is not None:
        d = a.median() - b.median()
        print(f"      中位差(窗內-窗外): {d:+.2f}pp")
        if formal:
            loto_boot(df[df.tom], df[~df.tom], val, ycol, label)
    return d


def main():
    dirs = []
    # F1 處置V4
    dp = pd.read_pickle("tmp_disposition_path_panel.pkl")
    dp["_d"] = pd.to_datetime(dp.entry_date)
    print("=" * 70)
    print("F1 處置V4(第3處置日收盤進場,base=淨報酬%)")
    print("=" * 70)
    for mm in ["20", "5"]:
        d = fam(dp[dp.match_min == mm], "base", "y", f"V4 {mm}分盤")
        if d is not None:
            dirs.append((f"V4-{mm}分", d))

    # F2 注意股跌觸發(晉級候選那組)
    at = pd.read_pickle("tmp_attention_event_panel.pkl")
    at = at[at.episode_first & (at.direction == "down")].copy()
    at["_d"] = pd.to_datetime(at.index.get_level_values(0)) if isinstance(at.index, pd.MultiIndex) else None
    if "_d" not in at or at["_d"] is None or at["_d"].isna().all():
        # 日期欄名防呆: 面板index或date欄
        for c in ("date", "announce_date", "first_date"):
            if c in at.columns:
                at["_d"] = pd.to_datetime(at[c])
                break
    print("\n" + "=" * 70)
    print("F2 注意股跌觸發(episode首筆,trade10=次日開盤買T+10收盤賣)")
    print("=" * 70)
    if "_d" in at.columns and at["_d"].notna().any():
        d = fam(at, "trade10", "y", "跌觸發")
        if d is not None:
            dirs.append(("注意跌觸發", d))
    else:
        print("    面板無日期欄,跳過(欄位=" + ",".join(at.columns[:8]) + ")")

    # F3 共振episode(2019+,成員等權,episode週最後交易日次日收盤買→+40交易日,減等權市場)
    print("\n" + "=" * 70)
    print("F3 共振episode(2019+子集重算報酬,成員等權-等權市場,+40交易日)")
    print("=" * 70)
    rs = pd.read_pickle("tmp_resonance_theme_events.pkl")
    rs = rs[rs.episode_first].copy()
    rs["week"] = pd.to_datetime(rs.week)
    rs = rs[rs.week >= "2019-01-01"]
    px = rd("SELECT code, date, close FROM fm_daily_price ORDER BY code, date")
    px["date"] = pd.to_datetime(px.date)
    piv = px[px.close > 0].pivot_table(index="date", columns="code", values="close")
    ew = (1 + piv.pct_change(fill_method=None).mean(axis=1).fillna(0)).cumprod()
    dts = piv.index
    rows = []
    for r in rs.itertuples():
        wk_end = r.week + pd.Timedelta(days=6)
        i = dts.searchsorted(wk_end, side="right")  # 週結束後第一個交易日
        if i + 40 >= len(dts):
            continue
        mem = [m for m in (r.members if isinstance(r.members, (list, tuple)) else str(r.members).split(",")) if m in piv.columns]
        if not mem:
            continue
        p0 = piv.iloc[i][mem]
        p1 = piv.iloc[i + 40][mem]
        ok = p0.notna() & p1.notna() & (p0 > 0)
        if ok.sum() == 0:
            continue
        ret = ((p1[ok] / p0[ok] - 1) * 100).mean()
        ret -= (ew.iloc[i + 40] / ew.iloc[i] - 1) * 100
        rows.append({"_d": dts[i], "y": dts[i].year, "r8": ret})
    rf = pd.DataFrame(rows)
    print(f"    可測episode: {len(rf)} (2019+)")
    if len(rf):
        d = fam(rf, "r8", "y", "共振ep")
        if d is not None:
            dirs.append(("共振", d))

    # F4 規則①-⑤ 151筆(僅描述)
    print("\n" + "=" * 70)
    print("F4 規則①-⑤熊市壓測151筆(ret8w,n小僅描述)")
    print("=" * 70)
    bt = pd.read_csv("tmp_bear_trades.csv")
    bt["_d"] = pd.to_datetime(bt.date)
    bt["y"] = bt["_d"].dt.year
    bt["ret"] = pd.to_numeric(bt.ret8w, errors="coerce")
    d = fam(bt, "ret", "y", "規則①-⑤", formal=False)
    if d is not None:
        dirs.append(("規則①-⑤", d))

    print("\n" + "=" * 70)
    print("meta觀察: 各家族(窗內-窗外)中位差方向")
    print("=" * 70)
    for lab, d in dirs:
        print(f"    {lab}: {d:+.2f}pp {'(窗內較好)' if d > 0 else '(窗外較好)'}")


if __name__ == "__main__":
    main()
