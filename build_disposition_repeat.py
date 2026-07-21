# -*- coding: utf-8 -*-
"""處置慣犯研究(使用者2026-07-21提案):半年內處置>=3次(超過2次)算慣犯,
研究①慣犯名單②常觸發哪一款(1-13,attention表triggers)③走法跟非慣犯有沒有差
機制先驗: 慣犯=市場已經認得的常客,可能導致「狼來了」效應(反應遞減)或反過來
         (規則固定+散戶認賠速度快=更乾淨的非資訊性賣壓,反應更強)——開放式問題不預設方向。

設計(預註冊):
- 事件級repeat旗標: 對每一筆處置事件,用start_date算「trailing 180日內同代碼處置次數(含自己)」,
  >=3視為該筆事件正處於一段慣犯連續期(event_repeat=True);<3為孤立/初犯事件
- 代碼級慣犯名單: 該代碼歷史上只要曾經有任一筆事件trailing>=3,整支股票列入慣犯名單(供排行榜用)
- 觸發款別: 借用attention表(fetch_attention.py解析的triggers 1-13欄),抓每筆處置announce_date
  前30個交易日內同代碼的attention紀錄,合併其triggers做款別tally(對到不代表因果只是關聯)
- 走法: 沿用build_disposition_event.py的SEG_A~D(公布→首日/首日→第3日/第3日→末日/末日→出關+2)
  與v1-v3可交易變體(尾盤買,扣0.45%成本),repeat vs 非repeat分層比較
用法: python build_disposition_repeat.py
"""
import sqlite3

import numpy as np
import pandas as pd

COST = 0.45
WINDOW_DAYS = 180
REPEAT_MIN = 3


def stat(x, lab):
    x = pd.Series(x).dropna()
    if len(x) < 15:
        print(f"  {lab}: n={len(x)}太少")
        return None
    print(f"  {lab}: 中位{x.median():+6.2f}% 均值{x.mean():+6.2f}% 勝率{(x > 0).mean() * 100:3.0f}% n={len(x):,}")
    return x


