@echo off
chcp 65001 >nul
echo Launch of the Z-Waif project...

:: Backend runs only on its own venv, never on a python found in PATH
set "PAI_PYTHON=%~dp0backend\venv\Scripts\python.exe"
if not exist "%PAI_PYTHON%" (
    echo [ERROR] Backend venv not found: %PAI_PYTHON%
    echo Run install.bat first.
    pause
    exit /b 1
)

:: Launching Python Process Manager
cd /d "%~dp0"
"%PAI_PYTHON%" run.py

pause
