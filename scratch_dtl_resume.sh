#!/bin/bash
# 單流紳士模式補洞:兩輪全年份pass(斷點續跑自動跳過已完成天),403退避由python層處理
cd "/c/Users/User/Desktop/股市AI"
# 冷卻已不需要(07-30已解封)
for pass in 1 2; do
  for y in 2014 2015 2016 2017 2018 2019 2020 2021 2022 2023 2024; do
    python scratch_pull_dt_lend.py --range $y-01-01 $y-12-31 --out tmp_dtlend_h$y.pkl >> scratch_dtlh_resume.log 2>&1
  done
  python scratch_pull_dt_lend.py --range 2025-01-01 2025-07-27 --out tmp_dtlend_h2025.pkl >> scratch_dtlh_resume.log 2>&1
  echo "PASS${pass}_DONE" >> scratch_dtlh_resume.log
done
echo "ALL_RESUME_DONE" >> scratch_dtlh_resume.log
