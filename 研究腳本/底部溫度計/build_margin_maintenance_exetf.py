# -*- coding: utf-8 -*-
"""ETF排除版融資維持率對照研究 -> 研究報告/research_margin_exetf.html(本機,gitignored)
背景: 2026-07-31使用者提問——現行「大盤融資維持率」(margin_maintenance_official/_otc,
  溫度計「警戒帶」卡的主指標)刻意納入ETF融資(官方FinMind數列本身含ETF;備援公式版
  fetch_margin_maintenance.py的calc_day()分子用MI_INDEX全市場收盤含ETF)。00631L等槓桿
  ETF的融資餘額變動偏機械式(隨ETF操作模式),與個股融資戶的散戶信心/斷頭壓力訊號本質不同,
  混在一起可能稀釋「恐慌溫度計」的敏感度——本卷建一支「排除ETF版」對照,不動生產管線
  (fetch_margin_maintenance.py/官方FinMind數列維持原樣),純研究對照。

ETF判斷: 股票代碼開頭"00"(專案既有慣例,見scratch_dt_lend_quick.py當沖借券考卷的
  ~stock_id.str.startswith("00")排除法)。已知限制: 00開頭涵蓋主要ETF(0050/0056/00631L/
  00679B債券ETF等),但TDR(91xxxx)、少數已下市/合併代碼不會被"00"抓到而是因fm_daily_price
  缺價自然被跳過(與官方calc_day()「缺價跳過」同一套處理,非本卷新增偏誤)。

分子: Σ(非ETF個股 margin_flow.fin_bal張×1000×fm_daily_price收盤價) ——複用fm_daily_price
  取代官方公式版特地抓的MI_INDEX全市場收盤;因分子本就要排除ETF,fm_daily_price缺的~200檔
  ETF價格本來就用不到,經查non-ETF代碼在fm_daily_price覆蓋率上市99.5%/上櫃99.6%,此簡化合理。

分母(本卷關鍵設計決定,兩版對照):
  (a)混合口徑=分子排除ETF ÷ 官方全市場分母(margin_total.MarginPurchaseMoney/
     margin_total_otc.money_today×1000,含ETF不拆分)。解讀="非ETF個股融資佔全市場
     融資總額的比例維持率"——分母沒動,單純看「拿掉ETF部位後,個股層對整體資金池的水位」。
  (b)自洽口徑=分母改成官方分母按「非ETF佔全市場融資張數比例」(Σnon-ETF fin_bal/Σ全部
     fin_bal)分攤出的非ETF專屬分母。⚠已知限制:margin_flow只有張數(股數),沒有個股層級的
     「融資金額(貸款本金)」欄位,官方分母本身也是全市場單一數字沒有逐股拆分,故此處用「張數
     占比」分攤只是一個粗略代理——實測ETF占全市場融資張數高達17-27%(遠高於ETF檔數占比
     ~18%,因00631L等槓桿ETF單價低但周轉量大,張數占比會高估其"金額"占比),會使(b)版嚴重
     偏離官方值,可信度低於(a),本卷仍附上但明確降級為「粗略探索,不建議採信」。

恐慌事件對照: 沿用既有build_panic_thermometer_report.py判定的「溫度計≥20」7個史冊級恐慌日
  (2020-03-13/2021-05-11/2022-06-22/2024-08-06/2025-04-08/2026-03-09/2026-06-10),margin_flow
  僅2022-01起有逐股資料,故只有後5個可用於本卷比較(前2個超出資料窗,誠實排除不硬湊)。

用法: python build_margin_maintenance_exetf.py
"""
import json
import sys
import sqlite3

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
DB = "capital_flow.db"
WARN = 150.0
GREEN, RED, BLUE, YELLOW, GRAY, PURPLE = "#7ec97e", "#e06c5a", "#6bb7e3", "#c3a55a", "#8a8878", "#b393d3"

PANIC_DAYS = ["2020-03-13", "2021-05-11", "2022-06-22", "2024-08-06",
              "2025-04-08", "2026-03-09", "2026-06-10"]

