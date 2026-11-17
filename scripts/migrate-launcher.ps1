[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$Root,
    [string]$Launcher,
    [string]$TaskName = 'WarshipPilot-Preview',
    [int]$Port = 22680,
    [switch]$Apply,
    [string]$Rollback,
    [int]$TimeoutMinutes = 15
)
$ErrorActionPreference = 'Stop'
$Root = [IO.Path]::GetFullPath($Root).TrimEnd('\')
if (!(Test-Path -LiteralPath "$Root\gui.py") -or !(Test-Path -LiteralPath "$Root\.git")) { throw 'Root must be an existing source installation' }
if ($Rollback -and $Apply) { throw 'Choose Apply or Rollback' }
$python = Join-Path $Root '.venv\Scripts\python.exe'
$oldTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($oldTask -and !($oldTask.Actions | Where-Object { $_.Arguments -like "*$Root\deploy\launcher\hidden.ps1*" })) {
    throw 'The scheduled task does not belong to this installation'
}

function Invoke-Console([string]$Action, $Body) {
    $parameters = @{ Uri="http://127.0.0.1:$Port/api/$Action"; Headers=@{Authorization=('Bearer '+$script:accessCode)}; TimeoutSec=15 }
    if ($null -ne $Body) { $parameters.Method='POST'; $parameters.ContentType='application/json'; $parameters.Body=($Body | ConvertTo-Json -Compress) }
    Invoke-RestMethod @parameters
}
function Wait-Healthy([int]$Seconds) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $value=Invoke-RestMethod "http://127.0.0.1:$Port/health" -TimeoutSec 2
            if ($value.product -eq 'WarshipPilot' -and $value.root -eq $Root) { return $value }
        } catch {}
        Start-Sleep -Milliseconds 500
    }
    throw 'Launcher startup timed out'
}
function Restore-Migration([string]$Backup) {
    $record=Get-Content -LiteralPath "$Backup\migration.json" -Raw | ConvertFrom-Json
    if ($record.root -ne $Root) { throw 'Backup belongs to a different installation' }
    $newTask=Get-ScheduledTask -TaskName 'WarshipPilot-LauncherMigration' -ErrorAction SilentlyContinue
    if ($newTask) {
        if (!($newTask.Actions | Where-Object { $_.Execute -eq "$Root\WarshipPilot.exe" })) { throw 'Migration task ownership changed' }
        Stop-ScheduledTask -TaskName $newTask.TaskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $newTask.TaskName -Confirm:$false
    }
    $launcherProcesses=Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -eq "$Root\WarshipPilot.exe" }
    foreach ($process in $launcherProcesses) { Stop-Process -Id $process.ProcessId -Force }
    $deadline=(Get-Date).AddSeconds(20)
    while ((Get-Date) -lt $deadline -and (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)) { Start-Sleep -Milliseconds 300 }
    if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) { throw 'Backend did not exit; keep the backup and stop it before rollback' }
    $environmentRecord=Join-Path $Root '.warship\environment-backup.json'
    if (Test-Path -LiteralPath $environmentRecord) {
        $newRecord=Get-Content -LiteralPath $environmentRecord -Raw
        if ($newRecord -ne $record.environmentRecord) {
            $environment=$newRecord | ConvertFrom-Json
            $environmentRoot=[IO.Path]::GetFullPath($environment.backup)
            if (!$environmentRoot.StartsWith("$Root\.warship\backups\",[StringComparison]::OrdinalIgnoreCase)) { throw 'Unexpected environment backup path' }
            if (Test-Path -LiteralPath "$environmentRoot\.venv") {
                $failed=[IO.Path]::GetFullPath("$Backup\failed-environment")
                if (!$failed.StartsWith([IO.Path]::GetFullPath($Backup)+'\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Unexpected recovery destination' }
                if (Test-Path -LiteralPath "$Root\.venv") { Move-Item -LiteralPath "$Root\.venv" -Destination $failed }
                Move-Item -LiteralPath "$environmentRoot\.venv" -Destination "$Root\.venv"
            }
        }
    }
    Copy-Item -LiteralPath "$Backup\deploy.yaml" -Destination "$Root\config\deploy.yaml" -Force
    foreach ($shortcut in $record.shortcuts) { Copy-Item -LiteralPath $shortcut.backup -Destination $shortcut.path -Force }
    $run='HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
    if ($record.runValue) { Set-ItemProperty -LiteralPath $run -Name WarshipPilot -Value $record.runValue }
    else { Remove-ItemProperty -LiteralPath $run -Name WarshipPilot -ErrorAction SilentlyContinue }
    if (Test-Path -LiteralPath "$Backup\task.xml") {
        Register-ScheduledTask -TaskName $TaskName -Xml (Get-Content -LiteralPath "$Backup\task.xml" -Raw) -Force | Out-Null
        if ($record.taskEnabled) { Enable-ScheduledTask -TaskName $TaskName | Out-Null; Start-ScheduledTask -TaskName $TaskName }
        else { Disable-ScheduledTask -TaskName $TaskName | Out-Null }
    }
    Write-Output "Restored installation from $Backup"
}
if ($Rollback) { Restore-Migration ([IO.Path]::GetFullPath($Rollback)); return }

Push-Location -LiteralPath $Root
try {
    $script:accessCode=(& $python -c 'from module.config.config import Config; import pathlib; print(Config(pathlib.Path.cwd()).deploy()[''WebUI''][''AccessCode''])').Trim()
    if ($LASTEXITCODE) { throw 'Could not read the existing configuration' }
    $health=Invoke-RestMethod "http://127.0.0.1:$Port/health" -TimeoutSec 5
    if ($health.product -ne 'WarshipPilot') { throw 'The port belongs to another product' }
    $owner=Get-CimInstance Win32_Process -Filter "ProcessId=$($health.pid)"
    if (!$owner.ExecutablePath.StartsWith("$Root\",[StringComparison]::OrdinalIgnoreCase)) { throw 'Backend belongs to another installation' }
    $state=Invoke-Console state $null
    if (!$Apply) {
        [pscustomobject]@{root=$Root;version=$health.version;running=$state.automation.running;scheduler=$state.automation.scheduler;task=$oldTask.TaskName;changesApplied=$false}
        return
    }
    if (!$Launcher -or !(Test-Path -LiteralPath $Launcher)) { throw 'Specify the verified launcher executable' }
    if (!(Test-Path -LiteralPath "$Root\deploy\launcher.py")) { throw 'Update the backend to the launcher contract before migration' }
    if (!$oldTask -or $oldTask.Principal.LogonType -ne 'Interactive') { throw 'An existing interactive task is required for remote migration' }
    if ($oldTask.Principal.UserId.Split('\')[-1] -ne $env:USERNAME) { throw 'Run migration as the interactive task user' }
    $existingMigration=Get-ScheduledTask -TaskName 'WarshipPilot-LauncherMigration' -ErrorAction SilentlyContinue
    if ($existingMigration) { throw 'A previous migration task exists; inspect or roll it back first' }
    $ready=Invoke-Console launcher-prepare @{}
    $deadline=(Get-Date).AddMinutes($TimeoutMinutes)
    while (!$ready.ready) {
        if ((Get-Date) -ge $deadline) { Invoke-Console launcher-cancel @{} | Out-Null; throw 'Current task did not drain before timeout' }
        Start-Sleep -Seconds 2
        $ready=Invoke-Console launcher-prepare @{}
    }
    $backup=Join-Path (Split-Path $Root -Parent) ((Split-Path $Root -Leaf)+'-launcher-backup-'+(Get-Date -Format 'yyyyMMdd-HHmmss'))
    New-Item -ItemType Directory -Path $backup | Out-Null
    Copy-Item -LiteralPath "$Root\config\deploy.yaml" -Destination "$backup\deploy.yaml"
    Export-ScheduledTask -TaskName $TaskName | Set-Content -LiteralPath "$backup\task.xml" -Encoding Unicode
    $shortcuts=@()
    $shell=New-Object -ComObject WScript.Shell
    foreach ($file in Get-ChildItem -LiteralPath ([Environment]::GetFolderPath('Desktop')) -Filter '*.lnk') {
        $link=$shell.CreateShortcut($file.FullName)
        if ($link.Arguments -like "*$Root\deploy\launcher\hidden.ps1*") {
            $copy=Join-Path $backup $file.Name
            Copy-Item -LiteralPath $file.FullName -Destination $copy
            $shortcuts+=@{path=$file.FullName;backup=$copy}
        }
    }
    $environmentRecord=''
    if (Test-Path -LiteralPath "$Root\.warship\environment-backup.json") { $environmentRecord=Get-Content -LiteralPath "$Root\.warship\environment-backup.json" -Raw }
    $run='HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
    $oldRun=(Get-ItemProperty -LiteralPath $run -Name WarshipPilot -ErrorAction SilentlyContinue).WarshipPilot
    @{root=$Root;taskEnabled=$oldTask.Settings.Enabled;environmentRecord=$environmentRecord;runValue=$oldRun;shortcuts=$shortcuts;commit=$health.commit} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath "$backup\migration.json" -Encoding UTF8
    try {
        Disable-ScheduledTask -TaskName $TaskName | Out-Null
        Invoke-Console shutdown @{} | Out-Null
        $deadline=(Get-Date).AddSeconds(45)
        while (Get-Process -Id $health.pid -ErrorAction SilentlyContinue) {
            if ((Get-Date) -ge $deadline) { throw 'Old backend did not exit' }
            Start-Sleep -Milliseconds 300
        }
        Copy-Item -LiteralPath $Launcher -Destination "$Root\WarshipPilot.exe" -Force
        $action=New-ScheduledTaskAction -Execute "$Root\WarshipPilot.exe" -Argument '--start-minimized --skip-update' -WorkingDirectory $Root
        $principal=New-ScheduledTaskPrincipal -UserId $oldTask.Principal.UserId -LogonType Interactive -RunLevel Limited
        Register-ScheduledTask -TaskName 'WarshipPilot-LauncherMigration' -Action $action -Principal $principal -Settings (New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries) | Out-Null
        Start-ScheduledTask -TaskName 'WarshipPilot-LauncherMigration'
        $newHealth=Wait-Healthy ($TimeoutMinutes*60)
        $after=Invoke-Console state $null
        if ($after.automation.scheduler -ne $state.automation.scheduler) { throw 'Scheduler state changed during migration' }
        foreach ($shortcut in $shortcuts) {
            $link=$shell.CreateShortcut($shortcut.path)
            $link.TargetPath="$Root\WarshipPilot.exe"; $link.Arguments=''; $link.WorkingDirectory=$Root; $link.Save()
        }
        if (!(Test-Path -LiteralPath $run)) { New-Item -Path $run -Force | Out-Null }
        Set-ItemProperty -LiteralPath $run -Name WarshipPilot -Value ('"'+$Root+'\WarshipPilot.exe" --start-minimized')
        @{ok=$true;root=$Root;backup=$backup;pid=$newHealth.pid;commit=$newHealth.commit;scheduler=$after.automation.scheduler;due=$after.automation.due} | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath "$backup\acceptance.json" -Encoding UTF8
        Write-Output "Migration verified; recovery backup: $backup"
    } catch {
        $original=$_
        Restore-Migration $backup
        throw $original
    }
} finally {
    try { Invoke-Console launcher-cancel @{} | Out-Null } catch {}
    Pop-Location
}
