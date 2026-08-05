# -*- coding: utf-8 -*-
"""台美隔夜題材連動·live訊號(每天美股收盤後=台北清晨/早上跑,或掛在update_all每日鏈)。

依據: build_us_tw_overnight_link.py(首輪,commit ac221a4)+build_us_tw_pocket_refine.py(第二輪精煉)
已驗證的三個活口訊號,見研究報告/research_us_tw_overnight.html:
  ①獨漲: 美題材原始>2%且SPX<0 → 台股同題材「開盤市價」進場,持5-10交易日(CAR5+0.68%/CAR10+1.15% demean,
    12年11正)。獨漲日跳空不過衝,是全專案少見開盤追買活著的訊號。
  ②強獨漲: 美題材原始>2.5%且SPX<-0.5% → 同上但肉加倍(CAR5+1.44%/CAR10+1.83%),組合模擬0.5%來回成本
    年化+19.9%/MDD-24.8%(持5)。事件~19題材日/年,出現頻率低,出現時是本訊號家族最強格。
  ③尾盤tilt: 美題材超額(減SPX)>2%但SPX>=0(有大盤掩護)→ 不追開盤(跳空過衝275%會回吐),只當
    「本來就要買的股票挑今天尾盤買」的tilt,持5日+0.57%(偏薄)。
命名(2026-08-05定名): 「題材獨漲」舊名「口袋」,「強獨漲」舊名「深口袋」,強度軸=分歧度。
⚠精煉輪教訓: 短持(5-10日)獨漲內不要疊創新高濾網(hi>0組短窗較弱,跳空透支,k40後拉平);「強題材子集」不延續
  (split-half死亡),不要因為某題材最近強就只做該題材。
時序: 美股收盤=台北清晨4-5點,訊號適用「下一個台股交易日」;本腳本可在當天台股開盤前任何時間跑。
用法: python watch_us_tw_overnight.py   (從根目錄執行;前置=先跑 抓取/fetch_us_daily_price.py 增量+
      抓取/fetch_global_index.py 更新SPX。掛在update_all.py每日鏈時順序已排好)
產出: console訊號表 + 研究報告/watch_us_tw_overnight.html
"""
import sqlite3
import sys
from datetime import datetime, timedelta

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

DB = "capital_flow.db"
OUT = "研究報告/watch_us_tw_overnight.html"
ADR_EXCLUDE = {"TSM", "UMC", "ASX"}
MAPPED_THEMES = [
    "IC設計", "CPO/光通訊", "AI伺服器", "半導體設備", "記憶體", "晶圓代工",
    "功率半導體", "電力設備", "組裝代工(EMS)", "機器人/自動化", "半導體材料",
    "電池/儲能", "連接器", "網通設備", "綠能/太陽能", "封測(OSAT/測試)",
    "被動元件", "化合物半導體", "PCB/CCL", "電信",
]
STALE_DAYS = 5          # 美股資料最新日距今>此日曆天數=陳舊警告
LOOKBACK = 45           # 近況段: 回看45日曆天的獨漲事件


def theme_day_signals(conn, us_date):
    """算單一美股日所有題材的r_raw/r_ex/hi_frac。回傳DataFrame。"""
    px = pd.read_sql(
        "select code, date, close from us_daily_price where date>=? and date<=?",
        conn, params=((pd.Timestamp(us_date) - timedelta(days=550)).strftime("%Y-%m-%d"), us_date))
    wide = px.pivot_table(index="date", columns="code", values="close", aggfunc="first").sort_index()
    ret = wide.pct_change(fill_method=None)
    roll_max = wide.rolling(252, min_periods=126).max()
    hi = (wide >= roll_max * 0.999).where(wide.notna() & roll_max.notna())
    spx = pd.read_sql("select date, close from index_daily where market='SPX' and date>=? and date<=?",
                      conn, params=((pd.Timestamp(us_date) - timedelta(days=14)).strftime("%Y-%m-%d"), us_date))
    spx = spx.set_index("date")["close"].sort_index()
    spx_ret = spx.pct_change().get(us_date, float("nan"))
    rows = []
    for t in MAPPED_THEMES:
        mem = [r[0] for r in conn.execute(
            "select distinct code from classification where country='美' and main_group=?", (t,))
            if r[0] not in ADR_EXCLUDE and r[0] in ret.columns]
        if not mem or us_date not in ret.index:
            continue
        r = ret.loc[us_date, mem]
        if r.notna().sum() == 0:
            continue
        rows.append({"theme": t, "r_raw": r.mean(), "n_us": int(r.notna().sum()),
                     "hi_frac": hi.loc[us_date, mem].mean(),
                     "spx": spx_ret, "r_ex": r.mean() - spx_ret})
    return pd.DataFrame(rows)


