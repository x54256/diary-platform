"""分析和历史建图共用的可恢复任务调度。"""

import asyncio
import copy
import json
import logging
import traceback
from contextlib import suppress
from datetime import timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy.exc import IntegrityError

from config import settings
from database import SessionLocal
from models.diary import Diary, DiaryEvent, DiaryStatus, OrganizeTask
from models.graph import GraphModelCall, GraphRun, GraphTask, utcnow
from models.user import User
from services.analysis_history import effective_feedback, feedback_to_context, get_current_analysis_run, run_to_state
from services.graph_runtime import GraphContext, GraphError, digest, freeze_config
from services.person_relations import load_person_relation_context
from services.task_environment import TASK_ENVIRONMENT

logger = logging.getLogger(__name__)
ACTIVE = ("QUEUED", "RUNNING")


def json_list(value):
    if value is None: return []
    if isinstance(value, str):
        try: value = json.loads(value)
        except ValueError: raise GraphError("SOURCE_NOT_READY", "来源数组JSON无法解析") from None
    if not isinstance(value, list): raise GraphError("SOURCE_NOT_READY", "来源内容必须为数组")
    return value


def source_material(source):
    return {k: source[k] for k in ("user_id", "diary_id", "diary_date", "organized_id", "original_text", "events", "introduction", "trivia", "plans")}


def snapshot(db, diary, *, analysis=False):
    org = diary.organized
    if not org: raise GraphError("SOURCE_NOT_READY", "日记缺少整理结果")
    records = sorted(org.events, key=lambda e: (e.sort_order, str(e.id)))
    events = [{"event_id": str(e.id), "title": e.event_title, "body": json_list(e.body),
        "feeling": json_list(e.feeling), "reflection": json_list(e.reflection),
        "importance": e.user_importance or e.ai_importance, "source_order": e.sort_order} for e in records]
    analysis_date = utcnow().astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()
    source = {"user_id": str(diary.user_id), "diary_id": str(diary.id),
        "diary_date": diary.diary_date.isoformat(), "organized_id": str(org.id),
        "original_text": diary.original_text, "events": events,
        "introduction": org.introduction or "", "trivia": json_list(org.trivia), "plans": json_list(org.plans),
        "person_relations": load_person_relation_context(db, str(diary.user_id))}
    source["structured_diary"] = {"diary_date": source["diary_date"], "analysis_date": analysis_date,
        "timezone": "Asia/Shanghai", "introduction": source["introduction"], "events": events,
        "trivia": source["trivia"], "plans": source["plans"]}
    prior = get_current_analysis_run(db, diary.id)
    source["previous_run_id"] = str(prior.id) if prior else None
    if not analysis and not prior:
        raise GraphError("SOURCE_NOT_READY", "历史日记缺少有效分析轮次")
    feedback = effective_feedback(db, prior.id) if prior and analysis else []
    source["analysis_mode"] = "feedback" if feedback else "ordinary"
    if prior and analysis:
        previous = run_to_state(prior, records)
        for key in ("event_analyses", "event_cognitive_calibration_analyses", "event_cognitive_enhancements", "event_question_answers"):
            for row, event in zip(previous.get(key, []), events): row["event_id"] = event["event_id"]
        source["previous_state"] = previous
        tags = []
        for event, record in zip(events, records):
            raw = record.event_tags
            if isinstance(raw, str):
                try: raw = json.loads(raw)
                except ValueError: raw = {}
            tags.append({"event_id": event["event_id"], "title": event["title"],
                "tags": {kind: (raw or {}).get(kind, []) for kind in ("domain", "topic", "person_object", "psychological", "knowledge")}})
        source["previous_metadata"] = {"title": org.title or "", "summary": org.summary or "",
            "location": org.location or "", "mood": prior.mood or "", "event_tags": tags}
    source["feedback_context"] = feedback_to_context(feedback, records)
    return source


