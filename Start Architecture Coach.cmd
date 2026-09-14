@echo off
set "HOME=%USERPROFILE%"
cd /d "%~dp0"
python -m archcoach serve
if errorlevel 1 (
  echo.
  echo Architecture Coach could not start. Run install.cmd first.
  pause
)

