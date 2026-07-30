# -*- coding: utf-8 -*-
"""注意股票事件研究(2026-07-20開題:處置前「注意」階段有沒有錢賺,三線合一之第二步)

機制先驗(與處置V4刻意不同,不可直接套用同一套「凍結→回流」故事):
處置=強制分盤(5/20分鐘)+預收款券=結構性流動性障礙,非資訊性賣壓才有反彈可言;
注意股票**無分盤無預收**,只是揭露(漲跌/量/週轉/借券等13款觸發資訊),市場照常交易——
本研究是開放式問題:注意到底是「動能延續的確認」還是「過熱的反轉警訊」,不預設答案。

設計(預註冊):
- 事件源: attention表(2019-01~2026-07,46,865筆/1,875檔),對到fm_daily_price有價格者
- episode化: 同代碼前後兩筆注意相隔<=10個交易日視為同一波「連續注意」,只取每波第一筆
  當主事件(避免同一波內逐日觸發造成前瞻窗重疊),cum_count(官方終身累計次數)另外分層報告
- 方向分類: reason原文含「跌幅」→跌觸發、含「漲幅」→漲觸發,兩者皆無(量/週轉率/借券/價差等)→中性觸發
- 報酬窗: pre5/10/20(注意前動能) + fwd1/3/5/10/20(收盤對收盤,原始形狀)
  可交易版=次日開盤買(公告多為盤後,當日收盤不可交易)→T+h收盤賣,扣0.3%成本,附大盤超額(TAIEX/TPEx)
- 升級路徑: 該episode事件後10/20/60個交易日內,同代碼是否出現在disposition表(start_date在窗內)
  → 注意→處置轉換率;反向補做「處置事件回溯,窗前是否曾被注意」→既有V4策略的領先指標價值
用法: python build_attention_event.py
"""
import re
import sqlite3

import numpy as np
import pandas as pd

COST = 0.30


def stat(x, lab):
    x = pd.Series(x).dropna()
    if len(x) < 15:
        print(f"  {lab}: n={len(x)}太少")
        return
    print(f"  {lab}: 中位{x.median():+6.2f}% 均值{x.mean():+6.2f}% 勝率{(x > 0).mean() * 100:3.0f}% n={len(x):,}")


def classify_dir(reason):
    has_down = "跌幅" in reason
    has_up = "漲幅" in reason
    if has_down and not has_up:
        return "跌觸發"
    if has_up and not has_down:
        return "漲觸發"
    if has_up and has_down:
        return "漲跌皆有"
    return "中性(量/週轉/借券)"


