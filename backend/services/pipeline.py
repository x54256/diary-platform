"""LangGraph 6 阶段 AI 整理流水线 - 支持断点续跑"""

import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, AsyncIterator, TypedDict

from langchain_deepseek import ChatDeepSeek
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from config import settings
from database import SessionLocal
from models.diary import OrganizeTask
from services.ai import (
    CHECK_PROMPT,
    CLEAN_CHECK_PROMPT,
    CLEAN_PROMPT,
    EVENT_ORGANIZE_PROMPT,
    METADATA_PROMPT,
    TEMPLATE_FILL_PROMPT,
    ai_service,
)

logger = logging.getLogger(__name__)

# AI 交互日志（与 ai.py 保持一致的双写模式）
_ai_logger = logging.getLogger("ai_pipeline")
_ai_logger.setLevel(logging.DEBUG)
_log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
os.makedirs(_log_dir, exist_ok=True)
_log_file = os.path.join(_log_dir, f"ai_{datetime.now().strftime('%Y-%m-%d')}.log")
_file_handler = logging.FileHandler(_log_file, encoding="utf-8")
_file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
if not _ai_logger.handlers:
    _ai_logger.addHandler(_file_handler)


# ---------------------------------------------------------------------------
# Pipeline State
# ---------------------------------------------------------------------------

class PipelineState(TypedDict, total=False):
    # 输入
    original_text: str
    task_id: str
    diary_id: str
    user_id: str

    # 中间产物
    cleaned_text: str
    checked_text: str
    clean_check_log: list
    introduction: str
    events_raw: list
    trivia: list
    plans: list
    structured_events: list

    # 最终产物
    final_introduction: str
    final_events: list
    final_trivia: list
    final_plans: list
    check_log: list
    title: str
    summary: str
    mood: str
    location: str
    event_tags: list

    # 进度追踪
    current_step: str


# ---------------------------------------------------------------------------
# LLM 初始化
# ---------------------------------------------------------------------------

def _get_llm(temperature: float) -> ChatDeepSeek:
    """根据 temperature 创建 ChatDeepSeek 实例（含 api_key 和 JSON 强制输出）"""
    kwargs: dict[str, Any] = {
        "model": settings.DEEPSEEK_MODEL,
        "api_key": settings.DEEPSEEK_API_KEY,
        "temperature": temperature,
        "timeout": 120,
        "max_retries": 2,
        "model_kwargs": {"response_format": {"type": "json_object"}},
    }
    # settings.DEEPSEEK_API_URL 含 /v1 后缀，与 ChatDeepSeek 默认值不同，需显式传入
    if settings.DEEPSEEK_API_URL:
        kwargs["base_url"] = settings.DEEPSEEK_API_URL
    return ChatDeepSeek(**kwargs)


def _update_step(task_id: str, step: str):
    """通过独立 DB session 更新 organize_tasks.current_step"""
    db = SessionLocal()
    try:
        task = db.query(OrganizeTask).filter(OrganizeTask.id == task_id).first()
        if task:
            task.current_step = step
            db.commit()
    except Exception as e:
        logger.warning("更新 current_step 失败: %s", e)
        db.rollback()
    finally:
        db.close()


async def _invoke_llm(llm: ChatDeepSeek, system_prompt: str, user_message: str, step_name: str = "") -> dict:
    """调用 LLM 并解析 JSON 响应（含双向日志）"""
    from langchain_core.messages import HumanMessage, SystemMessage

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_message),
    ]
    _ai_logger.info("[%s] 请求: system=%s, user=%s", step_name, system_prompt[:200], user_message[:500])
    response = await llm.ainvoke(messages)
    raw_content = response.content
    _ai_logger.info("[%s] 响应: %s", step_name, raw_content[:1000])
    return json.loads(raw_content)


# ---------------------------------------------------------------------------
# Checkpointer 管理
# ---------------------------------------------------------------------------

# 模块级单例：连接 + checkpointer 实例，避免每次调用都创建新连接池
_checkpointer_instance: AsyncPostgresSaver | None = None
_connection: AsyncConnection | None = None
_setup_done: bool = False


