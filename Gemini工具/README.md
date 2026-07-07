# Gemini 工具腳本

分類與供應鏈資料的維護流程：腳本生成指令 → 貼給 Gemini → 結果貼回 → 驗證後寫入資料檔。
所有腳本**從專案根目錄執行**（`python Gemini工具/xxx.py`），輸出檔會產生在根目錄。

## 腳本一覽

| 腳本 | 用途 | 何時用 |
|------|------|--------|
| `gen_sc_prompt.py` | 生成「錨點客戶供應鏈」指令（NVDA/AAPL/TSLA等） | 每季審查 `supply_chain.py` |
| `gen_chain_prompt.py` | 生成「橫向產業鏈上中下游」指令（功率半導體/被動元件/CPO等） | 每季審查 `industry_chains.py`，或新增產業鏈時改 CHAINS 關鍵字 |
| `parse_chain_result.py` | 解析產業鏈 Gemini 結果，逐筆核對資料庫代碼後生成 `industry_chains.py` | 拿到 Gemini 產業鏈結果後 |
| `gen_jp_kr_prompt.py` | 生成日股/韓股未分類個股的分類指令 | 每週 refresh 後有新進榜未分類時 |
| `gen_cn_prompt.py` | 生成陸股未分類個股的分類指令 | 同上 |

## 原則

1. **不能猜，要真實**——Gemini 結果必須經代碼核對（不在資料庫的直接剔除）才能寫入資料檔
2. 指令與結果的歷史存檔在 `Gemini紀錄/`（不進 git）
3. 供應鏈資料檔有 `LAST_UPDATED` 時間戳，dashboard 超過 90 天會顯示過期警告
