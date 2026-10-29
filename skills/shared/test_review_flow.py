import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from review_flow import transition, gate, folder_for, read_state


def source(revision=1):
    value = {'kind': 'diary-organized-review', 'schema_version': 1,
             'source': {'user_id': str(uuid4()), 'diary_id': str(uuid4()), 'organized_id': str(uuid4()),
                        'diary_date': '2026-10-29', 'structured_revision': revision},
             'events': [{'event_id': str(uuid4()), 'body': ['正文'], 'feeling': [], 'reflection': []}], 'plans': []}
    return rehash(value)


def rehash(value):
    value = copy.deepcopy(value)
    value.pop('source_sha256', None)
    value['source_sha256'] = hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return value


class ReviewFlowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.value = source()
        self.folder = folder_for(self.value, self.root)
        self.result = {'user_id': self.value['source']['user_id'], 'diary_id': self.value['source']['diary_id'],
                       'diary_date': '2026-10-29', 'completed_stages': ['organize'], 'next_stage': 'points'}
        patcher = patch('review_flow.folder_for', return_value=self.folder)
        patcher.start(); self.addCleanup(patcher.stop)

    def call(self, action, **kwargs):
        return transition(action, self.value, root=self.root, **kwargs)

    def report(self):
        return {'source_sha256': self.value['source_sha256'],
                'reviewed_event_ids': [e['event_id'] for e in self.value['events']],
                'plans_reviewed': True, 'pending_questions': [], 'conclusion': '逐项核对感受、成长与整篇计划，保留人工修改。'}

    def test_cloud_save_receipt_records_atomic_baseline_and_returns_review(self):
        from types import SimpleNamespace
        from skill_api import remote_document
        packet = self.root / 'packet.json'
        packet.write_text(json.dumps({'source': self.value['source']}))
        args = SimpleNamespace(command='save', packet=packet)
        with patch('skill_api.request', return_value={'status': '已提交', 'review_source': self.value}):
            result = remote_document('organize', args, {'write': True})
        self.assertEqual(result['next_stage'], 'review')
        self.assertNotIn('review_source', result)
        self.assertEqual(read_state(self.folder)['baseline'], self.value)
        self.assertEqual(gate(self.result, lambda: self.value)['next_stage'], 'review')

    def test_saved_organization_and_missing_record_cannot_skip_review(self):
        self.assertEqual(gate(self.result, lambda: self.value)['next_stage'], 'review')
        self.call('wait')
        self.assertEqual(gate(self.result, lambda: self.value)['review_phase'], 'waiting_user_review')
        self.assertEqual(read_state(self.folder)['baseline'], self.value)
        with self.assertRaises(ValueError): self.call('finish', report=self.report())
        with self.assertRaises(ValueError): self.call('start', user_message='')

    def test_notification_and_complete_review_release_only_unchanged_source(self):
        self.call('wait'); self.call('start', user_message='已在应用改好，继续')
        self.assertEqual(gate(self.result, lambda: self.value)['next_stage'], 'review')
        self.call('finish', report=self.report())
        self.assertEqual(gate(self.result, lambda: self.value)['next_stage'], 'points')
        modified = copy.deepcopy(self.value); modified['plans'] = ['新增计划']; modified = rehash(modified)
        self.assertEqual(gate(self.result, lambda: modified)['next_stage'], 'review')
        self.assertEqual(gate({**self.result, 'completed_stages': ['organize', 'points'], 'next_stage': 'relations'},
                              lambda: modified)['next_stage'], 'relations')

    def test_pending_questions_and_missing_events_cannot_finish(self):
        self.call('wait'); self.call('start', user_message='审阅完继续')
        for changes in ({'pending_questions': ['尚未确认的感受']}, {'plans_reviewed': False},
                        {'reviewed_event_ids': []}, {'source_sha256': 'stale'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.call('finish', report={**self.report(), **changes})

    def test_changed_source_can_be_reviewed_again_without_overwriting_baseline(self):
        self.call('wait'); baseline = copy.deepcopy(self.value)
        self.value['plans'] = ['新的计划']; self.value = rehash(self.value)
        with self.assertRaises(ValueError): self.call('wait')
        self.call('start', user_message='改好了继续'); self.call('finish', report=self.report())
        self.assertEqual(read_state(self.folder)['baseline'], baseline)
        self.assertEqual(gate(self.result, lambda: self.value)['next_stage'], 'points')
