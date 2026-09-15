@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_CMD="
python -c "import sys; assert sys.version_info[:2] == (3, 12)" >nul 2>nul
if not errorlevel 1 set "PYTHON_CMD=python"
if not defined PYTHON_CMD (
  py -3.12 -c "import sys; assert sys.version_info[:2] == (3, 12)" >nul 2>nul
  if not errorlevel 1 set "PYTHON_CMD=py -3.12"
)
if not defined PYTHON_CMD (
  echo ERROR: Python 3.12 is required and was not found.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  %PYTHON_CMD% -m venv .venv
  if errorlevel 1 goto :failed
)

".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :failed
".venv\Scripts\python.exe" -m pip install -r requirements.lock
if errorlevel 1 goto :failed
".venv\Scripts\python.exe" -m pip install -e . --no-deps --no-build-isolation
if errorlevel 1 goto :failed

where pnpm >nul 2>nul
if not errorlevel 1 (
  call pnpm install --frozen-lockfile
  if errorlevel 1 goto :failed
  goto :installed
)

for /d %%D in ("%USERPROFILE%\.cache\codex-runtimes\*") do (
  if exist "%%D\dependencies\bin\fallback\pnpm.cmd" (
    call "%%D\dependencies\bin\fallback\pnpm.cmd" install --frozen-lockfile
    if errorlevel 1 goto :failed
    goto :installed
  )
)

echo ERROR: pnpm was not found. Install pnpm, or install Codex with its bundled runtime, then retry.
pause
exit /b 1

:installed
".venv\Scripts\archcoach.exe" doctor
if errorlevel 1 goto :failed
echo.
echo Installation complete. Double-click "Start Architecture Coach.cmd".
pause
exit /b 0

:failed
echo.
echo ERROR: Installation did not complete. Fix the error above and run install.cmd again.
pause
exit /b 1