def classify(row):
    if pd.isna(row["spx"]):
        return "?SPX缺", ""
    if row["r_raw"] >= 0.025 and row["spx"] <= -0.005:
        return "🟢🟢強獨漲", "開盤市價進同題材台股,持5-10日(本家族最強格)"
    if row["r_raw"] >= 0.02 and row["spx"] < 0:
        return "🟢獨漲", "開盤市價進同題材台股,持5-10日"
    if row["r_ex"] >= 0.02 and row["spx"] >= 0:
        return "🔵尾盤tilt", "不追開盤(跳空過衝);本來要買的挑今日尾盤買,持5日(薄)"
    return "", ""


def spx_fallback(us_date):
    """index_daily的SPX還沒更新到us_date時,直接向yfinance要^GSPC補算當日報酬(best-effort)。"""
    try:
        import yfinance as yf
        h = yf.Ticker("^GSPC").history(
            start=(pd.Timestamp(us_date) - timedelta(days=10)).strftime("%Y-%m-%d"),
            auto_adjust=True)
        h.index = h.index.strftime("%Y-%m-%d")
        r = h["Close"].pct_change()
        if us_date in r.index and pd.notna(r[us_date]):
            print(f"[watch] index_daily無SPX {us_date},改用yfinance ^GSPC後備: {r[us_date] * 100:+.2f}%")
            return float(r[us_date])
    except Exception as e:
        print(f"[watch] yfinance SPX後備也失敗({e}),超額/獨漲分類今日無法判斷")
    return float("nan")


def tw_members(conn, theme):
    rows = conn.execute(
        "select distinct code from classification where country='台' and main_group=?", (theme,))
    codes = [r[0] for r in rows]
    names = dict(conn.execute(
        "select code, name from rankings where country='台' and snapshot_date="
        "(select max(snapshot_date) from rankings where country='台')"))
    return [f"{c}{names.get(c, '')}" for c in sorted(codes)]


