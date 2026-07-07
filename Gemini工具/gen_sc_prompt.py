# -*- coding: utf-8 -*-
"""生成供應鏈 Gemini 指令 — 以錨點客戶為核心，逐一問各市場供應商"""
import pandas as pd

tw = pd.read_csv("tw_top300.csv", dtype=str)[['rank','code','name']].head(150)
jp = pd.read_csv("jp_top500.csv", dtype=str)[['rank','code','name']].head(150)
kr = pd.read_csv("kr_top400.csv", dtype=str)[['rank','code','name']].head(150)
cn = pd.read_csv("cn_top600.csv", dtype=str)[['rank','code','name']].head(150)
us = pd.read_csv("us_top700.csv", dtype=str)[['rank','code','name']].head(150)

def fmt(df, country):
    return ", ".join([f"{r['code']}({r['name']})" for _, r in df.iterrows()])

tw_list = fmt(tw, "台")
jp_list = fmt(jp, "日")
kr_list = fmt(kr, "韓")
cn_list = fmt(cn, "陸")
us_list = fmt(us, "美")

prompt = f"""你是全球科技與半導體產業供應鏈分析師。
以下是我資料庫中各國前150名上市公司（代碼+名稱），請根據公開資料與產業知識，找出跨國直接供應鏈關係。

【台股前150名】
{tw_list}

【日股前150名】
{jp_list}

【韓股前150名】
{kr_list}

【陸股前150名】
{cn_list}

【美股前150名】
{us_list}

---
任務：針對下方每個「錨點客戶」，從上方清單中找出已知的直接一階供應商。

規則（非常重要）：
1. 只列有公開採購關係、供應商名單、財報揭露等確實資料的關係
2. 不確定、聽說、可能的關係一律不列
3. 代碼必須完全對應上方清單，不得自行編造
4. 同一條關係只列一次

輸出格式（每行一條，共輸出所有錨點的結果）：
供應商代碼 → 客戶代碼 | 供應品項（精簡一句話）

範例：
2330 → NVDA | CoWoS先進封裝代工（AI GPU用）
8035 → 2330 | 晶圓蝕刻設備（Etch）
000660 → NVDA | HBM3高頻寬記憶體

---
請分別列出以下錨點客戶的供應商（從上方清單中找）：

【A. AI算力 — NVDA（NVIDIA）】
供應什麼？CoWoS封裝、先進製程代工、HBM記憶體、基板、散熱、連接器、電源、伺服器組裝、網通設備等

【B. AI算力 — 伺服器三巨頭 MSFT/GOOGL/AMZN（微軟/Google/亞馬遜AWS）】
供應什麼？伺服器機殼、電源、散熱、交換器、儲存、記憶體模組等

【C. 消費電子 — AAPL（蘋果）】
供應什麼？晶圓代工、OLED面板、相機模組、電池、連接器、機殼、印刷電路板、觸控、揚聲器等

【D. 電動車/AI — TSLA（特斯拉）】
供應什麼？動力電池、電池材料、熱管理、精密結構件、車用玻璃、驅動晶片、充電樁零件等

【E. 半導體製程 — 2330（台積電）的設備與材料供應商】
供應什麼？蝕刻/CVD/ALD/CMP/量測設備、光罩、光刻膠、矽晶圓、特殊氣體、研磨液等

【F. 汽車 — 現代起亞（005380/000270）的核心零件供應商】
供應什麼？ADAS晶片、電池、模組、底盤零件、車用半導體等

【G. 記憶體生態 — 000660（SK海力士）/005930（三星）的上游供應商】
供應什麼？矽晶圓、製程設備、CMP液、特殊氣體、先進封裝材料等

【H. 中國AI/算力 — 阿里/騰訊/華為生態（若清單中有相關上游廠）】
供應什麼？伺服器零件、網通設備、算力晶片周邊、散熱等

請依 A ~ H 分段輸出，每段標出錨點名稱。
"""

with open("tmp_gemini_sc_prompt.txt", "w", encoding="utf-8") as f:
    f.write(prompt)

# 也生成 supply_chain.py 空框架
skeleton = '''# -*- coding: utf-8 -*-
"""
跨國供應鏈關係表
格式：(供應商代碼, 供應商國別, 客戶代碼, 客戶國別, 供應品項)
國別代碼：台 / 日 / 韓 / 陸 / 美
"""

LINKS = [
    # ── A. AI算力 NVIDIA 供應鏈 ──────────────────────────────────────
    # ("2330", "台", "NVDA", "美", "CoWoS先進封裝代工（AI GPU用）"),

    # ── B. 伺服器雲端三巨頭（MSFT/GOOGL/AMZN）────────────────────────

    # ── C. 蘋果（AAPL）供應鏈 ────────────────────────────────────────

    # ── D. 特斯拉（TSLA）供應鏈 ──────────────────────────────────────

    # ── E. 台積電（2330）設備/材料供應商 ──────────────────────────────

    # ── F. 現代起亞汽車供應鏈 ────────────────────────────────────────

    # ── G. 三星/SK海力士記憶體上游 ───────────────────────────────────

    # ── H. 中國算力/AI生態 ───────────────────────────────────────────
]

# ── 快速查詢輔助 ──────────────────────────────────────────────────────
def get_customers(code):
    """給代碼，回傳所有下游客戶"""
    return [(c, cn, prod) for sup, _, c, cn, prod in LINKS if sup == code]

def get_suppliers(code):
    """給代碼，回傳所有上游供應商"""
    return [(sup, sn, prod) for sup, sn, c, _, prod in LINKS if c == code]

def get_chain_by_country(supplier_country=None, customer_country=None):
    """篩選特定方向的跨國關係"""
    result = LINKS
    if supplier_country:
        result = [l for l in result if l[1] == supplier_country]
    if customer_country:
        result = [l for l in result if l[3] == customer_country]
    return result
'''

with open("supply_chain.py", "w", encoding="utf-8") as f:
    f.write(skeleton)

print("done -> tmp_gemini_sc_prompt.txt, supply_chain.py")
