@echo off
setlocal
cd /d "%~dp0frontend"

echo ==================================================
echo SMARTIS - WINDOWS BUILD REPAIR
 echo ==================================================

taskkill /F /IM smartis_assistant.exe >nul 2>&1
if exist "build" rmdir /s /q "build" >nul 2>&1
if exist ".dart_tool" rmdir /s /q ".dart_tool" >nul 2>&1

if not exist "windows\CMakeLists.txt" (
    flutter create --platforms=windows .
) else if not exist "windows\runner\Runner.rc" (
    flutter create --platforms=windows .
)

flutter clean
flutter pub get

if errorlevel 1 goto :error

echo.
echo Windows build state is repaired.
echo Now run: flutter run -d windows
pause
exit /b 0

:error
echo Repair failed. Check the Flutter installation and Visual Studio workload.
pause
exit /b 1
