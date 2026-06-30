# 股市資金流向追蹤 — 使用說明

## 每週更新資料(建議頻率：約一週一次)
```
python weekly_refresh.py
```
會自動：重新抓取台/日/韓/陸/美五市場成交金額排行 → 套用既有分類規則 → 抓最新匯率 → 寫入新的snapshot到 `capital_flow.db` → 重新產出 `dashboard.html`。

執行完會印出「新進榜但還沒分類」的公司清單(如果有的話)，可以手動補進對應的 `classify_tw.py` / `classify_jp.py` / `classify_kr.py` / `classify_cn.py` 的 `MAP` 字典裡。

## 看視覺化儀表板(兩種方式任選)

### 方式A：靜態網頁(推薦給懶人，不需要開終端機)
直接**雙擊 `dashboard.html`**，會用預設瀏覽器打開。資料是上次跑 `weekly_refresh.py` 時的快照，內嵌在檔案裡，不需要Python或伺服器執行。
- 「公司歷史趨勢」分頁的圖表需要連網(去抓Plotly.js的CDN)，其他兩個分頁可離線看
- 缺點：是固定快照，要看最新資料得重新跑一次 `python export_html.py`(或直接跑`weekly_refresh.py`，會自動產生)
- **這個檔案只在你自己電腦上能打開**，不是一個網址連結，別人沒有這個檔案就看不到(下面「分享給別人看」章節有說明怎麼做成真正的連結)

