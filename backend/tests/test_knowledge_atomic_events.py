import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from models.diary import DiaryEvent, DiaryOrganized, DiaryStatus
from routers.knowledge import _source
from services.knowledge_ai import (
    REVIEW_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
    _invoke,
    freeze_model_config,
    parse_and_validate,
    parse_and_validate_review,
    review_knowledge_events,
)
from services.knowledge_workflow import KnowledgeState, plan_event_batches, plan_review_batches, review_batch
from services.model_runtime import RuntimeModelConfig
from services.model_management import SETTING_KEYS, STEP_SETTING_KEYS
from utils.llm_log import LLM_LOG_BODY_LIMIT
from uuid import uuid4


class FakeSourceQuery:
    def __init__(self, *, first_value=None, all_value=None):
        self.first_value = first_value
        self.all_value = all_value or []

    def filter(self, *_args):
        return self

    def order_by(self, *_args):
        return self

    def first(self):
        return self.first_value

    def all(self):
        return self.all_value


class FakeSourceDb:
    def __init__(self, organized, events):
        self.organized = organized
        self.events = events

    def query(self, model):
        if model is DiaryOrganized:
            return FakeSourceQuery(first_value=self.organized)
        if model is DiaryEvent:
            return FakeSourceQuery(all_value=self.events)
        raise AssertionError(f"unexpected model: {model}")


def valid_payload(event_no=1):
    return {
        "results": [{
            "event_no": event_no,
            "title": "买酱油",
            "content": ["我去商店买了酱油。"],
            "occurred_on": "2026-08-11",
            "occurred_time": None,
        }],
    }


def review_input():
    candidate = valid_payload()["results"][0]
    return {
        "diary_date": "2026-08-11",
        "items": [{
            "event": {"event_no": 1, "title": "买酱油", "body": ["我可能下午去商店买酱油。"]},
            "candidate": candidate,
        }],
    }


def review_output(*, issues=None, **changes):
    result = {"issues": issues or [], **valid_payload()["results"][0]}
    result.update(changes)
    return {"results": [result]}


def test_atomic_event_output_accepts_exact_contract():
    result = parse_and_validate(json.dumps(valid_payload(), ensure_ascii=False), [1], "2026-08-11")
    assert result[0]["event_no"] == 1


@pytest.mark.parametrize("mutation", [
    lambda value: value["results"][0].pop("occurred_time"),
    lambda value: value["results"][0].update(content=[]),
    lambda value: value["results"][0].update(content=[""]),
    lambda value: value["results"][0].update(content="我去商店买了酱油。"),
])
def test_atomic_event_output_rejects_invalid_structure(mutation):
    payload = valid_payload()
    mutation(payload)
    with pytest.raises(ValueError):
        parse_and_validate(json.dumps(payload, ensure_ascii=False), [1], "2026-08-11")


def test_atomic_event_output_rejects_missing_fields():
    payload = valid_payload()
    payload["results"][0].pop("occurred_time")
    with pytest.raises(ValueError, match="缺少字段: occurred_time"):
        parse_and_validate(json.dumps(payload, ensure_ascii=False), [1], "2026-08-11")


def test_atomic_event_output_normalizes_relaxed_fields(caplog):
    payload = valid_payload()
    payload["extra"] = True
    result_item = payload["results"][0]
    result_item.update(
        title="123456789012345678901",
        content=["  第一段。  ", "第二段。"],
        occurred_on="明天",
        occurred_time="下午",
        unexpected=True,
    )

    result = parse_and_validate(json.dumps(payload, ensure_ascii=False), [1], "2026-08-11")

    assert result[0]["title"] == "12345678901234567890"
    assert result[0]["content"] == ["第一段。", "第二段。"]
    assert result[0]["occurred_on"] == "2026-08-11"
    assert result[0]["occurred_time"] is None
    assert "忽略模型多余字段" in caplog.text
    assert "标题已截断" in caplog.text
    assert "日期已回退" in caplog.text
    assert "时间已置空" in caplog.text


def test_batching_preserves_every_complete_event(monkeypatch):
    monkeypatch.setattr("services.knowledge_workflow.estimate_prompt_tokens", lambda _m, _s, user: len(user))
    events = [
        {"event_no": 1, "title": "A", "body": ["x" * 80]},
        {"event_no": 2, "title": "B", "body": ["y" * 80]},
        {"event_no": 3, "title": "C", "body": ["z" * 400]},
    ]
    batches = plan_event_batches(events, "2026-08-11", "test", 260)
    assert [event_no for batch in batches for event_no in batch] == [1, 2, 3]
    assert batches[-1] == [3]


def test_review_output_accepts_unchanged_candidate_without_issues():
    payload = review_input()
    result = parse_and_validate_review(
        json.dumps(review_output(), ensure_ascii=False),
        payload["items"],
        payload["diary_date"],
    )
    assert result[0]["issues"] == []


