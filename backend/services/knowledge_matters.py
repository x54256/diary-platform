"""知识库事项匹配：纯事件路向量召回 + 逐事件串行模型判定 + 单事务发布。

设计依据：docs/系统设计/知识库/知识库事项管理设计.md（2026-08-24 基线）。

- 召回：新事件向量 vs 历史知识事件向量（pgvector 余弦，相似度阈值 0.60 后 top-10）；批内向量在内存中计算余弦。
- 判定（knowledge_matter_assign）：每次只判断一个主体事件的去向，输出
  {matter_no, follower_event_nos, follower_orphan_nos}；matter_no 为候选编号 / 0（新建）/ null（不构成事项）。
- 全览（knowledge_matter_overview）：每组触达事项一次，输入旧全览 + 最近 10 事件 + 本批新事件。
- 归属结果在循环内立即生效（内存态）；全部处理完后单事务落库。
"""

import json
import logging
import math
from datetime import date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx

from config import settings
from database import SessionLocal
from models.diary import Diary
from models.knowledge import KnowledgeAtomicEvent, KnowledgeDeposit, KnowledgeMatter, KnowledgeTask
from services.embedding_client import embed_texts
from services.knowledge_ai import KnowledgeAIError, _invoke

logger = logging.getLogger(__name__)
_ai_logger = logging.getLogger("ai_pipeline")

ASSIGN_SYSTEM_PROMPT = (Path(__file__).resolve().parents[1] / "prompts" / "knowledge_matter_assign.txt").read_text(encoding="utf-8")
OVERVIEW_SYSTEM_PROMPT = (Path(__file__).resolve().parents[1] / "prompts" / "knowledge_matter_overview.txt").read_text(encoding="utf-8")

ASSIGN_STEP_KEY = "knowledge_matter_assign"
OVERVIEW_STEP_KEY = "knowledge_matter_overview"

RECALL_TOP_K = 10
MATTER_SIMILARITY_THRESHOLD = 0.60
RECENT_EVENTS_LIMIT = 10
MATTER_STATUSES = {"ONGOING", "ENDED", "PAUSED"}

# 事件分配状态（内存态）
_UNSET = "UNSET"
_NONE = "NONE"


def _reject_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"字段重复: {key}")
        result[key] = value
    return result


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if not norm_a or not norm_b:
        return 0.0
    return dot / (norm_a * norm_b)


def _embedding_text(title: str, content: list[str]) -> str:
    return (title or "").strip() + "\n" + "\n".join(content or [])


def compute_event_embeddings(items: list[dict[str, Any]]) -> list[list[float] | None]:
    """在原子事件发布前计算向量；失败时按约定返回空向量占位。"""
    inputs = [_embedding_text(item["title"], item["content"]) for item in items]
    last_error: Exception | None = None
    for attempt in range(1, settings.LLM_MAX_ATTEMPTS + 1):
        try:
            return list(embed_texts(inputs))
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt < settings.LLM_MAX_ATTEMPTS:
                logger.warning("知识事件向量化失败并重试", extra={"attempt": attempt, "error_type": type(exc).__name__})
    logger.error("知识事件向量化失败，原子事件将以空向量发布", extra={"error_type": type(last_error).__name__})
    return [None] * len(items)


def _event_payload(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": event["title"],
        "content": event["content"],
        "occurred_on": event["occurred_on"].isoformat(),
    }


# ---------------------------------------------------------------------------
# 调用 ④：事项归属判定
# ---------------------------------------------------------------------------

