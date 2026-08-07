"""运行时模型配置解析。"""

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import joinedload

from database import SessionLocal
from models.model_config import ChannelModel, ModelSetting, ModelStepSetting
from services.model_management import (
    ModelConfigError,
    STEP_LABELS,
    STEP_SETTING_KEYS,
    SETTING_REQUIREMENTS,
    decrypt_channel_key,
    protocol_for_model_type,
    validate_setting_choice,
    validate_thinking_choice,
)


class ModelRuntimeError(RuntimeError):
    """运行时模型配置错误。"""


@dataclass(frozen=True)
class RuntimeModelConfig:
    setting_key: str
    model_type: str
    protocol: str
    api_base_url: str
    api_key: str
    model_name: str
    step_key: str | None = None
    reasoning_mode: str = "unsupported"
    thinking_enabled: bool | None = None
    thinkmode: dict[str, Any] | None = None


# 语义检索 embedding 默认模型名（决策 12）：未配置 EMBEDDING 用途时的回退值。
# 维度与迁移 038、embedding_client 一致（1024）。仅作模型名回退；api_key /
# api_base_url 仍须来自管理端 DB 配置，否则上层 fail-open 降级为关键词召回。
EMBEDDING_MODEL_DEFAULT = "qwen3.7-text-embedding"


def resolve_model_setting(setting_key: str, step_key: str | None = None) -> RuntimeModelConfig:
    """解析业务用途对应的可调用模型配置。"""
    if setting_key not in SETTING_REQUIREMENTS:
        raise ModelRuntimeError("模型用途不合法")

    if step_key is not None and STEP_SETTING_KEYS.get(step_key) != setting_key:
        raise ModelRuntimeError("环节与模型用途不匹配")
    if setting_key == "transcription" and step_key is not None:
        raise ModelRuntimeError("语音转文字不支持环节配置")

    # embedding 用途：复用管理端 DB 托管配置；未配置时回退默认模型名（决策 12）。
    if setting_key == "embedding":
        return _resolve_embedding_setting()

    db = SessionLocal()
    try:
        setting = (
            db.query(ModelSetting)
            .options(
                joinedload(ModelSetting.channel_model).joinedload(ChannelModel.model),
                joinedload(ModelSetting.channel_model).joinedload(ChannelModel.channel),
            )
            .filter(ModelSetting.setting_key == setting_key)
            .first()
        )
        if not setting:
            raise ModelRuntimeError("当前用途未配置可用模型，请在管理端模型设置中配置。")
        step_setting = None
        if step_key:
            step_setting = (
                db.query(ModelStepSetting)
                .options(
                    joinedload(ModelStepSetting.channel_model).joinedload(ChannelModel.model),
                    joinedload(ModelStepSetting.channel_model).joinedload(ChannelModel.channel),
                )
                .filter(ModelStepSetting.step_key == step_key)
                .first()
            )
        channel_model = (
            step_setting.channel_model
            if step_setting and step_setting.channel_model
            else setting.channel_model
        )
        thinking_enabled = (
            step_setting.thinking_enabled
            if step_setting and step_setting.thinking_enabled is not None
            else setting.thinking_enabled
        )
        try:
            validate_setting_choice(setting_key, channel_model)
            if setting_key != "transcription":
                validate_thinking_choice(
                    channel_model,
                    bool(thinking_enabled),
                    STEP_LABELS.get(step_key, setting_key),
                )
            api_key = decrypt_channel_key(channel_model.channel)
        except ModelConfigError as exc:
            raise ModelRuntimeError(str(exc)) from exc
        return RuntimeModelConfig(
            setting_key=setting_key,
            step_key=step_key,
            model_type=channel_model.model.model_type,
            protocol=protocol_for_model_type(channel_model.model.model_type),
            api_base_url=channel_model.channel.api_base_url.rstrip("/"),
            api_key=api_key,
            model_name=channel_model.model.model_name,
            reasoning_mode=channel_model.model.reasoning_mode,
            thinking_enabled=thinking_enabled,
            thinkmode=channel_model.channel.thinkmode or {},
        )
    finally:
        db.close()


def _resolve_embedding_setting() -> RuntimeModelConfig:
    """解析 EMBEDDING 用途模型配置（语义检索向量化）。

    与 chat/organize 等一致走管理端 DB 托管配置（ModelSetting + ChannelModel +
    ApiChannel）。未配置 EMBEDDING 用途时回退为默认模型名 qwen3.7-text-embedding，
    api_key / api_base_url 留空，由上层（hybrid 模式语义分支）fail-open 降级为关键词
    召回，避免未配置即抛错中断搜索（决策 12）。
    """
    db = SessionLocal()
    try:
        setting = (
            db.query(ModelSetting)
            .options(
                joinedload(ModelSetting.channel_model).joinedload(ChannelModel.model),
                joinedload(ModelSetting.channel_model).joinedload(ChannelModel.channel),
            )
            .filter(ModelSetting.setting_key == "embedding")
            .first()
        )
        if not setting or not setting.channel_model:
            # 未配置：返回默认模型名，供后续 fail-open 降级（不抛错）。
            return RuntimeModelConfig(
                setting_key="embedding",
                model_type="embedding",
                protocol="openai_embeddings",
                api_base_url="",
                api_key="",
                model_name=EMBEDDING_MODEL_DEFAULT,
                reasoning_mode="unsupported",
                thinking_enabled=False,
                thinkmode={},
            )
        channel_model = setting.channel_model
        try:
            validate_setting_choice("embedding", channel_model)
            api_key = decrypt_channel_key(channel_model.channel)
        except ModelConfigError as exc:
            raise ModelRuntimeError(str(exc)) from exc
        return RuntimeModelConfig(
            setting_key="embedding",
            step_key=None,
            model_type=channel_model.model.model_type,
            protocol=protocol_for_model_type(channel_model.model.model_type),
            api_base_url=channel_model.channel.api_base_url.rstrip("/"),
            api_key=api_key,
            model_name=channel_model.model.model_name,
            reasoning_mode=channel_model.model.reasoning_mode,
            thinking_enabled=setting.thinking_enabled,
            thinkmode=channel_model.channel.thinkmode or {},
        )
    finally:
        db.close()


def resolve_thinking_payload(
    config: RuntimeModelConfig,
    enabled: bool | None = None,
) -> dict[str, Any]:
    """根据模型能力和渠道参数生成 OpenAI 兼容接口的扩展请求体。"""
    if enabled is None:
        enabled = bool(config.thinking_enabled)
    if config.reasoning_mode == "unsupported":
        return {}
    if config.reasoning_mode == "always_on":
        enabled = True
    if config.reasoning_mode not in {"switchable", "always_on"}:
        raise ModelRuntimeError("模型推理模式不合法")
    payload = (config.thinkmode or {}).get("enabled" if enabled else "disabled")
    if not isinstance(payload, dict):
        raise ModelRuntimeError("当前渠道未配置完整的 thinkmode 参数")
    return payload
