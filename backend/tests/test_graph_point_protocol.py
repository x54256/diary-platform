"""新版审核的严格边界、复核意见传递和失败恢复。"""

import copy
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from services.graph_points import validate_review, review_with_status, extract_event
from services.graph_runtime import GraphError


SOURCE = {"title": "一次退回", "paragraphs": [{"id": 1, "text": "申请退回一次。"}]}
CANDIDATE = {"title": "一次退回", "points": [{"no": 1, "summary": "申请反复退回", "detail": "申请退回一次。"}]}


def report(issues=None):
    return {"source_checks": [{"source_unit_id": 1, "comparison": "对照原文核对次数"}],
            "checks": [{"no": 1, "issues": copy.deepcopy(issues or [])}]}


ISSUE = {"field": "summary", "candidate_quote": "反复", "source_index": 1,
         "difference": "一次被扩大为多次", "repair": "保留一次"}


class PointProtocolTest(unittest.TestCase):
    def test_status_is_derived_without_mutating_raw_response(self):
        data = report([ISSUE])
        validate_review(data, SOURCE, CANDIDATE, "issues-v2")
        derived = review_with_status(data)
        self.assertFalse(derived["checks"][0]["summary_ok"])
        self.assertTrue(derived["checks"][0]["detail_ok"])
        self.assertNotIn("summary_ok", data["checks"][0])

    def test_new_wire_rejects_model_status_and_unknown_fields(self):
        for key in ("summary_ok", "extra"):
            data = report()
            data["checks"][0][key] = True
            with self.assertRaises(ValueError):
                validate_review(data, SOURCE, CANDIDATE, "issues-v2")

    def test_new_wire_still_rejects_missing_source_and_fabricated_quote(self):
        for data in (dict(report(), source_checks=[]), report([{**ISSUE, "candidate_quote": "申请...退回"}])):
            with self.assertRaises(ValueError):
                validate_review(data, SOURCE, CANDIDATE, "issues-v2")

    def test_legacy_contradictory_status_is_not_silently_repaired(self):
        data = report([ISSUE])
        data["checks"][0].update(summary_ok=True, detail_ok=True)
        with self.assertRaisesRegex(ValueError, "审核状态与问题矛盾"):
            validate_review(data, SOURCE, CANDIDATE)


class PointFeedbackTest(unittest.IsolatedAsyncioTestCase):
    async def test_persistent_issues_stop_after_two_rounds(self):
        class Context:
            config = {"point_review_protocol": "issues-v2"}
            run_id = uuid4()

            def __init__(self):
                self.state, self.calls = {}, []

            def owned(self, db):
                return SimpleNamespace(retry_count=0)

            def save(self, step=None, **changes):
                self.state.update(copy.deepcopy(changes))
                return copy.deepcopy(self.state)

            async def call(self, role, key, payload, validator):
                self.calls.append(role)
                result = copy.deepcopy(CANDIDATE) if role == "point_generate" else (
                    {"review": report([ISSUE]), "candidate": copy.deepcopy(CANDIDATE)}
                    if role == "point_combined" else report([ISSUE]))
                validator(result)
                return result

        ctx = Context()
        event = {"event_id": str(uuid4()), "title": SOURCE["title"], "body": ["申请退回一次。"]}
        with patch("services.graph_points.SessionLocal"):
            with self.assertRaises(GraphError) as raised:
                await extract_event(ctx, event, {})
        self.assertEqual(raised.exception.code, "POINT_REVIEW_FAILED")
        self.assertEqual(ctx.calls, ["point_generate", "point_combined", "point_review",
                                     "point_combined", "point_review"])
        self.assertEqual(ctx.state["point_work"][event["event_id"]]["round"], 2)

    async def test_review_feedback_survives_failure_and_resume(self):
        event_id = str(uuid4())
        initial = copy.deepcopy(CANDIDATE)
        first_fix = copy.deepcopy(initial)
        first_fix["points"][0]["detail"] = "申请退回了一次。"
        final_fix = copy.deepcopy(first_fix)
        final_fix["points"][0]["summary"] = "申请退回一次"

        class Context:
            config = {"point_review_protocol": "issues-v2"}
            run_id = uuid4()

            def __init__(self):
                self.state, self.calls, self.interrupted = {}, [], False

            def owned(self, db):
                return SimpleNamespace(retry_count=0)

            def save(self, step=None, **changes):
                self.state.update(copy.deepcopy(changes))
                return copy.deepcopy(self.state)

            async def call(self, role, key, payload, validator):
                self.calls.append((role, copy.deepcopy(payload)))
                if role == "point_generate":
                    result = initial
                elif role == "point_combined" and key.endswith(":1"):
                    # 首轮发现detail措辞问题，尚未识别summary的次数扩大。
                    issue = {**ISSUE, "field": "detail", "candidate_quote": "退回一次"}
                    result = {"review": report([issue]), "candidate": first_fix}
                elif role == "point_combined":
                    self_test.assertEqual(payload["previous_review"], report([ISSUE]))
                    if not self.interrupted:
                        self.interrupted = True
                        raise RuntimeError("模拟修正请求中断")
                    result = {"review": report([ISSUE]), "candidate": final_fix}
                else:
                    result = report([ISSUE]) if key.endswith(":1") else report()
                validator(result)
                return copy.deepcopy(result)

        self_test = self
        ctx = Context()
        event = {"event_id": event_id, "title": SOURCE["title"], "body": ["申请退回一次。"]}
        with patch("services.graph_points.SessionLocal"):
            with self.assertRaisesRegex(RuntimeError, "模拟修正请求中断"):
                await extract_event(ctx, event, {})
            saved = copy.deepcopy(ctx.state)
            self.assertEqual(saved["point_work"][event_id]["pending_review"], report([ISSUE]))
            result = await extract_event(ctx, event, saved)
        work = result["point_work"][event_id]
        self.assertTrue(work["passed"])
        self.assertEqual(work["points"][0]["summary"], "申请退回一次")
        self.assertEqual(sum(role == "point_generate" for role, _ in ctx.calls), 1)
        self.assertNotIn("previous_review", next(p for r, p in ctx.calls if r == "point_review"))
