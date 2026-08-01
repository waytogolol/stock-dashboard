# -*- coding: utf-8 -*-
"""配置引擎v1(2026-08-01,承接天氣儀三帶bugfix後的下一棒:天氣儀四維×策略矩陣權重×殺出深度總水位
×燈號事件倉信心%,合成逐日資金配置權重,取代300萬模擬器v0固定A3/B3/C2格數的靜態配置)。
====================================================================================
【這支腳本在解什麼新問題】
v0(build_portfolio_sim_300w.py)已經驗證了A(處置槽位)/B(題材S3週線)/C(溫度計機動)三個艙位「各自」
能不能賺錢,但艙位間的權重(3/3/2)是使用者手訂的固定風險旋鈕,不隨天氣/深度/信心度變動。這支腳本
把既有的四組已驗證訊號重新組裝成一個「逐日該給誰多少權重」的配置引擎,新問題只有一個:
**怎麼把regime+策略值班表+深度+信心度合成部位權重**,四組輸入訊號本身都不重新驗證/不重新回測:

  1. 天氣儀三帶象限(X=波動期限結構vol10/vol60,Y=蹺蹺板=櫃買/加權指數比值20日變化%):
     升溫>1.2/退潮<0.8/中性(過渡,不強制歸邊)——切點與export_html.py、build_regime_weather_report.py
     完全一致(2026-07-31三帶bugfix同一常數)。⚠若三帶切點需要調整,三處都要同步改。
  2. 策略矩陣權重=直接沿用天氣儀值班表已驗證的質化結論(不重新呼叫/重寫build_strategy_regime_matrix
     的r1(),也不重新統計),見下方QUAD_WEIGHT。
  3. 殺出深度總水位=export_html.py `_depth6`/`_depth_zone6`同一公式(上市融資餘額距245日高點縮水%,
     乾淨格≤-30/過渡段≤-20/死亡谷≤-10/淺段),當整體風險預算乘數。
  4. 事件倉信心%=export_html.py `_lit`/`_expo6`同一權重公式(0.6甜蜜格+0.4亞跌B+0.3融資警戒
     +0.3雙收斂+0.3跌停廣度,上限100%),重建為逐日歷史序列(live版只存「今日」一筆快照,回測需要
     逐日序列;本檔build_light_matrix()把v0build_lights()內部灑開成五個獨立布林序列後再加權)。

【已知限制,使用者已拍板,本引擎照既定方式處理,不重複討論】
A艙(處置槽位×題材)歷史回測用2026-06-30才存在的all_classified.csv分類套用回2019~2025的歷史事件,
是概念性前視(前視的是「拿未來才存在的分類貼回過去」這個動作本身,不是資料缺口),沒辦法回補。
A艙的**即時**滑動邏輯(今天套用今天當下的分類)沒有這個問題;但A艙**歷史回測數字**在本報告一律標注
「描述性參考,含前視,不當作本引擎v1權重依據的證據」——本引擎的策略矩陣權重是直接沿用值班表的質化
結論(第2點),不是從A艙歷史報酬重新估出來的,所以引擎的「設計」本身不受這個前視污染;只有A艙的
「回測績效數字」在解讀v0/v1的對照表時要打折扣。B艙(build_s3_weekly)/C艙(build_lights)歷史回測
沒有這個前視問題,可以正常當佐證。

【產出】
console + 研究報告/research_config_engine_v1.html(v0 vs v1逐項對照:倍數/CAGR/MDD/夏普/逐年勝率/
平均曝險;象限占比與深度/信心度分布;象限→A/B權重表；權益曲線圖)。
不改動dashboard.html/export_html.py(那是天氣儀v1的地盤,本腳本只讀規則不寫回)。

用法: python 研究腳本/綜合策略/build_config_engine_v1.py  (從根目錄,鐵律)
"""
import json
import sqlite3
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "研究腳本/綜合策略")
import build_portfolio_sim_300w as SIM  # 重用v0的A/B/C艙建構器(build_v4_events/build_lights/
                                          # build_s3_weekly)與原始simulate(),不重寫、不重新驗證

DB = "capital_flow.db"
OUT = "研究報告/research_config_engine_v1.html"

# ── 三帶切點(2026-07-31統一版,R1/R4驗證) ────────────────────────────────────
# ⚠象限切點需與export_html.py、build_regime_weather_report.py保持一致,如需修改三處都要改。
VOL_HOT, VOL_COOL = 1.2, 0.8

