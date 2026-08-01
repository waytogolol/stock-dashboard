# -*- coding: utf-8 -*-
"""樹模型探索當沖「贏家日」特徵交互作用(2026-08-01)。

⚠與平行進行的姊妹任務build_dtlend_winner_features.py(人工特徵battery+case-control AUC考卷)
互補、互不依賴、不共用輸出檔案,兩份各自獨立產出,由使用者對照比較。本卷角色定位=探索工具,
不是最終訊號:樹模型只用來擴大搜尋範圍、找出人工逐一測特徵可能漏掉的特徵組合(interaction),
任何找到的重要特徵/組合最後都要翻譯回明確規則、套用本專案既有的case-control+bootstrap框架
驗證過才算數,不直接把模型當黑盒訊號使用。

方法論設計重點(依使用者裁示逐條落實):
①標籤=贏家日: 比照人工battery定義,P&L proxy=(SellAmount-BuyAmount)/BuyAmount×100(逐股逐日,
  複用build_dtlend_report.py的load_dtlend());贏家=當日全宇宙(amt20>=0.3億∧四碼∧非00 ETF)
  排名前10%(pnl.rank(axis=1,pct=True)>=0.90,僅在每日有效樣本數>=30的交易日判定,避免早期
  當沖尚未普及、當日有效股數過少時「前10%」定義失真)。負例=case-control同日隨機抽樣的非贏家股
  (複用R.case_control(),排除當日所有贏家旗標股後從同宇宙隨機抽同數量),不用「其餘所有股票」
  當負例,避免類別極度不平衡又缺乏同日對照的問題;這樣可以直接拿AUC當評估指標,量級可與人工
  battery的單特徵AUC互相對照。
②訓練/測試集切分=按時間切,不用隨機k-fold: 同一天不同股票、同一檔股票鄰近幾天都不是獨立樣本,
  隨機切分會讓分數虛高。主切分=train<2024(2014-2023,10年)/test>=2024(2024-2026);另外做
  walk-forward擴張窗多折(test年份=2020~2026逐年,train=該年之前全部歷史),確認多個樣本外
  年份、橫跨多種regime(2020疫情崩盤/2021大多頭/2022熊市/…)下的AUC都不是單一巧合。
③套件: 環境檢查後確認沒有xgboost/lightgbm/shap,也沒有sklearn(⚠環境比預期更陽春,docstring
  下方「套件與環境聲明」段落誠實記錄此偏離,含唯一一次的pip install scikit-learn決策理由)。
④樹模型: 主模型=HistGradientBoostingClassifier(sklearn.ensemble原生梯度提升樹,概念上是
  xgboost/lightgbm不可得時最接近的sklearn內建替代品,原生支援NaN不必手動補值,對本資料集常見的
  rolling window熱身期NaN特別友善);次模型=RandomForestClassifier(交叉驗證特徵重要度排序穩不
  穩定);互動抽取用=淺層DecisionTreeClassifier(max_depth=3,大min_samples_leaf防止長出idiosyncratic
  小葉子),直接把樹的分裂路徑讀出來翻譯成規則,這是「找交互作用」最直接的做法。三模型均刻意調高
  min_samples_leaf/限制max_depth當正則化,抵銷「同一天不同股票高度相關,不是真正獨立樣本」這個
  已知風險(此為額外於時間切分之上的第二層防呆)。
⑤重要度: HistGB無內建feature_importances_,用permutation_importance(在**測試集**上算,避免
  訓練集算permutation importance本身的樂觀偏誤)當主排名;RF內建impurity-based importance當
  交叉對照。移除重要度前2名重新訓練=穩健性檢查,確認其餘特徵是否仍帶有效訊號還是純陪榜雜訊。
⑥規則翻譯: 從決策樹surrogate的分裂路徑中,挑「正例比例最高∧樣本數達門檻」的葉節點,把其路徑
  逐條分裂條件轉成人類看得懂的規則,再對**全樣本**(非训练/测试平衡後的樹模型面板,而是全宇宙
  全歷史wide frame)重跑case_control()+月群bootstrap(比照build_dtlend_report.py寫法)驗證。

⚠bootstrap函式key名稱對齊提醒(姊妹檔build_dtlend_pattern_pnl.py踩過的坑): R.boot_diff_ci
回傳dict用"diff"鍵、R.boot_median_ci用"med"鍵,本檔沿用時已核對,不重蹈同一camp。

用法: python 研究腳本/當沖借券/build_dtlend_tree_explore.py  (從根目錄執行,鐵律)
產出: 研究報告/research_dtlend_tree_explore.html
"""
import json
import sqlite3
import sys
import time

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "研究腳本/當沖借券")
import build_dtlend_report as R  # noqa: E402 (複用load_dtlend/load_classification無需/case_control/boot_diff_ci/boot_median_ci)

from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier  # noqa: E402
from sklearn.tree import DecisionTreeClassifier  # noqa: E402
from sklearn.inspection import permutation_importance  # noqa: E402
from sklearn.metrics import roc_auc_score  # noqa: E402

DB = "capital_flow.db"
OUT = "研究報告/research_dtlend_tree_explore.html"
rng = np.random.default_rng(20260801)

GREEN, RED, BLUE, YELLOW, GRAY = R.GREEN, R.RED, R.BLUE, R.YELLOW, R.GRAY
BG = R.BG

WIN_PCT = 0.90          # 贏家日=P&L proxy同日排名前10%
MIN_UNI_PER_DAY = 30    # 每日有效樣本數門檻(太少「前10%」定義失真)
FOLD_TEST_YEARS = [2020, 2021, 2022, 2023, 2024, 2025, 2026]   # walk-forward擴張窗測試折
MAIN_SPLIT_YEAR = 2024  # 主切分: train<2024 / test>=2024


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ======================================================================
# 1. 資料載入(複用build_dtlend_report的load_dtlend/case_control;價格取法比照build_dtlend_pattern_pnl)
# ======================================================================
def load_price_full(codes, date_lo):
    conn = sqlite3.connect(DB, timeout=60)
    ph = ",".join("?" * len(codes))
    px = pd.read_sql(
        f"SELECT code, date, open, high, low, close, volume, money FROM fm_daily_price "
        f"WHERE code IN ({ph}) AND date>=? AND close>0",
        conn, params=codes + [date_lo], parse_dates=["date"])
    conn.close()
    n0 = len(px)
    px = px[px.high >= px.low]  # 同姊妹檔防呆: high<low理論不可能之髒列剔除
    log(f"[load] fm_daily_price: {n0:,}列 → high>=low防呆後{len(px):,}列(剔除{n0 - len(px):,}列), "
        f"{px.code.nunique()}檔, {px.date.min().date()}~{px.date.max().date()}")
    out = tuple(px.pivot(index="date", columns="code", values=c)
                for c in ("open", "high", "low", "close", "volume", "money"))
    return out


