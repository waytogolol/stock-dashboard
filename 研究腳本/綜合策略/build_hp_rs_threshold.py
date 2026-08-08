# -*- coding: utf-8 -*-
"""高價股RS溫度計·參數敏感度考卷(2026-08-07,使用者自省「前5%是我亂訂的,要驗證」)。

背景: high_price_followup卷的RS溫度計(池內前5%籃子近3月RS>0→下月TAIEX+2.25%/勝率69% vs
+0.13%/55%,價差+2.12pp)已通過20組隨機安慰劑並上儀表板🌡️頁——但**門檻5%與窗口3月都是隨手訂的**。
本卷做二維敏感度: 門檻(1/3/5/10/20/30%+絕對>=500/>=1000元) × RS窗(1/2/3/6月)。

═══ 判準(預先註冊) ═══
穩健=**高原**(相鄰參數格數字接近、符號一致),過擬合=**尖峰**(只有特定格漂亮,鄰格崩掉)。
主指標=下月TAIEX報酬價差(RS>0組 − RS<=0組,pp);輔=勝率差、corr、n平衡度。
另附: 每格的隨機安慰劑對照(同檔數隨機抽樣20組的價差分布中位),看該格是否高於雜訊水位。
口徑同母卷: 月頻(月初收盤調倉),池=20日均額>=0.3億,毛報酬,2015起。
用法: python 研究腳本/綜合策略/build_hp_rs_threshold.py  (從根目錄執行,鐵律)
產出: 研究報告/research_hp_rs_threshold.html + console
"""
import sys
import sqlite3

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

DB = "capital_flow.db"
OUT = "研究報告/research_hp_rs_threshold.html"
LIQ_MIN = 0.3e8
PCTS = [1, 3, 5, 10, 20, 30]
ABS_LEVELS = [500, 1000]
WINDOWS = [1, 2, 3, 6]
rng = np.random.default_rng(20260807)


