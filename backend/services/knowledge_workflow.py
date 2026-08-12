"""知识沉淀 LangGraph 工作流。"""

import json
from contextvars import ContextVar
from datetime import datetime, timedelta
from typing import Any, TypedDict
from uuid import UUID, uuid4

from langgraph.graph import END, START, StateGraph

from config import settings
from database import SessionLocal
from models.diary import Diary, DiaryEvent, DiaryOrganized, DiaryStatus
from models.knowledge import KnowledgeAtomicEvent, KnowledgeDeposit, KnowledgeTask
from services.knowledge_ai import SYSTEM_PROMPT, extract_atomic_events, freeze_model_config
from services.llm_metrics import estimate_prompt_tokens
from services.model_runtime import ModelRuntimeError, resolve_model_setting
from services.pipeline import get_checkpointer


class KnowledgeWorkflowError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class KnowledgeOwnershipLost(KnowledgeWorkflowError):
    def __init__(self):
        super().__init__("OWNERSHIP_LOST", "任务执行权已失效")


class KnowledgeState(TypedDict, total=False):
    task_id: str
    user_id: str
    diary_id: str
    source_structured_revision: int
    frozen_model_config: dict[str, Any]
    frozen_diary_date: str
    frozen_events: list[dict[str, Any]]
    batches: list[list[int]]
    next_batch_index: int
    batch_results: list[dict[str, Any]]


_runtime_token: ContextVar[UUID | None] = ContextVar("knowledge_run_token", default=None)
WORKFLOW_LEASE_SECONDS = 180


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if not value:
        return []
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except (TypeError, json.JSONDecodeError):
            return []
    return []


def _owned_task(db, task_id: str, *, lock: bool = False) -> KnowledgeTask:
    token = _runtime_token.get()
    if token is None:
        raise KnowledgeOwnershipLost()
    query = db.query(KnowledgeTask).filter(
        KnowledgeTask.id == UUID(task_id), KnowledgeTask.status == "RUNNING",
        KnowledgeTask.run_token == token, KnowledgeTask.lease_until > datetime.utcnow(),
    )
    task = (query.with_for_update().first() if lock else query.first())
    if not task:
        raise KnowledgeOwnershipLost()
    return task


def _set_step(task_id: str, step: str) -> None:
    db = SessionLocal()
    try:
        task = _owned_task(db, task_id, lock=True)
        task.current_step = step
        task.lease_until = datetime.utcnow() + timedelta(seconds=WORKFLOW_LEASE_SECONDS)
        task.updated_at = datetime.utcnow()
        db.commit()
    finally:
        db.close()


def _renew_ownership(task_id: str) -> None:
    token = _runtime_token.get()
    if token is None:
        raise KnowledgeOwnershipLost()
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        updated = db.query(KnowledgeTask).filter(
            KnowledgeTask.id == UUID(task_id), KnowledgeTask.status == "RUNNING",
            KnowledgeTask.run_token == token, KnowledgeTask.lease_until > now,
        ).update({
            "lease_until": now + timedelta(seconds=WORKFLOW_LEASE_SECONDS),
            "updated_at": now,
        }, synchronize_session=False)
        db.commit()
        if updated != 1:
            raise KnowledgeOwnershipLost()
    finally:
        db.close()


def _validate_source_rows(db, task: KnowledgeTask, *, lock: bool = False) -> tuple[Diary, DiaryOrganized]:
    diary_query = db.query(Diary).filter(Diary.id == task.diary_id, Diary.user_id == task.user_id, Diary.deleted_at.is_(None))
    diary = diary_query.with_for_update().first() if lock else diary_query.first()
    if not diary or diary.status != DiaryStatus.analyzed:
        raise KnowledgeWorkflowError("SOURCE_CHANGED", "日记来源已变化")
    organized_query = db.query(DiaryOrganized).filter(DiaryOrganized.id == task.source_diary_organized_id, DiaryOrganized.diary_id == diary.id)
    organized = organized_query.with_for_update().first() if lock else organized_query.first()
    if not organized or organized.structured_revision != task.source_structured_revision:
        raise KnowledgeWorkflowError("SOURCE_CHANGED", "日记来源已变化")
    return diary, organized


