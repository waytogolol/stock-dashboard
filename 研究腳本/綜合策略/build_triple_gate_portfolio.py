# -*- coding: utf-8 -*-
"""三重門檻組合層考卷(2026-08-05,承接build_newhigh_gm_interaction.py同日判決)。

三重門檻=題材成員×90日獨立突破×最新季毛利率QoQ改善(事件層k40絕對+7.25%/demean+3.84✓/
賺賠比2.18/逐年12/12)。事件層漂亮不等於組合能做(週級動能127x教訓)——本卷把它翻成錢的視角:
逐日重疊事件的組合NAV,答「這條線離上板還差什麼」。

═══ 考題(預先註冊) ═══
Q1 組合指標: 進場=訊號次日收盤(零前視),持有H=20/40/60交易日(收對收對稱),同一檔在持有中
   再觸發不加碼(去重);日頻等權再平衡,空手期0%;成本來回0/0.5/1.0%。
   輸出=NAV/年化/MDD/夏普/Calmar/勝率/賺賠比/PF/曝險/平均並行檔數/逐年(展望理論排序判讀)。
Q2 對照線: ①三重門檻(主) ②題材成員×90日突破(無gm門檻,量gm層在組合層的增量)
   ③題材成員×240日突破(52週版,不疊gm——交乘卷判決52週不用疊) ④90日突破全體(無題材門檻)。
Q3 split-half: 2015-2020 vs 2021-2026分段指標(三因子雖無調參,穩定度要看)。
Q4 容量: 事件日均觸發檔數/成交額分布(0.3億池內),n_max並行。

口徑: 池=20日均額>=0.3億(前一日止);財報avail_date法定期限+5日;fm_daily_price close>0 AND money>0;
除權息未還原=保守偏誤(長持有卷影響較大,誠實揭露)。

用法: python 研究腳本/綜合策略/build_triple_gate_portfolio.py  (從根目錄執行,鐵律)
產出: 研究報告/research_triple_gate_portfolio.html + console
"""
import json
import sqlite3
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

DB = "capital_flow.db"
OUT = "研究報告/research_triple_gate_portfolio.html"
START = "2015-01-01"
LIQ_MIN = 0.3e8
FRESH_GAP = 20
H_LIST = [20, 40, 60]
COST_SIDES = [0.0, 0.0025, 0.005]
SPLIT = "2021-01-01"
BUFFER_DAYS = 5
STATUTORY = {1: (5, 15, 0), 2: (8, 14, 0), 3: (11, 14, 0), 4: (3, 31, 1)}
rng = np.random.default_rng(20260805)

GREEN, RED, BLUE, YELLOW, GRAY = "#7ec97e", "#e06c5a", "#6bb7e3", "#c3a55a", "#8a8878"
BG = {"paper_bgcolor": "#1a1a19", "plot_bgcolor": "#22221f",
      "font": {"color": "#ddd", "size": 12}, "margin": {"t": 42, "l": 52, "r": 18, "b": 40},
      "legend": {"orientation": "h"}}


def avail_date(quarter_end):
    qe = pd.Timestamp(quarter_end)
    q = (qe.month - 1) // 3 + 1
    m, d, yoff = STATUTORY[q]
    return pd.Timestamp(qe.year + yoff, m, d) + pd.Timedelta(days=BUFFER_DAYS)


def load_fund():
    conn = sqlite3.connect(DB, timeout=60)
    fin = pd.read_sql("SELECT code, date, gross_margin FROM tw_quarterly_financials_history",
                      conn, parse_dates=["date"])
    conn.close()
    rows = []
    for code, g in fin.groupby("code"):
        g = g.sort_values("date")
        qidx = pd.PeriodIndex(g.date, freq="Q")
        g = g.set_index(qidx)
        g = g[~g.index.duplicated(keep="first")]
        full = pd.period_range(g.index.min(), g.index.max(), freq="Q")
        g = g.reindex(full)
        gm = g.gross_margin * 100
        f = pd.DataFrame({"gm_chg": gm - gm.shift(1)})
        f["avail"] = [avail_date(p.end_time.normalize()) for p in f.index]
        f["code"] = code
        f = f[g.date.notna().values]
        rows.append(f)
    return pd.concat(rows, ignore_index=True).dropna(subset=["gm_chg"]).sort_values("avail")


