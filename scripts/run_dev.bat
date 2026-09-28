@echo off
title Crowdfunding Enterprise CRM - Network Dev Mode
color 0B

echo =======================================================================
echo   Launching Enterprise CRM (Network Accessible: Vite + FastAPI)
echo =======================================================================
echo.
echo [INFO] Finding Local Network IP Addresses...
for /f "tokens=4" %%a in ('route print ^| find " 0.0.0.0"') do (
    set LOCAL_IP=%%a
)
echo Local IP: %LOCAL_IP%
echo.
echo -----------------------------------------------------------------------
echo   Access Links:
echo   - Localhost (This PC): http://localhost:5173
echo   - Network (Other PCs/Mobiles): http://%LOCAL_IP%:5173
echo -----------------------------------------------------------------------
echo.

echo [1/2] Launching React Vite Dev Server on all network interfaces (0.0.0.0:5173)...
start "React Vite Frontend (Network Mode)" cmd /k "cd frontend && npm run dev -- --host"

echo [2/2] Launching FastAPI Backend Engine on all interfaces (0.0.0.0:8000)...
timeout /t 2 >nul
start "" http://localhost:5173

python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload

pause
