# -*- coding: utf-8 -*-
"""正式報告:「題材月營收動能」(2026-07-14凌晨研究線最終版本)
規格(吸取一整晚的教訓,逐條寫明)：
1. 產業/題材分組=project自己的細分題材分類(classification.main_group,如PCB/CCL/記憶體/CPO光通訊)，
   不是TWSE官方34類粗分類——官方分類太粗會把訊號稀釋掉(使用者發現)。
2. 趨勢訊號=題材月加總營收(FinMind fm_month_rev,911檔全市場成交值>=5000萬公司)的MoM/YoY，
   加總後才算比率(不是先算個股比率再平均)——避免小公司YoY%波動大帶偏中位數(使用者發現)。
3. 進場點=每月15號(不是1號)。原因：訊號用的是「上個月」的營收數字，但上個月營收要到這個月10-15號
   才公告，1號進場等於假裝已經知道還沒公布的數字，是look-ahead bug(使用者發現)。
4. 出場=固定60個交易日(不是月底)。原因：事件研究法(看不同天數offset的報酬路徑)發現這批訊號的優勢
   會隨時間持續擴大而非提前打完收工，抱到月底反而抓不到大部分報酬(使用者建議做事件研究法查證)。
5. 訊號種類：mom_streak3(連續3個月MoM為正)、mom_streak2(連續2個月)。

權益曲線建構教訓(2026-07-14修正)：60天持有期遠長於進場間隔(124筆分散在33個不同月份，意味著同時間
常有多筆持有中的部位重疊)，若把每筆交易的60天報酬整包記在「進場當天」再逐日鏈接，會產生不可能達成的
虛假複利(第一版algo算出82倍/年化176%，明顯不合理)。正確做法：把每筆交易展開成「持有期間內每一天的
真實日報酬」，逐日對齊，同一天有多個部位同時持有就等權平均——這樣才反映「同時間資金會被多筆部位分食」
的真實限制，跟本系列研究一貫做法(gap-dip/revenue-diffusion等)的每日組合構建邏輯一致，只是把窗口從
1天/月底延伸到完整60天。
"""
import pickle
import sqlite3

import pandas as pd

from research_report_tmpl import build_report

MAX_GAP_DAYS = 5
HOLD_DAYS = 60


def get_close(cache, code, date, mode="onOrAfter"):
    df = cache.get(code)
    if df is None:
        return None
    c = df["Close"]
    if hasattr(c, "columns"):
        c = c.iloc[:, 0]
    target = pd.Timestamp(date)
    idx = c.index[c.index <= target] if mode == "onOrBefore" else c.index[c.index >= target]
    if len(idx) == 0:
        return None
    found = idx[0] if mode == "onOrAfter" else idx[-1]
    if abs((target - found).days) > MAX_GAP_DAYS:
        return None
    return found


with open("tmp_revenue_price_cache.pkl", "rb") as f:
    cache = pickle.load(f)

panel = pd.read_pickle("tmp_theme_trend_streak_panel.pkl")
panel["entry_date_fixed"] = panel.month_start + pd.Timedelta(days=14)

twii = pd.read_pickle("tmp_twii_daily.pkl")
twii.columns = twii.columns.get_level_values(0)
twii = twii.sort_index()
c_twii = twii.Close
all_days_idx = [d for d in twii.index if str(d.date()) >= "2022-01-01"]
all_days = [str(d.date()) for d in all_days_idx]


def daily_returns_for_trade(row):
    """展開單筆交易成『持有期每日報酬』的Series(index=日期字串),而不是單一總報酬數字"""
    entry_pos = get_close(cache, row.code, row.entry_date_fixed, "onOrAfter")
    if entry_pos is None:
        return None
    df = cache.get(row.code)
    c = df["Close"]
    if hasattr(c, "columns"):
        c = c.iloc[:, 0]
    start_i = c.index.get_loc(entry_pos)
    end_i = start_i + HOLD_DAYS
    if end_i >= len(c):
        return None
    window = c.iloc[start_i:end_i + 1]
    daily_ret = window.pct_change().dropna() * 100
    daily_ret.index = daily_ret.index.map(lambda d: str(d.date()))
    return daily_ret


def build_equity(tdf):
    """逐日對齊:同一天多個部位同時持有就等權平均當天報酬,無部位的日子=0(現金)"""
    daily_frames = []
    for row in tdf.itertuples():
        dr = daily_returns_for_trade(row)
        if dr is not None:
            daily_frames.append(dr)
    if not daily_frames:
        return None
    all_ret = pd.concat(daily_frames, axis=1)
    port_ret = all_ret.mean(axis=1)  # 同一天多部位=等權平均;NaN(當天沒部位)視為0
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
              wl=None, pf=None,
              mult=mult, ann=ann, sharpe=mu / sdv * 252 ** 0.5 if sdv else 0,
              mdd=ddv.min(), calmar=ann / abs(ddv.min()) if ddv.min() else None,
              expo=(tmp.n > 0).mean() * 100)
    aw = tdf.ret60[tdf.ret60 > 0].mean()
    al = tdf.ret60[tdf.ret60 <= 0].mean()
    st["wl"] = abs(aw / al) if al else None
    st["pf"] = -tdf.ret60[tdf.ret60 > 0].sum() / tdf.ret60[tdf.ret60 <= 0].sum() if (tdf.ret60 <= 0).any() else None
    return all_days, [round(x, 4) for x in eq], yearly, st


