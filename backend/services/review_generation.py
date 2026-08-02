"""定期回顾任务执行与版本持久化。"""

from __future__ import annotations

import copy
import logging
import uuid
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from config import settings
from database import SessionLocal
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
from models.diary import DiaryEvent
from services.review_ai import (
    ReviewAIError, actual_review_model_info, review_analysis_action, review_daily_analysis_digest,
    review_daily_event_digest, review_week_event_organize_from_digests, validate_analysis_action_document,
)
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
    for item in document.get("items", []) if isinstance(document, dict) else []:
        if isinstance(item, dict):
            ids.update(str(value) for value in item.get("source_ids", []) if value)
    for domain in document.get("domains", []) if isinstance(document, dict) else []:
        for thread in domain.get("event_threads", []) if isinstance(domain, dict) else []:
            for node in thread.get("nodes", []) if isinstance(thread, dict) else []:
                ids.update(str(value) for value in node.get("source_ids", []) if value)
    return ids


def _daily_item_key(digest_date: date, source_ids: list[str]) -> str:
    """由日期和已冻结来源确定性生成每日事项 ID。"""
    seed = f"{digest_date.isoformat()}:{','.join(sorted(source_ids))}"
    return f"day-{uuid.uuid5(uuid.NAMESPACE_URL, seed)}"


def _assemble_daily_event_document(
    model_result: dict[str, Any], digest_date: date, sources: list[dict[str, Any]],
) -> dict[str, Any]:
    """将模型最小语义输出映射为可持久化的每日事项卡。"""
    source_by_id = {str(item.get("source_id")): item for item in sources}
    items: list[dict[str, Any]] = []
    for matter in model_result.get("matters", []):
        source_ids = sorted(str(value) for value in matter.get("source_ids", []))
        categories = {"event_source_ids": [], "annotation_source_ids": [], "schedule_source_ids": []}
        for source_id in source_ids:
            source = source_by_id[source_id]
            metadata = source.get("metadata") or {}
            if source.get("source_type") == "SCHEDULE_OCCURRENCE":
                categories["schedule_source_ids"].append(source_id)
            elif metadata.get("annotation_id"):
                categories["annotation_source_ids"].append(source_id)
            else:
                categories["event_source_ids"].append(source_id)
        items.append({
            "item_key": _daily_item_key(digest_date, source_ids),
            "title": matter["title"],
            "fact": matter["fact"],
            "current_status": matter["current_status"],
            "open_points": matter["open_points"],
            "source_ids": source_ids,
            **categories,
        })
    return {"digest_date": digest_date.isoformat(), "items": items}


def _assemble_daily_analysis_document(items: list[dict[str, Any]], model_result: dict[str, Any]) -> dict[str, Any]:
    """按代码预置事项补齐每日分析，禁止模型新增事项。"""
    by_key = {str(item.get("item_key")): item for item in model_result.get("matter_analyses", [])}
    fields = ("user_attention", "preferred_explanations", "prohibited_explanations", "feedback_constraints", "insufficient_evidence", "evidence_ids")
    return {
        "items": [
            {"item_key": item["item_key"], **{field: copy.deepcopy(by_key.get(item["item_key"], {}).get(field, [])) for field in fields}}
            for item in items
        ]
    }


def _assemble_week_event_document(model_result: dict[str, Any], daily_items: list[dict[str, Any]]) -> dict[str, Any]:
    """由模型的事项归属生成稳定的周级主线、节点与关注点。"""
    items = {str(item["item_key"]): item for item in daily_items}
    domains: dict[str, dict[str, Any]] = {}
    for position, semantic in enumerate(model_result.get("threads", []), start=1):
        item_keys = semantic["item_keys"]
        thread_key = f"thread-{uuid.uuid5(uuid.NAMESPACE_URL, '|'.join(sorted(item_keys)))}"
        nodes = []
        source_ids: list[str] = []
        for item_key in item_keys:
            item = items[item_key]
            node_key = f"node-{uuid.uuid5(uuid.NAMESPACE_URL, item_key)}"
            ids = list(item["source_ids"])
            source_ids.extend(ids)
            nodes.append({"node_key": node_key, "source_date": item["digest_date"], "change_type": "CURRENT_STATE", "fact": item["fact"], "source_ids": ids})
        domain_code = semantic["domain_code"]
        domain = domains.setdefault(domain_code, {"domain_code": domain_code, "core_focus": [], "event_threads": []})
        domain["event_threads"].append({
            "thread_key": thread_key, "title": semantic["title"], "primary_domain": domain_code,
            "related_domains": [], "narrative": "；".join(item["fact"] for item in (items[key] for key in item_keys)),
            "narrative_node_keys": [node["node_key"] for node in nodes], "continuity_status": "NEW",
            "current_status": semantic["current_status"], "previous_thread_key": None,
            "prior_context_source_ids": [], "selection_reason_codes": [semantic["selection_reason_code"]], "nodes": nodes, "links": [],
        })
        domain["core_focus"].append({"focus_key": f"focus-{thread_key}", "label": semantic["title"], "thread_keys": [thread_key], "source_ids": sorted(set(source_ids))})
    other_matters = [{"title": items[key]["title"], "narrative": items[key]["fact"], "source_ids": items[key]["source_ids"]} for key in model_result.get("other_item_keys", [])]
    return {"domains": list(domains.values()), "other_matters": other_matters}


