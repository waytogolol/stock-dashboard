# -*- coding: utf-8 -*-
import pandas as pd, classify_cn

cn = pd.read_csv("cn_top600.csv", dtype=str)
cn['rank'] = cn['rank'].astype(int)
unmatched = cn[~cn['code'].isin(classify_cn.MAP.keys())].sort_values('rank')

print(f"陸股未分類: {len(unmatched)} / {len(cn)}")

cn_list = "\n".join([f"#{r['rank']} {r['code']} {r['name']}" for _, r in unmatched.iterrows()])

prompt = f"""你是中國A股市場產業分析師。
以下是中國A股上市公司列表（排名|股票代碼|公司名稱），請幫我把每家公司分類到以下格式：

輸出格式（每行一家，絕對不能跳過任何一家）：
股票代碼 | 主族群 | 細分產品/業務 | 產業地位描述（一句話）

主族群參考（可自行增加）：
半導體設備、IC設計、封測(OSAT/測試)、記憶體、材料/化學品、
機器人/自動化、汽車、汽車零件、電池/儲能、電力設備、重工業/造船、
軍工/國防、醫療器材、製藥/生技、食品飲料、零售/電商、金融/銀行、
保險、證券、能源（石油/煤炭）、電信、網路服務/遊戲、建設/不動產、
物流/航空、農業、鋼鐵/有色金屬、化工、傳統製造、其他

規則：
1. 不能猜測、不能亂填，如果真的完全不確定就填「其他 | 其他 | 無法確認」
2. 陸股代碼格式為「數字.SH」或「數字.SZ」，保留原始格式
3. 每行格式嚴格對應：代碼 | 主族群 | 細分產品 | 地位描述

待分類陸股列表：
{cn_list}
"""

with open("tmp_gemini_cn_prompt.txt", "w", encoding="utf-8") as f:
    f.write(prompt)

print("done -> tmp_gemini_cn_prompt.txt")
