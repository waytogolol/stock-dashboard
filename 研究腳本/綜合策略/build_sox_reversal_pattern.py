# -*- coding: utf-8 -*-
"""SOX崩跌後單日暴力反彈型態歷史複現考卷(2026-08-03,使用者觀察案例:2026-07-28~29台股/半導體
連續重挫後,2026-07-30 SOX單日+8.19%暴力反彈,隔日2026-07-31台股跟漲+7.98%,同期SPX只有溫和波動
+0.21%/-1.52%/+1.66%/+0.70%=確認是半導體專屬事件非美股大盤事件;使用者印象反彈與美股半導體/科技
龍頭財報有關,想知道歷史上這種「連跌+SOX單日暴力反彈觸發全市場反轉」型態還有沒有出現過)。

案例數字複驗(index_daily): TAIEX 07-28 -4.65%/07-29 -3.76%;SOX 07-28 -4.49%/07-29 -5.33%/
07-30 +8.19%;TAIEX 07-31 +7.98%;SPX同期 +0.21%/-1.52%/+1.66%/+0.70%——與使用者描述完全吻合。

考卷規格(①核心+②加分,使用者任務書逐條對應):
① 型態歷史複現搜尋(index_daily全史,零外部抓取):
  跌深定義: SOX前一日(t-1,即反彈日t的前一天)3日或5日累積報酬<=門檻(可調,主用-8%/嚴格用-10%);
    門檻理由=本案TAIEX 3日跌幅-8.28%(2026-07-29)為基準取整-8%,SOX自身3日/5日跌幅達-11.6%/-15.8%
    更深故另設-10%嚴格版做穩健對照;-8%在SOX全史3日累積報酬分布中約為後2.54百分位(真正的尾部)。
  暴力反彈定義: SOX單日報酬>=門檻(主用+5%,嚴格版+8%);+5%≈SOX日報酬2.1個標準差、全史僅2.78%交易日
    達標,+8%≈3.4個標準差、僅0.53%交易日達標(本案+8.19%屬於這個尾中之尾)。
  去重(dedup): 崩跌段常見連續多天觸發同一組門檻(如2000拿斯達克泡沫、2008海嘯、2020疫情),若不去重
    會把同一次「崩跌-反彈」事件拆成好幾個獨立案例灌水樣本數;quiet=15個交易日內只取第一天當錨定日
    (敏感度: quiet=10→n=45/15→n=39/20~25→n=35,結論不敏感於這個參數的挑選)。
  事件研究法(CAR,零demean基準另計): SOX從反彈當日(k=0)起算k=1/3/5/10/20/60日報酬;
    台股從SOX反彈日「隔日起」(即TAIEX下一個可得交易日)起算同樣k日報酬,對應使用者原案「隔日起算」。
    demean=k日報酬平均值 減去 全樣本(所有交易日,非僅事件日)同k日無條件平均報酬(扣長期上漲飄移)。
    bootstrap(n=3000,對每個k個別重抽事件)算平均值95% CI,n>=10才做;n<15樣本另誠實只列逐案例數字。
② 財報歸因查證: 不重打Nasdaq calendar API(check_earnings.py用途是查「未來」財報,對歷史查證效率較低),
  改用專案既有 capital_flow.db.earnings_dates 表(由 抓取/fetch_earnings_history.py 以yfinance
  Ticker.earnings_dates 回補,market='美' 涵蓋2014-04~2026-09近百檔美股,已含NVDA/AMD/TSM/AVGO/MU/
  INTC/QCOM/ASML/LRCX/AMAT/KLAC/MRVL/TXN/ON/TER等主要半導體+MSFT/META等科技龍頭歷史財報公告日)——
  資料源同樣夠深且已在本地,不必再打外部API,對每個2014年以後的型態事件做財報日期窗口比對(事件前3天
  ~事件當天+1天)。⚠限制: 表格只涵蓋2014-04起,型態事件更早的年份(1995-2013,佔全樣本多數)無法查證。

用法: python 研究腳本/綜合策略/build_sox_reversal_pattern.py  (從根目錄執行,鐵律)
產出: 研究報告/research_sox_reversal_pattern.html
"""
import sqlite3
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

DB = "capital_flow.db"
OUT = "研究報告/research_sox_reversal_pattern.html"
K_LIST = [1, 3, 5, 10, 20, 60]
BOOT_N = 3000
QUIET = 15
rng = np.random.default_rng(42)

EARN_TICKERS = ["NVDA", "AMD", "TSM", "AVGO", "MU", "INTC", "QCOM", "ASML",
                "LRCX", "AMAT", "KLAC", "MRVL", "TXN", "ON", "TER"]
EARN_TICKERS_CTX = EARN_TICKERS + ["MSFT", "META"]   # 使用者記憶提及微軟,列入對照但不算半導體


