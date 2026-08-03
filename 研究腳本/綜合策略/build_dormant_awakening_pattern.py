# -*- coding: utf-8 -*-
"""沉寂覺醒型態考卷(2026-08-03,使用者第二個想法接續借殼上市討論):原始假說「大戶持股比例默默
增加預示借殼」需要歷史借殼事件當ground truth標籤,DB裡沒有這份清單,卡在標籤問題。使用者提出改用
純觀察特徵繞開標籤問題:不問「這是不是借殼股」,直接問「本來沒什麼流通性、後來流通性上升且短時間
內上漲很兇、市值小」這個型態本身,在歷史上出現後續怎麼走(續攻或洩壓),用型態搜尋+事件研究法
(同build_sox_reversal_pattern.py方法論),不需要借殼標籤也能測。

型態定義(全部point-in-time,只用截至觸發日t當天已知的資料,不偷看未來):
  沉寂期: t-120~t-20交易日(100日,故意跳過最近20日避免跟覺醒窗重疊)平均日成交金額,
    在當日全市場橫斷面排名後20%分位(用分位數而非絕對金額門檻,因13年橫跨市場規模成長,
    絕對金額門檻會隨時間漂移失真)。
  覺醒: t-20~t交易日(20日)平均日成交金額 / 沉寂期均量 >= 5倍。
  短時間上漲很兇: t-20~t價格報酬 >= +30%(與覺醒窗同一段,兩者本來就該同時發生)。
  市值小: 覺醒窗開始時(t-20,漲之前的市值,對應使用者「本來市值小」的敘事,而非漲完後的市值)
    落在當日全市場橫斷面排名後30%分位。市值=capital表股本(月頻快照,前向填補)×收盤價。
  去重: 同一檔股票60個交易日內只取第一次觸發當錨定日(同SOX考卷方法論,避免同一波行情
    連續觸發灌水樣本數)。

⚠️關鍵限制(誠實列出,不是可忽略細節):
  ①存活者偏差比一般研究更嚴重:fm_daily_price的宇宙是用「現存上市櫃股」名單回填歷史
    (tw_all_listed.csv現況名單),2031檔中只有7檔資料提前中止,幾乎沒有已下市/合併/改名的個股。
    借殼上市的常見結局(股票改名、合併消滅、下市)恰好是最容易被這個資料庫漏掉的案例——
    這個研究能回答的是「型態出現後、若公司還活著且沿用原代碼,股價續攻還是洩壓」,
    不能回答「型態出現後公司後來被借殼掉了嗎」。
  ②有效樣本窗口實際是2019-06~2026-07(~7年):雖然capital股本表2013年就有,但fm_daily_price
    主體1,478檔是2019-01-02才一次性補齊(另172檔回溯到2005),2019年以前橫斷面分位數分母太薄
    (不到500檔)會失真,故只採2019-06-01後的觸發事件(留足120日暖機)。
  ③型態本身不驗證「為什麼」,只驗證「然後呢」——跟SOX考卷同一立場:型態反覆出現不等於機制可靠,
    結果誠實看數字,不腦補故事。

2026-08-03延伸(使用者第三輪追問,四項交叉診斷,皆point-in-time純觀察不改核心觸發定義):
  ①大戶持股比例窗口改52週(~1年)為主、26週留對照——使用者指出借殼收籌碼多半半年~一年才收完,
    原本26週(~6個月)可能太短。②大戶「人數」(tdcc_people.n1000)與比例並列:使用者不確定吃貨是
    集中少數帳戶(人數不變/減少)還是多帳戶佈局(人數增加),純觀察不預設方向。③波動放大領先時間:
    20日/100日已實現波動比率(同流動性覺醒的比率結構,只是用日報酬標準差取代成交金額)是否比
    流動性/價格覺醒更早出現(回看80日內首次>=2倍的領先天數)。④月營收跳躍度(trailing12月YoY
    最大值-中位數):使用者假說=炒營收該是「有一期沒一期」而非穩定成長,用同一指標對全市場算
    無條件基準對比。

2026-08-03第四輪延伸:①股價淨值比(PBR<1.5)+每股淨值法規門檻(BVPS=收盤/PBR反推,全額交割<5元/
停止信用交易<10元票面,WebSearch查證非猜測)交叉驗證。②長紅長黑診斷(|收/開-1|>=5%比例,沉寂期vs
覺醒期)。③早期版(波動先兆版,拿掉流動性5x+漲幅30%門檻,波動放大2x直接觸發)——使用者裁示「不想
等30%才進場感覺太晚」,此版本fwd120勝率49-51%回到接近拋硬幣,優於主版的41-45%(追高效應),已列為
主要觀察名單。④**疊加篩選版(使用者2026-08-03裁示採用)**:單一角度都是弱訊號,但疊加三條件
(BVPS<10元∧PBR<1.5∧52週大戶比例上升)後主版/早期版fwd120中位數從負翻正(+17.75%/+16.28%,
勝率68-72%)——呼應「借殼上市本來就稀少,單一寬鬆條件篩出的樣本是雜訊為主」的判斷,疊加條件才逼近
真正少數樣本。案例:9912偉聯在此清單復現6輪(2020-2025各年),使用者稱有消息其2027年可能借殼,
現況(資料至2026-07-31)大戶比例52週+9.09pp持續墊高、BVPS已低於信用交易門檻、7/28單日成交暴增近
百倍——n=1軼事非統計證明但方向吻合值得追蹤。

用法: python 研究腳本/綜合策略/build_dormant_awakening_pattern.py  (從根目錄執行,鐵律)
產出: 研究報告/research_dormant_awakening_pattern.html
"""
import json
import sqlite3
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

DB = "capital_flow.db"
OUT = "研究報告/research_dormant_awakening_pattern.html"
LOAD_START = "2018-06-01"          # 暖機緩衝,實際採用觸發日 >= EVENT_START
EVENT_START = pd.Timestamp("2019-06-01")
BASE_WIN = 100                      # 沉寂期天數(t-120~t-20)
GAP = 20                            # 覺醒窗/報酬窗天數(t-20~t)
DEDUP_GAP = 60                      # 同碼事件去重(交易日)
K_LIST = [5, 10, 20, 40, 60, 120]
BOOT_N = 3000
rng = np.random.default_rng(42)

# 主版 / 嚴格版 參數(流動性+價格覺醒,較晚但已確認)
MAIN = dict(dormant_pctl=0.20, mult=5.0, rise=0.30, cap_pctl=0.30)
STRICT = dict(dormant_pctl=0.10, mult=8.0, rise=0.50, cap_pctl=0.20)
# 早期版參數(2026-08-03使用者裁示:波動放大領先診斷顯示92.6%案例波動比流動性/價格早~8日出現,
# 既然有領先性,直接把波動放大當主觸發條件,不必等流動性5x+漲幅30%都確認才進場——
# 拿掉PRICE_RET/LIQ_RATIO門檻,用VOL_RATIO取代,市值用觸發當下(非t-20,因為此版無固定GAP錨點)。
EARLY = dict(dormant_pctl=0.20, vol_mult=2.0, cap_pctl=0.30)


# ── 基礎資料載入(寬表:index=date, columns=code) ──────────────
def load_wide():
    con = sqlite3.connect(DB)
    px = pd.read_sql(
        "SELECT code, date, open, high, low, close, money FROM fm_daily_price "
        "WHERE code GLOB '[0-9][0-9][0-9][0-9]' AND date>=?",
        con, params=(LOAD_START,), parse_dates=["date"])
    cap = pd.read_sql(
        "SELECT code, date, shares FROM capital WHERE code GLOB '[0-9][0-9][0-9][0-9]'",
        con, parse_dates=["date"])
    con.close()
    close = px.pivot(index="date", columns="code", values="close").astype("float32")
    close = close.mask(close <= 0)   # 停牌/無成交日部分來源記0,會讓報酬比率爆成inf,一律視為缺值
    open_ = px.pivot(index="date", columns="code", values="open").astype("float32")
    open_ = open_.mask(open_ <= 0)
    high = px.pivot(index="date", columns="code", values="high").astype("float32")
    high = high.mask(high <= 0)
    low = px.pivot(index="date", columns="code", values="low").astype("float32")
    low = low.mask(low <= 0)
    money = px.pivot(index="date", columns="code", values="money").astype("float32")
    shares = cap.pivot(index="date", columns="code", values="shares")
    shares = shares.reindex(close.index).ffill().astype("float32")
    # 五張表欄位聯集對齊(有些代碼只在其中一張表出現)
    cols = close.columns.union(money.columns)
    close = close.reindex(columns=cols)
    open_ = open_.reindex(columns=cols)
    high = high.reindex(columns=cols)
    low = low.reindex(columns=cols)
    money = money.reindex(columns=cols)
    shares = shares.reindex(columns=cols)
    return close, open_, high, low, money, shares


