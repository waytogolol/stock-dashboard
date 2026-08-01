# -*- coding: utf-8 -*-
"""大盤×OTC regime天氣線收官報告(2026-07-31,使用者:「這些研究觀察很重要所以要詳細點 請補」)。

背景: 2026-07-30深夜~07-31晨的regime系列研究(策略×Regime矩陣考卷+晨場追加)判決原本只存在
commit訊息與記憶,無研究HTML;天氣儀v1(dashboard)已用其結論但速查版。本卷=完整收官檔案。

收錄七題(R1~R7)+紀錄項:
  R1 斜率版regime三分(年線位階×斜率)×九策略矩陣 —— 重跑build_strategy_regime_matrix載入器
  R2 排列版(月>季>年)vs斜率版 —— 切換次數/變天時點對比(矩陣考卷07-31晨追加的複現)
  R3 雙軸發現 —— 波動位階(vp10>=80=高波)是趨勢之外的獨立第二軸;九策略×高低波+score4×蹺蹺板
  R4 波動期限結構ts=vol10/vol60接力棒 —— 九策略×三帶(升溫>1.2/中性/退潮<0.8)+跌觸發單窗口穩健性
  R5 兩市排列2×2 —— 權值獨多/櫃買獨多/雙多/雙弱四格×代表策略
  R6 風暴起火點階梯 —— 兩市層(vp10升破80,±15日配對,2006起)+全球層(SPX×加權,2000起)
     +本波04-23vs考卷紀錄05-11錨定考證
  R7 當下讀數速查表(與天氣儀v1口徑對照)
  紀錄項: 多週期日週月排列共振指數層判不加值(行內考卷紀錄,未重跑)

口徑統一: vp10=加權(或該市)日報酬10日std在2006起全樣本的百分位;高波=vp10>=80;
ts=vol10/vol60;蹺蹺板=櫃買/加權指數比值20日變化%(⚠價格相對強弱,非成交量,與P5量縮無關);
排列=MA20>MA60>MA240。策略事件全部重用各考卷正式快取,不重新發明規則。
定位: 盤點層/觀察層(絕對報酬未扣大盤、事件自相關未bootstrap、RRG樣本2018-12起/score4樣本2022起窗窄)。

用法: python 研究腳本/綜合策略/build_regime_weather_report.py  (從根目錄,鐵律)
產出: 研究報告/research_regime_weather.html;事件快取=快取/tmp_regime_weather_events.pkl
"""
import json
import os
import sqlite3
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "研究腳本/綜合策略")
import build_strategy_regime_matrix as M  # noqa: E402  (REG於import時建好)

DB = "capital_flow.db"
EV_CACHE = "快取/tmp_regime_weather_events.pkl"
OUT = "研究報告/research_regime_weather.html"


# ── 基礎序列 ──────────────────────────────────────────────
def load_index():
    con = sqlite3.connect(DB)
    idx = {m: pd.read_sql("SELECT date, close FROM index_daily WHERE market=? ORDER BY date",
                          con, params=(m,), parse_dates=["date"]).set_index("date").close
           for m in ("TAIEX", "TPEx", "SPX")}
    con.close()
    return idx


IDX = load_index()


def vol_series(m):
    r = IDX[m].pct_change() * 100
    v10 = r.rolling(10).std()
    return {"v10": v10, "ts": v10 / r.rolling(60).std(),
            "vp": v10[v10.index >= "2006-01-01"].dropna().rank(pct=True) * 100,
            "vp20": r.rolling(20).std().pipe(lambda s: s[s.index >= "2006-01-01"].dropna().rank(pct=True) * 100),
            "vp60": r.rolling(60).std().pipe(lambda s: s[s.index >= "2006-01-01"].dropna().rank(pct=True) * 100)}


VOL = {m: vol_series(m) for m in ("TAIEX", "TPEx", "SPX")}
APP = (IDX["TPEx"] / IDX["TAIEX"]).dropna()
APP = (APP / APP.shift(20) - 1) * 100          # 蹺蹺板

# 象限三帶切點(2026-07-31統一版,R1/R4驗證): 升溫>VOL_HOT/退潮<VOL_COOL/中性=過渡帶(不強制併入任一邊)。
# ⚠象限切點需與export_html.py保持一致,如需修改兩處都要改。
VOL_HOT, VOL_COOL = 1.2, 0.8


def stack_series(m):
    px = IDX[m]
    ma20, ma60, ma240 = (px.rolling(w).mean() for w in (20, 60, 240))
    return ((ma20 > ma60) & (ma60 > ma240)).astype(int)


STACK = {m: stack_series(m) for m in ("TAIEX", "TPEx")}
SLOPE_BULL = (M.REG == "多頭").astype(int)      # 斜率版多頭 on/off


def load_money():
    con = sqlite3.connect(DB)
    mn = {m: pd.read_sql("SELECT date, money FROM index_daily WHERE market=? AND money>0 ORDER BY date",
                         con, params=(m,), parse_dates=["date"]).set_index("date").money
          for m in ("TAIEX", "TPEx")}
    con.close()
    return mn


# 量能版蹺蹺板(2026-07-31使用者挑戰「蹺蹺板是不是該用成交量」後加開對測):
# 櫃買成交值占比%(20日均)之20日變化pp;占比=經典散戶投機溫度計,與價格版對測誰配當Y軸
MNY = load_money()
SHARE = (MNY["TPEx"] / (MNY["TPEx"] + MNY["TAIEX"])).dropna() * 100
SHARE20 = SHARE.rolling(20).mean()
APP_V = (SHARE20 - SHARE20.shift(20)).dropna()


def at(series, dates):
    """事件日→序列值(ffill到最近交易日)"""
    d = pd.to_datetime(pd.Series(dates))
    return pd.Series(series.reindex(d, method="ffill").values, index=d.index)


def cell(r):
    if len(r) == 0:
        return {"n": 0, "txt": "—"}
    win = (r > 0).mean() * 100
    return {"n": int(len(r)), "win": win, "med": float(np.median(r)) * 100,
            "txt": f"n={len(r)} 勝{win:.0f}% 中位{np.median(r)*100:+.2f}%"}


def fmt_cell(c, hl=False):
    if c["n"] == 0:
        return "<td>—</td>"
    cls = "good" if c["med"] > 0 else "bad"
    mark = " class='hl'" if hl else ""
    return (f"<td{mark}><span class='{cls}'>{c['med']:+.2f}%</span>"
            f"<br><span class='sub'>勝{c['win']:.0f}% n={c['n']}</span></td>")


# ── 策略事件(重用矩陣考卷載入器,首跑後快取) ─────────────────
def load_events():
    if os.path.exists(EV_CACHE):
        print(f"策略事件用快取 {EV_CACHE}")
        return pd.read_pickle(EV_CACHE)
    print("首跑: 載入price_panel(全史逐股,約1-2分)...")
    pv = M.price_panel()
    ev = {
        "①處置V4(k10淨)": M.strat_dispo_v4(pv),
        "②甜蜜格並發≥20籃子(k20)": M.strat_sweetspot(pv),
        "③共振題材(8週)": M.strat_resonance(),
        "④跌觸發注意股(t10)": M.strat_attention_down(),
        "⑤深跌選股climax(k20)": M.strat_bottom(),
        "⑥score4營收清單(ret60)": M.strat_score4(False),
        "⑥b score4超額(excess60)": M.strat_score4(True),
        "⑦RRG H2領先×增漲(2週)": M.strat_rrg("領先", "增漲", "fwd2"),
        "⑧RRG H5落後×增漲(4週)": M.strat_rrg("落後", "增漲", "fwd4"),
        "⑨RRG H6轉強×縮漲(2週)": M.strat_rrg("轉強", "縮漲", "fwd2"),
    }
    pd.to_pickle(ev, EV_CACHE)
    return ev


EV = load_events()
SNAMES = list(EV.keys())


def cond_table(cond_fn, buckets):
    """九策略×條件分桶總表; cond_fn(dates)->labels"""
    rows = []
    for name in SNAMES:
        e = EV[name]
        if len(e) == 0:
            continue
        lab = cond_fn(e["date"])
        row = {"策略": name, "全期": cell(e["ret"])}
        for b in buckets:
            row[b] = cell(e.loc[(lab == b).values, "ret"])
        rows.append(row)
    return rows


def table_html(rows, buckets, note_low_n=8):
    head = "<tr><th>策略</th><th>全期</th>" + "".join(f"<th>{b}</th>" for b in buckets) + "<th>最佳格</th></tr>"
    body = ""
    for r in rows:
        best, bestv = None, None
        for b in buckets:
            c = r[b]
            if c["n"] >= note_low_n and (bestv is None or c["med"] > bestv):
                best, bestv = b, c["med"]
        cells = fmt_cell(r["全期"]) + "".join(fmt_cell(r[b], hl=(b == best)) for b in buckets)
        body += (f"<tr><th>{r['策略']}</th>{cells}"
                 f"<td>{best or '樣本不足'}</td></tr>")
    return f"<table>{head}{body}</table>"


# ══ R1 斜率版regime矩陣 ══════════════════════════════════
def r1():
    def f(dates):
        return at(M.REG, dates)
    rows = cond_table(f, ["多頭", "盤整", "空頭"])
    seg = M.REG.dropna()
    occ = {k: f"{v/len(seg)*100:.0f}%" for k, v in seg.value_counts().items()}
    neg = {}
    for name in SNAMES:
        e = EV[name]
        if len(e):
            yr = e.groupby(e["date"].dt.year)["ret"].median()
            neg[name] = [int(y) for y in yr[yr < 0].index]
    return rows, occ, str(seg.iloc[-1]), neg


