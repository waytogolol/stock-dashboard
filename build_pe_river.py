# -*- coding: utf-8 -*-
"""PE/PB河流圖 -> 研究報告/research_pe_river.html (本機,gitignored,價格/PER更新後重跑)
背景: 2026-07-28使用者交辦「個股版+題材版兩層一起做,標記營收開始轉好×河流下緣,附白話介紹」。
定位(依7/28兩場初驗判決): 看盤工具非訊號——
  題材版=便宜格(題材PE位階<=10,估值線唯一活格,熊市買點)的視覺呈現;
  個股版=底部悲觀出清參考(絕對diff含0無edge,僅超額+1.31抗跌)/頂部(>=90)輕警示(超額-0.85排0);
  ⚠記憶體/CPO=循環股PE陷阱(低PE=獲利頂,便宜半-貴半-5.27/-4.21pp反向)。
做法: EPS_ttm=收盤price/官方PER反推(BPS同理用PBR);河道=自家歷史PE(PB)分位10/30/50/70/90×EPS;
  題材=成員等權週指數+成員正PER中位(>=5檔有效);週頻2018起;營收=fm_month_rev最新兩期yoy。
用法: python build_pe_river.py
"""
import json
import sqlite3
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
DB = "capital_flow.db"
MIN_PE_MEMBERS = 5
QS = [0.10, 0.30, 0.50, 0.70, 0.90]
TRAP_KEY = ("記憶體", "CPO")          # 逐題材掃描: 低PE=循環股獲利頂反指標
MR_KEY = ("金融", "光學", "機器人", "連接器")  # 描述性偏均值回歸端(便宜半贏貴半+1~+6pp)


def rnd(v, n=2):
    return None if v is None or (isinstance(v, float) and not np.isfinite(v)) else round(float(v), n)


def load():
    con = sqlite3.connect(DB)
    cl = pd.read_sql("SELECT DISTINCT code, main_group FROM classification WHERE country='台'", con)
    per = pd.read_sql("SELECT date, code, per, pbr FROM per_daily", con, parse_dates=["date"])
    codes = sorted(per.code.unique())
    ph = ",".join("?" * len(codes))
    px = pd.read_sql(f"SELECT code, date, close FROM fm_daily_price WHERE code IN ({ph}) "
                     "AND date>='2018-01-01'", con, params=codes, parse_dates=["date"])
    rev = pd.read_sql(f"SELECT code, date, revenue FROM fm_month_rev WHERE code IN ({ph})",
                      con, params=codes)
    names = {}
    try:
        for c_, n_ in con.execute("SELECT code, name FROM company_names"):
            names[str(c_)] = n_
    except Exception:
        pass
    try:
        for c_, n_ in con.execute(
                "SELECT code, name FROM rankings WHERE market='台股' GROUP BY code"):
            names.setdefault(str(c_), n_)
    except Exception:
        pass
    con.close()
    try:
        ac = pd.read_csv("all_classified.csv")
        for _, r in ac[ac["國家"] == "台"].iterrows():
            names.setdefault(str(r["代碼"]), r["公司"])
    except Exception:
        pass
    return cl, per, px, rev, names