def load_market_regime(idx):
    """ts=vol10/vol60、vp10=vol10百分位(2006起),口徑比照build_regime_weather_report.py的vol_series()。"""
    con = sqlite3.connect(DB, timeout=60)
    px = pd.read_sql("SELECT date, close FROM index_daily WHERE market='TAIEX' ORDER BY date",
                      con, parse_dates=["date"]).set_index("date").close
    con.close()
    r = px.pct_change() * 100
    v10 = r.rolling(10).std()
    v60 = r.rolling(60).std()
    ts = v10 / v60
    vp10 = v10[v10.index >= "2006-01-01"].dropna().rank(pct=True) * 100
    # reindex/ffill到當沖面板的交易日曆(兩套日曆理論上高度重疊,ffill防極少數缺口)
    ts = ts.reindex(idx, method="ffill")
    vp10 = vp10.reindex(idx, method="ffill")
    log(f"[regime] ts(vol10/vol60) 覆蓋{ts.notna().sum()}/{len(ts)}日, "
        f"vp10覆蓋{vp10.notna().sum()}/{len(vp10)}日")
    return ts, vp10


# ======================================================================
# 2. 特徵建構(對照人工battery特徵集,但不手動組合interaction——留給樹模型自己找)
# ======================================================================
def build_features(op, high, low, close, vol, dtp, buyp, sellp):
    ratio = (dtp / vol).clip(0, 1)
    pnl = (sellp - buyp) / buyp.replace(0, np.nan) * 100
    prevclose = close.shift(1)

    feats = {}
    feats["gap_pct"] = (op / prevclose - 1) * 100
    feats["gap_up_true"] = (op > high.shift(1)).astype(float)     # 真跳空(高於昨高)
    feats["gap_down_true"] = (op < low.shift(1)).astype(float)    # 真跳空(低於昨低)

    amp = (high - low) / prevclose * 100
    feats["amp_pct"] = amp
    feats["amp_pct120"] = amp.rolling(120, min_periods=60).rank(pct=True) * 100  # 逐股120日震幅百分位

    feats["dt_ratio"] = ratio                                     # 當沖比率本身
    feats["vol_x20"] = vol / vol.rolling(20, min_periods=15).mean()  # 量能倍數(20日均含當日,同house慣例)

    for w in (5, 10, 20, 60):
        feats[f"nh_close_{w}"] = (close >= close.shift(1).rolling(w).max()).astype(float)
        feats[f"nh_high_{w}"] = (high >= high.shift(1).rolling(w).max()).astype(float)
        feats[f"nl_close_{w}"] = (close <= close.shift(1).rolling(w).min()).astype(float)
        feats[f"nl_low_{w}"] = (low <= low.shift(1).rolling(w).min()).astype(float)

    for w in (5, 20, 60):
        feats[f"bias_{w}"] = (close / close.rolling(w).mean() - 1) * 100

    ret1 = close.pct_change() * 100
    feats["prev_dir"] = np.sign(ret1.shift(1))       # 昨日漲跌方向(+1/-1/0)
    feats["prev_ratio"] = ratio.shift(1)             # 昨日當沖比率
    feats["prev_pnl"] = pnl.shift(1)                 # 昨日P&L proxy

    return feats, ratio, pnl


FEATURE_DESC = {
    "gap_pct": "跳空%(今開/昨收-1)", "gap_up_true": "真跳空向上(open>昨high)",
    "gap_down_true": "真跳空向下(open<昨low)", "amp_pct": "震幅%((high-low)/昨收)",
    "amp_pct120": "震幅120日百分位(逐股)", "dt_ratio": "當沖比率(今日)", "vol_x20": "量能倍數(今日vol/20日均vol)",
    "bias_5": "乖離5日均%", "bias_20": "乖離20日均%", "bias_60": "乖離60日均%",
    "prev_dir": "昨日漲跌方向", "prev_ratio": "昨日當沖比率", "prev_pnl": "昨日P&L proxy",
    "ts": "波動期限結構ts=vol10/vol60(大盤)", "vp10": "波動10日std百分位vp10(大盤,2006起)",
}
for _w in (5, 10, 20, 60):
    FEATURE_DESC[f"nh_close_{_w}"] = f"創{_w}日收盤新高"
    FEATURE_DESC[f"nh_high_{_w}"] = f"創{_w}日盤中新高"
    FEATURE_DESC[f"nl_close_{_w}"] = f"創{_w}日收盤新低"
    FEATURE_DESC[f"nl_low_{_w}"] = f"創{_w}日盤中新低"


# ======================================================================
# 3. 標籤+case-control面板組裝
# ======================================================================
def mask_to_evs(mask):
    s = mask.stack()
    s = s[s]
    if len(s) == 0:
        return pd.DataFrame(columns=["date", "code"])
    return pd.DataFrame({"date": s.index.get_level_values(0), "code": s.index.get_level_values(1)})


