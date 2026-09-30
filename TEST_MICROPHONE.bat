@echo off
setlocal
cd /d "%~dp0backend"
if not exist ".venv\Scripts\python.exe" (
    echo Backend virtual environment not found.
    echo Run run_backend.bat once first.
    pause
    exit /b 1
)
call ".venv\Scripts\activate.bat"
python tools\mic_diagnostic.py
set "EXIT_CODE=%ERRORLEVEL%"
echo.
pause
endlocal & exit /b %EXIT_CODE%
