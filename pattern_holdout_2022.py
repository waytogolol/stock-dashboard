# -*- coding: utf-8 -*-
"""保留集驗證(最後一槍) — 2025-2026, 陣容凍結:
大題材主案: 型態共振v1 = (A2 60日新高≥2/3 ∪ A5突破跳空≥1 ∪ 形狀0) 且非形狀3
成分歸因: A2 / A5 / 形狀0 / A2∪形狀0；微題材: A2 only
驗證後永久封卷。輸出: tmp_holdout.txt + 注入 research_2022_report.html
"""
exec(open("pattern_micro_check.py", encoding="utf-8").read())   # noqa 建立完整環境(train/cent/函式)

HOLD_CACHE = "tmp_mine_daily_hold.pkl"
mh = [h for h in hits if str(h["date"]) > TRAIN_END and h.get("pret8") is not None]
print(f"大題材保留集 {len(mh)} 筆")

# 微題材保留集觸發(同規則, 只取>TRAIN_END)
mh_micro = []
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
        if dates[t] <= TRAIN_END:
            continue
        top3m = sorted(rk[t], key=lambda c: rk[t][c])[:3]
        mh_micro.append({"theme": name, "date": dates[t], "members": top3m})
for h in mh_micro:
    rs = [px_ret8(m, str(h["date"])) for m in h["members"]]
    rs = [r for r in rs if r is not None]
    h["pret8"] = sum(rs) / len(rs) if rs else None
mh_micro = [h for h in mh_micro if h["pret8"] is not None]
print(f"微題材保留集 {len(mh_micro)} 筆")

# 保留集成員日線(範圍延伸到資料尾端)
need2 = sorted(set(m for h in mh + mh_micro for m in h["members"]))
if os.path.exists(HOLD_CACHE):
    with open(HOLD_CACHE, "rb") as f:
        dc2 = pickle.load(f)
else:
    dc2 = {}
todo2 = [c for c in need2 if c not in dc2]
for i in range(0, len(todo2), 40):
    chunk = todo2[i:i + 40]
    rem = list(chunk)
    for sfx in (".TW", ".TWO"):
        if not rem:
            break
        df0 = yf.download([f"{c}{sfx}" for c in rem], start="2024-01-01", end=str(dates[-1]),
                          interval="1d", group_by="ticker", auto_adjust=True,
                          threads=True, progress=False)
        got = []
        for c in rem:
            try:
                sub = (df0[f"{c}{sfx}"] if len(rem) > 1 else df0)[["Open", "High", "Low", "Close", "Volume"]].dropna()
                if len(sub) > 50:
                    dc2[c] = sub
                    got.append(c)
            except Exception:
                pass
        rem = [c for c in rem if c not in got]
    for c in chunk:
        dc2.setdefault(c, None)
    with open(HOLD_CACHE, "wb") as f:
        pickle.dump(dc2, f)
print(f"保留集日線覆蓋 {sum(1 for c in need2 if dc2.get(c) is not None)}/{len(need2)}")


def hist2(code, d, n=130):
    df0 = dc2.get(code)
    if df0 is None:
        return None
    o = df0[df0.index <= pd.Timestamp(d)]
    return o.tail(n) if len(o) >= 65 else None


def tag(hs):
    for h in hs:
        ws = {m: hist2(m, str(h["date"])) for m in h["members"]}
        h["hA2"] = sum(1 for w in ws.values() if w is not None and pat_new_high(w, 60)) >= 2
        h["hA5"] = any(pat_gap_nh(w) for w in ws.values() if w is not None)
        labs = []
        for w in ws.values():
            if w is None or len(w) < 60:
                continue
            p = w["Close"].tail(60).values.astype(float)
            z = (p - p.mean()) / (p.std() + 1e-9)
            labs.append(int(((z[None, :] - cent) ** 2).sum(axis=1).argmin()))
        if labs:
            vals, cnts = np.unique(labs, return_counts=True)
            h["hshape"] = int(vals[cnts.argmax()])
        else:
            h["hshape"] = None
        h["hS0"] = h["hshape"] == 0
        h["hS3"] = h["hshape"] == 3
        h["combo"] = (h["hA2"] or h["hA5"] or h["hS0"]) and not h["hS3"]


