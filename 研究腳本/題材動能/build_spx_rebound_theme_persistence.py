# -*- coding: utf-8 -*-
"""SPX止穩反彈·題材領導權延續性考卷(2026-08-05,使用者假說原文:「我們常常看到SPX跌後止穩,
SPX開始反彈時,我們會注意那些題材股票反彈的更大,這可能有延續性」)。

與既有考卷的分工: build_rebound_leadership.py(2026-07-30)測的是台股指數止穩日「個股cohort」
(舊將/新兵/抗跌)誰領跑——本卷測的是**美股題材層**: SPX反彈起點後,反彈最大的題材(vs最小的)
其台股對映題材後續是否持續領先。題材層×美股錨×延續性=乾淨空白。

═══ 設計(寫程式前預先註冊) ═══
Episode(零前視): SPX收盤距120日滾動高<=-5%為「修正中」;t0=修正中首個「單日漲>=+1%且收盤高於
  前5日收盤最低」的反彈起點日;episode間隔>=60美股交易日去重。敏感度: 修正門檻-10%子集。
領導強度: W=t0起3個美股交易日,各題材累計超額報酬(減SPX同窗)排名→Top3/Bot3題材。
  敏感度: W=1日(只看t0當天)。對照操作化: 「修正期抗跡」版(從修正峰到t0的題材超額,抗跌=領導)
  ——回答「進攻型領導(反彈猛)vs防守型領導(抗跌)哪個延續」。
台股結果: W結束後第一個台股交易日**開盤**進場(訊號=美股收盤,台股開盤前完全確認,零前視),
  同題材demean CAR k=5/10/20/40/60;Top3均值-Bot3均值=領導權延續價差。
美股自身延續(機制拆解): W後20美股日Top3-Bot3超額——延續性住在美股端還是台股端。
統計: episode=抽樣單位(集群bootstrap 2000次)+逐episode正負號誠實列(n~15-20,小樣本,
  比照feedback第3條逐期檢查;結論最多「候選」定位)。

口徑: 美股題材=us_daily_price 20對映題材(剔ADR);台股側fm_daily_price close>0 AND money>0;
台股題材=成員等權(>=2有值)。
用法: python 研究腳本/題材動能/build_spx_rebound_theme_persistence.py  (從根目錄執行,鐵律)
產出: 研究報告/research_rebound_theme_persistence.html + console
"""
import json
import sqlite3
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

DB = "capital_flow.db"
OUT = "研究報告/research_rebound_theme_persistence.html"
START = "2015-01-01"
CORR_TH = -0.05          # 修正門檻(主), -0.10敏感度
BOUNCE_TH = 0.01         # t0單日漲幅門檻
W_DAYS = 3               # 領導強度衡量窗(美股交易日)
GAP_EPISODE = 60         # episode去重間隔(美股交易日)
TOPN = 3
K_LIST = [5, 10, 20, 40, 60]
ADR_EXCLUDE = {"TSM", "UMC", "ASX"}
MAPPED_THEMES = [
    "IC設計", "CPO/光通訊", "AI伺服器", "半導體設備", "記憶體", "晶圓代工",
    "功率半導體", "電力設備", "組裝代工(EMS)", "機器人/自動化", "半導體材料",
    "電池/儲能", "連接器", "網通設備", "綠能/太陽能", "封測(OSAT/測試)",
    "被動元件", "化合物半導體", "PCB/CCL", "電信",
]
MIN_TW_MEMBERS = 2
rng = np.random.default_rng(20260805)

GREEN, RED, BLUE, YELLOW, GRAY = "#7ec97e", "#e06c5a", "#6bb7e3", "#c3a55a", "#8a8878"


def theme_ret(px_ret, members, min_n=MIN_TW_MEMBERS):
    cols = [c for c in members if c in px_ret.columns]
    if not cols:
        return None
    m = px_ret[cols]
    n = m.notna().sum(axis=1)
    return m.mean(axis=1).where(n >= min_n)


def load():
    conn = sqlite3.connect(DB, timeout=60)
    mem = {}
    for country, key in (("美", "us"), ("台", "tw")):
        for t in MAPPED_THEMES:
            mem[(key, t)] = [r[0] for r in conn.execute(
                "select distinct code from classification where country=? and main_group=?",
                (country, t))]
    all_tw = sorted({c for t in MAPPED_THEMES for c in mem[("tw", t)]})
    usd = pd.read_sql("select code,date,close from us_daily_price where date>='2014-01-01'", conn)
    twd = pd.read_sql(
        "select code,date,open,close from fm_daily_price "
        "where date>='2014-06-01' and close>0 and money>0 and code in (%s)" % ",".join("?" * len(all_tw)),
        conn, params=all_tw)
    idx = pd.read_sql("select market,date,open,close from index_daily "
                      "where market in ('TAIEX','SPX') and date>='2013-01-01'", conn)
    conn.close()
    return mem, usd, twd, idx


