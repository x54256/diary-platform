"""日记级混合搜索的无数据库单元测试。"""

import unittest
from datetime import date
from unittest.mock import patch

from services.search_service import RRF_K, _rank_diaries, search_diaries


def _event(diary_id, event_id, *, keyword=None, semantic=None):
    value = {
        "diary_id": diary_id, "diary_date": date(2026, 8, 1),
        "keyword_matches": [], "semantic_matches": [],
    }
    if keyword is not None:
        value["keyword_score"] = keyword
    if semantic is not None:
        value["semantic_score"] = semantic
    return event_id, value


class DiaryLevelRankingTest(unittest.TestCase):
    def test_diary_uses_one_best_event_rrf_not_cross_event_score_stitching(self):
        # 日记 A 的关键词和语义分来自不同事件；日记 B 的同一事件双命中应排在 A 前。
        keyword = dict([_event("A", "a-keyword", keyword=0.99), _event("B", "b", keyword=0.80)])
        semantic = dict([_event("A", "a-semantic", semantic=0.99), _event("B", "b", semantic=0.80)])
        ranked = _rank_diaries(keyword, semantic)
        self.assertEqual([item["diary_id"] for item in ranked], ["B", "A"])
        self.assertEqual(ranked[0]["best_event"]["event_id"], "b")
        self.assertAlmostEqual(ranked[0]["best_event"]["rrf_score"], 2 / (RRF_K + 2))

    def test_event_ranking_contains_true_scores_and_ranks(self):
        ranked = _rank_diaries(
            dict([_event("A", "a", keyword=0.9)]),
            dict([_event("A", "a", semantic=0.8)]),
        )
        best = ranked[0]["best_event"]
        self.assertEqual(best["keyword_rank"], 1)
        self.assertEqual(best["semantic_rank"], 1)
        self.assertAlmostEqual(best["rrf_score"], 2 / (RRF_K + 1))
        self.assertEqual(ranked[0]["rrf_rank"], 1)


class SearchStatusTest(unittest.TestCase):
    def test_semantic_failure_keeps_keyword_results_and_returns_unavailable(self):
        keyword = dict([_event("A", "a", keyword=0.9)])
        with patch("services.search_service._keyword_events", return_value=keyword), \
             patch("services.search_service._semantic_events", side_effect=RuntimeError("embedding down")), \
             patch("services.search_service._serialize_results", return_value=[{"diary_id": "A"}]):
            items, total, status = search_diaries(object(), "user", "跑步")
        self.assertEqual(items, [{"diary_id": "A"}])
        self.assertEqual(total, 1)
        self.assertEqual(status, "UNAVAILABLE")

    def test_partial_status_is_exposed_without_disabling_semantic_candidates(self):
        keyword = dict([_event("A", "a", keyword=0.9)])
        semantic = dict([_event("B", "b", semantic=0.9)])
        with patch("services.search_service._keyword_events", return_value=keyword), \
             patch("services.search_service._semantic_events", return_value=semantic), \
             patch("services.search_service._semantic_status", return_value="PARTIAL"), \
             patch("services.search_service._serialize_results", return_value=[{"diary_id": "A"}, {"diary_id": "B"}]):
            items, total, status = search_diaries(object(), "user", "跑步")
        self.assertEqual(total, 2)
        self.assertEqual(status, "PARTIAL")
        self.assertEqual(len(items), 2)