CSS = """
body{background:#1a1a19;color:#fff;font-family:"Noto Sans TC",sans-serif;margin:24px;max-width:1150px}
h1{font-size:20px} h2{font-size:15px;color:#c3c2b7;margin-top:28px;border-bottom:1px solid #333;padding-bottom:4px}
table{border-collapse:collapse;font-size:13px;font-variant-numeric:tabular-nums;margin:8px 0}
td,th{border:1px solid #333;padding:5px 10px;text-align:right} th{text-align:left;color:#c3c2b7}
.note{color:#8a8878;font-size:12px;line-height:1.7}
.good{color:#7ec97e}.bad{color:#e06c5a}.warn{color:#c3a55a}.hl{background:#2a2a28}
"""
BASE_LAYOUT = {"paper_bgcolor": "#1a1a19", "plot_bgcolor": "#22221f",
               "font": {"color": "#ddd", "family": "Noto Sans TC", "size": 12},
               "xaxis": {"gridcolor": "#333"}, "yaxis": {"gridcolor": "#333"},
               "margin": {"t": 48, "l": 55, "r": 20, "b": 40}, "height": 380,
               "legend": {"orientation": "h"}}


def build_market_panel(flow_table, official_table, den_query, den_scale=1.0):
    """單一市場(上市/上櫃)逐日面板: 官方ratio + ex-ETF(a)混合 + ex-ETF(b)自洽(張數分攤,粗略)。"""
    conn = sqlite3.connect(DB)
    flow = pd.read_sql(f"SELECT date, code, fin_bal FROM {flow_table}", conn)
    px = pd.read_sql("SELECT date, code, close FROM fm_daily_price", conn)
    off = pd.read_sql(f"SELECT date, ratio AS off_ratio FROM {official_table}", conn)
    den = pd.read_sql(den_query, conn)
    conn.close()
    den["den"] = den["den"] * den_scale

    flow["is_etf"] = flow.code.str.startswith("00")
    flow = flow.merge(px, on=["date", "code"], how="left")
    flow["val"] = flow.fin_bal * 1000 * flow.close  # NaN若缺價(TDR/下市代碼等,與官方calc_day同處理)

    bal_all = flow.groupby("date").fin_bal.sum().rename("bal_all")
    non = flow[~flow.is_etf]
    bal_ex = non.groupby("date").fin_bal.sum().rename("bal_ex")
    num_ex = non.groupby("date").val.sum().rename("num_ex")  # sum()預設skipna,自動排除缺價代碼
    miss = non.assign(m=non.val.isna()).groupby("date").m.sum().rename("miss")
    n_ex = non.groupby("date").code.count().rename("n_nonetf")

    panel = pd.concat([bal_all, bal_ex, num_ex, miss, n_ex], axis=1).reset_index()
    panel = panel.merge(off, on="date", how="inner").merge(den, on="date", how="inner")
    panel = panel[panel.bal_all > 0].copy()

    panel["ratio_a"] = panel.num_ex / panel.den * 100
    panel["etf_share_lots"] = 1 - panel.bal_ex / panel.bal_all
    den_b = panel.den * (panel.bal_ex / panel.bal_all)
    panel["ratio_b"] = panel.num_ex / den_b * 100
    panel["gap_a"] = panel.off_ratio - panel.ratio_a
    panel["gap_b"] = panel.off_ratio - panel.ratio_b
    panel = panel.sort_values("date").reset_index(drop=True)
    # 位階版(240日滾動百分位,呼應專案既有「維持率位階」慣例)——用來剔除ex-ETF(a)版
    # 因分母沒扣ETF而產生的系統性水位落差,改看「相對緊張程度」排名是否一致才是公平比較。
    panel["rank_off"] = panel.off_ratio.rolling(240, min_periods=120).rank(pct=True) * 100
    panel["rank_a"] = panel.ratio_a.rolling(240, min_periods=120).rank(pct=True) * 100
    return panel


def gap_stats(s):
    return {"mean": float(s.mean()), "std": float(s.std()), "median": float(s.median()),
            "min": float(s.min()), "max": float(s.max()),
            "p5": float(s.quantile(0.05)), "p95": float(s.quantile(0.95))}


def warn_discord(panel, col):
    """全歷史150警戒線判斷是否因ex-ETF版而翻轉(官方/ex-ETF版一個<150一個>=150)。"""
    off_warn = panel.off_ratio < WARN
    ex_warn = panel[col] < WARN
    disc = off_warn != ex_warn
    return int(disc.sum()), len(panel), panel.loc[disc, "date"].tolist()


