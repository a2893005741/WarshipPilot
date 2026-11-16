$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$credential = Import-Clixml -LiteralPath (Join-Path $env:LOCALAPPDATA 'Codex\Credentials\DESKTOP-3F63TNA.xml')
$session = New-PSSession -ComputerName DESKTOP-3F63TNA -Credential $credential
try {
    while ($null -ne ($line = [Console]::ReadLine())) {
        try {
            $request = $line | ConvertFrom-Json
            $answer = Invoke-Command -Session $session -ArgumentList $request -ScriptBlock {
                param($request)
                $ErrorActionPreference = 'Stop'
                $adb = 'D:\WarshipPilot\_internal\adb\adb.exe'
                $serial = '127.0.0.1:16416'
                if ($request.operation -eq 'check') {
                    $activity = & $adb -s $serial shell dumpsys activity activities
                    if (!(($activity | Select-String 'ResumedActivity') -match 'com.huanmeng.zhanjian2/')) { throw 'Game is not foreground' }
                    $processes = & $adb -s $serial shell ps -A
                    if ($processes -match 'com.mcmpnknkmcmlmkno.shipwarrliverfree|frida-server') { throw 'Legacy input owner still running' }
                    return @{ok=$true}
                }
                if ($request.operation -eq 'tap' -or $request.operation -eq 'swipe') {
                    $values = @($request.values | ForEach-Object { [string][int]$_ })
                    & $adb -s $serial shell input $request.operation @values | Out-Null
                    if ($LASTEXITCODE) { throw 'ADB input failed' }
                    return @{ok=$true}
                }
                if ($request.operation -ne 'frame') { throw 'Unsupported bridge operation' }
                $process = New-Object Diagnostics.Process
                $process.StartInfo = New-Object Diagnostics.ProcessStartInfo
                $process.StartInfo.FileName = $adb
                $process.StartInfo.Arguments = "-s $serial exec-out screencap -p"
                $process.StartInfo.UseShellExecute = $false
                $process.StartInfo.CreateNoWindow = $true
                $process.StartInfo.RedirectStandardOutput = $true
                $process.StartInfo.RedirectStandardError = $true
                $null = $process.Start()
                $memory = New-Object IO.MemoryStream
                $process.StandardOutput.BaseStream.CopyTo($memory)
                if (!$process.WaitForExit(20000) -or $process.ExitCode) { throw 'Screenshot failed' }
                $encoded = [Convert]::ToBase64String($memory.ToArray())
                $process.Dispose()
                $memory.Dispose()
                return @{png=$encoded}
            }
            [Console]::WriteLine(($answer | ConvertTo-Json -Compress -Depth 5))
        } catch {
            [Console]::WriteLine((@{error=$_.Exception.Message} | ConvertTo-Json -Compress))
        }
    }
} finally { Remove-PSSession $session }
