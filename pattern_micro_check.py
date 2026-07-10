# -*- coding: utf-8 -*-
"""微題材樣本內(2022-2024)型態分層檢查
重用 pattern_mining_2022.py 全環境(macro train/日線快取/型態函式/凍結聚類中心)
輸出: tmp_micro_shape.txt
"""
exec(open("pattern_mining_2022.py", encoding="utf-8").read())   # noqa — 建立完整環境

import sqlite3
from micro_themes import MICRO_THEMES

macro_train = train
_conn = sqlite3.connect("research_2022.db")
subp2 = pd.read_sql("SELECT code, sub_product FROM classification WHERE country='台'", _conn)
_conn.close()
subp2 = subp2.groupby("code")["sub_product"].apply(lambda s: " ".join(str(x) for x in s if pd.notna(x)))
tw2 = rankings[rankings["country"] == "台"]
tw_tot2 = tw2.groupby("snapshot_date")["twd"].sum().to_dict()

mm = {}
for name, cfg in MICRO_THEMES.items():
    kws, excl = cfg["kws"], set(cfg.get("exclude", []))
    m = set(c for c, t in subp2.items() if any(k.lower() in t.lower() for k in kws)) - excl
    if len(m) >= 3:
        mm[name] = m

mtrain = []
for name, mem in mm.items():
    sc, rk = [], []
    for d in dates:
        wk = tw2[(tw2["snapshot_date"] == d) & (tw2["code"].isin(mem))]
        tot = tw_tot2.get(d, 0)
        sc.append(float(wk["twd"].sum() / tot * 100) if tot > 0 else 0.0)
        rk.append(dict(zip(wk["code"], wk["rank"])))
    last = -99
    for t in range(13, len(dates)):
        med4 = float(np.median(sc[t - 4:t]))
        if med4 <= 0 or sc[t] / med4 < 2.5:
            continue
        jumps = [rk[t - 1][c] - rk[t][c] for c in rk[t] if c in rk[t - 1]]
        if not jumps or float(np.median(jumps)) < 35:
            continue
        if t - last < 4:
            last = t
            continue
        last = t
        if dates[t] > TRAIN_END:
            continue
        top3m = sorted(rk[t], key=lambda c: rk[t][c])[:3]
        mtrain.append({"theme": name, "date": dates[t], "members": top3m})

for h in mtrain:
    rs = [px_ret8(m, str(h["date"])) for m in h["members"]]
    rs = [r for r in rs if r is not None]
    h["pret8"] = sum(rs) / len(rs) if rs else None
mtrain = [h for h in mtrain if h["pret8"] is not None]

for h in mtrain:
    ws = {m: hist(m, str(h["date"])) for m in h["members"]}
    h["A2"] = sum(1 for w in ws.values() if w is not None and pat_new_high(w, 60)) >= 2
    h["A5"] = any(pat_gap_nh(w) for w in ws.values() if w is not None)
    labs = []
    for w in ws.values():
        if w is None or len(w) < 60:
            continue
        p = w["Close"].tail(60).values.astype(float)
        z = (p - p.mean()) / (p.std() + 1e-9)
        labs.append(int(((z[None, :] - cent) ** 2).sum(axis=1).argmin()))
    if labs:
        vals, cnts = np.unique(labs, return_counts=True)
        h["shape"] = int(vals[cnts.argmax()])
    else:
        h["shape"] = None

o2 = io.open("tmp_micro_shape.txt", "w", encoding="utf-8")
bp = pd.Series([h["pret8"] for h in mtrain])
o2.write(f"微題材樣本內 n={len(mtrain)} 基準勝率{(bp > 0).mean():.0%} 中位{bp.median():+.1%}\n\n")


def rep2(sel, label):
    pr = pd.Series([h["pret8"] for h in sel])
    if not len(pr):
        o2.write(f"{label}: 0筆\n")
        return
    o2.write(f"{label}: n={len(pr)} 勝率{(pr > 0).mean():.0%} 中位{pr.median():+.1%}\n")


rep2([h for h in mtrain if h["A2"]], "A2 60日新高≥2/3")
rep2([h for h in mtrain if h["A5"]], "A5 突破跳空≥1")
rep2([h for h in mtrain if not h["A2"] and not h["A5"]], "兩者皆無")
o2.write("\n形狀分佈(大題材凍結中心分類):\n")
for k in range(K):
    sel = [h for h in mtrain if h["shape"] == k]
    if sel:
        pr = pd.Series([h["pret8"] for h in sel])
        o2.write(f"  形狀{k}[{describe(cent[k])}]: n={len(sel)} 勝率{(pr > 0).mean():.0%} 中位{pr.median():+.1%}\n")
