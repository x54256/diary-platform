"""定期回顾任务执行与版本持久化。"""

from __future__ import annotations

import copy
import json
import logging
import re
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from config import settings
from database import SessionLocal
from models.diary import DiaryActionEventLink, DiaryActionScheduleLink
from models.review import (
    Review,
    ReviewAction,
    ReviewActionCheck,
    ReviewActionStatus,
    ReviewFeedback,
    ReviewGenerationMode,
    ReviewDailyDigest,
    ReviewDailyDigestStatus,
    ReviewTask,
    ReviewTaskStatus,
    ReviewTaskStep,
    ReviewVersion,
    ReviewVersionDependency,
    ReviewVersionType,
    ReviewSourceSet,
)
from services.task_environment import TASK_ENVIRONMENT
from services.review_ai import (
    DAILY_MATERIAL_CONTINUATION_PROMPT, DAILY_MATERIAL_PROMPT,
    ReviewAIError, actual_review_model_info, review_analysis_action, review_daily_material,
    review_week_event_organize_from_digests, validate_analysis_action_document,
)
from services.llm_metrics import estimate_prompt_tokens
from services.review_periods import ReviewPeriod
from services.review_sources import (
    ReviewSourceFreezer,
    load_source_catalog,
    previous_confirmed_actions_for_period,
)


logger = logging.getLogger("app.review_generation")
LEASE_DURATION = timedelta(minutes=10)


def _dates_between(start: date, end: date) -> list[date]:
    result: list[date] = []
    cursor = start
    while cursor <= end:
        result.append(cursor)
        cursor += timedelta(days=1)
    return result


