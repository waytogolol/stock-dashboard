# -*- coding: utf-8 -*-
"""恐慌流動性研究線判決報告產生器 -> research_panic_liquidity.html(本機,gitignored)
資料源: tmp_panic_converge_results.pkl(組合模擬) + disposition表(逐日路徑重算) + 各考卷定稿數字
用法: python build_panic_liquidity_report.py
"""
import json
import pickle
import sqlite3

import numpy as np
import pandas as pd

GREEN, RED, BLUE, GRAY = "#7ec97e", "#e06c5a", "#6bb7e3", "#8a8878"


def dispo_daily_profile():
    conn = sqlite3.connect("capital_flow.db")
    disp = pd.read_sql("SELECT * FROM disposition", conn)
    px = pd.read_sql("SELECT code, date, open, close FROM fm_daily_price ORDER BY code, date", conn)
    conn.close()
    px["date"] = pd.to_datetime(px.date)
    stocks = {c: g.sort_values("date").reset_index(drop=True) for c, g in px.groupby("code")}
    for c in ("start_date", "end_date"):
        disp[c] = pd.to_datetime(disp[c], errors="coerce")
    disp = disp.dropna(subset=["start_date", "end_date"])
    prof = {}

    def add(k, v):
        if pd.notna(v):
            prof.setdefault(k, []).append(v)
    for _, e in disp.iterrows():
        g = stocks.get(e.code)
        if g is None:
            continue
        dts = g.date
        s = np.searchsorted(dts.values, np.datetime64(e.start_date))
        en = np.searchsorted(dts.values, np.datetime64(e.end_date), side="right") - 1
        if s >= len(g) or en <= s or en - s > 25 or en - s < 6:
            continue
        c_, o_ = g.close.values, g.open.values
        n = len(g)

        def dr(i):
            return (c_[i] / c_[i - 1] - 1) * 100 if 0 < i < n and c_[i] > 0 and c_[i - 1] > 0 else np.nan
        for k, v in [("處置首日", dr(s)), ("第2日", dr(s + 1)), ("第3日", dr(s + 2)), ("第4日", dr(s + 3)),
                     ("倒數第3日", dr(en - 2)), ("倒數第2日", dr(en - 1)), ("末日", dr(en)),
                     ("出關日", dr(en + 1)), ("出關+1", dr(en + 2)), ("出關+2", dr(en + 3))]:
            add(k, v)
    order = ["處置首日", "第2日", "第3日", "第4日", "倒數第3日", "倒數第2日", "末日", "出關日", "出關+1", "出關+2"]
    med = [float(np.median(prof[k])) for k in order]
    win = [float((np.array(prof[k]) > 0).mean() * 100) for k in order]
    return order, med, win


def eq_trace(eq, name, color, weekly=True):
    s = eq.resample("W").last().dropna() if weekly else eq
    return {"x": [d.strftime("%Y-%m-%d") for d in s.index], "y": [round(float(v), 4) for v in s.values],
            "name": name, "type": "scatter", "mode": "lines", "line": {"color": color, "width": 2}}


