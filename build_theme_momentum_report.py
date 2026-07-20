# -*- coding: utf-8 -*-
"""正式報告:「題材月營收動能」判決版(2026-07-14,取代凌晨的待驗證版)。
資料=修復後全宇宙panel(tmp_theme_momentum_v2_panel.pkl,由build_theme_momentum_v2.py產生,
無新聞look-ahead條件);訊號=score(0-4)分層,主推score=4。

score定義(題材-月層級,tmp_theme_score.pkl,shift(1)口徑=進場日只用已公布月份;
2026-07-14逆向工程驗證100%,正式builder=build_theme_score_topn.py):
  mom_score  = 從最近已公布月往回數「連續加總MoM>0」的月數(巢狀streak,0~3)
  trend_yoy3 = 最近3個已公布月加總YoY的平均
  score      = mom_score + (trend_yoy3>0 ? 1 : 0)  → 0~4
  score=4 ⟺ 連續3個月MoM為正 且 近3月YoY均值為正(=mom_streak3加YoY趨勢確認,重疊92%)

規格教訓(全程使用者校正,詳研究紀錄20260714):細分題材分組/加總後算比率/15號進場/
60交易日持有(事件研究法)/權益曲線逐日展開等權平均(避免82x虛假複利)。
驗證狀態:LOTO+題材-月cluster bootstrap雙通過(build_theme_momentum_validate.py);
季節性=觸發率成立報酬否定;trailing新聞熱度=否定(build_news_heat_test.py)。
用法: python build_theme_momentum_report.py
"""
import pickle
import sqlite3

import pandas as pd

from research_report_tmpl import build_report

HOLD_DAYS = 60

with open("tmp_revenue_price_cache.pkl", "rb") as f:
    cache = pickle.load(f)

panel = pd.read_pickle("tmp_theme_momentum_v2_panel.pkl").copy()
panel["y"] = panel.year_month.str[:4]
print(f"判決版panel: {len(panel)}筆, score分布:\n{panel.score.value_counts().sort_index().to_string()}")

twii = pd.read_pickle("tmp_twii_daily.pkl")
twii.columns = twii.columns.get_level_values(0)
twii = twii.sort_index()
c_twii = twii.Close
all_days_idx = [d for d in twii.index if str(d.date()) >= "2022-01-01"]
all_days = [str(d.date()) for d in all_days_idx]


def daily_returns_for_trade(row):
    """展開單筆交易成『持有期每日報酬』Series(index=日期字串)。entry_day=panel已算好的實際進場日"""
    df = cache.get(row.code)
    if df is None:
        return None
    c = df["Close"]
    if hasattr(c, "columns"):
        c = c.iloc[:, 0]
    entry = pd.Timestamp(row.entry_day)
    if entry not in c.index:
        return None
    start_i = c.index.get_loc(entry)
    end_i = start_i + HOLD_DAYS
    if end_i >= len(c):
        return None
    window = c.iloc[start_i:end_i + 1]
    daily_ret = window.pct_change().dropna() * 100
    daily_ret.index = daily_ret.index.map(lambda d: str(d.date()))
    return daily_ret


def build_equity(tdf):
    """逐日對齊:同日多部位等權平均,無部位日=0(現金)"""
    daily_frames = [dr for row in tdf.itertuples() if (dr := daily_returns_for_trade(row)) is not None]
    if not daily_frames:
        return None
    all_ret = pd.concat(daily_frames, axis=1)
    port_ret = all_ret.mean(axis=1)
    port = pd.Series(0.0, index=all_days)
    idx = port_ret.index.intersection(port.index)
    port.loc[idx] = port_ret.loc[idx]
    eq = (1 + port / 100).cumprod()
    ddv = (eq / eq.cummax() - 1) * 100
    mu, sdv = port.mean(), port.std()
    n = len(port)
    mult = eq.iloc[-1]
    ann = (mult ** (252 / n) - 1) * 100
    n_open = all_ret.notna().sum(axis=1).reindex(port.index).fillna(0)
    tmp = pd.DataFrame({"date": all_days, "ret": port.values, "n": n_open.values})
    tmp["y"] = tmp.date.str[:4]
    yearly = {y: ((1 + g.ret / 100).prod() - 1) * 100 for y, g in tmp.groupby("y")}
    st = dict(trades=len(tdf), win=(tdf.ret60 > 0).mean() * 100, avg=tdf.ret60.mean(), med=tdf.ret60.median(),
              wl=None, pf=None, mult=mult, ann=ann, sharpe=mu / sdv * 252 ** 0.5 if sdv else 0,
              mdd=ddv.min(), calmar=ann / abs(ddv.min()) if ddv.min() else None,
              expo=(tmp.n > 0).mean() * 100)
    aw = tdf.ret60[tdf.ret60 > 0].mean()
    al = tdf.ret60[tdf.ret60 <= 0].mean()
    st["wl"] = abs(aw / al) if al else None
    st["pf"] = -tdf.ret60[tdf.ret60 > 0].sum() / tdf.ret60[tdf.ret60 <= 0].sum() if (tdf.ret60 <= 0).any() else None
    return all_days, [round(x, 4) for x in eq], yearly, st


