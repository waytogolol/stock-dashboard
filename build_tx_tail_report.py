# -*- coding: utf-8 -*-
"""H-尾盤結構性賣壓考卷報告 -> 研究報告/research_tx_tail.html (本機,gitignored)
資料源: tmp_tx_tail_full.pkl(build_tx_tail.py產出,1749日全史面板)
判決: 主測1長黑順勢空⏳觀察層 / 主測2週三長紅回吐空✅成立(n=11小樣本)
用法: python build_tx_tail.py && python build_tx_tail_report.py
"""
import json

import numpy as np
import pandas as pd

BLUE, YELLOW, GREEN, RED, GRAY = "#6bb7e3", "#c3a55a", "#7ec97e", "#e06c5a", "#8a8878"
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
COST = 0.0045
WD = "一二三四五"

df = pd.read_pickle("tmp_tx_tail_full.pkl")
blk = df[df.r_main <= -1.3]
red = df[df.r_main >= 1.3]
wred = red[red.wd == 2]

charts, html = [], []


def plot(div, traces, layout_extra, note=""):
    lay = dict(BG)
    lay.update(layout_extra)
    charts.append(f"Plotly.newPlot('{div}',{json.dumps(traces, ensure_ascii=False)},"
                  f"{json.dumps(lay, ensure_ascii=False)},{{displayModeBar:false,responsive:true}});")
    html.append(f'<div id="{div}" style="height:340px"></div>')
    if note:
        html.append(f'<div class="note">{note}</div>')


html.append("<h1>H-尾盤結構性賣壓（台指期全史考卷）</h1>")
html.append(f'<div class="note">全史面板 {len(df)} 交易日（2019-01-02 ~ {df.index.max().date()}，'
            "tx_5min 主力契約 5 分 K）。機制假說：台股當沖偏多生態→強制出場單集中尾盤＝結構性賣壓；"
            "13:25＝券商強平死線。門檻沿用快速驗證版預註冊：長黑/長紅=主段(開盤→13:00)±1.3%，"
            "成本=來回 0.0045%（約 2 點）。</div>")

html.append("<h2>判決摘要</h2>")
html.append('<table><tr><th>考題</th><th>判決</th><th>數字</th></tr>'
            '<tr><th>主測1 長黑順勢空(13:00空→13:45回補)</th><td class="warn">⏳觀察層</td>'
            '<td>n=71 淨中位+0.135%/均+0.160%/勝率65%，月群bootstrap CI[+0.080,+0.229]下緣&gt;0，'
            '但逐年6/8正(2019 n=1、2023 n=4微樣本年拖累)未達預註冊7/8門檻</td></tr>'
            '<tr><th>主測2 週三長紅回吐空</th><td class="good">✅成立</td>'
            '<td>n=11 淨中位+0.089%/勝率82%，CI[+0.064,+0.242]；非週三對照CI[-0.002,+0.101]含0＝週三特異性成立</td></tr>'
            '<tr><th>機制指紋</th><td class="good">✅雙確認</td>'
            '<td>劑量反應單調(主段越深尾殺越重)＋殺盤集中13:00-13:25強平窗(死線後歸零)</td></tr></table>')

# 圖1: 星期×型態 尾盤中位
xw = [f"週{WD[i]}" for i in range(5)]
t_blk = [round(float(blk[blk.wd == i].r_tail.median()), 3) if (blk.wd == i).sum() >= 5 else None for i in range(5)]
t_red = [round(float(red[red.wd == i].r_tail.median()), 3) if (red.wd == i).sum() >= 5 else None for i in range(5)]
plot("c1", [
    {"type": "bar", "name": "長黑日(n=71)", "x": xw, "y": t_blk, "marker": {"color": BLUE},
     "text": [f"{v:+.2f}" if v is not None else "" for v in t_blk], "textposition": "outside"},
    {"type": "bar", "name": "長紅日(n=70)", "x": xw, "y": t_red, "marker": {"color": YELLOW},
     "text": [f"{v:+.2f}" if v is not None else "" for v in t_red], "textposition": "outside"},
], {"title": "星期×型態：尾盤(13:00→13:45)中位報酬%", "barmode": "group",
    "yaxis": {"zeroline": True, "zerolinecolor": "#555"}},
    "長黑尾殺集中在週三至週五（週一二≈0）；長紅日尾盤五天全負＝回吐是常態，週三最徹底（順勢率僅9%＝91%回吐）。")

