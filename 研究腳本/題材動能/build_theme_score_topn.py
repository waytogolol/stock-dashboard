# -*- coding: utf-8 -*-
"""⑫延伸:「題材營收訊號只用前N大成員算,效果是否不輸全體加總?」(使用者2026-07-14提案)
動機:顯示層若只需前3/前5大,產業趨勢圖可以畫得乾淨;訊號層也可簡化。
機制預期:營收是重尾分布,加總本來就被前幾大主導→top-N版大概率與全體版高度重合。

設計(預註冊,單一設定不掃參數):
1. 先從fm_month_rev重建全體版score,與tmp_theme_score.pkl比對驗證口徑一致
   (順帶修復「score builder是已刪tmp檔不可覆核」的舊帳,本檔即正式builder)。
2. top-N成員=進場時點已知資訊:該題材內「截至資料月前一月」過去12個月平均營收前N大
   (擴張窗,無look-ahead);MoM/YoY只用這N家的加總算(當月與前月/去年同月都有資料者)。
3. 訊號換成score_topN,交易宇宙不變(v2 panel同一批),比較score=4組:
   訊號重疊率/TWII超額中位/勝率/逐年。判準:top-N不輸全體→顯示與訊號都可簡化。
score口徑(2026-07-14逆向工程還原自tmp_theme_score.pkl,三段驗證各100%一致):
  mom_agg(T)  = 題材成員營收單純加總的MoM% (sum跳過缺值,含成員進出的組成雜訊=原版口徑)
  mom_score(T)= 從最近已公布月(T-1)往回數「連續MoM>0」的月數(巢狀streak,0-3)
  trend_yoy3(T)= yoy_agg(T-1,T-2,T-3)三月平均(shift(1),只用已公布月)
  score = mom_score + (trend_yoy3>0)  → 0-4,全程無look-ahead
用法: python build_theme_score_topn.py
"""
import sqlite3

import numpy as np
import pandas as pd

MIN_MEMBERS = 3  # 題材>=3家FinMind覆蓋(使用者裁示門檻,沿用)


def build_score(rev_wide, label):
    """rev_wide: DataFrame index=月(Timestamp), columns=code, 值=該月營收(可NaN)。
    忠實重現原版口徑:單純加總(skipna),不做成員交集對齊"""
    tot = rev_wide.sum(axis=1, min_count=1)
    mom = tot.pct_change() * 100
    yoy = tot.pct_change(12) * 100
    s1, s2, s3 = mom.shift(1).gt(0), mom.shift(2).gt(0), mom.shift(3).gt(0)
    mom_score = np.where(~s1, 0, np.where(~s2, 1, np.where(~s3, 2, 3)))
    trend_yoy3 = yoy.shift(1).rolling(3).mean()
    sc = mom_score + trend_yoy3.gt(0).astype(int)
    return pd.DataFrame({"mom_agg": mom, "yoy_agg": yoy, f"score_{label}": sc})


