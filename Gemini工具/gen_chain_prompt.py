# -*- coding: utf-8 -*-
"""產業鏈(橫向)Gemini指令生成器 v2：修正關鍵字誤抓，生成可直接貼給Gemini的完整指令"""
import pandas as pd

df = pd.read_csv("all_classified.csv", dtype={"代碼": str})
df["搜尋文字"] = (df["主族群"].fillna("") + "|" + df["細分產品"].fillna("") + "|" + df["產業地位"].fillna(""))

# kws: 不分大小寫關鍵字；cs_kws: 區分大小寫(避免 SiC 誤抓 ASIC/ASICS、VC 誤抓 VCSEL)
CHAINS = {
    "功率半導體": {
        "kws": ["功率", "MOSFET", "IGBT", "碳化矽", "氮化鎵", "二極體", "整流", "閘流", "PMIC", "電源管理"],
        "cs_kws": ["SiC", "GaN"],
        "stage_hint": "上游=SiC/GaN基板、磊晶、材料；中游=IDM/晶圓代工/元件設計製造/封測；下游=電源模組、車用/工業電源應用",
    },
    "被動元件": {
        "kws": ["被動元件", "MLCC", "電容", "電感", "電阻", "石英元件", "晶振", "振盪器", "保護元件", "鋁質電解", "陶瓷粉", "陶瓷材料", "載帶", "磁性材料", "鋁箔"],
        "cs_kws": [],
        "stage_hint": "上游=陶瓷粉末、電極材料、鋁箔、載帶、設備；中游=MLCC/電感/電阻/電容製造；下游=模組與通路",
    },
    "CPO/光通訊": {
        "kws": ["光通訊", "光收發", "矽光子", "光纖", "光晶片", "雷射二極體", "雷射磊晶", "雷射光源", "800G", "光引擎", "AWG", "光被動", "光主動", "交換晶片", "交換器"],
        "cs_kws": ["CPO", "AEC", "SerDes"],
        "stage_hint": "上游=雷射晶片/磊晶、光學元件、特種光纖材料；中游=光收發模組、CPO封裝、AEC線纜；下游=交換器/網通系統、雲端資料中心設備",
    },
    "散熱/液冷": {
        "kws": ["散熱", "液冷", "均熱", "熱管理", "風扇", "水冷", "CDU", "溫控", "導熱"],
        "cs_kws": [],
        "stage_hint": "上游=導熱材料、風扇馬達驅動IC、精密零件；中游=散熱模組/VC均熱片/水冷板製造；下游=CDU機櫃系統、資料中心溫控整合",
    },
    "PCB/載板/CCL": {
        "kws": ["PCB", "印刷電路", "載板", "CCL", "銅箔基板", "電解銅箔", "玻纖", "玻璃纖維", "HDI", "軟板", "覆銅板", "鑽頭", "鑽針", "壓合"],
        "cs_kws": ["ABF"],
        "stage_hint": "上游=電解銅箔、玻纖布、樹脂、CCL覆銅板、鑽針/設備/化學品；中游=PCB/HDI/軟板/IC載板製造；下游=(併入伺服器/手機等應用，不必列)",
    },
}

def match(text, kws, cs_kws):
    low = text.lower()
    return any(k.lower() in low for k in kws) or any(k in text for k in cs_kws)

blocks = []
for chain, cfg in CHAINS.items():
    mask = df["搜尋文字"].apply(lambda t: match(t, cfg["kws"], cfg["cs_kws"]))
    sub = df[mask].drop_duplicates(subset=["國家", "代碼"]).sort_values(["國家", "排名"])
    print(f"{chain}: {len(sub)}家", dict(sub['國家'].value_counts()))
    lines = "\n".join(f"{r['國家']} {r['代碼']} {r['公司']}｜{r['細分產品']}" for _, r in sub.iterrows())
    blocks.append(f"■ 產業鏈「{chain}」候選名單（{len(sub)}家）\n階段定義提示：{cfg['stage_hint']}\n{lines}")

prompt = f"""你是全球電子產業鏈分析師。
我要建立五個「橫向產業鏈」的上中下游結構圖，涵蓋台/日/韓/陸/美五個市場。
以下每條產業鏈都附上我資料庫的候選公司名單（國別 代碼 公司名｜細分產品）。
候選名單是用關鍵字粗篩的，可能混入不屬於該鏈的公司。

任務：針對每條產業鏈，把「真正屬於該鏈」的公司分配到上游/中游/下游階段，並寫出它在鏈中的具體角色。

規則（非常重要）：
1. 只能從候選名單中挑選，不能自行新增公司
2. 不屬於該產業鏈的候選公司直接略過，不要硬塞
3. 角色描述要具體（例如「SiC 6吋基板」而不是「半導體材料」）
4. 不確定的直接略過，不能猜
5. 同一家公司可以出現在多條產業鏈（例如台積電同時在CPO鏈）

輸出格式（每行一筆）：
產業鏈 | 階段(上游/中游/下游) | 代碼 | 國別 | 具體角色（一句話）

範例：
功率半導體 | 上游 | sh688234 | 陸 | 全球前三大SiC碳化矽基板供應商
功率半導體 | 中游 | 6963 | 日 | SiC功率元件與車用IGBT大廠(ROHM)
CPO/光通訊 | 中游 | sz300308 | 陸 | 全球800G光收發模組出貨龍頭(旭創)

---
{chr(10).join(blocks)}
"""

with open("tmp_gemini_chain_prompt.txt", "w", encoding="utf-8") as f:
    f.write(prompt)
print("\n完整指令已存 tmp_gemini_chain_prompt.txt")
