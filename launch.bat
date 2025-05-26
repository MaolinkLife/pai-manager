@echo off
chcp 65001 >nul
echo 🛠 Запуск проекта Z-Waif...

:: Активируем venv
cd backend
call venv\Scripts\activate
cd ..

:: Запускаем Python-менеджер процессов
python run.py

pause