def assert_source_writable(db, diary_id, *, content=False):
    if db.query(GraphRun.id).join(GraphTask, GraphTask.id == GraphRun.task_id).filter(
        GraphRun.diary_id == diary_id, GraphTask.status.in_(ACTIVE), GraphRun.status.in_(("QUEUED", "RUNNING"))).first():
        raise GraphError("USER_TASK_ACTIVE", "该日记正在分析或建图，请等待任务完成")
    if content:
        diary = db.get(Diary, diary_id)
        frozen = db.query(GraphRun.id).filter(GraphRun.diary_id == diary_id, GraphRun.source_snapshot.is_not(None)).first()
        if frozen or (diary and diary.status == DiaryStatus.analyzed):
            raise GraphError("SOURCE_LOCKED", "已提交分析的来源内容不可修改")


def obsolete(db, diary):
    db.query(GraphRun).filter(GraphRun.diary_id == diary.id, GraphRun.status == "PUBLISHED").update(
        {"status": "OBSOLETE", "obsolete_at": utcnow(), "updated_at": utcnow()}, synchronize_session=False)
    ids = [e.id for e in diary.organized.events]
    if ids: db.query(DiaryEvent).filter(DiaryEvent.id.in_(ids)).update({"is_in_graph": False}, synchronize_session=False)


def create_analysis(db, user_id, diary_id):
    db.query(User).filter(User.id == user_id).with_for_update().one()
    active = db.query(GraphTask).filter(GraphTask.user_id == user_id, GraphTask.status.in_(ACTIVE)).first()
    if active:
        run = db.query(GraphRun).filter(GraphRun.task_id == active.id, GraphRun.diary_id == diary_id).first()
        if active.entry_type == "ANALYSIS" and run: return active, run
        raise GraphError("USER_TASK_ACTIVE", "当前用户已有分析或建图任务")
    diary = db.query(Diary).filter(Diary.id == diary_id, Diary.user_id == user_id, Diary.deleted_at.is_(None)).with_for_update().first()
    if not diary: raise GraphError("NOT_FOUND", "日记不存在")
    if diary.status not in (DiaryStatus.organized, DiaryStatus.analyzed):
        raise GraphError("SOURCE_NOT_READY", "只有已整理日记可以分析")
    frozen = freeze_config(include_analysis=True)
    source = snapshot(db, diary, analysis=True)
    task_id = uuid4()
    db.add(OrganizeTask(id=task_id, diary_id=diary.id, user_id=user_id, task_type="analyze",
        status="running", analysis_mode=source["analysis_mode"], current_step="PREPARE_SOURCE"))
    db.flush()
    task = GraphTask(id=task_id, user_id=user_id, entry_type="ANALYSIS", organize_task_id=task_id,
        date_from=diary.diary_date, date_to=diary.diary_date, config_snapshot=frozen)
    db.add(task); db.flush()
    run = GraphRun(task_id=task.id, user_id=user_id, diary_id=diary.id, diary_date=diary.diary_date,
        source_organized_id=diary.organized.id, source_snapshot=source, source_sha256=digest(source_material(source)),
        analysis_mode=source["analysis_mode"])
    db.add(run); db.flush()
    old_tasks = db.query(GraphTask).join(GraphRun, GraphRun.task_id == GraphTask.id).filter(
        GraphRun.diary_id == diary.id, GraphTask.status == "FAILED").all()
    for old in old_tasks: old.status, old.updated_at = "SUPERSEDED", utcnow()
    obsolete(db, diary)
    db.commit()
    graph_task_manager.wake()
    return task, run


def create_history(db, user_id, date_from, date_to):
    db.query(User).filter(User.id == user_id).with_for_update().one()
    if db.query(GraphTask.id).filter(GraphTask.user_id == user_id, GraphTask.status.in_(ACTIVE)).first():
        raise GraphError("USER_TASK_ACTIVE", "当前用户已有分析或建图任务")
    diaries = db.query(Diary.id, Diary.diary_date).filter(Diary.user_id == user_id,
        Diary.deleted_at.is_(None), Diary.diary_date.between(date_from, date_to)).order_by(Diary.diary_date, Diary.id).all()
    task = GraphTask(user_id=user_id, entry_type="HISTORY", date_from=date_from, date_to=date_to,
        config_snapshot=freeze_config() if diaries else {}, status="QUEUED" if diaries else "SUCCEEDED",
        completed_at=None if diaries else utcnow())
    db.add(task); db.flush()
    for diary in diaries: db.add(GraphRun(task_id=task.id, user_id=user_id, diary_id=diary.id, diary_date=diary.diary_date))
    db.commit(); graph_task_manager.wake(); return task


