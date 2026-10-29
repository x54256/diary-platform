"""隔离 SQLite 验证续接路由，不连接项目数据库。"""

import unittest
from unittest.mock import Mock

from sqlalchemy import create_engine, text

from status import inspect_diary
from db_source import readonly
from workflow import WorkflowError


class WorkflowStatusTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://')
        self.conn = self.engine.connect()
        tables = {
            'diaries': 'id TEXT, user_id TEXT, content_revision INTEGER',
            'diary_organized': 'id TEXT,diary_id TEXT,source_content_revision INTEGER,structured_revision INTEGER',
            'analysis_runs': 'id TEXT,diary_id TEXT,status TEXT,diary_organized_id TEXT,source_structured_revision INTEGER,created_at TEXT',
            'graph_tasks': 'id TEXT,user_id TEXT,status TEXT',
            'graph_runs': 'id TEXT,task_id TEXT,diary_id TEXT,status TEXT',
            'organize_tasks': 'id TEXT,diary_id TEXT,status TEXT',
        }
        for table, columns in tables.items():
            self.conn.exec_driver_sql(f'CREATE TABLE {table} ({columns})')
        self.conn.exec_driver_sql("INSERT INTO diaries VALUES ('d','u',1)")
        self.diary = {'id': 'd', 'diary_date': '2026-10-27', 'status': 'saved',
                      'is_dirty': False, 'runs': []}
        self.validator = Mock(return_value=([{'points': [{'no': 1}]}], {}))

    def tearDown(self):
        self.conn.close()
        self.engine.dispose()

    def organized(self):
        self.conn.exec_driver_sql("INSERT INTO diary_organized VALUES ('o','d',1,2)")
        self.diary['status'] = 'organized'

    def graph(self, state='POINTS_READY'):
        self.diary['runs'] = [{'id': 'g', 'status': state}]

    def analyzed(self, revision=2):
        self.diary['status'] = 'analyzed'
        self.conn.execute(text('INSERT INTO analysis_runs VALUES (:id,:did,:status,:oid,:rev,:at)'),
                          {'id': 'a', 'did': 'd', 'status': 'CURRENT', 'oid': 'o', 'rev': revision, 'at': '2026-10-28'})

    def inspect(self):
        return inspect_diary(self.conn, 'u', self.diary, self.validator)

    def test_saved_starts_with_organizing(self):
        self.assertEqual(self.inspect()['next_stage'], 'organize')

    def test_organized_resumes_points(self):
        self.organized()
        self.assertEqual(self.inspect()['next_stage'], 'points')

    def test_points_ready_resumes_relations(self):
        self.organized(); self.graph()
        result = self.inspect()
        self.assertEqual(result['next_stage'], 'relations')
        self.assertEqual(result['points'], 1)
        self.validator.assert_called_once_with(self.conn, 'u', 'g', published=False)

    def test_published_zero_edges_can_resume_analysis(self):
        self.organized(); self.graph('PUBLISHED')
        self.assertEqual(self.inspect()['next_stage'], 'analyze')
        self.validator.assert_called_once_with(self.conn, 'u', 'g', published=True)

    def test_all_current_results_complete(self):
        self.organized(); self.graph('PUBLISHED'); self.analyzed()
        result = self.inspect()
        self.assertEqual(result['next_stage'], 'complete')
        self.assertEqual(len(result['completed_stages']), 4)

    def test_existing_analysis_does_not_hide_missing_graph(self):
        self.organized(); self.analyzed()
        result = self.inspect()
        self.assertEqual(result['next_stage'], 'points')
        self.assertIn('analyze', result['completed_stages'])

    def test_outdated_analysis_stops_instead_of_regenerating(self):
        self.organized(); self.analyzed(revision=1)
        self.assertTrue(self.inspect()['blocked'])

    def test_dirty_protected_source_stops(self):
        self.organized(); self.graph(); self.diary['is_dirty'] = True
        result = self.inspect()
        self.assertTrue(result['blocked'])
        self.assertIsNone(result['next_stage'])

    def test_multiple_runs_not_chosen_by_recency(self):
        self.organized(); self.graph()
        self.diary['runs'].append({'id': 'g2', 'status': 'PUBLISHED'})
        self.assertTrue(self.inspect()['blocked'])
        self.validator.assert_not_called()

    def test_invalid_points_or_vectors_are_not_skipped(self):
        self.organized(); self.graph('PUBLISHED')
        self.validator.side_effect = WorkflowError('正式要点运行未覆盖全部来源事件')
        self.assertTrue(self.inspect()['blocked'])

    def test_active_task_stops_duplicate_work(self):
        self.conn.exec_driver_sql("INSERT INTO graph_tasks VALUES ('t','u','RUNNING')")
        self.assertEqual(self.inspect()['active_task_ids'], ['t'])

    def test_failed_task_requests_original_packet_recovery(self):
        self.organized()
        self.conn.exec_driver_sql("INSERT INTO graph_tasks VALUES ('t','u','FAILED')")
        self.conn.exec_driver_sql("INSERT INTO graph_runs VALUES ('g','t','d','FAILED')")
        result = self.inspect()
        self.assertTrue(result['blocked'])
        self.assertEqual(result['failed_task_ids'], ['t'])

    def test_query_runs_without_writes_and_readonly_rejects_mutation(self):
        self.organized()
        self.conn.commit()
        before = self.conn.exec_driver_sql('SELECT * FROM diary_organized').all()
        self.conn.rollback()
        with readonly(self.engine) as conn:
            result = inspect_diary(conn, 'u', self.diary, self.validator)
            self.assertEqual(result['next_stage'], 'points')
            with self.assertRaises(Exception):
                conn.exec_driver_sql('DELETE FROM diary_organized')
        after = self.conn.exec_driver_sql('SELECT * FROM diary_organized').all()
        self.assertEqual(before, after)


if __name__ == '__main__':
    unittest.main()
