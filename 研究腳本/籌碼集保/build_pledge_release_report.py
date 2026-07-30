# -*- coding: utf-8 -*-
"""H-解質考卷判決報告 -> 研究報告/research_pledge_release.html (本機,gitignored)
資料源: tmp_pledge_panel.pkl(build_pledge_release.py產出)
判決: ✅成立=觀察層「內部人高檔解質」警戒標記候選(體系第一個個股層賣方訊號)
用法: python build_pledge_release.py && python build_pledge_release_report.py
"""
import json
import pickle

BLUE, YELLOW, GREEN, RED, GRAY = "#6bb7e3", "#c3a55a", "#7ec97e", "#e06c5a", "#8a8878"
BG = {"paper_bgcolor": "#1a1a19", "plot_bgcolor": "#22221f",
      "font": {"color": "#ddd", "size": 12}, "margin": {"t": 40, "l": 60, "r": 20, "b": 60}}
CSS = """
body{background:#1a1a19;color:#fff;font-family:"Noto Sans TC",sans-serif;margin:24px;max-width:1100px}
h1{font-size:20px} h2{font-size:15px;color:#c3c2b7;margin-top:28px}
table{border-collapse:collapse;font-size:13px;font-variant-numeric:tabular-nums}
td,th{border:1px solid #333;padding:5px 10px;text-align:right} th{text-align:left}
.note{color:#8a8878;font-size:12px;line-height:1.7}
.good{color:#7ec97e}.bad{color:#e06c5a}.warn{color:#c3a55a}.hl{background:#2e2b22}
"""

P = pickle.load(open("tmp_pledge_panel.pkl", "rb"))
ins, oth, ins_set = P["ins"], P["oth"], P["ins_set"]
bA, bB = P["baseA"], P["baseB"]
lo_ci, hi_ci = P["main_boot"]
lo2, hi2 = P["pair_boot"]
d_med = P["pair_med"]

base = ins[~ins.agm]
MAIN = base[(base.pr >= 80) & (base.release_lots >= 1000)]
charts, html = [], []


def med(df, col="x60"):
    return round(float(df[col].dropna().median()), 2)


def win(df, col="x60"):
    v = df[col].dropna()
    return round(float((v > 0).mean() * 100))


def plot(div, traces, layout_extra, note="", height=340):
    lay = dict(BG)
    lay.update(layout_extra)
    charts.append(f"Plotly.newPlot('{div}',{json.dumps(traces, ensure_ascii=False)},"
                  f"{json.dumps(lay, ensure_ascii=False)},{{displayModeBar:false,responsive:true}});")
    html.append(f'<div id="{div}" style="height:{height}px"></div>')
    if note:
        html.append(f'<div class="note">{note}</div>')


html.append("<h1>H-解質：內部人高檔解質＝出貨嫌疑（判決 ✅ 成立）</h1>")
html.append(f'<div class="note">假說錨點：國巨2026-06-01「陳氏傳承」解質2,400+9,000張→6月底作頂。'
            f"資料：pledge_moves（MoneyDJ每日董監質設異動彙整，2019-01~2026-07，978檔皆可對日價）。"
            f"事件=t彙整日，進場口徑t+1開盤（無look-ahead），超額=減同窗TAIEX。"
            f"轉貸剔除{P['n_refi']}列（同日同人設質+解質同量級）。判準預註冊於build_pledge_release.py docstring跑前定稿。</div>")

