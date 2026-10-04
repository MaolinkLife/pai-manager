@echo off
echo ----------------------------------
echo Installing PAI dependencies
echo ----------------------------------

echo.
echo check Node.js...
where node >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js was not found. The frontend needs Node.js 20.19+, 22.12+ or 24+.
    pause
    exit /b 1
)
:: Angular 21 runs on Node.js ^20.19, ^22.12 or 24 and later
node -e "const [a, b] = process.versions.node.split('.').map(Number); process.exit((a === 20 && b >= 19) || (a === 22 && b >= 12) || a >= 24 ? 0 : 1)"
if errorlevel 1 (
    for /f %%v in ('node -v') do echo [ERROR] Node.js %%v is not supported. The frontend needs Node.js 20.19+, 22.12+ or 24+.
    pause
    exit /b 1
)

echo.
echo install frontend...
cd frontend

:: Always sync node_modules with package-lock.json: after an update the
:: existing node_modules still holds the packages of the previous version
call npm install
if errorlevel 1 (
    echo [ERROR] npm install failed, see the messages above.
    cd ..
    pause
    exit /b 1
)

cd ..

echo.
echo install backend...
cd backend

IF NOT EXIST venv\Scripts\python.exe (
    echo Create a virtual environment...
    python -m venv venv
)

:: Install into the backend venv explicitly; activate.bat may point elsewhere
set "VENV_PYTHON=%CD%\venv\Scripts\python.exe"
if not exist "%VENV_PYTHON%" (
    echo [ERROR] Backend venv was not created: %VENV_PYTHON%
    pause
    exit /b 1
)

:: Use project-local pip cache to avoid global AppData permission issues
if not exist temp\pip-cache (
    mkdir temp\pip-cache
)
set "PIP_CACHE_DIR=%CD%\temp\pip-cache"
set "PIP_NO_CACHE_DIR=1"

"%VENV_PYTHON%" -m pip install --upgrade pip wheel
"%VENV_PYTHON%" -m pip install "setuptools<81"
"%VENV_PYTHON%" -m pip install --no-cache-dir -r requirements.txt
cd ..

echo.
echo Installation is complete. Ready to run!
pause