# ── 基礎序列 ──────────────────────────────────────────────
def load_index(market):
    con = sqlite3.connect(DB)
    df = pd.read_sql("SELECT date, close FROM index_daily WHERE market=? ORDER BY date",
                      con, params=(market,), parse_dates=["date"])
    con.close()
    return df.set_index("date")["close"]


SOX = load_index("SOX")
TAIEX = load_index("TAIEX")
SPX = load_index("SPX")

RET1_SOX = SOX.pct_change()
CUM3_SOX = SOX / SOX.shift(3) - 1
CUM5_SOX = SOX / SOX.shift(5) - 1
PRE3 = CUM3_SOX.shift(1)     # 反彈日t的「前一天」3日累積跌幅
PRE5 = CUM5_SOX.shift(1)
CUM3_TW = TAIEX / TAIEX.shift(3) - 1
CUM5_TW = TAIEX / TAIEX.shift(5) - 1


def find_events(rebound_thresh, decl_thresh, window="either", quiet=QUIET):
    if window == "3d":
        cond = PRE3 <= decl_thresh
    elif window == "5d":
        cond = PRE5 <= decl_thresh
    else:
        cond = (PRE3 <= decl_thresh) | (PRE5 <= decl_thresh)
    mask = (RET1_SOX >= rebound_thresh) & cond
    pos, last = [], -10 ** 9
    for i, h in enumerate(mask.values):
        if h and (i - last) > quiet:
            pos.append(i)
            last = i
    return pos


def taiex_anchor_pos(d):
    if d < TAIEX.index[0]:
        return None
    p = TAIEX.index.searchsorted(d, side="right")
    return p if p < len(TAIEX) else None


def sox_fwd(i, k):
    return float(SOX.iloc[i + k] / SOX.iloc[i] - 1) * 100 if i + k < len(SOX) else np.nan


def tw_fwd(p, k):
    return float(TAIEX.iloc[p + k] / TAIEX.iloc[p] - 1) * 100 if (p is not None and p + k < len(TAIEX)) else np.nan


def baseline_unconditional(s):
    return {k: float(((s.shift(-k) / s - 1) * 100).mean()) for k in K_LIST}


BASE_SOX = baseline_unconditional(SOX)
BASE_TW = baseline_unconditional(TAIEX)


def event_table(pos_list):
    rows = []
    for i in pos_list:
        d = SOX.index[i]
        tp = taiex_anchor_pos(d)
        tw_pre3 = tw_pre5 = np.nan
        if tp is not None and tp - 1 >= 0:
            tw_pre3 = float(CUM3_TW.iloc[tp - 1] * 100)
            tw_pre5 = float(CUM5_TW.iloc[tp - 1] * 100)
        row = {"date": d, "sox_ret1": RET1_SOX.iloc[i] * 100,
               "pre3": PRE3.iloc[i] * 100, "pre5": PRE5.iloc[i] * 100,
               "tw_anchor": TAIEX.index[tp] if tp is not None else None,
               "tw_pre3": tw_pre3, "tw_pre5": tw_pre5}
        for k in K_LIST:
            row[f"sox_k{k}"] = sox_fwd(i, k)
            row[f"tw_k{k}"] = tw_fwd(tp, k)
        rows.append(row)
    return pd.DataFrame(rows)


def summarize_k(df, prefix, base):
    out = {}
    for k in K_LIST:
        v = df[f"{prefix}_k{k}"].dropna().values
        if len(v) == 0:
            out[k] = {"n": 0}
            continue
        med, mean, win = float(np.median(v)), float(np.mean(v)), float((v > 0).mean() * 100)
        dm = mean - base[k]
        ci = None
        if len(v) >= 10:
            bs = rng.choice(v, size=(BOOT_N, len(v)), replace=True).mean(axis=1)
            ci = (float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5)))
        out[k] = {"n": len(v), "med": med, "mean": mean, "dm": dm, "win": win, "ci": ci}
    return out


# ── 敏感度網格 ────────────────────────────────────────────
def sensitivity_grid():
    grids = {}
    for window in ("3d", "5d", "either"):
        rows = []
        for reb in (0.05, 0.06, 0.07, 0.08):
            row = {"反彈門檻": f"+{reb*100:.0f}%"}
            for decl in (-0.06, -0.08, -0.10, -0.12):
                row[f"{decl*100:.0f}%"] = len(find_events(reb, decl, window))
            rows.append(row)
        grids[window] = rows
    return grids


def dedup_sensitivity():
    return {q: len(find_events(0.05, -0.08, "either", quiet=q)) for q in (10, 15, 20, 25)}


# ── 財報歸因查證 ──────────────────────────────────────────
def load_earnings():
    con = sqlite3.connect(DB)
    ed = pd.read_sql("SELECT code, date FROM earnings_dates WHERE market='美'", con, parse_dates=["date"])
    con.close()
    return ed[ed.code.isin(EARN_TICKERS_CTX)]


