[CmdletBinding()]
param([string]$ComputerName = 'DESKTOP-3F63TNA', [string]$OutputRoot = 'dist-v0.4')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$releasePath = Join-Path $projectRoot "$OutputRoot\WarshipPilot"
$zipPath = Join-Path $projectRoot "$OutputRoot\WarshipPilot-0.4.0-win-x64.zip"
if (!(Test-Path -LiteralPath "$releasePath\WarshipPilot.exe")) { throw 'Build the EXE first' }
Add-Type -AssemblyName System.IO.Compression.FileSystem
if (Test-Path -LiteralPath $zipPath) { Remove-Item -LiteralPath $zipPath }
[IO.Compression.ZipFile]::CreateFromDirectory($releasePath, $zipPath, [IO.Compression.CompressionLevel]::Optimal, $false)
$credentialPath = Join-Path $env:LOCALAPPDATA "Codex\Credentials\$ComputerName.xml"
$credential = Import-Clixml -LiteralPath $credentialPath
$session = New-PSSession -ComputerName $ComputerName -Credential $credential
try {
    Invoke-Command -Session $session -ScriptBlock {
        if (Test-Path -LiteralPath 'D:\WarshipPilot') { throw 'D:\WarshipPilot already exists; stop and back it up before upgrading' }
    }
    Copy-Item -LiteralPath $zipPath -Destination 'D:\WarshipPilot-0.4.0-win-x64.zip' -ToSession $session
    Invoke-Command -Session $session -ScriptBlock {
        $ErrorActionPreference = 'Stop'
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        [IO.Compression.ZipFile]::ExtractToDirectory('D:\WarshipPilot-0.4.0-win-x64.zip', 'D:\WarshipPilot')
        $action = New-ScheduledTaskAction -Execute 'D:\WarshipPilot\WarshipPilot.exe' -Argument '--host 0.0.0.0 --no-browser' -WorkingDirectory 'D:\WarshipPilot'
        $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
        $desktopUser = (Get-CimInstance Win32_ComputerSystem).UserName
        if (!$desktopUser) { throw 'MuMu IPC requires a logged-in desktop user' }
        $principal = New-ScheduledTaskPrincipal -UserId $desktopUser -LogonType Interactive -RunLevel Highest
        $trigger = New-ScheduledTaskTrigger -AtLogOn -User $desktopUser
        Register-ScheduledTask -TaskName 'WarshipPilot-Preview' -Action $action -Settings $settings -Principal $principal -Trigger $trigger | Out-Null
        if (!(Get-NetFirewallRule -Name 'WarshipPilot-LAN' -ErrorAction SilentlyContinue)) {
            New-NetFirewallRule -Name 'WarshipPilot-LAN' -DisplayName 'WarshipPilot LAN preview' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 22680 -RemoteAddress LocalSubnet -Program 'D:\WarshipPilot\WarshipPilot.exe' | Out-Null
        }
        Start-ScheduledTask -TaskName 'WarshipPilot-Preview'
        $desktop = [Environment]::GetFolderPath('Desktop')
        $shell = New-Object -ComObject WScript.Shell
        $shortcut = $shell.CreateShortcut((Join-Path $desktop 'WarshipPilot.lnk'))
        $shortcut.TargetPath = 'D:\WarshipPilot\WarshipPilot.exe'
        $shortcut.Arguments = '--host 0.0.0.0'
        $shortcut.WorkingDirectory = 'D:\WarshipPilot'
        $shortcut.Save()
        Write-Output 'Installed D:\WarshipPilot; started scheduled background task WarshipPilot-Preview'
    }
} finally { Remove-PSSession $session }