def load_names():
    """沉寂股常常沒上過rankings週榜(rankings只收週成交值前200),改用tw_all_listed.csv全市場名單,
    rankings名稱較新故仍優先覆蓋。"""
    import csv
    names = {}
    with open("tw_all_listed.csv", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            names[row["code"]] = row["name"]
    con = sqlite3.connect(DB)
    df = pd.read_sql("SELECT code, name, snapshot_date FROM rankings WHERE country='台'", con)
    con.close()
    df = df.sort_values("snapshot_date").drop_duplicates("code", keep="last")
    names.update(dict(zip(df.code, df.name)))
    return names


PB_TH = 1.5   # 使用者2026-08-03提案:股價淨值比低(便宜相對淨資產)可能是借殼吸引力之一
# 每股淨值(BVPS)法規門檻(使用者提案,已查證非猜測,見WebSearch來源):
# 全額交割股=最近一期財報每股淨值<5元觸發,回5元以上除名;停止信用交易(融資融券)=面額10元股票
# 每股淨值<票面(10元)觸發暫停,回10元以上恢復。BVPS=收盤價/PBR反推,兩張表都已載入不需新抓取。
BVPS_FULL_DELIVERY_TH = 5.0
BVPS_CREDIT_TH = 10.0


def load_pbr_wide():
    con = sqlite3.connect(DB)
    df = pd.read_sql("SELECT code, date, pbr FROM per_daily WHERE code GLOB '[0-9][0-9][0-9][0-9]'",
                     con, parse_dates=["date"])
    con.close()
    return df.pivot(index="date", columns="code", values="pbr").astype("float32")


TDCC_THRESH = (600, 800, 1000)   # 大戶門檻張數三版本都測,不單押一個(小市值股門檻選擇本身沒有先驗答案)
# 使用者2026-08-03修正:「大戶默默墊高」該看~1年(借殼收籌碼多半半年~一年才收完),
# 52週為主口徑,26週留作對照(看訊號是不是更早期就已經在動,或反而是後期才加速)。
TDCC_WINDOWS = {26: 182, 52: 364}


def load_tdcc_wide():
    con = sqlite3.connect(DB)
    df = pd.read_sql("SELECT code, date, p600, p800, p1000 FROM tdcc_weekly WHERE code GLOB '[0-9][0-9][0-9][0-9]'",
                      con, parse_dates=["date"])
    con.close()
    return {t: df.pivot(index="date", columns="code", values=f"p{t}").astype("float32") for t in TDCC_THRESH}


def load_tdcc_people_wide():
    """大戶人數(非比例):使用者不確定借殼吃貨是集中在少數帳戶(人數不變/減少)還是多帳戶佈局
    (人數增加),兩者都可能,純觀察不預設方向。用n1000(千張門檻)對齊p1000主口徑慣例。"""
    con = sqlite3.connect(DB)
    df = pd.read_sql("SELECT code, date, n1000 FROM tdcc_people WHERE code GLOB '[0-9][0-9][0-9][0-9]'",
                      con, parse_dates=["date"])
    con.close()
    return df.pivot(index="date", columns="code", values="n1000").astype("float32")


CLOSE, OPEN, HIGH, LOW, MONEY, SHARES = load_wide()
NAMES = load_names()
TDCC = load_tdcc_wide()
TDCC_N = load_tdcc_people_wide()
PBR = load_pbr_wide().reindex(CLOSE.index).ffill(limit=5).astype("float32")   # 對齊CLOSE的date index才能用iloc[i]

BASE_MONEY = MONEY.rolling(BASE_WIN, min_periods=BASE_WIN).mean().shift(GAP)
AWAKE_MONEY = MONEY.rolling(GAP, min_periods=GAP).mean()
LIQ_RATIO = AWAKE_MONEY / BASE_MONEY.replace(0, np.nan)
PRICE_RET = CLOSE / CLOSE.shift(GAP) - 1
CAP_PRE = (SHARES.shift(GAP) * CLOSE.shift(GAP)) / 1e8   # 覺醒窗開始時(漲之前)的市值,億元
DORMANT_RANK = BASE_MONEY.rank(axis=1, pct=True)          # 分位數低=越沉寂
CAP_RANK = CAP_PRE.rank(axis=1, pct=True)                 # 分位數低=市值越小
CAP_NOW = (SHARES * CLOSE) / 1e8                           # 早期版用觸發當下市值(無GAP錨點可回溯)
CAP_NOW_RANK = CAP_NOW.rank(axis=1, pct=True)

# 波動放大(使用者新提案):長期穩定→突然放大,不要求方向已明朗,理論上可能比流動性/價格覺醒更早出現。
RET = CLOSE.pct_change(fill_method=None)
VOL_AWAKE = RET.rolling(GAP, min_periods=GAP).std()
VOL_BASE = RET.rolling(BASE_WIN, min_periods=BASE_WIN).std().shift(GAP)
VOL_RATIO = VOL_AWAKE / VOL_BASE.replace(0, np.nan)
VOL_LEAD_THRESH = 2.0    # 波動20日/100日基期倍數門檻
VOL_LOOKBACK = 80        # 往回找多少交易日內首次超過門檻

# 長紅長黑診斷(使用者新提案):吸貨股平常振幅該小,波動放大才會出現長紅/長黑單日大波動,
# 用開盤-收盤實體(非高低點振幅,較貼近K線「長紅長黑」的直覺定義)。
LONG_CANDLE_TH = 0.05
CANDLE_BODY = (CLOSE / OPEN - 1).abs()
LONG_CANDLE = CANDLE_BODY >= LONG_CANDLE_TH
BASE_CANDLE_RATE = float(np.nanmean(LONG_CANDLE.values)) * 100

# 無條件基準(demean用):對整張表算,不限觸發日
BASE_FWD = {k: float(np.nanmean((CLOSE.shift(-k) / CLOSE - 1).values)) * 100 for k in K_LIST}
BASE_TDCC = {}
for w, days in TDCC_WINDOWS.items():
    for t in TDCC_THRESH:
        delta = (TDCC[t] - TDCC[t].shift(w)).values
        BASE_TDCC[(w, t)] = {"mean": float(np.nanmean(delta)), "pos": float(np.nanmean(delta > 0)) * 100}
BASE_TDCC_N = {}
for w in TDCC_WINDOWS:
    delta_n = (TDCC_N - TDCC_N.shift(w)).values
    BASE_TDCC_N[w] = {"mean": float(np.nanmean(delta_n)), "pos": float(np.nanmean(delta_n > 0)) * 100}
_pbr_all = PBR.values.ravel()
_pbr_all = _pbr_all[~np.isnan(_pbr_all)]
BASE_PBR = {"median": float(np.median(_pbr_all)), "below_th_pct": float((_pbr_all < PB_TH).mean()) * 100}

BVPS = CLOSE / PBR.replace(0, np.nan)   # 每股淨值反推(收盤價/PBR)
_bvps_all = BVPS.values.ravel()
_bvps_all = _bvps_all[~np.isnan(_bvps_all)]
BASE_BVPS = {"median": float(np.median(_bvps_all)),
            "below_credit_pct": float((_bvps_all < BVPS_CREDIT_TH).mean()) * 100,
            "below_full_pct": float((_bvps_all < BVPS_FULL_DELIVERY_TH).mean()) * 100}


def build_mask(dormant_pctl, mult, rise, cap_pctl):
    return ((DORMANT_RANK <= dormant_pctl) & (LIQ_RATIO >= mult) &
             (PRICE_RET >= rise) & (CAP_RANK <= cap_pctl))


def build_mask_early(dormant_pctl, vol_mult, cap_pctl):
    return (DORMANT_RANK <= dormant_pctl) & (VOL_RATIO >= vol_mult) & (CAP_NOW_RANK <= cap_pctl)


def extract_events(mask):
    """逐碼掃描mask,>=EVENT_START才採計,同碼60交易日內去重(取錨定日)。"""
    events = []
    dates = mask.index
    start_pos = dates.searchsorted(EVENT_START)
    for code in mask.columns:
        col = mask[code].values
        last = -10 ** 9
        for i in range(start_pos, len(col)):
            if col[i] and (i - last) > DEDUP_GAP:
                events.append((code, dates[i], i))
                last = i
    return events


def tdcc_delta(code, date, thresh, window_days):
    tdf = TDCC[thresh]
    if code not in tdf.columns:
        return np.nan
    s = tdf[code].dropna()
    if s.empty:
        return np.nan
    idx_now = s.index.searchsorted(date, side="right") - 1
    idx_before = s.index.searchsorted(date - pd.Timedelta(days=window_days), side="right") - 1
    if idx_now < 0 or idx_before < 0:
        return np.nan
    return float(s.iloc[idx_now] - s.iloc[idx_before])


def tdcc_count_delta(code, date, window_days):
    if code not in TDCC_N.columns:
        return np.nan
    s = TDCC_N[code].dropna()
    if s.empty:
        return np.nan
    idx_now = s.index.searchsorted(date, side="right") - 1
    idx_before = s.index.searchsorted(date - pd.Timedelta(days=window_days), side="right") - 1
    if idx_now < 0 or idx_before < 0:
        return np.nan
    return float(s.iloc[idx_now] - s.iloc[idx_before])


def candle_rates(code, i):
    """沉寂期(t-120~t-20)長紅長黑比例 vs 覺醒/近期窗(t-20~t)比例,對照使用者假說:
    平常振幅小,波動放大才有長紅長黑。"""
    if code not in LONG_CANDLE.columns:
        return np.nan, np.nan
    col = LONG_CANDLE[code].values
    dormant_win = col[max(0, i - BASE_WIN - GAP):max(0, i - GAP)]
    awake_win = col[max(0, i - GAP):i + 1]
    dr = float(np.nanmean(dormant_win)) * 100 if len(dormant_win) else np.nan
    ar = float(np.nanmean(awake_win)) * 100 if len(awake_win) else np.nan
    return dr, ar


def vol_lead_lag(code, i):
    """觸發日i往回VOL_LOOKBACK個交易日內,波動比率首次>=門檻的位置;回傳領先天數
    (正值=波動放大比流動性/價格覺醒更早出現,0=同一天,NaN=回看窗內未曾超過門檻)。"""
    if code not in VOL_RATIO.columns:
        return np.nan
    s = VOL_RATIO[code].values
    start = max(0, i - VOL_LOOKBACK)
    window = s[start:i + 1]
    hits = np.where(window >= VOL_LEAD_THRESH)[0]
    if len(hits) == 0:
        return np.nan
    return int(i - (start + hits[0]))


def load_revenue():
    """tw_monthly_revenue只存最新一期(3,723列/1,972碼≈每碼1.9列,無歷史)不能用;
    改用fm_month_rev(132,874列/1,333碼,原始營收有深歷史)自算YoY(對前12期)。"""
    con = sqlite3.connect(DB)
    df = pd.read_sql("SELECT code, date, revenue FROM fm_month_rev WHERE code GLOB '[0-9][0-9][0-9][0-9]'",
                     con, parse_dates=["date"])
    con.close()
    df = df.sort_values(["code", "date"])
    df["yoy_pct"] = df.groupby("code")["revenue"].pct_change(12, fill_method=None) * 100
    df["yoy_pct"] = df["yoy_pct"].replace([np.inf, -np.inf], np.nan)   # 前期營收~0會除出inf,視為缺值
    return df


REV = load_revenue()
REV_BY_CODE = {c: g.set_index("date")["yoy_pct"] for c, g in REV.groupby("code")}
REV_LAG_DAYS = 25   # 月營收公告時滯保守估(法定10日內,留安全邊際避免前視)
REV_WIN_MONTHS = 12


def revenue_jumpiness(code, asof_date):
    """跳躍度=trailing 12個已公告月份YoY的(最大值-中位數)。高=有一兩個月特別跳出來(有一期沒一期),
    低=每月都差不多(穩定成長或穩定衰退)。"""
    s = REV_BY_CODE.get(code)
    if s is None or s.empty:
        return np.nan, 0
    cutoff = asof_date - pd.Timedelta(days=REV_LAG_DAYS)
    w = s[s.index <= cutoff].tail(REV_WIN_MONTHS).dropna()
    if len(w) < 6:
        return np.nan, len(w)
    return float(w.max() - w.median()), len(w)


def baseline_revenue_jumpiness():
    """無條件基準:對每檔股票全歷史逐月滾動算同一指標,不限事件日。
    只報中位數:近0期營收基期會讓YoY%炸出天文數字(定義上的極端值非真實訊號),均值被少數
    離群值主宰不可信(事件組均值曾見過均值上看千pp量級),中位數才是穩健統計量。"""
    vals = []
    for s in REV_BY_CODE.values():
        arr = s.values
        if len(arr) < REV_WIN_MONTHS + 6:
            continue
        for i in range(REV_WIN_MONTHS - 1, len(arr)):
            w = arr[i - REV_WIN_MONTHS + 1:i + 1]
            if np.isnan(w).sum() > REV_WIN_MONTHS - 6:
                continue
            vals.append(np.nanmax(w) - np.nanmedian(w))
    v = np.array(vals)
    return {"median": float(np.nanmedian(v)), "n": len(v)}


BASE_REV_JUMP = baseline_revenue_jumpiness()


def event_table(events, cap_frame=None):
    cap_frame = CAP_PRE if cap_frame is None else cap_frame
    rows = []
    for code, d, i in events:
        row = {"code": code, "name": NAMES.get(code, code), "date": d,
               "cap_yi": float(cap_frame[code].iloc[i]) if code in cap_frame.columns else np.nan,
               "dormant_money_wan": float(BASE_MONEY[code].iloc[i]) / 1e4 if code in BASE_MONEY.columns else np.nan,
               "liq_ratio": float(LIQ_RATIO[code].iloc[i]) if code in LIQ_RATIO.columns else np.nan,
               "price_ret20": float(PRICE_RET[code].iloc[i]) * 100 if code in PRICE_RET.columns else np.nan,
               "vol_ratio": float(VOL_RATIO[code].iloc[i]) if code in VOL_RATIO.columns else np.nan,
               "pbr": float(PBR[code].iloc[i]) if code in PBR.columns else np.nan,
               "bvps": float(BVPS[code].iloc[i]) if code in BVPS.columns else np.nan,
               "vol_lead_days": vol_lead_lag(code, i)}
        row["candle_dormant_pct"], row["candle_awake_pct"] = candle_rates(code, i)
        jump, jump_n = revenue_jumpiness(code, d)
        row["rev_jump"], row["rev_jump_n"] = jump, jump_n
        for w in TDCC_WINDOWS:
            row[f"holder_delta{w}w"] = tdcc_count_delta(code, d, TDCC_WINDOWS[w])
            for t in TDCC_THRESH:
                row[f"tdcc_delta{w}w_{t}"] = tdcc_delta(code, d, t, TDCC_WINDOWS[w])
        for k in K_LIST:
            j = i + k
            row[f"fwd{k}"] = (float(CLOSE[code].iloc[j] / CLOSE[code].iloc[i] - 1) * 100
                               if code in CLOSE.columns and j < len(CLOSE) and pd.notna(CLOSE[code].iloc[j])
                               and pd.notna(CLOSE[code].iloc[i]) else np.nan)
        rows.append(row)
    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)