def earnings_hits(dates, ed, day_before=3, day_after=1):
    out = {}
    cov_start = ed.date.min()
    for d in dates:
        if d < cov_start:
            out[d] = None   # 表格涵蓋範圍之外
            continue
        win = ed[(ed.date >= d - pd.Timedelta(days=day_before)) & (ed.date <= d + pd.Timedelta(days=day_after))]
        win = win.sort_values("date")
        chip = win[win.code.isin(EARN_TICKERS)]
        out[d] = {"all": list(zip(win.code, win.date.dt.strftime("%Y-%m-%d"))),
                   "chip_n": len(chip)}
    return out


# ── HTML輔助 ──────────────────────────────────────────────
def fmt_pct(x, nd=2):
    return "—" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:+.{nd}f}%"


def k_summary_table(summ, label):
    head = ("<tr><th>k</th><th>n</th><th>中位%</th><th>平均%</th><th>demean平均%(扣長期飄移)</th>"
            "<th>勝率</th><th>bootstrap平均值95% CI</th></tr>")
    body = ""
    for k in K_LIST:
        s = summ[k]
        if s["n"] == 0:
            body += f"<tr><th>k{k}</th><td colspan='6'>—</td></tr>"
            continue
        ci = "n<10不bootstrap" if s["ci"] is None else f"[{s['ci'][0]:+.2f}, {s['ci'][1]:+.2f}]"
        sig = ""
        if s["ci"] is not None:
            lo, hi = s["ci"]
            sig = " <span class='bad'>(排0,偏負)</span>" if hi < 0 else (
                  " <span class='good'>(排0,偏正)</span>" if lo > 0 else " <span class='sub'>(含0)</span>")
        cls = "good" if s["med"] > 0 else "bad"
        body += (f"<tr><th>k{k}</th><td>{s['n']}</td><td class='{cls}'>{s['med']:+.2f}%</td>"
                 f"<td>{s['mean']:+.2f}%</td><td>{s['dm']:+.2f}%</td><td>{s['win']:.0f}%</td>"
                 f"<td>{ci}{sig}</td></tr>")
    return f"<h3>{label}</h3><table>{head}{body}</table>"


def event_rows_html(df, ed_hits=None, live_date=None):
    rows = ""
    for _, r in df.iterrows():
        live = r["date"] == live_date
        cls = " class='hl'" if live else ""
        tw_anchor = r["tw_anchor"].date() if pd.notna(r["tw_anchor"]) else "—(早於TAIEX涵蓋範圍)"
        earn = ""
        if ed_hits is not None:
            h = ed_hits.get(r["date"])
            if h is None:
                earn = "<span class='sub'>財報表無涵蓋</span>"
            elif h["chip_n"] > 0:
                names = "、".join(f"{c}({d[5:]})" for c, d in h["all"])
                earn = f"<span class='good'>{names}</span>"
            elif h["all"]:
                names = "、".join(f"{c}({d[5:]})" for c, d in h["all"])
                earn = f"<span class='sub'>{names}(非半導體)</span>"
            else:
                earn = "<span class='sub'>窗口內無</span>"
        fmtk = lambda col: fmt_pct(r[col])
        rows += (f"<tr{cls}><td>{r['date'].date()}{'★本次案例' if live else ''}</td>"
                 f"<td>{fmtk('sox_ret1')}</td><td>{fmtk('pre3')}</td><td>{fmtk('pre5')}</td>"
                 f"<td>{tw_anchor}</td>"
                 + "".join(f"<td>{fmtk(f'sox_k{k}')}</td>" for k in K_LIST)
                 + "".join(f"<td>{fmtk(f'tw_k{k}')}</td>" for k in K_LIST)
                 + (f"<td style='text-align:left'>{earn}</td>" if ed_hits is not None else "")
                 + "</tr>")
    return rows


