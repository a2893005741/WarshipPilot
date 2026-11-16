[CmdletBinding()]
param([int]$TapX = -1, [int]$TapY = -1, [int]$SwipeY1 = -1, [int]$SwipeY2 = -1, [string]$Output = 'evidence\live-inspection.png')
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$cred = Import-Clixml -LiteralPath (Join-Path $env:LOCALAPPDATA 'Codex\Credentials\DESKTOP-3F63TNA.xml')
$session = New-PSSession -ComputerName DESKTOP-3F63TNA -Credential $cred
try {
    Invoke-Command -Session $session -ArgumentList $TapX,$TapY,$SwipeY1,$SwipeY2 -ScriptBlock {
        param($x,$y,$sy1,$sy2)
        $adb = 'D:\WarshipPilot\_internal\adb\adb.exe'
        $serial = '127.0.0.1:16416'
        if ($x -ge 0 -or $sy1 -ge 0) {
            if ($x -ge 1280 -or ($x -ge 0 -and ($y -lt 0 -or $y -ge 720))) { throw 'Outside image' }
            $activity = & $adb -s $serial shell dumpsys activity activities
            if (!(($activity | Select-String 'ResumedActivity') -match 'com.huanmeng.zhanjian2/')) { throw 'Game is not foreground' }
            $processes = & $adb -s $serial shell ps -A
            if ($processes -match 'com.mcmpnknkmcmlmkno.shipwarrliverfree|frida-server') { throw 'Legacy script/probe still running' }
            if ($sy1 -ge 0) {
                if ($sy1 -ge 720 -or $sy2 -lt 0 -or $sy2 -ge 720) { throw 'Outside image' }
                & $adb -s $serial shell input swipe 145 $sy1 145 $sy2 450 | Out-Null
            } else { & $adb -s $serial shell input tap $x $y | Out-Null }
            if ($LASTEXITCODE) { throw 'Input failed' }
            # Flush the frame submitted before Unity processed the input.
            & $adb -s $serial shell screencap /dev/null | Out-Null
        }
        $p = New-Object Diagnostics.Process
        $p.StartInfo = New-Object Diagnostics.ProcessStartInfo
        $p.StartInfo.FileName = $adb
        $p.StartInfo.Arguments = "-s $serial exec-out screencap -p"
        $p.StartInfo.UseShellExecute = $false
        $p.StartInfo.CreateNoWindow = $true
        $p.StartInfo.RedirectStandardOutput = $true
        $p.StartInfo.RedirectStandardError = $true
        $null = $p.Start()
        $memory = New-Object IO.MemoryStream
        $p.StandardOutput.BaseStream.CopyTo($memory)
        if (!$p.WaitForExit(20000) -or $p.ExitCode) { throw 'Screenshot failed' }
        New-Item -ItemType Directory -Path 'D:\WarshipPilot-dev' -Force | Out-Null
        [IO.File]::WriteAllBytes('D:\WarshipPilot-dev\latest.png',$memory.ToArray())
        $p.Dispose()
        $memory.Dispose()
    }
    Copy-Item -FromSession $session -LiteralPath 'D:\WarshipPilot-dev\latest.png' -Destination (Join-Path $root $Output) -Force
    Write-Output (Join-Path $root $Output)
} finally { Remove-PSSession $session }
