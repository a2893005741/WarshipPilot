[CmdletBinding()]
param([string]$OutputRoot = 'dist', [switch]$SkipNpmCi)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Push-Location $projectRoot
try {
    uv sync --frozen --group build
    if ($LASTEXITCODE) { throw 'Python dependencies failed' }
    Push-Location frontend
    try {
        if (!$SkipNpmCi -or !(Test-Path node_modules)) {
            npm ci
            if ($LASTEXITCODE) { throw 'Frontend dependencies failed' }
        }
        if (Test-Path dist) { Remove-Item -LiteralPath dist -Recurse -Force }
        npm run build
        if ($LASTEXITCODE) { throw 'Frontend build failed' }
    } finally { Pop-Location }
    uv run --frozen python scripts/make-icon.py
    uv run --frozen pyinstaller --noconfirm --clean --distpath $OutputRoot --onedir --windowed --name WarshipPilot --icon assets/app.ico --add-data 'frontend/dist;frontend/dist' --add-data 'assets;assets' --add-data 'bin;bin' --collect-all uvicorn --collect-all adbutils --collect-all uiautomator2 --collect-all uiautomator2cache --collect-all av --collect-all lupa --hidden-import lupa.lua52 --hidden-import wsproto --hidden-import uvicorn.protocols.websockets.wsproto_impl main.py
    if ($LASTEXITCODE) { throw 'EXE build failed' }
    $adbSource = 'C:\adb'
    if (!(Test-Path "$adbSource\adb.exe")) { throw 'Set adbSource to an Android platform-tools directory' }
    $target = Join-Path (Join-Path $projectRoot $OutputRoot) 'WarshipPilot'
    New-Item -ItemType Directory -Path "$target\_internal\adb" -Force | Out-Null
    foreach ($file in @('adb.exe','AdbWinApi.dll','AdbWinUsbApi.dll')) {
        Copy-Item -LiteralPath "$adbSource\$file" -Destination "$target\_internal\adb\$file" -Force
    }
    Copy-Item -LiteralPath README.md -Destination "$target\README.md" -Force
    Copy-Item -LiteralPath docs/THIRD-PARTY-NOTICES.md -Destination "$target\THIRD-PARTY-NOTICES.md" -Force
    Copy-Item -LiteralPath LICENSE -Destination "$target\LICENSE" -Force
    Copy-Item -LiteralPath docs/ALAS-PORT.json -Destination "$target\ALAS-PORT.json" -Force
    uv run --frozen python scripts/package-source.py --output $OutputRoot
    Write-Output "Release: $target\WarshipPilot.exe"
} finally { Pop-Location }