html.append("<h2>判決摘要</h2>")
html.append(f'<table>'
            f'<tr><th>項目</th><th>數字</th><th>意義</th></tr>'
            f'<tr class="hl"><th>主測：內部人×高檔位階≥80×大額≥1000張×排除轉貸×非股東會季</th>'
            f'<td class="bad">x60中位 {med(MAIN)}% / 勝率{win(MAIN)}%（n={len(MAIN)}/173檔）</td><td>事件後60日大幅跑輸大盤</td></tr>'
            f'<tr><th>同股隨機日基準A</th><td>{round(float(bA.median()), 2)}%（n={len(bA):,}）</td>'
            f'<td>池負飄移確實存在且大（中小型vs TAIEX基準錯配，CB礦山同款）→必須配對</td></tr>'
            f'<tr><th>同股高檔日基準B（pr≥80）</th><td>{round(float(bB.median()), 2)}%（n={len(bB):,}）</td>'
            f'<td>同一批股票自己的高檔日常態</td></tr>'
            f'<tr class="hl"><th>配對差（事件−基準B）</th><td class="bad">{d_med:+.2f}pp，'
            f'bootstrap95%CI[{lo2:+.2f},{hi2:+.2f}]</td><td class="good">CI上緣&lt;0＝解質增量真實非池飄移 → ✅成立</td></tr>'
            f'<tr><th>主測k60股票群bootstrap</th><td>CI[{lo_ci:+.2f},{hi_ci:+.2f}]</td><td>173檔股票群重抽，P(中位≥0)=0.000</td></tr>'
            f'</table>')

# 圖1: 核心對比
rows1 = [("主測：內部人高檔大額解質", med(MAIN), BLUE),
         ("同股隨機日基準A", round(float(bA.median()), 2), GRAY),
         ("同股高檔日基準B(配對)", round(float(bB.median()), 2), GRAY)]
plot("c1", [{"type": "bar", "x": [r[0] for r in rows1], "y": [r[1] for r in rows1],
             "marker": {"color": [r[2] for r in rows1]},
             "text": [f"{r[1]:+.2f}%" for r in rows1], "textposition": "outside"}],
     {"title": "核心對比：事件 vs 同股基準（k60超額中位%）", "showlegend": False,
      "yaxis": {"zeroline": True, "zerolinecolor": "#555"}},
     f"藍=事件組，灰=基準。配對差{d_med:+.2f}pp（CI上緣{hi2:+.2f}&lt;0）＝扣掉「這批股票本來就弱」後，解質仍額外帶來約4pp的60日跑輸。")

# 圖2: 主測時間軸
ks = ["x10", "x20", "x60"]
plot("c2", [{"type": "bar", "x": ["10日", "20日", "60日"], "y": [med(MAIN, k) for k in ks],
             "marker": {"color": BLUE},
             "text": [f"{med(MAIN, k):+.2f}%<br>勝率{win(MAIN, k)}%" for k in ks], "textposition": "outside"}],
     {"title": "主測事件後超額報酬遞延惡化（中位%）", "showlegend": False,
      "yaxis": {"zeroline": True, "zerolinecolor": "#555"}},
     "負向效應隨時間擴大（-1.6→-3.1→-6.9）＝出貨是過程不是單日事件，60日窗才吃滿。")

# 圖3: 機制面板
mech = [("主測(董事長/大股東)", med(MAIN), BLUE),
        ("其他role(董事/經理人)", med(oth[~oth.agm & (oth.pr >= 80) & (oth.release_lots >= 1000)]), GRAY),
        ("股東會季4-6月(混淆組)", med(ins[ins.agm & (ins.pr >= 80) & (ins.release_lots >= 1000)]), GRAY),
        ("內部人高檔大額【設質】", med(ins_set[~ins_set.agm & (ins_set.pr >= 80) & (ins_set.set_lots >= 1000)]), GRAY)]
plot("c3", [{"type": "bar", "x": [m[0] for m in mech], "y": [m[1] for m in mech],
             "marker": {"color": [m[2] for m in mech]},
             "text": [f"{m[1]:+.2f}%" for m in mech], "textposition": "outside"}],
     {"title": "機制三驗證（k60超額中位%）", "showlegend": False,
      "yaxis": {"zeroline": True, "zerolinecolor": "#555"}},
     "①role梯度：董事長/大股東(-6.9)＞董事/經理人(-3.9)＝位階越高資訊越強。"
     "②股東會季組(-1.3)≈基準＝表決權混淆無資訊，排除旗標正確。"
     "③設質對照(-3.7)≈基準＝加質押無訊號——方向專一性支持「解質=賣出前必要步驟」機制。")