def _stable_key(kind: str, *parts: object) -> str:
    """所有内部键均由代码根据稳定输入生成，模型不能控制。"""
    seed = "|".join(str(part) for part in parts)
    return f"{kind}-{uuid.uuid5(uuid.NAMESPACE_URL, seed)}"


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


def _daily_source_catalog(day_sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """每日调用只携带中高事件、历史未判定事件、划线及日程事实。"""
    highlighted_event_ids = {
        str((source.get("metadata") or {}).get("event_id"))
        for source in day_sources
        if (source.get("metadata") or {}).get("annotation_id")
        and (source.get("metadata") or {}).get("event_id")
    }
    result: list[dict[str, Any]] = []
    for source in day_sources:
        if source.get("source_type") == "SCHEDULE_OCCURRENCE":
            result.append(source)
            continue
        metadata = source.get("metadata") or {}
        if metadata.get("annotation_id"):
            result.append(source)
            continue
        event_id = metadata.get("event_id")
        importance = metadata.get("effective_importance")
        if event_id and (
            importance in {"HIGH", "MEDIUM"}
            or importance is None
            or str(event_id) in highlighted_event_ids
        ):
            result.append(source)
    return result


def _compact_week_catalog(source_catalog: list[dict[str, Any]], source_ids: set[str]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for source in source_catalog:
        is_schedule = source.get("source_type") == "SCHEDULE_OCCURRENCE"
        if str(source.get("source_id")) not in source_ids and not is_schedule:
            continue
        compact = copy.deepcopy(source)
        compact["content"] = (
            "该日程事实已按主题聚合；详见 schedule_aggregates。"
            if is_schedule else "该原始证据已被每日提炼引用；详见对应每日事项卡。"
        )
        result.append(compact)
    return result


def _schedule_aggregates(source_catalog: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for source in source_catalog:
        if source.get("source_type") != "SCHEDULE_OCCURRENCE" or source.get("period_role") != "CURRENT":
            continue
        metadata = source.get("metadata") or {}
        title = str(metadata.get("title") or source.get("content") or "日程")
        group = groups.setdefault(title, {"title": title, "planned_count": 0, "completed_count": 0, "dates": [], "details": []})
        group["planned_count"] += 1
        group["dates"].append(source.get("source_date"))
        if metadata.get("status") == "completed":
            group["completed_count"] += 1
        if metadata.get("execution_note"):
            group["details"].append({"source_id": source.get("source_id"), "note": metadata["execution_note"]})
    return list(groups.values())


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
        ReviewTask.id == task_id,
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
            daily_analysis_candidates: list[dict[str, Any]] = []
            all_daily_source_ids: set[str] = set()
            for digest_date in _dates_between(review.period_start, review.period_end):
                day_catalog = _daily_source_catalog([
                    item for item in source_catalog
                    if item.get("period_role") == "CURRENT" and item.get("source_date") == digest_date.isoformat()
                ])
                row = db.query(ReviewDailyDigest).filter(
                    ReviewDailyDigest.review_task_id == task.id,
                    ReviewDailyDigest.digest_date == digest_date,
                ).first()
                if not row:
                    row = ReviewDailyDigest(review_task_id=task.id, source_set_id=task.source_set_id, digest_date=digest_date)
                    db.add(row)
                    db.flush()
                if row.status == ReviewDailyDigestStatus.ANALYSIS_READY.value:
                    ids = _document_source_ids(row.event_document or {})
                    all_daily_source_ids.update(ids)
                    daily_analysis_candidates.append({
                        "analysis_id": f"daily:{row.id}", "content": str(row.analysis_document),
                        "feedback_usage": "NEUTRAL", "evidence_source_ids": sorted(ids), "feedbacks": [],
                    })
                    daily_rows.append(row)
                    continue
                if not day_catalog:
                    row.status = ReviewDailyDigestStatus.EMPTY.value
                    daily_rows.append(row)
                    continue
                day_source_ids = {str(item["source_id"]) for item in day_catalog}
                day_candidates = _daily_candidates(existing_candidates, day_source_ids)
                if row.status != ReviewDailyDigestStatus.EVENT_READY.value:
                    event_payload = {
                        "review": {"generation_mode": "FULL", "review_type": "WEEK", "period_start": digest_date.isoformat(), "period_end": digest_date.isoformat()},
                        "source_catalog": day_catalog,
                        "existing_analysis_candidates": day_candidates,
                        "missing_periods": [],
                    }
                    daily_result = await review_daily_event_digest(event_payload, review_task_id=str(task_id), max_attempts=settings.LLM_MAX_ATTEMPTS)
                    for update in daily_result.get("importance_updates", []):
                        source = next((item for item in day_catalog if item.get("source_id") == update.get("source_id")), None)
                        source_metadata = (source or {}).get("metadata", {})
                        event_id = None if source_metadata.get("annotation_id") else source_metadata.get("event_id")
                        if event_id:
                            event = db.query(DiaryEvent).filter(DiaryEvent.id == uuid.UUID(event_id)).first()
                            if event and not event.ai_importance:
                                event.ai_importance = update["importance"]
                                event.ai_importance_reason = update["reason"]
                                event.importance_origin = "LEGACY_BACKFILL"
                                event.importance_updated_at = datetime.utcnow()
                    row.event_document = _assemble_daily_event_document(daily_result, digest_date, day_catalog)
                    row.status = ReviewDailyDigestStatus.EVENT_READY.value
                    row.event_model_info = actual_review_model_info()
                    # 每日事件层是独立恢复点；分析失败不得回滚已完成事件层。
                    db.commit()
                daily_analysis_payload = {
                    "items": row.event_document["items"],
                    "existing_analysis_candidates": day_candidates,
                }
                daily_analysis = await review_daily_analysis_digest(daily_analysis_payload, review_task_id=str(task_id), max_attempts=settings.LLM_MAX_ATTEMPTS)
                row.analysis_document = _assemble_daily_analysis_document(row.event_document["items"], daily_analysis)
                row.analysis_model_info = actual_review_model_info()
                row.status = ReviewDailyDigestStatus.ANALYSIS_READY.value
                ids = _document_source_ids(row.event_document)
                all_daily_source_ids.update(ids)
                daily_analysis_candidates.append({
                    "analysis_id": f"daily:{row.id}", "content": str(row.analysis_document),
                    "feedback_usage": "NEUTRAL", "evidence_source_ids": sorted(ids), "feedbacks": [],
                })
                daily_rows.append(row)
                db.commit()
            if not all_daily_source_ids:
                task = _task_owned(db, task_id, run_token)
                task.status = ReviewTaskStatus.SKIPPED_NO_DATA.value
                task.completed_at = datetime.utcnow()
                db.commit()
                return
            week_catalog = _compact_week_catalog(source_catalog, all_daily_source_ids)
            daily_items = [
                {**item, "digest_date": row.digest_date.isoformat()}
                for row in daily_rows if row.status == ReviewDailyDigestStatus.ANALYSIS_READY.value
                for item in (row.event_document or {}).get("items", [])
            ]
            event_payload = {
                "review": {"generation_mode": "FULL", "review_type": review.review_type, "period_start": review.period_start.isoformat(), "period_end": review.period_end.isoformat()},
                "source_catalog": week_catalog,
                "daily_digests": [{"digest_date": row.digest_date.isoformat(), "event_document": row.event_document} for row in daily_rows if row.status == ReviewDailyDigestStatus.ANALYSIS_READY.value],
                "daily_items": daily_items,
                "schedule_aggregates": _schedule_aggregates(source_catalog),
                "existing_analysis_candidates": daily_analysis_candidates,
                "missing_periods": [],
            }
            if isinstance(task.event_result, dict) and "domains" in task.event_result:
                # 业务表中的周事件已通过组装与校验；恢复时绝不再次调用周模型。
                event_document = copy.deepcopy(task.event_result)
            else:
                weekly_semantics = await review_week_event_organize_from_digests(event_payload, review_task_id=str(task_id), max_attempts=settings.LLM_MAX_ATTEMPTS)
                event_document = _assemble_week_event_document(weekly_semantics, daily_items)
                event_model_info = actual_review_model_info()
                task = _task_owned(db, task_id, run_token)
                task.event_result = event_document
                db.commit()
            source_catalog = week_catalog
            existing_candidates = daily_analysis_candidates
            if stop_after == ReviewTaskStep.EVENT_ORGANIZE.value:
                return
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
            "existing_analysis_candidates": existing_candidates,
            "base_version_actions": _actions_payload(base_actions),
            "previous_confirmed_actions": previous_actions,
            "lower_review_actions": lower_review_actions,
            "derived_metrics": _derived_metrics(event_document, source_catalog, review.review_type),
            "missing_periods": missing_periods,
        }
        if isinstance(task.analysis_result, dict) and "domains" in task.analysis_result:
            # 已落库的任务中间产物是恢复依据，先重新校验再复用。
            analysis_result = copy.deepcopy(task.analysis_result)
            validate_analysis_action_document(analysis_result, analysis_payload)
        else:
            analysis_semantics = await review_analysis_action(
                analysis_payload,
                review_task_id=str(task_id),
                max_attempts=settings.LLM_MAX_ATTEMPTS,
            )
            analysis_result = _assemble_analysis_action_document(analysis_semantics, analysis_payload)
            # 模型输出先经最小语义校验，再由代码组装并复用完整持久化校验。
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
                ReviewTask.id == task_id,
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
