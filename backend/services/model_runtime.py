"""运行时模型配置解析。"""

from dataclasses import dataclass

from sqlalchemy.orm import joinedload

from database import SessionLocal
from models.model_config import ChannelModel, ModelSetting
from services.model_management import (
    ModelConfigError,
    SETTING_REQUIREMENTS,
    decrypt_channel_key,
    protocol_for_model_type,
    validate_setting_choice,
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


def resolve_model_setting(setting_key: str) -> RuntimeModelConfig:
    """解析业务用途对应的可调用模型配置。"""
    if setting_key not in SETTING_REQUIREMENTS:
        raise ModelRuntimeError("模型用途不合法")

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
        channel_model = setting.channel_model
        try:
            validate_setting_choice(setting_key, channel_model)
            api_key = decrypt_channel_key(channel_model.channel)
        except ModelConfigError as exc:
            raise ModelRuntimeError(str(exc)) from exc
        return RuntimeModelConfig(
            setting_key=setting_key,
            model_type=channel_model.model.model_type,
            protocol=protocol_for_model_type(channel_model.model.model_type),
            api_base_url=channel_model.channel.api_base_url.rstrip("/"),
            api_key=api_key,
            model_name=channel_model.model.model_name,
        )
    finally:
        db.close()