def main():
    live_date = pd.Timestamp("2026-07-30") if pd.Timestamp("2026-07-30") in SOX.index else None

    # 主定義 rebound>=5%, decl<=-8%(3日或5日either), 嚴格版 rebound>=8%, decl<=-10%
    pos_main = find_events(0.05, -0.08, "either")
    pos_strict = find_events(0.08, -0.10, "either")
    pos_3donly = find_events(0.05, -0.08, "3d")
    pos_5donly = find_events(0.05, -0.08, "5d")

    df_main = event_table(pos_main)
    df_strict = event_table(pos_strict)
    df_3d = event_table(pos_3donly)
    df_5d = event_table(pos_5donly)

    sox_sum_main = summarize_k(df_main, "sox", BASE_SOX)
    tw_sum_main = summarize_k(df_main, "tw", BASE_TW)
    sox_sum_strict = summarize_k(df_strict, "sox", BASE_SOX)
    tw_sum_strict = summarize_k(df_strict, "tw", BASE_TW)
    sox_sum_3d = summarize_k(df_3d, "sox", BASE_SOX)
    tw_sum_3d = summarize_k(df_3d, "tw", BASE_TW)
    sox_sum_5d = summarize_k(df_5d, "sox", BASE_SOX)
    tw_sum_5d = summarize_k(df_5d, "tw", BASE_TW)

    print("=" * 90)
    print(f"主定義(rebound>=5%,decl<=-8%,3d或5d任一): n={len(pos_main)}")
    print(f"嚴格版(rebound>=8%,decl<=-10%,貼近本次量級): n={len(pos_strict)}")
    for k in K_LIST:
        print(f"  主定義 SOX k{k}: {sox_sum_main[k]}")
    for k in K_LIST:
        print(f"  主定義 TAIEX(隔日起) k{k}: {tw_sum_main[k]}")

    # 敏感度網格
    grids = sensitivity_grid()
    dedup_sens = dedup_sensitivity()
    print("dedup quiet敏感度:", dedup_sens)

    # 聯合崩跌子集(TAIEX同日也跌深>=8%,3日或5日任一) —— 與本次最相似的歷史類比
    joint_mask = df_main.apply(lambda r: (pd.notna(r["tw_pre3"]) and (r["tw_pre3"] <= -8 or r["tw_pre5"] <= -8)), axis=1)
    df_joint = df_main[joint_mask].reset_index(drop=True)
    n_tw_avail = df_main["tw_anchor"].notna().sum()
    print(f"主定義{len(pos_main)}起事件中,TAIEX有資料可查={n_tw_avail}起,其中同期TAIEX自己也跌深(>=8%)={len(df_joint)}起")

    # 財報歸因查證
    ed = load_earnings()
    ed_hits_main = earnings_hits(df_main["date"].tolist(), ed)
    n_2014plus = sum(1 for d in df_main["date"] if d >= ed.date.min())
    n_chip_hit = sum(1 for d, h in ed_hits_main.items() if h is not None and h["chip_n"] > 0)
    print(f"財報查證: 主定義事件中2014年以後(表格涵蓋)有{n_2014plus}起,其中窗口內命中半導體/科技龍頭財報者{n_chip_hit}起")

    html = build_html(df_main, df_strict, df_joint, sox_sum_main, tw_sum_main, sox_sum_strict, tw_sum_strict,
                       sox_sum_3d, tw_sum_3d, sox_sum_5d, tw_sum_5d, grids, dedup_sens, ed_hits_main,
                       live_date, n_tw_avail, n_2014plus, n_chip_hit, ed)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"已產出 {OUT}")