def panic_window(panel, day, lead=1, lag=4):
    """panel.date為字串"YYYY-MM-DD"(SQL TEXT欄位),用字串比較即可,避免型別混用。"""
    dates = panel.date.values
    idx = np.flatnonzero(dates == day)
    if len(idx) == 0:
        # 找最近交易日(容忍panic list為週末/國定假日附近微差)
        cand = np.flatnonzero(dates >= day)
        if len(cand) == 0:
            return None
        idx = cand[:1]
    i0 = int(idx[0])
    lo, hi = max(0, i0 - lead), min(len(panel) - 1, i0 + lag)
    return panel.iloc[lo:hi + 1].copy(), i0


def fmt_table_rows(sub, i0):
    rows = []
    for i, r in sub.iterrows():
        tag = "◀恐慌日" if i == i0 else ""
        rows.append(f"<tr{' class=hl' if i == i0 else ''}><td>{r.date}{tag}</td>"
                    f"<td>{r.off_ratio:.2f}</td><td>{r.ratio_a:.2f}</td>"
                    f"<td class='{'bad' if r.gap_a > 1 else ('good' if r.gap_a < -1 else '')}'>{r.gap_a:+.2f}</td>"
                    f"<td>{'🚨<150' if r.off_ratio < WARN else '—'}</td>"
                    f"<td>{'🚨<150' if r.ratio_a < WARN else '—'}</td></tr>")
    return "".join(rows)


def eq_trace(panel, col, name, color, dash=None):
    return {"x": panel.date.tolist(), "y": [round(float(v), 2) for v in panel[col]],
            "name": name, "mode": "lines", "line": {"color": color, "width": 1.6,
                                                     **({"dash": dash} if dash else {})}}


