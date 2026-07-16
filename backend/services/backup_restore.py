"""系统备份与恢复服务"""

import hashlib
import json
import logging
import tempfile
import uuid
from datetime import date, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import pyzipper
from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from config import settings
from models.backup import BackupImportReport, BackupRestoreRecord
from models.diary import Diary, DiaryAnalysis, DiaryEvent, DiaryOrganized, DiaryStatus, OrganizeTask
from models.tag import EventTag, Tag, diary_tags
from models.user import User

BACKUP_SCHEMA_VERSION = 1
BACKUP_TABLES = [
    "users",
    "diaries",
    "organize_tasks",
    "diary_organized",
    "diary_events",
    "diary_analysis",
    "tags",
    "diary_tags",
    "event_tags",
]

MODEL_BY_TABLE = {
    "users": User,
    "diaries": Diary,
    "organize_tasks": OrganizeTask,
    "diary_organized": DiaryOrganized,
    "diary_events": DiaryEvent,
    "diary_analysis": DiaryAnalysis,
    "tags": Tag,
    "event_tags": EventTag,
}

IMPORT_ORDER = [
    "users",
    "diaries",
    "organize_tasks",
    "diary_organized",
    "diary_events",
    "diary_analysis",
    "tags",
    "diary_tags",
    "event_tags",
]

BACKUP_DIR = Path(__file__).resolve().parent.parent / "backup_packages"
BACKUP_DIR.mkdir(exist_ok=True)
logger = logging.getLogger("app.backup_restore")


def require_backup_key() -> bytes:
    """获取备份主密钥作为 ZIP 加密密码。"""
    if not settings.BACKUP_MASTER_KEY:
        raise ValueError("未配置 BACKUP_MASTER_KEY")
    return settings.BACKUP_MASTER_KEY.encode("utf-8")


