<#
.SYNOPSIS
    Weister - Prepare embedded Python environment

.DESCRIPTION
    Downloads official Python embeddable package, bootstraps pip,
    installs all backend dependencies into backend/python/.

.PARAMETER PythonVersion
    Python version, default 3.12.9
#>

param(
    [string]$PythonVersion = "3.12.9"
)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$backendDir = Join-Path $root "backend"
$pythonDir = Join-Path $backendDir "python"

function Write-Step($message) {
    Write-Host "[prepare-python] $message" -ForegroundColor Cyan
}

function Write-Ok($message) {
    Write-Host "  OK $message" -ForegroundColor Green
}

function Write-Err($message) {
    Write-Host "  FAIL $message" -ForegroundColor Red
}

# ---- Check if already exists ----

$pythonExe = Join-Path $pythonDir "python.exe"
if (Test-Path $pythonExe) {
    $version = & $pythonExe --version 2>&1
    Write-Step "Embedded Python already exists: $version"
    Write-Host "  Delete backend/python/ to reinstall"
    exit 0
}

# ---- Download Python embeddable ----

Write-Step "Downloading Python $PythonVersion embeddable package ..."

$url = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip"
$zipPath = Join-Path $env:TEMP "python-$PythonVersion-embed-amd64.zip"

Write-Host "  URL: $url"

try {
    Invoke-WebRequest -Uri $url -OutFile $zipPath -UseBasicParsing
    Write-Ok "Download complete"
} catch {
    Write-Err "Download failed: $_"
    exit 1
}

# ---- Extract ----

Write-Step "Extracting to backend/python/ ..."

if (Test-Path $pythonDir) {
    Remove-Item $pythonDir -Recurse -Force
}
New-Item -ItemType Directory -Path $pythonDir -Force | Out-Null

Expand-Archive -Path $zipPath -DestinationPath $pythonDir -Force
Remove-Item $zipPath -Force

if (Test-Path $pythonExe) {
    $version = & $pythonExe --version 2>&1
    Write-Ok "Python installed: $version"
} else {
    Write-Err "python.exe not found after extraction"
    exit 1
}

# ---- Enable pip ----

Write-Step "Setting up pip ..."

$getPipUrl = "https://bootstrap.pypa.io/get-pip.py"
$getPipPath = Join-Path $pythonDir "get-pip.py"

Invoke-WebRequest -Uri $getPipUrl -OutFile $getPipPath -UseBasicParsing

& $pythonExe $getPipPath --no-warn-script-location 2>&1 | Out-Host
if ($LASTEXITCODE -ne 0) {
    Write-Err "pip installation failed"
    exit 1
}
Remove-Item $getPipPath -Force

# Enable site-packages: uncomment "import site" in python*._pth
$pthFile = Get-ChildItem $pythonDir -Filter "python*._pth" | Select-Object -First 1
if ($pthFile) {
    # Write a fresh ._pth: site-packages enabled + ".." so the backend
    # package (../app) is importable via `python -m app`.
    # Without "..", the embedded interpreter only sees python/ itself and
    # `python -m app` fails with "No module named app".
    $zipLine = Get-Content $pthFile.FullName | Where-Object { $_ -match "\.zip$" } | Select-Object -First 1
    if (-not $zipLine) { $zipLine = "python312.zip" }
    $lines = @(
        $zipLine,
        ".",
        "..",
        "",
        "# Uncomment to run site.main() automatically",
        "import site"
    )
    Set-Content $pthFile.FullName $lines
    Write-Ok "site-packages enabled and backend path added"
}

# Verify pip
& $pythonExe -m pip --version 2>&1 | Out-Host
if ($LASTEXITCODE -ne 0) {
    Write-Err "pip not working"
    exit 1
}
Write-Ok "pip ready"

# ---- Install backend dependencies ----

Write-Step "Installing backend dependencies ..."

Push-Location $backendDir

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
    Write-Err "Dependency installation failed"
    Pop-Location
    exit 1
}

Pop-Location

# ---- Verify ----

Write-Step "Verifying dependencies ..."

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
    Write-Err "Dependency verification failed"
    exit 1
}

Write-Ok "All dependencies verified"
Write-Host ""
Write-Host "Embedded Python ready: backend/python/" -ForegroundColor Green
