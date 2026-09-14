@echo off
set "HOME=%USERPROFILE%"
cd /d "%~dp0"
python -m pip install -e ".[dev]"
where npm >nul 2>nul
if not errorlevel 1 (
  npm install
) else (
  for /d %%D in ("%USERPROFILE%\.cache\codex-runtimes\*") do if exist "%%D\dependencies\bin\fallback\pnpm.cmd" call "%%D\dependencies\bin\fallback\pnpm.cmd" install
)
echo.
echo Installation complete. Double-click "Start Architecture Coach.cmd".
pause
