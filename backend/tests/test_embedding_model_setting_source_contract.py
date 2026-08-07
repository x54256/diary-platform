"""向量化模型设置的关键契约。"""

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class EmbeddingModelSettingSourceContractTest(unittest.TestCase):
    def test_embedding_is_non_reasoning_setting_and_test_uses_embeddings_endpoint(self):
        service = (ROOT / "services" / "model_management.py").read_text()
        router = (ROOT / "routers" / "admin_models.py").read_text()
        self.assertIn('{"transcription", "embedding"}', service)
        self.assertIn('protocol == "openai_embeddings"', router)
        self.assertIn('f"{api_base_url}/embeddings"', router)

    def test_frontend_exposes_embedding_usage_without_thinking_switch(self):
        page = (ROOT.parent / "frontend" / "pages" / "admin" / "model-settings.vue").read_text()
        self.assertIn("{ key: 'embedding', label: '向量化', modelType: 'embedding' }", page)
        self.assertIn("usage.key !== 'embedding'", page)
