# -*- coding: utf-8 -*-
"""解析Gemini產業鏈結果 -> 驗證代碼存在於資料庫 -> 合併寫入 industry_chains.py

- 合併邏輯：新結果中出現的產業鏈整條取代舊資料；未出現的鏈保留不動
- 從專案根目錄執行：python Gemini工具/parse_chain_result.py [結果檔，預設tmp_chain_gemini_result.txt]
"""
import os
import sys
from collections import Counter
from datetime import date

import pandas as pd

sys.path.insert(0, os.getcwd())

INPUT = sys.argv[1] if len(sys.argv) > 1 else "tmp_chain_gemini_result.txt"

df = pd.read_csv("all_classified.csv", dtype={"代碼": str})
valid = set(zip(df["國家"], df["代碼"]))

rows, bad = [], []
for ln in open(INPUT, encoding="utf-8"):
    ln = ln.strip()
    if not ln or "|" not in ln:
        continue
    parts = [p.strip() for p in ln.split("|")]
    if len(parts) != 5:
        bad.append(("欄位數錯誤", ln)); continue
    chain, stage, code, country, role = parts
    if stage not in ("上游", "中游", "下游"):
        bad.append(("階段無效", ln)); continue
    if (country, code) not in valid:
        bad.append(("代碼不在資料庫", ln)); continue
    rows.append((chain, stage, code, country, role))

# 去重（同鏈同公司只留第一筆）
seen, new_rows = set(), []
for r in rows:
    k = (r[0], r[2], r[3])
    if k in seen:
        bad.append(("重複", " | ".join(r))); continue
    seen.add(k); new_rows.append(r)

new_chains = []
for r in new_rows:
    if r[0] not in new_chains:
        new_chains.append(r[0])

# 合併既有資料：新結果出現的鏈整條取代，其他保留
old_rows, old_chains = [], []
try:
    import industry_chains as ic
    old_chains = [c for c in ic.CHAINS if c not in new_chains]
    old_rows = [r for r in ic.CHAIN_LINKS if r[0] not in new_chains]
    print(f"保留既有 {len(old_chains)} 條鏈({len(old_rows)}筆)，本次新增/取代 {len(new_chains)} 條鏈({len(new_rows)}筆)")
except Exception:
    print("找不到既有 industry_chains.py，全新建立")

chains_order = old_chains + new_chains
all_rows = old_rows + new_rows
stage_order = {"上游": 0, "中游": 1, "下游": 2}
all_rows.sort(key=lambda r: (chains_order.index(r[0]), stage_order[r[1]]))

with open("industry_chains.py", "w", encoding="utf-8") as f:
    f.write('# -*- coding: utf-8 -*-\n')
    f.write('"""橫向產業鏈上中下游結構表\n')
    f.write('由 Gemini 整理、Gemini工具/parse_chain_result.py 驗證每筆代碼存在於資料庫後生成\n')
    f.write('格式：(產業鏈, 階段, 代碼, 國別, 具體角色)\n"""\n\n')
    f.write(f'LAST_UPDATED = "{date.today()}"\n\n')
    f.write(f'CHAINS = {chains_order!r}\n\n')
    f.write('CHAIN_LINKS = [\n')
    cur = None
    for chain, stage, code, country, role in all_rows:
        if chain != cur:
            f.write(f'\n    # ── {chain} ──\n')
            cur = chain
        f.write(f'    ({chain!r}, {stage!r}, {code!r}, {country!r}, {role!r}),\n')
    f.write(']\n')

with open("tmp_chain_parse_report.txt", "w", encoding="utf-8") as f:
    f.write(f"合併後總計: {len(all_rows)} 筆 / {len(chains_order)} 條鏈\n")
    cnt = Counter((r[0], r[1]) for r in all_rows)
    for c in chains_order:
        parts = [f"{s}{cnt.get((c, s), 0)}" for s in ("上游", "中游", "下游")]
        total = sum(cnt.get((c, s), 0) for s in ("上游", "中游", "下游"))
        f.write(f"  {c}: {total}家 ({' / '.join(parts)})\n")
    f.write(f"\n剔除: {len(bad)} 筆\n")
    for reason, ln in bad:
        f.write(f"  [{reason}] {ln}\n")
print("done -> industry_chains.py, tmp_chain_parse_report.txt")