o2.write("\n逐筆:\n")
for h in sorted(mtrain, key=lambda x: x["date"]):
    o2.write(f"  {h['date']} {h['theme']:<12} 形狀{h['shape']} A2{'✓' if h['A2'] else '×'} A5{'✓' if h['A5'] else '×'} {h['pret8']:+.1%}\n")
o2.close()
print("done -> tmp_micro_shape.txt")

# ── 型態探勘章節注入 research_2022_report.html ──
s = "<h2>🔬 型態探勘（嚴格樣本內 2022-2024，n=94；保留集未觸碰）</h2>"
s += f"<div class='note'>三路線：A預註冊型態庫(定義先寫死)、B連續特徵三分位、C價格路徑形狀聚類(演算法自己找型態)。基準：勝率{(base > 0).mean():.0%} 中位{base.median():+.1%}。晉級標準=樣本內逐年一致+跑贏基準。</div>"
s += "<h2>路線A：預註冊型態庫</h2><table><tr><th>型態</th><th>n</th><th>勝率</th><th>中位+8週</th><th>逐年勝出</th></tr>"
for name, n_, win, med, oky in sorted(resA, key=lambda x: -x[3]):
    s += f"<tr><th>{name}</th><td>{n_}</td><td>{win:.0%}</td><td>{med:+.1%}</td><td>{oky}/3</td></tr>"
s += "</table>"
s += "<h2>路線B：連續特徵（金塊：量能趨勢與波動擴張單調有效；相對強度無效）</h2>"
s += "<table><tr><th>特徵</th><th>低分位</th><th>中分位</th><th>高分位</th><th>單調性</th></tr>"
for f in ["dist_high", "squeeze", "vol_trend", "rs65", "above_ma20", "ret20"]:
    vals = [(h[f"F_{f}"], h["pret8"]) for h in train if h.get(f"F_{f}") is not None]
    if len(vals) < 30:
        continue
    vals.sort()
    n3 = len(vals) // 3
    terc = [vals[:n3], vals[n3:2 * n3], vals[2 * n3:]]
    st = [(pd.Series([x[1] for x in t]).median(), (pd.Series([x[1] for x in t]) > 0).mean()) for t in terc]
    mono = "↑" if st[0][0] < st[1][0] < st[2][0] else ("↓" if st[0][0] > st[1][0] > st[2][0] else "非單調")
    s += (f"<tr><th>{f}</th>" + "".join(f"<td>{m:+.1%}(勝{w:.0%})</td>" for m, w in st) + f"<td>{mono}</td></tr>")
s += "</table>"
s += "<h2>路線C：形狀聚類（kmeans自動分群，最大發現）</h2>"
s += "<table><tr><th>形狀</th><th>描述</th><th>觸發</th><th>勝率</th><th>中位</th><th>解讀</th></tr>"
notes = {0: "🏆最佳進場：漲過一段→回檔中被資金確認", 1: "❌追高：一路噴不歇", 2: "V型反轉",
         3: "❌迴避：死題材迴光返照", 4: "洗盤後再啟動"}
for k in range(K):
    sel = [train[hi]["pret8"] for hi, l in trig_lab.items() if l == k]
    pr = pd.Series(sel)
    if len(pr):
        s += (f"<tr><th>形狀{k}</th><td>{describe(cent[k])}</td><td>{len(pr)}</td>"
              f"<td>{(pr > 0).mean():.0%}</td><td>{pr.median():+.1%}</td><td>{notes.get(k, '')}</td></tr>")
s += "</table>"
s += "<h2>微題材分層檢查（n=19，僅方向參考）</h2>"
s += f"<div class='note'>微題材基準：勝率{(bp > 0).mean():.0%} 中位{bp.median():+.1%}。關鍵分歧：A5突破跳空對大題材3/3年有效、對微題材失靈——型態藥效因訊號類型而異。</div>"
s += "<table><tr><th>配置</th><th>n</th><th>勝率</th><th>中位</th></tr>"
for label, sel in [("A2 60日新高≥2/3", [h for h in mtrain if h["A2"]]),
                   ("A5 突破跳空≥1", [h for h in mtrain if h["A5"]]),
                   ("兩者皆無", [h for h in mtrain if not h["A2"] and not h["A5"]])]:
    pr = pd.Series([h["pret8"] for h in sel])
    if len(pr):
        s += f"<tr><th>{label}</th><td>{len(pr)}</td><td>{(pr > 0).mean():.0%}</td><td>{pr.median():+.1%}</td></tr>"
