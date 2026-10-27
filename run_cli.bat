@echo off
title uHand UNO Terminal Menu [COM3]
cd /d "%~dp0"
python main.py --cli --port COM3
if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] Application exited with error code %ERRORLEVEL%.
    pause
)
