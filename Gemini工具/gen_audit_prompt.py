# -*- coding: utf-8 -*-
"""分類標記稽核 Gemini 指令生成器
起因：2026-07-13 使用者發現 3532(台勝科) 被誤標成「特殊氣體/半導體製程氣體廠」，實際是矽晶圓大廠——
      疑似Gemini批次分類時複製貼上到別家公司的描述。既有的重複文字偵測法誤判率太高(見研究討論)，
      改用「反向請Gemini逐筆核對」——跟 Gemini工具/gen_chain_prompt.py 生成產業鏈時同一套紀律：
      不確定就跳過、不能猜；這裡反過來只要求它「找出有把握是錯的」，藉此把輸出壓到最短，省token。

用法：從專案根目錄執行 python Gemini工具/gen_audit_prompt.py [--batch-size 300]
輸出：tmp_gemini_audit_prompt_batch{i}.txt，依序貼給Gemini；結果貼回單一檔案後，
      比照 parse_chain_result.py 的模式手動核對再寫回 classify_tw.py / classify_jp.py 等對應MAP
      (不是直接改DB或CSV——那些是衍生檔，下次weekly_refresh會被覆蓋，教訓見3532案例)。
"""
import argparse
import os
import sys

import pandas as pd

sys.path.insert(0, os.getcwd())

HEADER = """你是全球股市產業分析師，任務是「抓錯」不是「重新分類」。

以下是我資料庫裡每家公司的既有分類標記（格式：國別 代碼 公司名｜主族群/細分產品/產業地位）。
這些標記是先前用AI批次生成的，可能存在少數錯誤（例如複製貼上到別家公司的描述、業務內容過時、
細分產品跟公司實際主力產品對不上等）。

任務：逐筆核對「產業地位」與「細分產品」欄位是否符合這家公司真實的主力業務。
只挑出你有把握判斷錯誤的，不要重新評論每一筆、不要調整你覺得只是「可以更精確」但並非錯誤的項目。
不確定的一律跳過，不能用猜的——這比多抓少抓更重要，因為誤報會浪費使用者逐筆人工核對的時間。

輸出格式（只列有問題的，一行一筆；如果這批全部正確，就回覆「本批無問題」）：
代碼 | 問題說明(一句話) | 建議正確的：主族群/細分產品/產業地位

範例：
3532 | 台勝科是矽晶圓大廠，不是氣體廠，這段描述像是誤植了別家公司的資料 | 半導體材料/矽晶圓/材料/矽晶圓大廠

---
"""

BATCH_DEFAULT = 300


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch-size", type=int, default=BATCH_DEFAULT)
    args = ap.parse_args()

    df = pd.read_csv("all_classified.csv", dtype={"代碼": str})
    df = df.sort_values(["國家", "排名"])
    print(f"待稽核共 {len(df)} 筆標記")

    lines = [f"{r['國家']} {r['代碼']} {r['公司']}｜{r['主族群']}/{r['細分產品']}/{r['產業地位']}"
              for _, r in df.iterrows()]

    n_batches = (len(lines) + args.batch_size - 1) // args.batch_size
    for i in range(n_batches):
        chunk = lines[i * args.batch_size:(i + 1) * args.batch_size]
        fname = f"tmp_gemini_audit_prompt_batch{i+1}.txt"
        with open(fname, "w", encoding="utf-8") as f:
            f.write(HEADER + "\n".join(chunk) + "\n")
        print(f"-> {fname} ({len(chunk)}筆)")

    print(f"\n共 {n_batches} 個指令檔，請依序貼給 Gemini。"
          f"每批預期回應應該很短(只列疑點)；全部結果貼給我(或存成一個檔告知檔名)後，"
          f"我會逐筆核對再決定要不要改 classify_*.py 對應的MAP(不直接改衍生的CSV/DB，"
          f"避免下次weekly_refresh時被覆蓋回錯誤版本)。")


if __name__ == "__main__":
    main()
