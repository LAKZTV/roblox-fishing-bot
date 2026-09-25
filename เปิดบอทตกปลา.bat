@echo off
cd /d "%~dp0"
title Fishing Bot

rem ---- find Python ----
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

rem ---- check / install libraries, then open the app ----
%PY% launcher.py
if errorlevel 1 pause
