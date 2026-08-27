"""知识库事项匹配：输出校验、串行循环语义与单事务发布的单元测试。"""

import asyncio
import json
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

import services.knowledge_matters as km


# ---------------------------------------------------------------------------
# 输出校验：调用④
# ---------------------------------------------------------------------------

def test_assign_accepts_attach_with_followers():
    raw = json.dumps({"matter_no": 2, "follower_event_nos": [2], "follower_orphan_nos": [1]})
    result = km.parse_and_validate_assign(raw, {2, 3}, {1, 2}, {1})
    assert result == {"matter_no": 2, "follower_event_nos": [2], "follower_orphan_nos": [1]}


def test_assign_accepts_create_and_none():
    create = km.parse_and_validate_assign(json.dumps({"matter_no": 0}), set(), set(), set())
    assert create["matter_no"] == 0
    none = km.parse_and_validate_assign(json.dumps({"matter_no": None}), set(), set(), set())
    assert none["matter_no"] is None


def test_assign_rejects_unknown_matter_no():
    with pytest.raises(ValueError):
        km.parse_and_validate_assign(json.dumps({"matter_no": 9}), set(), {1, 2}, set())


def test_assign_rejects_follower_out_of_input():
    with pytest.raises(ValueError):
        km.parse_and_validate_assign(json.dumps({"matter_no": 0, "follower_event_nos": [5]}), {2, 3}, set(), set())


def test_assign_rejects_duplicate_follower():
    with pytest.raises(ValueError):
        km.parse_and_validate_assign(json.dumps({"matter_no": 0, "follower_orphan_nos": [1, 1]}), set(), set(), {1})


def test_assign_rejects_none_with_followers():
    with pytest.raises(ValueError):
        km.parse_and_validate_assign(json.dumps({"matter_no": None, "follower_event_nos": [2]}), {2}, set(), set())


def test_assign_rejects_markdown_fence():
    with pytest.raises(ValueError):
        km.parse_and_validate_assign("```json\n{\"matter_no\": 0}\n```", set(), set(), set())


# ---------------------------------------------------------------------------
# 输出校验：调用⑤
# ---------------------------------------------------------------------------

def test_overview_new_requires_name():
    raw = json.dumps({"overview": "三月开始的旧房翻新。", "status": "ONGOING"})
    with pytest.raises(ValueError):
        km.parse_and_validate_overview(raw, is_new=True)
    ok = km.parse_and_validate_overview(
        json.dumps({"name": "装修新房", "overview": "三月开始的旧房翻新。", "status": "ONGOING"}),
        is_new=True,
    )
    assert ok["name"] == "装修新房"


def test_overview_rewrite_rejects_name():
    raw = json.dumps({"name": "不应出现", "overview": "重写后的全览。", "status": "ENDED"})
    with pytest.raises(ValueError):
        km.parse_and_validate_overview(raw, is_new=False)


def test_overview_rejects_bad_status_and_empty_overview():
    with pytest.raises(ValueError):
        km.parse_and_validate_overview(json.dumps({"overview": "x", "status": "DONE"}), is_new=False)
    with pytest.raises(ValueError):
        km.parse_and_validate_overview(json.dumps({"overview": "  ", "status": "ONGOING"}), is_new=False)


def test_overview_rejects_long_name():
    raw = json.dumps({"name": "装" * 40, "overview": "全览。", "status": "ONGOING"})
    with pytest.raises(ValueError):
        km.parse_and_validate_overview(raw, is_new=True)


# ---------------------------------------------------------------------------
# 串行循环：Fake 边界
# ---------------------------------------------------------------------------

def _vec(seed: float):
    return [seed, 1.0, 0.5]


class FakeQuery:
    def __init__(self, db, model):
        self.db = db
        self.model = model

    def filter(self, *_args):
        return self

    def order_by(self, *_args):
        return self

    def limit(self, *_args):
        return self

    def with_for_update(self):
        return self

    def first(self):
        if self.model is km.KnowledgeTask:
            return self.db.task
        if self.model is km.Diary:
            return self.db.diary
        if self.model is km.KnowledgeMatter:
            return self.db.matter_record
        if self.model is km.KnowledgeDeposit:
            return self.db.deposit
        if self.model is km.KnowledgeAtomicEvent:
            return self.db.orphan_row
        raise AssertionError(f"unexpected model: {self.model}")

    def all(self):
        if self.model is km.KnowledgeAtomicEvent:
            return self.db.event_rows
        raise AssertionError(f"unexpected model: {self.model}")


class FakeDb:
    def __init__(self, *, task, diary, event_rows, deposit, matter_record=None, orphan_row=None):
        self.task = task
        self.diary = diary
        self.event_rows = event_rows
        self.deposit = deposit
        self.matter_record = matter_record
        self.orphan_row = orphan_row
        self.added = []
        self.committed = False

    def query(self, model):
        return FakeQuery(self, model)

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.committed = True

    def rollback(self):
        pass

    def close(self):
        pass


