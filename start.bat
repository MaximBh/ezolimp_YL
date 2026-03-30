@echo off
setlocal
cd /d "%~dp0"
set "ROOT=%~dp0"

if exist ".env.local" (
  for /f "usebackq eol=# tokens=1,* delims==" %%A in (".env.local") do (
    if not "%%A"=="" set "%%A=%%B"
  )
)

if not exist ".venv\Scripts\python.exe" (
  echo Venv not found: .venv\Scripts\python.exe
  echo Create it with: py -3.13 -m venv .venv
  exit /b 1
)

pushd "%ROOT%backend"
start "Backend" /D "%ROOT%backend" "%ROOT%.venv\Scripts\python.exe" -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
popd

pushd "%ROOT%frontend"
start "Frontend" /D "%ROOT%frontend" "%ROOT%.venv\Scripts\python.exe" -m http.server 8080
popd

echo Servers started!
echo Backend: http://ezolimp:8000
echo Frontend: http://ezolimp:8080
echo Frontend fallback: http://localhost:8080
endlocal
