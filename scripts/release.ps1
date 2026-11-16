[CmdletBinding()]
param([string]$Notes = '', [switch]$Draft)
# Build the EXE, package it and publish a GitHub Release that the built-in
# updater picks up (asset name must stay WarshipPilot-<version>-win-x64.zip).
# Requires: clean, pushed working tree; gh logged in with access to the repo.
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Push-Location $projectRoot
try {
    $version = ([regex]::Match((Get-Content backend/version.py -Raw), 'VERSION = "([0-9.]+)"')).Groups[1].Value
    if (!$version) { throw 'VERSION not found in backend/version.py' }
    $tag = "v$version"
    if (git status --porcelain) { throw 'Working tree is not clean; commit first' }
    git fetch --quiet origin
    $branch = git rev-parse --abbrev-ref HEAD
    if ((git rev-parse HEAD) -ne (git rev-parse "origin/$branch")) { throw "Push $branch before releasing" }
    gh release view $tag 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { throw "Release $tag already exists; bump backend/version.py" }

    & "$PSScriptRoot/build.ps1" -OutputRoot dist
    $release = Join-Path $projectRoot 'dist\WarshipPilot'
    $zip = Join-Path $projectRoot "dist\WarshipPilot-$version-win-x64.zip"
    $source = Join-Path $projectRoot "dist\WarshipPilot-$version-source.zip"
    if (Test-Path -LiteralPath $zip) { Remove-Item -LiteralPath $zip }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [IO.Compression.ZipFile]::CreateFromDirectory($release, $zip, [IO.Compression.CompressionLevel]::Optimal, $false)
    $hash = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLower()

    $notesFile = New-TemporaryFile
    $body = if ($Notes) { $Notes } else { git log -1 --format=%B }
    Set-Content -LiteralPath $notesFile -Value "$body`n`nSHA-256 ($([IO.Path]::GetFileName($zip))): $hash" -Encoding UTF8
    $ghArgs = @('release', 'create', $tag, $zip, $source, '--title', "WarshipPilot $tag", '--notes-file', $notesFile, '--target', (git rev-parse HEAD))
    if ($Draft) { $ghArgs += '--draft' }
    gh @ghArgs
    if ($LASTEXITCODE) { throw 'gh release create failed' }
    Remove-Item -LiteralPath $notesFile
    Write-Output "Published $tag  sha256=$hash"
} finally { Pop-Location }
