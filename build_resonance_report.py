# -*- coding: utf-8 -*-
"""共振研究權益曲線報告 -> 研究報告/research_resonance.html
沿用tmp_portfolio_report.py的策略棧模板慣例:episode進場後持HOLD週,同週多筆episode等權疊加成單一週報酬序列,
COST=0.5%比照同模板。S1=全部共振事件(>=2檔同振);S2=breadth>=3檔同振(既有分層顯示較強)。
用法: python build_resonance_report.py
"""
import sqlite3

import pandas as pd

from research_report_tmpl import build_report

COST = 0.5
HOLD = 8

ep = pd.read_pickle("tmp_resonance_theme_episodes.pkl")
wk_panel = pd.read_pickle("tmp_resonance_weekly_panel.pkl")
wret = wk_panel.pct_change(fill_method=None) * 100
idx = wk_panel.index

conn = sqlite3.connect("capital_flow.db")
twii = pd.read_sql("SELECT date, close FROM index_daily WHERE market='TAIEX' ORDER BY date", conn,
                    parse_dates=["date"]).set_index("date").close
otc = pd.read_sql("SELECT date, close FROM index_daily WHERE market='TPEx' ORDER BY date", conn,
                   parse_dates=["date"]).set_index("date").close
conn.close()
tw_wk = twii.resample("W-FRI").last().dropna()
otc_wk = otc.resample("W-FRI").last().dropna()


def make_tier(wk_series):
    """水位階梯產生器(比照tmp_portfolio_report.py::tier_at,週線4週/13週均線):
    季線下0.3、月線下0.6、月線上1.0——用指數趨勢(非恐慌溫度計)當水位,
    因為共振是動能突破策略,跟恐慌溫度計(危機後反轉訊號)機制家族不同、regime常相反,
    直接套恐慌溫度計曝險分數邏輯上不match;指數趨勢ladder才是同一個「順勢」機制家族。"""
    m4, m13 = wk_series.rolling(4).mean(), wk_series.rolling(13).mean()

    def tier_at(dt):
        pos = wk_series.index.searchsorted(dt)
        if pos >= len(wk_series) or wk_series.index[pos] != dt or pos < 13:
            return 1.0
        px, a, b = wk_series.iloc[pos], m4.iloc[pos], m13.iloc[pos]
        if pd.notna(b) and px < b:
            return 0.3
        if pd.notna(a) and px < a:
            return 0.6
        return 1.0
    return tier_at


tier_twii = make_tier(tw_wk)
tier_otc = make_tier(otc_wk)


def simulate(trades, tier_fn=None):
    entries = []
    for t in trades.itertuples():
        ei = idx.searchsorted(pd.Timestamp(t.week))
        if ei >= len(idx) or idx[ei] != pd.Timestamp(t.week):
            continue
        mems = [c for c in t.members if c in wret.columns]
        if mems and ei < len(idx) - 1:
            entries.append((ei, mems))
    weekly = []
    for i in range(1, len(idx)):
        rets = []
        for ei, mems in entries:
            if ei < i <= ei + HOLD:
                rs = [wret.iloc[i].get(m) for m in mems]
                rs = [x for x in rs if pd.notna(x)]
                if rs:
                    rets.append(sum(rs) / len(rs) - (COST if i == ei + 1 else 0))
        r = sum(rets) / len(rets) if rets else 0.0
        if tier_fn is not None:
            r *= tier_fn(idx[i])
        weekly.append((str(idx[i].date()), r, len(rets)))
    return pd.DataFrame(weekly, columns=["date", "ret", "n"])


def trade_rets(trades):
    """單筆episode層級的fwd8週淨報酬(扣成本),供勝率/賺賠比/交易明細用"""
    out = []
    for t in trades.itertuples():
        ei = idx.searchsorted(pd.Timestamp(t.week))
        if ei >= len(idx) or idx[ei] != pd.Timestamp(t.week) or ei + HOLD >= len(idx):
            continue
        mems = [c for c in t.members if c in wret.columns]
        rs = []
        for m in mems:
            p0, p1 = wk_panel[m].iloc[ei], wk_panel[m].iloc[ei + HOLD]
            if pd.notna(p0) and pd.notna(p1) and p0 > 0:
                rs.append((p1 / p0 - 1) * 100)
        if rs:
            out.append({"date": str(t.week.date()), "theme": t.theme, "members": "、".join(mems),
                        "n_members": t.n_members, "ret": sum(rs) / len(rs) - COST})
    return pd.DataFrame(out)