def parse_and_validate_assign(
    raw: str,
    related_nos: set[int],
    candidate_matter_nos: set[int],
    orphan_nos: set[int],
) -> dict[str, Any]:
    """校验判定输出：matter_no ∈ {null, 0} ∪ 候选编号；跟随者编号必须存在于输入。"""
    if raw.lstrip().startswith("```"):
        raise ValueError("不能包含 Markdown 代码块")
    data = json.loads(raw, object_pairs_hook=_reject_duplicate)
    if not isinstance(data, dict):
        raise ValueError("顶层必须是对象")
    unknown = sorted(set(data) - {"matter_no", "follower_event_nos", "follower_orphan_nos"})
    if unknown:
        _ai_logger.warning("[knowledge_matter_assign] 忽略模型多余字段: fields=%s", unknown)
        for field in unknown:
            del data[field]
    if "matter_no" not in data:
        raise ValueError("缺少字段: matter_no")
    matter_no = data["matter_no"]
    if matter_no is not None:
        if type(matter_no) is not int:
            raise ValueError("matter_no 必须是整数或 null")
        if matter_no != 0 and matter_no not in candidate_matter_nos:
            raise ValueError(f"matter_no 不在候选编号中: {matter_no}")

    def _followers(field: str, allowed: set[int]) -> list[int]:
        value = data.get(field, [])
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError(f"{field} 必须是数组")
        result: list[int] = []
        for item in value:
            if type(item) is not int or item not in allowed:
                raise ValueError(f"{field} 包含输入中不存在的编号: {item}")
            if item in result:
                raise ValueError(f"{field} 编号重复: {item}")
            result.append(item)
        return result

    follower_events = _followers("follower_event_nos", related_nos)
    follower_orphans = _followers("follower_orphan_nos", orphan_nos)
    if matter_no is None and (follower_events or follower_orphans):
        raise ValueError("matter_no 为 null 时跟随者必须为空")
    return {
        "matter_no": matter_no,
        "follower_event_nos": follower_events,
        "follower_orphan_nos": follower_orphans,
    }


async def assign_matter(
    payload: dict[str, Any],
    snapshot: dict[str, Any],
    related_nos: set[int],
    candidate_matter_nos: set[int],
    orphan_nos: set[int],
) -> dict[str, Any]:
    user_message = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    last_error: Exception | None = None
    repair_used = False
    for attempt in range(1, settings.LLM_MAX_ATTEMPTS + 1):
        try:
            raw = await _invoke(snapshot, ASSIGN_SYSTEM_PROMPT, user_message, ASSIGN_STEP_KEY)
            try:
                return parse_and_validate_assign(raw, related_nos, candidate_matter_nos, orphan_nos)
            except (json.JSONDecodeError, ValueError) as validation_error:
                if repair_used:
                    raise KnowledgeAIError("MODEL_OUTPUT_INVALID", f"事项判定输出结构不合法: {validation_error}") from validation_error
                repair_used = True
                repair_prompt = "你是 JSON 结构修复器。只修复给定响应的 JSON 和字段结构，不改变内容语义；严格输出符合目标结构的 JSON。"
                repair_message = json.dumps({
                    "target": {"fields": ["matter_no", "follower_event_nos", "follower_orphan_nos"]},
                    "invalid_response": raw,
                    "validation_error": str(validation_error),
                }, ensure_ascii=False, separators=(",", ":"))
                repaired = await _invoke(snapshot, repair_prompt, repair_message, ASSIGN_STEP_KEY)
                try:
                    return parse_and_validate_assign(repaired, related_nos, candidate_matter_nos, orphan_nos)
                except (json.JSONDecodeError, ValueError) as exc:
                    raise KnowledgeAIError("MODEL_OUTPUT_INVALID", f"事项判定输出修复后仍不合法: {exc}") from exc
        except KnowledgeAIError:
            raise
        except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError, KeyError, TypeError, ValueError) as exc:
            last_error = exc
            if attempt < settings.LLM_MAX_ATTEMPTS:
                logger.warning("事项判定模型调用失败并重试", extra={"attempt": attempt, "error_type": type(exc).__name__})
    raise KnowledgeAIError("LLM_CALL_FAILED", "事项判定模型调用失败") from last_error


# ---------------------------------------------------------------------------
# 调用 ⑤：事项全览
# ---------------------------------------------------------------------------

def parse_and_validate_overview(raw: str, *, is_new: bool) -> dict[str, Any]:
    if raw.lstrip().startswith("```"):
        raise ValueError("不能包含 Markdown 代码块")
    data = json.loads(raw, object_pairs_hook=_reject_duplicate)
    if not isinstance(data, dict):
        raise ValueError("顶层必须是对象")
    expected = {"overview", "status"} | ({"name"} if is_new else set())
    missing = sorted(expected - set(data))
    if missing:
        raise ValueError(f"缺少字段: {', '.join(missing)}")
    extra = sorted(set(data) - expected)
    if not is_new and "name" in extra:
        raise ValueError("重写事项全览时不得返回 name")
    if extra:
        _ai_logger.warning("[knowledge_matter_overview] 忽略模型多余字段: fields=%s", extra)
        for field in extra:
            del data[field]
    overview = data["overview"]
    if not isinstance(overview, str) or not overview.strip():
        raise ValueError("overview 必须是非空字符串")
    data["overview"] = overview.strip()
    status = data["status"]
    if not isinstance(status, str) or status not in MATTER_STATUSES:
        raise ValueError(f"status 不合法: {status!r}")
    if is_new:
        name = data["name"]
        if not isinstance(name, str) or not name.strip():
            raise ValueError("name 必须是非空字符串")
        name = name.strip()
        if len(name) > 30:
            raise ValueError("name 长度不能超过 30 个字符")
        data["name"] = name
    return data


