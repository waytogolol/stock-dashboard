# -*- coding: utf-8 -*-
"""好壞波動分解延伸卷二(2026-08-01,接續build_vol_updown_explore.py誠實限制②③兩條待辦)。

背景: 好壞波動分解探索卷一(research_vol_updown_explore.html)已驗證bshare20(壞波動占比)
不是既有波動指標的重複資訊(corr<0.5),且對「跌觸發注意股」這支反轉型策略有真訊號(高bshare組
report+12.08%/勝82% vs低組+0.26%/勝51%,10/20/60三窗口穩健),但①只測了報酬預測未測風險/回撤、
②只外部驗證score4一支動能策略(結果薄弱)、③未做bootstrap。本卷補三個坑:

①風險/回撤角度(本卷新增維度): 對同一批既有事件,把目標變數從「未來k日報酬」換成
  「進場後k日內最大回撤mdd(從進場價起算路徑最低點%)」與「進場後k日報酬下檔半標準差semidev
  (MAR=0%,只算負報酬日,pct單位)」,k=20為主(對齊bshare20主窗口),看高低bshare20組在風險維度
  有無分離力,方向不預設。
②外部驗證擴大(本卷新增策略): 沿用build_strategy_regime_matrix.py既有正式函式strat_sweetspot
  (甜蜜格並發≥20籃子)、strat_dispo_v4(處置V4第3日進場),不重新設計規則,跟原本④跌觸發、⑥score4
  一起湊成四支反轉/動能策略做交叉驗證。
③統計嚴謹度升級: 全部改用build_dtlend_report.py既有boot_diff_ci(月群重抽樣2000次,95%CI,
  「排0」=顯著)取代卷一的裸中位數對照,避免重新發明bootstrap函式(卷一誠實限制①的坑)。

bshare20計算邏輯100%複用build_vol_updown_explore.py的vol_updown()/VU字典,不重新算好壞波動分解。
事件源=各策略正式快取,只多取一個既有已算出的code欄位(逐字複製既有篩選門檻,非重新設計規則)。

用法: python 研究腳本/綜合策略/build_vol_updown_explore_v2.py (從根目錄執行,鐵律)
產出: 研究報告/research_vol_updown_explore_v2.html
"""
import sqlite3
import sys
import time

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "研究腳本/綜合策略")
import build_vol_updown_explore as V1  # noqa: E402  bshare20等既有計算,直接複用不重算
import build_strategy_regime_matrix as M  # noqa: E402  既有策略事件正式函式,不重新設計規則

sys.path.insert(0, "研究腳本/當沖借券")
import build_dtlend_report as R  # noqa: E402  boot_diff_ci月群重抽樣工具,直接複用避免key不一致bug

DB = "capital_flow.db"
OUT = "研究報告/research_vol_updown_explore_v2.html"
VU = V1.VU                       # {"TAIEX":..., "TPEx":...} 好壞波動字典,卷一算好的,直接沿用
RISK_K = 20                      # 主風險窗口(對齊bshare20主窗口)


# ── 事件建構(retain code,逐字複製既有正式函式的篩選門檻) ──────────────
def events_with_code(pv):
    """四支策略的(code,date)事件表——與M.strat_*系列用同一套門檻,只多留code欄位供算風險路徑用。"""
    out = {}
    a = pd.read_pickle("快取/tmp_attention_full_panel.pkl")
    e = a[(a["down"] == 1) & (a["ep_first"] == 1)].dropna(subset=["t10"])
    out["④跌觸發注意股"] = e[["code", "date"]].copy()

    p = pd.read_pickle("快取/tmp_theme_momentum_v2_panel.pkl")
    e2 = p[(p["score"] == 4)].dropna(subset=["ret60", "entry_day"])
    out["⑥score4營收清單"] = e2[["code", "entry_day"]].rename(columns={"entry_day": "date"}).copy()

    ev = pd.read_pickle("快取/tmp_panic_sweetspot_events.pkl")
    q = ev[(ev["dd"] <= -6) & (ev["dd"] > -9) & (ev["pull"] >= 20) & (ev["rr"] > 1.2) & (ev["tv"] > 1)]
    cnt = q.groupby("d0").size()
    days = cnt[cnt >= 20].index
    out["甜蜜格並發≥20籃子"] = q[q["d0"].isin(days)][["code", "d0"]].rename(columns={"d0": "date"}).copy()

    con = sqlite3.connect(DB)
    d = pd.read_sql("SELECT code, start_date, end_date FROM disposition", con)
    con.close()
    d["start_date"] = pd.to_datetime(d["start_date"])
    d["end_date"] = pd.to_datetime(d["end_date"])
    d = d.dropna()
    rows = []
    for code, s0, s1 in d.itertuples(index=False):
        if code not in pv["close"].columns:
            continue
        c = pv["close"][code].dropna(); c = c[c > 0]
        o = pv["open"][code]; m = pv["money"][code]
        win = c.loc[s0:s1]
        if not (6 <= len(win) <= 25) or len(win) < 3:
            continue
        entry_d = win.index[2]
        tv3 = m.loc[:entry_d].dropna().tail(3).mean() / 1e8
        if not tv3 >= 0.3:
            continue
        after = c.loc[c.index > s1]
        if len(after) == 0:
            continue
        exit_d = after.index[0]
        if pd.isna(o.get(exit_d)) or o.get(exit_d, 0) <= 0:
            continue
        rows.append({"code": code, "date": entry_d})
    out["處置V4(第3日進場)"] = pd.DataFrame(rows)
    return out