def calc_ret60(row):
    entry_pos = get_close(cache, row.code, row.entry_date_fixed, "onOrAfter")
    if entry_pos is None:
        return None, None
    df = cache.get(row.code)
    c = df["Close"]
    if hasattr(c, "columns"):
        c = c.iloc[:, 0]
    start_i = c.index.get_loc(entry_pos)
    end_i = start_i + HOLD_DAYS
    if end_i >= len(c):
        return None, None
    return (c.iloc[end_i] / c.iloc[start_i] - 1) * 100, str(entry_pos.date())


panel[["ret60", "entry_day"]] = panel.apply(lambda r: pd.Series(calc_ret60(r)), axis=1)
panel = panel.dropna(subset=["ret60"]).copy()
print(f"可計算報酬筆數: {len(panel)}")

r1 = build_equity(panel[panel.mom_streak3])
d1, e1, y1, s1 = r1
strat1 = dict(name="連續3個月MoM為正(主推)", dates=d1, equity=e1, yearly=y1, stats=s1)
r2 = build_equity(panel[panel.mom_streak2])
d2, e2, y2, s2 = r2
strat2 = dict(name="連續2個月MoM為正", dates=d2, equity=e2, yearly=y2, stats=s2)
strategies = [strat1, strat2]

txr = c_twii.pct_change().fillna(0)
txe = (1 + txr).cumprod()
txe = txe[txe.index.map(lambda d: str(d.date())) >= "2022-01-01"]
txy = {}
for y, g in txr.groupby(txr.index.year):
    g2 = g[g.index.map(lambda d: str(d.date())) >= "2022-01-01"]
    if len(g2):
        txy[str(y)] = ((1 + g2).prod() - 1) * 100
bench_twii = dict(name="加權指數^TWII買進持有", dates=[str(d.date()) for d in txe.index],
                   equity=[round(float(x), 4) for x in txe / txe.iloc[0]], yearly=txy)

benchmarks = [bench_twii]

rdb = sqlite3.connect("research_2022.db")
names = dict(rdb.execute("SELECT code, name FROM (SELECT code, name, snapshot_date FROM rankings "
                          "WHERE country='台' ORDER BY snapshot_date) GROUP BY code"))
trades_show = panel[panel.mom_streak3].sort_values("entry_day").tail(150)
rows = "".join(
    f"<tr><th>{t.entry_day}</th><td>{t.industry}</td><td>{t.code} {names.get(t.code,'')}</td>"
    f"<td class='{'good' if t.ret60>0 else 'bad'}'>{t.ret60:+.1f}%</td></tr>"
    for t in trades_show.itertuples())
trades_html = ("<table><tr><th>進場日(15號)</th><th>題材</th><th>個股</th><th>60日報酬(單筆,非投組)</th></tr>"
               + rows + "</table>")

verdicts = [
    ("主推:連續3個月MoM為正", f"複利{s1['mult']:.2f}x/年化{s1['ann']:+.1f}%/夏普{s1['sharpe']:.2f}/MDD{s1['mdd']:.0f}%/"
                        f"{s1['trades']}筆/勝率{s1['win']:.0f}%/單筆中位{s1['med']:+.1f}%/平均同時曝險{s1['expo']:.0f}%的交易日"),
    ("對照:連續2個月MoM為正", f"複利{s2['mult']:.2f}x/年化{s2['ann']:+.1f}%/夏普{s2['sharpe']:.2f}/MDD{s2['mdd']:.0f}%/"
                        f"{s2['trades']}筆/勝率{s2['win']:.0f}%"),
    ("權益曲線修正說明", "第一版把每筆60天報酬整包記在進場當天再逐日鏈接，算出複利82倍/年化176%這種不可能"
                    "達成的數字(124筆分散在33個月但每筆抱60個交易日≈3個月，必然大量同時持有)。"
                    "已修正為逐日展開、同時持有的部位當天等權平均——這是本系列一貫的投組構建邏輯，只是"
                    "窗口從1天/月底延伸到完整60天"),
    ("時間點修正的重要性", "進場點從月初改到15號(避免用還沒公布的上月營收做決策)，出場從月底改成事件研究法"
                     "找出的60個交易日(訊號優勢隨時間持續擴大，月底出場只抓到一小部分)"),
    ("下一步", "n=120-124仍小，樣本外驗證(2022-24訓練/2025-26測試)、多題材重複計算問題，都還沒處理，"
             "這是初篩結果不是可上線策略"),
]
limits = ("樣本2022-2026；進場點=每月15號(或當月第一個>=15號的交易日)，出場=固定60個交易日後；"
          "權益曲線已修正為逐日展開等權平均，反映同時持有多部位時的資金分食，但仍是簡化模型"
          "(未設資金曝險上限，理論上可無限多部位同時開,實務會受本金限制)；"
          "股票可能同時屬於多個題材，同一筆營收公告可能在不同題材下被重複計算；"
          "size proxy/題材分組門檻(>=3家FinMind覆蓋公司)為使用者裁示，未做門檻穩健性掃描；"
          "未做樣本外訓練/測試切分，本報告數字為全樣本回測，過擬合風險未排除；未建停損。")
prereg = ("2026-07-14研究(使用者多輪校正)：細分題材(classification.main_group)+FinMind加總營收"
          "算MoM/YoY(避免個股比率失真)+連續3個月MoM為正當進場訊號+進場點修正到15號(避免look-ahead)+"
          "60個交易日固定持有(事件研究法找出的最佳窗口，非任意選定)+權益曲線逐日展開避免虛假複利。"
          "產生器=build_theme_momentum_report.py。")
build_report("research_theme_momentum.html", "題材月營收動能策略（連續MoM為正,60日持有）",
             prereg, strategies, benchmarks, trades_html, verdicts, limits)
print("done -> research_theme_momentum.html")
for s in strategies:
    print(s["name"], {k: (round(v, 2) if isinstance(v, float) else v) for k, v in s["stats"].items()})
