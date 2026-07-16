"""管理端系统备份与恢复接口"""

import json
import logging
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import SessionLocal, get_db
from models.backup import BackupImportReport, BackupRestoreRecord
from models.user import User
from schemas.common import serialize_utc_datetime
from services.auth import get_current_user
from services.backup_restore import (
    build_scope_summary,
    create_export_package,
    import_backup,
    precheck_backup,
    save_uploaded_package,
)

router = APIRouter(prefix="/api/admin/backup-restore", tags=["管理端-备份恢复"])
logger = logging.getLogger("app.admin_backup")


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """当前系统以 admin 账号作为超级管理员。"""
    if current_user.username != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权限访问管理端")
    return current_user


class ExportCreateRequest(BaseModel):
    """创建导出任务请求"""

    scope_type: str = "all"
    user_ids: Optional[List[str]] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None


class ImportCreateRequest(BaseModel):
    """创建正式导入任务请求"""

    record_id: UUID


def record_to_dict(record: BackupRestoreRecord) -> dict:
    return {
        "id": str(record.id),
        "operation_type": record.operation_type,
        "status": record.status,
        "scope_type": record.scope_type,
        "scope_summary": record.scope_summary,
        "current_phase": record.current_phase,
        "current_table": record.current_table,
        "backup_package_id": record.backup_package_id,
        "file_name": record.file_name,
        "file_expires_at": serialize_utc_datetime(record.file_expires_at),
        "started_at": serialize_utc_datetime(record.started_at),
        "finished_at": serialize_utc_datetime(record.finished_at),
        "result_summary": record.result_summary,
        "error_summary": record.error_summary,
        "created_at": serialize_utc_datetime(record.created_at),
        "updated_at": serialize_utc_datetime(record.updated_at),
    }


def run_export_task(record_id: UUID, request: ExportCreateRequest) -> None:
    db = SessionLocal()
    try:
        logger.info("开始导出备份任务: record_id=%s scope_type=%s", record_id, request.scope_type)
        record = db.get(BackupRestoreRecord, record_id)
        if record is None:
            logger.warning("导出备份任务不存在: record_id=%s", record_id)
            return
        create_export_package(
            db,
            record,
            request.scope_type,
            request.user_ids,
            request.start_date,
            request.end_date,
        )
        logger.info("导出备份任务完成: record_id=%s", record_id)
    except Exception as exc:
        logger.exception("导出备份任务失败: record_id=%s", record_id)
        record = db.get(BackupRestoreRecord, record_id)
        if record:
            record.status = "failed"
            record.current_phase = "失败"
            record.error_summary = f"{type(exc).__name__}: {exc}"
            record.finished_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()


def run_import_task(record_id: UUID) -> None:
    db = SessionLocal()
    try:
        logger.info("开始导入备份任务: record_id=%s", record_id)
        record = db.get(BackupRestoreRecord, record_id)
        if record is None:
            logger.warning("导入备份任务不存在: record_id=%s", record_id)
            return
        import_backup(db, record)
        logger.info("导入备份任务完成: record_id=%s", record_id)
    except Exception as exc:
        logger.exception("导入备份任务失败: record_id=%s", record_id)
        record = db.get(BackupRestoreRecord, record_id)
        if record:
            record.status = "failed"
            record.current_phase = "失败"
            record.error_summary = f"{type(exc).__name__}: {exc}"
            record.finished_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()


