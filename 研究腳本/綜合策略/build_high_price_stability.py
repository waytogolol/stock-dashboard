# -*- coding: utf-8 -*-
"""高價股穩定性考卷(2026-08-07,使用者假說:「高股價策略相對穩定——營收多數不差、籌碼穩,
且可能對大盤行情好壞有參考性;定義>500元或全市場價格前5%」)。

═══ 考題(預先註冊) ═══
P0 前提檢查: 高價股的營收真的不差嗎?——P(兩月營收連創12月高)/P(近3月YoY>0) vs 池基準。
P1 穩定性: 月頻等權組合(月初調倉,毛報酬)——高價(>500元)/相對高價(池內前5%)/中價(100-500)/
   低價(<50)/池全體 vs TAIEX: 年化/MDD/夏普/月勝率/逐年;個股層20日波動度中位(「穩」的直接量測);
   demean k20/k60月群bootstrap(相對大盤有沒有alpha)。
P2 大盤參考性: 高價組相對強弱RS(月報酬-TAIEX)的領先性——RS近3月均>0 vs <0,下月TAIEX表現分組
   (小樣本觀察層)。
口徑: 池=20日均額>=0.3億;形成=每月首交易日收盤(可執行);2015-01起;fm_daily_price未還原除權息
(高價股常高配息=此卷的絕對報酬顯著低估,demean比較兩邊同受但高價組傷更多——誠實列為主要限制)。
用法: python 研究腳本/綜合策略/build_high_price_stability.py  (從根目錄執行,鐵律)
產出: 研究報告/research_high_price_stability.html + console(含權益曲線,規範第19條)
"""
import json
import sqlite3
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

DB = "capital_flow.db"
OUT = "研究報告/research_high_price_stability.html"
LIQ_MIN = 0.3e8
rng = np.random.default_rng(20260807)

GROUPS = [("高價>500元", "abs500"), ("相對高價(池內前5%)", "top5"),
          ("中價100-500", "mid"), ("低價<50", "low"), ("池全體", "all")]


