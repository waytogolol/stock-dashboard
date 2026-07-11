# -*- coding: utf-8 -*-
"""dashboard.html 自動體檢（每週 export 後、push 前執行）
①DATA必要鍵存在且非空 ②交叉引用完整(top3/補漲/徽章→company_history等)
③JS語法(esprima) ④onclick函式皆有定義 ⑤getElementById的id皆存在
用法: python check_dashboard.py   (exit 0=PASS)
"""
import json
import re
import sys

import esprima

FAIL = []
WARN = []

html = open("dashboard.html", encoding="utf-8").read()
m = re.search(r"(?:const|var|let)\s+DATA\s*=\s*(\{.*?\});?\s*\n", html)
data = json.loads(m.group(1))
scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
js = "\n".join(scripts)

# ① 必要鍵
REQUIRED = ["snapshot_dates", "theme_history", "theme_pivot_all", "signal_current",
            "micro_current", "catchup_radar", "chip", "company_history", "market_tier",
            "health", "latest_date", "industry_chains"]
for k in REQUIRED:
    v = data.get(k)
    if v is None or (hasattr(v, "__len__") and len(v) == 0):
        FAIL.append(f"DATA.{k} 缺失或為空")

# ② 交叉引用
ch = data.get("company_history", {})
for c in data.get("signal_current", []):
    if c["theme"] not in data.get("theme_history", {}):
        WARN.append(f"訊號題材 {c['theme']} 不在 theme_history")
    for code, _name in c.get("top3", []):
        if f"台|{code}" not in ch:
            FAIL.append(f"top3 {c['theme']}/{code} 不在 company_history")
for r in data.get("catchup_radar", {}).get("rows", []):
    if f"台|{r['code']}" not in ch:
        WARN.append(f"補漲雷達 {r['code']} 不在 company_history")
for code, rec in list(data.get("chip", {}).items())[:100000]:
    for k2, v2 in rec.items():
        if not (0 <= v2 <= 100):
            FAIL.append(f"chip {code}.{k2}={v2} 超出0-100")
            break
sd = data.get("snapshot_dates", [])
if sd and data.get("latest_date") != sd[-1]:
    FAIL.append(f"latest_date({data.get('latest_date')}) != snapshot_dates末位({sd[-1]})")

# ③ JS 語法
try:
    js_clean = re.sub(r"^(\s*(?:const|var|let)\s+DATA\s*=\s*).*$", r"\1{};", js, count=1, flags=re.M)
    esprima.parseScript(js_clean)
except Exception as e:
    FAIL.append(f"esprima 解析失敗: {e}")

# ④ onclick 函式定義
defined = set(re.findall(r"function\s+(\w+)\s*\(", js))
called = set(re.findall(r'onclick=\\?"(\w+)\(', html))
for f in sorted(called - defined):
    FAIL.append(f"onclick 呼叫未定義函式: {f}")

# ⑤ getElementById 的 id 存在
ids_used = set(re.findall(r'getElementById\("([\w-]+)"\)', js))
ids_defined = set(re.findall(r'id="([\w-]+)"', html)) | set(re.findall(r'id=\\"([\w-]+)\\"', js))
DYNAMIC_OK = set()   # 動態生成的id白名單(確認後加入)
for i in sorted(ids_used - ids_defined - DYNAMIC_OK):
    WARN.append(f"getElementById('{i}') 找不到靜態 id (若為動態生成可加白名單)")

# ⑥ 檔案大小監控(payload有104週上限,仍持續監控防新資料源失控)
import os
mb = os.path.getsize("dashboard.html") / 1e6
sizes = sorted(((k, len(json.dumps(v, ensure_ascii=False))) for k, v in data.items()), key=lambda x: -x[1])
print(f"檔案 {mb:.1f} MB | DATA前3大: " + ", ".join(f"{k}={s/1e6:.1f}MB" for k, s in sizes[:3]))
if mb > 15:
    FAIL.append(f"dashboard.html {mb:.1f}MB 超過15MB硬上限")
elif mb > 10:
    WARN.append(f"dashboard.html {mb:.1f}MB 超過10MB(檢視新增資料源)")

print(f"=== dashboard 體檢: FAIL={len(FAIL)} WARN={len(WARN)} ===")
for x in FAIL:
    print("  [FAIL]", x)
for x in WARN[:20]:
    print("  [WARN]", x)
if len(WARN) > 20:
    print(f"  ...另有 {len(WARN)-20} 個 WARN")
sys.exit(1 if FAIL else 0)
