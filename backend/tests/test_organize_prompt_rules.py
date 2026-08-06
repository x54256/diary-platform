import unittest
from pathlib import Path


PROMPT_SOURCE = (Path(__file__).parents[1] / "services" / "ai.py").read_text(encoding="utf-8")


class OrganizePromptRulesTest(unittest.TestCase):
    def test_person_relation_rules_preserve_registered_common_names(self):
        self.assertIn("common_names 是用户确认过的有效称呼", PROMPT_SOURCE)
        self.assertIn("原文使用 common_names 时，必须保留原称呼", PROMPT_SOURCE)
        self.assertIn("只有结合上下文能够明确判断为该人物的识别错误", PROMPT_SOURCE)

    def test_event_text_keeps_plans_after_extraction(self):
        self.assertIn("plans 是从完整事件叙述中提取", PROMPT_SOURCE)
        self.assertIn("仍必须在对应事件的 organized_text 中保留", PROMPT_SOURCE)

    def test_body_is_complete_source_for_derived_fields(self):
        self.assertIn("body 是事件的完整信息源", PROMPT_SOURCE)
        self.assertIn("不得为避免字段重复而删减 body", PROMPT_SOURCE)

    def test_check_prompt_restores_content_removed_by_extraction(self):
        self.assertIn("派生字段抽离正文", PROMPT_SOURCE)
        self.assertIn("允许与派生字段重复", PROMPT_SOURCE)
        self.assertNotIn("例如计划放入正文", PROMPT_SOURCE)
        self.assertNotIn("与事件正文重复表达过多", PROMPT_SOURCE)

    def test_time_markup_rules_preserve_source_text_and_use_context(self):
        self.assertIn("diary_date", PROMPT_SOURCE)
        self.assertIn("结合上下文解析", PROMPT_SOURCE)
        self.assertIn("周一又要开会", PROMPT_SOURCE)
        self.assertIn("无法确定具体日期或时间时，保留原文", PROMPT_SOURCE)

    def test_template_fill_outputs_event_importance(self):
        self.assertIn('"importance": "HIGH|MEDIUM|LOW"', PROMPT_SOURCE)
        self.assertIn('"importance_reason"', PROMPT_SOURCE)

    def test_analysis_prompt_no_longer_generates_importance(self):
        analysis_source = (Path(__file__).parents[1] / "services" / "analysis_pipeline.py").read_text(encoding="utf-8")
        self.assertNotIn('"event_importances"', analysis_source)


if __name__ == "__main__":
    unittest.main()
