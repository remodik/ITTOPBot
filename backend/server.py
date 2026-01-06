import io
import logging
import os
import re
import uuid
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv
from fastapi import FastAPI, APIRouter, File, UploadFile, Form, HTTPException
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field, ConfigDict
from starlette.middleware.cors import CORSMiddleware

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

app = FastAPI()

api_router = APIRouter(prefix="/api")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ReportResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    report_type: str
    filename: str
    result: Any
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ReportHistoryItem(BaseModel):
    id: str
    report_type: str
    filename: str
    timestamp: str
    summary: str


REPORT_LABELS = {
    "schedule": "Расписание групп",
    "topics": "Темы занятий",
    "students": "Отчет по студентам",
    "attendance": "Посещаемость по преподавателям",
    "homework": "Проверка домашних заданий",
    "student_homework": "Сданные ДЗ студентами"
}


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
                return (day_num, first["time"])
            return (99, "99:99")
        
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

    pattern = re.compile(r'Урок\s*№?\s*\d+\.?\s*Тема:?\s*.+', re.IGNORECASE)

    valid_groups = {}
    invalid_groups = {}

    for col in df.columns:
        for idx, val in enumerate(df[col]):
            if pd.notna(val):
                val_str = str(val).strip()
                if val_str and len(val_str) > 3:
                    display_text = val_str[:100] + ("..." if len(val_str) > 100 else "")
                    
                    if pattern.match(val_str):
                        if display_text not in valid_groups:
                            valid_groups[display_text] = []
                        valid_groups[display_text].append({
                            "row": idx + 2,
                            "column": str(col)
                        })
                        result["stats"]["valid_count"] += 1
                    elif 'урок' in val_str.lower() or 'тема' in val_str.lower():
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

        if check_percent is not None and check_percent < 70:
            result["teachers"].append({
                "name": teacher_name,
                "check_percent": round(check_percent, 1),
                "issued": int(issued) if issued is not None else "—",
                "checked": int(checked) if checked is not None else "—",
                "status": "критично" if check_percent < 50 else "низкий"
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

    hw_grade_col = None
    for col in df.columns:
        col_lower = str(col).lower()
        if col_lower == 'homework' or col_lower == 'дз' or col_lower == 'домашн':
            hw_grade_col = col
            break

    logger.info(f"Found columns - name: {name_col}, percent: {percent_col}, hw_grade: {hw_grade_col}")

    for idx, row in df.iterrows():
        student_name = str(row[name_col]) if pd.notna(row[name_col]) else f"Строка {idx + 2}"

        if student_name.lower() in ['nan', 'none', '', 'всего', 'итого', 'total']:
            continue

        completion_percent = None
        hw_grade = None

        if percent_col is not None:
            val = row.get(percent_col)
            if pd.notna(val):
                with suppress(ValueError, TypeError):
                    val_str = str(val).replace('%', '').replace('-', '').strip()
                    if val_str:
                        completion_percent = float(val_str)

        if hw_grade_col is not None:
            val = row.get(hw_grade_col)
            if pd.notna(val):
                with suppress(ValueError, TypeError):
                    hw_grade = float(val)

        if completion_percent is not None and completion_percent < 70:
            result["students"].append({
                "name": student_name,
                "completion_percent": round(completion_percent, 1),
                "hw_grade": hw_grade if hw_grade is not None else "—",
                "status": "критично" if completion_percent < 50 else "низкий"
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


@api_router.post("/reports/upload")
async def upload_and_process(
        file: UploadFile = File(...),
        report_type: str = Form(...),
        period: str = Form(default="month")
):
    if report_type not in REPORT_PROCESSORS:
        raise HTTPException(status_code=400, detail=f"Неизвестный тип отчета: {report_type}")

    content = await file.read()

    try:
        try:
            df = pd.read_excel(io.BytesIO(content), engine='openpyxl')
        except Exception:
            df = pd.read_excel(io.BytesIO(content), engine='xlrd')

        processor = REPORT_PROCESSORS[report_type]

        if report_type == "homework":
            result_data = processor(df, period=period)
        else:
            result_data = processor(df)

        report = ReportResult(
            report_type=report_type,
            filename=file.filename,
            result=result_data
        )

        doc = report.model_dump()
        await db.reports.insert_one(doc)

        return {
            "id": report.id,
            "report_type": report.report_type,
            "report_label": REPORT_LABELS.get(report_type, report_type),
            "filename": report.filename,
            "result": result_data,
            "timestamp": report.timestamp
        }

    except Exception as e:
        logger.error(f"Error processing file: {e}")
        raise HTTPException(status_code=400, detail=f"Ошибка обработки файла: {str(e)}")


@api_router.get("/reports/history")
async def get_report_history():
    reports = await db.reports.find({}, {"_id": 0}).sort("timestamp", -1).to_list(100)

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
            "summary": summary
        })

    return {"history": history}


@api_router.get("/reports/{report_id}")
async def get_report(report_id: str):
    report = await db.reports.find_one({"id": report_id}, {"_id": 0})

    if not report:
        raise HTTPException(status_code=404, detail="Отчет не найден")

    return report


@api_router.delete("/reports/{report_id}")
async def delete_report(report_id: str):
    result = await db.reports.delete_one({"id": report_id})

    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Отчет не найден")

    return {"success": True, "message": "Отчет удален"}


app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