def value_to_json(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    return value


def row_to_dict(row: Any) -> Dict[str, Any]:
    return {column.name: value_to_json(getattr(row, column.name)) for column in row.__table__.columns}


def association_row_to_dict(row: Any) -> Dict[str, Any]:
    return {key: value_to_json(value) for key, value in dict(row._mapping).items()}


def parse_uuid(value: Any) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


def parse_datetime_value(value: Any) -> Any:
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def parse_date_value(value: Any) -> Any:
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def build_scope_summary(scope_type: str, user_ids: Optional[List[str]], start_date: Optional[str], end_date: Optional[str]) -> str:
    parts = [f"范围={scope_type}"]
    if user_ids:
        parts.append(f"用户数={len(user_ids)}")
    if start_date or end_date:
        parts.append(f"日记日期={start_date or '-'}~{end_date or '-'}")
    return "；".join(parts)


def collect_diary_ids(
    db: Session,
    scope_type: str,
    user_ids: Optional[List[str]],
    start_date: Optional[str],
    end_date: Optional[str],
) -> Optional[List[uuid.UUID]]:
    if scope_type == "all":
        return None

    query = db.query(Diary.id)
    if user_ids:
        query = query.filter(Diary.user_id.in_([parse_uuid(user_id) for user_id in user_ids]))
    if start_date:
        query = query.filter(Diary.diary_date >= parse_date_value(start_date))
    if end_date:
        query = query.filter(Diary.diary_date <= parse_date_value(end_date))
    return [row[0] for row in query.all()]


def table_rows(
    db: Session,
    table_name: str,
    diary_ids: Optional[List[uuid.UUID]],
    user_ids: Optional[List[str]],
) -> Iterable[Dict[str, Any]]:
    if diary_ids is None:
        if table_name == "diary_tags":
            return [association_row_to_dict(row) for row in db.execute(select(diary_tags)).all()]
        if table_name == "event_tags":
            return [row_to_dict(row) for row in db.query(EventTag).all()]
        return [row_to_dict(row) for row in db.query(MODEL_BY_TABLE[table_name]).all()]

    if table_name == "diaries":
        rows = db.query(Diary).filter(Diary.id.in_(diary_ids)).all()
    elif table_name == "users":
        owner_ids = [row[0] for row in db.query(Diary.user_id).filter(Diary.id.in_(diary_ids)).distinct().all()]
        rows = db.query(User).filter(User.id.in_(owner_ids)).all() if owner_ids else []
    elif table_name == "organize_tasks":
        rows = db.query(OrganizeTask).filter(OrganizeTask.diary_id.in_(diary_ids)).all()
    elif table_name == "diary_organized":
        rows = db.query(DiaryOrganized).filter(DiaryOrganized.diary_id.in_(diary_ids)).all()
    elif table_name == "diary_events":
        organized_ids = db.query(DiaryOrganized.id).filter(DiaryOrganized.diary_id.in_(diary_ids))
        rows = db.query(DiaryEvent).filter(DiaryEvent.diary_organized_id.in_(organized_ids)).all()
    elif table_name == "diary_analysis":
        organized_ids = db.query(DiaryOrganized.id).filter(DiaryOrganized.diary_id.in_(diary_ids))
        rows = db.query(DiaryAnalysis).filter(DiaryAnalysis.diary_organized_id.in_(organized_ids)).all()
    elif table_name == "tags":
        owner_ids = [row[0] for row in db.query(Diary.user_id).filter(Diary.id.in_(diary_ids)).distinct().all()]
        rows = db.query(Tag).filter(Tag.user_id.in_(owner_ids)).all() if owner_ids else []
    elif table_name == "diary_tags":
        rows = db.execute(select(diary_tags).where(diary_tags.c.diary_id.in_(diary_ids))).all()
        return [association_row_to_dict(row) for row in rows]
    elif table_name == "event_tags":
        organized_ids = db.query(DiaryOrganized.id).filter(DiaryOrganized.diary_id.in_(diary_ids))
        event_ids = db.query(DiaryEvent.id).filter(DiaryEvent.diary_organized_id.in_(organized_ids))
        rows = db.query(EventTag).filter(EventTag.diary_event_id.in_(event_ids)).all()
    else:
        rows = []
    return [row_to_dict(row) for row in rows]


def create_export_package(
    db: Session,
    record: BackupRestoreRecord,
    scope_type: str,
    user_ids: Optional[List[str]],
    start_date: Optional[str],
    end_date: Optional[str],
) -> None:
    logger.info("准备生成备份包: record_id=%s scope_type=%s", record.id, scope_type)
    record.status = "running"
    record.started_at = datetime.utcnow()
    record.current_phase = "准备数据"
    db.commit()

    diary_ids = collect_diary_ids(db, scope_type, user_ids, start_date, end_date)
    package_id = f"BKP-{record.id}"
    file_name = f"diary-platform-backup-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{record.id}.zip"
    output_path = BACKUP_DIR / file_name

    table_meta: Dict[str, Dict[str, Any]] = {}
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        zip_path = temp_path / "payload.zip"
        for table_name in BACKUP_TABLES:
            db.refresh(record)
            if record.status == "cancelled":
                record.current_phase = "已取消"
                record.finished_at = datetime.utcnow()
                db.commit()
                return
            record.current_phase = "导出数据"
            record.current_table = table_name
            db.commit()

            rows = list(table_rows(db, table_name, diary_ids, user_ids))
            logger.info("导出表数据: record_id=%s table=%s count=%d", record.id, table_name, len(rows))
            data_path = temp_path / f"{table_name}.jsonl"
            with data_path.open("w", encoding="utf-8") as file:
                for row in rows:
                    file.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
            table_meta[table_name] = {
                "count": len(rows),
                "sha256": hashlib.sha256(data_path.read_bytes()).hexdigest(),
            }

        manifest = {
            "system": "diary-platform",
            "backup_schema_version": BACKUP_SCHEMA_VERSION,
            "exported_at": datetime.utcnow().isoformat(),
            "record_id": str(record.id),
            "package_id": package_id,
            "scope": {
                "type": scope_type,
                "user_ids": user_ids or [],
                "start_date": start_date,
                "end_date": end_date,
            },
            "tables": table_meta,
        }
        manifest_path = temp_path / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

        record.current_phase = "压缩加密"
        record.current_table = None
        db.commit()
        with pyzipper.AESZipFile(
            zip_path,
            "w",
            compression=pyzipper.ZIP_DEFLATED,
            encryption=pyzipper.WZ_AES,
        ) as zip_file:
            zip_file.setpassword(require_backup_key())
            zip_file.write(manifest_path, "manifest.json")
            for table_name in BACKUP_TABLES:
                zip_file.write(temp_path / f"{table_name}.jsonl", f"{table_name}.jsonl")

        output_path.write_bytes(zip_path.read_bytes())

    logger.info("备份包生成成功: record_id=%s file=%s", record.id, output_path)
    record.status = "success"
    record.current_phase = "完成"
    record.backup_package_id = package_id
    record.file_name = file_name
    record.file_path = str(output_path)
    record.file_expires_at = datetime.utcnow() + timedelta(days=7)
    record.finished_at = datetime.utcnow()
    record.result_summary = json.dumps(
        {"tables": {name: meta["count"] for name, meta in table_meta.items()}},
        ensure_ascii=False,
    )
    db.commit()


def read_backup_payload(zip_bytes: bytes) -> Dict[str, Any]:
    with tempfile.TemporaryDirectory() as temp_dir:
        zip_path = Path(temp_dir) / "payload.zip"
        zip_path.write_bytes(zip_bytes)
        with pyzipper.AESZipFile(zip_path, "r") as zip_file:
            zip_file.setpassword(require_backup_key())
            manifest = json.loads(zip_file.read("manifest.json").decode("utf-8"))
            data: Dict[str, Any] = {"manifest": manifest, "tables": {}}
            for table_name in BACKUP_TABLES:
                content = zip_file.read(f"{table_name}.jsonl")
                expected = manifest.get("tables", {}).get(table_name, {}).get("sha256")
                actual = hashlib.sha256(content).hexdigest()
                if expected and expected != actual:
                    raise ValueError(f"{table_name}.jsonl 摘要不匹配")
                records = []
                for line in content.decode("utf-8").splitlines():
                    if line.strip():
                        records.append(json.loads(line))
                data["tables"][table_name] = records
            return data


def primary_key_exists(db: Session, table_name: str, row: Dict[str, Any]) -> bool:
    if table_name == "diary_tags":
        query = select(diary_tags).where(
            diary_tags.c.diary_id == parse_uuid(row["diary_id"]),
            diary_tags.c.tag_id == parse_uuid(row["tag_id"]),
        )
        return db.execute(query).first() is not None
    if table_name == "event_tags":
        return db.get(EventTag, {"diary_event_id": parse_uuid(row["diary_event_id"]), "tag_id": parse_uuid(row["tag_id"])}) is not None
    return db.get(MODEL_BY_TABLE[table_name], parse_uuid(row["id"])) is not None


def check_parent_exists(db: Session, table_name: str, row: Dict[str, Any]) -> Optional[str]:
    checks = {
        "diaries": [("users", User, "user_id")],
        "organize_tasks": [("diaries", Diary, "diary_id"), ("users", User, "user_id")],
        "diary_organized": [("organize_tasks", OrganizeTask, "task_id"), ("diaries", Diary, "diary_id")],
        "diary_events": [("diary_organized", DiaryOrganized, "diary_organized_id")],
        "diary_analysis": [("organize_tasks", OrganizeTask, "task_id"), ("diary_organized", DiaryOrganized, "diary_organized_id")],
        "tags": [("users", User, "user_id")],
        "diary_tags": [("diaries", Diary, "diary_id"), ("tags", Tag, "tag_id")],
        "event_tags": [("diary_events", DiaryEvent, "diary_event_id"), ("tags", Tag, "tag_id")],
    }
    for label, model, field in checks.get(table_name, []):
        if db.get(model, parse_uuid(row[field])) is None:
            return f"关联父数据不存在：{label}.{row[field]}"
    return None


def collect_payload_ids(payload: Dict[str, Any]) -> Dict[str, set]:
    ids: Dict[str, set] = {}
    for table_name, rows in payload["tables"].items():
        if table_name == "diary_tags":
            ids[table_name] = {(item["diary_id"], item["tag_id"]) for item in rows}
        elif table_name == "event_tags":
            ids[table_name] = {(item["diary_event_id"], item["tag_id"]) for item in rows}
        else:
            ids[table_name] = {item["id"] for item in rows if item.get("id")}
    return ids


def check_parent_exists_for_precheck(
    db: Session,
    table_name: str,
    row: Dict[str, Any],
    payload_ids: Dict[str, set],
) -> Optional[str]:
    checks = {
        "diaries": [("users", User, "user_id")],
        "organize_tasks": [("diaries", Diary, "diary_id"), ("users", User, "user_id")],
        "diary_organized": [("organize_tasks", OrganizeTask, "task_id"), ("diaries", Diary, "diary_id")],
        "diary_events": [("diary_organized", DiaryOrganized, "diary_organized_id")],
        "diary_analysis": [("organize_tasks", OrganizeTask, "task_id"), ("diary_organized", DiaryOrganized, "diary_organized_id")],
        "tags": [("users", User, "user_id")],
        "diary_tags": [("diaries", Diary, "diary_id"), ("tags", Tag, "tag_id")],
        "event_tags": [("diary_events", DiaryEvent, "diary_event_id"), ("tags", Tag, "tag_id")],
    }
    for label, model, field in checks.get(table_name, []):
        parent_id = str(row[field])
        if db.get(model, parse_uuid(parent_id)) is not None:
            continue
        if parent_id in payload_ids.get(label, set()):
            continue
        return f"关联父数据不存在：{label}.{parent_id}"
    return None


def precheck_backup(db: Session, encrypted_bytes: bytes) -> Dict[str, Any]:
    payload = read_backup_payload(encrypted_bytes)
    manifest = payload["manifest"]
    if manifest.get("backup_schema_version") != BACKUP_SCHEMA_VERSION:
        raise ValueError("备份 schema 版本不兼容")

    payload_ids = collect_payload_ids(payload)
    table_results = []
    for table_name in BACKUP_TABLES:
        created = skipped = failed = 0
        reasons: List[str] = []
        seen_ids = set()
        for row in payload["tables"][table_name]:
            row_key = f"{row.get('id') or row}"
            if row_key in seen_ids:
                failed += 1
                reasons.append(f"{row_key} 数据包内重复")
                continue
            seen_ids.add(row_key)
            try:
                if primary_key_exists(db, table_name, row):
                    skipped += 1
                    continue
                parent_error = check_parent_exists_for_precheck(db, table_name, row, payload_ids)
                if parent_error:
                    failed += 1
                    reasons.append(f"{row_key} {parent_error}")
                else:
                    created += 1
            except Exception as exc:
                failed += 1
                reasons.append(f"{row_key} {exc}")
        table_results.append({
            "table": table_name,
            "created": created,
            "skipped": skipped,
            "failed": failed,
            "summary": "；".join(reasons[:5]),
        })
    return {"manifest": manifest, "tables": table_results}


def model_values(table_name: str, row: Dict[str, Any]) -> Dict[str, Any]:
    uuid_fields = {
        "id", "user_id", "diary_id", "task_id", "diary_organized_id", "diary_event_id", "tag_id"
    }
    date_fields = {"diary_date"}
    datetime_fields = {
        "created_at", "updated_at", "organized_at", "analyzed_at"
    }
    values: Dict[str, Any] = {}
    for key, value in row.items():
        if key in uuid_fields and value is not None:
            values[key] = parse_uuid(value)
        elif key in date_fields:
            values[key] = parse_date_value(value)
        elif key in datetime_fields:
            values[key] = parse_datetime_value(value)
        elif table_name == "diaries" and key == "status" and value is not None:
            status_value = "saved" if value in {"draft", "published"} else value
            values[key] = DiaryStatus(status_value)
        else:
            values[key] = value
    return values


def insert_row(db: Session, table_name: str, row: Dict[str, Any]) -> None:
    values = model_values(table_name, row)
    if table_name == "diary_tags":
        db.execute(insert(diary_tags).values(**values))
    else:
        model = MODEL_BY_TABLE[table_name]
        db.add(model(**values))


def import_backup(db: Session, record: BackupRestoreRecord) -> None:
    if not record.file_path:
        raise ValueError("导入任务缺少备份包文件")
    record.status = "running"
    record.started_at = datetime.utcnow()
    record.current_phase = "解密校验"
    db.commit()

    payload = read_backup_payload(Path(record.file_path).read_bytes())
    report_expires_at = datetime.utcnow() + timedelta(days=7)
    totals = {}

    for table_name in IMPORT_ORDER:
        record.current_phase = "导入数据"
        record.current_table = table_name
        db.commit()
        created = skipped = failed = 0
        failures: List[str] = []
        skips: List[str] = []
        for row in payload["tables"][table_name]:
            row_key = row.get("id") or f"{row}"
            try:
                if primary_key_exists(db, table_name, row):
                    skipped += 1
                    skips.append(f"{row_key} 已存在，跳过")
                    continue
                parent_error = check_parent_exists(db, table_name, row)
                if parent_error:
                    failed += 1
                    failures.append(f"{row_key} {parent_error}")
                    continue
                insert_row(db, table_name, row)
                db.flush()
                db.commit()
                created += 1
            except Exception as exc:
                db.rollback()
                failed += 1
                failures.append(f"{row_key} {exc}")
        db.add(BackupImportReport(
            record_id=record.id,
            table_name=table_name,
            created_count=created,
            skipped_count=skipped,
            failed_count=failed,
            failure_summary="；".join(failures[:20]),
            skip_summary="；".join(skips[:20]),
            expires_at=report_expires_at,
        ))
        totals[table_name] = {"created": created, "skipped": skipped, "failed": failed}
        db.commit()

    failed_total = sum(item["failed"] for item in totals.values())
    record.status = "partial_failed" if failed_total else "success"
    record.current_phase = "完成"
    record.current_table = None
    record.finished_at = datetime.utcnow()
    record.result_summary = json.dumps(totals, ensure_ascii=False)
    db.commit()


def save_uploaded_package(content: bytes, record_id: uuid.UUID) -> str:
    file_path = BACKUP_DIR / f"import-{record_id}.zip"
    file_path.write_bytes(content)
    return str(file_path)
