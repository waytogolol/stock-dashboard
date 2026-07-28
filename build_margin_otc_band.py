# -*- coding: utf-8 -*-
"""上櫃融資維持率警戒帶考卷(預註冊2026-07-28,使用者裁示「上市上櫃維持率開個研究做驗證補充」)
========================================================================
預註冊四題(判決2026-07-29,樣本齊後首跑):
  E1 門檻移植: 上櫃mm<150首破episode(60交易日去重)→TPEx k5/10/20/60。對照=同法上市帶→TAIEX。
     先驗警語: 若上櫃事件頻率>2次/年=門檻不適用直接判死。→判決=0.77次/年合格,k60+9.12%/75%成立觀察層
  E2 自身位階版: 上櫃mm expanding位階<=5(最少3年暖機)→判決=不加值,在真崩盤前提早誤觸發,用150絕對線
  E3 獨立增量: →判決=真發現:兩市同破(n=5)k20+10.30/k60+11.12/80%強出清;
     上櫃單獨破(上市健康,n=7)短線中位全負=中小型領跌警訊別接
  E4 剪刀差(探索): spread=上市-上櫃 240日位階>=95→TPEx-TAIEX相對→判決=中小型續弱k10勝率28%=避開提示
判準: episode化去重/逐事件明細/n<15不bootstrap→觀察層;死格=帶內慢熊(2011-08/2018-08型)短線可再殺20%
報告: 研究報告/research_margin_band.html(雙市全史圖+權益曲線+明細,2026-07-29使用者要求補權益曲線)
用法: python build_margin_otc_band.py
"""
import json
import sqlite3
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
DB = "capital_flow.db"
KS = [5, 10, 20, 60]
GREEN, RED, BLUE, YELLOW, GRAY = "#7ec97e", "#e06c5a", "#6bb7e3", "#c3a55a", "#8a8878"
BG = {"paper_bgcolor": "#1a1a19", "plot_bgcolor": "#22221f",
      "font": {"color": "#ddd", "size": 12}, "margin": {"t": 42, "l": 52, "r": 18, "b": 40},
      "legend": {"orientation": "h"}}


def fwd(px, d, k):
    if d not in px.index:
        return None
    t = px.index.get_loc(d)
    if t + k >= len(px):
        return None
    return (px.iloc[t + k] / px.iloc[t] - 1) * 100


def episodes(dates, cal, sep=60):
    pos = {d: i for i, d in enumerate(cal)}
    out, last = [], -10**9
    for d in sorted(dates):
        if d in pos and pos[d] - last >= sep:
            out.append(d)
            last = pos[d]
    return out


def stats_rows(evs, px, base_px=None):
    """回傳(html列, 中位/勝率列html, console同步印)"""
    rows_html, allv = "", {k: [] for k in KS}
    for d in evs:
        cells = ""
        for k in KS:
            v = fwd(px, d, k)
            if v is not None and base_px is not None:
                b = fwd(base_px, d, k)
                v = v - b if b is not None else None
            if v is None:
                cells += "<td>—</td>"
            else:
                allv[k].append(v)
                cells += f"<td class='{'good' if v > 0 else 'bad'}'>{v:+.2f}</td>"
        rows_html += f"<tr><th>{d.date()}</th>{cells}</tr>"
    med = "".join(f"<td>{np.median(allv[k]):+.2f}</td>" if allv[k] else "<td>—</td>" for k in KS)
    win = "".join(f"<td>{np.mean(np.array(allv[k]) > 0) * 100:.0f}%</td>" if allv[k] else "<td>—</td>"
                  for k in KS)
    foot = f"<tr class='hl'><th>中位</th>{med}</tr><tr class='hl'><th>勝率</th>{win}</tr>"
    return rows_html + foot


def equity(idx, trig_days, hold=60):
    """事件T+1開盤買指數持hold日→空手(持有中忽略新事件);回傳淨值日序列。"""
    dates = idx.index
    ret = idx.pct_change().fillna(0.0)
    entry_pos = set()
    for d in trig_days:
        t = dates.get_loc(d)
        if t + 1 < len(dates):
            entry_pos.add(t + 1)
    eq, val, holding, pos_until = [], 1.0, False, -1
    for i in range(len(dates)):
        if i in entry_pos and not holding:
            holding = True
            pos_until = i + hold - 1
        elif holding:
            val *= (1 + ret.iloc[i])
            if i >= pos_until:
                holding = False
        eq.append(val)
    return pd.Series(eq, index=dates)


def wtrace(s, name, color, dash=None):
    w = s.resample("W").last().dropna()
    line = {"color": color, "width": 2}
    if dash:
        line.update({"dash": dash, "width": 1.6})
    return {"x": [d.strftime("%Y-%m-%d") for d in w.index],
            "y": [round(float(v), 4) for v in w.values],
            "name": name, "mode": "lines", "line": line,
            "hovertemplate": "%{x}: %{y:.3f}<extra>" + name + "</extra>"}


