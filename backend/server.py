import io
import logging
import os
import re
import secrets
import time
import uuid
from collections import defaultdict
from contextlib import suppress
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from enum import StrEnum

import pandas as pd
from dotenv import load_dotenv
from fastapi import FastAPI, APIRouter, File, UploadFile, Form, HTTPException, Depends, status, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, Field, ConfigDict, EmailStr
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware

from database import db

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')


SECRET_KEY = os.environ.get('JWT_SECRET_KEY', secrets.token_urlsafe(32))
CSRF_SECRET = os.environ.get('CSRF_SECRET_KEY', secrets.token_urlsafe(32))
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 1440

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()


class Role(StrEnum):
    ADMIN = "admin"
    MODERATOR = "moderator"
    USER = "user"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, requests_per_minute: int = 60):
        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        self.requests = defaultdict(list)
    
    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host if request.client else "unknown"
        now = time.time()
        minute_ago = now - 60

        self.requests[client_ip] = [t for t in self.requests[client_ip] if t > minute_ago]

        if len(self.requests[client_ip]) >= self.requests_per_minute:
            return JSONResponse(
                status_code=429,
                content={"detail": "Слишком много запросов. Попробуйте позже."}
            )
        
        self.requests[client_ip].append(now)
        response = await call_next(request)
        return response


app = FastAPI(
    title="Academic Reports API",
    description="API для обработки академических отчетов",
    version="2.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc"
)

api_router = APIRouter(prefix="/api")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class UserRole(BaseModel):
    role: Role
    can_create_users: bool = True
    can_delete_users: bool = False
    requires_approval_for_delete: bool = True


class User(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    email: EmailStr
    hashed_password: str
    role: Role = Role.MODERATOR
    is_superadmin: bool = False
    can_delete_without_approval: bool = False
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    created_by: str | None = None


class UserCreate(BaseModel):
    email: EmailStr
    role: Role = Role.MODERATOR
    can_delete_without_approval: bool = False


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    id: str
    email: EmailStr
    role: Role
    is_superadmin: bool
    can_delete_without_approval: bool
    created_at: str
    created_by: str | None = None


class Token(BaseModel):
    access_token: str
    token_type: str
    user: UserResponse


class DeleteRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    requested_by: str
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    status: str = "pending"


class ReportResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    report_type: str
    filename: str
    result: Any
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    created_by: str | None = None
    created_by_email: EmailStr | None = None


class ReportHistoryItem(BaseModel):
    id: str
    report_type: str
    filename: str
    timestamp: str
    summary: str
    created_by: str | None = None
    created_by_email: EmailStr | None = None


REPORT_LABELS = {
    "schedule": "Расписание: кол-во пар по дисциплинам",
    "topics": "Темы занятий: проверка формата",
    "students": "Студенты: ДЗ=1 или кл.работа<3",
    "attendance": "Посещаемость: преподаватели <40%",
    "homework": "Проверка ДЗ: преподаватели <70%",
    "student_homework": "Сдача ДЗ: студенты <70%"
}


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def require_role(user: User, *roles: Role) -> None:
    if user.role not in roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Недостаточно прав. Требуется роль: {', '.join(r.value for r in roles)}"
        )


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Неверные учетные данные",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        token = credentials.credentials
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.get_user_by_id(user_id)
    if user is None:
        raise credentials_exception
    user["hashed_password"] = user.pop("password", "")
    return User(**user)


async def get_admin_user(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != Role.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Недостаточно прав. Требуется роль администратора"
        )
    return current_user


def generate_password(length: int = 12) -> str:
    return secrets.token_urlsafe(length)[:length]


