"""阿里云 Fun-ASR HTTP 协议适配。"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from services.model_runtime import ModelRuntimeError, resolve_model_setting

logger = logging.getLogger("fun_asr")


class FunAsrError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class SubmitResultUnknown(FunAsrError):
    pass


@dataclass
class FunAsrTask:
    task_id: str
    request_id: str | None = None


@dataclass
class FunAsrStatus:
    status: str
    transcription_url: str | None = None
    request_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None


class FunAsrService:
    def __init__(self) -> None:
        self._client = httpx.AsyncClient()

    @property
    def base_url(self) -> str:
        return self._runtime_config().api_base_url

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._runtime_config().api_key}"}

    @staticmethod
    def _runtime_config():
        try:
            return resolve_model_setting("transcription")
        except ModelRuntimeError as exc:
            raise FunAsrError("CONFIG_MISSING", str(exc)) from exc

    async def close(self) -> None:
        await self._client.aclose()

    async def submit(self, file_url: str) -> FunAsrTask:
        payload = {
            "model": self._runtime_config().model_name,
            "input": {"file_urls": [file_url]},
            "parameters": {
                "channel_id": [0],
                "language_hints": ["zh"],
                "diarization_enabled": False,
            },
        }
        headers = {**self.headers, "X-DashScope-Async": "enable"}
        for attempt in range(3):
            try:
                self._log_request(
                    "POST",
                    f"{self.base_url}/services/audio/asr/transcription",
                    payload=payload,
                    attempt=attempt + 1,
                )
                response = await self._client.post(
                    f"{self.base_url}/services/audio/asr/transcription",
                    json=payload,
                    headers=headers,
                    timeout=httpx.Timeout(30, connect=10),
                )
                data = self._log_response(response)
            except httpx.ConnectError as exc:
                if attempt == 2:
                    raise FunAsrError("SUBMIT_CONNECT_ERROR", "无法连接语音识别服务") from exc
                await asyncio.sleep(2 ** attempt)
                continue
            except (httpx.ReadTimeout, httpx.RemoteProtocolError) as exc:
                raise SubmitResultUnknown("SUBMIT_RESULT_UNKNOWN", "提交结果未知，请手动重试") from exc
            if response.status_code == 429 or response.status_code >= 500:
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)
                    continue
            self._raise_for_response(response)
            task_id = data.get("output", {}).get("task_id")
            if not task_id:
                raise FunAsrError("INVALID_SUBMIT_RESPONSE", "语音识别服务未返回任务 ID")
            return FunAsrTask(task_id=task_id, request_id=data.get("request_id"))
        raise FunAsrError("SUBMIT_FAILED", "提交语音识别失败")

    async def query(self, task_id: str) -> FunAsrStatus:
        data = await self._request_json(
            "GET",
            f"{self.base_url}/tasks/{task_id}",
            timeout=httpx.Timeout(30, connect=10),
        )
        output = data.get("output", {})
        status = output.get("task_status", "UNKNOWN")
        results = output.get("results") or []
        result = results[0] if results else {}
        return FunAsrStatus(
            status=status,
            transcription_url=result.get("transcription_url") or output.get("transcription_url"),
            request_id=data.get("request_id"),
            error_code=result.get("code") or output.get("code"),
            error_message=result.get("message") or output.get("message"),
        )

    async def fetch_transcript(self, url: str) -> str:
        data = await self._request_json("GET", url, timeout=httpx.Timeout(120, connect=10), auth=False)
        texts = [str(item.get("text", "")).strip() for item in data.get("transcripts", [])]
        text = "\n".join(part for part in texts if part)
        if not text:
            raise FunAsrError("NO_SPEECH_TEXT", "未识别到有效语音")
        return text

    async def _request_json(self, method: str, url: str, timeout: httpx.Timeout, auth: bool = True) -> dict[str, Any]:
        for attempt in range(3):
            try:
                self._log_request(method, url, attempt=attempt + 1)
                response = await self._client.request(
                    method,
                    url,
                    headers=self.headers if auth else None,
                    timeout=timeout,
                )
                data = self._log_response(response)
                if response.status_code == 429 or response.status_code >= 500:
                    raise httpx.HTTPStatusError("retryable", request=response.request, response=response)
                self._raise_for_response(response)
                return data
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                if attempt == 2:
                    raise FunAsrError("PROVIDER_UNAVAILABLE", "语音识别服务暂时不可用") from exc
                await asyncio.sleep(2 ** attempt)
        raise FunAsrError("PROVIDER_UNAVAILABLE", "语音识别服务暂时不可用")

    def _log_request(self, method: str, url: str, payload: dict[str, Any] | None = None, attempt: int = 1) -> None:
        body = self._redact(payload) if payload is not None else None
        logger.info(
            "Fun-ASR 请求 method=%s url=%s attempt=%s body=%s",
            method,
            self._mask_url(url),
            attempt,
            self._dump_json(body),
        )

    def _log_response(self, response: httpx.Response) -> dict[str, Any]:
        try:
            data = response.json()
        except ValueError:
            data = {"raw": response.text}
        logger.info(
            "Fun-ASR 响应 status=%s body=%s",
            response.status_code,
            self._dump_json(self._redact(data)),
        )
        return data

    @classmethod
    def _redact(cls, value: Any) -> Any:
        if isinstance(value, dict):
            redacted: dict[str, Any] = {}
            for key, item in value.items():
                if key.lower() in {"authorization", "api_key", "api-key", "dashscope_api_key"}:
                    redacted[key] = "***"
                else:
                    redacted[key] = cls._redact(item)
            return redacted
        if isinstance(value, list):
            return [cls._redact(item) for item in value]
        if isinstance(value, str):
            return cls._mask_url(value)
        return value

    @staticmethod
    def _mask_url(value: str) -> str:
        if not value.startswith(("http://", "https://")):
            return value
        parsed = urlsplit(value)
        query = "***" if parsed.query else ""
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, ""))

    @staticmethod
    def _dump_json(value: Any) -> str:
        if value is None:
            return ""
        return json.dumps(value, ensure_ascii=False, default=str)

    @staticmethod
    def _raise_for_response(response: httpx.Response) -> None:
        if response.is_success:
            return
        try:
            data = response.json()
        except ValueError:
            data = {}
        logger.info(data)
        message = data.get("message") or f"语音识别服务返回 HTTP {response.status_code}"
        code = data.get("code") or f"HTTP_{response.status_code}"
        raise FunAsrError(str(code), str(message))


fun_asr_service = FunAsrService()
