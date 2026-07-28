# -*- coding: utf-8 -*-
"""研究報告目錄頁 -> 研究報告/index.html
CATALOG手動維護(新報告加一行即可)，依研究日期新→舊排序；日期=該考卷判決日。
用法: python build_report_index.py
"""

CATALOG = [
    # (研究日期, 檔名, 主題, 策略開發狀態, 一句話判決)
    # 狀態: live=✅已上板 tool=🧭時機工具 watch=🟡觀察層 wip=⏳研究中 dead=❌否定封存 meta=📊總覽 view=🔍盤感工具
    ("2026-07-29", "research_margin_band.html", "融資維持率警戒帶(上市×上櫃雙市判決)", "tool",
     "上櫃公式版2011起全史;E1上櫃<150首破成立觀察層(n=12,k60+9.12%/75%,0.77次/年);E3真發現=兩市同破強出清"
     "(k60+11.12%/80%)vs上櫃單獨破=中小型領跌警訊短線負;E2位階版不加值/E4剪刀差極端=中小型續弱2週避開提示;"
     "權益曲線E1→櫃買1.89x曝險19%MDD-24.6% vs 買進持有2.45x MDD-41%;死格=慢熊中段+首破後短線可再殺20%=帶內等急跌收斂再進"),
    ("2026-07-29", "research_attention_rules.html", "注意/處置法規逐款解剖(條文正源×研究註解)", "meta",
     "13款精確門檻(上市×上櫃差異)+處置升級四路徑+加重處置機制+11條核對發現(基數只計款1-8/連5路徑v1漏掉已補/"
     "快速道含款一bug已修/當沖加時12日/第一次處置僅大單預收/處置期間注意不計基數/款六=估值+換手+集中三重門)+"
     "計時器v2可算性路線圖;靜態彙整,法規改版時人工更新(build_attention_rules_report.py)"),
    ("2026-07-28", "research_pe_river.html", "PE/PB河流圖(題材版+個股版看盤工具)", "view",
     "股價疊自家歷史PE分位(10/30/50/70/90)×EPS_ttm等值線;題材版=便宜格(位階≤10,估值線唯一活格熊市買點)視覺呈現;"
     "個股版=河底參考(無絕對edge僅相對抗跌,雙殺出清>成長背離)+河頂輕警示;★=營收回升拐點×河底(法人格);"
     "⚠記憶體/CPO循環股PE陷阱(低PE=獲利頂);產生器build_pe_river.py隨update_all重產"),
    ("2026-07-20", "research_attention.html", "注意股票跌觸發買訊(完整版2026-07-26:權益曲線+持有網格+分組)", "watch",
     "晉級候選未上板:t10中位+5.62%/66%(0.45%房規口徑,n=477,LOTO 8/8+差值CI[+2.37,+12.11]續過;0.3%錨+5.77%重現0720判決✓);"
     "持有網格=報酬隨持有遞增t20+13.59%/70%(10日非甜蜜點,與共振「8週太短」同構);分組=事後升級處置組-2.31%/45%是虧損來源(未升級+9.47%/75%)"
     "但事前代理(30日6次+)切不開;題材成員+8.72%/75%方向加分(n=36不顯著);初犯連續無差;"
     "⚠2026年-2.50%/28%(n=39)=首個負年份警訊,上板前建議先live驗證數月;單利Σ+4,537pp/MDD-227pp/cap10版Σ+2,128pp"),
    ("2026-07-26", "research_conference.html", "法說會事件研究(買方死/賣方出貨窗)", "watch",
     "買方全滅:事後跟進-1.76%(安慰劑對照後真效應-0.84pp CI排0)/事前埋伏-0.12%CI含0/偷看答案H2特徵外推失敗(位階指紋=借來的動能);"
     "賣方觀察層:sell-the-news有劑量+出貨窗只在中小型→最強避開格=中小型×法說前已大漲(後10日-2.69%/38%,11/12月負),大型權值不適用;"
     "資料=conference表(Yahoo滾動一年,每週fetch_conference_yahoo),單一regime限制,轉正需MOPS歷史或live累積;使用者裁示先留研究頁不上板"),
    ("2026-07-27", "research_attention_trades.html", "注意股跌觸發逐筆K棒檢視器", "view",
     "477筆跌觸發交易逐筆K棒(公告前15根+持有段+後10根)+進出場/公告日/T+20參考線+cohort標準路徑帶;"
     "標籤✓規則卡(49筆)/⚠事後升級處置(149筆=虧損主源,親眼看長相);篩選=年/賺賠/規則卡/升級組,排序=劑量/金流;"
     "產生器build_attention_trade_viewer.py(價格或attention更新後重跑);2026警訊活案例=5386青雲公告後續跌-39%"),
    ("2026-07-25", "research_disposition_trades.html", "處置V4逐筆交易K棒檢視器", "view",
     "全2,953筆V4交易逐筆K棒+進出場/攤平點/標準路徑帶(產生器build_disposition_trade_viewer.py,價格更新後重跑);"
     "配套路徑考卷判決:窗內停損❌(8年0正,砍在統計谷底)/跌-10%攤平✅(配對差5分+1.65pp/20分+1.80pp,LOTO8/8,-15%以下別攤)/"
     "漲+3%加碼❌;d4w複驗=20分盤轉正/5分盤候選,live口徑d4w>0;內建G1-G4/V4/V5規則速查"),
    ("2026-07-20", "research_pledge_release.html", "H-解質(內部人高檔解質=賣方訊號)", "watch",
     "✅成立=體系首個個股層賣方訊號:內部人(董座/大股東)×高檔位階≥80×大額≥1000張→x60超額-6.90%/36%(n=330);配對複核過(配對差-3.93pp CI上緣<0);放空載具❌(中位真均值假右尾屠殺,停損版仍1.45x/MDD-60%)=訊號屬防守;質押面二題❌(低檔補提無增量/存量無梯度)=方向專一三度確認;上板警戒標記等裁示"),
    ("2026-07-20", "research_tx_tail.html", "H-尾盤結構性賣壓(台指期全史)", "watch",
     "主測1長黑順勢空⏳(淨均+0.16%/65%,CI下緣+0.08>0但6/8年=微樣本年拖累);主測2週三長紅回吐空✅(82%,n=11,非週三對照CI含0=週三特異);機制指紋雙確認=劑量單調+殺盤集中13:00-25強平窗;2026週五新制方向一致n=5待累積"),
    ("2026-07-19", "research_bottom_playbook.html", "🧭大盤低點作戰手冊(分型系統)", "tool",
     "亞跌五分型(B純亞跌=頭牌k10+3.12%/78%)+溫度計+⑥深跌選股+堆疊複驗+休市旗標+live檢查清單;7/17案例套用;核心=非資訊性賣壓四度統一"),
    ("2026-07-18", "research_panic_thermometer.html", "⑤恐慌溫度計", "tool",
     "成立(觀察層)：甜蜜格單日並發≥20＝7大恐慌日全命中零前視，k60中位+14.2%/83%，天真「大跌買」≈基準；死格=2022慢熊中段"),
    ("2026-07-18", "research_index_seasonal.html", "③雙指數月曆+③b全球九市場對照", "watch",
     "加權12月最強(泛亞共通)/9月弱降信度(全球九月已死=本地或雜訊)；7月弱=除息假象鐵證(全球7月是強月)但8月=亞洲共通真逆風；10月小型股逆風台美共通(結構性增信)；2月=農曆圈+SOX"),
    ("2026-07-17", "research_cb_mine.html", "CB礦山(CB線總判決)", "wip",
     "alpha在載具結構非事件訊號：題材×100-110×13月死線=2.24x/MDD-11.7%，發動哨續持2.66x；事件層死十餘卷；⚠待cb_daily流動性複核v2"),
    ("2026-07-15", "research_panic_liquidity.html", "恐慌流動性三部曲(漲停/梯度/處置)", "live",
     "處置V4晉級(bootstrap p<1e-4,月群CI[+2.30,+4.91])＝儀表板第5檢視；甜蜜格單筆過但MDD-60.6%=時機工具；擁擠化無遞減反變肥"),
    ("2026-07-14", "research_theme_momentum.html", "題材月營收動能(score=4)", "live",
     "score=4逐年全正確立為規則基底(XQ訊號組)；季節性=觸發率10-11月高但報酬反差(候選撤)；新聞熱度因子look-ahead-safe版驗證"),
    ("2026-07-13", "research_gap_dip_theme.html", "開低承接×題材級變體", "watch",
     "題材整體開低版延伸考卷；與個股版互補性檢查"),
    ("2026-07-12", "research_gap_dip.html", "個股恐慌開低隔夜承接", "tool",
     "需大盤紅日+月線上；只有T開盤進場有效(跳空吃肉機制)；與甜蜜格/c4的regime互補"),
    ("2026-07-12", "research_portfolio_overview.html", "策略棧總覽", "meta",
     "S3⑤強訊號+階梯=4.98x/夏普1.52/MDD-18.6%/2022年+1.0%=凸性代表作；新考卷通過就疊線"),
    ("2026-07-12", "research_chip_confirm.html", "籌碼確認訊號(外資位階)", "live",
     "A1(起漲51-300+外資20日位階≥80)=8.33x/夏普1.69/57% vs A0對照5.77x=濾網增量真實(儀表板籌碼徽章)；窗2023起無2022段為最大保留"),
    ("2026-07-11", "research_weekly_momo.html", "週級強者續強", "watch",
     "絕對強度>20%成立；位階化版否定→方法論：位階化只適用水準/存量特徵，事件強度吃絕對量級"),
    ("2026-07-11", "research_2022_report.html", "凍結規則2022-2026壓力測試(主卷)", "live",
     "151筆熊市交易明細主庫；規則①~⑤儀表板live；微題材/型態探勘/保留集驗證章節陸續注入；多考卷引用的母卷"),
]