def mdd(s):
    return float(((s / s.cummax()) - 1).min() * 100)


def main():
    conn = sqlite3.connect(DB)
    cal = pd.to_datetime([r[0] for r in conn.execute(
        "SELECT DISTINCT date FROM index_daily WHERE market='TAIEX' AND date>='2011-01-01' "
        "ORDER BY date")])
    otc = pd.read_sql("SELECT date, ratio FROM margin_maintenance_otc WHERE ratio>=100 "
                      "ORDER BY date", conn, parse_dates=["date"]).set_index("date").ratio
    twm = pd.read_sql("SELECT date, ratio FROM margin_maintenance_official WHERE ratio>=100 "
                      "ORDER BY date", conn, parse_dates=["date"]).set_index("date").ratio
    tpex = pd.read_sql("SELECT date, close FROM index_daily WHERE market='TPEx' ORDER BY date",
                       conn, parse_dates=["date"]).set_index("date").close
    taiex = pd.read_sql("SELECT date, close FROM index_daily WHERE market='TAIEX' ORDER BY date",
                        conn, parse_dates=["date"]).set_index("date").close
    conn.close()

    cov = len(otc) / len(cal) * 100
    print(f"上櫃維持率覆蓋: {len(otc)}/{len(cal)}交易日 = {cov:.1f}%")
    if cov < 95:
        print("⛔ 覆蓋<95%,回補未齊,先不跑")
        return

    # ---- 事件 ----
    e1 = episodes(otc[otc < 150].index, cal)
    tw_e = episodes(twm[(twm < 150) & (twm.index >= cal[0])].index, cal)
    yrs = (cal[-1] - cal[0]).days / 365.25
    pctl = otc.expanding(750).apply(lambda s: (s <= s.iloc[-1]).mean() * 100, raw=False)
    e2 = episodes(pctl[pctl <= 5].index, cal)
    twm_d = twm.reindex(otc.index).ffill()
    e3_only = [d for d in e2 if twm_d.get(d, np.nan) >= 150]
    e3_both = [d for d in e2 if twm_d.get(d, np.nan) < 150]
    both = pd.concat([twm.rename("tw"), otc.rename("otc")], axis=1).dropna()
    spread = both.tw - both.otc
    sp_pct = spread.rolling(240).rank(pct=True) * 100
    e4 = episodes(sp_pct[sp_pct >= 95].index, cal, sep=20)
    print(f"E1上櫃帶n={len(e1)}({len(e1) / yrs:.2f}次/年) 上市對照n={len(tw_e)} "
          f"E2位階n={len(e2)} E3單獨n={len(e3_only)}/同破n={len(e3_both)} E4剪刀n={len(e4)}")

    # ---- 權益曲線 ----
    win0 = pd.Timestamp("2011-01-01")
    tp = tpex[tpex.index >= win0]
    ta = taiex[taiex.index >= win0]
    eq_e1 = equity(tp, e1)
    eq_e3b = equity(tp, e3_both)
    eq_tw = equity(ta, tw_e)
    bh = tp / tp.iloc[0]
    yrs_eq = (tp.index[-1] - tp.index[0]).days / 365.25
    expo1 = len(e1) * 60 / len(tp) * 100

    # ---- 圖 ----
    charts = []
    mmw_tw = twm[twm.index >= win0].resample("W").last().dropna()
    mmw_ot = otc.resample("W").last().dropna()
    charts.append(("c_mm", [
        {"x": [d.strftime("%Y-%m-%d") for d in mmw_tw.index], "y": [round(float(v), 1) for v in mmw_tw],
         "name": "上市(官方)", "mode": "lines", "line": {"color": GRAY, "width": 1.6},
         "hovertemplate": "%{x}: %{y}%<extra>上市</extra>"},
        {"x": [d.strftime("%Y-%m-%d") for d in mmw_ot.index], "y": [round(float(v), 1) for v in mmw_ot],
         "name": "上櫃(公式版)", "mode": "lines", "line": {"color": BLUE, "width": 1.8},
         "hovertemplate": "%{x}: %{y}%<extra>上櫃</extra>"},
        {"x": [d.strftime("%Y-%m-%d") for d in e1],
         "y": [round(float(otc.asof(d)), 1) for d in e1],
         "name": "E1上櫃首破150", "mode": "markers",
         "marker": {"color": RED, "size": 10, "symbol": "triangle-down",
                    "line": {"color": "#22221f", "width": 1.5}},
         "hovertemplate": "%{x} 首破<extra>E1</extra>"},
        {"x": [d.strftime("%Y-%m-%d") for d in e3_both],
         "y": [round(float(otc.asof(d)), 1) for d in e3_both],
         "name": "E3b兩市同傷", "mode": "markers",
         "marker": {"color": YELLOW, "size": 12, "symbol": "star",
                    "line": {"color": "#22221f", "width": 1}},
         "hovertemplate": "%{x} 兩市同傷<extra>E3b</extra>"}],
        {"title": "雙市融資維持率全史(2011起,週線;紅線=150警戒)",
         "yaxis": {"title": "維持率%"},
         "shapes": [{"type": "line", "x0": mmw_ot.index[0].strftime("%Y-%m-%d"),
                     "x1": mmw_ot.index[-1].strftime("%Y-%m-%d"), "y0": 150, "y1": 150,
                     "line": {"color": RED, "width": 1, "dash": "dot"}}]}))
    charts.append(("c_eq", [
        wtrace(eq_e1, f"E1上櫃帶→櫃買60日({eq_e1.iloc[-1]:.2f}x,MDD{mdd(eq_e1):.0f}%)", BLUE),
        wtrace(eq_e3b, f"E3b兩市同破→櫃買60日({eq_e3b.iloc[-1]:.2f}x,MDD{mdd(eq_e3b):.0f}%)", YELLOW),
        wtrace(eq_tw, f"上市帶→加權60日對照({eq_tw.iloc[-1]:.2f}x,MDD{mdd(eq_tw):.0f}%)", GREEN, "dash"),
        wtrace(bh, f"櫃買買進持有({bh.iloc[-1]:.2f}x,MDD{mdd(bh):.0f}%)", GRAY, "dot")],
        {"title": (f"載具權益曲線(起點=1,log):事件T+1開盤買指數持60日→空手;"
                   f"E1曝險僅~{expo1:.0f}%——時機工具,別跟滿倉曲線比絕對高度"),
         "yaxis": {"title": "淨值", "type": "log"}}))

    # ---- 表 ----
    th = "".join(f"<th>k{k}</th>" for k in KS)
    tbl_e1 = f"<table><tr><th>E1上櫃帶(n={len(e1)})</th>{th}</tr>" + stats_rows(e1, tpex) + "</table>"
    tbl_tw = (f"<table><tr><th>對照:上市帶→TAIEX(n={len(tw_e)})</th>{th}</tr>" +
              stats_rows(tw_e, taiex) + "</table>")
    tbl_e3a = (f"<table><tr><th>E3a上櫃單獨極端(n={len(e3_only)})</th>{th}</tr>" +
               stats_rows(e3_only, tpex) + "</table>")
    tbl_e3b = (f"<table><tr><th>E3b兩市同傷(n={len(e3_both)})</th>{th}</tr>" +
               stats_rows(e3_both, tpex) + "</table>")
    tbl_e4 = (f"<table><tr><th>E4剪刀差極端→TPEx−TAIEX相對(n={len(e4)})</th>{th}</tr>" +
              stats_rows(e4, tpex, base_px=taiex) + "</table>")

    eq_note = (f"E1觸發{len(e1)}次/曝險~{expo1:.0f}%/年數{yrs_eq:.1f}: "
               f"E1→櫃買 {eq_e1.iloc[-1]:.2f}x(年化{(eq_e1.iloc[-1] ** (1 / yrs_eq) - 1) * 100:+.1f}%,"
               f"MDD{mdd(eq_e1):.1f}%) / E3b兩市同破 {eq_e3b.iloc[-1]:.2f}x({len(e3_both)}次) / "
               f"上市帶對照 {eq_tw.iloc[-1]:.2f}x / 櫃買買進持有 {bh.iloc[-1]:.2f}x(MDD{mdd(bh):.1f}%)")
    print(eq_note)

    divs = "".join(f'<div id="{d}" style="height:{400 if d == "c_mm" else 360}px"></div>'
                   for d, _, _ in charts)
    plots = "".join(
        f"Plotly.newPlot('{d}',{json.dumps(tr_, ensure_ascii=False)},"
        f"Object.assign({json.dumps(ly, ensure_ascii=False)},BG));" for d, tr_, ly in charts)

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>融資維持率警戒帶(雙市判決2026-07-29)</title>
<script src="plotly.min.js"></script><style>
body{{background:#1a1a19;color:#fff;font-family:"Noto Sans TC",sans-serif;margin:24px;max-width:1100px}}
h1{{font-size:20px}} h2{{font-size:15px;color:#c3c2b7;margin-top:28px;border-bottom:1px solid #333;padding-bottom:4px}}
table{{border-collapse:collapse;font-size:13px;font-variant-numeric:tabular-nums;margin:8px 0}}
td,th{{border:1px solid #333;padding:4px 10px;text-align:right}} th{{text-align:left;color:#c3c2b7}}
.note{{color:#8a8878;font-size:12.5px;line-height:1.8}} .good{{color:{GREEN}}} .bad{{color:{RED}}}
.warn{{color:{YELLOW}}} .hl{{background:#2a2a28}}</style></head><body>
<h1>🚨 融資維持率警戒帶:上市×上櫃雙市判決(2026-07-29)</h1>
<div class="note">上市=margin_maintenance_official(FinMind官方,公式版備援-0.01pp);
上櫃=margin_maintenance_otc(公式版=Σ逐股融資餘額張×TPEX官方收盤÷融資總金額,2011起3,804日,對帳見fetch_margin_maintenance.py);
考卷預註冊四題見build_margin_otc_band.py docstring,樣本齊後首跑即凍結。</div>

<h2>🗣️ 白話導讀</h2>
<div class="note">
<p><b>維持率是什麼:</b>全市場融資戶的擔保品市值÷借款金額。跌破150%＝大量融資戶進入追繳斷頭區
＝券商開始強制賣出＝<b>最典型的被迫賣壓</b>(賣的人不是看壞,是不得不賣),倒完就沒賣壓→歷史上帶內買進偏反彈。</p>
<p><b>為什麼要做上櫃版:</b>上櫃基線系統性低於上市(中小型槓桿更兇),且水位不同步——中小型可以自己先斷頭
(如2015-07/2018-08),這是上市線看不到的獨立資訊。公式版資料2011起,含2011歐債/2015股災/2018Q4/
2020疫情/2022熊/2024-08/2025-04七個壓力窗。</p>
<p><b>一句話判決:</b>上櫃&lt;150警戒帶成立(觀察層,k60+9.12%/75%);<b>但要看上市臉色</b>——
兩市同破=全市場斷頭出清=強買點(k60+11.12%/80%);上櫃單獨破而上市健康=中小型領跌警訊,
短線中位是負的,別接。剪刀差(上市−上櫃)拉到極端=中小型還會續弱約兩週,是避開提示不是反轉訊號。</p>
</div>

<h2>📋 判決表</h2>
<table>
<tr><th>題</th><th>判決</th><th>關鍵數字</th></tr>
<tr class="hl"><td>E1 門檻移植(上櫃&lt;150首破)</td><td class="good">成立,觀察層</td><td>n=12,0.77次/年(合格&lt;2);k60中位+9.12%/勝75%;k20僅-0.23%=肉在60日</td></tr>
<tr><td>E2 自身位階≤5版</td><td class="bad">不加值</td><td>k60+7.49%/67%不如E1;會在真崩盤前提早誤觸發(2015-07-20/2018-08-13)→live用150絕對線</td></tr>
<tr class="hl"><td>E3 獨立性切分</td><td class="good">真發現</td><td><b>兩市同破(n=5):k20+10.30/k60+11.12/80%;上櫃單獨破(n=7):k5~k20中位全負,k60僅+4.05=領跌警訊別接</b></td></tr>
<tr><td>E4 剪刀差極端(探索)</td><td class="warn">避開提示</td><td>n=46,TPEx相對TAIEX k10中位-0.68%/勝28%=中小型續弱~2週;非反轉訊號</td></tr>
<tr><td>死格</td><td class="bad">⚠</td><td>慢熊中段型再現:2011-08(k60-3.2)/2018-08(k60-15.4);首破後短線可再殺20%(2020-03/2025-03 k5≈-20)=<b>狀態非時點,帶內等急跌收斂日(雙收斂/溫度計)再進</b></td></tr>
</table>

{divs}
<div class="note">{eq_note}<br>權益曲線口徑=事件T+1開盤買指數持60交易日→空手(持有中忽略新事件),
無成本無槓桿;讀法=每單位曝險效率與回撤形狀,別跟滿倉比絕對高度。</div>

<h2>逐事件明細</h2>
{tbl_e1}{tbl_tw}{tbl_e3a}{tbl_e3b}
<h2>E4 剪刀差明細(相對報酬=TPEx−TAIEX)</h2>
{tbl_e4}
<h2>限制</h2>
<div class="note">n=12/7/5全小→觀察層不進規則;上櫃2011前無資料(API深度);episode去重60日=
慢熊會切成多事件;E3切分用上市當日&lt;150二分,未掃其他切點(防過擬合);
公式版2022-23個別日與官方有-1~-2.7pp資料端差異(見fetch_margin_maintenance.py對帳)。
live用法已上儀表板警戒帶卡(雙市讀數+同破/單獨破判讀)。</div>
</body><script>const BG={json.dumps(BG)};{plots}</script></html>"""
    out = "研究報告/research_margin_band.html"
    open(out, "w", encoding="utf-8").write(html)
    print(f"報告已產出 {out} ({len(html):,} chars, {len(charts)}圖)")


if __name__ == "__main__":
    main()
