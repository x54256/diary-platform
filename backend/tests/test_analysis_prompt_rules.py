"""日记分析提示词关键约束测试。"""

import unittest

from services.analysis_pipeline import (
    COGNITION_ANALYSIS_RULES,
    CORE_ANALYSIS_RULES,
    FEEDBACK_COGNITION_ANALYSIS_PROMPT,
    FEEDBACK_CORE_ANALYSIS_PROMPT,
)


class CoreAnalysisPromptRuleTest(unittest.TestCase):
    def test_person_relations_are_context_only(self):
        self.assertIn("人物关系参考", CORE_ANALYSIS_RULES)
        self.assertIn("分析时理解人物身份、人物与用户的关系以及指代的参考", CORE_ANALYSIS_RULES)
        self.assertIn("保留原文含义，不强行匹配", CORE_ANALYSIS_RULES)

    def test_role_does_not_default_to_psychological_counseling(self):
        self.assertIn("你是日记复盘分析助手", CORE_ANALYSIS_RULES)
        self.assertNotIn("心理咨询分析助手", CORE_ANALYSIS_RULES)

    def test_evidence_and_empty_results_take_priority(self):
        self.assertIn("证据与留空优先级（优先于下方所有模块目标）", CORE_ANALYSIS_RULES)
        self.assertIn("宁可返回空数组", CORE_ANALYSIS_RULES)
        self.assertIn("准确留空本身就是合格结果", CORE_ANALYSIS_RULES)

    def test_analysis_stays_with_current_evidence_without_personality_diagnosis(self):
        self.assertIn("推断必须能在当前事件中找到事实依据", CORE_ANALYSIS_RULES)
        self.assertIn("不做人格/长期心理结构诊断", CORE_ANALYSIS_RULES)

    def test_missing_evidence_cannot_be_invented(self):
        self.assertIn("所有分析仅以传入的events日记事件列表为唯一事实依据", CORE_ANALYSIS_RULES)
        self.assertIn("无对应线索则对应字段返回空，禁止编造内容硬凑分析", CORE_ANALYSIS_RULES)

    def test_action_suggestions_require_valid_upstream_analysis(self):
        self.assertIn("在前三类分析已经识别出明确调整空间时", CORE_ANALYSIS_RULES)
        self.assertIn("如果事件中没有明确可落地的调整空间、推进动作、表达动作或预防动作，则返回空数组", CORE_ANALYSIS_RULES)
        self.assertIn("不给出辞职/分手等重大高成本决策类建议", CORE_ANALYSIS_RULES)

    def test_diary_level_needs_and_actions_require_cross_event_evidence(self):
        self.assertIn("只梳理多个事件反复出现、或用户明确跨事件总结的关注点与需求", CORE_ANALYSIS_RULES)
        self.assertIn("针对至少两个事件共同呈现的问题给出调整动作", CORE_ANALYSIS_RULES)


class CognitionAnalysisPromptRuleTest(unittest.TestCase):
    def test_calibration_requires_identifiable_error_and_reliable_evidence(self):
        self.assertIn("只有能够同时指出“用户原理解”“更准确的事实或知识”“原理解具体错在哪里”时才输出", COGNITION_ANALYSIS_RULES)
        self.assertIn("指出不准确时必须说明可靠依据", COGNITION_ANALYSIS_RULES)
        self.assertIn("不得编造数据、来源或确定性结论", COGNITION_ANALYSIS_RULES)
        self.assertIn("当事件中没有理解时，直接输出空数组", COGNITION_ANALYSIS_RULES)

    def test_cognitive_enhancement_requires_explicit_user_cognition(self):
        self.assertIn("只有用户明确表达了观点、经验、反思、原则、方法或待完善的理解时才输出", COGNITION_ANALYSIS_RULES)
        self.assertIn("不得从普通行为反向创造“方法论”", COGNITION_ANALYSIS_RULES)

    def test_events_are_isolated(self):
        self.assertIn("禁止把相邻或其他事件中的观点、术语和事实用于事件 N", COGNITION_ANALYSIS_RULES)
        self.assertIn("其他事件只能用于日记级归纳", COGNITION_ANALYSIS_RULES)

    def test_feedback_prompts_inherit_shared_rules(self):
        self.assertIn(CORE_ANALYSIS_RULES, FEEDBACK_CORE_ANALYSIS_PROMPT)
        self.assertIn(COGNITION_ANALYSIS_RULES, FEEDBACK_COGNITION_ANALYSIS_PROMPT)


if __name__ == "__main__":
    unittest.main()
