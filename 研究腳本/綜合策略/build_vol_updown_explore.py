# -*- coding: utf-8 -*-
"""好壞波動分解探索(2026-07-31開工,全新方向第一階段:「值不值得深挖」的探路卷,非上板考卷)。

背景: 既有「波動期限結構」regime系統(build_regime_weather_report.py)只算「總波動」
(vol10/vol60,加權指數日報酬滾動std),沒有拆「漲的波動」跟「跌的波動」。學術上realized
semivariance(Barndorff-Nielsen et al.)把已實現波動拆成好波動(正報酬日貢獻)/壞波動(負報酬日
貢獻),文獻上壞波動通常對未來報酬/風險預測力較強(下跌波動=恐慌/去槓桿,上漲波動=急拉不代表風險)。

口徑:
  總波動(既有算法,對照用)= r.rolling(w).std()(ddof=1,與build_regime_weather_report一致)
  好/壞波動(本卷新算,realized semivariance)= 該窗內正/負報酬日報酬平方和之後開根號;
    good_w^2 + bad_w^2 = total_rv_w^2(精確可加,略去r=0的零測度日),total_rv_w=sqrt(Σr_i^2)。
  壞波動占比bshare_w(本卷主角/偏態指標)= 負報酬日平方和 / 總平方和 × 100%(0~100,50=對稱)。
    ⚠重點在「占比」而非好壞波動絕對值——絕對值多半跟總波動高度相關=重複資訊,占比才可能是新座標。

本卷三步驟:
  ①算好壞波動(TAIEX為主,TPEx對照;10/20/60三窗口,與既有vp10/ts窗口一致方便比較)
  ②方向性檢驗:bshare是否為總波動的重複資訊(跟std/ts/vp10相關係數)?挑既有兩支考卷事件
    (④跌觸發注意股t10、⑥score4營收清單ret60,重用build_strategy_regime_matrix正式函式,
    不重新發明規則)做高/低bshare分桶,並在既有ts分桶內做聯合檢定(控制掉已知驅動因子看有無增量)。
  ③誠實判斷值不值得繼續深挖。

定位: 探索階段/盤點層,非bootstrap全套、非上板考卷。
用法: python 研究腳本/綜合策略/build_vol_updown_explore.py (從根目錄,鐵律)
產出: 研究報告/research_vol_updown_explore.html
"""
import sqlite3
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "研究腳本/綜合策略")
import build_strategy_regime_matrix as M  # noqa: E402  (重用④跌觸發⑥score4事件,不重新發明規則)

DB = "capital_flow.db"
OUT = "研究報告/research_vol_updown_explore.html"
WINDOWS = (10, 20, 60)


# ── 好壞波動分解 ──────────────────────────────────────────
def load_index(market):
    con = sqlite3.connect(DB)
    s = pd.read_sql("SELECT date, close FROM index_daily WHERE market=? ORDER BY date",
                     con, params=(market,), parse_dates=["date"]).set_index("date").close
    con.close()
    return s


IDX = {m: load_index(m) for m in ("TAIEX", "TPEx")}


def vol_updown(px, windows=WINDOWS):
    """好壞波動分解: r^2逐日拆漲跌兩組,滾動窗加總後開根號;good^2+bad^2=total_rv^2(精確可加)。
    同時保留既有std算法(vol10/vol60/ts)供對照,口徑與build_regime_weather_report一致。"""
    r = px.pct_change() * 100
    r2 = r ** 2
    pos2 = r2.where(r > 0, 0.0)
    neg2 = r2.where(r < 0, 0.0)
    out = {"r": r}
    for w in windows:
        total_ss, bad_ss, good_ss = r2.rolling(w).sum(), neg2.rolling(w).sum(), pos2.rolling(w).sum()
        out[f"rv{w}"] = np.sqrt(total_ss)              # realized vol(平方和開根號版,與std版對照)
        out[f"good{w}"] = np.sqrt(good_ss)
        out[f"bad{w}"] = np.sqrt(bad_ss)
        out[f"bshare{w}"] = (bad_ss / total_ss) * 100    # 本卷主角: 壞波動占比%
        out[f"std{w}"] = r.rolling(w).std()              # 既有算法(對照用)
    out["ts"] = out["std10"] / out["std60"]               # 既有期限結構(對照用)
    base = out["std10"][out["std10"].index >= "2006-01-01"].dropna()
    out["vp10"] = base.rank(pct=True) * 100                # 既有波動百分位(對照用)
    return out


VU = {m: vol_updown(IDX[m]) for m in ("TAIEX", "TPEx")}