# ── 策略矩陣權重(直接沿用天氣儀值班表已驗證的質化結論,轉成量化槽位配比) ──────────
# 這是「把質化值班表翻譯成數字」的手訂配置政策,不是本腳本重新統計/最適化出來的結果——
# 開放未來版本用回測網格搜尋校準,這裡先給一組符合值班表方向與強弱的合理起點。
# a/b = A艙(處置事件策略)/B艙(題材S3動能)各拿多少倍的ab_baseline(v0基準=3+3=6)。
QUAD_WEIGHT = {
    "亂世":     {"a": 1.00, "b": 0.00},  # 升溫×大盤強:事件策略全額值班,題材逆風退場
    "題材天堂": {"a": 0.00, "b": 1.00},  # 退潮×小盤強:score4全額值班,事件策略退場
    "修復觀望": {"a": 0.30, "b": 0.30},  # 退潮×大盤強:等三重發車鈴,兩派同時打折觀望
    "過熱":     {"a": 0.20, "b": 0.60},  # 升溫×小盤強:score4觀察層(n=46小),B不給滿額、A留小額防踏空
    "過渡":     {"a": 0.50, "b": 0.50},  # 中性帶(任務1新增):不強制歸邊,兩派同時降權觀望
}

# ── 殺出深度風險預算乘數(依E5b分帶,乾淨格才拉滿格/死亡谷最危險縮手) ────────────
# 同樣是手訂乘數,方向性(乾淨格>過渡段=淺段>死亡谷)取自build_margin_flush_exam.py E5b判決
# (乾淨格−死亡谷+6.84pp CI排0=「殺夠深才乾淨,殺一半最毒」),量值未經網格校準。
DEPTH_MULT = {"乾淨格": 1.25, "過渡段": 1.00, "死亡谷": 0.60, "淺段": 1.00}

# ── 事件倉信心%對A艙(僅限亂世象限)的加碼/減碼幅度 ──────────────────────────
# conf_mult = 1 + CONF_BOOST*(confidence-0.5),confidence=0.5視為中性無資訊、不調整;
# CONF_BOOST=0.4→調整區間[0.8,1.2],刻意設計成溫和加減碼而非開關(任務要求「這信心度只對事件
# 策略有意義,不是全市場乘數」,故只在quad=="亂世"時生效,其餘象限a乘數固定=1)。
CONF_BOOST = 0.4


def rd(sql, params=None):
    con = sqlite3.connect(DB)
    df = pd.read_sql(sql, con, params=params)
    con.close()
    return df


# ══ 天氣儀三帶象限逐日序列 ══════════════════════════════════════════════
def build_quadrant(cal):
    """X=TAIEX vol10/vol60,Y=TPEx/TAIEX指數比值20日變化%;三帶切點=export_html.py同款常數。"""
    idx = rd("SELECT market, date, close FROM index_daily WHERE market IN ('TAIEX','TPEx')")
    idx["date"] = pd.to_datetime(idx.date)
    tw = idx[idx.market == "TAIEX"].set_index("date").close.sort_index()
    otc = idx[idx.market == "TPEx"].set_index("date").close.sort_index()
    r = tw.pct_change() * 100
    ts = (r.rolling(10).std() / r.rolling(60).std()).reindex(cal, method="ffill")
    app = (otc / tw).dropna()
    app = ((app / app.shift(20) - 1) * 100).reindex(cal, method="ffill")
    hot = (ts > VOL_HOT).values
    cool = (ts < VOL_COOL).values
    small = (app >= 0).values
    quad = pd.Series(np.select(
        [hot & small, hot & ~small, cool & small, cool & ~small],
        ["過熱", "亂世", "題材天堂", "修復觀望"], default="過渡"
    ), index=cal)
    return quad, ts, app


# ══ 殺出深度總水位逐日分帶 ══════════════════════════════════════════════
def build_depth(cal):
    """公式同export_html.py `_depth6`:今日/245日內最大值-1,分帶同`_depth_zone6`。
    主口徑用上市融資餘額;上櫃深度僅供對照未混入乘數(見腳本docstring open question)。"""
    def _series(sql):
        b = rd(sql)
        b["date"] = pd.to_datetime(b.date)
        b = b.set_index("date").v
        return ((b / b.rolling(245, min_periods=200).max() - 1) * 100).reindex(cal, method="ffill")

    depth_tw = _series("SELECT date, today_balance v FROM margin_total "
                        "WHERE name='MarginPurchaseMoney' ORDER BY date")
    depth_otc = _series("SELECT date, money_today v FROM margin_total_otc ORDER BY date")

    def zone(v):
        if pd.isna(v):
            return "淺段"
        return ("乾淨格" if v <= -30 else "過渡段" if v <= -20
                else "死亡谷" if v <= -10 else "淺段")
    return depth_tw.map(zone), depth_tw, depth_otc