def summarize_k(df):
    out = {}
    for k in K_LIST:
        v = df[f"fwd{k}"].dropna().values
        if len(v) == 0:
            out[k] = {"n": 0}
            continue
        med, mean, win = float(np.median(v)), float(np.mean(v)), float((v > 0).mean() * 100)
        dm = mean - BASE_FWD[k]
        ci = None
        if len(v) >= 10:
            bs = rng.choice(v, size=(BOOT_N, len(v)), replace=True).mean(axis=1)
            ci = (float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5)))
        out[k] = {"n": len(v), "med": med, "mean": mean, "dm": dm, "win": win, "ci": ci}
    return out


def sensitivity_grid():
    rows = []
    for dp in (0.10, 0.20, 0.30):
        for mult in (3, 5, 8):
            row = {"沉寂分位": f"後{int(dp*100)}%", "覺醒倍數": f"{mult}x"}
            for rise in (0.30, 0.50, 1.00):
                mask = build_mask(dp, mult, rise, MAIN["cap_pctl"])
                row[f"+{int(rise*100)}%"] = len(extract_events(mask))
            rows.append(row)
    return rows


def tdcc_crosscheck(df):
    out = {}
    for w in TDCC_WINDOWS:
        for t in TDCC_THRESH:
            v = df[f"tdcc_delta{w}w_{t}"].dropna().values
            if len(v) == 0:
                out[(w, t)] = {"n": 0}
                continue
            out[(w, t)] = {"n": len(v), "mean": float(np.mean(v)), "pos_rate": float((v > 0).mean() * 100),
                           "vs_base_mean": float(np.mean(v)) - BASE_TDCC[(w, t)]["mean"],
                           "vs_base_pos": float((v > 0).mean() * 100) - BASE_TDCC[(w, t)]["pos"]}
    return out


def holder_crosscheck(df):
    out = {}
    for w in TDCC_WINDOWS:
        v = df[f"holder_delta{w}w"].dropna().values
        if len(v) == 0:
            out[w] = {"n": 0}
            continue
        out[w] = {"n": len(v), "mean": float(np.mean(v)), "pos_rate": float((v > 0).mean() * 100),
                  "vs_base_mean": float(np.mean(v)) - BASE_TDCC_N[w]["mean"],
                  "vs_base_pos": float((v > 0).mean() * 100) - BASE_TDCC_N[w]["pos"]}
    return out


def vol_lead_summary(df):
    v = df["vol_lead_days"].dropna().values
    n_total = len(df)
    if len(v) == 0:
        return {"n_fired": 0, "n_total": n_total}
    return {"n_fired": len(v), "n_total": n_total, "fired_pct": len(v) / n_total * 100,
            "med_lead": float(np.median(v)), "mean_lead": float(np.mean(v)),
            "pct_led": float((v > 0).mean() * 100), "pct_same_day": float((v == 0).mean() * 100)}


def bvps_crosscheck(df):
    v = df["bvps"].dropna().values
    if len(v) == 0:
        return {"n": 0}
    return {"n": len(v), "median": float(np.median(v)),
            "below_credit_pct": float((v < BVPS_CREDIT_TH).mean()) * 100,
            "vs_base_credit": float((v < BVPS_CREDIT_TH).mean()) * 100 - BASE_BVPS["below_credit_pct"],
            "below_full_pct": float((v < BVPS_FULL_DELIVERY_TH).mean()) * 100,
            "vs_base_full": float((v < BVPS_FULL_DELIVERY_TH).mean()) * 100 - BASE_BVPS["below_full_pct"]}


def candle_summary(df):
    d = df[["candle_dormant_pct", "candle_awake_pct"]].dropna()
    if len(d) == 0:
        return {"n": 0}
    return {"n": len(d), "dormant_mean": float(d.candle_dormant_pct.mean()),
            "awake_mean": float(d.candle_awake_pct.mean()),
            "ratio": float(d.candle_awake_pct.mean() / d.candle_dormant_pct.mean())
                     if d.candle_dormant_pct.mean() > 0 else np.nan,
            "vs_base_dormant": float(d.candle_dormant_pct.mean()) - BASE_CANDLE_RATE,
            "vs_base_awake": float(d.candle_awake_pct.mean()) - BASE_CANDLE_RATE}


