"""日记分析提示词关键约束测试。"""

import unittest

from services.analysis_pipeline import (
    COGNITION_ANALYSIS_RULES,
    CORE_ANALYSIS_RULES,
    FEEDBACK_COGNITION_ANALYSIS_PROMPT,
    FEEDBACK_CORE_ANALYSIS_PROMPT,
)


class CoreAnalysisPromptRuleTest(unittest.TestCase):
    def test_role_does_not_default_to_psychological_counseling(self):
        self.assertIn("你是日记复盘分析助手", CORE_ANALYSIS_RULES)
        self.assertNotIn("心理咨询分析助手", CORE_ANALYSIS_RULES)

    def test_evidence_and_empty_results_take_priority(self):
        self.assertIn("证据与留空优先级（优先于下方所有模块目标）", CORE_ANALYSIS_RULES)
        self.assertIn("宁可返回空数组", CORE_ANALYSIS_RULES)
        self.assertIn("准确留空本身就是合格结果", CORE_ANALYSIS_RULES)

    def test_single_event_cannot_be_promoted_to_a_stable_pattern(self):
        self.assertIn("不得把单次行为推导为稳定习惯、人格特征或长期模式", CORE_ANALYSIS_RULES)
        self.assertIn("不得将一次行为描述为习惯、依赖或长期倾向", CORE_ANALYSIS_RULES)

    def test_missing_context_and_tools_cannot_be_invented(self):
        self.assertIn("不得补充事件中不存在的工具、资源、流程、历史行为和环境条件", CORE_ANALYSIS_RULES)
        self.assertIn("不得擅自指定 Jira、收藏夹等具体载体", CORE_ANALYSIS_RULES)

    def test_action_suggestions_require_valid_upstream_analysis(self):
        self.assertIn("如果前三类分析均为空，事件级建议也应为空", CORE_ANALYSIS_RULES)
        self.assertIn("不得给出确定诊断、风险物质或治疗动作", CORE_ANALYSIS_RULES)

    def test_diary_level_patterns_require_cross_event_evidence(self):
        self.assertIn("不得用单个事件的情绪代表全天", CORE_ANALYSIS_RULES)
        self.assertIn("只有至少两个事件呈现相同处理方式或决策特征时", CORE_ANALYSIS_RULES)
        self.assertIn("不得把单个普通事件扩大为全天问题", CORE_ANALYSIS_RULES)


class CognitionAnalysisPromptRuleTest(unittest.TestCase):
    def test_calibration_excludes_subjective_experience_and_missing_details(self):
        self.assertIn("不校准情绪、偏好和主观感受", COGNITION_ANALYSIS_RULES)
        self.assertIn("不因为用户没有交代判断、测量或验证过程", COGNITION_ANALYSIS_RULES)
        self.assertIn("信息不足只能说明无法判断，不能反推用户理解错误", COGNITION_ANALYSIS_RULES)

    def test_cognitive_enhancement_requires_explicit_user_cognition(self):
        self.assertIn("普通行为本身不等于用户已经形成认知", COGNITION_ANALYSIS_RULES)
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