def pack(w, tdf):
    eq = (1 + w.ret / 100).cumprod()
    dd = (eq / eq.cummax() - 1) * 100
    mu, sd = w.ret.mean(), w.ret.std()
    n = len(w)
    mult = eq.iloc[-1]
    ann = (mult ** (52 / n) - 1) * 100 if n else 0
    aw = tdf.ret[tdf.ret > 0].mean() if len(tdf) else None
    al = tdf.ret[tdf.ret <= 0].mean() if len(tdf) else None
    st = dict(trades=len(tdf), win=(tdf.ret > 0).mean() * 100 if len(tdf) else None,
              avg=tdf.ret.mean() if len(tdf) else None, med=tdf.ret.median() if len(tdf) else None,
              wl=abs(aw / al) if aw and al else None,
              pf=-tdf.ret[tdf.ret > 0].sum() / tdf.ret[tdf.ret <= 0].sum() if len(tdf) and (tdf.ret <= 0).any() else None,
              mult=mult, ann=ann, sharpe=mu / sd * 52 ** 0.5 if sd else 0, mdd=dd.min(),
              calmar=ann / abs(dd.min()) if dd.min() else None, expo=(w.n > 0).mean() * 100)
    w2 = w.copy()
    w2["y"] = w2.date.str[:4]
    yearly = {y: ((1 + g.ret / 100).prod() - 1) * 100 for y, g in w2.groupby("y")}
    return eq, st, yearly


configs = [("S1 全部共振(>=2檔同振)", ep, None), ("S2 強共振(>=3檔同振)", ep[ep.n_members >= 3], None),
           ("S3 S1+TWII水位階梯", ep, tier_twii), ("S4 S1+OTC水位階梯", ep, tier_otc)]
strategies, linear_curves = [], []
for name, tdf_ep, tier_fn in configs:
    w = simulate(tdf_ep, tier_fn=tier_fn)
    tdf = trade_rets(tdf_ep).sort_values("date")
    eq, st, yr = pack(w, tdf)
    # n_open=當週同時開倉題材數(僅S1/S2附上,S3/S4沿用S1同一批進場只是縮放部位,曲線會重複不重畫)
    strat = dict(name=name, dates=list(w.date), equity=[round(x, 4) for x in eq], yearly=yr, stats=st)
    if tier_fn is None:
        strat["n_open"] = [int(x) for x in w.n]
    strategies.append(strat)
    print(name, f"{st['mult']:.2f}x 夏普{st['sharpe']:.2f} MDD{st['mdd']:.1f}% 交易{st['trades']}筆 "
                f"最大同時開倉{w.n.max()}題材")
    # 單利累積: 每筆固定1單位,不复利,不受同時併發訊號分攤資金影響(比照使用者常用的單利對照慣例)
    # 注意: 水位階梯只影響「部位大小」不影響「單筆是否成立」,S3/S4單利累積跟S1完全一樣,不重複畫
    if tier_fn is None:
        cum = tdf.ret.cumsum()
        linear_curves.append(dict(name=name, dates=list(tdf.date), cum=[round(x, 2) for x in cum]))
        print(f"  單利累積: 均值{tdf.ret.mean():+.2f}% 中位{tdf.ret.median():+.2f}% Σ={cum.iloc[-1]:+.0f}%")

# S5: 8週出場+拉回(跌破自身4週均線)加碼再抱8週(2026-07-22驗證通過:LOTO 22年100%為正/
# 剔2009年後仍+2.77%;bootstrap絕對值CI95=[+0.21,+9.01] P(<=0)=0.0192,差值(vs單腿)CI95=[+0.78,+5.57] P(<=0)=0.0025)
ma4_stock = wk_panel.rolling(4).mean()
_s5_pairs = sorted(set(
    (idx.searchsorted(pd.Timestamp(r.week)), c)
    for _, r in ep.iterrows() for c in r.members
    if c in wk_panel.columns and idx.searchsorted(pd.Timestamp(r.week)) < len(idx)
    and idx[idx.searchsorted(pd.Timestamp(r.week))] == pd.Timestamp(r.week)
))
s5_entries = []  # (start_week_idx, code) 每筆固定持有HOLD週,含leg1+視情況的leg2
for ei, c in _s5_pairs:
    j8 = ei + HOLD
    if j8 >= len(idx):
        continue
    s5_entries.append((ei, c))
    for j in range(j8, min(ei + 16, len(idx))):
        cl, m = wk_panel[c].iloc[j], ma4_stock[c].iloc[j]
        if pd.notna(cl) and pd.notna(m) and cl < m:
            if j + HOLD < len(idx):
                s5_entries.append((j, c))
            break