# ══ 五燈逐日布林矩陣(供事件倉信心%用) ═══════════════════════════════════
def build_light_matrix(tw_close):
    """thermo/b/warn/conv/ld五欄逐日布林,門檻/窗長與export_html.py `_lit`完全比照。
    v0的build_lights()只回傳五燈OR之後的單一布林(給C艙進出場用),這裡拆開留五欄給信心%加權;
    甜蜜格/跌停沿用v0同一批快取面板(tmp_panic_gradient_panel.pkl/tmp_limit_flags.pkl),
    不重新從逐股價格算(避免與C艙口徑漂移、也省算力)。"""
    idx = rd("SELECT market, date, close FROM index_daily WHERE market IN ('N225','KOSPI','SPX')")
    idx["date"] = pd.to_datetime(idx.date)
    n2 = idx[idx.market == "N225"].set_index("date").close.pct_change() * 100
    ko = idx[idx.market == "KOSPI"].set_index("date").close.pct_change() * 100
    sp = idx[idx.market == "SPX"].set_index("date").close.sort_index()
    spr = sp.pct_change() * 100
    twr = tw_close.pct_change() * 100
    dd250 = (tw_close / tw_close.rolling(250, min_periods=120).max() - 1) * 100
    drop10 = (tw_close / tw_close.shift(10) - 1) * 100
    p = pd.read_pickle("快取/tmp_panic_gradient_panel.pkl")
    ss = p[(p.i1 == "-6~-9") & (p.i2 == ">=20%")]
    sweet = ss.groupby("d0").size()
    lf = pd.read_pickle("快取/tmp_limit_flags.pkl")
    ldc = lf[~lf.code.str.startswith("00")].groupby("date").ld_close.sum()

    trig = {"thermo": [], "b": [], "conv": [], "ld": []}
    for d in tw_close.index:
        if sweet.get(d, 0) >= 20:
            trig["thermo"].append(d)
        if ldc.get(d, 0) >= 20:
            trig["ld"].append(d)
        nv, kv = n2.get(d, np.nan), ko.get(d, np.nan)
        si = spr.index.searchsorted(d) - 1
        uv = float(spr.iloc[si]) if si >= 0 else np.nan
        if pd.notna(nv) and pd.notna(kv) and pd.notna(uv) and nv <= -2 and kv <= -2 and uv > -1:
            trig["b"].append(d)
        dv, rv, d10 = dd250.get(d), twr.get(d), drop10.get(d)
        if (pd.notna(dv) and -20 < dv <= -10 and pd.notna(rv) and rv <= -2
                and pd.notna(d10) and d10 <= -6):
            trig["conv"].append(d)

    hold = {"thermo": 60, "b": 10, "conv": 20, "ld": 20}  # 窗長同export_html.py `_remain6`呼叫值
    pos = {d: i for i, d in enumerate(tw_close.index)}
    out = pd.DataFrame(False, index=tw_close.index, columns=["thermo", "b", "conv", "ld", "warn"])
    for k, days in trig.items():
        arr = out[k].values
        for d in days:
            i = pos[d]
            arr[i:i + hold[k]] = True
        out[k] = arr

    mm = rd("SELECT date, ratio FROM margin_maintenance_official ORDER BY date")
    mm["date"] = pd.to_datetime(mm.date)
    mm = mm.set_index("date").ratio
    out["warn"] = (mm.reindex(tw_close.index, method="ffill") < 150).fillna(False)
    return out


def confidence_series(lights):
    """事件倉信心%=export_html.py `_expo6`同一權重公式,逐日版(上限100%)。"""
    conf = (0.6 * lights.thermo + 0.4 * lights.b + 0.3 * lights.warn
            + 0.3 * lights.conv + 0.3 * lights.ld)
    return conf.clip(upper=1.0)