def _document_source_ids(document: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for item in ((document.get("items", []) + document.get("matters", [])) if isinstance(document, dict) else []):
        if isinstance(item, dict):
            ids.update(str(value) for value in item.get("source_ids", []) if value)
    for domain in document.get("domains", []) if isinstance(document, dict) else []:
        for thread in domain.get("event_threads", []) if isinstance(domain, dict) else []:
            for node in thread.get("nodes", []) if isinstance(thread, dict) else []:
                ids.update(str(value) for value in node.get("source_ids", []) if value)
    return ids


def _daily_item_key() -> str:
    """生成每日事项的随机唯一 ID。"""
    return f"day-{uuid.uuid4()}"


def _assemble_daily_material_document(
    model_result: dict[str, Any], digest_date: date, events: list[dict[str, Any]], annotation_source_ids: dict[str, list[str]],
) -> dict[str, Any]:
    """将临时事件序号映射为事项级冻结来源，并生成事项键。"""
    event_by_no = {int(event["event_no"]): event for event in events}
    matters: list[dict[str, Any]] = []
    for matter in model_result["matters"]:
        source_events = [event_by_no[no] for no in matter["source_event_nos"]]
        source_ids = sorted({str(event["source_id"]) for event in source_events} | {
            annotation_id for event in source_events for annotation_id in annotation_source_ids.get(str(event["event_id"]), [])
        })
        material = {key: copy.deepcopy(value) for key, value in matter.items() if key != "source_event_nos"}
        material.update({
            "item_key": _daily_item_key(),
            "source_ids": source_ids,
            "source_event_ids": [str(event["event_id"]) for event in source_events],
        })
        matters.append(material)
    return {"digest_date": digest_date.isoformat(), "day_overview": copy.deepcopy(model_result["day_overview"]), "matters": matters}


def _weekly_fact(item: dict[str, Any]) -> str:
    values = item.get("facts_and_progress") or item.get("core_changes") or []
    return "；".join(value for value in values if isinstance(value, str))


def _assemble_week_event_document(model_result: dict[str, Any], weekly_items: list[dict[str, Any]]) -> dict[str, Any]:
    """主线与单日事项统一生成为领域内 thread；全部键由代码确定性生成。"""
    items = {str(item["item_key"]): item for item in weekly_items}
    domains: dict[str, dict[str, Any]] = {}

    def _node_source_ids(item: dict[str, Any]) -> list[str]:
        # 含 schedule_facts 的项，其日程来源 source_id 并入节点来源，使日程事实可进入分析证据白名单。
        ids = {str(source_id) for source_id in item.get("source_ids") or []}
        ids.update(
            str(fact["source_id"]) for fact in item.get("schedule_facts") or []
            if isinstance(fact, dict) and fact.get("source_id")
        )
        return sorted(ids)

    def _node_quotes(item: dict[str, Any]) -> list[str]:
        """提取事项中的原文引用（key_quotes）。"""
        quotes = item.get("key_quotes") or []
        return [str(q) for q in quotes if isinstance(q, str) and q.strip()]

    for thread in model_result.get("threads", []):
        item_keys = [str(key) for key in thread.get("member_item_keys", [])]
        span_type = "CROSS_DAY" if len(item_keys) >= 2 else "SINGLE_DAY"
        thread_key = f"thread-{uuid.uuid5(uuid.NAMESPACE_URL, '|'.join(sorted(item_keys)))}"
        narrative = thread["narrative"]
        nodes = []
        source_ids: list[str] = []
        for item_key in item_keys:
            item = items[item_key]
            node_source_ids = _node_source_ids(item)
            source_ids.extend(node_source_ids)
            nodes.append({
                "node_key": f"node-{uuid.uuid5(uuid.NAMESPACE_URL, item_key)}",
                "source_date": item["digest_date"], "change_type": "CURRENT_STATE",
                "fact": _weekly_fact(item), "source_ids": node_source_ids,
                "quotes": _node_quotes(item),
            })
        domain_code = thread["domain_code"]
        domain = domains.setdefault(domain_code, {"domain_code": domain_code, "core_focus": [], "event_threads": []})
        domain["event_threads"].append({
            "thread_key": thread_key, "title": thread["title"], "primary_domain": domain_code,
            "related_domains": [], "span_type": span_type, "narrative": narrative,
            "narrative_node_keys": [node["node_key"] for node in nodes], "continuity_status": "NEW",
            "current_status": thread["current_status"], "previous_thread_key": None,
            "prior_context_source_ids": [], "nodes": nodes, "links": [],
        })
        domain["core_focus"].append({"focus_key": f"focus-{thread_key}", "label": thread["title"], "thread_keys": [thread_key], "source_ids": sorted(set(source_ids))})
    return {"domains": list(domains.values())}


def _replay_stored_schedule_facts(daily_items: list[dict[str, Any]], event_result: dict[str, Any]) -> None:
    """resume 时原样重放事件环节落库的日程事实；旧结构无该键则保留实时重算结果。"""
    stored = event_result.get("schedule_facts_by_item") if isinstance(event_result, dict) else None
    if not isinstance(stored, dict):
        return
    for item in daily_items:
        facts = stored.get(str(item.get("item_key")))
        if facts:
            item["schedule_facts"] = copy.deepcopy(facts)
        else:
            item.pop("schedule_facts", None)


def _stable_key(kind: str, *parts: object) -> str:
    """所有内部键均由代码根据稳定输入生成，模型不能控制。"""
    seed = "|".join(str(part) for part in parts)
    return f"{kind}-{uuid.uuid5(uuid.NAMESPACE_URL, seed)}"


def _weekly_materials_for_analysis(weekly_items: list[dict[str, Any]], event_document: dict[str, Any]) -> list[dict[str, Any]]:
    """保留完整周级素材，并显式标记它们归属的主线。"""
    item_threads: dict[str, list[str]] = {}
    for domain in event_document.get("domains", []):
        for thread in domain.get("event_threads", []):
            thread_key = thread.get("thread_key")
            if not isinstance(thread_key, str):
                continue
            node_keys = {node.get("node_key") for node in thread.get("nodes", []) if isinstance(node, dict)}
            for item in weekly_items:
                item_key = str(item.get("item_key"))
                if f"node-{uuid.uuid5(uuid.NAMESPACE_URL, item_key)}" in node_keys:
                    item_threads.setdefault(item_key, []).append(thread_key)
    return [{**copy.deepcopy(item), "thread_keys": item_threads.get(str(item.get("item_key")), [])} for item in weekly_items]


def _assemble_analysis_action_document(model_result: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """将周分析/行动最小语义映射为既有持久化文档结构。"""
    domains: list[dict[str, Any]] = []
    for domain_pos, semantic_domain in enumerate(model_result.get("domains", [])):
        domain_code = semantic_domain["domain_code"]
        signals: list[dict[str, Any]] = []
        signal_keys: list[str] = []
        for signal_pos, signal in enumerate(semantic_domain.get("signals", [])):
            source_indexes = signal.get("source_indexes", [])
            source_ids = _signal_source_ids_for_assembly(signal.get("thread_keys", []), source_indexes, payload)
            key = _stable_key("signal", domain_code, signal_pos, signal["description"], *signal["thread_keys"])
            signal_keys.append(key)
            signals.append({
                "signal_key": key,
                **{name: value for name, value in copy.deepcopy(signal).items() if name != "source_indexes"},
                "source_ids": source_ids,
            })
        analyses: list[dict[str, Any]] = []
        analysis_keys: list[str] = []
        for analysis_pos, semantic_analysis in enumerate(semantic_domain.get("analyses", [])):
            key = _stable_key("analysis", domain_code, analysis_pos, semantic_analysis["angle_code"], semantic_analysis["claim"])
            analysis_keys.append(key)
            analysis = copy.deepcopy(semantic_analysis)
            signal_indexes = analysis.pop("signal_indexes")
            analyses.append({
                "analysis_key": key,
                "primary_domain": domain_code,
                "signal_keys": [signal_keys[index] for index in signal_indexes],
                **analysis,
            })
        actions: list[dict[str, Any]] = []
        for action_pos, semantic_action in enumerate(semantic_domain.get("actions", [])):
            action = copy.deepcopy(semantic_action)
            analysis_indexes = action.pop("basis_analysis_indexes")
            actions.append({
                "action_key": _stable_key("action", domain_code, action_pos, action["content"]),
                "primary_domain": domain_code,
                "basis_analysis_keys": [analysis_keys[index] for index in analysis_indexes],
                **action,
            })
        domains.append({
            "domain_code": domain_code,
            "signals": signals,
            "analysis_items": analyses,
            "action_candidates": actions,
        })
    return {"domains": domains, "previous_action_checks": copy.deepcopy(model_result.get("previous_action_checks", []))}


def _signal_source_ids_for_assembly(thread_keys: list[str], indexes: list[int], payload: dict[str, Any]) -> list[str]:
    sources = {
        source["source_id"]: source for source in payload.get("source_catalog", [])
        if isinstance(source, dict) and isinstance(source.get("source_id"), str)
    }
    thread_sources: dict[str, set[str]] = {}
    for domain in payload.get("event_document", {}).get("domains", []):
        if not isinstance(domain, dict):
            continue
        for thread in domain.get("event_threads", []):
            if not isinstance(thread, dict) or not isinstance(thread.get("thread_key"), str):
                continue
            thread_sources[thread["thread_key"]] = {
                source_id for node in thread.get("nodes", []) if isinstance(node, dict)
                for source_id in node.get("source_ids", []) if isinstance(source_id, str)
            }
    available_ids = list(dict.fromkeys(
        source_id for thread_key in sorted(set(thread_keys))
        for source_id in sorted(thread_sources.get(thread_key, set()))
        if sources.get(source_id, {}).get("period_role") == "CURRENT"
    ))
    return list(dict.fromkeys(available_ids[index] for index in indexes))


def _daily_candidates(candidates: list[dict[str, Any]], source_ids: set[str]) -> list[dict[str, Any]]:
    return [item for item in candidates if source_ids.intersection(str(value) for value in item.get("evidence_source_ids", []))]


def _daily_material_input(day_sources: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    """构造每日模型输入；日程和未评定事件保持在每日模型之外。"""
    annotations: dict[str, list[str]] = {}
    event_sources: list[dict[str, Any]] = []
    for source in day_sources:
        metadata = source.get("metadata") or {}
        event_id = metadata.get("event_id")
        if metadata.get("annotation_id") and event_id:
            annotations.setdefault(str(event_id), []).append(str(source["source_id"]))
            continue
        if (
            source.get("source_type") == "DIARY_EVENT"
            and event_id
            and not metadata.get("annotation_id")
            and metadata.get("effective_importance") in {"HIGH", "MEDIUM"}
        ):
            event_sources.append(source)
    event_sources.sort(key=lambda source: ((source.get("metadata") or {}).get("sort_order", 0), str(source["source_id"])))
    events = [{
        "event_no": index,
        "source_id": str(source["source_id"]),
        "event_id": str((source.get("metadata") or {})["event_id"]),
        "title": str((source.get("metadata") or {}).get("title") or "未命名事件"),
        "body": list((source.get("metadata") or {}).get("body") or []),
        "feeling": list((source.get("metadata") or {}).get("feeling") or []),
        "reflection": list((source.get("metadata") or {}).get("reflection") or []),
        "related_user_notes": [
            str(note_source.get("content") or "") for note_source in day_sources
            if str(note_source.get("source_id")) in annotations.get(str((source.get("metadata") or {})["event_id"]), [])
        ],
    } for index, source in enumerate(event_sources, start=1)]
    return events, annotations


def _daily_material_model_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{key: value for key, value in event.items() if key not in {"source_id", "event_id"}} for event in events]


def _daily_material_source_event_nos(document: dict[str, Any] | None) -> set[int]:
    if not isinstance(document, dict):
        return set()
    return {
        value for matter in document.get("matters", []) if isinstance(matter, dict)
        for value in matter.get("source_event_nos", []) if isinstance(value, int)
    }


def _next_daily_material_batch(
    digest_date: date, events: list[dict[str, Any]], start: int, previous_daily_material: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], int]:
    """在输入 token 预算内装入尽可能多的完整事件。"""
    batch: list[dict[str, Any]] = []
    prompt = DAILY_MATERIAL_CONTINUATION_PROMPT if previous_daily_material is not None else DAILY_MATERIAL_PROMPT
    while start + len(batch) < len(events):
        candidate = [*batch, events[start + len(batch)]]
        payload: dict[str, Any] = {"date": digest_date.isoformat(), "events": candidate}
        if previous_daily_material is not None:
            payload["previous_daily_material"] = previous_daily_material
        token_count = estimate_prompt_tokens(None, prompt, json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        if token_count > settings.REVIEW_DAILY_MATERIAL_INPUT_TOKEN_BUDGET:
            if not batch:
                raise ReviewAIError(
                    f"单个事件超过每日素材输入 token 预算: event_no={events[start].get('event_no')}"
                )
            break
        batch = candidate
    return batch, start + len(batch)


def _compact_week_catalog(source_catalog: list[dict[str, Any]], source_ids: set[str]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for source in source_catalog:
        is_schedule = source.get("source_type") == "SCHEDULE_OCCURRENCE"
        if str(source.get("source_id")) not in source_ids and not is_schedule:
            continue
        compact = copy.deepcopy(source)
        compact["content"] = (
            "该日程事实已按主题聚合；详见 weekly_items。"
            if is_schedule else "该原始证据已被每日素材引用；详见对应每日事项。"
        )
        result.append(compact)
    return result


_UUID_TEXT = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
# 发给模型的事项保留键；其余 UUID 字段一律剥离，组装时用内存中的完整 items 映射。
_MODEL_ITEM_UUID_KEYS = {"item_key", "source_ids", "source_event_ids"}


def _model_ready_item(item: dict[str, Any]) -> dict[str, Any]:
    def _slim_dict(mapping: dict[str, Any]) -> dict[str, Any]:
        return {
            inner_key: copy.deepcopy(inner_value)
            for inner_key, inner_value in mapping.items()
            if not (isinstance(inner_value, str) and _UUID_TEXT.match(inner_value))
        }

    slim: dict[str, Any] = {}
    for key, value in item.items():
        if key in _MODEL_ITEM_UUID_KEYS:
            slim[key] = copy.deepcopy(value)
            continue
        if isinstance(value, str) and _UUID_TEXT.match(value):
            continue
        if isinstance(value, list):
            if value and all(isinstance(entry, str) and _UUID_TEXT.match(entry) for entry in value):
                continue
            slim[key] = [
                _slim_dict(entry) if isinstance(entry, dict) else copy.deepcopy(entry)
                for entry in value
            ]
            continue
        if isinstance(value, dict):
            slim[key] = _slim_dict(value)
            continue
        slim[key] = copy.deepcopy(value)
    return slim


def _item_schedule_facts(
    source_catalog: list[dict[str, Any]],
    db: Session,
    user_id,
    event_id_to_items: dict[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    """经事件→行动项→有效日程关联，把快照中的日程执行事实精确挂到每日事项。"""
    event_ids: list[uuid.UUID] = []
    for event_id in event_id_to_items:
        try:
            event_ids.append(uuid.UUID(str(event_id)))
        except (TypeError, ValueError):
            continue
    if not event_ids:
        return {}
    event_links = (
        db.query(DiaryActionEventLink)
        .filter(
            DiaryActionEventLink.user_id == user_id,
            DiaryActionEventLink.diary_event_id.in_(event_ids),
        )
        .all()
    )
    if not event_links:
        return {}
    actions_by_event: dict[str, set[uuid.UUID]] = defaultdict(set)
    for link in event_links:
        actions_by_event[str(link.diary_event_id)].add(link.action_item_id)
    schedule_links = (
        db.query(DiaryActionScheduleLink)
        .filter(
            DiaryActionScheduleLink.user_id == user_id,
            DiaryActionScheduleLink.action_item_id.in_({action_id for ids in actions_by_event.values() for action_id in ids}),
            DiaryActionScheduleLink.unlinked_at.is_(None),
            DiaryActionScheduleLink.schedule_task_id.isnot(None),
        )
        .all()
    )
    tasks_by_action: dict[uuid.UUID, set[str]] = defaultdict(set)
    for link in schedule_links:
        tasks_by_action[link.action_item_id].add(str(link.schedule_task_id))
    occurrences_by_task: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for source in source_catalog:
        if source.get("source_type") != "SCHEDULE_OCCURRENCE" or source.get("period_role") != "CURRENT":
            continue
        metadata = source.get("metadata") or {}
        if metadata.get("status") == "deleted" or not metadata.get("task_id"):
            continue
        occurrences_by_task[str(metadata["task_id"])].append(source)
    facts_by_item: dict[str, list[dict[str, Any]]] = {}
    for items in event_id_to_items.values():
        for item in items:
            item_key = str(item.get("item_key") or "")
            if not item_key or item_key in facts_by_item:
                continue
            task_ids: set[str] = set()
            for event_id in item.get("source_event_ids") or []:
                for action_id in actions_by_event.get(str(event_id), ()):
                    task_ids.update(tasks_by_action.get(action_id, ()))
            seen: set[str] = set()
            facts: list[dict[str, Any]] = []
            for task_id in task_ids:
                for occurrence in occurrences_by_task.get(task_id, []):
                    source_id = str(occurrence.get("source_id"))
                    if source_id in seen:
                        continue
                    seen.add(source_id)
                    metadata = occurrence.get("metadata") or {}
                    facts.append({
                        "date": metadata.get("scheduled_date") or occurrence.get("source_date"),
                        "task_title": str(metadata.get("title") or "").strip(),
                        "status_text": "已标记完成" if metadata.get("status") == "completed" else "截至回顾生成时未标记完成",
                        "execution_note": str(metadata.get("execution_note") or "")[:200],
                        "source_id": source_id,
                    })
            if facts:
                facts.sort(key=lambda fact: (fact["date"] or "", fact["task_title"]))
                facts_by_item[item_key] = facts
    return facts_by_item


class ReviewGenerationError(RuntimeError):
    def __init__(self, message: str, code: str = "GENERATION_FAILED"):
        super().__init__(message)
        self.code = code


def _safe_task_error(exc: Exception) -> str:
    if isinstance(exc, ReviewGenerationError):
        return str(exc)
    if isinstance(exc, ReviewAIError):
        return "AI 生成结果未通过结构检查，请重试；若持续失败，请检查回顾模型配置。"
    return "回顾生成未完成，请重试；若持续失败，请联系管理员查看服务日志。"


def _task_owned(db: Session, task_id: uuid.UUID, run_token: uuid.UUID) -> ReviewTask:
    task = db.query(ReviewTask).filter(
        ReviewTask.id == task_id, ReviewTask.environment == TASK_ENVIRONMENT,
        ReviewTask.run_token == run_token,
        ReviewTask.status == ReviewTaskStatus.RUNNING.value,
    ).first()
    if not task:
        raise ReviewGenerationError("任务租约已经失效", "LEASE_LOST")
    return task


def _advance(
    db: Session,
    task_id: uuid.UUID,
    run_token: uuid.UUID,
    step: str,
    **values: Any,
) -> ReviewTask:
    task = _task_owned(db, task_id, run_token)
    task.current_step = step
    task.lease_until = datetime.utcnow() + LEASE_DURATION
    for key, value in values.items():
        setattr(task, key, value)
    db.commit()
    return task


def _analysis_candidates_from_version(db: Session, version: ReviewVersion) -> list[dict[str, Any]]:
    feedback = {str(item.analysis_item_id): item for item in version.feedback}
    result: list[dict[str, Any]] = []
    for domain in (version.analysis_document or {}).get("domains", []):
        for item in domain.get("analysis_items", []):
            item_id = str(item.get("analysis_item_id") or "")
            note = feedback.get(item_id)
            if note and note.is_inherited:
                preference = "UNCONFIRMED"
            elif note and note.rating and note.rating >= 4:
                preference = "PREFERRED_CANDIDATE"
            elif note and note.rating and note.rating <= 2:
                preference = "PROHIBITED"
            else:
                preference = "NEUTRAL"
            result.append({
                "analysis_id": item_id,
                "analysis_type": item.get("angle_code"),
                "content": item.get("claim"),
                "feedback_usage": preference,
                "evidence_source_ids": list(item.get("supporting_source_ids") or []),
                "feedbacks": ([{
                    "feedback_id": str(note.id),
                    "rating": note.rating,
                    "comment": note.comment,
                }] if note else []),
            })
    return result


def _actions_payload(actions: list[ReviewAction]) -> list[dict[str, Any]]:
    return [{
        "action_id": str(item.id),
        "primary_domain": item.primary_domain,
        "content": item.edited_content or item.content,
        "status": item.status,
    } for item in actions]


def _summary(event_document: dict[str, Any]) -> str:
    labels: list[str] = []
    for domain in event_document.get("domains", []):
        focuses = domain.get("core_focus") or []
        if isinstance(focuses, dict):
            focuses = [focuses]
        for focus in focuses:
            label = str(focus.get("label") or "").strip()
            if label:
                labels.append(label)
            if len(labels) >= 3:
                break
        if len(labels) >= 3:
            break
    if not labels:
        for domain in event_document.get("domains", []):
            for thread in domain.get("event_threads", []):
                title = str(thread.get("title") or "").strip()
                if title:
                    labels.append(title)
                if len(labels) >= 3:
                    break
            if len(labels) >= 3:
                break
    return "、".join(labels)[:120]


def _prepare_event_document(document: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(document)
    for domain in result.get("domains", []):
        for thread in domain.get("event_threads", []):
            thread.setdefault("thread_id", str(uuid.uuid4()))
    return result


def _derived_metrics(event_document: dict[str, Any], source_catalog: list[dict[str, Any]], review_type: str) -> dict[str, Any]:
    """根据事件层来源计算可供模型使用的重复/趋势门槛。"""
    sources = {str(item.get("source_id")): item for item in source_catalog}
    by_thread: dict[str, dict[str, Any]] = {}
    for domain in event_document.get("domains", []):
        for thread in domain.get("event_threads", []):
            source_ids = set(thread.get("prior_context_source_ids") or [])
            for node in thread.get("nodes") or []:
                source_ids.update(node.get("source_ids") or [])
            current = [sources[source_id] for source_id in source_ids if source_id in sources and sources[source_id].get("period_role") == "CURRENT"]
            dates = {item.get("source_date") for item in current if item.get("source_date")}
            week_keys = set()
            for item in current:
                source_date = item.get("source_date")
                if isinstance(source_date, str):
                    try:
                        week_keys.add(datetime.fromisoformat(source_date).date().isocalendar()[:2])
                    except ValueError:
                        pass
            by_thread[thread.get("thread_key")] = {
                "current_root_fact_count": len({item.get("root_fact_id") for item in current}),
                "current_date_count": len(dates),
                "current_week_count": len(week_keys),
                "trend_eligible": review_type == "MONTH" and len(week_keys) >= 3,
            }
    return {"by_thread_key": by_thread}


def _prepare_analysis_document(document: dict[str, Any]) -> tuple[dict[str, Any], dict[str, uuid.UUID]]:
    result = {"domains": []}
    key_to_id: dict[str, uuid.UUID] = {}
    for domain in document.get("domains", []):
        saved = {
            "domain_code": domain.get("domain_code"),
            "signals": copy.deepcopy(domain.get("signals") or []),
            "analysis_items": [],
        }
        for item in domain.get("analysis_items", []):
            copied = copy.deepcopy(item)
            item_id = uuid.uuid4()
            copied["analysis_item_id"] = str(item_id)
            key_to_id[str(copied.get("analysis_key"))] = item_id
            saved["analysis_items"].append(copied)
        if saved["signals"] or saved["analysis_items"]:
            result["domains"].append(saved)
    return result, key_to_id


def _persist_feedback_inheritance(
    db: Session,
    version: ReviewVersion,
    analysis_document: dict[str, Any],
    base_version: ReviewVersion | None,
) -> None:
    if not base_version:
        return
    old_feedback = {str(item.analysis_item_id): item for item in base_version.feedback}
    for domain in analysis_document.get("domains", []):
        for item in domain.get("analysis_items", []):
            source_id = str(item.get("source_analysis_item_id") or "")
            source = old_feedback.get(source_id)
            if not source:
                continue
            db.add(ReviewFeedback(
                version_id=version.id,
                user_id=version.user_id,
                analysis_item_id=uuid.UUID(str(item["analysis_item_id"])),
                angle_code=item.get("angle_code") or source.angle_code,
                rating=source.rating,
                comment=source.comment,
                is_inherited=True,
                source_feedback_id=source.id,
            ))


def _persist_actions(
    db: Session,
    version: ReviewVersion,
    analysis_result: dict[str, Any],
    analysis_ids: dict[str, uuid.UUID],
    base_actions: list[ReviewAction],
) -> None:
    old = {str(item.id): item for item in base_actions}
    mapped: set[str] = set()
    for domain in analysis_result.get("domains", []):
        for candidate in domain.get("action_candidates", []):
            source_id = str(candidate.get("source_action_id") or "")
            source = old.get(source_id)
            if source:
                mapped.add(source_id)
            basis_ids = [
                str(analysis_ids[key])
                for key in candidate.get("basis_analysis_keys", [])
                if key in analysis_ids
            ]
            db.add(ReviewAction(
                version_id=version.id,
                user_id=version.user_id,
                primary_domain=candidate.get("primary_domain") or domain.get("domain_code"),
                related_domains=candidate.get("related_domains") or [],
                content=candidate.get("content") or "",
                edited_content=source.edited_content if source else None,
                rationale=candidate.get("rationale") or (source.rationale if source else None),
                status=source.status if source else ReviewActionStatus.CANDIDATE.value,
                source_action_id=source.id if source else None,
                is_inherited=bool(source),
                basis_analysis_ids=basis_ids,
                basis_source_ids=candidate.get("basis_source_ids") or [],
                verification_rule=candidate.get("verification") or {},
            ))
    for source_id, source in old.items():
        if source_id in mapped or source.status != ReviewActionStatus.CONFIRMED.value:
            continue
        db.add(ReviewAction(
            version_id=version.id,
            user_id=version.user_id,
            primary_domain=source.primary_domain,
            related_domains=source.related_domains or [],
            content=source.content,
            edited_content=source.edited_content,
            rationale=source.rationale,
            status=source.status,
            source_action_id=source.id,
            is_inherited=True,
            basis_analysis_ids=source.basis_analysis_ids or [],
            basis_source_ids=source.basis_source_ids or [],
            verification_rule=source.verification_rule or {},
        ))


def _persist_action_checks(
    db: Session,
    version: ReviewVersion,
    analysis_result: dict[str, Any],
) -> None:
    for item in analysis_result.get("previous_action_checks", []):
        try:
            previous_action_id = uuid.UUID(str(item.get("previous_action_id")))
        except (TypeError, ValueError):
            continue
        db.add(ReviewActionCheck(
            version_id=version.id,
            user_id=version.user_id,
            previous_action_id=previous_action_id,
            check_status=item.get("check_status") or "NOT_ASSESSABLE",
            explanation=item.get("explanation") or "当前记录中没有找到足够的落实证据。",
            evidence_source_ids=item.get("evidence_source_ids") or [],
        ))


def _persist_dependencies(
    db: Session,
    version: ReviewVersion,
    dependencies: list[dict[str, Any]],
) -> None:
    for item in dependencies:
        db.add(ReviewVersionDependency(
            version_id=version.id,
            dependency_type=item["dependency_type"],
            dependency_review_id=item.get("dependency_review_id"),
            dependency_version_id=item.get("dependency_version_id"),
            period_start=item["period_start"],
            period_end=item["period_end"],
            status=item["status"],
            context_only=bool(item.get("context_only")),
        ))


def _copy_dependencies(db: Session, base: ReviewVersion) -> list[dict[str, Any]]:
    return [{
        "dependency_type": item.dependency_type,
        "dependency_review_id": item.dependency_review_id,
        "dependency_version_id": item.dependency_version_id,
        "period_start": item.period_start,
        "period_end": item.period_end,
        "status": item.status,
        "context_only": item.context_only,
    } for item in base.dependencies]


async def execute_review_task(
    task_id: uuid.UUID, run_token: uuid.UUID, *, stop_after: str | None = None,
) -> None:
    """执行回顾任务；stop_after 仅供 LangGraph 在已落库节点后写 checkpoint。"""
    db = SessionLocal()
    try:
        task = _task_owned(db, task_id, run_token)
        review = db.query(Review).filter(Review.id == task.review_id).first()
        if not review:
            raise ReviewGenerationError("回顾周期不存在", "REVIEW_NOT_FOUND")
        period = ReviewPeriod(review.review_type, review.period_start, review.period_end)
        base_version = (
            db.query(ReviewVersion).filter(ReviewVersion.id == task.base_version_id).first()
            if task.base_version_id else None
        )
        event_model_info = base_version.event_model_info if base_version else None
        analysis_model_info = None
        weekly_materials: list[dict[str, Any]] = []

        if task.generation_mode == ReviewGenerationMode.FULL.value:
            source_set = (
                db.query(ReviewSourceSet).filter(ReviewSourceSet.id == task.source_set_id).first()
                if task.source_snapshot_ready and task.source_set_id else None
            )
            frozen_context = source_set.input_snapshot if source_set and source_set.input_snapshot else None
            if not frozen_context and isinstance(task.analysis_result, dict):
                frozen_context = task.analysis_result.get("_frozen_context")
            if frozen_context:
                source_catalog = load_source_catalog(db, task.source_set_id)
                existing_candidates = frozen_context.get("existing_analysis_candidates") or []
                previous_actions = frozen_context.get("previous_confirmed_actions") or []
                lower_review_actions = frozen_context.get("lower_review_actions") or []
                dependencies = frozen_context.get("dependencies") or []
                for item in dependencies:
                    if isinstance(item.get("period_start"), str):
                        item["period_start"] = datetime.fromisoformat(item["period_start"]).date()
                    if isinstance(item.get("period_end"), str):
                        item["period_end"] = datetime.fromisoformat(item["period_end"]).date()
                    for key in ("dependency_review_id", "dependency_version_id"):
                        if item.get(key) and isinstance(item[key], str):
                            item[key] = uuid.UUID(item[key])
                missing_periods = frozen_context.get("missing_periods") or []
            else:
                task.freeze_attempts += 1
                _advance(db, task_id, run_token, ReviewTaskStep.FREEZE_SOURCES.value)
                frozen = ReviewSourceFreezer(db, task.user_id, period, base_version=base_version).freeze()
                task = _task_owned(db, task_id, run_token)
                task.source_set_id = frozen.source_set.id
                task.source_snapshot_ready = True
                source_catalog = frozen.source_catalog
                existing_candidates = frozen.existing_analysis_candidates
                previous_actions = frozen.previous_confirmed_actions
                lower_review_actions = frozen.lower_review_actions
                dependencies = frozen.dependencies
                missing_periods = frozen.missing_periods
                task.analysis_result = {
                    "_frozen_context": {
                        "existing_analysis_candidates": existing_candidates,
                        "previous_confirmed_actions": previous_actions,
                        "lower_review_actions": lower_review_actions,
                        "dependencies": [{
                            **item,
                            "period_start": item["period_start"].isoformat(),
                            "period_end": item["period_end"].isoformat(),
                            "dependency_review_id": str(item["dependency_review_id"])
                            if item.get("dependency_review_id") else None,
                            "dependency_version_id": str(item["dependency_version_id"])
                            if item.get("dependency_version_id") else None,
                        } for item in dependencies],
                        "missing_periods": missing_periods,
                    }
                }
                db.commit()
            if stop_after == ReviewTaskStep.FREEZE_SOURCES.value:
                return
            if not any(item.get("period_role") == "CURRENT" for item in source_catalog):
                task = _task_owned(db, task_id, run_token)
                task.status = ReviewTaskStatus.SKIPPED_NO_DATA.value
                task.completed_at = datetime.utcnow()
                task.error_code = None
                task.error_message = "这个周期没有可用于回顾的记录"
                db.commit()
                return
            if not (isinstance(task.event_result, dict) and "domains" in task.event_result):
                task.event_attempts += 1
            _advance(db, task_id, run_token, ReviewTaskStep.EVENT_ORGANIZE.value)
            daily_rows: list[ReviewDailyDigest] = []
            all_daily_source_ids: set[str] = set()
            for digest_date in _dates_between(review.period_start, review.period_end):
                day_sources = [
                    item for item in source_catalog
                    if item.get("period_role") == "CURRENT" and item.get("source_date") == digest_date.isoformat()
                ]
                daily_events, annotation_source_ids = _daily_material_input(day_sources)
                row = db.query(ReviewDailyDigest).filter(
                    ReviewDailyDigest.review_task_id == task.id,
                    ReviewDailyDigest.digest_date == digest_date,
                ).first()
                if not row:
                    row = ReviewDailyDigest(review_task_id=task.id, source_set_id=task.source_set_id, digest_date=digest_date)
                    db.add(row)
                    db.flush()
                if row.status == ReviewDailyDigestStatus.READY.value:
                    ids = _document_source_ids(row.material_document or {})
                    all_daily_source_ids.update(ids)
                    daily_rows.append(row)
                    continue
                if not daily_events:
                    row.status = ReviewDailyDigestStatus.EMPTY.value
                    daily_rows.append(row)
                    continue
                model_events = _daily_material_model_events(daily_events)
                # 模型调用期间不持有数据库事务，避免长请求占满连接池。
                db.commit()
                daily_result: dict[str, Any] | None = None
                batch_start = 0
                required_source_event_nos: set[int] = set()
                try:
                    while batch_start < len(model_events):
                        batch, next_start = _next_daily_material_batch(
                            digest_date, model_events, batch_start, daily_result,
                        )
                        daily_result = await review_daily_material(
                            {"date": digest_date.isoformat(), "events": batch},
                            previous_daily_material=daily_result,
                            validation_payload={
                                "date": digest_date.isoformat(),
                                "events": model_events,
                                "required_source_event_nos": sorted(required_source_event_nos),
                            },
                            review_task_id=str(task_id), max_attempts=settings.LLM_MAX_ATTEMPTS,
                        )
                        required_source_event_nos.update(_daily_material_source_event_nos(daily_result))
                        batch_start = next_start
                except ReviewAIError:
                    row.status = ReviewDailyDigestStatus.FAILED.value
                    db.commit()
                    raise
                assert daily_result is not None
                row.material_document = _assemble_daily_material_document(daily_result, digest_date, daily_events, annotation_source_ids)
                row.model_info = actual_review_model_info()
                row.status = ReviewDailyDigestStatus.READY.value
                ids = _document_source_ids(row.material_document)
                all_daily_source_ids.update(ids)
                daily_rows.append(row)
                db.commit()
            daily_items = [
                {**item, "digest_date": row.digest_date.isoformat(), "item_type": "DAILY_MATTER"}
                for row in daily_rows if row.status == ReviewDailyDigestStatus.READY.value
                for item in (row.material_document or {}).get("matters", [])
            ]
            if not daily_items:
                task = _task_owned(db, task_id, run_token)
                task.status = ReviewTaskStatus.SKIPPED_NO_DATA.value
                task.completed_at = datetime.utcnow()
                db.commit()
                return
            event_id_to_items: dict[str, list[dict[str, Any]]] = {}
            for item in daily_items:
                for event_id in item.get("source_event_ids") or []:
                    event_id_to_items.setdefault(str(event_id), []).append(item)
            facts_by_item = _item_schedule_facts(source_catalog, db, task.user_id, event_id_to_items)
            for item in daily_items:
                facts = facts_by_item.get(str(item.get("item_key")))
                if facts:
                    item["schedule_facts"] = facts
            weekly_items = daily_items
            week_catalog = _compact_week_catalog(source_catalog, all_daily_source_ids)
            # day_summaries = 每个 READY 每日素材的 day_overview，仅帮模型把握全周基调；叙事内容仍以 weekly_items 为准。
            day_summaries = [
                {
                    "digest_date": row.digest_date.isoformat(),
                    "main_changes": list(((row.material_document or {}).get("day_overview") or {}).get("main_changes") or []),
                    "overall_state": list(((row.material_document or {}).get("day_overview") or {}).get("overall_state") or []),
                }
                for row in daily_rows if row.status == ReviewDailyDigestStatus.READY.value
            ]
            event_payload = {
                "review": {"generation_mode": "FULL", "review_type": review.review_type, "period_start": review.period_start.isoformat(), "period_end": review.period_end.isoformat()},
                "day_summaries": day_summaries,
                "weekly_items": [_model_ready_item(item) for item in weekly_items],
            }
            if isinstance(task.event_result, dict) and "domains" in task.event_result:
                # 业务表中的周事件已通过组装与校验；恢复时绝不再次调用周模型。
                stored_result = copy.deepcopy(task.event_result)
                # 重放事件环节落库的日程事实，避免重试前日程状态变化导致素材与叙事矛盾；旧结构无该键则保留实时重算。
                _replay_stored_schedule_facts(daily_items, stored_result)
                stored_result.pop("schedule_facts_by_item", None)
                event_document = stored_result
            else:
                weekly_semantics = await review_week_event_organize_from_digests(event_payload, review_task_id=str(task_id), max_attempts=settings.LLM_MAX_ATTEMPTS)
                event_document = _assemble_week_event_document(weekly_semantics, weekly_items)
                event_model_info = actual_review_model_info()
                task = _task_owned(db, task_id, run_token)
                task.event_result = {**event_document, "schedule_facts_by_item": facts_by_item}
                db.commit()
            source_catalog = week_catalog
            weekly_materials = _weekly_materials_for_analysis(weekly_items, event_document)
            if stop_after == ReviewTaskStep.EVENT_ORGANIZE.value:
                return
            # 分析环节已关闭，直接使用空分析结果
            analysis_result = {"domains": []}
            missing_periods = []
            dependencies = []
            analysis_model_info = None
            task = _advance(db, task_id, run_token, ReviewTaskStep.PERSIST_VERSION.value)
            db.commit()
        else:
            if not base_version or not base_version.analysis_stale:
                raise ReviewGenerationError("只能基于分析已过期的事件编辑版本更新分析", "INVALID_BASE_VERSION")
            _advance(db, task_id, run_token, ReviewTaskStep.LOAD_BASE_EVENT.value)
            task = _task_owned(db, task_id, run_token)
            task.source_set_id = base_version.source_set_id
            task.source_snapshot_ready = True
            db.commit()
            source_catalog = load_source_catalog(db, base_version.source_set_id)
            existing_candidates = _analysis_candidates_from_version(db, base_version)
            previous_actions = previous_confirmed_actions_for_period(db, task.user_id, period)
            lower_review_actions = []
            dependencies = _copy_dependencies(db, base_version)
            missing_periods = copy.deepcopy(base_version.missing_periods or [])
            event_document = copy.deepcopy(base_version.event_document)
            if stop_after == ReviewTaskStep.FREEZE_SOURCES.value:
                return

        base_actions = list(base_version.actions) if base_version else []
        if task.generation_mode == ReviewGenerationMode.ANALYSIS_ONLY.value:
            task = _advance(db, task_id, run_token, ReviewTaskStep.ANALYSIS_ACTION.value)
            if not (isinstance(task.analysis_result, dict) and "domains" in task.analysis_result):
                task.analysis_attempts += 1
            db.commit()
            analysis_payload = {
                "review": {
                    "generation_mode": task.generation_mode,
                    "review_type": review.review_type,
                    "period_start": review.period_start.isoformat(),
                    "period_end": review.period_end.isoformat(),
                },
                "source_catalog": source_catalog,
                "event_document": event_document,
                "weekly_materials": weekly_materials,
                "existing_analysis_candidates": existing_candidates,
                "base_version_actions": _actions_payload(base_actions),
                "previous_confirmed_actions": previous_actions,
                "lower_review_actions": lower_review_actions,
                "derived_metrics": _derived_metrics(event_document, source_catalog, review.review_type),
                "missing_periods": missing_periods,
            }
            if isinstance(task.analysis_result, dict) and "domains" in task.analysis_result:
                analysis_result = copy.deepcopy(task.analysis_result)
                validate_analysis_action_document(analysis_result, analysis_payload)
            else:
                analysis_semantics = await review_analysis_action(
                    analysis_payload,
                    review_task_id=str(task_id),
                    max_attempts=settings.LLM_MAX_ATTEMPTS,
                )
                analysis_result = _assemble_analysis_action_document(analysis_semantics, analysis_payload)
                validate_analysis_action_document(analysis_result, analysis_payload)
                analysis_model_info = actual_review_model_info()
                task = _task_owned(db, task_id, run_token)
                task.analysis_result = analysis_result
                db.commit()
            if stop_after == ReviewTaskStep.ANALYSIS_ACTION.value:
                return

        _advance(db, task_id, run_token, ReviewTaskStep.PERSIST_VERSION.value)
        review = db.query(Review).filter(Review.id == task.review_id).with_for_update().one()
        next_version = (db.query(func.max(ReviewVersion.version_no)).filter(
            ReviewVersion.review_id == review.id
        ).scalar() or 0) + 1
        superseded = bool(task.base_version_id and review.current_version_id != task.base_version_id)
        prepared_event = _prepare_event_document(event_document)
        if task.generation_mode == ReviewGenerationMode.ANALYSIS_ONLY.value:
            # 用户编辑后的事实层必须逐字节保持，仅允许预先已经存在的 thread_id。
            prepared_event = copy.deepcopy(event_document)
        prepared_analysis, analysis_ids = _prepare_analysis_document(analysis_result)
        version = ReviewVersion(
            review_id=review.id,
            user_id=review.user_id,
            version_no=next_version,
            version_type=(
                ReviewVersionType.ANALYSIS_UPDATED.value
                if task.generation_mode == ReviewGenerationMode.ANALYSIS_ONLY.value
                else ReviewVersionType.REGENERATED.value if task.base_version_id else ReviewVersionType.GENERATED.value
            ),
            base_version_id=task.base_version_id,
            source_set_id=task.source_set_id,
            event_document=prepared_event,
            analysis_document=prepared_analysis,
            summary=_summary(prepared_event),
            analysis_stale=False,
            superseded_at_creation=superseded,
            missing_periods=missing_periods,
            event_model_info=event_model_info,
            analysis_model_info=analysis_model_info,
        )
        db.add(version)
        db.flush()
        if task.generation_mode == ReviewGenerationMode.FULL.value:
            db.query(ReviewDailyDigest).filter(
                ReviewDailyDigest.review_task_id == task.id,
            ).update({ReviewDailyDigest.review_version_id: version.id}, synchronize_session=False)
        _persist_feedback_inheritance(db, version, prepared_analysis, base_version)
        _persist_actions(db, version, analysis_result, analysis_ids, base_actions)
        _persist_action_checks(db, version, analysis_result)
        _persist_dependencies(db, version, dependencies)
        if not superseded:
            review.current_version_id = version.id
            review.is_unread = task.trigger_type == "AUTO"
        task = _task_owned(db, task_id, run_token)
        task.result_version_id = version.id
        task.status = ReviewTaskStatus.SUCCEEDED.value
        task.completed_at = datetime.utcnow()
        task.lease_until = None
        db.commit()
    except Exception as exc:
        db.rollback()
        try:
            task = db.query(ReviewTask).filter(
                ReviewTask.id == task_id, ReviewTask.environment == TASK_ENVIRONMENT,
                ReviewTask.run_token == run_token,
            ).first()
            if task:
                task.status = ReviewTaskStatus.FAILED.value
                task.error_code = getattr(exc, "code", "GENERATION_FAILED")
                task.error_message = _safe_task_error(exc)
                task.completed_at = datetime.utcnow()
                task.lease_until = None
                db.commit()
        except Exception:
            db.rollback()
        logger.exception("回顾任务执行失败 task_id=%s", task_id)
    finally:
        db.close()
