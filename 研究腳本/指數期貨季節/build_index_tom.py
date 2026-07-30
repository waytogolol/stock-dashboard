# -*- coding: utf-8 -*-
"""月內日曆效應考卷(turn-of-the-month,使用者2026-07-25提案:「文章說25號~次月5號行情好做」)
假說(使用者): 月底埋伏月營收(台股10日前強制公布)+權值股連動 => 25日~次月5日窗報酬優於其餘時段。
機制候選(預註冊,結果出來後只能在這三個裡挑,不得新編):
  M1 月營收埋伏(台股特有) => 若真,強段應延伸到6-10日(公布截止),且台股強於美日韓
  M2 月初資金流(定期定額/退休金/TOM全球異常) => 強段集中月初1-5日,且美日韓同樣有
  M3 月底作帳(投信季底更強) => 強段集中月底最後2-3交易日
設計(預註冊):
- 資料: index_daily TAIEX(1999-2026,27年)/TPEx(2005-2026)主測;SPX/N225/KOSPI同窗對照(機制判別)
- 主測窗W: 每月「日曆25日(含)後第一個交易日收盤買 -> 次月5日(含)後第一個交易日收盤賣」;
  互補窗C: 其餘時段(5日後首日收盤->同月25日前最後...即W出場到下個W進場)。W+C=全時段無縫。
- 判準: W-C配對差(同週期)均值,LOTO逐年+年群cluster bootstrap(B=10000,seed=42);
  W與C長度不同(約7 vs 14交易日),同時報「每交易日平均報酬」口徑;半段穩健(前半/後半年份)
- 解剖: 相對交易日曲線(月底倒數5日/月初前7日逐日平均報酬)定位強段在哪->механизм判別
- 誠實申報: 指數不可直接交易,報毛報酬;實作載具=台指期/OTC期或00631L等,成本另計;
  月曆效應家族先前判決=月份層有效(12月強),月內層是新軸
用法: python -X utf8 build_index_tom.py
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
D_IN = 25   # 窗進場: 日曆日>=25後第一個交易日
D_OUT = 5   # 窗出場: 次月日曆日>=5後第一個交易日


def read_sql_retry(sql, tries=8, wait=4):
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


def build_windows(px):
    """回傳每月週期的W報酬/C報酬/相對日標記。px=DataFrame(date,close)升冪。"""
    px = px.sort_values("date").reset_index(drop=True)
    d = px.date
    # 每月的W進場日: 該月第一個 day>=25 的交易日; W出場: 下月第一個 day>=5 的交易日
    entries = {}
    exits = {}
    for i, dt in enumerate(d):
        ym = (dt.year, dt.month)
        if dt.day >= D_IN and ym not in entries:
            entries[ym] = i
        if dt.day >= D_OUT and ym not in exits:
            exits[ym] = i
    rows = []
    yms = sorted(entries)
    for y, m in yms:
        ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
        if (ny, nm) not in exits or (ny, nm) not in entries:
            continue
        i_in = entries[(y, m)]
        i_out = exits[(ny, nm)]
        i_next_in = entries.get((ny, nm))
        if i_out <= i_in or i_next_in is None or i_next_in < i_out:
            continue
        c = px.close.values
        w = (c[i_out] / c[i_in] - 1) * 100
        comp = (c[i_next_in] / c[i_out] - 1) * 100  # 出場->下次進場=互補窗
        rows.append({"y": y, "m": m, "w": w, "c": comp,
                     "w_td": i_out - i_in, "c_td": i_next_in - i_out})
    return pd.DataFrame(rows)


def loto_boot_mean(df, col, label, b=B_BOOT, seed=SEED):
    years = sorted(df.y.unique())
    rows = []
    for yr in years:
        s2 = df[df.y != yr]
        if len(s2) >= 24:
            rows.append((yr, s2[col].mean()))
    rows.sort(key=lambda r: r[1])
    pos = sum(1 for _, v in rows if v > 0)
    print(f"      {label} LOTO最壞: 剔{rows[0][0]}後均值{rows[0][1]:+.2f}%, 為正{pos}/{len(rows)}年")
    rng = np.random.default_rng(seed)
    groups = {yr: df.loc[df.y == yr, col].values for yr in years}
    means = []
    for _ in range(b):
        pick = rng.choice(years, size=len(years), replace=True)
        arr = np.concatenate([groups[yr] for yr in pick])
        means.append(arr.mean())
    means = np.array(means)
    lo, hi = np.percentile(means, [2.5, 97.5])
    print(f"      {label} bootstrap: 均值CI95=[{lo:+.2f},{hi:+.2f}]% P(<=0)={(means <= 0).mean():.4f}")
    return lo, hi


def rel_day_curve(px, label):
    """月底倒數5日/月初前7日的逐日平均報酬(%)。"""
    px = px.sort_values("date").reset_index(drop=True)
    px["ret"] = px.close.pct_change() * 100
    ym = px.date.dt.to_period("M")
    px["td_in_m"] = px.groupby(ym).cumcount() + 1          # 月內第幾個交易日
    px["td_from_end"] = px.groupby(ym)["td_in_m"].transform("max") - px.td_in_m  # 0=月末日
    parts = []
    for k in range(4, -1, -1):
        r = px[px.td_from_end == k].ret.dropna()
        parts.append(f"末-{k}:{r.mean():+.3f}")
    for k in range(1, 8):
        r = px[px.td_in_m == k].ret.dropna()
        parts.append(f"初+{k}:{r.mean():+.3f}")
    mid = px[(px.td_from_end > 4) & (px.td_in_m > 7)].ret.dropna()
    print(f"    {label} 逐日均報酬%: " + " ".join(parts) + f" | 月中其餘:{mid.mean():+.3f}(基準)")


def main():
    idx = read_sql_retry("SELECT market, date, close FROM index_daily ORDER BY market, date")
    idx["date"] = pd.to_datetime(idx.date)
    for mkt in ["TAIEX", "TPEx", "SPX", "N225", "KOSPI"]:
        px = idx[idx.market == mkt][["date", "close"]]
        if len(px) < 500:
            continue
        wf = build_windows(px)
        main_mkt = mkt in ("TAIEX", "TPEx")
        print("\n" + "#" * 72)
        print(f"## {mkt} ({px.date.min().date()}~{px.date.max().date()}, 週期n={len(wf)}) "
              f"{'[主測]' if main_mkt else '[跨市場機制對照]'}")
        print("#" * 72)
        wpd = wf.w / wf.w_td
        cpd = wf.c / wf.c_td
        print(f"  W窗(25日→次月5日,~{wf.w_td.median():.0f}交易日): 均值{wf.w.mean():+.2f}%/窗 "
              f"中位{wf.w.median():+.2f}% 勝率{(wf.w > 0).mean() * 100:.0f}% 每交易日{wpd.mean():+.3f}%")
        print(f"  C窗(其餘,~{wf.c_td.median():.0f}交易日):        均值{wf.c.mean():+.2f}%/窗 "
              f"中位{wf.c.median():+.2f}% 勝率{(wf.c > 0).mean() * 100:.0f}% 每交易日{cpd.mean():+.3f}%")
        wf["diff"] = wf.w - wf.c
        wf["diff_pd"] = wpd - cpd
        print(f"  配對差(W-C): 均值{wf['diff'].mean():+.2f}%/週期 每交易日口徑{wf['diff_pd'].mean():+.3f}%")
        if main_mkt:
            loto_boot_mean(wf, "w", "W窗絕對")
            loto_boot_mean(wf, "diff", "W-C配對差")
            loto_boot_mean(wf, "diff_pd", "W-C(每日口徑)")
            half = wf.y.median()
            for tag, sub in (("前半", wf[wf.y <= half]), ("後半", wf[wf.y > half])):
                print(f"    {tag}({sub.y.min()}-{sub.y.max()}): W均{sub.w.mean():+.2f}% "
                      f"C均{sub.c.mean():+.2f}% 差{sub['diff'].mean():+.2f}% W勝率{(sub.w > 0).mean() * 100:.0f}%")
            # 月份交互(12月最強已知,W窗是否只是搭12月便車)
            wf["strong_month"] = wf.m.isin([11, 12, 0])
            ex12 = wf[wf.m != 12]
            print(f"    剔除12月進場週期後: W均{ex12.w.mean():+.2f}% 差{ex12['diff'].mean():+.2f}% "
                  f"(不變=非12月便車)")
        rel_day_curve(px, mkt)


if __name__ == "__main__":
    main()
