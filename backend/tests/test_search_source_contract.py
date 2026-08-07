"""无需数据库依赖的搜索关键安全契约回归检查。"""

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SearchSourceContractTest(unittest.TestCase):
    def test_router_calls_aliased_service_not_its_own_route_function(self):
        source = (ROOT / "routers" / "diaries.py").read_text()
        tree = ast.parse(source)
        imports = [node for node in tree.body if isinstance(node, ast.ImportFrom) and node.module == "services.search_service"]
        self.assertTrue(any(any(alias.name == "search_diaries" and alias.asname == "search_diaries_service" for alias in node.names) for node in imports))
        route = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "search_diaries")
        self.assertTrue(any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "search_diaries_service" for node in ast.walk(route)))

    def test_embedding_write_requires_unchanged_pending_snapshot(self):
        source = (ROOT / "services" / "embedding_sync.py").read_text()
        for required in ("content_hash", "snapshots", "db.expire_all()", "state.status != \"PENDING\"", "丢弃旧向量"):
            self.assertIn(required, source)

    def test_semantic_snippet_with_literal_query_is_marked_for_highlight(self):
        source = (ROOT / "services" / "search_service.py").read_text()
        self.assertIn("literal_keyword_match", source)
        self.assertIn('"keyword_matched": literal_keyword_match', source)
        self.assertIn("_snippet(row.content, q if literal_keyword_match else None)", source)
