@echo off
chcp 65001 >nul
title Academic Reports System

echo ==========================================
echo   Academic Reports System
echo ==========================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [Ошибка] Python не установлен!
    echo Скачайте Python с официального сайта: https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [OK] Python найден

echo.
echo [INFO] Запуск Backend...
cd backend

if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
    echo [OK] Виртуальное окружение активировано.
)

if exist "requirements.txt" (
    pip install -q -r requirements.txt 2>nul
)

start "Backend - Academic Reports" cmd /k "python -m uvicorn server:app --host 0.0.0.0 --port 8000 --reload"
echo [OK] Backend запущен на http://localhost:8000

cd ..

echo.
echo [INFO] Запуск Frontend...
cd frontend\public

start "Frontend - Academic Reports" cmd /k "python -m http.server 8080"
echo [OK] Frontend запущен на http://localhost:8080

cd ..\..

echo.
echo ==========================================
echo   Система запущена.
echo ==========================================
echo.
echo Frontend: http://localhost:8080
echo Backend:  http://localhost:8000
echo API Docs: http://localhost:8000/docs
echo.
echo Закройте окна терминалов для остановки
echo.

timeout /t 3 >nul
start http://localhost:8080

pause
