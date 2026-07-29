# -*- coding: utf-8 -*-
"""二進宮預測考卷(預註冊2026-07-29深夜,§6-8二訂的直接變現,使用者裁示開工)
========================================================================
背景: 同日條文覆核確認「一般自動處置的基數穿越處置期繼續累積」(處置前+處置期間注意照算)
→ 處置中的股票,出關前就能精算「出關瞬間是否已達/逼近二次處置門檻」=全新的事前資訊。
預註冊四題(寫死於開工前,首跑即凍結):
  Q0 預測器驗證: 出關日T_end用「款1-8注意在最近10/30營業日的累積」算距門檻gap=
     min(6-n10, 12-n30);預測組=熱(gap<=1,含已超標)/溫(2-3)/冷(>=4)。
     outcome=出關後7日曆日內再被公告處置。報命中率×混淆矩陣——先驗:熱組再處置率應遠高於冷組,
     否則「基數穿越」的機制理解有誤。
  Q1 報酬主測: 出關+1開盤(=V4規則出場點)起算fwd k5/10/20/60(收盤),熱vs冷配對差,
     LOTO逐年+月群bootstrap(k10/k20)。池=V4口徑(T1-T3∧tv3>=0.3億)為主,全池為穩健。
     先驗兩可(這正是開卷理由): 熱組=妖股動能未斷(漲觸發升級組+7.24%同構)→正?
     還是=再凍結10-12日流動性地獄→負? 無人事前分過。
  Q2 V4續抱決策(可交易化): 若Q1熱組顯著正→V4出場規則該改「熱票續抱10日」;
     量化=出關+1開→+10收的附加報酬,熱vs冷。
  Q3 對照既有G3(純弱勢出關跑贏): 本預測器用「基數熱度」,G3用「窗內價格路徑」——
     交叉表+窗內報酬相關,確認不是G3換皮。
判準: 配對差CI排0∧LOTO>=6/8年→候選;n<15觀察層;死格先驗=2022熊年。
資料: attention(款1-8濾)+disposition+fm_daily_price,計數口徑重用計時器v2(營業日窗)。
用法: python build_dispo_second_jail.py
"""
import sqlite3
import sys
import time

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
DB = "capital_flow.db"
KS = [5, 10, 20, 60]
rng = np.random.default_rng(20260729)


def rd(sql, params=None, tries=6, wait=5):
    for i in range(tries):
        try:
            con = sqlite3.connect(DB, timeout=30)
            df = pd.read_sql(sql, con, params=params)
            con.close()
            return df
        except sqlite3.OperationalError as e:
            if "locked" in str(e) and i < tries - 1:
                time.sleep(wait)
            else:
                raise


def med_win(v):
    v = pd.Series(v).dropna()
    if not len(v):
        return None, None, 0
    return float(v.median()), float((v > 0).mean() * 100), len(v)


def boot_diff(a, b, ym_a, ym_b, n_iter=2000):
    a, b = pd.Series(a).dropna(), pd.Series(b).dropna()
    if len(a) < 15 or len(b) < 15:
        return None
    am = pd.DataFrame({"v": a, "ym": ym_a[a.index]}).groupby("ym").v.apply(list)
    bm = pd.DataFrame({"v": b, "ym": ym_b[b.index]}).groupby("ym").v.apply(list)
    diffs = []
    for _ in range(n_iter):
        av = np.concatenate([am.iloc[i] for i in rng.integers(0, len(am), len(am))])
        bv = np.concatenate([bm.iloc[i] for i in rng.integers(0, len(bm), len(bm))])
        diffs.append(np.median(av) - np.median(bv))
    return (float(a.median() - b.median()),
            float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5)))