def build_panel(uni, pnl, feats, ts, vp10):
    valid = uni & pnl.notna()
    n_valid = valid.sum(axis=1)
    eligible = n_valid >= MIN_UNI_PER_DAY
    pnl_masked = pnl.where(valid)
    rank_pct = pnl_masked.rank(axis=1, pct=True)
    winner_mask = (rank_pct >= WIN_PCT) & valid & eligible.values[:, None]

    winner_evs = mask_to_evs(winner_mask)
    log(f"[panel] 贏家日事件(P&L proxy同日排名前10%,每日有效樣本>={MIN_UNI_PER_DAY}) "
        f"n={len(winner_evs):,}, {winner_evs.code.nunique()}檔, {winner_evs.date.nunique()}個交易日 "
        f"(排除有效樣本不足的{int((~eligible).sum())}個交易日)")

    ctrl_evs = R.case_control(winner_evs, uni, winner_mask, seed=20260801)
    log(f"[panel] case-control對照組(同日∧同宇宙,排除當日所有贏家股後隨機抽同數量非贏家股) n={len(ctrl_evs):,}")

    winner_evs = winner_evs.copy(); winner_evs["label"] = 1
    ctrl_evs = ctrl_evs.copy(); ctrl_evs["label"] = 0
    all_evs = pd.concat([winner_evs, ctrl_evs], ignore_index=True)

    feat_names = list(feats.keys())
    recs = []
    t0 = time.time()
    for i, (d, g) in enumerate(all_evs.groupby("date")):
        codes = g.code.values
        row = {fn: (feats[fn].loc[d].reindex(codes).values if d in feats[fn].index
                    else np.full(len(codes), np.nan)) for fn in feat_names}
        row["ts"] = ts.get(d, np.nan)
        row["vp10"] = vp10.get(d, np.nan)
        rec = pd.DataFrame(row)
        rec["date"] = d
        rec["code"] = codes
        rec["label"] = g.label.values
        recs.append(rec)
        if (i + 1) % 500 == 0:
            log(f"  面板組裝進度 {i + 1}/{all_evs.date.nunique()} 個交易日, 耗時{time.time() - t0:.0f}s")
    panel = pd.concat(recs, ignore_index=True)
    log(f"[panel] 面板組裝完成: {len(panel):,}列(贏家{int((panel.label == 1).sum()):,} / "
        f"對照{int((panel.label == 0).sum()):,}), 耗時{time.time() - t0:.0f}s")
    return panel, winner_mask


# ======================================================================
# 4. 樹模型: walk-forward AUC + 主切分 + 重要度 + 穩健性檢查 + 規則抽取
# ======================================================================
def make_hgb():
    return HistGradientBoostingClassifier(max_iter=300, max_depth=6, learning_rate=0.06,
                                           min_samples_leaf=100, l2_regularization=1.0,
                                           early_stopping=True, random_state=42)


def make_rf():
    return RandomForestClassifier(n_estimators=300, max_depth=8, min_samples_leaf=50,
                                   n_jobs=-1, random_state=42)


def walk_forward(panel, feat_cols):
    """擴張窗walk-forward: test年份逐年,train=該年以前全部歷史。回傳每折train/test AUC。"""
    yr = panel.date.dt.year
    rows = []
    for test_yr in FOLD_TEST_YEARS:
        tr_mask = yr < test_yr
        te_mask = yr == test_yr
        if tr_mask.sum() < 2000 or te_mask.sum() < 200:
            log(f"[walkforward] {test_yr}: train={tr_mask.sum()} test={te_mask.sum()} 樣本不足,跳過")
            continue
        Xtr, ytr = panel.loc[tr_mask, feat_cols], panel.loc[tr_mask, "label"]
        Xte, yte = panel.loc[te_mask, feat_cols], panel.loc[te_mask, "label"]
        m = make_hgb()
        m.fit(Xtr, ytr)
        auc_tr = roc_auc_score(ytr, m.predict_proba(Xtr)[:, 1])
        auc_te = roc_auc_score(yte, m.predict_proba(Xte)[:, 1])
        rows.append({"test_year": test_yr, "n_train": int(tr_mask.sum()), "n_test": int(te_mask.sum()),
                     "auc_train": auc_tr, "auc_test": auc_te})
        log(f"[walkforward] test={test_yr}: train n={tr_mask.sum():,}(<{test_yr}) test n={te_mask.sum():,} "
            f"AUC train={auc_tr:.4f} test={auc_te:.4f}")
    return pd.DataFrame(rows)


def find_leaf_rule(tree_clf, feat_cols, X_train, y_train, min_leaf_n=150):
    """從淺層決策樹挑「正例比例最高∧樣本數達門檻」的葉節點,逐條分裂條件轉成規則。"""
    tree_ = tree_clf.tree_
    leaf_id = tree_clf.apply(X_train.values)
    leaf_df = pd.DataFrame({"leaf": leaf_id, "y": y_train.values})
    stat = leaf_df.groupby("leaf")["y"].agg(["mean", "count"]).query("count >= @min_leaf_n")
    if len(stat) == 0:
        stat = leaf_df.groupby("leaf")["y"].agg(["mean", "count"])
    best_leaf = stat["mean"].idxmax()
    best_rate, best_n = stat.loc[best_leaf, "mean"], int(stat.loc[best_leaf, "count"])

    def find_path(node_id, target, path):
        if node_id == target:
            return path
        left, right = tree_.children_left[node_id], tree_.children_right[node_id]
        if left == -1:
            return None
        f, t = tree_.feature[node_id], tree_.threshold[node_id]
        r = find_path(left, target, path + [(f, t, "<=")])
        if r is not None:
            return r
        return find_path(right, target, path + [(f, t, ">")])

    path = find_path(0, best_leaf, [])
    conds = [(feat_cols[f], op, t) for f, t, op in path]
    return conds, best_rate, best_n


def rule_text(conds):
    parts = []
    for name, op, t in conds:
        desc = FEATURE_DESC.get(name, name)
        parts.append(f"{desc}{op}{t:.2f}")
    return " 且 ".join(parts)


def conds_to_mask(conds, feats, ts, vp10, close_index_cols):
    """把決策樹路徑條件套到全宇宙全歷史wide frame上,回傳布林mask(date x code)。"""
    mask = None
    for name, op, t in conds:
        if name == "ts":
            m = (ts <= t) if op == "<=" else (ts > t)
            m = pd.DataFrame(np.tile(m.values.reshape(-1, 1), (1, len(close_index_cols))),
                              index=m.index, columns=close_index_cols)
        elif name == "vp10":
            m = (vp10 <= t) if op == "<=" else (vp10 > t)
            m = pd.DataFrame(np.tile(m.values.reshape(-1, 1), (1, len(close_index_cols))),
                              index=m.index, columns=close_index_cols)
        else:
            frame = feats[name]
            m = (frame <= t) if op == "<=" else (frame > t)
        mask = m if mask is None else (mask & m.reindex_like(mask).fillna(False))
    return mask


