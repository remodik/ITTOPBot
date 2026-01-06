@echo off
chcp 65001 >nul
title Backend - Academic Reports

echo ================================
echo   Backend Server
echo ================================
echo.

cd /d "%~dp0"

python --version >nul 2>&1
if errorlevel 1 (
    echo [Ошибка] Python не установлен!
    pause
    exit /b 1
)

echo [OK] Python найден

if not exist "venv" (
    echo [INFO] Создание виртуального окружения...
    python -m venv venv
    echo [OK] venv создан
)

call venv\Scripts\activate.bat
echo [OK] venv активирован

if exist "requirements.txt" (
    echo [INFO] Установка зависимостей...
    pip install -q -r requirements.txt
    echo [OK] Зависимости установлены
)

if not exist ".env" (
    echo [INFO] Создание .env файла...
    (
        echo MONGO_URL=mongodb://localhost:27017
        echo DB_NAME=college_reports
        echo CORS_ORIGINS=http://localhost:8080,http://127.0.0.1:8080
    ) > .env
    echo [OK] .env создан
)

echo.
echo [OK] Запуск сервера...
echo     http://localhost:8000
echo     API Docs: http://localhost:8000/docs
echo.

python -m uvicorn server:app --host 0.0.0.0 --port 8000 --reload
