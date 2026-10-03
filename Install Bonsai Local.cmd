@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run install.cmd to install Architecture Coach first.
  exit /b 1
)
".venv\Scripts\python.exe" -m archcoach.bonsai install %*
if errorlevel 1 exit /b 1