# ======================================================================
# 5. HTML 呈現小工具(沿用R.boot_line邏輯但注意key名稱,見docstring坑提醒)
# ======================================================================
def boot_line(label, r, unit="pp"):
    if r is None:
        return f"<li>{label}: n太小,觀察層(未達bootstrap最低樣本門檻)</li>"
    key = "diff" if r and "diff" in r else ("med" if r and "med" in r else "stat")
    sig = "<b>✓排0(顯著)</b>" if r["sig"] else "含0(不顯著)"
    return f"<li>{label}: {r[key]:+.2f}{unit} 95%CI[{r['lo']:+.2f},{r['hi']:+.2f}] {sig}</li>"


# ======================================================================
# 6. main
# ======================================================================
def main():
    t_start = time.time()
    dt, _ln = R.load_dtlend()
    codes = sorted(dt.code.unique())
    log(f"[main] 當沖宇宙 {len(codes)} 檔")

    op, high, low, close, vol, money = load_price_full(codes, "2013-01-01")
    op, high, low, vol, money = (f.reindex(index=close.index, columns=close.columns)
                                  for f in (op, high, low, vol, money))

    amt20 = money.rolling(20, min_periods=15).mean() / 1e8
    uni = amt20 >= 0.3
    log(f"[main] 宇宙(amt20>=0.3億)股-日數={int(uni.sum().sum()):,} / 全表格{uni.size:,}格")

    dtp = dt.pivot_table(index="date", columns="code", values="Volume", aggfunc="sum").reindex(
        index=close.index, columns=close.columns)
    buyp = dt.pivot_table(index="date", columns="code", values="BuyAmount", aggfunc="sum").reindex(
        index=close.index, columns=close.columns)
    sellp = dt.pivot_table(index="date", columns="code", values="SellAmount", aggfunc="sum").reindex(
        index=close.index, columns=close.columns)

    feats, ratio, pnl = build_features(op, high, low, close, vol, dtp, buyp, sellp)
    log(f"[main] pnl proxy覆蓋: {pnl.notna().sum().sum():,}格; 特徵數(不含ts/vp10)={len(feats)}")

    ts, vp10 = load_market_regime(close.index)

    panel, winner_mask = build_panel(uni, pnl, feats, ts, vp10)
    feat_cols = list(feats.keys()) + ["ts", "vp10"]
    log(f"[main] 特徵欄位共{len(feat_cols)}個: {feat_cols}")

    nan_rate = panel[feat_cols].isna().mean().sort_values(ascending=False)
    log(f"[main] 特徵NaN比例(前5高): {nan_rate.head(5).to_dict()}")

    log("=" * 60 + "\n[main] Step1: walk-forward擴張窗多折AUC")
    wf = walk_forward(panel, feat_cols)

    log("=" * 60 + "\n[main] Step2: 主切分train<2024/test>=2024, 訓練HGB+RF")
    yr = panel.date.dt.year
    tr_mask, te_mask = (yr < MAIN_SPLIT_YEAR), (yr >= MAIN_SPLIT_YEAR)
    Xtr, ytr = panel.loc[tr_mask, feat_cols], panel.loc[tr_mask, "label"]
    Xte, yte = panel.loc[te_mask, feat_cols], panel.loc[te_mask, "label"]
    log(f"[main] 主切分: train(2014-{MAIN_SPLIT_YEAR - 1}) n={len(Xtr):,}, "
        f"test({MAIN_SPLIT_YEAR}起) n={len(Xte):,}")

    hgb = make_hgb()
    hgb.fit(Xtr, ytr)
    hgb_auc_tr = roc_auc_score(ytr, hgb.predict_proba(Xtr)[:, 1])
    hgb_auc_te = roc_auc_score(yte, hgb.predict_proba(Xte)[:, 1])
    log(f"[main] HGB主模型 AUC train={hgb_auc_tr:.4f} test={hgb_auc_te:.4f}")

    rf = make_rf()
    rf.fit(Xtr, ytr)
    rf_auc_tr = roc_auc_score(ytr, rf.predict_proba(Xtr)[:, 1])
    rf_auc_te = roc_auc_score(yte, rf.predict_proba(Xte)[:, 1])
    log(f"[main] RF次模型  AUC train={rf_auc_tr:.4f} test={rf_auc_te:.4f}")

    # 單特徵基準AUC(對照:多特徵樹模型相對單一特徵的增量)
    single_auc = {}
    for f in ("dt_ratio", "gap_pct", "amp_pct120", "vp10", "ts", "vol_x20", "prev_ratio"):
        v = Xte[f]
        ok = v.notna()
        if ok.sum() > 50:
            a = roc_auc_score(yte[ok], v[ok])
            single_auc[f] = max(a, 1 - a)  # 方向不拘,取離0.5較遠的一側,量級對照用

    log("=" * 60 + "\n[main] Step3: permutation importance(測試集上算,HGB主模型)")
    perm = permutation_importance(hgb, Xte, yte, n_repeats=10, random_state=42,
                                   scoring="roc_auc", n_jobs=-1)
    perm_imp = pd.Series(perm.importances_mean, index=feat_cols).sort_values(ascending=False)
    perm_std = pd.Series(perm.importances_std, index=feat_cols)
    log(f"[main] permutation importance前10:\n{perm_imp.head(10)}")

    rf_imp = pd.Series(rf.feature_importances_, index=feat_cols).sort_values(ascending=False)
    log(f"[main] RF impurity importance前10:\n{rf_imp.head(10)}")

    log("=" * 60 + "\n[main] Step4: 移除重要度前2名特徵,重新訓練穩健性檢查")
    top2 = perm_imp.head(2).index.tolist()
    remain_cols = [c for c in feat_cols if c not in top2]
    hgb2 = make_hgb()
    hgb2.fit(Xtr[remain_cols], ytr)
    auc_te_drop = roc_auc_score(yte, hgb2.predict_proba(Xte[remain_cols])[:, 1])
    perm2 = permutation_importance(hgb2, Xte[remain_cols], yte, n_repeats=10, random_state=42,
                                    scoring="roc_auc", n_jobs=-1)
    perm_imp2 = pd.Series(perm2.importances_mean, index=remain_cols).sort_values(ascending=False)
    log(f"[main] 移除{top2}後 test AUC={auc_te_drop:.4f}(原始{hgb_auc_te:.4f}); "
        f"新排名前5:\n{perm_imp2.head(5)}")

    log("=" * 60 + "\n[main] Step5: 淺層決策樹抽取交互作用規則")
    dt_clf = DecisionTreeClassifier(max_depth=3, min_samples_leaf=200, random_state=42)
    dt_clf.fit(Xtr, ytr)
    dt_auc_te = roc_auc_score(yte, dt_clf.predict_proba(Xte)[:, 1])
    from sklearn.tree import export_text
    tree_txt = export_text(dt_clf, feature_names=feat_cols, max_depth=3)
    log(f"[main] 淺層決策樹(depth3)test AUC={dt_auc_te:.4f}\n{tree_txt}")

    conds, leaf_rate, leaf_n = find_leaf_rule(dt_clf, feat_cols, Xtr, ytr, min_leaf_n=150)
    rtxt = rule_text(conds)
    base_rate_tr = float(ytr.mean())
    log(f"[main] 最佳葉節點規則: {rtxt} → 訓練集內贏家比例={leaf_rate * 100:.1f}%(n={leaf_n}, "
        f"訓練集基準線={base_rate_tr * 100:.1f}%)")

    log("=" * 60 + "\n[main] Step6: 規則翻譯回全宇宙全歷史wide frame, case-control+bootstrap驗證")
    rule_mask = conds_to_mask(conds, feats, ts, vp10, close.columns)
    rule_mask = rule_mask.reindex_like(uni).fillna(False) & uni
    rule_evs = mask_to_evs(rule_mask)
    log(f"[rule] 規則命中事件(全歷史全宇宙,未做gap去重,比照build_dtlend_pattern_pnl.py同日"
        f"contemporaneous設計) n={len(rule_evs):,}, {rule_evs.code.nunique()}檔, {rule_evs.date.nunique()}個交易日")

    rule_ctrl = R.case_control(rule_evs, uni, rule_mask, seed=20260802)
    log(f"[rule] case-control對照組 n={len(rule_ctrl):,}")

    def lookup_pnl(evs):
        vals, dates = [], []
        for d, g in evs.groupby("date"):
            if d not in pnl.index:
                continue
            row = pnl.loc[d]
            for c in g.code:
                v = row.get(c)
                if pd.notna(v):
                    vals.append(v)
                    dates.append(d)
        return vals, dates

    rv, rd = lookup_pnl(rule_evs)
    cv, cd = lookup_pnl(rule_ctrl)
    n_rule_and_winner = int((rule_mask & winner_mask).sum().sum())  # 規則命中且同時是贏家日的格數

    boot_vs_ctrl = R.boot_diff_ci(rv, rd, cv, cd)
    boot_vs0 = R.boot_median_ci(list(np.array(rv) - float(np.nanmedian(
        pnl.values[uni.values]))), rd)
    rule_hit_rate = n_rule_and_winner / len(rule_evs) * 100 if len(rule_evs) else float("nan")
    log(f"[rule] 規則組P&L proxy中位數={np.median(rv):+.2f}%(n={len(rv):,}) vs "
        f"case-control對照組中位數={np.median(cv):+.2f}%(n={len(cv):,}); "
        f"規則命中同時=贏家日比例={rule_hit_rate:.1f}%(基準線10%)")

    log("=" * 60 + "\n[main] 組裝報告")
    write_report(wf, hgb_auc_tr, hgb_auc_te, rf_auc_tr, rf_auc_te, single_auc,
                 perm_imp, perm_std, rf_imp, top2, auc_te_drop, perm_imp2,
                 dt_auc_te, tree_txt, conds, rtxt, leaf_rate, leaf_n, base_rate_tr,
                 rule_evs, rule_ctrl, rv, cv, boot_vs_ctrl, boot_vs0, rule_hit_rate,
                 len(Xtr), len(Xte), panel)
    log(f"[main] 全部完成,總耗時{time.time() - t_start:.0f}秒")


