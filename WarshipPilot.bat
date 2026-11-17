@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Missing runtime. Deploy with WarshipPilot.exe (WarshipPilotLauncher) first.
  pause
  exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "deploy\launcher\rebase-runtime.ps1" -Root "%CD%"
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m deploy.installer --restart --wait-gui %*
if errorlevel 1 (
  echo Startup failed. See log\installer-error.txt
  pause
  exit /b 1
)
