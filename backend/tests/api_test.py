import importlib
import os
import sys
import uuid
from io import BytesIO

import pandas as pd
from fastapi.testclient import TestClient


def load_server(tmp_path):
    os.environ["COLLEGE_DB_PATH"] = str(tmp_path / "test.db")

    if "backend.database" in sys.modules:
        importlib.reload(sys.modules["backend.database"])
    else:
        importlib.import_module("backend.database")

    if "backend.server" in sys.modules:
        importlib.reload(sys.modules["backend.server"])
    else:
        importlib.import_module("backend.server")

    return sys.modules["backend.server"]


def create_admin(server_module):
    user_id = str(uuid.uuid4())
    password = "password123"
    server_module.db.create_user(
        {
            "id": user_id,
            "email": "admin@example.com",
            "password": server_module.get_password_hash(password),
            "role": "admin",
            "is_superadmin": True,
            "can_delete_without_approval": True,
            "created_at": "2024-01-01T00:00:00+00:00",
        }
    )
    token = server_module.create_access_token({"sub": user_id})
    return password, token


def test_auth_and_users(tmp_path):
    server = load_server(tmp_path)
    client = TestClient(server.app)

    password, token = create_admin(server)

    login_response = client.post(
        "/api/auth/login",
        json={"email": "admin@example.com", "password": password},
    )
    assert login_response.status_code == 200

    headers = {"Authorization": f"Bearer {token}"}
    me_response = client.get("/api/auth/me", headers=headers)
    assert me_response.status_code == 200

    create_user_response = client.post(
        "/api/users",
        json={"email": "moderator@example.com", "role": "moderator"},
        headers=headers,
    )
    assert create_user_response.status_code == 200

    list_users_response = client.get("/api/users", headers=headers)
    assert list_users_response.status_code == 200
    assert len(list_users_response.json()["users"]) == 2


def test_reports_flow(tmp_path):
    server = load_server(tmp_path)
    client = TestClient(server.app)

    _, token = create_admin(server)
    headers = {"Authorization": f"Bearer {token}"}

    df = pd.DataFrame({"Темы": ["Урок № 1. Тема: Введение"]})
    buffer = BytesIO()
    df.to_excel(buffer, index=False)
    buffer.seek(0)

    upload_response = client.post(
        "/api/reports/upload",
        data={"report_type": "topics", "period": "month"},
        files={"file": ("topics.xlsx", buffer, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers=headers,
    )
    assert upload_response.status_code == 200
    report_id = upload_response.json()["id"]

    history_response = client.get("/api/reports/history", headers=headers)
    assert history_response.status_code == 200
    assert history_response.json()["history"][0]["id"] == report_id

    get_response = client.get(f"/api/reports/{report_id}", headers=headers)
    assert get_response.status_code == 200

    delete_response = client.delete(f"/api/reports/{report_id}", headers=headers)
    assert delete_response.status_code == 200