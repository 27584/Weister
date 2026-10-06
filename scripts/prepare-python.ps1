<#
.SYNOPSIS
    Weister · 准备嵌入式 Python 环境

.DESCRIPTION
    下载官方 Python embeddable package，配置 pip，安装后端全部依赖。
    产物在 backend/python/ 目录下，包含 python.exe + site-packages。

    Electron 桌面客户端直接用这个 python.exe 拉起 uvicorn。

.PARAMETER PythonVersion
    Python 版本，默认 3.12.9（与 pyproject.toml 的 requires-python >=3.12 对齐）

.EXAMPLE
    .\scripts\prepare-python.ps1
    下载并安装嵌入式 Python 环境。

.NOTES
    编码要求：UTF-8 with BOM（与 dev.ps1 一致）
#>

param(
    [string]$PythonVersion = "3.12.9"
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot | Split-Path | Split-Path
$backendDir = Join-Path $root "backend"
$pythonDir = Join-Path $backendDir "python"

function Write-Step($message) {
    Write-Host "[prepare-python] $message" -ForegroundColor Cyan
}

function Write-Ok($message) {
    Write-Host "  ✓ $message" -ForegroundColor Green
}

function Write-Err($message) {
    Write-Host "  ✗ $message" -ForegroundColor Red
}

# ---- 检查是否已存在 ----

$pythonExe = Join-Path $pythonDir "python.exe"
if (Test-Path $pythonExe) {
    $version = & $pythonExe --version 2>&1
    Write-Step "嵌入式 Python 已存在：$version"
    Write-Host "  如需重新安装，请先删除 backend/python/ 目录"
    exit 0
}

# ---- 下载 Python embeddable ----

Write-Step "下载 Python $PythonVersion embeddable package ..."

# Windows amd64
$url = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip"
$zipPath = Join-Path $env:TEMP "python-$PythonVersion-embed-amd64.zip"

Write-Host "  URL: $url"

try {
    Invoke-WebRequest -Uri $url -OutFile $zipPath -UseBasicParsing
    Write-Ok "下载完成"
} catch {
    Write-Err "下载失败：$_"
    Write-Host "  手动下载：$url"
    Write-Host "  放到 backend/python/ 下解压"
    exit 1
}

# ---- 解压 ----

Write-Step "解压到 backend/python/ ..."

if (Test-Path $pythonDir) {
    Remove-Item $pythonDir -Recurse -Force
}
New-Item -ItemType Directory -Path $pythonDir -Force | Out-Null

Expand-Archive -Path $zipPath -DestinationPath $pythonDir -Force
Remove-Item $zipPath -Force

if (Test-Path $pythonExe) {
    $version = & $pythonExe --version 2>&1
    Write-Ok "Python 安装成功：$version"
} else {
    Write-Err "解压后未找到 python.exe"
    exit 1
}

# ---- 启用 pip ----

Write-Step "配置 pip ..."

# 嵌入式 Python 默认不含 pip，需要手动 bootstrap
$getPipUrl = "https://bootstrap.pypa.io/get-pip.py"
$getPipPath = Join-Path $pythonDir "get-pip.py"

Invoke-WebRequest -Uri $getPipUrl -OutFile $getPipPath -UseBasicParsing

& $pythonExe $getPipPath --no-warn-script-location 2>&1 | Out-Host
if ($LASTEXITCODE -ne 0) {
    Write-Err "pip 安装失败"
    exit 1
}
Remove-Item $getPipPath -Force

# 启用 site-packages：取消 python312._pth 中 import site 的注释
$pthFile = Get-ChildItem $pythonDir -Filter "python*._pth" | Select-Object -First 1
if ($pthFile) {
    $content = Get-Content $pthFile.FullName
    $content = $content | ForEach-Object {
        if ($_ -match "^#import site") {
            "import site"
        } else {
            $_
        }
    }
    Set-Content $pthFile.FullName $content
    Write-Ok "已启用 site-packages（$($pthFile.Name)）"
}

# 验证 pip
& $pythonExe -m pip --version 2>&1 | Out-Host
if ($LASTEXITCODE -ne 0) {
    Write-Err "pip 不可用"
    exit 1
}
Write-Ok "pip 已就绪"

# ---- 安装后端依赖 ----

Write-Step "安装后端依赖 ..."

Push-Location $backendDir

# 用嵌入式 Python 的 pip 直接 install
& $pythonExe -m pip install --no-warn-script-location `
    "fastapi>=0.115.0" `
    "uvicorn[standard]>=0.32.0" `
    "python-multipart>=0.0.12" `
    "pydantic>=2.9.0" `
    "pydantic-settings>=2.6.0" `
    "langgraph>=0.2.60" `
    "langchain-core>=0.3.25" `
    "httpx>=0.27.2" `
    "python-dotenv>=1.0.1" `
    "pymupdf>=1.24.0" `
    "mcp>=1.0.0" `
    "tiktoken>=0.7.0" `
    2>&1 | Out-Host

if ($LASTEXITCODE -ne 0) {
    Write-Err "依赖安装失败"
    Pop-Location
    exit 1
}

Pop-Location

# ---- 验证 ----

Write-Step "验证关键依赖 ..."

$verifyScript = @"
import sys
modules = ['fastapi', 'uvicorn', 'pydantic', 'pydantic_settings',
           'langgraph', 'langchain_core', 'httpx', 'dotenv',
           'fitz', 'mcp', 'tiktoken']
missing = []
for m in modules:
    try:
        __import__(m)
    except ImportError:
        missing.append(m)
if missing:
    print('MISSING:', ', '.join(missing))
    sys.exit(1)
else:
    print('ALL OK')
"@

& $pythonExe -c $verifyScript 2>&1 | Out-Host
if ($LASTEXITCODE -ne 0) {
    Write-Err "依赖验证失败"
    exit 1
}

Write-Ok "全部依赖验证通过"
Write-Host ""
Write-Host "嵌入式 Python 环境已就绪：backend/python/" -ForegroundColor Green