# ── 風險/回撤目標變數 ──────────────────────────────────────
_PRICE_CACHE = {}


def _series(pv, code):
    if code not in _PRICE_CACHE:
        s = pv["close"].get(code)
        if s is None:
            _PRICE_CACHE[code] = None
        else:
            s = s.dropna()
            _PRICE_CACHE[code] = s[s > 0]
    return _PRICE_CACHE[code]


def fwd_risk(pv, code, entry_date, k):
    """(mdd, semidev): 從entry_date收盤起算(錨點邏輯同M.fwd_ret),往後k個交易日路徑的
    最大回撤%(相對進場價路徑最低點,<=0)+ 逐日報酬下檔半標準差(MAR=0%,只算負報酬日平方均方根,pct)。"""
    s = _series(pv, code)
    if s is None:
        return np.nan, np.nan
    i = s.index.searchsorted(pd.Timestamp(entry_date))
    if i >= len(s) or (s.index[i] - pd.Timestamp(entry_date)).days > 5 or i + k >= len(s):
        return np.nan, np.nan
    path = s.iloc[i:i + k + 1]
    cum = path / path.iloc[0] - 1
    mdd = float(cum.iloc[1:].min() * 100)
    daily = path.pct_change().dropna() * 100
    downside = daily.where(daily < 0, 0.0)
    semidev = float(np.sqrt((downside ** 2).mean()))
    return mdd, semidev


def add_risk(e, pv, k=RISK_K):
    mdd, semi = [], []
    for code, d in zip(e["code"], e["date"]):
        m_, s_ = fwd_risk(pv, code, d, k)
        mdd.append(m_); semi.append(s_)
    e = e.copy()
    e["mdd"], e["semidev"] = mdd, semi
    return e.dropna(subset=["mdd", "semidev"])


def add_risk_basket(e, pv, k=RISK_K):
    """甜蜜格籃子=同日多檔code,個股風險算完後同日取平均(與M.strat_sweetspot對ret的聚合方式一致)。"""
    e2 = add_risk(e, pv, k)
    if len(e2) == 0:
        return e2
    return e2.groupby("date", as_index=False).agg(mdd=("mdd", "mean"), semidev=("semidev", "mean"))


# ── 分桶+bootstrap ────────────────────────────────────────
def hi_lo_split_df(e, bs_series, q=(0.33, 0.66)):
    bs = V1.at(bs_series, e["date"])
    lo_th, hi_th = bs.quantile(q[0]), bs.quantile(q[1])
    return e.loc[(bs >= hi_th).values], e.loc[(bs <= lo_th).values]


def risk_cell(x):
    """風險目標變數已是%單位(非fraction),不可再乘100——與V1.cell()吃fraction的口徑不同,分開處理。"""
    x = pd.Series(x).dropna()
    if len(x) == 0:
        return {"n": 0, "med": None, "mean": None, "p10": None, "txt": "—"}
    return {"n": int(len(x)), "med": float(x.median()), "mean": float(x.mean()),
            "p10": float(np.quantile(x, 0.1)),
            "txt": f"n={len(x)} 中位{x.median():+.2f} 均{x.mean():+.2f} p10={np.quantile(x,.1):+.2f}"}