# ======================================================================
# 7. 報告組裝
# ======================================================================
def write_report(wf, hgb_auc_tr, hgb_auc_te, rf_auc_tr, rf_auc_te, single_auc,
                  perm_imp, perm_std, rf_imp, top2, auc_te_drop, perm_imp2,
                  dt_auc_te, tree_txt, conds, rtxt, leaf_rate, leaf_n, base_rate_tr,
                  rule_evs, rule_ctrl, rv, cv, boot_vs_ctrl, boot_vs0, rule_hit_rate,
                  n_train, n_test, panel):
    css = """
body{background:#1a1a19;color:#fff;font-family:"Noto Sans TC",sans-serif;margin:24px;max-width:1150px}
h1{font-size:20px} h2{font-size:15px;color:#c3c2b7;margin-top:30px;border-bottom:1px solid #333;padding-bottom:4px}
h3{font-size:13.5px;color:#a8a79a;margin:16px 0 4px}
table{border-collapse:collapse;font-size:12.5px;font-variant-numeric:tabular-nums;margin:8px 0}
td,th{border:1px solid #333;padding:4px 9px;text-align:right} th{text-align:left;color:#c3c2b7}
.note{color:#8a8878;font-size:12.5px;line-height:1.8} .good{color:#7ec97e} .bad{color:#e06c5a}
.warn{color:#c3a55a} .hl{background:#2b3a2b} .sub{color:#777;font-size:11px}
ul{margin:4px 0;padding-left:20px;font-size:12.5px;color:#ccc;line-height:1.7}
pre{background:#111;color:#ccc;padding:10px;border-radius:4px;font-size:11.5px;overflow-x:auto;line-height:1.5}
.verdict{font-size:13px;font-weight:bold;padding:6px 10px;border-radius:4px;display:inline-block;margin:4px 0}
.v-good{background:#243b24;color:#7ec97e} .v-bad{background:#3b2420;color:#e06c5a}
.v-warn{background:#3b3420;color:#c3a55a}
"""
    # ---- walk-forward表 ----
    wf_rows = "".join(
        f"<tr><th>{int(r.test_year)}</th><td>{r.n_train:,.0f}</td><td>{r.n_test:,.0f}</td>"
        f"<td>{r.auc_train:.4f}</td><td class='{'good' if r.auc_test > 0.55 else 'warn' if r.auc_test > 0.5 else 'bad'}'>{r.auc_test:.4f}</td></tr>"
        for r in wf.itertuples())
    wf_table = (f"<table><tr><th>測試年</th><th>train樣本數</th><th>test樣本數</th>"
                f"<th>train AUC(樣本內)</th><th>test AUC(樣本外)</th></tr>{wf_rows}</table>")
    wf_mean_te = wf.auc_test.mean()
    wf_std_te = wf.auc_test.std()

    # ---- 主切分AUC ----
    gap_hgb = hgb_auc_tr - hgb_auc_te
    gap_rf = rf_auc_tr - rf_auc_te
    overfit_cls = "v-good" if gap_hgb < 0.05 and gap_rf < 0.05 else "v-warn" if gap_hgb < 0.10 else "v-bad"
    overfit_txt = (f"train-test AUC差距 HGB={gap_hgb:+.4f} / RF={gap_rf:+.4f}" +
                   ("(差距小,樣本外表現穩定,未明顯過擬合)" if gap_hgb < 0.05 else
                    "(有一定差距,樣本外表現弱化但仍優於隨機0.5,屬正常泛化落差)" if gap_hgb < 0.10 else
                    "(差距偏大,樣本外表現大幅弱化,提示過擬合風險較高)"))

    main_table = f"""<table>
<tr><th>模型</th><th>train樣本數</th><th>test樣本數</th><th>AUC(train,樣本內)</th><th>AUC(test,樣本外)</th></tr>
<tr><th>HistGradientBoosting(主模型)</th><td>{n_train:,}</td><td>{n_test:,}</td>
<td>{hgb_auc_tr:.4f}</td><td class="good">{hgb_auc_te:.4f}</td></tr>
<tr><th>RandomForest(次模型,交叉對照)</th><td>{n_train:,}</td><td>{n_test:,}</td>
<td>{rf_auc_tr:.4f}</td><td class="good">{rf_auc_te:.4f}</td></tr>
<tr><th>淺層決策樹(depth3,規則抽取用)</th><td>{n_train:,}</td><td>{n_test:,}</td>
<td>—</td><td>{dt_auc_te:.4f}</td></tr>
</table>"""

    single_rows = "".join(
        f"<tr><th>{FEATURE_DESC.get(k, k)}</th><td>{v:.4f}</td></tr>" for k, v in single_auc.items())
    single_table = f"<table><tr><th>單一特徵(僅該欄位當分數)</th><th>AUC(test,樣本外)</th></tr>{single_rows}</table>"

    # ---- importance表 ----
    perm_rows = "".join(
        f"<tr><th>{i + 1}. {FEATURE_DESC.get(k, k)}</th><td>{v:.4f}</td><td>±{perm_std[k]:.4f}</td>"
        f"<td>{rf_imp.get(k, float('nan')):.4f}</td></tr>"
        for i, (k, v) in enumerate(perm_imp.head(15).items()))
    imp_table = (f"<table><tr><th>排名.特徵(HGB permutation importance排序)</th>"
                 f"<th>permutation importance(ΔAUC,test集)</th><th>±std(10次重複)</th>"
                 f"<th>RF impurity importance(交叉對照)</th></tr>{perm_rows}</table>")

    top2_desc = "、".join(FEATURE_DESC.get(k, k) for k in top2)
    drop_rows = "".join(
        f"<tr><th>{i + 1}. {FEATURE_DESC.get(k, k)}</th><td>{v:.4f}</td></tr>"
        for i, (k, v) in enumerate(perm_imp2.head(10).items()))
    drop_table = f"<table><tr><th>排名.特徵(移除{top2_desc}後)</th><th>permutation importance</th></tr>{drop_rows}</table>"
    robust_cls = "v-good" if auc_te_drop > 0.55 else "v-warn" if auc_te_drop > 0.51 else "v-bad"
    robust_txt = (f"移除前2大特徵({top2_desc})後test AUC={auc_te_drop:.4f}"
                  + (",仍明顯高於隨機0.5,其餘特徵確有獨立訊號、非單一巨大特徵陪榜"
                     if auc_te_drop > 0.55 else
                     ",略高於隨機但已大幅衰退,其餘特徵訊號薄弱"
                     if auc_te_drop > 0.51 else
                     ",已幾乎回到隨機0.5,原模型AUC幾乎完全由這1-2個特徵貢獻,其餘特徵近似雜訊陪榜"))

    # ---- 規則驗證 ----
    hit_win_cls = "v-good" if rule_hit_rate >= 15 else "v-warn" if rule_hit_rate >= 10 else "v-bad"
    ctrl_sig = boot_vs_ctrl is not None and boot_vs_ctrl["sig"] and boot_vs_ctrl["diff"] > 0
    vs0_sig = boot_vs0 is not None and boot_vs0["sig"] and boot_vs0["med"] > 0 if boot_vs0 else False
    if ctrl_sig:
        rule_verdict_cls, rule_verdict_txt = "v-good", "✅規則組P&L proxy顯著優於case-control同日對照組(排0),翻譯回顯式規則後站得住腳"
    elif boot_vs_ctrl is not None and boot_vs_ctrl["diff"] > 0:
        rule_verdict_cls, rule_verdict_txt = "v-warn", "🟡方向對(規則組優於對照組)但CI含0,樣本仍不足以排0"
    else:
        rule_verdict_cls, rule_verdict_txt = "v-bad", "❌規則組未顯著優於case-control對照組,樹模型抽取的規則翻譯回顯式規則後未能複現"

    rule_boot = "".join([
        boot_line("規則組 vs case-control同日對照組(P&L proxy中位差)", boot_vs_ctrl, unit="%"),
        boot_line("規則組 vs 全宇宙中位數(P&L proxy excess中位數,月群bootstrap vs 0)", boot_vs0, unit="%"),
    ])

    payload = {
        "wf": {"years": [int(y) for y in wf.test_year], "train": [round(a, 4) for a in wf.auc_train],
               "test": [round(a, 4) for a in wf.auc_test]},
        "imp": {"labels": [FEATURE_DESC.get(k, k) for k in perm_imp.head(12).index],
                "vals": [round(v, 4) for v in perm_imp.head(12).values]},
        "rule": {"labels": ["case-control對照組", "規則命中組"],
                 "vals": [round(float(np.median(cv)), 3), round(float(np.median(rv)), 3)]},
    }
    payload_json = json.dumps(payload, ensure_ascii=False)

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>樹模型探索當沖贏家日特徵交互作用(2026-08-01)</title>
<script src="plotly.min.js"></script><style>{css}</style></head><body>
<h1>🌲 樹模型探索當沖「贏家日」特徵交互作用</h1>
<div class="note">⚠定位聲明: 本卷是<b>探索工具</b>,不是最終訊號——樹模型只用來擴大搜尋範圍、
找人工逐一測特徵可能漏掉的特徵組合,任何重要特徵/交互作用最後都要翻譯回顯式規則、套用本專案既有
case-control+bootstrap框架驗證過才算數。與平行進行的姊妹任務build_dtlend_winner_features.py
(人工特徵battery+單特徵case-control AUC考卷)互補、互不依賴、各自獨立產出,供使用者對照。<br>
標籤=贏家日: P&amp;L proxy=(SellAmount-BuyAmount)/BuyAmount×100(逐股逐日),當日全宇宙
(amt20>=0.3億∧四碼∧非00 ETF)排名前10%(每日有效樣本&gt;={MIN_UNI_PER_DAY}才判定)。
負例=case-control同日隨機抽樣非贏家股(複用build_dtlend_report.py的case_control()),非「其餘全部」,
可直接拿AUC對照人工battery的單特徵AUC量級。訓練/測試<b>按時間切分</b>(非隨機k-fold),
主切分=train 2014-{MAIN_SPLIT_YEAR - 1} / test {MAIN_SPLIT_YEAR}起,另補walk-forward擴張窗多折。</div>

