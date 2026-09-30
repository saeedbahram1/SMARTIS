@echo off
setlocal EnableExtensions
cd /d "%~dp0backend"
if errorlevel 1 goto :error

echo ============================================================
echo SMARTIS - ONLINE VLC MEDIA SETUP
echo ============================================================

if not exist ".venv\Scripts\python.exe" (
    echo Creating Python virtual environment...
    py -3 -m venv .venv
    if errorlevel 1 goto :error
)

call ".venv\Scripts\activate.bat"
if errorlevel 1 goto :error

echo Checking online media extractor...
python -c "import yt_dlp; print('yt-dlp already installed:', yt_dlp.version.__version__)" >nul 2>&1
if errorlevel 1 (
    echo yt-dlp not found. Installing it...
    python -m pip install yt-dlp
    if errorlevel 1 goto :error
) else (
    echo Keeping the currently installed yt-dlp version to preserve the older working setup.
)
python -c "import yt_dlp; print('yt-dlp:', yt_dlp.version.__version__)"

where vlc.exe >nul 2>&1
if errorlevel 1 (
    if exist "%ProgramFiles%\VideoLAN\VLC\vlc.exe" (
        echo VLC found in Program Files.
    ) else if exist "%ProgramFiles(x86)%\VideoLAN\VLC\vlc.exe" (
        echo VLC found in Program Files (x86).
    ) else (
        echo WARNING: VLC was not found in the standard locations.
    )
) else (
    echo VLC found in PATH.
)

echo.
echo Online VLC playback setup completed.
echo Smartis searches online media and passes the direct stream to VLC.
echo It does NOT search local Music/Downloads folders.
pause
endlocal
exit /b 0

:error
echo.
echo Media setup failed. Check the output above.
pause
endlocal & exit /b 1
