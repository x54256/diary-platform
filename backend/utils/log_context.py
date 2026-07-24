"""日志链路上下文和统一格式。"""

import asyncio
import contextvars
import logging
import time
import uuid
from typing import Any


_chain_id = contextvars.ContextVar("chain_id", default="-")
_request_id = contextvars.ContextVar("request_id", default="-")


def new_id(prefix: str) -> str:
    """生成便于日志检索的链路标识。"""
    return f"{prefix}-{uuid.uuid4().hex[:16]}"


def set_request_context(chain_id: str | None = None, request_id: str | None = None):
    """设置当前请求上下文，返回可用于恢复上下文的 token。"""
    chain_token = _chain_id.set(chain_id or new_id("chain"))
    request_token = _request_id.set(request_id or new_id("req"))
    return chain_token, request_token


def reset_request_context(tokens) -> None:
    chain_token, request_token = tokens
    _request_id.reset(request_token)
    _chain_id.reset(chain_token)


def current_context() -> dict[str, str]:
    return {
        "chain_id": _chain_id.get(),
        "request_id": _request_id.get(),
    }


def log_extra(**fields: Any) -> dict[str, Any]:
    """返回业务日志字段；链路字段由 Filter 自动注入。"""
    return {key: value for key, value in fields.items() if value is not None}


class LogContextFilter(logging.Filter):
    """为所有 Handler 注入链路、进程、线程和 asyncio 任务信息。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.chain_id = _chain_id.get()
        record.request_id = _request_id.get()
        record.async_task = "-"
        try:
            task = asyncio.current_task()
            if task is not None:
                record.async_task = task.get_name() or str(id(task))
        except RuntimeError:
            pass
        return True


class ContextFormatter(logging.Formatter):
    """在普通文本日志后追加业务字段，兼顾人工阅读和检索。"""

    _standard_fields = set(logging.LogRecord(None, 0, "", 0, "", (), None).__dict__)
    _context_fields = {"chain_id", "request_id", "async_task", "event"}

    def format(self, record: logging.LogRecord) -> str:
        message = super().format(record)
        extras = []
        for key, value in record.__dict__.items():
            if key.startswith("_") or key in self._standard_fields or key in self._context_fields:
                continue
            if key in {"message", "asctime"}:
                continue
            extras.append(f"{key}={value}")
        if extras:
            message = f"{message} | {' '.join(extras)}"
        return message


class Stopwatch:
    """简单耗时计时器，避免在日志调用处重复计算。"""

    def __init__(self):
        self.started_at = time.perf_counter()

    def elapsed_ms(self) -> int:
        return int((time.perf_counter() - self.started_at) * 1000)
