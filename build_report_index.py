# -*- coding: utf-8 -*-
"""研究報告目錄頁 -> 研究報告/index.html
CATALOG手動維護(新報告加一行即可)，依研究日期新→舊排序；日期=該考卷判決日。
用法: python build_report_index.py
"""

CATALOG = [
    # (研究日期, 檔名, 主題, 策略開發狀態, 一句話判決)
    # 狀態: live=✅已上板 tool=🧭時機工具 watch=🟡觀察層 wip=⏳研究中 dead=❌否定封存 meta=📊總覽
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
<span class="s-meta">📊總覽</span>=彙整頁</div>
<table><tr><th>日期</th><th>主題</th><th>策略開發</th><th>一句話判決</th></tr>{rows}</table>
</body></html>"""
    open("研究報告/index.html", "w", encoding="utf-8").write(html)
    print(f"目錄已產出 研究報告/index.html ({len(CATALOG)}份報告)")


if __name__ == "__main__":
    main()