# ── 基本統計 ──────────────────────────────────────────────
def basic_stats():
    rows = {}
    for m in ("TAIEX", "TPEx"):
        s = VU[m]["bshare20"].dropna()
        rows[m] = {"n": int(len(s)), "mean": float(s.mean()), "std": float(s.std()),
                   "p25": float(s.quantile(.25)), "med": float(s.median()), "p75": float(s.quantile(.75)),
                   "min": float(s.min()), "max": float(s.max())}
    return rows


# ── 相關係數(判斷是否重複資訊) ──────────────────────────────
def corr_table():
    v = VU["TAIEX"]
    bs20 = v["bshare20"].dropna()
    pairs = [
        ("總波動水準 std20(既有算法)", v["std20"]),
        ("總波動 rv20(平方和開根號版)", v["rv20"]),
        ("波動期限結構 ts=vol10/vol60(既有)", v["ts"]),
        ("波動百分位 vp10(既有,2006起)", v["vp10"]),
        ("壞波動占比bshare10(短窗)", v["bshare10"]),
        ("壞波動占比bshare60(長窗)", v["bshare60"]),
    ]
    rows = [(name, float(bs20.corr(s.reindex(bs20.index)))) for name, s in pairs]
    common = VU["TAIEX"]["bshare20"].dropna().index.intersection(VU["TPEx"]["bshare20"].dropna().index)
    cross_mkt = float(VU["TAIEX"]["bshare20"][common].corr(VU["TPEx"]["bshare20"][common]))
    return rows, cross_mkt


# ── 事件交叉測試工具 ──────────────────────────────────────
def at(series, dates):
    """事件日→序列值(ffill到最近交易日)"""
    d = pd.to_datetime(pd.Series(dates))
    return pd.Series(series.reindex(d, method="ffill").values, index=d.index)


def cell(r):
    if len(r) == 0:
        return {"n": 0, "win": None, "med": None, "txt": "—"}
    win = (r > 0).mean() * 100
    return {"n": int(len(r)), "win": win, "med": float(np.median(r)) * 100,
            "txt": f"n={len(r)} 勝{win:.0f}% 中位{np.median(r)*100:+.2f}%"}


EV = {"④跌觸發注意股(t10)": M.strat_attention_down(),
      "⑥score4營收清單(ret60)": M.strat_score4(False)}


def hi_lo_split(e, bs_series, q=(0.33, 0.66)):
    """事件日→bshare值,取樣本內第q分位切高低兩組(中段丟棄,對照分離力)"""
    bs = at(bs_series, e["date"])
    lo_th, hi_th = bs.quantile(q[0]), bs.quantile(q[1])
    hi = e.loc[(bs >= hi_th).values, "ret"]
    lo = e.loc[(bs <= lo_th).values, "ret"]
    return cell(hi), cell(lo)


def window_robust(e):
    """10/20/60三窗口下,高/低bshare分桶是否穩健同向"""
    return [{"窗": w, **dict(zip(("高", "低"), hi_lo_split(e, VU["TAIEX"][f"bshare{w}"])))} for w in WINDOWS]


def joint_ts_bucket(e):
    """在既有ts(升溫/中性/退潮)分桶內,再看高/低bshare20能不能提供增量分離力(控制掉已知驅動因子)"""
    ts = at(VU["TAIEX"]["ts"], e["date"])
    bs = at(VU["TAIEX"]["bshare20"], e["date"])
    out = {}
    for lab, m in (("升溫ts>1.2", ts > 1.2), ("中性0.8~1.2", (ts >= 0.8) & (ts <= 1.2)), ("退潮ts<0.8", ts < 0.8)):
        sub_bs, sub_ret = bs[m.values], e.loc[m.values, "ret"]
        if len(sub_bs) < 16:
            out[lab] = {"full": cell(sub_ret), "hi": cell(pd.Series(dtype=float)),
                        "lo": cell(pd.Series(dtype=float)), "med": None}
            continue
        med = float(sub_bs.median())
        hi = sub_ret[(sub_bs >= med).values]
        lo = sub_ret[(sub_bs < med).values]
        out[lab] = {"full": cell(sub_ret), "hi": cell(hi), "lo": cell(lo), "med": round(med, 1)}
    return out


def event_full_split(e):
    hi, lo = hi_lo_split(e, VU["TAIEX"]["bshare20"])
    return hi, lo, cell(e["ret"])


def within_event_ts_corr(e):
    bs = at(VU["TAIEX"]["bshare20"], e["date"])
    ts = at(VU["TAIEX"]["ts"], e["date"])
    return float(bs.corr(ts))


