"""Fun-ASR HTTP 协议解析测试。"""

import json
import unittest
from unittest.mock import patch

import httpx

from services.fun_asr import FunAsrService
from services.model_runtime import RuntimeModelConfig


class FunAsrServiceTest(unittest.IsolatedAsyncioTestCase):
    def runtime_config(self):
        return RuntimeModelConfig(
            setting_key="transcription",
            model_type="asr",
            protocol="dashscope_asr",
            api_base_url="https://example.test/api/v1",
            api_key="test-key",
            model_name="test-asr-model",
        )

    async def test_submit_builds_async_request(self):
        captured = {}

        def handler(request: httpx.Request):
            captured["headers"] = request.headers
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json={"output": {"task_id": "task-1"}, "request_id": "req-1"})

        service = FunAsrService()
        await service._client.aclose()
        service._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with patch("services.fun_asr.resolve_model_setting", return_value=self.runtime_config()):
            try:
                task = await service.submit("https://files.test/audio")
            finally:
                await service.close()

        self.assertEqual(task.task_id, "task-1")
        self.assertEqual(captured["headers"]["x-dashscope-async"], "enable")
        self.assertEqual(captured["body"]["model"], "test-asr-model")
        self.assertEqual(captured["body"]["input"]["file_urls"], ["https://files.test/audio"])
        self.assertNotIn("vocabulary_id", captured["body"]["parameters"])

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
        with patch("services.fun_asr.resolve_model_setting", return_value=self.runtime_config()):
            try:
                result = await service.query("task-1")
                text = await service.fetch_transcript(result.transcription_url or "")
            finally:
                await service.close()

        self.assertEqual(result.status, "SUCCEEDED")
        self.assertEqual(text, "第一段\n第二段")

    async def test_submit_includes_vocabulary_id_when_present(self):
        captured = {}

        def handler(request: httpx.Request):
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json={"output": {"task_id": "task-vocab"}})

        service = FunAsrService()
        await service._client.aclose()
        service._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with patch("services.fun_asr.resolve_model_setting", return_value=self.runtime_config()):
            try:
                await service.submit("https://files.test/audio", vocabulary_id="vocab-1")
            finally:
                await service.close()

        self.assertEqual(captured["body"]["parameters"]["vocabulary_id"], "vocab-1")

    async def test_vocabulary_create_and_update_requests(self):
        requests = []

        def handler(request: httpx.Request):
            requests.append(json.loads(request.content))
            if request.url.path.endswith("/customization") and requests[-1]["input"]["action"] == "create_vocabulary":
                return httpx.Response(200, json={"output": {"vocabulary_id": "vocab-1"}})
            return httpx.Response(200, json={"output": {}})

        service = FunAsrService()
        await service._client.aclose()
        service._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with patch("services.fun_asr.resolve_model_setting", return_value=self.runtime_config()):
            try:
                vocabulary_id = await service.create_vocabulary(
                    [{"text": "探途趣游", "weight": 4, "lang": "zh"}],
                    "d123456789",
                )
                await service.update_vocabulary(
                    vocabulary_id,
                    [{"text": "codex", "weight": 4, "lang": "zh"}],
                )
            finally:
                await service.close()

        self.assertEqual(vocabulary_id, "vocab-1")
        self.assertEqual(requests[0]["input"]["target_model"], "test-asr-model")
        self.assertEqual(requests[1]["input"]["vocabulary_id"], "vocab-1")


if __name__ == "__main__":
    unittest.main()