async def write_matter_overview(payload: dict[str, Any], snapshot: dict[str, Any], *, is_new: bool) -> dict[str, Any]:
    user_message = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    last_error: Exception | None = None
    repair_used = False
    for attempt in range(1, settings.LLM_MAX_ATTEMPTS + 1):
        try:
            raw = await _invoke(snapshot, OVERVIEW_SYSTEM_PROMPT, user_message, OVERVIEW_STEP_KEY)
            try:
                return parse_and_validate_overview(raw, is_new=is_new)
            except (json.JSONDecodeError, ValueError) as validation_error:
                if repair_used:
                    raise KnowledgeAIError("MODEL_OUTPUT_INVALID", f"事项全览输出结构不合法: {validation_error}") from validation_error
                repair_used = True
                repair_prompt = "你是 JSON 结构修复器。只修复给定响应的 JSON 和字段结构，不改变内容语义；严格输出符合目标结构的 JSON。"
                repair_message = json.dumps({
                    "target": {"is_new": is_new},
                    "invalid_response": raw,
                    "validation_error": str(validation_error),
                }, ensure_ascii=False, separators=(",", ":"))
                repaired = await _invoke(snapshot, repair_prompt, repair_message, OVERVIEW_STEP_KEY)
                try:
                    return parse_and_validate_overview(repaired, is_new=is_new)
                except (json.JSONDecodeError, ValueError) as exc:
                    raise KnowledgeAIError("MODEL_OUTPUT_INVALID", f"事项全览输出修复后仍不合法: {exc}") from exc
        except KnowledgeAIError:
            raise
        except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError, KeyError, TypeError, ValueError) as exc:
            last_error = exc
            if attempt < settings.LLM_MAX_ATTEMPTS:
                logger.warning("事项全览模型调用失败并重试", extra={"attempt": attempt, "error_type": type(exc).__name__})
    raise KnowledgeAIError("LLM_CALL_FAILED", "事项全览模型调用失败") from last_error


# ---------------------------------------------------------------------------
# 串行匹配主流程
# ---------------------------------------------------------------------------

class _MatterState:
    """内存态事项：既有事项的缓存或本循环新建的事项。"""

    def __init__(self, key: str, matter: KnowledgeMatter | None):
        self.key = key
        self.id: UUID | None = matter.id if matter else None
        self.name: str | None = matter.name if matter else None
        self.overview: str | None = matter.overview if matter else None
        self.status: str = matter.status if matter else "ONGOING"
        self.started_on: date | None = matter.started_on if matter else None
        self.last_event_on: date | None = matter.last_event_on if matter else None
        self.event_count: int = matter.event_count if matter else 0
        # 新事项第一次生成全览后即成为可继续重写的内存事项，不能再次按新建处理。
        self.initialized = matter is not None
        # 本次运行挂入的成员：{title, content, occurred_on, batch_index|None, orphan_id|None}
        self.members: list[dict[str, Any]] = []
        self.recent_events: list[dict[str, Any]] | None = None  # 首次调用⑤时加载

    @property
    def is_new(self) -> bool:
        return not self.initialized


def _recall_history(user_id: UUID, vector: list[float], limit: int) -> list[KnowledgeAtomicEvent]:
    """历史事件库 pgvector 余弦近邻召回；无向量（存量/匹配失败）的事件不参与。"""
    db = SessionLocal()
    try:
        return (
            db.query(KnowledgeAtomicEvent)
            .filter(
                KnowledgeAtomicEvent.user_id == user_id,
                KnowledgeAtomicEvent.embedding.isnot(None),
                KnowledgeAtomicEvent.embedding.cosine_distance(vector) <= (1 - MATTER_SIMILARITY_THRESHOLD),
            )
            .order_by(KnowledgeAtomicEvent.embedding.cosine_distance(vector))
            .limit(limit)
            .all()
        )
    finally:
        db.close()


def _load_matter(matter_id: UUID, user_id: UUID) -> KnowledgeMatter | None:
    db = SessionLocal()
    try:
        return (
            db.query(KnowledgeMatter)
            .filter(KnowledgeMatter.id == matter_id, KnowledgeMatter.user_id == user_id)
            .first()
        )
    finally:
        db.close()