# ══ R2 排列版vs斜率版 ═══════════════════════════════════
def flips(b):
    """bool序列→翻轉事件[(date,to_state)];僅取持續>=20交易日的段"""
    b = b.dropna().astype(int)
    ch = b[b.diff() != 0]
    ev, runs = [], list(ch.index) + [b.index[-1]]
    for i, d in enumerate(ch.index):
        end = runs[i + 1]
        dur = b.index.get_loc(end) - b.index.get_loc(d)
        if dur >= 20 or i == len(ch.index) - 1:
            ev.append((d, int(b[d]), dur))
    return ev


def r2():
    out = {}
    for label, s in (("排列版(月>季>年)", STACK["TAIEX"]), ("斜率版(價vs年線×斜率)", SLOPE_BULL)):
        s = s[s.index >= "2000-01-01"]
        raw = int((s.diff() != 0).sum()) - 1
        fl = flips(s)
        out[label] = {"raw": raw, "fl": fl}
    # 變天(多頭→off)配對: 排列版每次off,找±90日內斜率版off,算領先日數
    a_off = [d for d, st, _ in out["排列版(月>季>年)"]["fl"] if st == 0]
    b_off = [d for d, st, _ in out["斜率版(價vs年線×斜率)"]["fl"] if st == 0]
    pairs = []
    for d in a_off:
        cand = [x for x in b_off if abs((x - d).days) <= 90]
        if cand:
            x = min(cand, key=lambda x: abs((x - d).days))
            pairs.append((d, x, (x - d).days))
    lead = [p[2] for p in pairs]
    cur = {"排列_加權": int(STACK["TAIEX"].iloc[-1]), "排列_櫃買": int(STACK["TPEx"].iloc[-1]),
           "斜率": int(SLOPE_BULL.iloc[-1])}
    px = IDX["TAIEX"]
    gap = float((px.rolling(20).mean().iloc[-1] / px.rolling(60).mean().iloc[-1] - 1) * 100)
    return out, pairs, lead, cur, gap


# ══ R3 雙軸: 高低波×九策略 + score4×蹺蹺板 + 高波日trend分佈 ══
def r3():
    vp = VOL["TAIEX"]["vp"]

    def f(dates):
        v = at(vp, dates)
        return v.map(lambda x: "高波(vp10≥80)" if x >= 80 else "低波(<80)")
    rows = cond_table(f, ["高波(vp10≥80)", "低波(<80)"])
    # 高波日的trend三分佈
    hot_days = vp.index[vp >= 80]
    dist = M.REG.reindex(hot_days, method="ffill").value_counts(normalize=True) * 100
    # 跌觸發×regime×波動巢狀(多頭內部加成)
    e = EV["④跌觸發注意股(t10)"]
    rg, v = at(M.REG, e["date"]), at(vp, e["date"])
    nest = {}
    for r_ in ("多頭", "盤整", "空頭"):
        for vv in ("高波", "低波"):
            m = (rg == r_).values & ((v >= 80) if vv == "高波" else (v < 80)).values
            nest[f"{r_}×{vv}"] = cell(e.loc[m, "ret"])
    # score4×蹺蹺板(risk-on/off)
    s4 = EV["⑥score4營收清單(ret60)"]
    ap = at(APP, s4["date"])
    s4x = {"risk-on(小盤強)": cell(s4.loc[(ap > 0).values, "ret"]),
           "risk-off(大盤強)": cell(s4.loc[(ap <= 0).values, "ret"])}
    return rows, dist, nest, s4x


# ══ R4 期限結構三帶 + 跌觸發單窗口穩健 ═══════════════════
def r4():
    ts = VOL["TAIEX"]["ts"]

    def f(dates):
        v = at(ts, dates)
        return v.map(lambda x: "升溫(ts>1.2)" if x > 1.2 else ("退潮(ts<0.8)" if x < 0.8 else "中性(0.8~1.2)"))
    rows = cond_table(f, ["升溫(ts>1.2)", "中性(0.8~1.2)", "退潮(ts<0.8)"])
    # 跌觸發×三個波動窗位階>=80(單窗口穩健)
    e = EV["④跌觸發注意股(t10)"]
    robust = {}
    for w, key in (("vp10", "vp"), ("vp20", "vp20"), ("vp60", "vp60")):
        v = at(VOL["TAIEX"][key], e["date"])
        robust[w] = {"高": cell(e.loc[(v >= 80).values, "ret"]),
                     "低": cell(e.loc[(v < 80).values, "ret"])}
    return rows, robust


# ══ R5 兩市排列2×2 ══════════════════════════════════════
def r5():
    tw, ot = STACK["TAIEX"], STACK["TPEx"]

    def lab_one(t, o):
        return {(1, 1): "雙多", (1, 0): "權值獨多", (0, 1): "櫃買獨多", (0, 0): "雙弱"}[(t, o)]

    def f(dates):
        tv, ov = at(tw, dates), at(ot, dates)
        return pd.Series([lab_one(int(a), int(b)) if pd.notna(a) and pd.notna(b) else None
                          for a, b in zip(tv, ov)], index=tv.index)
    buckets = ["雙多", "權值獨多", "櫃買獨多", "雙弱"]
    rows = cond_table(f, buckets)
    common = tw.index.intersection(ot.index)
    lab_days = pd.Series([lab_one(int(tw[d]), int(ot[d])) for d in common], index=common)
    occ = (lab_days[lab_days.index >= "2006-01-01"].value_counts(normalize=True) * 100).round(1).to_dict()
    return rows, occ, lab_days.iloc[-1]


# ══ R3b 蹺蹺板口徑考卷(價格版vs量能版+波動聯合檢定) ═══════════
def r3b():
    common = APP.dropna().index.intersection(APP_V.index)
    corr = float(pd.concat([APP[common], APP_V[common]], axis=1).corr().iloc[0, 1])
    s4 = EV["⑥score4營收清單(ret60)"]
    att = EV["④跌觸發注意股(t10)"]
    head = {}
    for label, ser in (("價格版", APP), ("量能版", APP_V)):
        a, b = at(ser, s4["date"]), at(ser, att["date"])
        head[label] = {"s4_on": cell(s4.loc[(a > 0).values, "ret"]),
                       "s4_off": cell(s4.loc[(a <= 0).values, "ret"]),
                       "att_on": cell(att.loc[(b > 0).values, "ret"]),
                       "att_off": cell(att.loc[(b <= 0).values, "ret"])}
    # 波動聯合檢定(使用者:「蹺蹺板要跟波動一起看才有意義」→檢定=蹺蹺板在各波動段內是否仍有分離力)
    joint = {}
    for sname, e in (("score4(ret60)", s4), ("跌觸發(t10)", att)):
        ts = at(VOL["TAIEX"]["ts"], e["date"])
        ap = at(APP, e["date"])
        for vs, vmask in (("升溫ts>1.2", (ts > 1.2)), ("退潮ts<0.8", (ts < 0.8))):
            for as_, amask in (("小盤強>0", (ap > 0)), ("大盤強≤0", (ap <= 0))):
                joint[f"{sname}|{vs}×{as_}"] = cell(e.loc[(vmask & amask).values, "ret"])
    yr_p = APP.groupby(APP.index.year).mean().round(1)
    yr_v = APP_V.groupby(APP_V.index.year).mean().round(2)
    now = {"P": round(float(APP.dropna().iloc[-1]), 1), "V": round(float(APP_V.iloc[-1]), 2),
           "share": round(float(SHARE20.dropna().iloc[-1]), 1)}
    return corr, head, joint, yr_p, yr_v, now


# ══ R8 單利權益曲線(天氣開關的目視驗收) ══════════════════
def lin_curve(e, mask=None):
    ev = e if mask is None else e.loc[mask.values]
    ev = ev.sort_values("date")
    g = ev.groupby("date")["ret"].sum() * 100     # 同日多筆各1單位加總
    cum = g.cumsum()
    return {"d": [str(d.date()) for d in cum.index], "v": [round(float(x), 1) for x in cum.values],
            "n": int(len(ev)), "sum": round(float(ev["ret"].sum() * 100))}


def r8():
    att = EV["④跌觸發注意股(t10)"]
    s4 = EV["⑥score4營收清單(ret60)"]
    ts_a = at(VOL["TAIEX"]["ts"], att["date"])
    ts_s = at(VOL["TAIEX"]["ts"], s4["date"])
    cv = {"att_all": lin_curve(att),
          "att_hot": lin_curve(att, ts_a > 1.2),
          "att_cool": lin_curve(att, ts_a < 0.8),
          "s4_all": lin_curve(s4),
          "s4_cool": lin_curve(s4, ts_s < 0.8),
          "s4_hot": lin_curve(s4, ts_s > 1.2)}
    relay = pd.concat([att.loc[(ts_a > 1.2).values], s4.loc[(ts_s < 0.8).values]])
    cv["relay"] = lin_curve(relay)
    # 象限版接力棒(依R3b聯合檢定=值班表忠實版,⚠事後從聯合表選格=描述性非預註冊):
    # 跌觸發只做亂世格(升溫×大盤強)/score4只做小盤強(risk-on)
    ap_a, ap_s = at(APP, att["date"]), at(APP, s4["date"])
    relay_q = pd.concat([att.loc[((ts_a > 1.2) & (ap_a <= 0)).values],
                         s4.loc[(ap_s > 0).values]])
    cv["relay_q"] = lin_curve(relay_q)
    cv["both_all"] = lin_curve(pd.concat([att, s4]))
    return cv


