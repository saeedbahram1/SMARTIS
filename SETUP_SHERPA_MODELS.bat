@echo off
setlocal

set "ROOT=%~dp0"
set "BACKEND=%ROOT%backend"
set "MODELS=%BACKEND%\models"
set "FA_DIR=%MODELS%\sherpa-fa"
set "EN_DIR=%MODELS%\sherpa-en"

if not exist "%BACKEND%\.venv\Scripts\python.exe" (
    echo Creating Python virtual environment...
    cd /d "%BACKEND%"
    py -3 -m venv .venv
    if errorlevel 1 goto :error
) else (
    cd /d "%BACKEND%"
)

call ".venv\Scripts\activate.bat"
if errorlevel 1 goto :error

python -m pip install -r requirements.txt
if errorlevel 1 goto :error

where curl >nul 2>&1
if errorlevel 1 goto :error
where tar >nul 2>&1
if errorlevel 1 goto :error

if not exist "%FA_DIR%" mkdir "%FA_DIR%"
if not exist "%EN_DIR%" mkdir "%EN_DIR%"

if not exist "%FA_DIR%\model.onnx" (
    echo Downloading Persian model...
    curl -L --fail -o "%FA_DIR%\model.onnx" "https://huggingface.co/Reza2kn/Shenava-Koochik-v1.0-sherpa-onnx/resolve/main/model.onnx"
    if errorlevel 1 goto :error
) else (
    echo Persian model already exists.
)

if not exist "%FA_DIR%\tokens.txt" (
    curl -L --fail -o "%FA_DIR%\tokens.txt" "https://huggingface.co/Reza2kn/Shenava-Koochik-v1.0-sherpa-onnx/resolve/main/tokens.txt"
    if errorlevel 1 goto :error
)


set "EN_ARCHIVE=%MODELS%\_en_download.tar.bz2"
set "EN_EXTRACT=%MODELS%\_en_extract"
if not exist "%EN_DIR%\encoder-epoch-99-avg-1.onnx" goto :download_english
if not exist "%EN_DIR%\decoder-epoch-99-avg-1.onnx" goto :download_english
if not exist "%EN_DIR%\joiner-epoch-99-avg-1.onnx" goto :download_english
if not exist "%EN_DIR%\tokens.txt" goto :download_english
echo English model already exists.
goto :models_done

:download_english
echo Downloading English model...
curl -L --fail -o "%EN_ARCHIVE%" "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-zipformer-large-en-2023-06-26.tar.bz2"
if errorlevel 1 goto :error
if exist "%EN_EXTRACT%" rmdir /s /q "%EN_EXTRACT%"
mkdir "%EN_EXTRACT%"
tar -xf "%EN_ARCHIVE%" -C "%EN_EXTRACT%"
if errorlevel 1 goto :error

set "EN_SRC="
for /d %%D in ("%EN_EXTRACT%\sherpa-onnx-zipformer-large-en-2023-06-26*") do set "EN_SRC=%%D"
if not defined EN_SRC goto :error

copy /y "%EN_SRC%\encoder-epoch-99-avg-1.onnx" "%EN_DIR%\" >nul
copy /y "%EN_SRC%\decoder-epoch-99-avg-1.onnx" "%EN_DIR%\" >nul
copy /y "%EN_SRC%\joiner-epoch-99-avg-1.onnx" "%EN_DIR%\" >nul
copy /y "%EN_SRC%\tokens.txt" "%EN_DIR%\" >nul
if errorlevel 1 goto :error

del /q "%EN_ARCHIVE%" >nul 2>&1
rmdir /s /q "%EN_EXTRACT%" >nul 2>&1

:models_done

echo.
echo Models are ready.
echo Run run_backend.bat next.
pause
endlocal
exit /b 0

:error
echo.
echo Sherpa model setup failed. Check the internet connection and the output above.
pause
endlocal
exit /b 1
