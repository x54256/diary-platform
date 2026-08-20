"""知识库知识事件提取模型调用与确定性结构校验。"""

import json
import logging
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy.orm import joinedload

from config import settings
from database import SessionLocal
from models.model_config import ChannelModel
from services.llm_metrics import prompt_token_count, record_llm_call
from services.model_management import decrypt_channel_key
from services.model_runtime import RuntimeModelConfig, resolve_thinking_payload
from utils.log_context import log_extra

logger = logging.getLogger(__name__)
_ai_logger = logging.getLogger("ai_pipeline")
SYSTEM_PROMPT = (Path(__file__).resolve().parents[1] / "prompts" / "knowledge_atomic_event.txt").read_text(encoding="utf-8")
REVIEW_SYSTEM_PROMPT = (Path(__file__).resolve().parents[1] / "prompts" / "knowledge_event_review.txt").read_text(encoding="utf-8")
REVIEW_ISSUE_TYPES = {
    "MISSING_INFORMATION",
    "UNSUPPORTED_INFORMATION",
    "ATTRIBUTION_CHANGED",
    "STATUS_CHANGED",
    "RELATION_CHANGED",
    "ORDER_CHANGED",
    "TITLE_MISMATCH",
    "TIME_MISMATCH",
}
REVIEW_FIELDS = {"title", "content", "occurred_on", "occurred_time"}

class KnowledgeAIError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def parse_and_validate(raw: str, event_nos: list[int], fallback_occurred_on: str) -> list[dict[str, Any]]:
    def reject_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"字段重复: {key}")
            result[key] = value
        return result

    def validate_fields(value: Any, expected: set[str], path: str) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError(f"{path} 必须是对象，实际类型: {type(value).__name__}")
        actual = set(value)
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        if missing:
            raise ValueError(f"{path} 字段不匹配（缺少字段: {', '.join(missing)}）")
        if extra:
            _ai_logger.warning("[knowledge_event_extract] 忽略模型多余字段: path=%s fields=%s", path, extra)
            for field in extra:
                del value[field]
        return value

    try:
        fallback_date = date.fromisoformat(fallback_occurred_on)
    except (TypeError, ValueError) as exc:
        raise ValueError("日记日期不合法，无法作为知识事件日期回退值") from exc

    if raw.lstrip().startswith("```"):
        raise ValueError("不能包含 Markdown 代码块")
    data = json.loads(raw, object_pairs_hook=reject_duplicate)
    data = validate_fields(data, {"results"}, "顶层")
    if not isinstance(data["results"], list):
        raise ValueError(f"顶层.results 必须是数组，实际类型: {type(data['results']).__name__}")
    if len(data["results"]) != len(event_nos):
        raise ValueError(f"results 数量与输入事件不一致（期望 {len(event_nos)}，实际 {len(data['results'])}）")
    output: list[dict[str, Any]] = []
    for index, item in enumerate(data["results"]):
        path = f"results[{index}]"
        item = validate_fields(
            item,
            {"event_no", "title", "content", "occurred_on", "occurred_time"},
            path,
        )
        if type(item["event_no"]) is not int or item["event_no"] != event_nos[index]:
            raise ValueError(f"results[{index}].event_no 顺序不合法")
        title, content = item["title"], item["content"]
        if not isinstance(title, str) or not title.strip():
            raise ValueError(f"{path}.title 不合法")
        title = title.strip()
        if len(title) > 20:
            _ai_logger.warning("[knowledge_event_extract] 知识事件标题已截断: path=%s original_length=%d", path, len(title))
            title = title[:20]
        item["title"] = title
        if (
            not isinstance(content, list)
            or not content
            or any(not isinstance(paragraph, str) or not paragraph.strip() for paragraph in content)
        ):
            raise ValueError(f"{path}.content 必须是非空字符串数组")
        item["content"] = [paragraph.strip() for paragraph in content]
        occurred_on = item["occurred_on"]
        try:
            normalized_date = date.fromisoformat(occurred_on) if isinstance(occurred_on, str) else None
        except ValueError:
            normalized_date = None
        if normalized_date is None:
            _ai_logger.warning("[knowledge_event_extract] 知识事件日期已回退为日记日期: path=%s invalid_value=%r fallback=%s", path, occurred_on, fallback_date.isoformat())
            normalized_date = fallback_date
        item["occurred_on"] = normalized_date.isoformat()
        occurred_time = item["occurred_time"]
        if occurred_time is not None:
            try:
                normalized_time = datetime.strptime(occurred_time, "%H:%M").strftime("%H:%M") if isinstance(occurred_time, str) else None
            except ValueError:
                normalized_time = None
            if normalized_time is None:
                _ai_logger.warning("[knowledge_event_extract] 知识事件时间已置空: path=%s invalid_value=%r", path, occurred_time)
            item["occurred_time"] = normalized_time
        output.append(item)
    return output


