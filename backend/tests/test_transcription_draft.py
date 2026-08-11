"""未启动语音草稿的恢复规则测试。"""

import unittest
from datetime import date
from types import SimpleNamespace
from uuid import uuid4

from routers.transcriptions import create_batch
from schemas.transcription import TranscriptionBatchCreate


class TranscriptionDraftTest(unittest.TestCase):
    def test_first_upload_batch_preserves_initial_diary_content(self):
        class FakeSession:
            def add(self, batch):
                self.batch = batch

            def commit(self):
                pass

            def refresh(self, batch):
                batch.id = uuid4()
                batch.items = []
                batch.error_message = None
                batch.expires_at = None
                batch.diary_id = None

        db = FakeSession()
        response = create_batch(
            TranscriptionBatchCreate(diary_date=date(2026, 7, 18), base_text="先写下的内容"),
            db,
            SimpleNamespace(id=uuid4()),
        )

        self.assertEqual(db.batch.diary_date, date(2026, 7, 18))
        self.assertEqual(db.batch.base_text, "先写下的内容")
        self.assertEqual(response.diary_date, date(2026, 7, 18))


if __name__ == "__main__":
    unittest.main()