# 圖4: 規模梯度(誠實揭露不單調)
sizes = [("<500張", 0, 500), ("500-1000", 500, 1000), ("1000-5000", 1000, 5000), (">=5000", 5000, 10**9)]
hi_df = base[base.pr >= 80]
sv = [med(hi_df[(hi_df.release_lots >= lo) & (hi_df.release_lots < h)]) for _, lo, h in sizes]
plot("c4", [{"type": "bar", "x": [s[0] for s in sizes], "y": sv, "marker": {"color": YELLOW},
             "text": [f"{v:+.2f}%" for v in sv], "textposition": "outside"}],
     {"title": "規模梯度（高檔非股東會季，k60超額中位%）——誠實揭露：不單調", "showlegend": False,
      "yaxis": {"zeroline": True, "zerolinecolor": "#555"}},
     "規模與跌幅非線性（500-1000張最溫和），劑量反應檢查不過＝保留註記；主判準只用≥1000張門檻不用連續劑量。")

# 分層全表
html.append("<h2>分層全表（x=超額中位% / 勝率%）</h2>")
rows = [("🎯主測 高檔≥80×大額≥1000張", MAIN),
        ("高檔×小額<1000張", base[(base.pr >= 80) & (base.release_lots < 1000)]),
        ("中檔位階20-80(全額)", base[(base.pr > 20) & (base.pr < 80)]),
        ("低檔位階≤20(斷頭補提假說,全額)", base[base.pr <= 20]),
        ("股東會季4-6月×高檔大額", ins[ins.agm & (ins.pr >= 80) & (ins.release_lots >= 1000)]),
        ("其他role高檔大額", oth[~oth.agm & (oth.pr >= 80) & (oth.release_lots >= 1000)]),
        ("內部人高檔大額設質", ins_set[~ins_set.agm & (ins_set.pr >= 80) & (ins_set.set_lots >= 1000)]),
        ("內部人低檔大額設質(補提壓力)", ins_set[~ins_set.agm & (ins_set.pr <= 20) & (ins_set.set_lots >= 1000)])]
body = "".join(
    f'<tr{" class=chl" if i == 0 else ""}><th>{lab}</th><td>{len(d)}</td>'
    f'<td>{med(d, "x10"):+.2f}/{win(d, "x10")}</td><td>{med(d, "x20"):+.2f}/{win(d, "x20")}</td>'
    f'<td>{med(d):+.2f}/{win(d)}</td></tr>'
    for i, (lab, d) in enumerate(rows))
html.append(f"<table><tr><th>分層</th><th>n</th><th>10日</th><th>20日</th><th>60日</th></tr>{body}</table>")

# 圖5: 放空載具權益曲線(tmp_pledge_short.pkl;使用者裁示=畫純放空個股不畫hedge;日期軸防類別錯位)
try:
    curves = pickle.load(open("tmp_pledge_short.pkl", "rb"))
    traces = []
    for (name, color) in [("raw k60(純放空)", BLUE), ("raw k20", YELLOW)]:
        ds, eq = curves[name]
        traces.append({"type": "scatter", "mode": "lines", "name": name.replace("raw ", "純放空 "),
                       "x": [str(d.date()) for d in ds], "y": [round(v, 3) for v in eq],
                       "line": {"color": color, "width": 2}})
    plot("c5", traces, {"title": "純放空個股 cap5權益曲線（扣成本）——❌不可做",
                        "xaxis": {"type": "date"}},
     "純放空個股（不對沖），cap5先到先選、1/5資金。k60版終值0.13x／k20版0.51x；"
     "單筆中位為正但均值深負＝肥右尾（60日內翻倍的妖股）屠殺空單；停損-15%版也只救回1.45x/MDD-60%。")
except (FileNotFoundError, KeyError):
    pass

