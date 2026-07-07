# -*- coding: utf-8 -*-
import pandas as pd, classify_jp, classify_kr

# 日股
jp_csv = pd.read_csv("jp_top500.csv", dtype=str)
jp_csv = jp_csv[['rank','code','name']].copy()
jp_csv['rank'] = jp_csv['rank'].astype(int)
jp_unmatched = jp_csv[~jp_csv['code'].isin(classify_jp.MAP.keys())].sort_values('rank')

# 韓股
kr_csv = pd.read_csv("kr_top400.csv", dtype=str)
kr_csv = kr_csv[['rank','code','name']].copy()
kr_csv['rank'] = kr_csv['rank'].astype(int)
kr_unmatched = kr_csv[~kr_csv['code'].isin(classify_kr.MAP.keys())].sort_values('rank')

print(f"日股未分類: {len(jp_unmatched)} / {len(jp_csv)}")
print(f"韓股未分類: {len(kr_unmatched)} / {len(kr_csv)}")

# 寫出日股未分類
with open("tmp_jp_unmatched_named.txt", "w", encoding="utf-8") as f:
    for _, r in jp_unmatched.iterrows():
        f.write(f"#{r['rank']}|{r['code']}|{r['name']}\n")

# 寫出韓股未分類
with open("tmp_kr_unmatched_named.txt", "w", encoding="utf-8") as f:
    for _, r in kr_unmatched.iterrows():
        f.write(f"#{r['rank']}|{r['code']}|{r['name']}\n")

# 寫出 Gemini 指令 (日股)
jp_list = "\n".join([f"#{r['rank']} {r['code']} {r['name']}" for _,r in jp_unmatched.iterrows()])
kr_list = "\n".join([f"#{r['rank']} {r['code']} {r['name']}" for _,r in kr_unmatched.iterrows()])

jp_prompt = f"""你是日本股市產業分析師。
以下是日本上市公司列表（排名|股票代碼|公司名稱），請幫我把每家公司分類到以下格式：

輸出格式（每行一家，絕對不能跳過任何一家）：
股票代碼 | 主族群 | 細分產品/業務 | 產業地位描述（一句話）

主族群參考（可自行增加）：
半導體設備、IC設計、封測(OSAT/測試)、記憶體、被動元件、材料/化學品、
機器人/自動化、汽車、汽車零件、電池/儲能、電力設備、重工業/造船、
精密儀器、醫療器材、製藥、食品飲料、零售/百貨、金融/保險、電信、
網路服務、遊戲/娛樂、建設/不動產、物流/倉儲、航空、能源、其他

規則：
1. 不能猜測、不能亂填，如果真的完全不確定就填「其他 | 其他 | 無法確認」
2. 日本代碼是4位數字，不要加任何前後綴
3. 每行格式嚴格對應：代碼 | 主族群 | 細分產品 | 地位

待分類日股列表：
{jp_list}
"""

kr_prompt = f"""你是韓國股市產業分析師。
以下是韓國上市公司列表（排名|股票代碼|公司名稱），請幫我把每家公司分類到以下格式：

輸出格式（每行一家，絕對不能跳過任何一家）：
股票代碼 | 主族群 | 細分產品/業務 | 產業地位描述（一句話）

主族群參考（可自行增加）：
記憶體、半導體設備、封測(OSAT/測試)、IC設計、電池/儲能、
汽車、汽車零件、造船、電力設備、重工業、化學品、材料、
顯示器/面板、相機模組、醫療器材、製藥、食品飲料、金融/保險、
電信、網路服務、遊戲/娛樂、物流、航空、建設/不動產、能源、其他、控股公司

規則：
1. 不能猜測、不能亂填，如果真的完全不確定就填「其他 | 其他 | 無法確認」
2. 韓國代碼是6位數字，保留原格式（如000660、0126Z0）
3. 每行格式嚴格對應：代碼 | 主族群 | 細分產品 | 地位

待分類韓股列表：
{kr_list}
"""

with open("tmp_gemini_jp_prompt.txt", "w", encoding="utf-8") as f:
    f.write(jp_prompt)

with open("tmp_gemini_kr_prompt.txt", "w", encoding="utf-8") as f:
    f.write(kr_prompt)

print("done -> tmp_gemini_jp_prompt.txt, tmp_gemini_kr_prompt.txt")
