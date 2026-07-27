"""ASR 热词构造和指纹测试。"""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from models.voice_profile import HotWord, PersonRelation
from services.asr_vocabulary import build_hotword_entries, hotword_fingerprint
from services.transcription_tasks import TranscriptionTaskManager


class _Query:
    def __init__(self, values):
        self.values = values

    def filter(self, *_args):
        return self

    def all(self):
        return self.values


class _FakeDb:
    def __init__(self, hot_words, people):
        self.hot_words = hot_words
        self.people = people

    def query(self, model):
        return _Query(self.hot_words if model is HotWord else self.people)


class AsrVocabularyTest(unittest.IsolatedAsyncioTestCase):
    def test_builds_all_manual_and_person_names_without_duplicates(self):
        user_id = uuid4()
        entries = build_hotword_entries(
            _FakeDb(
                [SimpleNamespace(text=" codex ")],
                [SimpleNamespace(name="小明", common_names=["明明", "Codex"])],
            ),
            user_id,
        )

        self.assertEqual(
            [entry["text"] for entry in entries],
            ["codex", "小明", "明明"],
        )
        self.assertTrue(all(entry["weight"] == 4 for entry in entries))

    def test_fingerprint_is_order_independent(self):
        first = [{"text": "小明", "weight": 4, "lang": "zh"}, {"text": "codex", "weight": 4, "lang": "zh"}]
        second = list(reversed(first))

        self.assertEqual(hotword_fingerprint(first), hotword_fingerprint(second))

    async def test_batch_reuses_existing_vocabulary_without_resync(self):
        manager = TranscriptionTaskManager()
        with patch.object(manager, "_load_batch_vocabulary_state", return_value=("vocab-1", "fingerprint")), \
                patch.object(manager, "_ensure_user_vocabulary", new_callable=AsyncMock) as ensure_user:
            vocabulary_id = await manager._ensure_batch_vocabulary(uuid4(), uuid4())
            self.assertEqual(vocabulary_id, "vocab-1")
            ensure_user.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
