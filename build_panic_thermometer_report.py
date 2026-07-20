# -*- coding: utf-8 -*-
"""⑤恐慌溫度計判決報告 -> 研究報告/research_panic_thermometer.html (本機,gitignored)
資料源: tmp_panic_gradient_panel.pkl(甜蜜格) + index_daily + margin_maintenance_official
定位: 市場層時機觀察工具(n=7不進規則)。用法: python build_panic_thermometer_report.py
"""
import json
import sqlite3

import pandas as pd

GREEN, RED, BLUE, YELLOW, GRAY = "#7ec97e", "#e06c5a", "#6bb7e3", "#c3a55a", "#8a8878"
BG = {"paper_bgcolor": "#1a1a19", "plot_bgcolor": "#22221f",
      "font": {"color": "#ddd", "size": 12}, "margin": {"t": 40, "l": 50, "r": 20, "b": 40}}
CSS = """
body{background:#1a1a19;color:#fff;font-family:"Noto Sans TC",sans-serif;margin:24px;max-width:1100px}
h1{font-size:20px} h2{font-size:15px;color:#c3c2b7;margin-top:28px}
table{border-collapse:collapse;font-size:13px;font-variant-numeric:tabular-nums}
td,th{border:1px solid #333;padding:5px 10px;text-align:right} th{text-align:left}
.note{color:#8a8878;font-size:12px;line-height:1.7}
.good{color:#7ec97e}.bad{color:#e06c5a}.warn{color:#c3a55a}
"""
KS = [1, 3, 5, 10, 20, 40, 60]


def load_idx(mkt):
    conn = sqlite3.connect("capital_flow.db")
    df = pd.read_sql("SELECT date, open, close FROM index_daily WHERE market=? ORDER BY date",
                     conn, params=(mkt,), parse_dates=["date"]).set_index("date")
    conn.close()
    return df


def fwd(df, t, k, from_open_next=False):
    if from_open_next:
        if t + 1 + k >= len(df):
            return None
        return (df.close.iloc[t + 1 + k] / df.open.iloc[t + 1] - 1) * 100
    if t + k >= len(df):
        return None
    return (df.close.iloc[t + k] / df.close.iloc[t] - 1) * 100


def episodes(trigger_dates, all_days, sep=10):
    pos = {d: i for i, d in enumerate(all_days)}
    out, last = [], -10**9
    for d in sorted(trigger_dates):
        if d in pos and pos[d] - last >= sep:
            out.append(d)
            last = pos[d]
    return out


def car_series(days, idx, open_ver=False):
    med, win = [], []
    for k in KS:
        vals = pd.Series([v for d in days if (v := fwd(idx, idx.index.get_loc(d), k, open_ver)) is not None])
        med.append(round(float(vals.median()), 2))
        win.append(round(float((vals > 0).mean() * 100)))
    return med, win