### 方式B：互動式儀表板(功能更完整)
```
streamlit run app.py
```
會在瀏覽器開一個本地網頁(預設 http://localhost:8501)，需要終端機保持執行中。同樣只有你自己的電腦能連，別人不能用這個網址。

兩種方式的內容一致，三個分頁：
1. **題材跨市場比較** — 預設只顯示前10大「題材概念股」熱度分數排行(排除金融/消費/傳統產業等廣義分類)，選一個族群(被動元件/CPO等)看各國入榜公司明細，依排名熱度上色。熱度分數=該題材在每個國家的「台幣金額÷該國全部上榜公司台幣金額總和」百分比，五國加總而成，分數越高代表資金集中度越高
2. **排行榜明細** — 篩選國家+題材的完整排行表，可點表頭排序
3. **公司歷史趨勢** — 選一家公司看排名隨時間變化(累積多次snapshot後才有趨勢可看)

金額欄位有兩種：「金額(億)」是該國原始幣別(億元/億韓元/億日圓/億人民幣/億美元)，「金額(億台幣)」是換算成台幣方便跨市場比較(用snapshot當天的即時匯率換算，存進資料庫，不會被之後的匯率波動影響歷史資料)。

## 財報/法說會提醒(隨時可查，不限週更)
```
python check_earnings.py [天數，預設14]
```
查未來N天美股財報日曆 + 台股法人說明會排程，**只列出有在我們追蹤名單裡(us_top700/tw_top300)的公司**，會標出該公司屬於哪個主族群(題材)，方便知道近期要注意誰。輸出存成`us_earnings_watch.csv`和`tw_earnings_watch.csv`。

注意：台股不像美股那樣有強制規定要提前公告確切的財報發布日，這裡抓的是「法人說明會」排程(MOPS官方公告)，跟實際財報發布日不一定完全同一天，但通常時間相近，可以當作觀察重點。日股、韓股也有類似的官方排程資料源(日股Kabutan的決算發表予定、韓股KRX的IR일정)，已確認可行但還沒實作，需要再擴充。

## 分享給別人看(把dashboard.html變成真正的網址連結)
目前的 `dashboard.html` 只是你電腦裡的一個檔案，雙擊打開是用 `file://` 本機路徑，**沒辦法直接傳一個連結給別人**。如果想讓別人用瀏覽器網址打開，需要把這個檔案放到某個網頁伺服器上，常見免費做法(由你決定要不要做，目前都還沒設置)：
- **GitHub Pages**：把這個資料夾放成一個GitHub repo，開啟Pages功能，免費拿到一個 `xxx.github.io` 網址。缺點是repo通常是公開的，等於把所有分類資料公開給任何人看
- **Netlify / Vercel 免費方案**：拖曳資料夾上傳就能拿到一個網址，也可以設成需要密碼才能看
- 不管哪種方式，因為資料是寫死內嵌在HTML裡的快照，要更新就要重新上傳一次新產生的`dashboard.html`，不會自動同步

## 資料來源
| 市場 | 資料源 | 存取方式 | 備註 |
|---|---|---|---|
| 台股上市 | [台灣證券交易所(TWSE)](https://www.twse.com.tw) | 官方OpenAPI `exchangeReport/MI_INDEX` | 免登入，當日成交資訊，需用最近交易日日期 |
| 台股上櫃 | [證券櫃買中心(TPEx)](https://www.tpex.org.tw) | 官方API `web/stock/aftertrading/daily_close_quotes` | 免登入，日期用民國年格式 |
| 日股 | [株探(Kabutan)](https://kabutan.jp) | 網頁`warning/trading_value_ranking`(売買代金ランキング) | 需要瀏覽器標頭(User-Agent/Referer)才能存取，否則會被擋；該站另有`themes/`主題股頁面可交叉比對分類，尚未串接 |
| 韓股 | KRX(韓國交易所)資料 | Python套件 [FinanceDataReader](https://github.com/FinanceData/FinanceDataReader) | 免登入免註冊，本身已排除ETF；Naver Finance有「테마」(主題)頁面可交叉比對分類，尚未串接 |
| 陸股 | 新浪財經(sina.com.cn) | Python套件 [akshare](https://github.com/akfamily/akshare) 的`stock_zh_a_spot()` | 免登入；**東方財富(eastmoney.com)的API在這個環境會被擋(502)，改用新浪財經**，本身已排除ETF/債券 |
| 美股 | [Nasdaq官方screener](https://www.nasdaq.com/market-activity/stocks/screener) | API `api.nasdaq.com/api/screener/stocks?download=true` | 免登入，一次拿全市場含sector/industry分類 |
| 匯率 | [open.er-api.com](https://www.exchangerate-api.com/) | 免費API，免註冊 | 每次更新時抓當天匯率存進資料庫，換算歷史資料不受後續匯率波動影響 |

族群/題材分類(`classify_*.py`)是依我自己的產業知識手動整理，**不是來自任何單一外部資料庫**，沒把握辨識的公司會留白標「未分類」，不會亂猜。中文名稱對照表(`names_*.py`)同樣是手動整理(陸股例外，用`zhconv`套件自動簡轉繁，不算手動翻譯)。

## 檔案說明
| 檔案 | 用途 |
|---|---|
| `fetch_top200.py` | 抓取五市場排行的核心邏輯(各市場抓幾名可在`TOP_N`調整) |
| `classify_*.py` | 各市場的族群/題材分類規則(MAP字典，可手動增補) |
| `names_*.py` | 日/韓/美股的中文簡稱對照表(code -> 中文名，可手動增補；陸股不需要，用zhconv自動簡轉繁) |
| `weekly_refresh.py` | 一鍵更新流程(抓取+分類+匯率+寫入資料庫+產出靜態網頁) |
| `build_db.py` | 把CSV資料寫進SQLite資料庫(含匯率表、中文名稱表) |
| `app.py` | Streamlit互動式儀表板 |
| `export_html.py` | 把資料庫匯出成單一靜態HTML檔案(`dashboard.html`) |
| `dashboard.html` | 雙擊打開的靜態網頁(由`export_html.py`產生，不要手動編輯) |
| `capital_flow.db` | SQLite資料庫(所有歷史snapshot都存在這裡) |
| `all_classified.csv` | 最新一次的完整分類結果(主族群,細分產品,國家,排名,代碼,公司,產業地位) |
| `check_earnings.py` | 查美股財報日曆+台股法說會排程，比對觀察名單，隨時可單獨執行 |
| `PROGRESS.md` | 開發過程記錄(資料源細節、踩過的坑、決策原因，比這份README更詳細) |