# ══ R9 指數層擇時權益曲線(2026-07-31使用者指定:標的=加權指數,看天氣/均線訊號擇時後的曲線) ══
def r9():
    px = IDX["TAIEX"]
    px = px[px.index >= "2006-01-01"]        # 統一起點=全訊號皆有值(蹺蹺板需櫃買2005起+緩衝)
    ret = px.pct_change().fillna(0)
    ap = APP.reindex(px.index)
    ts = VOL["TAIEX"]["ts"].reindex(px.index)
    stack = STACK["TAIEX"].reindex(px.index).fillna(0).astype(bool)
    slope = SLOPE_BULL.reindex(px.index).fillna(0).astype(bool)
    sigs = {
        "買進持有": pd.Series(True, index=px.index),
        "排列版開關(月>季>年才持有)": stack,
        "斜率版開關(價>年線∧斜率>0才持有)": slope,
        "小盤強才持有(蹺蹺板>0)": (ap > 0),
        "排列∧小盤強": (stack & (ap > 0)),
    }
    out = {}
    for name, sig in sigs.items():
        pos = sig.shift(1).fillna(False).astype(float)   # 收盤判訊號,隔日生效=零前視
        sr = ret * pos
        eq = (1 + sr).cumprod()
        yrs = (eq.index[-1] - eq.index[0]).days / 365.25
        ann = (float(eq.iloc[-1]) ** (1 / yrs) - 1) * 100
        vol_ann = float(sr.std()) * np.sqrt(252) * 100
        out[name] = {
            "eq": eq.iloc[::5],                          # 週抽樣畫圖
            "mult": round(float(eq.iloc[-1]), 2), "ann": round(ann, 1),
            "mdd": round(float((eq / eq.cummax() - 1).min() * 100), 1),
            "expo": round(float(pos.mean()) * 100), "sw": int((pos.diff().abs() > 0).sum()),
            "sharpe": round(ann / vol_ann, 2) if vol_ann else 0}
    # 象限×指數日報酬(訊號同樣shift(1));三帶版(2026-07-31統一,修正舊版ts>=1二元切法bug——
    # 舊版把中性帶(VOL_COOL~VOL_HOT)的日子強制併入升溫或退潮側,與R1/R4驗證的三帶口徑不一致,
    # 會稀釋兩側格子的真實效果;中性帶不強制歸邊,獨立算一個「過渡」桶。
    # ⚠象限切點需與export_html.py保持一致,如需修改兩處都要改。
    hot9, cool9 = ts > VOL_HOT, ts < VOL_COOL
    quad = pd.Series(np.select(
        [hot9 & (ap >= 0), hot9 & (ap < 0), cool9 & (ap >= 0), cool9 & (ap < 0)],
        ["急拉段", "亂世", "題材天堂", "修復觀望"], default="過渡(中性帶)"
    ), index=px.index).shift(1)
    qstat = {}
    for q in ("題材天堂", "急拉段", "修復觀望", "亂世", "過渡(中性帶)"):
        r = ret[(quad == q).values]
        if len(r):
            qstat[q] = {"days": int(len(r)), "occ": round(len(r) / len(ret) * 100),
                        "ann": round(float(r.mean()) * 252 * 100, 1),
                        "vol": round(float(r.std()) * np.sqrt(252) * 100, 1),
                        "win": round(float((r > 0).mean()) * 100)}
    return out, qstat


# ══ R6 起火點階梯 ═══════════════════════════════════════
# 口徑(2026-07-31收官定案,見報告敏感度表): 起火=vp10>80且前quiet=21交易日全程<=80(安靜期,
# 風暴中的再燃不算新火——不設安靜期會把2~5月連續高波算成十幾次事件,稀釋到全是市場平均);
# ±15日曆日配對成波,|gap|<=2日=同步爆;錨定=較早起火日。
# SPX著火旗標=錨定日後20日曆日內SPX vp10(2000起樣本)曾>80——方向性(錨後)是關鍵:
# 錨定前已熄的美股火不算(本波2026-04即此情況,4月上旬SPX的火在櫃買04-23起火前已熄)。
SPX_VP2000 = (IDX["SPX"].pct_change() * 100).rolling(10).std().dropna()
SPX_VP2000 = SPX_VP2000[SPX_VP2000.index >= "2000-01-01"].rank(pct=True) * 100
TW_VP2000 = (IDX["TAIEX"].pct_change() * 100).rolling(10).std().dropna()
TW_VP2000 = TW_VP2000[TW_VP2000.index >= "2000-01-01"].rank(pct=True) * 100


def upcross(vp, quiet=21):
    hot = (vp > 80)
    out = []
    for i, d in enumerate(vp.index):
        if hot.iloc[i] and (i == 0 or not hot.iloc[max(0, i - quiet):i].any()):
            out.append(d)
    return out


def kret(m, d, k):
    s = IDX[m]
    i = s.index.searchsorted(d)
    if i >= len(s) or i + k >= len(s):
        return np.nan
    return float(s.iloc[i + k] / s.iloc[i] - 1) * 100


def spx_fire_after(anchor, days=20):
    win = SPX_VP2000[(SPX_VP2000.index >= anchor) &
                     (SPX_VP2000.index <= anchor + pd.Timedelta(days=days))]
    return bool((win > 80).any())


def ladder(vp1, vp2, n1, n2, quiet=21, win=15, sync=2):
    e1, e2 = upcross(vp1, quiet), upcross(vp2, quiet)
    used2 = set()
    waves = []
    for d in e1:
        cand = [x for x in e2 if abs((x - d).days) <= win and x not in used2]
        if cand:
            x = min(cand, key=lambda x: abs((x - d).days))
            used2.add(x)
            gap = (x - d).days
            cls = "同步爆" if abs(gap) <= sync else (f"{n1}先爆" if gap > 0 else f"{n2}先爆")
            waves.append({"anchor": min(d, x), "d1": d, "d2": x, "cls": cls})
        else:
            waves.append({"anchor": d, "d1": d, "d2": None, "cls": f"{n1}獨爆"})
    for x in e2:
        if x not in used2:
            waves.append({"anchor": x, "d1": None, "d2": x, "cls": f"{n2}獨爆"})
    waves.sort(key=lambda w: w["anchor"])
    for w in waves:
        w["k20"] = kret("TAIEX", w["anchor"], 20)
        w["k60"] = kret("TAIEX", w["anchor"], 60)
        w["k20o"] = kret("TPEx", w["anchor"], 20) if w["anchor"] >= pd.Timestamp("2005-06-01") else np.nan
        w["k60o"] = kret("TPEx", w["anchor"], 60) if w["anchor"] >= pd.Timestamp("2005-06-01") else np.nan
        w["spx"] = spx_fire_after(w["anchor"])
    return waves, len(e1) + len(e2)


def lstat(waves, cls, key="k60", spx=None):
    sel = [w for w in waves if w["cls"] == cls and (spx is None or w["spx"] == spx)]
    v = pd.Series([w[key] for w in sel]).dropna()
    if len(v) == 0:
        return {"n": 0, "txt": "—"}
    return {"n": int(len(v)), "win": (v > 0).mean() * 100, "med": float(v.median()),
            "txt": f"n={len(v)} 勝{(v > 0).mean()*100:.0f}% 中位{v.median():+.2f}%"}


def sensitivity():
    """兩市層參數敏感度: quiet×sync四變體的三主類(誠實聲明用)"""
    out = []
    for quiet in (11, 21):
        for sync in (0, 2):
            w, _ = ladder(VOL["TAIEX"]["vp"], VOL["TPEx"]["vp"], "加權", "櫃買",
                          quiet=quiet, sync=sync)
            row = {"參數": f"quiet={quiet},同步≤{sync}日"}
            for c in ("加權先爆", "櫃買先爆", "同步爆"):
                row[c] = lstat(w, c)["txt"]
            out.append(row)
    return out


def r6():
    tw_otc, n_ev = ladder(VOL["TAIEX"]["vp"], VOL["TPEx"]["vp"], "加權", "櫃買")
    glob, n_ev_g = ladder(TW_VP2000, SPX_VP2000, "台股", "美股")
    # 本波考證: 2026-04~07兩市vp10連續段
    runs = {}
    for m in ("TAIEX", "TPEx"):
        vp = VOL[m]["vp"]
        seg = vp[(vp.index >= "2026-04-01")]
        hot = seg > 80
        blocks, s0 = [], None
        for d, h in hot.items():
            if h and s0 is None:
                s0 = d
            elif not h and s0 is not None:
                blocks.append((s0, prev))
                s0 = None
            prev = d
        if s0 is not None:
            blocks.append((s0, seg.index[-1]))
        runs[m] = blocks
    return tw_otc, n_ev, glob, n_ev_g, runs


# ══ R7 當下讀數 ═════════════════════════════════════════
def r7():
    con = sqlite3.connect(DB)
    dep = {}
    for k, sql in (("上市", "SELECT today_balance v FROM margin_total WHERE name='MarginPurchaseMoney' ORDER BY date DESC LIMIT 245"),
                   ("上櫃", "SELECT money_today v FROM margin_total_otc ORDER BY date DESC LIMIT 245")):
        b = pd.read_sql(sql, con).v
        dep[k] = round(float(b.iloc[0] / b.max() - 1) * 100, 1)
    con.close()
    last = APP.dropna().index[-1]
    return {"asof": str(last.date()),
            "斜率版regime": str(M.REG.iloc[-1]),
            "排列": f"加權{'多' if STACK['TAIEX'].iloc[-1] else '壞'}/櫃買{'多' if STACK['TPEx'].iloc[-1] else '壞'}",
            "vp10": {m: round(float(VOL[m]["vp"].iloc[-1])) for m in ("TAIEX", "TPEx", "SPX")},
            "ts": round(float(VOL["TAIEX"]["ts"].iloc[-1]), 2),
            "蹺蹺板": round(float(APP[last]), 1),
            "深度": dep}