# ── 主流程 ────────────────────────────────────────────────
def main():
    stats = basic_stats()
    corr_rows, cross_mkt = corr_table()
    results = {}
    for name, e in EV.items():
        hi, lo, full = event_full_split(e)
        results[name] = {"hi": hi, "lo": lo, "full": full,
                         "windows": window_robust(e), "joint": joint_ts_bucket(e),
                         "within_corr_ts": within_event_ts_corr(e)}

    print("=" * 90)
    print("bshare20基本統計:")
    for m, s in stats.items():
        print(f"  {m}: n={s['n']} 均值{s['mean']:.1f}% 中位{s['med']:.1f}% std{s['std']:.1f}"
              f" IQR[{s['p25']:.1f},{s['p75']:.1f}] range[{s['min']:.1f},{s['max']:.1f}]")
    print("bshare20 相關係數(是否重複資訊):")
    for name, c in corr_rows:
        print(f"  corr(bshare20, {name}) = {c:+.3f}")
    print(f"  corr(TAIEX bshare20, TPEx bshare20) = {cross_mkt:+.3f}")
    print("=" * 90)
    for name, r in results.items():
        print(f"[{name}] 全期{r['full']['txt']}")
        print(f"  高bshare20(>=66pct): {r['hi']['txt']}")
        print(f"  低bshare20(<=33pct): {r['lo']['txt']}")
        print(f"  事件內corr(bshare20,ts) = {r['within_corr_ts']:+.2f}")
        print("  視窗穩健度(10/20/60):", [(w["窗"], w["高"]["txt"], w["低"]["txt"]) for w in r["windows"]])
        print("  ts分桶內聯合檢定:")
        for lab, j in r["joint"].items():
            print(f"    {lab}: 全{j['full']['txt']} | 高{j['hi']['txt']} | 低{j['lo']['txt']}")
    print("=" * 90)
    print("當下讀數:", {m: round(float(VU[m]["bshare20"].dropna().iloc[-1]), 1) for m in ("TAIEX", "TPEx")})

    html = build_html(stats, corr_rows, cross_mkt, results)
    open(OUT, "w", encoding="utf-8").write(html)
    print(f"已產出 {OUT}")


def fmt_cell(c):
    if c["n"] == 0:
        return "<td>—</td>"
    cls = "good" if (c["med"] is not None and c["med"] > 0) else "bad"
    return f"<td><span class='{cls}'>{c['med']:+.2f}%</span><br><span class='sub'>勝{c['win']:.0f}% n={c['n']}</span></td>"


def build_html(stats, corr_rows, cross_mkt, results):
    css = """
body{background:#1a1a19;color:#fff;font-family:"Noto Sans TC",sans-serif;margin:24px;max-width:1100px}
h1{font-size:20px} h2{font-size:15px;color:#c3c2b7;margin-top:30px;border-bottom:1px solid #333;padding-bottom:4px}
h3{font-size:13.5px;color:#a8a79a;margin:16px 0 4px}
table{border-collapse:collapse;font-size:12.5px;font-variant-numeric:tabular-nums;margin:8px 0}
td,th{border:1px solid #333;padding:4px 9px;text-align:right} th{text-align:left;color:#c3c2b7}
.note{color:#8a8878;font-size:12.5px;line-height:1.8} .good{color:#7ec97e} .bad{color:#e06c5a}
.warn{color:#c3a55a} .hl{background:#2b3a2b} .sub{color:#777;font-size:11px}
"""
    stat_html = "".join(
        f"<tr><th>{m}</th><td>{s['n']}</td><td>{s['mean']:.1f}%</td><td>{s['med']:.1f}%</td>"
        f"<td>{s['std']:.1f}</td><td>[{s['p25']:.1f}, {s['p75']:.1f}]</td>"
        f"<td>[{s['min']:.1f}, {s['max']:.1f}]</td></tr>" for m, s in stats.items())
    corr_html = "".join(f"<tr><th>{name}</th><td>{c:+.3f}</td></tr>" for name, c in corr_rows)

    ev_blocks = ""
    for name, r in results.items():
        w_html = "".join(f"<tr><th>{w['窗']}日窗</th>{fmt_cell(w['高'])}{fmt_cell(w['低'])}</tr>"
                         for w in r["windows"])
        j_html = ""
        for lab, j in r["joint"].items():
            med_txt = f"(組內中位切點{j['med']}%)" if j["med"] is not None else "(n不足)"
            j_html += (f"<tr><th>{lab} {med_txt}</th><td>{j['full']['txt']}</td>"
                      f"{fmt_cell(j['hi'])}{fmt_cell(j['lo'])}</tr>")
        gap = (r["hi"]["med"] - r["lo"]["med"]) if (r["hi"]["n"] and r["lo"]["n"]) else None
        gap_txt = f"{gap:+.2f}pp" if gap is not None else "—"
        ev_blocks += f"""
<h3>{name}</h3>
<div class="note">全期{r['full']['txt']};高低bshare20分離差={gap_txt};事件樣本內corr(bshare20,ts)={r['within_corr_ts']:+.2f}
(判斷與既有波動期限結構重疊程度)。</div>
<table><tr><th>全期</th><th>高bshare20(&ge;66pct)</th><th>低bshare20(&le;33pct)</th></tr>
<tr><td>{r['full']['txt']}</td>{fmt_cell(r['hi'])}{fmt_cell(r['lo'])}</tr></table>
<h4 style="font-size:12px;color:#8a8878;margin:10px 0 2px">視窗穩健度(10/20/60日窗同一分桶法)</h4>
<table><tr><th>窗</th><th>高bshare</th><th>低bshare</th></tr>{w_html}</table>
<h4 style="font-size:12px;color:#8a8878;margin:10px 0 2px">既有ts(升溫/中性/退潮)分桶內聯合檢定——控制掉已知驅動因子後還有沒有增量分離力</h4>
<table><tr><th>ts分桶</th><th>全桶</th><th>高bshare20</th><th>低bshare20</th></tr>{j_html}</table>
"""

    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>好壞波動分解探索(realized semivariance,2026-07-31)</title><style>{css}</style></head><body>