def test_review_output_accepts_reported_field_change():
    payload = review_input()
    issues = [{"type": "STATUS_CHANGED", "field": "content", "description": "遗漏了可能状态"}]
    result = parse_and_validate_review(
        json.dumps(review_output(issues=issues, content=["我可能下午去商店买酱油。"]), ensure_ascii=False),
        payload["items"],
        payload["diary_date"],
    )
    assert result[0]["content"] == ["我可能下午去商店买酱油。"]


@pytest.mark.parametrize("output", [
    review_output(content=["我下午去商店买酱油。"]),
    review_output(
        issues=[{"type": "STATUS_CHANGED", "field": "content", "description": "遗漏了可能状态"}],
    ),
])
def test_review_output_rejects_issue_change_inconsistency(output):
    payload = review_input()
    with pytest.raises(ValueError):
        parse_and_validate_review(json.dumps(output, ensure_ascii=False), payload["items"], payload["diary_date"])


def test_review_batching_keeps_source_and_candidate_together(monkeypatch):
    monkeypatch.setattr("services.knowledge_workflow.estimate_prompt_tokens", lambda _m, _s, user: len(user))
    events = [
        {"event_no": 1, "title": "A", "body": ["x" * 80]},
        {"event_no": 2, "title": "B", "body": ["y" * 80]},
    ]
    candidates = {
        event["event_no"]: {
            "event_no": event["event_no"], "title": event["title"], "content": ["结果"],
            "occurred_on": "2026-08-11", "occurred_time": None,
        }
        for event in events
    }
    batches = plan_review_batches(events, candidates, "2026-08-11", "test", 350)
    assert [event_no for batch in batches for event_no in batch] == [1, 2]


def test_review_consistency_failure_retries_full_review_call(monkeypatch):
    payload = review_input()
    invalid = json.dumps(review_output(content=["我下午去商店买酱油。"]), ensure_ascii=False)
    valid = json.dumps(review_output(), ensure_ascii=False)
    responses = iter([invalid, valid])

    async def invoke(*_args, **_kwargs):
        return next(responses)

    monkeypatch.setattr("services.knowledge_ai._invoke", invoke)
    monkeypatch.setattr("services.knowledge_ai.settings.LLM_MAX_ATTEMPTS", 2)
    result = asyncio.run(review_knowledge_events(payload, {}))
    assert result[0]["issues"] == []


def test_review_structure_error_uses_one_json_repair(monkeypatch):
    payload = review_input()
    responses = iter(["not-json", json.dumps(review_output(), ensure_ascii=False)])

    async def invoke(*_args, **_kwargs):
        return next(responses)

    monkeypatch.setattr("services.knowledge_ai._invoke", invoke)
    monkeypatch.setattr("services.knowledge_ai.settings.LLM_MAX_ATTEMPTS", 1)
    result = asyncio.run(review_knowledge_events(payload, {}))
    assert result[0]["content"] == payload["items"][0]["candidate"]["content"]


def test_review_workflow_passes_full_event_and_candidate(monkeypatch):
    payload = review_input()
    captured = {}

    async def review(call_payload, snapshot):
        captured["payload"] = call_payload
        captured["snapshot"] = snapshot
        return [{"issues": [], **call_payload["items"][0]["candidate"]}]

    monkeypatch.setattr("services.knowledge_workflow._set_step", lambda *_args: None)
    monkeypatch.setattr("services.knowledge_workflow._renew_ownership", lambda *_args: None)
    monkeypatch.setattr("services.knowledge_workflow.review_knowledge_events", review)
    state = {
        "task_id": str(uuid4()),
        "frozen_diary_date": payload["diary_date"],
        "frozen_events": [payload["items"][0]["event"]],
        "batch_results": [{"batch_index": 0, "results": [payload["items"][0]["candidate"]]}],
        "review_batches": [[1]],
        "next_review_batch_index": 0,
        "review_batch_results": [],
        "frozen_review_model_config": {"model_name": "review-model"},
    }
    result = asyncio.run(review_batch(state))
    assert captured["payload"]["items"] == payload["items"]
    assert captured["snapshot"] == state["frozen_review_model_config"]
    assert result["next_review_batch_index"] == 1


def test_checkpoint_state_has_no_run_token_or_api_key():
    assert "run_token" not in KnowledgeState.__annotations__
    assert "api_key" not in KnowledgeState.__annotations__
    source = (Path(__file__).parents[1] / "services" / "knowledge_tasks.py").read_text()
    assert 'KnowledgeTask.run_token == run_token' in source
    assert 'KnowledgeTask.status == "RUNNING"' in source