def _make_event_row(title, occurred_on=date(2026, 8, 20)):
    return SimpleNamespace(
        id=uuid4(), title=title, content=[f"{title}的正文。"],
        occurred_on=occurred_on, occurred_time=None, matter_id=None, embedding=None,
    )


def _make_task():
    run_token = uuid4()
    return SimpleNamespace(
        id=uuid4(), user_id=uuid4(), diary_id=uuid4(), status="RUNNING",
        run_token=run_token, lease_until=datetime.utcnow() + timedelta(minutes=3),
        completed_at=None, error_code=None, error_message=None, updated_at=None,
    )


def _run_loop(
    monkeypatch, fake_db, *, assign_script, overview_result=None, history=None,
    existing_matter=None, embed_fn=None,
):
    """以脚本化模型返回跑一次完整串行匹配，返回 (assign_payloads, overview_payloads)。"""
    monkeypatch.setattr(km, "SessionLocal", lambda: fake_db)
    monkeypatch.setattr(
        km, "embed_texts",
        embed_fn or (lambda texts: [_vec(i + 1.0) for i in range(len(texts))]),
    )
    monkeypatch.setattr(km, "_recall_history", lambda user_id, vector, limit: history or [])
    monkeypatch.setattr(km, "_load_matter", lambda matter_id, user_id: existing_matter)
    monkeypatch.setattr(km, "_load_recent_events", lambda matter: [
        {"title": item["title"], "content": item["content"], "occurred_on": item["occurred_on"]}
        for item in matter.members
    ])
    vectors = km.compute_event_embeddings([
        {"title": row.title, "content": row.content} for row in fake_db.event_rows
    ])
    for row, vector in zip(fake_db.event_rows, vectors):
        row.embedding = vector

    assign_payloads = []
    overview_payloads = []
    script = list(assign_script)

    async def fake_assign(payload, snapshot, related_nos, matter_nos, orphan_nos):
        assign_payloads.append(payload)
        assert script, "assign 调用次数超出脚本"
        return script.pop(0)

    async def fake_overview(payload, snapshot, *, is_new):
        overview_payloads.append({"is_new": is_new, **payload})
        base = overview_result or {"overview": "全览。", "status": "ONGOING"}
        if is_new:
            return {"name": "装修新房", **base}
        return base

    monkeypatch.setattr(km, "assign_matter", fake_assign)
    monkeypatch.setattr(km, "write_matter_overview", fake_overview)

    asyncio.run(km.match_task_matters(
        str(fake_db.task.id), fake_db.task.run_token, {"assign": 1}, {"overview": 1},
    ))
    return assign_payloads, overview_payloads


def test_none_subject_creates_no_matter(monkeypatch):
    task = _make_task()
    event_row = _make_event_row("看了一场电影")
    deposit = SimpleNamespace(completed_stage="ATOMIC_EVENTS", updated_at=None)
    fake_db = FakeDb(task=task, diary=SimpleNamespace(diary_date=date(2026, 8, 21)),
                     event_rows=[event_row], deposit=deposit)

    assigns, overviews = _run_loop(monkeypatch, fake_db, assign_script=[{"matter_no": None,
                                                                         "follower_event_nos": [],
                                                                         "follower_orphan_nos": []}])

    assert len(assigns) == 1 and overviews == []
    assert fake_db.added == []
    assert event_row.embedding is not None and event_row.matter_id is None
    assert deposit.completed_stage == "MATTERS"
    assert task.status == "SUCCEEDED" and fake_db.committed


def test_embedding_temporary_failure_retries(monkeypatch):
    monkeypatch.setattr(km.settings, "LLM_MAX_ATTEMPTS", 2)
    task = _make_task()
    event_row = _make_event_row("看了一场电影")
    deposit = SimpleNamespace(completed_stage="ATOMIC_EVENTS", updated_at=None)
    fake_db = FakeDb(task=task, diary=SimpleNamespace(diary_date=date(2026, 8, 21)),
                     event_rows=[event_row], deposit=deposit)
    calls = 0

    def embed(texts):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("temporary")
        return [_vec(1.0) for _ in texts]

    _run_loop(
        monkeypatch, fake_db,
        assign_script=[{"matter_no": None, "follower_event_nos": [], "follower_orphan_nos": []}],
        embed_fn=embed,
    )

    assert calls == 2