@router.post("/exports")
def create_export(
    request: ExportCreateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    if request.scope_type not in {"all", "users", "diary_date", "users_and_diary_date"}:
        raise HTTPException(status_code=400, detail="导出范围类型不合法")
    record = BackupRestoreRecord(
        operation_type="export",
        status="pending",
        scope_type=request.scope_type,
        scope_summary=build_scope_summary(request.scope_type, request.user_ids, request.start_date, request.end_date),
        operator_user_id=current_user.id,
        current_phase="等待中",
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    background_tasks.add_task(run_export_task, record.id, request)
    return record_to_dict(record)


@router.post("/exports/{record_id}/cancel")
def cancel_export(
    record_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    record = db.get(BackupRestoreRecord, record_id)
    if record is None or record.operation_type != "export":
        raise HTTPException(status_code=404, detail="导出任务不存在")
    if record.status != "running":
        raise HTTPException(status_code=400, detail="只有运行中的导出任务可以取消")
    record.status = "cancelled"
    record.current_phase = "已取消"
    record.finished_at = datetime.utcnow()
    db.commit()
    return record_to_dict(record)


@router.get("/exports/{record_id}/download")
def download_export(
    record_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    record = db.get(BackupRestoreRecord, record_id)
    if record is None or record.operation_type != "export":
        raise HTTPException(status_code=404, detail="导出任务不存在")
    if record.status != "success" or not record.file_path or not record.file_name:
        raise HTTPException(status_code=400, detail="导出包不可下载")
    if record.file_expires_at and record.file_expires_at < datetime.utcnow():
        record.status = "expired"
        db.commit()
        raise HTTPException(status_code=400, detail="导出包已过期")
    audit = BackupRestoreRecord(
        operation_type="download",
        status="success",
        scope_type=record.scope_type,
        scope_summary=record.scope_summary,
        operator_user_id=current_user.id,
        backup_package_id=record.backup_package_id,
        file_name=record.file_name,
        finished_at=datetime.utcnow(),
        result_summary=f"下载导出包 {record.file_name}",
    )
    db.add(audit)
    db.commit()
    return FileResponse(record.file_path, filename=record.file_name, media_type="application/zip")


@router.post("/imports/precheck")
async def precheck_import(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    content = await file.read()
    record = BackupRestoreRecord(
        operation_type="precheck",
        status="running",
        scope_type="backup_package",
        scope_summary=file.filename,
        operator_user_id=current_user.id,
        file_name=file.filename,
        current_phase="预检",
        started_at=datetime.utcnow(),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    try:
        record.file_path = save_uploaded_package(content, record.id)
        result = precheck_backup(db, content)
        record.status = "success"
        record.current_phase = "预检完成"
        record.finished_at = datetime.utcnow()
        record.result_summary = json.dumps(result["tables"], ensure_ascii=False)
        db.commit()
        return {"record": record_to_dict(record), "precheck": result}
    except Exception as exc:
        logger.exception("导入预检失败: record_id=%s file_name=%s", record.id, file.filename)
        record.status = "failed"
        record.current_phase = "预检失败"
        record.finished_at = datetime.utcnow()
        record.error_summary = f"{type(exc).__name__}: {exc}"
        db.commit()
        raise HTTPException(status_code=400, detail=record.error_summary)


@router.post("/imports")
def create_import(
    request: ImportCreateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    precheck_record = db.get(BackupRestoreRecord, request.record_id)
    if precheck_record is None or precheck_record.operation_type != "precheck":
        raise HTTPException(status_code=404, detail="预检记录不存在")
    if precheck_record.status != "success" or not precheck_record.file_path:
        raise HTTPException(status_code=400, detail="预检未通过，不能导入")
    record = BackupRestoreRecord(
        operation_type="import",
        status="pending",
        scope_type="backup_package",
        scope_summary=precheck_record.scope_summary,
        operator_user_id=current_user.id,
        file_name=precheck_record.file_name,
        file_path=precheck_record.file_path,
        current_phase="等待中",
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    background_tasks.add_task(run_import_task, record.id)
    return record_to_dict(record)


@router.get("/imports/{record_id}/report")
def get_import_report(
    record_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    reports = db.query(BackupImportReport).filter(BackupImportReport.record_id == record_id).all()
    return [
        {
            "table_name": item.table_name,
            "created_count": item.created_count,
            "skipped_count": item.skipped_count,
            "failed_count": item.failed_count,
            "failure_summary": item.failure_summary,
            "skip_summary": item.skip_summary,
        }
        for item in reports
    ]


@router.get("/records")
def list_records(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    records = (
        db.query(BackupRestoreRecord)
        .order_by(BackupRestoreRecord.created_at.desc())
        .limit(100)
        .all()
    )
    return [record_to_dict(record) for record in records]


@router.get("/records/{record_id}")
def get_record(
    record_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    record = db.get(BackupRestoreRecord, record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    return record_to_dict(record)
