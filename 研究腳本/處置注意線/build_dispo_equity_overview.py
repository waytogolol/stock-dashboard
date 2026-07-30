# -*- coding: utf-8 -*-
"""處置線權益曲線總覽(2026-07-30使用者交辦「所有處置研究權益曲線合在一起」+追問「一路狂跌進處置效果差?」)
========================================================================
合併呈現(全部單利pp,同引擎同口徑,池=非人工管制∧窗6-25日∧tv3>=0.3億):
  ①V4全池(第3處置日尾盤買→出關日開盤出,net-0.45%) ②V4·20分盤 ③V4·T1甜蜜格(題材∩20分∩胃納>=2億)
  ④V5全池(倒數第3日尾盤買→出關日開盤) ⑤V5×前段跌(文件口徑:前段一直跌組較佳)
  ⑥V4+熱票逃生延長(出關時gap<=1的熱票不出場,續抱到逃生鈴響次日開盤/15日,=二進宮系列的接力版)
  ⑦前段方向三分組(使用者追問):公告前20日 狂跌<=-20% / 中性 / 大漲>=+20% 的V4表現+逐年
指標: n/勝率/平均/中位/Σpp/MDD/報酬比(Σ÷|MDD|)/夏普(單筆年化)/PF。
報告: 研究報告/research_dispo_equity_overview.html  用法: python build_dispo_equity_overview.py
"""
import json
import sqlite3
import sys
import time

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
DB = "capital_flow.db"
GREEN, RED, BLUE, YELLOW, GRAY, PURPLE = "#7ec97e", "#e06c5a", "#6bb7e3", "#c3a55a", "#8a8878", "#b57edc"
BG = {"paper_bgcolor": "#1a1a19", "plot_bgcolor": "#22221f", "font": {"color": "#ddd", "size": 12},
      "margin": {"t": 42, "l": 52, "r": 18, "b": 40}, "legend": {"orientation": "h"}}


def rd(sql, params=None, tries=6, wait=5):
    for i in range(tries):
        try:
            con = sqlite3.connect(DB, timeout=30)
            df = pd.read_sql(sql, con, params=params)
            con.close()
            return df
        except sqlite3.OperationalError as e:
            if "locked" in str(e) and i < tries - 1:
                time.sleep(wait)
            else:
                raise


