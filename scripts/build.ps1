<#
.SYNOPSIS
    Weister 路 妗岄潰瀹㈡埛绔竴閿瀯寤鸿剼鏈?

.DESCRIPTION
    鎸夐『搴忓畬鎴愪笁姝ユ瀯寤猴細
      1. 鍚庣 PyInstaller 鎵撳寘锛坆ackend/dist/backend/锛?
      2. 鍓嶇 Next.js standalone 鏋勫缓锛坒rontend/.next/standalone/锛?
      3. Electron electron-builder 鎵撳寘锛坋lectron/release/锛?

.EXAMPLE
    .\scripts\build.ps1
    鏋勫缓妗岄潰瀹㈡埛绔畨瑁呭寘銆?

.NOTES
    鍓嶇疆瑕佹眰锛?
      - uv锛圥ython 鍖呯鐞嗗櫒锛?
      - pnpm >= 9
      - Node.js >= 20
      - PyInstaller锛堣剼鏈細鑷姩瀹夎鍒板悗绔櫄鎷熺幆澧冿級

    缂栫爜瑕佹眰锛歎TF-8 with BOM锛堜笌 dev.ps1 涓€鑷达級
#>

param(
    [switch]$SkipBackend,
    [switch]$SkipFrontend,
    [switch]$SkipElectron
)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent

function Write-Step($index, $total, $message) {
    Write-Host ""
    Write-Host ("[" + $index + "/" + $total + "] " + $message) -ForegroundColor Cyan
}

function Write-Ok($message) {
    Write-Host ("  鉁?" + $message) -ForegroundColor Green
}

function Write-Warn($message) {
    Write-Host ("  鈿?" + $message) -ForegroundColor Yellow
}

function Write-Err($message) {
    Write-Host ("  鉁?" + $message) -ForegroundColor Red
}

function Test-Command($name) {
    return $null -ne (Get-Command $name -ErrorAction SilentlyContinue)
}

$total = 3
$step = 0

# ---- 鍓嶇疆妫€鏌?----

Write-Step 0 $total "妫€鏌ョ幆澧?

if (-not (Test-Command "pnpm")) {
    Write-Err "鏈壘鍒?pnpm锛岃鍏堝畨瑁咃細npm install -g pnpm"
    exit 1
}

if (-not (Test-Command "node")) {
    Write-Err "鏈壘鍒?node锛岃鍏堝畨瑁?Node.js >= 20"
    exit 1
}

Write-Ok "pnpm / node 宸插氨缁?

# ---- Step 1锛氬噯澶囧祵鍏ュ紡 Python 鐜 ----

if (-not $SkipBackend) {
    $step++
    Write-Step $step $total "鍑嗗宓屽叆寮?Python 鐜"

    $prepareScript = Join-Path $PSScriptRoot "prepare-python.ps1"
    & $prepareScript

    if (Test-Path "$root/backend/python/python.exe") {
        Write-Ok "宓屽叆寮?Python 灏辩华锛歜ackend/python/python.exe"
    } else {
        Write-Err "宓屽叆寮?Python 鍑嗗澶辫触"
        exit 1
    }
} else {
    Write-Warn "璺宠繃鍚庣鍑嗗"
}

# ---- Step 2锛氬墠绔?Next.js standalone 鏋勫缓 ----

if (-not $SkipFrontend) {
    $step++
    Write-Step $step $total "鍓嶇 Next.js standalone 鏋勫缓"

    Push-Location "$root/frontend"

    if (-not (Test-Path "node_modules")) {
        Write-Host "  瀹夎鍓嶇渚濊禆 ..."
        pnpm install 2>&1 | Out-Host
    }

    Write-Host "  鎵ц pnpm build ..."
    pnpm build 2>&1 | Out-Host

    if (Test-Path ".next/standalone/server.js") {
        Write-Ok "鍓嶇鏋勫缓鎴愬姛锛?next/standalone/server.js"
    } else {
        Write-Err "鍓嶇鏋勫缓澶辫触锛?next/standalone/server.js 涓嶅瓨鍦?
        Pop-Location
        exit 1
    }

    Pop-Location
} else {
    Write-Warn "璺宠繃鍓嶇鏋勫缓"
}

# ---- Step 3锛欵lectron electron-builder 鎵撳寘 ----

if (-not $SkipElectron) {
    $step++
    Write-Step $step $total "Electron electron-builder 鎵撳寘"

    Push-Location "$root/electron"

    if (-not (Test-Path "node_modules")) {
        Write-Host "  瀹夎 Electron 渚濊禆 ..."
        pnpm install 2>&1 | Out-Host
    }

    Write-Host "  鎵ц electron-builder ..."
    pnpm build 2>&1 | Out-Host

    # 鏌ユ壘鐢熸垚鐨勫畨瑁呭寘
    $installer = Get-ChildItem "release" -Filter "*.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($installer) {
        Write-Ok "瀹夎鍖呭凡鐢熸垚锛歟lectron/release/$($installer.Name)"
        Write-Host ""
        Write-Host "  瀹夎鍖呰矾寰勶細$root/electron/release/$($installer.Name)" -ForegroundColor Green
        Write-Host "  澶у皬锛?([math]::Round($installer.Length / 1MB, 1)) MB" -ForegroundColor Green
    } else {
        Write-Warn "鏈壘鍒板畨瑁呭寘锛岃妫€鏌?electron/release/ 鐩綍"
    }

    Pop-Location
} else {
    Write-Warn "璺宠繃 Electron 鎵撳寘"
}

# ---- 瀹屾垚 ----

Write-Host ""
Write-Host "鏋勫缓瀹屾垚" -ForegroundColor Green
