# -*- coding: utf-8 -*-
"""台股漲跌停判定器(讀fm_daily_price未調整價) -> tmp_limit_flags.pkl
規則(TWSE營業細則第62條,櫃買同制,已對官方範例驗證:基準40.60→漲停44.65):
  漲停價 = 前收(開盤競價基準)×1.10 向下對齊升降單位;跌停×0.90向上對齊
  升降單位六級距: <10:0.01 / 10-50:0.05 / 50-100:0.1 / 100-500:0.5 / 500-1000:1 / >=1000:5
旗標: lu_close=收盤鎖漲停 lu_touch=盤中觸及但收盤未鎖 lu_lock=一價鎖死(開=低=收=漲停)
      ld_close/ld_touch=跌停對應
防呆: ①除權息日開盤競價基準=參考價非前收→本判定會漏判(偏保守,之後可補FinMind除權息表精確化)
      ②新上市首5日無漲跌幅→該股在庫首日>2019-01-15者剔除前5個交易日
      ③浮點誤差用tick/2容忍
用法: python limit_up_detect.py   (可重跑,fm_daily_price增量後重新產生)
"""
import sqlite3

import numpy as np
import pandas as pd

TICKS = [(10, 0.01), (50, 0.05), (100, 0.1), (500, 0.5), (1000, 1.0), (np.inf, 5.0)]


def tick_of(p):
    for ub, t in TICKS:
        if p < ub:
            return t
    return 5.0


def limit_prices(prev_close):
    """回傳(漲停價, 跌停價);對齊方向=往內縮(官方例40.60→44.65/36.55)"""
    up_raw, dn_raw = prev_close * 1.10, prev_close * 0.90
    tu, td = tick_of(up_raw), tick_of(dn_raw)
    up = np.floor(up_raw / tu + 1e-9) * tu
    dn = np.ceil(dn_raw / td - 1e-9) * td
    return round(up, 2), round(dn, 2)


def main():
    conn = sqlite3.connect("capital_flow.db")
    px = pd.read_sql("SELECT code, date, open, high, low, close FROM fm_daily_price "
                     "ORDER BY code, date", conn)
    conn.close()
    px["date"] = pd.to_datetime(px.date)
    out = []
    t0 = pd.Timestamp("2019-01-15")
    for code, g in px.groupby("code", sort=False):
        g = g.sort_values("date").reset_index(drop=True)
        prev = g.close.shift(1)
        lim = prev.map(lambda p: limit_prices(p) if pd.notna(p) else (np.nan, np.nan))
        up = lim.str[0].values
        dn = lim.str[1].values
        tol = np.array([tick_of(p) / 2 if pd.notna(p) else np.nan for p in up])
        at_up_close = np.abs(g.close.values - up) < tol
        at_up_high = np.abs(g.high.values - up) < tol
        at_dn_close = np.abs(g.close.values - dn) < tol
        at_dn_low = np.abs(g.low.values - dn) < tol
        f = pd.DataFrame({
            "code": code, "date": g.date,
            "lu_close": at_up_close,
            "lu_touch": at_up_high & ~at_up_close,
            "lu_lock": at_up_close & (np.abs(g.open.values - up) < tol) & (np.abs(g.low.values - up) < tol),
            "ld_close": at_dn_close,
            "ld_touch": at_dn_low & ~at_dn_close,
            "ret": (g.close / prev - 1) * 100,
        })
        f.iloc[0, 2:7] = False  # 首日無前收
        if g.date.iloc[0] > t0:  # 新上市:首5日無漲跌幅
            f.iloc[:5, 2:7] = False
        out.append(f)
    flags = pd.concat(out, ignore_index=True)
    flags.to_pickle("tmp_limit_flags.pkl")
    n = flags[["lu_close", "lu_touch", "lu_lock", "ld_close", "ld_touch"]].sum()
    print(f"股-日 {len(flags):,} 筆 / {flags.code.nunique()} 檔 "
          f"({flags.date.min():%Y-%m-%d}~{flags.date.max():%Y-%m-%d})")
    print(f"收盤鎖漲停 {n.lu_close:,} (其中一價鎖死 {n.lu_lock:,}) | 觸及打開 {n.lu_touch:,} "
          f"| 收盤跌停 {n.ld_close:,} | 觸跌停打開 {n.ld_touch:,}")
    # sanity: 收盤鎖漲停的報酬應集中在+9.5%~+10%
    r = flags.loc[flags.lu_close, "ret"]
    print(f"鎖漲停報酬分布: min={r.min():.2f}% p5={r.quantile(.05):.2f}% "
          f"中位={r.median():.2f}% max={r.max():.2f}%")
    bad = flags[flags.lu_close & (flags.ret < 8.5)]
    print(f"報酬<8.5%的可疑鎖漲停(除權息誤判候選): {len(bad)}筆")


if __name__ == "__main__":
    main()
