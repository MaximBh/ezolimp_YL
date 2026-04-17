@echo off
setlocal EnableExtensions DisableDelayedExpansion

cd /d "%~dp0"

set "MODEL=deepseek-r1:8b"
set "ROOT=%CD%"
set "TARGET_MODELS=%ROOT%\.ollama\models"
set "MISSING_BLOB=%ROOT%\.ollama\models\blobs\sha256-e6a7edc1a4d7d9b2de136a221a57336b76316cfe53a252aeba814496c5ae439d"
set "OLLAMA_EXE=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"

if not exist "%OLLAMA_EXE%" (
  where ollama >nul 2>&1
  if errorlevel 1 (
    echo ERROR: Ollama is not installed or not in PATH.
    echo Install Ollama first: https://ollama.com/download
    exit /b 1
  )
  set "OLLAMA_EXE=ollama"
)

if not exist "%TARGET_MODELS%" mkdir "%TARGET_MODELS%"
set "OLLAMA_MODELS=%TARGET_MODELS%"

echo Using OLLAMA_MODELS=%OLLAMA_MODELS%
echo Pulling model %MODEL%...
"%OLLAMA_EXE%" pull "%MODEL%"
if errorlevel 1 (
  echo ERROR: Failed to pull model %MODEL%.
  exit /b 1
)

if exist "%MISSING_BLOB%" (
  echo OK: Missing blob restored:
  echo %MISSING_BLOB%
) else (
  echo Model pull finished, but exact blob file path was not found.
  echo This may happen if Ollama storage layout differs on your system.
)

exit /b 0