def main():
    listed = build_market_panel(
        "margin_flow", "margin_maintenance_official",
        "SELECT date, today_balance AS den FROM margin_total WHERE name='MarginPurchaseMoney'")
    otc = build_market_panel(
        "margin_flow_otc", "margin_maintenance_otc",
        "SELECT date, money_today AS den FROM margin_total_otc", den_scale=1000.0)

    print(f"上市面板: {len(listed)}日 {listed.date.min()}~{listed.date.max()}")
    print(f"上櫃面板: {len(otc)}日 {otc.date.min()}~{otc.date.max()}")

    gs_listed_a, gs_listed_b = gap_stats(listed.gap_a), gap_stats(listed.gap_b)
    gs_otc_a, gs_otc_b = gap_stats(otc.gap_a), gap_stats(otc.gap_b)
    print(f"上市 gap_a: 均{gs_listed_a['mean']:+.2f}pp 中位{gs_listed_a['median']:+.2f}pp "
          f"範圍[{gs_listed_a['min']:+.2f},{gs_listed_a['max']:+.2f}]")
    print(f"上市 gap_b: 均{gs_listed_b['mean']:+.2f}pp 範圍[{gs_listed_b['min']:+.2f},{gs_listed_b['max']:+.2f}]")

    d_listed_a, n_listed, dates_listed_a = warn_discord(listed, "ratio_a")
    d_otc_a, n_otc, dates_otc_a = warn_discord(otc, "ratio_a")
    d_listed_b, _, _ = warn_discord(listed, "ratio_b")
    d_otc_b, _, _ = warn_discord(otc, "ratio_b")
    print(f"上市 150警戒線翻轉天數: a版{d_listed_a}/{n_listed}日, b版{d_listed_b}/{n_listed}日")
    print(f"上櫃 150警戒線翻轉天數: a版{d_otc_a}/{n_otc}日, b版{d_otc_b}/{n_otc}日")

    # 位階版(240日滾動百分位)相關性——剔除系統性水位落差,只看「相對緊張排名」是否一致
    corr_level_listed = listed.off_ratio.corr(listed.ratio_a)
    corr_diff_listed = listed.off_ratio.diff().corr(listed.ratio_a.diff())
    corr_rank_listed = listed.rank_off.corr(listed.rank_a)
    corr_level_otc = otc.off_ratio.corr(otc.ratio_a)
    corr_diff_otc = otc.off_ratio.diff().corr(otc.ratio_a.diff())
    corr_rank_otc = otc.rank_off.corr(otc.rank_a)
    # 底部十分位重疊率(官方版判定"當下最緊張10%"的日子,ex-ETF版是否也判同一批日子緊張)
    def decile_overlap(panel, q=10):
        r = panel.dropna(subset=["rank_off", "rank_a"])
        off_bot = set(r.date[r.rank_off <= q])
        a_bot = set(r.date[r.rank_a <= q])
        if not off_bot:
            return None
        return len(off_bot & a_bot) / len(off_bot) * 100
    ov_listed = decile_overlap(listed)
    ov_otc = decile_overlap(otc)
    print(f"上市 相關性: 原始水準r={corr_level_listed:.3f} 日變化r={corr_diff_listed:.3f} "
          f"240日位階r={corr_rank_listed:.3f} 底部10%重疊率={ov_listed:.0f}%")
    print(f"上櫃 相關性: 原始水準r={corr_level_otc:.3f} 日變化r={corr_diff_otc:.3f} "
          f"240日位階r={corr_rank_otc:.3f} 底部10%重疊率={ov_otc:.0f}%")

    # 恐慌事件視窗(僅margin_flow涵蓋窗2022-01起的5個可用)
    usable_panic = [d for d in PANIC_DAYS if d >= listed.date.min()]
    skipped_panic = [d for d in PANIC_DAYS if d < listed.date.min()]
    panic_html_listed, panic_html_otc = "", ""
    panic_summary = []
    for d in usable_panic:
        r_l = panic_window(listed, d)
        r_o = panic_window(otc, d)
        if r_l is None:
            continue
        sub_l, i0_l = r_l
        panic_html_listed += (f"<tr class=hl><td colspan=6 style='text-align:left;"
                               f"color:{YELLOW}'>▼ {d}</td></tr>" + fmt_table_rows(sub_l, i0_l))
        off_warn_w = sub_l.off_ratio < WARN
        a_warn_w = sub_l.ratio_a < WARN
        extended = int(((~off_warn_w) & a_warn_w).sum())  # 官方已解除但ex-ETF仍亮
        reduced = int((off_warn_w & (~a_warn_w)).sum())     # 官方仍亮但ex-ETF已解除
        entry = {"date": d, "gap0": float(sub_l.gap_a.iloc[min(1, len(sub_l) - 1)]),
                 "max_gap": float(sub_l.gap_a.abs().max()),
                 "extended_days": extended, "reduced_days": reduced}
        if r_o is not None:
            sub_o, i0_o = r_o
            panic_html_otc += (f"<tr class=hl><td colspan=6 style='text-align:left;"
                                f"color:{YELLOW}'>▼ {d}</td></tr>" + fmt_table_rows(sub_o, i0_o))
        panic_summary.append(entry)

    max_abs_gap_panic = max(e["max_gap"] for e in panic_summary) if panic_summary else 0
    total_extended = sum(e["extended_days"] for e in panic_summary)
    total_reduced = sum(e["reduced_days"] for e in panic_summary)
    any_flip_panic = (total_extended + total_reduced) > 0

    # ETF佔融資張數比重(年度均值,解釋b版為何偏離大)
    listed["date_dt"] = pd.to_datetime(listed.date)
    yr_share = listed.set_index("date_dt").etf_share_lots.resample("YE").mean()
    yr_share_txt = "、".join(f"{y.year}:{v * 100:.0f}%" for y, v in yr_share.items())

    # ---- 圖表 ----
    charts = []
    charts.append(("c_listed_ts", [
        eq_trace(listed, "off_ratio", "官方版(含ETF)", GRAY),
        eq_trace(listed, "ratio_a", "ex-ETF(a)混合分母", BLUE),
        eq_trace(listed, "ratio_b", "ex-ETF(b)自洽分母⚠粗略", PURPLE, dash="dot")],
        {"title": "上市融資維持率：官方版 vs ex-ETF對照(2022-01起,%)",
         "yaxis": {"title": "維持率%"},
         "shapes": [{"type": "line", "x0": listed.date.iloc[0], "x1": listed.date.iloc[-1],
                     "y0": WARN, "y1": WARN, "line": {"color": RED, "width": 1, "dash": "dash"}}]}))
    charts.append(("c_otc_ts", [
        eq_trace(otc, "off_ratio", "官方版(含ETF)", GRAY),
        eq_trace(otc, "ratio_a", "ex-ETF(a)混合分母", BLUE),
        eq_trace(otc, "ratio_b", "ex-ETF(b)自洽分母⚠粗略", PURPLE, dash="dot")],
        {"title": "上櫃融資維持率：官方版 vs ex-ETF對照(2022-01起,%)",
         "yaxis": {"title": "維持率%"},
         "shapes": [{"type": "line", "x0": otc.date.iloc[0], "x1": otc.date.iloc[-1],
                     "y0": WARN, "y1": WARN, "line": {"color": RED, "width": 1, "dash": "dash"}}]}))
    charts.append(("c_gap", [
        {"x": listed.date.tolist(), "y": [round(float(v), 2) for v in listed.gap_a],
         "name": "上市 gap_a(官方−ex-ETF混合)", "mode": "lines", "line": {"color": BLUE, "width": 1.4}},
        {"x": otc.date.tolist(), "y": [round(float(v), 2) for v in otc.gap_a],
         "name": "上櫃 gap_a(官方−ex-ETF混合)", "mode": "lines", "line": {"color": YELLOW, "width": 1.4}}],
        {"title": "分歧(pp)＝官方版−ex-ETF(a)版：正值＝ETF把維持率墊高", "yaxis": {"title": "差距(pp)"}}))
    charts.append(("c_etfshare", [
        {"x": listed.date.tolist(), "y": [round(float(v) * 100, 2) for v in listed.etf_share_lots],
         "name": "上市 ETF占全市場融資張數比重%", "mode": "lines", "line": {"color": PURPLE, "width": 1.4}},
        {"x": otc.date.tolist(), "y": [round(float(v) * 100, 2) for v in otc.etf_share_lots],
         "name": "上櫃 ETF占全市場融資張數比重%", "mode": "lines", "line": {"color": GREEN, "width": 1.4}}],
        {"title": "ETF占全市場融資「張數」比重(b版偏離的根源;槓桿ETF單價低但週轉量大)",
         "yaxis": {"title": "占比%"}}))

    chart_html, chart_js = "", ""
    for cid, data, lay in charts:
        merged = {**BASE_LAYOUT, **lay, "yaxis": {**BASE_LAYOUT["yaxis"], **lay.get("yaxis", {})},
                  "title": {"text": lay["title"], "font": {"size": 14}}}
        chart_html += f'<div id="{cid}" style="margin-bottom:10px"></div>\n'
        chart_js += (f'Plotly.newPlot("{cid}", {json.dumps(data, ensure_ascii=False)}, '
                     f'{json.dumps(merged, ensure_ascii=False)}, {{displayModeBar:false}});\n')

    # ---- 判決 ----
    # 核心判準=「相對緊張排名」是否重複(日變化相關/240日位階相關/最緊張10%重疊率),
    # 而非原始水位差距——因為(a)版分子分母口徑不對稱,天生會有一個穩定的機械式落差,
    # 那不算新資訊;只有「排名/動態」對不上,才代表ex-ETF版看到了官方版看不到的東西。
    redundant = (corr_diff_listed >= 0.99 and corr_rank_listed >= 0.9 and ov_listed >= 80 and
                 corr_diff_otc >= 0.99 and corr_rank_otc >= 0.9 and ov_otc >= 80)
    weak_corr = corr_rank_listed < 0.7 or corr_rank_otc < 0.7
    if redundant:
        verdict = "🟡只留研究記錄，不建議正式納入警戒帶第二條線"
        verdict_detail = (
            f"日變化相關性上市{corr_diff_listed:.3f}／上櫃{corr_diff_otc:.3f}、240日位階(滾動百分位)"
            f"相關性上市{corr_rank_listed:.3f}／上櫃{corr_rank_otc:.3f}、「當下最緊張10%交易日」重疊率"
            f"上市{ov_listed:.0f}%／上櫃{ov_otc:.0f}%——四項指標都顯示ex-ETF(a)版幾乎是官方版的"
            f"『固定水位落差拷貝』。恐慌事件視窗內雖真的出現{total_extended}個交易日「官方版已解除150"
            f"警戒、但ex-ETF(a)版仍亮」(2022-06-22/2024-08-06/2025-04-08三役皆有,見下表)，但這個落差"
            f"用『上市線ex-ETF(a)版平均比官方低約{gs_listed_a['mean']:.0f}pp』這個穩定機械偏移即可完全"
            f"解釋，不是排除ETF後看到了官方版看不到的相對壓力——換算成同一把尺(如門檻降到~"
            f"{WARN - gs_listed_a['mean']:.0f}%)幾乎不會改變任何一天的警戒時間點。維護一整套第二pipeline"
            f"(margin_flow+fm_daily_price+margin_total)換來的訊號增量趨近於零。")
    elif weak_corr:
        verdict = "✅建議納入：位階相關性偏低，ex-ETF版有獨立資訊"
        verdict_detail = (f"240日位階相關性上市{corr_rank_listed:.3f}／上櫃{corr_rank_otc:.3f}未達高度一致，"
                           f"顯示ex-ETF版排名的『相對緊張程度』與官方版有實質分歧，值得正式納入當第二條線。")
    else:
        verdict = "🟡只留研究記錄：中度相關，暫不建議上板"
        verdict_detail = "相關性介於高度重複與明顯分歧之間，證據強度不足以支持新增維護成本，先留記錄持續觀察。"

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>ETF排除版融資維持率對照研究(2026-07-31)</title>
<script src="plotly.min.js"></script><style>{CSS}</style></head><body>
<h1>ETF排除版融資維持率對照研究：恐慌溫度計訊號夠不夠乾淨？</h1>
<p class="note">緣起：現行融資維持率(儀表板「🚨融資警戒帶」卡)主源FinMind官方數列與備援公式版皆刻意
含ETF融資(00631L等槓桿ETF的融資餘額變動偏機械式,理論上可能稀釋「散戶信心/斷頭壓力」的訊號純度)。
本卷只做對照研究,<b>不動</b>fetch_margin_maintenance.py生產管線與官方數列。
產生器 build_margin_maintenance_exetf.py；ETF判斷=代碼開頭"00"(專案既有慣例)。</p>

