<#
.SYNOPSIS
    Weister 质量门禁：ruff + pytest + 前端 tsc
#>
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$be = Join-Path $root "backend"
$fe = Join-Path $root "frontend"

Write-Host "[1/3] ruff" -ForegroundColor Cyan
Push-Location $be
& ".\.venv\Scripts\python.exe" -m ruff check app tests
if ($LASTEXITCODE -ne 0) { Pop-Location; exit 1 }
& ".\.venv\Scripts\python.exe" -m ruff format --check app
if ($LASTEXITCODE -ne 0) { Pop-Location; exit 1 }

Write-Host "[2/3] pytest" -ForegroundColor Cyan
& ".\.venv\Scripts\python.exe" -m pytest -q
if ($LASTEXITCODE -ne 0) { Pop-Location; exit 1 }
Pop-Location

Write-Host "[3/3] tsc --noEmit" -ForegroundColor Cyan
Push-Location $fe
& node ".\node_modules\typescript\bin\tsc" --noEmit
if ($LASTEXITCODE -ne 0) { Pop-Location; exit 1 }
Pop-Location

Write-Host "ALL PASS" -ForegroundColor Green
