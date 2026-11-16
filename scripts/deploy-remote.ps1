[CmdletBinding()]
param(
    [string]$ComputerName = 'DESKTOP-3F63TNA',
    [string]$RuntimeRoot = '.runtime-stage\portable',
    [string]$Repository = 'https://ghfast.top/https://github.com/a2893005741/WarshipPilot.git'
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$branch = (& git -C $root branch --show-current).Trim()
$commit = (& git -C $root rev-parse HEAD).Trim()
$origin = (& git -C $root remote get-url origin).Trim()
if (& git -C $root status --porcelain) { throw 'Commit source changes before deployment' }
if (![IO.Path]::IsPathRooted($RuntimeRoot)) { $RuntimeRoot = Join-Path $root $RuntimeRoot }
if (!(Test-Path -LiteralPath "$RuntimeRoot\.venv\python\python.exe")) { throw 'Prepare the portable runtime first' }
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$work = Join-Path $root ".deployment\$stamp"
$checkout = Join-Path $work 'WarshipPilot'
New-Item -ItemType Directory -Path $work -Force | Out-Null
& git clone --no-hardlinks --single-branch --branch $branch $root $checkout
if ($LASTEXITCODE) { throw 'Source clone failed' }
& git -C $checkout remote set-url origin $origin
Copy-Item -LiteralPath "$RuntimeRoot\.venv" -Destination "$checkout\.venv" -Recurse
Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive = Join-Path $work 'source-runtime.zip'
[IO.Compression.ZipFile]::CreateFromDirectory($checkout,$archive,[IO.Compression.CompressionLevel]::Fastest,$false)
$digest = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash
$credential = Import-Clixml -LiteralPath (Join-Path $env:LOCALAPPDATA "Codex\Credentials\$ComputerName.xml")
$session = New-PSSession -ComputerName $ComputerName -Credential $credential
try {
    $remoteArchive = "D:\WarshipPilot-source-$stamp.zip"
    Copy-Item -LiteralPath $archive -Destination $remoteArchive -ToSession $session
    $receipt = Invoke-Command -Session $session -ArgumentList $remoteArchive,$stamp,$digest,$branch,$commit,$Repository -ScriptBlock {
        param($archive,$stamp,$digest,$branch,$commit,$repository)
        $ErrorActionPreference = 'Stop'
        $live = 'D:\WarshipPilot'
        $stage = "D:\WarshipPilot-source-stage-$stamp"
        $backup = "D:\WarshipPilot-source-backup-$stamp"
        foreach ($path in @($live,$stage,$backup)) {
            if ([IO.Path]::GetFullPath($path) -notmatch '^D:\\WarshipPilot(?:-source-(?:stage|backup)-[0-9-]+)?$') { throw 'Unexpected deployment path' }
        }
        if ((Get-FileHash -LiteralPath $archive).Hash -ne $digest) { throw 'Archive checksum mismatch' }
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        [IO.Compression.ZipFile]::ExtractToDirectory($archive,$stage)
        & "$stage\deploy\launcher\rebase-runtime.ps1" -Root $stage
        & "$stage\.venv\Scripts\python.exe" -c 'import sys,cv2,lupa.lua52,yaml; assert sys.base_prefix.startswith(sys.argv[1]); print(sys.version)' $stage
        if ($LASTEXITCODE) { throw 'Portable runtime does not work on remote machine' }
        & "$stage\.venv\git\cmd\git.exe" -C $stage fetch --no-tags $repository "+refs/heads/${branch}:refs/remotes/origin/$branch"
        if ($LASTEXITCODE) { throw 'Remote Git update source is unavailable; old installation untouched' }
        $fetched = (& "$stage\.venv\git\cmd\git.exe" -C $stage rev-parse "refs/remotes/origin/$branch").Trim()
        if ($fetched -ne $commit) { throw 'Update source has not reached the deployed commit' }
        $oldTask = Get-ScheduledTask -TaskName 'WarshipPilot-Preview' -ErrorAction SilentlyContinue
        New-Item -ItemType Directory -Path "$stage\log" -Force | Out-Null
        if ($oldTask) { Export-ScheduledTask -TaskName $oldTask.TaskName | Set-Content -LiteralPath "$stage\log\task-backup.xml" -Encoding UTF8 }
        $listener = Get-NetTCPConnection -LocalPort 22680 -State Listen | Select-Object -First 1
        $oldProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)"
        $oldExecutable = $oldProcess.ExecutablePath
        $activeFolder = Split-Path $oldExecutable -Parent
        $oldData = if (Test-Path -LiteralPath "$activeFolder\data\access.json") { "$activeFolder\data" } elseif (Test-Path -LiteralPath "$live\data\access.json") { "$live\data" } else { 'D:\WarshipPilot-data' }
        $key = (Get-Content -LiteralPath "$oldData\access.json" -Raw | ConvertFrom-Json).key
        $headers = @{Authorization="Bearer $key"}
        $idle = $false
        for ($i=0;$i -lt 240;$i++) {
            $state = Invoke-RestMethod 'http://127.0.0.1:22680/api/state' -Headers $headers -TimeoutSec 10
            if (!$state.automation.running -and !$state.device.benchmark.running) { $idle=$true;break }
            Start-Sleep -Milliseconds 500
        }
        if (!$idle) { throw 'Current task is still running; old installation untouched' }
        Invoke-RestMethod 'http://127.0.0.1:22680/api/shutdown' -Method Post -Headers $headers -ContentType 'application/json' -Body '{}' | Out-Null
        for ($i=0;$i -lt 80;$i++) {
            try { $null=Invoke-RestMethod 'http://127.0.0.1:22680/health' -TimeoutSec 1 } catch { break }
            Start-Sleep -Milliseconds 250
        }
        if ($oldTask) { Stop-ScheduledTask -TaskName $oldTask.TaskName }
        # A directory rename preserves the full old installation, including data.
        Move-Item -LiteralPath $live -Destination $backup
        try {
            Move-Item -LiteralPath $stage -Destination $live
            & "$live\deploy\launcher\rebase-runtime.ps1" -Root $live
            $setup = @'
import sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from module.config.migration import migrate
from module.config.config import Config
root,backup=map(Path,sys.argv[1:3])
migrate(root,[Path(sys.argv[5]),backup/'data',Path('D:/WarshipPilot-data')])
c=Config(root);d=c.deploy()
d['Git'].update(Branch=sys.argv[3],Repository=sys.argv[4])
d['Adb']['Executable']='.venv/adb/adb.exe'
c.save_deploy(d)
'@
            $migrationSource = if ($oldData -eq "$live\data") { "$backup\data" } else { $oldData }
            $setup | & "$live\.venv\Scripts\python.exe" - $live $backup $branch $repository $migrationSource
            if ($LASTEXITCODE) { throw 'Configuration migration failed' }
            $desktopUser = (Get-CimInstance Win32_ComputerSystem).UserName
            if (!$desktopUser) { throw 'MuMu IPC needs a logged-in desktop user' }
            # Keep the task alive through the hidden cmd wrapper; Pythonw is monitored by installer.
            $action = New-ScheduledTaskAction -Execute 'wscript.exe' -Argument ('"'+$live+'\deploy\launcher\hidden.vbs" --no-browser') -WorkingDirectory $live
            $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
            $principal = New-ScheduledTaskPrincipal -UserId $desktopUser -LogonType Interactive -RunLevel Highest
            $trigger = New-ScheduledTaskTrigger -AtLogOn -User $desktopUser
            Register-ScheduledTask -TaskName 'WarshipPilot-Preview' -Action $action -Settings $settings -Principal $principal -Trigger $trigger -Force | Out-Null
            Get-NetFirewallRule -Name 'WarshipPilot-LAN' -ErrorAction SilentlyContinue | Remove-NetFirewallRule
            New-NetFirewallRule -Name 'WarshipPilot-LAN' -DisplayName 'WarshipPilot LAN' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 22680 -RemoteAddress LocalSubnet -Program "$live\.venv\Scripts\pythonw.exe" | Out-Null
            Start-ScheduledTask -TaskName 'WarshipPilot-Preview'
            $healthy=$false
            for ($i=0;$i -lt 120;$i++) {
                try { $health=Invoke-RestMethod 'http://127.0.0.1:22680/health' -TimeoutSec 1; if ($health.commit -eq $commit) { $healthy=$true;break } } catch {}
                Start-Sleep -Milliseconds 500
            }
            if (!$healthy) { throw 'Source GUI failed to start' }
            $shell=New-Object -ComObject WScript.Shell
            $shortcut=$shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) 'WarshipPilot.lnk'))
            $shortcut.TargetPath='wscript.exe'
            $shortcut.Arguments='"'+$live+'\deploy\launcher\hidden.vbs"'
            $shortcut.WorkingDirectory=$live
            $shortcut.Save()
            [pscustomobject]@{Commit=$commit;Branch=$branch;Backup=$backup;Health=$health;DataSource=$oldData}
        } catch {
            Stop-ScheduledTask -TaskName 'WarshipPilot-Preview' -ErrorAction SilentlyContinue
            $failed="D:\WarshipPilot-source-stage-$stamp-failed"
            if ([IO.Path]::GetFullPath($failed) -notmatch '^D:\\WarshipPilot-source-stage-[0-9-]+-failed$') { throw 'Unexpected failed path' }
            Get-CimInstance Win32_Process | Where-Object {$_.ExecutablePath -in @("$live\.venv\Scripts\python.exe","$live\.venv\Scripts\pythonw.exe")} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
            Move-Item -LiteralPath $live -Destination $failed
            Move-Item -LiteralPath $backup -Destination $live
            if (Test-Path -LiteralPath "$failed\log\task-backup.xml") { Register-ScheduledTask -TaskName 'WarshipPilot-Preview' -Xml (Get-Content -LiteralPath "$failed\log\task-backup.xml" -Raw) -Force | Out-Null }
            Start-ScheduledTask -TaskName 'WarshipPilot-Preview'
            throw
        }
    }
    $receipt | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath "$work\receipt.json" -Encoding UTF8
    $receipt
} finally { Remove-PSSession $session }
