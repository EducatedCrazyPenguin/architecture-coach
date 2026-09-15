@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\archcoach.exe" (
  echo Architecture Coach is not installed. Run install.cmd first.
  pause
  exit /b 1
)
".venv\Scripts\archcoach.exe" serve
if errorlevel 1 (
  echo.
  echo Architecture Coach could not start. Run install.cmd to repair the local environment.
  pause
  exit /b 1
)
