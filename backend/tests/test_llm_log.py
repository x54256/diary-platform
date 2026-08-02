"""大模型日志正文截断规则。"""

import unittest

from utils.llm_log import LLM_LOG_BODY_LIMIT, truncate_llm_log


class LlmLogTest(unittest.TestCase):
    def test_keeps_short_text_unchanged(self):
        self.assertEqual(truncate_llm_log("短文本"), "短文本")

    def test_truncates_long_text_and_keeps_length(self):
        text = "甲" * (LLM_LOG_BODY_LIMIT + 1)
        logged = truncate_llm_log(text)
        self.assertTrue(logged.startswith("甲" * LLM_LOG_BODY_LIMIT + "…"))
        self.assertIn(f"原始长度 {len(text)} 字符", logged)


if __name__ == "__main__":
    unittest.main()
