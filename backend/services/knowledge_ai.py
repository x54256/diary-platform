"""知识库原子事件提取模型调用与确定性结构校验。"""

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
        return value

    try:
        fallback_date = date.fromisoformat(fallback_occurred_on)
    except (TypeError, ValueError) as exc:
        raise ValueError("日记日期不合法，无法作为原子事件日期回退值") from exc

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
        item = validate_fields(item, {"event_no", "atomic_events"}, f"results[{index}]")
        if type(item["event_no"]) is not int or item["event_no"] != event_nos[index]:
            raise ValueError(f"results[{index}].event_no 顺序不合法")
        atoms = item["atomic_events"]
        if not isinstance(atoms, list) or not atoms:
            raise ValueError(f"results[{index}].atomic_events 必须是非空数组")
        for atom_index, atom in enumerate(atoms):
            path = f"results[{index}].atomic_events[{atom_index}]"
            atom = validate_fields(
                atom,
                {"title", "source_fragments", "content", "occurred_on", "occurred_time"},
                path,
            )
            title, content, fragments = atom["title"], atom["content"], atom["source_fragments"]
            if not isinstance(title, str) or not title.strip():
                raise ValueError(f"{path}.title 不合法")
            title = title.strip()
            if len(title) > 20:
                _ai_logger.warning("[knowledge_event_extract] 原子事件标题已截断: path=%s original_length=%d", path, len(title))
                title = title[:20]
            atom["title"] = title
            if not isinstance(content, str) or not content.strip():
                raise ValueError(f"{path}.content 不合法")
            if not isinstance(fragments, list) or not fragments or any(not isinstance(v, str) or not v.strip() for v in fragments):
                raise ValueError(f"{path}.source_fragments 不合法")
            occurred_on = atom["occurred_on"]
            try:
                normalized_date = date.fromisoformat(occurred_on) if isinstance(occurred_on, str) else None
            except ValueError:
                normalized_date = None
            if normalized_date is None:
                _ai_logger.warning("[knowledge_event_extract] 原子事件日期已回退为日记日期: path=%s invalid_value=%r fallback=%s", path, occurred_on, fallback_date.isoformat())
                normalized_date = fallback_date
            atom["occurred_on"] = normalized_date.isoformat()
            occurred_time = atom["occurred_time"]
            if occurred_time is not None:
                try:
                    normalized_time = datetime.strptime(occurred_time, "%H:%M").strftime("%H:%M") if isinstance(occurred_time, str) else None
                except ValueError:
                    normalized_time = None
                if normalized_time is None:
                    _ai_logger.warning("[knowledge_event_extract] 原子事件时间已置空: path=%s invalid_value=%r", path, occurred_time)
                atom["occurred_time"] = normalized_time
        output.append(item)
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


def _load_runtime_config(snapshot: dict[str, Any]) -> RuntimeModelConfig:
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
            setting_key="knowledge", step_key="knowledge_event_extract",
            model_type=snapshot["model_type"], protocol=snapshot["protocol"],
            api_base_url=snapshot["api_base_url"], api_key=decrypt_channel_key(channel_model.channel),
            model_name=snapshot["model_name"], channel_model_id=channel_model.id,
            reasoning_mode=snapshot.get("reasoning_mode", "unsupported"),
            thinking_enabled=snapshot.get("thinking_enabled"), thinkmode=snapshot.get("thinkmode") or {},
        )
    finally:
        db.close()


async def _invoke(snapshot: dict[str, Any], system_prompt: str, user_message: str) -> str:
    config = _load_runtime_config(snapshot)
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
        "[knowledge_event_extract] LLM 完整请求: url=%s headers=%s body=%s",
        f"{config.api_base_url}/chat/completions", request_headers, body,
        extra=log_extra(
            event="knowledge.llm.request_payload",
            step="knowledge_event_extract",
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
                "[knowledge_event_extract] LLM 完整原始响应: %s",
                response.text,
                extra=log_extra(
                    event="knowledge.llm.response_payload",
                    step="knowledge_event_extract",
                    model=config.model_name,
                ),
            )
            raise
        _ai_logger.info(
            "[knowledge_event_extract] LLM 完整原始响应: %s",
            response_data,
            extra=log_extra(
                event="knowledge.llm.response_payload",
                step="knowledge_event_extract",
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
            step_name="knowledge_event_extract", model_name=config.model_name,
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
