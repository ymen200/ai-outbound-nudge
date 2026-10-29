@echo off
title Full Testing Environment
color 0A

echo.
echo ╔══════════════════════════════════════════════════════════╗
echo ║   OUTREACH PROJECT - FULL TESTING ENVIRONMENT          ║
echo ║   Starting all services + opening interfaces...        ║
echo ╚══════════════════════════════════════════════════════════╝
echo.

:: ── Cleanup: kill stale processes from previous runs ───────
echo [*] Cleaning up stale processes on ports 8000, 8001, 8002...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000 " 2^>nul') do taskkill /F /PID %%a >nul 2>nul
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8001 " 2^>nul') do taskkill /F /PID %%a >nul 2>nul
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8002 " 2^>nul') do taskkill /F /PID %%a >nul 2>nul
taskkill /F /FI "WINDOWTITLE eq Message Generator" >nul 2>nul
taskkill /F /FI "WINDOWTITLE eq Sequence Generator" >nul 2>nul
taskkill /F /FI "WINDOWTITLE eq Outreach Orchestrator" >nul 2>nul
taskkill /F /FI "WINDOWTITLE eq Temporal Server" >nul 2>nul
taskkill /F /FI "WINDOWTITLE eq Temporal Worker" >nul 2>nul
echo     Ports cleared.
echo.

:: ── Check Temporal CLI ──────────────────────────────────────
where temporal >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [!] WARNING: Temporal CLI not found.
    echo     Install with: winget install temporalio.cli
    echo     Skipping Temporal server and worker.
    echo.
    set SKIP_TEMPORAL=1
) else (
    set SKIP_TEMPORAL=0
)

:: ── [1/5] Temporal Dev Server ──────────────────────────────
if %SKIP_TEMPORAL%==0 (
    echo [1/5] Starting Temporal Dev Server on port 7233...
    start "Temporal Server" cmd /k "temporal server start-dev"
    echo      Temporal Server STARTED
    timeout /t 3 /nobreak >nul
) else (
    echo [1/5] Skipping Temporal Server (CLI not installed)
)

echo.

:: ── [2/5] Message Generator API ────────────────────────────
echo [2/5] Starting Message Generator API on port 8000...
cd /d "c:\Users\ASUS\Desktop\Outreach-Project\message generator and sender"
start "Message Generator" cmd /k "call .\venv\Scripts\activate.bat && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000"
echo      Message Generator STARTED on port 8000
timeout /t 3 /nobreak >nul

echo.

:: ── [3/5] Sequence Generator API ───────────────────────────
echo [3/5] Starting Sequence Generator API on port 8001...
cd /d "c:\Users\ASUS\Desktop\Outreach-Project\sequence generator"
start "Sequence Generator" cmd /k "call .\venv\Scripts\activate.bat && python -m uvicorn scripts.api_server:app --host 0.0.0.0 --port 8001"
echo      Sequence Generator STARTED on port 8001
timeout /t 3 /nobreak >nul

echo.

:: ── [4/5] Outreach Orchestrator ────────────────────────────
echo [4/5] Starting Outreach Orchestrator on port 8002...
cd /d "c:\Users\ASUS\Desktop\Outreach-Project\outreach orchestrator"
start "Outreach Orchestrator" cmd /k "call ..\venv\Scripts\activate.bat && python -m uvicorn app.main:app --host 0.0.0.0 --port 8002"
echo      Outreach Orchestrator STARTED on port 8002
timeout /t 3 /nobreak >nul

echo.

:: ── [5/5] Temporal Worker ──────────────────────────────────
if %SKIP_TEMPORAL%==0 (
    echo [5/5] Starting Temporal Worker...
    cd /d "c:\Users\ASUS\Desktop\Outreach-Project\sequence generator"
    start "Temporal Worker" cmd /k "call .\venv\Scripts\activate.bat && python scripts/worker.py"
    echo      Temporal Worker STARTED
) else (
    echo [5/5] Skipping Temporal Worker (CLI not installed)
)

echo.

:: ── Wait for services to finish booting ────────────────────
echo Waiting for services to finish starting up...
timeout /t 5 /nobreak >nul

:: ── Open all interfaces in browser ─────────────────────────
echo.
echo ── Opening interfaces in your browser... ──
echo.

if %SKIP_TEMPORAL%==0 (
    echo   [Browser] Temporal Web UI        → http://localhost:8080
    start "" "http://localhost:8080"
)

echo   [Browser] Message Generator Docs → http://localhost:8000/docs
start "" "http://localhost:8000/docs"

echo   [Browser] Sequence Generator Docs→ http://localhost:8001/docs
start "" "http://localhost:8001/docs"

echo   [Browser] Orchestrator Docs      → http://localhost:8002/docs
start "" "http://localhost:8002/docs"

echo.
echo ╔══════════════════════════════════════════════════════════╗
echo ║   ALL SERVICES RUNNING - Interfaces opened above       ║
echo ╠══════════════════════════════════════════════════════════╣
echo ║                                                        ║
echo ║   Interfaces opened:                                   ║
if %SKIP_TEMPORAL%==0 (
echo ║     Temporal Web UI:      http://localhost:8080        ║
)
echo ║     Message Generator:    http://localhost:8000/docs   ║
echo ║     Sequence Generator:   http://localhost:8001/docs   ║
echo ║     Orchestrator:         http://localhost:8002/docs   ║
echo ║                                                        ║
echo ║   Quick test:                                          ║
echo ║     POST to http://localhost:8002/api/run              ║
echo ║     with your test payload from TESTING_GUIDE.md       ║
echo ║                                                        ║
echo ║   Press any key in THIS window to STOP all services    ║
echo ╚══════════════════════════════════════════════════════════╝
echo.
pause >nul

:: ── Shutdown all services ──────────────────────────────────
echo.
echo Shutting down all services...
taskkill /F /FI "WINDOWTITLE eq Message Generator" >nul 2>nul
taskkill /F /FI "WINDOWTITLE eq Sequence Generator" >nul 2>nul
taskkill /F /FI "WINDOWTITLE eq Outreach Orchestrator" >nul 2>nul
taskkill /F /FI "WINDOWTITLE eq Temporal Server" >nul 2>nul
taskkill /F /FI "WINDOWTITLE eq Temporal Worker" >nul 2>nul
echo All services stopped.
echo.
pause