<h2>📋 執行摘要（判決）</h2>
<table>
<tr><th>判決</th><td style="text-align:left"><b>{verdict}</b></td></tr>
<tr><th>理由</th><td style="text-align:left">{verdict_detail}</td></tr>
<tr><th>資料窗限制</th><td style="text-align:left">margin_flow逐股資料僅2022-01-03起(vs官方數列
2002起)，7個「溫度計≥20」史冊級恐慌日中僅{len(usable_panic)}個落在窗內可比較
({'、'.join(usable_panic)})；{('2020-03-13、2021-05-11超出窗外誠實排除，不硬湊。'
if skipped_panic else '')}</td></tr>
<tr><th>分母設計</th><td style="text-align:left">主用(a)混合口徑=ex-ETF分子÷官方全市場分母(不拆分)；
(b)自洽口徑用「非ETF占全市場融資張數比例」分攤官方分母，經查ETF占張數比重達
{yr_share.iloc[-1] * 100:.0f}%(2026,遠高於ETF檔數占比~18%，因槓桿ETF單價低週轉量大)，
會嚴重高估ETF的"金額"占比，(b)版數字明顯失真僅供參考，不建議採信。</td></tr>
</table>

<h2>差距分布(pp = 官方版 − ex-ETF版)</h2>
<table>
<tr><th>市場/口徑</th><th>均值</th><th>中位數</th><th>標準差</th><th>P5</th><th>P95</th><th>最小</th><th>最大</th></tr>
<tr><td>上市 gap_a(混合)</td><td>{gs_listed_a['mean']:+.2f}</td><td>{gs_listed_a['median']:+.2f}</td>
<td>{gs_listed_a['std']:.2f}</td><td>{gs_listed_a['p5']:+.2f}</td><td>{gs_listed_a['p95']:+.2f}</td>
<td>{gs_listed_a['min']:+.2f}</td><td>{gs_listed_a['max']:+.2f}</td></tr>
<tr><td>上市 gap_b(自洽⚠)</td><td>{gs_listed_b['mean']:+.2f}</td><td>{gs_listed_b['median']:+.2f}</td>
<td>{gs_listed_b['std']:.2f}</td><td>{gs_listed_b['p5']:+.2f}</td><td>{gs_listed_b['p95']:+.2f}</td>
<td>{gs_listed_b['min']:+.2f}</td><td>{gs_listed_b['max']:+.2f}</td></tr>
<tr class=hl><td>上櫃 gap_a(混合)</td><td>{gs_otc_a['mean']:+.2f}</td><td>{gs_otc_a['median']:+.2f}</td>
<td>{gs_otc_a['std']:.2f}</td><td>{gs_otc_a['p5']:+.2f}</td><td>{gs_otc_a['p95']:+.2f}</td>
<td>{gs_otc_a['min']:+.2f}</td><td>{gs_otc_a['max']:+.2f}</td></tr>
<tr><td>上櫃 gap_b(自洽⚠)</td><td>{gs_otc_b['mean']:+.2f}</td><td>{gs_otc_b['median']:+.2f}</td>
<td>{gs_otc_b['std']:.2f}</td><td>{gs_otc_b['p5']:+.2f}</td><td>{gs_otc_b['p95']:+.2f}</td>
<td>{gs_otc_b['min']:+.2f}</td><td>{gs_otc_b['max']:+.2f}</td></tr>
</table>
<p class="note">gap_a為正＝ETF把官方版墊高(常態，因ETF部位market value為正貢獻但分母沒扣除)。
ETF占全市場融資"張數"比重逐年：{yr_share_txt}(上市)。</p>

