@echo off
rem Launches the INTVAL web workbench and opens it in your default browser.
rem Double-click this file. Close this window (or press Ctrl+C) to stop the server.

setlocal
cd /d "%~dp0"
title INTVAL Workbench
set "PORT=8765"
set "URL=http://127.0.0.1:%PORT%"

rem Already running? Just open the browser.
powershell -NoProfile -Command "try { (Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 '%URL%') | Out-Null; exit 0 } catch { exit 1 }" >nul 2>&1
if not errorlevel 1 (
    echo Workbench is already running at %URL%
    start "" "%URL%"
    exit /b 0
)

rem Prefer the project's virtual environment.
set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"

rem Build the web UI once if it hasn't been built yet.
if not exist "web\dist\index.html" (
    echo Building the web UI for the first time...
    pushd web
    if not exist "node_modules" call npm install || goto :fail
    call npm run build || goto :fail
    popd
)

echo Starting INTVAL Workbench at %URL% ...
"%PY%" run.py --web --port %PORT%
if errorlevel 1 goto :fail
exit /b 0

:fail
echo.
echo Something went wrong. See the messages above.
pause
exit /b 1
