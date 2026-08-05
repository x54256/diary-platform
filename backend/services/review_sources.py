"""定期回顾来源冻结与模型输入组装。"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Iterable

from sqlalchemy.orm import Session, joinedload

from models.diary import AnalysisRun, Diary, DiaryActionScheduleLink, DiaryAnnotation, DiaryEvent, DiaryOrganized, DiaryStatus
from models.favorite import Favorite
from models.review import (
    Review,
    ReviewAction,
    ReviewActionStatus,
    ReviewFactKind,
    ReviewPeriodRole,
    ReviewSource,
    ReviewSourceSet,
    ReviewSourceSetItem,
    ReviewSourceSetStatus,
    ReviewSourceType,
    ReviewTask,
    ReviewTaskStatus,
    ReviewType,
    ReviewVersion,
)
from models.schedule import ScheduleOccurrence
from services.review_periods import ReviewPeriod, previous_period, week_bounds


@dataclass
class FrozenReviewInput:
    source_set: ReviewSourceSet
    source_catalog: list[dict[str, Any]]
    existing_analysis_candidates: list[dict[str, Any]] = field(default_factory=list)
    previous_confirmed_actions: list[dict[str, Any]] = field(default_factory=list)
    base_version_actions: list[dict[str, Any]] = field(default_factory=list)
    lower_review_actions: list[dict[str, Any]] = field(default_factory=list)
    dependencies: list[dict[str, Any]] = field(default_factory=list)
    missing_periods: list[dict[str, Any]] = field(default_factory=list)

    @property
    def has_current_facts(self) -> bool:
        return any(item["period_role"] == ReviewPeriodRole.CURRENT.value for item in self.source_catalog)


def _json(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _text_list(value: Any) -> str:
    parsed = _json(value, [])
    if isinstance(parsed, list):
        return " ".join(str(item).strip() for item in parsed if str(item).strip())
    return str(parsed or "").strip()


def source_to_catalog(source: ReviewSource) -> dict[str, Any]:
    return {
        "source_id": str(source.id),
        "root_fact_id": source.root_fact_id,
        "source_type": source.source_type,
        "root_source_type": source.root_source_type,
        "source_date": source.source_date.isoformat(),
        "period_role": source.period_role,
        "relative_position": source.relative_position,
        "origin_review_id": str(source.origin_review_id) if source.origin_review_id else None,
        "origin_review_version_id": str(source.origin_review_version_id) if source.origin_review_version_id else None,
        "origin_content_item_type": source.origin_content_item_type,
        "origin_content_item_id": str(source.origin_content_item_id) if source.origin_content_item_id else None,
        "origin_content_item_key": source.origin_content_item_key,
        "lineage": source.lineage or [],
        "fact_kind": source.fact_kind,
        "content": source.content,
        "metadata": source.snapshot or {},
    }


class ReviewSourceFreezer:
    def __init__(
        self,
        db: Session,
        user_id: uuid.UUID,
        period: ReviewPeriod,
        base_version: ReviewVersion | None = None,
    ):
        self.db = db
        self.user_id = user_id
        self.period = period
        self.base_version = base_version
        self.source_set = ReviewSourceSet(
            user_id=user_id,
            status=ReviewSourceSetStatus.BUILDING.value,
        )
        self.sources: list[ReviewSource] = []
        self.dependencies: list[dict[str, Any]] = []
        self.missing_periods: list[dict[str, Any]] = []
        self.lower_review_actions: list[dict[str, Any]] = []

    def add_source(self, **values: Any) -> ReviewSource:
        source = ReviewSource(user_id=self.user_id, **values)
        self.db.add(source)
        self.db.flush()
        self.db.add(ReviewSourceSetItem(source_set_id=self.source_set.id, source_id=source.id))
        self.sources.append(source)
        return source

    def freeze(self) -> FrozenReviewInput:
        self.db.add(self.source_set)
        self.db.flush()
        if self.period.review_type == ReviewType.WEEK.value:
            candidates = self._freeze_week()
        elif self.period.review_type == ReviewType.MONTH.value:
            candidates = self._freeze_month()
        else:
            raise ValueError("当前只实现周回顾和月回顾")

        self._preserve_base_corrections()

        dependencies, missing = self._freeze_prior_same_level()
        self.dependencies.extend(dependencies)
        self.missing_periods.extend(missing)
        previous_actions = self._previous_confirmed_actions()
        self.source_set.input_snapshot = {
            "existing_analysis_candidates": candidates,
            "previous_confirmed_actions": previous_actions,
            "lower_review_actions": self.lower_review_actions,
            "dependencies": [self._json_dependency(item) for item in self.dependencies],
            "missing_periods": self.missing_periods,
            "frozen_at": datetime.utcnow().isoformat(),
        }
        self.source_set.status = ReviewSourceSetStatus.READY.value
        self.db.flush()
        return FrozenReviewInput(
            source_set=self.source_set,
            source_catalog=[source_to_catalog(item) for item in self.sources],
            existing_analysis_candidates=candidates,
            previous_confirmed_actions=previous_actions,
            lower_review_actions=self.lower_review_actions,
            dependencies=self.dependencies,
            missing_periods=self.missing_periods,
        )

    def _preserve_base_corrections(self) -> None:
        if not self.base_version:
            return
        existing_ids = {item.id for item in self.sources}
        corrections = (
            self.db.query(ReviewSource)
            .join(ReviewSourceSetItem, ReviewSourceSetItem.source_id == ReviewSource.id)
            .filter(
                ReviewSourceSetItem.source_set_id == self.base_version.source_set_id,
                ReviewSource.source_type == ReviewSourceType.USER_FACT_CORRECTION.value,
                ReviewSource.user_id == self.user_id,
            )
            .all()
        )
        for source in corrections:
            if source.id in existing_ids:
                continue
            self.db.add(ReviewSourceSetItem(source_set_id=self.source_set.id, source_id=source.id))
            self.sources.append(source)

    @staticmethod
    def _json_dependency(item: dict[str, Any]) -> dict[str, Any]:
        result = dict(item)
        for key in ("period_start", "period_end"):
            if isinstance(result.get(key), date):
                result[key] = result[key].isoformat()
        for key in ("dependency_review_id", "dependency_version_id"):
            if result.get(key) is not None:
                result[key] = str(result[key])
        return result

    def _freeze_week(self) -> list[dict[str, Any]]:
        diaries = (
            self.db.query(Diary)
            .options(joinedload(Diary.organized).joinedload(DiaryOrganized.events))
            .filter(
                Diary.user_id == self.user_id,
                Diary.deleted_at.is_(None),
                Diary.diary_date >= self.period.start,
                Diary.diary_date <= self.period.end,
                Diary.status.in_([DiaryStatus.organized, DiaryStatus.analyzed]),
                Diary.organized.has(
                    DiaryOrganized.source_content_revision == Diary.content_revision
                ),
            )
            .order_by(Diary.diary_date, Diary.created_at)
            .all()
        )
        event_ids = [event.id for diary in diaries for event in (diary.organized.events if diary.organized else [])]
        diary_ids = [diary.id for diary in diaries]
        favorite_event_ids = set()
        favorite_diary_ids = set()
        if event_ids:
            favorite_event_ids = {
                item[0]
                for item in self.db.query(Favorite.event_id).filter(
                    Favorite.user_id == self.user_id,
                    Favorite.event_id.in_(event_ids),
                ).all()
            }
        if diary_ids:
            favorite_diary_ids = {
                item[0]
                for item in self.db.query(Favorite.diary_id).filter(
                    Favorite.user_id == self.user_id,
                    Favorite.diary_id.in_(diary_ids),
                ).all()
            }
        annotations = (
            self.db.query(DiaryAnnotation)
            .options(joinedload(DiaryAnnotation.comments))
            .filter(
                DiaryAnnotation.diary_id.in_(diary_ids),
                DiaryAnnotation.deleted_at.is_(None),
            )
            .all()
            if diary_ids else []
        )
        annotations_by_diary: dict[str, list[DiaryAnnotation]] = {}
        for annotation in annotations:
            annotations_by_diary.setdefault(str(annotation.diary_id), []).append(annotation)
        candidates: list[dict[str, Any]] = []
        event_source_ids: dict[str, str] = {}
        for diary in diaries:
            organized = diary.organized
            if not organized:
                continue
            diary_source_ids: list[str] = []
            for event in organized.events:
                sections = [
                    event.event_title or "未命名事件",
                    _text_list(event.body),
                    _text_list(event.feeling),
                    _text_list(event.reflection),
                ]
                content = "\n".join(section for section in sections if section)
                source = self.add_source(
                    root_fact_id=f"diary-event:{event.id}",
                    source_type=ReviewSourceType.DIARY_EVENT.value,
                    root_source_type=ReviewSourceType.DIARY_EVENT.value,
                    fact_kind=ReviewFactKind.USER_FACT.value,
                    source_date=diary.diary_date,
                    period_role=ReviewPeriodRole.CURRENT.value,
                    relative_position=None,
                    content=content,
                    lineage=[],
                    snapshot={
                        "diary_id": str(diary.id),
                        "event_id": str(event.id),
                        "title": event.event_title,
                        "body": _text_list(event.body),
                        "feeling": _text_list(event.feeling),
                        "reflection": _text_list(event.reflection),
                        "sort_order": event.sort_order,
                        "is_favorite": event.id in favorite_event_ids or diary.id in favorite_diary_ids,
                        "content_revision": diary.content_revision,
                        "structured_revision": organized.structured_revision,
                        "ai_importance": event.ai_importance,
                        "ai_importance_reason": event.ai_importance_reason,
                        "user_importance": event.user_importance,
                        "user_importance_reason": event.user_importance_reason,
                        "effective_importance": event.user_importance or event.ai_importance,
                        "importance_origin": event.importance_origin,
                    },
                )
                event_source_ids[str(event.id)] = str(source.id)
                diary_source_ids.append(str(source.id))

            for annotation in annotations_by_diary.get(str(diary.id), []):
                comments = [
                    item.content for item in annotation.comments
                    if item.deleted_at is None and item.content.strip()
                ]
                content_parts = [f"用户划线：{annotation.selected_text}"]
                if comments:
                    content_parts.append("用户评论：" + "；".join(comments))
                source = self.add_source(
                    root_fact_id=f"diary-annotation:{annotation.id}",
                    source_type=ReviewSourceType.DIARY_EVENT.value,
                    root_source_type=ReviewSourceType.DIARY_EVENT.value,
                    fact_kind=ReviewFactKind.USER_SELF_REPORT.value,
                    source_date=diary.diary_date,
                    period_role=ReviewPeriodRole.CURRENT.value,
                    relative_position=None,
                    content="\n".join(content_parts),
                    lineage=[],
                    snapshot={
                        "diary_id": str(diary.id),
                        "event_id": str(annotation.event_id) if annotation.event_id else None,
                        "annotation_id": str(annotation.id),
                        "target_type": annotation.target_type,
                    },
                )
                diary_source_ids.append(str(source.id))

            for item_type, raw_value, label in (
                ("TRIVIA", organized.trivia, "本期补充事项"),
                ("PLAN", organized.plans, "后续计划"),
            ):
                content = _text_list(raw_value)
                if not content:
                    continue
                source = self.add_source(
                    root_fact_id=f"diary-{item_type.lower()}:{diary.id}",
                    source_type=ReviewSourceType.DIARY_EVENT.value,
                    root_source_type=ReviewSourceType.DIARY_EVENT.value,
                    fact_kind=ReviewFactKind.USER_SELF_REPORT.value,
                    source_date=diary.diary_date,
                    period_role=ReviewPeriodRole.CURRENT.value,
                    relative_position=None,
                    content=f"{label}：{content}",
                    lineage=[],
                    snapshot={
                        "diary_id": str(diary.id),
                        "content_item_type": item_type,
                        "content_revision": diary.content_revision,
                        "structured_revision": organized.structured_revision,
                    },
                )
                diary_source_ids.append(str(source.id))

            current_run = (
                self.db.query(AnalysisRun)
                .options(joinedload(AnalysisRun.items), joinedload(AnalysisRun.feedbacks))
                .filter(
                    AnalysisRun.diary_id == diary.id,
                    AnalysisRun.status == "CURRENT",
                    AnalysisRun.source_structured_revision == organized.structured_revision,
                )
                .first()
            )
            if current_run:
                feedback_map = {
                    (item.scope, str(item.event_id or ""), item.analysis_type): item
                    for item in current_run.feedbacks
                }
                for item in current_run.items:
                    feedback = feedback_map.get((item.scope, str(item.event_id or ""), item.analysis_type))
                    feedback_usage = (
                        "UNCONFIRMED" if feedback and feedback.is_inherited
                        else "PREFERRED_CANDIDATE" if feedback and feedback.rating >= 4
                        else "PROHIBITED" if feedback and feedback.rating <= 2
                        else "NEUTRAL"
                    )
                    candidates.append({
                        "analysis_id": str(item.id),
                        "analysis_type": item.analysis_type,
                        "content": item.content,
                        "feedback_usage": feedback_usage,
                        "evidence_source_ids": (
                            [event_source_ids[str(item.event_id)]]
                            if item.event_id and str(item.event_id) in event_source_ids else diary_source_ids
                        ),
                        "feedbacks": ([{
                            "feedback_id": str(feedback.id),
                            "rating": feedback.rating,
                            "comment": feedback.comment,
                        }] if feedback else []),
                        "diary_id": str(diary.id),
                        "event_id": str(item.event_id) if item.event_id else None,
                    })

        occurrences = (
            self.db.query(ScheduleOccurrence)
            .options(joinedload(ScheduleOccurrence.task))
            .filter(
                ScheduleOccurrence.user_id == self.user_id,
                ScheduleOccurrence.scheduled_date >= self.period.start,
                ScheduleOccurrence.scheduled_date <= self.period.end,
            )
            .order_by(ScheduleOccurrence.scheduled_date, ScheduleOccurrence.start_time)
            .all()
        )
        task_ids = [occurrence.task_id for occurrence in occurrences if occurrence.task_id]
        linked_actions: dict[str, DiaryActionScheduleLink] = {}
        if task_ids:
            links = (
                self.db.query(DiaryActionScheduleLink)
                .options(joinedload(DiaryActionScheduleLink.action_item))
                .filter(
                    DiaryActionScheduleLink.user_id == self.user_id,
                    DiaryActionScheduleLink.schedule_task_id.in_(task_ids),
                    DiaryActionScheduleLink.unlinked_at.is_(None),
                )
                .order_by(DiaryActionScheduleLink.linked_at)
                .all()
            )
            for link in links:
                linked_actions[str(link.schedule_task_id)] = link
        for occurrence in occurrences:
            state = "已标记完成" if occurrence.status == "completed" else "截至回顾生成时未标记完成"
            note = f"；执行备注：{occurrence.execution_note}" if occurrence.execution_note else ""
            time_text = "全天" if occurrence.is_all_day else "－".join(
                value.strftime("%H:%M") for value in (occurrence.start_time, occurrence.end_time) if value
            )
            recurrence_type = occurrence.task.recurrence_type if occurrence.task else "NONE"
            action_link = linked_actions.get(str(occurrence.task_id)) if occurrence.task_id else None
            self.add_source(
                root_fact_id=f"schedule-occurrence:{occurrence.id}",
                source_type=ReviewSourceType.SCHEDULE_OCCURRENCE.value,
                root_source_type=ReviewSourceType.SCHEDULE_OCCURRENCE.value,
                fact_kind=ReviewFactKind.SCHEDULE_RECORD.value,
                source_date=occurrence.scheduled_date,
                period_role=ReviewPeriodRole.CURRENT.value,
                relative_position=None,
                content=f"{occurrence.title}；{time_text or '未设置时间'}；{state}{note}",
                lineage=[],
                snapshot={
                    "occurrence_id": str(occurrence.id),
                    "task_id": str(occurrence.task_id),
                    "title": occurrence.title,
                    "scheduled_date": occurrence.scheduled_date.isoformat(),
                    "is_all_day": occurrence.is_all_day,
                    "start_time": occurrence.start_time.isoformat() if occurrence.start_time else None,
                    "end_time": occurrence.end_time.isoformat() if occurrence.end_time else None,
                    "recurrence_type": recurrence_type,
                    "source_task_id": str(occurrence.task.source_task_id) if occurrence.task and occurrence.task.source_task_id else None,
                    "status": occurrence.status,
                    "completed_at": occurrence.completed_at.isoformat() if occurrence.completed_at else None,
                    "execution_note": occurrence.execution_note,
                    "linked_action_item_id": str(action_link.action_item_id) if action_link else None,
                    "linked_action_title": action_link.action_item.title if action_link and action_link.action_item else None,
                },
            )
        return candidates

    @staticmethod
    def _threads(document: dict[str, Any] | None) -> Iterable[tuple[str, dict[str, Any]]]:
        for domain in (document or {}).get("domains", []):
            domain_code = domain.get("domain_code")
            for thread in domain.get("event_threads", []):
                yield domain_code, thread

    @staticmethod
    def _thread_source_ids(thread: dict[str, Any]) -> set[str]:
        values: set[str] = set(thread.get("prior_context_source_ids") or [])
        if thread.get("narrative_correction_source_id"):
            values.add(str(thread["narrative_correction_source_id"]))
        for node in thread.get("nodes") or []:
            values.update(node.get("source_ids") or [])
        return values

    def _version_sources(self, version: ReviewVersion) -> dict[str, ReviewSource]:
        rows = (
            self.db.query(ReviewSource)
            .join(ReviewSourceSetItem, ReviewSourceSetItem.source_id == ReviewSource.id)
            .filter(ReviewSourceSetItem.source_set_id == version.source_set_id)
            .all()
        )
        return {str(item.id): item for item in rows}

    def _freeze_month(self) -> list[dict[str, Any]]:
        week_reviews = (
            self.db.query(Review)
            .options(joinedload(Review.current_version))
            .filter(
                Review.user_id == self.user_id,
                Review.review_type == ReviewType.WEEK.value,
                Review.period_start <= self.period.end,
                Review.period_end >= self.period.start,
                Review.current_version_id.isnot(None),
            )
            .order_by(Review.period_start)
            .all()
        )
        by_start = {item.period_start: item for item in week_reviews}
        week_start, _ = week_bounds(self.period.start)
        while week_start <= self.period.end:
            week_end = week_start + date.resolution * 6
            lower = by_start.get(week_start)
            dependency = {
                "dependency_type": "LOWER_PERIOD",
                "period_start": week_start,
                "period_end": week_end,
                "context_only": False,
            }
            if lower and lower.current_version_id:
                dependency.update({
                    "status": "AVAILABLE",
                    "dependency_review_id": lower.id,
                    "dependency_version_id": lower.current_version_id,
                })
            else:
                latest_task = (
                    self.db.query(ReviewTask)
                    .join(Review, Review.id == ReviewTask.review_id)
                    .filter(
                        Review.user_id == self.user_id,
                        Review.review_type == ReviewType.WEEK.value,
                        Review.period_start == week_start,
                        Review.period_end == week_end,
                    )
                    .order_by(ReviewTask.created_at.desc())
                    .first()
                )
                status = (
                    latest_task.status
                    if latest_task and latest_task.status in {
                        ReviewTaskStatus.FAILED.value,
                        ReviewTaskStatus.SKIPPED_NO_DATA.value,
                    }
                    else "MISSING"
                )
                dependency["status"] = status
                self.missing_periods.append({
                    "review_type": ReviewType.WEEK.value,
                    "period_start": week_start.isoformat(),
                    "period_end": week_end.isoformat(),
                    "status": status,
                })
            self.dependencies.append(dependency)
            week_start += date.resolution * 7

        candidates: list[dict[str, Any]] = []
        for lower in week_reviews:
            version = lower.current_version
            if not version:
                continue
            sources = self._version_sources(version)
            lower_source_id_map: dict[str, str] = {}
            lower_source_rows: dict[str, ReviewSource] = {}
            for domain_code, thread in self._threads(version.event_document):
                source_ids = self._thread_source_ids(thread)
                for source_id in source_ids:
                    root = sources.get(str(source_id))
                    if not root:
                        continue
                    if root.source_date < self.period.start:
                        role, relative = ReviewPeriodRole.CONTEXT_ONLY.value, "BEFORE"
                    elif root.source_date > self.period.end:
                        role, relative = ReviewPeriodRole.CONTEXT_ONLY.value, "AFTER"
                    else:
                        role, relative = ReviewPeriodRole.CURRENT.value, None
                    copied = self.add_source(
                        root_fact_id=root.root_fact_id,
                        source_type=ReviewSourceType.LOWER_REVIEW_EVENT.value,
                        root_source_type=root.root_source_type,
                        fact_kind=ReviewFactKind.REVIEW_DERIVED.value,
                        source_date=root.source_date,
                        period_role=role,
                        relative_position=relative,
                        origin_review_id=lower.id,
                        origin_review_version_id=version.id,
                        origin_content_item_type="EVENT_THREAD",
                        origin_content_item_key=thread.get("thread_key"),
                        content=thread.get("narrative") or root.content,
                        lineage=(root.lineage or []) + [{
                            "review_id": str(lower.id),
                            "review_version_id": str(version.id),
                            "content_item_id": thread.get("thread_key"),
                            "source_id": str(root.id),
                        }],
                        snapshot={"domain_code": domain_code, "lower_source_id": str(root.id)},
                    )
                    lower_source_id_map[str(root.id)] = str(copied.id)
                    lower_source_rows[str(root.id)] = copied

            feedback_by_analysis_id = {
                str(item.analysis_item_id): item for item in version.feedback
            }
            for domain in (version.analysis_document or {}).get("domains", []):
                for item in domain.get("analysis_items", []):
                    analysis_id = str(item.get("analysis_item_id") or item.get("analysis_key"))
                    feedback = feedback_by_analysis_id.get(analysis_id)
                    feedback_usage = (
                        "UNCONFIRMED" if feedback and feedback.is_inherited
                        else "PREFERRED_CANDIDATE" if feedback and feedback.rating and feedback.rating >= 4
                        else "PROHIBITED" if feedback and feedback.rating and feedback.rating <= 2
                        else "NEUTRAL"
                    )
                    try:
                        origin_analysis_id = uuid.UUID(analysis_id)
                    except (ValueError, TypeError):
                        origin_analysis_id = None
                    analysis_source_ids: list[str] = []
                    for source_id in item.get("supporting_source_ids") or []:
                        copied_root = lower_source_rows.get(str(source_id))
                        if not copied_root:
                            continue
                        analysis_source = self.add_source(
                            root_fact_id=copied_root.root_fact_id,
                            source_type=ReviewSourceType.LOWER_REVIEW_ANALYSIS.value,
                            root_source_type=copied_root.root_source_type,
                            fact_kind=ReviewFactKind.AI_ANALYSIS.value,
                            source_date=copied_root.source_date,
                            period_role=copied_root.period_role,
                            relative_position=copied_root.relative_position,
                            origin_review_id=lower.id,
                            origin_review_version_id=version.id,
                            origin_content_item_type="ANALYSIS_ITEM",
                            origin_content_item_id=origin_analysis_id,
                            origin_content_item_key=item.get("analysis_key"),
                            content=item.get("claim") or "",
                            lineage=(copied_root.lineage or []) + [{
                                "review_id": str(lower.id),
                                "review_version_id": str(version.id),
                                "content_item_id": analysis_id,
                                "source_id": str(source_id),
                            }],
                            snapshot={"lower_source_id": str(source_id), "angle_code": item.get("angle_code")},
                        )
                        analysis_source_ids.append(str(analysis_source.id))
                    candidates.append({
                        "analysis_id": analysis_id,
                        "analysis_type": item.get("angle_code"),
                        "content": item.get("claim"),
                        "feedback_usage": feedback_usage,
                        "evidence_source_ids": analysis_source_ids,
                        "feedbacks": ([{
                            "feedback_id": str(feedback.id),
                            "rating": feedback.rating,
                            "comment": feedback.comment,
                        }] if feedback else []),
                        "origin_review_version_id": str(version.id),
                    })
            for action in version.actions:
                self.lower_review_actions.append({
                    "action_id": str(action.id),
                    "origin_review_id": str(lower.id),
                    "origin_review_version_id": str(version.id),
                    "primary_domain": action.primary_domain,
                    "related_domains": action.related_domains or [],
                    "content": action.edited_content or action.content,
                    "status": action.status,
                    "basis_source_ids": [
                        lower_source_id_map[str(source_id)]
                        for source_id in action.basis_source_ids or []
                        if str(source_id) in lower_source_id_map
                    ],
                })
        return candidates

    def _freeze_prior_same_level(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        prior_period = previous_period(self.period)
        prior = (
            self.db.query(Review)
            .options(joinedload(Review.current_version))
            .filter(
                Review.user_id == self.user_id,
                Review.review_type == self.period.review_type,
                Review.period_start == prior_period.start,
                Review.period_end == prior_period.end,
            )
            .first()
        )
        dependency = {
            "dependency_type": "PRIOR_SAME_LEVEL",
            "period_start": prior_period.start,
            "period_end": prior_period.end,
            "context_only": True,
        }
        if not prior or not prior.current_version:
            dependency["status"] = "MISSING"
            return [dependency], []

        version = prior.current_version
        dependency.update({
            "status": "AVAILABLE",
            "dependency_review_id": prior.id,
            "dependency_version_id": version.id,
        })
        roots = self._version_sources(version)
        for domain_code, thread in self._threads(version.event_document):
            for source_id in self._thread_source_ids(thread):
                root = roots.get(str(source_id))
                if not root:
                    continue
                self.add_source(
                    root_fact_id=root.root_fact_id,
                    source_type=ReviewSourceType.PRIOR_REVIEW_EVENT.value,
                    root_source_type=root.root_source_type,
                    fact_kind=ReviewFactKind.REVIEW_DERIVED.value,
                    source_date=root.source_date,
                    period_role=ReviewPeriodRole.CONTEXT_ONLY.value,
                    relative_position="BEFORE",
                    origin_review_id=prior.id,
                    origin_review_version_id=version.id,
                    origin_content_item_type="EVENT_THREAD",
                    origin_content_item_key=thread.get("thread_key"),
                    content=thread.get("narrative") or root.content,
                    lineage=(root.lineage or []) + [{
                        "review_id": str(prior.id),
                        "review_version_id": str(version.id),
                        "content_item_id": thread.get("thread_key"),
                        "source_id": str(root.id),
                    }],
                    snapshot={"domain_code": domain_code, "prior_source_id": str(root.id)},
                )
        return [dependency], []

    def _previous_confirmed_actions(self) -> list[dict[str, Any]]:
        return previous_confirmed_actions_for_period(self.db, self.user_id, self.period)


def load_source_catalog(db: Session, source_set_id: uuid.UUID) -> list[dict[str, Any]]:
    sources = (
        db.query(ReviewSource)
        .join(ReviewSourceSetItem, ReviewSourceSetItem.source_id == ReviewSource.id)
        .filter(ReviewSourceSetItem.source_set_id == source_set_id)
        .order_by(ReviewSource.source_date, ReviewSource.id)
        .all()
    )
    return [source_to_catalog(item) for item in sources if item.period_role != ReviewPeriodRole.OUT_OF_PERIOD.value]


def previous_confirmed_actions_for_period(
    db: Session,
    user_id: uuid.UUID,
    period: ReviewPeriod,
) -> list[dict[str, Any]]:
    prior_period = previous_period(period)
    prior = db.query(Review).filter(
        Review.user_id == user_id,
        Review.review_type == period.review_type,
        Review.period_start == prior_period.start,
        Review.period_end == prior_period.end,
    ).first()
    if not prior or not prior.current_version_id:
        return []
    actions = db.query(ReviewAction).filter(
        ReviewAction.version_id == prior.current_version_id,
        ReviewAction.user_id == user_id,
        ReviewAction.status == ReviewActionStatus.CONFIRMED.value,
    ).all()
    return [{
        "previous_action_id": str(item.id),
        "primary_domain": item.primary_domain,
        "content": item.edited_content or item.content,
        "verification": item.verification_rule or {},
    } for item in actions]