def can_retry_task(db, task):
    if task.status != "FAILED": return False
    run = db.query(GraphRun).filter(GraphRun.task_id == task.id, GraphRun.status == "FAILED").order_by(GraphRun.diary_date, GraphRun.id).first()
    if not run: return False
    if db.query(GraphTask.id).filter(GraphTask.user_id == task.user_id, GraphTask.status.in_(ACTIVE)).first(): return False
    if db.query(GraphRun.id).filter(GraphRun.diary_id == run.diary_id, GraphRun.task_id != task.id,
            GraphRun.created_at > run.created_at, GraphRun.status != "SKIPPED").first(): return False
    diary = db.query(Diary).filter(Diary.id == run.diary_id, Diary.user_id == task.user_id, Diary.deleted_at.is_(None)).first()
    if not diary: return False
    if not run.source_snapshot: return True
    try:
        return digest(source_material(snapshot(db, diary, analysis=task.entry_type == "ANALYSIS"))) == run.source_sha256
    except GraphError:
        return False


def retry_task(db, task):
    db.query(User).filter(User.id == task.user_id).with_for_update().one()
    db.refresh(task, with_for_update=True)
    if task.status != "FAILED": raise GraphError("INVALID_TASK_STATE", "只有失败任务可以恢复")
    run = db.query(GraphRun).filter(GraphRun.task_id == task.id, GraphRun.status == "FAILED").order_by(GraphRun.diary_date, GraphRun.id).first()
    if not run: raise GraphError("INVALID_TASK_STATE", "没有可恢复的失败日期")
    if db.query(GraphTask.id).filter(GraphTask.user_id == task.user_id, GraphTask.status.in_(ACTIVE)).first():
        raise GraphError("USER_TASK_ACTIVE", "当前用户已有活动任务")
    if db.query(GraphRun.id).filter(GraphRun.diary_id == run.diary_id, GraphRun.task_id != task.id,
            GraphRun.created_at > run.created_at, GraphRun.status != "SKIPPED").first():
        raise GraphError("TASK_SUPERSEDED", "该日记已创建更新运行，请使用新任务")
    diary = db.query(Diary).filter(Diary.id == run.diary_id, Diary.user_id == task.user_id, Diary.deleted_at.is_(None)).with_for_update().first()
    if not diary: raise GraphError("SOURCE_CHANGED", "来源日记已不存在")
    if run.source_snapshot and digest(source_material(snapshot(db, diary, analysis=task.entry_type == "ANALYSIS"))) != run.source_sha256:
        raise GraphError("SOURCE_CHANGED", "来源已变化，请创建新分析任务")
    # 独立核验失败重新开启最多两轮；保留旧审核及调用记录。
    if run.error_code == "POINT_REVIEW_FAILED":
        state = copy.deepcopy(run.checkpoint)
        for work in state.get("point_work", {}).values():
            if not work.get("passed"): work.update(round=0, next="combined")
        run.checkpoint = state
    db.query(GraphModelCall).filter(GraphModelCall.task_id == task.id,
        GraphModelCall.status == "STARTED").update({"status": "UNKNOWN", "completed_at": utcnow()})
    run.status, run.error_code, run.error_message = "QUEUED", None, None
    task.status, task.error_code, task.error_message = "QUEUED", None, None
    task.retry_count += 1; task.available_at, task.updated_at = utcnow(), utcnow()
    if task.organize_task_id:
        db.query(OrganizeTask).filter(OrganizeTask.id == task.organize_task_id).update({"status": "running", "error_message": None})
    db.commit(); graph_task_manager.wake(); return task