def main():
    conn = sqlite3.connect(DB, timeout=60)
    us_date = conn.execute("select max(date) from us_daily_price").fetchone()[0]
    if us_date is None:
        print("us_daily_price空表,先跑 抓取/fetch_us_daily_price.py")
        return
    age = (datetime.now() - datetime.strptime(us_date, "%Y-%m-%d")).days
    stale = age > STALE_DAYS
    today = datetime.now().strftime("%Y-%m-%d %H:%M")

    sig = theme_day_signals(conn, us_date)
    if len(sig) and sig["spx"].isna().all():
        sig["spx"] = spx_fallback(us_date)
        sig["r_ex"] = sig["r_raw"] - sig["spx"]
    sig[["tier", "action"]] = sig.apply(lambda r: pd.Series(classify(r)), axis=1)
    sig = sig.sort_values("r_raw", ascending=False)
    spx_v = sig["spx"].iloc[0] if len(sig) else float("nan")

    print("=" * 78)
    spx_txt = f"SPX當日={spx_v * 100:+.2f}%" if pd.notna(spx_v) else "SPX缺值⚠(fetch_global_index+yfinance皆無)"
    print(f"台美隔夜題材訊號  美股最新交易日={us_date}(距今{age}天{'⚠陳舊,先跑fetch' if stale else ''})  {spx_txt}")
    print(f"適用: {us_date}(美東)收盤後的下一個台股交易日開盤前決策  產表時間={today}")
    print("=" * 78)
    hits = sig[sig["tier"] != ""]
    if hits.empty:
        print("今日無訊號(無題材達獨漲/尾盤tilt門檻)。")
    for r in hits.itertuples():
        print(f"{r.tier:<8} {r.theme:<14} 美題材{r.r_raw * 100:+.2f}%(n={r.n_us}) "
              f"SPX{r.spx * 100:+.2f}% 超額{r.r_ex * 100:+.2f}% 新高比{r.hi_frac * 100:.0f}%")
        print(f"         → {r.action}")
        mems = tw_members(conn, r.theme)
        print(f"         台股成員({len(mems)}): {', '.join(mems)}")
        print("         ⚠排除開盤跳空>=+9%(漲停鎖死買不到);短持勿疊創新高濾網、勿只做特定題材(精煉輪判決)")
    print("-" * 78)
    print("全題材今日狀態(參考層):")
    for r in sig.itertuples():
        print(f"  {r.theme:<14} 原始{r.r_raw * 100:+.2f}% 超額{r.r_ex * 100:+.2f}% 新高比{r.hi_frac * 100:.0f}% {r.tier}")

    # 未來7天美股題材成員財報日曆(us_earnings_dates含未來場次;財報版獨漲=exc>5%且SPX<0,
    # 見research_us_earnings_tw_link.html: 反應日CAR5+0.55✓,利多傳導利空不傳導,不用管beat/miss)
    try:
        upcoming = pd.read_sql(
            "select e.code, e.ann_date, e.session, c.main_group as theme "
            "from us_earnings_dates e join classification c on c.code=e.code and c.country='美' "
            "where e.ann_date >= date('now') and e.ann_date <= date('now','+7 day') "
            "order by e.ann_date, e.code", conn)
        print("-" * 78)
        print(f"未來7天美股題材成員財報({len(upcoming)}場;公布後反應日>+5%且SPX<0=財報版獨漲訊號):")
        for r in upcoming.itertuples():
            print(f"  {r.ann_date} {r.session:<3} {r.code:<6} [{r.theme}]")
    except Exception as e:
        upcoming = pd.DataFrame()
        print(f"[watch] 財報日曆讀取失敗({e}),先跑 抓取/fetch_us_earnings_dates.py")

    # 近況: 回看LOOKBACK日曆天的獨漲事件(歷史紀錄用)
    since = (pd.Timestamp(us_date) - timedelta(days=LOOKBACK)).strftime("%Y-%m-%d")
    dates = [r[0] for r in conn.execute(
        "select distinct date from us_daily_price where date>=? and date<=? order by date", (since, us_date))]
    hist = []
    for d in dates:
        s = theme_day_signals(conn, d)
        if s.empty:
            continue
        s[["tier", "action"]] = s.apply(lambda r: pd.Series(classify(r)), axis=1)
        for r in s[s["tier"].str.startswith("🟢", na=False)].itertuples():
            hist.append({"d": d, "theme": r.theme, "tier": r.tier,
                         "r_raw": r.r_raw, "spx": r.spx})
    hist_df = pd.DataFrame(hist)
    print("-" * 78)
    print(f"近{LOOKBACK}日曆天獨漲事件({len(hist_df)}筆):")
    for r in hist_df.itertuples():
        print(f"  {r.d} {r.tier} {r.theme} 美題材{r.r_raw * 100:+.2f}% SPX{r.spx * 100:+.2f}%")

    # HTML
    def row_html(r):
        mems = tw_members(conn, r.theme) if r.tier else []
        return (f"<tr class='{'hit' if r.tier else ''}'><td>{r.tier}</td><th>{r.theme}</th>"
                f"<td>{r.r_raw * 100:+.2f}%</td><td>{r.r_ex * 100:+.2f}%</td>"
                f"<td>{r.hi_frac * 100:.0f}%</td><td style='text-align:left'>{r.action}"
                + (f"<br><span class='sub'>{', '.join(mems)}</span>" if mems else "") + "</td></tr>")

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>台美隔夜題材訊號 {us_date}</title><style>
body{{background:#1a1a19;color:#fff;font-family:"Noto Sans TC",sans-serif;margin:24px;max-width:1100px}}
h1{{font-size:18px}} table{{border-collapse:collapse;font-size:12.5px;font-variant-numeric:tabular-nums}}
td,th{{border:1px solid #333;padding:4px 9px;text-align:right}} th{{text-align:left;color:#c3c2b7}}
.note{{color:#8a8878;font-size:12.5px;line-height:1.8}} .sub{{color:#9a9;font-size:11.5px}}
.hit{{background:#213321}} .warn{{color:#c3a55a;font-weight:bold}}
</style></head><body>
<h1>🌉 台美隔夜題材訊號 — 美股 {us_date} 收盤 → 下一個台股交易日</h1>
<div class="note">SPX當日 {f"{spx_v * 100:+.2f}%" if pd.notna(spx_v) else "缺值⚠"} ·
產表 {today}{'<span class="warn"> ⚠美股資料距今' + str(age) + '天=陳舊,先跑 抓取/fetch_us_daily_price.py</span>' if stale else ''}<br>
規則: 🟢🟢強獨漲=美題材>2.5%且SPX&lt;-0.5%(開盤進,最強) · 🟢獨漲=美題材>2%且SPX&lt;0(開盤進,持5-10日) ·
🔵尾盤tilt=超額>2%且SPX&gt;=0(勿追開盤)。依據 research_us_tw_overnight.html 兩輪考卷;
獨漲勿疊創新高/強題材濾網;排除開盤跳空>=+9%成員。</div>
<table><tr><th>訊號</th><th>題材</th><th>美題材原始</th><th>超額(減SPX)</th><th>美側新高比</th><th>行動/台股成員</th></tr>
{"".join(row_html(r) for r in sig.itertuples())}
</table>
<h1 style="font-size:15px;margin-top:26px">近{LOOKBACK}日曆天獨漲事件({len(hist_df)}筆)</h1>
<table><tr><th>美股日</th><th>級別</th><th>題材</th><th>美題材</th><th>SPX</th></tr>
{"".join(f"<tr><td>{r.d}</td><td>{r.tier}</td><th>{r.theme}</th><td>{r.r_raw * 100:+.2f}%</td><td>{r.spx * 100:+.2f}%</td></tr>" for r in hist_df.itertuples())}
</table>
<h1 style="font-size:15px;margin-top:26px">未來7天美股題材成員財報日曆({len(upcoming)}場)</h1>
<div class="note">公布後反應日「超額>+5%且SPX&lt;0」=財報版獨漲(CAR5+0.55✓,見research_us_earnings_tw_link.html);
利多傳導/利空不傳導,不用管beat/miss只看價格反應。AMC=美股盤後(反應日=次一美股日)。</div>
<table><tr><th>公布日</th><th>時段</th><th>代碼</th><th>題材</th></tr>
{"".join(f"<tr><td>{r.ann_date}</td><td>{r.session}</td><th>{r.code}</th><td style='text-align:left'>{r.theme}</td></tr>" for r in upcoming.itertuples())}
</table>
<div class="note">維運: python watch_us_tw_overnight.py(從根目錄);前置=fetch_us_daily_price增量+fetch_global_index(SPX)+fetch_us_earnings_dates(週頻)。</div>
</body></html>"""
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[watch] 已輸出 {OUT}")
    conn.close()


if __name__ == "__main__":
    main()