print(f"S5訊號(leg1+拉回leg2)個股-進場配對數: {len(s5_entries)}")


def simulate_s5(entries):
    weekly = []
    for i in range(1, len(idx)):
        rets = []
        for ei, c in entries:
            if ei < i <= ei + HOLD:
                v = wret.iloc[i].get(c)
                if pd.notna(v):
                    rets.append(v - (COST if i == ei + 1 else 0))
        r = sum(rets) / len(rets) if rets else 0.0
        weekly.append((str(idx[i].date()), r, len(rets)))
    return pd.DataFrame(weekly, columns=["date", "ret", "n"])


def trade_rets_s5(entries):
    out = []
    for ei, c in entries:
        if ei + HOLD >= len(idx):
            continue
        p0, p1 = wk_panel[c].iloc[ei], wk_panel[c].iloc[ei + HOLD]
        if pd.notna(p0) and pd.notna(p1) and p0 > 0:
            out.append({"date": str(idx[ei].date()), "theme": "(S5)", "members": c,
                        "n_members": None, "ret": (p1 / p0 - 1) * 100 - COST})
    return pd.DataFrame(out)


w5 = simulate_s5(s5_entries)
t5 = trade_rets_s5(s5_entries).sort_values("date")
eq5, st5, yr5 = pack(w5, t5)
strategies.append(dict(name="S5 8週出場+拉回加碼", dates=list(w5.date),
                       equity=[round(x, 4) for x in eq5], yearly=yr5, stats=st5, n_open=[int(x) for x in w5.n]))
print("S5 8週出場+拉回加碼", f"{st5['mult']:.2f}x 夏普{st5['sharpe']:.2f} MDD{st5['mdd']:.1f}% 交易{st5['trades']}筆")
cum5 = t5.ret.cumsum()
linear_curves.append(dict(name="S5 8週出場+拉回加碼", dates=list(t5.date), cum=[round(x, 2) for x in cum5]))
print(f"  單利累積: 均值{t5.ret.mean():+.2f}% 中位{t5.ret.median():+.2f}% Σ={cum5.iloc[-1]:+.0f}%")

twr = tw_wk.pct_change().fillna(0)
twr = twr[twr.index >= pd.Timestamp(strategies[0]["dates"][0])]
tw_eq = (1 + twr).cumprod()
tw_y = {str(y): ((1 + g).prod() - 1) * 100 for y, g in twr.groupby(twr.index.year)}
benchmarks = [dict(name="加權指數TAIEX", dates=[str(d.date()) for d in tw_eq.index],
                   equity=[round(float(x), 4) for x in tw_eq], yearly=tw_y)]

s2t = trade_rets(ep[ep.n_members >= 3]).sort_values("date")
rows = "".join(f"<tr><th>{t.date}</th><td>{t.theme}</td><td>{t.n_members}檔</td><td>{t.members}</td>"
               f"<td class='{'good' if t.ret > 0 else 'bad'}'>{t.ret:+.1f}%</td></tr>" for t in s2t.itertuples())
trades_html = ("<div class=\"note\">下表為S2「強共振(>=3檔)」逐筆明細(n=358)；"
               "S1母體事件較多(1,117筆)不逐筆列出,統計已在上方總表。S3/S4與S1單筆完全相同,差異只在部位大小(水位階梯),不重複列。</div>"
               "<table><tr><th>觸發週</th><th>題材</th><th>同振數</th><th>成員</th><th>+8週(net)</th></tr>" + rows + "</table>")