def parse_and_validate_review(
    raw: str,
    items: list[dict[str, Any]],
    fallback_occurred_on: str,
) -> list[dict[str, Any]]:
    def reject_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"字段重复: {key}")
            result[key] = value
        return result

    def exact_fields(value: Any, expected: set[str], path: str) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError(f"{path} 必须是对象")
        if set(value) != expected:
            raise ValueError(f"{path} 字段不匹配")
        return value

    if raw.lstrip().startswith("```"):
        raise ValueError("不能包含 Markdown 代码块")
    data = json.loads(raw, object_pairs_hook=reject_duplicate)
    data = exact_fields(data, {"results"}, "顶层")
    if not isinstance(data["results"], list) or len(data["results"]) != len(items):
        raise ValueError("results 数量与复核输入不一致")

    event_nos = [item["event"]["event_no"] for item in items]
    for index, item in enumerate(items):
        if item["candidate"].get("event_no") != event_nos[index]:
            raise ValueError(f"items[{index}] 的 event_no 不一致")
    final_payload = {"results": []}
    issues_by_index: list[list[dict[str, Any]]] = []

    def normalize_whitespace(value: str) -> str:
        return "".join(value.split())

    for index, result in enumerate(data["results"]):
        path = f"results[{index}]"
        result = exact_fields(
            result,
            {"event_no", "issues", "title", "content", "occurred_on", "occurred_time"},
            path,
        )
        if type(result["event_no"]) is not int or result["event_no"] != event_nos[index]:
            raise ValueError(f"{path}.event_no 顺序不合法")
        if not isinstance(result["issues"], list):
            raise ValueError(f"{path}.issues 必须是数组")
        normalized_issues: list[dict[str, Any]] = []
        for issue_index, issue in enumerate(result["issues"]):
            issue_path = f"{path}.issues[{issue_index}]"
            if not isinstance(issue, dict):
                raise ValueError(f"{issue_path} 必须是对象")
            unknown_fields = sorted(set(issue) - {"type", "field", "description", "source_quote", "candidate_quote"})
            if unknown_fields or {"type", "field", "description"} - set(issue):
                raise ValueError(f"{issue_path} 字段不匹配")
            if not isinstance(issue["type"], str) or issue["type"] not in REVIEW_ISSUE_TYPES:
                raise ValueError(f"{issue_path}.type 不合法")
            if not isinstance(issue["field"], str) or issue["field"] not in REVIEW_FIELDS:
                raise ValueError(f"{issue_path}.field 不合法")
            if not isinstance(issue["description"], str) or not issue["description"].strip():
                raise ValueError(f"{issue_path}.description 不合法")
            normalized_issue: dict[str, Any] = {
                "type": issue["type"],
                "field": issue["field"],
                "description": issue["description"].strip(),
            }
            source_quote: str | None = None
            if "source_quote" in issue:
                raw_source_quote = issue["source_quote"]
                if isinstance(raw_source_quote, str) and raw_source_quote.strip():
                    source_quote = raw_source_quote.strip()
                    normalized_issue["source_quote"] = source_quote
                else:
                    _ai_logger.warning("[knowledge_event_review] issue 证据字段不合法，已忽略: path=%s field=source_quote", issue_path)
            if "candidate_quote" in issue:
                raw_candidate_quote = issue["candidate_quote"]
                if raw_candidate_quote is None:
                    normalized_issue["candidate_quote"] = None
                elif isinstance(raw_candidate_quote, str) and raw_candidate_quote.strip():
                    normalized_issue["candidate_quote"] = raw_candidate_quote.strip()
                else:
                    _ai_logger.warning("[knowledge_event_review] issue 证据字段不合法，已忽略: path=%s field=candidate_quote", issue_path)
                    normalized_issue["candidate_quote"] = None
            if source_quote:
                event = items[index]["event"]
                segments = [str(event.get("title") or "")] + [str(paragraph) for paragraph in (event.get("body") or [])]
                normalized_quote = normalize_whitespace(source_quote)
                if not any(normalized_quote in normalize_whitespace(segment) for segment in segments):
                    _ai_logger.warning(
                        "[knowledge_event_review] source_quote 不在 event 原文中: path=%s event_no=%s source_quote=%s",
                        issue_path, event_nos[index], source_quote,
                    )
            normalized_issues.append(normalized_issue)
        issues_by_index.append(normalized_issues)
        final_payload["results"].append({key: result[key] for key in ("event_no", "title", "content", "occurred_on", "occurred_time")})

    normalized_finals = parse_and_validate(
        json.dumps(final_payload, ensure_ascii=False),
        event_nos,
        fallback_occurred_on,
    )
    output: list[dict[str, Any]] = []
    ordered_fields = ("title", "content", "occurred_on", "occurred_time")
    for index, final in enumerate(normalized_finals):
        candidate = items[index]["candidate"]
        issues = issues_by_index[index]
        changed_fields = {field for field in ordered_fields if final[field] != candidate[field]}
        issue_fields = {issue["field"] for issue in issues}
        if not issues and changed_fields:
            _ai_logger.warning(
                "[knowledge_event_review] 一致性违规（无 issue 但修改了字段），采纳模型修改后的最终结果: event_no=%s changed_fields=%s",
                final["event_no"], sorted(changed_fields),
            )
        if issues and not issue_fields.issubset(changed_fields):
            _ai_logger.warning(
                "[knowledge_event_review] 一致性违规（报告 issue 但对应字段未修改）: event_no=%s issue_fields=%s changed_fields=%s",
                final["event_no"], sorted(issue_fields), sorted(changed_fields),
            )
        if issues and not changed_fields.issubset(issue_fields):
            _ai_logger.warning(
                "[knowledge_event_review] 一致性违规（修改字段但未报告对应 issue），采纳模型修改后的最终结果: event_no=%s changed_fields=%s issue_fields=%s",
                final["event_no"], sorted(changed_fields), sorted(issue_fields),
            )
        output.append({"event_no": final["event_no"], "issues": issues, **{field: final[field] for field in ordered_fields}})
    return output


