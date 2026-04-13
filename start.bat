@echo off
echo ========================================
echo   Auto-Pricer Worker - Auto-Restart
echo ========================================
:loop
echo.
echo [%date% %time%] Pulling latest code...
git pull origin main
echo [%date% %time%] Activating virtual environment...
if not exist "venv" (
    echo [%date% %time%] Creating virtual environment...
    python -m venv venv
)
call venv\Scripts\activate
echo [%date% %time%] Installing dependencies...
pip install -q -r requirements.txt
echo [%date% %time%] Starting worker...
python worker.py
echo.
echo [%date% %time%] Worker exited. Restarting in 3 seconds...
timeout /t 3 /nobreak
goto loop