def main():
    res = pickle.load(open("tmp_panic_converge_results.pkl", "rb"))
    twii = pd.read_pickle("tmp_twii_long.pkl").dropna()
    labels, med, win = dispo_daily_profile()

    charts = []
    # 圖1: 處置逐日路徑(方向冗餘編碼正負,色彩非唯一通道)
    charts.append(("chart_path", [{
        "x": labels, "y": med, "type": "bar",
        "marker": {"color": [GREEN if v > 0 else RED for v in med]},
        "customdata": [round(w) for w in win],
        "hovertemplate": "%{x}: 中位%{y:.2f}%｜勝率%{customdata}%<extra></extra>"}],
        {"title": "處置期間逐日中位報酬(~1,890事件)：跌在首日、漲在倒數2-3日、出關即死",
         "yaxis": {"title": "中位日報酬%"}}))
    # 圖2: V4權益曲線 vs TWII(同起點=1)
    eq = res["dispo_v4"]["equity"]
    tw = twii[(twii.index >= eq.index.min()) & (twii.index <= eq.index.max())]
    tw = tw / tw.iloc[0]
    charts.append(("chart_v4", [eq_trace(eq, "策略", BLUE), eq_trace(tw, "TWII", GRAY)],
                   {"title": "處置V4組合(等權日再平衡=理論上限口徑, log軸)",
                    "yaxis": {"title": "淨值(起點=1)", "type": "log"}}))
    # 圖3: 甜蜜格三載具分開(複利全取 vs 並發上限5 vs TWII;單利Σ見文字)
    curves = pickle.load(open("tmp_sweetspot_curves.pkl", "rb"))
    eq = res["sweetspot"]["equity"]
    tw = twii[(twii.index >= eq.index.min()) & (twii.index <= eq.index.max())]
    tw = tw / tw.iloc[0]
    charts.append(("chart_sw", [eq_trace(eq, "複利全取(MDD-60.6%)", BLUE),
                                eq_trace(curves["eq5"], "並發上限5檔(MDD-24.8%)", "#c3a55a"),
                                eq_trace(tw, "TWII", GRAY)],
                   {"title": "恐慌甜蜜格：載具決定曲線——全取 vs 並發上限5(單筆edge同一個)",
                    "yaxis": {"title": "淨值(起點=1)"}}))

    # 圖4: c1/c13/c4/甜蜜格 單利累積曲線(每筆1單位,比訊號品質的公平載具)
    split = pickle.load(open("tmp_xq_split_curves.pkl", "rb"))
    traces = []
    for k, name, col in [("c4", "c4 接刀(每筆1.50%)", BLUE), ("sweet", "甜蜜格(每筆1.07%)", "#c3a55a"),
                         ("c13", "c13 連兩黑(每筆0.35%)", "#b393d3"), ("c1", "c1 破5日線(每筆0.32%)", GRAY)]:
        s = split[k].resample("W").last().dropna()
        traces.append({"x": [d.strftime("%Y-%m-%d") for d in s.index],
                       "y": [round(float(v), 1) for v in s.values], "name": name,
                       "type": "scatter", "mode": "lines", "line": {"color": col, "width": 2}})
    charts.append(("chart_split", traces,
                   {"title": "獨立策略單利累積(每筆1單位,Σ淨額%)：c1/c13靠右尾彩券,c4/甜蜜格靠基準率",
                    "yaxis": {"title": "累積淨額%"}}))

    base_layout = {"paper_bgcolor": "#1a1a19", "plot_bgcolor": "#1a1a19",
                   "font": {"color": "#ddd", "family": "Noto Sans TC", "size": 12},
                   "xaxis": {"gridcolor": "#333"}, "yaxis": {"gridcolor": "#333"},
                   "margin": {"t": 48, "l": 60, "r": 20, "b": 40}, "height": 360,
                   "legend": {"orientation": "h"}}
    chart_html, chart_js = "", ""
    for cid, data, lay in charts:
        merged = {**base_layout, **lay,
                  "yaxis": {**base_layout["yaxis"], **lay.get("yaxis", {})},
                  "title": {"text": lay["title"], "font": {"size": 14}}}
        chart_html += f'<div id="{cid}"></div>\n'
        chart_js += f'Plotly.newPlot("{cid}", {json.dumps(data, ensure_ascii=False)}, {json.dumps(merged, ensure_ascii=False)}, {{displayModeBar:false}});\n'

    v4, sw = res["dispo_v4"], res["sweetspot"]
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>恐慌流動性提供研究判決版(2026-07-15/16)</title>
<script src="plotly.min.js"></script><style>
body{{background:#1a1a19;color:#fff;font-family:"Noto Sans TC",sans-serif;margin:24px;max-width:1100px}}
h1{{font-size:20px}} h2{{font-size:15px;color:#c3c2b7;margin-top:30px;border-bottom:1px solid #333;padding-bottom:4px}}
table{{border-collapse:collapse;font-size:13px;font-variant-numeric:tabular-nums;margin:10px 0}}
td,th{{border:1px solid #333;padding:5px 12px;text-align:right}} th{{text-align:left;color:#c3c2b7}}
.note{{color:#8a8878;font-size:12px;line-height:1.7}} .good{{color:{GREEN}}} .bad{{color:{RED}}}
.hl{{background:#2a2a28}}</style></head><body>
<h1>恐慌流動性提供研究：漲停・恐慌梯度・處置股（判決版 2026-07-16）</h1>
<p class="note">一句話：短線 alpha 不在「追強」而在「接非資訊性的被迫賣壓」——漲停後追買全滅；
強勢股暴力回檔的尾盤接刀、處置股流動性凍結週期的中段進場，是兩個過驗證的口袋。
本報告數字全部扣 0.45% 來回成本；產生器 build_panic_liquidity_report.py。</p>

<h2>執行摘要判決表</h2>
<table>
<tr><th>考卷</th><th>判決</th><th>關鍵數字</th><th>腳本</th></tr>
<tr><td>漲停×跳空×題材(成員層選股)</td><td class="bad">否定</td><td>同題材配對 −0.63pp/48%＝題材內輪動,漲停選不出贏家</td><td>build_limitup_gap_theme.py</td></tr>
<tr><td>漲停＝題材點火確認(題材層)</td><td>觀察層</td><td>score=4有漲停 +3.03%/59% vs 無 −0.03%；劑量單調；bootstrap p=0.082差臨門一腳→live累積</td><td>build_limitup_confirm_validate.py</td></tr>
<tr><td>漲停後追買/拉回買點(E1/E2/E3)</td><td class="bad">全線否定</td><td>三變體 −2.4~−2.7%/36-41%；「等回檔選到弱者」第四度應驗；鎖死+1.12%被拆穿=2025單年產物</td><td>build_limitup_pullback.py</td></tr>
<tr><td>XQ 15條件解剖</td><td>c4存活</td><td>c4大漲拉回接刀 +2.15%/69%；c7/c9/c10/c12負拖累建議關閉</td><td>build_xq_dipbuy_test.py</td></tr>
<tr class="hl"><td>恐慌梯度甜蜜格(尾盤接刀)</td><td class="good">單筆通過</td><td>+1.53%/61%(n=1,468)；bootstrap CI[+0.04,+2.71] p=0.021；組合層需搭載具</td><td>build_panic_gradient.py</td></tr>
<tr class="hl"><td>🏆處置V4(第3日買→出關開盤出)</td><td class="good">通過</td><td>+3.77%/62%(n=1,871)；bootstrap CI[+2.30,+4.91] p&lt;0.0001；扣TWII八年全正</td><td>build_disposition_event.py</td></tr>
<tr><td>處置「出關行情」</td><td class="bad">迷思</td><td>出關日起連三日負(−0.31/−0.55/−0.18)；江湖課程教的窗口正好是接刀方</td><td>同上</td></tr>
</table>

<h2>統一機制：非資訊性被迫賣壓才有反彈（三個劑量反應）</h2>
<p class="note">①恐慌深度：回檔&lt;10%→≥20%,反彈期望單調上升(跌停級首跌段=死格−1.50%,呼應舊判決「鎖跌停陷阱」)
②處置嚴厲度：5分盤+2.26%/58% → 20分盤+6.96%/71%＝凍結越狠反彈越大
③處置前段跌幅：前段一直跌+4.14%/66% &gt; 已漲+1.57%/55%(彈簧壓縮)。
死格＝大盤平靜+族群共跌(−0.03%/47%)＝題材退潮是「有資訊」的賣壓,不接。
與既有開低承接(要大盤紅=確保個股獨立恐慌)機制統一。</p>

<h2>處置股：完整週期解剖</h2>
{chart_html.split(chr(10))[0]}
<table>
<tr><th>形態</th><th>進場</th><th>出場</th><th>淨中位</th><th>勝率</th><th>n</th></tr>
<tr class="hl"><td>V4 全段</td><td>第3處置日尾盤</td><td>出關日開盤</td><td class="good">+3.78%</td><td>62%</td><td>1,878</td></tr>
<tr><td>V5 搶跑段(前段跌&lt;−5%)</td><td>倒數第3日尾盤</td><td>出關日開盤</td><td class="good">+4.14%</td><td>66%</td><td>526</td></tr>
<tr><td>20分盤子集</td><td>同V4</td><td>同V4</td><td class="good">+6.96%</td><td>71%</td><td>614</td></tr>
<tr><td>毒格:「人工管制撮合」類</td><td>—</td><td>—</td><td class="bad">−4.71%</td><td>38%</td><td>86</td></tr>
</table>
<table>
<tr><th>年</th><th>V4淨中位</th><th>扣TWII</th><th>勝率</th><th>n</th></tr>
<tr><td>2019</td><td>+2.23</td><td>+0.35</td><td>59%</td><td>54</td></tr>
<tr><td>2020</td><td>+5.30</td><td>+3.71</td><td>62%</td><td>299</td></tr>
<tr><td>2021</td><td>+3.32</td><td>+3.23</td><td>62%</td><td>258</td></tr>
<tr><td>2022</td><td class="bad">−0.45</td><td class="good">+1.29</td><td>47%</td><td>113</td></tr>
<tr><td>2023</td><td>+1.07</td><td>+1.30</td><td>58%</td><td>149</td></tr>
<tr><td>2024</td><td>+2.21</td><td>+1.74</td><td>59%</td><td>258</td></tr>
<tr><td>2025</td><td>+3.44</td><td>+1.62</td><td>61%</td><td>224</td></tr>
<tr class="hl"><td>2026</td><td class="good">+6.85</td><td class="good">+3.75</td><td>69%</td><td>519</td></tr>
</table>
<p class="note">擁擠化檢查：若策略被課程普及吃掉,搶跑應提前、末段應變薄——實際倒數第2日/末日在2026反而史上最肥(+2.46/+2.07)。
結構性保護＝預收全額款券(限制大資金)+分盤(限制成交)+處置污名。出關行情迷思的人反而提供我們出關開盤的出場流動性。</p>
{chart_html.split(chr(10))[1]}
<p class="note">組合口徑警語：等權日再平衡+全事件參與=理論上限(複利{v4['compound']:.0f}x讀故事就好,別當實盤預期);
可信的是單筆分布(中位+3.77%/勝率62%/bootstrap CI[{v4['ci_lo']:+.2f},{v4['ci_hi']:+.2f}])、
夏普{v4['sharpe']:.2f}、MDD{v4['mdd']:.1f}%(崩盤窗多部位同跌)、曝險{v4['exposure']:.0f}%、單利Σ{v4['simple_sum']:+.0f}%(n={v4['n']:,})。</p>

<h2>恐慌梯度甜蜜格（與XQ條件的關係：c1/c13淺回檔族獨立=死,活的只有深度恐慌族）</h2>
<table>
<tr><th>獨立策略(同框架)</th><th>淨中位</th><th>勝率</th><th>n</th><th>與甜蜜格重疊</th><th>判定</th></tr>
<tr><td>c1 首破5日線</td><td class="bad">−0.03%</td><td>49%</td><td>2,311</td><td>0%</td><td class="bad">死(2022後歸零=真衰減)</td></tr>
<tr><td>c13 強勢連兩黑</td><td class="bad">+0.11%</td><td>51%</td><td>2,777</td><td>0%</td><td class="bad">死(同上)</td></tr>
<tr><td>c4 大漲拉回接刀</td><td class="good">+2.04%</td><td>66%</td><td>745</td><td>40%</td><td class="good">活,與甜蜜格互補</td></tr>
</table>
<p class="note">關鍵互補：2020連鎖崩跌年甜蜜格−2.86%而c4 +0.33%——c4的長黑條件(開高3%殺低)天然濾掉跳空低開的
連鎖崩跌日=甜蜜格缺的2020型防護。「甜蜜格+長黑」=預註冊考卷候選(防過擬合暫掛)。</p>
{chart_html.split(chr(10))[3]}
<p class="note">曲線判讀：單利累積(每筆1單位)是比訊號品質的公平載具。c1/c13總和為正(Σ+748/+984%)但靠2,300-2,800筆
右尾彩券堆出來(中位≈0),且斜率前陡後平=edge已衰減;c4(745筆)與甜蜜格(1,468筆)斜率穩定=基準率型優勢。</p>
<p class="note">規則：近40日曾漲20%(15日高&gt;40日低×1.2) × 已回檔≥20% × 當日跌−6~−9% × 成交值&gt;1億
→ <b>尾盤收盤買,T+2開盤出</b>。單筆+1.53%/61%(n=1,468,月均16.7件),bootstrap CI[{sw['ci_lo']:+.2f},{sw['ci_hi']:+.2f}] p=0.021。
敏感度=高原非尖刺(全部變體+1.2~+2.0/58-63%);剔除2025仍+1.32/60%;剔除大盤黑K日仍+1.22/61%。</p>
<table>
<tr><th>進出組合</th><th>淨中位</th><th>勝率</th></tr>
<tr class="hl"><td>尾盤進→T+2開出(基準)</td><td class="good">+1.59%</td><td>62%</td></tr>
<tr><td>其中隔夜跳空段</td><td>+1.07%</td><td>64%</td></tr>
<tr><td>隔日開盤進→T+2開出</td><td class="bad">+0.25%</td><td>52%</td></tr>
</table>
<p class="note">尾盤進場是必要條件(2/3的肉在隔夜)。尾部風險=2020型連鎖崩跌(−2.86%/39%)；死格=大盤平靜+族群共跌。
<b>載具對照(單筆edge同一個,Σ單利+1,571%/n=1,468)</b>：複利全取=1.61x/夏普0.37/MDD−60.6%(崩盤日77件齊發整籃跌)
vs <b>並發上限5檔(1/5固定資金,先到先選)=1.92x/夏普0.66/MDD−24.8%,只取636件反而全面更好</b>——
問題從來不在單筆而在資金分配;仍屬「進場時機工具」定位,獨立成策略需再加崩跌gate+死格過濾+選件優先序(未測,防過擬合先掛起)。</p>
{chart_html.split(chr(10))[2]}

<h2>漲停線三層判決（原始問題：同族群該買誰）</h2>
<p class="note">①成員層：漲停/動能排名/均線都選不出題材內贏家(輪動);唯一弱加分=MA20之上(配對+2.04pp/59%但逐年不穩)。
②題材層：score=4+族群內有漲停=點火確認(+3.03 vs −0.03,劑量單調,LOTO全過,p=0.082→觀察層live累積,8月批可註記)。
③飆股率:score=4+漲停+跳空格62.4%(60日內+30%),但case-control顯示飆股僅27.9%事前有漲停=「不可或缺」的預測版不成立。</p>

<h2>上線前檢查清單</h2>
<p class="note">處置V4/V5：①分盤流動性成交可行性(5/20分盤尾盤能吃多少量,掛單策略) ②組合載具設計(同日多件的資金分配,
2026年月均60件遠超資金負載→需選件規則:20分盤優先/前段跌優先) ③覆蓋率47%外的小型股未驗 ④「人工管制撮合」毒格成因待查。
甜蜜格：①2020型連鎖崩跌gate ②與開低承接/處置事件重疊去重 ③崩盤日並發上限。
漲停點火確認：live累積至樣本夠再重驗bootstrap。</p>

<p class="note">資料資產(本輪新增)：fm_daily_price 234萬筆日OHLC(2019起,未調整)、tmp_limit_flags.pkl漲停旗標(34,559次)、
disposition表4,021筆、cb_info 1,799檔+cb_overview 45.7萬筆(2019起)、margin_maintenance_official官方融資維持率(2002起)、
tdcc_weekly回補中(2013起)。面板:tmp_limitup_gap_panel/tmp_limitup_pullback_panel/tmp_panic_gradient_panel/
tmp_disposition_panel+v4+v5/tmp_xq_dipbuy_panel+c4_raw/tmp_panic_sweetspot_events/tmp_panic_converge_results。</p>
<script>{chart_js}</script></body></html>"""
    open("research_panic_liquidity.html", "w", encoding="utf-8").write(html)
    print(f"報告已產出 research_panic_liquidity.html ({len(html):,} chars, {len(charts)}圖)")


if __name__ == "__main__":
    main()