def freeze_model_config(config: RuntimeModelConfig) -> dict[str, Any]:
    if not config.channel_model_id:
        raise KnowledgeAIError("KNOWLEDGE_MODEL_NOT_CONFIGURED", "知识沉淀模型未配置")
    return {
        "channel_model_id": str(config.channel_model_id),
        "model_type": config.model_type,
        "protocol": config.protocol,
        "api_base_url": config.api_base_url,
        "model_name": config.model_name,
        "reasoning_mode": config.reasoning_mode,
        "thinking_enabled": config.thinking_enabled,
        "thinkmode": config.thinkmode or {},
    }


def _load_runtime_config(snapshot: dict[str, Any], step_key: str = "knowledge_event_extract") -> RuntimeModelConfig:
    db = SessionLocal()
    try:
        channel_model = (
            db.query(ChannelModel)
            .options(joinedload(ChannelModel.channel), joinedload(ChannelModel.model))
            .filter(ChannelModel.id == UUID(snapshot["channel_model_id"]))
            .first()
        )
        if not channel_model or not channel_model.enabled or not channel_model.channel.enabled:
            raise KnowledgeAIError("LLM_CALL_FAILED", "冻结的知识沉淀模型不可用")
        return RuntimeModelConfig(
            setting_key="knowledge", step_key=step_key,
            model_type=snapshot["model_type"], protocol=snapshot["protocol"],
            api_base_url=snapshot["api_base_url"], api_key=decrypt_channel_key(channel_model.channel),
            model_name=snapshot["model_name"], channel_model_id=channel_model.id,
            reasoning_mode=snapshot.get("reasoning_mode", "unsupported"),
            thinking_enabled=snapshot.get("thinking_enabled"), thinkmode=snapshot.get("thinkmode") or {},
        )
    finally:
        db.close()


