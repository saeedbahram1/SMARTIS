@echo off
cd /d "%~dp0backend"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" tools\qwen_chat_diagnostic.py
) else (
  py tools\qwen_chat_diagnostic.py
)
echo.
echo Exit code: %ERRORLEVEL%
pause
