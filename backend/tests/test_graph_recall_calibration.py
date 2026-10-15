"""校准参数的候选上限与同日比较边界。"""

import unittest
from scripts.calibrate_layer1_recall import select_pairs
from scripts.recheck_graph_quality import validate_result


class RecallCalibrationTest(unittest.TestCase):
    def test_extra_adjudication_id_reports_expected_and_actual(self):
        pairs = [{'pair_id': 'P039', 'event_a_id': 'a', 'event_b_id': 'b'}]
        valid = {'pair_id': 'P039', 'status': 'NO_RELATION', 'reason': '无关联', 'relation': None}
        validate_result({'results': [valid]}, pairs, {})
        with self.assertRaisesRegex(AssertionError, "预期.*P039.*实际.*P039_dup"):
            validate_result({'results': [valid, {**valid, 'pair_id': 'P039_dup'}]}, pairs, {})

    def setUp(self):
        self.rows = [{'pair_id':f'h{i}', 'current_id':'today', 'history_id':f'h{i}',
                      'same_day':False, 'similarity':score} for i,score in
                     enumerate([0.8,0.7,0.6,0.5,0.42,0.41,0.1])]
        self.rows.append({'pair_id':'same-day','current_id':'today','history_id':'peer',
                          'same_day':True,'similarity':-0.2})

    def test_looser_threshold_does_not_exceed_five_history_events(self):
        self.assertEqual(select_pairs(self.rows, {'today':{}}, 0.5),
                         {'h0','h1','h2','h3','same-day'})
        expected = {'h0','h1','h2','h3','h4','same-day'}
        self.assertEqual(select_pairs(self.rows, {'today':{}}, 0.4), expected)
        self.assertEqual(select_pairs(self.rows, {'today':{}}, None), expected)

    def test_tie_uses_history_id_and_same_day_is_not_filtered(self):
        self.rows[5]['similarity'] = 0.42
        ids = select_pairs(list(reversed(self.rows)), {'today':{}}, None)
        self.assertIn('h4', ids)
        self.assertNotIn('h5', ids)
        self.assertIn('same-day', ids)