def ret_cell(x):
    """報酬目標變數是fraction,沿用V1.cell()口徑(內部*100),確保pp量級不重複也不遺漏。"""
    return V1.cell(x)


def boot_ret(hi, lo):
    """報酬(fraction)→bootstrap前先*100轉pp,避免量級誤讀。"""
    return R.boot_diff_ci(hi["ret"].values * 100, hi["date"], lo["ret"].values * 100, lo["date"])


def boot_risk(hi, lo, col):
    """風險目標已是%單位,直接丟進bootstrap,不再乘100。"""
    return R.boot_diff_ci(hi[col].values, hi["date"], lo[col].values, lo["date"])


def window_robust(e, value_col, cellfn, scale=1.0):
    rows = []
    for w in (10, 20, 60):
        hi, lo = hi_lo_split_df(e, VU["TAIEX"][f"bshare{w}"])
        rows.append({"窗": w, "高": cellfn(hi[value_col] * scale), "低": cellfn(lo[value_col] * scale)})
    return rows


# ── 主流程 ────────────────────────────────────────────────
def main():
    t0 = time.time()
    print("[準備] 載入全宇宙價格面板(fm_daily_price pivot,約4百萬列)…")
    pv = M.price_panel()
    print(f"  完成 {time.time()-t0:.0f}s,codes={len(pv['close'].columns)}")

    print("[事件] 建構四策略(code,date)事件表(風險用)…")
    code_ev = events_with_code(pv)
    for name, e in code_ev.items():
        print(f"  {name}: {len(e)}筆(未算風險前)")

    print("[事件] 建構四策略正式(date,ret)事件表(報酬外部驗證用,重用M.strat_*)…")
    return_ev = {
        "④跌觸發注意股": M.strat_attention_down(),
        "⑥score4營收清單": M.strat_score4(False),
        "甜蜜格並發≥20籃子": M.strat_sweetspot(pv),
        "處置V4(第3日進場)": M.strat_dispo_v4(pv),
    }
    for name, e in return_ev.items():
        print(f"  {name}: {len(e)}筆(ret) vs code_ev {len(code_ev[name])}筆(risk前)")

    print(f"[風險] 計算k={RISK_K}日forward mdd/semidev…")
    risk_ev = {}
    for name, e in code_ev.items():
        if len(e) == 0:
            risk_ev[name] = e
            continue
        risk_ev[name] = add_risk_basket(e, pv) if "甜蜜格" in name else add_risk(e, pv)
        print(f"  {name}: {len(risk_ev[name])}筆(算完風險後,已濾NaN)")
    print(f"  風險計算耗時累計 {time.time()-t0:.0f}s")

    # ①報酬維度(外部驗證,四策略統一補bootstrap)
    ret_results = {}
    for name, e in return_ev.items():
        if len(e) < 10:
            ret_results[name] = None
            continue
        hi, lo = hi_lo_split_df(e, VU["TAIEX"]["bshare20"])
        ret_results[name] = {
            "full": ret_cell(e["ret"]), "hi": ret_cell(hi["ret"]), "lo": ret_cell(lo["ret"]),
            "boot": boot_ret(hi, lo), "windows": window_robust(e, "ret", ret_cell),
        }

    # ②風險維度(mdd/semidev,四策略)
    risk_results = {}
    for name, e in risk_ev.items():
        if len(e) < 10:
            risk_results[name] = None
            continue
        hi, lo = hi_lo_split_df(e, VU["TAIEX"]["bshare20"])
        risk_results[name] = {
            "n": len(e),
            "mdd": {"full": risk_cell(e["mdd"]), "hi": risk_cell(hi["mdd"]), "lo": risk_cell(lo["mdd"]),
                    "boot": boot_risk(hi, lo, "mdd"), "windows": window_robust(e, "mdd", risk_cell)},
            "semidev": {"full": risk_cell(e["semidev"]), "hi": risk_cell(hi["semidev"]),
                        "lo": risk_cell(lo["semidev"]), "boot": boot_risk(hi, lo, "semidev"),
                        "windows": window_robust(e, "semidev", risk_cell)},
        }

    print("=" * 90)
    print("①報酬維度(bootstrap升級版,四策略):")
    for name, r in ret_results.items():
        if r is None:
            print(f"  [{name}] n不足,略"); continue
        print(f"  [{name}] 全期{r['full']['txt']} | 高{r['hi']['txt']} | 低{r['lo']['txt']} | "
              f"bootstrap={fmt_boot(r['boot'])}")
    print("②風險維度(mdd/semidev,四策略):")
    for name, r in risk_results.items():
        if r is None:
            print(f"  [{name}] n不足,略"); continue
        print(f"  [{name}] n={r['n']}")
        print(f"    mdd{RISK_K}: 高{r['mdd']['hi']['txt']} | 低{r['mdd']['lo']['txt']} | "
              f"bootstrap={fmt_boot(r['mdd']['boot'])}")
        print(f"    semidev{RISK_K}: 高{r['semidev']['hi']['txt']} | 低{r['semidev']['lo']['txt']} | "
              f"bootstrap={fmt_boot(r['semidev']['boot'])}")
    print("=" * 90)
    print(f"總耗時 {time.time()-t0:.0f}s")

    html = build_html(ret_results, risk_results)
    open(OUT, "w", encoding="utf-8").write(html)
    print(f"已產出 {OUT}")


