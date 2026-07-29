"""管理端模型配置服务。"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import case, or_
from sqlalchemy.orm import Session, joinedload

from models.model_config import ApiChannel, ChannelModel, ModelCatalog, ModelSetting
from utils.crypto import decrypt_text, encrypt_text

MODEL_TYPES = ["language", "asr"]
REASONING_MODES = ["unsupported", "switchable", "always_on"]
SETTING_KEYS = ["organize", "analysis", "chat", "transcription"]
LANGUAGE_CATEGORIES = ["通用对话", "深度推理", "长上下文", "代码能力", "轻量高速"]
ASR_CATEGORIES = ["实时语音识别", "录音文件识别"]
ABILITY_TIER_ORDER = {
    "T0 旗舰全能": 1,
    "T0 全能旗舰": 1,
    "T0.5 推理专项天花板": 2,
    "T1 次旗舰均衡": 3,
    "T1 专项顶级": 3,
    "T2 企业主力": 4,
    "T2 通用商用": 4,
    "T2.5 中端推理特化": 5,
    "T3 轻量通用": 6,
    "T3 轻量专项": 6,
    "T4 极速轻量": 7,
}

SETTING_REQUIREMENTS = {
    "organize": ("language", "openai_chat"),
    "analysis": ("language", "openai_chat"),
    "chat": ("language", "openai_chat"),
    "transcription": ("asr", "dashscope_asr"),
}


class ModelConfigError(ValueError):
    """模型配置业务异常。"""


def ability_tier_sort_value(ability_tier: str | None) -> int:
    return ABILITY_TIER_ORDER.get(ability_tier or "", 999)


def has_api_key(channel: ApiChannel) -> bool:
    return bool(channel.api_key_encrypted)


def serialize_model(model: ModelCatalog) -> dict[str, Any]:
    return {
        "id": str(model.id),
        "model_type": model.model_type,
        "provider_name": model.provider_name,
        "model_name": model.model_name,
        "reasoning_mode": model.reasoning_mode,
        "ability_tier": model.ability_tier,
        "ability_category": model.ability_category,
        "original_category": model.original_category,
        "core_features": model.core_features,
        "scenarios": model.scenarios,
        "score": model.score,
        "score_label": model.score_label,
        "enabled": model.enabled,
        "is_custom": model.is_custom,
        "created_at": model.created_at.isoformat() if model.created_at else None,
        "updated_at": model.updated_at.isoformat() if model.updated_at else None,
    }


def serialize_channel(channel: ApiChannel) -> dict[str, Any]:
    return {
        "id": str(channel.id),
        "name": channel.name,
        "api_base_url": channel.api_base_url,
        "thinkmode": channel.thinkmode or {},
        "has_api_key": has_api_key(channel),
        "enabled": channel.enabled,
        "created_at": channel.created_at.isoformat() if channel.created_at else None,
        "updated_at": channel.updated_at.isoformat() if channel.updated_at else None,
    }


def serialize_channel_model(item: ChannelModel) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "channel_id": str(item.channel_id),
        "model_id": str(item.model_id),
        "enabled": item.enabled,
        "channel": serialize_channel(item.channel) if item.channel else None,
        "model": serialize_model(item.model) if item.model else None,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


def serialize_setting(setting: ModelSetting) -> dict[str, Any]:
    return {
        "id": str(setting.id),
        "setting_key": setting.setting_key,
        "channel_model_id": str(setting.channel_model_id),
        "channel_model": serialize_channel_model(setting.channel_model),
        "updated_by": str(setting.updated_by) if setting.updated_by else None,
        "updated_at": setting.updated_at.isoformat() if setting.updated_at else None,
        "unavailable_reason": unavailable_reason(setting.channel_model),
    }


def unavailable_reason(channel_model: ChannelModel) -> str:
    if not channel_model.enabled:
        return "渠道模型已禁用"
    if not channel_model.model.enabled:
        return "模型已禁用"
    if not channel_model.channel.enabled:
        return "渠道已禁用"
    if not has_api_key(channel_model.channel):
        return "渠道未配置密钥"
    return ""


def list_models(
    db: Session,
    model_type: str | None = None,
    ability_tier: str | None = None,
    ability_category: str | None = None,
    provider_name: str | None = None,
    enabled: bool | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[ModelCatalog], int]:
    query = db.query(ModelCatalog)
    if model_type:
        query = query.filter(ModelCatalog.model_type == model_type)
    if ability_tier:
        query = query.filter(ModelCatalog.ability_tier == ability_tier)
    if ability_category:
        query = query.filter(ModelCatalog.ability_category == ability_category)
    if provider_name:
        query = query.filter(ModelCatalog.provider_name == provider_name)
    if enabled is not None:
        query = query.filter(ModelCatalog.enabled == enabled)
    if keyword:
        pattern = f"%{keyword}%"
        query = query.filter(
            or_(
                ModelCatalog.model_name.ilike(pattern),
                ModelCatalog.provider_name.ilike(pattern),
                ModelCatalog.core_features.ilike(pattern),
                ModelCatalog.scenarios.ilike(pattern),
            )
        )
    total = query.count()
    tier_order = case(ABILITY_TIER_ORDER, value=ModelCatalog.ability_tier, else_=999)
    items = (
        query
        .order_by(tier_order, ModelCatalog.score.desc().nullslast(), ModelCatalog.model_type, ModelCatalog.model_name)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return items, total


def create_model(db: Session, data: dict[str, Any]) -> ModelCatalog:
    validate_model_payload(data)
    model = ModelCatalog(
        model_type=data["model_type"],
        provider_name=data["provider_name"],
        model_name=data["model_name"],
        reasoning_mode=data.get("reasoning_mode", "unsupported"),
        ability_tier=data["ability_tier"],
        ability_category=data["ability_category"],
        original_category=data.get("original_category") or data["ability_category"],
        core_features=data.get("core_features") or "",
        scenarios=data.get("scenarios") or "",
        score=data.get("score"),
        score_label=data.get("score_label") or (str(data["score"]) if data.get("score") is not None else ""),
        enabled=True,
        is_custom=True,
    )
    db.add(model)
    db.commit()
    db.refresh(model)
    return model


def update_model(db: Session, model: ModelCatalog, data: dict[str, Any]) -> ModelCatalog:
    if "enabled" in data and data["enabled"] is False:
        ensure_model_not_used(db, model.id)
    for field in [
        "provider_name",
        "model_name",
        "reasoning_mode",
        "ability_tier",
        "ability_category",
        "original_category",
        "core_features",
        "scenarios",
        "score",
        "score_label",
        "enabled",
    ]:
        if field in data:
            setattr(model, field, data[field])
    validate_model_payload({
        "model_type": model.model_type,
        "provider_name": model.provider_name,
        "model_name": model.model_name,
        "ability_tier": model.ability_tier,
        "ability_category": model.ability_category,
        "reasoning_mode": model.reasoning_mode,
    })
    db.commit()
    db.refresh(model)
    return model


def delete_model(db: Session, model: ModelCatalog) -> None:
    ensure_model_not_used(db, model.id)
    db.delete(model)
    db.commit()


def validate_model_payload(data: dict[str, Any]) -> None:
    model_type = data.get("model_type")
    category = data.get("ability_category")
    if model_type not in MODEL_TYPES:
        raise ModelConfigError("模型类型不合法")
    if not data.get("provider_name") or not data.get("model_name") or not data.get("ability_tier"):
        raise ModelConfigError("模型厂商、名称和能力梯队不能为空")
    if model_type == "language" and category not in LANGUAGE_CATEGORIES:
        raise ModelConfigError("语言模型能力分类不合法")
    if model_type == "asr" and category not in ASR_CATEGORIES:
        raise ModelConfigError("ASR 模型能力分类不合法")
    if data.get("reasoning_mode", "unsupported") not in REASONING_MODES:
        raise ModelConfigError("模型推理模式不合法")


def validate_thinkmode(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ModelConfigError("渠道 thinkmode 必须是 JSON 对象")
    if not value:
        return {}
    if not isinstance(value.get("enabled"), dict) or not isinstance(value.get("disabled"), dict):
        raise ModelConfigError("渠道 thinkmode 必须同时包含 enabled 和 disabled 对象")
    return value


def create_channel(db: Session, data: dict[str, Any]) -> ApiChannel:
    thinkmode = validate_thinkmode(data.get("thinkmode", {}))
    channel = ApiChannel(
        name=data["name"],
        api_base_url=data["api_base_url"].rstrip("/"),
        api_key_encrypted=encrypt_text(data["api_key"]) if data.get("api_key") else None,
        thinkmode=thinkmode,
        enabled=data.get("enabled", True),
    )
    db.add(channel)
    db.commit()
    db.refresh(channel)
    return channel


def update_channel(db: Session, channel: ApiChannel, data: dict[str, Any]) -> ApiChannel:
    if "enabled" in data and data["enabled"] is False:
        ensure_channel_not_used(db, channel.id)
    if "name" in data:
        channel.name = data["name"]
    if "api_base_url" in data:
        channel.api_base_url = data["api_base_url"].rstrip("/")
    if data.get("api_key"):
        channel.api_key_encrypted = encrypt_text(data["api_key"])
    if "thinkmode" in data:
        channel.thinkmode = validate_thinkmode(data["thinkmode"])
    if "enabled" in data:
        channel.enabled = data["enabled"]
    db.commit()
    db.refresh(channel)
    return channel


def clear_channel_api_key(db: Session, channel: ApiChannel) -> ApiChannel:
    ensure_channel_not_used(db, channel.id)
    channel.api_key_encrypted = None
    db.commit()
    db.refresh(channel)
    return channel


def delete_channel(db: Session, channel: ApiChannel) -> None:
    ensure_channel_not_used(db, channel.id)
    db.delete(channel)
    db.commit()


def set_channel_models(db: Session, channel: ApiChannel, rows: list[dict[str, Any]]) -> list[ChannelModel]:
    existing = {item.model_id: item for item in channel.channel_models}
    seen: set[UUID] = set()
    for row in rows:
        model_id = UUID(str(row["model_id"]))
        model = db.get(ModelCatalog, model_id)
        if not model:
            raise ModelConfigError("模型不存在")
        item = existing.get(model_id)
        enabled = row.get("enabled", True)
        if item:
            if item.enabled and not enabled:
                ensure_channel_model_not_used(db, item.id)
            item.enabled = enabled
            item.updated_at = datetime.utcnow()
        else:
            item = ChannelModel(
                channel_id=channel.id,
                model_id=model.id,
                enabled=enabled,
            )
            db.add(item)
        seen.add(model_id)
    for model_id, item in existing.items():
        if model_id not in seen:
            ensure_channel_model_not_used(db, item.id)
            db.delete(item)
    db.commit()
    return (
        db.query(ChannelModel)
        .options(joinedload(ChannelModel.model), joinedload(ChannelModel.channel))
        .filter(ChannelModel.channel_id == channel.id)
        .all()
    )


def protocol_for_model_type(model_type: str) -> str:
    if model_type == "language":
        return "openai_chat"
    if model_type == "asr":
        return "dashscope_asr"
    raise ModelConfigError("模型类型不合法")


def save_model_settings(db: Session, settings_data: dict[str, str], user_id: UUID) -> list[ModelSetting]:
    settings: list[ModelSetting] = []
    for setting_key, channel_model_id_text in settings_data.items():
        if setting_key not in SETTING_KEYS:
            raise ModelConfigError("模型用途不合法")
        channel_model = (
            db.query(ChannelModel)
            .options(joinedload(ChannelModel.model), joinedload(ChannelModel.channel))
            .filter(ChannelModel.id == UUID(str(channel_model_id_text)))
            .first()
        )
        if not channel_model:
            raise ModelConfigError("渠道模型不存在")
        validate_setting_choice(setting_key, channel_model)
        setting = db.query(ModelSetting).filter(ModelSetting.setting_key == setting_key).first()
        if not setting:
            setting = ModelSetting(setting_key=setting_key)
            db.add(setting)
        setting.channel_model_id = channel_model.id
        setting.updated_by = user_id
        setting.updated_at = datetime.utcnow()
        settings.append(setting)
    db.commit()
    return (
        db.query(ModelSetting)
        .options(
            joinedload(ModelSetting.channel_model).joinedload(ChannelModel.model),
            joinedload(ModelSetting.channel_model).joinedload(ChannelModel.channel),
        )
        .order_by(ModelSetting.setting_key)
        .all()
    )


def validate_setting_choice(setting_key: str, channel_model: ChannelModel) -> None:
    expected_model_type, _expected_protocol = SETTING_REQUIREMENTS[setting_key]
    if channel_model.model.model_type != expected_model_type:
        raise ModelConfigError("模型类型与用途不匹配")
    reason = unavailable_reason(channel_model)
    if reason:
        raise ModelConfigError(reason)


def ensure_model_not_used(db: Session, model_id: UUID) -> None:
    exists = (
        db.query(ModelSetting)
        .join(ChannelModel)
        .filter(ChannelModel.model_id == model_id)
        .first()
    )
    if exists:
        raise ModelConfigError("模型正在被模型设置使用，不能执行该操作")


def ensure_channel_not_used(db: Session, channel_id: UUID) -> None:
    exists = (
        db.query(ModelSetting)
        .join(ChannelModel)
        .filter(ChannelModel.channel_id == channel_id)
        .first()
    )
    if exists:
        raise ModelConfigError("渠道正在被模型设置使用，不能执行该操作")


def ensure_channel_model_not_used(db: Session, channel_model_id: UUID) -> None:
    exists = db.query(ModelSetting).filter(ModelSetting.channel_model_id == channel_model_id).first()
    if exists:
        raise ModelConfigError("渠道模型正在被模型设置使用，不能执行该操作")


def decrypt_channel_key(channel: ApiChannel) -> str:
    if not channel.api_key_encrypted:
        raise ModelConfigError("渠道未配置密钥")
    return decrypt_text(channel.api_key_encrypted)