@asynccontextmanager
async def get_checkpointer() -> AsyncIterator[AsyncPostgresSaver]:
    """
    获取 AsyncPostgresSaver 实例（异步上下文管理器）。
    - 首次调用时创建持久连接并执行 setup() 建表
    - 后续调用复用同一连接和实例，不再重复 setup
    - 连接在进程生命周期内保持存活

    用法：
        async with get_checkpointer() as checkpointer:
            graph = builder.compile(checkpointer=checkpointer)
            await graph.ainvoke(...)
    """
    global _checkpointer_instance, _connection, _setup_done

    if _checkpointer_instance is not None:
        # 已有单例，直接复用
        yield _checkpointer_instance
        return

    # 首次创建：直接建立持久 AsyncConnection（与 from_conn_string 内部参数一致）
    conn = await AsyncConnection.connect(
        settings.CHECKPOINT_CONN_STRING,
        autocommit=True,
        prepare_threshold=0,
        row_factory=dict_row,
    )
    saver = AsyncPostgresSaver(conn=conn)

    # 首次 setup：创建 checkpoints / checkpoint_writes / checkpoint_blobs 表
    if not _setup_done:
        await saver.setup()
        _setup_done = True

    # 保存到模块级单例
    _checkpointer_instance = saver
    _connection = conn
    yield saver


# ---------------------------------------------------------------------------
# 6 个 Node 异步函数
# ---------------------------------------------------------------------------

async def text_clean(state: PipelineState) -> dict:
    """Node 1: 文本清洗 (temp=0.3)"""
    task_id = state["task_id"]
    _update_step(task_id, "text_cleaning")

    original_text = state["original_text"]
    llm = _get_llm(0.3)
    result = await _invoke_llm(
        llm,
        CLEAN_PROMPT,
        json.dumps({"original_text": original_text}, ensure_ascii=False),
        step_name="text_clean",
    )
    return {"cleaned_text": result.get("cleaned_text", original_text)}


async def clean_check(state: PipelineState) -> dict:
    """Node 2: 清洗审核 (temp=0.3)"""
    task_id = state["task_id"]
    _update_step(task_id, "clean_checking")

    original_text = state["original_text"]
    cleaned_text = state["cleaned_text"]
    llm = _get_llm(0.3)
    result = await _invoke_llm(
        llm,
        CLEAN_CHECK_PROMPT,
        json.dumps(
            {"original_text": original_text, "cleaned_text": cleaned_text},
            ensure_ascii=False,
        ),
        step_name="clean_check",
    )
    return {
        "checked_text": result.get("checked_text", cleaned_text),
        "clean_check_log": result.get("clean_check_log", []),
    }


async def event_organize(state: PipelineState) -> dict:
    """Node 3: 事件整理 (temp=0.5)"""
    task_id = state["task_id"]
    _update_step(task_id, "event_organizing")

    checked_text = state["checked_text"]
    llm = _get_llm(0.5)
    result = await _invoke_llm(
        llm,
        EVENT_ORGANIZE_PROMPT,
        json.dumps({"checked_text": checked_text}, ensure_ascii=False),
        step_name="event_organize",
    )

    introduction = result.get("introduction", "")
    if not isinstance(introduction, str):
        introduction = ""
    trivia = result.get("trivia", [])
    if not isinstance(trivia, list):
        trivia = []
    plans = result.get("plans", [])
    if not isinstance(plans, list):
        plans = []

    return {
        "introduction": introduction,
        "events_raw": result.get("events", []),
        "trivia": trivia,
        "plans": plans,
    }


async def template_fill(state: PipelineState) -> dict:
    """Node 4: 三字段结构化 (temp=0.5)"""
    task_id = state["task_id"]
    _update_step(task_id, "structuring")

    events_raw = state["events_raw"]
    llm = _get_llm(0.5)
    result = await _invoke_llm(
        llm,
        TEMPLATE_FILL_PROMPT,
        json.dumps({"events": events_raw}, ensure_ascii=False),
        step_name="template_fill",
    )
    structured_events = ai_service._validate_events(result.get("events", []))
    return {"structured_events": structured_events}