async def validate_source(state: KnowledgeState) -> dict[str, Any]:
    task_id = state["task_id"]
    _set_step(task_id, "VALIDATE_SOURCE")
    db = SessionLocal()
    try:
        task = _owned_task(db, task_id)
        diary, organized = _validate_source_rows(db, task)
        if db.query(KnowledgeDeposit.diary_id).filter(KnowledgeDeposit.diary_id == diary.id).first():
            raise KnowledgeWorkflowError("ALREADY_DEPOSITED", "该日记已完成知识沉淀")
        events = db.query(DiaryEvent).filter(DiaryEvent.diary_organized_id == organized.id).order_by(DiaryEvent.sort_order, DiaryEvent.id).all()
        if not events:
            raise KnowledgeWorkflowError("EMPTY_STRUCTURED_DIARY", "结构化日记没有事件")
        frozen: list[dict[str, Any]] = []
        for event_no, event in enumerate(events, start=1):
            item = {
                "event_no": event_no,
                "title": event.event_title or "",
                "body": _json_list(event.body),
            }
            if not item["title"].strip() and not item["body"]:
                raise KnowledgeWorkflowError("EMPTY_STRUCTURED_EVENT", f"第 {event_no} 个结构化事件为空")
            frozen.append(item)
        try:
            model = resolve_model_setting("knowledge", "knowledge_event_extract")
        except ModelRuntimeError as exc:
            raise KnowledgeWorkflowError("KNOWLEDGE_MODEL_NOT_CONFIGURED", str(exc)) from exc
        return {
            "user_id": str(task.user_id),
            "diary_id": str(task.diary_id),
            "source_structured_revision": task.source_structured_revision,
            "frozen_model_config": freeze_model_config(model),
            "frozen_diary_date": diary.diary_date.isoformat(),
            "frozen_events": frozen,
            "next_batch_index": 0,
            "batch_results": [],
        }
    finally:
        db.close()


async def prepare_batches(state: KnowledgeState) -> dict[str, Any]:
    _set_step(state["task_id"], "PREPARE_BATCHES")
    batches = plan_event_batches(
        state["frozen_events"], state["frozen_diary_date"],
        state["frozen_model_config"]["model_name"], settings.KNOWLEDGE_EVENT_INPUT_TOKEN_BUDGET,
    )
    return {"batches": batches}


def plan_event_batches(events: list[dict[str, Any]], diary_date: str, model_name: str, budget: int) -> list[list[int]]:
    """按完整结构化事件贪心装批，单个超长事件也不拆分。"""
    batches: list[list[int]] = []
    current: list[dict[str, Any]] = []
    for event in events:
        candidate = current + [event]
        message = json.dumps({"diary_date": diary_date, "events": candidate}, ensure_ascii=False, separators=(",", ":"))
        if current and estimate_prompt_tokens(model_name, SYSTEM_PROMPT, message) > budget:
            batches.append([item["event_no"] for item in current])
            current = [event]
        else:
            current = candidate
    if current:
        batches.append([item["event_no"] for item in current])
    return batches


async def extract_batch(state: KnowledgeState) -> dict[str, Any]:
    _set_step(state["task_id"], "EXTRACT_BATCH")
    batch_index = state["next_batch_index"]
    event_numbers = state["batches"][batch_index]
    wanted = set(event_numbers)
    events = [event for event in state["frozen_events"] if event["event_no"] in wanted]
    payload = {"diary_date": state["frozen_diary_date"], "events": events}
    results = await extract_atomic_events(payload, state["frozen_model_config"])
    _renew_ownership(state["task_id"])
    return {
        "batch_results": [*state.get("batch_results", []), {"batch_index": batch_index, "results": results}],
        "next_batch_index": batch_index + 1,
    }


def _after_extract(state: KnowledgeState) -> str:
    return "EXTRACT_BATCH" if state["next_batch_index"] < len(state["batches"]) else "PUBLISH"


