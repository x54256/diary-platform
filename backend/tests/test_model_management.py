"""模型管理核心规则测试。"""

import csv
import unittest
from pathlib import Path
from types import SimpleNamespace

from services.model_management import (
    ModelConfigError,
    STEP_SETTING_KEYS,
    validate_setting_choice,
    validate_thinking_choice,
)
from services.model_management import ability_tier_sort_value
from services.model_seed import repair_model_management_schema
from services.model_runtime import RuntimeModelConfig, resolve_thinking_payload


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
            model=SimpleNamespace(model_type=model_type, enabled=True, reasoning_mode="unsupported"),
            channel=SimpleNamespace(enabled=True, api_key_encrypted="encrypted", thinkmode={}),
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

    def test_thinking_mode_must_match_model_capability(self):
        unsupported = self.channel_model("language")
        with self.assertRaisesRegex(ModelConfigError, "不支持思考模式"):
            validate_thinking_choice(unsupported, True, "文本清洗")

        always_on = self.channel_model("language")
        always_on.model.reasoning_mode = "always_on"
        always_on.channel.thinkmode = {"enabled": {"enable_thinking": True}, "disabled": {"enable_thinking": False}}
        with self.assertRaisesRegex(ModelConfigError, "强制开启"):
            validate_thinking_choice(always_on, False)

    def test_switchable_model_requires_channel_thinking_payload(self):
        switchable = self.channel_model("language")
        switchable.model.reasoning_mode = "switchable"
        with self.assertRaisesRegex(ModelConfigError, "未配置思考参数"):
            validate_thinking_choice(switchable, False)

        switchable.channel.thinkmode = {
            "enabled": {"enable_thinking": True},
            "disabled": {"enable_thinking": False},
        }
        validate_thinking_choice(switchable, True)
        validate_thinking_choice(switchable, False)

    def test_all_ten_steps_have_fixed_stage_ownership(self):
        self.assertEqual(sum(value == "organize" for value in STEP_SETTING_KEYS.values()), 5)
        self.assertEqual(sum(value == "analysis" for value in STEP_SETTING_KEYS.values()), 5)


class ModelListQueryRuleTest(unittest.TestCase):
    def test_ability_tier_sort_value_orders_stronger_tiers_first(self):
        self.assertLess(ability_tier_sort_value("T0 旗舰全能"), ability_tier_sort_value("T1 次旗舰均衡"))
        self.assertLess(ability_tier_sort_value("T1 次旗舰均衡"), ability_tier_sort_value("T4 极速轻量"))
        self.assertEqual(ability_tier_sort_value("未知梯队"), 999)


class ThinkingPayloadTest(unittest.TestCase):
    def config(self, reasoning_mode: str, enabled: bool):
        return RuntimeModelConfig(
            setting_key="analysis",
            model_type="language",
            protocol="openai_chat",
            api_base_url="https://example.com",
            api_key="key",
            model_name="model",
            reasoning_mode=reasoning_mode,
            thinking_enabled=enabled,
            thinkmode={
                "enabled": {"enable_thinking": True},
                "disabled": {"enable_thinking": False},
            },
        )

    def test_switchable_model_uses_effective_thinking_state(self):
        self.assertEqual(
            resolve_thinking_payload(self.config("switchable", True)),
            {"enable_thinking": True},
        )
        self.assertEqual(
            resolve_thinking_payload(self.config("switchable", False)),
            {"enable_thinking": False},
        )

    def test_unsupported_model_sends_no_thinking_payload(self):
        self.assertEqual(resolve_thinking_payload(self.config("unsupported", False)), {})


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