# ══ v1動態配置模擬(比照SIM.simulate()逐日力學,只把固定a_slots/b_slots/c_slots換成
#     逐日動態值;dynamic=False時退化回v0固定配比,供對SIM.simulate()做數值一致性驗證) ══
def simulate_v1(cal, tw_close, ev, close_map, lit, s3w, quad, depth_zone, confidence,
                 dynamic=True, n_slot=10, ab_baseline=6, c_slots_base=2,
                 a0=3, b0=3, label="", start="2019-06-01", end="2026-07-01", quiet=False):
    cal = [d for d in cal if pd.Timestamp(start) <= d <= pd.Timestamp(end)]
    ev_by_day = {d: g for d, g in ev.groupby("entry")}
    s3_dates = set(s3w.index)
    cash, b_val = SIM.CAP0, 0.0
    a_pos = []
    c_size, c_entry_px = 0.0, None
    nav_series = []
    a_pnl = c_pnl = 0.0
    b_base = 0
    quad_count = {}
    for d in cal:
        q = quad.get(d, "過渡")
        z = depth_zone.get(d, "淺段")
        cf = confidence.get(d, 0.0)
        quad_count[q] = quad_count.get(q, 0) + 1
        if dynamic:
            w = QUAD_WEIGHT.get(q, QUAD_WEIGHT["過渡"])
            dm = DEPTH_MULT.get(z, 1.0)
            # 事件倉信心%只調整「亂世象限的A艙(事件策略)」,不誤用在B艙(題材動能)或非亂世象限
            conf_mult = (1 + CONF_BOOST * (cf - 0.5)) if q == "亂世" else 1.0
            a_slots = ab_baseline * w["a"] * dm * conf_mult
            b_slots = ab_baseline * w["b"] * dm
            c_slots = c_slots_base * dm
        else:
            a_slots, b_slots, c_slots = a0, b0, c_slots_base
        # A出場
        keep = []
        for p in a_pos:
            if p["exit"] <= d:
                cash += p["size"] * (1 + p["net"] / 100)
                a_pnl += p["size"] * p["net"] / 100
            else:
                keep.append(p)
        a_pos = keep
        # C出入場
        twp = tw_close.get(d)
        if lit.get(d, False) and c_size == 0 and pd.notna(twp):
            nav_now = cash + b_val + sum(
                p["size"] * (close_map[p["code"]].asof(d) / p["entry_px"]) for p in a_pos)
            want = c_slots * nav_now / n_slot
            c_size = min(want, cash)
            c_entry_px = twp
            cash -= c_size
        elif not lit.get(d, False) and c_size > 0 and pd.notna(twp):
            cash += c_size * (twp / c_entry_px)
            c_pnl += c_size * (twp / c_entry_px - 1)
            c_size = 0.0
        # B週線(週五結算+再平衡)
        if d in s3_dates:
            r = s3w.loc[d]
            b_val *= (1 + r.ret / 100)
            nav_now = cash + b_val + c_size * (twp / c_entry_px if c_size else 0) + sum(
                p["size"] * (close_map[p["code"]].asof(d) / p["entry_px"]) for p in a_pos)
            target = (b_slots * nav_now / n_slot) if r.n > 0 else 0.0
            delta = target - b_val
            if delta > 0:
                delta = min(delta, cash)
            cash -= delta
            b_val += delta
            b_base += 1
        # A進場(優先序=tier→tv3,同v0)
        g = ev_by_day.get(d)
        if g is not None:
            for r in g.sort_values(["tier", "tv3"], ascending=[True, False]).itertuples():
                if len(a_pos) >= a_slots:
                    break
                nav_now = cash + b_val + c_size * (twp / c_entry_px if c_size else 0) + sum(
                    p["size"] * (close_map[p["code"]].asof(d) / p["entry_px"]) for p in a_pos)
                size = min(nav_now / n_slot, 0.01 * r.tv3 * 1e8, cash)
                if size <= 10_000:
                    continue
                cash -= size
                a_pos.append({"code": r.code, "size": size, "entry_px": r.entry_px,
                              "exit": r.exit, "net": r.net})
        # 日終NAV
        a_mark = sum(p["size"] * (close_map[p["code"]].asof(d) / p["entry_px"]) for p in a_pos)
        c_mark = c_size * (twp / c_entry_px) if c_size and pd.notna(twp) else c_size
        nav = cash + b_val + a_mark + c_mark
        nav_series.append((d, nav, (a_mark + b_val + c_mark) / nav, q))
    nv = pd.DataFrame(nav_series, columns=["date", "nav", "expo", "quad"]).set_index("date")
    tw_win = tw_close.reindex(nv.index).ffill()
    bh = tw_win / tw_win.iloc[0]
    mult = nv.nav.iloc[-1] / SIM.CAP0
    yrs = (nv.index[-1] - nv.index[0]).days / 365.25
    dr = nv.nav.pct_change().dropna()
    sharpe = dr.mean() / dr.std() * np.sqrt(252) if dr.std() > 0 else np.nan
    mdd = float(((nv.nav / nv.nav.cummax()) - 1).min() * 100)
    bh_mdd = float(((bh / bh.cummax()) - 1).min() * 100)
    yearly = []
    for y, gy in nv.groupby(nv.index.year):
        r_p = gy.nav.iloc[-1] / gy.nav.iloc[0] - 1
        b_y = tw_win.loc[gy.index]
        r_b = b_y.iloc[-1] / b_y.iloc[0] - 1
        yearly.append((y, r_p * 100, r_b * 100, r_p > r_b))
    if not quiet:
        print(f"[{label}] {nv.index[0].date()}~{nv.index[-1].date()}  "
              f"組合{mult:.2f}x(CAGR{(mult ** (1 / yrs) - 1) * 100:+.1f}%) vs 大盤{bh.iloc[-1]:.2f}x | "
              f"MDD {mdd:+.1f}% vs 大盤{bh_mdd:+.1f}% | 夏普{sharpe:.2f} | "
              f"平均曝險{nv.expo.mean() * 100:.0f}%")
        wy = sum(1 for _, _, _, w in yearly if w)
        print("   逐年: " + "  ".join(f"{y}:{rp:+.1f}%vs{rb:+.1f}%{'✓' if w else '✗'}"
                                      for y, rp, rb, w in yearly) + f"  ({wy}/{len(yearly)}年勝)")
        print(f"   損益歸因: A處置{a_pnl / 1e4:+,.0f}萬 C機動{c_pnl / 1e4:+,.0f}萬 "
              f"B題材={'(併入NAV,週線結算)' if b_base else '未啟用'}")
        if dynamic:
            print("   象限占比: " + "、".join(
                f"{k}{v / len(cal) * 100:.0f}%" for k, v in sorted(quad_count.items(),
                                                                    key=lambda x: -x[1])))
    return dict(mult=mult, mdd=mdd, sharpe=sharpe, bh=float(bh.iloc[-1]), bh_mdd=bh_mdd,
                wy=sum(1 for _, _, _, w in yearly if w), ny=len(yearly),
                expo=float(nv.expo.mean()), nav=nv, quad_count=quad_count, yearly=yearly)


