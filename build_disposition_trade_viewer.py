# -*- coding: utf-8 -*-
"""處置V4逐筆交易K棒檢視器(使用者2026-07-25提案:「只看數字沒看走勢抓不到盤感」)
產出: 研究報告/research_disposition_trades.html (本地單檔,不進閹割版,使用者已裁示)
內容: 全部V4交易(第3處置日收盤買→出關次日開盤賣)逐筆K棒圖——
  公告前15根+處置窗全段+出關後10根;標記=處置窗底色/公告日虛線/進場▲/出場▼/-10%攤平觸發點
  副圖=本筆持有段cum%曲線 vs 同分盤cohort標準路徑帶(P25-P75+中位,使用者裁示要)
  左欄清單可排序(最賺/最賠/回撤最深/隨機20)+篩選(分盤/年/賺賠/G組/代碼),鍵盤←→翻筆刷盤感
設計註記: 台式紅漲綠跌;紅漲棒=空心、綠跌棒=實心(次要編碼,CVD/列印下方向仍可讀);
  沿用房規深色主題(#1a1a19/Noto Sans TC);名稱源=attention>rankings>cb_info(覆蓋~68%,缺=只顯代碼)
模板化: trade_payload()/HTML骨架寫成通用「事件→K棒圖」形狀,之後注意股/共振/CB回測可重用
用法: python -X utf8 build_disposition_trade_viewer.py
"""
import json
import sqlite3
import sys
import time
from datetime import datetime

import numpy as np
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DB = "capital_flow.db"
OUT = "研究報告/research_disposition_trades.html"
TDCC_PANEL = "快取/tmp_disposition_tdcc_panel.pkl"
COHORT = "快取/tmp_disposition_path_cohort.pkl"
PRE, POST = 15, 10
COST = 0.45
ADDON_X = -10.0  # 已驗證攤平headline門檻


def read_sql_retry(sql, tries=5, wait=3):
    for i in range(tries):
        try:
            conn = sqlite3.connect(DB, timeout=30)
            df = pd.read_sql(sql, conn)
            conn.close()
            return df
        except sqlite3.OperationalError as e:
            if "locked" in str(e) and i < tries - 1:
                print(f"  (db locked,{wait}s重試)")
                time.sleep(wait)
            else:
                raise


def load_names():
    """台股名稱: attention > rankings > cb_info(前4碼)。"""
    m = {}
    cb = read_sql_retry("SELECT substr(cb_id,1,4) AS code, cb_name AS name FROM cb_info "
                        "WHERE cb_name IS NOT NULL")
    for r in cb.itertuples():
        nm = str(r.name)
        for suf in "一二三四五六七八九十":
            nm = nm.rstrip(suf)
        m[r.code] = nm
    rk = read_sql_retry("SELECT DISTINCT code, name FROM rankings WHERE name IS NOT NULL AND name!=''")
    for r in rk.itertuples():
        m[r.code] = str(r.name)
    at = read_sql_retry("SELECT DISTINCT code, name FROM attention WHERE name IS NOT NULL AND name!=''")
    for r in at.itertuples():
        m[r.code] = str(r.name)
    return m


