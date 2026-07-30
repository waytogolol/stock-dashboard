# -*- coding: utf-8 -*-
"""③雙指數月曆判決報告 -> 研究報告/research_index_seasonal.html (本機,gitignored)
資料源: index_daily/index_tr(fetch_index_daily.py) + earnings_dates(2330)
定位: 觀察層風險月曆非擇時規則。用法: python build_index_seasonal_report.py
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
.good{color:#7ec97e}.bad{color:#e06c5a}
"""
TXT = {"TAIEX": "加權", "TPEx": "櫃買"}


def load(table, mkt, col="close"):
    conn = sqlite3.connect("capital_flow.db")
    s = pd.read_sql(f"SELECT date, {col} AS px FROM {table} WHERE market=? ORDER BY date",
                    conn, params=(mkt,), parse_dates=["date"]).set_index("date").px
    conn.close()
    return s


def monthly(px):
    m = px.resample("ME").last().pct_change().dropna() * 100
    return pd.DataFrame({"ret": m, "y": m.index.year, "m": m.index.month})


def month_stats(mr, y_from=None):
    rows = []
    for m in range(1, 13):
        g = mr[mr.m == m]
        if y_from:
            g = g[g.y >= y_from]
        rows.append({"m": m, "n": len(g), "med": g.ret.median(), "mean": g.ret.mean(),
                     "win": (g.ret > 0).mean() * 100,
                     "min": g.ret.min(), "miny": int(g.loc[g.ret.idxmin(), "y"]),
                     "max": g.ret.max(), "maxy": int(g.loc[g.ret.idxmax(), "y"])})
    return rows


def bar_month(divid, rows, rows15, title, ytitle="中位月報酬%"):
    med = [r["med"] for r in rows]
    return (divid, [{
        "x": [f"{r['m']}月" for r in rows], "y": [round(v, 2) for v in med], "type": "bar",
        "marker": {"color": [GREEN if v > 0 else RED for v in med]},
        "customdata": [[round(r["win"]), round(r15["med"], 2), round(r15["win"])]
                       for r, r15 in zip(rows, rows15)],
        "hovertemplate": ("%{x}: 中位%{y:+.2f}%｜勝率%{customdata[0]}%"
                          "｜2015起 中位%{customdata[1]:+.2f}%/勝%{customdata[2]}%<extra></extra>")}],
        {"title": title, "yaxis": {"title": ytitle}})