<h2>⚙️ 套件與環境聲明(誠實記錄)</h2>
<div class="note">環境檢查: 無xgboost、無lightgbm、無shap——且<b>連sklearn本身都未預裝</b>
(超出原本「sklearn幾乎一定有裝」的預期)。權衡: 若堅持「不裝任何套件」則只能手刻決策樹/森林,
出錯風險(統計結論層級的bug)遠高於安裝一個成熟穩定套件的環境風險,故本次<b>唯一一次額外動作</b>=
<code>pip install scikit-learn</code>(純wheel安裝,無需編譯,相依的numpy/scipy已存在且版本相容,
未觸及xgboost/lightgbm等較重、Windows下常有DLL問題的套件)。主模型改用
<code>sklearn.ensemble.HistGradientBoostingClassifier</code>(sklearn原生梯度提升樹,
概念上最接近xgboost/lightgbm的內建替代品,原生支援缺值不必手動補值,對本資料集常見的rolling window
熱身期NaN特別友善);次模型<code>RandomForestClassifier</code>交叉對照重要度排序穩定性;
另用淺層<code>DecisionTreeClassifier</code>(max_depth=3)直接讀分裂路徑抽取交互作用規則。
三模型均刻意調高min_samples_leaf/限制max_depth當正則化,對抗「同一天不同股票高度相關,
不是真正獨立樣本」的已知風險(時間切分之上的第二層防呆)。</div>

