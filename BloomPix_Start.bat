@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ==================================================
echo   BloomPix - Chocolate Surface SEM Analyzer
echo ==================================================

if not exist "%USERPROFILE%\Desktop\BloomPix.lnk" (
    if not exist "%USERPROFILE%\OneDrive\Desktop\BloomPix.lnk" (
        if exist "%~dp0assets\bloompix.ico" (
            if exist "%~dp0scripts\create_windows_shortcut.vbs" (
                cscript //nologo "%~dp0scripts\create_windows_shortcut.vbs" >nul 2>&1
            )
        )
    )
)

set "PYTHON_EXE="
set "NEED_INSTALL=0"

if exist "%~dp0python_embed\python.exe" (
    set "PYTHON_EXE=%~dp0python_embed\python.exe"
) else if exist "%~dp0venv\Scripts\python.exe" (
    set "PYTHON_EXE=%~dp0venv\Scripts\python.exe"
) else if exist "%~dp0.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
) else (
    set "SYS_PYTHON="
    for /f "delims=" %%I in ('where python 2^>nul') do (
        if not defined SYS_PYTHON set "SYS_PYTHON=%%I"
    )
    if defined SYS_PYTHON (
        echo [BloomPix] Creating virtual environment in "%~dp0venv"...
        "%SYS_PYTHON%" -m venv "%~dp0venv"
        if errorlevel 1 (
            echo [ERROR] Failed to create virtual environment.
            pause
            exit /b 1
        )
        set "PYTHON_EXE=%~dp0venv\Scripts\python.exe"
        set "NEED_INSTALL=1"
    )
)

if not defined PYTHON_EXE (
    echo [ERROR] No Python runtime found.
    echo Checked:
    echo   1. %~dp0python_embed\python.exe
    echo   2. %~dp0venv\Scripts\python.exe
    echo   3. %~dp0.venv\Scripts\python.exe
    echo   4. System python on PATH
    pause
    exit /b 1
)

if not "%PYTHON_EXE%"=="%~dp0python_embed\python.exe" (
    "%PYTHON_EXE%" -c "import streamlit" >nul 2>&1
    if errorlevel 1 set "NEED_INSTALL=1"
)

if "!NEED_INSTALL!"=="1" (
    echo [BloomPix] Installing dependencies from requirements.txt...
    "%PYTHON_EXE%" -m pip install --upgrade pip
    "%PYTHON_EXE%" -m pip install -r "%~dp0requirements.txt"
    if errorlevel 1 (
        echo [ERROR] Failed to install Python dependencies.
        pause
        exit /b 1
    )
)

if exist ".git" (
    where git >nul 2>nul
    if !errorlevel! equ 0 (
        echo [BloomPix] Checking for repository updates...
        git pull --ff-only >nul 2>&1
    ) else if exist "%~dp0scripts\auto_update.py" (
        echo [BloomPix] Checking for GitHub updates...
        "%PYTHON_EXE%" "%~dp0scripts\auto_update.py" --repo ABGoralchuk/BloomPix --branch main
    )
) else if exist "%~dp0scripts\auto_update.py" (
    echo [BloomPix] Checking for GitHub updates...
    "%PYTHON_EXE%" "%~dp0scripts\auto_update.py" --repo ABGoralchuk/BloomPix --branch main
)

echo [BloomPix] Using Python: "%PYTHON_EXE%"
"%PYTHON_EXE%" -m streamlit run "%~dp0app.py" --server.headless false
if errorlevel 1 (
    echo.
    echo [ERROR] BloomPix exited with an error.
    pause
    exit /b 1
)

endlocal
