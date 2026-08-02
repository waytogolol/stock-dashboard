# -*- coding: utf-8 -*-
"""台股「財報董事會日期」抓取(預告優先，查無預告則退而求其次存實際核准/公告日)
-> capital_flow.db.tw_board_earnings_dates (供財報事件研究用，見 研究腳本/財報事件/)

背景(2026-08查證，取代不明來源的MoneyDJ理財行事曆「財報公告」欄):
  使用者假說＝台股個股別財報「預告」機制＝董事會召開預告(重大訊息)。查證結果:
  ①MOPS新版(mops.twse.com.tw)無獨立「預計財務報告公告日期」查詢頁；
  ②MOPS舊版 mopsov.twse.com.tw/mops/web/t05st01 (依「公司代號+民國年」查詢重大訊息，
    免登入GET即可，同check_earnings.py風格)裡確實找得到規則明文依據＝金管會2024年起新制:
    上市櫃公司預計於董事會通過季報/年報時，須事先於重大訊息公告董事會預計召開日期
    (至少提前7日，因公司法召集董事會需提前7日通知)。
  ③實測驗證(2330台積電/4979華星光等)：主旨寫法不只一種，已知三種變體皆含
    "財務報告"+"董事會"+"日期"字樣:
      - "公告民國113年度第一季合併財務報告之董事會決議日期"(2330,113/05/02預告→113/05/10核准，提前8天)
      - "公告本公司113年第一季財務報告董事會召開日期"(4979,113/04/25→113/05/03，提前8天)
      - "公告決議民國113年度第四季合併財務報告之董事會預計召開日期為114年02月12日"(2330,114/01/24→114/02/12，提前19天)
    實際核准/公告訊息主旨固定含"財務報告"+"董事會"+"決議通過"，此類訊息2024年之前即存在(無預告)。
  ④誠實限制：預告類訊息確認為2024Q1起才有(112年度以前查無)，但即使2024年後也不是每家/每季必發
    (2330本身2025Q1~Q3即未見預告，只補發了2024Q4/年報那筆)，非100%覆蓋的官方欄位，故存為nullable。
    另，大型權值股(如台積電)常在法說會自結數當天就先公布EPS，數週後才召開董事會核准正式財報，
    此時「董事會核准」日已非市場第一次得知數字的時點(該情境已有研究腳本/法說會/build_conference_*.py
    另外處理)；中小型未開法說會的公司則董事會核准公告較可能是市場第一次得知財報內容的時點。
  ⑤MOPS無「全市場當日重大訊息」批次端點(t05st01需co_id逐檔查)，故只能逐檔查詢，非整批API。

範圍(2026-08-02使用者裁示縮小，務實優先於涵蓋率): 只抓tw_top300.csv裡「成交金額排名」
      前TOP_N大(預設40，可調30~50)，不做額外中小型隨機抽樣(舊版n_extra=300經實測會導致
      MOPS對逐檔高頻查詢軟性阻擋而卡死，且抓完300~600檔耗時過長不切實際，故拿掉)；
      回溯YEARS_BACK個民國年(預設3年，2024Q1新制上路後至今應已完整涵蓋)。
      更早的實際核准日期MOPS仍查得到，但預告類訊息2024年前必為空，故不刻意拉更長。
用法: python 抓取/fetch_tw_earnings_dates.py [TOP_N(預設40)] [回溯年數(預設3)]
      (建議在專案根目錄執行；40檔x3年≈120次查詢，每次查詢間隔SLEEP秒禮貌限速，
      預估約10~15分鐘。若連續CONSEC_WARN家完全查無資料會印警告並拉長冷卻，
      避免真的被官方網站軟性阻擋卻渾然不知。)
"""
import re
import sqlite3
import sys
import time
from datetime import date

import pandas as pd
import requests
from bs4 import BeautifulSoup

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DB = "capital_flow.db"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
HEADERS = {"User-Agent": UA, "Referer": "https://mopsov.twse.com.tw/mops/web/t05st01"}
SLEEP = 2.5           # 官方網站逐檔查詢禮貌限速(2026-08-02實測0.4秒過於積極，會觸發軟性阻擋)
CONSEC_WARN = 5        # 連續N家完全查無資料 -> 印警告+拉長冷卻(懷疑被阻擋)
COOLDOWN = 60          # 觸發警告後的冷卻秒數
SEED = 42

SEASON_MAP = {"一": 1, "二": 2, "三": 3, "四": 4}

PRE_MUST = ("財務報告", "董事會")


def is_pre_announce(subj):
    return all(k in subj for k in PRE_MUST) and "日期" in subj and "通過" not in subj