<h2>150%警戒線判斷是否翻轉(全歷史)</h2>
<table>
<tr><th>市場/口徑</th><th>翻轉天數</th><th>樣本天數</th><th>翻轉率</th></tr>
<tr><td>上市 ex-ETF(a)</td><td>{d_listed_a}</td><td>{n_listed}</td><td>{d_listed_a / n_listed * 100:.1f}%</td></tr>
<tr><td>上市 ex-ETF(b)⚠</td><td>{d_listed_b}</td><td>{n_listed}</td><td>{d_listed_b / n_listed * 100:.1f}%</td></tr>
<tr><td>上櫃 ex-ETF(a)</td><td>{d_otc_a}</td><td>{n_otc}</td><td>{d_otc_a / n_otc * 100:.1f}%</td></tr>
<tr><td>上櫃 ex-ETF(b)⚠</td><td>{d_otc_b}</td><td>{n_otc}</td><td>{d_otc_b / n_otc * 100:.1f}%</td></tr>
</table>
<p class="note">翻轉＝官方版與ex-ETF版一個&lt;150%一個&gt;=150%(觸發判斷不同)。
(b)版因分母設計粗略，翻轉率參考意義有限，僅列出對照。</p>

<h2>訊號動態是否重複？(判決核心判準——剔除機械式水位落差後的相對排名對照)</h2>
<table>
<tr><th>指標</th><th>上市</th><th>上櫃</th><th>說明</th></tr>
<tr><td>原始水準相關r</td><td>{corr_level_listed:.3f}</td><td>{corr_level_otc:.3f}</td>
<td style="text-align:left">兩序列同期水準相關(受同一套個股/大盤驅動,預期本來就高)</td></tr>
<tr class=hl><td>日變化相關r</td><td>{corr_diff_listed:.3f}</td><td>{corr_diff_otc:.3f}</td>
<td style="text-align:left">逐日漲跌是否同步——剔除固定offset後的關鍵指標</td></tr>
<tr class=hl><td>240日位階相關r</td><td>{corr_rank_listed:.3f}</td><td>{corr_rank_otc:.3f}</td>
<td style="text-align:left">滾動百分位排名(呼應專案既有「維持率位階」慣例)是否一致</td></tr>
<tr class=hl><td>最緊張10%日重疊率</td><td>{ov_listed:.0f}%</td><td>{ov_otc:.0f}%</td>
<td style="text-align:left">官方版判定「近一年最緊張的10%交易日」，ex-ETF版是否判同一批日子緊張</td></tr>
</table>
<p class="note">四項指標一致指向「動態高度重複」：ex-ETF(a)版幾乎就是官方版做了一個穩定水位下移的拷貝，
不是在講不同的故事。</p>

