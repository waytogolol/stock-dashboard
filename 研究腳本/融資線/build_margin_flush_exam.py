# -*- coding: utf-8 -*-
"""融資殺出/量能出清考卷(市場層,預註冊2026-07-29,使用者提案「法人看回檔時融資殺出多少/
量能放大到多少億=底部浮現」+追問「維持率要看20日增減速度幅度多少才出清乾淨」)
========================================================================
預註冊五題(寫死於開工前,首跑即凍結):
  E1 融資殺出幅度: 指數回檔位階(dd250<=-10%) ∧ 融資餘額20日減幅的240日位階<=5(=近一年最猛去槓桿速度)
     →episode(60日去重)→fwd k5/10/20/60。增量基準=回檔位階裸格(dd250<=-10單獨)。
  E2 量能倍數: 回檔位階 ∧ 當日成交金額/20日均>=1.5(⚠絕對億數非平稳,必須相對口徑;敏感度掃1.25/2.0)
     →episode(20日去重)。次要切分=當日漲跌方向(放量下殺vs放量反攻,描述性)。
  E3 上市×上櫃2×2(2011起): 兩市各自算E1狀態→同殺/上市單獨/上櫃單獨→兩指數fwd。
     先驗對照=警戒帶E3「兩市同破=強出清/單獨破=領跌警訊」是否在流量口徑重現。
  E4 增量對五燈(生死題): E1/E2事件日若全部落在既有燈亮窗內=重複訊號無上板價值;
     全滅日子集仍切得出fwd差才有增量。E4a全史版(警戒帶/亞跌B/雙收斂三燈,2003起)
     /E4b嚴格版(加溫度計+跌停廣度五燈,2019-03起)。
  E5 維持率速度幅度(使用者假說): a)mm20日變化pp全梯度bins×fwd(兩市)——「殺多快才出清乾淨」的正面回答
     b)融資餘額距240日高點縮減深度bins∧回檔位階(出清深度=乾淨度?)
     c)E1事件內殺出深度分半(劑量,描述性) d)機械式「等殺勢歸零(chg20>=0)再進」對照(⑱b止穩追高複驗,流量口徑)。
判準: episode去重/逐年LOTO/月群bootstrap(n>=15才給CI,否則觀察層);死格先驗=2022慢熊融資殺13個月
     連環誤觸發→2022列逐年明細必看。⚠E5a與⑱d(mm急殺門檻體檢)部分重疊,本卷=正式化+雙市+全梯度。
資料: margin_total(上市融資金額2001起)/margin_total_otc(TPEX彙總2011起,fetch_margin_total_otc.py)
     /index_daily(close+money)/margin_maintenance_official+otc。上櫃覆蓋<95%時自動跳過OTC段。
報告: 研究報告/research_margin_flush.html   用法: python build_margin_flush_exam.py
"""
import json
import sqlite3
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
DB = "capital_flow.db"
KS = [5, 10, 20, 60]
DD_TH, PCTL_TH, VOLX_TH = -10, 5, 1.5
GREEN, RED, BLUE, YELLOW, GRAY = "#7ec97e", "#e06c5a", "#6bb7e3", "#c3a55a", "#8a8878"
BG = {"paper_bgcolor": "#1a1a19", "plot_bgcolor": "#22221f",
      "font": {"color": "#ddd", "size": 12}, "margin": {"t": 42, "l": 52, "r": 18, "b": 40},
      "legend": {"orientation": "h"}}
rng = np.random.default_rng(20260729)


def fwd_map(close):
    """預算所有k的前瞻報酬DataFrame(close→close,%)。"""
    out = {}
    for k in KS:
        out[k] = (close.shift(-k) / close - 1) * 100
    return pd.DataFrame(out)


def episodes(dates, cal, sep=60):
    pos = {d: i for i, d in enumerate(cal)}
    out, last = [], -10**9
    for d in sorted(dates):
        if d in pos and pos[d] - last >= sep:
            out.append(d)
            last = pos[d]
    return out


def med_win(vals):
    v = pd.Series(vals).dropna()
    if not len(v):
        return None, None, 0
    return float(v.median()), float((v > 0).mean() * 100), len(v)


def cell(fw, days, k):
    return med_win([fw[k].get(d) for d in days])


def boot_diff(a_days, b_days, fw, k, n_iter=2000):
    """月群bootstrap: a組-b組 fwd[k]中位差 95%CI。回傳(diff, lo, hi)或None(n太小)。"""
    a = pd.Series({d: fw[k].get(d) for d in a_days}).dropna()
    b = pd.Series({d: fw[k].get(d) for d in b_days}).dropna()
    if len(a) < 15 or len(b) < 15:
        return None
    am = a.groupby(a.index.strftime("%Y-%m")).apply(list)
    bm = b.groupby(b.index.strftime("%Y-%m")).apply(list)
    diffs = []
    for _ in range(n_iter):
        av = np.concatenate([am.iloc[i] for i in rng.integers(0, len(am), len(am))])
        bv = np.concatenate([bm.iloc[i] for i in rng.integers(0, len(bm), len(bm))])
        diffs.append(np.median(av) - np.median(bv))
    d0 = float(a.median() - b.median())
    return d0, float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))


def loto_years(a_days, b_days, fw, k):
    """逐年配對: 每年(a中位-b中位),回傳(正年數, 總年數)。"""
    a = pd.Series({d: fw[k].get(d) for d in a_days}).dropna()
    b = pd.Series({d: fw[k].get(d) for d in b_days}).dropna()
    pos = tot = 0
    for y in sorted(set(a.index.year) & set(b.index.year)):
        av, bv = a[a.index.year == y], b[b.index.year == y]
        if len(av) and len(bv):
            tot += 1
            pos += (av.median() - bv.median()) > 0
    return pos, tot


