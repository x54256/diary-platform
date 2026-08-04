"""行动项规划与同步请求的规则测试。"""

import unittest

from schemas.actions import ActionSchedulePayload
from services.analysis_pipeline import ACTION_PLANNING_PROMPT, _action_planning_input


class ActionPlanningRuleTest(unittest.TestCase):
    def test_prompt_requires_atomization_and_schedule_fields(self):
        self.assertIn("拆分", ACTION_PLANNING_PROMPT)
        self.assertIn("一条行动项只能包含一件", ACTION_PLANNING_PROMPT)
        self.assertIn("start_date", ACTION_PLANNING_PROMPT)
        self.assertIn("analysis_source_keys", ACTION_PLANNING_PROMPT)

    def test_input_assigns_stable_source_keys(self):
        data = _action_planning_input({
            "structured_diary": {"diary_date": "2026-08-03", "plans": ["完成复盘"]},
            "diary_analysis": {"action_suggestions": ["预约体检"]},
            "event_analyses": [{"title": "工作", "action_suggestions": ["拆分需求"]}],
        })
        self.assertEqual(data["plans"][0]["source_key"], "plan:0")
        self.assertEqual(data["action_suggestions"][0]["source_key"], "event:0:suggestion:0")
        self.assertEqual(data["action_suggestions"][1]["source_key"], "diary:suggestion:0")


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
