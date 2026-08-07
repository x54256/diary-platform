"""管理端搜索索引重建接口。"""

import json
from datetime import date, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models.search_rebuild import SearchIndexRebuildJob
from models.user import User
from routers.admin_backup import require_admin
from schemas.common import serialize_utc_datetime
from services.search_rebuild_jobs import count_eligible_events

router = APIRouter(prefix="/api/admin/search-index", tags=["管理端-搜索索引"])


class SearchIndexRebuildCreateRequest(BaseModel):
    start_date: date
    end_date: date


def job_to_dict(job: SearchIndexRebuildJob) -> dict:
    try:
        failures = json.loads(job.failure_details or "[]")
    except json.JSONDecodeError:
        failures = []
    return {
        "id": str(job.id),
        "start_date": job.start_date.isoformat(),
        "end_date": job.end_date.isoformat(),
        "status": job.status,
        "total_events": job.total_events,
        "processed_events": job.processed_events,
        "succeeded_events": job.succeeded_events,
        "failed_events": job.failed_events,
        "failure_details": failures,
        "created_at": serialize_utc_datetime(job.created_at),
        "started_at": serialize_utc_datetime(job.started_at),
        "finished_at": serialize_utc_datetime(job.finished_at),
    }


@router.post("/rebuild", status_code=status.HTTP_201_CREATED)
def create_rebuild_job(
    request: SearchIndexRebuildCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    if request.start_date > request.end_date:
        raise HTTPException(status_code=422, detail="start_date 不能晚于 end_date")
    active = db.query(SearchIndexRebuildJob.id).filter(
        SearchIndexRebuildJob.status.in_(["queued", "running"])
    ).first()
    if active:
        raise HTTPException(status_code=409, detail="已有搜索索引重建任务正在执行")
    total = count_eligible_events(db, request.start_date, request.end_date)
    now = datetime.utcnow()
    job = SearchIndexRebuildJob(
        operator_user_id=current_user.id,
        start_date=request.start_date,
        end_date=request.end_date,
        total_events=total,
        status="completed" if total == 0 else "queued",
        finished_at=now if total == 0 else None,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job_to_dict(job)


@router.get("/rebuild-jobs")
def list_rebuild_jobs(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    jobs = db.query(SearchIndexRebuildJob).order_by(SearchIndexRebuildJob.created_at.desc()).limit(100).all()
    return [job_to_dict(job) for job in jobs]


@router.post("/rebuild-jobs/{job_id}/cancel")
def cancel_rebuild_job(
    job_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    job = db.get(SearchIndexRebuildJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="搜索索引重建任务不存在")
    if job.status not in {"queued", "running"}:
        raise HTTPException(status_code=400, detail="当前任务不可取消")
    job.status = "cancelled"
    job.finished_at = datetime.utcnow()
    db.commit()
    return job_to_dict(job)