def prep(close, money, bal):
    df = pd.DataFrame({"close": close, "money": money})
    df["bal"] = bal.reindex(df.index).ffill(limit=3)
    df["dd250"] = (df.close / df.close.rolling(250, min_periods=200).max() - 1) * 100
    df["chg20"] = (df.bal / df.bal.shift(20) - 1) * 100
    df["pctl240"] = df.chg20.rolling(240, min_periods=200).rank(pct=True) * 100
    df["volx"] = df.money / df.money.rolling(20).mean()
    df["bal_dd240"] = (df.bal / df.bal.rolling(240, min_periods=200).max() - 1) * 100
    df["ret1"] = df.close.pct_change() * 100
    return df


def fmt_row(label, fw, days, hi_k=(20, 60)):
    tds = ""
    for k in KS:
        m, w, n = cell(fw, days, k)
        if m is None:
            tds += "<td>—</td>"
        else:
            cls = "good" if m > 0 else "bad"
            tds += f"<td class='{cls}'>{m:+.2f}% / {w:.0f}%</td>"
    return f"<tr><th>{label} (n={len(days)})</th>{tds}</tr>"


def detail_table(title, fw, days, extra=None):
    th = "".join(f"<th>k{k}</th>" for k in KS)
    ex_th = f"<th>{extra[0]}</th>" if extra else ""
    rows = ""
    for d in days:
        cells = ""
        for k in KS:
            v = fw[k].get(d)
            cells += ("<td>—</td>" if v is None or pd.isna(v)
                      else f"<td class='{'good' if v > 0 else 'bad'}'>{v:+.2f}</td>")
        ex_td = f"<td>{extra[1].get(d, '—')}</td>" if extra else ""
        rows += f"<tr><th>{d.date()}</th>{ex_td}{cells}</tr>"
    meds, wins = "", ""
    for k in KS:
        m, w, n = cell(fw, days, k)
        meds += f"<td>{m:+.2f}</td>" if m is not None else "<td>—</td>"
        wins += f"<td>{w:.0f}%</td>" if w is not None else "<td>—</td>"
    pad = "<td></td>" if extra else ""
    return (f"<table><tr><th>{title}</th>{ex_th}{th}</tr>{rows}"
            f"<tr class='hl'><th>中位</th>{pad}{meds}</tr>"
            f"<tr class='hl'><th>勝率</th>{pad}{wins}</tr></table>")


def equity(idx_close, trig_days, hold=60):
    dates = idx_close.index
    ret = idx_close.pct_change().fillna(0.0)
    entry = {dates.get_loc(d) + 1 for d in trig_days if dates.get_loc(d) + 1 < len(dates)}
    eq, val, holding, until = [], 1.0, False, -1
    for i in range(len(dates)):
        if i in entry and not holding:
            holding, until = True, i + hold - 1
        elif holding:
            val *= 1 + ret.iloc[i]
            if i >= until:
                holding = False
        eq.append(val)
    return pd.Series(eq, index=dates)


def wtrace(s, name, color, dash=None):
    w = s.resample("W").last().dropna()
    line = {"color": color, "width": 2}
    if dash:
        line.update({"dash": dash, "width": 1.6})
    return {"x": [d.strftime("%Y-%m-%d") for d in w.index],
            "y": [round(float(v), 4) for v in w.values],
            "name": name, "mode": "lines", "line": line,
            "hovertemplate": "%{x}: %{y:.3f}<extra>" + name + "</extra>"}


def mdd(s):
    return float(((s / s.cummax()) - 1).min() * 100)


def gradient_table(df, fw, col, bins, labels, cond=None, title=""):
    """狀態級梯度表: col落在bins各格的日子×fwd20/60中位/勝率/n。回傳(html, console列, rows)。"""
    mask0 = cond if cond is not None else pd.Series(True, index=df.index)
    html = f"<table><tr><th>{title}</th><th>n日</th><th>f20中位/勝率</th><th>f60中位/勝率</th></tr>"
    lines, rows = [], []
    for (lo, hi), lab in zip(bins, labels):
        m = mask0 & (df[col] > lo) & (df[col] <= hi)
        days = df.index[m.fillna(False)]
        m20, w20, n20 = cell(fw, days, 20)
        m60, w60, n60 = cell(fw, days, 60)
        rows.append((lab, len(days), m20, w20, m60, w60))
        if m20 is None:
            html += f"<tr><th>{lab}</th><td>{len(days)}</td><td>—</td><td>—</td></tr>"
            lines.append(f"    {lab:>12}: n=0")
        else:
            c20 = "good" if m20 > 0 else "bad"
            c60 = "good" if m60 > 0 else "bad"
            html += (f"<tr><th>{lab}</th><td>{len(days)}</td>"
                     f"<td class='{c20}'>{m20:+.2f}% / {w20:.0f}%</td>"
                     f"<td class='{c60}'>{m60:+.2f}% / {w60:.0f}%</td></tr>")
            lines.append(f"    {lab:>12}: n={len(days):5d}  f20 {m20:+.2f}%/{w20:.0f}%  "
                         f"f60 {m60:+.2f}%/{w60:.0f}%")
    return html + "</table>", lines, rows


