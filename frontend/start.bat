@echo off
chcp 65001 >nul
title Frontend - Academic Reports

echo ================================
echo   Frontend Server
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

if exist "public" (
    cd public
)

if not exist "index.html" (
    echo [Ошибка] index.html не найден!
    pause
    exit /b 1
)

echo [OK] index.html найден
echo.
echo [OK] Запуск сервера...
echo     http://localhost:8080
echo.

python -m http.server 8080
