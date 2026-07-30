# -*- coding: utf-8 -*-
"""法說會事件研究考卷(2026-07-26,使用者裁示開工;資料=conference表Yahoo回補2025-08起)
機制假說: 法說會=公司「主動擇時」的軟訊息事件(想講好話才開)——與被迫披露(財報/月營收)不同家族,
不踩「財報前效應❌無條件埋伏」舊判決。先驗: 事後偏正但可能已price in;方向開放。
設計(預註冊):
- 母體: conference表已舉行場次,(code,date)去重,4碼個股,對到fm_daily_price
- 主測A(可交易): D+1開盤買→D+5/10/20收盤賣,扣0.45%;超額=減TAIEX同窗報酬
- 描述B(不可交易,公告時點不可得): 事前run-up D-10收→D-1收(形狀觀察)
- 分組: ①自辦(訊息含「召開」不含「參加」) vs 受邀參加券商場 ②線上/電話 vs 實體
  ③上市 vs 上櫃 ④事前位階(D-1收盤的240日位階>=80高檔 / <=50低檔)
- 驗證限制(誠實申報): 樣本僅~12個月(2025-08~2026-07)=單一regime,年層LOTO不可行;
  改用月群cluster bootstrap(B=10000,seed=42)+逐月方向;**判決上限=觀察層候選**,
  轉正需MOPS歷史回補或live累積(使用者已裁示:此窗有價值再考慮MOPS)
用法: python -X utf8 build_conference_event.py
"""
import sqlite3
import sys
import time

import numpy as np
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DB = "capital_flow.db"
COST = 0.45
KS = [5, 10, 20]
B_BOOT = 10000
SEED = 42


def rd(sql, tries=6, wait=4):
    for i in range(tries):
        try:
            con = sqlite3.connect(DB, timeout=30)
            df = pd.read_sql(sql, con)
            con.close()
            return df
        except sqlite3.OperationalError as e:
            if "locked" in str(e) and i < tries - 1:
                time.sleep(wait)
            else:
                raise


def stat(x, lab, pref="    "):
    x = pd.Series(x).dropna()
    if len(x) < 15:
        print(f"{pref}{lab}: n={len(x)}太少")
        return None
    print(f"{pref}{lab}: 中位{x.median():+6.2f}% 均值{x.mean():+6.2f}% "
          f"勝率{(x > 0).mean() * 100:3.0f}% n={len(x):,}")
    return x


def month_boot(df, col, label, b=B_BOOT, seed=SEED):
    d = df.dropna(subset=[col]).copy()
    d["mo"] = d.date.dt.to_period("M").astype(str)
    mos = sorted(d.mo.unique())
    if len(mos) < 6 or len(d) < 60:
        print(f"      [{label}] 月份/樣本不足,略過")
        return
    mm = d.groupby("mo")[col].median()
    pos = (mm > 0).sum()
    print(f"      逐月中位為正: {pos}/{len(mos)}月 (最差月{mm.idxmin()}={mm.min():+.2f}%)")
    rng = np.random.default_rng(seed)
    groups = {m: d.loc[d.mo == m, col].values for m in mos}
    meds = []
    for _ in range(b):
        pick = rng.choice(mos, size=len(mos), replace=True)
        arr = np.concatenate([groups[m] for m in pick])
        meds.append(np.median(arr))
    meds = np.array(meds)
    lo, hi = np.percentile(meds, [2.5, 97.5])
    print(f"      月群bootstrap: 中位CI95=[{lo:+.2f},{hi:+.2f}]% P(<=0)={(meds <= 0).mean():.4f}")