def pbr_crosscheck(df):
    v = df["pbr"].dropna().values
    if len(v) == 0:
        return {"n": 0}
    return {"n": len(v), "median": float(np.median(v)), "below_th_pct": float((v < PB_TH).mean()) * 100,
            "vs_base_below_th": float((v < PB_TH).mean()) * 100 - BASE_PBR["below_th_pct"]}


def rev_jump_summary(df):
    v = df[["rev_jump", "rev_jump_n"]].dropna()
    v = v[v.rev_jump_n >= 6].rev_jump.values
    if len(v) == 0:
        return {"n": 0}
    return {"n": len(v), "median": float(np.median(v)),
            "vs_base_median": float(np.median(v)) - BASE_REV_JUMP["median"]}


# ── 疊加篩選版(使用者2026-08-03裁示採用)────────────────────
# 單一角度都是弱訊號(見上方各交叉驗證),但疊加後fwd120中位數從負翻正——呼應「借殼上市本來就稀少,
# 單一寬鬆條件篩出的800-1400筆是雜訊為主」的判斷,疊加條件才逼近真正的少數樣本。
STACK_TDCC_THRESH = 1000
STACK_WINDOW = 52


def apply_stack_filter(df):
    cond = ((df.bvps < BVPS_CREDIT_TH) & (df.pbr < PB_TH) &
            (df[f"tdcc_delta{STACK_WINDOW}w_{STACK_TDCC_THRESH}"] > 0))
    return df[cond].copy()


# ── 雙濾網疊加版(使用者2026-08-04裁示測試,同樣本挖出來的候選,待新樣本驗證)────
# ①52週大戶增幅門檻從>0拉高到>1.5pp(贏家vs輸家對照挖出來的差異化因子)
# ②排除「觸發日當天本身正是漲停」(使用者原始直覺,經精準操作化後驗證:觸發日非漲停中位+23.75%,
#   觸發日剛好漲停中位-5.07%,連續漲停streak越長越差,乾淨單調——呼應project既有「一字鎖死型漲停
#   後續落後」的獨立驗證,見[[feedback_strategy_research_thinking]]第14條)
COMBINED_TDCC_TH = 1.5
LIMIT_UP_TH = 0.095   # 台股漲停約+10%,留緩衝抓>=9.5%


def t_is_limitup(code, date):
    if code not in CLOSE.columns or date not in CLOSE[code].index:
        return False
    s = CLOSE[code]
    i = s.index.get_loc(date)
    if i == 0 or not np.isfinite(s.iloc[i]) or not np.isfinite(s.iloc[i - 1]) or s.iloc[i - 1] <= 0:
        return False
    return bool((s.iloc[i] / s.iloc[i - 1] - 1) >= LIMIT_UP_TH)


def apply_combined_filter(df):
    cond = ((df.bvps < BVPS_CREDIT_TH) & (df.pbr < PB_TH) &
            (df[f"tdcc_delta{STACK_WINDOW}w_{STACK_TDCC_THRESH}"] > COMBINED_TDCC_TH))
    sub = df[cond].copy()
    not_limitup = [not t_is_limitup(r.code, r.date) for r in sub.itertuples()]
    return sub[not_limitup].copy()


# ── 策略化:進場=早期版疊加,出場=固定持有(2026-08-04使用者要求「進場/出場/權益曲線長怎樣」)──
# 停損/停利已測試過(hold=40/60/90/120 × 停損-15%/-20%)全部讓總報酬與MDD雙雙變差——多數回落中的
# 部位最終會回升,提早停損等於砍在阿呆谷,故正式版=固定持有到期,不設停損停利。
HOLD_DAYS = 120
MAX_CONCURRENT = 5   # 資金實際可行口徑的部位上限(歷史最大同時開倉13筆,保守抓5筆分散)


def build_trades(df, hold_days=HOLD_DAYS):
    """每筆訊號t進場(收盤價),固定持有hold_days交易日後收盤出場(不足則出場於最後可得交易日)。"""
    trades = []
    for _, r in df.iterrows():
        code, d = r.code, r.date
        if code not in CLOSE.columns:
            continue
        s = CLOSE[code]
        if d not in s.index:
            continue
        i = s.index.get_loc(d)
        entry_px = s.iloc[i]
        if not np.isfinite(entry_px) or entry_px <= 0:
            continue
        j = min(i + hold_days, len(s) - 1)
        exit_px = s.iloc[j]
        if not np.isfinite(exit_px):
            continue
        trades.append({"code": code, "name": r["name"], "entry_date": d, "exit_date": s.index[j],
                       "ret_pct": (exit_px / entry_px - 1) * 100})
    return pd.DataFrame(trades).sort_values("entry_date").reset_index(drop=True)


def add_concurrency(trades):
    """每筆進場當下同時開倉數(含自己),供資金實際口徑分攤權重用。"""
    conc = []
    for _, r in trades.iterrows():
        n = ((trades.entry_date <= r.entry_date) & (trades.exit_date >= r.entry_date)).sum()
        conc.append(int(n))
    trades = trades.copy()
    trades["concurrent"] = conc
    return trades


def equity_curves(trades):
    """單利累積(同案慣例:每筆1單位,Σ淨額%),依exit_date排序;另算資金實際口徑(同時最多
    MAX_CONCURRENT筆平分資金)。回傳(t含權重欄, raw累積Series, capped累積Series, stats dict)。"""
    t = add_concurrency(trades).sort_values("exit_date").reset_index(drop=True)
    t["w_capped"] = np.minimum(1.0, MAX_CONCURRENT / t.concurrent.replace(0, 1)) / MAX_CONCURRENT
    cum_raw = t.ret_pct.cumsum()
    cum_capped = (t.ret_pct * t.w_capped).cumsum()

    def _stats(cum, label):
        dd = cum - cum.cummax()
        years = (t.exit_date.max() - t.entry_date.min()).days / 365.25
        pf_den = t.ret_pct[t.ret_pct <= 0].sum() if label == "raw" else (t.ret_pct * t.w_capped)[t.ret_pct <= 0].sum()
        pf_num = t.ret_pct[t.ret_pct > 0].sum() if label == "raw" else (t.ret_pct * t.w_capped)[t.ret_pct > 0].sum()
        pf = pf_num / abs(pf_den) if pf_den < 0 else np.inf
        return {"n": len(t), "total": float(cum.iloc[-1]), "ann": float(cum.iloc[-1] / years),
                "mdd": float(dd.min()), "win": float((t.ret_pct > 0).mean() * 100), "pf": float(pf),
                "years": float(years)}

    return t, cum_raw, cum_capped, _stats(cum_raw, "raw"), _stats(cum_capped, "capped")


CANDLE_LOOKBACK = 60   # 進場前回看天數(涵蓋沉寂→覺醒轉折過程)
CANDLE_LOOKAHEAD = 10  # 出場後多看幾天(顯示出場後續走勢)


def candle_chart_js(code, name, entry_date, exit_date, ret_pct, chart_id):
    """單筆交易K棒圖:進場前60日(沉寂→覺醒轉折)~出場後10日,標記進場/出場點,副圖疊成交金額。"""
    if code not in CLOSE.columns:
        return ""
    s_close = CLOSE[code]
    if entry_date not in s_close.index:
        return ""
    i = s_close.index.get_loc(entry_date)
    j = s_close.index.get_loc(exit_date) if exit_date in s_close.index else i
    start = max(0, i - CANDLE_LOOKBACK)
    end = min(len(s_close) - 1, j + CANDLE_LOOKAHEAD)
    idx = s_close.index[start:end + 1]
    o, h, l, c = OPEN[code].loc[idx], HIGH[code].loc[idx], LOW[code].loc[idx], CLOSE[code].loc[idx]
    vol = (MONEY[code].loc[idx] / 1e4)   # 萬元
    xs = [d.strftime("%Y-%m-%d") for d in idx]
    cls = "good" if ret_pct > 0 else "bad"
    candle = {"x": xs, "open": [float(v) for v in o.values], "high": [float(v) for v in h.values],
             "low": [float(v) for v in l.values], "close": [float(v) for v in c.values],
             "type": "candlestick", "name": code, "increasing": {"line": {"color": "#e06c5a"}},
             "decreasing": {"line": {"color": "#7ec97e"}}, "xaxis": "x", "yaxis": "y"}
    vol_bar = {"x": xs, "y": [float(v) for v in vol.values], "type": "bar", "name": "成交金額(萬)",
              "marker": {"color": "#6b7280"}, "xaxis": "x", "yaxis": "y2"}
    entry_x = entry_date.strftime("%Y-%m-%d")
    exit_x = exit_date.strftime("%Y-%m-%d") if exit_date in idx else xs[-1]
    shapes = [{"type": "line", "x0": entry_x, "x1": entry_x, "yref": "paper", "y0": 0, "y1": 1,
              "line": {"color": "#c3a55a", "width": 1.5, "dash": "dot"}},
             {"type": "line", "x0": exit_x, "x1": exit_x, "yref": "paper", "y0": 0, "y1": 1,
              "line": {"color": "#6bb7e3", "width": 1.5, "dash": "dot"}}]
    layout = {"paper_bgcolor": "#1a1a19", "plot_bgcolor": "#1a1a19",
              "font": {"color": "#ddd", "family": "Noto Sans TC", "size": 11},
              "title": {"text": f"{code} {name}  進場{entry_x}→出場{exit_x}  "
                                f"<span style='color:{'#e06c5a' if ret_pct>0 else '#7ec97e'}'>{ret_pct:+.1f}%</span>",
                        "font": {"size": 13}},
              "xaxis": {"gridcolor": "#333", "rangeslider": {"visible": False}},
              "yaxis": {"gridcolor": "#333", "domain": [0.28, 1], "title": "price"},
              "yaxis2": {"domain": [0, 0.2], "title": "成交金額(萬)"},
              "shapes": shapes, "height": 320, "margin": {"t": 40, "l": 55, "r": 15, "b": 30},
              "showlegend": False}
    return (f'<div id="{chart_id}"></div>\n'
           f'<script>Plotly.newPlot("{chart_id}", {json.dumps([candle, vol_bar], ensure_ascii=False)}, '
           f'{json.dumps(layout, ensure_ascii=False)}, {{displayModeBar:false}});</script>')


