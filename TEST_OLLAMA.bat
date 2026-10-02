@echo off
setlocal
cd /d "%~dp0backend"
if not exist ".venv\Scripts\python.exe" (
  echo Smartis backend virtual environment was not found.
  echo Start Smartis once first so run_backend.bat can create it.
  pause
  exit /b 1
)
call ".venv\Scripts\activate.bat"
python tools\ollama_diagnostic.py
set "RC=%ERRORLEVEL%"
echo.
echo Diagnostic exit code: %RC%
pause
endlocal & exit /b %RC%
