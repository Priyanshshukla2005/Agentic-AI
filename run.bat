@echo off
REM Start Business Starter on Windows:   double-click run.bat  (or type run.bat in a terminal)
REM 1. creates a virtual environment (venv\) if missing   2. installs the requirements
REM 3. copies .env.example to .env if missing             4. starts the server for this computer + the Wi-Fi
cd /d "%~dp0"

if not exist venv (
  echo Creating virtual environment in venv\ ...
  python -m venv venv || (echo Python 3.10+ is needed: https://www.python.org/downloads/ & pause & exit /b 1)
)
call venv\Scripts\activate.bat

echo Installing requirements (first time can take a few minutes) ...
python -m pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt || (echo Installing failed. & pause & exit /b 1)

if not exist .env (
  copy .env.example .env >nul
  echo Created .env from .env.example - add your GROQ_API_KEY there, or set LLM_PROVIDER=mock.
)

if "%PORT%"=="" set PORT=8000
set LAN_IP=
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do if not defined LAN_IP set LAN_IP=%%a
set LAN_IP=%LAN_IP: =%
echo.
echo   On this computer : http://127.0.0.1:%PORT%
if defined LAN_IP echo   On a phone (same Wi-Fi): http://%LAN_IP%:%PORT%
echo   Press Ctrl+C to stop.
echo.
uvicorn app.main:app --host 0.0.0.0 --port %PORT%