# ══ HTML報告 ═════════════════════════════════════════════════════════
def build_html(v0, v1, static_check, quad, ts, app, depth_zone_tw, depth_tw, depth_otc,
               confidence, cal_win, start, end):
    css = """
body{background:#1a1a19;color:#fff;font-family:"Noto Sans TC",sans-serif;margin:24px;max-width:1100px}
h1{font-size:20px} h2{font-size:15px;color:#c3c2b7;margin-top:30px;border-bottom:1px solid #333;padding-bottom:4px}
h3{font-size:13.5px;color:#a8a79a;margin:16px 0 4px}
table{border-collapse:collapse;font-size:12.5px;font-variant-numeric:tabular-nums;margin:8px 0}
td,th{border:1px solid #333;padding:4px 9px;text-align:right} th{text-align:left;color:#c3c2b7}
.note{color:#8a8878;font-size:12.5px;line-height:1.8} .good{color:#7ec97e} .bad{color:#e06c5a}
.warn{color:#c3a55a;font-weight:700}
"""
    def row(label, a, b, fmt="{:+.1f}%", better="high"):
        av, bv = a, b
        cls_a = "good" if (better == "high" and av >= bv) or (better == "low" and av <= bv) else ""
        cls_b = "good" if (better == "high" and bv > av) or (better == "low" and bv < av) else ""
        return (f"<tr><th>{label}</th><td class='{cls_a}'>{fmt.format(av)}</td>"
                f"<td class='{cls_b}'>{fmt.format(bv)}</td></tr>")

    cmp_html = (
        "<tr><th>指標</th><th>v0原始基準(A3B3C2固定)</th><th>v1配置引擎(動態)</th></tr>"
        + row("倍數(mult)", v0["mult"], v1["mult"], "{:.2f}x", "high")
        + row("MDD", v0["mdd"], v1["mdd"], "{:+.1f}%", "high")  # MDD越接近0越好
        + row("夏普(粗)", v0["sharpe"], v1["sharpe"], "{:.2f}", "high")
        + row("平均曝險", v0["expo"] * 100, v1["expo"] * 100, "{:.0f}%", "high")
        + f"<tr><th>逐年勝率</th><td>{v0['wy']}/{v0['ny']}</td><td>{v1['wy']}/{v1['ny']}</td></tr>"
        + f"<tr><th>對照大盤買進持有</th><td colspan=2>{v0['bh']:.2f}x／MDD{v0['bh_mdd']:+.1f}%"
          "(同一窗口,兩次模擬應算出同一個數字,見下方一致性檢查)</td></tr>"
    )
    qw_html = "".join(
        f"<tr><th>{q}</th><td>{w['a']:.2f}</td><td>{w['b']:.2f}</td></tr>"
        for q, w in QUAD_WEIGHT.items())
    dm_html = "".join(f"<tr><th>{z}</th><td>×{m}</td></tr>" for z, m in DEPTH_MULT.items())
    occ = v1["quad_count"]
    occ_total = sum(occ.values())
    occ_html = "".join(
        f"<tr><th>{q}</th><td>{n}</td><td>{n / occ_total * 100:.1f}%</td></tr>"
        for q, n in sorted(occ.items(), key=lambda x: -x[1]))
    yr_html = "".join(
        f"<tr><td>{y}</td><td class='{'good' if wp else 'bad'}'>{rp:+.1f}%</td>"
        f"<td class='{'good' if wc else 'bad'}'>{rc:+.1f}%</td><td>{rb:+.1f}%</td></tr>"
        for (y, rp, rb, wp), (_, rc, _, wc) in zip(v0["yearly"], v1["yearly"]))

    v0_eq, v1_eq = v0["nav"].nav / SIM.CAP0, v1["nav"].nav / SIM.CAP0
    bh_win = (SIM.rd("SELECT date, close FROM index_daily WHERE market='TAIEX' ORDER BY date")
              .assign(date=lambda d: pd.to_datetime(d.date)).set_index("date").close
              .reindex(v0_eq.index).ffill())
    bh_win = bh_win / bh_win.iloc[0]
    payload = {
        "v0": {"d": [str(d.date()) for d in v0_eq.index], "v": [round(float(x), 3) for x in v0_eq.values]},
        "v1": {"d": [str(d.date()) for d in v1_eq.index], "v": [round(float(x), 3) for x in v1_eq.values]},
        "bh": {"d": [str(d.date()) for d in bh_win.index], "v": [round(float(x), 3) for x in bh_win.values]},
    }
    bg = {"paper_bgcolor": "#1a1a19", "plot_bgcolor": "#22221f",
          "font": {"color": "#ddd", "size": 12}, "margin": {"t": 30, "l": 55, "r": 20, "b": 40}}
    a0v = static_check["a0"]["mult"]
    a1v = static_check["a1"]["mult"]
    consist_html = (
        f"<div class='note'>一致性檢查(非任務核心,純自我驗證):simulate_v1()以dynamic=False強制固定"
        f"a_slots=3/b_slots=3/c_slots=2(等同v0原始配置)重跑一次,理論上應與SIM.simulate()原始函式算出同一個數字——"
        f"倍數{a0v:.4f}x(本檔靜態模式) vs {a1v:.4f}x(v0原始函式),"
        f"{'<span class=\"good\">✓一致,力學複製無誤</span>' if abs(a0v - a1v) < 0.01 else '<span class=\"bad\">⚠有落差,見下方説明</span>'}。"
        "</div>")

    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>配置引擎v1——天氣儀×策略矩陣×殺出深度×事件倉信心% vs 300萬模擬器v0(2026-08-01)</title>