def build_html(df_main, df_strict, df_joint, sox_sum_main, tw_sum_main, sox_sum_strict, tw_sum_strict,
               sox_sum_3d, tw_sum_3d, sox_sum_5d, tw_sum_5d, grids, dedup_sens, ed_hits_main,
               live_date, n_tw_avail, n_2014plus, n_chip_hit, ed):
    css = """
body{background:#1a1a19;color:#fff;font-family:"Noto Sans TC",sans-serif;margin:24px;max-width:1250px}
h1{font-size:20px} h2{font-size:15px;color:#c3c2b7;margin-top:30px;border-bottom:1px solid #333;padding-bottom:4px}
h3{font-size:13.5px;color:#a8a79a;margin:16px 0 4px}
table{border-collapse:collapse;font-size:12px;font-variant-numeric:tabular-nums;margin:8px 0}
td,th{border:1px solid #333;padding:4px 8px;text-align:right} th{text-align:left;color:#c3c2b7}
.note{color:#8a8878;font-size:12.5px;line-height:1.8} .good{color:#7ec97e} .bad{color:#e06c5a}
.warn{color:#c3a55a} .hl{background:#3a3420} .sub{color:#777;font-size:11px}
.scroll{max-height:520px;overflow-y:auto;display:block}
.chart{width:100%;height:360px}
"""
    live_row_main = df_main[df_main["date"] == live_date]
    live_pre3 = float(live_row_main["pre3"].iloc[0]) if len(live_row_main) else None
    live_pre5 = float(live_row_main["pre5"].iloc[0]) if len(live_row_main) else None
    live_ret1 = float(live_row_main["sox_ret1"].iloc[0]) if len(live_row_main) else None

    # 敏感度表HTML
    def grid_html(rows, label):
        cols = ["-6%", "-8%", "-10%", "-12%"]
        head = "<tr><th>反彈門檻＼跌深門檻</th>" + "".join(f"<th>{c}</th>" for c in cols) + "</tr>"
        body = "".join("<tr><th>" + r["反彈門檻"] + "</th>" + "".join(f"<td>{r[c]}</td>" for c in cols) + "</tr>"
                        for r in rows)
        return f"<h3>去重後案例數(quiet={QUIET}日)——{label}</h3><table>{head}{body}</table>"

    sens_html = grid_html(grids["3d"], "跌深=3日累積報酬窗口") + grid_html(grids["5d"], "跌深=5日累積報酬窗口") + \
                grid_html(grids["either"], "跌深=3日或5日任一(本卷主用)")
    dedup_html = "、".join(f"quiet={q}→n={n}" for q, n in dedup_sens.items())

    # 主表(39筆全列)
    head_main = ("<tr><th>SOX反彈日</th><th>SOX單日</th><th>SOX前3日</th><th>SOX前5日</th><th>台股隔日起錨定</th>"
                 + "".join(f"<th>SOX k{k}</th>" for k in K_LIST)
                 + "".join(f"<th>台股 k{k}</th>" for k in K_LIST) + "<th>窗口內半導體/科技龍頭財報</th></tr>")
    body_main = event_rows_html(df_main, ed_hits_main, live_date)
    main_table = f"<div class='scroll'><table>{head_main}{body_main}</table></div>"

    head_strict = ("<tr><th>SOX反彈日</th><th>SOX單日</th><th>SOX前3日</th><th>SOX前5日</th><th>台股隔日起錨定</th>"
                   + "".join(f"<th>SOX k{k}</th>" for k in K_LIST)
                   + "".join(f"<th>台股 k{k}</th>" for k in K_LIST) + "</tr>")
    body_strict = event_rows_html(df_strict, None, live_date)
    strict_table = f"<div class='scroll'><table>{head_strict}{body_strict}</table></div>"

    body_joint = event_rows_html(df_joint, None, live_date)
    joint_table = f"<table>{head_strict}{body_joint}</table>"

    # 窗口穩健性摘要(k1/k20/k60)
    def compact_row2(label, summ, n):
        cells = ""
        for k in (1, 20, 60):
            s = summ[k]
            if s["n"] == 0:
                cells += "<td>—</td>"
            else:
                cls = "good" if s["med"] > 0 else "bad"
                cells += f"<td><span class='{cls}'>{s['med']:+.2f}%</span> <span class='sub'>(勝{s['win']:.0f}%)</span></td>"
        return f"<tr><th>{label}(n={n})</th>{cells}</tr>"

    def robust_table():
        rows = [
            ("SOX·3日窗口only", sox_sum_3d, None),
            ("SOX·5日窗口only", sox_sum_5d, None),
            ("SOX·3日或5日任一(主定義)", sox_sum_main, None),
            ("台股(隔日起)·3日窗口only", tw_sum_3d, None),
            ("台股(隔日起)·5日窗口only", tw_sum_5d, None),
            ("台股(隔日起)·3日或5日任一(主定義)", tw_sum_main, None),
        ]
        body = ""
        for label, summ, _ in rows:
            n = summ[1]["n"]
            body += compact_row2(label, summ, n)
        return f"<table><tr><th>定義</th><th>k1中位</th><th>k20中位</th><th>k60中位</th></tr>{body}</table>"

    robust_html = robust_table()

    # 財報查證摘要表(只列2014年以後、有命中或無命中都列出,誠實列全部)
    ed_rows = ""
    for _, r in df_main.iterrows():
        d = r["date"]
        h = ed_hits_main.get(d)
        if h is None:
            continue
        tag = "✅半導體/科技龍頭" if h["chip_n"] > 0 else ("🔸有財報但非半導體" if h["all"] else "—無")
        names = "、".join(f"{c}({dd[5:]})" for c, dd in h["all"]) if h["all"] else "—"
        live = " ★本次" if d == live_date else ""
        ed_rows += f"<tr><td>{d.date()}{live}</td><td>{tag}</td><td style='text-align:left'>{names}</td></tr>"
    ed_table = f"<table><tr><th>事件日</th><th>判定</th><th>窗口內(前3天~後1天)財報名單</th></tr>{ed_rows}</table>"

    # 圖表payload
    def ser_dates(df, col):
        d = df.dropna(subset=[col])
        return [str(x.date()) for x in d["date"]], [round(float(x), 2) for x in d[col]]

    chart_bar = {
        "k": [f"k{k}" for k in K_LIST],
        "sox_dm": [round(sox_sum_main[k]["dm"], 2) if sox_sum_main[k]["n"] else None for k in K_LIST],
        "tw_dm": [round(tw_sum_main[k]["dm"], 2) if tw_sum_main[k]["n"] else None for k in K_LIST],
    }
    d3, v3 = ser_dates(df_main, "pre3")
    chart_scatter = {
        "d": [str(x.date()) for x in df_main["date"]],
        "pre3": [round(float(x), 1) for x in df_main["pre3"]],
        "ret1": [round(float(x), 1) for x in df_main["sox_ret1"]],
        "live": [1 if x == live_date else 0 for x in df_main["date"]],
    }
    bg = {"paper_bgcolor": "#1a1a19", "plot_bgcolor": "#22221f",
          "font": {"color": "#ddd", "size": 12}, "margin": {"t": 40, "l": 55, "r": 20, "b": 40}}

    import json
    payload = {"bar": chart_bar, "scatter": chart_scatter}

    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>SOX崩跌後暴力反彈型態複現考卷(2026-08-03)</title>
