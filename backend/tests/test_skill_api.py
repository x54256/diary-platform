"""固定 Token、操作边界及错误回执；不连接数据库。"""
import json
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from config import settings
from routers.skill_api import router
from services.skill_worker import check_identity


class SkillApiTest(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(router, prefix='/diary')
        self.client = TestClient(app)
        self.token = patch.object(settings, 'SKILL_API_TOKEN', 'test-only')
        self.token.start()
        self.addCleanup(self.token.stop)
        self.headers = {'Authorization': 'Bearer test-only'}

    def post(self, path='workflow/status', body=None, headers=None):
        return self.client.post('/diary/api/skills/' + path, json=body or {},
                                headers=self.headers if headers is None else headers)

    @patch('routers.skill_api.subprocess.run')
    def test_disabled_or_wrong_token_never_starts_worker(self, run):
        for headers in ({}, {'Authorization': 'Bearer wrong'}, {'Authorization': 'Basic test-only'}):
            self.assertEqual(self.post(headers=headers).status_code, 401)
        with patch.object(settings, 'SKILL_API_TOKEN', ''):
            self.assertEqual(self.post().status_code, 503)
        run.assert_not_called()

    @patch('routers.skill_api.subprocess.run')
    def test_allowlist_rejects_sql_shell_and_schema_writes(self, run):
        for path in ('sql/execute', 'workflow/../../shell', 'points/execute'):
            self.assertEqual(self.post(path).status_code, 404)
        self.assertEqual(self.post('points/schema', {'params': {'write': True}}).status_code, 400)
        run.assert_not_called()

    @patch('routers.skill_api.subprocess.run')
    def test_worker_only_receives_fixed_entry_and_returns_receipt(self, run):
        run.return_value = SimpleNamespace(returncode=0, stdout=json.dumps({'ok': True, 'result': {'next_stage': 'points'}}))
        response = self.post(body={'params': {'date': '2026-10-29'}})
        self.assertEqual(response.json(), {'next_stage': 'points'})
        argv = run.call_args.args[0]
        self.assertEqual(argv[1:], ['-m', 'services.skill_worker'])
        self.assertNotIn('test-only', run.call_args.kwargs['input'])

    @patch('routers.skill_api.subprocess.run')
    def test_timeout_tells_client_to_query_original_state(self, run):
        run.side_effect = subprocess.TimeoutExpired('fixed-worker', 900)
        response = self.post()
        self.assertEqual(response.status_code, 504)
        self.assertIn('先查询原任务状态', response.json()['detail'])

    @patch('routers.skill_api.subprocess.run')
    def test_invalid_worker_output_is_not_exposed(self, run):
        run.return_value = SimpleNamespace(returncode=1, stdout='private-data')
        response = self.post()
        self.assertEqual(response.status_code, 500)
        self.assertNotIn('private-data', response.text)

    def test_identity_checks_nested_history_and_packages(self):
        check_identity({'items': [{'source': {'user_id': 'owner', 'username': 'x5456'}}]}, 'owner', 'x5456')
        for value in ({'snapshot': {'events': {'E1': {'user_id': 'other'}}}}, {'username': 'other'}):
            with self.assertRaises(ValueError): check_identity(value, 'owner', 'x5456')


if __name__ == '__main__': unittest.main()
