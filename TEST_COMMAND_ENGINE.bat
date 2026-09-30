@echo off
setlocal EnableExtensions
cd /d "%~dp0backend"
if not exist ".venv\Scripts\python.exe" (
    echo Backend virtual environment not found. Run run_backend.bat first.
    pause
    exit /b 1
)
call ".venv\Scripts\activate.bat"
if errorlevel 1 goto :error
python tools\command_self_test.py
if errorlevel 1 goto :error
echo.
echo Command engine test completed successfully.
pause
endlocal
exit /b 0
:error
echo.
echo Command engine self-test failed.
pause
endlocal & exit /b 1
