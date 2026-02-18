@echo off
setlocal

set "BASE_DIR=%~dp0"
cd /d "%BASE_DIR%"

if not exist ".venv\Scripts\python.exe" (
  echo [Setup] Creating virtual environment...
  python -m venv .venv
)

if not exist ".venv\Scripts\python.exe" (
  echo [Error] Python venv creation failed.
  pause
  exit /b 1
)

echo [Run] Launching Web UI...
".venv\Scripts\python.exe" -m pip install -r requirements.txt >nul 2>nul
start "" "http://127.0.0.1:5842"
".venv\Scripts\python.exe" webapp.py

endlocal