def main():
    cl, per, px, rev, names = load()
    per.loc[per.per <= 0, "per"] = np.nan
    per.loc[per.pbr <= 0, "pbr"] = np.nan

    # ---- 週頻化(W-FRI取每週最後值) ----
    for df in (per, px):
        df["w"] = df.date.dt.to_period("W-FRI").dt.end_time.dt.normalize()
    pxw = px.sort_values("date").groupby(["code", "w"]).close.last().unstack("code")
    pew = per.sort_values("date").groupby(["code", "w"]).per.last().unstack("code")
    pbw = per.sort_values("date").groupby(["code", "w"]).pbr.last().unstack("code")
    weeks = pxw.index
    pew = pew.reindex(weeks)
    pbw = pbw.reindex(weeks)
    wlabels = [d.strftime("%Y-%m-%d") for d in weeks]

    # ---- 個股營收: 最新兩期yoy ----
    rev["m"] = rev.date.str[:7]
    rev = rev.sort_values(["code", "m"])
    rev["yoy"] = (rev.revenue / rev.groupby("code").revenue.shift(12) - 1) * 100
    ryo = {}
    for c_, g in rev.groupby("code"):
        v = g.yoy.dropna()
        if len(v) >= 2:
            ryo[c_] = (rnd(v.iloc[-1], 1), rnd(v.iloc[-2], 1), g.m.iloc[-1])

    # ---- 題材層 ----
    members = cl.groupby("main_group").code.apply(
        lambda s: [c for c in s if c in pxw.columns]).to_dict()
    theme_rev = rev.merge(cl, on="code").groupby(["main_group", "m"]).revenue.sum().reset_index()
    theme_rev = theme_rev.sort_values(["main_group", "m"])
    theme_rev["yoy"] = (theme_rev.revenue /
                        theme_rev.groupby("main_group").revenue.shift(12) - 1) * 100
    themes, theme_rows = {}, []
    for gname, cs in sorted(members.items()):
        if len(cs) < MIN_PE_MEMBERS:
            continue
        sub_px = pxw[cs]
        idx = (1 + sub_px.pct_change(fill_method=None).mean(axis=1).fillna(0)).cumprod() * 100
        pe_med = pew[cs].median(axis=1)
        pe_med[pew[cs].notna().sum(axis=1) < MIN_PE_MEMBERS] = np.nan
        pe_valid = pe_med.dropna()
        if len(pe_valid) < 52:
            continue
        qv = [rnd(pe_valid.quantile(q)) for q in QS]
        pctl = float((pe_valid <= pe_valid.iloc[-1]).mean() * 100)
        g = theme_rev[theme_rev.main_group == gname].yoy.dropna()
        y0, y1 = (rnd(g.iloc[-1], 1), rnd(g.iloc[-2], 1)) if len(g) >= 2 else (None, None)
        badges = []
        if any(k in gname for k in TRAP_KEY):
            badges.append("⚠循環股PE陷阱")
        elif any(k in gname for k in MR_KEY):
            badges.append("偏均值回歸")
        if pctl <= 10:
            badges.append("★便宜格")
        if y0 is not None and y1 is not None:
            if y0 > y1:
                badges.append("營收回升↗" + ("(轉正)" if y0 > 0 >= y1 else ""))
        themes[gname] = {"px": [rnd(v) for v in idx], "pe": [rnd(v) for v in pe_med],
                         "q": qv, "pctl": round(pctl, 1), "n": len(cs),
                         "pe_now": rnd(pe_valid.iloc[-1]), "y0": y0, "y1": y1,
                         "badges": badges}
        theme_rows.append((gname, pctl))

    # ---- 個股層 ----
    cl_map = cl.groupby("code").main_group.apply(lambda s: "/".join(sorted(set(s)))).to_dict()
    stocks, bot_rows, top_rows = {}, [], []
    for c_ in pxw.columns:
        s_px, s_pe, s_pb = pxw[c_], pew[c_], pbw[c_]
        pe_valid = s_pe.dropna()
        if s_px.notna().sum() < 60 or len(pe_valid) < 60:
            continue
        first = int(np.argmax(s_px.notna().values))
        qpe = [rnd(pe_valid.quantile(q)) for q in QS]
        pbv = s_pb.dropna()
        qpb = [rnd(pbv.quantile(q)) for q in QS] if len(pbv) >= 60 else None
        # PER週更會落後價格1-2週:最後有效值在3週內=可算位階;更舊=虧損斷流不給
        lv = s_pe.last_valid_index()
        if lv is None or (weeks[-1] - lv).days > 21:
            pctl = None
        else:
            pctl = float((pe_valid <= pe_valid.iloc[-1]).mean() * 100)
        y = ryo.get(c_)
        badges = []
        if pctl is not None and pctl <= 10:
            badges.append("河底")
            if y and y[0] is not None and y[1] is not None and y[0] > y[1]:
                badges.append("★營收回升×河底")
            elif y and y[0] is not None and y[0] > 0:
                badges.append("⚠成長背離")
        if pctl is not None and pctl >= 90:
            badges.append("河頂警示")
        nm = names.get(c_, "")
        stocks[c_] = {"s": first, "px": [rnd(v) for v in s_px.iloc[first:]],
                      "pe": [rnd(v) for v in s_pe.iloc[first:]],
                      "pb": [rnd(v) for v in s_pb.iloc[first:]],
                      "qpe": qpe, "qpb": qpb, "pctl": rnd(pctl, 1),
                      "name": nm, "theme": cl_map.get(c_, ""),
                      "pe_now": rnd(pe_valid.iloc[-1]), "y": y and [y[0], y[1], y[2]],
                      "badges": badges}
        if pctl is not None and pctl <= 10:
            bot_rows.append(c_)
        if pctl is not None and pctl >= 90:
            top_rows.append(c_)

    bot_rows.sort(key=lambda c: (0 if "★營收回升×河底" in stocks[c]["badges"] else 1,
                                 stocks[c]["pctl"]))
    top_rows.sort(key=lambda c: -stocks[c]["pctl"])
    theme_rows.sort(key=lambda x: x[1])

    payload = {"weeks": wlabels, "themes": themes, "stocks": stocks,
               "theme_order": [t for t, _ in theme_rows],
               "bot": bot_rows[:200], "top": top_rows[:120],
               "asof": wlabels[-1]}

    html = HTML_HEAD + "<script>const D=" + json.dumps(
        payload, ensure_ascii=False, separators=(",", ":")) + ";</script>" + HTML_TAIL
    out = "研究報告/research_pe_river.html"
    open(out, "w", encoding="utf-8").write(html)
    print(f"完成 {out}: 題材{len(themes)}個 / 個股{len(stocks)}檔 / 週軸{len(wlabels)} / "
          f"河底{len(bot_rows)}檔(★{sum(1 for c in bot_rows if '★營收回升×河底' in stocks[c]['badges'])}) / "
          f"河頂{len(top_rows)}檔 / {len(html) / 1e6:.1f}MB")


