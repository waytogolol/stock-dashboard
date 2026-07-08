# -*- coding: utf-8 -*-
"""全題材動能發動訊號掃描：套用記憶體案例研究得出的檢查清單規則
規則(發動確認)：
  1. 連漲>=2週
  2. 廣度>=50% 且連續兩週
  3. >=3國子分數同步上升
  4. 最大單國佔分數 <80%（排除單國獨撐假訊號）
去雜訊：同題材前4週內已有觸發則不重複列
驗證：附觸發後+8週分數倍率與13週內最大倍率
用法: python scan_signals.py
"""
import pandas as pd

from case_study_theme import COUNTRIES, add_signals, load, theme_series

BROAD = {
    "金融", "科技(綜合)", "生技醫藥", "消費(非必需)", "工業", "傳統產業", "傳統消費", "公用事業", "能源",
    "不動產", "電信", "傳統產業/原材料", "電力設備", "控股公司", "航運", "造船", "商社", "商社/建設",
    "汽車", "其他", "未分類", "媒體/娛樂", "遊戲/娛樂", "品牌3C", "IT/系統整合", "網路服務", "人力資源",
    "工業電腦/物聯網", "IC通路", "安防設備",
}


def find_triggers(df):
    out = []
    diffs = {c: df[f"sub_{c}"].diff() for c in COUNTRIES}
    last_trigger = -99
    for i in range(2, len(df)):
        r = df.iloc[i]
        rp = df.iloc[i - 1]
        if r["連漲週"] < 2:
            continue
        if not (pd.notna(r["breadth_up"]) and pd.notna(rp["breadth_up"])
                and r["breadth_up"] >= 50 and rp["breadth_up"] >= 50):
            continue
        rising = sum(1 for c in COUNTRIES if pd.notna(diffs[c].iloc[i]) and diffs[c].iloc[i] > 0)
        if rising < 3:
            continue
        if r["score"] <= 0:
            continue
        max_share = max(r[f"sub_{c}"] for c in COUNTRIES) / r["score"]
        if max_share > 0.8:
            continue
        if i - last_trigger < 4:
            last_trigger = i
            continue
        last_trigger = i
        fwd8 = df["score"].iloc[i + 8] / r["score"] if i + 8 < len(df) else None
        fwd13max = df["score"].iloc[i + 1:i + 14].max() / r["score"] if i + 1 < len(df) else None
        out.append({
            "date": df.index[i], "score": round(r["score"], 2),
            "pos": round(r["位階"] * 100), "breadth": round(r["breadth_up"]),
            "rising": rising,
            "fwd8x": round(fwd8, 2) if fwd8 else None,
            "max13x": round(fwd13max, 2) if fwd13max else None,
        })
    return out


def main():
    rankings, cls = load()
    # 有台股成員的題材
    tw_groups = set(cls[cls["country"] == "台"]["main_group"].unique())
    counts = cls.groupby("main_group")["code"].count()
    themes = sorted(g for g in cls["main_group"].unique()
                    if g in tw_groups and counts.get(g, 0) >= 3 and g not in BROAD)
    print(f"掃描 {len(themes)} 個題材...")

    all_hits = []
    for theme in themes:
        df = add_signals(theme_series(rankings, cls, theme))
        for t in find_triggers(df):
            t["theme"] = theme
            all_hits.append(t)

    all_hits.sort(key=lambda x: x["date"])
    lines = [f"{'日期':<12}{'題材':<14}{'分數':>7}{'位階%':>5}{'廣度%':>5}{'升國':>4}{'+8週倍率':>8}{'13週最大':>8}"]
    for h in all_hits:
        f8 = f"{h['fwd8x']}" if h['fwd8x'] else "-"
        f13 = f"{h['max13x']}" if h['max13x'] else "-"
        lines.append(f"{h['date']:<12}{h['theme']:<14}{h['score']:>7}{h['pos']:>5}{h['breadth']:>5}{h['rising']:>4}{f8:>8}{f13:>8}")
    win = [h for h in all_hits if h["fwd8x"] and h["fwd8x"] > 1]
    total_f8 = [h for h in all_hits if h["fwd8x"]]
    lines.append(f"\n觸發總數: {len(all_hits)}，+8週上漲比例: {len(win)}/{len(total_f8)}")
    with open("tmp_scan_report.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("done -> tmp_scan_report.txt")


if __name__ == "__main__":
    main()
