"""定期回顾的 LangGraph 编排：checkpoint 只记录已完成的业务节点。"""

from __future__ import annotations

import uuid
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from database import SessionLocal
from models.review import ReviewGenerationMode, ReviewTask, ReviewTaskStatus, ReviewTaskStep
from services.pipeline import get_checkpointer, run_graph_with_checkpoint
from services.review_generation import execute_review_task


class ReviewWorkflowState(TypedDict, total=False):
    task_id: str
    terminal: bool
    analysis_only: bool


async def _run_stage(state: ReviewWorkflowState, step: str) -> ReviewWorkflowState:
    task_id = uuid.UUID(state["task_id"])
    db = SessionLocal()
    try:
        task = db.query(ReviewTask).filter(ReviewTask.id == task_id).one()
        if not task.run_token:
            raise RuntimeError("回顾任务没有有效租约")
        token = task.run_token
    finally:
        db.close()
    await execute_review_task(task_id, token, stop_after=step)
    db = SessionLocal()
    try:
        task = db.query(ReviewTask).filter(ReviewTask.id == task_id).one()
        if task.status == ReviewTaskStatus.FAILED.value:
            raise RuntimeError(task.error_message or "回顾任务阶段失败")
        return {
            "terminal": task.status in {ReviewTaskStatus.SUCCEEDED.value, ReviewTaskStatus.SKIPPED_NO_DATA.value},
            "analysis_only": task.generation_mode == ReviewGenerationMode.ANALYSIS_ONLY.value,
        }
    finally:
        db.close()


async def freeze_sources(state: ReviewWorkflowState) -> ReviewWorkflowState:
    return await _run_stage(state, ReviewTaskStep.FREEZE_SOURCES.value)


async def organize_events(state: ReviewWorkflowState) -> ReviewWorkflowState:
    return await _run_stage(state, ReviewTaskStep.EVENT_ORGANIZE.value)


async def analyze_actions(state: ReviewWorkflowState) -> ReviewWorkflowState:
    return await _run_stage(state, ReviewTaskStep.ANALYSIS_ACTION.value)


async def persist_version(state: ReviewWorkflowState) -> ReviewWorkflowState:
    return await _run_stage(state, ReviewTaskStep.PERSIST_VERSION.value)


def _next_or_end(state: ReviewWorkflowState) -> str:
    return END if state.get("terminal") else "next"


def _after_freeze(state: ReviewWorkflowState) -> str:
    if state.get("terminal"):
        return END
    return "analyze_actions" if state.get("analysis_only") else "organize_events"


async def execute_review_graph(task_id: uuid.UUID, run_token: uuid.UUID) -> None:
    """从 PostgreSQL checkpoint 恢复回顾图；业务表始终是产物真相。"""
    builder = StateGraph(ReviewWorkflowState)
    builder.add_node("freeze_sources", freeze_sources)
    builder.add_node("organize_events", organize_events)
    builder.add_node("analyze_actions", analyze_actions)
    builder.add_node("persist_version", persist_version)
    builder.add_edge(START, "freeze_sources")
    builder.add_conditional_edges("freeze_sources", _after_freeze, {END: END, "organize_events": "organize_events", "analyze_actions": "analyze_actions"})
    builder.add_conditional_edges("organize_events", _next_or_end, {END: END, "next": "analyze_actions"})
    builder.add_conditional_edges("analyze_actions", _next_or_end, {END: END, "next": "persist_version"})
    builder.add_edge("persist_version", END)
    async with get_checkpointer() as checkpointer:
        graph = builder.compile(checkpointer=checkpointer)
        await run_graph_with_checkpoint(graph, str(task_id), {"task_id": str(task_id)})