def capacity_stats(df):
    """胃納量分析:覺醒窗(t-20~t)日均成交金額分布,估算單筆部位/整體策略資金上限。"""
    rows = []
    for r in df.itertuples():
        if r.code not in MONEY.columns or r.date not in MONEY[r.code].index:
            continue
        s = MONEY[r.code]
        i = s.index.get_loc(r.date)
        awake_avg = s.iloc[max(0, i - 19):i + 1].mean() / 1e4
        entry_day = s.iloc[i] / 1e4
        rows.append({"awake_avg_wan": awake_avg, "entry_day_wan": entry_day})
    v = pd.DataFrame(rows)
    if len(v) == 0:
        return {"n": 0}
    IMPACT_PCT = 0.15   # 單筆部位不超過覺醒窗日均量的15%(市場衝擊上限經驗值)
    med_awake = float(v.awake_avg_wan.median())
    p10_awake = float(v.awake_avg_wan.quantile(0.10))
    return {"n": len(v), "med_awake_wan": med_awake, "p10_awake_wan": p10_awake,
            "med_position_wan": med_awake * IMPACT_PCT, "p10_position_wan": p10_awake * IMPACT_PCT,
            "impact_pct": IMPACT_PCT}


# ── HTML ──────────────────────────────────────────────────
def fmt_pct(x, nd=2):
    return "—" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:+.{nd}f}%"


def k_summary_table(summ, label):
    head = ("<tr><th>k(交易日)</th><th>n</th><th>中位%</th><th>平均%</th><th>demean平均%(扣長期飄移)</th>"
            "<th>勝率</th><th>bootstrap平均值95% CI</th></tr>")
    body = ""
    for k in K_LIST:
        s = summ[k]
        if s["n"] == 0:
            body += f"<tr><th>k{k}</th><td colspan='6'>—</td></tr>"
            continue
        ci = "n<10不bootstrap" if s["ci"] is None else f"[{s['ci'][0]:+.2f}, {s['ci'][1]:+.2f}]"
        sig = ""
        if s["ci"] is not None:
            lo, hi = s["ci"]
            sig = " <span class='bad'>(排0,偏負)</span>" if hi < 0 else (
                  " <span class='good'>(排0,偏正)</span>" if lo > 0 else " <span class='sub'>(含0)</span>")
        cls = "good" if s["med"] > 0 else "bad"
        body += (f"<tr><th>k{k}</th><td>{s['n']}</td><td class='{cls}'>{s['med']:+.2f}%</td>"
                 f"<td>{s['mean']:+.2f}%</td><td>{s['dm']:+.2f}%</td><td>{s['win']:.0f}%</td>"
                 f"<td>{ci}{sig}</td></tr>")
    return f"<table>{head}{body}</table>"


def sens_grid_html(grid):
    head = "<tr><th>沉寂分位</th><th>覺醒倍數</th><th>+30%</th><th>+50%</th><th>+100%</th></tr>"
    body = "".join(f"<tr><th>{r['沉寂分位']}</th><th>{r['覺醒倍數']}</th>"
                   f"<td>{r['+30%']}</td><td>{r['+50%']}</td><td>{r['+100%']}</td></tr>" for r in grid)
    return f"<table>{head}{body}</table>"


def events_rows_html(df, top_n=60, show_liq_price=True):
    d = df.sort_values("date", ascending=False).head(top_n)
    rows = ""
    for _, r in d.iterrows():
        fwd_cells = "".join(f"<td>{fmt_pct(r[f'fwd{k}'])}</td>" for k in K_LIST)
        tdcc_cells = "".join(f"<td>{fmt_pct(r[f'tdcc_delta52w_{t}'])}</td>" for t in TDCC_THRESH)
        vol_cell = f"{r['vol_lead_days']:.0f}日" if pd.notna(r['vol_lead_days']) else "—"
        rev_cell = f"{r['rev_jump']:+.1f}pp" if pd.notna(r['rev_jump']) else "—"
        pbr_cell = f"{r['pbr']:.2f}" if pd.notna(r['pbr']) else "—"
        bvps_cell = f"{r['bvps']:.1f}元" if pd.notna(r['bvps']) else "—"
        mid_cells = (f"<td>{r['liq_ratio']:.1f}x</td><td class='good'>{fmt_pct(r['price_ret20'])}</td>"
                    if show_liq_price else f"<td>{r['vol_ratio']:.1f}x</td>")
        rows += (f"<tr><td>{r['date'].date()}</td><td>{r['code']} {r['name']}</td>"
                 f"<td>{r['cap_yi']:.1f}億</td><td>{r['dormant_money_wan']:.0f}萬</td>"
                 f"{mid_cells}{fwd_cells}{tdcc_cells}<td>{vol_cell}</td><td>{rev_cell}</td>"
                 f"<td>{pbr_cell}</td><td>{bvps_cell}</td></tr>")
    return rows


def tdcc_cross_html(tdcc):
    head = ("<tr><th>窗口</th><th>大戶門檻</th><th>n</th><th>事件前平均Δp</th><th>對比基準超額</th>"
            "<th>正比例</th><th>對比基準超額</th></tr>")
    body = ""
    for w in TDCC_WINDOWS:
        for t in TDCC_THRESH:
            c = tdcc.get((w, t), {"n": 0})
            if c["n"] == 0:
                body += f"<tr><th>{w}週</th><th>{t}張</th><td colspan='5'>—</td></tr>"
                continue
            cls = "good" if c["vs_base_mean"] > 0 else "bad"
            body += (f"<tr><th>{w}週</th><th>{t}張</th><td>{c['n']}</td><td class='{cls}'>{c['mean']:+.2f}pp</td>"
                     f"<td class='{cls}'>{c['vs_base_mean']:+.2f}pp</td><td>{c['pos_rate']:.0f}%</td>"
                     f"<td class='{cls}'>{c['vs_base_pos']:+.1f}pp</td></tr>")
    return f"<table>{head}{body}</table>"


def holder_cross_html(holder):
    head = ("<tr><th>窗口</th><th>n</th><th>事件前平均Δ大戶人數(千張門檻)</th><th>對比基準超額</th>"
            "<th>正比例</th><th>對比基準超額</th></tr>")
    body = ""
    for w in TDCC_WINDOWS:
        c = holder.get(w, {"n": 0})
        if c["n"] == 0:
            body += f"<tr><th>{w}週</th><td colspan='5'>—</td></tr>"
            continue
        cls = "good" if c["vs_base_mean"] > 0 else "bad"
        body += (f"<tr><th>{w}週</th><td>{c['n']}</td><td class='{cls}'>{c['mean']:+.2f}人</td>"
                 f"<td class='{cls}'>{c['vs_base_mean']:+.2f}人</td><td>{c['pos_rate']:.0f}%</td>"
                 f"<td class='{cls}'>{c['vs_base_pos']:+.1f}pp</td></tr>")
    return f"<table>{head}{body}</table>"


def bvps_html(bv):
    if bv.get("n", 0) == 0:
        return "<div class='note'>PBR資料缺值無法反推BVPS。</div>"
    cls10 = "good" if bv["vs_base_credit"] > 0 else "bad"
    cls5 = "good" if bv["vs_base_full"] > 0 else "bad"
    return (f"<div class='note'>n={bv['n']}, 事件組每股淨值中位={bv['median']:.1f}元。"
            f"BVPS&lt;{BVPS_CREDIT_TH:.0f}元(信用交易停止門檻)比例=<span class='{cls10}'>{bv['below_credit_pct']:.0f}%</span>"
            f"(對比基準{BASE_BVPS['below_credit_pct']:.0f}%,超額<span class='{cls10}'>{bv['vs_base_credit']:+.1f}pp</span>)、"
            f"BVPS&lt;{BVPS_FULL_DELIVERY_TH:.0f}元(全額交割門檻)比例=<span class='{cls5}'>{bv['below_full_pct']:.0f}%</span>"
            f"(對比基準{BASE_BVPS['below_full_pct']:.0f}%,超額<span class='{cls5}'>{bv['vs_base_full']:+.1f}pp</span>)。"
            f"門檻為法規硬數字(WebSearch查證):全額交割&lt;5元、停止信用交易&lt;票面10元。</div>")


def candle_html(cs):
    if cs.get("n", 0) == 0:
        return "<div class='note'>樣本不足。</div>"
    return (f"<div class='note'>n={cs['n']}, 沉寂期(t-120~t-20)長紅長黑(|收/開-1|>={LONG_CANDLE_TH*100:.0f}%)"
            f"日數比例平均={cs['dormant_mean']:.1f}%(對比全市場基準{BASE_CANDLE_RATE:.1f}%,"
            f"{cs['vs_base_dormant']:+.1f}pp)、覺醒/近期窗(t-20~t)比例平均="
            f"<span class='good'>{cs['awake_mean']:.1f}%</span>(對比基準{cs['vs_base_awake']:+.1f}pp)、"
            f"覺醒/沉寂倍數=<b>{cs['ratio']:.1f}x</b>。使用者假說:平常振幅小,波動放大才有長紅長黑。</div>")


