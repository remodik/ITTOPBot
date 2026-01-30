import json
import os
import sqlite3
from abc import ABC, abstractmethod
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    POSTGRES_AVAILABLE = True
except ImportError:
    POSTGRES_AVAILABLE = False


DATABASE_URL = os.environ.get("DATABASE_URL")
DB_PATH = Path(os.environ.get("COLLEGE_DB_PATH", Path(__file__).parent / "college_reports.db"))


class DatabaseBackend(ABC):
    @abstractmethod
    @contextmanager
    def connection(self) -> Generator:
        pass

    @abstractmethod
    def execute(self, query: str, params: tuple = ()) -> Any:
        pass

    @abstractmethod
    def fetchone(self, query: str, params: tuple = ()) -> dict | None:
        pass

    @abstractmethod
    def fetchall(self, query: str, params: tuple = ()) -> list[dict]:
        pass

    @abstractmethod
    def execute_write(self, query: str, params: tuple = ()) -> int:
        pass


class SQLiteBackend(DatabaseBackend):
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connection(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def execute(self, query: str, params: tuple = ()) -> sqlite3.Cursor:
        with self.connection() as conn:
            return conn.execute(query, params)

    def fetchone(self, query: str, params: tuple = ()) -> dict | None:
        with self.connection() as conn:
            cursor = conn.execute(query, params)
            row = cursor.fetchone()
            return dict(row) if row else None

    def fetchall(self, query: str, params: tuple = ()) -> list[dict]:
        with self.connection() as conn:
            cursor = conn.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def execute_write(self, query: str, params: tuple = ()) -> int:
        with self.connection() as conn:
            cursor = conn.execute(query, params)
            return cursor.rowcount


class PostgreSQLBackend(DatabaseBackend):
    def __init__(self, database_url: str):
        self.database_url = database_url

    @contextmanager
    def connection(self) -> Generator:
        conn = psycopg2.connect(self.database_url)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def execute(self, query: str, params: tuple = ()) -> Any:
        query = self._convert_placeholders(query)
        with self.connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute(query, params)
            return cursor

    def fetchone(self, query: str, params: tuple = ()) -> dict | None:
        query = self._convert_placeholders(query)
        with self.connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute(query, params)
            row = cursor.fetchone()
            return dict(row) if row else None

    def fetchall(self, query: str, params: tuple = ()) -> list[dict]:
        query = self._convert_placeholders(query)
        with self.connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def execute_write(self, query: str, params: tuple = ()) -> int:
        query = self._convert_placeholders(query)
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return cursor.rowcount

    @staticmethod
    def _convert_placeholders(query: str) -> str:
        return query.replace("?", "%s")


def get_backend() -> DatabaseBackend:
    if DATABASE_URL and POSTGRES_AVAILABLE:
        return PostgreSQLBackend(DATABASE_URL)
    return SQLiteBackend(DB_PATH)


_backend: DatabaseBackend | None = None


def get_db() -> DatabaseBackend:
    global _backend
    if _backend is None:
        _backend = get_backend()
    return _backend


def init_db():
    backend = get_db()

    is_postgres = isinstance(backend, PostgreSQLBackend) if POSTGRES_AVAILABLE else False

    if is_postgres:
        with backend.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS reports (
                    id TEXT PRIMARY KEY,
                    report_type TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    result TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                )
            """)
    else:
        backend.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id TEXT PRIMARY KEY,
                report_type TEXT NOT NULL,
                filename TEXT NOT NULL,
                result TEXT NOT NULL,
                timestamp TEXT NOT NULL
            )
        """)

    if is_postgres:
        backend.execute("ALTER TABLE reports ADD COLUMN IF NOT EXISTS created_by TEXT")
        backend.execute("ALTER TABLE reports ADD COLUMN IF NOT EXISTS created_by_email TEXT")
    else:
        try:
            backend.execute("ALTER TABLE reports ADD COLUMN created_by TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            backend.execute("ALTER TABLE reports ADD COLUMN created_by_email TEXT")
        except sqlite3.OperationalError:
            pass


class Database:
    def __init__(self):
        init_db()
        self.create_users_table()
        self.create_delete_requests_table()

    @staticmethod
    def insert_report(report_data: dict[str, Any]) -> None:
        backend = get_db()
        backend.execute_write("""
            INSERT INTO reports (id, report_type, filename, result, timestamp, created_by, created_by_email)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            report_data['id'],
            report_data['report_type'],
            report_data['filename'],
            json.dumps(report_data['result'], ensure_ascii=False),
            report_data['timestamp'],
            report_data.get('created_by'),
            report_data.get('created_by_email')
        ))

    @staticmethod
    def get_all_reports(limit: int = 100) -> list[dict[str, Any]]:
        backend = get_db()
        rows = backend.fetchall(
            "SELECT * FROM reports ORDER BY timestamp DESC LIMIT ?",
            (limit,)
        )

        reports = []
        for row in rows:
            reports.append({
                'id': row['id'],
                'report_type': row['report_type'],
                'filename': row['filename'],
                'result': json.loads(row['result']),
                'timestamp': row['timestamp'],
                'created_by': row.get('created_by'),
                'created_by_email': row.get('created_by_email')
            })
        return reports

    @staticmethod
    def get_report_by_id(report_id: str) -> dict[str, Any] | None:
        backend = get_db()
        row = backend.fetchone("SELECT * FROM reports WHERE id = ?", (report_id,))

        if row:
            return {
                'id': row['id'],
                'report_type': row['report_type'],
                'filename': row['filename'],
                'result': json.loads(row['result']),
                'timestamp': row['timestamp'],
                'created_by': row.get('created_by'),
                'created_by_email': row.get('created_by_email')
            }
        return None

    @staticmethod
    def delete_report(report_id: str) -> bool:
        backend = get_db()
        deleted = backend.execute_write("DELETE FROM reports WHERE id = ?", (report_id,))
        return deleted > 0

    def create_users_table(self):
        backend = get_db()
        is_postgres = isinstance(backend, PostgreSQLBackend) if POSTGRES_AVAILABLE else False

        if is_postgres:
            with backend.connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        id TEXT PRIMARY KEY,
                        email TEXT UNIQUE NOT NULL,
                        password TEXT NOT NULL,
                        role TEXT DEFAULT 'user',
                        is_superadmin BOOLEAN DEFAULT FALSE,
                        can_delete_without_approval BOOLEAN DEFAULT FALSE,
                        created_at TEXT NOT NULL,
                        created_by TEXT
                    )
                """)
        else:
            backend.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    email TEXT UNIQUE NOT NULL,
                    password TEXT NOT NULL,
                    role TEXT DEFAULT 'user',
                    is_superadmin INTEGER DEFAULT 0,
                    can_delete_without_approval INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    created_by TEXT
                )
            """)
            self._migrate_users_table()

    @staticmethod
    def _migrate_users_table():
        backend = get_db()
        if isinstance(backend, SQLiteBackend):
            with backend.connection() as conn:
                cursor = conn.execute("PRAGMA table_info(users)")
                columns = [col[1] for col in cursor.fetchall()]

                if 'is_superadmin' not in columns:
                    conn.execute("ALTER TABLE users ADD COLUMN is_superadmin INTEGER DEFAULT 0")
                if 'can_delete_without_approval' not in columns:
                    conn.execute("ALTER TABLE users ADD COLUMN can_delete_without_approval INTEGER DEFAULT 0")
                if 'created_by' not in columns:
                    conn.execute("ALTER TABLE users ADD COLUMN created_by TEXT")

    @staticmethod
    def create_user(user_data: dict[str, Any]) -> None:
        password = user_data.get("password") or user_data.get("hashed_password")
        if not password:
            raise ValueError("User password is required (password/hashed_password)")

        backend = get_db()
        is_postgres = isinstance(backend, PostgreSQLBackend) if POSTGRES_AVAILABLE else False

        try:
            if is_postgres:
                backend.execute_write("""
                    INSERT INTO users (id, email, password, role, is_superadmin, can_delete_without_approval, created_at, created_by)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    user_data['id'],
                    user_data['email'],
                    password,
                    user_data.get('role', 'user'),
                    user_data.get('is_superadmin', False),
                    user_data.get('can_delete_without_approval', False),
                    user_data['created_at'],
                    user_data.get('created_by')
                ))
            else:
                backend.execute_write("""
                    INSERT INTO users (id, email, password, role, is_superadmin, can_delete_without_approval, created_at, created_by)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    user_data['id'],
                    user_data['email'],
                    password,
                    user_data.get('role', 'user'),
                    1 if user_data.get('is_superadmin') else 0,
                    1 if user_data.get('can_delete_without_approval') else 0,
                    user_data['created_at'],
                    user_data.get('created_by')
                ))
        except Exception as e:
            if "UNIQUE" in str(e).upper() or "unique" in str(e).lower():
                raise ValueError(f"User with this email already exists") from e
            raise ValueError(str(e)) from e

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        backend = get_db()
        row = backend.fetchone("SELECT * FROM users WHERE email = ?", (email,))

        if row:
            return self._row_to_user_dict(row)
        return None

    def get_user_by_id(self, user_id: str) -> dict[str, Any] | None:
        backend = get_db()
        row = backend.fetchone("SELECT * FROM users WHERE id = ?", (user_id,))

        if row:
            return self._row_to_user_dict(row)
        return None

    def get_all_users(self) -> list[dict[str, Any]]:
        backend = get_db()
        rows = backend.fetchall("SELECT * FROM users ORDER BY created_at DESC")
        return [self._row_to_user_dict(row) for row in rows]

    @staticmethod
    def delete_user(user_id: str) -> bool:
        backend = get_db()
        deleted = backend.execute_write("DELETE FROM users WHERE id = ?", (user_id,))
        return deleted > 0

    @staticmethod
    def update_user(user_id: str, updates: dict[str, Any]) -> bool:
        if not updates:
            return False

        backend = get_db()
        is_postgres = isinstance(backend, PostgreSQLBackend) if POSTGRES_AVAILABLE else False

        set_clauses = []
        values = []
        for key, value in updates.items():
            if key in ('is_superadmin', 'can_delete_without_approval'):
                if not is_postgres:
                    value = 1 if value else 0
            set_clauses.append(f"{key} = ?")
            values.append(value)

        values.append(user_id)
        query = f"UPDATE users SET {', '.join(set_clauses)} WHERE id = ?"

        updated = backend.execute_write(query, tuple(values))
        return updated > 0

    @staticmethod
    def _row_to_user_dict(row: dict) -> dict[str, Any]:
        d = dict(row)
        d['is_superadmin'] = bool(d.get('is_superadmin', 0))
        d['can_delete_without_approval'] = bool(d.get('can_delete_without_approval', 0))
        return d

    @staticmethod
    def create_delete_requests_table():
        backend = get_db()
        is_postgres = isinstance(backend, PostgreSQLBackend) if POSTGRES_AVAILABLE else False

        if is_postgres:
            with backend.connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS delete_requests (
                        id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        requested_by TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        status TEXT DEFAULT 'pending'
                    )
                """)
        else:
            backend.execute("""
                CREATE TABLE IF NOT EXISTS delete_requests (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    requested_by TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    FOREIGN KEY (user_id) REFERENCES users(id),
                    FOREIGN KEY (requested_by) REFERENCES users(id)
                )
            """)

    @staticmethod
    def create_delete_request(request_data: dict[str, Any]) -> None:
        backend = get_db()
        backend.execute_write("""
            INSERT INTO delete_requests (id, user_id, requested_by, created_at, status)
            VALUES (?, ?, ?, ?, ?)
        """, (
            request_data['id'],
            request_data['user_id'],
            request_data['requested_by'],
            request_data['created_at'],
            request_data.get('status', 'pending')
        ))

    @staticmethod
    def get_delete_request_by_id(request_id: str) -> dict[str, Any] | None:
        backend = get_db()
        return backend.fetchone("SELECT * FROM delete_requests WHERE id = ?", (request_id,))

    @staticmethod
    def get_pending_delete_request(user_id: str) -> dict[str, Any] | None:
        backend = get_db()
        return backend.fetchone(
            "SELECT * FROM delete_requests WHERE user_id = ? AND status = 'pending'",
            (user_id,)
        )

    @staticmethod
    def get_all_pending_delete_requests() -> list[dict[str, Any]]:
        backend = get_db()
        return backend.fetchall(
            "SELECT * FROM delete_requests WHERE status = 'pending' ORDER BY created_at DESC"
        )

    @staticmethod
    def update_delete_request_status(request_id: str, status: str) -> bool:
        backend = get_db()
        updated = backend.execute_write(
            "UPDATE delete_requests SET status = ? WHERE id = ?",
            (status, request_id)
        )
        return updated > 0

    @staticmethod
    def delete_delete_requests_by_user_id(user_id: str) -> int:
        backend = get_db()
        return backend.execute_write("DELETE FROM delete_requests WHERE user_id = ?", (user_id,))


db = Database()
