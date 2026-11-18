@echo off
setlocal

title GiveBrite Payout Enrichment Tool
echo ============================================================
echo   GiveBrite Payouts and Transfers Donor Data Enrichment
echo ============================================================
echo.

cd /d "%~dp0"

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not found on your system or not added to PATH.
    echo Please install Python 3 and ensure Add Python to PATH is checked.
    echo.
    pause
    exit /b 1
)

echo Checking dependencies: pandas and openpyxl...
python -c "import pandas, openpyxl" >nul 2>&1
if %errorlevel% neq 0 (
    echo Installing required packages: pandas openpyxl...
    pip install pandas openpyxl
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to install pandas and openpyxl.
        echo.
        pause
        exit /b 1
    )
)

echo Dependencies verified.
echo.
echo Running donor metadata enrichment...
echo ------------------------------------------------------------

python "%~dp0enrich_transfers_from_main_donors.py"

echo.
echo ============================================================
echo   Execution Finished
echo ============================================================
echo.
pause