def _load_recent_events(matter: _MatterState) -> list[dict[str, Any]]:
    """事项最近 10 个归属事件（含本次运行已挂入成员），按发生时间正序。"""
    recent: list[dict[str, Any]] = []
    if matter.id is not None:
        db = SessionLocal()
        try:
            rows = (
                db.query(KnowledgeAtomicEvent)
                .filter(KnowledgeAtomicEvent.matter_id == matter.id)
                .order_by(
                    KnowledgeAtomicEvent.occurred_on.desc(),
                    KnowledgeAtomicEvent.occurred_time.desc().nullslast(),
                    KnowledgeAtomicEvent.id.desc(),
                )
                .limit(RECENT_EVENTS_LIMIT)
                .all()
            )
        finally:
            db.close()
        recent = [{"title": row.title, "content": row.content, "occurred_on": row.occurred_on} for row in rows]
    recent.extend({"title": m["title"], "content": m["content"], "occurred_on": m["occurred_on"]} for m in matter.members)
    recent.sort(key=lambda item: item["occurred_on"], reverse=True)
    recent = recent[:RECENT_EVENTS_LIMIT]
    recent.reverse()
    return recent


async def _refresh_overview(matter: _MatterState, new_members: list[dict[str, Any]], snapshot: dict[str, Any]) -> None:
    """调用⑤为触达事项生成/重写全览与状态，结果写回内存态（循环内立即生效）。"""
    matter.recent_events = _load_recent_events(matter)
    ordered_members = sorted(new_members, key=lambda m: m["occurred_on"])
    payload = {
        "matter": (
            None if matter.is_new
            else {"name": matter.name, "overview": matter.overview, "status": matter.status}
        ),
        "recent_events": [_event_payload(item) for item in matter.recent_events],
        "new_events": [_event_payload(item) for item in ordered_members],
    }
    result = await write_matter_overview(payload, snapshot, is_new=matter.is_new)
    if matter.is_new:
        matter.name = result["name"]
    matter.overview = result["overview"]
    matter.status = result["status"]
    matter.initialized = True


