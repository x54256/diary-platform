"""使用真实日记验证事件图谱关系识别设计。

该脚本不写入正式业务表，只读取真实日记和历史知识事件，并将试验结果
写入本地 JSON 文件。模型调用使用管理端当前的 analysis 和 embedding 配置。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from sqlalchemy.orm import joinedload

from config import settings
from database import SessionLocal
from models.diary import Diary, DiaryEvent, DiaryOrganized
from models.knowledge import KnowledgeAtomicEvent
from models.model_config import ChannelModel, ModelCatalog, ModelSetting
from services.analysis_pipeline import _get_llm
from services.embedding_client import embed_texts
from services.model_management import (
    decrypt_channel_key,
    get_embedding_config,
    validate_setting_choice,
    validate_thinking_choice,
)
from services.model_runtime import RuntimeModelConfig, resolve_thinking_payload
from services.person_relations import load_person_relation_context


DEFAULT_DIARY_IDS = [
    "3381b76d-cf19-452a-8879-e33ff5446aaa",  # 2026-08-27, 7 events
    "fb68a61e-5417-4a6c-93ad-4353ddd4a0b3",  # 2026-08-28, 9 events
    "043d142e-fa41-4ff6-9caa-079909bd124e",  # 2026-08-29, 4 events
]

RELATION_TYPES = {"CONTINUATION", "CAUSAL", "ASSOCIATION", "THEMATIC", "REFERENCE"}
CONFIDENCES = {"HIGH", "MEDIUM", "LOW"}
CONTINUATION_RESULTS = {"EXECUTED", "EXECUTED_FAILED", None}
PLAN_SOURCES = {"SELF", "THIRD_PARTY", None}
AI_LOGGER = logging.getLogger("ai_pipeline")
RELATION_FIELDS = {
    "source_event_key",
    "target_event_key",
    "relation_type",
    "confidence",
    "continuation_result",
    "plan_source",
    "reason",
    "source_evidence",
    "target_evidence",
}
EVIDENCE_FIELDS = {"body_index", "quote"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="用真实日记验证事件关系设计")
    parser.add_argument("--diary-id", action="append", dest="diary_ids")
    parser.add_argument("--top-per-query", type=int, default=5)
    parser.add_argument("--max-candidates", type=int, default=15)
    parser.add_argument("--model", help="仅覆盖本次关系识别模型，不修改管理端配置")
    parser.add_argument("--resume", action="store_true", help="复用输出文件中已通过的调用和召回候选")
    parser.add_argument(
        "--output",
        default="../.scratch/event-relation-validation-20260901.json",
    )
    return parser.parse_args()


def parse_body(value: Any) -> list[str]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    if not isinstance(value, list):
        return []
    return [item if isinstance(item, str) else "" for item in value]


def body_items(body: list[str]) -> list[dict[str, Any]]:
    return [
        {"body_index": index, "text": text.strip()}
        for index, text in enumerate(body)
        if text.strip()
    ]


def full_body(body: list[str]) -> str:
    return "\n\n".join(item["text"] for item in body_items(body))


def extract_prompt(document: str, heading: str) -> str:
    heading_start = document.index(heading)
    fence_start = document.index("```text", heading_start) + len("```text")
    fence_end = document.index("```", fence_start)
    return document[fence_start:fence_end].strip()


def cosine_similarity(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)


def load_current_diaries(diary_ids: list[str]) -> tuple[list[dict[str, Any]], str, list[dict[str, Any]]]:
    db = SessionLocal()
    try:
        diaries: list[dict[str, Any]] = []
        user_id: str | None = None
        people: list[dict[str, Any]] = []
        for diary_id in diary_ids:
            diary = (
                db.query(Diary)
                .filter(Diary.id == UUID(diary_id), Diary.deleted_at.is_(None))
                .first()
            )
            if not diary or not diary.organized:
                raise RuntimeError(f"日记或结构化结果不存在: {diary_id}")
            if user_id is None:
                user_id = str(diary.user_id)
                people = load_person_relation_context(db, diary.user_id)
            elif user_id != str(diary.user_id):
                raise RuntimeError("验证样本必须属于同一用户")

            events: list[dict[str, Any]] = []
            for event in sorted(diary.organized.events, key=lambda item: item.sort_order):
                body = parse_body(event.body)
                if not body_items(body):
                    continue
                events.append({
                    "event_id": str(event.id),
                    "event_key": f"E{len(events) + 1}",
                    "event_order": event.sort_order,
                    "title": event.event_title or "",
                    "body_raw": body,
                    "body": body_items(body),
                })
            diaries.append({
                "diary_id": str(diary.id),
                "diary_date": str(diary.diary_date),
                "events": events,
            })
        if user_id is None:
            raise RuntimeError("没有可验证的日记")
        return diaries, user_id, people
    finally:
        db.rollback()
        db.close()


def load_historical_events(user_id: str, excluded_diary_ids: set[str]) -> list[dict[str, Any]]:
    db = SessionLocal()
    try:
        rows = (
            db.query(KnowledgeAtomicEvent, DiaryEvent, Diary)
            .join(DiaryEvent, DiaryEvent.id == KnowledgeAtomicEvent.source_diary_event_id)
            .join(DiaryOrganized, DiaryOrganized.id == DiaryEvent.diary_organized_id)
            .join(Diary, Diary.id == DiaryOrganized.diary_id)
            .filter(
                KnowledgeAtomicEvent.user_id == UUID(user_id),
                Diary.deleted_at.is_(None),
            )
            .order_by(Diary.diary_date.asc(), DiaryEvent.sort_order.asc(), KnowledgeAtomicEvent.source_order.asc())
            .all()
        )
        result: list[dict[str, Any]] = []
        seen_event_ids: set[str] = set()
        for knowledge, event, diary in rows:
            event_id = str(event.id)
            if str(diary.id) in excluded_diary_ids or event_id in seen_event_ids:
                continue
            body = parse_body(event.body)
            if not body_items(body):
                continue
            seen_event_ids.add(event_id)
            result.append({
                "historical_event_id": event_id,
                "historical_knowledge_event_id": str(knowledge.id),
                "diary_id": str(diary.id),
                "diary_date": str(diary.diary_date),
                "title": event.event_title or "",
                "body_raw": body,
                "body": body_items(body),
            })
        return result
    finally:
        db.rollback()
        db.close()


def vectorize_events(events: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    chunks_by_event: dict[str, list[dict[str, Any]]] = {}
    unique_texts: list[str] = []
    text_index: dict[str, int] = {}
    for event in events:
        event_id = event.get("event_id") or event["historical_event_id"]
        chunks = [{"chunk_type": "FULL_BODY", "body_index": None, "text": full_body(event["body_raw"])}]
        chunks.extend(
            {"chunk_type": "BODY_PARAGRAPH", "body_index": item["body_index"], "text": item["text"]}
            for item in event["body"]
        )
        chunks_by_event[event_id] = chunks
        for chunk in chunks:
            text = chunk["text"]
            if text not in text_index:
                text_index[text] = len(unique_texts)
                unique_texts.append(text)

    vectors = embed_texts(unique_texts)
    for chunks in chunks_by_event.values():
        for chunk in chunks:
            vector = vectors[text_index[chunk["text"]]]
            if not vector or len(vector) != 1024 or any(not math.isfinite(value) for value in vector):
                raise RuntimeError("embedding 返回结果不合法")
            chunk["embedding"] = vector
    return chunks_by_event


def recall_candidates(
    current_event: dict[str, Any],
    historical_events: list[dict[str, Any]],
    vectors: dict[str, list[dict[str, Any]]],
    top_per_query: int,
    max_candidates: int,
) -> list[dict[str, Any]]:
    current_chunks = vectors[current_event["event_id"]]
    per_event_hits: dict[str, dict[str, Any]] = {}
    history_by_id = {event["historical_event_id"]: event for event in historical_events}

    for current_chunk in current_chunks:
        query_hits: list[dict[str, Any]] = []
        for history in historical_events:
            history_id = history["historical_event_id"]
            best_history_chunk = max(
                vectors[history_id],
                key=lambda chunk: cosine_similarity(current_chunk["embedding"], chunk["embedding"]),
            )
            similarity = cosine_similarity(current_chunk["embedding"], best_history_chunk["embedding"])
            query_hits.append({
                "historical_event_id": history_id,
                "similarity": similarity,
                "current_chunk_type": current_chunk["chunk_type"],
                "current_body_index": current_chunk["body_index"],
                "historical_chunk_type": best_history_chunk["chunk_type"],
                "historical_body_index": best_history_chunk["body_index"],
            })
        query_hits.sort(key=lambda item: (-item["similarity"], item["historical_event_id"]))
        for hit in query_hits[:top_per_query]:
            history_id = hit["historical_event_id"]
            previous = per_event_hits.get(history_id)
            if previous is None or hit["similarity"] > previous["max_similarity"]:
                history = history_by_id[history_id]
                per_event_hits[history_id] = {
                    "historical_event_id": history_id,
                    "historical_knowledge_event_id": history["historical_knowledge_event_id"],
                    "diary_date": history["diary_date"],
                    "title": history["title"],
                    "max_similarity": hit["similarity"],
                    "best_match": {key: value for key, value in hit.items() if key not in {"historical_event_id", "similarity"}},
                }

    merged = sorted(
        per_event_hits.values(),
        key=lambda item: (-item["max_similarity"], item["historical_event_id"]),
    )
    return merged[:max_candidates]


def validate_evidence(evidence: Any, event: dict[str, Any], field: str) -> None:
    if not isinstance(evidence, list) or not evidence:
        raise ValueError(f"{field} 必须是非空数组")
    body_by_index = {item["body_index"]: item["text"] for item in event["body"]}
    for item in evidence:
        if not isinstance(item, dict) or set(item) != EVIDENCE_FIELDS:
            raise ValueError(f"{field} 证据字段不合法")
        index = item.get("body_index")
        quote = item.get("quote")
        if index not in body_by_index or not isinstance(quote, str) or not quote.strip():
            raise ValueError(f"{field} 证据下标或引文不合法")
        if quote not in body_by_index[index]:
            raise ValueError(f"{field} 引文不是连续原文: {quote}")


def validate_relations(
    result: Any,
    events_by_key: dict[str, dict[str, Any]],
    historical: bool,
) -> list[dict[str, Any]]:
    if not isinstance(result, dict) or set(result) != {"relations"} or not isinstance(result["relations"], list):
        raise ValueError("顶层输出必须且只能包含 relations 数组")
    duplicates: set[tuple[str, str, str]] = set()
    for relation in result["relations"]:
        if not isinstance(relation, dict) or set(relation) != RELATION_FIELDS:
            raise ValueError("关系字段集合不合法")
        source_key = relation["source_event_key"]
        target_key = relation["target_event_key"]
        if source_key not in events_by_key or target_key not in events_by_key or source_key == target_key:
            raise ValueError("关系端点不合法")
        if historical and ((source_key == "C") + (target_key == "C") != 1):
            raise ValueError("历史关系必须恰好一端为 C")
        relation_type = relation["relation_type"]
        if relation_type not in RELATION_TYPES or relation["confidence"] not in CONFIDENCES:
            raise ValueError("关系类型或置信度不合法")
        if relation["continuation_result"] not in CONTINUATION_RESULTS or relation["plan_source"] not in PLAN_SOURCES:
            raise ValueError("CONTINUATION 子属性不合法")
        if relation_type != "CONTINUATION" and (
            relation["continuation_result"] is not None or relation["plan_source"] is not None
        ):
            raise ValueError("非 CONTINUATION 关系必须使用空子属性")
        if not isinstance(relation["reason"], str) or not relation["reason"].strip():
            raise ValueError("关系理由不能为空")
        duplicate_key = (source_key, target_key, relation_type)
        if duplicate_key in duplicates:
            raise ValueError("存在同方向、同类型重复关系")
        duplicates.add(duplicate_key)
        validate_evidence(relation["source_evidence"], events_by_key[source_key], "source_evidence")
        validate_evidence(relation["target_evidence"], events_by_key[target_key], "target_evidence")
    return result["relations"]


async def invoke_json(
    llm: Any,
    prompt: str,
    payload: dict[str, Any],
    *,
    step_name: str,
    model_name: str,
) -> Any:
    user_message = json.dumps(payload, ensure_ascii=False)
    AI_LOGGER.info(
        "[%s] 真实验证 LLM 完整参数: model=%s temperature=0.1 "
        "response_format=json_object\nsystem=%s\nuser=%s",
        step_name,
        model_name,
        prompt,
        user_message,
    )
    try:
        response = await llm.ainvoke([
            SystemMessage(content=prompt),
            HumanMessage(content=user_message),
        ])
        content = response.content
        AI_LOGGER.info("[%s] 真实验证 LLM 完整返回: %s", step_name, content)
        if not isinstance(content, str):
            raise ValueError("模型返回内容不是字符串")
        return json.loads(content)
    except Exception as exc:
        AI_LOGGER.exception(
            "[%s] 真实验证 LLM 调用失败: model=%s error_type=%s error=%s",
            step_name,
            model_name,
            type(exc).__name__,
            exc,
        )
        raise


def public_relation(relation: dict[str, Any], events_by_key: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        **relation,
        "source_title": events_by_key[relation["source_event_key"]]["title"],
        "target_title": events_by_key[relation["target_event_key"]]["title"],
    }


def save_result(path: Path, result: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


def build_relation_llm(model_name: str | None) -> tuple[Any, str]:
    if not model_name:
        llm = _get_llm(0.1, "analysis", None)
        resolved_name = getattr(llm, "model_name", None) or getattr(llm, "model", None)
        return llm, str(resolved_name)

    db = SessionLocal()
    try:
        targets = (
            db.query(ChannelModel)
            .options(joinedload(ChannelModel.model), joinedload(ChannelModel.channel))
            .join(ModelCatalog, ModelCatalog.id == ChannelModel.model_id)
            .filter(
                ModelCatalog.model_name == model_name,
                ModelCatalog.model_type == "language",
                ModelCatalog.enabled.is_(True),
                ChannelModel.enabled.is_(True),
            )
            .all()
        )
        targets = [target for target in targets if target.channel.enabled]
        if not targets:
            raise RuntimeError(f"指定关系模型不可用: {model_name}")
        if len(targets) > 1:
            raise RuntimeError(f"指定关系模型存在多个可用渠道: {model_name}")
        target = targets[0]
        validate_setting_choice("analysis", target)
        analysis_setting = db.query(ModelSetting).filter(ModelSetting.setting_key == "analysis").first()
        base_thinking = bool(analysis_setting and analysis_setting.thinking_enabled)
        if target.model.reasoning_mode == "always_on":
            thinking_enabled = True
        elif target.model.reasoning_mode == "unsupported":
            thinking_enabled = False
        else:
            thinking_enabled = base_thinking
        validate_thinking_choice(target, thinking_enabled, "关系识别")
        runtime = RuntimeModelConfig(
            setting_key="analysis",
            step_key=None,
            model_type="language",
            protocol="openai_chat",
            api_base_url=target.channel.api_base_url.rstrip("/"),
            api_key=decrypt_channel_key(target.channel),
            model_name=target.model.model_name,
            channel_model_id=target.id,
            reasoning_mode=target.model.reasoning_mode,
            thinking_enabled=thinking_enabled,
            thinkmode=target.channel.thinkmode or {},
        )
    finally:
        db.rollback()
        db.close()

    kwargs: dict[str, Any] = {
        "model": runtime.model_name,
        "api_key": runtime.api_key,
        "temperature": 0.1,
        "timeout": 12000,
        "max_retries": settings.LLM_MAX_ATTEMPTS - 1,
        "base_url": runtime.api_base_url,
        "model_kwargs": {"response_format": {"type": "json_object"}},
    }
    thinking_payload = resolve_thinking_payload(runtime)
    if thinking_payload:
        kwargs["extra_body"] = thinking_payload
    return ChatOpenAI(**kwargs), runtime.model_name


async def main() -> None:
    args = parse_args()
    diary_ids = args.diary_ids or DEFAULT_DIARY_IDS
    output_path = Path(args.output).resolve()
    document_path = Path(__file__).resolve().parents[2] / "docs/系统设计/知识库/事件图谱分析流程实现设计-评审稿.md"
    document = document_path.read_text(encoding="utf-8")
    current_prompt = extract_prompt(document, "## 11. 当前日记关系识别系统提示词")
    historical_prompt = extract_prompt(document, "## 12. 历史关系识别系统提示词")

    diaries, user_id, person_relations = load_current_diaries(diary_ids)
    historical_events = load_historical_events(user_id, set(diary_ids))
    all_events = [event for diary in diaries for event in diary["events"]] + historical_events

    llm, relation_model_name = build_relation_llm(args.model)
    previous_result = None
    if args.resume and output_path.exists():
        previous_result = json.loads(output_path.read_text(encoding="utf-8"))

    vectors: dict[str, list[dict[str, Any]]] = {}
    if previous_result is None:
        embedding_config = get_embedding_config()
        print(f"vectorizing {len(all_events)} events", file=sys.stderr, flush=True)
        vectors = vectorize_events(all_events)
        result: dict[str, Any] = {
            "started_at": datetime.now().isoformat(),
            "design_document": str(document_path),
            "model": relation_model_name,
            "models_used": [relation_model_name],
            "embedding_model": embedding_config.model_name,
            "embedding_dimensions": embedding_config.dimensions,
            "recall_threshold": None,
            "top_per_query": args.top_per_query,
            "max_candidates": args.max_candidates,
            "historical_pool_size": len(historical_events),
            "existing_relations_available": False,
            "diaries": [],
        }
    else:
        result = previous_result
        result.pop("completed_at", None)
        models_used = list(result.get("models_used") or [result.get("model")])
        if relation_model_name not in models_used:
            models_used.append(relation_model_name)
        result["models_used"] = models_used
        result["resumed_at"] = datetime.now().isoformat()
    previous_diaries = {
        item["diary_id"]: item
        for item in (previous_result or {}).get("diaries", [])
    }
    result["diaries"] = []
    save_result(output_path, result)

    history_by_id = {event["historical_event_id"]: event for event in historical_events}
    for diary_index, diary in enumerate(diaries, start=1):
        print(f"current relations {diary_index}/{len(diaries)}: {diary['diary_date']}", file=sys.stderr, flush=True)
        current_payload = {
            "diary_date": diary["diary_date"],
            "timezone": "Asia/Shanghai",
            "person_relations": person_relations,
            "events": [
                {
                    "event_key": event["event_key"],
                    "event_order": event["event_order"],
                    "title": event["title"],
                    "body": event["body"],
                }
                for event in diary["events"]
            ],
        }
        current_events_by_key = {event["event_key"]: event for event in diary["events"]}
        old_diary_result = previous_diaries.get(diary["diary_id"], {})
        diary_result: dict[str, Any] = {
            "diary_id": diary["diary_id"],
            "diary_date": diary["diary_date"],
            "event_count": len(diary["events"]),
            "event_titles": [event["title"] for event in diary["events"]],
            "current_relation_validation": {},
            "historical_relation_validations": [],
        }
        old_current = old_diary_result.get("current_relation_validation", {})
        if args.resume and old_current.get("status") == "PASSED":
            diary_result["current_relation_validation"] = old_current
        else:
            try:
                raw_current = await invoke_json(
                    llm,
                    current_prompt,
                    current_payload,
                    step_name=f"event_relation_live_current_{diary['diary_date']}",
                    model_name=relation_model_name,
                )
                current_relations = validate_relations(raw_current, current_events_by_key, historical=False)
                diary_result["current_relation_validation"] = {
                    "status": "PASSED",
                    "model": relation_model_name,
                    "relations": [public_relation(item, current_events_by_key) for item in current_relations],
                }
            except Exception as exc:  # 试验要保留失败并继续下一样本。
                diary_result["current_relation_validation"] = {
                    "status": "FAILED",
                    "model": relation_model_name,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }

        old_history_by_key = {
            item["current_event_key"]: item
            for item in old_diary_result.get("historical_relation_validations", [])
        }
        for event_index, current_event in enumerate(diary["events"], start=1):
            print(
                f"historical relations {diary_index}/{len(diaries)} event {event_index}/{len(diary['events'])}",
                file=sys.stderr,
                flush=True,
            )
            old_validation = old_history_by_key.get(current_event["event_key"], {})
            if args.resume and old_validation.get("candidates"):
                candidates = [
                    {key: value for key, value in candidate.items() if key != "event_key"}
                    for candidate in old_validation["candidates"]
                ]
            else:
                candidates = recall_candidates(
                    current_event,
                    historical_events,
                    vectors,
                    args.top_per_query,
                    args.max_candidates,
                )
            historical_input_events: list[dict[str, Any]] = []
            historical_events_by_key: dict[str, dict[str, Any]] = {"C": current_event}
            candidate_summaries: list[dict[str, Any]] = []
            for candidate_index, candidate in enumerate(candidates, start=1):
                key = f"H{candidate_index}"
                history = history_by_id[candidate["historical_event_id"]]
                historical_events_by_key[key] = history
                historical_input_events.append({
                    "event_key": key,
                    "diary_date": history["diary_date"],
                    "title": history["title"],
                    "body": history["body"],
                })
                candidate_summaries.append({"event_key": key, **candidate})

            validation: dict[str, Any] = {
                "current_event_key": current_event["event_key"],
                "current_title": current_event["title"],
                "candidates": candidate_summaries,
            }
            if args.resume and old_validation.get("status") == "PASSED":
                validation = old_validation
            elif not candidates:
                validation.update({"status": "PASSED", "relations": []})
            else:
                historical_payload = {
                    "timezone": "Asia/Shanghai",
                    "person_relations": person_relations,
                    "current_event": {
                        "event_key": "C",
                        "diary_date": diary["diary_date"],
                        "title": current_event["title"],
                        "body": current_event["body"],
                    },
                    "historical_events": historical_input_events,
                    "existing_relations": [],
                }
                try:
                    raw_historical = await invoke_json(
                        llm,
                        historical_prompt,
                        historical_payload,
                        step_name=(
                            f"event_relation_live_historical_{diary['diary_date']}_"
                            f"{current_event['event_key']}"
                        ),
                        model_name=relation_model_name,
                    )
                    historical_relations = validate_relations(
                        raw_historical,
                        historical_events_by_key,
                        historical=True,
                    )
                    validation.update({
                        "status": "PASSED",
                        "model": relation_model_name,
                        "relations": [
                            public_relation(item, historical_events_by_key)
                            for item in historical_relations
                        ],
                    })
                except Exception as exc:
                    validation.update({
                        "status": "FAILED",
                        "model": relation_model_name,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    })
            diary_result["historical_relation_validations"].append(validation)
            save_result(output_path, result | {"diaries": result["diaries"] + [diary_result]})

        result["diaries"].append(diary_result)
        save_result(output_path, result)

    result["completed_at"] = datetime.now().isoformat()
    save_result(output_path, result)
    print(str(output_path))


if __name__ == "__main__":
    asyncio.run(main())