def find_episodes(spx_close, corr_th):
    dd = spx_close / spx_close.rolling(120).max() - 1
    ret1 = spx_close.pct_change()
    low5 = spx_close.shift(1).rolling(5).min()
    dates = list(spx_close.index)
    t0s = []
    last_i = -10**9
    for i, d in enumerate(dates):
        if i < 120 or pd.isna(dd.iloc[i]):
            continue
        # 前一日仍在修正中(用前日dd,避免「當天大漲把dd拉回門檻內」漏掉真反彈起點)
        if pd.isna(dd.iloc[i - 1]) or dd.iloc[i - 1] > corr_th:
            continue
        if ret1.iloc[i] >= BOUNCE_TH and spx_close.iloc[i] > low5.iloc[i]:
            if i - last_i >= GAP_EPISODE:
                t0s.append((d, i, float(dd.iloc[i - 1])))
                last_i = i
    return t0s, dd


def main():
    mem, usd, twd, idx = load()
    spx = idx[idx.market == "SPX"].set_index("date")["close"].sort_index()
    tai = idx[idx.market == "TAIEX"].set_index("date").sort_index()
    spx_ret = spx.pct_change()

    us_close = usd.pivot_table(index="date", columns="code", values="close", aggfunc="first").sort_index()
    us_ret = us_close.pct_change(fill_method=None)
    tw_close = twd.pivot_table(index="date", columns="code", values="close", aggfunc="first").reindex(tai.index).sort_index()
    tw_open = twd.pivot_table(index="date", columns="code", values="open", aggfunc="first").reindex(tai.index).sort_index()
    tw_open = tw_open.where(tw_open > 0)

    # 題材層序列
    us_ex = {}                      # 美題材超額(減SPX)日報酬
    tw_car = {}                     # 台題材demean CAR(開盤錨)
    tai_car_o = {k: tai["close"].shift(-k) / tai["open"] - 1 for k in K_LIST}
    car_o = {k: tw_close.shift(-k) / tw_open - 1 for k in K_LIST}
    for t in MAPPED_THEMES:
        us_members = [c for c in mem[("us", t)] if c not in ADR_EXCLUDE]
        r = theme_ret(us_ret, us_members, min_n=1)
        if r is None:
            continue
        us_ex[t] = r - spx_ret.reindex(r.index)
        tw_car[t] = {k: theme_ret(car_o[k], mem[("tw", t)]) for k in K_LIST}

    us_dates = np.array(us_ret.index)      # ⚠美股日線2015起,與SPX序列(2013起)位置基底不同,
    tai_dates = np.array(tai.index)        #   一律用「日期」重新對位,絕不混用兩邊的整數位置

    def run_exam(corr_th, w_days, rank_mode, label):
        """rank_mode: 'bounce'=W窗超額 / 'defense'=修正峰→t0抗跌度"""
        t0s, dd = find_episodes(spx, corr_th)
        t0s = [x for x in t0s if x[0] >= START]
        episodes = []
        for d0, i0_spx, depth in t0s:      # i0_spx=SPX序列位置,只准用於spx自身(defense的峰值窗)
            iu0 = int(np.searchsorted(us_dates, d0))          # t0映射到美股日線位置
            if iu0 >= len(us_dates) or us_dates[iu0] > d0:    # t0當天美股日線須有資料
                if iu0 >= len(us_dates):
                    continue
                if (pd.Timestamp(us_dates[iu0]) - pd.Timestamp(d0)).days > 3:
                    continue
            iw = iu0 + w_days - 1
            if iw >= len(us_dates):
                continue
            d_w_end = us_dates[iw]
            # 領導強度
            strength = {}
            for t, ex in us_ex.items():
                if rank_mode == "bounce":
                    seg = ex.loc[us_dates[iu0]:d_w_end]
                    if seg.notna().sum() < w_days:
                        continue
                    strength[t] = float(seg.sum())
                else:   # defense: 修正峰(120日高當日)→t0前一美股日的累計超額
                    win = spx.iloc[max(0, i0_spx - 120):i0_spx]
                    if len(win) < 20 or iu0 < 1:
                        continue
                    peak_d = win.idxmax()
                    seg = ex.loc[peak_d:us_dates[iu0 - 1]]
                    if seg.notna().sum() < 10:
                        continue
                    strength[t] = float(seg.sum())
            if len(strength) < 8:
                continue
            ranked = sorted(strength, key=strength.get, reverse=True)
            top, bot = ranked[:TOPN], ranked[-TOPN:]
            # 台股進場日=W結束後第一個台股交易日
            entry_pos = int(np.searchsorted(tai_dates, d_w_end, side="right"))
            if entry_pos >= len(tai_dates):
                continue
            entry_d = tai_dates[entry_pos]
            rec = {"t0": d0, "depth": depth, "entry": entry_d,
                   "top": top, "bot": bot,
                   "top_w": np.mean([strength[t] for t in top]) * 100,
                   "bot_w": np.mean([strength[t] for t in bot]) * 100}
            ok = True
            for k in K_LIST:
                tv = [tw_car[t][k].get(entry_d, np.nan) for t in top if t in tw_car]
                bv = [tw_car[t][k].get(entry_d, np.nan) for t in bot if t in tw_car]
                bench = tai_car_o[k].get(entry_d, np.nan)
                tvm = np.nanmean(tv) - bench if np.isfinite(np.nanmean(tv)) else np.nan
                bvm = np.nanmean(bv) - bench if np.isfinite(np.nanmean(bv)) else np.nan
                rec[f"top{k}"] = tvm * 100
                rec[f"bot{k}"] = bvm * 100
                rec[f"sp{k}"] = (tvm - bvm) * 100 if pd.notna(tvm) and pd.notna(bvm) else np.nan
            if pd.isna(rec.get("sp20")):
                ok = False
            # 美股自身延續: W後20美股日Top-Bot超額
            j0 = iw + 1
            if j0 + 20 < len(us_dates):
                tus = np.nanmean([us_ex[t].iloc[j0:j0 + 20].sum() for t in top])
                bus = np.nanmean([us_ex[t].iloc[j0:j0 + 20].sum() for t in bot])
                rec["us_cont"] = (tus - bus) * 100
            if ok:
                episodes.append(rec)
        E = pd.DataFrame(episodes)
        print(f"\n【{label}】episodes={len(E)}")
        if len(E) < 6:
            print("  episode數不足,跳過")
            return None
        for r in E.itertuples():
            print(f"  {r.t0} 深度{r.depth * 100:+.1f}% 進場{r.entry} Top={'/'.join(r.top)}(W{r.top_w:+.1f}%) "
                  f"Bot={'/'.join(r.bot)}(W{r.bot_w:+.1f}%)")
            print(f"    價差Top-Bot: " + " ".join(
                f"k{k}={getattr(r, f'sp{k}'):+.2f}" if pd.notna(getattr(r, f"sp{k}")) else f"k{k}=—"
                for k in K_LIST) + (f"  美股自身20日{r.us_cont:+.2f}%" if pd.notna(getattr(r, 'us_cont', np.nan)) else ""))
        pooled = {}
        for k in K_LIST:
            v = E[f"sp{k}"].dropna().values
            if len(v) < 6:
                continue
            means = [np.mean(v[rng.integers(0, len(v), len(v))]) for _ in range(2000)]
            lo, hi = np.percentile(means, [2.5, 97.5])
            pooled[k] = {"mean": float(np.mean(v)), "lo": float(lo), "hi": float(hi),
                         "sig": bool(lo > 0 or hi < 0), "pos": int((v > 0).sum()), "n": len(v),
                         "top": float(E[f"top{k}"].mean()), "bot": float(E[f"bot{k}"].mean())}
            p = pooled[k]
            print(f"  [pooled k{k}] Top{p['top']:+.2f}% Bot{p['bot']:+.2f}% 價差{p['mean']:+.2f}pp "
                  f"CI[{p['lo']:+.2f},{p['hi']:+.2f}]{'✓排0' if p['sig'] else '含0'} "
                  f"正號{p['pos']}/{p['n']}")
        usc = E["us_cont"].dropna()
        us_line = None
        if len(usc) >= 6:
            means = [np.mean(usc.values[rng.integers(0, len(usc), len(usc))]) for _ in range(2000)]
            lo, hi = np.percentile(means, [2.5, 97.5])
            us_line = {"mean": float(usc.mean()), "lo": float(lo), "hi": float(hi),
                       "sig": bool(lo > 0 or hi < 0), "pos": int((usc > 0).sum()), "n": len(usc)}
            print(f"  [美股自身延續20日] Top-Bot={us_line['mean']:+.2f}% "
                  f"CI[{us_line['lo']:+.2f},{us_line['hi']:+.2f}]{'✓排0' if us_line['sig'] else '含0'} "
                  f"正號{us_line['pos']}/{us_line['n']}")
        return {"label": label, "E": E, "pooled": pooled, "us": us_line}

    print("=" * 86)
    print("SPX止穩反彈·題材領導權延續性考卷")
    print("=" * 86)
    main_res = run_exam(CORR_TH, W_DAYS, "bounce", "主檢定: 修正-5%×反彈W=3日×進攻型排名")
    sens_w1 = run_exam(CORR_TH, 1, "bounce", "敏感度: W=1日(只看t0當天)")
    sens_deep = run_exam(-0.10, W_DAYS, "bounce", "敏感度: 深修正-10%子集")
    defense = run_exam(CORR_TH, W_DAYS, "defense", "對照操作化: 防守型排名(修正期抗跌)")

    # ---------- HTML ----------
    def blk(res):
        if res is None:
            return "<div class='note'>episode數不足。</div>"
        E, pooled = res["E"], res["pooled"]
        ep_rows = "".join(
            f"<tr><th>{r.t0}</th><td>{r.depth * 100:+.1f}%</td><td>{r.entry}</td>"
            f"<td style='text-align:left'>{'/'.join(r.top)}</td><td style='text-align:left'>{'/'.join(r.bot)}</td>"
            + "".join(f"<td class='{'good' if pd.notna(getattr(r, f'sp{k}')) and getattr(r, f'sp{k}') > 0 else 'bad'}'>"
                      f"{getattr(r, f'sp{k}'):+.2f}</td>" if pd.notna(getattr(r, f"sp{k}")) else "<td>—</td>"
                      for k in K_LIST) + "</tr>"
            for r in E.itertuples())
        pooled_rows = "".join(
            f"<tr><th>k{k}</th><td>{p['top']:+.2f}%</td><td>{p['bot']:+.2f}%</td>"
            f"<td><b>{p['mean']:+.2f}pp</b></td><td>[{p['lo']:+.2f},{p['hi']:+.2f}]"
            f"{'<b>✓</b>' if p['sig'] else ''}</td><td>{p['pos']}/{p['n']}</td></tr>"
            for k, p in pooled.items())
        us_txt = ""
        if res["us"]:
            u = res["us"]
            us_txt = (f"<div class='note'>美股端自身延續(W後20美股日Top-Bot超額): {u['mean']:+.2f}% "
                      f"CI[{u['lo']:+.2f},{u['hi']:+.2f}]{'✓排0' if u['sig'] else '含0'},正號{u['pos']}/{u['n']}。</div>")
        return (f"<table><tr><th>t0(SPX反彈起點)</th><th>深度</th><th>台股進場日</th><th>Top3題材</th><th>Bot3題材</th>"
                + "".join(f"<th>k{k}價差</th>" for k in K_LIST) + f"</tr>{ep_rows}</table>"
                f"<h3>pooled(episode集群bootstrap)</h3>"
                f"<table><tr><th>窗</th><th>Top3</th><th>Bot3</th><th>價差</th><th>95%CI</th><th>正號</th></tr>"
                f"{pooled_rows}</table>{us_txt}")

    CSS = """
body{background:#1a1a19;color:#fff;font-family:"Noto Sans TC",sans-serif;margin:24px;max-width:1150px}
h1{font-size:20px} h2{font-size:15px;color:#c3c2b7;margin-top:30px;border-bottom:1px solid #333;padding-bottom:4px}
h3{font-size:13.5px;color:#a8a79a;margin:14px 0 4px}
table{border-collapse:collapse;font-size:12.5px;font-variant-numeric:tabular-nums;margin:8px 0}
td,th{border:1px solid #333;padding:4px 8px;text-align:right} th{text-align:left;color:#c3c2b7}
.note{color:#8a8878;font-size:12.5px;line-height:1.8} .good{color:#7ec97e} .bad{color:#e06c5a}
ul{margin:4px 0;padding-left:20px;font-size:12.5px;color:#ccc;line-height:1.7}
.verdict{font-size:13px;font-weight:bold;padding:6px 10px;border-radius:4px;display:inline-block;margin:4px 0}
.v-good{background:#243b24;color:#7ec97e} .v-bad{background:#3b2420;color:#e06c5a}
.v-warn{background:#3b3420;color:#c3a55a}
"""
    mk = main_res["pooled"] if main_res else {}
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>SPX止穩反彈·題材領導權延續性(2026-08-05)</title><style>{CSS}</style></head><body>
<h1>🔄 SPX止穩反彈·題材領導權延續性考卷</h1>
<div class="note">使用者假說:「SPX跌後止穩開始反彈時,反彈更大的題材可能有延續性」。
Episode=SPX距120日高&lt;=-5%修正中,首個單日+1%且高於前5日低的反彈起點(60日去重,零前視);
領導強度=t0起3美股日題材累計超額(減SPX)排名Top3/Bot3;台股=W結束後首個台股日<b>開盤</b>進場,
同題材demean CAR k=5~60,Top3-Bot3=延續性價差;episode集群bootstrap+逐episode誠實列(小樣本,
結論上限=候選)。與build_rebound_leadership.py(台股止穩日個股cohort)分工,本卷=美股錨×題材層。</div>