html.append("<h2>放空載具判決（❌不可做）與質押面二題</h2>")
html.append('<table><tr><th>載具/考題</th><th>數字</th><th>判決</th></tr>'
            '<tr><th>對沖空 k60（空股+多台指，cap5）</th><td>單筆中位+3.45%但均值-4.23%，最壞-149%，複利0.35x/MDD-78%</td>'
            '<td class="bad">❌ 中位真、均值假——肥右尾屠殺空單</td></tr>'
            '<tr><th>對沖空 k60＋停損-15%（收盤價停損）</th><td>均值救回+0.94%，但36%筆數停損、最壞仍-86%（跳空/漲停鎖死穿越停損）、1.45x/MDD-60%</td>'
            '<td class="bad">❌ 遠遜於策略棧任何多方線（4-6x）</td></tr>'
            '<tr><th>純放空（不對沖）k60/k20</th><td>複利0.13x/0.51x</td><td class="bad">❌ 更糟（還吃大盤上漲）</td></tr>'
            '<tr><th>質押題②：低檔補提設質=斷頭壓力前兆？（≥1000張×位階≤20，n=760）</th>'
            '<td>事件x60 -7.47% vs 同股低檔日基準-6.48%，配對差-0.99pp CI[-2.83,+0.41]含0</td>'
            '<td class="bad">❌ 低檔股本來就弱，補提無增量</td></tr>'
            '<tr><th>質押題③：高檔設質有增量嗎？（≥1000張×位階≥80，n=295）</th>'
            '<td>事件x60 -3.58% vs 同股高檔日基準-4.36%，配對差+0.79pp CI[-2.62,+2.69]跨零（方向甚至微偏正）</td>'
            '<td class="bad">❌ 無增量——設質=借錢留倉，不是出貨腳印</td></tr>'
            '<tr><th>質押題①：存量位階初篩（526檔，起點偏差警語）</th>'
            '<td>高存量≥90 x60 -6.02% vs 低存量≤50 -6.13%＝無梯度；壓力態(存量≥80×價≤20) -7.52%微差不足以升級</td>'
            '<td class="warn">初篩無假說可升級</td></tr></table>')
html.append('<div class="note">合併結論：<b>方向專一性四度確認——只有「內部人×高檔×解質」帶資訊；'
            '高檔設質(+0.79pp)、低檔補提(-0.99pp)、質押存量(無梯度)全不帶</b>。訊號的正確用法=防守（持股減碼審查/避開名單），'
            '不是進攻（放空）：肥右尾養活本策略棧的多方線，同一條尾巴屠殺空方載具。'
            '腳本：build_pledge_short.py／tmp_pledge_short_stop.py／build_pledge_stock.py（質押二題預註冊）。</div>')

html.append("<h2>live應用與限制</h2>")
html.append('<div class="note">'
            "應用定位＝觀察層「內部人解質警戒」標記（與處置股觀察同級）：持有中個股若觸發主測條件"
            "（內部人解質≥1000張×股價240日位階≥80×非4-6月×非轉貸），列入減碼審查——不是自動出場，是強制看一眼。"
            "限制：①2019+單一窗口無holdout ②規模劑量不單調 ③位階梯度平（中低檔解質raw也弱，"
            "但配對複核只做了高檔主測，其他位階口徑未驗證增量）④維運需fetch_pledge.py每週跑保持live。"
            "面板tmp_pledge_panel.pkl；考卷build_pledge_release.py（預註冊docstring）。</div>")

page = ("<!DOCTYPE html><html><head><meta charset='utf-8'><title>H-解質：內部人高檔解質</title>"
        f'<script src="plotly.min.js"></script><style>{CSS}</style></head><body>'
        + "".join(html) + "<script>" + "".join(charts) + "</script></body></html>")
open("研究報告/research_pledge_release.html", "w", encoding="utf-8").write(page)
print(f"已產出 研究報告/research_pledge_release.html ({len(page) / 1e3:.0f}KB, 5圖)")