# ══ 主流程+HTML ═════════════════════════════════════════
def main():
    r1_rows, r1_occ, r1_cur, r1_neg = r1()
    r2_out, r2_pairs, r2_lead, r2_cur, r2_gap = r2()
    r3_rows, r3_dist, r3_nest, r3_s4 = r3()
    ap_corr, ap_head, ap_joint, ap_yrp, ap_yrv, ap_now = r3b()
    r4_rows, r4_robust = r4()
    r5_rows, r5_occ, r5_cur = r5()
    w_two, n_ev2, w_glob, n_evg, runs = r6()
    cur = r7()
    curves = r8()
    r9_out, r9_q = r9()

    print("=" * 90)
    print("指數擇時(2006起,隔日生效):")
    for name, o in r9_out.items():
        print(f"  {name}: {o['mult']}x 年化{o['ann']}% MDD{o['mdd']}% 曝險{o['expo']}% 切換{o['sw']}次 粗夏普{o['sharpe']}")
    print("象限×指數日報酬(年化):", {k: f"{v['ann']}%/佔{v['occ']}%" for k, v in r9_q.items()})
    print(f"蹺蹺板口徑對測: corr(價格版,量能版)={ap_corr:+.2f} 當下 P={ap_now['P']}% V={ap_now['V']}pp 占比20日均={ap_now['share']}%")
    for label in ("價格版", "量能版"):
        h = ap_head[label]
        print(f"  {label}: score4 on {h['s4_on']['txt']} / off {h['s4_off']['txt']}"
              f" | 跌觸發 on {h['att_on']['txt']} / off {h['att_off']['txt']}")
    print("聯合檢定(波動段內蹺蹺板是否仍分離):")
    for k, v in ap_joint.items():
        print(f"  {k}: {v['txt']}")
    print("單利曲線Σpp:", {k: (v['sum'], v['n']) for k, v in curves.items()})

    # console對帳
    print("=" * 90)
    e = EV["④跌觸發注意股(t10)"]
    vp = at(VOL["TAIEX"]["vp"], e["date"])
    ts = at(VOL["TAIEX"]["ts"], e["date"])
    print("對帳|跌觸發×高波:", cell(e.loc[(vp >= 80).values, "ret"])["txt"], "(考卷+9.86%/74%)")
    print("對帳|跌觸發×升溫>1.2:", cell(e.loc[(ts > 1.2).values, "ret"])["txt"], "(考卷+9.86%/76%)")
    s4 = EV["⑥score4營收清單(ret60)"]
    ts4 = at(VOL["TAIEX"]["ts"], s4["date"])
    vp4 = at(VOL["TAIEX"]["vp"], s4["date"])
    print("對帳|score4×退潮<0.8:", cell(s4.loc[(ts4 < 0.8).values, "ret"])["txt"], "(考卷+13.81%/76%)")
    print("對帳|score4×低波vp<80:", cell(s4.loc[(vp4 < 80).values, "ret"])["txt"], "(考卷低波+10.58%)")
    print("對帳|score4×低波vp<50:", cell(s4.loc[(vp4 < 50).values, "ret"])["txt"], "(口徑探測)")
    print("對帳|score4×risk-on:", r3_s4["risk-on(小盤強)"]["txt"], "(考卷+14.36%)")
    print("對帳|score4×risk-off:", r3_s4["risk-off(大盤強)"]["txt"], "(考卷+5.49%)")
    for c in ("加權先爆", "櫃買先爆", "同步爆"):
        print(f"對帳|兩市{c}:", lstat(w_two, c)["txt"])
    print("  升級|櫃買先爆×SPX錨後安靜:", lstat(w_two, "櫃買先爆", spx=False)["txt"],
          " ×SPX錨後著火:", lstat(w_two, "櫃買先爆", spx=True)["txt"])
    for c in ("台股先爆", "美股先爆", "台股獨爆"):
        print(f"對帳|全球{c}:", lstat(w_glob, c)["txt"])
    print("對帳|排列版切換:", r2_out["排列版(月>季>年)"]["raw"], "vs 斜率版:", r2_out["斜率版(價vs年線×斜率)"]["raw"],
          "(考卷=排列版少4成)  變天配對領先日數中位:", np.median(r2_lead) if r2_lead else "—")
    print("當下:", cur)

    sens = sensitivity()
    html = build_html(r1_rows, r1_occ, r1_cur, r1_neg, r2_out, r2_pairs, r2_lead, r2_cur, r2_gap,
                      r3_rows, r3_dist, r3_nest, r3_s4, r4_rows, r4_robust,
                      r5_rows, r5_occ, r5_cur, w_two, n_ev2, w_glob, n_evg, runs, cur, sens,
                      (ap_corr, ap_head, ap_joint, ap_yrp, ap_yrv, ap_now), curves, r9_out, r9_q)
    open(OUT, "w", encoding="utf-8").write(html)
    print(f"已產出 {OUT}")


def wave_table(waves, label1, label2):
    rows = ""
    for w in waves:
        cls = w["cls"]
        col = "bad" if cls == f"{label1}先爆" else ("good" if "同步" in cls else "")
        k = lambda x: f"{x:+.1f}%" if pd.notna(x) else "—"
        rows += (f"<tr><td>{w['anchor'].date()}</td><td class='{col}'>{cls}</td>"
                 f"<td>{w['d1'].date() if w['d1'] is not None else '—'}</td>"
                 f"<td>{w['d2'].date() if w['d2'] is not None else '—'}</td>"
                 f"<td>{'🔥' if w['spx'] else '—'}</td>"
                 f"<td>{k(w['k20'])}</td><td>{k(w['k60'])}</td><td>{k(w['k20o'])}</td><td>{k(w['k60o'])}</td></tr>")
    return ("<table><tr><th>波錨定日</th><th>類別</th><th>" + label1 + "起火</th><th>" + label2 +
            "起火</th><th>SPX錨後20日著火</th><th>加權k20</th><th>加權k60</th><th>櫃買k20</th><th>櫃買k60</th></tr>"
            + rows + "</table>")