def pbr_html(pb):
    if pb.get("n", 0) == 0:
        return "<div class='note'>PBR資料缺值,無法計算。</div>"
    cls = "good" if pb["vs_base_below_th"] > 0 else "bad"
    return (f"<div class='note'>n={pb['n']}, 事件組股價淨值比中位={pb['median']:.2f}倍,"
            f"PBR&lt;{PB_TH}比例=<span class='{cls}'>{pb['below_th_pct']:.0f}%</span>"
            f"(對比全市場無條件基準{BASE_PBR['below_th_pct']:.0f}%,超額<span class='{cls}'>{pb['vs_base_below_th']:+.1f}pp</span>)。"
            f"使用者假說:低股價淨值比(便宜相對淨資產)可能是借殼吸引力之一。</div>")


def vol_lead_html(vl):
    if vl.get("n_fired", 0) == 0:
        return "<div class='note'>回看窗內無事件觸及波動放大門檻。</div>"
    return (f"<div class='note'>觸發事件中有 <b>{vl['fired_pct']:.0f}%</b>(n={vl['n_fired']}/{vl['n_total']})"
            f"在回看{VOL_LOOKBACK}日內曾出現波動放大(20日/100日波動比>={VOL_LEAD_THRESH}x)。"
            f"其中領先天數中位 <b>{vl['med_lead']:.0f}日</b>(平均{vl['mean_lead']:.1f}日)、"
            f"波動放大比流動性/價格覺醒更早出現的比例={vl['pct_led']:.0f}%、同日出現={vl['pct_same_day']:.0f}%。</div>")


def rev_jump_html(rj):
    if rj.get("n", 0) == 0:
        return "<div class='note'>可算跳躍度樣本不足(需trailing 12個月中至少6個月有月營收資料)。</div>"
    cls = "good" if rj["vs_base_median"] > 0 else "bad"
    return (f"<div class='note'>n={rj['n']}, 事件組跳躍度中位數(trailing12月YoY 最大值-中位數)"
            f"={rj['median']:+.1f}pp,對比全市場無條件基準中位數{BASE_REV_JUMP['median']:+.1f}pp"
            f"(n={BASE_REV_JUMP['n']:,})超額<span class='{cls}'>{rj['vs_base_median']:+.1f}pp</span>。"
            f"只報中位數:YoY%近0期基期會炸出天文數字離群值,均值不可信。"
            f"數值越高=營收越像「有一期沒一期」的跳躍式,越低=越像穩定成長/穩定衰退。</div>")


def equity_chart_js(cum_raw, cum_capped, t, chart_id="equity_chart"):
    def _tr(cum, name, col):
        return {"x": [d.strftime("%Y-%m-%d") for d in t.exit_date], "y": [round(float(v), 1) for v in cum.values],
                "name": name, "type": "scatter", "mode": "lines", "line": {"color": col, "width": 2}}
    data = [_tr(cum_raw, f"訊號口徑(每筆1單位,n={len(t)})", "#e06c5a"),
           _tr(cum_capped, f"資金實際口徑(同時最多{MAX_CONCURRENT}筆平分,歷史最大重疊13筆)", "#7ec97e")]
    layout = {"paper_bgcolor": "#1a1a19", "plot_bgcolor": "#1a1a19",
              "font": {"color": "#ddd", "family": "Noto Sans TC", "size": 12},
              "xaxis": {"gridcolor": "#333"}, "yaxis": {"gridcolor": "#333", "title": "累積淨額%"},
              "margin": {"t": 48, "l": 60, "r": 20, "b": 40}, "height": 380, "legend": {"orientation": "h"},
              "title": {"text": "早期版疊加·固定持有120日·權益曲線(依出場日累積,單利非複利)", "font": {"size": 14}}}
    return (f'<div id="{chart_id}"></div>\n'
           f'<script>Plotly.newPlot("{chart_id}", {json.dumps(data, ensure_ascii=False)}, '
           f'{json.dumps(layout, ensure_ascii=False)}, {{displayModeBar:false}});</script>')


def strategy_stats_html(s_raw, s_capped):
    def row(lab, s):
        return (f"<tr><th>{lab}</th><td>{s['n']}</td><td class='good'>{s['total']:+.1f}%</td>"
               f"<td class='good'>{s['ann']:+.1f}%</td><td class='bad'>{s['mdd']:+.1f}%</td>"
               f"<td>{s['win']:.0f}%</td><td>{s['pf']:.2f}</td><td>{s['years']:.1f}年</td></tr>")
    head = "<tr><th>口徑</th><th>n</th><th>總報酬</th><th>年化</th><th>MDD</th><th>勝率</th><th>獲利因子</th><th>期間</th></tr>"
    return (f"<table>{head}{row('訊號口徑(每筆1單位)', s_raw)}{row(f'資金實際口徑(同時上限{MAX_CONCURRENT}筆)', s_capped)}</table>"
           f"<div class='note'>訊號口徑=本專案既有慣例(如build_panic_liquidity_report.py的V4/V5曲線),"
           f"假設每筆訊號都能全額進場,適合判斷「訊號本身有沒有edge」;<b>但46筆訊號中位數同時開倉數6筆、"
           f"最高曾同時13筆</b>,真實資金不可能每筆都全額壓,資金實際口徑(平分{MAX_CONCURRENT}筆額度)才是較"
           f"貼近可執行的數字。停損/停利已測試(持有40/60/90/120日 × 停損-15%/-20%全部組合)——"
           f"<b>結論是不要停損</b>:每個持有天數下,加停損都讓總報酬跟MDD雙雙變差,顯示多數回落中的部位"
           f"最終會回升,提早停損等於砍在阿呆谷。剔除最大單一贏家後訊號口徑總報酬仍有+1336.9%,"
           f"不是單一極端值撐起來的,但少數大贏家(如+249%/+201%/+134%)確實貢獻了總報酬的可觀比例,"
           f"屬於本案全程一致的「多數小賠+少數暴賺」右尾偏態,不是「每筆都穩定小賺」的策略。</div>")


def trades_table_html(t):
    rows = ""
    for _, r in t.sort_values("entry_date", ascending=False).iterrows():
        cls = "good" if r.ret_pct > 0 else "bad"
        rows += (f"<tr><td>{r.entry_date.date()}</td><td>{r.exit_date.date()}</td>"
                f"<td>{r.code} {r['name']}</td><td>{r.concurrent}</td>"
                f"<td class='{cls}'>{r.ret_pct:+.2f}%</td></tr>")
    return (f"<div class='scroll'><table><tr><th>進場日</th><th>出場日</th><th>股票</th>"
           f"<th>當下同時開倉數</th><th>報酬</th></tr>{rows}</table></div>")


def capacity_html(cap):
    if cap.get("n", 0) == 0:
        return "<div class='note'>樣本不足,無法估算胃納量。</div>"
    return (f"<div class='note'><b>胃納量(這個策略能吃下多少資金)</b>:n={cap['n']}筆,進場當下"
           f"覺醒窗(t-20~t)日均成交金額中位數僅<b>{cap['med_awake_wan']:,.0f}萬元</b>"
           f"(後10%分位更僅{cap['p10_awake_wan']:,.0f}萬元)。抓「單筆部位不超過當日均量"
           f"{cap['impact_pct']*100:.0f}%」的市場衝擊上限經驗值,單筆部位建議上限約"
           f"<b>{cap['med_position_wan']:,.0f}萬元</b>(較差流動性個股僅{cap['p10_position_wan']:,.0f}萬元)。"
           f"歷史最多同時開倉13筆、中位數6筆,現實抓{MAX_CONCURRENT}筆估算,整體策略合理資金上限大概落在"
           f"<b>幾十萬到一兩百萬新台幣</b>這個量級——超過這個規模,買單本身會把沒什麼流通性的股票價格推高"
           f"(回測進場價失真),部位大到佔單日成交量一大截時賣出也會把價格砍下來(實際出場價比回測差)。"
           f"這不是能規模化的策略,是小資金才吃得下的利基打法,資金越大越吃不下去。</div>")


def trades_with_charts_html(t):
    """逐筆交易K棒圖(進場前60日沉寂→覺醒轉折~出場後10日),依報酬排序讓使用者一眼看出贏輸家長相差異。"""
    out = ""
    for idx, r in t.sort_values("ret_pct", ascending=False).reset_index(drop=True).iterrows():
        cid = f"tchart_{idx}_{r.code}"
        out += candle_chart_js(r.code, r["name"], r.entry_date, r.exit_date, r.ret_pct, cid)
    return out


