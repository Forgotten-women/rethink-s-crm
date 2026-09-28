@echo off
title Crowdfunding Enterprise CRM - Full Stack Launcher
color 0A

echo ========================================================
echo   Crowdfunding Enterprise CRM (FastAPI + React Vite)
echo ========================================================
echo.

echo [1/3] Building React Frontend static assets...
cd frontend
call npm run build
if %errorlevel% neq 0 (
    echo [ERROR] Frontend build failed!
    pause
    exit /b %errorlevel%
)
cd ..

echo.
echo [2/3] Opening browser at http://127.0.0.1:8000 ...
start "" http://127.0.0.1:8000

echo.
echo [3/3] Launching FastAPI Backend Engine on http://127.0.0.1:8000 ...
echo Press CTRL+C in this window to stop the server anytime.
echo.

python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload

pause