def test_create_matter_with_follower_skips_follower(monkeypatch):
    task = _make_task()
    row_a = _make_event_row("看瓷砖")
    row_b = _make_event_row("讨论装修预算")
    deposit = SimpleNamespace(completed_stage="ATOMIC_EVENTS", updated_at=None)
    fake_db = FakeDb(task=task, diary=SimpleNamespace(diary_date=date(2026, 8, 21)),
                     event_rows=[row_a, row_b], deposit=deposit)

    assigns, overviews = _run_loop(
        monkeypatch, fake_db,
        assign_script=[{"matter_no": 0, "follower_event_nos": [2], "follower_orphan_nos": []}],
    )

    # 跟随者不再作为主体处理：assign 与 overview 各只调一次。
    assert len(assigns) == 1 and len(overviews) == 1
    assert overviews[0]["is_new"] is True
    assert len(overviews[0]["new_events"]) == 2
    assert len(fake_db.added) == 1
    matter = fake_db.added[0]
    assert matter.name == "装修新房" and matter.event_count == 2
    assert matter.started_on == date(2026, 8, 20) and matter.last_event_on == date(2026, 8, 20)
    assert row_a.matter_id == matter.id and row_b.matter_id == matter.id


def test_attach_revives_ended_matter_before_overview(monkeypatch):
    task = _make_task()
    event_row = _make_event_row("定了沙发和餐桌")
    matter_id = uuid4()
    matter_record = SimpleNamespace(
        id=matter_id, user_id=task.user_id, name="装修新房", overview="旧全览。", status="ENDED",
        started_on=date(2026, 3, 15), last_event_on=date(2026, 6, 1), event_count=5, updated_at=None,
    )
    neighbor = SimpleNamespace(
        id=uuid4(), matter_id=matter_id, title="验收水电改造",
        content=["水电验收通过。"], occurred_on=date(2026, 6, 1),
    )
    deposit = SimpleNamespace(completed_stage="ATOMIC_EVENTS", updated_at=None)
    fake_db = FakeDb(task=task, diary=SimpleNamespace(diary_date=date(2026, 8, 21)),
                     event_rows=[event_row], deposit=deposit, matter_record=matter_record)

    assigns, overviews = _run_loop(
        monkeypatch, fake_db,
        assign_script=[{"matter_no": 1, "follower_event_nos": [], "follower_orphan_nos": []}],
        history=[neighbor], existing_matter=matter_record,
    )

    assert overviews[0]["is_new"] is False
    # 复活代码规则：调用⑤时事项状态已被代码置回进行中（原记录为已结束）。
    assert overviews[0]["matter"]["status"] == "ONGOING"
    assert matter_record.event_count == 6
    assert matter_record.last_event_on == date(2026, 8, 20)
    assert matter_record.started_on == date(2026, 3, 15)
    assert event_row.matter_id == matter_id
    assert fake_db.added == []


def test_orphan_adoption_into_new_matter(monkeypatch):
    task = _make_task()
    event_row = _make_event_row("又去看了一套房")
    orphan_row = SimpleNamespace(
        id=uuid4(), title="看了一套房", content=["三月看了一套房。"],
        occurred_on=date(2026, 3, 15), matter_id=None, embedding=_vec(2.0),
    )
    deposit = SimpleNamespace(completed_stage="ATOMIC_EVENTS", updated_at=None)
    fake_db = FakeDb(task=task, diary=SimpleNamespace(diary_date=date(2026, 8, 21)),
                     event_rows=[event_row], deposit=deposit, orphan_row=orphan_row)

    assigns, overviews = _run_loop(
        monkeypatch, fake_db,
        assign_script=[{"matter_no": 0, "follower_event_nos": [], "follower_orphan_nos": [1]}],
        history=[orphan_row],
    )

    assert assigns[0]["candidate_orphans"][0]["title"] == "看了一套房"
    matter = fake_db.added[0]
    # 收编：孤立事件挂入新事项，且事项起始日期回溯到孤立事件的发生日期。
    assert orphan_row.matter_id == matter.id
    assert matter.started_on == date(2026, 3, 15)
    assert matter.event_count == 2


def test_new_matter_immediately_visible_in_next_iteration(monkeypatch):
    task = _make_task()
    rows = [_make_event_row("看瓷砖"), _make_event_row("讨论预算"), _make_event_row("定了沙发")]
    deposit = SimpleNamespace(completed_stage="ATOMIC_EVENTS", updated_at=None)
    fake_db = FakeDb(task=task, diary=SimpleNamespace(diary_date=date(2026, 8, 21)),
                     event_rows=rows, deposit=deposit)

    assigns, overviews = _run_loop(
        monkeypatch, fake_db,
        assign_script=[
            {"matter_no": 0, "follower_event_nos": [], "follower_orphan_nos": []},
            {"matter_no": 1, "follower_event_nos": [3], "follower_orphan_nos": []},
        ],
    )

    # 第二次判定的候选事项中包含本循环刚创建的事项（立即生效）。
    assert len(assigns) == 2
    assert [payload["is_new"] for payload in overviews] == [True, False]
    assert overviews[0]["recent_events"] == []
    assert len(overviews[1]["recent_events"]) == 1
    assert len(overviews[1]["new_events"]) == 2
    second_candidates = assigns[1]["candidate_matters"]
    assert any(candidate["name"] == "装修新房" for candidate in second_candidates)
    matter = fake_db.added[0]
    assert matter.event_count == 3
    assert all(row.matter_id == matter.id for row in rows)
