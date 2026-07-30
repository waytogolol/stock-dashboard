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


def v4_v5_dated_curves():
    """V4/V5單利累積曲線(每筆1單位,依出場日排序,剔人工管制毒格,扣0.45%成本)。
    v4/v5 panel無日期欄→從disposition+價格重算日期化交易(口徑同原卷)。"""
    conn = sqlite3.connect("capital_flow.db")
    disp = pd.read_sql("SELECT * FROM disposition", conn)
    px = pd.read_sql("SELECT code, date, open, close FROM fm_daily_price ORDER BY code, date", conn)
    conn.close()
    px["date"] = pd.to_datetime(px.date)
    stocks = {c: g.sort_values("date").reset_index(drop=True) for c, g in px.groupby("code")}
    for c in ("start_date", "end_date"):
        disp[c] = pd.to_datetime(disp[c], errors="coerce")
    disp = disp.dropna(subset=["start_date", "end_date"])
    disp = disp[~disp.reason.astype(str).str.contains("人工管制")]
    t4, t5 = [], []
    for _, e in disp.iterrows():
        g = stocks.get(e.code)
        if g is None:
            continue
        dts = g.date
        s = np.searchsorted(dts.values, np.datetime64(e.start_date))
        en = np.searchsorted(dts.values, np.datetime64(e.end_date), side="right") - 1
        n = len(g)
        if s >= n or en <= s or en - s > 25 or en - s < 6 or en + 1 >= n:
            continue
        c_, o_ = g.close.values, g.open.values
        if o_[en + 1] <= 0:
            continue
        d_exit = dts.iloc[en + 1]
        if c_[s + 2] > 0:
            t4.append((d_exit, (o_[en + 1] / c_[s + 2] - 1) * 100 - 0.45))
        if en - 2 > s and c_[en - 2] > 0:
            t5.append((d_exit, (o_[en + 1] / c_[en - 2] - 1) * 100 - 0.45))

    def curve(tr):
        s = pd.DataFrame(tr, columns=["d", "r"]).groupby("d").r.sum().sort_index().cumsum()
        return s, len(tr)
    c4, n4 = curve(t4)
    c5, n5 = curve(t5)
    return c4, n4, c5, n5


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

    # 圖5: V4 vs V5 單利累積曲線(2026-07-19 V5補章,使用者要求)
    c4s, n4, c5s, n5 = v4_v5_dated_curves()
    v5p = pd.read_pickle("tmp_disposition_v5_panel.pkl")
    v5_all = v5p.v5.dropna()
    b_dn = v5p[v5p.pre_path <= -5].v5.dropna()
    b_md = v5p[(v5p.pre_path > -5) & (v5p.pre_path < 5)].v5.dropna()
    b_up = v5p[v5p.pre_path >= 5].v5.dropna()

    def _tr(s, name, col):
        w = s.resample("W").last().dropna()
        return {"x": [d.strftime("%Y-%m-%d") for d in w.index],
                "y": [round(float(v), 1) for v in w.values], "name": name,
                "type": "scatter", "mode": "lines", "line": {"color": col, "width": 2}}
    charts.append(("chart_v5", [_tr(c4s, f"V4 第3日→出關開盤(n={n4:,})", BLUE),
                                _tr(c5s, f"V5 倒數第3日→出關開盤(n={n5:,})", "#c3a55a")],
                   {"title": "V4 vs V5 單利累積(每筆1單位,Σ淨額%,剔人工管制毒格,同尺對照)",
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
<h1>恐慌流動性提供研究：漲停・恐慌梯度・處置股（判決版 2026-07-16・V5補章 07-19・處置完整檔案 07-29）</h1>
<p class="note">一句話：短線 alpha 不在「追強」而在「接非資訊性的被迫賣壓」——漲停後追買全滅；
強勢股暴力回檔的尾盤接刀、處置股流動性凍結週期的中段進場，是兩個過驗證的口袋。
本報告數字全部扣 0.45% 來回成本；產生器 build_panic_liquidity_report.py。</p>

<h2>⚡ 處置股交易員速查表（只想知道怎麼做的，看這張就夠）</h2>
<table>
<tr><th>項目</th><th>做法</th><th>歷史數字</th></tr>
<tr class="hl"><td>買點① V4（主力）</td><td style="text-align:left">第<b>3個處置日尾盤</b>收盤買 → <b>出關日開盤</b>賣（抱約8個交易日）</td><td class="good">+3.78%／62%（n=1,878）</td></tr>
<tr><td>買點② V5（短打）</td><td style="text-align:left"><b>倒數第3日尾盤</b>買 → 出關日開盤賣（抱約4日）；只買「處置前段一直跌」的</td><td class="good">前段跌組 +4.14%／66%</td></tr>
<tr><td>出場鐵律</td><td style="text-align:left"><b>出關日開盤走人，不戀棧</b>——出關起連三日是負的，等「出關行情」的人是我們的出場流動性</td><td class="bad">出關後三日 −0.31/−0.55/−0.18</td></tr>
<tr><td>持有中管理</td><td style="text-align:left"><b>不停損</b>（−10%停損8年0正=砍在統計谷底）、<b>不追強加碼</b>；首次收盤跌−10~−15%＝🟢<b>攤平帶</b>用新資金加1單位；−15%以下肉沒了別攤</td><td>攤平配對差 +1.65~+1.80pp</td></tr>
<tr><td>選件優先序</td><td style="text-align:left">①20分盤＞5分盤 ②題材成員加分 ③💰<b>第3日成交值當日全市場排名≤300優先、＞800直接跳過</b>（站上季線限定）④d4w＞0✓＝大戶逆接（信心加分）</td><td>20分+6.96%／排名≤200組+5.72%</td></tr>
<tr><td>⚠避開</td><td style="text-align:left">「人工管制撮合」類、處置前段已漲＞10%的強勢票、成交值排名＞800的雜訊小票</td><td class="bad">人工管制 −4.71%／38%</td></tr>
<tr><td>Regime 警語</td><td style="text-align:left">2022全面熊市＝唯一負年（−0.45%）；跌破季線時💰成交值加分休眠；滾動勝率驟降＝冷regime確認（縮單量），不是崩盤預言</td><td>2022 −0.45%／47%</td></tr>
<tr><td>工具</td><td style="text-align:left">儀表板處置頁（今日行動＋📅日程速覽＋攤平帶行動鈴）；逐筆K棒＝research_disposition_trades.html；XQ行動盤第三檔</td><td>—</td></tr>
</table>

<h2>🗣️ 白話導讀：處置制度是什麼？為什麼有錢賺？（沒接觸過的先讀這段）</h2>
<p class="note">
<b>制度流程：</b>股票短期漲跌太兇、週轉率太高等異常（共13款條件），交易所會先公告為「<b>注意股票</b>」；
注意累積達標——標準道＝10個營業日內6次、30日內12次，快速道＝連續3個營業日觸「款一」（累積漲跌幅）——
就升級為「<b>處置股票</b>」，通常為期10個營業日。處置的內容：第一次＝<b>5分鐘分盤撮合</b>（每5分鐘才撮合一次，
不能隨時成交）；30個營業日內再犯＝第二次處置，升級<b>20分鐘分盤</b>；同時「<b>預收全額款券</b>」＝買股要先付全額現金、
信用交易實質被封。更嚴的「人工管制撮合」是另一種類＝本策略毒格，別碰。</p>
<p class="note">
<b>為什麼會跌：</b>處置把當沖客、隔日沖、融資客全部趕走（不能快速進出＋不能用槓桿），流動性被制度性抽乾——
公告首日中位<b>−1.87%</b>，前兩日是衝擊殺跌段。<b>為什麼會反彈：</b>與一般利空不同，處置有<b>明確的到期日</b>，
資金回流的時點可預期——投機資金在解凍前搶跑回流，<b>倒數第2日＝全週期最強日（+1.43%）</b>。
這就是「流動性凍結週期」：跌是制度造成的（非資訊性），到期解凍是寫在公告上的。</p>
<p class="note">
<b>為什麼第3日進場：</b>逐日解剖（下方圖1）顯示前兩日公告衝擊還在殺，第3日起進入中段築底——第3日尾盤買＝
避開衝擊段、吃完整回流段。<b>為什麼看第3日成交值：</b>進場當天收盤前這數字已完全知道（零前視）；
且處置期間成交值被分盤壓縮（約剩處置前的0.64倍／20分盤0.30倍），第3日還留得住的量＝
被凍結的「真金白銀存量」，量大＝解凍時搶跑回流的力道大；量小到當日排名800名外＝本來就沒人玩的票，
解凍了也沒人回來（+0.00%/50%純雜訊）。</p>

<h2>📋 處置研究線考卷總帳（2026-07-16開線至今全部判決，防忘備查）</h2>
<table>
<tr><th>考卷</th><th>判決</th><th>一句話</th></tr>
<tr class="hl"><td>V4 全段進場</td><td class="good">✅上板</td><td>第3日尾盤買→出關開盤賣 +3.78%/62%，bootstrap排0，扣大盤8年全正</td></tr>
<tr class="hl"><td>V5 搶跑段</td><td class="good">✅上板</td><td>倒數第3日買，只買前段跌組 +4.14%/66%；與V4同事件重疊，擇一或補刀</td></tr>
<tr><td>「出關行情」</td><td class="bad">❌迷思</td><td>出關起連三日負；出關日開盤=我們的出場點</td></tr>
<tr><td>處置公告日做空</td><td class="bad">❌</td><td>edge在公告收盤前反應完，隔日空吃不到</td></tr>
<tr><td>G3純弱勢出關</td><td>🟡觀察</td><td>處置期一路弱勢收尾的，出關後反而跑贏（5分k5+2.61pp LOTO8/8）</td></tr>
<tr><td>d4w（千張大戶4週流向）</td><td class="good">✅信心層</td><td>d4w&gt;0=大戶逆接：20分盤複驗轉正(+5.77pp)、5分盤候選；覆蓋64%僅加分不否決</td></tr>
<tr><td>路徑管理：停損</td><td class="bad">❌</td><td>−10%停損8年0正＝砍在統計谷底；跌破後剩餘段仍為正</td></tr>
<tr class="hl"><td>路徑管理：攤平</td><td class="good">✅上板</td><td>跌−10~−15%新資金攤平 配對差+1.65~1.80pp LOTO8/8；−15%以下別攤</td></tr>
<tr><td>路徑管理：強勢加碼</td><td class="bad">❌</td><td>漲+3%加碼8年0正（均值回歸家族禁追）</td></tr>
<tr><td>騎乘（注意期買等升處置）</td><td class="bad">❌</td><td>升級組從注意首日到處置公告中位只隔1天，run-up早走完</td></tr>
<tr><td>慣犯研究</td><td>📖描述</td><td>340檔慣犯佔54.8%事件；款2棘輪+款6估值咬住；20分盤內慣犯加分、5分盤內減分</td></tr>
<tr><td>容量分析</td><td>📖工具</td><td>第3日成交值≈前20日×0.64(5分)/0.30(20分)；400萬池熱regime 15-20月→1000萬；池上限~3000萬</td></tr>
<tr><td>TOM月曆×V4</td><td class="bad">❌</td><td>月底月初進場的5分盤V4反而較差；被動進場日無法挑，僅倉位參考</td></tr>
<tr><td>比例×人數象限／週級大戶</td><td class="bad">❌封存</td><td>「誰在接」的質地不影響d4w效力；通用籌碼欄位路線關閉</td></tr>
<tr><td>滾動勝率×大盤regime</td><td>🟡同時指標</td><td>勝率驟降=冷regime確認非領先訊號（領先性5/8年、控季線後增量弱）；高勝率端=順風確認較有料</td></tr>
<tr class="hl"><td>💰成交值加分（07-29新）</td><td class="good">✅上板</td><td>五分位完美單調＋凍結驗+5.74pp CI排0；live口徑=當日排名≤300優先/＞800跳過；站上季線限定（詳下專章）</td></tr>
</table>

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

<h2>V5 出關前搶跑段（倒數第3日尾盤買→出關日開盤出，持~4日；2026-07-19補章）</h2>
<p class="note">首發判決在研究紀錄20260716-17場「處置分層補測」(tmp_disposition_v5_panel.pkl)，此前只上了儀表板行動欄
(🔔V5買點鈴)沒進報告——本章補齊。<b>機制</b>：逐日解剖(上圖1)顯示<b>倒數第2日＝全處置週期最強日(+1.43%)</b>，
搶跑資金在出關前回流；V5就只吃這一段，與V4共用同一個出場點(出關日開盤)，等於V4的「前段截短版」，
持有~4日較合短打偏好。<b>使用者原始直覺</b>「倒數三天＋前面一直跌」獲數據證實：</p>
<table>
<tr><th>V5 分層(前段=首日→倒數4日)</th><th>淨中位</th><th>勝率</th><th>n</th></tr>
<tr><td>全樣本</td><td class="good">{v5_all.median():+.2f}%</td><td>{(v5_all > 0).mean() * 100:.0f}%</td><td>{len(v5_all):,}</td></tr>
<tr class="hl"><td>前段一直跌 &lt;−5%（彈簧壓縮）</td><td class="good">{b_dn.median():+.2f}%</td><td>{(b_dn > 0).mean() * 100:.0f}%</td><td>{len(b_dn):,}</td></tr>
<tr><td>前段盤整 −5~+5%</td><td>{b_md.median():+.2f}%</td><td>{(b_md > 0).mean() * 100:.0f}%</td><td>{len(b_md):,}</td></tr>
<tr><td>前段已漲 &gt;+5%（避開）</td><td>{b_up.median():+.2f}%</td><td>{(b_up > 0).mean() * 100:.0f}%</td><td>{len(b_up):,}</td></tr>
</table>
{chart_html.split(chr(10))[4]}
<p class="note">曲線口徑＝單利累積(每筆1單位,Σ淨額%,依出場日排序,剔「人工管制」毒格,扣0.45%成本)，兩線同尺同期。
判讀：V4肉厚(吃全段)、V5短平快(資金週轉率高,單位時間報酬率其實不輸)；<b>兩者同事件高度重疊,不是兩個獨立策略</b>——
實戰擇一段做,或V4為主、錯過第3日買點的事件用V5補刀。加分項與V4同構：20分盤&gt;5分盤、題材成員、前段跌。
毒格同樣適用：「人工管制撮合」類V5也是負(−4.7%族),儀表板已自動標⚠。</p>

<h2>💰 成交值加分專章（2026-07-29考卷，切樣本＋四控全過＝正式上板）</h2>
<p class="note"><b>由來</b>：滾動勝率考卷的探索格「站上季線×大成交值最強」未預註冊→本卷正式驗，
預先聲明三個混淆全控：①大成交值↔20分盤相關（熱票才二進宮）→分盤內部各驗
②絕對億數非平稳（市場8年變大）→年內三分位重驗 ③市場別（上櫃小票多）→市場內重驗。
口徑＝<b>第3處置日（＝V4進場日）當天的成交值</b>，進場當天收盤前完全已知，零前視；
換口徑（公告前20日均額amt20）同向＝穩健。產生器 build_dispo_amt_size.py。</p>
<table>
<tr><th>關卡</th><th>結果</th></tr>
<tr><td>全史五分位梯度</td><td class="good">完美單調：Q1(0.03億)+0.18%/51% → Q5(6.5億)+5.50%/66%</td></tr>
<tr class="hl"><td>切樣本凍結驗</td><td class="good">2019-22找到+2.59pp → <b>2023-26凍結段+5.74pp，月cluster bootstrap CI[+3.80,+8.00]排0＝樣本外更強</b></td></tr>
<tr><td>控①分盤內</td><td class="good">20分內+5.89pp／5分內+3.84pp 皆同向</td></tr>
<tr><td>控②年內三分位</td><td class="good">7/8年正；唯一失效＝2022全面熊市(−2.05pp)</td></tr>
<tr><td>控③市場內</td><td class="good">上市+3.71／上櫃+4.66 皆同向</td></tr>
<tr><td>控④regime交互</td><td>加分只在<b>站上季線</b>(+4.80pp)；跌破季線梯度消失略反(−1.33pp)＝熊市大小票一視同仁</td></tr>
<tr><td>穩健：amt20口徑</td><td class="good">全樣本+5.90pp；凍結段+7.29pp CI[+4.94,+8.87]</td></tr>
</table>
<p class="note"><b>門檻動態化（使用者抓到的關鍵）</b>：絕對億數嚴重非平稳——三分位下切點2019年0.07億→2026年0.89億，
<b>8年漂12倍</b>，寫死億數的規則必過時。四種動態口徑全保住訊號：年內三分位7/8年正、滾動12月V4三分位+4.41pp、
佔當日大盤成交金額比+4.17pp、<b>當日全市場成交值排名+4.55pp（採用：最直觀＋天生抗漂移）</b>。</p>
<table>
<tr><th>當日全市場排名門檻掃描</th><th>門檻內</th><th>門檻外</th><th>差</th></tr>
<tr><td>排名≤100</td><td class="good">+4.94%/64%(n=147)</td><td>+2.42%/58%</td><td>+2.52pp</td></tr>
<tr class="hl"><td>排名≤200（最肥）</td><td class="good">+5.72%/67%(n=437)</td><td>+2.02%/57%</td><td>+3.70pp</td></tr>
<tr class="hl"><td>排名≤300（採用＝💰標記線）</td><td class="good">+4.91%/66%(n=827)</td><td>+1.65%/56%</td><td>+3.26pp</td></tr>
<tr><td>排名≤500</td><td class="good">+4.44%/64%(n=1,532)</td><td>+0.82%/53%</td><td>+3.61pp</td></tr>
<tr class="hl"><td>排名≤800（採用＝⬇跳過線）</td><td class="good">+3.99%/62%(n=2,148)</td><td class="bad">+0.00%/50%＝純雜訊</td><td>+4.00pp</td></tr>
</table>
<p class="note"><b>實戰規則（已上儀表板處置頁）</b>：「第3日值」欄自動附當日排名——站上季線時，
排名≤300標💰優先給單、排名＞800標⬇直接跳過；跌破季線時標記自動隱藏（regime條件寫進程式）。
<b>機制</b>：處置期間成交值被分盤壓縮到剩0.64倍(5分)/0.30倍(20分)，第3日還留得住的量＝被凍結的真金白銀存量，
量大＝解凍搶跑回流力道大；排名800外的票本來就沒人玩，解凍也沒人回來。與容量分析雙重利好：
成交值大＝胃納大（下得了單）＋報酬還更好。</p>

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
    open("研究報告/research_panic_liquidity.html", "w", encoding="utf-8").write(html)
    print(f"報告已產出 research_panic_liquidity.html ({len(html):,} chars, {len(charts)}圖)")


if __name__ == "__main__":
    main()
