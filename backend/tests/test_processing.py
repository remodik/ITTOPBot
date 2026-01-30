import importlib
import os
import sys

import pandas as pd


def load_server(tmp_path):
    os.environ["COLLEGE_DB_PATH"] = str(tmp_path / "test_processing.db")
    if "database" in sys.modules:
        importlib.reload(sys.modules["backend.database"])
    else:
        importlib.import_module("backend.database")
    if "server" in sys.modules:
        importlib.reload(sys.modules["backend.server"])
    else:
        importlib.import_module("backend.server")
    return sys.modules["backend.server"]


def test_process_schedule_basic(tmp_path):
    server = load_server(tmp_path)
    df = pd.DataFrame(
        [
            {
                "Группа": "A-01",
                "Время": "09:00",
                "Понедельник": "Предмет: Математика\nПреподаватель: X",
            }
        ]
    )
    result = server.process_schedule(df)

    assert result["total_pairs"] == 1
    assert result["groups"][0]["name"] == "A-01"
    assert result["groups"][0]["disciplines"][0]["name"] == "Математика"


def test_process_topics_basic(tmp_path):
    server = load_server(tmp_path)
    df = pd.DataFrame({"Темы": ["Урок № 1. Тема: Введение", "Тема лекции"]})
    result = server.process_topics(df)

    assert result["stats"]["valid_count"] == 1
    assert result["stats"]["invalid_count"] == 1


def test_process_students_basic(tmp_path):
    server = load_server(tmp_path)
    df = pd.DataFrame(
        {
            "ФИО": ["Студент 1", "Студент 2"],
            "ДЗ": [1, 4],
            "Классная работа": [4, 2],
        }
    )
    result = server.process_students(df)

    assert result["stats"]["total_found"] == 2
    assert any("Средняя оценка" in issue for issue in result["students"][0]["issues"])


def test_process_attendance_basic(tmp_path):
    server = load_server(tmp_path)
    df = pd.DataFrame({"ФИО": ["Преподаватель"], "Посещаемость": ["30%"]})
    result = server.process_attendance(df)

    assert result["stats"]["total_found"] == 1
    assert result["teachers"][0]["attendance"] == 30.0


def test_process_homework_basic(tmp_path):
    server = load_server(tmp_path)
    df = pd.DataFrame(
        [
            {"ФИО": "", "Месяц": "", "Кол1": "Выдано", "Кол2": "Проверено"},
            {"ФИО": "Преподаватель", "Месяц": "Март", "Кол1": 10, "Кол2": 5},
        ]
    )
    result = server.process_homework(df, period="month")

    assert result["stats"]["total_found"] == 1
    assert result["teachers"][0]["check_percent"] == 50.0


def test_process_student_homework_basic(tmp_path):
    server = load_server(tmp_path)
    df = pd.DataFrame({"ФИО": ["Студент"], "Процент выполнения": [60]})
    result = server.process_student_homework(df)

    assert result["stats"]["total_found"] == 1
    assert result["students"][0]["completion_percent"] == 60.0