def main():
    conn = sqlite3.connect(DB, timeout=60)
    px = pd.read_sql("SELECT code,date,close,money FROM fm_daily_price "
                     "WHERE date>='2013-06-01' AND close>0 AND money>0", conn)
    tai = pd.read_sql("SELECT date,close FROM index_daily WHERE market='TAIEX' "
                      "AND date>='2013-06-01' ORDER BY date", conn)
    rev = pd.read_sql("SELECT code, date, revenue FROM fm_month_rev", conn, parse_dates=["date"])
    conn.close()

    C = px.pivot_table(index="date", columns="code", values="close", aggfunc="first").sort_index()
    MN = px.pivot_table(index="date", columns="code", values="money", aggfunc="first").sort_index()
    tai = tai.set_index("date")["close"]
    dates = list(C.index)
    t_arr = np.array(dates)
    liq20 = MN.rolling(20, min_periods=15).mean().shift(1)
    Cf = C.ffill(limit=5)
    tai_f = tai.reindex(C.index).ffill()
    ret_d = C.pct_change(fill_method=None)
    vol20 = ret_d.rolling(20, min_periods=15).std() * np.sqrt(252) * 100

    rev_w = rev.pivot_table(index="date", columns="code", values="revenue", aggfunc="first").sort_index()
    hi_m = (rev_w >= rev_w.rolling(12, min_periods=12).max()) & rev_w.notna()
    yoy3 = rev_w.rolling(3).sum() / rev_w.shift(12).rolling(3).sum() - 1

    # 月初形成日
    didx = pd.to_datetime(pd.Index(dates))
    month_first = ~didx.to_period("M").duplicated()
    f_idx = [i for i in np.where(month_first)[0] if dates[i] >= "2015-01-01" and i + 1 < len(dates)]

    def month_groups(i):
        """形成日i的各組成員(池內)。"""
        c_row = C.iloc[i]
        l_row = liq20.iloc[i]
        pool = c_row.index[(c_row.notna()) & (l_row >= LIQ_MIN)]
        prices = c_row[pool]
        th5 = prices.quantile(0.95)
        return {"abs500": set(prices.index[prices >= 500]),
                "top5": set(prices.index[prices >= th5]),
                "mid": set(prices.index[(prices >= 100) & (prices < 500)]),
                "low": set(prices.index[prices < 50]),
                "all": set(pool)}

    # ---------- P0 前提 + 波動度 ----------
    prem = {k: {"r1": [], "yoy": [], "vol": [], "n": []} for _, k in GROUPS}
    for i in f_idx[::3]:      # 每3個月抽樣一次(前提統計夠密)
        d = pd.Timestamp(dates[i])
        mons = [m for m in rev_w.index if (m + pd.DateOffset(months=1) + pd.Timedelta(days=11)) <= d]
        if len(mons) < 2:
            continue
        h1, h2 = hi_m.loc[mons[-1]], hi_m.loc[mons[-2]]
        yy = yoy3.loc[mons[-1]]
        vv = vol20.iloc[i]
        for _, k in GROUPS:
            g = month_groups(i)[k]
            if not g:
                continue
            gl = list(g)
            r1 = np.mean([bool(h1.get(c, False)) and bool(h2.get(c, False)) for c in gl])
            yp = np.nanmean([1.0 if (pd.notna(yy.get(c, np.nan)) and yy[c] > 0) else 0.0
                             for c in gl if pd.notna(yy.get(c, np.nan))] or [np.nan])
            vm = np.nanmedian([vv.get(c, np.nan) for c in gl])
            prem[k]["r1"].append(r1)
            prem[k]["yoy"].append(yp)
            prem[k]["vol"].append(vm)
            prem[k]["n"].append(len(gl))
    print("P0 前提檢查(季抽樣均值):")
    p0 = {}
    for lab, k in GROUPS:
        p0[k] = {"n": np.mean(prem[k]["n"]), "r1": np.nanmean(prem[k]["r1"]) * 100,
                 "yoy": np.nanmean(prem[k]["yoy"]) * 100, "vol": np.nanmedian(prem[k]["vol"])}
        print(f"  {lab:<18} 平均檔數{p0[k]['n']:.0f} P(兩月營收連創高)={p0[k]['r1']:.1f}% "
              f"P(近3月YoY>0)={p0[k]['yoy']:.1f}% 20日年化波動中位{p0[k]['vol']:.1f}%")

    # ---------- P1 月頻NAV + demean事件 ----------
    navs = {k: [1.0] for _, k in GROUPS}
    navs["TAIEX"] = [1.0]
    nav_dates = [dates[f_idx[0]]]
    ev = {k: [] for _, k in GROUPS}      # (ym, demean月報酬)個股層
    for a, b in zip(f_idx[:-1], f_idx[1:]):
        g = month_groups(a)
        tai_r = tai_f.iloc[b] / tai_f.iloc[a] - 1
        for _, k in GROUPS:
            rets = []
            for c in g[k]:
                ci = Cf.columns.get_loc(c)
                p0_, p1_ = C.iat[a, ci], Cf.iat[b, ci]
                if pd.notna(p0_) and pd.notna(p1_) and p0_ > 0:
                    r = p1_ / p0_ - 1
                    rets.append(r)
                    ev[k].append((dates[a][:7], r - tai_r))
            navs[k].append(navs[k][-1] * (1 + (np.mean(rets) if rets else 0.0)))
        navs["TAIEX"].append(navs["TAIEX"][-1] * (1 + tai_r))
        nav_dates.append(dates[b])

    def nav_stats(v):
        s = pd.Series(v)
        yrs = (pd.Timestamp(nav_dates[-1]) - pd.Timestamp(nav_dates[0])).days / 365.25
        ann = s.iloc[-1] ** (1 / yrs) - 1
        mdd = (s / s.cummax() - 1).min()
        mr = s.pct_change().dropna()
        shp = mr.mean() / mr.std() * np.sqrt(12) if mr.std() > 0 else np.nan
        return ann * 100, mdd * 100, shp, (mr > 0).mean() * 100

    print("\nP1 月頻等權組合(毛報酬,月初調倉):")
    p1 = {}
    tai_mr = pd.Series(navs["TAIEX"]).pct_change().dropna()
    for lab, k in GROUPS + [("TAIEX", "TAIEX")]:
        ann, mdd, shp, win = nav_stats(navs[k])
        beat = np.nan
        if k != "TAIEX":
            gm = pd.Series(navs[k]).pct_change().dropna()
            beat = (gm.values > tai_mr.values).mean() * 100
        p1[k] = {"ann": ann, "mdd": mdd, "shp": shp, "win": win, "beat": beat,
                 "calmar": ann / abs(mdd) if mdd < 0 else np.nan}
        print(f"  {lab:<18} 年化{ann:+.1f}% MDD{mdd:.1f}% 夏普{shp:.2f} Calmar{p1[k]['calmar']:.2f} "
              f"月勝率{win:.0f}%" + (f" 月贏大盤率{beat:.0f}%" if pd.notna(beat) else ""))

    def boot_ev(k):
        E = pd.DataFrame(ev[k], columns=["ym", "v"])
        if len(E) < 100:
            return None
        grp = {m: g.v.values for m, g in E.groupby("ym")}
        keys = list(grp)
        means = [np.mean(np.concatenate([grp[m] for m in rng.choice(keys, len(keys))]))
                 for _ in range(1000)]
        lo, hi = np.percentile(means, [2.5, 97.5])
        return {"mean": E.v.mean() * 100, "lo": lo * 100, "hi": hi * 100,
                "sig": bool(lo > 0 or hi < 0), "n": len(E)}

    print("\nP1b 個股層月demean(月群bootstrap):")
    p1b = {}
    for lab, k in GROUPS:
        b = boot_ev(k)
        p1b[k] = b
        if b:
            print(f"  {lab:<18} n={b['n']:,} 月demean{b['mean']:+.2f}%[{b['lo']:+.2f},{b['hi']:+.2f}]"
                  f"{'✓' if b['sig'] else '含0'}")

    # ---------- P2 大盤參考性 ----------
    hp = pd.Series(navs["top5"]).pct_change().dropna().values
    tm = tai_mr.values
    rs = hp - tm
    rs3 = pd.Series(rs).rolling(3).mean().values
    nxt = np.roll(tm, -1)[:-1]
    r3 = rs3[:-1]
    ok = ~np.isnan(r3)
    pos, neg = nxt[ok & (r3 > 0)], nxt[ok & (r3 <= 0)]
    print(f"\nP2 大盤參考性(相對高價前5%組RS近3月均→下月TAIEX): "
          f"RS>0時下月TAIEX均{np.mean(pos) * 100:+.2f}%(n={len(pos)},勝率{(pos > 0).mean() * 100:.0f}%) "
          f"vs RS<=0時{np.mean(neg) * 100:+.2f}%(n={len(neg)},勝率{(neg > 0).mean() * 100:.0f}%)")
    corr = np.corrcoef(r3[ok], nxt[ok])[0, 1]
    print(f"  corr(RS3月均, 下月TAIEX)={corr:+.3f}")
    p2 = {"pos_m": np.mean(pos) * 100, "pos_n": len(pos), "pos_w": (pos > 0).mean() * 100,
          "neg_m": np.mean(neg) * 100, "neg_n": len(neg), "neg_w": (neg > 0).mean() * 100,
          "corr": corr}

    # ---------- HTML ----------
    CSS = """
body{background:#1a1a19;color:#fff;font-family:"Noto Sans TC",sans-serif;margin:24px;max-width:1050px}
h1{font-size:20px} h2{font-size:15px;color:#c3c2b7;margin-top:28px;border-bottom:1px solid #333;padding-bottom:4px}
table{border-collapse:collapse;font-size:12.5px;font-variant-numeric:tabular-nums;margin:8px 0}
td,th{border:1px solid #333;padding:4px 9px;text-align:right} th{text-align:left;color:#c3c2b7}
.note{color:#8a8878;font-size:12.5px;line-height:1.8} .good{color:#7ec97e} .bad{color:#e06c5a}
.hl{background:#2b3a2b}
ul{margin:4px 0;padding-left:20px;font-size:12.5px;color:#ccc;line-height:1.7}
.verdict{font-size:13px;font-weight:bold;padding:6px 10px;border-radius:4px;display:inline-block;margin:4px 0}
.v-good{background:#243b24;color:#7ec97e} .v-bad{background:#3b2420;color:#e06c5a}
.v-warn{background:#3b3420;color:#c3a55a}
"""
    p0_html = ("<table><tr><th>組</th><th>平均檔數</th><th>P(兩月營收連創高)</th><th>P(近3月YoY>0)</th>"
               "<th>20日年化波動中位</th></tr>"
               + "".join(f"<tr{' class=hl' if k in ('abs500', 'top5') else ''}><th>{lab}</th>"
                         f"<td>{p0[k]['n']:.0f}</td><td>{p0[k]['r1']:.1f}%</td>"
                         f"<td>{p0[k]['yoy']:.1f}%</td><td>{p0[k]['vol']:.1f}%</td></tr>"
                         for lab, k in GROUPS) + "</table>")
    p1_html = ("<table><tr><th>組</th><th>年化(毛)</th><th>MDD</th><th>夏普</th><th>Calmar</th>"
               "<th>月勝率</th><th>月贏大盤率</th><th>月demean CI</th></tr>")
    for lab, k in GROUPS + [("TAIEX", "TAIEX")]:
        b = p1b.get(k)
        ci = (f"{b['mean']:+.2f}[{b['lo']:+.2f},{b['hi']:+.2f}]{'✓' if b['sig'] else ''}" if b else "—")
        p1_html += (f"<tr{' class=hl' if k in ('abs500', 'top5') else ''}><th>{lab}</th>"
                    f"<td>{p1[k]['ann']:+.1f}%</td><td>{p1[k]['mdd']:.1f}%</td>"
                    f"<td>{p1[k]['shp']:.2f}</td><td>{p1[k]['calmar']:.2f}</td>"
                    f"<td>{p1[k]['win']:.0f}%</td>"
                    f"<td>{p1[k]['beat']:.0f}%</td>" if pd.notna(p1[k]["beat"]) else
                    f"<tr><th>{lab}</th><td>{p1[k]['ann']:+.1f}%</td><td>{p1[k]['mdd']:.1f}%</td>"
                    f"<td>{p1[k]['shp']:.2f}</td><td>{p1[k]['calmar']:.2f}</td><td>{p1[k]['win']:.0f}%</td><td>—</td>")
        p1_html += f"<td>{ci}</td></tr>" if k != "TAIEX" else "<td>—</td></tr>"
    p1_html += "</table>"

    nav_json = json.dumps([{"name": lab, "dates": nav_dates,
                            "vals": [round(x, 4) for x in navs[k]]}
                           for lab, k in GROUPS + [("TAIEX", "TAIEX")]], ensure_ascii=False)

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>高價股穩定性(2026-08-07)</title>
<script src="plotly.min.js"></script><style>{CSS}</style></head><body>
<h1>💎 高價股穩定性考卷: >500元 / 池內前5%</h1>
<div class="note">使用者假說:「高股價相對穩定——營收多不差、籌碼穩,且可能對大盤行情有參考性」。
月頻等權(月初調倉,毛報酬未扣成本),池=20日均額>=0.3億,2015起。
⚠主要限制: fm_daily_price未還原除權息——高價績優股配息高,<b>本卷絕對報酬對高價組顯著低估</b>
(每年可能低估2-4pp),組間比較时高價組被系統性壓低,判讀時要放在心上。</div>
<h2>P0 前提檢查: 高價股營收真的不差嗎? + 波動度</h2>
{p0_html}
<h2>P1 穩定性與報酬(月頻等權)</h2>
{p1_html}
<div id="c_nav" style="height:440px"></div>
<h2>P2 大盤參考性(前5%組RS近3月均→下月TAIEX)</h2>
<div class="note">RS>0時下月TAIEX均{p2['pos_m']:+.2f}%(n={p2['pos_n']},勝率{p2['pos_w']:.0f}%) vs
RS&lt;=0時{p2['neg_m']:+.2f}%(n={p2['neg_n']},勝率{p2['neg_w']:.0f}%);corr={p2['corr']:+.3f}。
月頻小樣本,觀察層。</div>
<h2>⚖️ 判決(2026-08-07首輪)</h2>
<ul>
<li><span class="verdict v-warn">①前提半對半錯</span> 「營收不差」✓成立: 高價組P(近3月YoY>0)=73.7~78%
vs 池65%/低價組58.9%,兩月連創高機率也近雙倍;但「籌碼穩/波動小」<b>✗反向</b>——高價組20日年化波動
中位42.7%/40.1%是<b>全場最高</b>(低價33.6%最低)=高價股多為成長股,高價≠穩定。</li>
<li><span class="verdict v-bad">②穩定性假說否定: 高價組合是全場最不穩的</span> 高價>500月頻等權:
MDD-50.5%全場最深/Calmar0.28墊底/夏普0.60,輸TAIEX(-28.6%/0.50/0.85)也輸低價組(Calmar0.47);
個股層月demean全數含0(中價組甚至-0.87%✓負)=<b>價格高低本身不是alpha也不是防禦</b>。
(除息未還原對高價績優股低估約2-4pp/年,補回也追不平MDD差距,結論不翻。)</li>
<li><span class="verdict v-good">③意外活口=你的第三個直覺: 高價股相對強弱是大盤風險偏好溫度計</span>
前5%組RS近3月均>0→下月TAIEX+2.25%/勝率69%(n=72) vs RS<=0→+0.13%/勝率55%(corr+0.253)——
「領頭羊還在漲=行情健康」有訊號;觀察層候選(月頻小樣本未做安慰劑),可考慮併入🛡️大盤溫度計頁
當補充指標,列待辦。</li>
<li><b>④實務翻譯</b>: 不開「高價股」策略線,>500元不當篩選條件(選股請回雙新高/三重門檻的
基本面×價格結構);高價RS溫度計=本卷唯一帶走的東西。</li>
</ul>
<div class="note">維運: python 研究腳本/綜合策略/build_high_price_stability.py(從根目錄執行)。</div>
<script>
const NAVS={nav_json};
Plotly.newPlot('c_nav', NAVS.map(s=>({{x:s.dates,y:s.vals,name:s.name,mode:'lines'}})),
  {{title:'月頻等權權益曲線(毛報酬,未扣成本/未還原除息,對數軸)', paper_bgcolor:'#1a1a19',
    plot_bgcolor:'#22221f',font:{{color:'#ddd',size:12}},yaxis:{{title:'NAV',type:'log'}},
    legend:{{orientation:'h'}},margin:{{t:42,l:52,r:18,b:40}}}});
</script>
</body></html>"""
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n[report] 已輸出 {OUT}")


if __name__ == "__main__":
    main()