def fmt_boot(b):
    if b is None:
        return "n太小(<15/月群不足)"
    sig = "✓排0顯著" if b["sig"] else "含0不顯著"
    return f"{b['diff']:+.2f} 95%CI[{b['lo']:+.2f},{b['hi']:+.2f}] {sig}(na={b['na']},nb={b['nb']})"


# ── HTML ──────────────────────────────────────────────────
def fmt_ret_td(c):
    if c["n"] == 0:
        return "<td>—</td>"
    cls = "good" if (c["med"] is not None and c["med"] > 0) else "bad"
    return f"<td><span class='{cls}'>{c['med']:+.2f}%</span><br><span class='sub'>勝{c['win']:.0f}% n={c['n']}</span></td>"


def fmt_risk_pair(hi_c, lo_c, worse_is_negative=True):
    """風險欄位(mdd恆<=0、semidev恆>=0)沒有天然的0軸可判好壞,改用高/低兩組『相對比較』上色
    ——比哪一組風險比較大,不是比正負號(絕對門檻上色對這兩個指標永遠同一色,是誤導)。"""
    def render(c, cls):
        if c["n"] == 0 or c["med"] is None:
            return "<td>—</td>"
        return f"<td><span class='{cls}'>{c['med']:+.2f}</span><br><span class='sub'>p10={c['p10']:+.2f} n={c['n']}</span></td>"
    if hi_c["n"] == 0 or lo_c["n"] == 0 or hi_c["med"] is None or lo_c["med"] is None or hi_c["med"] == lo_c["med"]:
        return render(hi_c, ""), render(lo_c, "")
    hi_less_risky = (hi_c["med"] > lo_c["med"]) if worse_is_negative else (hi_c["med"] < lo_c["med"])
    return (render(hi_c, "good" if hi_less_risky else "bad"),
            render(lo_c, "bad" if hi_less_risky else "good"))