def process_schedule(df: pd.DataFrame) -> dict:
    result = {
        "title": "Отчет по расписанию групп",
        "description": "Количество пар по каждой дисциплине",
        "groups": [],
        "total_pairs": 0
    }

    logger.info(f"Schedule report - Available columns: {list(df.columns)}")

    group_col = None
    for col in df.columns:
        col_lower = str(col).lower()
        if 'группа' in col_lower or 'group' in col_lower:
            group_col = col
            break

    day_order = {
        'понедельник': 1, 'вторник': 2, 'среда': 3, 'четверг': 4,
        'пятница': 5, 'суббота': 6, 'воскресенье': 7
    }

    day_cols = []
    for col in df.columns:
        col_str = str(col).lower()
        for day_name in day_order.keys():
            if day_name in col_str:
                day_cols.append((col, day_name))
                break

    logger.info(f"Found group_col: {group_col}, day_cols: {day_cols}")

    groups_data = {}

    for idx, row in df.iterrows():
        group_name = str(row[group_col]) if group_col and pd.notna(row[group_col]) else None
        if not group_name or group_name.lower() in ['nan', 'none', '']:
            continue

        if group_name not in groups_data:
            groups_data[group_name] = {
                "name": group_name,
                "disciplines": {},
                "total": 0
            }

        for day_col, day_name in day_cols:
            cell_value = row.get(day_col)
            if pd.notna(cell_value) and str(cell_value).strip():
                cell_str = str(cell_value).strip()
                
                subject = None
                if 'Предмет:' in cell_str or 'предмет:' in cell_str:
                    match = re.search(r'[Пп]редмет:\s*(.+?)(?:\n|\\n|$)', cell_str)
                    if match:
                        subject = match.group(1).strip()
                else:
                    subject = cell_str.split('\n')[0].strip()

                if subject:
                    time_val = "—"
                    col_idx = list(df.columns).index(day_col)
                    if col_idx > 0:
                        time_col = df.columns[col_idx - 1]
                        time_check = row.get(time_col)
                        if pd.notna(time_check) and ':' in str(time_check):
                            time_val = str(time_check)

                    if subject not in groups_data[group_name]["disciplines"]:
                        groups_data[group_name]["disciplines"][subject] = []
                    
                    groups_data[group_name]["disciplines"][subject].append({
                        "day": day_name.capitalize(),
                        "day_order": day_order[day_name],
                        "time": time_val
                    })
                    groups_data[group_name]["total"] += 1
                    result["total_pairs"] += 1

    for group_name, data in groups_data.items():
        disciplines_list = []
        
        for disc_name, occurrences in data["disciplines"].items():
            sorted_occurrences = sorted(occurrences, key=lambda x: (x["day_order"], x["time"]))
            
            disciplines_list.append({
                "name": disc_name,
                "count": len(occurrences),
                "occurrences": [{"day": o["day"], "time": o["time"]} for o in sorted_occurrences]
            })
        
        def get_first_occurrence_key(d):
            if d["occurrences"]:
                first = d["occurrences"][0]
                day_num = day_order.get(first["day"].lower(), 99)
                return day_num, first["time"]
            return 99, "99:99"
        
        disciplines_list = sorted(disciplines_list, key=get_first_occurrence_key)
        
        result["groups"].append({
            "name": data["name"],
            "disciplines": disciplines_list,
            "total": data["total"]
        })

    result["groups"] = sorted(result["groups"], key=lambda x: x["name"])

    return result