def build_html(r1_rows, r1_occ, r1_cur, r1_neg, r2_out, r2_pairs, r2_lead, r2_cur, r2_gap,
               r3_rows, r3_dist, r3_nest, r3_s4, r4_rows, r4_robust,
               r5_rows, r5_occ, r5_cur, w_two, n_ev2, w_glob, n_evg, runs, cur, sens,
               appetite, curves, r9_out, r9_q):
    ap_corr, ap_head, ap_joint, ap_yrp, ap_yrv, ap_now = appetite
    css = """
body{background:#1a1a19;color:#fff;font-family:"Noto Sans TC",sans-serif;margin:24px;max-width:1150px}
h1{font-size:20px} h2{font-size:15px;color:#c3c2b7;margin-top:30px;border-bottom:1px solid #333;padding-bottom:4px}
h3{font-size:13.5px;color:#a8a79a;margin:16px 0 4px}
table{border-collapse:collapse;font-size:12.5px;font-variant-numeric:tabular-nums;margin:8px 0}
td,th{border:1px solid #333;padding:4px 9px;text-align:right} th{text-align:left;color:#c3c2b7}
.note{color:#8a8878;font-size:12.5px;line-height:1.8} .good{color:#7ec97e} .bad{color:#e06c5a}
.warn{color:#c3a55a} .hl{background:#2b3a2b} .sub{color:#777;font-size:11px}
.scroll{max-height:420px;overflow-y:auto;display:inline-block}
"""
    # 逐段組裝
    r1_html = table_html(r1_rows, ["多頭", "盤整", "空頭"])
    neg_html = "".join(f"<tr><th>{k}</th><td style='text-align:left'>{v if v else '無'}</td></tr>"
                       for k, v in r1_neg.items())
    r2_fl_html = ""
    for label, o in r2_out.items():
        r2_fl_html += f"<h3>{label}: 原始切換{o['raw']}次(2000起)</h3>"
    pair_rows = "".join(f"<tr><td>{a.date()}</td><td>{b.date()}</td>"
                        f"<td class='{'good' if d >= 0 else 'bad'}'>{d:+d}</td></tr>"
                        for a, b, d in r2_pairs)
    r3_html = table_html(r3_rows, ["高波(vp10≥80)", "低波(<80)"])
    dist_html = "、".join(f"{k} {v:.0f}%" for k, v in r3_dist.items())
    nest_html = "".join(f"<tr><th>{k}</th><td>{v['txt']}</td></tr>" for k, v in r3_nest.items())
    s4_html = "".join(f"<tr><th>{k}</th><td>{v['txt']}</td></tr>" for k, v in r3_s4.items())
    r4_html = table_html(r4_rows, ["升溫(ts>1.2)", "中性(0.8~1.2)", "退潮(ts<0.8)"])
    rb_html = "".join(f"<tr><th>{w}</th><td>{d['高']['txt']}</td><td>{d['低']['txt']}</td></tr>"
                      for w, d in r4_robust.items())
    r5_html = table_html(r5_rows, ["雙多", "權值獨多", "櫃買獨多", "雙弱"])
    occ5 = "、".join(f"{k} {v}%" for k, v in r5_occ.items())

    # R3b 蹺蹺板口徑對測
    aph = "".join(f"<tr><th>{lb}</th><td>{h['s4_on']['txt']}</td><td>{h['s4_off']['txt']}</td>"
                  f"<td>{(h['s4_on']['med'] - h['s4_off']['med']):+.2f}pp</td>"
                  f"<td>{h['att_on']['txt']}</td><td>{h['att_off']['txt']}</td>"
                  f"<td>{(h['att_on']['med'] - h['att_off']['med']):+.2f}pp</td></tr>"
                  for lb, h in ap_head.items())
    apj = "".join(f"<tr><th>{k}</th><td>{v['txt']}</td></tr>" for k, v in ap_joint.items())
    yrs = sorted(set(ap_yrp.index) | set(ap_yrv.index))
    apy = ("<tr><th>年</th>" + "".join(f"<th>{y}</th>" for y in yrs) + "</tr>"
           + "<tr><th>價格版年均%</th>" + "".join(f"<td>{ap_yrp.get(y, float('nan')):+.1f}</td>" for y in yrs) + "</tr>"
           + "<tr><th>量能版年均pp</th>" + "".join(f"<td>{ap_yrv.get(y, float('nan')):+.2f}</td>" for y in yrs) + "</tr>")

    # R8 單利曲線標籤
    cvlab = {k: f"Σ{v['sum']:+,}pp n={v['n']}" for k, v in curves.items()}
    # R9 指數擇時
    r9h = "".join(f"<tr><th>{n}</th><td>{o['mult']}x</td><td>{o['ann']:+.1f}%</td><td>{o['mdd']}%</td>"
                  f"<td>{o['expo']}%</td><td>{o['sw']}</td><td>{o['sharpe']}</td></tr>"
                  for n, o in r9_out.items())
    r9qh = "".join(f"<tr><th>{q}</th><td>{v['occ']}%</td>"
                   f"<td class=\"{'good' if v['ann'] > 0 else 'bad'}\">{v['ann']:+.1f}%</td>"
                   f"<td>{v['vol']}%</td><td>{v['win']}%</td></tr>" for q, v in r9_q.items())

    lad2 = "".join(f"<tr><th>{c}</th><td>{lstat(w_two, c, 'k20')['txt']}</td><td>{lstat(w_two, c)['txt']}</td>"
                   f"<td>{lstat(w_two, c, 'k60o')['txt']}</td></tr>"
                   for c in ("加權先爆", "櫃買先爆", "同步爆", "加權獨爆", "櫃買獨爆"))
    lad2 += ("<tr><th>　└ 櫃買先爆×SPX錨後安靜</th><td>" + lstat(w_two, "櫃買先爆", "k20", spx=False)["txt"] +
             "</td><td class='hl'>" + lstat(w_two, "櫃買先爆", spx=False)["txt"] + "</td><td>" +
             lstat(w_two, "櫃買先爆", "k60o", spx=False)["txt"] + "</td></tr>" +
             "<tr><th>　└ 櫃買先爆×SPX錨後著火</th><td>" + lstat(w_two, "櫃買先爆", "k20", spx=True)["txt"] +
             "</td><td class='hl'>" + lstat(w_two, "櫃買先爆", spx=True)["txt"] + "</td><td>" +
             lstat(w_two, "櫃買先爆", "k60o", spx=True)["txt"] + "</td></tr>")
    ladg = "".join(f"<tr><th>{c}</th><td>{lstat(w_glob, c, 'k20')['txt']}</td><td>{lstat(w_glob, c)['txt']}</td></tr>"
                   for c in ("台股先爆", "美股先爆", "同步爆", "台股獨爆", "美股獨爆"))
    sens_html = "".join("<tr><th>" + r["參數"] + "</th>" +
                        "".join(f"<td>{r[c]}</td>" for c in ("加權先爆", "櫃買先爆", "同步爆")) + "</tr>"
                        for r in sens)
    runs_html = ""
    for m, blocks in runs.items():
        seg = "；".join(f"{s.date()}→{e.date()}" for s, e in blocks)
        runs_html += f"<tr><th>{m}</th><td style='text-align:left'>{seg}</td></tr>"

    cur_html = "".join(f"<tr><th>{k}</th><td style='text-align:left'>{v}</td></tr>" for k, v in [
        ("資料至", cur["asof"]),
        ("斜率版regime", cur["斜率版regime"]),
        ("排列版兩市", cur["排列"] + f"(加權月季差{r2_gap:+.2f}%)"),
        ("vp10位階", f"加權{cur['vp10']['TAIEX']}／櫃買{cur['vp10']['TPEx']}／SPX{cur['vp10']['SPX']}分位"),
        ("期限結構ts", f"{cur['ts']}(>1.2=升溫帶)"),
        ("蹺蹺板20日", f"{cur['蹺蹺板']:+.1f}%"),
        ("兩市排列格", str(r5_cur)),
        ("殺出深度", f"上市{cur['深度']['上市']}%／上櫃{cur['深度']['上櫃']}%"),
    ])

    # 圖資料
    def ser(s, start):
        s = s.dropna()
        s = s[s.index >= start]
        return {"d": [str(d.date()) for d in s.index], "v": [round(float(x), 2) for x in s.values]}
    payload = {
        "vp": {m: ser(VOL[m]["vp"], "2025-07-01") for m in ("TAIEX", "TPEx", "SPX")},
        "ts": ser(VOL["TAIEX"]["ts"], "2018-01-01"),
        "app": ser(APP, "2018-01-01"),
        "px": ser(IDX["TAIEX"], "2000-01-01"),
        "stack": ser(STACK["TAIEX"].astype(float), "2000-01-01"),
        "slope": ser(SLOPE_BULL.astype(float), "2000-01-01"),
        "anchors": [str(w["anchor"].date()) for w in w_two if w["anchor"] >= pd.Timestamp("2025-07-01")],
        "appv": ser(APP_V, "2018-01-01"),
        "cv": {k: {"d": v["d"], "v": v["v"], "lab": cvlab[k]} for k, v in curves.items()},
        "idx": {n: {"d": [str(d.date()) for d in o["eq"].index],
                    "v": [round(float(x), 3) for x in o["eq"].values]} for n, o in r9_out.items()},
    }
    bg = {"paper_bgcolor": "#1a1a19", "plot_bgcolor": "#22221f",
          "font": {"color": "#ddd", "size": 12}, "margin": {"t": 30, "l": 50, "r": 20, "b": 40}}

    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>大盤×OTC regime天氣線收官(2026-07-31)</title>
<script src="plotly.min.js"></script><style>{css}</style></head><body>
<h1>🌦️ 大盤×OTC regime天氣線收官報告——趨勢、波動、大小盤蹺蹺板三軸與策略值班表(2026-07-31)</h1>
<div class="note">本卷收官2026-07-30深夜~07-31晨的regime系列研究(策略×Regime矩陣考卷c4f53f2/a2c6173+晨場行內追加),
原判決只存在commit訊息,本檔=完整重跑複現+逐事件明細。資料=index_daily(加權1999起/櫃買2005起/SPX 1927起)、
九策略事件取各考卷正式快取(不重新發明規則)。<b>定位=盤點層/觀察層,非上板開關</b>。
dashboard「天氣儀v1」是本卷結論的看盤速查版。</div>

<h2>🗣️ 白話導讀</h2>
<div class="note">
<p><b>這條線在問什麼:</b>大盤的「天氣」能不能用少數幾個收盤可判、零前視的數字講清楚,並且天氣不同時,
該派哪支策略值班?答案=三軸:①<b>趨勢軸</b>(均線:年線位階×斜率,或排列月&gt;季&gt;年)、
②<b>波動軸</b>(vol10位階vp10、期限結構vol10/vol60)、③<b>大小盤蹺蹺板軸</b>(櫃買/加權指數比值20日變化)。</p>
<p><b>⚠名詞防呆(2026-07-31使用者提問後補):</b>「蹺蹺板」是櫃買/加權<b>指數比值</b>的相對強弱=資金風險偏好座標,
<b>不是成交量</b>,與P5縮量止跌的「量縮」完全無關——P5是進場扳機(時點),蹺蹺板是天氣座標(狀態)。
框架口訣:<b>深度定倉位、P5定扳機、天氣定值班</b>。</p>
<p><b>核心結論一句話:</b>壞天氣才是這套研究體系的主場——事件策略(跌觸發/甜蜜格/處置)全部在盤整、空頭、
高波動、升溫段突出;營收動能(score4)在低波、退潮、risk-on段突出;<b>多頭好天氣裡沒有任何策略突出,
大盤自己就是最好的策略</b>。兩派是接力棒:風暴中做反轉,風暴後做動能。</p>
</div>