def build_html(ret_results, risk_results):
    css = """
body{background:#1a1a19;color:#fff;font-family:"Noto Sans TC",sans-serif;margin:24px;max-width:1150px}
h1{font-size:20px} h2{font-size:15px;color:#c3c2b7;margin-top:30px;border-bottom:1px solid #333;padding-bottom:4px}
h3{font-size:13.5px;color:#a8a79a;margin:16px 0 4px}
table{border-collapse:collapse;font-size:12.5px;font-variant-numeric:tabular-nums;margin:8px 0}
td,th{border:1px solid #333;padding:4px 9px;text-align:right} th{text-align:left;color:#c3c2b7}
.note{color:#8a8878;font-size:12.5px;line-height:1.8} .good{color:#7ec97e} .bad{color:#e06c5a}
.warn{color:#c3a55a} .hl{background:#2b3a2b} .sub{color:#777;font-size:11px}
"""
    # ①報酬維度表
    ret_rows = ""
    for name, r in ret_results.items():
        if r is None:
            ret_rows += f"<tr><th>{name}</th><td colspan=4>n不足,無法檢定</td></tr>"
            continue
        ret_rows += (f"<tr><th>{name}</th><td>{r['full']['txt']}</td>{fmt_ret_td(r['hi'])}"
                     f"{fmt_ret_td(r['lo'])}<td>{fmt_boot(r['boot'])}</td></tr>")
    ret_win_blocks = ""
    for name, r in ret_results.items():
        if r is None:
            continue
        w_html = "".join(f"<tr><th>{w['窗']}日窗</th>{fmt_ret_td(w['高'])}{fmt_ret_td(w['低'])}</tr>"
                         for w in r["windows"])
        ret_win_blocks += (f"<h3>{name}</h3><table><tr><th>bshare窗</th><th>高</th><th>低</th></tr>"
                          f"{w_html}</table>")

    # ②風險維度表
    risk_rows = ""
    for name, r in risk_results.items():
        if r is None:
            risk_rows += f"<tr><th>{name}</th><td colspan=6>n不足,無法檢定</td></tr>"
            continue
        m, s = r["mdd"], r["semidev"]
        m_hi_td, m_lo_td = fmt_risk_pair(m["hi"], m["lo"], worse_is_negative=True)
        s_hi_td, s_lo_td = fmt_risk_pair(s["hi"], s["lo"], worse_is_negative=False)
        risk_rows += (f"<tr><th>{name}(n={r['n']})</th>"
                      f"{m_hi_td}{m_lo_td}<td>{fmt_boot(m['boot'])}</td>"
                      f"{s_hi_td}{s_lo_td}"
                      f"<td>{fmt_boot(s['boot'])}</td></tr>")
    risk_win_blocks = ""
    for name, r in risk_results.items():
        if r is None:
            continue
        for lab, key, worse_neg in (("最大回撤mdd" + str(RISK_K), "mdd", True),
                                     ("下檔半標準差semidev" + str(RISK_K), "semidev", False)):
            w_rows = []
            for w in r[key]["windows"]:
                hi_td, lo_td = fmt_risk_pair(w["高"], w["低"], worse_is_negative=worse_neg)
                w_rows.append(f"<tr><th>{w['窗']}日窗切法</th>{hi_td}{lo_td}</tr>")
            w_html = "".join(w_rows)
            risk_win_blocks += (f"<h3>{name} · {lab}(bshare窗口切法穩健度,風險目標固定k={RISK_K})</h3>"
                               f"<table><tr><th>bshare窗</th><th>高</th><th>低</th></tr>{w_html}</table>")

    cur = {m: round(float(VU[m]["bshare20"].dropna().iloc[-1]), 1) for m in ("TAIEX", "TPEx")}

    return f"""<!DOCTYPE html><html lang="zh-Hant"><head><meta charset="utf-8">
<title>好壞波動分解延伸卷二:風險/回撤角度+外部驗證(2026-08-01)</title><style>{css}</style></head><body>
<h1>🌗 好壞波動分解延伸卷二——風險/回撤角度 + 外部驗證擴大(2026-08-01)</h1>
<div class="note">接續<a href="research_vol_updown_explore.html" style="color:#6bb7e3">卷一探路卷</a>
(bshare20壞波動占比已驗證非重複資訊,對跌觸發注意股有報酬面真訊號)。本卷補三件事:
①目標變數從「未來報酬」換成「未來k={RISK_K}日最大回撤mdd/下檔半標準差semidev」測風險維度;
②外部驗證擴大到甜蜜格、處置V4兩支既有反轉策略(沿用build_strategy_regime_matrix.py正式函式,
不重新設計規則);③全面補bootstrap(月群重抽樣2000次,95%CI)取代卷一的裸中位數對照。</div>

<h2>🗣️ 白話導讀</h2>
<div class="note">
<p><b>風險角度怎麼算:</b>mdd{RISK_K}=進場後{RISK_K}個交易日內,價格相對進場價的路徑最低點跌幅%
(越負=中途曾經跌得越深);semidev{RISK_K}=同一段期間逐日報酬的下檔半標準差(只算負報酬日,
MAR=0%,越高=下跌時波動越劇烈)。兩者都是「風險大小」不是「最終賺賠」——即使最終報酬打平,
過程可能很顛簸(高semidev)或很平順(低semidev),這是報酬面完全看不到的維度。</p>
<p><b>外部驗證怎麼做:</b>四支既有反轉/動能策略(跌觸發、score4、甜蜜格、處置V4)全部重跑報酬面
(補bootstrap)+風險面(mdd/semidev),高低bshare20分桶邏輯與卷一相同(樣本內33/66百分位切兩組)。</p>
<p><b>判讀重點:</b>看下面兩張總表——報酬面「bootstrap是否排0」判斷卷一發現是否經得起更嚴謹檢定;
風險面「高低組mdd/semidev有沒有顯著差、方向是正是負」判斷好壞波動分解對風險預測有沒有加值,
方向事前不預設,兩個方向都如實記錄。</p>
</div>

<h2>①報酬維度——四策略bootstrap升級版(取代卷一裸中位數對照)</h2>
<div class="note">高低bshare20分桶=事件當日bshare20(ffill)樣本內33/66百分位切兩組;bootstrap=月群
重抽樣2000次95%CI(build_dtlend_report.boot_diff_ci,「排0」=高低組差異顯著)。</div>
<table><tr><th>策略</th><th>全期</th><th>高bshare20</th><th>低bshare20</th><th>高低差bootstrap(pp)</th></tr>
{ret_rows}</table>
<h3 style="margin-top:20px">bshare窗口穩健度(10/20/60三窗口切法,目標變數固定為該策略原生持有期報酬)</h3>
{ret_win_blocks}

<h2>②風險維度(新增)——mdd{RISK_K}/semidev{RISK_K},高低bshare20組對照</h2>
<div class="note">mdd越負=中途跌得越深(風險越大);semidev越高=下跌時波動越劇烈(風險越大)。
p10=該組最差10%分位數(尾部風險參考)。</div>
<table><tr><th>策略</th><th>mdd高bshare</th><th>mdd低bshare</th><th>mdd高低差bootstrap</th>
<th>semidev高bshare</th><th>semidev低bshare</th><th>semidev高低差bootstrap</th></tr>
{risk_rows}</table>
<h3 style="margin-top:20px">bshare窗口穩健度(10/20/60三窗口切法,風險目標固定k={RISK_K})</h3>
{risk_win_blocks}

<h2>當下讀數</h2>
<div class="note">TAIEX bshare20={cur['TAIEX']}%,TPEx bshare20={cur['TPEx']}%(與卷一同步讀數)。</div>

<h2>誠實限制</h2>
<div class="note">
①事件建構=逐字複製各策略正式函式(M.strat_attention_down/strat_score4/strat_sweetspot/
strat_dispo_v4)的既有篩選門檻多取一個code欄位算風險路徑,理論上樣本應與正式函式一致,
主控台輸出有印兩邊n數做交叉核對;<br>
②風險目標變數k固定20日(對齊bshare20主窗口),未對「風險目標窗口本身」做10/60日敏感度(只對
「bshare切分窗口」做了10/20/60穩健度),即mdd10/mdd60未測,是本卷已知簡化;<br>
③甜蜜格籃子的風險值=同日多檔個股mdd/semidev算完後取平均,跟該策略「ret」欄位的聚合方式一致,
但平均掉了個股間的離散度,可能低估籃子內部的風險異質性;<br>
④高低分桶仍是事後(in-sample)樣本內百分位切法,存在資料窺探風險,bootstrap只驗證「差異是否
偶然」不能消除這層設計上的偏誤;<br>
⑤處置V4/甜蜜格事件本身帶有本質性的高波動/恐慌背景(進場時點常常就是恐慌高峰附近),與跌觸發相比
基期風險水準本來就不同,高低bshare組的風險差異可能部分反映「進場時機」而非bshare20本身的獨立
預測力,本卷未做進一步的迴歸控制拆解。
</div>

<h2>誠實判讀結論</h2>
<div class="note">見對話回報(精簡版),完整數字以上方兩張總表+bootstrap CI為準。</div>
<div class="note">維運: python 研究腳本/綜合策略/build_vol_updown_explore_v2.py(從根目錄執行,
依賴capital_flow.db的disposition/fm_daily_price表+快取/tmp_attention_full_panel.pkl+
快取/tmp_theme_momentum_v2_panel.pkl+快取/tmp_panic_sweetspot_events.pkl,無新建快取檔)。</div>
</body></html>"""


if __name__ == "__main__":
    main()