def is_actual(subj):
    # 已知寫法："...業經董事會決議通過..."/"公告董事會決議通過..."/"公告本公司董事會通過..."，
    # 共同點只有「通過」二字(不一定接"決議"/"核定")，故僅要求財務報告+董事會+通過三詞同時出現。
    return all(k in subj for k in PRE_MUST) and "通過" in subj


def extract_period(subj):
    """從主旨文字取財報期別；台股無獨立Q4季報(第四季併入年報)，故第四季正規化為年報(A)。"""
    m = re.search(r"(\d{2,3})年度?第?([一二三四])季", subj)
    if m:
        y = int(m.group(1)) + 1911
        s = SEASON_MAP[m.group(2)]
        return f"{y}A" if s == 4 else f"{y}Q{s}"
    m2 = re.search(r"(\d{2,3})年度", subj)
    if m2:
        return f"{int(m2.group(1)) + 1911}A"
    return None


def fetch_company_year(co_id, typek, roc_year, tries=2, timeout=15, retry_wait=2):
    """查一家公司某民國年度全部重大訊息(單一GET含全年，非分頁)，回傳[(date_iso, subj_無空白), ...]
    tries/timeout刻意壓低(2次x15秒)：MOPS若軟性阻擋(掛住連線到逾時而非明快拒絕)，
    單一請求最壞情況只等 2x(15+2)=34秒，不會像舊版3x(20+3)≈69秒那樣拖垮整個迴圈。"""
    params = {"co_id": co_id, "year": str(roc_year), "step": "1", "firstin": "true", "TYPEK": typek}
    for i in range(tries):
        try:
            r = requests.get("https://mopsov.twse.com.tw/mops/web/t05st01", params=params,
                              headers=HEADERS, timeout=timeout)
            r.encoding = "utf-8"
            soup = BeautifulSoup(r.text, "html.parser")
            table = soup.select_one("table.hasBorder")
            if table is None:
                return []
            rows = []
            for tr in table.find_all("tr")[1:]:
                tds = tr.find_all("td")
                if len(tds) < 5:
                    continue
                d = tds[2].get_text(strip=True)
                subj = re.sub(r"\s+", "", tds[4].get_text())
                try:
                    y, m, dd = d.split("/")
                    iso = date(int(y) + 1911, int(m), int(dd)).isoformat()
                except ValueError:
                    continue
                rows.append((iso, subj))
            return rows
        except requests.RequestException:
            time.sleep(retry_wait)
    return []


def build_universe(top_n):
    """只取tw_top300.csv裡成交金額排名前top_n大(2026-08-02裁示：不做額外中小型隨機抽樣，
    務實抓得完、抓得穩優先於涵蓋率)"""
    top = pd.read_csv("tw_top300.csv", dtype={"code": str}).sort_values("rank")
    top["typek"] = top["market"].apply(lambda s: "otc" if "櫃" in s else "sii")
    uni = top[["code", "name", "rank", "typek"]].head(top_n).drop_duplicates(subset="code")
    return uni.reset_index(drop=True)


