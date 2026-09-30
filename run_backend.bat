@echo off
setlocal
cd /d "%~dp0backend"
if errorlevel 1 goto :error

echo ============================================================
echo SMARTIS BACKEND
echo ============================================================

if not exist ".venv\Scripts\python.exe" (
    echo Creating Python virtual environment...
    py -3 -m venv .venv
    if errorlevel 1 goto :error
)

call ".venv\Scripts\activate.bat"
if errorlevel 1 goto :error

python -m pip install -r requirements.txt
if errorlevel 1 goto :error

if not exist "models\sherpa-fa\model.onnx" (
    echo.
    echo [WARNING] Persian Sherpa model was not found.
    echo Run SETUP_SHERPA_MODELS.bat first.
    echo.
)

if not exist "models\sherpa-en\encoder-epoch-99-avg-1.onnx" (
    echo [WARNING] English Sherpa model was not found.
    echo Run SETUP_SHERPA_MODELS.bat first.
    echo.
)

python main.py
set "EXIT_CODE=%ERRORLEVEL%"
echo.
echo Backend stopped with code %EXIT_CODE%.
pause
endlocal & exit /b %EXIT_CODE%

:error
echo.
echo Smartis backend could not start.
pause
endlocal & exit /b 1
