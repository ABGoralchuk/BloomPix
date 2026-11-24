@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ==================================================
echo   BloomPix - Chocolate Surface SEM Analyzer
echo ==================================================

if exist ".git" (
    where git >nul 2>&1
    if !errorlevel! equ 0 (
        echo [BloomPix] Checking repository status...
        git status --short
    )
)

set "PYTHON_EXE="

if exist "%~dp0python_embed\python.exe" (
    set "PYTHON_EXE=%~dp0python_embed\python.exe"
) else if exist "%~dp0venv\Scripts\python.exe" (
    set "PYTHON_EXE=%~dp0venv\Scripts\python.exe"
) else if exist "%~dp0.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
) else (
    for /f "delims=" %%I in ('where python 2^>nul') do (
        if not defined PYTHON_EXE set "PYTHON_EXE=%%I"
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

echo [BloomPix] Using Python: "%PYTHON_EXE%"
"%PYTHON_EXE%" -m streamlit run app.py
if errorlevel 1 (
    echo.
    echo [ERROR] BloomPix exited with an error.
    pause
    exit /b 1
)

endlocal
