"""语音转写批次接口。"""

from __future__ import annotations

import asyncio
import logging
import mimetypes
import os
import shutil
import uuid
from datetime import date, datetime
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from models.transcription import TranscriptionBatch, TranscriptionItem
from models.user import User
from schemas.transcription import (
    TranscriptionBatchResponse,
    TranscriptionCancelResponse,
    TranscriptionItemResponse,
    TranscriptionStart,
)
from services.auth import get_current_user
from services.transcription_tasks import remove_file, token_hash, transcription_task_manager

router = APIRouter(prefix="/api/transcription-batches", tags=["语音转写"])
file_router = APIRouter(prefix="/api/transcription-files", tags=["语音转写文件"])
logger = logging.getLogger("transcription.api")

ALLOWED_EXTENSIONS = {
    "aac", "amr", "avi", "flac", "flv", "m4a", "mkv", "mov", "mp3", "mp4",
    "mpeg", "ogg", "opus", "wav", "webm", "wma", "wmv",
}


def get_batch(db: Session, batch_id: UUID, user_id: UUID, lock: bool = False) -> TranscriptionBatch:
    query = db.query(TranscriptionBatch).filter(
        TranscriptionBatch.id == batch_id,
        TranscriptionBatch.user_id == user_id,
    )
    if lock:
        query = query.with_for_update()
    batch = query.first()
    if not batch:
        raise HTTPException(status_code=404, detail="任务不存在")
    return batch


def serialize_batch(batch: TranscriptionBatch) -> TranscriptionBatchResponse:
    return TranscriptionBatchResponse(
        id=batch.id,
        diary_date=batch.diary_date,
        status=batch.status,
        diary_id=batch.diary_id,
        error_message=batch.error_message,
        expires_at=batch.expires_at,
        items=[
            TranscriptionItemResponse(
                id=item.id,
                sort_order=item.sort_order,
                filename=item.original_filename,
                file_size=item.file_size,
                status=item.status,
                transcript_preview=item.transcript_text if batch.status == "PARTIAL_FAILED" else None,
                error_code=item.error_code,
                error_message=item.error_message,
                retry_count=item.retry_count,
            )
            for item in sorted(batch.items, key=lambda value: value.sort_order)
            if item.status != "DELETED"
        ],
    )