def main():
    top_n = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    n_years = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    uni = build_universe(top_n)
    roc_now = date.today().year - 1911
    years = list(range(roc_now - n_years + 1, roc_now + 1))
    print(f"universe={len(uni)}檔(tw_top300成交金額排名前{top_n}大), 查詢民國年={years}, "
          f"SLEEP={SLEEP}秒/請求, 預估上限≈{len(uni) * len(years) * (SLEEP + 1) / 60:.1f}分")
    print("涵蓋名單: " + "、".join(f"{r.code}{r.name}(#{r.rank})" for r in uni.itertuples()))

    all_rows = []  # (code, period, kind, date_iso, subj)
    empties = 0
    consec_empty = 0
    t0 = time.time()
    for i, r in enumerate(uni.itertuples()):
        code, typek = r.code, r.typek
        got_any = False
        for yr in years:
            rows = fetch_company_year(code, typek, yr)
            time.sleep(SLEEP)
            if not rows and yr == years[-1]:
                alt = "sii" if typek == "otc" else "otc"  # 型別可能過期(轉板)，換一種重試
                rows = fetch_company_year(code, alt, yr)
                time.sleep(SLEEP)
            for iso, subj in rows:
                if is_pre_announce(subj):
                    p = extract_period(subj)
                    if p:
                        all_rows.append((code, p, "pre", iso, subj))
                        got_any = True
                elif is_actual(subj):
                    p = extract_period(subj)
                    if p:
                        all_rows.append((code, p, "actual", iso, subj))
                        got_any = True
        if not got_any:
            empties += 1
            consec_empty += 1
        else:
            consec_empty = 0
        if consec_empty >= CONSEC_WARN:
            print(f"⚠警告: 連續{consec_empty}檔({code}含)完全查無資料，疑似被MOPS軟性阻擋，"
                  f"冷卻{COOLDOWN}秒後繼續...")
            time.sleep(COOLDOWN)
            consec_empty = 0
        if (i + 1) % 10 == 0 or (i + 1) == len(uni):
            el = time.time() - t0
            remain = el / (i + 1) * (len(uni) - i - 1)
            print(f"進度 {i + 1}/{len(uni)}  已累積事件{len(all_rows)}筆  查無資料{empties}檔  "
                  f"耗時{el / 60:.1f}分 預估剩餘{remain / 60:.1f}分")

    print(f"\n迴圈已跑完全部{len(uni)}檔目標公司清單(非中途中斷)。")
    uni.assign(got_data=uni.code.isin({c for c, *_ in all_rows})).to_csv(
        "快取/tmp_tw_board_dates_universe.csv", index=False, encoding="utf-8-sig")
    if not all_rows:
        print("查無任何資料，未寫入DB")
        return

    df = pd.DataFrame(all_rows, columns=["code", "period", "kind", "date", "subj"])
    df.to_pickle("快取/tmp_tw_board_dates_raw.pkl")  # 原始逐筆證據，供稽核/除錯

    mkt_map = dict(zip(uni.code, uni.typek))
    pre = (df[df.kind == "pre"].sort_values("date")
           .groupby(["code", "period"], as_index=False).first()[["code", "period", "date", "subj"]]
           .rename(columns={"date": "pre_date", "subj": "pre_subj"}))
    act = (df[df.kind == "actual"].sort_values("date")
           .groupby(["code", "period"], as_index=False).first()[["code", "period", "date", "subj"]]
           .rename(columns={"date": "actual_date", "subj": "actual_subj"}))
    merged = pd.merge(pre, act, on=["code", "period"], how="outer")
    merged["market"] = merged.code.map(mkt_map)
    both = merged.pre_date.notna() & merged.actual_date.notna()
    merged["lead_days"] = pd.NA
    merged.loc[both, "lead_days"] = (pd.to_datetime(merged.loc[both, "actual_date"])
                                      - pd.to_datetime(merged.loc[both, "pre_date"])).dt.days
    today = str(date.today())
    merged["fetched"] = today

    conn = sqlite3.connect(DB, timeout=30)
    conn.execute("""CREATE TABLE IF NOT EXISTS tw_board_earnings_dates (
        code TEXT, market TEXT, period TEXT,
        pre_date TEXT, pre_subj TEXT,
        actual_date TEXT, actual_subj TEXT,
        lead_days INTEGER, fetched TEXT,
        PRIMARY KEY (code, period))""")
    cols = ["code", "market", "period", "pre_date", "pre_subj", "actual_date", "actual_subj", "lead_days", "fetched"]
    conn.executemany(f"INSERT OR REPLACE INTO tw_board_earnings_dates VALUES ({','.join(['?'] * len(cols))})",
                      merged[cols].where(pd.notna(merged[cols]), None).values.tolist())
    conn.commit()
    n_total, n_codes = conn.execute(
        "SELECT COUNT(*), COUNT(DISTINCT code) FROM tw_board_earnings_dates").fetchone()

    # CSV快照(近期watch用途，比照專案既有*_earnings_watch.csv風格)
    names = pd.read_sql("SELECT code, name_zh FROM company_names WHERE country='台'", conn)
    conn.close()
    watch = merged.merge(names, on="code", how="left").sort_values(
        ["actual_date", "pre_date"], na_position="first")
    watch = watch[["code", "name_zh", "market", "period", "pre_date", "actual_date", "lead_days"]]
    watch.to_csv("tw_earnings_board_watch.csv", index=False, encoding="utf-8-sig")

    n_both = int(both.sum())
    n_pre_only = int((merged.pre_date.notna() & merged.actual_date.isna()).sum())
    n_act_only = int((merged.pre_date.isna() & merged.actual_date.notna()).sum())
    lead = merged.loc[both, "lead_days"]
    print(f"\n完成。本次跑：{len(uni)}檔 x {len(years)}個民國年，共取得{len(df):,}筆事件訊息")
    print(f"合併去重後 {len(merged):,} 個(code,period)：兩者皆有(可算提前天數)={n_both}、僅預告={n_pre_only}、僅實際={n_act_only}")
    if n_both:
        print(f"提前天數：中位數{lead.median():.0f}天 / 平均{lead.mean():.1f}天 / "
              f"範圍[{lead.min():.0f},{lead.max():.0f}]")
    print(f"DB tw_board_earnings_dates 累積 {n_total:,} 筆 / {n_codes} 檔")
    print(f"CSV -> tw_earnings_board_watch.csv ({len(watch):,} 列)")


if __name__ == "__main__":
    main()
