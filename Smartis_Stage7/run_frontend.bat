@echo off
setlocal
cd /d "%~dp0frontend"

echo ==================================================
echo SMARTIS FRONTEND - SAFE WINDOWS RUN
 echo ==================================================

if not exist "windows\CMakeLists.txt" (
    echo Generating Windows runner...
    flutter create --platforms=windows .
) else if not exist "windows\runner\Runner.rc" (
    echo Repairing Windows runner...
    flutter create --platforms=windows .
)

if exist "build" (
    echo Removing stale build cache...
    rmdir /s /q "build" >nul 2>&1
)

flutter clean
if errorlevel 1 echo Flutter clean returned a warning; continuing.

flutter pub get
if errorlevel 1 goto :error

flutter run -d windows
if errorlevel 1 goto :error

goto :done

:error
echo.
echo Smartis failed to start. Run REPAIR_WINDOWS.bat.
pause
exit /b 1

:done
pause
endlocal