<h2>主檢定: 修正-5% × 反彈W=3日 × 進攻型排名</h2>
{blk(main_res)}
<h2>敏感度: W=1日(只看t0當天的反彈)</h2>
{blk(sens_w1)}
<h2>敏感度: 深修正(-10%)子集</h2>
{blk(sens_deep)}
<h2>對照操作化: 防守型排名(修正期抗跌度,峰→t0)</h2>
{blk(defense)}

<h2>⚖️ 判決(2026-08-05首輪)</h2>
<ul>
<li><span class="verdict v-bad">四種操作化全數null: 反彈初期領導題材無延續性</span>
主檢定(W=3日進攻排名)Top-Bot全窗含0且正號11-13/21≈丟銅板;W=1日版/深修正-10%子集/防守型
(抗跌排名)版全部含0——同一個直覺換了四種操作化都測不出,是乾淨null非單一定義失手。</li>
<li><b>機制拆解也一致</b>: 美股端自身延續(W後20美股日Top-Bot)主檢定-1.77%含0——延續性連美股端
都不存在,台股端沒得繼承。防守型排名甚至各窗全負(抗跌題材之後偏落後,反轉味,但含0)。</li>
<li><b>與「題材獨漲」線不矛盾,反而互補定位</b>: 獨漲吃的是「隔夜題材訊號未被台股開盤定價」的
<b>事件層錯價</b>(訊號→次日,快)——反彈領導吃的是「強者恆強的排名延續」(<b>排行層</b>,慢),
後者在題材層不存在。值得注意Top與Bot在反彈後<b>都大漲</b>(主檢定k40: Top+5.83%/Bot+4.80%)=
反彈期雨露均霑,「參與反彈」本身有肉,「挑反彈最猛的題材」是雜訊。SPX止穩訊號家族的既有活口
是底部溫度計(抄底訊號)與題材獨漲(隔夜事件),不是題材排行。</li>
<li><b>呼應既有判決</b>: 與精煉卷「強題材子集split-half死亡(題材強弱不延續)」同一個結論的
第二次獨立重現——<b>題材層的相對強弱排序沒有記憶</b>,個股cohort層(build_rebound_leadership.py
舊將/新兵)與事件層(獨漲)才是可用的結構。</li>
</ul>

<h2>已知限制</h2>
<div class="note">①episode數天生少(~10-25個),集群bootstrap檢定力有限,逐episode正負號比CI更重要,
任何結論最多「候選」;②Top3/Bot3各episode題材組成不同,價差混合了「題材本身」與「領導強度」;
③台股側fm_daily_price未還原除權息(長窗保守偏誤);④修正門檻/-反彈定義為研究者選擇,已附W=1/-10%
敏感度;⑤k40/60窗跨episode重疊可能(2022連續修正),集群單位=episode已部分處理。</div>
<div class="note">維運: python 研究腳本/題材動能/build_spx_rebound_theme_persistence.py(從根目錄執行)。
姊妹卷: build_us_tw_overnight_link.py/build_us_tw_pocket_refine.py(題材獨漲線)、
build_rebound_leadership.py(台股止穩個股cohort)。</div>
</body></html>"""
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n[report] 已輸出 {OUT}")


if __name__ == "__main__":
    main()
