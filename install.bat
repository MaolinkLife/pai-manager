@echo off
echo ----------------------------------
echo Installing Z-Waif dependencies
echo ----------------------------------

echo.
echo install frontend...
cd frontend

:: Проверяем, есть ли node_modules
if not exist node_modules (
    echo node_modules не найден, выполняю npm install...
    call npm install
) else (
    echo node_modules найден
)

:: Проверяем наличие @angular-devkit/build-angular
echo Проверяю наличие @angular-devkit/build-angular...
call npm ls @angular-devkit/build-angular >nul 2>&1
if %errorlevel% neq 0 (
    echo Устанавливаю @angular-devkit/build-angular...
    call npm install --save-dev @angular-devkit/build-angular
) else (
    echo @angular-devkit/build-angular уже установлен
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
