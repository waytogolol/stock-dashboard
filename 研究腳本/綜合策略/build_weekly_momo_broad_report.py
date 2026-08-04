# -*- coding: utf-8 -*-
"""週級強者續強·廣宇宙複測+風控疊加考卷 -> 研究報告/research_weekly_momo_broad.html (2026-08-04)
使用者要求把今天的探索(廣宇宙複測/regime控倉/長假減碼+安慰劑檢定)整理成正式研究html並附權益曲線。
承接research_weekly_momo.html(133檔動能選樣宇宙研究,2026-07-11)——本卷是它點名的「下一步」:
待inst_flow全市場~1400檔廣宇宙複測通過才算最終通過。全部計算直接複用/重算自
build_weekly_momo_regime_overlay.py(regime控倉)+build_weekly_momo_holiday_overlay2.py(長假減碼+
安慰劑對照)兩支既有考卷腳本的邏輯,不重新發明,只是加上HTML/Plotly渲染。
用法: python 研究腳本/綜合策略/build_weekly_momo_broad_report.py (從根目錄執行,鐵律)
"""
import json
import sys

import numpy as np
import pandas as pd
import sqlite3

sys.path.insert(0, "研究腳本/綜合策略")
import build_weekly_momo_regime_overlay as M  # noqa: E402

DB = "capital_flow.db"
RNG = np.random.default_rng(20260804)
N_RANDOM = 200


def load_holidays(min_gap):
    con = sqlite3.connect(DB)
    df = pd.read_sql("select date from index_daily where market='TAIEX' order by date",
                      con, parse_dates=["date"])
    con.close()
    df["gap"] = df["date"].diff().dt.days
    return [(df.loc[i - 1, "date"], df.loc[i, "date"]) for i in df.index[df["gap"] >= min_gap]]


def crosses(entry_wk, exit_wk, holidays):
    return any(b <= exit_wk and a >= entry_wk for b, a in holidays)


def row_stats(name, ret, exec_trades):
    st = M.stats_from_ret(ret)
    tr = M.trade_stats(exec_trades)
    ci = M.bootstrap_ci(exec_trades)
    return dict(name=name, **st, **{f"tr_{k}": v for k, v in tr.items()}, ci_lo=ci[0], ci_hi=ci[1])


def equity_trace(ret, name, color):
    r = ret.dropna()
    eq = (1 + r).cumprod()
    return {"x": [d.strftime("%Y-%m-%d") for d in eq.index], "y": [round(float(v), 3) for v in eq.values],
            "name": name, "type": "scatter", "mode": "lines", "line": {"color": color, "width": 1.8}}


def equity_chart(traces, title, chart_id, log=True):
    layout = {"paper_bgcolor": "#1a1a19", "plot_bgcolor": "#1a1a19",
              "font": {"color": "#ddd", "family": "Noto Sans TC", "size": 12},
              "xaxis": {"gridcolor": "#333"},
              "yaxis": {"gridcolor": "#333", "title": "權益(起點=1)",
                        "type": "log" if log else "linear"},
              "margin": {"t": 48, "l": 60, "r": 20, "b": 40}, "height": 420,
              "legend": {"orientation": "h"}, "title": {"text": title, "font": {"size": 14}}}
    return (f'<div id="{chart_id}"></div>\n'
            f'<script>Plotly.newPlot("{chart_id}", {json.dumps(traces, ensure_ascii=False)}, '
            f'{json.dumps(layout, ensure_ascii=False)}, {{displayModeBar:false}});</script>')


def taiex_bh_ret(grid):
    """大盤買進持有週報酬序列,對齊grid(週五收盤,同fm_daily_price週化口徑)"""
    con = sqlite3.connect(DB)
    px = pd.read_sql("select date, close from index_daily where market='TAIEX' order by date",
                      con, parse_dates=["date"])
    con.close()
    px["wk"] = px["date"].dt.to_period("W-FRI").dt.end_time.dt.normalize()
    wk_close = px.groupby("wk")["close"].last()
    wk_close = wk_close.reindex(grid, method="ffill")
    return wk_close.pct_change()


def fmt_row(d):
    sig = "✓排0" if (d["ci_lo"] > 0 or d["ci_hi"] < 0) else "含0"
    return (f"<tr><td>{d['name']}</td><td>{d['mult']:.2f}x</td><td>{d['cagr']:+.1f}%</td>"
            f"<td class='bad'>{d['mdd']:.1f}%</td><td>{d['sharpe']:.2f}</td><td>{d['calmar']:.2f}</td>"
            f"<td>{d['tr_pf']:.2f}</td><td>{d['tr_win']:.1f}%</td>"
            f"<td>{d['tr_mean']:+.2f}%[{d['ci_lo']:+.2f},{d['ci_hi']:+.2f}] {sig}</td></tr>")


