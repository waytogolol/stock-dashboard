# -*- coding: utf-8 -*-
"""回補歷史週快照（估算值）：用 yfinance 收盤價×成交量估算每日成交金額，
重建過去每週日的五市場排名，寫入 capital_flow.db。

- 只回補 2026-06-21（第一筆真實快照）之前的週日，絕不覆蓋真實抓取的資料
- 宇宙 = 目前各市場排行榜成分股（有生存者偏差：當時很熱但已跌出榜的不會出現）
- 金額為估算值，與官方成交金額有小差異（鉅額/盤後交易等）

風控機制：
- 自適應節流：成功慢慢加速、失敗指數退避(30s→60s→120s→240s→300s)
- 斷點續傳：每批存快取 tmp_backfill_cache.pkl，中斷重跑自動續傳、不重複請求
- 熔斷：連續3批全空判定被限流，保存進度後主動停止

用法: python backfill_history.py [週數，預設26]
被限流中斷後，等一段時間直接重跑同一指令即可續傳。
"""
import os
import pickle
import sqlite3
import sys
import time
from datetime import date, timedelta

import pandas as pd
import yfinance as yf

import os as _os
DB = _os.environ.get("CF_DB", "capital_flow.db")   # 研究沙盒: set CF_DB=research_2022.db
EARLIEST_REAL = date(2026, 6, 21)   # 第一筆真實快照，只回補這之前
CHUNK = 50                          # 每批檔數，小批次避免請求過猛
BASE_SLEEP = 4                      # 批次間基礎間隔(秒)
CACHE = "tmp_backfill_cache.pkl" if DB == "capital_flow.db" else f"tmp_backfill_{DB.replace('.db','')}.pkl"

UNIVERSE_FILES = {
    "台": "tw_top300.csv",
    "日": "jp_top500.csv",
    "韓": "kr_top400.csv",
    "陸": "cn_top600.csv",
    "美": "us_top700.csv",
}
UNIT = {"台": "TWD", "日": "JPY_million", "韓": "KRW", "陸": "CNY", "美": "USD"}


class RateGuard:
    """風控：自適應節流 + 熔斷"""
    def __init__(self, base_sleep=BASE_SLEEP, max_fail=3):
        self.sleep_s = base_sleep
        self.consec_fail = 0
        self.max_fail = max_fail

    def ok(self):
        self.consec_fail = 0
        self.sleep_s = max(BASE_SLEEP, self.sleep_s * 0.8)   # 成功後緩慢恢復速度
        time.sleep(self.sleep_s)

    def fail(self):
        """回傳 True = 熔斷（該停了）"""
        self.consec_fail += 1
        cool = min(300, 30 * (2 ** (self.consec_fail - 1)))  # 30→60→120→240→300
        print(f"  [風控] 冷卻 {cool}s（連續失敗 {self.consec_fail}/{self.max_fail}）")
        time.sleep(cool)
        self.sleep_s = min(20, self.sleep_s * 2)              # 之後放慢節奏
        return self.consec_fail >= self.max_fail


def load_cache():
    if os.path.exists(CACHE):
        with open(CACHE, "rb") as f:
            return pickle.load(f)
    return {}


def save_cache(cache):
    with open(CACHE, "wb") as f:
        pickle.dump(cache, f)


def backfill_sundays(n_weeks):
    d = EARLIEST_REAL - timedelta(days=7)
    out = []
    for _ in range(n_weeks):
        out.append(d)
        d -= timedelta(days=7)
    return sorted(out)


def ticker_variants(country, code):
    """回傳 yahoo ticker 候選清單（按優先序），空list=跳過"""
    if country == "台":
        return [code + ".TW", code + ".TWO"]
    if country == "日":
        if len(code) == 4 and code.isdigit():
            return [code + ".T"]
        return [code + "A.T"]          # 新型含字母代碼(285→285A.T)
    if country == "韓":
        if len(code) == 6 and code.isdigit():
            return [code + ".KS", code + ".KQ"]
        return []                      # 特殊代碼(0126Z0等)跳過
    if country == "陸":
        if code.startswith("sh"):
            return [code[2:] + ".SS"]
        if code.startswith("sz"):
            return [code[2:] + ".SZ"]
        return []                      # 北交所 yahoo 無資料
    if country == "美":
        return [code.replace("/", "-")]
    return []


def download_batch(tickers, start, end, cache, guard):
    """分批下載成交金額序列。cache: {ticker: series 或 None(試過沒資料)}"""
    todo = [t for t in tickers if t not in cache]
    skip = len(tickers) - len(todo)
    if skip:
        print(f"  快取已有 {skip} 檔，跳過重複請求")
    for i in range(0, len(todo), CHUNK):
        chunk = todo[i:i + CHUNK]
        df = None
        try:
            df = yf.download(chunk, start=start, end=end, interval="1d",
                             group_by="ticker", auto_adjust=False,
                             threads=True, progress=False)
        except Exception as e:
            print(f"  批次 {i//CHUNK+1} 例外: {e}")
        got = 0
        if df is not None and not df.empty:
            for t in chunk:
                try:
                    sub = df[t] if len(chunk) > 1 else df
                    s = (sub["Close"] * sub["Volume"]).dropna()
                    s = s[s > 0]
                    cache[t] = s if len(s) else None
                    if len(s):
                        got += 1
                except Exception:
                    cache[t] = None
        save_cache(cache)   # 每批即存，中斷不丟進度
        n_ok = sum(1 for v in cache.values() if v is not None)
        print(f"  進度 {min(i+CHUNK, len(todo))}/{len(todo)}，本批有效 {got}，累計有效 {n_ok}")
        if df is None or df.empty or got == 0:
            if guard.fail():
                print("\n[熔斷] 連續失敗達上限，疑似被限流。進度已存快取，"
                      "請等 10 分鐘以上後重跑同一指令續傳。")
                sys.exit(1)
        else:
            guard.ok()
    return cache


