[CmdletBinding()]
param(
    [string]$Destination = '.runtime-stage\portable',
    [string]$AdbDirectory = 'C:\adb',
    [string]$GitDirectory = 'C:\Program Files\Git'
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
if (![IO.Path]::IsPathRooted($Destination)) { $Destination = Join-Path $root $Destination }
$Destination = [IO.Path]::GetFullPath($Destination)
$runtime = Join-Path $Destination '.venv'
if (Test-Path -LiteralPath $runtime) { throw "Destination already exists: $runtime" }
$uv = (Get-Command uv).Source
$base = (& $uv python find --system 3.14).Trim()
if ($LASTEXITCODE) { throw 'Python 3.14 is unavailable' }
$baseDirectory = Split-Path $base -Parent
if (!(Test-Path -LiteralPath "$baseDirectory\Lib\encodings\__init__.py")) { throw 'Python standard library is missing' }
& $uv venv --relocatable --python $base $runtime
if ($LASTEXITCODE) { throw 'venv creation failed' }
$previousEnvironment = $env:UV_PROJECT_ENVIRONMENT
try {
    $env:UV_PROJECT_ENVIRONMENT = $runtime
    & $uv sync --frozen --no-dev --link-mode copy --project $root
    if ($LASTEXITCODE) { throw 'Locked dependency installation failed' }
} finally { $env:UV_PROJECT_ENVIRONMENT = $previousEnvironment }
Copy-Item -LiteralPath $baseDirectory -Destination "$runtime\python" -Recurse
# uv's Windows redirectors embed the build computer's interpreter path.
# Use the real interpreter with adjacent DLLs; pyvenv.cfg supplies its bundled stdlib.
Copy-Item -LiteralPath "$runtime\python\python.exe","$runtime\python\pythonw.exe" -Destination "$runtime\Scripts" -Force
Get-ChildItem -LiteralPath "$runtime\python" -Filter '*.dll' | Copy-Item -Destination "$runtime\Scripts" -Force
Copy-Item -LiteralPath $uv -Destination "$runtime\uv.exe"
New-Item -ItemType Directory -Path "$runtime\git","$runtime\adb" -Force | Out-Null
foreach ($folder in @('cmd','mingw64','usr','etc')) {
    Copy-Item -LiteralPath (Join-Path $GitDirectory $folder) -Destination "$runtime\git\$folder" -Recurse
}
Copy-Item -LiteralPath (Join-Path $GitDirectory 'LICENSE.txt') -Destination "$runtime\git"
& "$runtime\git\cmd\git.exe" config --file "$runtime\git\etc\gitconfig" http.sslBackend schannel
if ($LASTEXITCODE) { throw 'Portable Git certificate configuration failed' }
& "$runtime\git\cmd\git.exe" config --file "$runtime\git\etc\gitconfig" http.schannelUseSSLCAInfo false
if ($LASTEXITCODE) { throw 'Portable Git trust configuration failed' }
foreach ($file in @('adb.exe','AdbWinApi.dll','AdbWinUsbApi.dll')) {
    Copy-Item -LiteralPath (Join-Path $AdbDirectory $file) -Destination "$runtime\adb"
}
& "$root\deploy\launcher\rebase-runtime.ps1" -Root $Destination
& "$runtime\Scripts\python.exe" -c 'import sys,cv2,lupa.lua52,yaml,uvicorn; assert sys.version_info[:2] == (3,14); print(sys.base_prefix)'
if ($LASTEXITCODE) { throw 'Portable Python check failed' }
$probeScript = @'
import hashlib,sys
from pathlib import Path
root,runtime=map(Path,sys.argv[1:])
(runtime/'.warship-lock').write_text(hashlib.sha256((root/'uv.lock').read_bytes()+(root/'pyproject.toml').read_bytes()).hexdigest(),encoding='utf-8')
'@
$probeScript | & "$runtime\Scripts\python.exe" - $root $runtime
if ($LASTEXITCODE) { throw 'Dependency fingerprint failed' }
& "$runtime\git\cmd\git.exe" --version
& "$runtime\adb\adb.exe" version
Write-Output "Portable runtime prepared: $runtime"