STATUS = {
    "live": ("s-live", "✅已上板"), "tool": ("s-tool", "🧭時機工具"),
    "watch": ("s-watch", "🟡觀察層"), "wip": ("s-wip", "⏳研究中"),
    "dead": ("s-dead", "❌否定封存"), "meta": ("s-meta", "📊總覽"),
    "view": ("s-tool", "🔍盤感工具"),
}

CSS = """
body{background:#1a1a19;color:#fff;font-family:"Noto Sans TC",sans-serif;margin:24px;max-width:1100px}
h1{font-size:20px}
table{border-collapse:collapse;font-size:13px}
td,th{border:1px solid #333;padding:7px 12px;text-align:left;vertical-align:top}
a{color:#6bb7e3;text-decoration:none} a:hover{text-decoration:underline}
.d{color:#8a8878;white-space:nowrap;font-variant-numeric:tabular-nums}
.note{color:#8a8878;font-size:12px;line-height:1.7}
.s{white-space:nowrap}
.s-live{color:#7ec97e}.s-tool{color:#6bb7e3}.s-watch{color:#c3a55a}
.s-wip{color:#b393d3}.s-dead{color:#e06c5a}.s-meta{color:#8a8878}
"""


def main():
    rows = "".join(
        f"<tr><td class='d'>{d}</td><td><a href='{f}'>{topic}</a></td>"
        f"<td class='s {STATUS[st][0]}'>{STATUS[st][1]}</td><td>{verdict}</td></tr>"
        for d, f, topic, st, verdict in CATALOG)
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>研究報告目錄</title>
<style>{CSS}</style></head><body>
<h1>📚 研究報告目錄（新→舊）</h1>
<div class="note">研究日期=該考卷判決日；詳細判決與全部死卷紀錄見 封存/研究_*/研究紀錄MD 與專案記憶。
新報告產出後在 build_report_index.py 的 CATALOG 加一行重跑。<br>
策略開發狀態：<span class="s-live">✅已上板</span>=儀表板/XQ live執行中｜
<span class="s-tool">🧭時機工具</span>=擇時觀察用,不單獨成策略｜
<span class="s-watch">🟡觀察層</span>=判決成立,累積樣本/等裁示｜
<span class="s-wip">⏳研究中</span>=複核或定稿未完｜
<span class="s-dead">❌否定封存</span>=負判決僅留檔｜
<span class="s-meta">📊總覽</span>=彙整頁｜
<span class="s-tool">🔍盤感工具</span>=逐筆走勢檢視,非回測判決頁</div>
<table><tr><th>日期</th><th>主題</th><th>策略開發</th><th>一句話判決</th></tr>{rows}</table>
</body></html>"""
    open("研究報告/index.html", "w", encoding="utf-8").write(html)
    print(f"目錄已產出 研究報告/index.html ({len(CATALOG)}份報告)")


if __name__ == "__main__":
    main()
