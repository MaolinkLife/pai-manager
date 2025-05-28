@echo off
echo ----------------------------------
echo Установка зависимостей Z-Waif
echo ----------------------------------

echo.
echo Устанавливаем frontend...
cd frontend
call npm install
cd ..

echo.
echo Настраиваем backend...
cd backend

IF NOT EXIST venv (
    echo Создаём виртуальное окружение...
    python -m venv venv
)

call venv\Scripts\activate.bat
pip install -r requirements.txt
cd ..

echo.
echo Установка завершена. Готово к запуску!
pause