def test_analysis_run_is_not_a_knowledge_source_dependency():
    backend = Path(__file__).parents[1]
    runtime_sources = "\n".join(
        (backend / path).read_text()
        for path in (
            "models/knowledge.py",
            "routers/knowledge.py",
            "services/knowledge_workflow.py",
        )
    )
    assert "source_analysis_run_id" not in runtime_sources
    assert "source_structured_revision" in runtime_sources


def test_knowledge_model_input_only_uses_title_and_body():
    backend = Path(__file__).parents[1]
    workflow = (backend / "services" / "knowledge_workflow.py").read_text()
    router = (backend / "routers" / "knowledge.py").read_text()
    assert '"title": event.event_title or ""' in workflow
    assert '"body": _json_list(event.body)' in workflow
    assert '"feeling": _json_list(event.feeling)' not in workflow
    assert '"reflection": _json_list(event.reflection)' not in workflow
    assert "values = (event.event_title, event.body)" in router


def test_analyzed_diary_accepts_current_structured_events_without_analysis_run():
    organized = SimpleNamespace(id=uuid4(), structured_revision=17)
    event = SimpleNamespace(event_title="当前事件", body=[], feeling=[], reflection=[])
    diary = SimpleNamespace(id=uuid4(), status=DiaryStatus.analyzed)
    assert _source(FakeSourceDb(organized, [event]), diary) is organized


def test_non_analyzed_diary_is_rejected():
    diary = SimpleNamespace(id=uuid4(), status=DiaryStatus.organized)
    with pytest.raises(HTTPException) as error:
        _source(FakeSourceDb(None, []), diary)
    assert error.value.detail["code"] == "DIARY_NOT_ANALYZED"


@pytest.mark.parametrize(("organized", "events", "code", "message"), [
    (None, [], "STRUCTURED_SOURCE_MISSING", "当前日记没有结构化内容"),
    (SimpleNamespace(id=uuid4()), [], "EMPTY_STRUCTURED_DIARY", "结构化日记没有事件"),
    (
        SimpleNamespace(id=uuid4()),
        [SimpleNamespace(event_title="", body=[], feeling=[], reflection=[])],
        "EMPTY_STRUCTURED_EVENT",
        "第 1 个结构化事件为空",
    ),
])
def test_invalid_structured_source_returns_specific_reason(organized, events, code, message):
    diary = SimpleNamespace(id=uuid4(), status=DiaryStatus.analyzed)
    with pytest.raises(HTTPException) as error:
        _source(FakeSourceDb(organized, events), diary)
    assert error.value.detail == {"code": code, "message": message}


def test_knowledge_status_exposes_specific_unavailable_reason():
    backend = Path(__file__).parents[1]
    schema = (backend / "schemas" / "knowledge.py").read_text()
    router = (backend / "routers" / "knowledge.py").read_text()
    assert "unavailable_reason: str | None" in schema
    assert '"unavailable_reason": unavailable_reason' in router


def test_knowledge_event_response_includes_source_context():
    backend = Path(__file__).parents[1]
    schema = (backend / "schemas" / "knowledge.py").read_text()
    router = (backend / "routers" / "knowledge.py").read_text()
    assert "source_diary_date: date" in schema
    assert "source_event_title: str | None" in schema
    assert "Diary.diary_date" in router
    assert "source_event.event_title" in router


def test_knowledge_publish_uses_one_result_per_source_event():
    workflow = (Path(__file__).parents[1] / "services" / "knowledge_workflow.py").read_text()
    assert 'result_by_event[event_no] = result' in workflow
    assert 'result["atomic_events"]' not in workflow
    assert "source_order=0" in workflow
    assert "source_fragments=" not in workflow


def test_drop_analysis_source_migration_rebuilds_current_source_index():
    migration = (Path(__file__).parents[1] / "migrations" / "043_drop_knowledge_analysis_source.sql").read_text()
    assert migration.count("DROP COLUMN source_analysis_run_id") == 2
    assert "ON knowledge_tasks(diary_id, source_structured_revision)" in migration


def test_knowledge_content_array_migration_removes_source_fragments():
    migration = (Path(__file__).parents[1] / "migrations" / "045_knowledge_event_content_array.sql").read_text()
    assert "DROP COLUMN source_fragments" in migration
    assert "ALTER COLUMN content TYPE JSONB" in migration
    assert "to_jsonb(ARRAY[content])" in migration


def test_frozen_model_config_excludes_decrypted_key():
    snapshot = freeze_model_config(RuntimeModelConfig(
        setting_key="knowledge", step_key="knowledge_event_extract", model_type="language",
        protocol="openai_chat", api_base_url="https://example.test", api_key="secret-value",
        model_name="example", channel_model_id=uuid4(),
    ))
    assert "api_key" not in snapshot
    assert "secret-value" not in json.dumps(snapshot)


