#!/bin/bash

set -e

echo "=========================================="
echo "  Academic Reports System"
echo "=========================================="
echo ""

GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

check_dependencies() {
    echo -e "${BLUE}Проверка зависимостей...${NC}"
    
    if ! command -v python3 &> /dev/null; then
        echo -e "${RED}Ошибка: Python3 не установлен${NC}"
        exit 1
    fi
    
    echo -e "${GREEN}✓ Python3 найден: $(python3 --version)${NC}"
}

start_backend() {
    echo ""
    echo -e "${BLUE}Запуск Backend...${NC}"
    cd backend

    if [ -d "venv" ]; then
        source venv/bin/activate
        echo -e "${GREEN}✓ Виртуальное окружение активировано${NC}"
    fi

    if [ -f "requirements.txt" ]; then
        pip install -q -r requirements.txt 2>/dev/null || true
    fi

    python3 -m uvicorn server:app --host 0.0.0.0 --port 8000 --reload &
    BACKEND_PID=$!
    echo -e "${GREEN}✓ Backend запущен (PID: $BACKEND_PID)${NC}"
    echo -e "${GREEN}  → http://localhost:8000${NC}"
    echo -e "${GREEN}  → API Docs: http://localhost:8000/docs${NC}"
    
    cd ..
}

start_frontend() {
    echo ""
    echo -e "${BLUE}Запуск Frontend...${NC}"
    cd frontend/public

    python3 -m http.server 8080 &
    FRONTEND_PID=$!
    echo -e "${GREEN}✓ Frontend запущен (PID: $FRONTEND_PID)${NC}"
    echo -e "${GREEN}  → http://localhost:8080${NC}"
    
    cd ../..
}

cleanup() {
    echo ""
    echo -e "${BLUE}Остановка сервисов...${NC}"
    kill $BACKEND_PID 2>/dev/null || true
    kill $FRONTEND_PID 2>/dev/null || true
    echo -e "${GREEN}✓ Сервисы остановлены${NC}"
    exit 0
}

trap cleanup SIGINT SIGTERM

check_dependencies
start_backend
start_frontend

echo ""
echo "=========================================="
echo -e "${GREEN}Система запущена.${NC}"
echo "=========================================="
echo ""
echo "Frontend: http://localhost:8080"
echo "Backend:  http://localhost:8000"
echo "API Docs: http://localhost:8000/docs"
echo ""

wait