def process_topics(df: pd.DataFrame) -> dict:
    result = {
        "title": "Отчет по темам занятий",
        "description": "Проверка формата записи тем: 'Урок № _. Тема: _'",
        "valid": [],
        "invalid": [],
        "stats": {"valid_count": 0, "invalid_count": 0}
    }

    logger.info(f"Topics report - Available columns: {list(df.columns)}")
    logger.info(f"Topics report - DataFrame shape: {df.shape}")

    pattern = re.compile(r'Урок\s*№?\s*\d+\.?\s*Тема:?\s*.+', re.IGNORECASE)
    
    topic_keywords = [
        'урок', 'тема', 'занятие', 'лекция', 'практика', 
        'лабораторная', 'семинар', 'контрольная', 'самостоятельная',
        'работа', 'задание', 'повторение', 'изучение', 'введение',
        'основы', 'понятие', 'определение', 'раздел', 'глава'
    ]

    valid_groups = {}
    invalid_groups = {}
    
    checked_cells = 0
    matched_keywords = 0

    for col in df.columns:
        for idx, val in enumerate(df[col]):
            if pd.notna(val):
                val_str = str(val).strip()
                if val_str and len(val_str) > 3:
                    checked_cells += 1
                    display_text = val_str[:100] + ("..." if len(val_str) > 100 else "")
                    
                    if pattern.match(val_str):
                        if display_text not in valid_groups:
                            valid_groups[display_text] = []
                        valid_groups[display_text].append({
                            "row": idx + 2,
                            "column": str(col)
                        })
                        result["stats"]["valid_count"] += 1
                        logger.info(f"  Valid topic found at row {idx + 2}: {display_text[:50]}")
                    else:
                        val_lower = val_str.lower()
                        is_topic = any(keyword in val_lower for keyword in topic_keywords)
                        
                        if is_topic:
                            matched_keywords += 1
                            if display_text not in invalid_groups:
                                invalid_groups[display_text] = {
                                    "reason": "Неверный формат. Ожидается: 'Урок № _. Тема: _'",
                                    "occurrences": []
                                }
                            invalid_groups[display_text]["occurrences"].append({
                                "row": idx + 2,
                                "column": str(col)
                            })
                            result["stats"]["invalid_count"] += 1
                            logger.info(f"  Invalid topic found at row {idx + 2}: {display_text[:50]}")

    logger.info(f"Topics report - Checked {checked_cells} cells total")
    logger.info(f"Topics report - Found {matched_keywords} cells with keywords")
    logger.info(f"Topics report - Valid: {result['stats']['valid_count']}, Invalid: {result['stats']['invalid_count']}")

    for text, occurrences in valid_groups.items():
        sorted_occ = sorted(occurrences, key=lambda x: x["row"])
        result["valid"].append({
            "text": text,
            "count": len(occurrences),
            "occurrences": sorted_occ
        })

    for text, data in invalid_groups.items():
        sorted_occ = sorted(data["occurrences"], key=lambda x: x["row"])
        result["invalid"].append({
            "text": text,
            "reason": data["reason"],
            "count": len(data["occurrences"]),
            "occurrences": sorted_occ
        })

    result["valid"] = sorted(result["valid"], key=lambda x: x["occurrences"][0]["row"] if x["occurrences"] else 0)
    result["invalid"] = sorted(result["invalid"], key=lambda x: x["occurrences"][0]["row"] if x["occurrences"] else 0)

    logger.info(f"Topics report - Returning {len(result['valid'])} valid groups and {len(result['invalid'])} invalid groups")

    return result


def process_students(df: pd.DataFrame) -> dict:
    result = {
        "title": "Отчет по студентам",
        "description": "Студенты со средней оценкой за ДЗ = 1 или оценкой за классную работу ниже 3",
        "students": [],
        "stats": {"total_found": 0}
    }

    name_cols = [col for col in df.columns if
                 any(word in str(col).lower() for word in ['фио', 'студент', 'имя', 'name', 'ученик'])]
    hw_cols = [col for col in df.columns if
               any(word in str(col).lower() for word in ['домашн', 'дз', 'homework', 'hw'])]
    class_cols = [col for col in df.columns if
                  any(word in str(col).lower() for word in ['классн', 'урок', 'class', 'работа'])]

    name_col = name_cols[0] if name_cols else df.columns[0]

    for idx, row in df.iterrows():
        student_name = str(row[name_col]) if pd.notna(row[name_col]) else f"Строка {idx + 2}"

        hw_grade = None
        class_grade = None

        for col in hw_cols:
            val = row.get(col)
            if pd.notna(val):
                with suppress(ValueError, TypeError):
                    hw_grade = float(val)
                    break

        for col in class_cols:
            val = row.get(col)
            if pd.notna(val):
                with suppress(ValueError, TypeError):
                    class_grade = float(val)
                    break

        if hw_grade is None or class_grade is None:
            numeric_cols = [col for col in df.columns if
                            df[col].dtype in ['int64', 'float64'] or str(df[col].dtype) == 'object']
            for col in numeric_cols:
                val = row.get(col)
                if pd.notna(val):
                    with suppress(ValueError, TypeError):
                        grade = float(val)
                        if 0 <= grade <= 5:
                            if hw_grade is None:
                                hw_grade = grade
                            elif class_grade is None:
                                class_grade = grade

        issues = []
        if hw_grade is not None and hw_grade == 1:
            issues.append(f"Средняя оценка за ДЗ = {hw_grade}")
        if class_grade is not None and class_grade < 3:
            issues.append(f"Оценка за классную работу = {class_grade}")

        if issues:
            result["students"].append({
                "name": student_name,
                "hw_grade": hw_grade,
                "class_grade": class_grade,
                "issues": issues
            })
            result["stats"]["total_found"] += 1

    return result


