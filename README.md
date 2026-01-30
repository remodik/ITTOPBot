# Academic Reports System

Система интеллектуального анализа академических отчетов для учебных заведений.

## Описание

Веб-приложение для автоматической обработки и анализа отчетов по расписанию, успеваемости студентов, посещаемости и домашним заданиям. Система принимает .xls/.xlsx файлы и генерирует детальные отчеты с визуализацией.

## Возможности

1. **Отчет по расписанию групп** - Автоматический подсчет количества пар по каждой дисциплине
2. **Отчет по темам занятий** - Проверка корректности формата записи тем (формат: "Урок № _. Тема: _")
3. **Отчет по студентам** - Анализ успеваемости (студенты со средней оценкой за ДЗ = 1 или оценкой за классную работу < 3)
4. **Отчет по посещаемости** - Контроль посещаемости преподавателей (< 40%)
5. **Отчет по проверке ДЗ** - Мониторинг проверки домашних заданий преподавателями (< 70%)
6. **Отчет по сданным ДЗ студентами** - Отслеживание выполнения заданий студентами (< 70%)

## Технологии

### Frontend
- HTML5
- CSS3 (с CSS Variables)
- Vanilla JavaScript (без фреймворков)

### Backend
- Python 3.8+
- FastAPI
- pandas (обработка Excel)
- openpyxl / xlrd (чтение Excel файлов)
- MongoDB (хранение истории отчетов)
- Motor (асинхронный драйвер MongoDB)

## Требования

- Python 3.8 или выше
- MongoDB 4.0 или выше (локальный или MongoDB Atlas)
- Современный веб-браузер

## Установка

### 1. Клонирование репозитория

```bash
git clone <repository-url>
cd CollegeSite
```

### 2. Настройка MongoDB

#### Вариант A: Локальный MongoDB
Установите MongoDB с официального сайта: https://www.mongodb.com/try/download/community

#### Вариант B: MongoDB Atlas (облачная БД)
1. Создайте бесплатный аккаунт на https://www.mongodb.com/cloud/atlas
2. Создайте кластер
3. Получите строку подключения

### 3. Настройка Backend

```bash
cd backend

# Отредактируйте файл .env и укажите ваши настройки MongoDB
# Для локального MongoDB:
MONGO_URL=mongodb://localhost:27017
DB_NAME=college_reports

# Для MongoDB Atlas:
# MONGO_URL=mongodb+srv://username:password@cluster.mongodb.net/
# DB_NAME=college_reports
```

### 4. Установка зависимостей Python

```bash
# Linux/Mac
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Windows
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

## Запуск

### Быстрый старт с Docker (рекомендуется)

Если у вас установлен Docker и Docker Compose:

```bash
# Клонируйте репозиторий
git clone <repository-url>
cd CollegeSite

# Запустите все сервисы одной командой
docker-compose up -d

# Проверьте статус
docker-compose ps

# Для остановки
docker-compose down
```

После запуска:
- **Frontend**: http://localhost:8080
- **Backend API**: http://localhost:8000
- **MongoDB**: localhost:27017

### Linux/Mac

```bash
# Запуск всей системы одной командой
./start.sh

# Или запуск отдельно:
# Backend
cd backend && ./start.sh

# Frontend (в другом терминале)
cd frontend && ./start.sh
```

### Windows

```batch
REM Backend
cd backend
start.bat