strategies = []
for sel, name in [(panel.score == 4, "score=4(主推:連3月MoM正+近3月YoY均值正)"),
                  (panel.score == 3, "score=3(差一分,對照)"),
                  (panel.score <= 2, "score≤2(其餘,對照)")]:
    d, e, yr, st = build_equity(panel[sel])
    strategies.append(dict(name=name, dates=d, equity=e, yearly=yr, stats=st))

txr = c_twii.pct_change().fillna(0)
txe = (1 + txr).cumprod()
txe = txe[txe.index.map(lambda d: str(d.date())) >= "2022-01-01"]
txy = {}
for y, g in txr.groupby(txr.index.year):
    g2 = g[g.index.map(lambda d: str(d.date())) >= "2022-01-01"]
    if len(g2):
        txy[str(y)] = ((1 + g2).prod() - 1) * 100
benchmarks = [dict(name="加權指數^TWII買進持有", dates=[str(d.date()) for d in txe.index],
                   equity=[round(float(x), 4) for x in txe / txe.iloc[0]], yearly=txy)]

# ---------- 附表:score分層統計/逐年/季節性/新聞熱度 ----------
def stat_row(g, col):
    return (f"<td>{len(g)}</td><td>{g[col].median():+.2f}%</td>"
            f"<td>{g[col].mean():+.2f}%</td><td>{(g[col] > 0).mean() * 100:.0f}%</td>")

score_tbl = ("<p><b>score分層統計(單筆60日,左=原始/右=TWII超額)</b></p>"
             "<table><tr><th>score</th><th>n</th><th>中位</th><th>均值</th><th>勝率</th>"
             "<th>n</th><th>超額中位</th><th>超額均值</th><th>超額勝率</th></tr>")
for sc in range(5):
    g = panel[panel.score == sc]
    score_tbl += f"<tr><th>{sc}</th>{stat_row(g, 'ret60')}{stat_row(g, 'excess60')}</tr>"
score_tbl += "</table>"

yr_tbl = ("<p><b>score=4逐年(TWII超額)</b></p><table><tr><th>年</th><th>n</th><th>群數</th>"
          "<th>超額中位</th><th>勝率</th><th>其他score中位</th></tr>")
s4 = panel[panel.score == 4]
for y in sorted(panel.y.unique()):
    a = s4[s4.y == y]
    b = panel[(panel.y == y) & (panel.score < 4)]
    yr_tbl += (f"<tr><th>{y}</th><td>{len(a)}</td>"
               f"<td>{a.groupby(['industry', 'year_month']).ngroups}</td>"
               f"<td>{a.excess60.median():+.2f}%</td><td>{(a.excess60 > 0).mean() * 100:.0f}%</td>"
               f"<td>{b.excess60.median():+.2f}%</td></tr>")
yr_tbl += "</table>"

nh = pd.read_pickle("tmp_news_heat_panel.pkl")
nh_tbl = ("<p><b>⑫b新聞熱度判決表(TWII超額中位/勝率)——否定</b></p>"
          "<table><tr><th>組別</th><th>1M窗口</th><th>3M窗口</th></tr>")
for label, sel in [("①score4×有新聞", lambda c: (nh.score == 4) & nh[c]),
                   ("②score4×無新聞", lambda c: (nh.score == 4) & ~nh[c]),
                   ("③有新聞單獨(全score)", lambda c: nh[c]),
                   ("　無新聞(全score)", lambda c: ~nh[c])]:
    cells = ""
    for c in ["news_1M(35d)", "news_3M(95d)"]:
        g = nh[sel(c)]
        cells += f"<td>n={len(g)} 中位{g.excess60.median():+.2f}% 勝{(g.excess60 > 0).mean() * 100:.0f}%</td>"
    nh_tbl += f"<tr><th>{label}</th>{cells}</tr>"
nh_tbl += "</table>"

rdb = sqlite3.connect("研究報告/research_2022.db")
names = dict(rdb.execute("SELECT code, name FROM (SELECT code, name, snapshot_date FROM rankings "
                          "WHERE country='台' ORDER BY snapshot_date) GROUP BY code"))
trades_show = s4.sort_values("entry_day").tail(150)
rows = "".join(
    f"<tr><th>{t.entry_day}</th><td>{t.industry}</td><td>{t.code} {names.get(t.code, '')}</td>"
    f"<td class='{'good' if t.ret60 > 0 else 'bad'}'>{t.ret60:+.1f}%</td>"
    f"<td class='{'good' if t.excess60 > 0 else 'bad'}'>{t.excess60:+.1f}%</td></tr>"
    for t in trades_show.itertuples())