def process_attendance(df: pd.DataFrame) -> dict:
    result = {
        "title": "Отчет по посещаемости",
        "description": "Преподаватели, посещаемость пар у которых ниже 40%",
        "teachers": [],
        "stats": {"total_found": 0, "threshold": 40}
    }

    name_cols = [col for col in df.columns if
                 any(word in str(col).lower() for word in ['фио', 'преподаватель', 'учитель', 'педагог', 'name'])]
    attendance_cols = [col for col in df.columns if
                       any(word in str(col).lower() for word in ['посещаемость', 'attendance', '%', 'процент'])]

    name_col = name_cols[0] if name_cols else df.columns[0]

    for idx, row in df.iterrows():
        teacher_name = str(row[name_col]) if pd.notna(row[name_col]) else None
        if not teacher_name or teacher_name.lower() in ['nan', 'none', '']:
            continue

        attendance = None

        for col in attendance_cols:
            val = row.get(col)
            if pd.notna(val):
                with suppress(ValueError, TypeError):
                    val_str = str(val).replace('%', '').strip()
                    attendance = float(val_str)
                    break

        if attendance is None:
            for col in df.columns:
                val = row.get(col)
                if pd.notna(val):
                    with suppress(ValueError, TypeError):
                        val_str = str(val).replace('%', '').strip()
                        num = float(val_str)
                        if 0 <= num <= 100:
                            attendance = num
                            break

        if attendance is not None and attendance < 40:
            result["teachers"].append({
                "name": teacher_name,
                "attendance": round(attendance, 1),
                "status": "critical" if attendance < 20 else "warning"
            })
            result["stats"]["total_found"] += 1

    result["teachers"] = sorted(result["teachers"], key=lambda x: x["attendance"])
    return result


def process_homework(df: pd.DataFrame, period: str = "month") -> dict:
    period_labels = {
        "month": "за месяц",
        "week": "за неделю",
        "day": "за день"
    }

    result = {
        "title": f"Отчет по проверке домашних заданий ({period_labels.get(period, period)})",
        "description": "Преподаватели, чей процент проверки заданий ниже 70%",
        "teachers": [],
        "stats": {"total_found": 0, "threshold": 70},
        "period": period
    }

    name_cols = [col for col in df.columns if
                 any(word in str(col).lower() for word in ['фио', 'преподаватель', 'учитель', 'педагог', 'name'])]

    name_col = name_cols[0] if name_cols else df.columns[0]

    logger.info(f"Homework report - Available columns: {list(df.columns)}")

    col_mapping = {}
    if len(df) > 0:
        first_row = df.iloc[0]
        for col in df.columns:
            val = first_row.get(col)
            if pd.notna(val):
                col_mapping[col] = str(val).lower()

    logger.info(f"Column mapping from first row: {col_mapping}")

    period_start_cols = {
        "month": "Месяц",
        "week": "Неделя",
        "day": "День"
    }

    issued_col = None
    checked_col = None

    start_col = period_start_cols.get(period, "Месяц")
    found_period = False

    cols_list = list(df.columns)
    for i, col in enumerate(cols_list):
        if col == start_col:
            found_period = True
            for j in range(i + 1, min(i + 5, len(cols_list))):
                next_col = cols_list[j]
                val_lower = col_mapping.get(next_col, "")
                if 'выдано' in val_lower or 'выдан' in val_lower:
                    issued_col = next_col
                elif 'проверено' in val_lower or 'проверен' in val_lower:
                    checked_col = next_col
            break

    if not found_period or (issued_col is None and checked_col is None):
        for col, val_lower in col_mapping.items():
            if any(word in val_lower for word in ['выдано', 'выдан', 'задано', 'issued']):
                if issued_col is None:
                    issued_col = col
            elif any(word in val_lower for word in ['проверено', 'проверен', 'checked', 'оценено']):
                if checked_col is None:
                    checked_col = col

    logger.info(f"Found columns for period '{period}' - issued: {issued_col}, checked: {checked_col}")

    start_idx = 1 if col_mapping else 0

    for idx, row in df.iloc[start_idx:].iterrows():
        teacher_name = str(row[name_col]) if pd.notna(row[name_col]) else None
        if not teacher_name or teacher_name.lower() in ['nan', 'none', '', 'всего']:
            continue

        check_percent = None
        issued = None
        checked = None

        if issued_col is not None:
            val = row.get(issued_col)
            if pd.notna(val):
                with suppress(ValueError, TypeError):
                    issued = float(val)

        if checked_col is not None:
            val = row.get(checked_col)
            if pd.notna(val):
                with suppress(ValueError, TypeError):
                    checked = float(val)

        if issued is None or issued == 0:
            continue

        if issued is not None and issued > 0 and checked is not None:
            check_percent = (checked / issued) * 100
            issued_int = int(issued) if issued is not None else 0
            checked_int = int(checked) if checked is not None else 0

        if check_percent is not None and check_percent < 70:
            result["teachers"].append({
                "name": teacher_name,
                "check_percent": round(check_percent, 1),
                "issued": int(issued) if issued is not None else "—",
                "checked": int(checked) if checked is not None else "—",
                "status": "критично" if check_percent < 50 else "низкий",
                "message":  f"Проверено {checked_int} из {issued_int} заданий ({round(check_percent, 1)}%)"
            })
            result["stats"]["total_found"] += 1

    result["teachers"] = sorted(result["teachers"], key=lambda x: x["check_percent"])
    return result