<h2>📋 判決表(2026-07-31收官)</h2>
<table>
<tr><th>題</th><th>判決</th><th>關鍵數字(本次重跑)</th></tr>
<tr><td>R1 斜率版regime×九策略</td><td class="good">✅盤整=事件策略天堂</td><td>甜蜜格/跌觸發/共振皆盤整最突出;
V4處置空頭最肥=逆循環;<b>多頭期九策略無一突出</b>;H5多頭反而負=別用</td></tr>
<tr><td>R2 排列版vs斜率版</td><td class="good">✅排列版切換更少且變天早</td><td>詳下表;當下加權月季差{r2_gap:+.2f}%=死亡交叉倒數,
配置引擎建議採排列版</td></tr>
<tr><td>R3 波動位階雙軸</td><td class="good">✅獨立第二軸</td><td>高波日trend三分天下({dist_html});
亂世派=跌觸發高波才有肉、治世派=score4低波/risk-on才肥</td></tr>
<tr><td>R3b 蹺蹺板口徑對測(07-31追加)</td><td class="good">✅價格版勝出+象限力學驗證</td><td>價格版score4分離+6.72pp
vs 量能版+3.93pp(corr=0.53,量能版=交叉驗證副口徑);<b>聯合檢定=升溫段內蹺蹺板把score4切成+23.91%/87% vs
+0.04%/50%=「蹺蹺板要跟波動一起看」成立</b>;跌觸發的家=亂世格+10.83%/78%;過熱格新發現=score4急拉段+23.91%/87%(n=46觀察)</td></tr>
<tr><td>R8 單利權益曲線(07-31追加)</td><td class="good">✅天氣開關目視兌現</td><td>跌觸發Σ+4,537pp與考卷一字不差;
升溫段52%事件吃61%的肉;score4開關=小盤強非ts;象限版接力棒=值班表忠實版(描述性)</td></tr>
<tr><td>R9 指數擇時權益曲線(07-31使用者指定)</td><td class="warn">🟡均線=風控工具/蹺蹺板≠擇時器</td><td>斜率版開關
夏普0.57/MDD-22.7%(買進持有0.49/-58.3%)=買MDD不買報酬;蹺蹺板擇時大盤0.36=爛+象限對指數無梯度
=<b>天氣儀是策略選擇器不是大盤擇時器</b>,三軸各司其職</td></tr>
<tr><td>R4 期限結構接力棒</td><td class="good">✅兩派主場互斥</td><td>跌觸發升溫段突出而退潮歸零;
score4退潮段最肥;單窗口位階(10/20/60)結論穩健</td></tr>
<tr><td>R5 兩市排列2×2</td><td class="warn">🟡n薄觀察層</td><td>櫃買獨多=題材天堂格、雙弱=事件策略最肥、
權值獨多(當下)=score4最弱格</td></tr>
<tr><td>R6 起火點階梯</td><td class="warn">🟡n小觀察層+升級</td><td>加權先爆=真風暴(n=4全負-18.46%,複現更強);
同步爆=常V底;<b>升級=櫃買先爆本身3正3負混雜,鑰匙=SPX錨後20日著火與否(6/6完美分離)</b>;
全球層考卷數字未穩定複現→降級,SPX資訊改由兩市層×SPX旗標承載;<b>SPX警報線80分位雙重支撐</b></td></tr>
<tr><td>紀錄 多週期排列共振</td><td class="bad">❌指數層不加值</td><td>日週月排列框數不帶方向(上坡1框下坡1框混雜),
多週期概念留題材層(行內考卷紀錄,未重跑)</td></tr>
</table>

<h2>📋 與考卷紀錄逐項對帳(07-30深夜~07-31晨行內判決 vs 本卷系統化複現)</h2>
<table>
<tr><th>考卷紀錄</th><th>本卷複現</th><th>對帳</th></tr>
<tr><td>跌觸發×升溫&gt;1.2 = +9.86%/勝76%</td><td>+9.86%/76%(n=250)</td><td class="good">✓一字不差</td></tr>
<tr><td>score4×退潮&lt;0.8 = +13.81%/勝76%</td><td>+13.81%/76%(n=169)</td><td class="good">✓一字不差</td></tr>
<tr><td>score4×risk-off = +5.49%</td><td>+5.69%/64%</td><td class="good">✓吻合</td></tr>
<tr><td>score4×risk-on = +14.36%</td><td>+12.41%/75%</td><td class="good">✓方向與量級吻合(蹺蹺板窗口微差)</td></tr>
<tr><td>跌觸發×高波 = +9.86%/74%</td><td>+11.39%/78%(vp10≥80)</td><td class="good">✓方向吻合(高波門檻微差)</td></tr>
<tr><td>score4×低波 = +10.58%</td><td>+6.06%(vp&lt;80)</td><td class="warn">🟡方向同、量級差=行內「低波」門檻無從還原,以本卷口徑為準</td></tr>
<tr><td>排列版比斜率版切換少4成</td><td>94次 vs 152次 = 少38%</td><td class="good">✓</td></tr>
<tr><td>排列版變天早</td><td>配對領先中位21日</td><td class="good">✓</td></tr>
<tr><td>加權先爆9次 k60-9.12%/勝33%</td><td>n=4 -18.46%/25%</td><td class="good">✓方向更強(n隨安靜期參數)</td></tr>
<tr><td>同步爆6次 +9.01%</td><td>n=15 +5.99%/67%</td><td class="good">✓方向吻合</td></tr>
<tr><td>櫃買先爆7次 加權k60全勝+3.56%</td><td>n=6 3正3負中位-1.50%</td><td class="bad">✗未複現→<b>升級條件版:×SPX錨後安靜=3/3正、×SPX著火=3/3負</b></td></tr>
<tr><td>全球層 台先美跟n=8 -6.21%/25%等</td><td>分類隨參數擺動</td><td class="bad">✗未穩定複現→降級紀錄,SPX資訊改掛兩市層旗標</td></tr>
<tr><td>兩市層事件77次</td><td>{n_ev2}次(quiet=21)</td><td class="good">✓吻合=行內版應同有安靜期</td></tr>
</table>
<div class="note">對帳原則:複現成功=數字可信可維運;未複現=行內參數無從還原的格子,<b>以本卷寫死口徑為準</b>並降級或升級,
不硬湊考卷數字。天氣儀v1徽章文案已同步改用本卷複現版數字。</div>

<h2>R1 斜率版regime三分×九策略矩陣</h2>
<div class="note">regime=加權收盤vs年線×年線20日斜率(多頭/空頭/盤整,全史占比{r1_occ}),當下=<b>{r1_cur}</b>。
各策略持有期不同(k10~8週),<b>只比同列跨格</b>,絕對值不跨列比。綠格=該策略最佳regime(n≥8才判)。</div>
{r1_html}
<h3>各策略逐年中位&lt;0的年份(死格對帳)</h3>
<table>{neg_html}</table>
<div class="note">口徑三重驗證:V4唯一負年2022/甜蜜格2022死格/跌觸發2026首負——與各正式考卷判決吻合=載入器沒接錯線。
⑧H5「多頭反而負」=07-31新知:當下regime=多頭且H5H6值班中→H5正處自己的弱格。</div>

<h2>R2 排列版(月&gt;季&gt;年)vs 斜率版——換一副更穩的趨勢眼鏡</h2>
{r2_fl_html}
<div class="note">原始切換次數=布林序列翻轉數(2000起,含雜訊翻轉);排列版把「價格在年線上下穿梭」的雜訊
換成「三條均線的相對位置」,天然濾掉大半假翻轉。</div>
<h3>變天配對(排列版多頭→翻空 vs 斜率版最近翻空,±90日,正=排列版先變天)</h3>
<table class="scroll"><tr><th>排列版翻空日</th><th>斜率版翻空日</th><th>排列領先(日)</th></tr>{pair_rows}</table>
<div class="note">領先日數中位={np.median(r2_lead) if r2_lead else '—'}日。當下:排列版加權{'多頭' if r2_cur['排列_加權'] else '翻空'}/
櫃買{'多頭' if r2_cur['排列_櫃買'] else '翻空'},斜率版{'多頭' if r2_cur['斜率'] else '非多頭'};
加權月季差{r2_gap:+.2f}%=<b>死亡交叉倒數讀秒中</b>。</div>
<div id="c4" style="height:420px"></div>

<h2>R3 雙軸發現——波動位階是趨勢之外的獨立第二軸</h2>
<div class="note">高波=事件日加權vp10(2006起全樣本百分位)≥80。高波日的trend分佈={dist_html}=
<b>高波不專屬空頭</b>,是獨立座標,所以值得單獨一軸。</div>
{r3_html}
<h3>跌觸發×regime×波動巢狀(「多頭內部仍有高波加成」的驗證)</h3>
<table>{nest_html}</table>
<h3>score4×蹺蹺板(risk-on/off)</h3>
<table>{s4_html}</table>
<div class="note">兩派分工成形:<b>亂世派</b>(跌觸發)=高波才有肉,低波近零;<b>治世派</b>(score4)=低波+risk-on才肥。
共振介於中間(雙軸中性)。</div>

<h2>R3b 蹺蹺板口徑考卷——價格版 vs 量能版(2026-07-31使用者挑戰後加開)</h2>
<div class="note"><b>問題:</b>「蹺蹺板=資金風險偏好」這個解讀怎麼驗證?會不會該用成交量?<br>
<b>兩個候選口徑:</b>①<b>價格版</b>(現行天氣儀Y軸)=櫃買/加權<b>指數比值</b>20日變化%——量的是中小型「漲得比權值好不好」;
②<b>量能版</b>=櫃買成交值占兩市比%(20日均)的20日變化pp——量的是資金「人在哪裡」。兩版相關係數={ap_corr:+.2f}。<br>
<b>驗證標準(力學派):</b>解讀對不對,看它能不能<b>分離策略報酬</b>——軸有分離力=軸有意義,語意是附贈的。</div>
<h3>正面對決:同一個訊號各切on/off,誰的分離差距(on−off)大</h3>
<table><tr><th>口徑</th><th>score4×小盤強</th><th>score4×大盤強</th><th>差距</th>
<th>跌觸發×小盤強</th><th>跌觸發×大盤強</th><th>差距</th></tr>{aph}</table>
<h3>波動聯合檢定(使用者:「蹺蹺板要跟波動一起看才有意義」——檢定=在同一波動段內,蹺蹺板還有沒有加分離力)</h3>
<table>{apj}</table>
<h3>年度敘事對照(語意檢查:年均值與已知行情敘事是否相符)</h3>
<div class="scroll" style="max-width:100%;overflow-x:auto">{apy}</div>
<div class="note">讀法:2021中小型狂潮年應為正、2022熊市與2024權值AI年應為負——兩版都該通過這個「常識對帳」,
通過才有資格談「風險偏好」語意。當下讀數:價格版{ap_now['P']:+.1f}%/量能版{ap_now['V']:+.2f}pp
(櫃買占比20日均{ap_now['share']}%)。</div>
<div id="c5" style="height:300px"></div>
<h3>R3b判決</h3>
<div class="note">
①<b>價格版勝出,Y軸維持現行口徑</b>:score4分離差價格版+6.72pp vs 量能版+3.93pp(跌觸發兩版同向,
量能版略深但整體價格版全面);corr=+0.53=兩構念相關但不相同,<b>量能版降為交叉驗證副口徑</b>
(兩版方向一致=「風險偏好」構念穩健,不是單一口徑的巧合);<br>
②<b>「蹺蹺板要跟波動一起看」成立(聯合檢定)</b>:升溫段內蹺蹺板把score4切成+23.91%/87% vs +0.04%/50%
(差23.9pp!)、退潮段內+32.08%/85% vs +7.95%/72%——<b>單軸的分離力遠不如聯合,這就是四象限設計的力學依據</b>;<br>
③跌觸發的家=<b>亂世格(升溫×大盤強)+10.83%/78%(n=227)</b>,修復觀望格(退潮×大盤強)連跌觸發都負(-3.05%/38%)
=值班表逐格兌現;<br>
④<b>新發現=「過熱」格(升溫×小盤強)score4 +23.91%/87%(n=46)</b>:升溫不只出現在崩盤,也出現在
V底右側急拉段——過熱格改讀「急拉段」:score4意外肥但波動仍高、含急轉風險(n小觀察層,象限命名維持)。
</div>