HTML_HEAD = """<!DOCTYPE html><html><head><meta charset="utf-8"><title>PE/PB河流圖(看盤工具)</title>
<script src="plotly.min.js"></script><style>
body{background:#1a1a19;color:#eee;font-family:"Noto Sans TC",sans-serif;margin:20px;max-width:1150px}
h1{font-size:20px} h2{font-size:15px;color:#c3c2b7;margin-top:26px}
.note{color:#8a8878;font-size:12.5px;line-height:1.8}
.note b{color:#c3c2b7}
select,input{background:#22221f;color:#eee;border:1px solid #444;padding:5px 8px;border-radius:6px;font-size:14px}
table{border-collapse:collapse;font-size:13px;font-variant-numeric:tabular-nums}
td,th{border:1px solid #333;padding:4px 9px;text-align:right} th{text-align:left}
.good{color:#7ec97e}.bad{color:#e06c5a}.warn{color:#c3a55a}.star{color:#e8c34a;font-weight:700}
.tag{display:inline-block;border:1px solid #555;border-radius:10px;padding:0 7px;font-size:11.5px;margin-left:4px;color:#c3c2b7}
a{color:#6bb7e3}
.clk{cursor:pointer;text-decoration:underline dotted}
</style></head><body>
<h1>🏞️ PE/PB 河流圖——「這家公司現在貴還是便宜」一眼看</h1>

<h2>🗣️ 河流圖是什麼？怎麼做的？(白話介紹)</h2>
<div class="note">
<p><b>是什麼:</b>把一檔股票(或一個題材)的「賺錢能力」畫成一條河,股價是河裡的船。
河由五條線組成——把公司每股盈餘(EPS)分別乘上它<b>自己歷史上</b>出現過的低估~高估本益比(PE的10/30/50/70/90百分位),
得到五條「等值線」。<b>船貼河底=用自己史上最便宜的價錢在交易;船衝出河頂=用史上最貴的估值在交易</b>。
河道本身會隨獲利上下移動:獲利成長,整條河往上抬(同樣PE對應更高股價);獲利衰退,河往下沉——
這就是河流圖比「只看股價創新高/新低」高明的地方:它同時把「賺多少」跟「給多貴」分開看。</p>
<p><b>怎麼做的:</b>官方每天公布本益比(PER),我們用「收盤價÷PER」反推出市場口徑的近四季EPS(EPS_ttm),
再乘固定PE分位得到河道(PB版同理:收盤÷PBR反推每股淨值BPS)。題材版=成員等權週指數當船、
成員正PER中位數(至少5檔有效)當題材PE。資料2018年起、週頻;虧損期間官方不給PER,河會斷流(灰段)——這本身就是資訊。</p>
<p><b>怎麼用(本專案已驗證的判決,詳見 research_valuation.html):</b><br>
① <b>題材版河底=唯一驗證過的活訊號</b>:題材PE位階≤10(便宜格)→次2月+4.16%/69%,絕對+超額雙軌排0——
但73%樣本集中2022=<b>熊市工具</b>,是「跌到自己地板」的熊市買點,不是隨時可用的訊號。<br>
② <b>個股版河底=參考不是訊號</b>:全市場初驗絕對報酬無edge(diff含0),只有「相對其他股略抗跌」(超額+1.31排0);
河底裡「營收雙殺出清組」反而最強、「營收還很好卻掉到河底(成長背離)」最弱——<b>便宜要配悲觀,不是配成長</b>。<br>
③ <b>河頂=輕警示</b>:位階≥90之後溫和偏弱(超額-0.85排0,8年7負),提醒減碼審查,強度不足以做空。<br>
④ <b>⚠循環股PE陷阱</b>:記憶體/CPO這類景氣循環題材<b>反向</b>——獲利頂時E爆增讓PE看起來超便宜,低PE=該賣不該買。
買循環股別看PE河流,看產業週期。</p>
<p><b>★「營收開始轉好×河底」標記(法人愛用組合):</b>多數法人喜歡「跌到河流下緣(或歷史PE位階低點)+
營收出現回升拐點」再進場——本頁把「位階≤10 且 最新月營收yoy高於前月」的自動標★。
注意研究注記:「開始轉好」指的是<b>拐點</b>(可以還是負的,剛從谷底回升),這與初驗最強的「悲觀出清組」相容;
若營收早就很好還躺在河底,是背離(市場不信這獲利),初驗裡是最弱組,標⚠別誤當便宜。</p>
<p><b>限制:</b>E修正混淆(PE變便宜可能是E被上修,也可能是價跌一半;河道抬升要看是不是真獲利)、
虧損股無PER斷流、分類表2025-26整理有倖存者偏差、位階用全史百分位(看盤口徑,與研究的expanding口徑略異)。</p>
</div>
"""