async def content_check(state: PipelineState) -> dict:
    """Node 5: 内容审核 (temp=0.3)"""
    task_id = state["task_id"]
    _update_step(task_id, "content_checking")

    original_text = state["original_text"]
    introduction = state["introduction"]
    trivia = state["trivia"]
    plans = state["plans"]
    structured_events = state["structured_events"]

    llm = _get_llm(0.3)
    check_input = json.dumps(
        {
            "original_text": original_text,
            "organized_result": {
                "introduction": introduction,
                "trivia": trivia,
                "plans": plans,
            },
            "structured_events": structured_events,
        },
        ensure_ascii=False,
    )
    result = await _invoke_llm(llm, CHECK_PROMPT, check_input, step_name="content_check")

    final_introduction = result.get("introduction", introduction)
    final_events = ai_service._validate_events(
        result.get("events", structured_events)
    )
    final_trivia = result.get("trivia", trivia)
    if not isinstance(final_trivia, list):
        final_trivia = trivia
    final_plans = result.get("plans", plans)
    if not isinstance(final_plans, list):
        final_plans = plans

    return {
        "final_introduction": final_introduction,
        "final_events": final_events,
        "final_trivia": final_trivia,
        "final_plans": final_plans,
        "check_log": result.get("check_log", []),
    }


async def metadata_extract(state: PipelineState) -> dict:
    """Node 6: 元数据提取 (temp=0.3)"""
    task_id = state["task_id"]
    _update_step(task_id, "metadata_extracting")

    original_text = state["original_text"]
    final_introduction = state["final_introduction"]
    final_events = state["final_events"]
    final_trivia = state["final_trivia"]
    final_plans = state["final_plans"]

    llm = _get_llm(0.3)
    meta_input = json.dumps(
        {
            "original_text": original_text,
            "final_result": {
                "introduction": final_introduction,
                "events": final_events,
                "trivia": final_trivia,
                "plans": final_plans,
            },
        },
        ensure_ascii=False,
    )
    result = await _invoke_llm(llm, METADATA_PROMPT, meta_input, step_name="metadata_extract")

    return {
        "title": result.get("title", ""),
        "summary": result.get("summary", ""),
        "mood": result.get("mood", ""),
        "location": result.get("location", ""),
        "event_tags": result.get("event_tags", []),
    }


# ---------------------------------------------------------------------------
# 流水线执行
# ---------------------------------------------------------------------------

async def run_pipeline(
    original_text: str, task_id: str, diary_id: str, user_id: str
) -> dict:
    """构建并执行 LangGraph 6 阶段流水线"""
    builder = StateGraph(PipelineState)
    builder.add_node("text_clean", text_clean)
    builder.add_node("clean_check", clean_check)
    builder.add_node("event_organize", event_organize)
    builder.add_node("template_fill", template_fill)
    builder.add_node("content_check", content_check)
    builder.add_node("metadata_extract", metadata_extract)

    builder.add_edge(START, "text_clean")
    builder.add_edge("text_clean", "clean_check")
    builder.add_edge("clean_check", "event_organize")
    builder.add_edge("event_organize", "template_fill")
    builder.add_edge("template_fill", "content_check")
    builder.add_edge("content_check", "metadata_extract")
    builder.add_edge("metadata_extract", END)

    # 配置 checkpointer（支持断点续跑，复用单例连接确保 setup 已执行）
    async with get_checkpointer() as checkpointer:
        graph = builder.compile(checkpointer=checkpointer)

        # 执行
        config = {"configurable": {"thread_id": task_id}}
        result = await graph.ainvoke(
            {
                "original_text": original_text,
                "task_id": task_id,
                "diary_id": diary_id,
                "user_id": user_id,
            },
            config=config,
        )

    # 返回与 ai.py organize_diary 相同格式的 dict
    return {
        "title": result.get("title", ""),
        "summary": result.get("summary", ""),
        "events": result.get("final_events", []),
        "check_log": result.get("check_log", []),
        "clean_check_log": result.get("clean_check_log", []),
        "mood": result.get("mood", ""),
        "location": result.get("location", ""),
        "event_tags": result.get("event_tags", []),
        "introduction": result.get("final_introduction", ""),
        "trivia": result.get("final_trivia", []),
        "plans": result.get("final_plans", []),
    }


# ---------------------------------------------------------------------------
# Checkpoint 清理
# ---------------------------------------------------------------------------

async def cleanup_checkpoint(task_id: str):
    """清理指定任务的 checkpoint 数据（复用单例连接）"""
    async with get_checkpointer() as checkpointer:
        await checkpointer.adelete_thread(task_id)
