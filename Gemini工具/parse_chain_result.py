# -*- coding: utf-8 -*-
"""解析Gemini產業鏈結果 -> 驗證代碼存在於資料庫 -> 生成 industry_chains.py"""
import pandas as pd

df = pd.read_csv("all_classified.csv", dtype={"代碼": str})
valid = set(zip(df["國家"], df["代碼"]))

rows, bad = [], []
for ln in open("tmp_chain_gemini_result.txt", encoding="utf-8"):
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
seen, uniq = set(), []
for r in rows:
    k = (r[0], r[2], r[3])
    if k in seen:
        bad.append(("重複", " | ".join(r))); continue
    seen.add(k); uniq.append(r)

chains_order = []
for r in uniq:
    if r[0] not in chains_order:
        chains_order.append(r[0])

stage_order = {"上游": 0, "中游": 1, "下游": 2}
uniq.sort(key=lambda r: (chains_order.index(r[0]), stage_order[r[1]]))

with open("industry_chains.py", "w", encoding="utf-8") as f:
    f.write('# -*- coding: utf-8 -*-\n')
    f.write('"""橫向產業鏈上中下游結構表\n')
    f.write('由 Gemini 整理、tmp_parse_chain.py 驗證每筆代碼存在於資料庫後生成\n')
    f.write('格式：(產業鏈, 階段, 代碼, 國別, 具體角色)\n"""\n\n')
    f.write('LAST_UPDATED = "2026-07-07"\n\n')
    f.write(f'CHAINS = {chains_order!r}\n\n')
    f.write('CHAIN_LINKS = [\n')
    cur = None
    for chain, stage, code, country, role in uniq:
        if chain != cur:
            f.write(f'\n    # ── {chain} ──\n')
            cur = chain
        f.write(f'    ({chain!r}, {stage!r}, {code!r}, {country!r}, {role!r}),\n')
    f.write(']\n')

with open("tmp_chain_parse_report.txt", "w", encoding="utf-8") as f:
    f.write(f"有效: {len(uniq)} 筆\n")
    from collections import Counter
    cnt = Counter((r[0], r[1]) for r in uniq)
    for c in chains_order:
        parts = [f"{s}{cnt.get((c, s), 0)}" for s in ("上游", "中游", "下游")]
        total = sum(cnt.get((c, s), 0) for s in ("上游", "中游", "下游"))
        f.write(f"  {c}: {total}家 ({' / '.join(parts)})\n")
    f.write(f"\n剔除: {len(bad)} 筆\n")
    for reason, ln in bad:
        f.write(f"  [{reason}] {ln}\n")
print("done")