async def match_task_matters(
    task_id: str,
    run_token: UUID,
    assign_snapshot: dict[str, Any],
    overview_snapshot: dict[str, Any],
) -> None:
    """MATCH_MATTERS 节点主体：串行判定 + 单事务发布。

    失败时抛出 KnowledgeAIError（MATTER_MATCH_FAILED / MODEL_OUTPUT_INVALID），
    已发布知识事件不受影响，事件向量与归属均不落库。
    """
    db = SessionLocal()
    try:
        task = db.query(KnowledgeTask).filter(
            KnowledgeTask.id == UUID(task_id),
            KnowledgeTask.status == "RUNNING",
            KnowledgeTask.run_token == run_token,
            KnowledgeTask.lease_until > datetime.utcnow(),
        ).first()
        if not task:
            raise KnowledgeAIError("OWNERSHIP_LOST", "任务执行权已失效")
        user_id = task.user_id
        diary_id = task.diary_id
        diary_row = db.query(Diary).filter(Diary.id == diary_id).first()
        diary_date_value = diary_row.diary_date if diary_row else None
        deposit = db.query(KnowledgeDeposit).filter(KnowledgeDeposit.diary_id == diary_id).first()
        if deposit and deposit.completed_stage == "MATTERS":
            # 幂等：事项阶段已完成，直接置任务成功，不重复匹配（升级任务场景）。
            now = datetime.utcnow()
            task.status = "SUCCEEDED"
            task.lease_until = None
            task.completed_at = now
            task.updated_at = now
            db.commit()
            return
        rows = (
            db.query(KnowledgeAtomicEvent)
            .filter(KnowledgeAtomicEvent.diary_id == diary_id)
            .order_by(KnowledgeAtomicEvent.occurred_on, KnowledgeAtomicEvent.id)
            .all()
        )
        if not rows:
            if not deposit:
                raise KnowledgeAIError("MATTER_MATCH_FAILED", "成功沉淀记录不存在")
            now = datetime.utcnow()
            deposit.completed_stage = "MATTERS"
            deposit.updated_at = now
            task.status = "SUCCEEDED"
            task.lease_until = None
            task.completed_at = now
            task.error_code = None
            task.error_message = None
            task.updated_at = now
            db.commit()
            return
        batch: list[dict[str, Any]] = [
            {
                "id": row.id,
                "event_no": index,
                "title": row.title,
                "content": row.content,
                "occurred_on": row.occurred_on,
                "embedding": row.embedding,
                "assignment": _UNSET,
            }
            for index, row in enumerate(rows, start=1)
        ]
    finally:
        db.close()
    matters: dict[str, _MatterState] = {}
    new_counter = 0
    by_event_no = {item["event_no"]: item for item in batch}

    def _matter_for_key(key: str) -> _MatterState | None:
        return matters.get(key)

    def _existing_matter_state(matter_id: UUID) -> _MatterState | None:
        key = str(matter_id)
        state = matters.get(key)
        if state is None:
            record = _load_matter(matter_id, user_id)
            if record is None:
                return None
            state = _MatterState(key, record)
            matters[key] = state
        return state

    for subject in batch:
        if subject["assignment"] != _UNSET:
            continue
        if subject["embedding"] is None:
            subject["assignment"] = _NONE
            continue

        # 1. 批内召回（内存余弦，含已分配事件——其归属事项成为候选）。
        batch_scored = sorted(
            (
                (other, _cosine_similarity(subject["embedding"], other["embedding"]))
                for other in batch
                if other["event_no"] != subject["event_no"] and other["embedding"] is not None
            ),
            key=lambda pair: pair[1],
            reverse=True,
        )
        batch_scored = [
            pair for pair in batch_scored if pair[1] >= MATTER_SIMILARITY_THRESHOLD
        ][:RECALL_TOP_K]

        # 2. 历史召回（pgvector）。
        history_neighbors = _recall_history(user_id, subject["embedding"], RECALL_TOP_K)

        # 3. 候选整理。
        candidate_matters: list[dict[str, Any]] = []
        seen_matter_keys: set[str] = set()

        def _push_matter(state: _MatterState) -> None:
            if state.key in seen_matter_keys:
                return
            seen_matter_keys.add(state.key)
            # 本循环新建的事项尚未落库，最近事件日期取已挂入成员的最大值。
            last_on = state.last_event_on
            if state.members:
                member_max = max(m["occurred_on"] for m in state.members)
                last_on = member_max if last_on is None else max(last_on, member_max)
            candidate_matters.append({
                "matter_no": len(candidate_matters) + 1,
                "key": state.key,
                "name": state.name,
                "overview": state.overview,
                "status": state.status,
                "last_event_on": (last_on or subject["occurred_on"]).isoformat(),
            })

        related_events: list[dict[str, Any]] = []
        for other, _score in batch_scored:
            if other["assignment"] == _UNSET:
                related_events.append(other)
            elif other["assignment"] != _NONE:
                state = _matter_for_key(other["assignment"])
                if state is not None:
                    _push_matter(state)

        candidate_orphans: list[dict[str, Any]] = []
        for neighbor in history_neighbors:
            if neighbor.matter_id:
                state = _existing_matter_state(neighbor.matter_id)
                if state is not None:
                    _push_matter(state)
            else:
                candidate_orphans.append({
                    "orphan_no": len(candidate_orphans) + 1,
                    "id": neighbor.id,
                    "title": neighbor.title,
                    "content": neighbor.content,
                    "occurred_on": neighbor.occurred_on,
                })

        # 4. 调用④判定。
        payload = {
            "diary_date": diary_date_value.isoformat() if diary_date_value else None,
            "subject": {"event_no": subject["event_no"], **_event_payload(subject)},
            "related_events": [
                {"event_no": item["event_no"], **_event_payload(item)} for item in related_events
            ],
            "candidate_matters": [
                {k: v for k, v in candidate.items() if k != "key"} for candidate in candidate_matters
            ],
            "candidate_orphans": [
                {"orphan_no": orphan["orphan_no"], **_event_payload(orphan)} for orphan in candidate_orphans
            ],
        }
        decision = await assign_matter(
            payload,
            assign_snapshot,
            {item["event_no"] for item in related_events},
            {candidate["matter_no"] for candidate in candidate_matters},
            {orphan["orphan_no"] for orphan in candidate_orphans},
        )

        # 5. 代码执行判定结果。
        matter_no = decision["matter_no"]
        if matter_no is None:
            subject["assignment"] = _NONE
            continue
        if matter_no == 0:
            new_counter += 1
            matter = _MatterState(f"new:{new_counter}", None)
            matters[matter.key] = matter
        else:
            key = candidate_matters[matter_no - 1]["key"]
            matter = matters[key]
            # 复活代码规则：已结束/已搁置事项被挂入时直接回到进行中，
            # 随后调用⑤仍会基于文本输出最终状态。
            if matter.status != "ONGOING":
                matter.status = "ONGOING"

        iteration_members: list[dict[str, Any]] = [
            {"title": subject["title"], "content": subject["content"], "occurred_on": subject["occurred_on"],
             "batch_event_no": subject["event_no"], "orphan_id": None}
        ]
        subject["assignment"] = matter.key
        for follower_no in decision["follower_event_nos"]:
            follower = by_event_no[follower_no]
            follower["assignment"] = matter.key
            iteration_members.append({
                "title": follower["title"], "content": follower["content"], "occurred_on": follower["occurred_on"],
                "batch_event_no": follower_no, "orphan_id": None,
            })
        for orphan_no in decision["follower_orphan_nos"]:
            orphan = candidate_orphans[orphan_no - 1]
            iteration_members.append({
                "title": orphan["title"], "content": orphan["content"], "occurred_on": orphan["occurred_on"],
                "batch_event_no": None, "orphan_id": orphan["id"],
            })
        # 6. 调用⑤重写触达事项的全览与状态（内存态立即生效）。
        # recent_events 只包含调用前已有的最近事件；本轮成员仅进入 new_events。
        await _refresh_overview(matter, iteration_members, overview_snapshot)
        matter.members.extend(iteration_members)

    # 7. 单事务提交：事件向量与归属、事项新建/更新、阶段推进、任务成功。
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        task = (
            db.query(KnowledgeTask)
            .filter(
                KnowledgeTask.id == UUID(task_id),
                KnowledgeTask.status == "RUNNING",
                KnowledgeTask.run_token == run_token,
                KnowledgeTask.lease_until > now,
            )
            .with_for_update()
            .first()
        )
        if not task:
            raise KnowledgeAIError("OWNERSHIP_LOST", "任务执行权已失效")

        matter_ids: dict[str, UUID] = {}
        for matter in matters.values():
            if not matter.members:
                continue
            member_dates = [member["occurred_on"] for member in matter.members]
            if matter.id is None:
                matter.id = uuid4()
                db.add(KnowledgeMatter(
                    id=matter.id, user_id=user_id, name=matter.name, overview=matter.overview,
                    status=matter.status, started_on=min(member_dates), last_event_on=max(member_dates),
                    event_count=len(matter.members), created_at=now, updated_at=now,
                ))
            else:
                record = (
                    db.query(KnowledgeMatter)
                    .filter(KnowledgeMatter.id == matter.id, KnowledgeMatter.user_id == user_id)
                    .with_for_update()
                    .first()
                )
                if not record:
                    raise KnowledgeAIError("MATTER_MATCH_FAILED", "目标事项已不存在")
                record.overview = matter.overview
                record.status = matter.status
                record.event_count = record.event_count + len(matter.members)
                record.started_on = min(record.started_on, min(member_dates))
                record.last_event_on = max(record.last_event_on, max(member_dates))
                record.updated_at = now
            matter_ids[matter.key] = matter.id

        event_rows = (
            db.query(KnowledgeAtomicEvent)
            .filter(KnowledgeAtomicEvent.diary_id == diary_id)
            .with_for_update()
            .all()
        )
        row_by_id = {row.id: row for row in event_rows}
        for item in batch:
            row = row_by_id[item["id"]]
            row.embedding = item["embedding"]
            if item["assignment"] not in (_UNSET, _NONE):
                row.matter_id = matter_ids[item["assignment"]]

        for matter in matters.values():
            for member in matter.members:
                if member["orphan_id"] is None:
                    continue
                orphan_row = (
                    db.query(KnowledgeAtomicEvent)
                    .filter(
                        KnowledgeAtomicEvent.id == member["orphan_id"],
                        KnowledgeAtomicEvent.matter_id.is_(None),
                    )
                    .first()
                )
                if orphan_row is not None:
                    orphan_row.matter_id = matter_ids[matter.key]

        deposit = (
            db.query(KnowledgeDeposit)
            .filter(KnowledgeDeposit.diary_id == diary_id)
            .with_for_update()
            .first()
        )
        if not deposit:
            raise KnowledgeAIError("MATTER_MATCH_FAILED", "成功沉淀记录不存在")
        deposit.completed_stage = "MATTERS"
        deposit.updated_at = now

        task.status = "SUCCEEDED"
        task.lease_until = None
        task.completed_at = now
        task.error_code = None
        task.error_message = None
        task.updated_at = now
        db.commit()
    except KnowledgeAIError:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise KnowledgeAIError("MATTER_MATCH_FAILED", "事项匹配发布失败") from exc
    finally:
        db.close()