<h2>R4 波動期限結構ts=vol10/vol60——兩派的接力棒</h2>
<div class="note">ts&gt;1=短期波動高於長期=風暴升溫中;ts&lt;1=退潮。主場確認線:升溫&gt;1.2/退潮&lt;0.8(天氣儀X軸虛線)。</div>
{r4_html}
<h3>跌觸發×單窗口波動位階穩健性(10/20/60日窗各自≥80 vs &lt;80)</h3>
<table><tr><th>窗</th><th>高位階</th><th>低位階</th></tr>{rb_html}</table>
<div class="note">三個窗口結論同向=「風暴中做反轉」不是挑參數挑出來的。</div>
<div id="c2" style="height:340px"></div>
<div id="c3" style="height:300px"></div>

<h2>R5 兩市排列2×2——權值與中小型各自的天</h2>
<div class="note">格=加權排列×櫃買排列(2006起占比:{occ5}),當下=<b>{r5_cur}</b>。</div>
{r5_html}
<div class="note">⚠n薄警告:「櫃買獨多」占比低、score4樣本2022起,十三戰全勝那格是方向參考不是保證;
雙弱=事件策略最肥與R1「壞天氣主場」互證。</div>

<h2>R6 風暴起火點階梯——誰先著火,決定這場火燒不燒得大</h2>
<div class="note">口徑(收官定案):起火=該市vp10&gt;80分位<b>且前21交易日全程≤80</b>(安靜期——風暴中的再燃不算新火,
不設安靜期會把2~5月連續高波拆成十幾次假事件,統計稀釋到全是市場平均;敏感度見下);兩市層事件共{n_ev2}次
(考卷紀錄77次≈吻合);±15日曆日配對成波,|gap|≤2日=同步爆;報酬從波錨定日(較早起火日)起算。
<b>SPX著火旗標=錨定日後20日曆日內SPX vp10曾&gt;80</b>(方向性是關鍵:錨定前已熄的美股火不算)。</div>
<h3>兩市層(加權×櫃買,2006起)</h3>
<table><tr><th>類別</th><th>加權k20</th><th>加權k60</th><th>櫃買k60</th></tr>{lad2}</table>
<div class="note"><b>本卷最重要的升級發現:「櫃買先爆」本身不是免死金牌</b>——六役3正3負混雜,
分毒/虛驚的鑰匙=<b>SPX有沒有在錨定後20日內跟著著火</b>:SPX安靜→2021本土疫情三役全正(+0.28/+8.70/+8.92%),
SPX著火→2010歐債/2022烏克蘭/2022五月三役全負(-3.27/-9.54/-8.11%)=<b>6/6完美分離</b>(n小觀察層)。
這給了SPX警報線80分位第二個獨立支撐(第一個=全球層考卷紀錄)。</div>
<h3>全球層(台股×SPX,2000起,事件共{n_evg}次)——參數敏感,降級紀錄</h3>
<table><tr><th>類別</th><th>加權k20</th><th>加權k60</th></tr>{ladg}</table>
<div class="note">⚠考卷紀錄的全球層(台先美跟n=8 k60-6.21%勝25%/美先n=9 +4.85%/67%/台獨n=39 +2.10%/67%)
在本卷系統化口徑下<b>未穩定複現</b>(行內版參數無從還原,分類隨安靜期/同步窗擺動)→全球層降級為紀錄,
SPX的資訊改由上面兩市層×SPX旗標承載(6/6分離,口徑固定可維運)。</div>
<h3>階梯讀法(收官版)</h3>
<div class="note"><b>加權先爆</b>(權值先被砍=外資在動)=宏觀系統性真風暴:n=4全負中位-18.46%
(2007-11金融海嘯前緣/2008-05海嘯直前/2024-07 AI大回檔/2025-01)——考卷紀錄-9.12%勝33%,本卷複現方向更強;
<b>同步爆</b>(≤2日,全面恐慌一次殺完)=常為V底:+5.99%/67%(2011-08/2018-02/2020-01/2025-03關稅…);
<b>櫃買先爆</b>=看SPX臉色(上段);<b>獨爆</b>(對方15日內沒跟)=多為局部事件,溫和正。
<b>⚠SPX警報線=SPX vp10升破80分位——本波若SPX著火,劇本從虛驚改判警戒</b>。</div>
<h3>本波考證(2026-04起,含SPX時間線)</h3>
<table>{runs_html}</table>
<div class="note">時間線:SPX 03-31~04-09著火(85分位)→<b>04-09後熄火</b>→櫃買04-23起火(SPX已安靜14日)→
加權04-30跟進→加權05-15後降溫、05-21再燃→07-15/16喘息、07-17再燃(同一場火的尾段,非新火)。
本波=<b>櫃買先爆×SPX錨後安靜</b>=歷史正格劇本;實現對帳:錨04-23起k20+12.07%/k60+17.28%(6月創高)
=虛驚劇本兌現,7月為第二腿(6月中SPX曾4日80~83分位=警報線閃過,觀察)。
考卷紀錄「05-11櫃買先爆→05-22加權跟進」=行內逐事件口徑,錨定日差數週但<b>分類相同</b>;
天氣儀v1(允許≤3日喘息)錨04-23與本段一致。另本卷系統化口徑(quiet=21)把2026整個火季視為
<b>02-09同步爆(SPX安靜)開場的連環火</b>(4月=再燃非新火),該波實現k60+24.0%=同步爆V底格兌現——
三種口徑錨定日不同,<b>實戰結論相同:SPX安靜的台股自燃,歷史偏正格;警報線盯SPX</b>。
6月中SPX曾4日80~83分位(明細表2026-06-15美股獨爆🔥)後7月出現第二腿=警報線作為持續監控的佐證(觀察)。</div>
<h3>參數敏感度(兩市層,加權k60)</h3>
<table><tr><th>參數</th><th>加權先爆</th><th>櫃買先爆</th><th>同步爆</th></tr>{sens_html}</table>
<div class="note">加權先爆的「負」與同步爆的「正」跨參數穩定;櫃買先爆的裸統計隨參數擺動=
必須疊SPX旗標才能用——這正是把它升級成條件版的原因。</div>
<h3>兩市層逐波明細(卷軸)</h3>
<div class="scroll">{wave_table(w_two, '加權', '櫃買')}</div>
<h3>全球層逐波明細(卷軸)</h3>
<div class="scroll">{wave_table(w_glob, '台股', '美股')}</div>
<div id="c1" style="height:360px"></div>

<h2>R8 單利權益曲線——天氣開關的目視驗收(每筆1單位Σpp,不複利)</h2>
<div class="note">口徑=各事件報酬×100後按日累加(同日多筆各1單位),<b>單利非複利</b>(事件重疊無法複利,
比照跌觸發考卷Σpp慣例);跌觸發持有10日/score4持有60日,<b>兩策略Σpp不能互比</b>,只看「同策略開關前後」。
接力棒=升溫段(ts&gt;1.2)只做跌觸發+退潮段(ts&lt;0.8)只做score4的合併。</div>
<div id="c6" style="height:340px"></div>
<div id="c7" style="height:340px"></div>
<div id="c8" style="height:340px"></div>
<div class="note">讀法(Σpp/事件數):
①跌觸發:全開{curves['att_all']['sum']:+,}pp/{curves['att_all']['n']}筆
(<b>Σ+4,537pp與跌觸發考卷紀錄一字不差=管線自驗</b>),升溫段{curves['att_hot']['sum']:+,}pp/{curves['att_hot']['n']}筆
={curves['att_hot']['n']/curves['att_all']['n']*100:.0f}%的事件吃走{curves['att_hot']['sum']/curves['att_all']['sum']*100:.0f}%的肉,
退潮段近乎躺平——風暴中做反轉;<br>
②score4:全開{curves['s4_all']['sum']:+,}pp/{curves['s4_all']['n']}筆,退潮段最肥但中性段仍有肉=
<b>ts單軸對score4切不乾淨,score4真正的開關是小盤強(risk-on),見R3b聯合檢定</b>;<br>
③接力棒:ts版{curves['relay']['sum']:+,}pp/{curves['relay']['n']}筆 vs
象限版{curves['relay_q']['sum']:+,}pp/{curves['relay_q']['n']}筆 vs 全開{curves['both_all']['sum']:+,}pp/{curves['both_all']['n']}筆
——象限版(值班表忠實版)以{curves['relay_q']['n']/curves['both_all']['n']*100:.0f}%的事件數留住
{curves['relay_q']['sum']/curves['both_all']['sum']*100:.0f}%的Σ;⚠象限版=事後從聯合表選格,描述性非預註冊。<br>
單利曲線斜率=事件密度非資金曲線;兩策略持有期不同(10日vs60日),Σ不能互比。</div>

