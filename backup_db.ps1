# backup_db.ps1 — capital_flow.db 滾動備份到私有repo stock-db-backup
# 單版本策略: commit --amend + push --force, 遠端永遠只保留最新一版(~58MB不膨脹)
# 用法: 每週更新流程最後執行  powershell -File backup_db.ps1
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Push-Location $root
python make_backup.py    # 精簡備份: 只留不可重建小表(大表歸冷備zip), 守住GitHub 100MB限制
if ($LASTEXITCODE -ne 0) { Pop-Location; throw "make_backup.py 失敗 (exit $LASTEXITCODE) — 備份中止!" }
Pop-Location
Push-Location (Join-Path $root "db_backup")
try {
    git add capital_flow.db
    git commit --amend -m "backup $(Get-Date -Format yyyy-MM-dd)" | Out-Null
    git push --force origin master
    if ($LASTEXITCODE -ne 0) { throw "git push 被拒 (exit $LASTEXITCODE) — 備份未上傳, 遠端仍是舊版!" }
    Write-Output "備份完成 -> github.com/waytogolol/stock-db-backup ($(Get-Date -Format yyyy-MM-dd))"
} finally {
    Pop-Location
}
