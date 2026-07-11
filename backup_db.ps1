# backup_db.ps1 — capital_flow.db 滾動備份到私有repo stock-db-backup
# 單版本策略: commit --amend + push --force, 遠端永遠只保留最新一版(~58MB不膨脹)
# 用法: 每週更新流程最後執行  powershell -File backup_db.ps1
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Copy-Item (Join-Path $root "capital_flow.db") (Join-Path $root "db_backup\capital_flow.db") -Force
Push-Location (Join-Path $root "db_backup")
try {
    git add capital_flow.db
    git commit --amend -m "backup $(Get-Date -Format yyyy-MM-dd)" | Out-Null
    git push --force origin master
    Write-Output "備份完成 -> github.com/waytogolol/stock-db-backup ($(Get-Date -Format yyyy-MM-dd))"
} finally {
    Pop-Location
}