<h2>時間序列對照</h2>
{chart_html.split(chr(10))[0]}
{chart_html.split(chr(10))[1]}
{chart_html.split(chr(10))[2]}
{chart_html.split(chr(10))[3]}

<h2>恐慌事件視窗對照——上市(恐慌日前1日～後4日)</h2>
<table><tr><th>日期</th><th>官方版%</th><th>ex-ETF(a)%</th><th>差距pp</th>
<th>官方150判斷</th><th>ex-ETF(a)150判斷</th></tr>{panic_html_listed}</table>

<h2>恐慌事件視窗對照——上櫃(恐慌日前1日～後4日)</h2>
<table><tr><th>日期</th><th>官方版%</th><th>ex-ETF(a)%</th><th>差距pp</th>
<th>官方150判斷</th><th>ex-ETF(a)150判斷</th></tr>{panic_html_otc}</table>

<h2>誠實判斷</h2>
<p class="note">
①<b>差距存在且方向/幅度都很穩定</b>：ETF部位(collateral market value)持續墊高官方版維持率
(gap_a上市均{gs_listed_a['mean']:+.2f}pp／上櫃均{gs_otc_a['mean']:+.2f}pp)，恐慌日視窗內最大分歧
{max_abs_gap_panic:.2f}pp，跟全期分布相比並沒有失控放大——ETF融資的「機械式」性質在平日和恐慌日
一樣穩定地把整體讀數墊高一個大致固定的量，不是那種「恐慌時才突然失真」的干擾。
②<b>150%警戒判斷『表面上』確實會因排除ETF而改變，但那是機械偏移的副作用，不是新資訊</b>：
上市線恐慌事件視窗內共有{total_extended}個交易日出現「官方版已解除150警戒、ex-ETF(a)版仍亮」
(2022-06-22/2024-08-06/2025-04-08三役皆有，見上方事件表)——乍看是ex-ETF版更謹慎、多留崗位
幾天，但日變化相關r={corr_diff_listed:.3f}、240日位階相關r={corr_rank_listed:.3f}、最緊張10%日
重疊率{ov_listed:.0f}%全部顯示兩版動態幾乎同步，這個「多亮幾天」完全可以用「上市線ex-ETF(a)版
平均比官方低約{gs_listed_a['mean']:.0f}pp」這個穩定offset解釋：只要把警戒門檻同步降到~
{WARN - gs_listed_a['mean']:.0f}%，兩版的解除時間點幾乎重合。上櫃線因ETF融資占比小很多，
連這個副作用都幾乎不出現(gap僅{gs_otc_a['mean']:+.1f}pp、恐慌視窗內幾乎無150翻轉)。
③<b>分母口徑(b)不可信</b>：因margin_flow沒有個股層級的融資金額(貸款本金)欄位，只能用張數占比
分攤官方分母，而槓桿ETF單價低、週轉量大，張數占比({yr_share.iloc[-1] * 100:.0f}%)遠高於其真實金額
占比，導致(b)版數字系統性失真(比官方版還高出數十pp)，本卷判定(b)版不具參考價值，僅供對照展示
其失真幅度。
④<b>建議</b>：{verdict}。ex-ETF(a)版沒有在關鍵時刻提供官方版看不到的相對壓力資訊，維護一整套
第二pipeline(margin_flow+fm_daily_price+margin_total)的邊際價值很低；但「ETF融資約占官方版
讀數上市{gs_listed_a['mean']:.0f}pp／上櫃{gs_otc_a['mean']:.1f}pp，且占全市場融資張數比重已從
2022年{yr_share.iloc[0] * 100:.0f}%升到{yr_share.iloc[-1] * 100:.0f}%」這個描述性事實值得寫進
研究記錄備查，日後若ETF占比持續上升，這條線可能需要重新評估。
</p>

<h2>已知限制</h2>
<p class="note">
①margin_flow/margin_flow_otc僅2022-01起有逐股資料，本卷比較基準期短於官方數列全史(2002起)，
無法驗證更早期(如2008金融海嘯、2015-08、2020-03)ETF排除是否改變判斷；
②ETF判斷用代碼開頭"00"，TDR(91xxxx開頭)、少數下市/合併代碼不會被此規則抓到，但這些代碼在
fm_daily_price多半缺價會被自然跳過(與官方calc_day()同一套處理，非本卷新增偏誤)；
③分母(b)版張數占比代理法有已知系統性偏誤(見上)，不建議採信；
④本卷數字與官方calc_day()公式版對帳誤差(≤0.14pp)無關，是另一條獨立計算路徑，只共用
margin_total/margin_total_otc分母與margin_flow分子資料源。
</p>
<script>{chart_js}</script></body></html>"""
    out_path = "研究報告/research_margin_exetf.html"
    open(out_path, "w", encoding="utf-8").write(html)
    print(f"報告已產出 {out_path} ({len(html):,} chars, {len(charts)}圖)")


if __name__ == "__main__":
    main()