def main():
    conn = sqlite3.connect(DB, timeout=60)
    px = pd.read_sql("SELECT code,date,close,money FROM fm_daily_price "
                     "WHERE date>='2014-06-01' AND close>0 AND money>0", conn)
    tai = pd.read_sql("SELECT date,close FROM index_daily WHERE market='TAIEX' "
                      "AND date>='2014-06-01' ORDER BY date", conn)
    conn.close()
    C = px.pivot_table(index="date", columns="code", values="close", aggfunc="first").sort_index()
    MN = px.pivot_table(index="date", columns="code", values="money", aggfunc="first").sort_index()
    tai = tai.set_index("date")["close"].reindex(C.index).ffill()
    Cf = C.ffill(limit=5)
    dates = list(C.index)
    liq_prev = MN.rolling(20, min_periods=15).mean().shift(1)
    didx = pd.to_datetime(pd.Index(dates))
    f_idx = [i for i in np.where(~didx.to_period("M").duplicated())[0]
             if dates[i] >= "2015-01-01" and i + 1 < len(dates)]
    tai_m = np.array([tai.iloc[b] / tai.iloc[a] - 1 for a, b in zip(f_idx[:-1], f_idx[1:])])

    def group_month_rets(selector):
        out, sizes = [], []
        for a, b in zip(f_idx[:-1], f_idx[1:]):
            pr = C.iloc[a].where(liq_prev.iloc[a] >= LIQ_MIN).dropna()
            codes = selector(pr)
            rets = []
            for c in codes:
                ci = Cf.columns.get_loc(c)
                p0, p1 = C.iat[a, ci], Cf.iat[b, ci]
                if pd.notna(p0) and pd.notna(p1) and p0 > 0:
                    rets.append(p1 / p0 - 1)
            out.append(np.mean(rets) if rets else np.nan)
            sizes.append(len(rets))
        return np.array(out), float(np.mean(sizes))

    def rs_stats(grp_m, win):
        rs = grp_m - tai_m
        rs_w = pd.Series(rs).rolling(win).mean().values
        nxt = np.roll(tai_m, -1)[:-1]
        r = rs_w[:-1]
        ok = ~np.isnan(r) & ~np.isnan(nxt)
        pos, neg = nxt[ok & (r > 0)], nxt[ok & (r <= 0)]
        if len(pos) < 10 or len(neg) < 10:
            return None
        return {"diff": (np.mean(pos) - np.mean(neg)) * 100,
                "pos_m": np.mean(pos) * 100, "neg_m": np.mean(neg) * 100,
                "pos_w": (pos > 0).mean() * 100, "neg_w": (neg > 0).mean() * 100,
                "win_diff": ((pos > 0).mean() - (neg > 0).mean()) * 100,
                "n_pos": len(pos), "n_neg": len(neg),
                "corr": float(np.corrcoef(r[ok], nxt[ok])[0, 1])}

    print("① 門檻 × RS窗 二維敏感度(數字=下月TAIEX價差pp: RS>0組 − RS<=0組)")
    header = "  " + "門檻\\窗".ljust(16) + "".join(f"{w}月".rjust(9) for w in WINDOWS) + "   平均檔數"
    print(header)
    grid, sizes = {}, {}
    for p in PCTS:
        gm, sz = group_month_rets(lambda pr, _p=p: list(pr.index[pr >= pr.quantile(1 - _p / 100)]))
        sizes[f"前{p}%"] = sz
        row = []
        for w in WINDOWS:
            st = rs_stats(gm, w)
            grid[(f"前{p}%", w)] = st
            row.append(f"{st['diff']:+.2f}" if st else "—")
        print("  " + f"前{p}%".ljust(16) + "".join(x.rjust(9) for x in row) + f"   {sz:.0f}")
    for lv in ABS_LEVELS:
        gm, sz = group_month_rets(lambda pr, _l=lv: list(pr.index[pr >= _l]))
        sizes[f">={lv}元"] = sz
        row = []
        for w in WINDOWS:
            st = rs_stats(gm, w)
            grid[(f">={lv}元", w)] = st
            row.append(f"{st['diff']:+.2f}" if st else "—")
        print("  " + f">={lv}元".ljust(16) + "".join(x.rjust(9) for x in row) + f"   {sz:.0f}")

    print("\n② 主格(前5%×3月)明細 + 鄰格對照")
    for key in [("前3%", 3), ("前5%", 3), ("前10%", 3), ("前5%", 2), ("前5%", 6)]:
        st = grid.get(key)
        if st:
            print(f"  {key[0]}×{key[1]}月: 價差{st['diff']:+.2f}pp "
                  f"({st['pos_m']:+.2f}%/勝{st['pos_w']:.0f}% vs {st['neg_m']:+.2f}%/勝{st['neg_w']:.0f}%) "
                  f"勝率差{st['win_diff']:+.0f}pp corr={st['corr']:+.3f} n={st['n_pos']}/{st['n_neg']}")

    print("\n③ 隨機安慰劑水位(同檔數隨機抽樣20組,取價差中位/P95;窗=3月)")
    plac = {}
    for lab, n_take in [("前1%", sizes["前1%"]), ("前5%", sizes["前5%"]),
                        ("前20%", sizes["前20%"])]:
        ds = []
        for k in range(20):
            rk = np.random.default_rng(500 + k)
            gm, _ = group_month_rets(
                lambda pr, _n=int(round(n_take)), _r=rk: list(_r.choice(pr.index, size=min(_n, len(pr)),
                                                                       replace=False)))
            st = rs_stats(gm, 3)
            if st:
                ds.append(st["diff"])
        ds = np.array(ds)
        plac[lab] = {"med": float(np.median(ds)), "p95": float(np.percentile(ds, 95)),
                     "n": int(round(n_take))}
        real = grid[(lab, 3)]["diff"]
        print(f"  {lab}(約{plac[lab]['n']}檔): 真實{real:+.2f}pp vs 安慰劑中位{plac[lab]['med']:+.2f}"
              f"/P95{plac[lab]['p95']:+.2f} → {'高於P95✓' if real > plac[lab]['p95'] else '未超過P95⚠'}")

    # ---------- HTML ----------
    CSS = """
body{background:#1a1a19;color:#fff;font-family:"Noto Sans TC",sans-serif;margin:24px;max-width:1000px}
h1{font-size:20px} h2{font-size:15px;color:#c3c2b7;margin-top:26px;border-bottom:1px solid #333;padding-bottom:4px}
table{border-collapse:collapse;font-size:12.5px;font-variant-numeric:tabular-nums;margin:8px 0}
td,th{border:1px solid #333;padding:5px 10px;text-align:right} th{text-align:left;color:#c3c2b7}
.note{color:#8a8878;font-size:12.5px;line-height:1.8} .good{color:#7ec97e} .bad{color:#e06c5a}
.hl{background:#2b3a2b;font-weight:bold}
ul{margin:4px 0;padding-left:20px;font-size:12.5px;color:#ccc;line-height:1.7}
"""
    rows_html = ""
    for lab in [f"前{p}%" for p in PCTS] + [f">={lv}元" for lv in ABS_LEVELS]:
        cells = ""
        for w in WINDOWS:
            st = grid.get((lab, w))
            if st is None:
                cells += "<td>—</td>"
                continue
            cls = "hl" if (lab == "前5%" and w == 3) else ("good" if st["diff"] > 1 else
                                                          ("bad" if st["diff"] < 0 else ""))
            cells += (f"<td class='{cls}'>{st['diff']:+.2f}<br>"
                      f"<span style='color:#777;font-size:10.5px'>勝率差{st['win_diff']:+.0f}pp</span></td>")
        rows_html += f"<tr><th>{lab}</th>{cells}<td>{sizes[lab]:.0f}</td></tr>"
    grid_html = ("<table><tr><th>門檻＼RS窗</th>" + "".join(f"<th>{w}月</th>" for w in WINDOWS)
                 + "<th>平均檔數</th></tr>" + rows_html + "</table>")
    plac_html = ("<table><tr><th>組</th><th>真實價差</th><th>安慰劑中位</th><th>安慰劑P95</th><th>判定</th></tr>"
                 + "".join(f"<tr><th>{k}(約{v['n']}檔)</th><td>{grid[(k, 3)]['diff']:+.2f}pp</td>"
                           f"<td>{v['med']:+.2f}</td><td>{v['p95']:+.2f}</td>"
                           f"<td>{'✓高於P95' if grid[(k, 3)]['diff'] > v['p95'] else '⚠未超過'}</td></tr>"
                           for k, v in plac.items()) + "</table>")

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>高價RS門檻敏感度(2026-08-07)</title><style>{CSS}</style></head><body>
<h1>🎚️ 高價股RS溫度計·參數敏感度: 門檻幾% × RS看幾個月</h1>
<div class="note">使用者自省「前5%是隨手訂的」。判準=<b>高原(相鄰格接近且同號)</b>才穩健,
<b>尖峰(只有一格好)</b>=過擬合。數字為下月TAIEX報酬價差(RS>0組 − RS<=0組,pp);
月頻月初調倉、池=20日均額>=0.3億、2015起。<b>綠底=母卷採用的前5%×3月</b>。</div>
<h2>① 二維敏感度矩陣</h2>
{grid_html}
<h2>② 隨機安慰劑水位對照(窗=3月)</h2>
{plac_html}
<h2>⚖️ 判決(2026-08-07)</h2>
<ul>
<li><span style="background:#243b24;color:#7ec97e;padding:6px 10px;border-radius:4px;font-weight:bold">
①5%不是亂訂,但也不是最佳——<b>真正的結構是「前1~5% × 2~3月」的高原</b></span>
該區6格全部落在+1.54~+2.62pp(前1%×2月+2.62最高、前3%×3月+2.00、前5%×3月+2.12),
相鄰格同號同量級=<b>高原不是尖峰</b>,訊號穩健。絕對門檻版(>=500元+1.51~+1.66、>=1000元+1.46~+1.80)
也落在同一帶=不管用相對還是絕對定義「高價」,結論一致。</li>
<li><span style="background:#3b2420;color:#e06c5a;padding:6px 10px;border-radius:4px;font-weight:bold">
②門檻放太寬會死: 10%以上崩掉</span>
前10%×3月僅+0.30、前20%全帶±0.6內、前30%多數為負;<b>安慰劑檢定確認</b>: 前1%/前5%真實值
高於隨機分布P95✓,前20%(-0.02)未超過(P95+1.17)——<b>「高價」的資訊只存在於夠集中的頂端</b>,
稀釋成前20%就變回大盤本身。</li>
<li><span style="background:#3b3420;color:#c3a55a;padding:6px 10px;border-radius:4px;font-weight:bold">
③窗比門檻更敏感: 1個月版會翻負</span>
前5%×1月=-0.41、前20%×1月=-0.60——單月RS雜訊太大(個股事件主導);
6月版也衰減(前5%僅+0.74)=太慢。<b>2~3月是甜蜜區</b>。</li>
<li><b>④動作(已執行)</b>: 儀表板🌡️位階風險改用<b>6格平均</b>(門檻1/3/5% × 窗2/3月)當讀數,
並顯示各格數值與「幾格為正」——避免單格抖動造成的假訊號翻轉;判讀時看<b>方向一致性</b>
(6格全正/全負最可信,3:3=中性別當訊號)。</li>
</ul>
<div class="note">維運: python 研究腳本/綜合策略/build_hp_rs_threshold.py(從根目錄執行)。
母卷: research_high_price_followup.html(RS三關安慰劑)、儀表板🌡️頁位階風險區塊。</div>
</body></html>"""
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n[report] 已輸出 {OUT}")


if __name__ == "__main__":
    main()
