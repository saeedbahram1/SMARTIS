@echo off
setlocal
cd /d "%~dp0backend"
if exist ".venv\Scripts\activate.bat" call ".venv\Scripts\activate.bat"
echo ============================================================
echo SMARTIS 2.13 - router / chat / confirmation self-test
echo (uses a fake Ollama on port 11999; nothing on your PC is touched)
echo ============================================================
python tools\router_self_test.py
echo.
pause
endlocal