def test_knowledge_model_request_and_response_are_logged_in_full(monkeypatch):
    runtime = RuntimeModelConfig(
        setting_key="knowledge", step_key="knowledge_event_extract", model_type="language",
        protocol="openai_chat", api_base_url="https://example.test", api_key="secret-value",
        model_name="example", channel_model_id=uuid4(),
    )
    response_payload = {
        "choices": [{"message": {"content": "ok"}}],
        "usage": {},
        "padding": "乙" * (LLM_LOG_BODY_LIMIT + 100),
    }

    class FakeResponse:
        def json(self):
            return response_payload

        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, *_args, **_kwargs):
            return FakeResponse()

    monkeypatch.setattr("services.knowledge_ai._load_runtime_config", lambda _snapshot, _step_key: runtime)
    monkeypatch.setattr("services.knowledge_ai.httpx.AsyncClient", FakeClient)
    monkeypatch.setattr("services.knowledge_ai.record_llm_call", lambda **_kwargs: None)
    logged_messages = []
    monkeypatch.setattr(
        "services.knowledge_ai._ai_logger.info",
        lambda message, *args, **_kwargs: logged_messages.append(message % args),
    )

    user_message = "甲" * (LLM_LOG_BODY_LIMIT + 100)
    assert asyncio.run(_invoke({}, "system", user_message)) == "ok"
    messages = "\n".join(logged_messages)
    assert "LLM 完整请求" in messages
    assert "LLM 完整原始响应" in messages
    assert "已截断，原始长度" not in messages
    assert user_message in messages
    assert response_payload["padding"] in messages
    assert "secret-value" in messages


def test_prompt_and_model_usage_match_current_contract():
    assert "source_fragments" not in SYSTEM_PROMPT
    assert "atomic_events" not in SYSTEM_PROMPT
    assert "content" in SYSTEM_PROMPT
    assert "summary" not in SYSTEM_PROMPT
    assert "摘要" not in SYSTEM_PROMPT
    assert "完整阅读当前事件的 title 和全部 body" in SYSTEM_PROMPT
    assert "只生成一个结果" in SYSTEM_PROMPT
    assert "保留原文明示的每项独立语义" in SYSTEM_PROMPT
    assert "无法判断是否增加新语义时保留" in SYSTEM_PROMPT
    assert "主体、陈述内容、确定程度和完成状态共同组成一项完整语义" in SYSTEM_PROMPT
    assert "状态词所表达的确定程度必须保留" in SYSTEM_PROMPT
    assert "从原文到结果逐项检查" in SYSTEM_PROMPT
    assert "从结果到原文逐项检查" in SYSTEM_PROMPT
    assert "不追求压缩比例" in SYSTEM_PROMPT
    assert "分段只用于提高可读性" in SYSTEM_PROMPT
    assert "压缩表达" not in SYSTEM_PROMPT
    assert "事件主干" not in SYSTEM_PROMPT
    assert "必要背景" not in SYSTEM_PROMPT
    assert "关键过程" not in SYSTEM_PROMPT
    assert "回顾价值" not in SYSTEM_PROMPT
    assert "表达简洁" not in SYSTEM_PROMPT
    assert '"content": [' in SYSTEM_PROMPT
    assert "knowledge" in SETTING_KEYS
    assert STEP_SETTING_KEYS["knowledge_event_extract"] == "knowledge"


def test_review_prompt_and_workflow_match_review_contract():
    assert "event 是判断正确与否的唯一事实依据" in REVIEW_SYSTEM_PROMPT
    assert "从 event 到 candidate 逐项检查" in REVIEW_SYSTEM_PROMPT
    assert "从 candidate 到 event 逐项检查" in REVIEW_SYSTEM_PROMPT
    assert "无法判断某项信息是否可以省略时，判定为遗漏并补回" in REVIEW_SYSTEM_PROMPT
    assert "最小修改不能阻止补回遗漏信息" in REVIEW_SYSTEM_PROMPT
    assert "没有 issue 时，最终字段必须与 candidate 完全一致" in REVIEW_SYSTEM_PROMPT
    assert STEP_SETTING_KEYS["knowledge_event_review"] == "knowledge"
    workflow = (Path(__file__).parents[1] / "services" / "knowledge_workflow.py").read_text()
    assert 'builder.add_node("PREPARE_REVIEW_BATCHES"' in workflow
    assert 'builder.add_node("REVIEW_BATCH"' in workflow
    assert "KnowledgeEventReview(" in workflow


def test_knowledge_review_migration_updates_step_constraint_and_creates_review_table():
    migration = (Path(__file__).parents[1] / "migrations" / "046_knowledge_event_review.sql").read_text()
    assert "PREPARE_REVIEW_BATCHES" in migration
    assert "REVIEW_BATCH" in migration
    assert "CREATE TABLE IF NOT EXISTS knowledge_event_reviews" in migration
    assert "ON DELETE CASCADE" in migration