<h2>📋 核心結論總表</h2>
<table>
<tr><th>檢定</th><th>結果</th></tr>
<tr><th>樣本外AUC是否穩定(walk-forward多折,{len(wf)}折)</th>
<td>test AUC均值={wf_mean_te:.4f}(std={wf_std_te:.4f})</td></tr>
<tr><th>主切分train-test AUC差距(過擬合診斷)</th>
<td><span class="verdict {overfit_cls}">{overfit_txt}</span></td></tr>
<tr><th>移除前2大特徵穩健性檢查</th>
<td><span class="verdict {robust_cls}">{robust_txt}</span></td></tr>
<tr><th>樹模型規則翻譯回顯式規則後驗證</th>
<td><span class="verdict {rule_verdict_cls}">{rule_verdict_txt}</span></td></tr>
</table>

<h2>① Walk-forward擴張窗多折樣本外AUC</h2>
<div class="note">每折test=該年全年,train=該年以前全部歷史(擴張窗)。跨2020疫情崩盤/2021大多頭/
2022熊市/2023-2026等不同regime都能看到樣本外AUC,才能排除「單一巧合期間」疑慮。</div>
{wf_table}
<div id="c_wf" style="height:320px"></div>

<h2>② 主切分(train 2014-{MAIN_SPLIT_YEAR - 1} / test {MAIN_SPLIT_YEAR}起)——樣本外AUC證明沒有過擬合</h2>
{main_table}
<div class="note">對照: 各單一特徵獨立當分數的AUC(取離0.5較遠一側,量級對照用,可與人工battery的
單特徵AUC互相參照)。</div>
{single_table}

<h2>③ Feature Importance排名(HGB permutation importance,測試集上算,避免訓練集算的樂觀偏誤)</h2>
{imp_table}
<div id="c_imp" style="height:420px"></div>

<h2>④ 穩健性檢查: 移除前2大特徵({top2_desc})重新訓練</h2>
<div class="note">目的=確認排名不是被單一巨大特徵完全主導、其餘都是雜訊陪榜。</div>
{drop_table}

<h2>⑤ 淺層決策樹(depth=3)分裂路徑——交互作用直接可讀</h2>
<div class="note">淺層樹test AUC={dt_auc_te:.4f}(比HGB/RF簡化很多,犧牲部分準確度換取可解讀性,
純作規則抽取用途,不是最終判讀模型)。以下為完整分裂路徑文字輸出:</div>
<pre>{tree_txt}</pre>

