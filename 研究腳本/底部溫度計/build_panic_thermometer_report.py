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
        {"title": f"溫度計≥20觸發點位（{len(eps[20])}個episode全是史冊級恐慌日,零前視）",
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

    expo = (len(eps[20]) * 60) / len(eq_tw) * 100
    yrs = (eq_tw.index[-1] - eq_tw.index[0]).days / 365.25
    charts.append(("c_eq", [
        wtrace(eq_tw, f"溫度計→加權60日({eq_tw.iloc[-1]:.2f}x,MDD{mdd(eq_tw):.1f}%)", BLUE),
        wtrace(eq_otc, f"溫度計→櫃買60日({eq_otc.iloc[-1]:.2f}x,MDD{mdd(eq_otc):.1f}%)", YELLOW),
        wtrace(bh, f"加權買進持有({bh.iloc[-1]:.2f}x,MDD{mdd(bh):.1f}%)", GRAY, "dot")],
        {"title": (f"載具權益曲線(起點=1,log)：觸發T+1開盤買指數持60日,曝險僅~{expo:.0f}% "
                   "——時機工具非替代持股,別跟滿倉曲線比絕對高度"),
         "yaxis": {"title": "淨值", "type": "log"}}))
    eq_stats = (f"觸發{len(eps[20])}次/曝險~{expo:.0f}%/年數{yrs:.1f}：溫度計→加權 {eq_tw.iloc[-1]:.2f}x"
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

    ep_list = "、".join(d.strftime("%Y-%m-%d") for d in eps[20])
    verdicts = [
        ("溫度計定義", "甜蜜格(近40日曾漲20%×已回檔≥20%×當日跌6-9%)單日並發觸發數；分布p99=16/max=77；門檻≥20+10日episode去重"),
        ("命中", f"{len(eps[20])}個episode＝{ep_list}，全是史冊級恐慌日，零前視；收盤價逐一手核公開紀錄"),
        ("前瞻", "k20中位+4.93%/勝86%、k60+14.21%/83% vs 全日基準k60+4.88%/70%"),
        ("增量檢查(feedback#11)", "天真訊號「加權日跌≥2%」(n=31) k60僅+5.08%/72%≈基準 → 溫度計增量真實，不是「大跌日買就賺」"),
        ("可交易性(feedback#12)", "T+1開盤版k60+13.53%幾乎不衰減=指數層無跳空吃肉問題"),
        ("唯一死格", "2022-06-22(k60-4.42%)=慢熊中段恐慌≠底，與警戒帶2008慢熊例外同族失效模式"),
        ("與融資警戒帶", "重疊4/7=互補非重複：溫度計抓急殺出清、警戒帶抓斷頭水位；2025-04-08兩者同亮→k60+23%"),
        ("載具權益(絕對報酬層)", eq_stats),
        ("定位", f"市場層時機觀察工具(與甜蜜格/開低承接同層)；n={len(eps[20])}不做bootstrap不進規則；live=崩盤日跑fm_daily_price增量後算當日並發數"),
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
<div class="note">母體=tmp_panic_gradient_panel.pkl甜蜜格1,468筆(對帳分毫不差)，2019-03起；
指數=index_daily；維持率=margin_maintenance_official(濾官方壞點&lt;100)。</div>

<h2>🗣️ 白話導讀（沒看過這條研究線的先讀這段）</h2>
<div class="note" style="color:#c3c2b7;font-size:13px">
<p><b>溫度計在量什麼？</b>「甜蜜格」是個股層的恐慌接刀條件：一檔股票近40日曾經漲過20%（先前是熱門股）、
已經從高點回檔超過20%、今天又再殺6~9%、而且成交值超過1億（有量、殺得動真金白銀）——符合的股票就是
「先前的贏家今天被人不計價砍出來」。溫度計＝<b>今天全市場有幾檔同時長這樣</b>。平常日這個數字是0~3；
p99也才16。<b>某天突然噴到20以上＝全市場的熱門股同一天被集體屠殺</b>，這種日子歷史上每次都對應
教科書級的恐慌事件（疫情崩盤、股災、關稅恐慌…見下方episode明細）。</p>
<p><b>為什麼恐慌日反而是買點？</b>核心機制＝<b>區分「誰在賣」</b>。因為斷頭、停損單、風控砍倉而賣＝
「被迫賣壓」——賣的人不是因為公司變壞而賣，是因為他不得不賣。這種賣壓有個特性：倒完就沒了。
所以被迫賣壓集中引爆的極端日（＝出清、climax），往往就是波段低點。反過來，公司真的變壞的賣壓
（資訊性賣壓）不會一天倒完，接了會繼續跌。溫度計的門檻設計（先漲過→深回檔→今天再急殺→有量）
就是在過濾出「被迫賣」的形狀。本專案口訣：<b>不買止穩，買出清</b>。</p>
<p><b>怎麼用？</b>並發數≥20那天（或隔天開盤，報酬幾乎不衰減，見圖3黃線）進場，抱60個交易日。
歷史全部episode都反彈（見明細表）。<b>什麼時候不能用？</b>唯一失敗＝2022-06-22：已經陰跌好幾個月的
慢熊「中段」出現的恐慌，接了繼續跌——所以看到燈亮先問一句「這是急殺出清，還是陰跌很久之後的中段恐慌？」
急殺型（從高點快速跌下來+溫度計爆表）才是機會形狀。</p>
</div>

<h2>📋 執行摘要（判決表）</h2><table>{vrows}</table>

<h2>🚦 五燈家族總帳（儀表板「大盤溫度計」檢視的五個燈，各自的研究出處與數字）</h2>
<div class="note">本報告主體=第一燈（恐慌溫度計）的完整判決；其餘四燈研究散在各自考卷，此表集中備查。
機制上全是同一家族：<b>從不同角度偵測「被迫賣壓出清」</b>——溫度計量個股層集體屠殺、跌停廣度量「想賣賣不掉」、
警戒帶量斷頭潮水位、雙收斂量指數層「跌夠深+正在急殺」、亞跌B量「源頭（美股）沒事的亞洲恐慌」。</div>
<table>
<tr><th>燈</th><th>白話條件</th><th>進場後歷史表現</th><th>持有期</th><th>警語（何時失靈）</th><th>研究出處</th></tr>
<tr><th>🌡️ 恐慌溫度計</th><td style='text-align:left'>甜蜜格並發≥20檔＝熱門股集體屠殺日</td>
<td>k20 +4.93%/勝86%、k60 +14.21%/83%</td><td>60日</td>
<td style='text-align:left'>2022-06型慢熊中段恐慌≠底（唯一敗格）</td><td style='text-align:left'>本報告(build_panic_thermometer.py)</td></tr>
<tr><th>🌏 亞跌B訊號</th><td style='text-align:left'>日經≤−2%×韓股≤−2%×美股前夜>−1%＝美國沒事的亞洲賣壓</td>
<td>k10 +3.12%/78%（bootstrap過）</td><td>10日</td>
<td style='text-align:left'>8-10月觸發只吃短；美亞同跌(A型)＝全球危機別接</td><td style='text-align:left'>build_asia_sync.py</td></tr>
<tr><th>📉 位階雙收斂</th><td style='text-align:left'>距一年高點−10~−20% × 當日≤−2% × 10日≤−6%＝跌夠深+正在急殺</td>
<td>k20 +3.10%/69%</td><td>20日</td>
<td style='text-align:left'>只回落5~10%＝接刀死區；≤−20%只吃短</td><td style='text-align:left'>tmp_low_coverage.py(46低點覆蓋診斷)</td></tr>
<tr><th>🧱 跌停廣度</th><td style='text-align:left'>收盤跌停≥20家＝連想賣都賣不掉的斷頭日</td>
<td>k10 +3.09%/75%</td><td>20日</td>
<td style='text-align:left'>第一腿spike≠底（2020-01-30跌停286家後k60−6.28%）</td><td style='text-align:left'>tmp_breadth_limit_thermo.py</td></tr>
<tr><th>🚨 融資警戒帶</th><td style='text-align:left'>大盤融資維持率<150%＝券商強制斷頭潮水位</td>
<td>9事件 k60中位+14.4%/78%</td><td>狀態層(非時點)</td>
<td style='text-align:left'>2008慢熊首破例外；帶內要等急跌日(如雙收斂亮)再進</td><td style='text-align:left'>margin_maintenance_official+作戰手冊</td></tr>
</table>
<div class="note">曝險讀數（水位階梯v0,研究稿）＝溫度計0.6＋亞跌B 0.4＋警戒帶0.3＋雙收斂0.3＋跌停廣度0.3，各在自己持有窗內計分，加總封頂1.0。
多燈同亮＝獨立證據疊加（2025-04-08溫度計×警戒帶同亮→k60+23%）。</div>
{divs}
<h2>觸發數≥20 episode明細</h2>{ep_table}
<h2>門檻敏感度（中位% / 勝率%，收盤版）</h2>{sens_table}
<h2>已知限制</h2><div class="note">n={len(eps[20])}無bootstrap；2019起樣本偏多頭(全日基準k60即+4.88%)；
母體=研究池1379檔有存活偏差(影響並發數水位,門檻屬樣本內校準)；2026-06-10 k60未到期；
門檻20為分布事後選定,N=10/40敏感度同方向(高原非尖刺)緩解；2022型慢熊中段觸發是已知失效模式,搭配態勢階梯使用。</div>
</body><script>const BG={json.dumps(BG)};{plots}</script></html>"""
    out = "研究報告/research_panic_thermometer.html"
    open(out, "w", encoding="utf-8").write(html)
    print(f"報告已產出 {out} ({len(html):,} chars, {len(charts)}圖)")


if __name__ == "__main__":
    main()
