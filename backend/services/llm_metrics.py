"""LLM 调用 token 和耗时统计。"""

import json
import logging
from typing import Any

logger = logging.getLogger("llm.metrics")


def _usage_value(response: Any, key: str) -> int | None:
    """兼容 LangChain response_metadata 和 usage_metadata 两种结构。"""
    if isinstance(response, dict):
        metadata_values = (response.get("usage_metadata"), response.get("response_metadata"), response)
    else:
        metadata_values = (
            getattr(response, "usage_metadata", None),
            getattr(response, "response_metadata", None),
        )
    for metadata in (
        *metadata_values,
    ):
        if not isinstance(metadata, dict):
            continue
        usage = metadata.get("token_usage") or metadata.get("usage") or metadata
        if isinstance(usage, dict):
            value = usage.get(key)
            if value is None and key == "prompt_tokens":
                value = usage.get("input_tokens")
            if isinstance(value, int):
                return value
    return None


def estimate_prompt_tokens(model_name: str | None, system_prompt: str, user_message: str) -> int:
    """在服务商未返回 usage 时，按模型编码估算输入 token。"""
    payload = json.dumps(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        ensure_ascii=False,
    )
    try:
        import tiktoken

        try:
            encoding = tiktoken.encoding_for_model(model_name or "")
        except (KeyError, ValueError):
            encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(payload))
    except ModuleNotFoundError:
        # 生产依赖中包含 tiktoken；保留无依赖测试/诊断环境的可用性。
        return max(1, len(payload) // 4)


def prompt_token_count(response: Any, model_name: str | None, system_prompt: str, user_message: str) -> tuple[int, str]:
    """返回输入 token 数及其来源。"""
    usage = _usage_value(response, "prompt_tokens")
    if usage is not None:
        return usage, "usage"
    return estimate_prompt_tokens(model_name, system_prompt, user_message), "estimated"


def record_llm_call(
    *,
    step_name: str,
    model_name: str | None,
    prompt_tokens: int,
    prompt_tokens_source: str,
    duration_ms: int,
    status: str,
    error_type: str | None = None,
) -> None:
    """独立事务保存一次调用；统计失败不得影响主业务。"""
    from database import SessionLocal
    from models.llm_call import LlmCallLog
    from utils.log_context import current_context

    db = SessionLocal()
    try:
        context = current_context()
        db.add(LlmCallLog(
            step_name=step_name or "unknown",
            model_name=model_name,
            prompt_tokens=prompt_tokens,
            prompt_tokens_source=prompt_tokens_source,
            duration_ms=duration_ms,
            status=status,
            error_type=error_type,
            request_id=context["request_id"],
            chain_id=context["chain_id"],
        ))
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("保存 LLM 调用统计失败")
    finally:
        db.close()