def process_student_homework(df: pd.DataFrame) -> dict:
    result = {
        "title": "Отчет по сданным домашним заданиям студентами",
        "description": "Студенты с процентом выполненных заданий ниже 70%",
        "students": [],
        "stats": {"total_found": 0, "threshold": 70}
    }

    logger.info(f"Student homework report - Available columns: {list(df.columns)}")

    name_col = None
    for col in df.columns:
        col_lower = str(col).lower()
        if any(word in col_lower for word in ['fio', 'фио', 'студент', 'имя', 'name', 'ученик']):
            name_col = col
            break
    if name_col is None:
        name_col = df.columns[0]

    percent_col = None
    for col in df.columns:
        col_lower = str(col).lower()
        if 'percentage' in col_lower and 'homework' in col_lower:
            percent_col = col
            break
        if any(word in col_lower for word in ['процент', '% дз', 'percent hw', 'completion']):
            percent_col = col
            break

    logger.info(f"Found columns - name: {name_col}, percent: {percent_col}")

    for idx, row in df.iterrows():
        student_name = str(row[name_col]) if pd.notna(row[name_col]) else f"Строка {idx + 2}"

        if student_name.lower() in ['nan', 'none', '', 'всего', 'итого', 'total']:
            continue

        completion_percent = None

        if percent_col is not None:
            val = row.get(percent_col)
            if pd.notna(val):
                with suppress(ValueError, TypeError):
                    val_str = str(val).replace('%', '').replace('-', '').strip()
                    if val_str:
                        completion_percent = float(val_str)

        if completion_percent is not None and completion_percent < 70:
            result["students"].append({
                "name": student_name,
                "completion_percent": round(completion_percent, 1)
            })
            result["stats"]["total_found"] += 1

    result["students"] = sorted(result["students"], key=lambda x: x["completion_percent"])
    return result


REPORT_PROCESSORS = {
    "schedule": process_schedule,
    "topics": process_topics,
    "students": process_students,
    "attendance": process_attendance,
    "homework": process_homework,
    "student_homework": process_student_homework
}


@api_router.get("/")
async def root():
    return {"message": "Academic Reports API"}


@api_router.post("/auth/login")
async def login(user_login: UserLogin):
    user = db.get_user_by_email(user_login.email)

    if not user or not verify_password(user_login.password, user["password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный email или пароль"
        )

    user["hashed_password"] = user.pop("password", "")
    user_with_defaults = User(**user)

    access_token = create_access_token(data={"sub": user["id"]})
    user_response = UserResponse(**user_with_defaults.model_dump())

    return Token(access_token=access_token, token_type="bearer", user=user_response)


@api_router.get("/auth/me")
async def get_me(current_user: User = Depends(get_current_user)):
    return UserResponse(**current_user.model_dump())


@api_router.post("/users", response_model=dict)
async def create_user(
    user_create: UserCreate,
    current_user: User = Depends(get_current_user)
):
    if current_user.role != Role.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Недостаточно прав. Создавать пользователей может только администратор"
        )

    existing_user = db.get_user_by_email(user_create.email)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Пользователь с таким email уже существует"
        )

    password = generate_password()
    hashed_password = get_password_hash(password)

    user = User(
        email=user_create.email,
        hashed_password=hashed_password,
        role=user_create.role,
        can_delete_without_approval=user_create.can_delete_without_approval,
        created_by=current_user.id
    )

    user_data = user.model_dump()
    user_data['password'] = user_data.pop('hashed_password')
    db.create_user(user_data)

    return {
        "user": UserResponse(**user.model_dump()),
        "password": password
    }


