<#
.SYNOPSIS
    Weister - Prepare the embedded Python environment.

.DESCRIPTION
    Downloads the official Python embeddable package, bootstraps pip and
    installs every backend dependency into backend/python/.

    IMPORTANT: keep this file pure ASCII.
    PowerShell 5.1 decodes a BOM-less .ps1 file as ANSI, so a non-ASCII byte
    inside a comment can swallow the following line break and merge the next
    statement into that comment (this silently ate an assignment and produced
    "-Path is null" errors). ASCII-only sources are encoding-proof.

.PARAMETER PythonVersion
    Python version, default 3.12.9.

.PARAMETER Force
    Delete backend/python/ and reinstall from scratch.
    Without it an existing python/ is kept, but dependencies are still
    installed/verified against it.
#>

param(
    [string]$PythonVersion = "3.12.9",
    [switch]$Force
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

$pythonExe = Join-Path $pythonDir "python.exe"

# ---------------------------------------------------------------------------
# Isolation from the build machine's per-user site-packages
# ---------------------------------------------------------------------------
#
# The embeddable Python ships a python3xx._pth containing "import site", so the
# interpreter runs site.main() at startup and site appends
#   %APPDATA%\Python\PythonXY\site-packages
# to sys.path.
#
# Consequence: if fastapi / uvicorn / pydantic were ever installed with
# `pip install --user` on the build machine, the pip call below reports
# "Requirement already satisfied" and skips the install entirely. The packages
# stay in the build machine's user directory and never reach
# backend/python/Lib/site-packages. Everything works locally (the user
# directory masks the problem) and the distributed build dies with:
#   ModuleNotFoundError: No module named 'uvicorn'
# The backend exits instantly, the client waits 60 seconds and then shows
# "backend not responding after 60s".
#
# Do NOT rely on the PYTHONNOUSERSITE environment variable here: while a
# ._pth file exists the interpreter runs in isolated mode and PYTHON* env
# vars are ignored - measured, pip still saw the build machine's user
# site-packages with it set. The only reliable switch is the `-s` command
# line flag: it sets sys.flags.no_user_site, site.main() skips the user
# directory, and the bundled Lib\site-packages keeps loading normally.
#
# `-s` is therefore threaded through the whole script: pip bootstrap, the
# dependency install and the final verification.

# ---- Reuse an existing environment, or install one ----

if ((Test-Path $pythonExe) -and (-not $Force)) {
    $version = & $pythonExe -s --version 2>&1
    Write-Step "Embedded Python already exists: $version"
    Write-Host "  Skip download, continue to dependency check (-Force to reinstall)"
} else {
    if ((-not (Test-Path $pythonExe)) -and (Test-Path $pythonDir)) {
        Write-Step "Incomplete python/ found, reinstalling ..."
        Remove-Item $pythonDir -Recurse -Force
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
        $version = & $pythonExe -s --version 2>&1
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

    & $pythonExe -s $getPipPath --no-warn-script-location 2>&1 | Out-Host
    if ($LASTEXITCODE -ne 0) {
        Write-Err "pip installation failed"
        exit 1
    }
    Remove-Item $getPipPath -Force

    # Enable site-packages: rewrite python*._pth with "import site".
    $pthFile = Get-ChildItem $pythonDir -Filter "python*._pth" | Select-Object -First 1
    if ($pthFile) {
        # Fresh ._pth: site-packages enabled, plus ".." so the backend package
        # (../app) is importable through `python -m app`. Without ".." the
        # embedded interpreter only sees python/ itself and `python -m app`
        # fails with "No module named app".
        $zipLine = Get-Content $pthFile.FullName | Where-Object { $_ -match "\.zip$" } | Select-Object -First 1
        if (-not $zipLine) {
            # Derived from $PythonVersion (3.12.x -> python312.zip), never hardcoded.
            $zipLine = "python$((($PythonVersion -split '\.')[0..1]) -join '').zip"
        }
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
    & $pythonExe -s -m pip --version 2>&1 | Out-Host
    if ($LASTEXITCODE -ne 0) {
        Write-Err "pip not working"
        exit 1
    }
    Write-Ok "pip ready"
}

# ---- Install backend dependencies ----
#
# `-s` all the way through (see the note at the top): pip therefore cannot see
# the build machine's user directory and cannot fake an install.

Write-Step "Installing backend dependencies ..."

Push-Location $backendDir

& $pythonExe -s -m pip install --no-warn-script-location --no-input `
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
#
# Run with `-s` so this reproduces the import environment of a machine that
# has no user site-packages - the only way to catch a fake pass. Every module
# must also resolve to a file inside backend/python/.

Write-Step "Verifying dependencies (isolated from user site-packages) ..."

$verifyScript = @'
import importlib
import sys
from pathlib import Path

root = Path(sys.executable).resolve().parent
mods = ["fastapi", "uvicorn", "pydantic", "pydantic_settings",
        "langgraph", "langchain_core", "httpx", "dotenv",
        "fitz", "mcp", "tiktoken"]

missing, stray = [], []
for m in mods:
    try:
        mod = importlib.import_module(m)
    except Exception as exc:
        missing.append("{} ({}: {})".format(m, type(exc).__name__, exc))
        continue
    where = getattr(mod, "__file__", None)
    if not where:
        locs = list(getattr(mod, "__path__", None) or [])
        where = locs[0] if locs else None
    if not where:
        continue
    origin = Path(where).resolve()
    if root != origin and root not in origin.parents:
        stray.append("{} -> {}".format(m, origin))

if stray:
    print("OUTSIDE PACKAGE (user site-packages leak):")
    for s in stray:
        print("  " + s)
if missing:
    print("MISSING: " + ", ".join(missing))
sys.exit(1 if (missing or stray) else 0)
'@

# Written to a temp file instead of passed through `-c`: multi-line source on
# the command line gets mangled by PowerShell's native argument escaping (the
# quotes are stripped and Python answers with an unlocatable SyntaxError).
# The file lands in backend/ (guaranteed to exist) so it does not depend on
# TEMP/TMP being set.
$verifyPath = Join-Path $backendDir ".weister-verify-deps.py"
Set-Content -Path $verifyPath -Value $verifyScript -Encoding ASCII
& $pythonExe -s $verifyPath 2>&1 | Out-Host
$verifyOk = $LASTEXITCODE -eq 0
Remove-Item $verifyPath -Force

if (-not $verifyOk) {
    Write-Err "Dependency verification failed (see MISSING / OUTSIDE PACKAGE above)"
    exit 1
}

# `python -m app` only resolves because of the ".." line in python*._pth.
Write-Step "Checking 'python -m app' resolution ..."

Push-Location $backendDir
$appProbePath = Join-Path $backendDir ".weister-verify-app.py"
Set-Content -Path $appProbePath -Value "import app; print('app package importable: ' + app.__file__)" -Encoding ASCII
& $pythonExe -s $appProbePath 2>&1 | Out-Host
$appOk = $LASTEXITCODE -eq 0
Remove-Item $appProbePath -Force
Pop-Location

if (-not $appOk) {
    Write-Err "app package not importable (python*._pth must contain '..')"
    exit 1
}

Write-Ok "All dependencies verified"
Write-Host ""
Write-Host "Embedded Python ready: backend/python/" -ForegroundColor Green