def main():
    conn = sqlite3.connect(DB)
    tw_bal = pd.read_sql("SELECT date, today_balance FROM margin_total "
                         "WHERE name='MarginPurchaseMoney' ORDER BY date",
                         conn, parse_dates=["date"]).set_index("date").today_balance
    try:
        otc_bal = pd.read_sql("SELECT date, money_today FROM margin_total_otc ORDER BY date",
                              conn, parse_dates=["date"]).set_index("date").money_today * 1000
    except Exception:
        otc_bal = pd.Series(dtype=float)
    idx = {}
    for m in ("TAIEX", "TPEx", "N225", "KOSPI", "SPX"):
        idx[m] = pd.read_sql("SELECT date, close, money FROM index_daily WHERE market=? "
                             "ORDER BY date", conn, params=(m,),
                             parse_dates=["date"]).set_index("date")
    mm_tw = pd.read_sql("SELECT date, ratio FROM margin_maintenance_official WHERE ratio>=100 "
                        "ORDER BY date", conn, parse_dates=["date"]).set_index("date").ratio
    mm_otc = pd.read_sql("SELECT date, ratio FROM margin_maintenance_otc WHERE ratio>=100 "
                         "ORDER BY date", conn, parse_dates=["date"]).set_index("date").ratio
    conn.close()

    tw = prep(idx["TAIEX"].close, idx["TAIEX"].money, tw_bal)
    tw = tw[tw.index >= "2001-01-01"]
    fw_tw = fwd_map(tw.close)
    fwmap_tw = {k: fw_tw[k] for k in KS}
    cal_tw = list(tw.index)

    otc_cal = tw.index[tw.index >= "2011-01-01"]
    otc_cov = otc_bal.reindex(otc_cal).notna().mean() * 100 if len(otc_bal) else 0.0
    has_otc = otc_cov >= 95
    print(f"上櫃融資金額覆蓋(2011起): {otc_cov:.1f}% → {'✓齊' if has_otc else '⛔未齊,OTC段跳過'}")
    if has_otc:
        op = prep(idx["TPEx"].close, idx["TPEx"].money, otc_bal)
        op = op[op.index >= "2011-01-01"]
        fw_op = fwd_map(op.close)
        fwmap_op = {k: fw_op[k] for k in KS}

    # ================= E1 融資殺出幅度 =================
    print("\n================ E1 融資殺出幅度(上市) ================")
    st_dd = (tw.dd250 <= DD_TH)
    st_e1 = st_dd & (tw.pctl240 <= PCTL_TH)
    e1 = episodes(tw.index[st_e1.fillna(False)], cal_tw)
    dd_only = episodes(tw.index[st_dd.fillna(False)], cal_tw)
    yrs = (tw.index[-1] - tw.index[0]).days / 365.25
    print(f"E1 episode n={len(e1)} ({len(e1) / yrs:.2f}次/年) | 回檔裸格episode n={len(dd_only)}")
    for lab, days in (("E1殺出", e1), ("回檔裸格", dd_only)):
        s = "  ".join(f"k{k} {cell(fwmap_tw, days, k)[0]:+.2f}%/{cell(fwmap_tw, days, k)[1]:.0f}%"
                      for k in KS if cell(fwmap_tw, days, k)[0] is not None)
        print(f"  {lab}(n={len(days)}): {s}")
    # 狀態級增量: 回檔位階內, 殺出日 vs 非殺出日
    a_days = tw.index[(st_dd & (tw.pctl240 <= PCTL_TH)).fillna(False)]
    b_days = tw.index[(st_dd & (tw.pctl240 > PCTL_TH)).fillna(False)]
    e1_boot = {}
    for k in (20, 60):
        r = boot_diff(a_days, b_days, fwmap_tw, k)
        p, t = loto_years(a_days, b_days, fwmap_tw, k)
        e1_boot[k] = (r, p, t)
        if r:
            print(f"  狀態級增量 f{k}: 殺出-其餘 {r[0]:+.2f}pp CI[{r[1]:+.2f},{r[2]:+.2f}] "
                  f"逐年{p}/{t}正 (殺出日n={len(a_days)}/其餘n={len(b_days)})")
    e1_2022 = [d for d in e1 if d.year == 2022]
    print(f"  死格檢查: 2022年E1 episode n={len(e1_2022)} {[str(d.date()) for d in e1_2022]}")

    # ================= E2 量能倍數 =================
    print("\n================ E2 量能倍數(上市) ================")
    e2_all, e2_stats = {}, {}
    for th in (1.25, VOLX_TH, 2.0):
        st = st_dd & (tw.volx >= th)
        ev = episodes(tw.index[st.fillna(False)], cal_tw, sep=20)
        e2_all[th] = ev
        m20, w20, _ = cell(fwmap_tw, ev, 20)
        m60, w60, _ = cell(fwmap_tw, ev, 60)
        tag = "◄主測" if th == VOLX_TH else ""
        print(f"  量倍>={th}: n={len(ev)}  f20 {m20:+.2f}%/{w20:.0f}%  f60 {m60:+.2f}%/{w60:.0f}% {tag}")
    e2 = e2_all[VOLX_TH]
    a2 = tw.index[(st_dd & (tw.volx >= VOLX_TH)).fillna(False)]
    b2 = tw.index[(st_dd & (tw.volx < VOLX_TH)).fillna(False)]
    e2_boot = {}
    for k in (20, 60):
        r = boot_diff(a2, b2, fwmap_tw, k)
        p, t = loto_years(a2, b2, fwmap_tw, k)
        e2_boot[k] = (r, p, t)
        if r:
            print(f"  狀態級增量 f{k}: 爆量-未爆量 {r[0]:+.2f}pp CI[{r[1]:+.2f},{r[2]:+.2f}] 逐年{p}/{t}正")
    # 次要: 方向切分(狀態級,描述)
    dir_rows = []
    for lab, mask in (("放量下殺(ret1<=-1%)", st_dd & (tw.volx >= VOLX_TH) & (tw.ret1 <= -1)),
                      ("放量反攻(ret1>=+1%)", st_dd & (tw.volx >= VOLX_TH) & (tw.ret1 >= 1)),
                      ("放量平盤(中間)", st_dd & (tw.volx >= VOLX_TH) & (tw.ret1.abs() < 1))):
        days = tw.index[mask.fillna(False)]
        m20, w20, _ = cell(fwmap_tw, days, 20)
        m60, w60, _ = cell(fwmap_tw, days, 60)
        dir_rows.append((lab, len(days), m20, w20, m60, w60))
        if m20 is not None:
            print(f"  {lab}: n={len(days)}  f20 {m20:+.2f}%/{w20:.0f}%  f60 {m60:+.2f}%/{w60:.0f}%")

    # ================= E3 上市×上櫃 2×2 =================
    e3_res = None
    if has_otc:
        print("\n================ E3 上市×上櫃 2×2(2011起) ================")
        st_tw_flush = (st_e1.reindex(op.index)).fillna(False)
        st_op_flush = ((op.dd250 <= DD_TH) & (op.pctl240 <= PCTL_TH)).fillna(False)
        e1_op = episodes(op.index[st_op_flush], list(op.index))
        e1_tw_11 = [d for d in e1 if d >= pd.Timestamp("2011-01-01")]
        union_days = sorted(set(e1_tw_11) | set(e1_op))
        union_ep = episodes(union_days, cal_tw, sep=20)
        both, tw_only, op_only = [], [], []
        for d in union_ep:
            t_f = bool(st_e1.get(d, False))
            o_f = bool(st_op_flush.get(d, False))
            (both if (t_f and o_f) else tw_only if t_f else op_only).append(d)
        print(f"  同殺n={len(both)} 上市單獨n={len(tw_only)} 上櫃單獨n={len(op_only)} "
              f"(上櫃E1 episode n={len(e1_op)})")
        e3_res = {"both": both, "tw_only": tw_only, "op_only": op_only, "e1_op": e1_op}
        for lab, days in (("兩市同殺", both), ("上市單獨", tw_only), ("上櫃單獨", op_only)):
            for mkt, fwm in (("加權", fwmap_tw), ("櫃買", fwmap_op)):
                vals = []
                for k in KS:
                    m, w, n = cell(fwm, days, k)
                    vals.append(f"k{k} {m:+.2f}%/{w:.0f}%" if m is not None else f"k{k} —")
                print(f"  {lab}→{mkt}: n={len(days)}  " + "  ".join(vals))
    else:
        print("\nE3: 上櫃覆蓋未齊,跳過(回補完成後重跑本腳本)")

    # ================= E4 對五燈增量(生死題) =================
    print("\n================ E4 對既有燈的增量(生死題) ================")
    n2r = idx["N225"].close.pct_change() * 100
    kor = idx["KOSPI"].close.pct_change() * 100
    spr = idx["SPX"].close.pct_change() * 100
    spr_prev = spr.reindex(tw.index, method="ffill").shift(0)

    def us_prev(d):
        si = spr.index.searchsorted(d) - 1
        return float(spr.iloc[si]) if si >= 0 else np.nan

    b_days_l = []
    conv_days_l = []
    drop10 = (tw.close / tw.close.shift(10) - 1) * 100
    for d in tw.index:
        nv = n2r.get(d, np.nan)
        kv = kor.get(d, np.nan)
        uv = us_prev(d)
        if pd.notna(nv) and pd.notna(kv) and pd.notna(uv) and nv <= -2 and kv <= -2 and uv > -1:
            b_days_l.append(d)
        dv, rv, d10 = tw.dd250.get(d), tw.ret1.get(d), drop10.get(d)
        if (pd.notna(dv) and -20 < dv <= DD_TH and pd.notna(rv) and rv <= -2
                and pd.notna(d10) and d10 <= -6):
            conv_days_l.append(d)
    mm_tw_d = mm_tw.reindex(tw.index).ffill()
    warn_state = (mm_tw_d < 150).fillna(False)

    def window_mask(days, hold):
        m = pd.Series(False, index=tw.index)
        pos = {d: i for i, d in enumerate(tw.index)}
        arr = m.values
        for d in days:
            i = pos.get(d)
            if i is not None:
                arr[i:i + hold] = True
        return pd.Series(arr, index=tw.index)

    lit3 = warn_state | window_mask(b_days_l, 10) | window_mask(conv_days_l, 20)
    # 五燈嚴格(2019-03起): 加溫度計/跌停廣度
    p_panel = pd.read_pickle("快取/tmp_panic_gradient_panel.pkl")
    ss = p_panel[(p_panel.i1 == "-6~-9") & (p_panel.i2 == ">=20%")]
    sweet_cnt = ss.groupby("d0").size()
    thermo_days = [d for d in sweet_cnt.index[sweet_cnt >= 20] if d in set(tw.index)]
    lfp = pd.read_pickle("快取/tmp_limit_flags.pkl")
    ldc = lfp[~lfp.code.str.startswith("00")].groupby("date").ld_close.sum()
    ld_days = [d for d in ldc.index[ldc >= 20] if d in set(tw.index)]
    lit5 = lit3 | window_mask(thermo_days, 60) | window_mask(ld_days, 20)

    e4_out = {}
    for tag, lit, w0, sig_days in (("E4a全史三燈", lit3, "2003-01-01", e1),
                                    ("E4b五燈嚴格", lit5, "2019-03-01", e1)):
        sig = [d for d in sig_days if d >= pd.Timestamp(w0)]
        dark = [d for d in sig if not lit.get(d, False)]
        litd = [d for d in sig if lit.get(d, False)]
        rows = []
        for lab, days in ((f"{tag}·全滅日殺出", dark), (f"{tag}·燈亮日殺出", litd)):
            m20, w20, _ = cell(fwmap_tw, days, 20)
            m60, w60, _ = cell(fwmap_tw, days, 60)
            rows.append((lab, days, m20, w20, m60, w60))
            s = (f"f20 {m20:+.2f}%/{w20:.0f}%  f60 {m60:+.2f}%/{w60:.0f}%"
                 if m20 is not None else "n=0")
            print(f"  {lab}: n={len(days)}  {s}")
        e4_out[tag] = rows
    # E2對燈
    e2_dark = [d for d in e2 if d >= pd.Timestamp("2003-01-01") and not lit3.get(d, False)]
    m20, w20, _ = cell(fwmap_tw, e2_dark, 20)
    m60, w60, _ = cell(fwmap_tw, e2_dark, 60)
    if m20 is not None:
        print(f"  E2爆量·三燈全滅日: n={len(e2_dark)}  f20 {m20:+.2f}%/{w20:.0f}%  "
              f"f60 {m60:+.2f}%/{w60:.0f}%")
    e4_out["e2_dark"] = (e2_dark, m20, w20, m60, w60)

    # ================= E5 維持率速度幅度(使用者假說) =================
    print("\n================ E5 維持率20日速度幅度(使用者假說) ================")
    tw5 = tw.copy()
    tw5["mm"] = mm_tw_d
    tw5["mm_chg20"] = tw5.mm - tw5.mm.shift(20)
    bins = [(-999, -20), (-20, -15), (-15, -10), (-10, -5), (-5, -2), (-2, 2), (2, 5), (5, 999)]
    labels = ["<-20pp", "-20~-15", "-15~-10", "-10~-5", "-5~-2", "-2~+2", "+2~+5", ">+5pp"]
    print("  E5a 上市: mm20日變化梯度(全樣本狀態級)")
    g_tw_html, lines, g_tw_rows = gradient_table(tw5, fwmap_tw, "mm_chg20", bins, labels,
                                                 title="上市mm chg20")
    print("\n".join(lines))
    g_op_html, g_op_rows = "", []
    if has_otc and len(mm_otc):
        op5 = op.copy()
        op5["mm"] = mm_otc.reindex(op.index).ffill()
        op5["mm_chg20"] = op5.mm - op5.mm.shift(20)
        print("  E5a 上櫃:")
        g_op_html, lines, g_op_rows = gradient_table(op5, fwmap_op, "mm_chg20", bins, labels,
                                                     title="上櫃mm chg20")
        print("\n".join(lines))
    # E5b 融資餘額縮減深度(∧回檔位階)
    dbins = [(-5, 0), (-10, -5), (-15, -10), (-20, -15), (-30, -20), (-999, -30)]
    dlabels = ["0~-5%", "-5~-10", "-10~-15", "-15~-20", "-20~-30", "<-30%"]
    print("  E5b 上市: 融資餘額距240日高點縮減深度 ∧ 指數回檔位階<=-10")
    g_d_html, lines, g_d_rows = gradient_table(tw5, fwmap_tw, "bal_dd240",
                                               [(lo, hi) for lo, hi in dbins], dlabels,
                                               cond=st_dd, title="餘額縮減∧回檔")
    print("\n".join(lines))
    # E5c E1事件劑量分半
    e1_depth = {d: float(tw.chg20.get(d)) for d in e1 if pd.notna(tw.chg20.get(d))}
    order = sorted(e1_depth, key=e1_depth.get)
    deep, shallow = order[:len(order) // 2], order[len(order) // 2:]
    e5c = {}
    for lab, days in (("殺更深半", deep), ("殺較淺半", shallow)):
        m60, w60, _ = cell(fwmap_tw, days, 60)
        e5c[lab] = (days, m60, w60)
        print(f"  E5c {lab}: n={len(days)} chg20範圍"
              f"[{min(e1_depth[d] for d in days):+.1f},{max(e1_depth[d] for d in days):+.1f}]%"
              f"  f60 {m60:+.2f}%/{w60:.0f}%")
    # 頭條格目標bootstrap(月群): E5a極速殺 vs 其餘全樣本 / E5b乾淨格 vs 死亡谷
    hb = {}
    a = tw5.index[(tw5.mm_chg20 <= -20).fillna(False)]
    b = tw5.index[(tw5.mm_chg20 > -20).fillna(False)]
    hb["e5a_f20"] = boot_diff(a, b, fwmap_tw, 20)
    a2b = tw5.index[(st_dd & (tw5.bal_dd240 <= -30)).fillna(False)]
    b2b = tw5.index[(st_dd & (tw5.bal_dd240 > -20) & (tw5.bal_dd240 <= -10)).fillna(False)]
    hb["e5b_f60"] = boot_diff(a2b, b2b, fwmap_tw, 60)
    for lab, key in (("E5a極速殺(<-20pp)−其餘 f20", "e5a_f20"),
                     ("E5b乾淨格(<-30%)−死亡谷(-10~-20%) f60", "e5b_f60")):
        r = hb[key]
        if r:
            print(f"  頭條bootstrap {lab}: {r[0]:+.2f}pp CI[{r[1]:+.2f},{r[2]:+.2f}]"
                  f"{' ✓排0' if r[1] > 0 or r[2] < 0 else ' 含0'}")
    # E5d 等殺勢歸零再進
    wait_days = []
    posmap = {d: i for i, d in enumerate(tw.index)}
    for d in e1:
        i = posmap[d]
        seg = tw.chg20.iloc[i + 1:i + 121]
        hit = seg.index[seg >= 0]
        if len(hit):
            wait_days.append(hit[0])
    m_now, w_now, _ = cell(fwmap_tw, e1, 60)
    m_wait, w_wait, _ = cell(fwmap_tw, wait_days, 60)
    print(f"  E5d 等chg20歸零再進(n={len(wait_days)}): f60 {m_wait:+.2f}%/{w_wait:.0f}% "
          f"vs E1當下進 {m_now:+.2f}%/{w_now:.0f}%")

    # ================= 報告 =================
    charts = []
    balw = (tw.bal / 1e8).resample("W").last().dropna()
    twcw = tw.close.resample("W").last().dropna()
    tr1 = [
        {"x": [d.strftime("%Y-%m-%d") for d in balw.index], "y": [round(float(v)) for v in balw],
         "name": "上市融資餘額(億)", "mode": "lines", "line": {"color": BLUE, "width": 1.8},
         "yaxis": "y", "hovertemplate": "%{x}: %{y}億<extra>融資餘額</extra>"},
        {"x": [d.strftime("%Y-%m-%d") for d in twcw.index], "y": [round(float(v)) for v in twcw],
         "name": "加權指數", "mode": "lines", "line": {"color": GRAY, "width": 1.2},
         "yaxis": "y2", "hovertemplate": "%{x}: %{y}<extra>加權</extra>"},
        {"x": [d.strftime("%Y-%m-%d") for d in e1],
         "y": [round(float(tw.bal.asof(d) / 1e8)) for d in e1],
         "name": "E1融資殺出", "mode": "markers",
         "marker": {"color": RED, "size": 9, "symbol": "triangle-down",
                    "line": {"color": "#22221f", "width": 1}},
         "hovertemplate": "%{x} E1殺出<extra></extra>"}]
    charts.append(("c_bal", tr1,
                   {"title": "上市融資餘額全史(2001起,週線)×E1殺出事件",
                    "yaxis": {"title": "融資餘額(億)"},
                    "yaxis2": {"overlaying": "y", "side": "right", "showgrid": False,
                               "type": "log"}}))
    if has_otc:
        obw = (op.bal / 1e8).resample("W").last().dropna()
        opw = op.close.resample("W").last().dropna()
        charts.append(("c_obal", [
            {"x": [d.strftime("%Y-%m-%d") for d in obw.index], "y": [round(float(v)) for v in obw],
             "name": "上櫃融資餘額(億)", "mode": "lines", "line": {"color": YELLOW, "width": 1.8},
             "hovertemplate": "%{x}: %{y}億<extra>上櫃餘額</extra>"},
            {"x": [d.strftime("%Y-%m-%d") for d in opw.index], "y": [round(float(v), 1) for v in opw],
             "name": "櫃買指數", "mode": "lines", "line": {"color": GRAY, "width": 1.2},
             "yaxis": "y2", "hovertemplate": "%{x}: %{y}<extra>櫃買</extra>"}],
            {"title": "上櫃融資餘額(2011起,週線,TPEX彙總)",
             "yaxis": {"title": "融資餘額(億)"},
             "yaxis2": {"overlaying": "y", "side": "right", "showgrid": False}}))
    eq_e1 = equity(tw.close, e1)
    eq_dd = equity(tw.close, dd_only)
    bh = tw.close / tw.close.iloc[0]
    charts.append(("c_eq", [
        wtrace(eq_e1, f"E1殺出→加權60日({eq_e1.iloc[-1]:.2f}x,MDD{mdd(eq_e1):.0f}%)", BLUE),
        wtrace(eq_dd, f"回檔裸格→60日對照({eq_dd.iloc[-1]:.2f}x,MDD{mdd(eq_dd):.0f}%)", GREEN, "dash"),
        wtrace(bh, f"加權買進持有({bh.iloc[-1]:.2f}x,MDD{mdd(bh):.0f}%)", GRAY, "dot")],
        {"title": "權益曲線(事件T+1買加權持60日→空手;E1是時機工具,別跟滿倉比高度)",
         "yaxis": {"title": "淨值", "type": "log"}}))
    # E5a梯度長條圖
    gx = [r[0] for r in g_tw_rows]
    gy = [r[4] if r[4] is not None else 0 for r in g_tw_rows]
    gw = [f"n={r[1]},勝{r[5]:.0f}%" if r[4] is not None else "n=0" for r in g_tw_rows]
    charts.append(("c_grad", [
        {"x": gx, "y": [round(v, 2) for v in gy], "type": "bar",
         "marker": {"color": [RED if v < 0 else GREEN for v in gy]},
         "text": gw, "textposition": "outside",
         "hovertemplate": "%{x}: f60中位%{y:+.2f}%<extra></extra>"}],
        {"title": "使用者假說直答:上市維持率20日變化(pp)梯度 → 之後60日中位報酬",
         "yaxis": {"title": "f60中位%"}}))

    kth = "".join(f"<th>k{k}</th>" for k in KS)
    sum_rows = fmt_row("E1融資殺出", fwmap_tw, e1) + fmt_row("回檔裸格對照", fwmap_tw, dd_only)
    if has_otc and e3_res:
        sum_rows += (fmt_row("E3兩市同殺→加權", fwmap_tw, e3_res["both"])
                     + fmt_row("E3上市單獨→加權", fwmap_tw, e3_res["tw_only"])
                     + fmt_row("E3上櫃單獨→櫃買", fwmap_op, e3_res["op_only"]))
    dirtbl = "<table><tr><th>E2次切:方向</th><th>n日</th><th>f20</th><th>f60</th></tr>"
    for lab, n, m20, w20, m60, w60 in dir_rows:
        if m20 is None:
            dirtbl += f"<tr><th>{lab}</th><td>{n}</td><td>—</td><td>—</td></tr>"
        else:
            dirtbl += (f"<tr><th>{lab}</th><td>{n}</td>"
                       f"<td class='{'good' if m20 > 0 else 'bad'}'>{m20:+.2f}%/{w20:.0f}%</td>"
                       f"<td class='{'good' if m60 > 0 else 'bad'}'>{m60:+.2f}%/{w60:.0f}%</td></tr>")
    dirtbl += "</table>"

    def bootstr(bd, k):
        r, p, t = bd[k]
        if not r:
            return "n小無CI"
        return f"{r[0]:+.2f}pp CI[{r[1]:+.2f},{r[2]:+.2f}] 逐年{p}/{t}正"

    e4tbl = "<table><tr><th>E4切分</th><th>n</th><th>f20</th><th>f60</th></tr>"
    for tag in ("E4a全史三燈", "E4b五燈嚴格"):
        for lab, days, m20, w20, m60, w60 in e4_out[tag]:
            if m20 is None:
                e4tbl += f"<tr><th>{lab}</th><td>{len(days)}</td><td>—</td><td>—</td></tr>"
            else:
                e4tbl += (f"<tr><th>{lab}</th><td>{len(days)}</td>"
                          f"<td class='{'good' if m20 > 0 else 'bad'}'>{m20:+.2f}%/{w20:.0f}%</td>"
                          f"<td class='{'good' if m60 > 0 else 'bad'}'>{m60:+.2f}%/{w60:.0f}%</td></tr>")
    ed = e4_out["e2_dark"]
    if ed[1] is not None:
        e4tbl += (f"<tr><th>E2爆量·三燈全滅</th><td>{len(ed[0])}</td>"
                  f"<td class='{'good' if ed[1] > 0 else 'bad'}'>{ed[1]:+.2f}%/{ed[2]:.0f}%</td>"
                  f"<td class='{'good' if ed[3] > 0 else 'bad'}'>{ed[3]:+.2f}%/{ed[4]:.0f}%</td></tr>")
    e4tbl += "</table>"

    detail = detail_table(f"E1融資殺出逐事件(n={len(e1)})", fwmap_tw, e1,
                          extra=("chg20", {d: f"{tw.chg20.get(d):+.1f}%" for d in e1}))
    detail_e2 = detail_table(f"E2爆量逐事件(n={len(e2)})", fwmap_tw, e2,
                             extra=("量倍", {d: f"{tw.volx.get(d):.2f}x" for d in e2}))
    e3_detail = ""
    if has_otc and e3_res:
        e3_detail = (detail_table(f"E3兩市同殺→加權(n={len(e3_res['both'])})", fwmap_tw,
                                  e3_res["both"])
                     + detail_table(f"E3上櫃單獨→櫃買(n={len(e3_res['op_only'])})", fwmap_op,
                                    e3_res["op_only"]))

    divs = "".join(f'<div id="{d}" style="height:380px"></div>' for d, _, _ in charts)
    plots = "".join(f"Plotly.newPlot('{d}',{json.dumps(t, ensure_ascii=False)},"
                    f"Object.assign({json.dumps(ly, ensure_ascii=False)},BG));"
                    for d, t, ly in charts)
    e5d_str = (f"等chg20歸零(n={len(wait_days)}) f60 {m_wait:+.2f}%/{w_wait:.0f}% vs "
               f"E1當下 {m_now:+.2f}%/{w_now:.0f}%")

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>融資殺出/量能出清考卷(2026-07-29)</title>
<script src="plotly.min.js"></script><style>
body{{background:#1a1a19;color:#fff;font-family:"Noto Sans TC",sans-serif;margin:24px;max-width:1100px}}
h1{{font-size:20px}} h2{{font-size:15px;color:#c3c2b7;margin-top:28px;border-bottom:1px solid #333;padding-bottom:4px}}
table{{border-collapse:collapse;font-size:13px;font-variant-numeric:tabular-nums;margin:8px 0}}
td,th{{border:1px solid #333;padding:4px 10px;text-align:right}} th{{text-align:left;color:#c3c2b7}}
.note{{color:#8a8878;font-size:12.5px;line-height:1.8}} .good{{color:{GREEN}}} .bad{{color:{RED}}}
.warn{{color:{YELLOW}}} .hl{{background:#2a2a28}}</style></head><body>
<h1>💸 融資殺出/量能出清考卷:市場層流量計(2026-07-29)</h1>
<div class="note">預註冊五題見build_margin_flush_exam.py docstring。資料=上市融資金額(margin_total,2001起)
/上櫃(margin_total_otc,TPEX彙總2011起)/index_daily成交金額/雙市維持率。與警戒帶的分工:
警戒帶=<b>水位計</b>(維持率絕對水位),本卷=<b>流量計</b>(融資餘額正在被殺出的速度+量能出清)。</div>

<h2>🗣️ 白話導讀</h2>
<div class="note">
<p><b>這卷在問什麼:</b>大盤已經在回檔(距一年高點跌10%以上)時,「融資餘額正在被快速砍」和
「成交量爆出來」哪個是底部訊號?以及使用者追問:維持率20日要掉多快多深,斷頭賣壓才算倒完(出清乾淨)?</p>
<p><b>機制:</b>融資餘額下降=有人被斷頭或自己砍槓桿=被迫賣壓正在釋放;殺得越急,賣壓釋放越快,
倒完的一天越近。量能放大=有人願意接這些被砍出來的股票=換手完成。</p>
<p><b>E5d重要提醒:</b>「等殺勢歸零再進」({e5d_str})——與⑱b止穩追高教訓對照,別等確認。</p>
</div>

<h2>📋 判決表(2026-07-29首跑即凍結)</h2>
<table>
<tr><th>題</th><th>判決</th><th>關鍵數字</th></tr>
<tr><td>E1 融資殺出速度位階</td><td class="bad">❌不轉正</td><td>事件層中位優於回檔裸格(k60+6.27% vs +3.46%)
但狀態級增量f60 −2.31pp CI[−6.96,+2.97]含0、逐年僅5/13——「殺出速度年相對位階」對回檔裸格無穩定加值;
死格再現=2022-06-21(慢熊中段,與溫度計唯一敗筆同窗)</td></tr>
<tr><td>E2 量能倍數</td><td class="warn">🟡候選觀察層</td><td>主測(量倍≥1.5)n=38 f60+4.94%/66%;
狀態級f20+3.00pp逐年13/16正但CI[−0.82,+7.37]含0;最肥子格=<b>放量下殺日(f60+11.05%/81%,n=21)</b>=
爆量長黑出清形狀,與「不買止穩買出清」同構(次切描述性,未預註冊)</td></tr>
<tr><td>E3 兩市同殺2×2</td><td class="good">✅同構重現</td><td><b>兩市同殺(n=5):k60加權+8.21%/75%、櫃買+7.97%/100%;
上市單獨(n=4)短線全負、上櫃單獨(n=6)平庸</b>——與警戒帶E3「兩市同破=強出清/單獨破=別接」
水位×流量兩口徑互相印證;n小=觀察層</td></tr>
<tr><td>E4 對五燈增量(生死題)</td><td class="bad">⚠高重疊證實</td><td>E1事件19/22落在燈亮窗內=殺出訊號與五燈
高度重複(先驗猜中),全滅日n=3不足以立格;E2爆量·三燈全滅n=11 f60+3.58%/82%=量能有一絲獨立性但n小
——<b>本卷不上新燈</b>,量能倍數掛E2觀察</td></tr>
<tr><td>E5a 維持率20日速度(使用者假說)</td><td class="warn">🟡半成立</td><td>兩市同形:<b>&lt;−20pp極速殺才有肉</b>
(上市f20+4.83%/76%、上櫃f60+9.95%/77%),<b>−10~−20pp=殺一半最毒段</b>(上市f20+0.33~+0.43%);
bootstrap極速殺−其餘f20+3.57pp CI[−0.95,+6.27]含0(事件簇)=速度是「狀態讀數」非開關,與⑱d死貓跳一致</td></tr>
<tr><td>E5b 餘額縮減深度</td><td class="good">✅真發現=乾淨格</td><td><b>回檔中融資餘額距240日高點縮水&gt;30%=出清乾淨格
(f60+5.90%/71%,n=1082);縮水10~20%=死亡谷(f20 −3.03%/21%)</b>;乾淨格−死亡谷f60+6.84pp CI[+0.57,+14.20]✓排0
——「殺夠深才乾淨,殺一半最毒」的深度口徑成立</td></tr>
<tr><td>E5d 等殺勢歸零</td><td class="bad">❌又輸</td><td>等chg20回0再進f60+2.08%/67% vs E1當下+6.27%/62%
=「等止穩」第N+1度輸給「買出清」</td></tr>
</table>
<div class="note"><b>總結論:深度&gt;速度</b>——融資「殺了多少」(存量縮減深度)有資訊、「正在殺多快」(速度位階)沒有穩定增量;
乾淨格是<b>狀態帶</b>(帶內每一天),進場時點仍交給既有出清日訊號(溫度計/雙收斂/跌停廣度),與警戒帶「狀態非時點」同一句話。</div>

<h2>📋 事件層總表(中位%/勝率)</h2>
<table><tr><th>格</th>{kth}</tr>{sum_rows}</table>
<div class="note">E1狀態級增量(回檔位階內,殺出日−其餘日): f20 {bootstr(e1_boot, 20)};f60 {bootstr(e1_boot, 60)}。<br>
E2狀態級增量(爆量−未爆量): f20 {bootstr(e2_boot, 20)};f60 {bootstr(e2_boot, 60)}。<br>
E5c事件劑量: 殺更深半f60 {e5c['殺更深半'][1]:+.2f}%/{e5c['殺更深半'][2]:.0f}% vs
殺較淺半 {e5c['殺較淺半'][1]:+.2f}%/{e5c['殺較淺半'][2]:.0f}%。</div>

{divs}

<h2>E2 量能倍數:方向次切(描述性)</h2>
{dirtbl}

<h2>E4 對既有五燈的增量(生死題)</h2>
{e4tbl}
<div class="note">全滅日=事件當天不在任何燈的持有窗內(E4a=警戒帶/亞跌B/雙收斂三燈全史;
E4b加溫度計+跌停廣度,2019-03起)。若殺出訊號只在燈亮日有肉=與五燈重複,無上板價值。</div>

<h2>E5a 維持率20日變化梯度(使用者假說直答)</h2>
{g_tw_html}{g_op_html}
<div class="note">頭條bootstrap(月群): 極速殺(&lt;-20pp)−其餘 f20 = {
    f"{hb['e5a_f20'][0]:+.2f}pp CI[{hb['e5a_f20'][1]:+.2f},{hb['e5a_f20'][2]:+.2f}]"
    + ("✓排0" if hb['e5a_f20'][1] > 0 else "含0") if hb['e5a_f20'] else "n小"}。</div>
<h2>E5b 融資餘額縮減深度∧回檔位階</h2>
{g_d_html}
<div class="note">頭條bootstrap(月群): 乾淨格(&lt;-30%)−死亡谷(-10~-20%) f60 = {
    f"{hb['e5b_f60'][0]:+.2f}pp CI[{hb['e5b_f60'][1]:+.2f},{hb['e5b_f60'][2]:+.2f}]"
    + ("✓排0" if hb['e5b_f60'][1] > 0 else "含0") if hb['e5b_f60'] else "n小"}。</div>

<h2>逐事件明細</h2>
{detail}{detail_e2}{e3_detail}
<h2>限制</h2>
<div class="note">事件n小→觀察層;E5a與⑱d(mm急殺門檻體檢)部分重疊=本卷正式化;
2022慢熊死格逐事件明細必看;上櫃資料2011起(無2008);量能口徑=index_daily.money相對倍數(抗漂移);
E4b五燈窗2019-03起樣本極小。</div>
</body><script>const BG={json.dumps(BG)};{plots}</script></html>"""
    out = "研究報告/research_margin_flush.html"
    open(out, "w", encoding="utf-8").write(html)
    print(f"\n報告已產出 {out} ({len(html):,} chars, {len(charts)}圖)")


if __name__ == "__main__":
    main()
