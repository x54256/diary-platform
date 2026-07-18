"""语音转写顺序规则测试。"""

import unittest
from types import SimpleNamespace

from services.transcription_tasks import compose_transcription_text


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


if __name__ == "__main__":
    unittest.main()
