"""阿里云 Fun-ASR HTTP 协议适配。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import httpx

from config import settings


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
        if settings.DASHSCOPE_API_BASE_URL:
            return settings.DASHSCOPE_API_BASE_URL.rstrip("/")
        if settings.DASHSCOPE_WORKSPACE_ID:
            return f"https://{settings.DASHSCOPE_WORKSPACE_ID}.cn-beijing.maas.aliyuncs.com/api/v1"
        return "https://dashscope.aliyuncs.com/api/v1"

    @property
    def headers(self) -> dict[str, str]:
        if not settings.DASHSCOPE_API_KEY:
            raise FunAsrError("CONFIG_MISSING", "未配置 DASHSCOPE_API_KEY")
        return {"Authorization": f"Bearer {settings.DASHSCOPE_API_KEY}"}

    async def close(self) -> None:
        await self._client.aclose()

    async def submit(self, file_url: str) -> FunAsrTask:
        payload = {
            "model": "fun-asr",
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
                response = await self._client.post(
                    f"{self.base_url}/services/audio/asr/transcription",
                    json=payload,
                    headers=headers,
                    timeout=httpx.Timeout(30, connect=10),
                )
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
            data = response.json()
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
                response = await self._client.request(
                    method,
                    url,
                    headers=self.headers if auth else None,
                    timeout=timeout,
                )
                if response.status_code == 429 or response.status_code >= 500:
                    raise httpx.HTTPStatusError("retryable", request=response.request, response=response)
                self._raise_for_response(response)
                return response.json()
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                if attempt == 2:
                    raise FunAsrError("PROVIDER_UNAVAILABLE", "语音识别服务暂时不可用") from exc
                await asyncio.sleep(2 ** attempt)
        raise FunAsrError("PROVIDER_UNAVAILABLE", "语音识别服务暂时不可用")

    @staticmethod
    def _raise_for_response(response: httpx.Response) -> None:
        if response.is_success:
            return
        try:
            data = response.json()
        except ValueError:
            data = {}
        message = data.get("message") or f"语音识别服务返回 HTTP {response.status_code}"
        code = data.get("code") or f"HTTP_{response.status_code}"
        raise FunAsrError(str(code), str(message))


fun_asr_service = FunAsrService()
