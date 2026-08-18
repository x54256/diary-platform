"""语音转写顺序规则测试。"""

import unittest
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from services.transcription_tasks import TranscriptionTaskManager, compose_transcription_text


class TranscriptionOrderTest(unittest.TestCase):
    def test_composes_transcripts_by_sort_order_not_completion_order(self):
        items = [
            SimpleNamespace(sort_order=2, transcript_text="第三段"),
            SimpleNamespace(sort_order=0, transcript_text="第一段"),
            SimpleNamespace(sort_order=1, transcript_text="第二段"),
        ]

        self.assertEqual(
            compose_transcription_text("原始文本", items),
            "原始文本\n\n第一段\n\n第二段\n\n第三段",
        )

    def test_finalizes_batch_that_already_has_a_diary(self):
        diary = SimpleNamespace(
            id=uuid4(),
            deleted_at=None,
            original_text="",
            diary_date=None,
            content_revision=1,
            is_dirty=True,
        )
        item = SimpleNamespace(status="SUCCEEDED", sort_order=0, transcript_text="转写内容")
        batch = SimpleNamespace(
            id=uuid4(),
            user_id=uuid4(),
            diary_id=diary.id,
            diary=diary,
            diary_date=None,
            base_text="",
            status="PROCESSING",
            completed_at=None,
            expires_at=None,
            items=[item],
        )

        class FakeQuery:
            def filter_by(self, **_kwargs):
                return self

            def with_for_update(self):
                return self

            def first(self):
                return batch

        class FakeSession:
            committed = False

            def query(self, _model):
                return FakeQuery()

            def commit(self):
                self.committed = True

            def rollback(self):
                pass

            def close(self):
                pass

        db = FakeSession()
        with patch("services.transcription_tasks.SessionLocal", return_value=db):
            TranscriptionTaskManager.finalize_batch(batch.id)

        self.assertTrue(db.committed)
        self.assertEqual(batch.status, "COMPLETED")
        self.assertIsNotNone(batch.completed_at)
        self.assertEqual(diary.original_text, "转写内容")
        self.assertEqual(diary.content_revision, 2)
        self.assertFalse(diary.is_dirty)
        self.assertIsNone(item.transcript_text)


if __name__ == "__main__":
    unittest.main()