<script src="plotly.min.js"></script><style>{css}</style></head><body>
<h1>⚙️ 配置引擎v1——天氣儀四維×策略矩陣權重×殺出深度總水位×燈號事件倉信心%(2026-08-01)</h1>
<div class="note">目的=把regime+策略值班表+深度+信心度合成「逐日該給誰多少權重」的資金配置引擎,取代
300萬模擬器v0固定A3/B3/C2格數的靜態配置。四組輸入訊號(天氣儀三帶象限/值班表/殺出深度分帶/五燈信心%)
本身皆為既有已驗證結論的直接沿用,本卷只解「怎麼合成部位權重」這個新問題,不重新驗證/回測任何一組
輸入訊號。回測窗={start}~{end}(與v0一致)。</div>

<h2 class="warn">⚠ 讀表前必看:A艙前視限制</h2>
<div class="note">本回測A艙(處置槽位×題材)沿用<code>build_v4_events()</code>既有事件明細,含2026年題材
分類(all_classified.csv 2026-06-30才存在)套用回2019~2025歷史事件的<b>前視偏誤</b>——這是概念性前視
(前視的是「拿未來才有的分類貼回過去」這個動作本身),不是資料缺口,無法回補,使用者已拍板不修。
<b>下表A艙相關的歷史回測數字(v0與v1皆含)僅供描述性參考,不當作本引擎v1權重設計依據的證據</b>——
本引擎的策略矩陣權重是直接沿用天氣儀值班表的質化結論轉譯而來,不是從A艙歷史報酬重新估計出來的,
所以「引擎設計」本身不受此前視污染,受影響的只有下表呈現的絕對報酬數字。A艙的<b>即時</b>滑動邏輯
(今天套用今天當下的分類)沒有這個問題。B艙(build_s3_weekly)/C艙(build_lights)歷史回測無此前視,
可正常佐證。</div>