async def publish(state: KnowledgeState) -> dict[str, Any]:
    _set_step(state["task_id"], "PUBLISH")
    db = SessionLocal()
    try:
        task = _owned_task(db, state["task_id"], lock=True)
        diary, organized = _validate_source_rows(db, task, lock=True)
        if db.query(KnowledgeDeposit.diary_id).filter(KnowledgeDeposit.diary_id == diary.id).first():
            raise KnowledgeWorkflowError("ALREADY_DEPOSITED", "该日记已完成知识沉淀")
        result_by_event: dict[int, list[dict[str, Any]]] = {}
        for batch in sorted(state["batch_results"], key=lambda item: item["batch_index"]):
            for result in batch["results"]:
                event_no = result["event_no"]
                if event_no in result_by_event:
                    raise KnowledgeWorkflowError("MODEL_OUTPUT_INVALID", "原子事件结果重复")
                result_by_event[event_no] = result["atomic_events"]
        expected = list(range(1, len(state["frozen_events"]) + 1))
        source_events = db.query(DiaryEvent).filter(
            DiaryEvent.diary_organized_id == organized.id,
        ).order_by(DiaryEvent.sort_order, DiaryEvent.id).all()
        if sorted(result_by_event) != expected or len(source_events) != len(expected):
            raise KnowledgeWorkflowError("MODEL_OUTPUT_INVALID", "原子事件结果未完整覆盖来源")
        now = datetime.utcnow()
        db.add(KnowledgeDeposit(
            diary_id=diary.id, user_id=task.user_id, task_id=task.id,
            source_diary_organized_id=organized.id, source_structured_revision=organized.structured_revision,
            completed_stage="ATOMIC_EVENTS", deposited_at=now,
        ))
        db.flush()
        for event_no in expected:
            source_id = source_events[event_no - 1].id
            for source_order, atom in enumerate(result_by_event[event_no]):
                occurred_time = datetime.strptime(atom["occurred_time"], "%H:%M").time() if atom["occurred_time"] else None
                db.add(KnowledgeAtomicEvent(
                    id=uuid4(), user_id=task.user_id, diary_id=diary.id,
                    source_diary_event_id=source_id, source_order=source_order,
                    title=atom["title"], source_fragments=atom["source_fragments"],
                    content=atom["content"], occurred_on=datetime.strptime(atom["occurred_on"], "%Y-%m-%d").date(),
                    occurred_time=occurred_time, created_at=now,
                ))
        task.status = "SUCCEEDED"
        task.lease_until = None
        task.completed_at = now
        task.error_code = None
        task.error_message = None
        task.updated_at = now
        db.commit()
        return {}
    except KnowledgeWorkflowError:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise KnowledgeWorkflowError("PUBLISH_FAILED", "原子事件发布失败") from exc
    finally:
        db.close()


def _builder() -> StateGraph:
    builder = StateGraph(KnowledgeState)
    builder.add_node("VALIDATE_SOURCE", validate_source)
    builder.add_node("PREPARE_BATCHES", prepare_batches)
    builder.add_node("EXTRACT_BATCH", extract_batch)
    builder.add_node("PUBLISH", publish)
    builder.add_edge(START, "VALIDATE_SOURCE")
    builder.add_edge("VALIDATE_SOURCE", "PREPARE_BATCHES")
    builder.add_edge("PREPARE_BATCHES", "EXTRACT_BATCH")
    builder.add_conditional_edges("EXTRACT_BATCH", _after_extract, {"EXTRACT_BATCH": "EXTRACT_BATCH", "PUBLISH": "PUBLISH"})
    builder.add_edge("PUBLISH", END)
    return builder


async def run_knowledge_graph(task_id: UUID, run_token: UUID) -> dict[str, Any]:
    initial: KnowledgeState = {"task_id": str(task_id)}
    token = _runtime_token.set(run_token)
    try:
        async with get_checkpointer() as checkpointer:
            graph = _builder().compile(checkpointer=checkpointer)
            config = {"configurable": {"thread_id": str(task_id)}}
            snapshot = await graph.aget_state(config)
            if snapshot.next:
                return dict(await graph.ainvoke(None, config=config))
            if snapshot.values and not snapshot.next:
                return dict(snapshot.values)
            return dict(await graph.ainvoke(initial, config=config))
    finally:
        _runtime_token.reset(token)
