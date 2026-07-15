# -*- coding: utf-8 -*-
"""CB磁吸考卷(H-CB1/H-CB3,2026-07-15與使用者定稿設計,130%強贖條款博弈)
機制: 發行公司最優路徑=拉過轉換價→推上130%→撐30日→強贖逼轉換=不還本金。
預測: 股價在轉換價110-130%×未轉換餘額大=「最後一哩」動機最強→前瞻偏多;
      餘額已轉光=戲演完→無效果;深價外(<90%)=賣回壓力窗另計。

設計(預註冊):
- 面板: cb_overview月末快照(2019-01~2026-06),cb→標的=cb_id前4碼,一股多CB取餘額最大
- 狀態: ratio=標的價/轉換價 四桶(<0.9深價外/0.9-1.1攻防/1.1-1.3磁吸/>=1.3達標)
        × out=未轉換餘額比例(>50% vs <=50%)
- 前瞻: 快照日→+21交易日收盤,扣同期TWII
- 判準: 磁吸×高餘額顯著>其他格且劑量順機制 → 候選;全格平=CB結構無альфа
用法: python build_cb_magnet.py
"""
import sqlite3

import numpy as np
import pandas as pd


def stat(x, lab):
    x = pd.Series(x).dropna()
    if len(x) < 15:
        print(f"  {lab}: n={len(x)}太少")
        return
    print(f"  {lab}: 超額中位{x.median():+6.2f}% 勝率{(x > 0).mean() * 100:3.0f}% n={len(x):,}")


def main():
    conn = sqlite3.connect("capital_flow.db")
    ov = pd.read_sql("SELECT cb_id, date, conv_price, outstanding, issuance, stock_price "
                     "FROM cb_overview", conn)
    px = pd.read_sql("SELECT code, date, close FROM fm_daily_price ORDER BY code, date", conn)
    conn.close()
    ov["date"] = pd.to_datetime(ov.date)
    px["date"] = pd.to_datetime(px.date)
    closes = {c: g.set_index("date").close for c, g in px.groupby("code")}
    twii = pd.read_pickle("tmp_twii_long.pkl").dropna()

    ov = ov[(ov.conv_price > 0) & (ov.stock_price > 0) & (ov.issuance > 0) & ov.outstanding.notna()]
    ov["code"] = ov.cb_id.str[:4]
    ov["m"] = ov.date.dt.to_period("M")
    # 月末快照,一股多CB取餘額最大
    snap = ov.sort_values("date").groupby(["cb_id", "m"]).tail(1)
    snap = snap.sort_values("outstanding").groupby(["code", "m"]).tail(1)
    snap["ratio"] = snap.stock_price / snap.conv_price
    snap["out_r"] = snap.outstanding / snap.issuance

    rows = []
    for r in snap.itertuples():
        s = closes.get(r.code)
        if s is None:
            continue
        seg = s[s.index >= r.date]
        if len(seg) < 22 or seg.iloc[0] <= 0:
            continue
        fwd = (seg.iloc[21] / seg.iloc[0] - 1) * 100
        tw = (twii.asof(seg.index[21]) / twii.asof(seg.index[0]) - 1) * 100
        rows.append({"code": r.code, "m": str(r.m), "y": r.date.year,
                     "ratio": r.ratio, "out_r": r.out_r, "ex": fwd - tw})
    df = pd.DataFrame(rows)
    df["rb"] = pd.cut(df.ratio, [0, 0.9, 1.1, 1.3, 99],
                      labels=["<0.9深價外", "0.9-1.1攻防", "1.1-1.3磁吸", ">=1.3達標"])
    df["ob"] = np.where(df.out_r > 0.5, "餘額>50%", "餘額<=50%")
    print(f"股-月快照: {len(df):,}筆 / {df.code.nunique()}檔 ({df.m.min()}~{df.m.max()})")

    print("\n== ratio×餘額 網格(+21交易日TWII超額) ==")
    for rb in ["<0.9深價外", "0.9-1.1攻防", "1.1-1.3磁吸", ">=1.3達標"]:
        for ob in ["餘額>50%", "餘額<=50%"]:
            stat(df[(df.rb == rb) & (df.ob == ob)].ex, f"{rb}×{ob}")

    print("\n== 磁吸格(1.1-1.3×餘額>50%)逐年 ==")
    mag = df[(df.rb == "1.1-1.3磁吸") & (df.ob == "餘額>50%")]
    for y, g in mag.groupby("y"):
        stat(g.ex, str(y))

    df.to_pickle("tmp_cb_magnet_panel.pkl")
    print("\n面板存 tmp_cb_magnet_panel.pkl")


if __name__ == "__main__":
    main()