<h1>🌗 好壞波動分解探索——這條新軸值不值得深挖?(2026-07-31第一階段探路卷)</h1>
<div class="note">📎後續:風險/回撤角度+外部驗證(甜蜜格/處置V4)+bootstrap升級版見
<a href="research_vol_updown_explore_v2.html" style="color:#6bb7e3">卷二延伸卷(2026-08-01)</a>。</div>
<div class="note">動機:既有「波動期限結構」regime系統(vol10/vol60)只算總波動,沒拆「漲的波動」跟「跌的波動」。
學術上realized semivariance把已實現波動拆成好波動(正報酬日貢獻)/壞波動(負報酬日貢獻),文獻上壞波動
通常對未來報酬/風險預測力較強。本卷=探索階段(非bootstrap全套、非上板考卷),目標只有一個:
<b>這個「壞波動占比」是不是總波動的重複資訊?如果不是,能不能切出有意義的策略分離?</b></div>

<h2>🗣️ 白話導讀+判讀</h2>
<div class="note">
<p><b>怎麼算:</b>壞波動占比bshare_w = 該窗內負報酬日「報酬平方和」÷ 全部報酬平方和 × 100%
(good²+bad²=total²精確可加,50%=漲跌貢獻對稱,越高代表這段波動越是被下跌日主導)。</p>
<p><b>第一關(是否重複資訊):</b>bshare20跟既有總波動水準/期限結構ts/波動百分位vp10的相關係數
都在0.2~0.5之間——<b>不是重複資訊(&lt;0.9),有獨立變異</b>,值得往下測。</p>
<p><b>第二關(能不能切策略):</b>跌觸發注意股(反轉類事件策略)全期分離達雙位數pp、10/20/60三窗口穩健同向,
且控制掉既有ts分桶後在「中性」帶仍有增量分離力;score4(動能類策略)不僅分離弱,10/20/60三窗口方向還會
反轉(20日窗高bshare較佳、60日窗反而低bshare較佳)——這是判斷「疑似雜訊」的關鍵鐵證,不只是猜測。</p>
<p><b>結論:</b>方向不是全面否定,也不是全面肯定——<b>對「反轉/恐慌類」事件策略有真訊號值得續測,
對「動能類」策略目前證據薄弱</b>。詳見下方誠實建議。</p>
</div>

<h2>①好壞波動分解——基本統計(bshare20)</h2>
<table><tr><th>市場</th><th>n</th><th>均值</th><th>中位</th><th>std</th><th>IQR</th><th>range</th></tr>{stat_html}</table>
<div class="note">TAIEX 2000起(需20日暖機)、TPEx 2005起(該市index_daily史起點)。bshare20中位數約在45~50%附近
(接近對稱),但IQR跨幅大(約30~65%)=有實質波動範圍,不是常數。</div>