async def _invoke(
    snapshot: dict[str, Any],
    system_prompt: str,
    user_message: str,
    step_key: str = "knowledge_event_extract",
) -> str:
    config = _load_runtime_config(snapshot, step_key)
    body: dict[str, Any] = {
        "model": config.model_name,
        "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_message}],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    thinking = resolve_thinking_payload(config)
    if thinking:
        body.update(thinking)
    request_headers = {"Authorization": f"Bearer {config.api_key}"}
    _ai_logger.info(
        "[%s] LLM 完整请求: url=%s headers=%s body=%s",
        step_key,
        f"{config.api_base_url}/chat/completions", request_headers, body,
        extra=log_extra(
            event="knowledge.llm.request_payload",
            step=step_key,
            model=config.model_name,
        ),
    )
    started = time.monotonic()
    response_data: dict[str, Any] | None = None
    status = "failed"
    error_type: str | None = None
    try:
        async with httpx.AsyncClient(timeout=1200.0) as client:
            response = await client.post(
                f"{config.api_base_url}/chat/completions",
                headers=request_headers, json=body,
            )
        try:
            response_data = response.json()
        except Exception:
            _ai_logger.info(
                "[%s] LLM 完整原始响应: %s",
                step_key,
                response.text,
                extra=log_extra(
                    event="knowledge.llm.response_payload",
                    step=step_key,
                    model=config.model_name,
                ),
            )
            raise
        _ai_logger.info(
            "[%s] LLM 完整原始响应: %s",
            step_key,
            response_data,
            extra=log_extra(
                event="knowledge.llm.response_payload",
                step=step_key,
                model=config.model_name,
            ),
        )
        response.raise_for_status()
        content = response_data["choices"][0]["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise KnowledgeAIError("MODEL_OUTPUT_INVALID", "模型未返回有效正文")
        status = "success"
        return content
    except Exception as exc:
        error_type = type(exc).__name__
        raise
    finally:
        prompt_tokens, source = prompt_token_count(response_data, config.model_name, system_prompt, user_message)
        usage = response_data.get("usage", {}) if isinstance(response_data, dict) else {}
        completion = usage.get("completion_tokens") or usage.get("output_tokens")
        record_llm_call(
            step_name=step_key, model_name=config.model_name,
            prompt_tokens=prompt_tokens, prompt_tokens_source=source,
            duration_ms=int((time.monotonic() - started) * 1000), status=status,
            error_type=error_type, completion_tokens=completion if isinstance(completion, int) else None,
        )


async def extract_atomic_events(payload: dict[str, Any], snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    event_nos = [item["event_no"] for item in payload["events"]]
    fallback_occurred_on = payload["diary_date"]
    user_message = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    last_error: Exception | None = None
    repair_used = False
    for attempt in range(1, settings.LLM_MAX_ATTEMPTS + 1):
        try:
            raw = await _invoke(snapshot, SYSTEM_PROMPT, user_message)
            try:
                return parse_and_validate(raw, event_nos, fallback_occurred_on)
            except (json.JSONDecodeError, ValueError) as validation_error:
                _ai_logger.error(
                    "[knowledge_event_extract] 模型输出校验失败: phase=initial error=%s raw_response=%s",
                    str(validation_error), raw,
                    extra=log_extra(
                        event="knowledge.llm.validation_failed",
                        step="knowledge_event_extract",
                        phase="initial",
                        error_type=type(validation_error).__name__,
                    ),
                )
                if repair_used:
                    raise KnowledgeAIError("MODEL_OUTPUT_INVALID", f"模型输出结构不合法: {validation_error}") from validation_error
                repair_used = True
                repair_prompt = "你是 JSON 结构修复器。只修复给定响应的 JSON 和字段结构，不改变内容语义；严格输出符合目标结构的 JSON。"
                repair_message = json.dumps({
                    "target": {"event_nos": event_nos},
                    "invalid_response": raw,
                    "validation_error": str(validation_error),
                }, ensure_ascii=False, separators=(",", ":"))
                repaired = await _invoke(snapshot, repair_prompt, repair_message)
                try:
                    return parse_and_validate(repaired, event_nos, fallback_occurred_on)
                except (json.JSONDecodeError, ValueError) as exc:
                    _ai_logger.error(
                        "[knowledge_event_extract] 模型输出校验失败: phase=repair error=%s raw_response=%s",
                        str(exc), repaired,
                        extra=log_extra(
                            event="knowledge.llm.validation_failed",
                            step="knowledge_event_extract",
                            phase="repair",
                            error_type=type(exc).__name__,
                        ),
                    )
                    raise KnowledgeAIError("MODEL_OUTPUT_INVALID", f"模型输出结构修复后仍不合法: {exc}") from exc
        except KnowledgeAIError:
            raise
        except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError, KeyError, TypeError, ValueError) as exc:
            last_error = exc
            if attempt < settings.LLM_MAX_ATTEMPTS:
                logger.warning("知识提取模型调用失败并重试", extra={"attempt": attempt, "error_type": type(exc).__name__})
    raise KnowledgeAIError("LLM_CALL_FAILED", "知识提取模型调用失败") from last_error


async def review_knowledge_events(payload: dict[str, Any], snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    items = payload["items"]
    event_nos = [item["event"]["event_no"] for item in items]
    user_message = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    last_error: Exception | None = None
    repair_used = False
    for attempt in range(1, settings.LLM_MAX_ATTEMPTS + 1):
        try:
            raw = await _invoke(snapshot, REVIEW_SYSTEM_PROMPT, user_message, "knowledge_event_review")
            try:
                return parse_and_validate_review(raw, items, payload["diary_date"])
            except (json.JSONDecodeError, ValueError) as validation_error:
                if repair_used:
                    raise KnowledgeAIError("MODEL_OUTPUT_INVALID", f"复核输出结构不合法: {validation_error}") from validation_error
                repair_used = True
                repair_prompt = "你是 JSON 结构修复器。只修复给定响应的 JSON 和字段结构，不改变内容语义；严格输出符合目标结构的 JSON。"
                repair_message = json.dumps({
                    "target": {"event_nos": event_nos},
                    "invalid_response": raw,
                    "validation_error": str(validation_error),
                }, ensure_ascii=False, separators=(",", ":"))
                repaired = await _invoke(snapshot, repair_prompt, repair_message, "knowledge_event_review")
                try:
                    return parse_and_validate_review(repaired, items, payload["diary_date"])
                except (json.JSONDecodeError, ValueError) as exc:
                    raise KnowledgeAIError("MODEL_OUTPUT_INVALID", f"复核输出结构修复后仍不合法: {exc}") from exc
        except KnowledgeAIError:
            raise
        except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError, KeyError, TypeError, ValueError) as exc:
            last_error = exc
            if attempt < settings.LLM_MAX_ATTEMPTS:
                logger.warning("知识复核模型调用失败并重试", extra={"attempt": attempt, "error_type": type(exc).__name__})
    raise KnowledgeAIError("LLM_CALL_FAILED", "知识复核模型调用失败") from last_error
