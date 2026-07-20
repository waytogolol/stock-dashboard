# -*- coding: utf-8 -*-
"""大盤低點作戰手冊報告 -> 研究報告/research_bottom_playbook.html
整合: 亞跌五分型(1999+)/⑥低點橫斷面選股/堆疊複驗/鄰居休市旗標/live檢查清單+2026-07-17案例。
溫度計細節見research_panic_thermometer.html(同資料夾可互連)。
用法: python build_bottom_playbook_report.py
"""
import json
import sqlite3

import numpy as np
import pandas as pd

GREEN, RED, BLUE, YELLOW, GRAY, PURPLE = "#7ec97e", "#e06c5a", "#6bb7e3", "#c3a55a", "#8a8878", "#b393d3"
BG = {"paper_bgcolor": "#1a1a19", "plot_bgcolor": "#22221f",
      "font": {"color": "#ddd", "size": 12}, "margin": {"t": 40, "l": 50, "r": 20, "b": 40}}
CSS = """
body{background:#1a1a19;color:#fff;font-family:"Noto Sans TC",sans-serif;margin:24px;max-width:1100px}
h1{font-size:20px} h2{font-size:15px;color:#c3c2b7;margin-top:28px}
table{border-collapse:collapse;font-size:13px;font-variant-numeric:tabular-nums}
td,th{border:1px solid #333;padding:5px 10px;text-align:right} th{text-align:left}
.note{color:#8a8878;font-size:12px;line-height:1.7}
.good{color:#7ec97e}.bad{color:#e06c5a}.warn{color:#c3a55a}
a{color:#6bb7e3;text-decoration:none}
"""
KS = [10, 20, 60]