@api_router.get("/users")
async def list_users(current_user: User = Depends(get_current_user)):
    if current_user.role not in [Role.ADMIN, Role.MODERATOR]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Недостаточно прав"
        )

    users = db.get_all_users()
    result = []
    for u in users:
        u['hashed_password'] = u.pop('password', '')
        result.append(UserResponse(**u))
    return {"users": result}


@api_router.delete("/users/{user_id}")
async def delete_user(user_id: str, current_user: User = Depends(get_current_user)):
    target_user = db.get_user_by_id(user_id)

    if not target_user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    if target_user.get("is_superadmin", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Невозможно удалить суперадминистратора"
        )

    if current_user.role == Role.ADMIN and target_user.get("role") == Role.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Модераторы не могут удалять администраторов"
        )

    if current_user.role == Role.ADMIN:
        deleted = db.delete_user(user_id)

        if not deleted:
            raise HTTPException(status_code=404, detail="Пользователь не найден")

        db.delete_delete_requests_by_user_id(user_id)

        return {"success": True, "message": "Пользователь удален"}

    elif current_user.role == Role.MODERATOR:
        if current_user.can_delete_without_approval:
            deleted = db.delete_user(user_id)

            if not deleted:
                raise HTTPException(status_code=404, detail="Пользователь не найден")

            return {"success": True, "message": "Пользователь удален"}
        else:
            existing_request = db.get_pending_delete_request(user_id)

            if existing_request:
                raise HTTPException(
                    status_code=400,
                    detail="Запрос на удаление уже существует"
                )

            delete_request = DeleteRequest(
                user_id=user_id,
                requested_by=current_user.id
            )

            db.create_delete_request(delete_request.model_dump())

            return {
                "success": True,
                "message": "Запрос на удаление отправлен",
                "requires_approval": True
            }
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Недостаточно прав"
        )


@api_router.get("/delete-requests")
async def list_delete_requests(admin_user: User = Depends(get_admin_user)):
    requests = db.get_all_pending_delete_requests()

    for req in requests:
        user = db.get_user_by_id(req["user_id"])
        requester = db.get_user_by_id(req["requested_by"])

        if user:
            user['hashed_password'] = user.pop('password', '')
            req["user"] = UserResponse(**user)
        else:
            req["user"] = None
            
        if requester:
            requester['hashed_password'] = requester.pop('password', '')
            req["requester"] = UserResponse(**requester)
        else:
            req["requester"] = None

    return {"requests": requests}


@api_router.post("/delete-requests/{request_id}/approve")
async def approve_delete_request(request_id: str, admin_user: User = Depends(get_admin_user)):
    delete_request = db.get_delete_request_by_id(request_id)

    if not delete_request:
        raise HTTPException(status_code=404, detail="Запрос не найден")

    if delete_request["status"] != "pending":
        raise HTTPException(status_code=400, detail="Запрос уже обработан")

    db.delete_user(delete_request["user_id"])
    db.update_delete_request_status(request_id, "approved")

    return {"success": True, "message": "Пользователь удален"}


@api_router.post("/delete-requests/{request_id}/reject")
async def reject_delete_request(request_id: str, admin_user: User = Depends(get_admin_user)):
    delete_request = db.get_delete_request_by_id(request_id)

    if not delete_request:
        raise HTTPException(status_code=404, detail="Запрос не найден")

    if delete_request["status"] != "pending":
        raise HTTPException(status_code=400, detail="Запрос уже обработан")

    db.update_delete_request_status(request_id, "rejected")

    return {"success": True, "message": "Запрос отклонен"}


@api_router.patch("/users/{user_id}/delete-permission")
async def update_delete_permission(
    user_id: str,
    can_delete_without_approval: bool,
    admin_user: User = Depends(get_admin_user)
):
    updated = db.update_user(user_id, {"can_delete_without_approval": can_delete_without_approval})

    if not updated:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    return {"success": True, "message": "Права обновлены"}