def main(n_weeks):
    snapshots = backfill_sundays(n_weeks)
    start = str(snapshots[0] - timedelta(days=10))
    end = str(snapshots[-1] + timedelta(days=1))
    print(f"回補 {len(snapshots)} 週: {snapshots[0]} ~ {snapshots[-1]}")

    # 1) 宇宙與 ticker 對照
    plan = []   # (country, code, name, [variants])
    for country, fname in UNIVERSE_FILES.items():
        uni = pd.read_csv(fname, dtype=str)
        for _, r in uni.iterrows():
            variants = ticker_variants(country, r["code"])
            if variants:
                plan.append((country, r["code"], r["name"], variants))
    print(f"宇宙共 {len(plan)} 檔")

    # 2) 下載（主要代碼 -> 備用代碼），全程風控+快取
    cache = load_cache()
    guard = RateGuard()
    primary = sorted(set(p[3][0] for p in plan))
    print("下載主要代碼...")
    cache = download_batch(primary, start, end, cache, guard)
    fallback = sorted(set(
        p[3][1] for p in plan
        if len(p[3]) > 1 and cache.get(p[3][0]) is None
    ))
    if fallback:
        print(f"下載備用代碼({len(fallback)}檔)...")
        cache = download_batch(fallback, start, end, cache, guard)

    # 3) 每檔選定最終資料
    resolved, missing = {}, []
    for country, code, name, variants in plan:
        hit = next((v for v in variants if cache.get(v) is not None), None)
        if hit:
            resolved[(country, code)] = cache[hit]
        else:
            missing.append(f"{country}{code}")
    print(f"對到資料 {len(resolved)} 檔，無資料 {len(missing)} 檔")

    # 4) 歷史匯率
    print("下載歷史匯率...")
    fx_raw = yf.download(["TWD=X", "JPY=X", "KRW=X", "CNY=X"], start=start, end=end,
                         interval="1d", group_by="ticker", auto_adjust=False,
                         threads=True, progress=False)
    fx_close = {c: fx_raw[c]["Close"].dropna() for c in ["TWD=X", "JPY=X", "KRW=X", "CNY=X"]}

    def fx_asof(series, snap):
        s = series[series.index.date <= snap]
        return float(s.iloc[-1]) if len(s) else None

    # 5) 逐週建排名寫入DB
    conn = sqlite3.connect(DB)
    names = {(c, k): n for c, k, n, _ in plan}
    total_rows = 0
    for snap in snapshots:
        week_start = snap - timedelta(days=6)
        usdtwd = fx_asof(fx_close["TWD=X"], snap)
        usdjpy = fx_asof(fx_close["JPY=X"], snap)
        usdkrw = fx_asof(fx_close["KRW=X"], snap)
        usdcny = fx_asof(fx_close["CNY=X"], snap)
        if usdtwd:
            fx_rows = [(str(snap), "TWD", 1.0), (str(snap), "USD", usdtwd)]
            if usdjpy: fx_rows.append((str(snap), "JPY", usdtwd / usdjpy))
            if usdkrw: fx_rows.append((str(snap), "KRW", usdtwd / usdkrw))
            if usdcny: fx_rows.append((str(snap), "CNY", usdtwd / usdcny))
            conn.executemany("INSERT OR REPLACE INTO fx_rates (snapshot_date,currency,twd_per_unit) VALUES (?,?,?)", fx_rows)

        snap_summary = []
        for country in UNIVERSE_FILES:
            rows = []
            for (c, code), turnover in resolved.items():
                if c != country:
                    continue
                s = turnover[(turnover.index.date >= week_start) & (turnover.index.date <= snap)]
                if not len(s):
                    continue
                amt = float(s.iloc[-1])   # 該週最後一個交易日
                if country == "日":
                    amt = amt / 1e6       # JPY -> 百萬日圓
                rows.append((code, amt))
            rows.sort(key=lambda x: -x[1])
            db_rows = [
                (str(snap), country, code, names[(country, code)], i + 1, amt, UNIT[country])
                for i, (code, amt) in enumerate(rows)
            ]
            conn.executemany(
                "INSERT OR REPLACE INTO rankings (snapshot_date,country,code,name,rank,amount,amount_unit) VALUES (?,?,?,?,?,?,?)",
                db_rows,
            )
            total_rows += len(db_rows)
            snap_summary.append(f"{country}{len(db_rows)}")
        conn.commit()
        print(f"{snap}: {' '.join(snap_summary)}")

    conn.close()
    with open("tmp_backfill_report.txt", "w", encoding="utf-8") as f:
        f.write(f"回補完成: {len(snapshots)}週, 共{total_rows}筆排名\n")
        f.write(f"無資料跳過({len(missing)}檔): {', '.join(missing)}\n")
    print(f"完成！共寫入 {total_rows} 筆，報告見 tmp_backfill_report.txt")


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 26
    main(n)