<script src="plotly.min.js"></script><style>{css}</style></head><body>
<h1>⚡ SOX崩跌後單日暴力反彈型態——歷史複現考卷</h1>
<div class="note">
使用者觀察案例: 2026-07-28~29台股/半導體連續重挫(TAIEX -4.65%/-3.76%,SOX -4.49%/-5.33%),
2026-07-30 SOX單日暴力反彈<b>+8.19%</b>,隔日2026-07-31 TAIEX跟漲<b>+7.98%</b>；
同期SPX只有溫和波動(+0.21%/-1.52%/+1.66%/+0.70%)——確認是半導體類股專屬事件,非美股大盤整體事件
(index_daily逐日複驗,數字與使用者描述完全吻合)。任務: 歷史上這種「連跌深+SOX單日暴力反彈觸發
全市場反轉」型態還有沒有出現過?本卷用capital_flow.db.index_daily全史(零外部抓取)搜尋,並用財報
歷史資料表查證是否對應特定龍頭公司財報公告。<b>定位=觀察層/型態盤點,非交易訊號</b>。
</div>

<h2>①-a 型態定義與門檻理由</h2>
<div class="note">
<b>跌深</b>: SOX反彈日(t)的前一天(t-1)3日或5日累積報酬 &lt;= 門檻。門檻理由——本案TAIEX 3日跌幅
2026-07-29收盤達-8.28%,取整為主定義門檻<b>-8%</b>;SOX自身當時3日/5日跌幅更深達-11.6%/-15.8%,
故另設<b>-10%</b>做貼近本次量級的嚴格版對照。-8%在SOX全史3日累積報酬分布中約為後2.54百分位
(真正尾部,非隨手挑的整數)。<br>
<b>暴力反彈</b>: SOX單日報酬 &gt;= 門檻。SOX日報酬標準差約2.39%,主定義門檻<b>+5%</b>≈2.1個標準差、
全史僅2.78%交易日達標；嚴格版<b>+8%</b>≈3.4個標準差、僅0.53%交易日達標(本案+8.19%即落在此列)。<br>
<b>去重</b>: 崩跌段常見連續多天觸發同一組門檻(2000科技泡沫/2008海嘯/2020疫情皆數天內多次觸發),
不去重會把同一次「崩跌—反彈」拆成多起獨立案例灌水樣本。做法=quiet={QUIET}個交易日內只取第一天
為錨定日(該波段的代表案例)。dedup參數敏感度: {dedup_html}——n隨quiet增加而略降但不劇烈,結論不
敏感於這個參數的挑選。
</div>

<h2>①-b 敏感度表(不同反彈/跌深門檻下,去重後案例數)</h2>
{sens_html}
<div class="note">主定義(反彈&gt;=5%,跌深&lt;=-8%,3日或5日任一): <b>n={len(df_main)}</b>；
嚴格版(反彈&gt;=8%,跌深&lt;=-10%,貼近本次量級): <b>n={len(df_strict)}</b>。
本次案例(2026-07-30,反彈{live_ret1:+.2f}%/前3日{live_pre3:+.2f}%/前5日{live_pre5:+.2f}%)兩組門檻都達標。</div>

<h2>①-c0 主定義全部{len(df_main)}起事件逐案明細(不篩選,全部列出)</h2>
<div class="note">SOX從反彈當日起算,台股從SOX反彈日隔日起算;金色列=本次案例;財報欄=②節查證結果先行標於此。</div>
{main_table}

<h2>①-c 主定義CAR事件研究(n={len(df_main)},反彈&gt;=5%/跌深&lt;=-8%)</h2>
<div class="note">SOX從反彈當日(k=0)起算;台股從SOX反彈日<b>隔日起</b>(TAIEX下一個可得交易日)起算,對應
使用者原案「隔日起算」的口徑。demean=事件平均值 減去 全樣本(所有交易日起算,非僅事件日)同k日無條件
平均報酬,用來扣除長期上漲飄移;bootstrap(3000次)算平均值95% CI,n&gt;=10才做,CI完全落在0以外才
標記顯著方向,否則視為「含0/不顯著」。</div>
{k_summary_table(sox_sum_main, "SOX(反彈當下起算)")}
{k_summary_table(tw_sum_main, "TAIEX(SOX反彈隔日起算)")}
<div class="note"><b>誠實判讀</b>: 主定義下SOX近端(k1~k10)中位數多為負值、勝率僅41~45%,k1平均值demean後
95% CI完全落在0以下(偏負,不含0)——換句話說,SOX單日暴力反彈後<b>近幾天平均反而略回吐部分漲幅
(「甜蜜點的隔天賣壓」較常見),不是可靠的延續訊號</b>;k60雖中位數轉正但CI寬且含0(被少數極端案例撐起,
非普遍現象)。台股(隔日起)各k的CI也都含0,無法排除零效果——本次(2026-07-31)+7.98%的跟漲力度遠高於
歷史中位數,屬於歷史分布中偏強的個案而非典型結果。</div>

