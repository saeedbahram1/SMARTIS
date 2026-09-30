@echo off
setlocal EnableExtensions
cd /d "%~dp0"

start "Smartis Backend" cmd /k call "%~dp0run_backend.bat"
timeout /t 3 /nobreak >nul
start "Smartis Frontend" cmd /k call "%~dp0run_frontend.bat"

endlocal
