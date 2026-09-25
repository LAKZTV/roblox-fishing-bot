@echo off
cd /d "%~dp0"
title Fishing Bot
set "VENV=%~dp0.venv"
set "VPY=%VENV%\Scripts\python.exe"

rem ---- use the local environment (.venv) if it works ----
if exist "%VPY%" (
    "%VPY%" -c "import sys" >nul 2>nul && goto run
    echo Local environment is broken, rebuilding...
    rmdir /s /q "%VENV%"
)

rem ---- first time: find a system Python only to create .venv ----
set "PY="
py -3 -c "import sys" >nul 2>nul && set "PY=py -3"
if not defined PY python -c "import sys" >nul 2>nul && set "PY=python"
if not defined PY (
    echo [X] Python not found.
    echo.
    echo     1. Download Python 3 from https://www.python.org/downloads/
    echo     2. During setup, tick "Add python.exe to PATH"
    echo     3. Open this file again
    echo.
    pause
    exit /b 1
)
echo Creating local environment in .venv ^(first time only^)...
%PY% -m venv "%VENV%"
if errorlevel 1 (
    echo [X] Could not create .venv
    pause
    exit /b 1
)

:run
rem ---- install libraries into .venv if needed, then open the app ----
"%VPY%" launcher.py
if errorlevel 1 pause