def build_html(df_main, df_strict, summ_main, summ_strict, grid, tdcc_main, tdcc_strict, n_events_main, n_events_strict,
               holder_main, holder_strict, vol_main, rev_main, pbr_main, pbr_strict,
               df_early, summ_early, tdcc_early, holder_early, pbr_early, n_events_early,
               candle_main, candle_early, bvps_main, bvps_strict, bvps_early,
               stack_main, summ_stack_main, stack_early, summ_stack_early,
               trades, cum_raw, cum_capped, stat_raw, stat_capped, cap_stack,
               trades2, cum_raw2, cum_capped2, stat_raw2, stat_capped2, cap_combined):
    css = """
body{background:#1a1a19;color:#fff;font-family:"Noto Sans TC",sans-serif;margin:24px;max-width:1300px}
h1{font-size:20px} h2{font-size:15px;color:#c3c2b7;margin-top:30px;border-bottom:1px solid #333;padding-bottom:4px}
h3{font-size:13.5px;color:#a8a79a;margin:16px 0 4px}
table{border-collapse:collapse;font-size:12px;font-variant-numeric:tabular-nums;margin:8px 0}
td,th{border:1px solid #333;padding:4px 8px;text-align:right} th{text-align:left;color:#c3c2b7}
.note{color:#8a8878;font-size:12.5px;line-height:1.8} .good{color:#7ec97e} .bad{color:#e06c5a}
.warn{color:#c3a55a} .sub{color:#777;font-size:11px}
.scroll{max-height:520px;overflow-y:auto;display:block}
"""
    limits = """
<div class='note'>
<b>限制(務必先讀)</b>:①存活者偏差重:資料庫用現存上市櫃股名單回填歷史,已下市/合併/改名的個股幾乎不在樣本內——
這正是借殼案例最常見的結局,本研究能回答「型態出現後、公司還活著且沿用原代碼時股價續攻或洩壓」,
不能回答「型態出現後公司是否真的被借殼」。②有效樣本窗口2019-06~2026-07(~7年),更早期橫斷面分母太薄不採計。
③型態本身不驗證機制,只驗證「然後呢」,型態反覆出現不代表訊號可靠(同SOX考卷立場)。
④覺醒窗與報酬窗定義為同一段(t-20~t),兩者本質上綁在一起,fwd0(觸發日本身)不重複計入forward報酬(k從5起算)。
</div>"""
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>沉寂覺醒型態考卷</title>
<script src="plotly.min.js"></script><style>{css}</style></head><body>
<h1>沉寂覺醒型態考卷:沒流通性→覺醒→短時間上漲很兇,然後呢?</h1>
<div class='note'>使用者第二個想法(2026-08-03):繞開借殼標籤問題,直接用可觀察特徵(本來沒流通性/後來流通性上升/
短時間上漲很兇/市值小)搜尋型態本身,測「然後呢」而非「這是不是借殼股」。方法論同SOX跌深反彈考卷:零新抓取,
用本地fm_daily_price+capital+tdcc_weekly搜尋歷史複現,事件研究法(demean+bootstrap CI)。</div>
{limits}

<h2>①型態定義</h2>
<div class='note'>
沉寂期=t-120~t-20交易日均日成交金額,橫斷面分位數落在後20%(主版)/後10%(嚴格版)。<br>
覺醒=t-20~t均量 / 沉寂期均量 >= 5倍(主版)/ 8倍(嚴格版)。<br>
短時間上漲很兇=t-20~t價格報酬 >= +30%(主版)/ +50%(嚴格版)。<br>
市值小=覺醒窗開始時(漲之前)市值橫斷面分位數落在後30%(主版)/後20%(嚴格版)。<br>
去重=同碼60交易日內只取第一次觸發當錨定日。
</div>

<h2>②敏感度網格(事件數,固定市值分位=後30%)</h2>
{sens_grid_html(grid)}

<h2>③主版事件研究(n={n_events_main})</h2>
<h3>觸發後前瞻報酬(demean=扣個股橫斷面長期無條件平均飄移)</h3>
{k_summary_table(summ_main, "主版")}
<h3>大戶持股比例交叉驗證(呼應原始假說:52週=主口徑約1年,借殼收籌碼多半半年~一年才收完;26週留作對照;
600/800/1000張三門檻都測,不單押一個)</h3>
{tdcc_cross_html(tdcc_main)}
<h3>大戶「人數」交叉驗證(非比例;使用者不確定借殼吃貨是集中少數帳戶還是多帳戶佈局,純觀察不預設方向)</h3>
{holder_cross_html(holder_main)}
<h3>波動放大領先時間診斷(使用者新提案:長期穩定→突然放大,是否比流動性/價格覺醒更早出現)</h3>
{vol_lead_html(vol_main)}
<h3>營收跳躍度交叉驗證(使用者新提案:借殼股炒營收應該是「有一期沒一期」而非穩定成長)</h3>
{rev_jump_html(rev_main)}
<h3>股價淨值比交叉驗證(使用者新提案:PBR&lt;{PB_TH}可能是借殼吸引力之一)</h3>
{pbr_html(pbr_main)}
<h3>長紅長黑診斷(使用者新提案:平常振幅小,波動放大才有長紅長黑)</h3>
{candle_html(candle_main)}
<h3>每股淨值法規門檻交叉驗證(使用者新提案:全額交割/信用交易資格門檻)</h3>
{bvps_html(bvps_main)}

<h2>④嚴格版事件研究(n={n_events_strict})</h2>
{k_summary_table(summ_strict, "嚴格版")}
<h3>大戶持股比例交叉驗證(嚴格版)</h3>
{tdcc_cross_html(tdcc_strict)}
<h3>大戶人數交叉驗證(嚴格版)</h3>
{holder_cross_html(holder_strict)}
<h3>股價淨值比交叉驗證(嚴格版)</h3>
{pbr_html(pbr_strict)}
<h3>每股淨值法規門檻交叉驗證(嚴格版)</h3>
{bvps_html(bvps_strict)}

<h2>⑤主版觸發個股明細(最新60筆,依觸發日倒序)</h2>
<div class='scroll'><table>
<tr><th>觸發日</th><th>股票</th><th>市值(漲前)</th><th>沉寂期均量</th><th>覺醒倍數</th><th>t-20~t報酬</th>
{"".join(f"<th>fwd{k}</th>" for k in K_LIST)}{"".join(f"<th>Δp{t}(前52週)</th>" for t in TDCC_THRESH)}
<th>波動放大領先(日)</th><th>營收跳躍度</th><th>PBR</th><th>BVPS</th></tr>
{events_rows_html(df_main)}
</table></div>

<h2>⑥早期版(波動先兆版,n={n_events_early})</h2>
<div class='note'><b>2026-08-03使用者裁示</b>:波動放大領先診斷顯示92.6%案例波動比流動性/價格早~8日出現,
既然有領先性,直接把波動放大當主觸發條件——定義=沉寂(同主版,後20%分位)∧波動放大(20日/100日波動比>={EARLY['vol_mult']}x)
∧市值小(觸發當下,後{int(EARLY['cap_pctl']*100)}%分位),<b>不要求流動性5x或漲幅30%已確認</b>,理論上比主版更早進場,
代價是雜訊也可能更多(畢竟少了兩個確認條件)。</div>
<h3>觸發後前瞻報酬</h3>
{k_summary_table(summ_early, "早期版")}
<h3>大戶持股比例交叉驗證</h3>
{tdcc_cross_html(tdcc_early)}
<h3>大戶人數交叉驗證</h3>
{holder_cross_html(holder_early)}
<h3>股價淨值比交叉驗證</h3>
{pbr_html(pbr_early)}
<h3>長紅長黑診斷</h3>
{candle_html(candle_early)}
<h3>每股淨值法規門檻交叉驗證</h3>
{bvps_html(bvps_early)}
<h3>早期版觸發個股明細(最新60筆)</h3>
<div class='scroll'><table>
<tr><th>觸發日</th><th>股票</th><th>市值</th><th>沉寂期均量</th><th>波動放大倍數</th>
{"".join(f"<th>fwd{k}</th>" for k in K_LIST)}{"".join(f"<th>Δp{t}(前52週)</th>" for t in TDCC_THRESH)}
<th>波動放大領先(日)</th><th>營收跳躍度</th><th>PBR</th><th>BVPS</th></tr>
{events_rows_html(df_early, show_liq_price=False)}
</table></div>

<h2>⑦疊加篩選版(使用者2026-08-03裁示採用:單一角度都弱,疊加後fwd120中位數翻正)</h2>
<div class='note'>條件=BVPS&lt;{BVPS_CREDIT_TH:.0f}元(信用交易停止門檻)∧PBR&lt;{PB_TH}∧52週大戶(千張)比例上升,
分別套用在主版/早期版事件上。呼應「借殼上市本來就稀少,單一寬鬆條件篩出的樣本是雜訊為主」的判斷——
疊加多個弱訊號逼近真正的少數樣本,不是統計上更嚴謹,而是更貼近現實裡這個現象本來就罕見的事實。
<b>案例驗證</b>:9912偉聯在早期版疊加清單中復現6輪(2020~2025各年),使用者稱有消息其2027年可能借殼上市,
現況(資料至2026-07-31)大戶比例52週+9.09pp持續墊高、BVPS已低於信用交易門檻、7/28單日成交暴增近百倍——
n=1軼事非統計證明但方向吻合。</div>

<h3>主版疊加(n={len(stack_main)})</h3>
{k_summary_table(summ_stack_main, "主版疊加")}
<div class='scroll'><table>
<tr><th>觸發日</th><th>股票</th><th>市值(漲前)</th><th>沉寂期均量</th><th>覺醒倍數</th><th>t-20~t報酬</th>
{"".join(f"<th>fwd{k}</th>" for k in K_LIST)}{"".join(f"<th>Δp{t}(前52週)</th>" for t in TDCC_THRESH)}
<th>波動放大領先(日)</th><th>營收跳躍度</th><th>PBR</th><th>BVPS</th></tr>
{events_rows_html(stack_main, top_n=200)}
</table></div>

