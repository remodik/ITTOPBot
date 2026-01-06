#!/bin/bash

set -e

echo "================================"
echo "  Backend Server"
echo "================================"
echo ""

GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

cd "$(dirname "$0")"

if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Ошибка: Python3 не установлен!${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Python3: $(python3 --version)${NC}"

if [ ! -d "venv" ]; then
    echo -e "${BLUE}Создание виртуального окружения...${NC}"
    python3 -m venv venv
    echo -e "${GREEN}✓ venv создан${NC}"
fi

source venv/bin/activate
echo -e "${GREEN}✓ venv активирован${NC}"

if [ -f "requirements.txt" ]; then
    echo -e "${BLUE}Установка зависимостей...${NC}"
    pip install -q -r requirements.txt
    echo -e "${GREEN}✓ Зависимости установлены.${NC}"
fi

if [ ! -f ".env" ]; then
    echo -e "${BLUE}Создание .env файла...${NC}"
    cat > .env << EOF
MONGO_URL=mongodb://localhost:27017
DB_NAME=college_reports
CORS_ORIGINS=http://localhost:8080,http://127.0.0.1:8080
EOF
    echo -e "${GREEN}✓ .env создан (используется локальный MongoDB)${NC}"
fi

echo ""
echo -e "${GREEN}Запуск сервера...${NC}"
echo -e "${GREEN}→ http://localhost:8000${NC}"
echo -e "${GREEN}→ API Docs: http://localhost:8000/docs${NC}"
echo ""

python3 -m uvicorn server:app --host 0.0.0.0 --port 8000 --reload
