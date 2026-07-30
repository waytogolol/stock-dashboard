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

    # ================= 報告(2026-07-29使用者要求:權益曲線+績效數據) =================
    import json
    GREEN, RED, BLUE, YELLOW, GRAY = "#7ec97e", "#e06c5a", "#6bb7e3", "#c3a55a", "#8a8878"
    BG = {"paper_bgcolor": "#1a1a19", "plot_bgcolor": "#22221f",
          "font": {"color": "#ddd", "size": 12},
          "margin": {"t": 42, "l": 52, "r": 18, "b": 40}, "legend": {"orientation": "h"}}

    def cum_curve(sub, k):
        """單利累加曲線(逐事件k日淨報酬pp,依出關日排序)+績效dict。"""
        s = sub.dropna(subset=[f"f{k}"]).sort_values("end")
        rets = s[f"f{k}"].values
        cum = np.cumsum(rets)
        dd = float((cum - np.maximum.accumulate(cum)).min()) if len(cum) else 0.0
        st = {"n": len(s), "win": float((rets > 0).mean() * 100) if len(s) else None,
              "avg": float(np.mean(rets)) if len(s) else None,
              "med": float(np.median(rets)) if len(s) else None,
              "sum": float(cum[-1]) if len(s) else 0.0, "mdd": dd,
              "pf": (-rets[rets > 0].sum() / rets[rets <= 0].sum()
                     if len(s) and (rets <= 0).any() else None)}
        return [str(d.date()) for d in s.end], [round(float(v), 1) for v in cum], st

    charts = []
    HOLD_K = 10
    tr = {}
    for g_, color in (("熱", RED), ("溫", YELLOW), ("冷", BLUE)):
        xs, ys, st = cum_curve(v4p[v4p.grp == g_], HOLD_K)
        tr[g_] = st
        charts.append({"x": xs, "y": ys, "name": f"{g_}組(Σ{st['sum']:+.0f}pp,MDD{st['mdd']:.0f}pp)",
                       "mode": "lines", "line": {"color": color, "width": 2},
                       "hovertemplate": "%{x}: %{y}pp<extra>" + g_ + "</extra>"})
    c_eq = ("c_eq", charts,
            {"title": f"權益曲線(V4池,出關+1開盤買持{HOLD_K}日,單利累加pp;讀形狀別讀絕對值)",
             "yaxis": {"title": "累計pp"}})
    grad_rows = []
    for gv in sorted(ev.gap.unique()):
        sub = ev[ev.gap == gv]
        if len(sub) >= 10:
            grad_rows.append((int(gv), len(sub), sub.renext.mean() * 100))
    c_grad = ("c_grad", [{
        "x": [f"gap{g:+d}" for g, _, _ in grad_rows],
        "y": [round(r, 1) for _, _, r in grad_rows], "type": "bar",
        "marker": {"color": [RED if r >= 15 else YELLOW if r >= 8 else GREEN
                             for _, _, r in grad_rows]},
        "text": [f"n={n}" for _, n, _ in grad_rows], "textposition": "outside",
        "hovertemplate": "%{x}: %{y}%<extra></extra>"}],
        {"title": "Q0預測器:出關日基數距門檻gap → 7日內再處置率(%),紅線=全體基準率8.2%",
         "yaxis": {"title": "再處置率%"},
         "shapes": [{"type": "line", "x0": -0.5, "x1": len(grad_rows) - 0.5,
                     "y0": base, "y1": base, "xref": "x",
                     "line": {"color": RED, "width": 1, "dash": "dot"}}]})

    def grp_table(pool, lab):
        h = f"<table><tr><th>{lab}</th><th>n</th>" + "".join(
            f"<th>k{k}中位/勝率</th>" for k in KS) + "</tr>"
        for g_ in ("熱", "溫", "冷"):
            sub = pool[pool.grp == g_]
            tds = ""
            for k in KS:
                m, w, n = med_win(sub[f"f{k}"])
                tds += (f"<td class='{'good' if m > 0 else 'bad'}'>{m:+.2f}%/{w:.0f}%</td>"
                        if m is not None else "<td>—</td>")
            h += f"<tr><th>{g_}</th><td>{len(sub)}</td>{tds}</tr>"
        return h + "</table>"

    perf = "<table><tr><th>績效(V4池,持10日)</th><th>熱</th><th>溫</th><th>冷</th></tr>"
    for key, lab2 in (("n", "交易數"), ("win", "勝率%"), ("avg", "平均%"), ("med", "中位%"),
                      ("sum", "單利Σpp"), ("mdd", "MDD(pp)"), ("pf", "獲利因子")):
        cells = "".join(f"<td>{tr[g_][key]:.1f}</td>" if tr[g_][key] is not None else "<td>—</td>"
                        for g_ in ("熱", "溫", "冷"))
        perf += f"<tr><th>{lab2}</th>{cells}</tr>"
    perf += "</table>"

    yr_tbl = "<table><tr><th>逐年(V4池k10中位/勝率)</th><th>熱</th><th>冷</th><th>差pp</th></tr>"
    for y in sorted(v4p.y.unique()):
        ya = v4p[(v4p.y == y) & (v4p.grp == "熱")]
        yb = v4p[(v4p.y == y) & (v4p.grp == "冷")]
        ma, wa, na = med_win(ya.f10)
        mb, wb, nb = med_win(yb.f10)
        if ma is None or mb is None:
            continue
        d_ = ma - mb
        yr_tbl += (f"<tr><th>{y}</th><td>{ma:+.2f}%/{wa:.0f}%(n={na})</td>"
                   f"<td>{mb:+.2f}%/{wb:.0f}%(n={nb})</td>"
                   f"<td class='{'good' if d_ > 0 else 'bad'}'>{d_:+.2f}</td></tr>")
    yr_tbl += "</table>"

    hot = v4p[v4p.grp == "熱"].sort_values("end", ascending=False)
    det = ("<table><tr><th>熱組逐事件(V4池,新→舊)</th><th>出關日</th><th>gap</th>"
           "<th>7日內再處置</th><th>分盤</th><th>k10</th><th>k20</th></tr>")
    for r in hot.itertuples():
        f10s = f"{r.f10:+.1f}%" if pd.notna(r.f10) else "—"
        f20s = f"{r.f20:+.1f}%" if pd.notna(r.f20) else "—"
        det += (f"<tr><th>{r.code}</th><td>{r.end.date()}</td><td>{int(r.gap):+d}</td>"
                f"<td>{'✓' if r.renext else ''}</td><td>{r.mins}分</td>"
                f"<td class='{'good' if pd.notna(r.f10) and r.f10 > 0 else 'bad'}'>{f10s}</td>"
                f"<td class='{'good' if pd.notna(r.f20) and r.f20 > 0 else 'bad'}'>{f20s}</td></tr>")
    det += "</table>"

    divs = "".join(f'<div id="{d}" style="height:380px"></div>' for d, _, _ in (c_grad, c_eq))
    plots = "".join(f"Plotly.newPlot('{d}',{json.dumps(t, ensure_ascii=False)},"
                    f"Object.assign({json.dumps(ly, ensure_ascii=False)},BG));"
                    for d, t, ly in (c_grad, c_eq))
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>二進宮預測考卷(2026-07-29)</title>
<script src="plotly.min.js"></script><style>
body{{background:#1a1a19;color:#fff;font-family:"Noto Sans TC",sans-serif;margin:24px;max-width:1100px}}
h1{{font-size:20px}} h2{{font-size:15px;color:#c3c2b7;margin-top:28px;border-bottom:1px solid #333;padding-bottom:4px}}
table{{border-collapse:collapse;font-size:13px;font-variant-numeric:tabular-nums;margin:8px 0}}
td,th{{border:1px solid #333;padding:4px 10px;text-align:right}} th{{text-align:left;color:#c3c2b7}}
.note{{color:#8a8878;font-size:12.5px;line-height:1.8}} .good{{color:{GREEN}}} .bad{{color:{RED}}}
.warn{{color:{YELLOW}}} .hl{{background:#2a2a28}}</style></head><body>
<h1>🔁 二進宮預測考卷:出關日基數狀態=事前可算的新資訊(2026-07-29)</h1>
<div class="note">預註冊四題見build_dispo_second_jail.py docstring。背景=§6-8二訂(同日):一般自動處置的
基數穿越處置期繼續累積→出關前就能算「距二次處置門檻幾步」。n={len(ev)}出關事件(2019-02起,排除人工管制)。</div>

<h2>🗣️ 白話導讀</h2>
<div class="note">
<p><b>這卷在問什麼:</b>股票處置出關那天,官方基數(最近10日/30日的款1-8注意次數)是公開可算的。
基數還很滿的「熱票」出關後大機率馬上再被關(二進宮=20分鐘分盤+全民預收);基數乾淨的「冷票」則真正自由。
這兩群的出關後走勢,從來沒人事前分過。</p>
<p><b>判決一句話:</b>預測器成立(熱票再處置率21.4%=冷票5倍,梯度完美單調);報酬層方向=
「熱票較肥」(妖股動能未斷,與漲觸發升級組+7.24%同構)但CI含0=觀察層。
<b>實戰讀法:持有中的處置股,出關前看它熱不熱——熱票別假設出關就恢復流動性(1/5機率馬上再關),
但也別急著跑(續抱10日中位+1.95% vs 冷票-1.89%)。</b></p>
</div>

<h2>📋 判決表</h2>
<table>
<tr><th>題</th><th>判決</th><th>關鍵數字</th></tr>
<tr class="hl"><td>Q0 預測器</td><td class="good">✅成立</td><td>7日內再處置率:gap≤-4超標36%/熱(≤1)21.4%/溫8.7%/冷(≥4)4.2%,基準8.2%;完美單調、零前視</td></tr>
<tr><td>Q1 報酬層</td><td class="warn">🟡觀察層</td><td>V4池熱k10+1.95%/55% vs 冷-1.89%/45%,差+3.84pp CI[-0.73,+11.27]含0;逐年6/8正+5分盤內+3.56/20分盤內+3.14兩控同向</td></tr>
<tr><td>Q2 續抱決策</td><td class="warn">方向支持但薄</td><td>熱組續抱10日+1.95%/55% vs 冷-1.89%/45%→V4出場規則不動,熱票「別急著跑」為觀察建議</td></tr>
<tr><td>Q3 正交性</td><td class="good">✓真新維度</td><td>Spearman(gap,窗內報酬)=-0.167=與G3(窗內路徑)幾乎無關;G3「窗內弱勢較好」在熱/冷內皆重現=兩維度可疊</td></tr>
<tr><td>死格</td><td class="bad">⚠</td><td>2021年熱組k20 -8.00%/41%(n=41)=最大反例年;報酬層升格需live或更多熊年樣本</td></tr>
</table>

{divs}

<h2>逐日CAR(#12家規:讓資料自己說肉在哪個天期;2026-07-29使用者追問後補)</h2>
<table><tr><th>k</th><th>熱組中位/勝率</th><th>冷組中位/勝率</th><th>差pp</th></tr>
<tr><td>1</td><td>+1.46%/52%</td><td>-1.88%/43%</td><td>+3.34</td></tr>
<tr><td>2</td><td>+1.80%/55%</td><td>-2.59%/43%</td><td>+4.39</td></tr>
<tr class="hl"><td>7</td><td>+1.65%/54%</td><td>-3.10%/41%</td><td><b>+4.75(峰)</b></td></tr>
<tr><td>10</td><td>+1.95%/55%</td><td>-1.89%/45%</td><td>+3.84</td></tr>
<tr><td>15</td><td>+4.00%/54%</td><td>-0.06%/50%</td><td>+4.06</td></tr>
<tr><td>20</td><td>+1.89%/54%</td><td>-0.31%/50%</td><td>+2.19</td></tr>
<tr><td>30</td><td>+0.11%/50%</td><td>-0.64%/49%</td><td>+0.76</td></tr>
<tr><td>60</td><td>+1.49%/51%</td><td>+2.45%/54%</td><td class="bad">-0.96(反轉)</td></tr></table>
<div class="note">形狀判讀:edge第1天就在、<b>k2~k15高原(+3.7~+4.8pp)</b>、k20起衰減、k30歸零、k60反轉=
甜蜜帶「前2~3週」,10日=高原中點(7/15日等效,差距雜訊級不調參),<b>別抱過20日</b>;
機制吻合=催化全在前段(7日內再處置21%+再處置窗10-12日的第3日搶跑循環)。
進場點=出關+1開盤的三理由:①注意公告到出關日收盤才齊=零前視 ②處置期間買進受限(分盤+預收),
出關+1=新資金真正進得去的第一個開盤 ③與V4規則出場點同一時刻=持有者續抱決策的淨差。
(數字來源tmp_sj_car.py,與主表同口徑V4池)</div>

<h2>各組報酬(出關+1開盤起,中位/勝率)</h2>
{grp_table(v4p, "V4池(T1-T3∧amt20≥0.3億)")}
{grp_table(ev, "全池")}
<h2>績效彙總(V4池,持10日,單利)</h2>
{perf}
<div class="note">⚠單利累加口徑=每筆等權,無資金上限;熱組n=253筆/7.5年≈34筆/年;
權益曲線讀形狀(斜率與回撤段)別讀絕對值。</div>
<h2>逐年對照</h2>
{yr_tbl}
<h2>熱組逐事件明細</h2>
{det}
<h2>限制</h2>
<div class="note">再處置率未到100%=出關後仍需繼續中注意才會再關(安分票會被窗口稀釋)=機率預測;
Q1 CI含0=觀察層不進規則;2021反例年未解;gap口徑只算標準道(10日6次/30日12次),快速道(連3/連5)
在出關情境幾乎不適用(處置期間連續性被切斷);人工管制型已排除(§6-8重置適用彼、不適用此)。</div>
</body><script>const BG={json.dumps(BG)};{plots}</script></html>"""
    out = "研究報告/research_dispo_second_jail.html"
    open(out, "w", encoding="utf-8").write(html)
    print(f"\n報告已產出 {out} ({len(html):,} chars)")


if __name__ == "__main__":
    main()