def main():
    conn = sqlite3.connect("capital_flow.db")
    att = pd.read_sql("SELECT * FROM attention", conn)
    px = pd.read_sql("SELECT code, date, open, close FROM fm_daily_price ORDER BY code, date", conn)
    disp = pd.read_sql("SELECT code, start_date FROM disposition", conn)
    idx = pd.read_sql("SELECT market, date, close FROM index_daily WHERE market IN ('TAIEX','TPEx')", conn)
    conn.close()

    px["date"] = pd.to_datetime(px.date)
    att["announce_date"] = pd.to_datetime(att.announce_date)
    disp["start_date"] = pd.to_datetime(disp.start_date)
    idx["date"] = pd.to_datetime(idx.date)

    stocks = {c: g.sort_values("date").reset_index(drop=True) for c, g in px.groupby("code")}
    idx_map = {m: g.sort_values("date").set_index("date").close for m, g in idx.groupby("market")}
    disp_by_code = {c: sorted(g.start_date.tolist()) for c, g in disp.groupby("code")}

    att = att.sort_values(["code", "announce_date"]).reset_index(drop=True)
    att["direction"] = att.reason.map(classify_dir)

    rows = []
    for code, grp in att.groupby("code"):
        g = stocks.get(code)
        if g is None:
            continue
        dts = g.date.values
        idx_mkt = idx_map.get("TAIEX" if grp.market.iloc[0] == "上市" else "TPEx")
        prev_i = None
        for _, e in grp.iterrows():
            ia = np.searchsorted(dts, np.datetime64(e.announce_date))
            if ia >= len(g) or dts[ia] != np.datetime64(e.announce_date):
                continue  # 注意日非交易日快照對不到價格(理論上不該發生,防呆)
            episode_first = prev_i is None or (ia - prev_i) > 10
            prev_i = ia

            c_, o_ = g.close.values, g.open.values

            def ok(i):
                return 0 <= i < len(g) and c_[i] > 0

            def ret(i, j, entry_open=False, exit_open=False):
                if not (ok(i) and ok(j)):
                    return np.nan
                p0 = o_[i] if entry_open else c_[i]
                p1 = o_[j] if exit_open else c_[j]
                if p0 <= 0 or p1 <= 0:
                    return np.nan
                return (p1 / p0 - 1) * 100

            def idx_ret(i, j):
                if idx_mkt is None:
                    return np.nan
                d0, d1 = dts[i] if ok(i) else None, dts[j] if ok(j) else None
                if d0 is None or d1 is None:
                    return np.nan
                try:
                    p0, p1 = idx_mkt.loc[d0], idx_mkt.loc[d1]
                except KeyError:
                    return np.nan
                return (p1 / p0 - 1) * 100

            # 升級路徑: 注意日後N個交易日內,同碼是否出現處置start_date
            future_disp = [d for d in disp_by_code.get(code, []) if d > e.announce_date]
            days_to_disp = None
            if future_disp:
                nd = future_disp[0]
                j = np.searchsorted(dts, np.datetime64(nd))
                if 0 <= j < len(g):
                    days_to_disp = j - ia

            r = {
                "code": code, "market": e.market, "y": e.announce_date.year,
                "cum_count": e.cum_count, "direction": e.direction, "triggers": e.triggers,
                "episode_first": episode_first,
                "pre5": ret(ia - 5, ia) if ia >= 5 else np.nan,
                "pre10": ret(ia - 10, ia) if ia >= 10 else np.nan,
                "pre20": ret(ia - 20, ia) if ia >= 20 else np.nan,
                "fwd1": ret(ia, ia + 1), "fwd3": ret(ia, ia + 3), "fwd5": ret(ia, ia + 5),
                "fwd10": ret(ia, ia + 10), "fwd20": ret(ia, ia + 20),
                "trade5": (ret(ia + 1, ia + 5, entry_open=True) - COST) if ok(ia + 1) else np.nan,
                "trade10": (ret(ia + 1, ia + 10, entry_open=True) - COST) if ok(ia + 1) else np.nan,
                "xs_trade10": ((ret(ia + 1, ia + 10, entry_open=True) - COST)
                               - idx_ret(ia + 1, ia + 10)) if ok(ia + 1) else np.nan,
                "days_to_disp": days_to_disp,
            }
            rows.append(r)

    df = pd.DataFrame(rows)
    print(f"注意事件對到價格: {len(df):,}/{len(att):,}筆原始注意公告 ({df.code.nunique()}檔), "
          f"{df.y.min()}~{df.y.max()}")
    ep = df[df.episode_first]
    print(f"episode化(去除10交易日內連續觸發)後主事件數: {len(ep):,}筆 "
          f"(平均每波連鎖 {len(df) / max(len(ep), 1):.1f} 筆公告)")

    print("\n== 注意前動能(是追高還是抄底被注意?) ==")
    stat(ep.pre5, "pre5 ")
    stat(ep.pre10, "pre10")
    stat(ep.pre20, "pre20")

    print("\n== 原始形狀(收盤對收盤,含公告當日) ==")
    stat(ep.fwd1, "fwd1 ")
    stat(ep.fwd3, "fwd3 ")
    stat(ep.fwd5, "fwd5 ")
    stat(ep.fwd10, "fwd10")
    stat(ep.fwd20, "fwd20")

    print("\n== 可交易版(次日開盤買,扣成本0.3%) ==")
    stat(ep.trade5, "trade5  次日開→T+5收")
    stat(ep.trade10, "trade10 次日開→T+10收")
    stat(ep.xs_trade10, "xs_trade10 扣大盤超額")

    print("\n== 方向分層(fwd10,原始) ==")
    for d, g in ep.groupby("direction"):
        stat(g.fwd10, f"{d:12s}")

    print("\n== 首波vs連鎖層級分層(trade10) ==")
    stat(df[df.episode_first].trade10, "episode第一筆")
    stat(df[~df.episode_first].trade10, "episode內後續筆(連續觸發)")
    stat(ep[ep.cum_count == 1].trade10, "官方終身第1次")
    stat(ep[ep.cum_count >= 4].trade10, "官方終身第4次+(慣犯)")

    print("\n== 逐年(trade10) ==")
    for y, g in ep.groupby("y"):
        stat(g.trade10, str(y))

    print("\n== 升級路徑:注意→處置 ==")
    for n, lab in [(10, "10個交易日內"), (20, "20個交易日內"), (60, "60個交易日內")]:
        hit = ep.days_to_disp.notna() & (ep.days_to_disp <= n) & (ep.days_to_disp >= 0)
        print(f"  注意後{lab}升級為處置: {hit.mean() * 100:.1f}% ({hit.sum():,}/{len(ep):,})")

    df.to_pickle("tmp_attention_event_panel.pkl")
    print("\n面板存 tmp_attention_event_panel.pkl (含episode_first旗標與cum_count/direction/triggers分層欄位)")


if __name__ == "__main__":
    main()