def main():
    px = {k: load("index_daily", k) for k in TXT}
    tr = {k: load("index_tr", k, "price") for k in TXT}
    mr = {k: monthly(px[k]) for k in TXT}
    st = {k: month_stats(mr[k]) for k in TXT}
    st15 = {k: month_stats(mr[k], 2015) for k in TXT}

    charts = [
        bar_month("c_tw", st["TAIEX"], st15["TAIEX"],
                  "加權逐月中位報酬 1999-2026（12月最強/9月唯一真弱月；hover含2015起子窗）"),
        bar_month("c_otc", st["TPEx"], st15["TPEx"],
                  "櫃買逐月中位報酬 2005-2026（2月最強但近年衰減/10月最弱）"),
    ]

    # 價差月曆(櫃買-加權)
    a = mr["TAIEX"].set_index(["y", "m"])
    o = mr["TPEx"].set_index(["y", "m"])
    j = o.join(a, lsuffix="_o", rsuffix="_a").dropna()
    j["sp"] = j.ret_o - j.ret_a
    sp_rows, sp15_rows = [], []
    for m in range(1, 13):
        g = j.xs(m, level="m")
        g15 = g[g.index >= 2015]
        sp_rows.append({"m": m, "med": g.sp.median(), "win": (g.sp > 0).mean() * 100, "n": len(g)})
        sp15_rows.append({"med": g15.sp.median(), "win": (g15.sp > 0).mean() * 100})
    charts.append(("c_sp", [{
        "x": [f"{r['m']}月" for r in sp_rows], "y": [round(r["med"], 2) for r in sp_rows],
        "type": "bar", "marker": {"color": [GREEN if r["med"] > 0 else RED for r in sp_rows]},
        "customdata": [[round(r["win"]), round(r15["med"], 2), round(r15["win"])]
                       for r, r15 in zip(sp_rows, sp15_rows)],
        "hovertemplate": ("%{x}: 價差中位%{y:+.2f}pp｜櫃買勝率%{customdata[0]}%"
                          "｜2015起 %{customdata[1]:+.2f}pp/勝%{customdata[2]}%<extra></extra>")}],
        {"title": "櫃買-加權 月價差（正=中小型相對強；9-10月=中小型系統性逆風,兩窗一致）",
         "yaxis": {"title": "價差中位pp"}}))

    # 除息校正: TR-價格 月gap
    gap_tr = {}
    for mkt in TXT:
        p = monthly(px[mkt]).set_index(["y", "m"])
        t = monthly(tr[mkt]).set_index(["y", "m"])
        jj = p.join(t, lsuffix="_p", rsuffix="_t").dropna()
        jj["gap"] = jj.ret_t - jj.ret_p
        gap_tr[mkt] = jj.groupby(level="m").gap.median()
    charts.append(("c_div", [
        {"x": [f"{m}月" for m in range(1, 13)], "y": [round(gap_tr["TAIEX"][m], 2) for m in range(1, 13)],
         "type": "bar", "name": "加權", "marker": {"color": BLUE},
         "hovertemplate": "%{x} 加權: +%{y:.2f}pp<extra></extra>"},
        {"x": [f"{m}月" for m in range(1, 13)], "y": [round(gap_tr["TPEx"][m], 2) for m in range(1, 13)],
         "type": "bar", "name": "櫃買", "marker": {"color": YELLOW},
         "hovertemplate": "%{x} 櫃買: +%{y:.2f}pp<extra></extra>"}],
        {"title": "除息機械拖累（含息報酬指數月報－價格指數月報,中位pp）：7-8月的『弱』大半是除息假象",
         "yaxis": {"title": "含息-價格 月gap pp"}, "barmode": "group"}))

    # 逐年×逐月熱點圖 (diverging: 紅跌/綠漲/中性=0, 色階截±12%避免極端年洗掉對比)
    DIV_SCALE = [[0, RED], [0.5, "#2a2a27"], [1, GREEN]]

    def heat_month(divid, mkt):
        d = {(r.y, r.m): r.ret for r in mr[mkt].itertuples()}
        years = sorted({y for y, _ in d}, reverse=True)
        z = [[round(d[(y, m)], 2) if (y, m) in d else None for m in range(1, 13)] for y in years]
        return (divid, [{
            "type": "heatmap", "x": [f"{m}月" for m in range(1, 13)],
            "y": [str(y) for y in years], "z": z, "zmid": 0, "zmin": -12, "zmax": 12,
            "colorscale": DIV_SCALE, "colorbar": {"title": "%", "outlinewidth": 0},
            "hovertemplate": "%{y}年%{x}: %{z:+.2f}%<extra></extra>", "hoverongaps": False}],
            {"title": f"{TXT[mkt]} 逐年×逐月報酬熱點圖(色階截±12%,精確值看hover)",
             "yaxis": {"dtick": 1, "tickfont": {"size": 10}}}, 30 + len(years) * 17)

    # 逐年×月旬熱點圖 (36欄)
    dec_cells = {}
    for mkt in TXT:
        r = px[mkt].pct_change().dropna()
        dec = pd.cut(r.index.day, [0, 10, 20, 31], labels=["上", "中", "下"])
        grp = pd.DataFrame({"r": r.values, "y": r.index.year, "m": r.index.month, "dec": dec})
        dec_cells[mkt] = grp.groupby(["y", "m", "dec"], observed=True).r.apply(
            lambda s: ((1 + s).prod() - 1) * 100).reset_index()

    def heat_dec(divid, mkt):
        cell = dec_cells[mkt]
        d = {(r.y, r.m, r.dec): r.r for r in cell.itertuples()}
        years = sorted(cell.y.unique(), reverse=True)
        cols = [(m, dd) for m in range(1, 13) for dd in ["上", "中", "下"]]
        z = [[round(d[(y, m, dd)], 2) if (y, m, dd) in d else None for m, dd in cols] for y in years]
        return (divid, [{
            "type": "heatmap", "x": [f"{m}月{dd}" for m, dd in cols],
            "y": [str(y) for y in years], "z": z, "zmid": 0, "zmin": -6, "zmax": 6,
            "colorscale": DIV_SCALE, "colorbar": {"title": "%", "outlinewidth": 0},
            "hovertemplate": "%{y}年%{x}旬: %{z:+.2f}%<extra></extra>", "hoverongaps": False}],
            {"title": f"{TXT[mkt]} 逐年×月旬報酬熱點圖(36欄,色階截±6%)",
             "xaxis": {"tickfont": {"size": 9}}, "yaxis": {"dtick": 1, "tickfont": {"size": 10}}},
            30 + len(years) * 17)

    # ③b全球對照熱點圖(2005+共同窗, 9市場×12月中位)
    GLOB = ["TAIEX", "TPEx", "SPX", "RUT", "SOX", "N225", "KOSPI", "HSI", "SSE"]
    gm = {}
    for k in GLOB:
        gm[k] = mr[k] if k in mr else monthly(load("index_daily", k))
    gz = [[round(float(gm[k][(gm[k].m == m) & (gm[k].y >= 2005)].ret.median()), 2)
           for m in range(1, 13)] for k in GLOB]
    charts.append(("c_glob", [{
        "type": "heatmap", "x": [f"{m}月" for m in range(1, 13)], "y": GLOB, "z": gz,
        "zmid": 0, "zmin": -3, "zmax": 3, "colorscale": DIV_SCALE,
        "colorbar": {"title": "%", "outlinewidth": 0},
        "hovertemplate": "%{y} %{x}: 中位%{z:+.2f}%<extra></extra>"}],
        {"title": "③b全球對照(2005+中位%)：12月強=泛亞共通/2月強=農曆圈+SOX/7月全球其實是強月(台股弱=除息)/8月=亞洲共通逆風",
         "yaxis": {"autorange": "reversed"}}, 360))

    charts.append(heat_month("c_hm_tw", "TAIEX"))
    charts.append(heat_month("c_hm_otc", "TPEx"))
    charts.append(heat_dec("c_hd_tw", "TAIEX"))
    charts.append(heat_dec("c_hd_otc", "TPEx"))

    # 月×旬中位表格
    dec_tbl = {}
    for mkt in TXT:
        cell = dec_cells[mkt]
        dec_tbl[mkt] = {(m, d): cell[(cell.m == m) & (cell.dec == d)].r.median()
                        for m in range(1, 13) for d in ["上", "中", "下"]}

    def dectable(mkt):
        h = "<tr><th>月</th><th>上旬</th><th>中旬</th><th>下旬</th></tr>"
        rows = ""
        for m in range(1, 13):
            cells = ""
            for d in ["上", "中", "下"]:
                v = dec_tbl[mkt][(m, d)]
                cells += f"<td class='{'good' if v > 0 else 'bad'}'>{v:+.2f}</td>"
            rows += f"<tr><th>{m}月</th>{cells}</tr>"
        return f"<table>{h}{rows}</table>"

    # 逐月統計主表
    def mtable(mkt):
        h = ("<tr><th>月</th><th>n</th><th>中位%</th><th>均%</th><th>勝率%</th>"
             "<th>最差(年)</th><th>最佳(年)</th><th>2015起中位%</th><th>2015起勝率%</th></tr>")
        rows = ""
        for r, r15 in zip(st[mkt], st15[mkt]):
            cls = "good" if r["med"] > 0 else "bad"
            rows += (f"<tr><th>{r['m']}月</th><td>{r['n']}</td><td class='{cls}'>{r['med']:+.2f}</td>"
                     f"<td>{r['mean']:+.2f}</td><td>{r['win']:.0f}</td>"
                     f"<td class='bad'>{r['min']:+.1f} ({r['miny']})</td>"
                     f"<td class='good'>{r['max']:+.1f} ({r['maxy']})</td>"
                     f"<td>{r15['med']:+.2f}</td><td>{r15['win']:.0f}</td></tr>")
        return f"<table>{h}{rows}</table>"

    # 台積電法說
    conn = sqlite3.connect("capital_flow.db")
    events = sorted(r[0] for r in conn.execute(
        "SELECT date FROM earnings_dates WHERE market='台' AND code='2330' AND date>='2021-09-01'"))
    conn.close()
    ev_rows = ""
    for mkt in TXT:
        s = px[mkt]
        recs = []
        for e in events:
            t = s.index.searchsorted(pd.Timestamp(e))
            if t - 6 < 0 or t + 10 >= len(s):
                continue
            recs.append({"pre5": (s.iloc[t - 1] / s.iloc[t - 6] - 1) * 100,
                         "post5": (s.iloc[t + 5] / s.iloc[t] - 1) * 100,
                         "post10": (s.iloc[t + 10] / s.iloc[t] - 1) * 100})
        ev = pd.DataFrame(recs)
        ev_rows += (f"<tr><th>{TXT[mkt]} (n={len(ev)})</th>"
                    f"<td>{ev.pre5.median():+.2f}% / {(ev.pre5 > 0).mean() * 100:.0f}%</td>"
                    f"<td>{ev.post5.median():+.2f}% / {(ev.post5 > 0).mean() * 100:.0f}%</td>"
                    f"<td>{ev.post10.median():+.2f}% / {(ev.post10 > 0).mean() * 100:.0f}%</td></tr>")

    # CB錯配
    w = j.reset_index()
    w = w[w.y >= 2019]
    cb_line = (f"2019起：加權月均{w.ret_a.mean():+.2f}%、櫃買月均{w.ret_o.mean():+.2f}%、"
               f"價差月均{w.sp.mean():+.2f}pp → CB池-2%/月基線中只有~0.4pp是中小型效應，"
               f"剩~1.6pp=CB發行股真實劣勢（圈錢股是輸家；礦山報告v2建議雙基準並列）")

    verdicts = [
        ("加權月曆", "12月最強(+2.85%/勝81%,2015起82%,肉在下旬+2.29%=作帳)；9月唯一真弱月(-0.52%/44%,2015起36%)；「五窮六絕」不成立"),
        ("除息假象", "7-8月表面弱=除息機械拖累：含息校正7月+1.80pp/8月+0.86pp，含息7月實際約+1.9%；9月的弱是真的(校正僅+0.12)"),
        ("櫃買月曆", "2月最強(+4.40%/82%)但2015起價差衰減至+0.59pp(2026年-5.1)；10月最弱(-1.62%/38%)"),
        ("中小型相對月曆(最有用)", "櫃買-加權10月-1.84pp/櫃買勝率14%(21年17負,2015起仍-1.68/27%,2025年-8.3pp)+9月-1.29pp = 9-10月中小型策略池系統性逆風月；11月兩窗矛盾不採"),
        ("台積電法說指數層", "事前無方向(加權-0.69%/42%)、事後[+1,+10]加權+0.99%/63% = 龍頭財報後跟漲窗的指數版(n=19觀察層)"),
        ("CB基準錯配複核", cb_line),
        ("③b全球對照五問(2005+,預註冊)", "Q1九月弱非全球(2005+各國九月皆不弱;SPX九月效應是1950-2004現象已死)→台股9月格降信度、僅2015起本地現象；Q2十二月強=泛亞共通(台+2.85/日+2.94/陸+2.06,美僅+0.85)→獲外部支持；Q3二月強=農曆圈成立(櫃買+4.40/上證+2.39/加權+2.70 vs SPX+0.58/N225+0.42),例外SOX+2.92=台股2月可能是紅包×半導體季節性雙疊加；Q4七月全球其實是強月(SPX+2.07/HSI+3.62)→台股7月弱=除息特有鐵證,但**8月弱=亞洲共通**(櫃買-1.58/N225-1.16/KOSPI-0.94/HSI-0.70 vs SPX+1.22)=判決修正:7月純除息假象、8月=除息+亞洲真逆風混合；Q5十月小型股逆風=台美共通(RUT-SPX十月-1.44pp/36% vs 櫃買-加權-1.84pp/14%,美方機制=稅務賣壓/基金十月年度結帳)→10月格結構性增信,9月小型弱台灣特有；(非預註冊發現:4月小型股兩邊都弱-0.65/-1.59pp,標記觀察)"),
        ("定位", "觀察層風險月曆，非擇時規則——12格×多指標必有假陽性，只信有機制故事的格(作帳/除息/9-10月中小逆風)"),
    ]
    vrows = "".join(f"<tr><th>{a}</th><td style='text-align:left'>{b}</td></tr>" for a, b in verdicts)

    divs = "".join(f'<div id="{c[0]}" style="height:{c[3] if len(c) > 3 else 360}px"></div>'
                   for c in charts)
    plots = "".join(
        f"Plotly.newPlot('{c[0]}',{json.dumps(c[1], ensure_ascii=False)},"
        f"Object.assign({json.dumps(c[2], ensure_ascii=False)},BG));" for c in charts)
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>雙指數月曆判決(2026-07-19)</title>
<script src="plotly.min.js"></script><style>{CSS}</style></head><body>
<h1>③雙指數月曆：加權(1999起)×櫃買(2005起) 季節性判決</h1>
<div class="note">資料=index_daily/index_tr(FinMind,fetch_index_daily.py冪等)；錨點自驗:2020-03-19=8681/2022-10-25=12666/2008-11-21=4171全對。
逐月報酬=月末收盤pct_change；旬=日報酬按1-10/11-20/21-31複利；除息校正=含息報酬指數-價格指數。</div>
<h2>📋 執行摘要（判決表）</h2><table>{vrows}</table>
{divs}
<h2>加權逐月統計表</h2>{mtable("TAIEX")}
<h2>櫃買逐月統計表</h2>{mtable("TPEx")}
<h2>月×旬 中位%（左=加權，右=櫃買）</h2>
<div style="display:flex;gap:24px">{dectable("TAIEX")}{dectable("TPEx")}</div>
<h2>台積電法說 前後指數反應（中位/勝率, 2021-09起）</h2>
<table><tr><th></th><th>事前[-5,-1]</th><th>事後[+1,+5]</th><th>事後[+1,+10]</th></tr>{ev_rows}</table>
<h2>已知限制</h2><div class="note">每月格n=21~28只夠看方向；12格×多指標的多重檢定必出假陽性，僅帶機制故事的格子可信；
日曆效應為全球被套利最重的因子，樣本外衰減常見(櫃買2月格已現衰減)；2月受農曆年休市日數影響；
上旬/下旬與月營收公告時點的交互見策略月曆考卷(待跑)。</div>
</body><script>const BG={json.dumps(BG)};{plots}</script></html>"""
    out = "研究報告/research_index_seasonal.html"
    open(out, "w", encoding="utf-8").write(html)
    print(f"報告已產出 {out} ({len(html):,} chars, {len(charts)}圖)")


if __name__ == "__main__":
    main()