def main():
    disp = read_sql_retry("SELECT * FROM disposition")
    px = read_sql_retry("SELECT code, date, open, high, low, close, volume FROM fm_daily_price "
                        "ORDER BY code, date")
    for c in ("announce_date", "start_date", "end_date"):
        disp[c] = pd.to_datetime(disp[c], errors="coerce")
    disp = disp.dropna(subset=["start_date", "end_date"]).reset_index(drop=True)
    px["date"] = pd.to_datetime(px["date"])
    data_max = str(px.date.max().date())
    stocks = {c: g.sort_values("date").reset_index(drop=True) for c, g in px.groupby("code")}
    names = load_names()

    tp = pd.read_pickle(TDCC_PANEL)
    meta = tp.set_index("event_id")[["grp_r8_a", "d4w"]]
    cohort = pd.read_pickle(COHORT)

    trades = []
    for ev_id, e in disp.iterrows():
        g = stocks.get(e.code)
        if g is None:
            continue
        dts = g["date"].values
        n = len(g)
        s = int(np.searchsorted(dts, np.datetime64(e.start_date)))
        en = int(np.searchsorted(dts, np.datetime64(e.end_date), side="right") - 1)
        if s >= n or en <= s or en - s > 25 or en - s < 6 or en + 1 >= n:
            continue
        o_, h_, l_, c_, v_ = (g[k].values for k in ("open", "high", "low", "close", "volume"))
        entry_i = s + 2
        if c_[entry_i] <= 0 or o_[en + 1] <= 0:
            continue
        lo = max(0, s - PRE)
        hi = min(n - 1, en + POST)
        # 持有段cum(前值填補0價無成交日)
        seg = pd.Series(c_[entry_i:en + 1]).replace(0, np.nan).ffill().values
        cum = (seg / seg[0] - 1.0) * 100
        tradable = c_[entry_i:en + 1] > 0
        add_k = next((k for k in range(1, len(cum)) if tradable[k] and cum[k] <= ADDON_X), None)
        v4 = (o_[en + 1] / seg[0] - 1.0) * 100 - COST
        ia = -1
        if pd.notna(e.announce_date):
            j = int(np.searchsorted(dts, np.datetime64(e.announce_date)))
            if lo <= j <= hi:
                ia = j - lo
        mrow = meta.loc[ev_id] if ev_id in meta.index else None
        d4w = None if mrow is None or pd.isna(mrow.d4w) else round(float(mrow.d4w), 2)
        grp = "" if mrow is None or pd.isna(mrow.grp_r8_a) else str(mrow.grp_r8_a)
        rng = slice(lo, hi + 1)
        trades.append({
            "c": e.code, "nm": names.get(e.code, ""), "y": int(e.start_date.year),
            "mm": str(e.match_min), "v4": round(float(v4), 2),
            "dd": round(float(np.nanmin(cum)), 1), "g": grp, "d4": d4w,
            "ed": str(g["date"].iloc[entry_i].date()),
            "dt": [str(d.date()) for d in g["date"].iloc[rng]],
            "o": [round(float(x), 2) for x in o_[rng]],
            "h": [round(float(x), 2) for x in h_[rng]],
            "l": [round(float(x), 2) for x in l_[rng]],
            "cl": [round(float(x), 2) for x in c_[rng]],
            "v": [int(round(x / 1000)) for x in v_[rng]],
            "iS": s - lo, "iE": en - lo, "iN": entry_i - lo, "iX": en + 1 - lo, "iA": ia,
            "iAd": (entry_i + add_k - lo) if add_k is not None else -1,
            "xp": round(float(o_[en + 1]), 2),
            "cum": [round(float(x), 2) for x in cum],
        })
    trades.sort(key=lambda t: t["ed"], reverse=True)
    coh = {mm: {"k": [int(x) for x in df.k], "med": [round(float(x), 2) for x in df.med],
                "p25": [round(float(x), 2) for x in df.p25],
                "p75": [round(float(x), 2) for x in df.p75]} for mm, df in cohort.items()}
    payload = json.dumps({"trades": trades, "coh": coh}, ensure_ascii=False,
                         separators=(",", ":"))
    n5 = sum(1 for t in trades if t["mm"] == "5")
    print(f"交易數: {len(trades):,} (5分{n5:,}/20分{len(trades) - n5:,}); "
          f"名稱缺={sum(1 for t in trades if not t['nm'])}; payload={len(payload) / 1e6:.1f}MB")

    html = TEMPLATE.replace("__GEN__", datetime.now().strftime("%Y-%m-%d %H:%M")) \
        .replace("__DMAX__", data_max).replace("__N__", f"{len(trades):,}") \
        .replace("__DATA__", payload)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"輸出 {OUT} ({len(html) / 1e6:.1f}MB)")