def main():
    disp = rd("SELECT code, announce_date, start_date, end_date, reason, match_min "
              "FROM disposition")
    att = rd("SELECT code, announce_date, triggers FROM attention")
    cls = rd("SELECT DISTINCT code FROM classification WHERE country='台'")
    theme_codes = set(cls.code)
    for c in ("announce_date", "start_date", "end_date"):
        disp[c] = pd.to_datetime(disp[c], errors="coerce")
    att["announce_date"] = pd.to_datetime(att.announce_date)
    disp = disp.dropna(subset=["start_date", "end_date"]).sort_values("announce_date")
    disp = disp[disp.code.str.fullmatch(r"\d{4}", na=False)]

    cal_df = rd("SELECT DISTINCT date FROM fm_daily_price ORDER BY date")
    cal = pd.to_datetime(cal_df.date)
    pos = {d: i for i, d in enumerate(cal)}

    codes = sorted(disp.code.unique())
    ph = ",".join("?" * len(codes))
    px = rd(f"SELECT code, date, open, close, money FROM fm_daily_price WHERE code IN ({ph}) "
            f"ORDER BY code, date", codes)
    px["date"] = pd.to_datetime(px.date)
    pmap = {c: g.sort_values("date").reset_index(drop=True) for c, g in px.groupby("code")}

    def c18(t):
        return any(x in {"1", "2", "3", "4", "5", "6", "7", "8"}
                   for x in str(t or "").split(","))

    att18 = att[att.triggers.map(c18)]
    att_by = {c: sorted({pos[d] for d in g.announce_date if d in pos})
              for c, g in att18.groupby("code")}
    disp_by = dict(tuple(disp.groupby("code")))

    # ---- 事件建構: 每筆處置在出關日算基數狀態 ----
    rows = []
    for _, e in disp.iterrows():
        if e.end_date not in pos or "人工管制" in str(e.reason):
            continue
        ei = pos[e.end_date]
        acis = att_by.get(e.code, [])
        n10 = sum(1 for i in acis if ei - 9 <= i <= ei)
        n30 = sum(1 for i in acis if ei - 29 <= i <= ei)
        gap = min(6 - n10, 12 - n30)
        # outcome: 出關後7日曆日內再公告處置
        g_d = disp_by[e.code]
        nxt = g_d[g_d.announce_date > e.end_date]
        renext = (len(nxt) > 0 and
                  (nxt.announce_date.iloc[0] - e.end_date).days <= 7)
        # 報酬: 出關+1開盤起
        g = pmap.get(e.code)
        if g is None:
            continue
        dts = g.date.values
        en = int(np.searchsorted(dts, np.datetime64(e.end_date), side="right") - 1)
        if en < 20 or en + 1 >= len(g) or g.open.iloc[en + 1] <= 0:
            continue
        o1 = g.open.iloc[en + 1]
        fwd = {}
        for k in KS:
            fwd[k] = ((g.close.iloc[en + 1 + k] / o1 - 1) * 100
                      if en + 1 + k < len(g) else np.nan)
        # 窗內報酬(Q3對照G3口徑=處置窗內價格路徑)
        s = int(np.searchsorted(dts, np.datetime64(e.start_date)))
        inwin = ((g.close.iloc[en] / g.close.iloc[s - 1] - 1) * 100
                 if 0 < s <= en and g.close.iloc[s - 1] > 0 else np.nan)
        amt20 = g.money.iloc[max(0, en - 19):en + 1].mean() / 1e8
        mm = str(e.match_min)
        theme = e.code in theme_codes
        tier = 1 if (theme and mm == "20") else (2 if theme else (3 if mm == "20" else 4))
        rows.append({"code": e.code, "end": e.end_date, "y": e.end_date.year,
                     "ym": e.end_date.strftime("%Y-%m"),
                     "n10": n10, "n30": n30, "gap": gap, "renext": bool(renext),
                     "grp": "熱" if gap <= 1 else ("溫" if gap <= 3 else "冷"),
                     "tier": tier, "mins": mm, "amt20": amt20, "inwin": inwin,
                     **{f"f{k}": fwd[k] for k in KS}})
    ev = pd.DataFrame(rows)
    ev = ev[ev.end >= "2019-01-01"].reset_index(drop=True)
    print(f"處置出關事件 n={len(ev)} ({ev.end.min().date()}~{ev.end.max().date()}) | "
          f"組成: 熱{(ev.grp == '熱').sum()} 溫{(ev.grp == '溫').sum()} 冷{(ev.grp == '冷').sum()}")

    # ================= Q0 預測器驗證 =================
    print("\n===== Q0 預測器驗證(出關7日內再處置率) =====")
    for g_, sub in ev.groupby("grp"):
        print(f"  {g_}(gap{'<=1' if g_ == '熱' else '2-3' if g_ == '溫' else '>=4'}): "
              f"n={len(sub)}  再處置率={sub.renext.mean() * 100:.1f}%")
    base = ev.renext.mean() * 100
    print(f"  全體基準率={base:.1f}% (#11 case-control家規:命中率要跟基準率比)")
    # gap逐值梯度
    print("  gap逐值再處置率梯度:")
    for gv in sorted(ev.gap.unique()):
        sub = ev[ev.gap == gv]
        if len(sub) >= 10:
            print(f"    gap={gv:+d}: n={len(sub):4d} 再處置率{sub.renext.mean() * 100:5.1f}%")

    # ================= Q1 報酬主測 =================
    print("\n===== Q1 出關+1開盤起報酬: 熱 vs 冷 =====")
    for pool_lab, pool in (("V4池(T1-T3∧tv3代理amt20>=0.3億)",
                            ev[(ev.tier <= 3) & (ev.amt20 >= 0.3)]),
                           ("全池", ev)):
        print(f"  [{pool_lab}] n={len(pool)}")
        for g_ in ("熱", "溫", "冷"):
            sub = pool[pool.grp == g_]
            cells = "  ".join(
                f"k{k} {med_win(sub[f'f{k}'])[0]:+.2f}%/{med_win(sub[f'f{k}'])[1]:.0f}%"
                for k in KS if med_win(sub[f"f{k}"])[0] is not None)
            print(f"    {g_}(n={len(sub)}): {cells}")
        a, b = pool[pool.grp == "熱"], pool[pool.grp == "冷"]
        for k in (10, 20):
            r = boot_diff(a[f"f{k}"], b[f"f{k}"], a.ym, b.ym)
            if r:
                pos_y = tot_y = 0
                for y in sorted(set(a.y) & set(b.y)):
                    av, bv = a[a.y == y][f"f{k}"].dropna(), b[b.y == y][f"f{k}"].dropna()
                    if len(av) >= 3 and len(bv) >= 3:
                        tot_y += 1
                        pos_y += av.median() > bv.median()
                print(f"    熱−冷 k{k}: {r[0]:+.2f}pp CI[{r[1]:+.2f},{r[2]:+.2f}]"
                      f"{' ✓排0' if r[1] > 0 or r[2] < 0 else ' 含0'} 逐年{pos_y}/{tot_y}正")

    # 控: 分盤內(熱組可能都是準20分盤)
    print("  控·分盤內(V4池):")
    v4p = ev[(ev.tier <= 3) & (ev.amt20 >= 0.3)]
    for mm in ("5", "20"):
        sub = v4p[v4p.mins == mm]
        a, b = sub[sub.grp == "熱"], sub[sub.grp == "冷"]
        m_a = med_win(a.f20)
        m_b = med_win(b.f20)
        if m_a[0] is not None and m_b[0] is not None:
            print(f"    {mm}分盤: 熱k20 {m_a[0]:+.2f}%/{m_a[1]:.0f}%(n={m_a[2]}) vs "
                  f"冷 {m_b[0]:+.2f}%/{m_b[1]:.0f}%(n={m_b[2]}) 差{m_a[0] - m_b[0]:+.2f}pp")

    # ================= Q2 V4續抱決策 =================
    print("\n===== Q2 V4續抱決策(出關+1開→+10收 附加報酬) =====")
    for g_ in ("熱", "冷"):
        sub = v4p[v4p.grp == g_]
        m, w, n = med_win(sub.f10)
        if m is not None:
            print(f"  {g_}組續抱10日: {m:+.2f}%/{w:.0f}%(n={n})")

    # ================= Q3 對照G3(窗內路徑) =================
    print("\n===== Q3 與G3(窗內價格路徑)的正交性 =====")
    ok = ev.dropna(subset=["inwin"])
    print(f"  窗內報酬 中位: 熱{ok[ok.grp == '熱'].inwin.median():+.2f}% / "
          f"冷{ok[ok.grp == '冷'].inwin.median():+.2f}%")
    for g_ in ("熱", "冷"):
        sub = ok[ok.grp == g_]
        weak = sub[sub.inwin < 0]
        strong = sub[sub.inwin >= 0]
        mw, ww, nw = med_win(weak.f20)
        ms, ws, ns = med_win(strong.f20)
        if mw is not None and ms is not None:
            print(f"  {g_}×窗內弱勢: k20 {mw:+.2f}%/{ww:.0f}%(n={nw}) | "
                  f"{g_}×窗內強勢: {ms:+.2f}%/{ws:.0f}%(n={ns})")
    r_corr = ok[["gap", "inwin"]].corr(method="spearman").iloc[0, 1]
    print(f"  Spearman(gap, 窗內報酬) = {r_corr:+.3f} (|值|小=與G3正交=真新維度)")

    # 逐年明細(死格檢查)
    print("\n===== 逐年(V4池 熱組k20) =====")
    for y, sub in v4p[v4p.grp == "熱"].groupby("y"):
        m, w, n = med_win(sub.f20)
        if m is not None:
            print(f"  {y}: {m:+.2f}%/{w:.0f}%(n={n})")


if __name__ == "__main__":
    main()
