@echo off
setlocal EnableExtensions DisableDelayedExpansion

cd /d "%~dp0"
set "ROOT=%CD%"
set "VENV_PY=%ROOT%\.venv\Scripts\python.exe"
set "BACKEND_PORT=8000"
set "FRONTEND_PORT=3000"
set "OLLAMA_PORT=11434"
set "OLLAMA_EXE=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
set "DRY_RUN="

if /I "%~1"=="--dry-run" set "DRY_RUN=1"

if exist "%ROOT%\.env.local" (
  for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%ROOT%\.env.local") do (
    if not "%%~A"=="" set "%%~A=%%~B"
  )
)

if defined DRY_RUN (
  echo Dry run mode.
  echo.
  echo Python path: "%VENV_PY%"
  echo Ollama:      "%OLLAMA_EXE%" serve  ^(with OLLAMA_MODELS from .env.local if set^)
  echo DB init:     cd /d "%ROOT%\backend" ^&^& "%VENV_PY%" -c "from app.database import create_tables; create_tables()"
  echo Backend:     cd /d "%ROOT%\backend" ^&^& "%VENV_PY%" -m uvicorn app.main:app --host 127.0.0.1 --port %BACKEND_PORT%
  echo Frontend:    cd /d "%ROOT%\frontend" ^&^& "%VENV_PY%" -m http.server %FRONTEND_PORT%
  exit /b 0
)

if not exist "%VENV_PY%" (
  echo Creating virtual environment...
  where py >nul 2>&1
  if not errorlevel 1 (
    py -3 -m venv "%ROOT%\.venv"
  ) else (
    python -m venv "%ROOT%\.venv"
  )
  if errorlevel 1 (
    echo Failed to create .venv
    pause
    exit /b 1
  )

  echo Installing dependencies...
  "%VENV_PY%" -m pip install -r "%ROOT%\requirements.txt"
  if errorlevel 1 (
    echo Failed to install dependencies
    pause
    exit /b 1
  )
)

set "OLLAMA_LISTENING="
for /f "tokens=1,2,3,4,5" %%A in ('netstat -ano ^| findstr /R /C:":%OLLAMA_PORT% .*LISTENING"') do (
  set "OLLAMA_LISTENING=1"
)

if not defined OLLAMA_LISTENING (
  if exist "%OLLAMA_EXE%" (
    echo Starting Ollama API...
    if defined OLLAMA_MODELS (
      start "EzOlimp Ollama :%OLLAMA_PORT%" /MIN cmd /c "set OLLAMA_MODELS=%OLLAMA_MODELS% && ""%OLLAMA_EXE%"" serve"
    ) else (
      start "EzOlimp Ollama :%OLLAMA_PORT%" /MIN cmd /c """%OLLAMA_EXE%"" serve"
    )
    timeout /t 3 >nul
  ) else (
    echo Ollama not found at "%OLLAMA_EXE%". Skipping local LLM server startup.
  )
) else (
  echo Ollama API already running on :%OLLAMA_PORT%
)

set "BACKEND_LISTENING="
for /f "tokens=1,2,3,4,5" %%A in ('netstat -ano ^| findstr /R /C:":%BACKEND_PORT% .*LISTENING"') do (
  set "BACKEND_LISTENING=1"
)

set "FRONTEND_LISTENING="
for /f "tokens=1,2,3,4,5" %%A in ('netstat -ano ^| findstr /R /C:":%FRONTEND_PORT% .*LISTENING"') do (
  set "FRONTEND_LISTENING=1"
)

echo Initializing database...
pushd "%ROOT%\backend"
"%VENV_PY%" -c "from app.database import create_tables; create_tables()"
if errorlevel 1 (
  popd
  echo Failed to initialize database
  pause
  exit /b 1
)
popd

echo Starting servers...
if not defined BACKEND_LISTENING (
  start "EzOlimp Backend :8000" cmd /k "cd /d ""%ROOT%\backend"" && ""%VENV_PY%"" -m uvicorn app.main:app --host 127.0.0.1 --port %BACKEND_PORT%"
) else (
  echo Backend already running on :%BACKEND_PORT%
)

if not defined FRONTEND_LISTENING (
  start "EzOlimp Frontend :3000" cmd /k "cd /d ""%ROOT%\frontend"" && ""%VENV_PY%"" -m http.server %FRONTEND_PORT%"
) else (
  echo Frontend already running on :%FRONTEND_PORT%
)

echo.
echo Backend:  http://localhost:%BACKEND_PORT%/
echo Frontend: http://localhost:%FRONTEND_PORT%/
echo.
echo Press any key to close this launcher window...
pause >nul

endlocal
