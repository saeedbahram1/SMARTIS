@echo off
setlocal enabledelayedexpansion
title Smartis Backend

cd /d "%~dp0backend"

if not exist ".venv\Scripts\python.exe" (
    echo [Smartis] Creating backend virtual environment (.venv)...
    where py >nul 2>nul
    if %errorlevel% equ 0 (
        py -3 -m venv .venv
    ) else (
        python -m venv .venv
    )
)

if not exist ".venv\Scripts\activate.bat" (
    echo [Smartis ERROR] Failed to initialize Python virtual environment.
    echo Please make sure Python 3.10+ is installed and in your PATH.
    pause
    exit /b 1
)

echo [Smartis] Activating virtual environment...
call ".venv\Scripts\activate.bat"

echo [Smartis] Checking dependencies...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

echo [Smartis] Starting FastAPI Backend on 127.0.0.1:8765...
python main.py

if %errorlevel% neq 0 (
    echo.
    echo [Smartis] Backend stopped with an error code: %errorlevel%
    pause
)