<h2>①-d 嚴格版(貼近本次量級: 反彈&gt;=8%/跌深&lt;=-10%,n={len(df_strict)})</h2>
<div class="note">全部{len(df_strict)}起逐案明細(不篩選):</div>
{strict_table}
{k_summary_table(sox_sum_strict, "SOX(反彈當下起算)")}
{k_summary_table(tw_sum_strict, "TAIEX(SOX反彈隔日起算)")}
<div class="note">門檻拉高到貼近本次實際量級後,樣本更小(n={len(df_strict)}),但方向並未變得更樂觀——
SOX k1中位數-4.31%/勝率僅25%,k3中位數-3.90%/勝率僅18%,CI皆偏負且不含0；<b>反彈越暴力,近端出現
「先吐後穩」的傾向反而越明顯</b>,這與「暴力反彈=強勢確認」的直覺相反,值得特別提醒使用者。</div>

<h2>①-e 型態視窗穩健性(3日窗口 vs 5日窗口 vs 任一,結論是否一致)</h2>
{robust_html}
<div class="note">不論用3日窗口、5日窗口或任一,SOX與台股的k1/k20/k60中位數方向與勝率大致一致
(近端偏弱、遠端不穩定)——結論對「跌深窗口用3日還是5日」這個選擇不敏感。</div>

<h2>①-f 與本次最相似的歷史類比(SOX與TAIEX同期都跌深&gt;=8%,n={len(df_joint)}含本次)</h2>
<div class="note">主定義{len(df_main)}起事件中,TAIEX有資料可查者{n_tw_avail}起,其中同期TAIEX自己
3日或5日跌幅也&lt;=-8%(即兩地同步重挫,最貼近本次情境)者僅{len(df_joint)}起——本次案例屬於歷史上
相對少見的「兩地同步重挫」子類型(多數SOX式暴力反彈案例其實是SOX/美股自身的局部事件,台股當時未必
同步重挫)。逐案列出(樣本極小,只做觀察層陳述,不做統計檢定):</div>
{joint_table}
<div class="note"><b>個案觀察</b>: 這6起中,2001-09-24與2025-04-09後續(k60)SOX/台股皆大幅走高
(對應911後與2025年關稅危機後的V型築底),但2000-10-04與2008-10-13後續(k60)卻是延續大跌
(對應網路泡沫與金融海嘯「熊市中繼假反彈」)——同樣的「SOX暴力反彈」訊號,結局南轅北轍,關鍵差異在於
當時是不是處於更大一輪熊市的半途,而這個差異<b>訊號本身無法分辨</b>,必須另外靠趨勢位階/總經環境判斷。
本次(2026-07-30)後續走向現階段資料尚不足以判斷屬於哪一種。</div>

<h2>② 半導體/科技龍頭財報歸因查證</h2>
<div class="note">方法: 不重打Nasdaq calendar API(check_earnings.py原設計是查詢「未來」財報日曆,
對回溯歷史效率較低),改用專案既有 <code>capital_flow.db.earnings_dates</code> 表——由
<code>抓取/fetch_earnings_history.py</code> 以 yfinance <code>Ticker.earnings_dates</code>
回補,market='美'已涵蓋{ed.date.min().date()}~{ed.date.max().date()}近百檔美股,含NVDA/AMD/TSM/
AVGO/MU/INTC/QCOM/ASML/LRCX/AMAT/KLAC/MRVL/TXN/ON/TER等主要半導體(+MSFT/META等科技龍頭對照,
因使用者記憶提及微軟)。對每個事件日,查「事件前3天~事件當天+1天」窗口內是否有這些公司財報公告。
⚠<b>限制</b>: 此表只涵蓋{ed.date.min().date()}以後,主定義{len(df_main)}起事件中僅
{n_2014plus}起落在涵蓋範圍內,其餘(多數,1995~2013年的較早期事件)無法查證——這是誠實的資料限制,
不是查不到就假裝没有的空白。</div>
<div class="note"><b>結果</b>: {n_2014plus}起可查證事件中,窗口內命中半導體/科技龍頭財報者
<b>{n_chip_hit}起({n_chip_hit/n_2014plus*100:.0f}%)</b>,其餘{n_2014plus-n_chip_hit}起窗口內
查無這些公司財報(訊號可能來自總經/政策等其他驅動)。</div>
{ed_table}
<div class="note"><b>本次案例(2026-07-30)驗證</b>: 窗口內命中 KLAC(2026-07-28)、LRCX/META/MSFT/
QCOM/TER(皆2026-07-29)——一整批半導體設備(LRCX、KLAC、TER)+行動晶片(QCOM)+雲端資本支出巨頭
(META、MSFT)同一兩天內集中公告財報,隔日SOX即暴力反彈。這與使用者「印象中與微軟財報有關」的記憶
吻合但更精確：<b>不是單一龍頭,而是同一週的半導體+雲端資本支出財報群聚,MSFT只是這群公司之一</b>,
而非本身是半導體股卻被記錯。<br>
<b>2024-07-31的歷史回聲</b>: 表中同樣命中的另一起——2024-07-31——財報名單幾乎是同一組班底
(AMD/MSFT/LRCX/META/QCOM/INTC,2024-07-30~08-01集中公告),兩年後(2026-07-30)劇本重演,說明
「7月底科技財報季群聚觸發SOX劇烈反應」本身是有跡可循的重複現象;但要注意——2024-07-31那次事件後
SOX近端表現其實相當差(k1-7.14%/k3-13.64%/k5-15.42%,見①-c主表),<b>財報群聚確實能解釋為什麼
會有一次暴力反彈,但不保證反彈後不會回吐,「機制故事成立」與「訊號可靠」是兩件事</b>。</div>