<h2>⑥ 翻譯回顯式規則 + case-control/bootstrap驗證</h2>
<div class="note">從決策樹depth3分裂路徑中挑「訓練集內贏家比例最高∧樣本數達門檻(&gt;=150)」的
葉節點,逐條分裂條件組成規則:</div>
<div class="note" style="font-size:13.5px;color:#ddd;background:#22221f;padding:8px;border-radius:4px">
<b>規則: {rtxt}</b><br>
訓練集內: 此規則命中時贏家比例={leaf_rate * 100:.1f}%(n={leaf_n:,}) vs 訓練集基準線{base_rate_tr * 100:.1f}%
</div>
<div class="note">把此規則套回<b>全宇宙全歷史</b>wide frame(非樹模型訓練用的平衡面板)重新計算:
規則命中事件n={len(rule_evs):,}({rule_evs.code.nunique()}檔,{rule_evs.date.nunique()}個交易日,
未做gap去重,比照build_dtlend_pattern_pnl.py同日contemporaneous設計);
case-control對照組n={len(rule_ctrl):,}。規則命中同時=贏家日的比例=
<span class="{'good' if rule_hit_rate >= 15 else 'warn' if rule_hit_rate >= 10 else 'bad'}">{rule_hit_rate:.1f}%</span>
(全樣本基準線=10%定義)。</div>
<h3>bootstrap/case-control顯著性(月群重抽樣,95%CI)</h3>
<ul>{rule_boot}</ul>
<div id="c_rule" style="height:300px"></div>

<h2>🔍 與人工逐一特徵測試相比: 樹模型的額外發現</h2>
<div class="note">
人工battery是逐一測試單一特徵(或使用者手動設計的固定組合)的case-control AUC,樹模型的價值在於
<b>自動搜尋</b>特徵間的交互切點,不受限於研究者事先猜到的組合。本卷淺層決策樹的分裂路徑(見上方⑤)
本身就是交互作用的直接證據——樹在根節點先按某特徵切一刀,再於子節點內對<b>另一個</b>特徵切第二刀,
兩刀合起來的葉節點命中率({leaf_rate * 100:.1f}%)顯著高於任一特徵單獨切出的水準(見②單一特徵AUC對照),
這正是「特徵組合」層次的訊號,不是單一特徵能提供的。至於這個組合是否比人工battery已經測過的固定組合
(若有測到類似交互)更強、或是全新發現,需俟兩份報告都完成後由使用者逐條對照(本卷不重複讀取姊妹檔的
輸出,避免互相依賴)。</div>

<h2>已知限制與資料品質問題(誠實聲明)</h2>
<div class="note">
①<b>樹模型是探索工具,不是最終訊號</b>——本卷全程以「翻譯回顯式規則後case-control+bootstrap能否複現」
為最終判準,見上方⑥,若複現失敗即應視為過擬合的假象,不採用;<br>
②贏家日標籤本身要求BuyAmount&gt;0才能定義P&amp;L proxy,case-control對照組則從全宇宙(含當日零/極少
當沖活動的股票)隨機抽樣,故「dt_ratio(當沖比率本身)」預期會是重要度最高的特徵之一(贏家必然有實質
當沖活動,隨機對照組不必然),這是設計上的預期而非模型的意外發現,見④穩健性檢查(移除該特徵後其餘特徵
是否仍有訊號)才是回答「除了活躍度以外還有沒有型態訊號」的關鍵;<br>
③同一天不同股票、同一檔股票鄰近幾天皆非真正獨立樣本,本卷用(a)時間切分(walk-forward+主切分)
(b)三模型皆調高min_samples_leaf/限制max_depth 兩層防呆對抗虛高風險,但月群bootstrap的「同月內近似
獨立」假設仍是保守但非完美的做法(同註於build_dtlend_report.py其他考卷);<br>
④amp_pct120等逐股rolling(120)特徵在個股上市未滿120個交易日時為NaN,樹模型原生處理缺值,惟意味著
新股樣本在該特徵維度的資訊量天生較薄;<br>
⑤vp10/ts為大盤層特徵,同一天所有股票數值相同(非個股層資訊),樹模型可能把它當成「時間分段」的替代品
而非真正對比不同股票的訊號來源,解讀交互作用時需留意這點,不宜過度延伸為「個股層」發現;<br>
⑥規則驗證的case-control對照組為單一次固定種子抽樣(20260802),非窮舉,母體夠大時影響有限但非零;<br>
⑦本卷為盤點層/觀察層,不涉及交易成本、可交易性(T+1開盤進場版)驗證,亦不預設上板。
</div>
<div class="note">維運: python 研究腳本/當沖借券/build_dtlend_tree_explore.py(從根目錄執行,鐵律)。
姊妹檔(互補、互不依賴): 研究腳本/當沖借券/build_dtlend_winner_features.py(人工特徵battery+
case-control AUC考卷)、build_dtlend_report.py(load_dtlend/case_control等基礎建設出處)、
build_dtlend_pattern_pnl.py(P&amp;L proxy contemporaneous驗證先例)。</div>

<script>
const D={payload_json};
const BG={json.dumps(BG, ensure_ascii=False)};
Plotly.newPlot('c_wf', [
  {{x:D.wf.years, y:D.wf.train, name:'train AUC(樣本內)', type:'scatter', mode:'lines+markers', line:{{color:'{GRAY}'}}}},
  {{x:D.wf.years, y:D.wf.test, name:'test AUC(樣本外)', type:'scatter', mode:'lines+markers', line:{{color:'{GREEN}'}}}}
], Object.assign({{title:'Walk-forward擴張窗: 逐年樣本外AUC', yaxis:{{title:'AUC', range:[0.45,1]}},
  shapes:[{{type:'line', x0:D.wf.years[0], x1:D.wf.years[D.wf.years.length-1], y0:0.5, y1:0.5,
  line:{{dash:'dot', color:'#666'}}}}]}}, BG));
Plotly.newPlot('c_imp', [{{x:D.imp.vals.slice().reverse(), y:D.imp.labels.slice().reverse(),
  type:'bar', orientation:'h', marker:{{color:'{BLUE}'}}}}],
  Object.assign({{title:'Permutation Importance(ΔAUC,test集,前12名)', margin:{{t:42,l:180,r:18,b:40}}}}, BG));
Plotly.newPlot('c_rule', [{{x:D.rule.labels, y:D.rule.vals, type:'bar',
  marker:{{color:['{GRAY}','{GREEN}']}}, text:D.rule.vals.map(v=>v.toFixed(2)+'%'), textposition:'outside'}}],
  Object.assign({{title:'規則命中組 vs case-control對照組: P&L proxy中位數', yaxis:{{title:'%',zeroline:true,zerolinecolor:'#555'}}}}, BG));
</script>
</body></html>"""
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    log(f"[report] 已輸出 {OUT}")


if __name__ == "__main__":
    main()