@router.post("", response_model=TranscriptionBatchResponse, status_code=201)
def create_batch(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    batch = TranscriptionBatch(user_id=current_user.id, status="COLLECTING")
    db.add(batch)
    db.commit()
    db.refresh(batch)
    logger.info("创建语音转写批次 batch_id=%s user_id=%s status=%s", batch.id, current_user.id, batch.status)
    return serialize_batch(batch)


@router.get("/active", response_model=TranscriptionBatchResponse | None)
def active_batch(
    diary_date: date,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    batch = db.query(TranscriptionBatch).filter(
        TranscriptionBatch.user_id == current_user.id,
        TranscriptionBatch.diary_date == diary_date,
        TranscriptionBatch.status.in_(("QUEUED", "PROCESSING", "PARTIAL_FAILED", "FINALIZING")),
    ).order_by(TranscriptionBatch.created_at.desc()).first()
    logger.info(
        "查询活动语音转写批次 user_id=%s diary_date=%s found=%s batch_id=%s status=%s",
        current_user.id,
        diary_date,
        bool(batch),
        batch.id if batch else None,
        batch.status if batch else None,
    )
    return serialize_batch(batch) if batch else None


@router.post("/{batch_id}/items", response_model=TranscriptionItemResponse, status_code=201)
async def upload_item(
    batch_id: UUID,
    file: UploadFile = File(...),
    sort_order: int = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    batch = get_batch(db, batch_id, current_user.id)
    logger.info(
        "开始上传语音 item batch_id=%s user_id=%s filename=%s content_type=%s sort_order=%s",
        batch_id,
        current_user.id,
        file.filename,
        file.content_type,
        sort_order,
    )
    if batch.status != "COLLECTING":
        logger.warning("拒绝上传语音：批次状态不允许 batch_id=%s status=%s", batch.id, batch.status)
        raise HTTPException(status_code=409, detail="任务已经开始处理")
    if sort_order < 0:
        logger.warning("拒绝上传语音：排序无效 batch_id=%s sort_order=%s", batch.id, sort_order)
        raise HTTPException(status_code=400, detail="音频顺序无效")
    original_name = Path(file.filename or "audio").name[:255]
    extension = Path(original_name).suffix.lower().lstrip(".")
    if extension not in ALLOWED_EXTENSIONS:
        logger.warning("拒绝上传语音：扩展名不支持 batch_id=%s filename=%s extension=%s", batch.id, original_name, extension)
        raise HTTPException(status_code=415, detail="不支持该音频格式")
    upload_type = (file.content_type or "application/octet-stream").lower()
    if not (
        upload_type.startswith("audio/")
        or upload_type.startswith("video/")
        or upload_type in {"application/octet-stream", "application/ogg"}
    ):
        logger.warning("拒绝上传语音：Content-Type 不支持 batch_id=%s filename=%s content_type=%s", batch.id, original_name, upload_type)
        raise HTTPException(status_code=415, detail="不支持该音频格式")
    storage_dir = Path(settings.TRANSCRIPTION_STORAGE_PATH)
    await asyncio.to_thread(storage_dir.mkdir, parents=True, exist_ok=True)
    storage_reserve = 10 * 1024 * 1024
    if shutil.disk_usage(storage_dir).free <= storage_reserve:
        logger.warning("拒绝上传语音：存储空间不足 batch_id=%s storage_dir=%s", batch.id, storage_dir)
        raise HTTPException(status_code=507, detail="服务器存储空间不足，请稍后再试")
    path = storage_dir / f"{uuid.uuid4().hex}.{extension}"
    size = 0
    try:
        handle = await asyncio.to_thread(path.open, "wb")
        try:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > settings.TRANSCRIPTION_MAX_FILE_SIZE:
                    logger.warning("拒绝上传语音：文件过大 batch_id=%s filename=%s size=%s", batch.id, original_name, size)
                    raise HTTPException(status_code=413, detail="单个音频不能超过 300 MB")
                if shutil.disk_usage(storage_dir).free < len(chunk) + storage_reserve:
                    logger.warning("拒绝上传语音：写入时存储空间不足 batch_id=%s filename=%s size=%s", batch.id, original_name, size)
                    raise HTTPException(status_code=507, detail="服务器存储空间不足，请稍后再试")
                await asyncio.to_thread(handle.write, chunk)
        finally:
            await asyncio.to_thread(handle.close)
        if size == 0:
            logger.warning("拒绝上传语音：空文件 batch_id=%s filename=%s", batch.id, original_name)
            raise HTTPException(status_code=400, detail="音频文件不能为空")
        item = TranscriptionItem(
            batch_id=batch.id,
            sort_order=sort_order,
            original_filename=original_name,
            content_type=(mimetypes.guess_type(original_name)[0] or "application/octet-stream")[:100],
            file_size=size,
            storage_path=str(path),
            status="UPLOADED",
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        logger.info(
            "语音上传完成 batch_id=%s item_id=%s filename=%s size=%s content_type=%s sort_order=%s",
            batch.id,
            item.id,
            item.original_filename,
            item.file_size,
            item.content_type,
            item.sort_order,
        )
        return TranscriptionItemResponse(
            id=item.id, sort_order=item.sort_order, filename=item.original_filename,
            file_size=item.file_size, status=item.status, retry_count=item.retry_count,
        )
    except HTTPException:
        remove_file(str(path))
        raise
    except IntegrityError:
        db.rollback()
        remove_file(str(path))
        logger.warning("语音上传失败：顺序冲突 batch_id=%s filename=%s sort_order=%s", batch.id, original_name, sort_order)
        raise HTTPException(status_code=409, detail="音频顺序冲突，请重新选择")
    except Exception:
        remove_file(str(path))
        logger.exception("语音上传异常 batch_id=%s filename=%s size=%s", batch.id, original_name, size)
        raise HTTPException(status_code=500, detail="音频上传失败")


@router.post("/{batch_id}/start", response_model=TranscriptionBatchResponse, status_code=202)
def start_batch(
    batch_id: UUID,
    payload: TranscriptionStart,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    batch = get_batch(db, batch_id, current_user.id, lock=True)
    logger.info(
        "启动语音转写批次 batch_id=%s user_id=%s diary_date=%s base_text_length=%s",
        batch.id,
        current_user.id,
        payload.diary_date,
        len(payload.base_text or ""),
    )
    if batch.status != "COLLECTING":
        logger.warning("拒绝启动语音转写：批次状态不允许 batch_id=%s status=%s", batch.id, batch.status)
        raise HTTPException(status_code=409, detail="当前任务已经开始处理")
    items = [item for item in batch.items if item.status == "UPLOADED"]
    if not items or len(items) != len(batch.items):
        logger.warning("拒绝启动语音转写：音频未全部上传 batch_id=%s uploaded=%s total=%s", batch.id, len(items), len(batch.items))
        raise HTTPException(status_code=409, detail="请等待全部音频上传完成")
    batch.diary_date = payload.diary_date
    batch.base_text = payload.base_text
    batch.status = "QUEUED"
    batch.started_at = datetime.utcnow()
    for item in items:
        item.status = "QUEUED"
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        logger.warning("拒绝启动语音转写：日期存在活动批次 batch_id=%s user_id=%s diary_date=%s", batch.id, current_user.id, payload.diary_date)
        raise HTTPException(status_code=409, detail="该日期正在生成日记")
    db.refresh(batch)
    logger.info("语音转写批次已入队 batch_id=%s item_count=%s diary_date=%s", batch.id, len(items), batch.diary_date)
    return serialize_batch(batch)


@router.get("/{batch_id}", response_model=TranscriptionBatchResponse)
def query_batch(batch_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    batch = get_batch(db, batch_id, current_user.id)
    logger.info("查询语音转写批次 batch_id=%s user_id=%s status=%s diary_id=%s", batch.id, current_user.id, batch.status, batch.diary_id)
    return serialize_batch(batch)


@router.delete("/{batch_id}/items/{item_id}", status_code=204)
def delete_item(
    batch_id: UUID,
    item_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    batch = get_batch(db, batch_id, current_user.id, lock=True)
    item = db.query(TranscriptionItem).filter_by(id=item_id, batch_id=batch.id).first()
    if not item:
        raise HTTPException(status_code=404, detail="音频不存在")
    if item.status not in {"UPLOADED", "FAILED"}:
        logger.warning("拒绝删除语音：状态不允许 batch_id=%s item_id=%s status=%s", batch.id, item.id, item.status)
        raise HTTPException(status_code=409, detail="当前状态不能删除")
    path = item.storage_path
    previous_status = item.status
    item.status = "DELETED"
    item.transcript_text = None
    db.commit()
    if remove_file(path):
        item.storage_path = None
        db.commit()
    if batch.status == "PARTIAL_FAILED":
        transcription_task_manager.evaluate_batch(batch.id)
    logger.info("删除语音完成 batch_id=%s item_id=%s previous_status=%s file_removed=%s", batch.id, item.id, previous_status, path is not None)
    return Response(status_code=204)


def retry_items(batch: TranscriptionBatch, items: list[TranscriptionItem], db: Session) -> TranscriptionBatchResponse:
    if batch.status != "PARTIAL_FAILED" or (batch.expires_at and batch.expires_at <= datetime.utcnow()):
        logger.warning("拒绝重试语音：批次不可重试 batch_id=%s status=%s expires_at=%s", batch.id, batch.status, batch.expires_at)
        raise HTTPException(status_code=410, detail="语音已过期，请重新上传")
    retryable = [item for item in items if item.status == "FAILED" and item.storage_path and os.path.exists(item.storage_path)]
    if not retryable:
        logger.warning("拒绝重试语音：无可重试项 batch_id=%s requested=%s", batch.id, len(items))
        raise HTTPException(status_code=409, detail="没有可重试的音频")
    for item in retryable:
        item.status = "QUEUED"
        item.provider_task_id = None
        item.provider_request_id = None
        item.error_code = None
        item.error_message = None
        item.retry_count += 1
    batch.status = "PROCESSING"
    batch.expires_at = None
    db.commit()
    db.refresh(batch)
    logger.info("语音重试已入队 batch_id=%s retryable_count=%s", batch.id, len(retryable))
    return serialize_batch(batch)


@router.post("/{batch_id}/items/{item_id}/retry", response_model=TranscriptionBatchResponse, status_code=202)
def retry_item(batch_id: UUID, item_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    batch = get_batch(db, batch_id, current_user.id, lock=True)
    item = db.query(TranscriptionItem).filter_by(id=item_id, batch_id=batch.id).first()
    if not item:
        raise HTTPException(status_code=404, detail="音频不存在")
    return retry_items(batch, [item], db)


@router.post("/{batch_id}/retry-failed", response_model=TranscriptionBatchResponse, status_code=202)
def retry_failed(batch_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    batch = get_batch(db, batch_id, current_user.id, lock=True)
    return retry_items(batch, batch.items, db)


@router.post("/{batch_id}/cancel", response_model=TranscriptionCancelResponse)
def cancel_batch(batch_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    batch = get_batch(db, batch_id, current_user.id, lock=True)
    if batch.status == "COMPLETED" or batch.diary_id:
        logger.warning("拒绝取消语音转写：日记已创建 batch_id=%s diary_id=%s", batch.id, batch.diary_id)
        raise HTTPException(status_code=409, detail="日记已经创建，不能取消")
    if batch.status in {"CANCELLED", "EXPIRED"}:
        logger.warning("拒绝取消语音转写：批次已终态 batch_id=%s status=%s", batch.id, batch.status)
        raise HTTPException(status_code=409, detail="任务已经结束")
    response = TranscriptionCancelResponse(
        diary_date=batch.diary_date,
        base_text=batch.base_text or "",
        status="CANCELLED",
    )
    paths = [item.storage_path for item in batch.items if item.storage_path]
    batch.status = "CANCELLED"
    batch.completed_at = datetime.utcnow()
    batch.base_text = None
    for item in batch.items:
        item.transcript_text = None
        item.access_token_hash = None
        item.access_expires_at = None
    db.commit()
    for item, path in zip([item for item in batch.items if item.storage_path], paths):
        if remove_file(path):
            item.storage_path = None
    db.commit()
    logger.info("取消语音转写完成 batch_id=%s removed_file_count=%s", batch.id, len(paths))
    return response


@file_router.api_route("/{token}", methods=["GET", "HEAD"])
def download_file(token: str, db: Session = Depends(get_db)):
    item = db.query(TranscriptionItem).filter(
        TranscriptionItem.access_token_hash == token_hash(token),
        TranscriptionItem.access_expires_at > datetime.utcnow(),
        TranscriptionItem.status.in_(("SUBMITTING", "SUBMITTED", "RUNNING")),
    ).first()
    if not item or not item.storage_path or not os.path.isfile(item.storage_path):
        logger.warning("语音临时文件下载失败：token 无效、过期或文件不存在")
        raise HTTPException(status_code=404, detail="文件不存在")
    logger.info("语音临时文件下载命中 item_id=%s batch_id=%s size=%s content_type=%s", item.id, item.batch_id, item.file_size, item.content_type)
    filename = Path(item.storage_path).name
    return Response(
        status_code=200,
        headers={
            "X-Accel-Redirect": f"/protected-transcriptions/{filename}",
            "Content-Type": item.content_type or "application/octet-stream",
            "Content-Length": str(item.file_size),
        },
    )