def main():
    conn = sqlite3.connect("capital_flow.db")
    disp = pd.read_sql("SELECT * FROM disposition", conn)
    px = pd.read_sql("SELECT code, date, open, close FROM fm_daily_price ORDER BY code, date", conn)
    att = pd.read_sql("SELECT code, announce_date, triggers FROM attention WHERE triggers != ''", conn)
    conn.close()

    for c in ("announce_date", "start_date", "end_date"):
        disp[c] = pd.to_datetime(disp[c], errors="coerce")
    disp = disp.dropna(subset=["start_date", "end_date"]).sort_values(["code", "start_date"]).reset_index(drop=True)
    px["date"] = pd.to_datetime(px.date)
    att["announce_date"] = pd.to_datetime(att.announce_date)

    # ---- 事件級 trailing 180日repeat計數 ----
    trailing = np.zeros(len(disp), dtype=int)
    for code, idx in disp.groupby("code").groups.items():
        idx = list(idx)
        dates = disp.loc[idx, "start_date"].values
        for k, i in enumerate(idx):
            lo = dates[k] - np.timedelta64(WINDOW_DAYS, "D")
            trailing[i] = int(((dates >= lo) & (dates <= dates[k])).sum())
    disp["trailing_cnt"] = trailing
    disp["event_repeat"] = disp.trailing_cnt >= REPEAT_MIN

    repeat_codes = sorted(disp.loc[disp.event_repeat, "code"].unique())
    print(f"處置事件總數 {len(disp):,} / {disp.code.nunique()}檔")
    print(f"半年內達{REPEAT_MIN}次+的「慣犯」代碼數: {len(repeat_codes)} "
          f"({len(repeat_codes) / disp.code.nunique() * 100:.1f}% 的處置股)")
    print(f"慣犯代碼貢獻的處置事件數: {disp.code.isin(repeat_codes).sum():,} "
          f"({disp.code.isin(repeat_codes).sum() / len(disp) * 100:.1f}% 佔全部事件)")

    print("\n== 慣犯排行榜(依終身處置次數,前20) ==")
    rank = (disp[disp.code.isin(repeat_codes)]
            .groupby("code")
            .agg(market=("market", "first"), n_total=("code", "size"),
                 n_repeat_window=("event_repeat", "sum"),
                 first_=("start_date", "min"), last_=("start_date", "max"))
            .sort_values("n_total", ascending=False))
    for code, r in rank.head(20).iterrows():
        print(f"  {code} {r.market}: 終身{r.n_total}次(半年窗內達標{r.n_repeat_window}次) "
              f"{r.first_.date()}~{r.last_.date()}")

    # ---- 觸發款別: 每筆處置announce_date前30個交易日內同代碼attention triggers ----
    att = att.sort_values(["code", "announce_date"])
    att_by_code = {c: g.sort_values("announce_date") for c, g in att.groupby("code")}

    def clause_tally(sub_disp):
        from collections import Counter
        cnt = Counter()
        hit_events = 0
        for _, e in sub_disp.iterrows():
            g = att_by_code.get(e.code)
            if g is None:
                continue
            win = g[(g.announce_date <= e.announce_date) &
                    (g.announce_date >= e.announce_date - pd.Timedelta(days=45))]
            if len(win) == 0:
                continue
            hit_events += 1
            clauses = set()
            for trg in win.triggers:
                clauses.update(trg.split(","))
            for c in clauses:
                cnt[c] += 1
        return cnt, hit_events

    print("\n== 觸發款別關聯(公布日前45天內同代碼attention triggers,款別可複選) ==")
    rep_events = disp[disp.event_repeat]
    non_events = disp[~disp.event_repeat]
    cnt_rep, hit_rep = clause_tally(rep_events)
    cnt_non, hit_non = clause_tally(non_events)
    print(f"慣犯窗內事件(n={len(rep_events)}, 對到attention {hit_rep}筆): {dict(sorted(cnt_rep.items(), key=lambda x: -x[1]))}")
    print(f"非慣犯事件  (n={len(non_events)}, 對到attention {hit_non}筆): {dict(sorted(cnt_non.items(), key=lambda x: -x[1]))}")
    if hit_rep:
        print("慣犯款別佔比: " + ", ".join(f"款{k}={v / hit_rep * 100:.0f}%" for k, v in sorted(cnt_rep.items(), key=lambda x: -x[1])))
    if hit_non:
        print("非慣犯款別佔比: " + ", ".join(f"款{k}={v / hit_non * 100:.0f}%" for k, v in sorted(cnt_non.items(), key=lambda x: -x[1])))

    # ---- 走法(SEG_A-D + v1-v3),沿用build_disposition_event.py邏輯 ----
    stocks = {c: g.sort_values("date").reset_index(drop=True) for c, g in px.groupby("code")}
    rows = []
    for _, e in disp.iterrows():
        g = stocks.get(e.code)
        if g is None:
            continue
        dts = g.date
        s_arr = np.searchsorted(dts.values, np.datetime64(e.start_date))
        e_arr = np.searchsorted(dts.values, np.datetime64(e.end_date), side="right") - 1
        if s_arr >= len(g) or e_arr < 0 or e_arr <= s_arr or e_arr - s_arr > 25:
            continue
        a_arr = s_arr - 1
        c_, o_ = g.close.values, g.open.values
        n = len(g)

        def px_ok(i):
            return 0 <= i < n and c_[i] > 0

        def seg(i, j, open_exit=False):
            if not (px_ok(i) and 0 <= j < n):
                return np.nan
            p1 = o_[j] if open_exit else c_[j]
            if p1 <= 0:
                return np.nan
            return (p1 / c_[i] - 1) * 100

        rows.append({
            "code": e.code, "market": e.market, "y": e.start_date.year,
            "event_repeat": e.event_repeat, "trailing_cnt": e.trailing_cnt, "match_min": e.match_min,
            "segA": seg(a_arr, s_arr), "segB": seg(s_arr, min(s_arr + 2, e_arr)),
            "segC": seg(min(s_arr + 2, e_arr), e_arr), "segD": seg(e_arr, e_arr + 2, open_exit=True),
            "v1": seg(s_arr, s_arr + 2, open_exit=True) - COST,
            "v2": seg(s_arr + 4, s_arr + 6, open_exit=True) - COST if s_arr + 4 <= e_arr else np.nan,
            "v3": seg(e_arr, e_arr + 2, open_exit=True) - COST,
        })
    df = pd.DataFrame(rows)
    df.to_pickle("tmp_disposition_repeat_panel.pkl")
    print(f"\n對到價格的處置事件: {len(df):,} (面板存tmp_disposition_repeat_panel.pkl)")

    print("\n== 走法:慣犯窗內事件 vs 非慣犯事件 ==")
    rep = df[df.event_repeat]
    non = df[~df.event_repeat]
    for seg_name, lab in [("segA", "SEG_A 公布→處置首日"), ("segB", "SEG_B 首日→第3日"),
                           ("segC", "SEG_C 第3日→末日"), ("segD", "SEG_D 末日→出關+2開")]:
        print(f" {lab}")
        stat(rep[seg_name], "  慣犯窗內")
        stat(non[seg_name], "  非慣犯  ")

    print("\n== 可交易變體v1-v3 ==")
    for v, lab in [("v1", "V1 首日尾盤買→+2開"), ("v2", "V2 第5處置日尾盤買→+2開"), ("v3", "V3 末日尾盤買→出關+2開")]:
        print(f" {lab}")
        stat(rep[v], "  慣犯窗內")
        stat(non[v], "  非慣犯  ")

    print("\n== 分盤級別交叉(慣犯是否更容易踩到20分盤) ==")
    print("慣犯窗內事件分盤分布:\n" + rep.match_min.value_counts(normalize=True).mul(100).round(1).to_string())
    print("非慣犯事件分盤分布:\n" + non.match_min.value_counts(normalize=True).mul(100).round(1).to_string())

    print("\n== 逐年v3(出關行情,慣犯窗內) ==")
    for y, g in rep.groupby("y"):
        stat(g.v3, str(y))


if __name__ == "__main__":
    main()
