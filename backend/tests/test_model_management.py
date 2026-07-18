"""模型管理核心规则测试。"""

import csv
import unittest
from pathlib import Path
from types import SimpleNamespace

from services.model_management import ModelConfigError, validate_setting_choice
from services.model_management import ability_tier_sort_value
from services.model_seed import repair_model_management_schema


class ModelSeedDataTest(unittest.TestCase):
    def test_seed_file_contains_language_and_asr_models(self):
        path = Path(__file__).resolve().parent.parent / "data" / "model_seed.csv"
        with path.open("r", encoding="utf-8", newline="") as file:
            rows = list(csv.DictReader(file))

        self.assertEqual(sum(1 for row in rows if row["model_type"] == "language"), 70)
        self.assertEqual(sum(1 for row in rows if row["model_type"] == "asr"), 30)
        self.assertEqual(
            {row["ability_category"] for row in rows if row["model_type"] == "asr"},
            {"实时语音识别", "录音文件识别"},
        )


class ModelSettingRuleTest(unittest.TestCase):
    def channel_model(self, model_type: str, enabled: bool = True):
        return SimpleNamespace(
            enabled=enabled,
            model=SimpleNamespace(model_type=model_type, enabled=True),
            channel=SimpleNamespace(enabled=True, api_key_encrypted="encrypted"),
        )

    def test_language_usage_requires_openai_chat_language_model(self):
        validate_setting_choice("analysis", self.channel_model("language"))

        with self.assertRaises(ModelConfigError):
            validate_setting_choice("analysis", self.channel_model("asr"))

    def test_transcription_requires_dashscope_asr_model(self):
        validate_setting_choice("transcription", self.channel_model("asr"))

        with self.assertRaises(ModelConfigError):
            validate_setting_choice("transcription", self.channel_model("language"))

    def test_disabled_channel_model_is_unavailable(self):
        with self.assertRaises(ModelConfigError):
            validate_setting_choice("analysis", self.channel_model("language", enabled=False))


class ModelListQueryRuleTest(unittest.TestCase):
    def test_ability_tier_sort_value_orders_stronger_tiers_first(self):
        self.assertLess(ability_tier_sort_value("T0 旗舰全能"), ability_tier_sort_value("T1 次旗舰均衡"))
        self.assertLess(ability_tier_sort_value("T1 次旗舰均衡"), ability_tier_sort_value("T4 极速轻量"))
        self.assertEqual(ability_tier_sort_value("未知梯队"), 999)


class ModelSchemaRepairTest(unittest.TestCase):
    def test_schema_repair_drops_legacy_channel_model_columns(self):
        executed_sql: list[str] = []

        class FakeSession:
            def execute(self, statement):
                executed_sql.append(str(statement))

            def commit(self):
                executed_sql.append("COMMIT")

        repair_model_management_schema(FakeSession())

        sql = "\n".join(executed_sql)
        self.assertIn("DROP COLUMN IF EXISTS api_model_name", sql)
        self.assertIn("DROP COLUMN IF EXISTS protocol", sql)


if __name__ == "__main__":
    unittest.main()