s += "</table>"
# 五形狀中心長相圖 + 形狀0案例明細
import json as _json
cent_payload = {f"形狀{k}[{describe(cent[k])}]": [round(float(v), 3) for v in cent[k]] for k in range(K)}
s += "<h2>五個形狀的長相（z正規化群中心，x=觸發前60個交易日）</h2><div id='pc1' style='height:340px'></div>"
s += ("<script>const PD=" + _json.dumps(cent_payload, ensure_ascii=False) + ";"
      "const PCOL=['#3987e5','#8a8878','#199e70','#e66767','#9085e9'];"
      "Plotly.newPlot('pc1',Object.keys(PD).map((k,i)=>({y:PD[k],name:k,mode:'lines',"
      "line:{color:PCOL[i],width:i===0?3.5:1.6}})),"
      "{paper_bgcolor:'#1a1a19',plot_bgcolor:'#1a1a19',font:{color:'#c3c2b7',size:12},"
      "xaxis:{title:'觸發前交易日(0=60日前,59=觸發週)',gridcolor:'#2c2c2a'},"
      "yaxis:{title:'z分數(僅形狀,無單位)',gridcolor:'#2c2c2a'},legend:{orientation:'h',y:1.15},"
      "margin:{t:10,b:48,l:56,r:20},hovermode:'x unified'},{responsive:true});</script>")

s += "<h2>形狀0「升後回檔」案例明細（樣本內20筆）</h2>"
s += ("<div class='note'>中段漲=觸發前40~20日成員均漲幅；近段回=前20日~觸發成員均報酬。點代碼可去XQ/TV對圖。<br>"
      "<b>回檔深度測量(46檔次)</b>：波段高點→低點 平均-18.7%/中位-16.5%(四分位-13.5%~-23.7%)；"
      "低點守10日線僅2%、守月線0%、守季線9%、<b>破季線89%</b>；觸發日距高點中位-11.9%——"
      "這不是輕回踩，是跌破季線的深度洗盤後被資金訊號確認。這解釋了A8回踩不破/A6均線多頭為何失敗(要求守支撐反而篩掉贏家)，"
      "也正是均線出場策略缺的「回補紀律」的形狀：破季線出場後，等形狀0+資金訊號=回補點。</div>")
s += "<table><tr><th>日期</th><th>題材</th><th>中段漲</th><th>近段回</th><th>+8週股價</th><th>成員</th></tr>"
shape0_rows = []
for hi, l in sorted(trig_lab.items(), key=lambda x: str(train[x[0]]["date"])):
    if l != 0:
        continue
    h = train[hi]
    mids, recs = [], []
    for m in h["members"]:
        w = hist(m, str(h["date"]))
        if w is None or len(w) < 60:
            continue
        c = w["Close"].tail(60).values
        mids.append(c[39] / c[19] - 1)
        recs.append(c[59] / c[39] - 1)
    mid = float(np.mean(mids)) if mids else float("nan")
    rec = float(np.mean(recs)) if recs else float("nan")
    pret = format(h["pret8"], "+.1%") if h["pret8"] is not None else "—"
    s += (f"<tr><th>{h['date']}</th><td>{h['theme']}</td><td>{mid:+.1%}</td><td>{rec:+.1%}</td>"
          f"<td>{pret}</td><td>{'、'.join(h['members'])}</td></tr>")
    shape0_rows.append((str(h["date"]), h["theme"], mid, rec, h["pret8"], h["members"]))
s += "</table>"
with io.open("tmp_shape0_cases.txt", "w", encoding="utf-8") as f0:
    for d, th, mid, rec, p8, mems in shape0_rows:
        f0.write(f"{d} {th:<14} 中段{mid:+.1%} 近段{rec:+.1%} +8週{p8:+.1%} {'、'.join(mems)}\n")

s += ("<h2>入圍名單（待批准後開保留集，一次定案）</h2><div class='note'>"
      "大題材：A5突破跳空＋A2 60日新高＋形狀0(凍結中心最近鄰)；迴避=形狀3。"
      "微題材：A2 60日新高；形狀1/3觀察記錄。保留集=2025-26(大題材57筆+微題材14筆)，"
      "驗證後不論結果永久封卷。</div>")
sec = "<!--PATTERN_START-->" + s + "<!--PATTERN_END-->"
rp = io.open("research_2022_report.html", encoding="utf-8").read()
if "<!--PATTERN_START-->" in rp:
    import re as _re
    rp = _re.sub(r"<!--PATTERN_START-->.*?<!--PATTERN_END-->", lambda _m: sec, rp, flags=_re.S)
else:
    rp = rp.replace("</body>", sec + "</body>")
io.open("research_2022_report.html", "w", encoding="utf-8").write(rp)
print("型態探勘章節已注入 research_2022_report.html")
