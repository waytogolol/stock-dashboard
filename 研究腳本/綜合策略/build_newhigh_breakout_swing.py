# -*- coding: utf-8 -*-
"""創新高突破·波段延續性考卷(2026-08-05,使用者假說:「題材股價創新高(90天新高、60天新高)
都很有機會比較長的波段獲利」)。

與既有判決的關係(先盤點,避免重做):
· research_theme_member_selection(2026-08-02): 「題材觸發後」用創新高選成員=null——但那是條件於
  題材觸發的窄框架;本卷測**無條件**版: 全市場流動池,60/90日新高突破本身。
· 週級動能pathshape卷: giveback(收盤貼近週高)延續力強=方向一致的旁證(週錨)。
· executable_scan C3(要求已離開窗內高點)無效=「離高點」方向已測過,本卷測反方向(貼/破高點)。
· 台美獨漲線: 美股側新高交乘=短窗反轉長窗拉平(那是美股題材層,本卷是台股個股層)。
三問自查: ①誰被迫交易?——無人被迫,是行為財務的高點錨定效應(George&Hwang 52週高動能:投資人
錨定舊高、對突破反應不足),機制存在但非強制流,預期偏薄,照測(case-first)。②資訊新嗎?——價格
公開,但「創新高」是顯著性事件。③為何沒被吃掉?——錨定偏誤持續存在+波段時間尺度執行者少。

═══ 設計(預先註冊) ═══
訊號: 收盤=近N日最高收盤(N=60/90/240對照);兩種事件版:
  (a)延續新高=任何新高日(會在上升趨勢中每天觸發,樣本大,代表「持有在新高的股票」)
  (b)獨立突破=新高日且前20交易日內無N日新高(盤整後突破,樣本小,代表「剛突破買進」)
池: 20日均額>=0.3億(取前一日止,零前視)。
進場: 主錨=**次日收盤**(訊號確認後才出現的價格,與週級動能活口同口徑,feedback第18條);
  對照=訊號日收盤(紙上版),k20並排揭露侵蝕;訊號日漲停(漲幅>=+9%)另旗標=買不到風險。
結果: k=5/10/20/40/60(波段焦點),絕對+demean(減TAIEX)並列(第13條),勝率/賺賠比(第15/17條),
  同日配對=同日流動池「非新高股」均值當對照(拆「新高多=多頭市」的日期組成效應,第11條),
  月群bootstrap+逐年;題材成員(classification台)vs非成員交乘(使用者原話「題材股」)。
已知限制: fm_daily_price未還原除權息(長窗保守偏誤);demean一律用TAIEX(上櫃成員未分流);
延續新高版同股連日重複觸發(月群集群處理);多重比較(N×2版×5窗)判讀靠形狀與逐年非單格CI。

用法: python 研究腳本/綜合策略/build_newhigh_breakout_swing.py  (從根目錄執行,鐵律)
產出: 研究報告/research_newhigh_swing.html + console
"""
import json
import sqlite3
import sys
import time

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

DB = "capital_flow.db"
OUT = "研究報告/research_newhigh_swing.html"
START = "2015-01-01"
N_LIST = [60, 90, 240]
K_LIST = [5, 10, 20, 40, 60]
LIQ_MIN = 0.3e8           # 20日均額(前一日止)
FRESH_GAP = 20            # 獨立突破=前20交易日內無N日新高
LIMITUP_TH = 0.09         # 訊號日漲幅>=+9%≈漲停旗標
rng = np.random.default_rng(20260805)


def load():
    conn = sqlite3.connect(DB, timeout=60)
    px = pd.read_sql("SELECT code,date,close,money FROM fm_daily_price "
                     "WHERE date>='2013-01-01' AND close>0 AND money>0", conn)
    tai = pd.read_sql("SELECT date,close FROM index_daily WHERE market='TAIEX' "
                      "AND date>='2013-01-01' ORDER BY date", conn)
    theme_codes = {r[0] for r in conn.execute(
        "select distinct code from classification where country='台'")}
    conn.close()
    C = px.pivot_table(index="date", columns="code", values="close", aggfunc="first").sort_index()
    MN = px.pivot_table(index="date", columns="code", values="money", aggfunc="first").sort_index()
    tai = tai.set_index("date")["close"]
    print(f"[load] 面板 {C.shape[0]}日×{C.shape[1]}檔; 題材成員{len(theme_codes)}檔")
    return C, MN, tai, theme_codes