def build():
    disp = rd("SELECT code, announce_date, start_date, end_date, reason, match_min FROM disposition")
    att = rd("SELECT code, announce_date, triggers FROM attention")
    cls = rd("SELECT DISTINCT code FROM classification WHERE country='台'")
    theme_codes = set(cls.code)
    for c in ("announce_date", "start_date", "end_date"):
        disp[c] = pd.to_datetime(disp[c], errors="coerce")
    att["announce_date"] = pd.to_datetime(att.announce_date)
    disp = disp.dropna(subset=["start_date", "end_date"]).sort_values("announce_date")
    disp = disp[disp.code.str.fullmatch(r"\d{4}", na=False)]
    cal = pd.to_datetime(rd("SELECT DISTINCT date FROM fm_daily_price ORDER BY date").date)
    pos = {d: i for i, d in enumerate(cal)}
    codes = sorted(disp.code.unique())
    ph = ",".join("?" * len(codes))
    px = rd(f"SELECT code, date, open, close, money FROM fm_daily_price WHERE code IN ({ph}) "
            f"ORDER BY code, date", codes)
    px["date"] = pd.to_datetime(px.date)
    pmap = {c: g.sort_values("date").reset_index(drop=True) for c, g in px.groupby("code")}

    def c18(t):
        return any(x in {"1", "2", "3", "4", "5", "6", "7", "8"} for x in str(t or "").split(","))

    att18 = att[att.triggers.map(c18)]
    att_by = {c: set(pos[d] for d in g.announce_date if d in pos) for c, g in att18.groupby("code")}
    disp_by = dict(tuple(disp.groupby("code")))

    rows = []
    for _, e in disp.iterrows():
        g = pmap.get(e.code)
        if g is None or "人工管制" in str(e.reason):
            continue
        dts = g.date.values
        n = len(g)
        s = int(np.searchsorted(dts, np.datetime64(e.start_date)))
        en = int(np.searchsorted(dts, np.datetime64(e.end_date), side="right") - 1)
        if s >= n or en <= s or en - s > 25 or en - s < 6 or en + 1 >= n:
            continue
        c_, o_, m_ = g["close"].values, g["open"].values, g["money"].values
        if c_[s + 2] <= 0 or o_[en + 1] <= 0:
            continue
        tv3 = m_[s + 2] / 1e8
        if tv3 < 0.3:
            continue
        mm = str(e.match_min)
        theme = e.code in theme_codes
        tier = 1 if (theme and mm == "20") else (2 if theme else (3 if mm == "20" else 4))
        if tier == 4:
            continue
        cap = m_[max(0, s - 20):s].mean() / 1e8 if s >= 5 else np.nan
        v4 = (o_[en + 1] / c_[s + 2] - 1) * 100 - 0.45
        v5 = (o_[en + 1] / c_[en - 2] - 1) * 100 - 0.45 if en - 2 > s and c_[en - 2] > 0 else np.nan
        pre_v5 = (c_[en - 2] / c_[s - 1] - 1) * 100 if s >= 1 and c_[s - 1] > 0 and en - 2 > s else np.nan
        # 公告前20日報酬(使用者追問的方向分組;錨=公告日或窗首日前一日)
        ai = int(np.searchsorted(dts, np.datetime64(e.announce_date))) if pd.notna(e.announce_date) else s
        ai = min(ai, n - 1)
        r20pre = (c_[ai - 1] / c_[ai - 21] - 1) * 100 if ai >= 21 and c_[ai - 21] > 0 else np.nan
        # 出關熱度+逃生延長(⑥):熱票不出,續抱到逃生鈴/15日
        ei_cal = pos.get(pd.Timestamp(e.end_date))
        v4ext, hot = v4, False
        if ei_cal is not None:
            A = att_by.get(e.code, set())
            n10 = sum(1 for i in A if ei_cal - 9 <= i <= ei_cal)
            n30 = sum(1 for i in A if ei_cal - 29 <= i <= ei_cal)
            hot = min(6 - n10, 12 - n30) <= 1
            if hot and en + 16 < n:
                gpos = {pos[d]: i for i, d in enumerate(g.date) if d in pos}
                nxt = disp_by[e.code]
                nxt = nxt[nxt.announce_date > e.end_date]
                ann_pos = (pos.get(nxt.announce_date.iloc[0])
                           if len(nxt) and nxt.announce_date.iloc[0] in pos else None)
                exit_px = None
                for t in range(ei_cal + 1, ei_cal + 16):
                    gi = gpos.get(t)
                    if gi is None:
                        continue
                    n10t = sum(1 for i in A if t - 9 <= i <= t)
                    n30t = sum(1 for i in A if t - 29 <= i <= t)
                    trig = (t in A) and min(6 - n10t, 12 - n30t) <= 1
                    if (ann_pos is not None and t == ann_pos) or trig:
                        if gi + 1 < n and o_[gi + 1] > 0:
                            exit_px = o_[gi + 1]
                        break
                if exit_px is None:
                    gi15 = gpos.get(ei_cal + 15)
                    exit_px = c_[gi15] if gi15 is not None else c_[min(n - 1, en + 15)]
                v4ext = (exit_px / c_[s + 2] - 1) * 100 - 0.45
        rows.append({"code": e.code, "end": e.end_date, "y": e.end_date.year,
                     "tier": tier, "mins": mm, "tv3": tv3, "cap": cap,
                     "v4": v4, "v5": v5, "pre_v5": pre_v5, "r20pre": r20pre,
                     "hot": hot, "v4ext": v4ext})
    ev = pd.DataFrame(rows)
    return ev[ev.end >= "2019-01-01"].reset_index(drop=True)