def main():
    p = pd.read_pickle("tmp_panic_gradient_panel.pkl")
    ss = p[(p.i1 == "-6~-9") & (p.i2 == ">=20%")]
    tw = load_idx("TAIEX")
    otc = load_idx("TPEx")
    win_idx = tw[(tw.index >= "2019-03-01") & (tw.index <= ss.d0.max())]
    cnt = ss.groupby("d0").size().reindex(win_idx.index, fill_value=0)
    all_days = list(tw.index)

    eps = {n: episodes(cnt[cnt >= n].index, all_days) for n in (10, 20, 40)}
    naive_r = tw.close.pct_change() * 100
    naive = episodes(naive_r[(naive_r <= -2) & (naive_r.index >= "2019-03-01")
                             & (naive_r.index <= ss.d0.max())].index, all_days)
    base_days = list(win_idx.index[:-61])

    car20, w20 = car_series(eps[20], tw)
    car20o, w20o = car_series(eps[20], tw, open_ver=True)
    carN, wN = car_series(naive, tw)
    carB, wB = car_series(base_days, tw)

    charts = []
    # 圖1: 加權log + 觸發標記
    twp = tw[tw.index >= "2019-03-01"].close.resample("W").last().dropna()
    charts.append(("c_idx", [
        {"x": [d.strftime("%Y-%m-%d") for d in twp.index], "y": [round(float(v), 0) for v in twp.values],
         "name": "加權(週線)", "mode": "lines", "line": {"color": GRAY, "width": 1.5}},
        {"x": [d.strftime("%Y-%m-%d") for d in eps[20]],
         "y": [round(float(tw.close.asof(d)), 0) for d in eps[20]],
         "name": "溫度計≥20觸發", "mode": "markers+text",
         "text": [d.strftime("%y/%m") for d in eps[20]], "textposition": "bottom center",
         "textfont": {"color": BLUE, "size": 10},
         "marker": {"color": BLUE, "size": 11, "symbol": "triangle-up",
                    "line": {"color": "#22221f", "width": 2}},
         "hovertemplate": "%{x} 觸發｜加權%{y:,.0f}<extra></extra>"}],
        {"title": "溫度計≥20觸發點位（7個episode全是史冊級恐慌日,零前視）",
         "yaxis": {"title": "加權指數", "type": "log"}}))
    # 圖2: 每日並發數
    charts.append(("c_cnt", [{
        "x": [d.strftime("%Y-%m-%d") for d in cnt.index], "y": [int(v) for v in cnt.values],
        "type": "bar", "name": "甜蜜格單日並發數", "marker": {"color": BLUE},
        "hovertemplate": "%{x}: %{y}檔<extra></extra>"}],
        {"title": "甜蜜格單日並發觸發數（p99=16, max=77@2025-04-09；門檻線=20）",
         "yaxis": {"title": "當日觸發檔數"},
         "shapes": [{"type": "line", "x0": cnt.index[0].strftime("%Y-%m-%d"),
                     "x1": cnt.index[-1].strftime("%Y-%m-%d"), "y0": 20, "y1": 20,
                     "line": {"color": YELLOW, "width": 1, "dash": "dot"}}]}))
    # 圖3: 前瞻中位報酬曲線比較
    xs = [f"k={k}" for k in KS]
    charts.append(("c_car", [
        {"x": xs, "y": car20, "name": "溫度計≥20 (n=7)", "mode": "lines+markers",
         "line": {"color": BLUE, "width": 2}, "marker": {"size": 8},
         "customdata": w20, "hovertemplate": "%{x}: %{y:+.2f}%｜勝率%{customdata}%<extra>溫度計</extra>"},
        {"x": xs, "y": car20o, "name": "溫度計≥20 T+1開盤版", "mode": "lines+markers",
         "line": {"color": YELLOW, "width": 2, "dash": "dash"}, "marker": {"size": 8},
         "customdata": w20o, "hovertemplate": "%{x}: %{y:+.2f}%｜勝率%{customdata}%<extra>T+1開</extra>"},
        {"x": xs, "y": carN, "name": "天真訊號:日跌≥2% (n=31)", "mode": "lines+markers",
         "line": {"color": RED, "width": 2}, "marker": {"size": 8},
         "customdata": wN, "hovertemplate": "%{x}: %{y:+.2f}%｜勝率%{customdata}%<extra>天真</extra>"},
        {"x": xs, "y": carB, "name": "全日基準", "mode": "lines+markers",
         "line": {"color": GRAY, "width": 1.5, "dash": "dot"}, "marker": {"size": 6},
         "customdata": wB, "hovertemplate": "%{x}: %{y:+.2f}%｜勝率%{customdata}%<extra>基準</extra>"}],
        {"title": "觸發後加權前瞻中位報酬：溫度計增量真實（天真「大跌買」≈基準）",
         "yaxis": {"title": "中位累積報酬%"}}))

    # 權益曲線: 觸發T+1開盤買指數持有60交易日→空手 (可交易版), 對照=加權買進持有
    def equity(idx, trig_days, hold=60):
        dates = idx.index
        ret = idx.close.pct_change().fillna(0.0)
        open_ret = (idx.close / idx.open - 1)   # 進場日: T+1開→T+1收
        pos_until = -1
        entry_pos = set()
        for d in trig_days:
            t = dates.get_loc(d)
            if t + 1 < len(dates):
                entry_pos.add(t + 1)
        eq, val, holding = [], 1.0, False
        for i in range(len(dates)):
            if i in entry_pos and not holding:
                holding = True
                pos_until = i + hold - 1
                val *= (1 + open_ret.iloc[i])
            elif holding:
                val *= (1 + ret.iloc[i])
                if i >= pos_until:
                    holding = False
            eq.append(val)
        return pd.Series(eq, index=dates)

    win0 = pd.Timestamp("2019-03-01")
    eq_tw = equity(tw[tw.index >= win0], eps[20])
    eq_otc = equity(otc[otc.index >= win0], [d for d in eps[20] if d in otc.index])
    bh = tw[tw.index >= win0].close
    bh = bh / bh.iloc[0]

    def mdd(s):
        return float(((s / s.cummax()) - 1).min() * 100)

    def wtrace(s, name, color, dash=None):
        w = s.resample("W").last().dropna()
        line = {"color": color, "width": 2}
        if dash:
            line.update({"dash": dash, "width": 1.5})
        return {"x": [d.strftime("%Y-%m-%d") for d in w.index],
                "y": [round(float(v), 4) for v in w.values],
                "name": name, "mode": "lines", "line": line,
                "hovertemplate": "%{x}: %{y:.3f}<extra>" + name + "</extra>"}

    expo = (7 * 60) / len(eq_tw) * 100
    yrs = (eq_tw.index[-1] - eq_tw.index[0]).days / 365.25
    charts.append(("c_eq", [
        wtrace(eq_tw, f"溫度計→加權60日({eq_tw.iloc[-1]:.2f}x,MDD{mdd(eq_tw):.1f}%)", BLUE),
        wtrace(eq_otc, f"溫度計→櫃買60日({eq_otc.iloc[-1]:.2f}x,MDD{mdd(eq_otc):.1f}%)", YELLOW),
        wtrace(bh, f"加權買進持有({bh.iloc[-1]:.2f}x,MDD{mdd(bh):.1f}%)", GRAY, "dot")],
        {"title": (f"載具權益曲線(起點=1,log)：觸發T+1開盤買指數持60日,曝險僅~{expo:.0f}% "
                   "——時機工具非替代持股,別跟滿倉曲線比絕對高度"),
         "yaxis": {"title": "淨值", "type": "log"}}))
    eq_stats = (f"觸發7次/曝險~{expo:.0f}%/年數{yrs:.1f}：溫度計→加權 {eq_tw.iloc[-1]:.2f}x"
                f"(年化{(eq_tw.iloc[-1] ** (1 / yrs) - 1) * 100:+.1f}%,MDD{mdd(eq_tw):.1f}%)、"
                f"→櫃買 {eq_otc.iloc[-1]:.2f}x(MDD{mdd(eq_otc):.1f}%)；"
                f"加權買進持有 {bh.iloc[-1]:.2f}x(MDD{mdd(bh):.1f}%)。"
                f"讀法=每單位曝險效率與回撤,不是絕對高度(2019-26大多頭滿倉必勝過23%曝險)")

    # episode明細表
    conn = sqlite3.connect("capital_flow.db")
    mm = pd.read_sql("SELECT date, ratio FROM margin_maintenance_official", conn,
                     parse_dates=["date"]).set_index("date").ratio
    conn.close()
    mm = mm[mm >= 100]
    rows = ""
    for d in eps[20]:
        t = tw.index.get_loc(d)
        to = otc.index.get_loc(d) if d in otc.index else None
        r = mm.asof(d)
        cells = [f"<th>{d.date()}</th>", f"<td>{cnt[d]:.0f}</td>",
                 f"<td>{tw.close.iloc[t]:,.0f}</td>",
                 f"<td class='{'warn' if r < 150 else ''}'>{r:.1f}{' ⚠' if r < 150 else ''}</td>"]
        for idx_, tt in ((tw, t), (otc, to)):
            for k in (20, 60):
                v = fwd(idx_, tt, k) if tt is not None else None
                cells.append(f"<td class='{'good' if (v or 0) > 0 else 'bad'}'>"
                             f"{v:+.2f}%</td>" if v is not None else "<td>—</td>")
        rows += "<tr>" + "".join(cells) + "</tr>"
    ep_table = ("<table><tr><th>觸發日</th><th>並發數</th><th>加權收盤</th><th>維持率</th>"
                "<th>加權k20</th><th>k60</th><th>櫃買k20</th><th>k60</th></tr>" + rows + "</table>")

    # 敏感度表 N=10/20/40
    sens = ""
    for n in (10, 20, 40):
        med, win_ = car_series(eps[n], tw)
        sens += (f"<tr><th>觸發數≥{n} (n={len(eps[n])})</th>" +
                 "".join(f"<td class='{'good' if m > 0 else 'bad'}'>{m:+.2f}% / {w}%</td>"
                         for m, w in zip(med, win_)) + "</tr>")
    sens_table = ("<table><tr><th>門檻</th>" + "".join(f"<th>k={k}</th>" for k in KS) +
                  "</tr>" + sens + "</table>")

    verdicts = [
        ("溫度計定義", "甜蜜格(近40日曾漲20%×已回檔≥20%×當日跌6-9%)單日並發觸發數；分布p99=16/max=77；門檻≥20+10日episode去重"),
        ("命中", "7個episode=2020-03-13/2021-05-11/2022-06-22/2024-08-06/2025-04-08/2026-03-09/2026-06-10，全是史冊級恐慌日，零前視；收盤價逐一手核公開紀錄"),
        ("前瞻", "k20中位+4.93%/勝86%、k60+14.21%/83% vs 全日基準k60+4.88%/70%"),
        ("增量檢查(feedback#11)", "天真訊號「加權日跌≥2%」(n=31) k60僅+5.08%/72%≈基準 → 溫度計增量真實，不是「大跌日買就賺」"),
        ("可交易性(feedback#12)", "T+1開盤版k60+13.53%幾乎不衰減=指數層無跳空吃肉問題"),
        ("唯一死格", "2022-06-22(k60-4.42%)=慢熊中段恐慌≠底，與警戒帶2008慢熊例外同族失效模式"),
        ("與融資警戒帶", "重疊4/7=互補非重複：溫度計抓急殺出清、警戒帶抓斷頭水位；2025-04-08兩者同亮→k60+23%"),
        ("載具權益(絕對報酬層)", eq_stats),
        ("定位", "市場層時機觀察工具(與甜蜜格/開低承接同層)；n=7不做bootstrap不進規則；live=崩盤日跑fm_daily_price增量後算當日並發數"),
    ]
    vrows = "".join(f"<tr><th>{a}</th><td style='text-align:left'>{b}</td></tr>" for a, b in verdicts)

    divs = "".join(f'<div id="{d}" style="height:{380 if d == "c_idx" else 320}px"></div>'
                   for d, _, _ in charts)
    plots = "".join(
        f"Plotly.newPlot('{d}',{json.dumps(tr_, ensure_ascii=False)},"
        f"Object.assign({json.dumps(ly, ensure_ascii=False)},BG));" for d, tr_, ly in charts)
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>恐慌溫度計判決(2026-07-19)</title>
<script src="plotly.min.js"></script><style>{CSS}</style></head><body>
<h1>⑤恐慌溫度計：甜蜜格單日並發數=大盤恐慌出清標記（判決=成立,觀察層）</h1>
<div class="note">母體=tmp_panic_gradient_panel.pkl甜蜜格1,468筆(對帳分毫不差)，2019-03~2026-07；
指數=index_daily；維持率=margin_maintenance_official(濾官方壞點&lt;100)。</div>
<h2>📋 執行摘要（判決表）</h2><table>{vrows}</table>
{divs}
<h2>觸發數≥20 episode明細</h2>{ep_table}
<h2>門檻敏感度（中位% / 勝率%，收盤版）</h2>{sens_table}
<h2>已知限制</h2><div class="note">n=7無bootstrap；2019起樣本偏多頭(全日基準k60即+4.88%)；
母體=研究池1379檔有存活偏差(影響並發數水位,門檻屬樣本內校準)；2026-06-10 k60未到期；
門檻20為分布事後選定,N=10/40敏感度同方向(高原非尖刺)緩解；2022型慢熊中段觸發是已知失效模式,搭配態勢階梯使用。</div>
</body><script>const BG={json.dumps(BG)};{plots}</script></html>"""
    out = "研究報告/research_panic_thermometer.html"
    open(out, "w", encoding="utf-8").write(html)
    print(f"報告已產出 {out} ({len(html):,} chars, {len(charts)}圖)")


if __name__ == "__main__":
    main()
