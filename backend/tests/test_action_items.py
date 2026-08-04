"""行动项规划与同步请求的规则测试。"""

import unittest

from schemas.actions import ActionSchedulePayload
from services.analysis_pipeline import ACTION_PLANNING_PROMPT, _action_planning_input


class ActionPlanningRuleTest(unittest.TestCase):
    def test_prompt_requires_atomization_and_schedule_fields(self):
        self.assertIn("拆分", ACTION_PLANNING_PROMPT)
        self.assertIn("一条行动项只能包含一件", ACTION_PLANNING_PROMPT)
        self.assertIn("start_date", ACTION_PLANNING_PROMPT)
        self.assertIn('"source"', ACTION_PLANNING_PROMPT)
        self.assertIn('"source_key"', ACTION_PLANNING_PROMPT)
        self.assertIn('"text"', ACTION_PLANNING_PROMPT)
        self.assertNotIn('"source_kind"', ACTION_PLANNING_PROMPT)
        self.assertIn("0=周日、1=周一", ACTION_PLANNING_PROMPT)
        self.assertIn("每年 8 月 4 日", ACTION_PLANNING_PROMPT)
        self.assertIn("recurrence_until", ACTION_PLANNING_PROMPT)

    def test_input_assigns_stable_source_keys(self):
        data = _action_planning_input({
            "structured_diary": {"diary_date": "2026-08-03", "plans": ["完成复盘"]},
            "diary_analysis": {"action_suggestions": ["预约体检"]},
            "event_analyses": [{"title": "工作", "action_suggestions": ["拆分需求"]}],
        })
        self.assertTrue(data["plans"][0]["source_key"].startswith("plan:0:"))
        self.assertTrue(data["action_suggestions"][0]["source_key"].startswith("suggestion:event:0:"))
        self.assertTrue(data["action_suggestions"][1]["source_key"].startswith("suggestion:diary:"))


class ActionSchedulePayloadTest(unittest.TestCase):
    def test_all_day_clears_time(self):
        payload = ActionSchedulePayload(start_date="2026-08-03", start_time="09:00", end_time="10:00")
        self.assertIsNone(payload.start_time)
        self.assertIsNone(payload.end_time)

    def test_nth_weekday_requires_complete_rule(self):
        with self.assertRaises(ValueError):
            ActionSchedulePayload(start_date="2026-08-03", recurrence_type="MONTHLY_NTH_WEEKDAY")


if __name__ == "__main__":
    unittest.main()