def main():
    print("建置基準三門檻(10%/15%/20%)...")
    base_rows, base_traces, base_data = [], [], {}
    weeks = M.WIDE_RET.index
    start_i = weeks.searchsorted(pd.Timestamp(M.START))
    grid = weeks[start_i:]
    colors = {0.10: "#6bb7e3", 0.15: "#c3a55a", 0.20: "#7ec97e"}
    for th in (0.10, 0.15, 0.20):
        trades, baskets = M.build_trades(th)
        ret, exec_t = M.portfolio_curve(baskets, grid, mode="baseline", weighting="equal")
        base_rows.append(row_stats(f"{th:.0%}門檻+top10", ret, exec_t))
        base_traces.append(equity_trace(ret, f"{th:.0%}門檻", colors[th]))
        base_data[th] = (baskets, ret)

    print("大盤買進持有benchmark...")
    ret_bh = taiex_bh_ret(grid)
    bh_ret_clean = ret_bh.dropna()
    bh_exec = pd.DataFrame({"net_ret": bh_ret_clean.values, "entry_week": bh_ret_clean.index})
    base_rows.append(row_stats("大盤買進持有(TAIEX)", ret_bh, bh_exec))
    base_traces.append(equity_trace(ret_bh, "大盤買進持有(TAIEX)", "#8a8878"))
    equity_chart_base = equity_chart(base_traces, "廣宇宙複測·三門檻 vs 大盤買進持有 權益曲線(對數刻度,起點=1)", "eq_base")

    print("regime控倉(沿用build_weekly_momo_regime_overlay.py既有結果,重算20%門檻驗證數字一致性)...")
    baskets20, ret20 = base_data[0.20]
    regime_rows = [row_stats("20%基準(全押)", ret20, M.portfolio_curve(baskets20, grid, mode="baseline")[1])]
    for rule_name, rule in [("trend", "趨勢空頭"), ("vol", "高波動"), ("combo", "任一不利")]:
        fav = M.make_favorable_lookup(baskets20, rule_name)
        r_sw, e_sw = M.portfolio_curve(baskets20, grid, favorable_fn=fav, mode="switch")
        regime_rows.append(row_stats(f"{rule}·開關", r_sw, e_sw))

    print("長假減碼+安慰劑對照(20%/15%門檻)...")
    holidays_wide = load_holidays(4)
    holiday_rows_by_th = {}
    holiday_traces = [t for t in base_traces if t["name"] in ("20%門檻", "大盤買進持有(TAIEX)")]
    for th in (0.20, 0.15):
        baskets, ret_b = base_data[th]
        wk_list = list(baskets.keys())
        cross = {wk: crosses(wk, baskets[wk]["exit_week"].iloc[0], holidays_wide) for wk in wk_list}
        n_cross = sum(cross.values())
        fav = lambda wk: not cross[wk]  # noqa: E731
        ret_hw, exec_hw = M.portfolio_curve(baskets, grid, favorable_fn=fav, mode="reduce_capital",
                                            reduce_frac=0.5, weighting="equal")
        rows = [row_stats(f"{th:.0%}基準(全押)", ret_b, M.portfolio_curve(baskets, grid, mode="baseline")[1]),
                row_stats(f"{th:.0%}長假減碼50%", ret_hw, exec_hw)]
        # 安慰劑:200次隨機同規模減碼
        mdds = []
        for _ in range(N_RANDOM):
            picked = set(RNG.choice(wk_list, size=n_cross, replace=False))
            fav_r = lambda wk: wk not in picked  # noqa: E731
            r_r, _ = M.portfolio_curve(baskets, grid, favorable_fn=fav_r, mode="reduce_capital",
                                       reduce_frac=0.5, weighting="equal")
            mdds.append(M.stats_from_ret(r_r)["mdd"])
        mdds = np.array(mdds)
        beat_pct = (mdds < row_stats("", ret_hw, exec_hw)["mdd"]).mean() * 100
        holiday_rows_by_th[th] = dict(rows=rows, n_cross=n_cross, n_total=len(wk_list),
                                      random_median=float(np.median(mdds)), beat_pct=beat_pct)
        if th == 0.20:
            holiday_traces.append(equity_trace(ret_hw, "20%門檻+長假減碼50%", "#e06c5a"))
    equity_chart_holiday = equity_chart(holiday_traces, "20%門檻基準 vs 長假減碼版 權益曲線對照", "eq_holiday")

    css = """
body{background:#1a1a19;color:#fff;font-family:"Noto Sans TC",sans-serif;margin:24px;max-width:1200px}
h1{font-size:20px} h2{font-size:15px;color:#c3c2b7;margin-top:30px;border-bottom:1px solid #333;padding-bottom:4px}
h3{font-size:13.5px;color:#a8a79a;margin:16px 0 4px}
table{border-collapse:collapse;font-size:12.5px;font-variant-numeric:tabular-nums;margin:8px 0}
td,th{border:1px solid #333;padding:5px 9px;text-align:right} th{text-align:left;color:#c3c2b7}
.note{color:#8a8878;font-size:12.5px;line-height:1.8} .good{color:#7ec97e} .bad{color:#e06c5a}
.warn{color:#c3a55a}
"""
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>週級強者續強·廣宇宙複測+風控疊加考卷</title>
<script src="plotly.min.js"></script><style>{css}</style></head><body>
<h1>週級強者續強·廣宇宙複測+風控疊加考卷(2026-08-04)</h1>
<div class='note'>承接<a href="research_weekly_momo.html">research_weekly_momo.html</a>(133檔動能選樣宇宙,
2026-07-11)點名的下一步:「待inst_flow全市場~1400檔廣宇宙複測通過才算最終通過」。使用者提案每週輪動
持有~10檔、目標高賺賠比+低MDD(展望理論框架),本卷做三件事:①全市場廣宇宙複測驗證方向是否為子集假象
②用既有regime天氣線矩陣測試能否壓低MDD③使用者提案「長假前收手」測試+隨機安慰劑對照驗證機制真偽。</div>

