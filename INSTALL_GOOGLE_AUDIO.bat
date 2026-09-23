@echo off
setlocal enabledelayedexpansion
title Smartis Audio & Google STT Setup

echo ======================================================
echo    Smartis Audio Environment Setup & Verification
echo ======================================================
echo.

cd /d "%~dp0backend"

if not exist ".venv\Scripts\python.exe" (
    echo [1/5] Creating Python virtual environment (.venv)...
    where py >nul 2>nul
    if !errorlevel! equ 0 (
        py -3 -m venv .venv
    ) else (
        python -m venv .venv
    )
) else (
    echo [1/5] Found existing virtual environment (.venv).
)

if not exist ".venv\Scripts\activate.bat" (
    echo [ERROR] Could not set up Python virtual environment.
    echo Make sure Python 3.10+ is installed and available in PATH.
    pause
    exit /b 1
)

echo [2/5] Activating virtual environment...
call ".venv\Scripts\activate.bat"

echo [3/5] Installing audio & backend requirements...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

echo.
echo [4/5] Verifying SpeechRecognition and PyAudio...
python -c "import speech_recognition; print('  SpeechRecognition package: OK')" 2>nul
if %errorlevel% neq 0 (
    echo [FAIL] SpeechRecognition is NOT installed properly.
) else (
    set SR_STATUS=OK
)

python -c "import pyaudio; print('  PyAudio package: OK')" 2>nul
if %errorlevel% neq 0 (
    echo [FAIL] PyAudio is NOT installed properly.
    echo Hint: You may install PyAudio wheel for your Python version with:
    echo pip install pipwin ^&^& pipwin install pyaudio
) else (
    set PA_STATUS=OK
)

echo.
echo [5/5] Testing system microphones...
python -c "import speech_recognition as sr; mics = sr.Microphone.list_microphone_names(); print('  Microphones detected:', len(mics)); [print(f'    [{i}] {name}') for i, name in enumerate(mics)]" 2>nul
if %errorlevel% neq 0 (
    set MIC_STATUS=WARNING
) else (
    set MIC_STATUS=OK
)

echo.
echo ======================================================
echo                 VERIFICATION RESULTS
echo ======================================================
if "%SR_STATUS%"=="OK" (
    echo SpeechRecognition : OK
) else (
    echo SpeechRecognition : FAILED
)

if "%PA_STATUS%"=="OK" (
    echo PyAudio           : OK
) else (
    echo PyAudio           : FAILED
)

if "%MIC_STATUS%"=="OK" (
    echo Microphone        : OK
) else (
    echo Microphone        : CHECK AUDIO DRIVERS
)

if "%SR_STATUS%"=="OK" if "%PA_STATUS%"=="OK" (
    echo Google STT        : READY
) else (
    echo Google STT        : NOT READY
)
echo ======================================================
echo.
echo Setup script completed. You can now launch Smartis using run_backend.bat and run_frontend.bat!
echo.
pause