REM Frontend (в другом окне командной строки)
cd frontend
start.bat
```

### Доступ к приложению

- **Frontend**: http://localhost:8080
- **Backend API**: http://localhost:8000
- **API Documentation**: http://localhost:8000/docs
- **Alternative API Docs**: http://localhost:8000/redoc

## Использование

1. Откройте браузер и перейдите на http://localhost:8080
2. Выберите тип отчета (нажмите на одну из карточек)
3. Загрузите Excel файл (.xls или .xlsx):
   - Перетащите файл в область загрузки, или
   - Нажмите кнопку "Выбрать файл"
4. Система автоматически обработает файл и отобразит результаты
5. Просмотрите историю предыдущих отчетов во вкладке "История"

## Формат данных

### Отчет по расписанию
- Столбец с названием "Дисциплина", "Предмет" или "Урок"
- Каждая строка - одна пара

### Отчет по темам занятий
- Любой столбец с темами занятий
- Формат: "Урок № X. Тема: название темы"

### Отчет по студентам
- Столбец "ФИО" или "Студент" - имя студента
- Столбцы с оценками за домашнюю и классную работу

### Отчет по посещаемости
- Столбец "ФИО" или "Преподаватель" - имя преподавателя
- Столбец с процентом посещаемости

### Отчет по проверке ДЗ
- Столбец "ФИО" или "Преподаватель" - имя преподавателя
- Столбцы "Процент проверки", "Выдано", "Проверено"

### Отчет по сданным ДЗ студентами
- Столбец "ФИО" или "Студент" - имя студента
- Столбцы с процентом выполнения или количеством сданных/заданных работ

## Структура проекта

```
CollegeSite/
├── backend/
│   ├── server.py           # Главный файл FastAPI сервера
│   ├── requirements.txt    # Python зависимости
│   ├── .env               # Конфигурация (создайте на основе .env.example)
│   ├── start.sh           # Скрипт запуска (Linux/Mac)
│   └── start.bat          # Скрипт запуска (Windows)
├── frontend/
│   └── public/
│       ├── index.html     # Главная страница
│       ├── main.js        # JavaScript (если отдельный файл)
│       └── debug-monitor.js
├── start.sh              # Главный скрипт запуска (Linux/Mac)
└── README.md            # Этот файл
```

## API Endpoints

### POST `/api/reports/upload`
Загрузка и обработка отчета
- Параметры: `file` (multipart/form-data), `report_type` (form field)
- Возвращает: обработанный отчет с результатами

### GET `/api/reports/history`
Получение истории всех отчетов
- Возвращает: список всех обработанных отчетов

### GET `/api/reports/{report_id}`
Получение конкретного отчета по ID
- Возвращает: детали отчета

### DELETE `/api/reports/{report_id}`
Удаление отчета
- Возвращает: подтверждение удаления

## Примеры тестовых данных

Примеры Excel файлов для тестирования можно найти по ссылкам из ТЗ:
- [Расписание групп](https://docs.google.com/spreadsheets/d/1l2lzy5Vki11s9V074m-piCAX2hsn9mEJ/edit?gid=1967042033#gid=1967042033)
- [Темы занятий](https://docs.google.com/spreadsheets/d/1TP9Rdzu51GBSSzDkH-XOmuD9HUykZg0j/edit)
- [Отчет по студентам](https://docs.google.com/spreadsheets/d/1ttBkXFDm9jlzoxI_Tm7l0DUm6-ZROdMj/edit)
- [Посещаемость](https://docs.google.com/spreadsheets/d/1B1q27X4tOFOuh1KaRORfDY-Ip89K37V_/edit)
- [Проверка ДЗ](https://docs.google.com/spreadsheets/d/1LOjNCjb1d8AKAR6ydxfM8ClBKAzcCp8G/edit)
- [Сданные ДЗ студентами](https://docs.google.com/spreadsheets/d/1pFNNJS_KVMdRTkKueZXJu0Gf3ImTD27m/edit)

## Устранение неполадок

### MongoDB не запускается
- Убедитесь, что MongoDB установлен и запущен
- Проверьте правильность строки подключения в `.env`
- Для MongoDB Atlas проверьте Network Access и Database Access настройки

### Backend не запускается
- Проверьте, что установлены все зависимости: `pip install -r requirements.txt`
- Убедитесь, что порт 8000 не занят другим приложением
- Проверьте логи на наличие ошибок

### Frontend не отображается
- Проверьте, что Python 3 установлен: `python3 --version`
- Убедитесь, что порт 8080 не занят
- Проверьте, что backend запущен и доступен

### Ошибка CORS
- Проверьте настройку `CORS_ORIGINS` в `.env`
- Убедитесь, что frontend и backend запущены на правильных портах

## Разработка

### Добавление нового типа отчета

1. Добавьте обработчик в `backend/server.py`:
```python
def process_new_report(df: pd.DataFrame) -> dict:
    # Ваша логика обработки
    return result
```

2. Добавьте в словарь процессоров:
```python
REPORT_PROCESSORS = {
    # ...
    "new_report": process_new_report
}
```

3. Добавьте карточку в `frontend/public/index.html`

## Лицензия

MIT

## Поддержка

При возникновении проблем создайте issue в репозитории проекта.