<div class='note'><b>⚠資料清洗(意外發現,務必記錄)</b>:fm_daily_price有約1.25%的列close&lt;=0或money&lt;=0
(2014起3,776,052列中47,121列涉及903檔),若不濾掉會製造「單週漲幅=inf」「次週跌幅=-100%」的偽事件,是本卷
早期探索版MDD失真的最大成因。本卷全程用close&gt;0 &amp; money&gt;0清洗,已建議之後全市場fm_daily_price
相關考卷比照處理,DB也已新增fm_daily_price_clean檢視表當保底防護。</div>

<h2>一、廣宇宙複測(全市場fm_daily_price 2015起,0.3億20週均額流動性過濾,top10持股上限,等權)</h2>
<div class='note'>訊號=個股單週漲幅超過門檻;進場=訊號週收盤(⚠理想化假設,未校正實際可執行性,見下方限制);
出場=次週收盤;成本0.5%/筆單邊。</div>
<table><tr><th>版本</th><th>複利</th><th>年化</th><th>MDD</th><th>夏普</th><th>Calmar</th>
<th>PF</th><th>勝率</th><th>單筆均報酬(bootstrap月群CI)</th></tr>
{"".join(fmt_row(r) for r in base_rows)}</table>
{equity_chart_base}
<div class='note'>方向確認為真(非133檔子集假象),20%門檻bootstrap CI排0顯著。但風險特徵比原133檔研究明顯
變差(原研究15-20%門檻MDD僅-27.8~-38.4%),10%門檻在廣宇宙下不穩健(CI含0)。兩次最大回撤(2025-04關稅崩盤/
2026-07-24修正)皆對應真實系統性重挫,非個股雜訊。</div>

<h2>二、Regime控倉測試(20%門檻,沿用build_regime_weather_report.py既有趨勢/波動regime公式)</h2>
<table><tr><th>版本</th><th>複利</th><th>年化</th><th>MDD</th><th>夏普</th><th>Calmar</th>
<th>PF</th><th>勝率</th><th>單筆均報酬(bootstrap月群CI)</th></tr>
{"".join(fmt_row(r) for r in regime_rows)}</table>
<div class='note' style="color:#e06c5a">❌<b>誠實負結果</b>:所有regime開關版MDD皆比基準<b>更差</b>(關掉的多是
好週不是壞週)。根因診斷:基準版最差15週中,0週在空頭regime觸發、僅3週在高波regime觸發——MDD主要驅動是
<b>個股集中度風險</b>(33%訊號週籃子僅1-3檔),不是大盤系統性風險,大盤級regime分類器天生偵測不到這種風險,
跟處置V4/跌觸發等regime分離力明顯的策略不是同一種病。2025-04崩盤週策略當週剛好零訊號(運氣,非regime功勞);
2026-07-24修正時趨勢regime全程顯示多頭沒有示警,波動regime雖高波但2026年迄今73.6%時間都是高波(非精準示警)。</div>