TEMPLATE = r"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>處置V4逐筆交易K棒檢視器</title><style>
body{background:#1a1a19;color:#fff;font-family:"Noto Sans TC",sans-serif;margin:18px;font-size:14px}
h1{font-size:19px;margin:0 0 4px}
.note{color:#8a8878;font-size:12px;line-height:1.7}
.wrap{display:flex;gap:14px;margin-top:10px;align-items:flex-start}
#side{width:330px;flex:none}
#main{flex:1;min-width:0}
.frow{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px}
select,input,button{background:#262624;color:#ddd;border:1px solid #3a3a37;border-radius:4px;
  padding:3px 7px;font-size:12px;font-family:inherit}
button{cursor:pointer} button:hover{border-color:#8a8878}
#list{max-height:78vh;overflow-y:auto;border:1px solid #2c2c2a;border-radius:4px}
.row{padding:5px 9px;border-bottom:1px solid #242422;cursor:pointer;font-size:12.5px;
  display:flex;justify-content:space-between;gap:6px;white-space:nowrap}
.row:hover{background:#242423}
.row.on{background:#2e2c24;border-left:3px solid #e8b34b;padding-left:6px}
.good{color:#7ec97e}.bad{color:#e06c5a}.mut{color:#8a8878}
#head{font-size:15px;margin-bottom:6px;line-height:1.6}
#head b{font-size:17px}
.tag{background:#2c2c2a;border-radius:3px;padding:1px 7px;font-size:12px;color:#c3c2b7;margin-left:6px}
#chartbox{overflow-x:auto;border:1px solid #2c2c2a;border-radius:4px;background:#1e1e1c}
svg{display:block}
.subttl{color:#c3c2b7;font-size:12.5px;margin:12px 0 4px}
#tip{position:fixed;display:none;background:#111;border:1px solid #444;border-radius:4px;
  padding:6px 9px;font-size:12px;pointer-events:none;z-index:9;line-height:1.6;
  font-variant-numeric:tabular-nums}
.cnt{color:#8a8878;font-size:12px;margin:4px 2px}
kbd{background:#2c2c2a;border-radius:3px;padding:0 5px;font-size:11px}
a{color:#6bb7e3;text-decoration:none} a:hover{text-decoration:underline}
details{margin:8px 0 2px;background:#20201e;border:1px solid #2c2c2a;border-radius:4px;padding:6px 10px}
summary{cursor:pointer;color:#c3c2b7;font-size:12.5px}
.lg{color:#c3c2b7;font-size:12.5px;line-height:1.95;margin-top:6px}
.lg b{color:#fff}
</style></head><body>
<h1>處置V4逐筆交易K棒檢視器</h1>
<div class="note">口徑=第3處置交易日收盤買▲ → 出關次日開盤賣▼,扣0.45%。共 __N__ 筆(2019~,資料至__DMAX__,產生__GEN__)。
淡黃底=處置窗,灰虛線=公告日,◯攤=窗內首次收盤跌破-10%(已驗證攤平點)。紅=漲(空心) 綠=跌(實心)。
鍵盤 <kbd>←</kbd><kbd>→</kbd> 翻上一筆/下一筆。</div>
<details><summary>📖 圖例與規則說明(G1-G4/V4/V5/d4w/持有中加減碼)——完整回測卡片見 <a href="research_panic_liquidity.html">恐慌流動性三部曲</a></summary>
<div class="lg">
<b>出關前型態 G1-G4</b>(看處置窗最後5個交易日;門檻=2-3日連漲累積≥8%/單日回吐≤-5%,考卷build_disposition_exit_fade 2026-07-24):<br>
・<b>G1</b> 拉高又重吐=連漲≥8%結束於最後5日內+其後單日≤-5% ——「主力提早下車」假說<b class="bad">❌否定</b>:出關後不較差,20分盤反而略贏G4(k10+4.21pp邊緣);量能無出貨腳印。案例=8261富鼎2026-07。<br>
・<b>G2</b> 連漲守住=有連漲≥8%、無回吐,守到出關。<br>
・<b>G3</b> 純弱勢收尾=無連漲+最後3窗日內有單日≤-5% ——<b class="good">✅出關後統計跑贏</b>:5分k5+2.61pp(LOTO 8/8)/20分k10+11.54pp;機制=市場獎勵被洗出來的,不是拉高過的。案例=2454聯發科2026-05(V4賠12%但出關後5日+43.7%)。<br>
・<b>G4</b> 其餘=基準組。<br>
<b>V4/V5</b>: V4=第3處置日收盤買→出關次日開盤賣(本頁主角;20分盤T1甜蜜格+8.8%/78%=⭐R1)。V5=倒數第3日收盤買→出關日開盤賣;V5事前否決=進場前G1型態已完成→跳過(20分~3pp)。<br>
<b>d4w</b>=公告前最新集保快照的千張大戶%減4週前值(>0=大戶正在進)。2026-07-25複驗:<b>20分盤轉正</b>(早窗refit+5.77pp/晚窗+2.29pp)/5分盤維持候選;live口徑=d4w&gt;0打✓(免參數版四格全過),定位=信心加碼層非硬濾網(覆蓋64%有倖存者偏差)。<br>
<b>持有中加減碼</b>(路徑考卷2026-07-25,配對差LOTO+bootstrap): 停損<b class="bad">❌</b>(-10%停損8年0正,砍在統計谷底;跌破-10%後剩餘段中位5分+1.5%/20分+7.0%仍為正)/跌-10%攤平<b class="good">✅</b>(配對差5分+1.65pp/20分+1.80pp,LOTO 8/8;-15%以下肉沒了別攤;等本金預留版❌=照常滿倉進,攤平用新資金)/漲+3%加碼<b class="bad">❌</b>(8年0正,處置窗內強勢不追)/「+8%出一半∧-10%攤平」組合=平滑度最佳(std與MDD大砍)但探索性未預註冊,待live cohort複驗。
</div></details>
<div class="wrap">
<div id="side">
  <div class="frow">
    <select id="fmm"><option value="">全部分盤</option><option value="5">5分盤</option><option value="20">20分盤</option></select>
    <select id="fy"><option value="">全部年份</option></select>
    <select id="fpl"><option value="">賺+賠</option><option value="w">賺</option><option value="l">賠</option></select>
    <select id="fg"><option value="">全部G組</option><option>G1</option><option>G2</option><option>G3</option><option>G4</option></select>
  </div>
  <div class="frow">
    <select id="srt">
      <option value="new">進場日 新→舊</option><option value="best">最賺</option>
      <option value="worst">最賠</option><option value="dd">回撤最深</option><option value="d4">d4w高→低</option>
    </select>
    <button id="rnd">隨機20</button>
    <input id="q" placeholder="代碼" size="6">
  </div>
  <div class="cnt" id="cnt"></div>
  <div id="list"></div>
</div>
<div id="main">
  <div id="head"></div>
  <div id="chartbox"></div>
  <div class="subttl">持有段走勢 vs 同分盤「標準路徑」帶(灰帶=P25~P75,虛線=中位,金線=本筆) — 偏離帶下緣≠停損訊號(考卷判決:剩餘段仍為正)</div>
  <div id="bandbox"></div>
</div>
</div>
<div id="tip"></div>
<script>
const D=__DATA__;
const T=D.trades, COH=D.coh;
const UP="#e06c5a", DN="#7ec97e", AMB="#e8b34b", BLU="#7ab8e0", MUT="#8a8878", GRID="#2b2b29";
let flt=[], sel=-1;
const $=id=>document.getElementById(id);
const yrs=[...new Set(T.map(t=>t.y))].sort();
yrs.forEach(y=>{const o=document.createElement("option");o.textContent=y;$("fy").appendChild(o);});
const GDESC={G1:"出關前2-3日連漲≥8%+單日回吐≤-5%(主力下車假說已否定,8261型)",
  G2:"出關前連漲≥8%無回吐,守到出關",
  G3:"無連漲+最後3日單日≤-5%純弱勢收尾→出關後統計跑贏(5分k5+2.61pp/20分k10+11.54pp,2454型)",
  G4:"其餘(基準組)"};
function fmt(x){return (x>0?"+":"")+x.toFixed(2)+"%";}
function esc(s){return String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));}

function applyFilter(rand){
  const mm=$("fmm").value, fy=$("fy").value, pl=$("fpl").value, fg=$("fg").value, q=$("q").value.trim();
  flt=T.map((t,i)=>i).filter(i=>{const t=T[i];
    return (!mm||t.mm===mm)&&(!fy||String(t.y)===fy)&&(!pl||(pl==="w"?t.v4>0:t.v4<=0))
      &&(!fg||t.g===fg)&&(!q||t.c.startsWith(q));});
  const s=$("srt").value;
  if(s==="best")flt.sort((a,b)=>T[b].v4-T[a].v4);
  else if(s==="worst")flt.sort((a,b)=>T[a].v4-T[b].v4);
  else if(s==="dd")flt.sort((a,b)=>T[a].dd-T[b].dd);
  else if(s==="d4")flt.sort((a,b)=>(T[b].d4??-99)-(T[a].d4??-99));
  else flt.sort((a,b)=>T[b].ed<T[a].ed?-1:1);
  if(rand){for(let i=flt.length-1;i>0;i--){const j=Math.floor(Math.random()*(i+1));[flt[i],flt[j]]=[flt[j],flt[i]];}flt=flt.slice(0,20);}
  renderList();
  if(flt.length)show(0);else{$("head").innerHTML="<span class=mut>無符合筆數</span>";$("chartbox").innerHTML="";$("bandbox").innerHTML="";}
}
function renderList(){
  const cap=400, el=$("list");el.innerHTML="";
  flt.slice(0,cap).forEach((idx,pos)=>{
    const t=T[idx],r=document.createElement("div");
    r.className="row";r.dataset.pos=pos;
    r.innerHTML=`<span>${t.c} ${esc(t.nm)||""} <span class=mut>${t.ed.slice(0,7)} ${t.mm}分 ${t.g}</span></span>`+
      `<span class="${t.v4>0?"good":"bad"}">${fmt(t.v4)}</span>`;
    r.onclick=()=>show(pos);
    el.appendChild(r);
  });
  $("cnt").textContent=`${flt.length} 筆`+(flt.length>cap?`(清單只列前${cap},鍵盤可翻全部)`:"");
}
function show(pos){
  sel=pos;
  document.querySelectorAll(".row").forEach(r=>r.classList.toggle("on",+r.dataset.pos===pos));
  const rowEl=document.querySelector(`.row[data-pos="${pos}"]`);
  if(rowEl)rowEl.scrollIntoView({block:"nearest"});
  const t=T[flt[pos]];
  $("head").innerHTML=`<b>${t.c} ${esc(t.nm)}</b><span class=tag>${t.y}</span><span class=tag>${t.mm}分盤</span>`+
    `<span class=tag title="${GDESC[t.g]||""}">${t.g||"G?"}</span>`+
    `<span class=tag>d4w ${t.d4==null?"—":(t.d4>0?"+":"")+t.d4}${t.d4!=null&&t.d4>0?" ✓":""}</span>`+
    ` <span class="${t.v4>0?"good":"bad"}" style="font-size:17px">${fmt(t.v4)}</span>`+
    `<span class=mut> 窗內最深${t.dd.toFixed(1)}% · 進${t.ed} ${t.cl[t.iN]} → 出${t.dt[t.iX]} ${t.xp} · 第${pos+1}/${flt.length}筆</span>`;
  drawChart(t);drawBand(t);
}
function drawChart(t){
  const nb=t.dt.length, slot=Math.max(9,Math.min(15,Math.floor(900/nb)));
  const ML=52,MR=10,MT=8,PH=380,VH=64,GAP=16,MB=20;
  const W=ML+MR+nb*slot, H=MT+PH+GAP+VH+MB;
  const val=[];for(let i=0;i<nb;i++){if(t.cl[i]>0){val.push(t.h[i],t.l[i]);}}
  val.push(t.xp);
  let ymin=Math.min(...val),ymax=Math.max(...val);
  const pad=(ymax-ymin)*0.05||1;ymin-=pad;ymax+=pad;
  const Y=v=>MT+PH*(1-(v-ymin)/(ymax-ymin));
  const X=i=>ML+i*slot+slot/2;
  const vmax=Math.max(...t.v,1);
  const VY=v=>MT+PH+GAP+VH*(1-v/vmax);
  let s=`<svg width="${W}" height="${H}" font-family="Noto Sans TC">`;
  s+=`<rect x="${X(t.iS)-slot/2}" y="${MT}" width="${(t.iE-t.iS+1)*slot}" height="${PH+GAP+VH}" fill="rgba(232,179,75,0.06)"/>`;
  const step=(ymax-ymin)/4;
  for(let i=0;i<=4;i++){const v=ymin+step*i,y=Y(v);
    s+=`<line x1="${ML}" x2="${W-MR}" y1="${y}" y2="${y}" stroke="${GRID}"/>`+
       `<text x="${ML-5}" y="${y+4}" fill="${MUT}" font-size="11" text-anchor="end">${v>=100?v.toFixed(0):v.toFixed(1)}</text>`;}
  const lstep=Math.max(1,Math.floor(nb/7));
  for(let i=0;i<nb;i+=lstep)s+=`<text x="${X(i)}" y="${H-5}" fill="${MUT}" font-size="10.5" text-anchor="middle">${t.dt[i].slice(5)}</text>`;
  if(t.iA>=0)s+=`<line x1="${X(t.iA)}" x2="${X(t.iA)}" y1="${MT}" y2="${MT+PH}" stroke="${MUT}" stroke-dasharray="4 3"/>`+
    `<text x="${X(t.iA)}" y="${MT+11}" fill="${MUT}" font-size="10.5" text-anchor="middle">公告</text>`;
  const cw=Math.max(3,Math.floor(slot*0.6));
  for(let i=0;i<nb;i++){
    if(t.cl[i]<=0){s+=`<text x="${X(i)}" y="${Y((ymin+ymax)/2)}" fill="#3a3a37" font-size="10" text-anchor="middle">×</text>`;continue;}
    const up=t.cl[i]>=t.o[i]&&t.o[i]>0, col=up?UP:DN;
    const yh=Y(t.h[i]),yl=Y(t.l[i]);
    s+=`<line x1="${X(i)}" x2="${X(i)}" y1="${yh}" y2="${yl}" stroke="${col}" stroke-width="1"/>`;
    const o=t.o[i]>0?t.o[i]:t.cl[i];
    let yt=Y(Math.max(o,t.cl[i])),yb=Y(Math.min(o,t.cl[i]));
    if(yb-yt<1.5){yt=(yt+yb)/2-0.75;yb=yt+1.5;}
    s+=up?`<rect x="${X(i)-cw/2}" y="${yt}" width="${cw}" height="${yb-yt}" fill="#1e1e1c" stroke="${col}" stroke-width="1.4" rx="1"/>`
         :`<rect x="${X(i)-cw/2}" y="${yt}" width="${cw}" height="${yb-yt}" fill="${col}" rx="1"/>`;
    if(t.v[i]>0)s+=`<rect x="${X(i)-cw/2}" y="${VY(t.v[i])}" width="${cw}" height="${VY(0)-VY(t.v[i])}" fill="#45443f"/>`;
  }
  const yEn=Y(t.cl[t.iN]);
  s+=`<path d="M ${X(t.iN)} ${Y(t.l[t.iN])+16} l -6 10 l 12 0 z" fill="${AMB}"/>`+
     `<text x="${X(t.iN)}" y="${Y(t.l[t.iN])+38}" fill="${AMB}" font-size="11" text-anchor="middle">進</text>`;
  s+=`<path d="M ${X(t.iX)} ${Y(t.h[t.iX]>0?t.h[t.iX]:t.xp)-16} l -6 -10 l 12 0 z" fill="${BLU}"/>`+
     `<text x="${X(t.iX)}" y="${Y(t.h[t.iX]>0?t.h[t.iX]:t.xp)-30}" fill="${BLU}" font-size="11" text-anchor="middle">出</text>`;
  if(t.iAd>=0)s+=`<circle cx="${X(t.iAd)}" cy="${Y(t.cl[t.iAd])}" r="6.5" fill="none" stroke="${AMB}" stroke-width="1.8"/>`+
     `<text x="${X(t.iAd)}" y="${Y(t.cl[t.iAd])+20}" fill="${AMB}" font-size="10.5" text-anchor="middle">攤</text>`;
  for(let i=0;i<nb;i++)s+=`<rect x="${ML+i*slot}" y="${MT}" width="${slot}" height="${PH+GAP+VH}" fill="transparent" data-i="${i}" class="hb"/>`;
  s+=`</svg>`;
  $("chartbox").innerHTML=s;
  const tip=$("tip");
  $("chartbox").querySelectorAll(".hb").forEach(r=>{
    r.addEventListener("mousemove",ev=>{
      const i=+r.dataset.i;
      const chg=(i>0&&t.cl[i-1]>0&&t.cl[i]>0)?((t.cl[i]/t.cl[i-1]-1)*100).toFixed(2):null;
      tip.style.display="block";
      tip.innerHTML=t.cl[i]<=0?`${t.dt[i]}<br><span class=mut>無成交</span>`:
        `${t.dt[i]}${i>=t.iS&&i<=t.iE?' <span class=mut>處置中</span>':''}<br>開${t.o[i]} 高${t.h[i]} 低${t.l[i]} 收${t.cl[i]}`+
        (chg!=null?` <span class="${+chg>=0?'good':'bad'}">${+chg>0?'+':''}${chg}%</span>`:"")+
        `<br><span class=mut>量${t.v[i].toLocaleString()}張</span>`;
      tip.style.left=Math.min(ev.clientX+14,window.innerWidth-190)+"px";
      tip.style.top=(ev.clientY+12)+"px";
    });
    r.addEventListener("mouseleave",()=>tip.style.display="none");
  });
}
function drawBand(t){
  const c=COH[t.mm];if(!c){$("bandbox").innerHTML="";return;}
  const K=t.cum.length-1, xmax=Math.max(K,20);
  const ML=52,MR=14,MT=10,PH=170,MB=22;
  const W=Math.min(880,Math.max(560,ML+MR+xmax*38)), H=MT+PH+MB;
  const xs=(W-ML-MR)/xmax;
  const vals=[...t.cum];
  for(let i=0;i<c.k.length;i++){if(c.k[i]<=xmax){vals.push(c.p25[i],c.p75[i]);}}
  let ymin=Math.min(...vals,-2),ymax=Math.max(...vals,2);
  const pad=(ymax-ymin)*0.08;ymin-=pad;ymax+=pad;
  const X=k=>ML+k*xs, Y=v=>MT+PH*(1-(v-ymin)/(ymax-ymin));
  let s=`<svg width="${W}" height="${H}" font-family="Noto Sans TC">`;
  const step=(ymax-ymin)/4;
  for(let i=0;i<=4;i++){const v=ymin+step*i;
    s+=`<line x1="${ML}" x2="${W-MR}" y1="${Y(v)}" y2="${Y(v)}" stroke="${GRID}"/>`+
       `<text x="${ML-5}" y="${Y(v)+4}" fill="${MUT}" font-size="11" text-anchor="end">${v.toFixed(0)}%</text>`;}
  for(let k=0;k<=xmax;k+=2)s+=`<text x="${X(k)}" y="${H-5}" fill="${MUT}" font-size="10.5" text-anchor="middle">${k}</text>`;
  s+=`<line x1="${ML}" x2="${W-MR}" y1="${Y(0)}" y2="${Y(0)}" stroke="#3a3a37"/>`;
  let up="",dn="";
  for(let i=0;i<c.k.length;i++){if(c.k[i]>xmax)break;up+=`${i?"L":"M"} ${X(c.k[i])} ${Y(c.p75[i])} `;}
  const pts=c.k.filter(k=>k<=xmax).length;
  for(let i=pts-1;i>=0;i--)dn+=`L ${X(c.k[i])} ${Y(c.p25[i])} `;
  s+=`<path d="${up}${dn}Z" fill="rgba(255,255,255,0.07)"/>`;
  let med="";for(let i=0;i<pts;i++)med+=`${i?"L":"M"} ${X(c.k[i])} ${Y(c.med[i])} `;
  s+=`<path d="${med}" fill="none" stroke="${MUT}" stroke-width="1.5" stroke-dasharray="5 4"/>`;
  let own="";for(let k=0;k<=K;k++)own+=`${k?"L":"M"} ${X(k)} ${Y(t.cum[k])} `;
  s+=`<path d="${own}" fill="none" stroke="${AMB}" stroke-width="2"/>`;
  s+=`<circle cx="${X(K)}" cy="${Y(t.cum[K])}" r="3.5" fill="${AMB}"/>`+
     `<text x="${X(K)+7}" y="${Y(t.cum[K])+4}" fill="${AMB}" font-size="11.5">${fmt(t.cum[K])}</text>`;
  if(t.iAd>=0){const k=t.iAd-t.iN;
    s+=`<circle cx="${X(k)}" cy="${Y(t.cum[k])}" r="5.5" fill="none" stroke="${AMB}" stroke-width="1.6"/>`;}
  s+=`<text x="${W-MR}" y="${MT+12}" fill="${MUT}" font-size="11" text-anchor="end">x=距進場交易日</text>`;
  s+=`</svg>`;
  $("bandbox").innerHTML=s;
}
["fmm","fy","fpl","fg","srt"].forEach(id=>$(id).onchange=()=>applyFilter(false));
$("q").oninput=()=>applyFilter(false);
$("rnd").onclick=()=>applyFilter(true);
document.addEventListener("keydown",e=>{
  if(e.target.tagName==="INPUT")return;
  if(e.key==="ArrowRight"&&sel<flt.length-1)show(sel+1);
  if(e.key==="ArrowLeft"&&sel>0)show(sel-1);
});
applyFilter(false);
</script></body></html>"""


if __name__ == "__main__":
    main()
