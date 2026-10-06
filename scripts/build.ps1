<#
.SYNOPSIS
    Weister · 桌面客户端一键构建脚本

.DESCRIPTION
    按顺序完成三步构建：
      1. 后端 PyInstaller 打包（backend/dist/backend/）
      2. 前端 Next.js standalone 构建（frontend/.next/standalone/）
      3. Electron electron-builder 打包（electron/release/）

.EXAMPLE
    .\scripts\build.ps1
    构建桌面客户端安装包。

.NOTES
    前置要求：
      - uv（Python 包管理器）
      - pnpm >= 9
      - Node.js >= 20
      - PyInstaller（脚本会自动安装到后端虚拟环境）

    编码要求：UTF-8 with BOM（与 dev.ps1 一致）
#>

param(
    [switch]$SkipBackend,
    [switch]$SkipFrontend,
    [switch]$SkipElectron
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot | Split-Path | Split-Path

function Write-Step($index, $total, $message) {
    Write-Host ""
    Write-Host ("[" + $index + "/" + $total + "] " + $message) -ForegroundColor Cyan
}

function Write-Ok($message) {
    Write-Host ("  ✓ " + $message) -ForegroundColor Green
}

function Write-Warn($message) {
    Write-Host ("  ⚠ " + $message) -ForegroundColor Yellow
}

function Write-Err($message) {
    Write-Host ("  ✗ " + $message) -ForegroundColor Red
}

function Test-Command($name) {
    return $null -ne (Get-Command $name -ErrorAction SilentlyContinue)
}

$total = 3
$step = 0

# ---- 前置检查 ----

Write-Step 0 $total "检查环境"

if (-not (Test-Command "uv")) {
    Write-Err "未找到 uv，请先安装：https://docs.astral.sh/uv/"
    exit 1
}

if (-not (Test-Command "pnpm")) {
    Write-Err "未找到 pnpm，请先安装：npm install -g pnpm"
    exit 1
}

if (-not (Test-Command "node")) {
    Write-Err "未找到 node，请先安装 Node.js >= 20"
    exit 1
}

Write-Ok "uv / pnpm / node 已就绪"

# ---- Step 1：后端 PyInstaller 打包 ----

if (-not $SkipBackend) {
    $step++
    Write-Step $step $total "后端 PyInstaller 打包"

    Push-Location "$root/backend"

    # 确保 PyInstaller 已安装
    Write-Host "  检查 PyInstaller ..."
    $pyinstallerCheck = uv run python -c "import PyInstaller; print(PyInstaller.__version__)" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  安装 PyInstaller ..."
        uv pip install pyinstaller 2>&1 | Out-Host
    }

    # 清理旧产物
    if (Test-Path "dist/backend") {
        Write-Host "  清理旧的后端构建产物 ..."
        Remove-Item "dist/backend" -Recurse -Force
    }

    Write-Host "  执行 PyInstaller ..."
    uv run pyinstaller pyinstaller.spec --noconfirm 2>&1 | Out-Host

    if (Test-Path "dist/backend/backend.exe") {
        Write-Ok "后端打包成功：dist/backend/backend.exe"
    } else {
        Write-Err "后端打包失败：dist/backend/backend.exe 不存在"
        Pop-Location
        exit 1
    }

    Pop-Location
} else {
    Write-Warn "跳过后端打包"
}

# ---- Step 2：前端 Next.js standalone 构建 ----

if (-not $SkipFrontend) {
    $step++
    Write-Step $step $total "前端 Next.js standalone 构建"

    Push-Location "$root/frontend"

    if (-not (Test-Path "node_modules")) {
        Write-Host "  安装前端依赖 ..."
        pnpm install 2>&1 | Out-Host
    }

    Write-Host "  执行 pnpm build ..."
    pnpm build 2>&1 | Out-Host

    if (Test-Path ".next/standalone/server.js") {
        Write-Ok "前端构建成功：.next/standalone/server.js"
    } else {
        Write-Err "前端构建失败：.next/standalone/server.js 不存在"
        Pop-Location
        exit 1
    }

    Pop-Location
} else {
    Write-Warn "跳过前端构建"
}

# ---- Step 3：Electron electron-builder 打包 ----

if (-not $SkipElectron) {
    $step++
    Write-Step $step $total "Electron electron-builder 打包"

    Push-Location "$root/electron"

    if (-not (Test-Path "node_modules")) {
        Write-Host "  安装 Electron 依赖 ..."
        pnpm install 2>&1 | Out-Host
    }

    Write-Host "  执行 electron-builder ..."
    pnpm build 2>&1 | Out-Host

    # 查找生成的安装包
    $installer = Get-ChildItem "release" -Filter "*.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($installer) {
        Write-Ok "安装包已生成：electron/release/$($installer.Name)"
        Write-Host ""
        Write-Host "  安装包路径：$root/electron/release/$($installer.Name)" -ForegroundColor Green
        Write-Host "  大小：$([math]::Round($installer.Length / 1MB, 1)) MB" -ForegroundColor Green
    } else {
        Write-Warn "未找到安装包，请检查 electron/release/ 目录"
    }

    Pop-Location
} else {
    Write-Warn "跳过 Electron 打包"
}

# ---- 完成 ----

Write-Host ""
Write-Host "构建完成" -ForegroundColor Green