sS = {s["name"]: s["stats"] for s in strategies}
verdicts = [
    ("雙關卡驗證(S1)", "LOTO逐年剔除21種情境100%為正(最差剔2009年後中位+3.18%);cluster bootstrap(年群,B=10000)"
                 "CI95=[+1.85,+5.96]/P(≤0)=0.0005——雙過"),
    ("breadth梯度(S1 vs S2)", f"S1={sS['S1 全部共振(>=2檔同振)']['mult']:.2f}x/夏普{sS['S1 全部共振(>=2檔同振)']['sharpe']:.2f} "
                  f"vs S2(>=3檔強共振)={sS['S2 強共振(>=3檔同振)']['mult']:.2f}x/夏普{sS['S2 強共振(>=3檔同振)']['sharpe']:.2f}"
                  "——同振檔數越多後續越強,梯度乾淨"),
    ("水位階梯(S3 TWII vs S4 OTC)", f"S1原始MDD{sS['S1 全部共振(>=2檔同振)']['mdd']:.1f}% -> "
                  f"S3(TWII階梯)MDD{sS['S3 S1+TWII水位階梯']['mdd']:.1f}%/夏普{sS['S3 S1+TWII水位階梯']['sharpe']:.2f} "
                  f"vs S4(OTC階梯)MDD{sS['S4 S1+OTC水位階梯']['mdd']:.1f}%/夏普{sS['S4 S1+OTC水位階梯']['sharpe']:.2f}"
                  "——兩種指數水位對同一批訊號的風控效果對照,兩者皆非恐慌溫度計(機制家族不同,見下)"),
    ("為何不用恐慌溫度計當水位", "共振是順勢突破策略(盤面要熱才會有訊號),恐慌溫度計是危機後反轉訊號"
                  "(盤面剛崩過才會亮)——兩者常是相反的regime,直接套溫度計曝險分數邏輯上不match,"
                  "改用TWII/OTC週線4週/13週均線的順勢水位階梯(比照tmp_portfolio_report.py慣例)"),
    ("去重疊測試(已解決)", "個股同時掛多題材/重複觸發的重疊比例本來就小(同週跨題材2.5%、時間重疊11%),"
                  "實測去重疊前後績效幾乎無差(複利218.8x vs 204.9x,勝率同為53%)——不是拖累績效的因素,不必處理"),
    ("S5出場研究(2026-07-22新驗證)", f"固定8週持有 vs 延長到20週:報酬持續上升無衰竭(fwd8中位+3.51%->fwd20中位+8.41%,"
                  "勝率59%->64%);但破均線/長黑群集等動態早出場規則全部測試失敗(比固定持有更差,會洗掉還在噴的部位)。"
                  "折衷方案=固定8週出場(顧資金週轉)+8-16週內若出現拉回(跌破自身4週均線)加碼再抱8週"
                  f"：單腿中位+1.25%/勝率53% -> 合計中位+3.98%/勝率57%(91.6%的部位都有拉回機會);"
                  "LOTO 22年100%為正(最差剔2009年後+2.77%)、bootstrap絕對值CI95=[+0.21,+9.01]/P(≤0)=0.0192、"
                  f"差值CI95=[+0.78,+5.57]/P(≤0)=0.0025——雙過,晉級候選S5:{sS['S5 8週出場+拉回加碼']['mult']:.2f}x/"
                  f"夏普{sS['S5 8週出場+拉回加碼']['sharpe']:.2f}/MDD{sS['S5 8週出場+拉回加碼']['mdd']:.1f}%"),
    ("面子檢查", "訊號定義未用記憶體2025案例校準(借pattern_mining_2022.py既有4%+2倍量/60日新高慣例),"
               "但獨立抓到2025-09-19記憶體題材8/11檔同振=21年史上第二高breadth,吻合使用者回憶的那波行情"),
    ("集中度", "前3大題材(PCB/CCL、半導體設備、封測)僅佔全部事件30.6%,非單一題材灌水"),
]
limits = ("週線close-to-close近似,未用開盤價進場(比照tmp_portfolio_report模板);成本0.5%/筆未含滑價;"
          "水位階梯(S3/S4)只調整部位大小,單筆勝率/中位跟S1完全相同,階梯效果只看得到MDD/夏普/複利倍數的差異;"
          "尚未檢查與既有scan_signals.py點火規則/score=4題材動能的重疊率,不確定是否為獨立增量訊號;"
          "出場規則(固定持有8週)未優化,使用者已提出要再深入研究分段/動態出場;"
          "跨題材同週確認(曾測得中位+5.11%/勝率69%,n=70)已測試過但實際不適合當獨立策略"
          "(持倉週占比僅24%,權益曲線夏普反而較低),使用者裁示移除,先不放進本報告的策略棧;"
          "宇宙=classification表country='台'成員數>=5的22個題材,2005起(早期資料量薄)。")
prereg = ("訊號=同main_group(>=5檔成員)同週>=2檔個股「日線爆量創高(單日+4%且量>=2倍20日均量)+週線同步創12週高」共振,"
          "4週內去重(episode化);持有HOLD=8週,成本0.5%/筆,次週收盤進(近似)。"
          "S3/S4=S1疊加TWII/OTC週線4週、13週均線水位階梯(季線下0.3/月線下0.6/月線上1.0)。")
build_report("研究報告/research_resonance.html", "多週期題材共振研究(2005-2026)",
             prereg, strategies, benchmarks, trades_html, verdicts, limits, linear_curves=linear_curves)
print("-> 研究報告/research_resonance.html")