<h2>R9 指數層擇時權益曲線——標的=加權指數,天氣/均線訊號直接擇時(2026-07-31使用者指定加開)</h2>
<div class="note">口徑:2006起(全訊號皆有值的統一起點),收盤判訊號<b>隔日生效=零前視</b>,空手=現金(不計利息),
無交易成本(指數不可直接交易,期貨可近似;切換次數見表,排列版26年不到百次=成本敏感度低)。
<b>問題意識:天氣/均線訊號拿來擇時大盤本身,能不能贏買進持有?</b></div>
<table><tr><th>版本</th><th>倍數(2006起)</th><th>年化</th><th>MDD</th><th>曝險</th><th>切換次數</th><th>粗夏普</th></tr>{r9h}</table>
<h3>四象限×指數日報酬(象限訊號同樣隔日生效)</h3>
<table><tr><th>象限</th><th>日數占比</th><th>年化報酬</th><th>年化波動</th><th>日勝率</th></tr>{r9qh}</table>
<div id="c9" style="height:420px"></div>
<div class="note" id="r9verdict"><b>判讀(跑完定稿):</b><br>
①<b>均線開關買的是MDD不是報酬</b>:兩版倍數都輸買進持有(6.18x),但MDD從-58.3%砍到-29.4%(排列)/-22.7%(斜率),
粗夏普持平~微升——趨勢濾網的經典結論,擇時是風險控制工具非報酬增強器;<br>
②<b>指數擇時這件事上斜率版反而略優</b>(夏普0.57/MDD-22.7% vs 排列版0.50/-29.4%):R2說排列版「切換少、變天早」
是指<b>當策略天氣標籤</b>用(少假翻轉),但直接開關大盤時,斜率版多留12pp曝險反而效率高——兩個工作用兩副眼鏡,不矛盾;<br>
③<b>蹺蹺板拿去擇時大盤=爛</b>(0.36,MDD-40.9%,切換450次),象限×指數日報酬也無梯度
(修復觀望年化反而最高13.7%——「修復」兩字本來就是漲回來的日子)=<b>鐵證:天氣儀是「策略選擇器」不是「大盤擇時器」</b>,
蹺蹺板的資訊全在「該做題材還是做事件」(R3b分離23.9pp),不在大盤方向——天氣定值班、趨勢管方向、深度管總水位,三軸各司其職;<br>
⚠此節=描述性回測(規則來自本卷研究,非預註冊;無成本無滑價;空手期現金零報酬),定位=研究曲線非交易系統;
個股/事件策略(R8)才是體系的主戰場,指數擇時是天氣儀的體檢表。</div>

<h2>R7 當下讀數速查(與天氣儀v1對照)</h2>
<table>{cur_html}</table>
<div class="note">與dashboard天氣儀v1同源同口徑;天氣儀每日更新,本表=收官日快照。</div>

<h2>已知限制(誠實聲明)</h2>
<div class="note">
①絕對報酬未扣大盤:空頭格的正中位含大量超額成分,「空頭最肥」講的是相對突出不是絕對好賺;<br>
②事件自相關未bootstrap:恐慌事件成簇,勝率的有效n低於表列n,起火點階梯尤其(n=個位數=觀察層);<br>
③樣本窗窄:RRG系2018-12起、score4面板2022起→「空頭格」主要吃2022一年,一個熊市撐起的格子;<br>
④排列2×2「櫃買獨多」格占比低且與score4樣本重疊窄,十三戰全勝是方向參考;<br>
⑤本卷全部=盤點層/觀察層,不改任何已上板規則的開關;策略絕對值不跨列比(持有期不同);<br>
⑥起火點階梯全域參數敏感(安靜期/同步窗/錨定容忍都會動到n與錨定日):跨參數穩定的只有
「加權先爆=負」「同步爆=正」兩件事;櫃買先爆必須疊SPX旗標;全球層已降級——<b>階梯全體=觀察層,不下單</b>;<br>
⑦多週期共振「不加值」判決來自行內考卷未重跑,列為紀錄項。
</div>
<div class="note">維運:python 研究腳本/綜合策略/build_regime_weather_report.py(事件快取
快取/tmp_regime_weather_events.pkl,策略事件更新後刪快取重跑)。姊妹檔:研究報告/research_heat_flow.html
(題材層RRG)、research_margin_flush.html(殺出深度)、dashboard天氣儀v1(看盤速查)。</div>

<script>
const D={json.dumps(payload, ensure_ascii=False)};
const BG={json.dumps(bg)};
Plotly.newPlot('c1', [
 {{x:D.vp.TAIEX.d,y:D.vp.TAIEX.v,name:'加權vp10',line:{{width:2}}}},
 {{x:D.vp.TPEx.d,y:D.vp.TPEx.v,name:'櫃買vp10',line:{{width:2}}}},
 {{x:D.vp.SPX.d,y:D.vp.SPX.v,name:'SPX vp10',line:{{dash:'dot'}}}},
], Object.assign({{title:'近一年兩市+SPX波動位階vp10(80=起火線,▲=波錨定日)',
 shapes:[{{type:'line',y0:80,y1:80,xref:'paper',x0:0,x1:1,line:{{color:'#e06c5a',dash:'dash',width:1}}}}]
   .concat(D.anchors.map(a=>({{type:'line',x0:a,x1:a,yref:'paper',y0:0,y1:1,line:{{color:'#c3a55a',width:1,dash:'dot'}}}}))),
}},BG));
Plotly.newPlot('c2', [{{x:D.ts.d,y:D.ts.v,name:'ts=vol10/vol60'}}],
 Object.assign({{title:'波動期限結構(2018起):>1.2升溫=亂世派主場,<0.8退潮=治世派主場',
 shapes:[[1,'#888'],[1.2,'#e06c5a'],[0.8,'#7ec97e']].map(s=>({{type:'line',y0:s[0],y1:s[0],xref:'paper',x0:0,x1:1,line:{{color:s[1],dash:'dash',width:1}}}}))}},BG));
Plotly.newPlot('c3', [{{x:D.app.d,y:D.app.v,name:'蹺蹺板',fill:'tozeroy'}}],
 Object.assign({{title:'蹺蹺板=櫃買/加權比值20日變化%(2018起):正=敢買中小型'}} ,BG));
Plotly.newPlot('c5', [
 {{x:D.app.d,y:D.app.v,name:'價格版(%)',line:{{width:1.5}}}},
 {{x:D.appv.d,y:D.appv.v,name:'量能版(pp)',yaxis:'y2',line:{{width:1.5,dash:'dot'}}}},
], Object.assign({{title:'蹺蹺板兩口徑對照(2018起):價格版=左軸% / 量能版=右軸pp',
 yaxis2:{{overlaying:'y',side:'right',showgrid:false}}}},BG));
const CVL = (k,nm,st)=>({{x:D.cv[k].d,y:D.cv[k].v,name:nm+'｜'+D.cv[k].lab,line:st||{{}}}});
Plotly.newPlot('c6', [CVL('att_all','跌觸發全事件'),CVL('att_hot','×升溫ts>1.2',{{width:2.5,color:'#e06c5a'}}),
 CVL('att_cool','×退潮ts<0.8',{{dash:'dot',color:'#5dade2'}})],
 Object.assign({{title:'跌觸發(t10)單利累積pp:升溫段吃肉,退潮段躺平'}},BG));
Plotly.newPlot('c7', [CVL('s4_all','score4全事件'),CVL('s4_cool','×退潮ts<0.8',{{width:2.5,color:'#7ec97e'}}),
 CVL('s4_hot','×升溫ts>1.2',{{dash:'dot',color:'#c3a55a'}})],
 Object.assign({{title:'score4(ret60)單利累積pp:退潮段吃肉'}},BG));
Plotly.newPlot('c8', [CVL('both_all','兩策略全開'),CVL('relay','ts版接力棒(升溫跌觸發+退潮score4)',{{dash:'dot',color:'#c3a55a'}}),
 CVL('relay_q','象限版接力棒(亂世跌觸發+risk-on score4)',{{width:2.5,color:'#ffd97a'}})],
 Object.assign({{title:'接力棒 vs 全開(⚠持有期混合,概念示意;象限版=值班表忠實版)'}},BG));
Plotly.newPlot('c9', Object.keys(D.idx).map((n,i)=>({{x:D.idx[n].d,y:D.idx[n].v,name:n,
 line:{{width:i===0?1.2:1.8,dash:i===0?'dot':'solid'}}}})),
 Object.assign({{title:'指數層擇時權益曲線(加權,2006起,起點1,log,訊號隔日生效,無成本)',yaxis:{{type:'log'}}}},BG));
Plotly.newPlot('c4', [
 {{x:D.px.d,y:D.px.v,name:'加權(log)',yaxis:'y',line:{{color:'#8ab4f8',width:1}}}},
 {{x:D.stack.d,y:D.stack.v.map(v=>v?1.06:null),name:'排列版多頭',yaxis:'y2',mode:'markers',marker:{{size:3,color:'#7ec97e'}}}},
 {{x:D.slope.d,y:D.slope.v.map(v=>v?1.0:null),name:'斜率版多頭',yaxis:'y2',mode:'markers',marker:{{size:3,color:'#c3a55a'}}}},
], Object.assign({{title:'排列版vs斜率版多頭段對比(2000起,下方兩條帶=各自判定多頭的日子)',
 yaxis:{{type:'log',domain:[0.25,1]}},yaxis2:{{domain:[0,0.18],range:[0.9,1.15],showticklabels:false}}}},BG));
</script></body></html>"""


if __name__ == "__main__":
    main()
