"""
MOPS 可轉換公司債（國內）董事會決議發行公告抓取
抓取欄位：發行總額、承銷或代銷機構、募得價款之用途及運用計畫、承銷方式

使用規則（避免 IP 被封）：
  - 每次 HTTP 請求之間至少等 5 秒
  - 每個月份的清單查完後再等 8 秒
  - 連線失敗時自動重試，間隔加倍（5 → 10 → 20 秒），重試上限 3 次
  - 每次重試都重建 Session（不重複使用舊的連線）
"""
import requests, time, re, csv, random
from bs4 import BeautifulSoup

BASE = "https://mopsov.twse.com.tw"
UA   = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"

# ── 時間常數（秒）─────────────────────────────────────────
DELAY_BETWEEN_REQUESTS = 5   # 每兩個 HTTP 請求之間的基本等待
DELAY_BETWEEN_MONTHS   = 8   # 每個月份處理完後的額外等待
DELAY_SESSION_INIT     = 4   # 建 Session 取 index 後到第一個 POST 的等待
MAX_RETRIES            = 3   # 連線失敗最多重試次數


def _jitter(base_sec):
    """在 base_sec 基礎上加 0~2 秒隨機抖動，避免規律性請求。"""
    return base_sec + random.uniform(0, 2)


def _new_session():
    """建立一個全新 Session，取一次 index 頁面拿 cookie，然後等待。"""
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Referer":    BASE + "/mops/web/index",
        "Accept":     "text/html,application/xhtml+xml,*/*;q=0.9",
        "Accept-Language": "zh-TW,zh;q=0.9",
        "Connection": "close",   # 不保持長連線，每次請求都重新握手
    })
    s.get(BASE + "/mops/web/index", timeout=12)
    time.sleep(_jitter(DELAY_SESSION_INIT))
    return s


def _post_with_retry(path, data, label=""):
    """
    對 MOPS POST endpoint 發請求，失敗時重建 Session 並以指數退避重試。
    回傳 (response_text, success_bool)。
    """
    wait = DELAY_BETWEEN_REQUESTS
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            s = _new_session()
            r = s.post(BASE + path, data=data, timeout=20)
            r.encoding = "utf-8"
            s.close()
            return r.text, True
        except Exception as e:
            print(f"  [連線失敗] {label} (嘗試 {attempt}/{MAX_RETRIES}): {type(e).__name__}")
            if attempt < MAX_RETRIES:
                sleep_time = _jitter(wait)
                print(f"  → 等待 {sleep_time:.0f} 秒後重試...")
                time.sleep(sleep_time)
                wait *= 2   # 指數退避
            else:
                print(f"  [放棄] {label} 已達重試上限")
                return "", False


# ── Step 1：查詢清單 ──────────────────────────────────────

def search_cb_announcements(roc_year, month):
    """POST ajax_t05sr01_3，關鍵字搜尋「董事會決議發行國內轉換公司債」的重大訊息清單。"""
    data = {
        "encodeURIComponent": "1",
        "step":     "2",
        "firstin":  "1",
        "off":      "1",
        "TYPEK":    "all",
        "year":     str(roc_year),
        "month":    str(month),
        "CO_ID":    "",
        "keyword":  "董事會決議發行國內轉換公司債",
    }
    html, ok = _post_with_retry("/mops/web/ajax_t05sr01_3", data, f"清單查詢 {roc_year}/{month:02d}")
    return html, ok


def parse_announcement_list(html):
    """從清單 HTML 解析出每則公告的基本資訊。"""
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    table = soup.find("table")
    if not table:
        # 印出前 300 字幫助診斷（去除多餘空白）
        preview = " ".join(html.split())[:300]
        print(f"  [警告] 找不到清單表格 → {preview}")
        return rows
    for tr in table.find_all("tr")[1:]:
        tds = tr.find_all("td")
        if len(tds) < 5:
            continue
        code  = tds[0].get_text(strip=True)
        name  = tds[1].get_text(strip=True)
        date  = tds[2].get_text(strip=True)
        seq   = tds[3].get_text(strip=True)
        title = tds[4].get_text(strip=True)
        if "轉換公司債" in title and "國內" in title:
            rows.append({"code": code, "name": name, "date": date, "seq": seq, "title": title})
    return rows


# ── Step 2：取公告全文 ────────────────────────────────────