tag(mh)
tag(mh_micro)

oh = io.open("tmp_holdout.txt", "w", encoding="utf-8")


def reph(sel, all_, label):
    pr = pd.Series([h["pret8"] for h in sel])
    bp_ = pd.Series([h["pret8"] for h in all_])
    if not len(pr):
        oh.write(f"{label}: 0筆\n")
        return None
    yrs = []
    for y in ("2025", "2026"):
        g = pd.Series([h["pret8"] for h in sel if str(h["date"])[:4] == y])
        yrs.append(f"{y}:{g.median():+.1%}(n={len(g)})" if len(g) else f"{y}:—")
    line = (f"{label:<30} n={len(pr):>3} 勝率{(pr > 0).mean():.0%} 中位{pr.median():+.1%} "
            f"平均{pr.mean():+.1%} {' '.join(yrs)}")
    oh.write(line + "\n")
    return (label, len(pr), float((pr > 0).mean()), float(pr.median()), float(pr.mean()), yrs)


oh.write(f"== 保留集 2025-2026 (大題材{len(mh)}筆/微題材{len(mh_micro)}筆) 一次定案 ==\n\n[大題材]\n")
rows_h = []
rows_h.append(reph(mh, mh, "基準(全部觸發)"))
rows_h.append(reph([h for h in mh if h["combo"]], mh, "★型態共振v1(A2∪A5∪形狀0,排形狀3)"))
rows_h.append(reph([h for h in mh if h["hA2"] or h["hS0"]], mh, "A2∪形狀0"))
rows_h.append(reph([h for h in mh if h["hA2"]], mh, "A2 60日新高≥2/3"))
rows_h.append(reph([h for h in mh if h["hA5"]], mh, "A5突破跳空"))
rows_h.append(reph([h for h in mh if h["hS0"]], mh, "形狀0升後回檔"))
rows_h.append(reph([h for h in mh if h["hS3"]], mh, "形狀3陰跌盤整(應該爛)"))
oh.write("\n[微題材]\n")
rows_h.append(reph(mh_micro, mh_micro, "微題材基準"))
rows_h.append(reph([h for h in mh_micro if h["hA2"]], mh_micro, "微題材 A2 60日新高≥2/3"))
oh.write("\n逐筆(大題材保留集):\n")
for h in sorted(mh, key=lambda x: str(x["date"])):
    oh.write(f"  {h['date']} {h['theme']:<12} A2{'✓' if h['hA2'] else '×'} A5{'✓' if h['hA5'] else '×'} "
             f"形狀{h['hshape']} {'★' if h['combo'] else ' '} {h['pret8']:+.1%}\n")
oh.close()

# 注入報告(置於績效指標總表之前) + 封卷
sh = "<h2>🎯 保留集驗證(2025-2026)——最後一槍，已封卷</h2>"
sh += "<div class='note'>陣容於樣本內凍結後一次驗證，此後本考卷永久關閉。★=主案。</div>"
sh += "<table><tr><th>配置</th><th>n</th><th>勝率</th><th>中位</th><th>平均</th><th>2025/2026</th></tr>"
for r in rows_h:
    if r is None:
        continue
    label, n_, win, med, mean_, yrs = r
    star = "★" if label.startswith("★") else ""
    sh += (f"<tr><th>{label}</th><td>{n_}</td><td>{win:.0%}</td><td>{med:+.1%}</td>"
           f"<td>{mean_:+.1%}</td><td>{'　'.join(yrs)}</td></tr>")
sh += "</table>"
sec2 = "<!--HOLDOUT_START-->" + sh + "<!--HOLDOUT_END-->"
rp = io.open("research_2022_report.html", encoding="utf-8").read()
if "<!--HOLDOUT_START-->" in rp:
    import re as _re
    rp = _re.sub(r"<!--HOLDOUT_START-->.*?<!--HOLDOUT_END-->", lambda _m: sec2, rp, flags=_re.S)
else:
    rp = rp.replace("<h2>績效指標總表</h2>", sec2 + "<h2>績效指標總表</h2>")
io.open("research_2022_report.html", "w", encoding="utf-8").write(rp)
print("done -> tmp_holdout.txt + 報告已注入保留集章節")
