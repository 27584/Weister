<#
.SYNOPSIS
    Weister · 一键启动脚本

.DESCRIPTION
    启动前后端开发服务，自动完成端口清理、依赖检查、环境准备与健康检查。

.PARAMETER Stop
    停止已运行的服务（释放 8000 与 3000 端口）。

.PARAMETER Reload
    后端以热重载模式启动，修改 Python 代码后自动重启。

.EXAMPLE
    .\dev.ps1
    启动前后端服务。

.EXAMPLE
    .\dev.ps1 -Reload
    以热重载模式启动后端。

.EXAMPLE
    .\dev.ps1 -Stop
    停止所有服务。

.NOTES
    前置要求：
      - Node.js >= 20
      - pnpm >= 9
      - uv（Python 包管理器）

    编码要求：
      - 本文件必须以 UTF-8 with BOM 保存。Windows PowerShell 5.1 会把无 BOM 的
        .ps1 按 ANSI/GBK 解码，中文串错位后会吞掉引号与换行，报出假性的
        MissingEndCurlyBrace 语法错误；也可改用 PowerShell 7（pwsh）运行。

    服务地址：
      - 前端 http://localhost:3000
      - 后端 http://127.0.0.1:8000/docs
#>

param(
    [switch]$Stop,
    [switch]$Reload
)

$ErrorActionPreference = "Continue"
$root = $PSScriptRoot

# ---- 工具函数 ----

function Write-Step($index, $total, $message) {
    Write-Host ("[" + $index + "/" + $total + "] " + $message) -ForegroundColor Cyan
}

function Write-Detail($message) {
    Write-Host ("  " + $message) -ForegroundColor DarkGray
}

function Write-Ok($message) {
    Write-Host ("  " + $message) -ForegroundColor Green
}

function Write-Warn($message) {
    Write-Host ("  " + $message) -ForegroundColor Yellow
}

function Stop-Port($port) {
    <#
    .SYNOPSIS
        强制释放指定端口。
    #>
    $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    foreach ($c in $conns) {
        $p = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue
        if ($p) {
            Write-Detail ("释放端口 " + $port + " (PID " + $p.Id + " " + $p.ProcessName + ")")
            Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
        }
    }
}

function Test-Command($name) {
    <#
    .SYNOPSIS
        检查命令是否可用。
    #>
    return $null -ne (Get-Command $name -ErrorAction SilentlyContinue)
}

# ---- 停止模式 ----

if ($Stop) {
    Write-Step 1 1 "停止服务"
    Stop-Port 8000
    Stop-Port 3000
    Write-Ok "已停止"
    exit 0
}

# ---- 前置检查 ----

Write-Step 0 4 "检查环境"

if (-not (Test-Command "uv")) {
    Write-Warn "未找到 uv，请先安装：https://docs.astral.sh/uv/"
    exit 1
}

if (-not (Test-Command "pnpm")) {
    Write-Warn "未找到 pnpm，请先安装：npm install -g pnpm"
    exit 1
}

Write-Ok "uv 与 pnpm 已就绪"

# ---- 清理端口 ----

Write-Step 1 4 "清理占用端口"
Stop-Port 8000
Stop-Port 3000
Start-Sleep -Seconds 1

# ---- 安装依赖 ----

Write-Step 2 4 "检查依赖"

if (-not (Test-Path "$root/backend/.venv")) {
    Write-Detail "安装后端依赖 ..."
    Push-Location "$root/backend"
    uv sync
    Pop-Location
} else {
    Write-Detail "后端依赖已存在"
}

if (-not (Test-Path "$root/frontend/node_modules")) {
    Write-Detail "安装前端依赖 ..."
    Push-Location "$root/frontend"
    pnpm install
    Pop-Location
} else {
    Write-Detail "前端依赖已存在"
}

# ---- 准备环境变量 ----

$envFile = "$root/backend/.env"
$envExample = "$root/backend/.env.example"
if ((-not (Test-Path $envFile)) -and (Test-Path $envExample)) {
    Copy-Item $envExample $envFile
    Write-Detail "已从 .env.example 创建 backend/.env"
}

# ---- 启动后端 ----

Write-Step 3 4 "启动后端"

# 优先用本地 venv（不依赖 uv 缓存；C 盘满时 uv 可能失败）
$venvUvicorn = Join-Path $root "backend\.venv\Scripts\uvicorn.exe"
$venvPython = Join-Path $root "backend\.venv\Scripts\python.exe"
if (Test-Path $venvUvicorn) {
    Write-Detail "使用 backend/.venv 直启 uvicorn"
    $be = Start-Process -FilePath $venvUvicorn `
        -ArgumentList @("app.main:app", "--host", "127.0.0.1", "--port", "8000") `
        -WorkingDirectory "$root/backend" `
        -PassThru -NoNewWindow
} elseif (Test-Command "uv") {
    $beArgs = @("run", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000")
    if ($Reload) {
        $beArgs += "--reload"
        Write-Detail "热重载已启用"
    }
    $be = Start-Process -FilePath "uv" `
        -ArgumentList $beArgs `
        -WorkingDirectory "$root/backend" `
        -PassThru -NoNewWindow
} else {
    Write-Warn "未找到 uvicorn，请先执行 uv sync 或检查 backend/.venv"
    exit 1
}

Start-Sleep -Seconds 5

$backendOk = $false
try {
    $h = Invoke-RestMethod "http://127.0.0.1:8000/api/health" -TimeoutSec 8
    Write-Ok ("后端就绪 (PID " + $be.Id + ", version " + $h.version + ")")
    $backendOk = $true
} catch {
    Write-Warn "后端健康检查失败，请查看上方输出"
}

# ---- 启动前端 ----

Write-Step 4 4 "启动前端"

# 优先生产模式（构建产物已存在时）：秒开；否则回落 dev
$nextStandalone = Test-Path "$root/frontend\.next\BUILD_ID"
if ($nextStandalone -and -not $Reload) {
    Write-Detail "检测到生产构建，使用 pnpm start（更快）"
    $fe = Start-Process -FilePath "cmd.exe" `
        -ArgumentList "/c", "pnpm start" `
        -WorkingDirectory "$root/frontend" `
        -PassThru -NoNewWindow
} else {
    $fe = Start-Process -FilePath "cmd.exe" `
        -ArgumentList "/c", "pnpm dev" `
        -WorkingDirectory "$root/frontend" `
        -PassThru -NoNewWindow
}

Start-Sleep -Seconds 8

# ---- 输出摘要 ----

Write-Host ""
Write-Host "服务已启动" -ForegroundColor Green
Write-Host ""
Write-Host "  前端  http://localhost:3000"
Write-Host "  后端  http://127.0.0.1:8000/docs"
Write-Host ""
Write-Detail ("进程  backend PID=" + $be.Id + "  frontend PID=" + $fe.Id)
Write-Host ""
Write-Host "停止服务  .\dev.ps1 -Stop" -ForegroundColor DarkGray