<h3>早期版疊加(n={len(stack_early)},建議主要觀察名單)</h3>
{k_summary_table(summ_stack_early, "早期版疊加")}
<div class='scroll'><table>
<tr><th>觸發日</th><th>股票</th><th>市值</th><th>沉寂期均量</th><th>波動放大倍數</th>
{"".join(f"<th>fwd{k}</th>" for k in K_LIST)}{"".join(f"<th>Δp{t}(前52週)</th>" for t in TDCC_THRESH)}
<th>波動放大領先(日)</th><th>營收跳躍度</th><th>PBR</th><th>BVPS</th></tr>
{events_rows_html(stack_early, top_n=200, show_liq_price=False)}
</table></div>

<h2>⑧策略化:進場/出場/權益曲線(使用者2026-08-04要求)</h2>
<div class='note'>
<b>進場</b>=早期版疊加(沉寂後20%分位∧波動放大2倍以上∧市值後30%分位∧BVPS&lt;{BVPS_CREDIT_TH:.0f}元∧
PBR&lt;{PB_TH}∧52週大戶(千張)比例上升),觸發當日收盤進場。<br>
<b>出場</b>=固定持有{HOLD_DAYS}個交易日後收盤出場,<b>不設停損停利</b>(見下方測試結果)。
</div>
{equity_chart_js(cum_raw, cum_capped, trades)}
<h3>績效統計</h3>
{strategy_stats_html(stat_raw, stat_capped)}
{capacity_html(cap_stack)}
<h3>逐筆交易明細</h3>
{trades_table_html(trades)}

<h2>⑨雙濾網疊加版+K棒明細(使用者2026-08-04裁示測試)</h2>
<div class='note warn'>
<b>⚠️看到勝率100%/MDD=0%不要相信它——這是過擬合警訊,不是好消息</b>。在⑧的基礎上再疊加兩個濾網:
①52週大戶增幅門檻從&gt;0拉高到&gt;{COMBINED_TDCC_TH}pp ②排除「觸發日當天本身正是漲停」——兩個濾網
都是<b>從同一批46筆交易裡看贏家/輸家差異回頭挑出來的</b>,拿同一批資料再測一次,數學上近似「調參數調到
剛好把樣本內所有輸家都篩掉」,n只剩18筆還100%獲利/0%回撤,幾乎可以肯定是過擬合而非真實edge——
真實策略不可能沒有回撤。這個版本純粹拿來看K棒明細長怎樣(下方逐筆圖),<b>不能當成比⑧更好的正式版本</b>,
未來有新樣本(時間往後推進出現的新觸發)驗證過关之前,實際操作應該以⑧(單一濾網,勝率72%、MDD-7.8%,
數字更難看但更可信)為準。
</div>
{equity_chart_js(cum_raw2, cum_capped2, trades2, chart_id="equity_chart2")}
<h3>績效統計</h3>
{strategy_stats_html(stat_raw2, stat_capped2)}
{capacity_html(cap_combined)}
<h3>逐筆交易K棒明細(依報酬排序,金色虛線=進場日,藍色虛線=出場日,副圖=成交金額)</h3>
{trades_with_charts_html(trades2)}

</body></html>"""
    return html


def main():
    mask_main = build_mask(**MAIN)
    mask_strict = build_mask(**STRICT)
    ev_main = extract_events(mask_main)
    ev_strict = extract_events(mask_strict)
    df_main = event_table(ev_main)
    df_strict = event_table(ev_strict)

    print("=" * 90)
    print(f"主版(沉寂後20%/覺醒5x/漲幅+30%/市值後30%): n={len(ev_main)}")
    print(f"嚴格版(沉寂後10%/覺醒8x/漲幅+50%/市值後20%): n={len(ev_strict)}")

    summ_main = summarize_k(df_main)
    summ_strict = summarize_k(df_strict)
    for k in K_LIST:
        print(f"  主版 fwd{k}: {summ_main[k]}")

    grid = sensitivity_grid()
    print("敏感度網格:", grid)

    tdcc_main = tdcc_crosscheck(df_main)
    tdcc_strict = tdcc_crosscheck(df_strict)
    for w in TDCC_WINDOWS:
        for t in TDCC_THRESH:
            print(f"主版大戶交叉驗證({w}週/{t}張): {tdcc_main[(w, t)]} "
                  f"(基準均值{BASE_TDCC[(w, t)]['mean']:+.2f}pp/正比例{BASE_TDCC[(w, t)]['pos']:.0f}%)")

    holder_main = holder_crosscheck(df_main)
    holder_strict = holder_crosscheck(df_strict)
    for w in TDCC_WINDOWS:
        print(f"主版大戶人數交叉驗證({w}週): {holder_main[w]} "
              f"(基準均值{BASE_TDCC_N[w]['mean']:+.2f}人/正比例{BASE_TDCC_N[w]['pos']:.0f}%)")

    vol_main = vol_lead_summary(df_main)
    print(f"波動放大領先診斷(主版): {vol_main}")

    rev_main = rev_jump_summary(df_main)
    print(f"營收跳躍度交叉驗證(主版): {rev_main} (基準中位{BASE_REV_JUMP['median']:+.1f}pp, n={BASE_REV_JUMP['n']:,})")

    pbr_main = pbr_crosscheck(df_main)
    pbr_strict = pbr_crosscheck(df_strict)
    print(f"股價淨值比交叉驗證(主版): {pbr_main} (基準PBR<{PB_TH}比例={BASE_PBR['below_th_pct']:.0f}%)")

    candle_main = candle_summary(df_main)
    print(f"長紅長黑診斷(主版): {candle_main} (基準{BASE_CANDLE_RATE:.1f}%)")

    bvps_main = bvps_crosscheck(df_main)
    bvps_strict = bvps_crosscheck(df_strict)
    print(f"每股淨值法規門檻交叉驗證(主版): {bvps_main} "
          f"(基準<10元={BASE_BVPS['below_credit_pct']:.0f}%/<5元={BASE_BVPS['below_full_pct']:.0f}%)")

    # ── 早期版(波動先兆版):不等流動性/漲幅確認,波動放大一出現就算觸發 ──
    mask_early = build_mask_early(**EARLY)
    ev_early = extract_events(mask_early)
    df_early = event_table(ev_early, cap_frame=CAP_NOW)
    print(f"早期版(沉寂後20%/波動放大{EARLY['vol_mult']}x/市值後30%,無流動性漲幅門檻): n={len(ev_early)}")
    summ_early = summarize_k(df_early)
    for k in K_LIST:
        print(f"  早期版 fwd{k}: {summ_early[k]}")
    tdcc_early = tdcc_crosscheck(df_early)
    holder_early = holder_crosscheck(df_early)
    pbr_early = pbr_crosscheck(df_early)
    candle_early = candle_summary(df_early)
    bvps_early = bvps_crosscheck(df_early)
    print(f"早期版大戶/人數/PBR/長紅長黑/BVPS交叉驗證: tdcc={tdcc_early} holder={holder_early} pbr={pbr_early} "
          f"candle={candle_early} bvps={bvps_early}")

    # ── 疊加篩選版(使用者2026-08-03裁示採用) ──
    stack_main = apply_stack_filter(df_main)
    stack_early = apply_stack_filter(df_early)
    summ_stack_main = summarize_k(stack_main)
    summ_stack_early = summarize_k(stack_early)
    print(f"疊加篩選版(BVPS<{BVPS_CREDIT_TH:.0f}∧PBR<{PB_TH}∧52週大戶比例上升): "
          f"主版n={len(stack_main)} 早期版n={len(stack_early)}")
    for k in (60, 120):
        print(f"  主版疊加 fwd{k}: {summ_stack_main[k]}")
        print(f"  早期版疊加 fwd{k}: {summ_stack_early[k]}")

    # ── 策略化:進場=早期版疊加,出場=固定持有,權益曲線(使用者2026-08-04要求) ──
    trades = build_trades(stack_early, HOLD_DAYS)
    trades, cum_raw, cum_capped, stat_raw, stat_capped = equity_curves(trades)
    cap_stack = capacity_stats(stack_early)
    print(f"策略權益曲線: 訊號口徑={stat_raw} 資金實際口徑(上限{MAX_CONCURRENT}筆)={stat_capped}")
    print(f"胃納量(疊加篩選版): {cap_stack}")

    # ── 雙濾網疊加版:52週大戶>1.5pp∧觸發日非漲停(使用者2026-08-04裁示測試) ──
    combined = apply_combined_filter(df_early)
    trades2 = build_trades(combined, HOLD_DAYS)
    trades2, cum_raw2, cum_capped2, stat_raw2, stat_capped2 = equity_curves(trades2)
    cap_combined = capacity_stats(combined)
    print(f"雙濾網疊加版: n={len(combined)} 訊號口徑={stat_raw2} 資金實際口徑={stat_capped2}")
    print(f"胃納量(雙濾網疊加版): {cap_combined}")

    html = build_html(df_main, df_strict, summ_main, summ_strict, grid, tdcc_main, tdcc_strict,
                       len(ev_main), len(ev_strict), holder_main, holder_strict, vol_main, rev_main,
                       pbr_main, pbr_strict, df_early, summ_early, tdcc_early, holder_early, pbr_early, len(ev_early),
                       candle_main, candle_early, bvps_main, bvps_strict, bvps_early,
                       stack_main, summ_stack_main, stack_early, summ_stack_early,
                       trades, cum_raw, cum_capped, stat_raw, stat_capped, cap_stack,
                       trades2, cum_raw2, cum_capped2, stat_raw2, stat_capped2, cap_combined)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"已產出 {OUT}")


if __name__ == "__main__":
    main()
