[CmdletBinding()]
param([string]$ComputerName = 'DESKTOP-3F63TNA', [string]$OutputRoot = 'dist-v0.4')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$release = Join-Path $projectRoot "$OutputRoot\WarshipPilot"
$version = '0.4.0'
$zip = Join-Path $projectRoot "$OutputRoot\WarshipPilot-$version-win-x64.zip"
if (!(Test-Path -LiteralPath "$release\WarshipPilot.exe")) { throw 'Build the release first' }
Add-Type -AssemblyName System.IO.Compression.FileSystem
$freshZip = Join-Path $projectRoot "$OutputRoot\WarshipPilot-$version-$([guid]::NewGuid().ToString('N')).zip"
[IO.Compression.ZipFile]::CreateFromDirectory($release, $freshZip, [IO.Compression.CompressionLevel]::Optimal, $false)
Move-Item -LiteralPath $freshZip -Destination $zip -Force
$exeHash = (Get-FileHash -LiteralPath "$release\WarshipPilot.exe").Hash
$zipHash = (Get-FileHash -LiteralPath $zip).Hash
$credential = Import-Clixml -LiteralPath (Join-Path $env:LOCALAPPDATA "Codex\Credentials\$ComputerName.xml")
$session = New-PSSession -ComputerName $ComputerName -Credential $credential
try {
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $remoteZip = "D:\WarshipPilot-$version-$stamp.zip"
    Copy-Item -LiteralPath $zip -Destination $remoteZip -ToSession $session
    $receipt = Invoke-Command -Session $session -ArgumentList $remoteZip,$stamp,$exeHash,$zipHash,$version -ScriptBlock {
        param($archive,$stamp,$expectedExe,$expectedZip,$version)
        $ErrorActionPreference = 'Stop'
        $live = 'D:\WarshipPilot'
        $data = 'D:\WarshipPilot-data'
        $stage = "D:\WarshipPilot-stage-$stamp"
        $backup = "D:\WarshipPilot-backup-$stamp"
        $dataBackup = "D:\WarshipPilot-data-backup-$stamp"
        $failed = "D:\WarshipPilot-failed-$stamp"
        $failedData = "D:\WarshipPilot-data-failed-$stamp"
        # All directory moves below are restricted to these explicit D: root paths.
        foreach ($path in @($live,$data,$stage,$backup,$dataBackup,$failed,$failedData)) {
            if ([IO.Path]::GetFullPath($path) -notmatch '^D:\\WarshipPilot(?:-data)?(?:-(?:stage|backup|failed)-[0-9-]+)?$') { throw 'Unexpected upgrade path' }
        }
        if ((Get-FileHash -LiteralPath $archive).Hash -ne $expectedZip) { throw 'Archive hash mismatch' }
        if (!(Test-Path -LiteralPath $live) -or !(Test-Path -LiteralPath $data)) { throw 'Expected existing installation and data' }
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        [IO.Compression.ZipFile]::ExtractToDirectory($archive, $stage)
        if ((Get-FileHash -LiteralPath "$stage\WarshipPilot.exe").Hash -ne $expectedExe) { throw 'EXE hash mismatch' }
        $accessHash = (Get-FileHash -LiteralPath "$data\access.json").Hash
        $sampleIds = @(Get-ChildItem -LiteralPath "$data\samples" -Directory | ForEach-Object Name)
        $key = (Get-Content -LiteralPath "$data\access.json" -Raw | ConvertFrom-Json).key
        $headers = @{Authorization = "Bearer $key"}
        $oldProcesses = @(Get-Process WarshipPilot -ErrorAction SilentlyContinue | Where-Object Path -eq "$live\WarshipPilot.exe")
        Invoke-RestMethod -Uri 'http://127.0.0.1:22680/api/shutdown' -Method Post -Headers $headers -ContentType 'application/json' -Body '{}' | Out-Null
        foreach ($process in $oldProcesses) {
            if (!$process.WaitForExit(30000)) { throw 'Old application did not shut down cleanly; installation untouched' }
        }
        Stop-ScheduledTask -TaskName 'WarshipPilot-Preview'
        Copy-Item -LiteralPath $data -Destination $dataBackup -Recurse
        try {
            Move-Item -LiteralPath $live -Destination $backup
            Move-Item -LiteralPath $stage -Destination $live
            Start-ScheduledTask -TaskName 'WarshipPilot-Preview'
            $healthy = $false
            for ($attempt = 0; $attempt -lt 80; $attempt++) {
                try {
                    $health = Invoke-RestMethod -Uri 'http://127.0.0.1:22680/health' -TimeoutSec 1
                    if ($health.version -eq $version) { $healthy = $true; break }
                } catch {}
                Start-Sleep -Milliseconds 250
            }
            if (!$healthy) { throw 'New version failed to start' }
            $catalog = Invoke-RestMethod -Uri 'http://127.0.0.1:22680/api/legacy-catalog' -Headers $headers
            if ($catalog.stats.point_expressions -ne 624) { throw 'Packaged recognition assets unavailable' }
            if ((Get-FileHash -LiteralPath "$data\access.json").Hash -ne $accessHash) { throw 'Access code changed' }
            $newSampleIds = @(Get-ChildItem -LiteralPath "$data\samples" -Directory | ForEach-Object Name)
            if (@(Compare-Object $sampleIds $newSampleIds).Count) { throw 'Saved samples changed' }
            [pscustomobject]@{version=$health.version; host_name=$env:COMPUTERNAME; exe_sha256=$expectedExe; zip_sha256=$expectedZip; backup=$backup; data_backup=$dataBackup; access_preserved=$true; samples_preserved=$true; sample_count=$newSampleIds.Count; legacy_rules=$catalog.stats.point_expressions}
        } catch {
            $failure = $_
            Stop-ScheduledTask -TaskName 'WarshipPilot-Preview'
            Get-Process WarshipPilot -ErrorAction SilentlyContinue | Where-Object Path -eq "$live\WarshipPilot.exe" | Stop-Process -Force
            if (Test-Path -LiteralPath $backup) {
                if (Test-Path -LiteralPath $live) { Move-Item -LiteralPath $live -Destination $failed }
                Move-Item -LiteralPath $backup -Destination $live
                Move-Item -LiteralPath $data -Destination $failedData
                Copy-Item -LiteralPath $dataBackup -Destination $data -Recurse
            }
            Start-ScheduledTask -TaskName 'WarshipPilot-Preview'
            throw "Upgrade rolled back: $failure"
        }
    }
    $receipt | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $projectRoot 'evidence\v0.4-deployment.json') -Encoding UTF8
    $receipt | Select-Object version,host_name,backup,data_backup,sample_count,legacy_rules,access_preserved,samples_preserved
} finally { Remove-PSSession $session }