def main():
    conn = sqlite3.connect("capital_flow.db")
    rev = pd.read_sql("SELECT code, date, revenue FROM fm_month_rev", conn, dtype={"code": str})
    rev["m"] = pd.to_datetime(rev.date)
    cls = pd.read_sql("SELECT code, main_group industry FROM classification WHERE country='台'",
                      conn, dtype={"code": str}).drop_duplicates()

    ref = pd.read_pickle("tmp_theme_score.pkl")
    themes = sorted(ref.industry.unique())
    print(f"重建score: {len(themes)}個題材(比對基準=tmp_theme_score.pkl)")

    out_full, out_top = [], {3: [], 5: []}
    for ind in themes:
        codes = cls[cls.industry == ind].code.unique()
        g = rev[rev.code.isin(codes)]
        if g.code.nunique() < MIN_MEMBERS:
            continue
        wide = g.pivot_table(index="m", columns="code", values="revenue", aggfunc="first").sort_index()
        full = build_score(wide, "full")
        full["industry"] = ind
        out_full.append(full)
        # top-N: 每個資料月m,用「m之前(不含m)」12個月平均營收排名取前N
        trail = wide.shift(1).rolling(12, min_periods=3).mean()
        for n in (3, 5):
            rev_top = wide.copy()
            for i, m in enumerate(wide.index):
                ranks = trail.iloc[i].dropna().sort_values(ascending=False)
                keep = set(ranks.head(n).index) if len(ranks) else set(wide.columns)
                rev_top.iloc[i, [j for j, c in enumerate(wide.columns) if c not in keep]] = np.nan
            top = build_score(rev_top, f"top{n}")
            top["industry"] = ind
            out_top[n].append(top)

    full = pd.concat(out_full).reset_index().rename(columns={"index": "m"})
    full["year_month"] = full.m.dt.strftime("%Y%m")
    # ---- 驗證:與既有pkl比對 ----
    chk = ref.merge(full, on=["industry", "year_month"], suffixes=("_ref", ""))
    both = chk.dropna(subset=["mom_agg_ref", "mom_agg"])
    mom_match = (both.mom_agg_ref.round(4) == both.mom_agg.round(4)).mean()
    sc_match = (chk.score == chk.score_full).mean()
    print(f"與tmp_theme_score.pkl比對: mom_agg一致率{mom_match * 100:.1f}% "
          f"score一致率{sc_match * 100:.1f}% (n={len(chk)})")

    panel = pd.read_pickle("tmp_theme_momentum_v2_panel.pkl").copy()
    panel["y"] = panel.year_month.str[:4]
    merged = panel.merge(full[["industry", "year_month", "score_full"]],
                         on=["industry", "year_month"], how="left")
    for n in (3, 5):
        t = pd.concat(out_top[n]).reset_index().rename(columns={"index": "m"})
        t["year_month"] = t.m.dt.strftime("%Y%m")
        merged = merged.merge(t[["industry", "year_month", f"score_top{n}"]],
                              on=["industry", "year_month"], how="left")

    print("\n--- score=4 各版本比較(交易層,TWII超額) ---")
    base = merged[merged.score == 4]
    print(f"全體版(基準):    n={len(base)} 中位{base.excess60.median():+.2f}% "
          f"勝率{(base.excess60 > 0).mean() * 100:.0f}% 群數{base.groupby(['industry','year_month']).ngroups}")
    for col, name in [("score_top3", "top3版"), ("score_top5", "top5版")]:
        g = merged[merged[col] == 4]
        gm = g.groupby(["industry", "year_month"]).ngroups
        ov = merged[(merged.score == 4) & (merged[col] == 4)]
        ovg = ov.groupby(["industry", "year_month"]).ngroups
        bg = base.groupby(["industry", "year_month"]).ngroups
        print(f"{name}:          n={len(g)} 中位{g.excess60.median():+.2f}% "
              f"勝率{(g.excess60 > 0).mean() * 100:.0f}% 群數{gm} | 與全體版重疊群{ovg}/{bg}")
        print(f"  逐年超額中位: " + "  ".join(
            f"{y}:{g[g.y == y].excess60.median():+.1f}%(n={len(g[g.y == y])})"
            for y in sorted(g.y.dropna().unique())))
        only_new = merged[(merged[col] == 4) & (merged.score < 4)]
        only_old = merged[(merged.score == 4) & (merged[col] < 4)]
        print(f"  只有{name}觸發: n={len(only_new)} 中位{only_new.excess60.median():+.2f}% | "
              f"只有全體版觸發: n={len(only_old)} 中位{only_old.excess60.median():+.2f}%")

    # 顯示層參考:前N大營收集中度
    conc3, conc5 = [], []
    for ind in themes:
        codes = cls[cls.industry == ind].code.unique()
        g = rev[(rev.code.isin(codes)) & (rev.m == rev.m.max())]
        if len(g) >= MIN_MEMBERS:
            s = g.groupby("code").revenue.sum().sort_values(ascending=False)
            conc3.append(s.head(3).sum() / s.sum())
            conc5.append(s.head(5).sum() / s.sum())
    print(f"\n顯示層參考: 最新月題材營收前3大占比中位{np.median(conc3) * 100:.0f}% / "
          f"前5大占比中位{np.median(conc5) * 100:.0f}%")

    full.to_pickle("tmp_theme_score_rebuilt.pkl")
    print("已存 tmp_theme_score_rebuilt.pkl (正式重建版全體score,含mom/yoy序列)")


if __name__ == "__main__":
    main()