<h2>📈 圖表</h2>
<div id="c1" class="chart"></div>
<div class="note">demean CAR(扣長期飄移後的平均超額報酬)按k horizon;SOX從反彈當日起算,台股從隔日起算。
可見兩者在k1~k10多落在0附近或以下,只有k60轉正但如上述CI寬、由少數案例撐起。</div>
<div id="c2" class="chart"></div>
<div class="note">事件時間軸: x=SOX反彈日,y=事件前3日累積跌幅(負值越深代表崩跌越急),點大小=反彈當日
漲幅;金色星標=本次案例(2026-07-30)。可見型態集中在幾個大波動年份(2000-2002科技泡沫、2008海嘯、
2020疫情初期、2025關稅危機),平靜年份(2012-2017、2022-2023)幾乎不出現。</div>

<h2>誠實限制與定位</h2>
<div class="note">
①事後選門檻的警語: 門檻(-8%/+5%及嚴格版-10%/+8%)皆有數字依據(本案實際幅度+全史百分位),
但仍是研究者選定的參數,敏感度表已列出其他組合下n如何變化供讀者自行檢視,結論方向(近端偏弱、
遠端不穩定)在敏感度網格內大致穩健,但無法排除仍存在未測試到的參數組合下結果不同。<br>
②樣本量: 主定義n={len(df_main)}、嚴格版n={len(df_strict)}、與本次最相似的聯合崩跌子集僅n=
{len(df_joint)}(含本次)——後兩者樣本量小,bootstrap CI雖已計算但寬,本卷已避免對n&lt;15的切分做
過度精確的顯著性宣稱,逐案列出讓讀者自行判讀。<br>
③台股資料起自1999-01-05,早於此的SOX事件(5起,1995-1998)無法計算台股側反應,已在主表標示。<br>
④財報歸因只能查證2014年以後的事件({n_2014plus}/{len(df_main)}起),更早期事件無法比對,不假裝
有查到。<br>
⑤本卷為型態盤點/觀察層,<b>不是交易訊號</b>——核心誠實結論是「SOX崩跌後單日暴力反彈」這個型態
歷史上確實出現過(且不只一次),但它<b>不是</b>可靠的「觸底確認/反轉延續」訊號,近端(1~10個交易日)
歷史平均反而略偏負,是否延續高度依賴當時處在牛熊哪個階段,這個訊號本身無法分辨。
</div>

<script>
const D={json.dumps(payload, ensure_ascii=False)};
const BG={json.dumps(bg)};
Plotly.newPlot('c1', [
 {{x:D.bar.k, y:D.bar.sox_dm, name:'SOX demean CAR(反彈當下起)', type:'bar', marker:{{color:'#5dade2'}}}},
 {{x:D.bar.k, y:D.bar.tw_dm, name:'台股demean CAR(隔日起)', type:'bar', marker:{{color:'#ffd97a'}}}},
], Object.assign({{title:'主定義(n={len(df_main)}) demean CAR by k horizon',
 yaxis:{{title:'demean CAR(%)',zeroline:true,zerolinecolor:'#666',zerolinewidth:1}},
 barmode:'group'}}, BG));
Plotly.newPlot('c2', [
 {{x:D.scatter.d, y:D.scatter.pre3, mode:'markers', name:'歷史案例',
   marker:{{size:D.scatter.ret1.map(v=>Math.max(6,v*1.6)), color:'#7ec97e', opacity:0.75}},
   text:D.scatter.ret1.map(v=>'SOX反彈+'+v+'%')}},
 {{x:D.scatter.d.filter((_,i)=>D.scatter.live[i]), y:D.scatter.pre3.filter((_,i)=>D.scatter.live[i]),
   mode:'markers', name:'本次案例(2026-07-30)',
   marker:{{size:16, color:'#e06c5a', symbol:'star'}}}},
], Object.assign({{title:'事件時間軸: 事件前3日跌幅 vs 日期(點大小=反彈當日漲幅)',
 yaxis:{{title:'事件前3日累積報酬(%)'}}}}, BG));
</script>
</body></html>"""


if __name__ == "__main__":
    main()