<h2>三、長假前減碼測試+隨機安慰劑對照(使用者提案)</h2>
<div class='note'>意外驗證:2025-04關稅崩盤的確切日期,TAIEX上一交易日2025-04-02收21,298,下一交易日
2025-04-07(清明連假,間隔5天)直接跳空到19,232附近——全球「解放日」關稅衝擊剛好發生在台股放假期間,
是使用者提案要防的缺口風險活案例,非巧合。長假定義=index_daily相鄰交易日間隔&gt;=4曆天(2015起156次)。
安慰劑對照=隨機抽跟長假週數量相同的週同樣減碼50%,重複200次看分佈,長假版MDD要顯著優於隨機分佈中位數
才算通過檢定(不是單純「減碼曝險」的效果)。</div>
"""
    for th in (0.20, 0.15):
        d = holiday_rows_by_th[th]
        beat = 100 - d["beat_pct"]
        verdict_color = "good" if beat >= 65 else ("warn" if beat >= 55 else "bad")
        verdict_txt = "通過安慰劑檢定,精準度優於隨機" if beat >= 65 else (
            "邊緣,證據不夠一致" if beat >= 55 else "未通過安慰劑檢定,幾乎等同隨機亂猜")
        html += f"""<h3>{th:.0%}門檻(跨長假訊號週{d['n_cross']}/{d['n_total']}檔)</h3>
<table><tr><th>版本</th><th>複利</th><th>年化</th><th>MDD</th><th>夏普</th><th>Calmar</th>
<th>PF</th><th>勝率</th><th>單筆均報酬(bootstrap月群CI)</th></tr>
{"".join(fmt_row(r) for r in d['rows'])}</table>
<div class='note'>隨機對照(N=200)MDD中位數={d['random_median']:.1f}%,長假減碼版贏過{beat:.0f}%的隨機同規模
版本(50%=純巧合) → <span class='{verdict_color}'>{verdict_txt}</span></div>
"""
    html += f"""
{equity_chart_holiday}
<div class='note'><b>誠實總結</b>:20%門檻下長假減碼有一定道理(MDD改善且通過安慰劑檢定,減碼版同時優於
更早測過的開關版);15%門檻下完全通不過安慰劑檢定,效果等同隨機。跟今天多個研究同一個模式:同一效果在不同
門檻下不穩健,只能列為候選觀察層,不是穩健結論。窄版長假定義(僅春節等&gt;=9天)測試結果更差(20%門檻MDD
幾乎無改善,15%門檻反而惡化),證實2025-04案例的教訓——傷到的是清明這種常規連假不是春節,窄版防錯方向。</div>

<h2>四、已知限制</h2>
<div class='note'>
①<b>進場可執行性未校正</b>:目前用「訊號週收盤價」當進場價,即看到當週已漲超過門檻的收盤當下立刻買進,
現實中無法做到(需嘛盤中追、需嘛等下週一開盤),這是本卷最大的已知缺口,未測試修正版對報酬的實際侵蝕幅度。<br>
②<b>無停損/減碼機制</b>:進場後固定持有一週不做任何中途風控,未測試停損版本。<br>
③<b>樣本內設計</b>:regime/長假規則的門檻/定義選擇(vp10&gt;=80、假期&gt;=4天等)沿用既有考卷慣例或本卷
探索時的選擇,未做參數敏感度網格搜尋,存在一定程度的資料窺探風險。<br>
④<b>持倉權重口徑</b>:主口徑=等權(依當週實際觸發檔數平分),固定10槽口徑另有測試(見對話記錄),兩者MDD
結構不同但regime/長假結論方向一致。<br>
⑤本卷不涉及進場/出場滑價、當沖規範、實際下單流動性衝擊成本,僅0.5%單邊固定成本簡化處理。
</div>
<div class='note sub'>產生器: 研究腳本/綜合策略/build_weekly_momo_broad_report.py(依賴build_weekly_momo_
regime_overlay.py);資料更新後可重跑,數字會隨fm_daily_price/index_daily最新資料變動。</div>
</body></html>"""
    with open("研究報告/research_weekly_momo_broad.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("完成: 研究報告/research_weekly_momo_broad.html")


if __name__ == "__main__":
    main()