def main():
    t0 = time.time()
    C, MN, tai, theme_codes = load()
    dates = np.array(C.index)
    start_i = int(np.searchsorted(dates, START))
    liq_ok = (MN.rolling(20, min_periods=15).mean().shift(1) >= LIQ_MIN)
    ret1 = C.pct_change(fill_method=None)
    Cf = C.ffill(limit=5)
    tai_r = tai.reindex(C.index)
    is_theme = np.array([c in theme_codes for c in C.columns])

    all_out = {}
    for N in N_LIST:
        rmax = C.rolling(N, min_periods=int(N * 0.8)).max()
        is_hi = (C >= rmax * 0.9999) & C.notna()
        hi_recent = is_hi.shift(1).rolling(FRESH_GAP, min_periods=1).max()   # 前20日內曾新高
        events = []
        max_k = max(K_LIST)
        for i in range(start_i, len(dates) - max_k - 1):
            row = is_hi.iloc[i].values & liq_ok.iloc[i].values
            if not row.any():
                continue
            idxs = np.where(row)[0]
            t = dates[i]
            e_i = i + 1
            # 同日對照: 流動池內「非新高」股的次日收盤進場k報酬(之後配對用)
            for ci in idxs:
                e1 = C.iat[e_i, ci]
                if pd.isna(e1) or e1 <= 0:
                    continue
                rec = {"code": C.columns[ci], "t": t,
                       "fresh": not bool(hi_recent.iat[i, ci]),
                       "limitup": bool(ret1.iat[i, ci] >= LIMITUP_TH) if pd.notna(ret1.iat[i, ci]) else False,
                       "theme": bool(is_theme[ci]),
                       "paper20": (Cf.iat[i + 20, ci] / C.iat[i, ci] - 1) if pd.notna(C.iat[i, ci]) else np.nan}
                ok = True
                for k in K_LIST:
                    x = Cf.iat[e_i + k, ci]
                    if pd.isna(x):
                        ok = False
                        break
                    b = tai_r.iloc[e_i + k] / tai_r.iloc[e_i] - 1
                    rec[f"r{k}"] = x / e1 - 1
                    rec[f"dm{k}"] = rec[f"r{k}"] - b
                if ok:
                    events.append(rec)
        E = pd.DataFrame(events)
        E["month"] = E["t"].str[:7]
        E["year"] = E["t"].str[:4]
        all_out[N] = E
        print(f"[N={N}] 事件{len(E):,}筆(獨立突破{E.fresh.sum():,} 訊號日漲停{E.limitup.sum():,} "
              f"題材成員{E.theme.sum():,}) {E.t.min()}~{E.t.max()}  [{time.time() - t0:.0f}s]")

    # 同日流動池基準(非新高): 抽樣算(全算太重)——每日流動池內非任何N新高的股票均值
    # 用N=60的is_hi當「新高家族」定義做對照池
    N0 = 60
    rmax0 = C.rolling(N0, min_periods=48).max()
    is_hi0 = (C >= rmax0 * 0.9999) & C.notna()

    def build_ctrl(theme_only):
        """對照池: 流動池×非新高日;theme_only=True時限題材成員(拆『成員本身就強』的名單溢價,
        這是題材成員新高組的正確基準——事後名單偏誤下,成員任何日子都可能贏大盤)。"""
        rows = []
        for i in range(start_i, len(dates) - max(K_LIST) - 1, 3):     # 每3日抽樣,夠密
            mask = liq_ok.iloc[i].values & C.iloc[i].notna().values & (~is_hi0.iloc[i].values)
            if theme_only:
                mask = mask & is_theme
            if mask.sum() < 20:
                continue
            e_i = i + 1
            e1 = C.iloc[e_i].values
            rec = {"t": dates[i]}
            okk = True
            for k in K_LIST:
                x = Cf.iloc[e_i + k].values
                with np.errstate(invalid="ignore", divide="ignore"):
                    rr = np.where((e1 > 0) & mask, x / e1 - 1, np.nan)
                b = tai_r.iloc[e_i + k] / tai_r.iloc[e_i] - 1
                v = np.nanmean(rr)
                if not np.isfinite(v):
                    okk = False
                    break
                rec[f"r{k}"] = v
                rec[f"dm{k}"] = v - b
            if okk:
                rows.append(rec)
        df = pd.DataFrame(rows)
        df["month"] = df["t"].str[:7]
        return df

    CTRL = build_ctrl(False)
    CTRL_TH = build_ctrl(True)
    print(f"[ctrl] 同日非新高對照池: 全池{len(CTRL):,}日 / 題材成員限定{len(CTRL_TH):,}日")

    def boot(vals, months, n_iter=1000):
        v = pd.DataFrame({"v": vals, "m": months}).dropna()
        if len(v) < 15 or v.m.nunique() < 6:
            return None
        grp = {k: g.v.values for k, g in v.groupby("m")}
        keys = list(grp)
        means = [np.mean(np.concatenate([grp[k] for k in rng.choice(keys, len(keys))]))
                 for _ in range(n_iter)]
        lo, hi = np.percentile(means, [2.5, 97.5])
        return {"mean": float(v.v.mean()), "lo": float(lo), "hi": float(hi),
                "sig": bool(lo > 0 or hi < 0)}

    def stats_block(E, lab):
        if len(E) < 50:
            print(f"  {lab}: n={len(E)}不足")
            return None
        out = {"lab": lab, "n": len(E), "n_lock": int(E.limitup.sum())}
        for k in K_LIST:
            r = E[f"r{k}"]
            w, l = r[r > 0], r[r <= 0]
            b = boot(E[f"dm{k}"].values, E.month.values)
            out[k] = {"abs": r.mean() * 100, "med": r.median() * 100,
                      "dm": E[f"dm{k}"].mean() * 100,
                      "win": len(w) / len(r) * 100,
                      "wl": (w.mean() / abs(l.mean())) if len(w) and len(l) else np.nan,
                      "boot": b}
        y = E.groupby("year")[f"dm20"].mean()
        out["yr20"] = f"{int((y > 0).sum())}/{len(y)}"
        y40 = E.groupby("year")[f"dm40"].mean()
        out["yr40"] = f"{int((y40 > 0).sum())}/{len(y40)}"
        s = out[20]
        print(f"  {lab:<34} n={out['n']:>7,}(鎖{out['n_lock']:,}) "
              f"k20絕對{s['abs']:+.2f}%/demean{s['dm']:+.2f}% 勝率{s['win']:.0f}% 賺賠{s['wl']:.2f} "
              + (f"CI[{s['boot']['lo'] * 100:+.2f},{s['boot']['hi'] * 100:+.2f}]"
                 f"{'✓' if s['boot']['sig'] else ''}" if s["boot"] else "")
              + f" k40dm{out[40]['dm']:+.2f}% k60dm{out[60]['dm']:+.2f}% 逐年20/40:{out['yr20']}/{out['yr40']}")
        return out

    print("\n" + "=" * 96)
    print("創新高突破·波段延續性  (進場=次日收盤,絕對+demean並列,k=5~60)")
    print("=" * 96)
    results = {}
    for N in N_LIST:
        E = all_out[N]
        print(f"\n【N={N}日新高】")
        results[(N, "all")] = stats_block(E, f"(a)延續新高(全部新高日)")
        results[(N, "fresh")] = stats_block(E[E.fresh], f"(b)獨立突破(前{FRESH_GAP}日無新高)")
        results[(N, "fresh_nolock")] = stats_block(E[E.fresh & ~E.limitup], f"(b')獨立突破×排訊號日漲停")
        results[(N, "fresh_theme")] = stats_block(E[E.fresh & E.theme], f"(b)獨立突破×題材成員")
        results[(N, "fresh_nontheme")] = stats_block(E[E.fresh & ~E.theme], f"(b)獨立突破×非題材成員")

    # 對照池
    print("\n【同日非新高對照池(N=60定義,抽樣日均值)】")
    ctrl_line, ctrl_th_line = {}, {}
    for k in K_LIST:
        ctrl_line[k] = {"abs": CTRL[f"r{k}"].mean() * 100, "dm": CTRL[f"dm{k}"].mean() * 100}
        ctrl_th_line[k] = {"abs": CTRL_TH[f"r{k}"].mean() * 100, "dm": CTRL_TH[f"dm{k}"].mean() * 100}
        print(f"  k{k}: 全池絕對{ctrl_line[k]['abs']:+.2f}%/demean{ctrl_line[k]['dm']:+.2f}%  "
              f"題材成員限定絕對{ctrl_th_line[k]['abs']:+.2f}%/demean{ctrl_th_line[k]['dm']:+.2f}%")
    print("  ⚠題材成員非新高日的demean=「名單溢價」基準(classification是現在編的名單回填歷史,"
          "事後名單偏誤);題材成員新高組的真突破溢價=其demean減去此基準")

    # 紙上vs可執行(N=90獨立突破)
    E90 = all_out[90]
    fr = E90[E90.fresh]
    paper = fr["paper20"].mean() * 100
    real = fr["r20"].mean() * 100
    print(f"\n【可執行性(N=90獨立突破)】訊號日收盤進場k20={paper:+.2f}%(紙上) vs 次日收盤進場={real:+.2f}%"
          f" → 隔夜+首日侵蝕{paper - real:+.2f}pp")

    # ---------- HTML ----------
    CSS = """
body{background:#1a1a19;color:#fff;font-family:"Noto Sans TC",sans-serif;margin:24px;max-width:1200px}
h1{font-size:20px} h2{font-size:15px;color:#c3c2b7;margin-top:30px;border-bottom:1px solid #333;padding-bottom:4px}
table{border-collapse:collapse;font-size:12.5px;font-variant-numeric:tabular-nums;margin:8px 0}
td,th{border:1px solid #333;padding:4px 8px;text-align:right} th{text-align:left;color:#c3c2b7}
.note{color:#8a8878;font-size:12.5px;line-height:1.8} .good{color:#7ec97e} .bad{color:#e06c5a}
.hl{background:#2b3a2b}
ul{margin:4px 0;padding-left:20px;font-size:12.5px;color:#ccc;line-height:1.7}
.verdict{font-size:13px;font-weight:bold;padding:6px 10px;border-radius:4px;display:inline-block;margin:4px 0}
.v-good{background:#243b24;color:#7ec97e} .v-bad{background:#3b2420;color:#e06c5a}
.v-warn{background:#3b3420;color:#c3a55a}
.scroll{overflow-x:auto}
"""

    def row_html(key, hl=False):
        r = results.get(key)
        if r is None:
            return ""
        cells = ""
        for k in K_LIST:
            s = r[k]
            ci = (f"<br><span style='color:#777;font-size:10.5px'>[{s['boot']['lo'] * 100:+.2f},"
                  f"{s['boot']['hi'] * 100:+.2f}]{'✓' if s['boot']['sig'] else ''}</span>" if s["boot"] else "")
            cells += (f"<td>{s['abs']:+.2f}<br><b>{s['dm']:+.2f}</b>{ci}</td>")
        s20 = r[20]
        return (f"<tr{' class=hl' if hl else ''}><th>{r['lab']}</th><td>{r['n']:,}<br>鎖{r['n_lock']:,}</td>"
                f"{cells}<td>{s20['win']:.0f}%</td><td>{s20['wl']:.2f}</td>"
                f"<td>{r['yr20']}<br>{r['yr40']}</td></tr>")

    khead = "".join(f"<th>k{k}絕對/<b>demean</b></th>" for k in K_LIST)
    tables = ""
    for N in N_LIST:
        tables += (f"<h2>N={N}日新高</h2><div class='scroll'><table>"
                   f"<tr><th>組</th><th>n</th>{khead}<th>k20勝率</th><th>k20賺賠比</th><th>逐年20/40</th></tr>"
                   + row_html((N, "all"))
                   + row_html((N, "fresh"), hl=True)
                   + row_html((N, "fresh_nolock"))
                   + row_html((N, "fresh_theme"))
                   + row_html((N, "fresh_nontheme"))
                   + "</table></div>")
    ctrl_html = "".join(f"<td>{ctrl_line[k]['abs']:+.2f}/<b>{ctrl_line[k]['dm']:+.2f}</b></td>" for k in K_LIST)
    ctrl_th_html = "".join(f"<td>{ctrl_th_line[k]['abs']:+.2f}/<b>{ctrl_th_line[k]['dm']:+.2f}</b></td>" for k in K_LIST)

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>創新高突破·波段延續性(2026-08-05)</title><style>{CSS}</style></head><body>
<h1>📈 創新高突破(60/90/240日)·波段延續性考卷</h1>
<div class="note">使用者假說:「題材股價創新高(90天/60天)有機會比較長的波段獲利」。
池=20日均額>=0.3億(前一日止);(a)延續新高=所有新高日,(b)獨立突破=前{FRESH_GAP}日無新高的首破日;
進場=<b>次日收盤</b>(可執行,同週級動能活口口徑);絕對/demean(減TAIEX)並列;月群bootstrap。
既有相關判決: 題材觸發後用創新高選成員=null(theme_member_selection)/週高giveback=延續力旁證/
美股題材側新高=短窗反轉長窗平(獨漲線)。</div>
{tables}
<h2>同日非新高對照池(拆「新高多=多頭市」日期組成 + 題材成員「名單溢價」基準)</h2>
<div class='scroll'><table><tr><th>對照池(非新高日,抽樣{len(CTRL):,}日)</th>{"".join(f"<th>k{k}</th>" for k in K_LIST)}</tr>
<tr><th>全流動池 絕對/<b>demean</b></th>{ctrl_html}</tr>
<tr><th>題材成員限定 絕對/<b>demean</b></th>{ctrl_th_html}</tr></table></div>
<div class="note">⚠<b>事後名單偏誤警戒</b>: classification題材名單是「現在」編的,回填歷史=可能挑到
事後才變重要的股票。「題材成員限定非新高日」列=名單本身的溢價基準——題材成員新高組的
<b>真突破溢價=其demean−此基準</b>,不能直接拿demean當突破的功勞。</div>
<h2>可執行性</h2>
<div class="note">N=90獨立突破: 訊號日收盤(紙上)k20={paper:+.2f}% vs 次日收盤進場={real:+.2f}%,
隔夜+首日侵蝕{paper - real:+.2f}pp;「鎖」欄=訊號日漲幅>=+9%(漲停鎖死風險,b'列=排除後)。</div>
<h2>⚖️ 判決(2026-08-05首輪)</h2>
<ul>
<li><span class="verdict v-good">①假說核心成立——但只在「題材成員」身上,且使用者原話「題材股」精準命中</span>
獨立突破×題材成員: 90日k20 demean+1.52%✓[+0.92,+2.16]/k60+4.22%,240日k20+2.14%✓/k60+6.16%,
勝率52-53%/賺賠比1.76-1.79/逐年k40 demean 12/12全正(含2022熊市)——波段(1-3個月)持續累積,
正是使用者說的「比較長的波段獲利」形狀。</li>
<li><span class="verdict v-bad">②非題材成員的新高突破=負溢價,避開</span> 60日k20-1.32%✓為負/k60-3.86%,
90日-1.01%——<b>沒有題材故事撐的孤兒突破是假突破</b>,追進去輸給大盤。全市場混合版因此被稀釋
(60/90日null,240日僅+0.89✓薄)。</li>
<li><span class="verdict v-warn">③名單溢價扣除後仍活,但事後名單偏誤=最大保留</span>
題材成員「非新高日」基準demean k20+0.56/k40+1.13/k60+1.80(classification是現在編的名單回填歷史,
成員本來就偏強)——淨突破溢價=90日k60約+2.4pp/240日k60約+4.4pp,90/240日CI下緣仍高於基準
(60日壓線)。無歷史時點題材名單可完全排除此偏誤,定位<b>候選層</b>,靠live累積樣本外驗證。</li>
<li><b>④新高窗單調: 越長越強(240&gt;90&gt;60)</b>——與行為財務52週高錨定效應(George&Hwang)一致;
使用者選的60/90日成立但52週(240日)新高更肥,60日是三者中最弱(扣基準後壓線)。</li>
<li><b>⑤可執行性過關</b>: 隔夜+首日侵蝕僅+0.53pp(vs獨漲線的跳空過衝溫和許多),排訊號日漲停後
240日版仍✓——次日收盤進場可行。</li>
<li><b>⑥實務翻譯</b>: 「題材成員股突破90日/52週新高(前20日未曾新高的首破)→次日收盤進場,
波段持有1-3個月」=候選規則;與毛利率QoQ資格門檻(fundamental_momo卷)同屬季級持股層,
兩者交乘是自然下一步;與獨漲訊號互補(獨漲=隔夜事件快訊號,新高突破=個股慢訊號)。</li>
</ul>
<h2>已知限制</h2>
<div class="note">①fm_daily_price未還原除權息(長窗保守偏誤,新高股常配息,k40/60絕對報酬低估);
②demean一律減TAIEX(上櫃成員未分流);③(a)版同股連日重複觸發,統計靠月群集群,n非獨立股數;
④多重比較(3N×5組×5窗)判讀靠跨N一致性+逐年,不靠單格CI;⑤獨立突破的{FRESH_GAP}日盤整定義為
研究者選擇,未做敏感度。</div>
<div class="note">維運: python 研究腳本/綜合策略/build_newhigh_breakout_swing.py(從根目錄執行)。
姊妹卷: build_theme_member_selection.py(題材觸發後選股null)、build_weekly_momo_pathshape_overlay.py
(週高giveback)、build_us_tw_pocket_refine.py(獨漲線)。</div>
</body></html>"""
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n[report] 已輸出 {OUT}  總耗時{time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
