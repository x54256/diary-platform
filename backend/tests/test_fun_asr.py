"""Fun-ASR HTTP 协议解析测试。"""

import json
import unittest

import httpx

from config import settings
from services.fun_asr import FunAsrService


class FunAsrServiceTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.original_key = settings.DASHSCOPE_API_KEY
        self.original_base = settings.DASHSCOPE_API_BASE_URL
        self.original_model = settings.TRANSCRIPTION_MODEL
        settings.DASHSCOPE_API_KEY = "test-key"
        settings.DASHSCOPE_API_BASE_URL = "https://example.test/api/v1"
        settings.TRANSCRIPTION_MODEL = "test-asr-model"

    async def asyncTearDown(self):
        settings.DASHSCOPE_API_KEY = self.original_key
        settings.DASHSCOPE_API_BASE_URL = self.original_base
        settings.TRANSCRIPTION_MODEL = self.original_model

    async def test_submit_builds_async_request(self):
        captured = {}

        def handler(request: httpx.Request):
            captured["headers"] = request.headers
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json={"output": {"task_id": "task-1"}, "request_id": "req-1"})

        service = FunAsrService()
        await service._client.aclose()
        service._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            task = await service.submit("https://files.test/audio")
        finally:
            await service.close()

        self.assertEqual(task.task_id, "task-1")
        self.assertEqual(captured["headers"]["x-dashscope-async"], "enable")
        self.assertEqual(captured["body"]["model"], "test-asr-model")
        self.assertEqual(captured["body"]["input"]["file_urls"], ["https://files.test/audio"])

    async def test_query_and_result_text_parsing(self):
        def handler(request: httpx.Request):
            if request.url.path.endswith("/tasks/task-1"):
                return httpx.Response(200, json={
                    "output": {"task_status": "SUCCEEDED", "results": [{"transcription_url": "https://result.test/data"}]},
                    "request_id": "req-2",
                })
            return httpx.Response(200, json={"transcripts": [{"text": "第一段"}, {"text": "第二段"}]})

        service = FunAsrService()
        await service._client.aclose()
        service._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            result = await service.query("task-1")
            text = await service.fetch_transcript(result.transcription_url or "")
        finally:
            await service.close()

        self.assertEqual(result.status, "SUCCEEDED")
        self.assertEqual(text, "第一段\n第二段")


if __name__ == "__main__":
    unittest.main()