HTML_TAIL = """
<h2>📌 題材版河流圖(便宜格的視覺化)</h2>
<div>題材:<select id="selTheme"></select> <span id="themeInfo"></span></div>
<div id="chTheme" style="height:430px"></div>
<h2>題材總覽(按PE位階由低到高;★便宜格=已驗證熊市買點)</h2>
<div id="tblTheme"></div>

<h2>🔎 個股版河流圖(看盤參考)</h2>
<div>個股:<input id="inpStock" list="dlStock" placeholder="輸入代號或名稱" style="width:220px">
<datalist id="dlStock"></datalist>
<select id="selMode"><option value="pe">PE河流</option><option value="pb">PB河流</option></select>
<span id="stockInfo"></span></div>
<div id="chStock" style="height:430px"></div>
<h2>河底清單(個股PE位階≤10;★=營收回升×河底)</h2>
<div class="note">參考層非訊號:河底只有「相對抗跌」沒有絕對edge;⚠成長背離=營收還正卻在河底,初驗最弱組。</div>
<div id="tblBot"></div>
<h2>河頂警示(個股PE位階≥90;輕度減碼審查)</h2>
<div id="tblTop"></div>
<div class="note" style="margin-top:20px">產生器 build_pe_river.py(隨update_all重產);位階=全史百分位;
營收=fm_month_rev最新期vs前期yoy;判決出處=research_valuation.html;資料至 <span id="asof"></span>。</div>
<script>
const BG={paper_bgcolor:"#1a1a19",plot_bgcolor:"#22221f",font:{color:"#ddd",size:12},
  margin:{t:44,l:55,r:18,b:40},legend:{orientation:"h"},hovermode:"x unified"};
const BANDC=["#2c6e49","#4c956c","#8a8878","#c3a55a","#e06c5a"];
const BLAB=["超便宜P10","便宜P30","中位P50","偏貴P70","超貴P90"];
document.getElementById("asof").textContent=D.asof;

function bandTraces(weeks,px,val,q){
  // val=PE(或PB)序列; 河道線k = px*q[k]/val (= EPS_ttm×q[k])
  const tr=[];
  for(let k=0;k<5;k++){
    const y=val.map((v,i)=>(v&&px[i])?+(px[i]*q[k]/v).toFixed(2):null);
    tr.push({x:weeks,y:y,name:BLAB[k]+"("+q[k]+"x)",mode:"lines",
      line:{color:BANDC[k],width:1},fill:k?"tonexty":undefined,
      fillcolor:"rgba(120,140,120,0.10)",
      hovertemplate:"%{y:,.1f}<extra>"+BLAB[k]+"</extra>"});
  }
  tr.push({x:weeks,y:px,name:"價格",mode:"lines",line:{color:"#f0f0f0",width:2},
    hovertemplate:"%{y:,.1f}<extra>價格</extra>"});
  return tr;
}
function badgeHtml(bs){return (bs||[]).map(b=>{
  const cls=b.startsWith("★")?"star":(b.startsWith("⚠")?"warn":"");
  return '<span class="tag '+cls+'">'+b+"</span>";}).join("");}
function yoyTxt(y0,y1){
  if(y0===null||y0===undefined)return "—";
  const c0=y0>0?"good":"bad",c1=(y1||0)>0?"good":"bad";
  return '<span class="'+c0+'">'+y0.toFixed(1)+"%</span>(前期<span class='"+c1+"'>"+
    (y1===null?"—":y1.toFixed(1)+"%")+"</span>)";}

// ---- 題材版 ----
const selT=document.getElementById("selTheme");
D.theme_order.forEach(t=>{const o=document.createElement("option");o.value=t;
  const th=D.themes[t];o.textContent=t+"(位階"+th.pctl+(th.badges.some(b=>b.startsWith("★"))?"★":"")+")";
  selT.appendChild(o);});
function drawTheme(){
  const t=selT.value,th=D.themes[t];
  Plotly.react("chTheme",bandTraces(D.weeks,th.px,th.pe,th.q),
    Object.assign({title:t+" PE河流(成員等權指數,起點=100;現在PE "+th.pe_now+
      " / 位階"+th.pctl+")",yaxis:{title:"等權指數",type:"log"}},BG));
  document.getElementById("themeInfo").innerHTML=
    "成員"+th.n+"檔｜PE位階<b>"+th.pctl+"</b>｜營收yoy "+yoyTxt(th.y0,th.y1)+badgeHtml(th.badges);
}
selT.onchange=drawTheme;

// 題材總覽表
(function(){
  let h="<table><tr><th>題材</th><th>成員</th><th>現在PE</th><th>PE位階</th><th>營收yoy(最新/前期)</th><th>標記</th></tr>";
  D.theme_order.forEach(t=>{const th=D.themes[t];
    const pc=th.pctl<=10?'<b class="star">'+th.pctl+"</b>":(th.pctl>=90?'<span class="warn">'+th.pctl+"</span>":th.pctl);
    h+="<tr><th><span class='clk' onclick='selT.value=\\""+t+"\\";drawTheme()'>"+t+"</span></th><td>"+th.n+
       "</td><td>"+th.pe_now+"</td><td>"+pc+"</td><td>"+yoyTxt(th.y0,th.y1)+"</td><td style='text-align:left'>"+
       badgeHtml(th.badges)+"</td></tr>";});
  document.getElementById("tblTheme").innerHTML=h+"</table>";
})();

// ---- 個股版 ----
const dl=document.getElementById("dlStock");
Object.keys(D.stocks).forEach(c=>{const o=document.createElement("option");
  o.value=c;o.label=c+" "+D.stocks[c].name;dl.appendChild(o);});
const inp=document.getElementById("inpStock"),selM=document.getElementById("selMode");
function drawStock(){
  let c=inp.value.trim().split(" ")[0];
  if(!D.stocks[c]){ // 名稱搜尋
    const hit=Object.keys(D.stocks).find(k=>D.stocks[k].name&&D.stocks[k].name.includes(inp.value.trim()));
    if(hit)c=hit;else return;
  }
  const s=D.stocks[c],mode=selM.value;
  const q=mode==="pe"?s.qpe:s.qpb,val=mode==="pe"?s.pe:s.pb;
  const weeks=D.weeks.slice(s.s);
  if(!q){document.getElementById("stockInfo").textContent="此股PB資料不足";return;}
  Plotly.react("chStock",bandTraces(weeks,s.px,val,q),
    Object.assign({title:c+" "+s.name+" "+(mode==="pe"?"PE":"PB")+"河流"+
      (s.pctl!==null?"(PE位階"+s.pctl+")":"(最新PER缺值=虧損中)"),
      yaxis:{title:"股價",type:"log"}},BG));
  document.getElementById("stockInfo").innerHTML=(s.theme?"題材:"+s.theme+"｜":"")+
    "現在PE "+(s.pe_now||"—")+"｜位階<b>"+(s.pctl===null?"—(虧損)":s.pctl)+"</b>｜營收yoy "+
    (s.y?yoyTxt(s.y[0],s.y[1])+"(至"+s.y[2]+")":"—")+badgeHtml(s.badges);
}
inp.onchange=drawStock;selM.onchange=drawStock;
function stockTable(list,elId){
  let h="<table><tr><th>股票</th><th>題材</th><th>現在PE</th><th>位階</th><th>營收yoy(最新/前期)</th><th>標記</th></tr>";
  list.forEach(c=>{const s=D.stocks[c];
    h+="<tr><th><span class='clk' onclick='inp.value=\\""+c+"\\";drawStock()'>"+c+" "+(s.name||"")+
       "</span></th><td style='text-align:left'>"+(s.theme||"—")+"</td><td>"+(s.pe_now||"—")+"</td><td>"+s.pctl+
       "</td><td>"+(s.y?yoyTxt(s.y[0],s.y[1]):"—")+"</td><td style='text-align:left'>"+badgeHtml(s.badges)+"</td></tr>";});
  document.getElementById(elId).innerHTML=h+"</table>";
}
stockTable(D.bot,"tblBot");stockTable(D.top,"tblTop");
// 初始畫面
if(D.theme_order.length){selT.value=D.theme_order[0];drawTheme();}
if(D.bot.length){inp.value=D.bot[0];drawStock();}
</script></body></html>"""


if __name__ == "__main__":
    main()
