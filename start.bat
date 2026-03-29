@echo off
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Venv not found: .venv\Scripts\python.exe
  echo Create it with: py -3.13 -m venv .venv
  exit /b 1
)

start cmd /k "cd /d \"%~dp0backend\" && \"%~dp0.venv\Scripts\python.exe\" -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000"
start cmd /k "cd /d \"%~dp0frontend\" && \"%~dp0.venv\Scripts\python.exe\" -m http.server 8080"

echo Servers started!
echo Backend: http://127.0.0.1:8000
echo Frontend: http://127.0.0.1:8080
pause
