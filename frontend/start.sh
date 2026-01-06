#!/bin/bash

set -e

echo "================================"
echo "  Frontend Server"
echo "================================"
echo ""

GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

cd "$(dirname "$0")"

if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Ошибка: Python3 не установлен${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Python3: $(python3 --version)${NC}"

if [ -d "public" ]; then
    cd public
fi

if [ ! -f "index.html" ]; then
    echo -e "${RED}Ошибка: index.html не найден!${NC}"
    exit 1
fi

echo -e "${GREEN}✓ index.html найден.${NC}"
echo ""
echo -e "${GREEN}Запуск сервера...${NC}"
echo -e "${GREEN}→ http://localhost:8080${NC}"
echo ""

python3 -m http.server 8080