trades_html = (score_tbl + yr_tbl + nh_tbl +
               "<p><b>score=4逐筆明細(近150筆)</b></p>"
               "<table><tr><th>進場日</th><th>題材</th><th>個股</th><th>60日報酬</th><th>TWII超額</th></tr>"
               + rows + "</table>")

s1 = strategies[0]["stats"]
verdicts = [
    ("主推:score=4", f"複利{s1['mult']:.2f}x/年化{s1['ann']:+.1f}%/夏普{s1['sharpe']:.2f}/MDD{s1['mdd']:.0f}%/"
                    f"{s1['trades']}筆/勝率{s1['win']:.0f}%/單筆中位{s1['med']:+.1f}%；TWII超額中位+2.55%(唯一超額為正的分層)"),
    ("為何只推score=4", "劑量反應不是線性而是斷崖:score 0-3超額全歸零或轉負,只有4分(連3月MoM正+近3月YoY均值正)突出。"
                     "score=4與mom_streak3重疊92%=同一資訊加YoY確認,不是獨立新因子——訊號本質是二元(全有或全無)"),
    ("LOTO集中度檢查=通過", "無單一題材撐盤:最壞剔除(散熱/結構件101筆)後剩餘中位仍+1.69%/勝率54%;"
                        "剔除最大題材PCB/CCL(151筆,18%)中位反升至+3.12%=它在拖後腿(build_theme_momentum_validate.py)"),
    ("cluster bootstrap=通過", "題材-月群層級(115群,B=10000):score=4超額中位+2.55% CI[+0.28,+4.78];"
                            "vs score<4中位差+3.82pp CI[+1.39,+6.09] 單尾p=0.0004"),
    ("逐年=regime依賴", "超額逐年CI:2025[+2.49,+15.06]獨立顯著/2024[-5.32,+0.43]偏負/其餘跨0——"
                     "題材行情年放大器非全天候,與台積電法說環境版/H-融資同構"),
    ("態勢階梯疊加=縮放可用/門檻否定(2026-07-14補測)",
     "進場門檻版(tier=1.0才進)=否定:被擋的288筆中位+12.17%/勝率77%全是大魚(訊號在大盤破線時觸發"
     "=最強反彈批),複利9.42x→3.40x且MDD反惡化到-39%——「位階不擋大魚」再度應驗;"
     "組合縮放版(日報酬×當日tier,訊號照進)=採用:夏普1.90→2.07/MDD-29.8%→-21.6%/Calmar 2.27→2.31,"
     "代價複利9.42→5.79x——凸性哲學標準用法,與S3⑤+階梯同構(build_theme_momentum_tier.py,"
     "tier=週線vs4週/13週均凍結口徑,上一完成週生效無look-ahead)"),
    ("季節性=報酬面否定", "10-11月觸發率11.1%vs其他月6.7%(Q4庫存回補確認),但報酬10-11月中位+1.01%/勝51%"
                      "反而低於其他月+2.84%/58%——訊號變多≠變好,不上儀表板(build_theme_momentum_seasonal.py)"),
    ("⑫b新聞熱度=否定", "trailing新聞覆蓋(進場前1/3個月被MoneyDJ報導)無溢價且略偏負(見附表)——"
                     "舊版panel高報酬=look-ahead選樣artifact,勿再引用(build_news_heat_test.py)"),
]
limits = ("樣本2022-2026;進場=每月15號後首個交易日(訊號只用已公布月份,shift(1)口徑),出場=固定60交易日;"
          "權益曲線逐日展開等權平均,未設曝險上限(理論可無限部位,實務受本金限制);"
          "同一股票可屬多題材=同筆營收可能重複入場;宇宙=FinMind覆蓋∩題材分類表僅283檔,"
          "分類表為現狀快照套用到歷史有存活者/分類漂移偏差(本系統既有簡化);"
          "score=4樣本828筆但獨立單位僅115個題材-月群/27題材;全樣本回測無訓練/測試切分"
          "(2022-24 vs 2025-26逐年表可當粗略代理);未建停損。")
prereg = ("2026-07-14判決版(取代凌晨待驗證版):panel修復兩個致命問題(移除新聞覆蓋look-ahead條件/"
          "改用FinMind全覆蓋宇宙283檔)後重測,加TWII超額報酬判準+LOTO+cluster bootstrap+季節性複驗+"
          "新聞熱度假說判決。產生器=build_theme_momentum_report.py,panel=build_theme_momentum_v2.py,"
          "驗證=build_theme_momentum_validate.py,詳細=封存/研究_20260714/研究紀錄。")
build_report("研究報告/research_theme_momentum.html", "題材月營收動能策略（score=4,60日持有）判決版",
             prereg, strategies, benchmarks, trades_html, verdicts, limits)
print("done -> research_theme_momentum.html")
for s in strategies:
    print(s["name"], {k: (round(v, 2) if isinstance(v, float) else v) for k, v in s["stats"].items()})