def main():
    conf = rd("SELECT code, date, time, name, market, place, information FROM conference")
    conf["date"] = pd.to_datetime(conf.date)
    conf = conf[conf.code.str.fullmatch(r"\d{4}")]
    conf = conf.sort_values(["code", "date", "time"]).drop_duplicates(["code", "date"])
    px = rd("SELECT code, date, open, close FROM fm_daily_price ORDER BY code, date")
    px["date"] = pd.to_datetime(px.date)
    stocks = {c: g.sort_values("date").reset_index(drop=True) for c, g in px.groupby("code")}
    # 基準=等權全市場指數(每日全股票平均報酬累乘)——TAIEX市值加權在2330獨走行情下
    # 對個股事件是系統性負偏基準(CB磁吸考卷同教訓),TAIEX版只留作對照
    piv = px[px.close > 0].pivot_table(index="date", columns="code", values="close")
    dret = piv.pct_change(fill_method=None)
    ew_ret = dret.mean(axis=1).fillna(0.0)
    ew_idx = (1 + ew_ret).cumprod()
    ew_dts = ew_idx.index.values
    ew_cls = ew_idx.values
    twii = rd("SELECT date, close FROM index_daily WHERE market='TAIEX' ORDER BY date")
    twii["date"] = pd.to_datetime(twii.date)
    tw_dts = twii.date.values
    tw_cls = twii.close.values

    rows = []
    for r in conf.itertuples():
        g = stocks.get(r.code)
        if g is None:
            continue
        dts = g.date.values
        n = len(g)
        i = int(np.searchsorted(dts, np.datetime64(r.date)))  # 首個>=D的bar(D休市則次日)
        if i + 1 >= n or i < 11 or i + max(KS) + 1 >= n:
            continue  # 需要D+1進場與D+20出場都存在(未來場次/太新自然排除)
        o_, c_ = g.open.values, g.close.values
        if o_[i + 1] <= 0:
            continue
        rec = {"code": r.code, "date": r.date, "market": r.market,
               "own": "召開" in str(r.information) and "參加" not in str(r.information),
               "online": any(k in (str(r.place) + str(r.information)) for k in ("線上", "視訊", "電話", "網路")),
               }
        # 事前run-up(描述)
        if c_[i - 11] > 0 and c_[i - 1] > 0:
            rec["pre10"] = (c_[i - 1] / c_[i - 11] - 1) * 100
        # 位階(D-1收盤 vs 前240日)
        w = c_[max(0, i - 241):i]
        w = w[w > 0]
        if len(w) >= 120:
            rec["ptile"] = (w <= c_[i - 1]).mean() * 100
        # 事後可交易: D+1開盤→D+k收盤, 超額=減TAIEX
        for k in KS:
            j = i + k
            if j < n and c_[j] > 0:
                raw = (c_[j] / o_[i + 1] - 1) * 100 - COST
                rec[f"raw{k}"] = raw
                ei = int(np.searchsorted(ew_dts, dts[i + 1]))
                ej = int(np.searchsorted(ew_dts, dts[j], side="right") - 1)
                if 0 <= ei < len(ew_cls) and 0 <= ej < len(ew_cls) and ei < ej:
                    rec[f"x{k}"] = raw - (ew_cls[ej] / ew_cls[ei] - 1) * 100
                ti = int(np.searchsorted(tw_dts, dts[i + 1]))
                tj = int(np.searchsorted(tw_dts, dts[j], side="right") - 1)
                if 0 <= ti < len(tw_cls) and 0 <= tj < len(tw_cls) and ti < tj:
                    rec[f"tx{k}"] = raw - (tw_cls[tj] / tw_cls[ti] - 1) * 100
        # 安慰劑: 同檔股票,事件前30交易日假錨點,同k=10口徑(控制個股skew與等權基準偏差)
        p = i - 30
        if p >= 1 and p + 10 < n and o_[p + 1] > 0 and c_[p + 10] > 0:
            praw = (c_[p + 10] / o_[p + 1] - 1) * 100 - COST
            ei = int(np.searchsorted(ew_dts, dts[p + 1]))
            ej = int(np.searchsorted(ew_dts, dts[p + 10], side="right") - 1)
            if 0 <= ei < len(ew_cls) and 0 <= ej < len(ew_cls) and ei < ej:
                rec["plc10"] = praw - (ew_cls[ej] / ew_cls[ei] - 1) * 100
        rows.append(rec)
    ev = pd.DataFrame(rows)
    ev.to_pickle("快取/tmp_conference_event_panel.pkl")
    print(f"法說會事件: conference去重{len(conf):,}場 -> 可測{len(ev):,}場 "
          f"({ev.date.min().date()}~{ev.date.max().date()}); 自辦{ev.own.mean() * 100:.0f}% "
          f"線上{ev.online.mean() * 100:.0f}% 上櫃{(ev.market == 'TWO').mean() * 100:.0f}%")
    print("⚠限制: 單一regime(~12個月),月群bootstrap代年層LOTO,判決上限=觀察層候選\n")

    print("== 主測A: 法說會後 D+1開→D+k收 超額報酬(減等權全市場指數,扣0.45%) ==")
    for k in KS:
        stat(ev[f"x{k}"], f"x{k}(等權超額)")
    month_boot(ev, "x10", "全體x10")
    print("    -- 對照口徑 --")
    for k in [10]:
        stat(ev[f"raw{k}"], f"raw{k}(未調整毛報酬)")
        stat(ev[f"tx{k}"], f"tx{k}(減TAIEX,市值加權基準錯配示範)")
    print("    -- 安慰劑對照(同檔,事件前30交易日假錨,x10同口徑;事件-安慰劑=真事件效應) --")
    a = stat(ev.x10, "事件x10")
    b = stat(ev.plc10, "安慰劑x10")
    if a is not None and b is not None:
        print(f"      事件-安慰劑 中位差={a.median() - b.median():+.2f}pp (≈0=skew假象/顯著負=真出貨窗)")
        both = ev.dropna(subset=["x10", "plc10"]).copy()
        both["d_ev"] = both.x10 - both.plc10
        month_boot(both, "d_ev", "事件-安慰劑配對差")

    print("\n== 描述B: 事前run-up D-10→D-1(不可交易,形狀) ==")
    stat(ev.pre10, "pre10")

    print("\n== 分組(x10超額) ==")
    for mask, lab in [(ev.own, "自辦"), (~ev.own, "受邀券商場"),
                      (ev.online, "線上"), (~ev.online, "實體"),
                      (ev.market == "TW", "上市"), (ev.market == "TWO", "上櫃"),
                      (ev.ptile >= 80, "高位階>=80"), (ev.ptile <= 50, "低位階<=50")]:
        stat(ev.loc[mask, "x10"], f"x10 {lab}")
    for a_mask, b_mask, lab in [(ev.own, ~ev.own, "自辦-受邀"),
                                (ev.ptile <= 50, ev.ptile >= 80, "低位階-高位階")]:
        a, b = ev.loc[a_mask, "x10"].dropna(), ev.loc[b_mask, "x10"].dropna()
        if len(a) >= 30 and len(b) >= 30:
            print(f"    [{lab}] 中位差={a.median() - b.median():+.2f}pp")
            month_boot(ev[a_mask], "x10", f"{lab}左組")

    print("\n== 交互: 自辦×低位階(苦主出來講話?) vs 自辦×高位階(得意場) ==")
    for pm, pl in [(ev.ptile <= 50, "低位階"), (ev.ptile >= 80, "高位階")]:
        stat(ev.loc[ev.own & pm, "x10"], f"自辦×{pl} x10")
        stat(ev.loc[~ev.own & pm, "x10"], f"受邀×{pl} x10")


if __name__ == "__main__":
    main()