def fetch_announcement_detail(code, date, seq):
    """POST ajax_t05sr01_2，取單則公告全文。"""
    data = {
        "encodeURIComponent": "1",
        "step":        "2",
        "firstin":     "1",
        "off":         "1",
        "TYPEK":       "all",
        "co_id":       code,
        "announce_dt": date,
        "seqno":       seq,
    }
    html, ok = _post_with_retry("/mops/web/ajax_t05sr01_2", data, f"全文 {code} {date}#{seq}")
    return html, ok


def parse_detail(html):
    """從公告全文 HTML 抽取四個目標欄位。"""
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator="\n")

    # 所有已知欄位名稱，用來判斷「下一個欄位」在哪裡截斷
    all_labels = [
        "發行總額", "承銷或代銷機構", "募得價款之用途及運用計畫", "承銷方式",
        "轉換期間", "轉換價格", "擔保情形", "委託保管銀行", "轉換公司債名稱",
        "董事會決議日期", "預計發行日期", "每張發行金額",
    ]

    def extract(label):
        stop = "|".join(re.escape(l) for l in all_labels if l != label)
        pattern = re.escape(label) + r"\s*[：:]\s*(.+?)(?=" + stop + r"|\Z)"
        m = re.search(pattern, text, re.S)
        if not m:
            return ""
        # 清理多餘的空白與換行
        return re.sub(r"\s+", " ", m.group(1)).strip()

    return {
        "發行總額":                extract("發行總額"),
        "承銷或代銷機構":          extract("承銷或代銷機構"),
        "募得價款之用途及運用計畫": extract("募得價款之用途及運用計畫"),
        "承銷方式":                extract("承銷方式"),
    }


# ── 主流程 ────────────────────────────────────────────────

def fetch_cb_announcements(roc_year=None, months=None, out_csv="cb_announcements.csv"):
    import datetime
    today = datetime.date.today()
    if roc_year is None:
        roc_year = today.year - 1911
    if months is None:
        # 預設查當月＋上個月
        months = [today.month]
        if today.month > 1:
            months.insert(0, today.month - 1)

    print(f"搜尋年度: 民國{roc_year}年，月份: {months}")
    print(f"(每次請求之間至少等 {DELAY_BETWEEN_REQUESTS} 秒，請耐心等候)")

    all_records = []

    for month in months:
        print(f"\n{'='*40}")
        print(f"搜尋 {roc_year}/{month:02d}")
        print(f"{'='*40}")

        html, ok = search_cb_announcements(roc_year, month)
        if not ok:
            print("  清單查詢失敗，跳過此月份")
            continue

        announcements = parse_announcement_list(html)
        print(f"  找到符合「國內轉換公司債」公告: {len(announcements)} 則")

        for i, ann in enumerate(announcements, 1):
            print(f"\n  [{i}/{len(announcements)}] {ann['code']} {ann['name']}  {ann['date']} #{ann['seq']}")
            print(f"    標題: {ann['title'][:60]}")

            time.sleep(_jitter(DELAY_BETWEEN_REQUESTS))

            detail_html, ok = fetch_announcement_detail(ann["code"], ann["date"], ann["seq"])
            if not ok:
                print("    全文取得失敗，略過此則")
                continue

            fields = parse_detail(detail_html)
            record = {**ann, **fields}
            all_records.append(record)

            print(f"    發行總額  : {fields['發行總額'][:80]}")
            print(f"    承銷機構  : {fields['承銷或代銷機構'][:80]}")
            print(f"    承銷方式  : {fields['承銷方式'][:80]}")
            print(f"    款項用途  : {fields['募得價款之用途及運用計畫'][:80]}")

        if month != months[-1]:
            print(f"\n  月份切換，等待 {DELAY_BETWEEN_MONTHS} 秒...")
            time.sleep(_jitter(DELAY_BETWEEN_MONTHS))

    # ── 輸出 CSV ──
    if all_records:
        cols = ["date", "code", "name", "title",
                "發行總額", "承銷或代銷機構", "承銷方式", "募得價款之用途及運用計畫", "seq"]
        with open(out_csv, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(all_records)
        print(f"\n完成！共 {len(all_records)} 筆，已存至 {out_csv}")
    else:
        print("\n查無資料。可能原因：")
        print("  1. 本月/上月尚無符合條件的董事會公告（正常情況）")
        print("  2. MOPS 關鍵字參數需調整（可改為只用 '轉換公司債'）")
        print("  3. IP 仍在封鎖中（明天再試）")

    return all_records


if __name__ == "__main__":
    records = fetch_cb_announcements()
