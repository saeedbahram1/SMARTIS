@echo off
setlocal EnableExtensions
cd /d "%~dp0frontend"
if errorlevel 1 goto :error

echo ============================================================
echo SMARTIS - WINDOWS BUILD REPAIR
echo ============================================================

echo [1/6] Closing Smartis...
taskkill /F /IM smartis_desktop.exe >nul 2>&1

if not exist "windows\CMakeLists.txt" goto :regenerate
if not exist "windows\flutter\CMakeLists.txt" goto :regenerate
goto :project_ready

:regenerate
echo [2/6] Regenerating the Windows platform files...
call flutter create --platforms=windows .
if errorlevel 1 goto :error

:project_ready
echo [3/6] Cleaning Flutter build artifacts...
call flutter clean
if errorlevel 1 goto :error

echo [4/6] Restoring Flutter packages and generated Windows files...
call flutter pub get
if errorlevel 1 goto :error

if not exist "windows\flutter\CMakeLists.txt" (
    echo ERROR: windows\flutter\CMakeLists.txt is still missing.
    goto :error
)

if not exist "windows\flutter\generated_plugins.cmake" (
    echo ERROR: flutter pub get did not generate generated_plugins.cmake.
    goto :error
)

echo [5/6] Building Windows application...
call flutter build windows
if errorlevel 1 goto :error

echo [6/6] Repair verification complete.
echo.
echo Windows build repair completed successfully.
echo You can now run: run_frontend.bat
pause
endlocal
exit /b 0

:error
echo.
echo Repair failed. Check the Flutter output above.
echo Required tooling: Flutter Windows desktop support + Visual Studio Desktop C++.
pause
endlocal & exit /b 1
