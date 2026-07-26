# -*- coding: utf-8 -*-
"""注意股跌觸發逐筆交易K棒檢視器(2026-07-27,使用者要求;模板重用自build_disposition_trade_viewer)
產出: 研究報告/research_attention_trades.html(本地)
每筆: 公告前15根+持有段(次日開盤→T+10收盤,底色)+後10根;標記=公告日虛線/進▲/出▼(T+10)/T+20參考線;
副圖=本筆持有段cum% vs 跌觸發cohort標準路徑帶;meta=公告跌幅(劑量)/款別/金流/PE/規則卡✓/⚠事後升級處置
用法: python -X utf8 build_attention_trade_viewer.py  (價格或attention更新後重跑)
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
OUT = "研究報告/research_attention_trades.html"
PANEL = "tmp_attention_full_panel.pkl"
PRE, HOLD, POST = 15, 10, 10


def read_sql_retry(sql, tries=5, wait=3):
    for i in range(tries):
        try:
            conn = sqlite3.connect(DB, timeout=30)
            df = pd.read_sql(sql, conn)
            conn.close()
            return df
        except sqlite3.OperationalError as e:
            if "locked" in str(e) and i < tries - 1:
                time.sleep(wait)
            else:
                raise


def main():
    eps = pd.read_pickle(PANEL)
    rs = eps.reason.astype(str)
    down = eps[rs.str.contains("跌幅") & ~rs.str.contains("漲幅") & eps.t10.notna()].copy()
    names = read_sql_retry("SELECT DISTINCT code, name FROM attention WHERE name IS NOT NULL")
    nm = dict(zip(names.code, names.name))
    px = read_sql_retry("SELECT code, date, open, high, low, close, volume FROM fm_daily_price "
                        "ORDER BY code, date")
    px["date"] = pd.to_datetime(px.date)
    data_max = str(px.date.max().date())
    stocks = {c: g.sort_values("date").reset_index(drop=True) for c, g in px.groupby("code")}

    trades, paths = [], []
    for r in down.itertuples():
        g = stocks.get(r.code)
        if g is None:
            continue
        dts = g.date.values
        n = len(g)
        j = int(np.searchsorted(dts, np.datetime64(r.date), side="right"))  # 進場bar(公告次日)
        if j >= n or g.open.values[j] <= 0 or j + HOLD >= n:
            continue
        lo = max(0, j - PRE - 1)
        hi = min(n - 1, j + HOLD + POST)
        o_, h_, l_, c_, v_ = (g[k].values[lo:hi + 1] for k in ("open", "high", "low", "close", "volume"))
        entry_px = float(g.open.values[j])
        K = min(20, n - 1 - j)
        cum = [(float(g.close.values[j + k]) / entry_px - 1) * 100 for k in range(0, K + 1)]
        paths.append(cum)
        tg = str(r.triggers or "")
        ok = ("4" not in tg.split(",")) and pd.notna(r.drop_mag) and r.drop_mag >= 34 and \
             pd.notna(r.amt20) and r.amt20 >= 0.3 and pd.notna(r.pe) and r.pe > 0
        i_ann = int(np.searchsorted(g.date.values, np.datetime64(r.date)))
        trades.append({
            "c": r.code, "nm": nm.get(r.code, ""), "y": int(r.y),
            "net": round(float(r.t10), 2), "t20": None if pd.isna(r.t20) else round(float(r.t20), 2),
            "mag": None if pd.isna(r.drop_mag) else round(float(r.drop_mag), 1),
            "tg": tg, "amt": None if pd.isna(r.amt20) else round(float(r.amt20), 2),
            "pe": None if pd.isna(r.pe) else round(float(r.pe), 1),
            "ok": bool(ok), "upg": bool(r.upgrade), "mkt": r.market,
            "ann": str(pd.Timestamp(r.date).date()),
            "dt": [str(pd.Timestamp(d).date()) for d in g.date.values[lo:hi + 1]],
            "o": [round(float(x), 2) for x in o_], "h": [round(float(x), 2) for x in h_],
            "l": [round(float(x), 2) for x in l_], "cl": [round(float(x), 2) for x in c_],
            "v": [int(round(x / 1000)) for x in v_],
            "iA": i_ann - lo if lo <= i_ann <= hi else -1,
            "iN": j - lo, "iX": j + HOLD - lo,
            "i20": (j + 20 - lo) if j + 20 <= hi else -1,
            "cum": [round(x, 2) for x in cum],
        })
    trades.sort(key=lambda t: t["ann"], reverse=True)
    # cohort帶(k=0..20)
    coh = []
    for k in range(0, 21):
        vals = np.array([p[k] for p in paths if len(p) > k])
        if len(vals) >= 30:
            coh.append({"k": k, "med": round(float(np.median(vals)), 2),
                        "p25": round(float(np.percentile(vals, 25)), 2),
                        "p75": round(float(np.percentile(vals, 75)), 2)})
    payload = json.dumps({"trades": trades, "coh": coh}, ensure_ascii=False, separators=(",", ":"))
    print(f"跌觸發交易: {len(trades):,}筆 規則卡✓{sum(1 for t in trades if t['ok'])} "
          f"升級組{sum(1 for t in trades if t['upg'])} payload={len(payload) / 1e6:.1f}MB")
    html = TEMPLATE.replace("__GEN__", datetime.now().strftime("%Y-%m-%d %H:%M")) \
        .replace("__DMAX__", data_max).replace("__N__", f"{len(trades):,}") \
        .replace("__DATA__", payload)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"輸出 {OUT} ({len(html) / 1e6:.1f}MB)")


TEMPLATE = r"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>注意股跌觸發逐筆K棒檢視器</title><style>
body{background:#1a1a19;color:#fff;font-family:"Noto Sans TC",sans-serif;margin:18px;font-size:14px}
h1{font-size:19px;margin:0 0 4px}
.note{color:#8a8878;font-size:12px;line-height:1.7}
.wrap{display:flex;gap:14px;margin-top:10px;align-items:flex-start}
#side{width:340px;flex:none}
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
a{color:#6bb7e3;text-decoration:none}
</style></head><body>
<h1>注意股「跌觸發」逐筆K棒檢視器</h1>
<div class="note">口徑=公告次日開盤買▲ → T+10收盤賣▼(扣0.45%);共 __N__ 筆(2019~,資料至__DMAX__,產生__GEN__)。
底色=持有段,灰虛線=公告日,右側點虛線=T+20參考(網格顯示20日更肥)。紅=漲(空心) 綠=跌(實心)。
標籤: ✓=候選規則卡(跌幅≥34%∧金流≥0.3億∧有PE∧無款4) / ⚠升=事後20日內升級處置(虧損主源,-2.31%/45%,事前不可知——看它們長怎樣正是本頁重點)。
鍵盤 <kbd>←</kbd><kbd>→</kbd> 翻筆。詳細判決見 <a href="research_attention.html">research_attention.html</a>。</div>
<div class="wrap">
<div id="side">
  <div class="frow">
    <select id="fy"><option value="">全部年份</option></select>
    <select id="fpl"><option value="">賺+賠</option><option value="w">賺</option><option value="l">賠</option></select>
    <select id="fok"><option value="">全部</option><option value="1">✓規則卡</option></select>
    <select id="fupg"><option value="">升級+未升級</option><option value="1">⚠升級組</option><option value="0">未升級</option></select>
  </div>
  <div class="frow">
    <select id="srt">
      <option value="new">公告日 新→舊</option><option value="best">最賺</option>
      <option value="worst">最賠</option><option value="mag">劑量深→淺</option><option value="amt">金流大→小</option>
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
  <div class="subttl">持有段走勢 vs 跌觸發cohort「標準路徑」帶(灰帶=P25~P75,虛線=中位,金線=本筆,x=距進場交易日,0=進場日開盤基準)</div>
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
function fmt(x){return (x>0?"+":"")+x.toFixed(2)+"%";}
function esc(s){return String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));}
function applyFilter(rand){
  const fy=$("fy").value, pl=$("fpl").value, ok=$("fok").value, ug=$("fupg").value, q=$("q").value.trim();
  flt=T.map((t,i)=>i).filter(i=>{const t=T[i];
    return (!fy||String(t.y)===fy)&&(!pl||(pl==="w"?t.net>0:t.net<=0))&&(!ok||t.ok)
      &&(ug===""||(ug==="1"?t.upg:!t.upg))&&(!q||t.c.startsWith(q));});
  const s=$("srt").value;
  if(s==="best")flt.sort((a,b)=>T[b].net-T[a].net);
  else if(s==="worst")flt.sort((a,b)=>T[a].net-T[b].net);
  else if(s==="mag")flt.sort((a,b)=>(T[b].mag||0)-(T[a].mag||0));
  else if(s==="amt")flt.sort((a,b)=>(T[b].amt||0)-(T[a].amt||0));
  else flt.sort((a,b)=>T[b].ann<T[a].ann?-1:1);
  if(rand){for(let i=flt.length-1;i>0;i--){const j=Math.floor(Math.random()*(i+1));[flt[i],flt[j]]=[flt[j],flt[i]];}flt=flt.slice(0,20);}
  renderList();
  if(flt.length)show(0);else{$("head").innerHTML="<span class=mut>無符合筆數</span>";$("chartbox").innerHTML="";$("bandbox").innerHTML="";}
}
function renderList(){
  const cap=400, el=$("list");el.innerHTML="";
  flt.slice(0,cap).forEach((idx,pos)=>{
    const t=T[idx],r=document.createElement("div");
    r.className="row";r.dataset.pos=pos;
    r.innerHTML=`<span>${t.ok?"✓":""}${t.upg?"⚠":""}${t.c} ${esc(t.nm)||""} <span class=mut>${t.ann.slice(0,7)} ${t.mag!=null?t.mag.toFixed(0)+"%":""}</span></span>`+
      `<span class="${t.net>0?"good":"bad"}">${fmt(t.net)}</span>`;
    r.onclick=()=>show(pos);
    el.appendChild(r);
  });
  $("cnt").textContent=`${flt.length} 筆`+(flt.length>cap?`(清單列前${cap},鍵盤可翻全部)`:"");
}
function show(pos){
  sel=pos;
  document.querySelectorAll(".row").forEach(r=>r.classList.toggle("on",+r.dataset.pos===pos));
  const rowEl=document.querySelector(`.row[data-pos="${pos}"]`);
  if(rowEl)rowEl.scrollIntoView({block:"nearest"});
  const t=T[flt[pos]];
  $("head").innerHTML=`<b>${t.c} ${esc(t.nm)}</b><span class=tag>${t.y}</span>`+
    (t.ok?`<span class=tag style="color:var(--amb,#e8b34b)">✓規則卡</span>`:"")+
    (t.upg?`<span class=tag style="color:#e06c5a">⚠後升級處置</span>`:"")+
    `<span class=tag>跌幅${t.mag!=null?t.mag.toFixed(1)+"%":"—"}</span><span class=tag>款${t.tg}</span>`+
    `<span class=tag>金流${t.amt!=null?t.amt+"億":"—"}</span><span class=tag>PE ${t.pe!=null?t.pe:"虧損/無"}</span>`+
    ` <span class="${t.net>0?"good":"bad"}" style="font-size:17px">${fmt(t.net)}</span>`+
    `<span class=mut> t20=${t.t20!=null?fmt(t.t20):"—"} · 公告${t.ann} · 第${pos+1}/${flt.length}筆</span>`;
  drawChart(t);drawBand(t);
}
function drawChart(t){
  const nb=t.dt.length, slot=Math.max(9,Math.min(15,Math.floor(900/nb)));
  const ML=52,MR=10,MT=8,PH=380,VH=64,GAP=16,MB=20;
  const W=ML+MR+nb*slot, H=MT+PH+GAP+VH+MB;
  const val=[];for(let i=0;i<nb;i++){if(t.cl[i]>0){val.push(t.h[i],t.l[i]);}}
  let ymin=Math.min(...val),ymax=Math.max(...val);
  const pad=(ymax-ymin)*0.05||1;ymin-=pad;ymax+=pad;
  const Y=v=>MT+PH*(1-(v-ymin)/(ymax-ymin));
  const X=i=>ML+i*slot+slot/2;
  const vmax=Math.max(...t.v,1);
  const VY=v=>MT+PH+GAP+VH*(1-v/vmax);
  let s=`<svg width="${W}" height="${H}" font-family="Noto Sans TC">`;
  s+=`<rect x="${X(t.iN)-slot/2}" y="${MT}" width="${(t.iX-t.iN+1)*slot}" height="${PH+GAP+VH}" fill="rgba(232,179,75,0.06)"/>`;
  const step=(ymax-ymin)/4;
  for(let i=0;i<=4;i++){const v=ymin+step*i,y=Y(v);
    s+=`<line x1="${ML}" x2="${W-MR}" y1="${y}" y2="${y}" stroke="${GRID}"/>`+
       `<text x="${ML-5}" y="${y+4}" fill="${MUT}" font-size="11" text-anchor="end">${v>=100?v.toFixed(0):v.toFixed(1)}</text>`;}
  const lstep=Math.max(1,Math.floor(nb/7));
  for(let i=0;i<nb;i+=lstep)s+=`<text x="${X(i)}" y="${H-5}" fill="${MUT}" font-size="10.5" text-anchor="middle">${t.dt[i].slice(5)}</text>`;
  if(t.iA>=0)s+=`<line x1="${X(t.iA)}" x2="${X(t.iA)}" y1="${MT}" y2="${MT+PH}" stroke="${MUT}" stroke-dasharray="4 3"/>`+
    `<text x="${X(t.iA)}" y="${MT+11}" fill="${MUT}" font-size="10.5" text-anchor="middle">公告</text>`;
  if(t.i20>=0)s+=`<line x1="${X(t.i20)}" x2="${X(t.i20)}" y1="${MT}" y2="${MT+PH}" stroke="#4a4a46" stroke-dasharray="2 4"/>`+
    `<text x="${X(t.i20)}" y="${MT+11}" fill="#4a4a46" font-size="10" text-anchor="middle">T+20</text>`;
  const cw=Math.max(3,Math.floor(slot*0.6));
  for(let i=0;i<nb;i++){
    if(t.cl[i]<=0){s+=`<text x="${X(i)}" y="${Y((ymin+ymax)/2)}" fill="#3a3a37" font-size="10" text-anchor="middle">×</text>`;continue;}
    const up=t.cl[i]>=t.o[i]&&t.o[i]>0, col=up?UP:DN;
    s+=`<line x1="${X(i)}" x2="${X(i)}" y1="${Y(t.h[i])}" y2="${Y(t.l[i])}" stroke="${col}" stroke-width="1"/>`;
    const o=t.o[i]>0?t.o[i]:t.cl[i];
    let yt=Y(Math.max(o,t.cl[i])),yb=Y(Math.min(o,t.cl[i]));
    if(yb-yt<1.5){yt=(yt+yb)/2-0.75;yb=yt+1.5;}
    s+=up?`<rect x="${X(i)-cw/2}" y="${yt}" width="${cw}" height="${yb-yt}" fill="#1e1e1c" stroke="${col}" stroke-width="1.4" rx="1"/>`
         :`<rect x="${X(i)-cw/2}" y="${yt}" width="${cw}" height="${yb-yt}" fill="${col}" rx="1"/>`;
    if(t.v[i]>0)s+=`<rect x="${X(i)-cw/2}" y="${VY(t.v[i])}" width="${cw}" height="${VY(0)-VY(t.v[i])}" fill="#45443f"/>`;
  }
  s+=`<path d="M ${X(t.iN)} ${Y(t.l[t.iN])+16} l -6 10 l 12 0 z" fill="${AMB}"/>`+
     `<text x="${X(t.iN)}" y="${Y(t.l[t.iN])+38}" fill="${AMB}" font-size="11" text-anchor="middle">進</text>`;
  if(t.iX<nb)s+=`<path d="M ${X(t.iX)} ${Y(t.h[t.iX]>0?t.h[t.iX]:t.cl[t.iX])-16} l -6 -10 l 12 0 z" fill="${BLU}"/>`+
     `<text x="${X(t.iX)}" y="${Y(t.h[t.iX]>0?t.h[t.iX]:t.cl[t.iX])-30}" fill="${BLU}" font-size="11" text-anchor="middle">出</text>`;
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
        `${t.dt[i]}${i>=t.iN&&i<=t.iX?' <span class=mut>持有中</span>':''}<br>開${t.o[i]} 高${t.h[i]} 低${t.l[i]} 收${t.cl[i]}`+
        (chg!=null?` <span class="${+chg>=0?'good':'bad'}">${+chg>0?'+':''}${chg}%</span>`:"")+
        `<br><span class=mut>量${t.v[i].toLocaleString()}張</span>`;
      tip.style.left=Math.min(ev.clientX+14,window.innerWidth-190)+"px";
      tip.style.top=(ev.clientY+12)+"px";
    });
    r.addEventListener("mouseleave",()=>tip.style.display="none");
  });
}
function drawBand(t){
  const c=COH;if(!c||!c.length){$("bandbox").innerHTML="";return;}
  const K=t.cum.length-1, xmax=20;
  const ML=52,MR=14,MT=10,PH=170,MB=22;
  const W=Math.min(880,Math.max(560,ML+MR+xmax*38)), H=MT+PH+MB;
  const xs=(W-ML-MR)/xmax;
  const vals=[...t.cum];
  c.forEach(r=>{vals.push(r.p25,r.p75);});
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
  let up2="",dn2="";
  c.forEach((r,i)=>{up2+=`${i?"L":"M"} ${X(r.k)} ${Y(r.p75)} `;});
  for(let i=c.length-1;i>=0;i--)dn2+=`L ${X(c[i].k)} ${Y(c[i].p25)} `;
  s+=`<path d="${up2}${dn2}Z" fill="rgba(255,255,255,0.07)"/>`;
  let med="";c.forEach((r,i)=>{med+=`${i?"L":"M"} ${X(r.k)} ${Y(r.med)} `;});
  s+=`<path d="${med}" fill="none" stroke="${MUT}" stroke-width="1.5" stroke-dasharray="5 4"/>`;
  let own="";for(let k=0;k<=Math.min(K,xmax);k++)own+=`${k?"L":"M"} ${X(k)} ${Y(t.cum[k])} `;
  s+=`<path d="${own}" fill="none" stroke="${AMB}" stroke-width="2"/>`;
  const kk=Math.min(K,xmax);
  s+=`<circle cx="${X(kk)}" cy="${Y(t.cum[kk])}" r="3.5" fill="${AMB}"/>`+
     `<text x="${X(kk)+7}" y="${Y(t.cum[kk])+4}" fill="${AMB}" font-size="11.5">${fmt(t.cum[kk])}</text>`;
  s+=`<line x1="${X(10)}" x2="${X(10)}" y1="${MT}" y2="${MT+PH}" stroke="#4a4a46" stroke-dasharray="2 4"/>`+
     `<text x="${X(10)}" y="${MT+12}" fill="#4a4a46" font-size="10">T+10出場</text>`;
  s+=`</svg>`;
  $("bandbox").innerHTML=s;
}
["fy","fpl","fok","fupg","srt"].forEach(id=>$(id).onchange=()=>applyFilter(false));
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
