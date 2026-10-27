@echo off
title uHand UNO Legacy GUI [COM3]
cd /d "%~dp0"
python main.py --gui --port COM3
if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] Application exited with error code %ERRORLEVEL%.
    pause
)
