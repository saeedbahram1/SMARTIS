@echo off
setlocal
cd /d "%~dp0frontend"

echo ==================================================
echo         SMARTIS - WINDOWS BUILD REPAIR
echo ==================================================

echo [1/4] Stopping any running Smartis processes...
taskkill /F /IM smartis_assistant.exe >nul 2>&1

echo [2/4] Clearing build and cache directories...
if exist "build" rmdir /s /q "build" >nul 2>&1
if exist ".dart_tool" rmdir /s /q ".dart_tool" >nul 2>&1
if exist "windows\flutter\ephemeral" rmdir /s /q "windows\flutter\ephemeral" >nul 2>&1

echo [3/4] Ensuring Windows CMake platform files exist...
if not exist "windows\CMakeLists.txt" (
    flutter create --platforms=windows .
) else if not exist "windows\runner\Runner.rc" (
    flutter create --platforms=windows .
)

echo [4/4] Fetching Flutter dependencies...
flutter clean
flutter pub get

if errorlevel 1 goto :error

echo.
echo ==================================================
echo [SUCCESS] Windows build state is repaired cleanly.
echo You can now launch the app using: run_frontend.bat
echo ==================================================
pause
exit /b 0

:error
echo.
echo [ERROR] Repair encountered an issue. Please verify:
echo 1. Flutter is installed and in PATH (flutter doctor).
echo 2. Visual Studio "Desktop development with C++" workload is installed.
pause
exit /b 1
