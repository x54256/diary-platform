"""历史批量入图、状态恢复及有效和过时结果查询。"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session, aliased, load_only

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


@router.post("/build", response_model=GraphTaskResponse, status_code=202)
def build_graph_only(payload: HistoryBuildRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """为已整理或已分析日记仅生成图谱；保留原日记状态及分析结果。"""
    try:
        task = create_history(db, user.id, payload.date_from, payload.date_to, graph_only=True)
    except GraphError as error:
        db.rollback()
        raise http_error(error) from error
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


def graph_result(db, run, diary_id, *, history=False, focus_event_id=None):
    if run is None: return {"diary_id": diary_id, "run": None, "events": [], "relations": []}
    node_query = db.query(GraphRunEvent).filter(GraphRunEvent.run_id == run.id)
    if focus_event_id is not None:
        node_query = node_query.filter(GraphRunEvent.event_id == focus_event_id)
    if not history and run.status != "POINTS_READY":
        node_query = node_query.join(DiaryEvent, DiaryEvent.id == GraphRunEvent.event_id).filter(DiaryEvent.is_in_graph.is_(True))
    nodes = node_query.order_by(GraphRunEvent.source_order, GraphRunEvent.event_id).all()
    query = db.query(GraphEventRelation).filter(GraphEventRelation.user_id == run.user_id,
        or_(GraphEventRelation.source_run_id == run.id, GraphEventRelation.target_run_id == run.id))
    if focus_event_id is not None:
        query = query.filter(or_(GraphEventRelation.source_event_id == focus_event_id,
                                 GraphEventRelation.target_event_id == focus_event_id))
    if not history:
        sr, tr, owner = aliased(GraphRun), aliased(GraphRun), aliased(GraphRun)
        sd, td = aliased(Diary), aliased(Diary)
        se, te = aliased(DiaryEvent), aliased(DiaryEvent)
        query = query.join(owner, owner.id == GraphEventRelation.run_id).join(sr, sr.id == GraphEventRelation.source_run_id).join(tr, tr.id == GraphEventRelation.target_run_id).join(
            sd, sd.id == sr.diary_id).join(td, td.id == tr.diary_id).join(se, se.id == GraphEventRelation.source_event_id).join(te, te.id == GraphEventRelation.target_event_id).filter(
                owner.status == "PUBLISHED", sr.status == "PUBLISHED", tr.status == "PUBLISHED", sd.deleted_at.is_(None), td.deleted_at.is_(None), se.is_in_graph.is_(True), te.is_in_graph.is_(True))
    relations = []
    edges = query.order_by(GraphEventRelation.id).all()
    evidence_map = {}
    if edges:
        evidence_rows = db.query(GraphRelationEvidence, GraphEventPoint.no).join(GraphEventPoint,
            GraphEventPoint.id == GraphRelationEvidence.point_id).filter(
            GraphRelationEvidence.relation_id.in_([edge.id for edge in edges]),
            GraphRelationEvidence.user_id == run.user_id).order_by(GraphEventPoint.no).all()
        for evidence, no in evidence_rows:
            evidence_map.setdefault(evidence.relation_id, []).append((evidence, no))
    for r in edges:
        evidence = evidence_map.get(r.id, [])
        relations.append({"id": r.id, "source_event_id": r.source_event_id, "target_event_id": r.target_event_id,
            "relation_type": r.relation_type, "certainty": r.certainty, "description": r.description,
            "final_source": r.final_source,
            "source_points": [{"point_id": e.point_id, "no": no} for e, no in evidence if e.side == "SOURCE"],
            "target_points": [{"point_id": e.point_id, "no": no} for e, no in evidence if e.side == "TARGET"]})
    # 按证据所属运行补齐跨日节点，避免混入同一事件的其他版本。
    endpoint_keys = {(node.run_id, node.event_id) for node in nodes}
    for edge in edges:
        endpoint_keys.update(((edge.source_run_id, edge.source_event_id),
                              (edge.target_run_id, edge.target_event_id)))
    extra_ids = {event_id for _, event_id in endpoint_keys}
    all_nodes = db.query(GraphRunEvent).filter(GraphRunEvent.user_id == run.user_id,
        GraphRunEvent.event_id.in_(extra_ids)).all() if extra_ids else []
    all_nodes = [node for node in all_nodes if (node.run_id, node.event_id) in endpoint_keys]
    runs = {}
    event_titles = {}
    if all_nodes:
        run_ids = {node.run_id for node in all_nodes}
        if history:
            run_rows = db.query(GraphRun).options(load_only(
                GraphRun.id, GraphRun.user_id, GraphRun.diary_id, GraphRun.diary_date,
                GraphRun.source_snapshot,
            )).filter(GraphRun.user_id == run.user_id, GraphRun.id.in_(run_ids)).all()
            runs = {item.id: item for item in run_rows}
        else:
            run_rows = db.query(GraphRun.id, GraphRun.diary_id, GraphRun.diary_date).filter(
                GraphRun.user_id == run.user_id, GraphRun.id.in_(run_ids)
            ).all()
            runs = {item.id: item for item in run_rows}
            event_titles = dict(db.query(DiaryEvent.id, DiaryEvent.event_title).filter(
                DiaryEvent.id.in_(extra_ids)
            ).all())
    point_map = {}
    if all_nodes:
        for point in db.query(GraphEventPoint.id, GraphEventPoint.run_id, GraphEventPoint.event_id,
                GraphEventPoint.no, GraphEventPoint.summary, GraphEventPoint.detail).filter(GraphEventPoint.user_id == run.user_id,
                GraphEventPoint.event_id.in_(extra_ids), GraphEventPoint.run_id.in_(runs)).order_by(GraphEventPoint.no).all():
            point_map.setdefault((point.run_id, point.event_id), []).append(
                {"id": point.id, "no": point.no, "summary": point.summary, "detail": point.detail})
    events = []
    for node in sorted(all_nodes, key=lambda node: (node.run_id != run.id,
            runs[node.run_id].diary_date, node.source_order, str(node.event_id))):
        owner_run = runs[node.run_id]
        if history:
            source = next((item for item in (owner_run.source_snapshot or {}).get("events", [])
                           if item["event_id"] == str(node.event_id)), {})
            title = source.get("title", "")
        else:
            title = event_titles.get(node.event_id) or ""
        events.append({"event_id": node.event_id, "run_id": node.run_id, "diary_id": owner_run.diary_id,
            "title": title, "diary_date": owner_run.diary_date,
            "occurred_on": node.occurred_on, "points": point_map.get((node.run_id, node.event_id), [])})
    return {"diary_id": diary_id, "run": {"id": run.id, "status": run.status,
        "published_at": run.published_at, "obsolete_at": run.obsolete_at, "analysis_run_id": run.analysis_run_id},
        "events": events, "relations": relations}


@router.get("/diaries/{diary_id}", response_model=GraphResultResponse)
def current_graph(diary_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    diary = db.query(Diary).filter(Diary.id == diary_id, Diary.user_id == user.id, Diary.deleted_at.is_(None)).first()
    if not diary: raise HTTPException(404, detail="日记不存在")
    run = db.query(GraphRun).options(load_only(
        GraphRun.id, GraphRun.user_id, GraphRun.diary_id, GraphRun.diary_date, GraphRun.status,
        GraphRun.published_at, GraphRun.obsolete_at, GraphRun.analysis_run_id,
    )).filter(GraphRun.diary_id == diary_id, GraphRun.user_id == user.id,
        GraphRun.status.in_(("PUBLISHED", "POINTS_READY"))).order_by(GraphRun.created_at.desc(), GraphRun.id.desc()).first()
    return graph_result(db, run, diary_id)


@router.get("/runs/{run_id}", response_model=GraphResultResponse)
def historical_graph(run_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    run = db.query(GraphRun).options(load_only(
        GraphRun.id, GraphRun.user_id, GraphRun.diary_id, GraphRun.diary_date, GraphRun.status,
        GraphRun.published_at, GraphRun.obsolete_at, GraphRun.analysis_run_id,
    )).filter(GraphRun.id == run_id, GraphRun.user_id == user.id).first()
    if not run: raise HTTPException(404, detail="运行不存在")
    return graph_result(db, run, run.diary_id, history=True)


@router.get("/events/{event_id}/neighbors", response_model=GraphResultResponse)
def event_neighbors(event_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    run = db.query(GraphRun).options(load_only(
        GraphRun.id, GraphRun.user_id, GraphRun.diary_id, GraphRun.diary_date, GraphRun.status,
        GraphRun.published_at, GraphRun.obsolete_at, GraphRun.analysis_run_id,
    )).join(GraphRunEvent, GraphRunEvent.run_id == GraphRun.id).join(
        Diary, Diary.id == GraphRun.diary_id).join(DiaryEvent, DiaryEvent.id == GraphRunEvent.event_id).filter(
        GraphRun.user_id == user.id, GraphRun.status.in_(("PUBLISHED", "POINTS_READY")), GraphRunEvent.event_id == event_id,
        Diary.deleted_at.is_(None), or_(GraphRun.status == "POINTS_READY", DiaryEvent.is_in_graph.is_(True))).order_by(
            GraphRun.created_at.desc(), GraphRun.id.desc()).first()
    if not run:
        raise HTTPException(404, detail="事件没有有效图谱")
    return graph_result(db, run, run.diary_id, focus_event_id=event_id)