@api_router.post("/reports/upload")
async def upload_and_process(
        file: UploadFile = File(...),
        report_type: str = Form(...),
        period: str = Form(default="month"),
        current_user: User = Depends(get_current_user)
):
    if report_type not in REPORT_PROCESSORS:
        raise HTTPException(status_code=400, detail=f"Неизвестный тип отчета: {report_type}")

    content = await file.read()

    try:
        filename = (file.filename or "").lower()
        ext = Path(filename).suffix
        logger.info(f"Processing file: {filename}, extension: {ext}, size: {len(content)} bytes")

        df = None
        errors = []

        engines = ["openpyxl", "xlrd", None]
        if ext == ".xls":
            engines = ["xlrd", "openpyxl", None]

        for engine in engines:
            try:
                logger.info(f"Trying engine: {engine}")
                df = pd.read_excel(io.BytesIO(content), engine=engine)
                logger.info(f"Success with engine: {engine}")
                break
            except Exception as engine_error:
                errors.append(f"{engine}: {engine_error}")
                continue

        if df is None:
            raise ValueError(f"Не удалось прочитать файл. Ошибки: {'; '.join(errors)}")

        processor = REPORT_PROCESSORS[report_type]

        if report_type == "homework":
            result_data = processor(df, period=period)
        else:
            result_data = processor(df)

        report = ReportResult(
            report_type=report_type,
            filename=file.filename,
            result=result_data,
            created_by=current_user.id,
            created_by_email=current_user.email
        )

        db.insert_report(report.model_dump())

        return {
            "id": report.id,
            "report_type": report.report_type,
            "report_label": REPORT_LABELS.get(report_type, report_type),
            "filename": report.filename,
            "result": result_data,
            "timestamp": report.timestamp,
            "created_by": report.created_by,
            "created_by_email": report.created_by_email
        }

    except Exception as e:
        logger.error(f"Error processing file: {e}")
        raise HTTPException(status_code=400, detail=f"Ошибка обработки файла: {str(e)}")


@api_router.get("/reports/history")
async def get_report_history(current_user: User = Depends(get_current_user)):
    reports = db.get_all_reports(limit=100)

    history = []
    for r in reports:
        result = r.get("result", {})

        if r["report_type"] == "schedule":
            summary = f"Найдено {result.get('total_pairs', 0)} пар"
        elif r["report_type"] == "topics":
            stats = result.get("stats", {})
            summary = f"Верных: {stats.get('valid_count', 0)}, неверных: {stats.get('invalid_count', 0)}"
        elif r["report_type"] == "students":
            summary = f"Найдено {result.get('stats', {}).get('total_found', 0)} студентов"
        elif r["report_type"] == "attendance":
            summary = f"Найдено {result.get('stats', {}).get('total_found', 0)} преподавателей"
        elif r["report_type"] == "homework":
            summary = f"Найдено {result.get('stats', {}).get('total_found', 0)} преподавателей"
        elif r["report_type"] == "student_homework":
            summary = f"Найдено {result.get('stats', {}).get('total_found', 0)} студентов"
        else:
            summary = ""

        history.append({
            "id": r["id"],
            "report_type": r["report_type"],
            "report_label": REPORT_LABELS.get(r["report_type"], r["report_type"]),
            "filename": r["filename"],
            "timestamp": r["timestamp"],
            "summary": summary,
            "created_by": r.get("created_by"),
            "created_by_email": r.get("created_by_email")
        })

    return {"history": history}


@api_router.get("/reports/{report_id}")
async def get_report(report_id: str, current_user: User = Depends(get_current_user)):
    report = db.get_report_by_id(report_id)

    if not report:
        raise HTTPException(status_code=404, detail="Отчет не найден")

    return report


@api_router.delete("/reports/{report_id}")
async def delete_report(report_id: str, current_user: User = Depends(get_current_user)):
    deleted = db.delete_report(report_id)
    
    if not deleted:
        raise HTTPException(status_code=404, detail="Отчет не найден")

    return {"success": True, "message": "Отчет удален"}


@api_router.get("/health")
async def health():
    return {"status": "ok"}


app.add_middleware(SecurityHeadersMiddleware)

app.add_middleware(RateLimitMiddleware, requests_per_minute=120)

CORS_ORIGINS = os.environ.get('CORS_ORIGINS', '*').split(',')
CORS_ORIGINS = [origin.strip() for origin in CORS_ORIGINS if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True if CORS_ORIGINS != ['*'] else False,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(api_router)
