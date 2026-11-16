param([string]$Root = (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent))
$ErrorActionPreference = 'Stop'
$runtime = Join-Path $Root '.venv'
$configuration = Join-Path $runtime 'pyvenv.cfg'
if (!(Test-Path -LiteralPath "$runtime\python\python.exe")) { throw 'Bundled Python is missing' }
$content = [IO.File]::ReadAllText($configuration)
$content = [regex]::Replace($content, '(?m)^home = .*$', ('home = ' + (Join-Path $runtime 'python')))
[IO.File]::WriteAllText($configuration, $content, [Text.UTF8Encoding]::new($false))