def main():
    conn = sqlite3.connect(DB, timeout=60)
    px = pd.read_sql("SELECT code,date,close,money FROM fm_daily_price "
                     "WHERE date>='2013-01-01' AND close>0 AND money>0", conn)
    tai = pd.read_sql("SELECT date,close FROM index_daily WHERE market='TAIEX' "
                      "AND date>='2013-01-01' ORDER BY date", conn)
    theme_codes = {r[0] for r in conn.execute(
        "select distinct code from classification where country='台'")}
    conn.close()
    fund = load_fund()

    C = px.pivot_table(index="date", columns="code", values="close", aggfunc="first").sort_index()
    MN = px.pivot_table(index="date", columns="code", values="money", aggfunc="first").sort_index()
    tai = tai.set_index("date")["close"]
    dates = list(C.index)
    dpos = {d: i for i, d in enumerate(dates)}
    start_i = int(np.searchsorted(np.array(dates), START))
    liq_ok = (MN.rolling(20, min_periods=15).mean().shift(1) >= LIQ_MIN)
    Cf = C.ffill(limit=5)
    is_theme = np.array([c in theme_codes for c in C.columns])

    # gm map: code -> (avail_dates, gm_chg)
    fundmap = {c: (g.avail.values, g.gm_chg.values) for c, g in fund.groupby("code")}

    def gm_at(code, d):
        fm = fundmap.get(code)
        if fm is None:
            return np.nan
        k = int(np.searchsorted(fm[0], np.datetime64(d), side="right")) - 1
        if k < 0 or (pd.Timestamp(d) - pd.Timestamp(fm[0][k])).days > 200:
            return np.nan
        return fm[1][k]

    def build_events(N, need_theme, need_gm):
        rmax = C.rolling(N, min_periods=int(N * 0.8)).max()
        is_hi = (C >= rmax * 0.9999) & C.notna()
        hi_recent = is_hi.shift(1).rolling(FRESH_GAP, min_periods=1).max()
        events = []
        for i in range(start_i, len(dates) - 2):
            row = is_hi.iloc[i].values & (~hi_recent.iloc[i].values.astype(bool)) & liq_ok.iloc[i].values
            if need_theme:
                row = row & is_theme
            if not row.any():
                continue
            d = dates[i]
            for ci in np.where(row)[0]:
                code = C.columns[ci]
                if need_gm:
                    g = gm_at(code, d)
                    if not (pd.notna(g) and g > 0):
                        continue
                events.append((code, i))
        return events

    def simulate(events, hold, cost_side, lab):
        """進場=訊號次日收盤;持有hold交易日;同檔持有中再觸發跳過;日頻等權;空手0%。"""
        daily_ret = {}
        ev_rets = []
        held_until = {}          # code -> exit index(持有去重)
        n_pos = 0
        conc = {}                # i -> 並行檔數
        for code, i in sorted(events, key=lambda x: x[1]):
            e_i = i + 1
            x_i = e_i + hold
            if x_i >= len(dates):
                continue
            if held_until.get(code, -1) >= e_i:
                continue
            ci = Cf.columns.get_loc(code)
            path = Cf.iloc[e_i:x_i + 1, ci].values
            if pd.isna(path).any() or path[0] <= 0:
                continue
            held_until[code] = x_i
            n_pos += 1
            rets = np.empty(hold)
            rets[:] = path[1:] / path[:-1] - 1
            rets[0] -= cost_side
            rets[-1] -= cost_side
            for j in range(hold):
                daily_ret.setdefault(e_i + 1 + j, []).append(rets[j])
            ev_rets.append((dates[i], (1 - cost_side) * path[-1] / path[0] * (1 - cost_side) - 1))
        if not daily_ret:
            return None
        span = range(min(daily_ret), max(daily_ret) + 1)
        nav, peak, mdd = 1.0, 1.0, 0.0
        navs, nav_dates, rs = [], [], []
        for i in span:
            r_day = np.mean(daily_ret[i]) if i in daily_ret else 0.0
            nav *= 1 + r_day
            rs.append(r_day)
            peak = max(peak, nav)
            mdd = min(mdd, nav / peak - 1)
            navs.append(nav)
            nav_dates.append(dates[i])
        rs = np.array(rs)
        yrs = len(rs) / 252
        ann = nav ** (1 / yrs) - 1
        shp = rs.mean() / rs.std() * np.sqrt(252) if rs.std() > 0 else np.nan
        expo = np.mean([1 if i in daily_ret else 0 for i in span])
        avg_conc = np.mean([len(daily_ret[i]) for i in daily_ret])
        er = pd.DataFrame(ev_rets, columns=["t", "ret"])
        w, l = er[er.ret > 0].ret, er[er.ret <= 0].ret
        pf = w.sum() / abs(l.sum()) if len(l) and l.sum() < 0 else np.inf
        wl = (w.mean() / abs(l.mean())) if len(w) and len(l) else np.nan
        nav_s = pd.Series(navs, index=pd.to_datetime(nav_dates))
        ynav = nav_s.groupby(nav_s.index.year).last()
        yprev = ynav.shift(1)
        yprev.iloc[0] = 1.0
        yearly = ((ynav / yprev - 1) * 100).round(1).to_dict()
        # split-half
        halves = {}
        for hl, mask in (("2015-2020", er.t < SPLIT), ("2021-", er.t >= SPLIT)):
            s = er[mask]
            if len(s) < 20:
                continue
            hw, hlz = s[s.ret > 0].ret, s[s.ret <= 0].ret
            halves[hl] = {"n": len(s), "mean": s.ret.mean() * 100,
                          "win": len(hw) / len(s) * 100,
                          "wl": (hw.mean() / abs(hlz.mean())) if len(hw) and len(hlz) else np.nan}
        out = {"lab": lab, "hold": hold, "cost": cost_side * 2 * 100, "n_pos": n_pos,
               "nav": nav, "ann": ann * 100, "mdd": mdd * 100, "sharpe": shp,
               "calmar": (ann * 100) / abs(mdd * 100) if mdd < 0 else np.nan,
               "expo": expo * 100, "conc": avg_conc,
               "win": len(w) / len(er) * 100, "wl": wl, "pf": pf,
               "yearly": yearly, "halves": halves, "nav_series": nav_s}
        print(f"  {lab:<30} H{hold} 成本{out['cost']:.1f}%: 事件{n_pos:,} NAV={nav:.2f} "
              f"年化{out['ann']:+.1f}% MDD{out['mdd']:.1f}% 夏普{shp:.2f} Calmar{out['calmar']:.2f} "
              f"曝險{out['expo']:.0f}% 並行{avg_conc:.1f}檔 勝率{out['win']:.0f}% 賺賠{wl:.2f} PF{pf:.2f}")
        return out

    print("=" * 100)
    print("三重門檻組合層(進場=次日收盤,日頻等權,持有去重)")
    print("=" * 100)
    ev_triple = build_events(90, True, True)
    ev_theme90 = build_events(90, True, False)
    ev_240 = build_events(240, True, False)
    ev_all90 = build_events(90, False, False)
    print(f"[events] 三重門檻{len(ev_triple):,} / 題材×90突破{len(ev_theme90):,} / "
          f"題材×240突破{len(ev_240):,} / 90突破全體{len(ev_all90):,}")

    sims = []
    print("\n【主線: 三重門檻,H×成本網格】")
    for H in H_LIST:
        for cs in COST_SIDES:
            s = simulate(ev_triple, H, cs, "①三重門檻(題材×90突破×gm改善)")
            if s:
                sims.append(s)
    print("\n【對照線(H=40,成本0.5%來回)】")
    for lab, ev in [("②題材×90突破(無gm門檻)", ev_theme90),
                    ("③題材×240突破(52週版,不疊gm)", ev_240),
                    ("④90突破全體(無題材門檻)", ev_all90)]:
        s = simulate(ev, 40, 0.0025, lab)
        if s:
            sims.append(s)
    # 大盤對照
    tai_s = tai.reindex(dates).dropna()
    tai_sub = tai_s[tai_s.index >= START]
    tai_nav = tai_sub / tai_sub.iloc[0]
    tai_ret = tai_sub.pct_change().dropna()
    tai_ann = (tai_nav.iloc[-1]) ** (252 / len(tai_ret)) - 1
    tai_dd = (tai_nav / tai_nav.cummax() - 1).min()
    print(f"\n  TAIEX同期: 年化{tai_ann * 100:+.1f}% MDD{tai_dd * 100:.1f}% "
          f"Calmar{tai_ann / abs(tai_dd):.2f}")

    # 容量
    trig_days = pd.Series([dates[i] for _, i in ev_triple]).value_counts()
    print(f"\n[容量] 三重門檻: 有觸發的日數{len(trig_days)}(全期{len(dates) - start_i}交易日), "
          f"觸發日均{trig_days.mean():.1f}檔/日, 最大單日{trig_days.max()}檔")

    main40 = next((s for s in sims if s["lab"].startswith("①") and s["hold"] == 40 and s["cost"] == 0.5), None)

    # ---------- HTML ----------
    CSS = """
body{background:#1a1a19;color:#fff;font-family:"Noto Sans TC",sans-serif;margin:24px;max-width:1200px}
h1{font-size:20px} h2{font-size:15px;color:#c3c2b7;margin-top:30px;border-bottom:1px solid #333;padding-bottom:4px}
table{border-collapse:collapse;font-size:12.5px;font-variant-numeric:tabular-nums;margin:8px 0}
td,th{border:1px solid #333;padding:4px 8px;text-align:right} th{text-align:left;color:#c3c2b7}
.note{color:#8a8878;font-size:12.5px;line-height:1.8} .good{color:#7ec97e} .bad{color:#e06c5a}
.hl{background:#2b3a2b}
ul{margin:4px 0;padding-left:20px;font-size:12.5px;color:#ccc;line-height:1.7}
.verdict{font-size:13px;font-weight:bold;padding:6px 10px;border-radius:4px;display:inline-block;margin:4px 0}
.v-good{background:#243b24;color:#7ec97e} .v-bad{background:#3b2420;color:#e06c5a}
.v-warn{background:#3b3420;color:#c3a55a}
.scroll{overflow-x:auto}
"""
    rows_html = ""
    for s in sims:
        hl = " class='hl'" if (s["lab"].startswith("①") and s["hold"] == 40 and s["cost"] == 0.5) else ""
        rows_html += (f"<tr{hl}><th>{s['lab']}</th><td>H{s['hold']}</td><td>{s['cost']:.1f}%</td>"
                      f"<td>{s['n_pos']:,}</td><td>{s['nav']:.2f}</td><td>{s['ann']:+.1f}%</td>"
                      f"<td>{s['mdd']:.1f}%</td><td>{s['sharpe']:.2f}</td><td>{s['calmar']:.2f}</td>"
                      f"<td>{s['expo']:.0f}%</td><td>{s['conc']:.1f}</td><td>{s['win']:.0f}%</td>"
                      f"<td>{s['wl']:.2f}</td><td>{s['pf']:.2f}</td></tr>")
    sim_tbl = ("<div class='scroll'><table><tr><th>線</th><th>持有</th><th>來回成本</th><th>事件</th><th>NAV</th>"
               "<th>年化</th><th>MDD</th><th>夏普</th><th>Calmar</th><th>曝險</th><th>並行</th>"
               "<th>勝率</th><th>賺賠比</th><th>PF</th></tr>" + rows_html + "</table></div>")

    yr_html, half_html = "", ""
    if main40:
        yr_html = ("<table><tr><th>年</th><th>①三重門檻H40(0.5%成本)</th></tr>"
                   + "".join(f"<tr><th>{y}</th><td class='{'good' if v > 0 else 'bad'}'>{v:+.1f}%</td></tr>"
                             for y, v in main40["yearly"].items()) + "</table>")
        half_html = ("<table><tr><th>分段(事件層)</th><th>n</th><th>單筆均值</th><th>勝率</th><th>賺賠比</th></tr>"
                     + "".join(f"<tr><th>{h}</th><td>{v['n']:,}</td><td>{v['mean']:+.2f}%</td>"
                               f"<td>{v['win']:.0f}%</td><td>{v['wl']:.2f}</td></tr>"
                               for h, v in main40["halves"].items()) + "</table>")
    nav_payload = []
    for s in sims:
        if s["cost"] == 0.5 and s["hold"] == 40:
            ns = s["nav_series"].resample("W").last().dropna()
            nav_payload.append({"name": f"{s['lab'][:14]}H40", "dates": [d.strftime("%Y-%m-%d") for d in ns.index],
                                "vals": [round(v, 4) for v in ns.values]})
    tn = tai_nav
    tn.index = pd.to_datetime(tn.index)
    tnw = tn.resample("W").last().dropna()
    nav_payload.append({"name": "TAIEX", "dates": [d.strftime("%Y-%m-%d") for d in tnw.index],
                        "vals": [round(v, 4) for v in tnw.values]})
    payload = json.dumps(nav_payload, ensure_ascii=False)

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>三重門檻組合層(2026-08-05)</title>
<script src="plotly.min.js"></script><style>{CSS}</style></head><body>
<h1>🏗️ 三重門檻組合層考卷: 題材成員×90日獨立突破×毛利率QoQ改善</h1>
<div class="note">承接research_newhigh_gm.html(事件層k40+7.25%/dm+3.84✓/逐年12/12)。本卷=錢的視角:
進場次日收盤,持有H=20/40/60(收對收),同檔持有中不加碼,日頻等權,空手0%;成本來回0/0.5/1.0%。
評估依展望理論排序: MDD小>賺賠比大>Calmar>逐期穩定>絕對報酬。</div>
{sim_tbl}
<div class="note">TAIEX同期: 年化{tai_ann * 100:+.1f}%/MDD{tai_dd * 100:.1f}%/Calmar{tai_ann / abs(tai_dd):.2f}。
容量: 觸發日均{trig_days.mean():.1f}檔/最大單日{trig_days.max()}檔(0.3億池內)。</div>
<h2>逐年(主線H40·0.5%成本)</h2>{yr_html}
<h2>split-half(事件層)</h2>{half_html}
<div id="c_nav" style="height:420px"></div>
<h2>⚖️ 判決(2026-08-05)</h2>
<ul>
<li><span class="verdict v-good">①組合層過關,而且成本不敏感</span> 主線H40·0.5%來回成本=
年化+31.6%/MDD-33.8%/夏普1.25/Calmar0.94/賺賠比2.14/PF2.34;<b>1%成本仍+27.2%/Calmar0.78</b>——
持有40日=年週轉僅~6次,成本侵蝕溫和(對比週級動能年40次週轉1.1%歸零、獨漲overlay同病)。
TAIEX同期+14.8%/MDD-31.6%/Calmar0.47: 相同量級的MDD,兩倍以上的報酬效率。split-half兩段皆正
(單筆+4.51%/+8.24%)。</li>
<li><span class="verdict v-good">②對照線的更大發現: 52週×題材(不疊gm)=全場最佳線</span>
③題材×240日突破H40: <b>年化+36.9%/MDD-32.8%/Calmar1.12/PF2.53</b>——印證交乘卷「52週突破
不需gm門檻」;②無gm的90日版+28.7%/Calmar0.92→<b>gm層在組合層增量約+2.9pp年化</b>(真實但溫和,
主要價值在事件層勝率/賺賠比的改善);④無題材門檻版+16.4%≈大盤+成本=<b>題材門檻是alpha主源</b>
——同時也是事後名單偏誤最集中的地方,誠實一體兩面。</li>
<li><b>③實務配置建議(候選)</b>: 主幹=題材成員×52週突破(H40,不看財報);衛星=三重門檻(90日,
gm改善);兩者事件天然部分重疊,合併操作時同檔去重即可。持有H40是Calmar甜蜜點(H20 MDD惡化,
H60邊際趨平)。容量: 觸發日均1.8檔/最大單日8檔,並行31-42檔=分散度天然足夠。</li>
<li><span class="verdict v-warn">④上板前的兩關</span> (a)事後名單偏誤無法用歷史資料解=
watch_triple_gate.py每日live累積樣本外,3-6個月後對照回測預期首驗;(b)次日收盤進場的尾盤
成交成本未實測(與週級動能同一未決,本卷0.5-1%情境已涵蓋合理範圍)。過這兩關前=候選層最高級,
不上板。</li>
</ul>
<h2>已知限制</h2>
<div class="note">①事後名單偏誤(題材成員)沿卷未解;②除權息未還原,H40-60長持有低估配息報酬
(保守偏誤,真實更好);③次日收盤進場的尾盤成交成本未實測(與週級動能同一未決,0.5-1%情境涵蓋);
④同檔去重後仍可能同題材多檔齊觸發(題材集中度),未做題材上限;⑤日頻等權=每日再平衡的理想化,
實務近似持有到期。</div>
<div class="note">維運: python 研究腳本/綜合策略/build_triple_gate_portfolio.py(從根目錄執行)。
姊妹: build_newhigh_gm_interaction.py(事件層)、watch_triple_gate.py(live掃描)。</div>
<script>
const NAVS={payload};
const BG={json.dumps(BG, ensure_ascii=False)};
Plotly.newPlot('c_nav', NAVS.map(s=>({{x:s.dates,y:s.vals,name:s.name,mode:'lines'}})),
  Object.assign({{title:'NAV(H40,0.5%來回成本,週頻取樣) vs TAIEX', yaxis:{{title:'NAV'}}}}, BG));
</script>
</body></html>"""
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n[report] 已輸出 {OUT}")


if __name__ == "__main__":
    main()