def main():
    conn = sqlite3.connect("capital_flow.db")

    def load(mkt):
        return pd.read_sql("SELECT date, open, close FROM index_daily WHERE market=? ORDER BY date",
                           conn, params=(mkt,), parse_dates=["date"]).set_index("date")
    tw = load("TAIEX")
    n2 = load("N225").close.pct_change() * 100
    ko = load("KOSPI").close.pct_change() * 100
    sp = load("SPX").close.pct_change() * 100
    conn.close()

    twr = tw.close.pct_change() * 100
    df = pd.DataFrame({"tw": twr}).dropna()
    df = df[df.index >= "1999-02-01"]
    df["n225"] = n2.reindex(df.index)     # 嚴格版: 休市=NaN不觸發
    df["kospi"] = ko.reindex(df.index)
    si = sp.dropna()
    pos = si.index.searchsorted(df.index) - 1
    df["us"] = [si.iloc[p] if p >= 0 else np.nan for p in pos]

    def episodes(days, sep=10):
        p2 = {d: i for i, d in enumerate(tw.index)}
        out, last = [], -10**9
        for d in sorted(days):
            if d in p2 and p2[d] - last >= sep:
                out.append(d)
                last = p2[d]
        return out

    def fwd(d, k):
        t = tw.index.get_loc(d)
        if t + 1 + k < len(tw) and tw.open.iloc[t + 1] > 0:
            return (tw.close.iloc[t + 1 + k] / tw.open.iloc[t + 1] - 1) * 100
        return np.nan

    asia = (df.n225 <= -2) & (df.kospi <= -2)
    configs = [
        ("B 純亞跌(美>-1%)", asia & (df.us > -1), BLUE),
        ("A 美亞同跌", asia & (df.us <= -2), RED),
        ("C 台獨跌", (df.tw <= -2) & ~asia.fillna(False), YELLOW),
        ("D 亞跌台溫和", asia & (df.tw > -1), PURPLE),
    ]
    import random
    random.seed(42)
    base_days = random.sample(list(df.index[:-70]), 800)

    traces, table_rows = [], []
    for name, mask, color in configs + [("全日基準", None, GRAY)]:
        days = base_days if mask is None else episodes(df.index[mask.fillna(False)])
        med, win = [], []
        for k in KS:
            v = pd.Series([fwd(d, k) for d in days]).dropna()
            med.append(round(float(v.median()), 2))
            win.append(round(float((v > 0).mean() * 100)))
        traces.append({"x": [f"k={k}" for k in KS], "y": med, "name": f"{name}(n={len(days)})",
                       "mode": "lines+markers", "line": {"color": color, "width": 2},
                       "marker": {"size": 8}, "customdata": win,
                       "hovertemplate": "%{x}: %{y:+.2f}%｜勝率%{customdata}%<extra>" + name + "</extra>"})
        table_rows.append((name, len(days), med, win))
    charts = [("c_types", traces,
               {"title": "五分型 T+1開盤進場前瞻(1999+,中位%): 關鍵不是跌多深,是美國有沒有事",
                "yaxis": {"title": "中位累積報酬%"}})]

    # B訊號載具權益曲線(觸發T+1開買加權持N日,其餘空手)
    B_eps = episodes(df.index[(asia & (df.us > -1)).fillna(False)])

    def equity(trig_days, hold):
        ret = tw.close.pct_change().fillna(0.0)
        open_ret = (tw.close / tw.open - 1)
        entry_pos = {tw.index.get_loc(d) + 1 for d in trig_days
                     if tw.index.get_loc(d) + 1 < len(tw)}
        eq, val, holding, pos_until = [], 1.0, False, -1
        start = tw.index.searchsorted(pd.Timestamp("1999-02-01"))
        for i in range(start, len(tw)):
            if i in entry_pos and not holding:
                holding = True
                pos_until = i + hold - 1
                val *= (1 + open_ret.iloc[i])
            elif holding:
                val *= (1 + ret.iloc[i])
                if i >= pos_until:
                    holding = False
            eq.append(val)
        return pd.Series(eq, index=tw.index[start:])

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

    eq10 = equity(B_eps, 10)
    eq20 = equity(B_eps, 20)
    bh = tw.close[tw.close.index >= "1999-02-01"]
    bh = bh / bh.iloc[0]
    yrs = (eq10.index[-1] - eq10.index[0]).days / 365.25
    expo10 = len(B_eps) * 10 / len(eq10) * 100
    expo20 = len(B_eps) * 20 / len(eq20) * 100
    charts.append(("c_eq", [
        wtrace(eq10, f"B訊號→加權持10日({eq10.iloc[-1]:.2f}x,MDD{mdd(eq10):.1f}%,曝險~{expo10:.0f}%)", BLUE),
        wtrace(eq20, f"B訊號→加權持20日({eq20.iloc[-1]:.2f}x,MDD{mdd(eq20):.1f}%,曝險~{expo20:.0f}%)", YELLOW),
        wtrace(bh, f"加權買進持有({bh.iloc[-1]:.2f}x,MDD{mdd(bh):.1f}%)", GRAY, "dot")],
        {"title": "B純亞跌載具權益曲線(1999起,起點=1,log)——時機工具:看每單位曝險效率與回撤,非絕對高度",
         "yaxis": {"title": "淨值", "type": "log"}}))
    eq_line = (f"1999起{yrs:.0f}年51 episode:持10日版{eq10.iloc[-1]:.2f}x"
               f"(年化{(eq10.iloc[-1] ** (1 / yrs) - 1) * 100:+.1f}%,MDD{mdd(eq10):.1f}%,曝險僅{expo10:.0f}%)、"
               f"持20日版{eq20.iloc[-1]:.2f}x(MDD{mdd(eq20):.1f}%);買進持有{bh.iloc[-1]:.2f}x(MDD{mdd(bh):.1f}%);"
               f"溫度計載具(2019起2.28x/櫃買2.84x)見溫度計報告")

    # ⑥深跌三分位 + 堆疊
    p6 = pd.read_pickle("tmp_bottom_xsection_panel.pkl")
    p6["b"] = p6.groupby("ep")["dret"].transform(
        lambda s: pd.qcut(s, 3, labels=["深跌", "中", "淺跌"], duplicates="drop"))
    bar1, bar2 = [], []
    for b in ["深跌", "中", "淺跌"]:
        g = p6[p6.b == b]
        bar1.append(round(float(g.reto20.dropna().median()), 2))
        bar2.append(round(float(g.reto60.dropna().median()), 2))
    charts.append(("c_deep", [
        {"x": ["深跌1/3", "中1/3", "淺跌1/3"], "y": bar1, "name": "k20", "type": "bar",
         "marker": {"color": BLUE}, "hovertemplate": "%{x} k20: %{y:+.2f}%<extra></extra>"},
        {"x": ["深跌1/3", "中1/3", "淺跌1/3"], "y": bar2, "name": "k60", "type": "bar",
         "marker": {"color": YELLOW}, "hovertemplate": "%{x} k60: %{y:+.2f}%<extra></extra>"}],
        {"title": "⑥選股端: 溫度計日前150×當日跌幅三分位(T+1開盤,原始中位%)——買被殺最兇的",
         "barmode": "group", "yaxis": {"title": "中位%"}}))

    pa = pd.read_pickle("tmp_asia_sync_stock_panel.pkl")
    # p6補hot旗標(同tmp_bottom_x_addon邏輯: 同main_group當日>=5檔在前150)
    conn2 = sqlite3.connect("capital_flow.db")
    gmap = {}
    for code, mg in conn2.execute("SELECT code, main_group FROM classification WHERE country='台'"):
        gmap.setdefault(code, set()).add(mg)
    conn2.close()
    hot_col = pd.Series(False, index=p6.index)
    for ep, g in p6.groupby("ep"):
        cnt = {}
        for c in g.code:
            for mg in gmap.get(c, ()):
                cnt[mg] = cnt.get(mg, 0) + 1
        for r in g.itertuples():
            sizes = [cnt[mg] for mg in gmap.get(r.code, ())]
            hot_col[r.Index] = bool(sizes and max(sizes) >= 5)
    p6["hot"] = hot_col

    cells = [("溫度計日 深跌×熱族群", p6, True), ("溫度計日 深跌×非熱", p6, False),
             ("B日 深跌×熱族群", pa, True), ("B日 深跌×非熱", pa, False)]
    xs, ys, cols = [], [], []
    for name, pnl, hot in cells:
        g = pnl[(pnl.b == "深跌") & (pnl.hot == hot)]
        v = g.reto60.dropna()
        xs.append(name)
        ys.append(round(float(v.median()), 2) if len(v) else None)
        cols.append(GREEN if hot else GRAY)
    charts.append(("c_stack", [{
        "x": xs, "y": ys, "type": "bar", "marker": {"color": cols},
        "hovertemplate": "%{x}: k60中位%{y:+.2f}%<extra></extra>"}],
        {"title": "深跌×熱族群60日格: 兩個獨立事件集互相複驗(綠=熱族群)",
         "yaxis": {"title": "k60中位%"}}))

    # 表格
    trow = "".join(
        f"<tr><th>{n}</th><td>{cnt}</td>" +
        "".join(f"<td class='{'good' if m > 0 else 'bad'}'>{m:+.2f}% / {w}%</td>"
                for m, w in zip(med, win)) + "</tr>"
        for n, cnt, med, win in table_rows)
    type_table = ("<table><tr><th>分型</th><th>n</th>" +
                  "".join(f"<th>k={k}</th>" for k in KS) + "</tr>" + trow + "</table>")

    checklist = """
<table>
<tr><th>檢查項</th><th style='text-align:left'>判讀</th></tr>
<tr><th>1. 誰在跌?(分型)</th><td style='text-align:left'>日經&KOSPI皆≤-2%且SPX前夜>-1% → B純亞跌=最佳格;美股也≤-2% → A=短線別接;只有台股跌 → C=無邊際;日/韓休市日分型不自動判定,人工讀</td></tr>
<tr><th>2. 台股跟跌了嗎?</th><td style='text-align:left'>B×台也跌≤-1.5%=甜蜜亞型(k10+3.46%/89%);台撐住 → 等補跌完成再進</td></tr>
<tr><th>3. 溫度計並發數</th><td style='text-align:left'>甜蜜格單日並發≥20=出清climax(<a href='research_panic_thermometer.html'>詳報告</a>);B亮=預備、溫度計亮=進場、同亮=最強</td></tr>
<tr><th>4. 維持率水位</th><td style='text-align:left'>&lt;150/140=斷頭出清帶(另一機會層);遠離=無系統性斷頭(健康)</td></tr>
<tr><th>5. 2022型排除檢查</th><td style='text-align:left'>長期月線下陰跌+維持率持續走低+跌停占比低=慢熊陷阱,溫度計唯一死格;急殺型(從高點快跌+climax併發)才是機會形狀</td></tr>
<tr><th>6. 鄰居休市旗標</th><td style='text-align:left'>昨日日/韓大跌+今日該市休市=台股獨自消化區域賣壓=承壓日(勝率42-43%),接刀等鄰居復市</td></tr>
<tr><th>7. 選股端</th><td style='text-align:left'>T+1開盤買前150成交值中當日跌最深1/3(k20+9.83%/72%);持60日挑熱族群(同族群≥5檔在榜);先創高領導股反而別追(V反彈=補漲行情)</td></tr>
<tr><th>8. 倉位</th><td style='text-align:left'>尊重態勢階梯——破月/季線倉位本來就降檔,時機工具=局部進攻非全面翻多</td></tr>
</table>"""

    case = """
<table>
<tr><th>2026-07-17案例套用</th><th style='text-align:left'>讀數</th></tr>
<tr><th>分型</th><td style='text-align:left'>亞跌×台補跌(韓7/17休市變體;日經-4.03%/SPX前夜-0.51%);三週B型環境(韓國危機主導,SPX全程±1.2%)</td></tr>
<tr><th>旗標</th><td style='text-align:left'>⚠鄰居休市旗標命中: 韓7/16殺-6.37%後休市,台股獨自消化→-6.47%</td></tr>
<tr><th>溫度計</th><td style='text-align:left'>7/14=23(第8個episode觸發)→7/17=53=climax級(史上第二高)</td></tr>
<tr><th>態勢/體質</th><td style='text-align:left'>距高-10.6%/破月線/貼季線/半年線上+10.9%;維持率180.7遠離警戒帶</td></tr>
<tr><th>模板</th><td style='text-align:left'>2024-08/2025-04型,非2022型(急殺+climax+維持率健康,2022特徵全不符)</td></tr>
<tr><th>反面</th><td style='text-align:left'>①韓股復市日賣壓釋放(E旗標隔日偏弱)與溫度計T+1進場有張力 ②6/10觸發小敗=5週兩觸發的派發疑慮 ③8月=亞洲共通逆風月</td></tr>
<tr><th>判決</th><td style='text-align:left'>非資訊性賣壓出清高潮,機率偏反彈格;live樣本待驗收</td></tr>
</table>"""

    verdicts = [
        ("核心機制", "「非資訊性賣壓才有反彈」四度統一:個股層(大盤崩拖下水可接/族群獨跌=資訊性死格)→市場層(全球同跌肥/純本土弱)→跨市場分型(B純亞跌最佳/A全球危機別接/C台獨跌無邊際)→休市旗標(賣壓關門外=承壓)"),
        ("B純亞跌訊號", "51 episode(嚴格版)/k10+3.12%/78%/bootstrap P(≤0)=0.0000/兩半期皆有效/閾值高原;台也跌亞型k10+3.46%/89%"),
        ("溫度計", "並發≥20=7大恐慌日全命中,k60+14.2%/83%;與B訊號獨立互補(B=環境預備,溫度計=climax扳機)"),
        ("選股端", "深跌1/3=T+1開k20+9.83%/72%(跳空差≈0=買得到);60日格「深跌×熱族群」在溫度計日(+22.6%)與B日(+10.1%)兩獨立事件集互相複驗"),
        ("載具權益(絕對報酬層)", eq_line),
        ("已知死格", "2022慢熊中段(溫度計/B皆失效)=用檢查項5排除;橫斷面無慢熊指紋,排除靠市場層態勢"),
        ("定位", "全套=觀察層作戰手冊,n小(溫度計7/B型51)不進自動規則;live累積驗收(第8 episode=2026-07-14進行中)"),
    ]
    vrows = "".join(f"<tr><th>{a}</th><td style='text-align:left'>{b}</td></tr>" for a, b in verdicts)

    divs = "".join(f'<div id="{c[0]}" style="height:360px"></div>' for c in charts)
    plots = "".join(
        f"Plotly.newPlot('{c[0]}',{json.dumps(c[1], ensure_ascii=False)},"
        f"Object.assign({json.dumps(c[2], ensure_ascii=False)},BG));" for c in charts)
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>大盤低點作戰手冊(2026-07-19)</title>
<script src="plotly.min.js"></script><style>{CSS}</style></head><body>
<h1>🧭 大盤低點作戰手冊：恐慌日分類系統與選股配方(判決版)</h1>
<div class="note">整合五張考卷: 亞跌五分型(build_asia_sync.py,1999+嚴格版)/⑤溫度計(<a href="research_panic_thermometer.html">獨立報告</a>)/⑥低點橫斷面(build_bottom_xsection.py)/堆疊複驗(build_asia_sync_stock.py)/鄰居休市旗標(tmp_neighbor_holiday.py)。全部T+1開盤進場口徑=可交易、零前視。</div>
<h2>📋 執行摘要(判決表)</h2><table>{vrows}</table>
{divs}
<h2>五分型統計總表(中位%/勝率, T+1開盤)</h2>{type_table}
<h2>🔍 live檢查清單(崩盤日照著跑)</h2>{checklist}
<h2>📌 2026-07-17 live案例(第8 episode,驗收中)</h2>{case}
<h2>已知限制</h2><div class="note">溫度計n=7/B型n=51=觀察層不進自動規則;分型5型×閾值有多重檢定成分(劑量反應+兩半期+bootstrap+機制緩解);
⑥研究池survivorship;熱族群live版無前視但靜態題材版有;亞跌考卷case-inspired自2026-03;
E休市旗標n=30/12僅方向;2022型排除靠人工判讀非量化規則。</div>
</body><script>const BG={json.dumps(BG)};{plots}</script></html>"""
    out = "研究報告/research_bottom_playbook.html"
    open(out, "w", encoding="utf-8").write(html)
    print(f"報告已產出 {out} ({len(html):,} chars, {len(charts)}圖)")


if __name__ == "__main__":
    main()
