$ErrorActionPreference = 'Stop'
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
Set-Location -LiteralPath $root
New-Item -ItemType Directory -Path (Join-Path $root 'log') -Force | Out-Null
& (Join-Path $root 'WarshipPilot.bat') @args *> (Join-Path $root 'log\launcher.log')
exit $LASTEXITCODE
