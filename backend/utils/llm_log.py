"""大模型交互日志的正文截断工具。"""

from __future__ import annotations

import json
from typing import Any


LLM_LOG_BODY_LIMIT = 2_000


def truncate_llm_log(value: Any, limit: int = LLM_LOG_BODY_LIMIT) -> str:
    """转为可读文本，并在超过上限时保留前缀和原始长度。"""
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False, default=str)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}…（已截断，原始长度 {len(text)} 字符）"
