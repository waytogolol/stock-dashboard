# 爬蟲注意事項（避免 IP 封鎖）

## 慘痛教訓（MOPS 案例）

mopsov.twse.com.tw 被封鎖超過 48 小時，原因是初期請求速度過快，
觸發政府網站主動 IP 黑名單，且不會自動解除。

---

## 事前：開爬前必做的 4 件事

### 1. 先查有沒有官方 API
在動手寫爬蟲前，檢查以下順序：
- 官方開放資料平台（如 TWSE: openapi.twse.com.tw）
- 第三方聚合服務（FinMind、CSMAR、TEJ）
- 網站是否有 CSV/Excel 下載功能（手動或 form POST）
- 網站的 `robots.txt`（`網址/robots.txt`），不允許爬的路徑就不要碰

### 2. 從瀏覽器開發者工具逆向
用 Chrome DevTools > Network Tab，找真實的 API endpoint：
- 政府/金融網站通常有隱藏的 JSON API（比 HTML 好解析，也比較不敏感）
- 找到後先用 `curl` 手動測一次，確認不需要 session token

### 3. 先用 1~2 頁測試，絕對不要直接全量跑
```python
# 壞習慣：直接全量
for month in all_months:  # 可能 60 個月
    fetch(month)

# 好習慣：先測試 2 筆
for month in all_months[:2]:
    fetch(month)
    time.sleep(10)
```

### 4. 估算請求總量 → 決定速率
- 總請求數 × 每秒上限 = 最短完成時間
- 原則：**讓網站感覺不到你的存在**
- 政府/金融網站：**最少 10 秒間隔，建議 15~30 秒**
- 一般商業網站：最少 3~5 秒

---

## 執行中：保護 IP 的設定

```python
import time, random, requests
from requests.adapters import HTTPAdapter

DELAY_MIN = 10     # 秒，政府網站
DELAY_MAX = 20
MAX_RETRIES = 2    # 失敗不要一直 retry，2次就停
TOTAL_REQUESTS_PER_SESSION = 20   # 超過就重建 session + 長休眠

def make_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept-Language": "zh-TW,zh;q=0.9",
        "Connection": "close",   # 不要 keep-alive，降低關聯性
    })
    return s

def safe_fetch(session, url, retries=0):
    try:
        r = session.get(url, timeout=30)
        r.raise_for_status()
        return r
    except Exception as e:
        if retries >= MAX_RETRIES:
            print(f"[放棄] {url}: {e}")
            return None
        wait = 30 * (retries + 1)   # 第1次失敗等30秒，第2次等60秒
        print(f"[重試 {retries+1}] 等待 {wait}s...")
        time.sleep(wait)
        return safe_fetch(make_session(), url, retries + 1)

# 每N筆重建 session，模擬新用戶
request_count = 0
session = make_session()
for item in targets:
    if request_count > 0 and request_count % 15 == 0:
        session.close()
        session = make_session()
        time.sleep(random.uniform(60, 120))   # 長休眠
    result = safe_fetch(session, item)
    time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
    request_count += 1
```

---

## 發現 IP 被封後的處理

### 症狀判斷
| 症狀 | 可能原因 | 解法 |
|------|----------|------|
| HTTP 403 | 反爬蟲規則觸發 | 調整 header，等幾小時 |
| ConnectionError (TCP拒絕) | IP 黑名單 | 需要換 IP |
| HTTP 429 Too Many Requests | 速率限制（軟封鎖） | 等 24h，再降速 |
| 回傳空白/假資料 | 蜜罐/偽裝 | 停止，分析回傳內容 |

#### MOPS 實際狀況（已驗證 2026-07）

MOPS 使用**應用層 WAF**，而不只是 IP 封鎖：
- GET `/mops/web/index` → ✅ 200 OK（公開歡迎頁，不受保護）
- GET `/mops/web/t05sr01`（搜尋頁） → ❌ RemoteDisconnected
- POST `/mops/web/ajax_t05sr01_3`（查詢 API） → ❌ RemoteDisconnected

即使 IP 沒被封、瀏覽器可正常開啟，Python requests 仍被封鎖。
伺服器會驗證是否為真實瀏覽器（可能包含 JS challenge 或 Browser Fingerprinting）。
`requests` 無法繞過，**唯一程式化解法是 Selenium / Playwright（真實瀏覽器驅動）**。

## 換 IP 方法（由易到難）
1. **重開路由器**（如果 ISP 給動態 IP，可能換到新 IP）
2. **用行動網路熱點** 跑一次（不同 IP 段）
3. **VPN** 切換節點（注意：政府網站可能封 VPN 出口 IP）
4. 如果以上都不行 → **改用替代資料源**（見下方）

### MOPS 替代方案
- **TWSE Open API**：https://openapi.twse.com.tw（有部分公司資料）
- **FinMind**：https://finmindtrade.com（台股聚合資料，有免費 API）
- **手動下載**：登入 MOPS，用篩選條件手動匯出 CSV
- **XBRL 結構化資料**：MOPS 部分公告有 XBRL 格式可程式化解析

---

## 快速 Checklist（每次爬新網站前）

- [ ] 查過 `robots.txt` 了嗎？
- [ ] 有沒有官方 API / CSV 下載可用？
- [ ] 請求間隔 ≥ 10 秒了嗎（政府/金融網站）？
- [ ] 用 1~2 筆測試過再全量跑了嗎？
- [ ] 設了 MAX_RETRIES 上限，失敗不會無限 retry 嗎？
- [ ] session 有定期重建（每 15~20 次）嗎？
- [ ] 失敗時有寫 log，方便事後補跑嗎？