<h2>📊 v0 vs v1 主要指標對照</h2>
<table>{cmp_html}</table>
{consist_html}

<h2>📈 權益曲線(v0固定配置 vs v1動態配置 vs 大盤買進持有,log軸)</h2>
<div id="eqChart" style="height:440px"></div>

<h2>🗂️ 逐年報酬對照</h2>
<table><tr><th>年</th><th>v0</th><th>v1</th><th>大盤</th></tr>{yr_html}</table>

<h2>⚖️ 策略矩陣權重(象限→A/B艙ab_baseline倍數,手訂配置政策見腳本docstring)</h2>
<table><tr><th>象限</th><th>A艙(事件策略)</th><th>B艙(題材動能)</th></tr>{qw_html}</table>
<div class="note">ab_baseline=6(=v0基準a_slots3+b_slots3);上表數字為該倍數的乘數,例如「亂世→A=1.00」
代表當日a_slots目標=6×1.00×殺出深度乘數×(僅亂世適用的)事件倉信心乘數。C艙(溫度計機動)不受象限
影響,只受殺出深度乘數縮放(見下),因為C艙本身已經是五燈觸發的獨立機制,不需要天氣regime軸二次判斷。</div>

<h2>💧 殺出深度風險預算乘數</h2>
<table><tr><th>深度分帶</th><th>乘數(套用在A/B/C全部槽位目標上)</th></tr>{dm_html}</table>
<div class="note">公式沿用export_html.py `_depth6`(今日融資餘額/245日內最大值-1,上市口徑);
方向性取自build_margin_flush_exam.py E5b(乾淨格−死亡谷+6.84pp CI排0=「殺夠深才乾淨,殺一半最毒」)。
事件倉信心%(五燈加權,公式同export_html.py `_expo6`)僅疊加在「亂世象限的A艙」上做±20%的加碼/減碼微調
(conf_mult=1+0.4×(信心%-0.5)),不套用在B艙或C艙——B艙是題材動能非事件策略;C艙的on/off本身已經是
同一批燈號驅動,再乘一次信心%等於同一份資訊算兩次,故意不重複套用(細節見腳本docstring)。</div>

<h2>🌦️ 回測窗象限占比與訊號分布</h2>
<table><tr><th>象限</th><th>天數</th><th>占比</th></tr>{occ_html}</table>
<div class="note">殺出深度(上市)分布:中位{depth_tw.median():+.1f}%、
乾淨格天數占比{(depth_zone_tw == '乾淨格').mean() * 100:.1f}%、死亡谷天數占比
{(depth_zone_tw == '死亡谷').mean() * 100:.1f}%(上櫃深度中位{depth_otc.median():+.1f}%,
僅供對照未混入乘數,見open question)。事件倉信心%均值{confidence.reindex(cal_win).mean() * 100:.1f}%、
最新一日{confidence.iloc[-1] * 100:.0f}%(應與dashboard天氣儀當下的事件倉信心徽章數字量級一致,
交叉驗證見console輸出)。</div>

<h2>❓ Open Questions(未自行假設,留待使用者確認)</h2>
<div class="note">
<p>1. 殺出深度風險預算乘數以「上市」融資餘額深度為主(v0既有做法的延伸),上櫃深度只用來對照顯示、
沒有混入乘數計算——是否要改成兩市加權平均或取兩者較保守值,待確認。</p>
<p>2. 事件倉信心%只加碼/減碼「亂世象限的A艙」,沒有套用到C艙——雖然C艙同樣是五燈觸發的溫度計艙位,
理論上也可以用同一信心度做部位微調,但這樣等於同一批燈號的資訊被算兩次(C的on/off本身已內含燈號
資訊),為避免重複計算、也為求嚴格對應任務指示「這信心度只對事件策略/亂世象限有意義」,保守選擇不
套用在C艙。如果使用者認為C艙也該吃這個信心度做二次微調,可以再擴充。</p>
<p>3. QUAD_WEIGHT(象限→A/B權重)與DEPTH_MULT(深度→風險預算乘數)的具體數字都是把值班表的「質化」
結論(誰值班/誰退場/誰觀察)手工翻譯成的量化槽位配比,方向性(誰該加誰該減)有研究依據,但確切倍數
(例如「亂世給A×1.00而非×0.8或×1.5」)沒有經過網格搜尋或其他統計方法校準——這是本引擎v1的已知簡化,
留給下一版做參數敏感度掃描或優化。</p>
</div>

