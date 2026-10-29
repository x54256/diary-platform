"""云端传输、纯标准库命令入口及上传文件边界。"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from skill_api import ApiError, api_enabled, request
from skill_files import read_bytes, uploaded_files

ROOT = Path(__file__).resolve().parents[2]


class BridgeTest(unittest.TestCase):
    def setUp(self):
        self.calls = []
        calls = self.calls
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                calls.append((self.path, self.headers.get('Authorization'), body))
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'read_only': True}).encode())
            def log_message(self, *args): pass
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.env = {'DIARY_DATA_MODE': 'api', 'DIARY_API_BASE_URL': f'http://127.0.0.1:{self.server.server_port}/diary/api',
                    'DIARY_API_TOKEN': 'test-token-only'}
        self.context = patch.dict(os.environ, self.env)
        self.context.start()

    def tearDown(self):
        self.context.stop()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def test_each_request_carries_token_and_utf8_content(self):
        for _ in range(2):
            request('analyze', 'prepare', {'diary_id': 'example'}, {'/cloud/分析稿.md': '已确认稿'})
        self.assertEqual(len(self.calls), 2)
        for path, auth, body in self.calls:
            self.assertEqual(path, '/diary/api/skills/analyze/prepare')
            self.assertEqual(auth, 'Bearer test-token-only')
            self.assertEqual(body['files']['/cloud/分析稿.md'], '已确认稿')

    def test_cloud_cli_does_not_load_backend_packages(self):
        commands = [
            ('diary-workflow/scripts/status.py', ['--date', '2026-10-29'], 'workflow/status'),
            ('diary-organizer/scripts/store_diary.py', ['find', '--date', '2026-10-29'], 'organize/find'),
            ('diary-event-points/scripts/export_events.py', ['find', '--username', 'x5456', '--date', '2026-10-29'], 'points-source/find'),
            ('diary-event-points/scripts/store_points.py', ['schema'], 'points/schema'),
            ('diary-event-points/scripts/store_points.py', ['embedding-config'], 'points/embedding-config'),
            ('diary-event-relations/scripts/workflow.py', ['find', '--username', 'x5456', '--date', '2026-10-29'], 'relations/find'),
            ('diary-analyzer/scripts/store_analysis.py', ['find', '--date', '2026-10-29'], 'analyze/find'),
        ]
        for script, args, endpoint in commands:
            with self.subTest(script=script, args=args):
                # -S 禁止加载第三方包，验证云端入口不依赖数据库驱动。
                run = subprocess.run([sys.executable, '-S', str(ROOT / 'skills' / script), *args],
                                     capture_output=True, text=True, env=os.environ.copy())
                self.assertEqual(run.returncode, 0, run.stderr)
                self.assertEqual(self.calls[-1][0], '/diary/api/skills/' + endpoint)
                self.assertNotIn('test-token-only', run.stdout + run.stderr)

    def test_missing_token_and_invalid_mode_stop_without_network(self):
        with patch.dict(os.environ, {'DIARY_API_TOKEN': ''}):
            with self.assertRaises(ApiError): request('workflow', 'status')
        with patch.dict(os.environ, {'DIARY_DATA_MODE': 'invalid'}):
            with self.assertRaises(ApiError): api_enabled()
        self.assertEqual(self.calls, [])

    def test_default_mode_preserves_database_behavior(self):
        with patch.dict(os.environ, {}, clear=True): self.assertFalse(api_enabled())


class UploadedFilesTest(unittest.TestCase):
    def test_cloud_paths_are_read_from_upload_not_server_files(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder).resolve() / 'private.txt'
            path.write_text('server-private')
            with uploaded_files({str(path): 'cloud-content'}):
                self.assertEqual(read_bytes(path), b'cloud-content')
            with uploaded_files({}):
                with self.assertRaises(ValueError): read_bytes(path)
            self.assertEqual(read_bytes(path), b'server-private')

    def test_upload_cannot_replace_deployed_skill_fingerprint(self):
        path = ROOT / 'skills/diary-workflow/SKILL.md'
        expected = path.read_bytes()
        with uploaded_files({str(path): 'forged'}): self.assertEqual(read_bytes(path), expected)


if __name__ == '__main__': unittest.main()