def perf(sub, col, label):
    s = sub.dropna(subset=[col]).sort_values("end")
    r = s[col].values
    if len(r) < 5:
        return None
    cum = np.cumsum(r)
    mdd = float((cum - np.maximum.accumulate(cum)).min())
    yrs = max((s.end.max() - s.end.min()).days / 365.25, 0.5)
    sharpe = float(np.mean(r) / np.std(r) * np.sqrt(len(r) / yrs)) if np.std(r) > 0 else np.nan
    return {"label": label, "x": [str(d.date()) for d in s.end],
            "cum": [round(float(v), 1) for v in cum], "n": len(r),
            "win": float((r > 0).mean() * 100), "avg": float(np.mean(r)),
            "med": float(np.median(r)), "sum": float(cum[-1]), "mdd": mdd,
            "rmdd": float(cum[-1] / abs(mdd)) if mdd < 0 else np.nan, "sharpe": sharpe,
            "pf": float(-r[r > 0].sum() / r[r <= 0].sum()) if (r <= 0).any() else np.nan}


def main():
    ev = build()
    print(f"處置事件池 n={len(ev)} ({ev.end.min().date()}~{ev.end.max().date()}) "
          f"熱票{ev.hot.sum()}")
    lines = [
        (perf(ev, "v4", "①V4全池"), RED),
        (perf(ev[ev.mins == "20"], "v4", "②V4·20分盤"), YELLOW),
        (perf(ev[(ev.tier == 1) & (ev.cap >= 2)], "v4", "③V4·T1甜蜜格"), GREEN),
        (perf(ev, "v5", "④V5全池"), BLUE),
        (perf(ev[ev.pre_v5 < 0], "v5", "⑤V5×前段跌"), PURPLE),
        (perf(ev, "v4ext", "⑥V4+熱票逃生延長"), GRAY),
    ]
    hdr = f"{'線':<16}{'n':>6}{'勝率':>6}{'平均':>8}{'中位':>8}{'Σpp':>9}{'MDD':>9}{'報酬/MDD':>9}{'夏普':>7}{'PF':>6}"
    print("\n" + hdr)
    for st, _ in lines:
        if st:
            print(f"{st['label']:<16}{st['n']:>6}{st['win']:>5.0f}%{st['avg']:>+8.2f}{st['med']:>+8.2f}"
                  f"{st['sum']:>+9.0f}{st['mdd']:>+9.0f}{st['rmdd']:>9.2f}{st['sharpe']:>7.2f}{st['pf']:>6.2f}")

    # ---- ⑦前段方向(使用者追問「一路狂跌進處置效果差?」) ----
    print("\n===== ⑦公告前20日方向 × V4 =====")
    dir_groups = [("狂跌組(r20pre<=-20%)", ev[ev.r20pre <= -20]),
                  ("溫跌組(-20~0)", ev[(ev.r20pre > -20) & (ev.r20pre < 0)]),
                  ("溫漲組(0~+20)", ev[(ev.r20pre >= 0) & (ev.r20pre < 20)]),
                  ("大漲組(>=+20%)", ev[ev.r20pre >= 20])]
    dir_stats = []
    for lab, sub in dir_groups:
        st = perf(sub, "v4", lab)
        dir_stats.append(st)
        if st:
            print(f"{lab:<20} n={st['n']:>4} 勝{st['win']:.0f}% 中位{st['med']:+.2f}% "
                  f"Σ{st['sum']:+.0f}pp 報酬比{st['rmdd']:.2f} 夏普{st['sharpe']:.2f}")
    print("狂跌組逐年(中位/勝率):")
    yr_fall = []
    for y, g in ev[ev.r20pre <= -20].groupby("y"):
        r = g.v4.dropna()
        if len(r) >= 3:
            yr_fall.append((y, float(r.median()), float((r > 0).mean() * 100), len(r)))
            print(f"  {y}: {r.median():+.2f}%/{(r > 0).mean() * 100:.0f}%(n={len(r)})")

    # ---- 報告 ----
    traces = []
    for st, color in lines:
        if st:
            traces.append({"x": st["x"], "y": st["cum"],
                           "name": f"{st['label']}(Σ{st['sum']:+.0f},R/MDD{st['rmdd']:.1f},夏普{st['sharpe']:.1f})",
                           "mode": "lines", "line": {"color": color, "width": 2},
                           "hovertemplate": "%{x}: %{y}pp<extra>" + st["label"] + "</extra>"})

    def tbl(stats_list, title):
        h = (f"<table><tr><th>{title}</th><th>n</th><th>勝率</th><th>平均</th><th>中位</th>"
             f"<th>Σpp</th><th>MDD</th><th>報酬/MDD</th><th>夏普</th><th>PF</th></tr>")
        for st in stats_list:
            if not st:
                continue
            h += (f"<tr><th>{st['label']}</th><td>{st['n']}</td><td>{st['win']:.0f}%</td>"
                  f"<td>{st['avg']:+.2f}%</td><td>{st['med']:+.2f}%</td><td>{st['sum']:+.0f}</td>"
                  f"<td>{st['mdd']:+.0f}</td><td><b>{st['rmdd']:.2f}</b></td>"
                  f"<td><b>{st['sharpe']:.2f}</b></td><td>{st['pf']:.2f}</td></tr>")
        return h + "</table>"

    yrt = "<table><tr><th>狂跌組逐年</th><th>中位/勝率</th><th>n</th></tr>" + "".join(
        f"<tr><th>{y}</th><td class='{'good' if m > 0 else 'bad'}'>{m:+.2f}%/{w:.0f}%</td><td>{n}</td></tr>"
        for y, m, w, n in yr_fall) + "</table>"

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>處置線權益曲線總覽(2026-07-30)</title>
<script src="plotly.min.js"></script><style>
body{{background:#1a1a19;color:#fff;font-family:"Noto Sans TC",sans-serif;margin:24px;max-width:1100px}}
h1{{font-size:20px}} h2{{font-size:15px;color:#c3c2b7;margin-top:28px;border-bottom:1px solid #333;padding-bottom:4px}}
table{{border-collapse:collapse;font-size:13px;font-variant-numeric:tabular-nums;margin:8px 0}}
td,th{{border:1px solid #333;padding:4px 10px;text-align:right}} th{{text-align:left;color:#c3c2b7}}
.note{{color:#8a8878;font-size:12.5px;line-height:1.8}} .good{{color:{GREEN}}} .bad{{color:{RED}}}
.warn{{color:{YELLOW}}} .hl{{background:#2a2a28}}</style></head><body>
<h1>📈 處置線權益曲線總覽——全部策略一張圖(2026-07-30)</h1>
<div class="note">同引擎同口徑(池=非人工管制∧窗6-25日∧tv3≥0.3億∧T1-T3;單利pp;net含-0.45%成本):
V4=第3處置日尾盤買→出關日開盤出/V5=倒數第3日尾盤買→出關日開盤/T1甜蜜格=題材∩20分∩胃納≥2億/
熱票逃生延長=出關gap≤1者續抱到逃生鈴響次日開盤(二進宮系列)。⚠單利累加讀形狀,別讀絕對值;
各線交易高度重疊(同一事件的不同切法),不能加總當組合。產生器build_dispo_equity_overview.py。</div>
<div id="c_eq" style="height:460px"></div>
<h2>績效總表</h2>
{tbl([st for st, _ in lines], "策略線")}
<h2>⑦公告前方向×V4(2026-07-30使用者追問「一路狂跌進處置效果差?」)</h2>
{tbl(dir_stats, "公告前20日方向")}
{yrt}
<h2>限制</h2>
<div class="note">各線同源重疊≠可加總;逃生延長=觀察層(escape近似,未預註冊);V5×前段跌口徑=窗首日前收→倒數第3日收;
狂跌/大漲分組錨=公告日前20交易日;無滑價模型(分盤實際成交難度未計);2019前無資料。</div>
</body><script>const BG={json.dumps(BG)};
Plotly.newPlot('c_eq',{json.dumps(traces, ensure_ascii=False)},
Object.assign({{"title":"處置線全家權益曲線(單利pp)","yaxis":{{"title":"累計pp"}}}},BG));</script></html>"""
    out = "研究報告/research_dispo_equity_overview.html"
    open(out, "w", encoding="utf-8").write(html)
    print(f"\n報告已產出 {out} ({len(html):,} chars)")


if __name__ == "__main__":
    main()