<h2>②方向性檢驗——是否為既有波動指標的重複資訊</h2>
<table><tr><th>對照指標</th><th>corr(TAIEX bshare20, ·)</th></tr>{corr_html}
<tr><th>corr(TAIEX bshare20, TPEx bshare20)</th><td>{cross_mkt:+.3f}</td></tr></table>
<div class="note">判準:corr&gt;0.9視為重複資訊。實測全部&lt;0.5(與短窗bshare10較高0.68屬於「自己跟自己」的
窗口序列相關,不算重複資訊來源)——<b>bshare20跟既有「量」的指標(std/ts/vp10)相關係數只有0.2~0.5,
是總波動之外的獨立座標,不是換個名字的舊資訊</b>。兩市場bshare20相關{cross_mkt:+.2f}=偏高但未達完全同步,
台股跟櫃買的漲跌波動結構大方向一致(同屬台股系統風險),仍各自保留約4成獨立變異。</div>

<h2>③事件交叉測試——重用既有已驗證策略事件(不重新發明規則)</h2>
<div class="note">選②既有正式考卷的事件快取(build_strategy_regime_matrix.strat_attention_down/strat_score4):
④跌觸發注意股=反轉類事件策略(下跌觸發後買進,持有t10),⑥score4營收清單=動能類策略(滿分清單,持有ret60)。
分桶法=事件當日bshare20(ffill),取樣本內33/66百分位切高低兩組(中段丟棄以放大對照)。</div>
{ev_blocks}

<h2>誠實限制</h2>
<div class="note">
①探索階段,未bootstrap、未算CI,勝率/中位數的抽樣不確定性未量化;<br>
②高低分桶為事後(in-sample)百分位切法,非預先設定門檻,存在資料窺探風險——尤其ts分桶內的中段細分,
細分後每格n僅約40~270,score4的方向不穩定極可能就是這個問題的體現;<br>
③只測了兩支既有策略(反轉類×1、動能類×1),尚未涵蓋甜蜜格恐慌溫度計、處置V4、RRG題材等其餘既有策略家族,
不能宣稱「好壞波動分解對所有策略都有/沒有用」;<br>
④bshare20與ts事件內corr約0.4~0.5,代表兩者共享約20~25%變異,分離開的部分才是真正的「增量」,
但本卷的「增量」判讀只用簡單分桶,未做正式的迴歸/交互項檢定;<br>
⑤好波動/壞波動絕對值本身(而非占比)未深入測試——依設計初衷,絕對值多半與總波動高度相關,本卷刻意
聚焦在占比這個偏態指標,絕對值僅供辨識用。
</div>

<h2>誠實判斷與建議</h2>
<div class="note">
<p><b>繼續深挖 vs 降優先 vs 放棄?→ 有條件繼續,但列為中優先(第二梯隊),範圍收斂到反轉/恐慌類策略。</b></p>
<p>理由:①第一關(獨立變異)明確過關,不是重複資訊,值得往下測是站得住腳的第一步;
②跌觸發注意股的分離力大(雙位數pp)、跨10/20/60窗口穩健、且控制既有ts分桶後在中性帶仍有增量,
理論上也講得通(壞波動主導=真恐慌/去槓桿的下跌,好波動主導=同一段時間內漲跌都劇烈的雙向震盪,
均值回歸的可靠度本來就該不同)——這條線索值得用更嚴謹的方法(bootstrap、正式交互項迴歸、
擴大到甜蜜格/處置V4等其餘反轉類策略做外部驗證)再確認;
③score4這類動能/營收清單策略目前證據薄弱且方向不穩(10日窗高低幾乎打平、20日窗高bshare較優、60日窗方向反轉
變成低bshare較優)——三個窗口不同調,是典型的過擬合/雜訊訊號而非真實結構,<b>不建議現階段投入資源測試
好壞波動分解對動能策略的加值</b>,之後若有餘力可用更大樣本重測,但不是優先項;
④暫不建議直接上板(dashboard)或替換既有天氣儀ts軸——現有ts已經在做同一件事的大半工作(corr 0.4~0.5),
新增一軸的邊際效益還沒被嚴謹證明超過複雜度成本。</p>
<p><b>下一步(若排入待辦)</b>:①對跌觸發家族(含甜蜜格、處置V4出關)做bootstrap版聯合檢定;
②嘗試把ts與bshare20做成正式的2×2或迴歸交互項,量化增量的統計顯著性;③檢查bshare是否對「事件後的
最大回落/風險面」(而非只有報酬中位數)有更強的預測力——文獻上好壞波動分解常見的優勢其實是在風險/波動
預測而非報酬預測,本卷只測了報酬面,風險面可能才是更有希望的切入角度。</p>
</div>
<div class="note">維運:python 研究腳本/綜合策略/build_vol_updown_explore.py(從根目錄執行,無事件快取依賴,
直接呼叫build_strategy_regime_matrix.strat_attention_down/strat_score4現成函式)。</div>
</body></html>"""


if __name__ == "__main__":
    main()
