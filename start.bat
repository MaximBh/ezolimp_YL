@echo off
cd backend
start cmd /k "python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000"
cd ..\frontend
start cmd /k "python -m http.server 8080"
echo Servers started!
echo Backend: http://127.0.0.1:8000
echo Frontend: http://127.0.0.1:8080
pause