<script>
const DATA = {json.dumps(payload, ensure_ascii=False)};
const BG = {json.dumps(bg)};
const CVL = (k, name, extra) => Object.assign({{x: DATA[k].d, y: DATA[k].v, name: name, mode: 'lines'}}, extra || {{}});
Plotly.newPlot('eqChart', [
  CVL('bh', '大盤買進持有', {{line: {{color: '#5dade2', width: 1.5, dash: 'dot'}}}}),
  CVL('v0', 'v0固定配置(A3B3C2)', {{line: {{color: '#8a8878', width: 2}}}}),
  CVL('v1', 'v1動態配置引擎', {{line: {{color: '#e0b45a', width: 2.5}}}}),
], Object.assign({{yaxis: {{type: 'log', title: 'NAV倍數(log)', gridcolor: '#333'}},
                   xaxis: {{gridcolor: '#333'}}, legend: {{orientation: 'h', y: -0.15}}}}, BG),
  {{displayModeBar: false, responsive: true}});
</script>
</body></html>"""


def main():
    tw = rd("SELECT date, close FROM index_daily WHERE market='TAIEX' ORDER BY date")
    tw["date"] = pd.to_datetime(tw.date)
    tw_close = tw.set_index("date").close
    cal = list(tw_close.index)
    start, end = "2019-06-01", "2026-07-01"
    cal_win = [d for d in cal if pd.Timestamp(start) <= d <= pd.Timestamp(end)]

    print("V4事件/S3週線/四燈建構中(重用v0建構器)…")
    ev, close_map = SIM.build_v4_events()
    lit = SIM.build_lights(tw_close)
    s3w = SIM.build_s3_weekly(tw_close)
    print(f"  V4事件{len(ev)}筆 / 燈亮窗{int(lit.sum())}天 / S3週線{len(s3w)}週")

    print("天氣儀三帶象限/殺出深度/五燈信心%建構中…")
    quad, ts, app = build_quadrant(cal)
    depth_zone_tw, depth_tw, depth_otc = build_depth(cal)
    lights = build_light_matrix(tw_close)
    confidence = confidence_series(lights).reindex(cal, method="ffill").fillna(0.0)
    print(f"  最新讀數({cal[-1].date()}): ts={ts.iloc[-1]:.2f} 蹺蹺板{app.iloc[-1]:+.1f}% "
          f"={quad.iloc[-1]}象限 | 殺出深度(上市){depth_tw.iloc[-1]:+.1f}%={depth_zone_tw.iloc[-1]} "
          f"| 事件倉信心{confidence.iloc[-1] * 100:.0f}% "
          f"(⚠應與dashboard天氣儀當下的事件倉信心徽章同量級,若export_html.py剛跑過可對照console"
          f"「大盤溫度計」那行的曝險數字互相驗證)")

    print("\n===== v0原始基準(SIM.simulate()原函式,未修改) =====")
    v0_orig = SIM.simulate(cal, tw_close, ev, close_map, lit, s3w, label="v0原始函式·A3B3C2")

    print("\n===== 一致性檢查:simulate_v1(dynamic=False)應與v0原始函式數字一致 =====")
    static_a0 = simulate_v1(cal, tw_close, ev, close_map, lit, s3w, quad, depth_zone_tw,
                             confidence, dynamic=False, a0=3, b0=3, start=start, end=end,
                             label="本檔靜態模式(a0=3,b0=3,c=2)")
    static_check = {"a0": static_a0, "a1": v0_orig}
    if abs(static_a0["mult"] - v0_orig["mult"]) < 0.01:
        print("   ✓ 一致:simulate_v1力學複製v0原始simulate()無誤,可信任下面的v1動態結果。")
    else:
        print("   ⚠ 有落差,需檢查simulate_v1與SIM.simulate()是否邏輯不同步。")

    print("\n===== v1配置引擎(動態:天氣儀象限×值班表×殺出深度×事件倉信心%) =====")
    v1 = simulate_v1(cal, tw_close, ev, close_map, lit, s3w, quad, depth_zone_tw,
                      confidence, dynamic=True, start=start, end=end, label="v1動態配置引擎")

    print("\n產出報告中…")
    # 報告的v0欄位用static_a0(本檔simulate_v1的dynamic=False複製品,含nav/yearly明細供畫圖/逐年表用)
    # 而非SIM.simulate()原函式(該函式不回傳逐日nav/逐年明細)——上面一致性檢查已確認兩者數字相同,
    # 故可放心互換,報告數字仍等同v0原始函式的結果。
    html = build_html(static_a0, v1, static_check, quad, ts, app, depth_zone_tw, depth_tw,
                       depth_otc, confidence, cal_win, start, end)
    open(OUT, "w", encoding="utf-8").write(html)
    print(f"已產出 {OUT}")


if __name__ == "__main__":
    main()
