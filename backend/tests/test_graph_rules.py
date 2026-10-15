"""图谱事实、证据和接口边界的确定性检查。"""

import copy
import unittest

from pydantic import ValidationError
from schemas.graph import HistoryBuildRequest
from services.graph_points import paragraphs, source_units, validate_points, validate_combined, validate_review
from services.graph_relations import validate_pair, equivalent, pair_key, validate_vector
from services.graph_analysis import event_results, feedback_targets, validate_rewrites, CORE_FIELDS
from services.graph_runtime import GraphError


class GraphRulesTest(unittest.TestCase):
    def test_body_json_is_paragraphs_not_characters(self):
        self.assertEqual(paragraphs('["甲。","乙。"]'), [{"id": 1, "text": "甲。"}, {"id": 2, "text": "乙。"}])
        with self.assertRaises(GraphError): paragraphs('"甲。"')

    def test_point_number_rejects_boolean_and_gaps(self):
        data = {"title": "原题", "points": [{"no": True, "summary": "甲", "detail": "甲。"}]}
        with self.assertRaises(ValueError): validate_points(data, {"title": "原题"})
        data["points"][0]["no"] = 2
        with self.assertRaises(ValueError): validate_points(data, {"title": "原题"})

    def test_review_cannot_silently_change_approved_candidate(self):
        event = {"title": "原题", "paragraphs": [{"id": 1, "text": "甲。"}]}
        candidate = {"title": "原题", "points": [{"no": 1, "summary": "甲", "detail": "甲。"}]}
        result = {"review": {"source_checks": [{"source_unit_id": 1, "comparison": "一致"}],
            "checks": [{"no": 1, "summary_ok": True, "detail_ok": True, "issues": []}]}, "candidate": copy.deepcopy(candidate)}
        result["candidate"]["points"][0]["detail"] = "修改。"
        with self.assertRaises(ValueError): validate_combined(result, event, candidate)

    def test_direction_and_evidence_must_belong_to_pair(self):
        events = {"a": {"points": [{"no": 1}]}, "b": {"points": [{"no": 1}]}}
        pair = {"pair_id": pair_key("a", "b"), "event_a_id": "a", "event_b_id": "b"}
        result = {"pair_id": pair["pair_id"], "status": "RELATED", "reason": "两端明确联系", "relation": {
            "source_event_id": "a", "target_event_id": "b", "relation_type": "引发事件", "certainty": "SPECULATIVE",
            "source_point_nos": [1], "target_point_nos": [1], "description": "原文明示推测"}}
        validate_pair(result, pair, events)
        result["relation"]["target_point_nos"] = [2]
        with self.assertRaises(ValueError): validate_pair(result, pair, events)
        result["relation"]["target_point_nos"] = [1]
        result["relation"]["target_event_id"] = "third"
        with self.assertRaises(ValueError): validate_pair(result, pair, events)

    def test_pair_key_is_unordered_without_changing_direction(self):
        self.assertEqual(pair_key("a", "b"), pair_key("b", "a"))
        self.assertFalse(equivalent({"status": "NO_RELATION"}, {"status": "UNRESOLVED"}))

    def test_vector_zero_nonfinite_or_wrong_dimension_rejected(self):
        for value in ([0.0] * 1024, [1.0] * 1023, [float("nan")] * 1024):
            with self.assertRaises(ValueError): validate_vector(value)

    def test_duplicate_titles_are_resolved_by_id(self):
        events = [{"event_id": "a", "title": "同标题"}, {"event_id": "b", "title": "同标题"}]
        rows = [{"event_id": "b", "title": "同标题"}, {"event_id": "a", "title": "同标题"}]
        self.assertEqual([r["event_id"] for r in event_results(rows, events)], ["a", "b"])
        rows[0]["event_id"] = "a"
        with self.assertRaises(ValueError): event_results(rows, events)

    def test_feedback_rewrites_include_diary_and_no_unknown_block(self):
        targets = feedback_targets([{"scope": "EVENT", "event_id": "a", "analysis_type": "EMOTION"}], CORE_FIELDS)
        self.assertEqual(targets, {("EVENT", "a", "EMOTION"), ("DIARY", None, "EMOTION")})
        with self.assertRaises(ValueError): validate_rewrites({"rewrites": []}, targets, CORE_FIELDS)

    def test_history_date_range_and_extra_options(self):
        with self.assertRaises(ValidationError): HistoryBuildRequest(date_from="2026-10-15", date_to="2026-10-14")
        with self.assertRaises(ValidationError): HistoryBuildRequest(date_from="2026-10-14", date_to="2026-10-14", force=True)

    def test_missing_last_source_check_reports_required_ids(self):
        event = {"title": "原题", "paragraphs": [{"id": 1, "text": "甲。乙。"}]}
        candidate = {"title": "原题", "points": [{"no": 1, "summary": "甲乙", "detail": "甲。乙。"}]}
        review = {"source_checks": [{"source_unit_id": 1, "comparison": "一致"}],
            "checks": [{"no": 1, "summary_ok": True, "detail_ok": True, "issues": []}]}
        with self.assertRaisesRegex(ValueError, r"预期\[1, 2\]，实际\[1\]"):
            validate_review(review, event, candidate)

    def test_source_check_id_alias_names_the_required_field_in_retry_error(self):
        event = {"title": "原题", "paragraphs": [{"id": 1, "text": "甲。"}]}
        candidate = {"title": "原题", "points": [{"no": 1, "summary": "甲", "detail": "甲。"}]}
        review = {"source_checks": [{"id": 1, "comparison": "一致"}],
            "checks": [{"no": 1, "summary_ok": True, "detail_ok": True, "issues": []}]}
        with self.assertRaisesRegex(ValueError, "必须使用字段source_unit_id"):
            validate_review(review, event, candidate)