class GraphTaskManager:
    def __init__(self):
        self._runner = None
        self._wake = asyncio.Event()
        self._stopping = False

    def wake(self): self._wake.set()

    async def start(self):
        self._stopping = False
        if not self._runner or self._runner.done(): self._runner = asyncio.create_task(self._loop())

    async def stop(self):
        self._stopping = True; self._wake.set()
        if self._runner:
            self._runner.cancel()
            with suppress(asyncio.CancelledError): await self._runner

    def claim(self):
        with SessionLocal() as db:
            stale = db.query(GraphTask).filter(GraphTask.environment == TASK_ENVIRONMENT,
                GraphTask.status == "RUNNING", GraphTask.lease_until < utcnow()).with_for_update(skip_locked=True).all()
            for task in stale:
                task.status, task.run_token = "QUEUED", None
                db.query(GraphModelCall).filter(GraphModelCall.task_id == task.id, GraphModelCall.status == "STARTED").update({"status": "UNKNOWN"})
            task = db.query(GraphTask).filter(GraphTask.environment == TASK_ENVIRONMENT,
                GraphTask.status == "QUEUED", GraphTask.available_at <= utcnow()).order_by(GraphTask.created_at, GraphTask.id).with_for_update(skip_locked=True).first()
            if not task: db.commit(); return None
            task.status, task.run_token = "RUNNING", uuid4()
            task.lease_until = utcnow() + timedelta(seconds=settings.GRAPH_LEASE_SECONDS)
            task.started_at = task.started_at or utcnow(); task.updated_at = utcnow()
            result = (task.id, task.run_token); db.commit(); return result

    async def heartbeat(self, task_id, token):
        while True:
            await asyncio.sleep(settings.GRAPH_HEARTBEAT_SECONDS)
            with SessionLocal() as db:
                count = db.query(GraphTask).filter(GraphTask.id == task_id, GraphTask.status == "RUNNING",
                    GraphTask.run_token == token, GraphTask.lease_until > utcnow()).update(
                        {"lease_until": utcnow() + timedelta(seconds=settings.GRAPH_LEASE_SECONDS)})
                db.commit()
                if not count: return

    async def execute(self, task_id, token):
        from services.graph_workflow import execute_task
        heart = asyncio.create_task(self.heartbeat(task_id, token))
        try:
            await execute_task(task_id, token)
        except asyncio.CancelledError: raise
        except Exception as exc:
            code = exc.code if isinstance(exc, GraphError) else "EXECUTION_FAILED"
            message = str(exc) if isinstance(exc, GraphError) else "任务执行失败，详见阶段检查记录"
            if code == "OWNERSHIP_LOST": return
            with SessionLocal() as db:
                task = db.query(GraphTask).filter(GraphTask.id == task_id, GraphTask.status == "RUNNING", GraphTask.run_token == token,
                    GraphTask.lease_until > utcnow()).with_for_update().first()
                if not task: return
                task.status, task.error_code, task.error_message, task.updated_at = "FAILED", code, message, utcnow()
                db.query(GraphModelCall).filter(GraphModelCall.task_id == task.id,
                    GraphModelCall.status == "STARTED").update({"status": "UNKNOWN", "completed_at": utcnow()})
                if task.current_run_id:
                    run = db.query(GraphRun).filter(GraphRun.id == task.current_run_id).one()
                    if run.status not in ("PUBLISHED", "OBSOLETE", "SKIPPED"):
                        run.status, run.error_code, run.error_message = "FAILED", code, message
                        state = dict(run.checkpoint or {})
                        state["error_context"] = exc.context if isinstance(exc, GraphError) else {
                            "exception_type": type(exc).__name__,
                            "frames": [{"file": frame.filename.rsplit("/", 1)[-1],
                                        "line": frame.lineno, "function": frame.name}
                                       for frame in traceback.extract_tb(exc.__traceback__)]}
                        run.checkpoint = state
                if task.organize_task_id:
                    db.query(OrganizeTask).filter(OrganizeTask.id == task.organize_task_id).update({"status": "failed", "error_message": message})
                db.commit()
            logger.error("图谱任务失败 code=%s type=%s task_id=%s", code, type(exc).__name__, task_id)
        finally:
            heart.cancel()
            with suppress(asyncio.CancelledError): await heart

    async def _loop(self):
        while not self._stopping:
            try:
                claimed = self.claim()
                if claimed: await self.execute(*claimed); continue
            except Exception:
                logger.error("图谱调度检查失败，等待下次检查")
            self._wake.clear()
            try: await asyncio.wait_for(self._wake.wait(), timeout=5)
            except asyncio.TimeoutError: pass


graph_task_manager = GraphTaskManager()