# 圖2: 劑量反應
labs, meds, ns = [], [], []
for lab, lo_, hi_ in [("-1.3~-2%", -2, -1.3), ("-2~-3%", -3, -2), ("-3~-5%", -5, -3)]:
    g = df[(df.r_main > lo_) & (df.r_main <= hi_)]
    labs.append(f"主段{lab}<br>n={len(g)}")
    meds.append(round(float(g.r_tail.median()), 3))
plot("c2", [{"type": "bar", "x": labs, "y": meds, "marker": {"color": BLUE},
             "text": [f"{v:+.3f}" for v in meds], "textposition": "outside"}],
     {"title": "劑量反應：主段跌越深，尾盤殺越重（尾盤中位%）", "showlegend": False},
     "單調梯度＝機制指紋一：跌深日被套當沖部位越多，強制出場賣壓越重。")

# 圖3: 強平窗分解
plot("c3", [{"type": "bar", "x": ["13:00→13:25<br>(強平窗)", "13:25→13:45<br>(死線後)"],
             "y": [round(float(blk.r_sq.median()), 3), round(float(blk.r_late.median()), 3)],
             "marker": {"color": BLUE},
             "text": [f"{round(float(blk.r_sq.median()), 3):+.3f}", f"{round(float(blk.r_late.median()), 3):+.3f}"],
             "textposition": "outside"}],
     {"title": "長黑日尾盤分解：殺盤集中在強平窗（中位%）", "showlegend": False},
     "機制指紋二：13:25 券商強平死線前殺完（-0.068%），死線後歸零（-0.013%）＝賣壓來源是強制出場非資訊。")

# 圖4: 兩策略累積淨損益
b1 = blk.sort_index()
pnl1 = (-b1.r_tail - COST)
eq1 = pnl1.cumsum()
b2 = wred.sort_index()
pnl2 = (-b2.r_tail - COST)
eq2 = pnl2.cumsum()
plot("c4", [
    {"type": "scatter", "mode": "lines", "name": "主測1 長黑順勢空",
     "x": [str(d.date()) for d in eq1.index], "y": [round(float(v), 3) for v in eq1],
     "line": {"color": BLUE, "width": 2}},
    {"type": "scatter", "mode": "lines", "name": "主測2 週三長紅回吐空",
     "x": [str(d.date()) for d in eq2.index], "y": [round(float(v), 3) for v in eq2],
     "line": {"color": YELLOW, "width": 2}},
], {"title": "累積淨損益（%點數單利加總，扣成本）", "xaxis": {"type": "category", "nticks": 8}},
    f"主測1累積+{eq1.iloc[-1]:.1f}%（71筆），主測2累積+{eq2.iloc[-1]:.1f}%（11筆）。"
    "％口徑=指數報酬，1口大台每+0.1%≈45點×200＝依現價換算。")

# 逐年表
html.append("<h2>主測1 長黑順勢空 逐年</h2>")
rows = "".join(
    f"<tr><th>{y}</th><td>{(g > 0).mean() * 100:.0f}%</td><td>{g.mean():+.3f}%</td>"
    f"<td>{g.median():+.3f}%</td><td>{len(g)}</td></tr>"
    for y, g in pnl1.groupby(b1.year))
html.append(f"<table><tr><th>年</th><th>勝率</th><th>均</th><th>中位</th><th>n</th></tr>{rows}</table>")

html.append("<h2>附註與限制</h2>")
html.append('<div class="note">'
            "①主測1未達上板=逐年一致性差在n=1/n=4微樣本年，CI下緣&gt;0＝邊際真實但單筆小(+0.16%≈70點大台)，"
            "月均不到1筆＝輔助性交易線非主力。②主測2 n=11＝統計過門檻但樣本薄，live累積驗證。"
            "③2026週五結算新制：週五×長紅 n=5 中位-0.031%/回吐60%＝方向與週三窗一致，樣本不足待累積。"
            "④成本假設2點來回＝掛市價微滑價未計；13:00整點進場用13:00根開盤價＝可執行口徑。"
            "⑤面板tmp_tx_tail_full.pkl；考卷build_tx_tail.py；判準預註冊寫於docstring跑前定稿。</div>")

page = ("<!DOCTYPE html><html><head><meta charset='utf-8'><title>H-尾盤結構性賣壓</title>"
        f'<script src="plotly.min.js"></script><style>{CSS}</style></head><body>'
        + "".join(html) + "<script>" + "".join(charts) + "</script></body></html>")
open("研究報告/research_tx_tail.html", "w", encoding="utf-8").write(page)
print(f"已產出 研究報告/research_tx_tail.html ({len(page) / 1e3:.0f}KB, 4圖)")
