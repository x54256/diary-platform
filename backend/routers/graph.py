"""历史批量入图、状态恢复及有效和过时结果查询。"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session, aliased

from database import get_db
from models.diary import Diary, DiaryEvent
from models.graph import GraphEventPoint, GraphEventRelation, GraphRelationEvidence, GraphRun, GraphRunEvent, GraphTask
from models.user import User
from schemas.graph import GraphResultResponse, GraphTaskResponse, HistoryBuildRequest
from services.auth import get_current_user
from services.graph_runtime import GraphError
from services.graph_tasks import can_retry_task, create_history, retry_task

router = APIRouter(prefix="/api/graph", tags=["事件图谱"])


def http_error(error):
    return HTTPException(status_code=404 if error.code == "NOT_FOUND" else 409,
                         detail={"code": error.code, "message": str(error)})


def task_result(db, task):
    runs = db.query(GraphRun).filter(GraphRun.task_id == task.id).order_by(GraphRun.diary_date, GraphRun.id).all()
    current = next((r for r in runs if r.id == task.current_run_id), None)
    error = None
    if task.error_code:
        context = (current.checkpoint or {}).get("error_context", {}) if current else {}
        error = {"code": task.error_code, "message": task.error_message,
            "stage": context.get("stage") or (current.current_step if current else None),
            **{k: context.get(k) for k in ("event_id", "pair_id", "call_id")}}
    return {"task_id": task.id, "entry_type": task.entry_type, "status": task.status,
        "date_from": task.date_from, "date_to": task.date_to, "current_run_id": task.current_run_id,
        "current_diary_id": current.diary_id if current else None,
        "current_date": current.diary_date if current else None, "current_step": current.current_step if current else None,
        "total_days": len(runs), "published_days": sum(r.published_at is not None for r in runs),
        "skipped_days": sum(r.status == "SKIPPED" for r in runs), "failed_days": sum(r.status == "FAILED" for r in runs),
        "pending_days": sum(r.status in ("QUEUED", "RUNNING") for r in runs), "error": error,
        "can_retry": can_retry_task(db, task), "runs": [{"run_id": r.id, "diary_id": r.diary_id,
            "diary_date": r.diary_date, "status": r.status, "current_step": r.current_step,
            "skip_reason": r.skip_reason, "error": {"code": r.error_code, "message": r.error_message} if r.error_code else None} for r in runs]}


def owned_task(db, task_id, user_id):
    task = db.query(GraphTask).filter(GraphTask.id == task_id, GraphTask.user_id == user_id).first()
    if not task: raise HTTPException(404, detail="任务不存在")
    return task


@router.post("/history-build", response_model=GraphTaskResponse, status_code=202)
def build_history(payload: HistoryBuildRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try: task = create_history(db, user.id, payload.date_from, payload.date_to)
    except GraphError as error: db.rollback(); raise http_error(error) from error
    return task_result(db, task)


@router.get("/tasks/{task_id}", response_model=GraphTaskResponse)
def get_task(task_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return task_result(db, owned_task(db, task_id, user.id))


@router.post("/tasks/{task_id}/retry", response_model=GraphTaskResponse, status_code=202)
def retry(task_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    task = owned_task(db, task_id, user.id)
    try: retry_task(db, task)
    except GraphError as error: db.rollback(); raise http_error(error) from error
    return task_result(db, task)


def graph_result(db, run, diary_id, *, history=False):
    if run is None: return {"diary_id": diary_id, "run": None, "events": [], "relations": []}
    source_events = {e["event_id"]: e for e in (run.source_snapshot or {}).get("events", [])}
    node_query = db.query(GraphRunEvent).filter(GraphRunEvent.run_id == run.id)
    if not history: node_query = node_query.join(DiaryEvent, DiaryEvent.id == GraphRunEvent.event_id).filter(DiaryEvent.is_in_graph.is_(True))
    nodes = node_query.order_by(GraphRunEvent.source_order, GraphRunEvent.event_id).all()
    events = []
    for node in nodes:
        points = db.query(GraphEventPoint).filter(GraphEventPoint.run_id == run.id,
            GraphEventPoint.event_id == node.event_id).order_by(GraphEventPoint.no).all()
        source = source_events.get(str(node.event_id), {})
        events.append({"event_id": node.event_id, "title": source.get("title", ""), "diary_date": run.diary_date,
            "occurred_on": node.occurred_on, "points": [{"id": p.id, "no": p.no, "summary": p.summary, "detail": p.detail} for p in points]})
    query = db.query(GraphEventRelation).filter(GraphEventRelation.user_id == run.user_id,
        or_(GraphEventRelation.source_run_id == run.id, GraphEventRelation.target_run_id == run.id))
    if not history:
        sr, tr, owner = aliased(GraphRun), aliased(GraphRun), aliased(GraphRun)
        sd, td = aliased(Diary), aliased(Diary)
        se, te = aliased(DiaryEvent), aliased(DiaryEvent)
        query = query.join(owner, owner.id == GraphEventRelation.run_id).join(sr, sr.id == GraphEventRelation.source_run_id).join(tr, tr.id == GraphEventRelation.target_run_id).join(
            sd, sd.id == sr.diary_id).join(td, td.id == tr.diary_id).join(se, se.id == GraphEventRelation.source_event_id).join(te, te.id == GraphEventRelation.target_event_id).filter(
                owner.status == "PUBLISHED", sr.status == "PUBLISHED", tr.status == "PUBLISHED", sd.deleted_at.is_(None), td.deleted_at.is_(None), se.is_in_graph.is_(True), te.is_in_graph.is_(True))
    relations = []
    for r in query.order_by(GraphEventRelation.id).all():
        evidence = db.query(GraphRelationEvidence, GraphEventPoint.no).join(GraphEventPoint,
            GraphEventPoint.id == GraphRelationEvidence.point_id).filter(GraphRelationEvidence.relation_id == r.id).order_by(GraphRelationEvidence.side, GraphEventPoint.no).all()
        relations.append({"id": r.id, "source_event_id": r.source_event_id, "target_event_id": r.target_event_id,
            "relation_type": r.relation_type, "certainty": r.certainty, "description": r.description,
            "final_source": r.final_source,
            "source_points": [{"point_id": e.point_id, "no": no} for e, no in evidence if e.side == "SOURCE"],
            "target_points": [{"point_id": e.point_id, "no": no} for e, no in evidence if e.side == "TARGET"]})
    return {"diary_id": diary_id, "run": {"id": run.id, "status": run.status,
        "published_at": run.published_at, "obsolete_at": run.obsolete_at, "analysis_run_id": run.analysis_run_id},
        "events": events, "relations": relations}


@router.get("/diaries/{diary_id}", response_model=GraphResultResponse)
def current_graph(diary_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    diary = db.query(Diary).filter(Diary.id == diary_id, Diary.user_id == user.id, Diary.deleted_at.is_(None)).first()
    if not diary: raise HTTPException(404, detail="日记不存在")
    run = db.query(GraphRun).filter(GraphRun.diary_id == diary_id, GraphRun.user_id == user.id, GraphRun.status == "PUBLISHED").first()
    return graph_result(db, run, diary_id)


@router.get("/runs/{run_id}", response_model=GraphResultResponse)
def historical_graph(run_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    run = db.query(GraphRun).filter(GraphRun.id == run_id, GraphRun.user_id == user.id).first()
    if not run: raise HTTPException(404, detail="运行不存在")
    return graph_result(db, run, run.diary_id, history=True)
