@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Dota 2 Review Assistant

set "ROOT=%~dp0"
set "VENV_PY=%ROOT%.venv\Scripts\python.exe"

echo ==========================================
echo   Dota 2 Review Assistant
echo ==========================================
echo.

rem ----- Locate Python 3.10+ -----
set "PYTHON="
where py >nul 2>nul
if not errorlevel 1 (
    py -3 -c "import sys; assert sys.version_info >= (3, 10)" >nul 2>nul
    if not errorlevel 1 set "PYTHON=py -3"
)
if not defined PYTHON (
    where python >nul 2>nul
    if not errorlevel 1 (
        python -c "import sys; assert sys.version_info >= (3, 10)" >nul 2>nul
        if not errorlevel 1 set "PYTHON=python"
    )
)
if not defined PYTHON (
    echo [ERROR] Python 3.10 or newer was not found.
    echo.
    echo Install Python from https://www.python.org/downloads/
    echo During installation, enable "Add python.exe to PATH".
    echo.
    pause
    exit /b 1
)

rem ----- Create the virtual environment once -----
if not exist "%VENV_PY%" (
    echo [SETUP] Creating virtual environment...
    %PYTHON% -m venv "%ROOT%.venv"
    if errorlevel 1 goto :setup_failed
)

rem ----- Install dependencies if they are missing -----
"%VENV_PY%" -c "import fastapi, uvicorn, httpx, jinja2, pydantic, pydantic_settings, multipart" >nul 2>nul
if errorlevel 1 (
    echo [SETUP] Installing dependencies. This may take a few minutes...
    "%VENV_PY%" -m pip install --upgrade pip --disable-pip-version-check
    "%VENV_PY%" -m pip install -r "%ROOT%requirements.txt" --disable-pip-version-check
    if errorlevel 1 goto :setup_failed
)

echo [INFO] Starting the server...
echo [INFO] The browser will open automatically when it is ready.
echo [INFO] Keep this window open. Type Q + Enter to stop the server.
echo.

"%VENV_PY%" "%ROOT%scripts\launcher.py"
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo [ERROR] The application stopped with exit code %EXIT_CODE%.
    echo Please read the messages above and try again.
    echo.
    pause
)

exit /b %EXIT_CODE%

:setup_failed
echo.
echo [ERROR] Setup failed. Check your network connection and Python installation.
echo.
pause
exit /b 1
