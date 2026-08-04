"""管理端模型配置服务。"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import case, or_
from sqlalchemy.orm import Session, joinedload

from models.model_config import ApiChannel, ChannelModel, ModelCatalog, ModelSetting, ModelStepSetting
from utils.crypto import decrypt_text, encrypt_text

MODEL_TYPES = ["language", "asr"]
REASONING_MODES = ["unsupported", "switchable", "always_on"]
SETTING_KEYS = ["organize", "analysis", "review", "chat", "transcription"]
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
    "review": ("language", "openai_chat"),
    "chat": ("language", "openai_chat"),
    "transcription": ("asr", "dashscope_asr"),
}
STEP_SETTING_KEYS = {
    "text_clean": "organize",
    "clean_check": "organize",
    "event_organize": "organize",
    "template_fill": "organize",
    "content_check": "organize",
    "mood_tag_extract": "analysis",
    "core_analysis": "analysis",
    "cognition_analysis": "analysis",
    "action_planning": "analysis",
    "feedback_core_analysis": "analysis",
    "feedback_cognition_analysis": "analysis",
    "review_daily_material": "review",
    "review_event_organize": "review",
    "review_analysis_action": "review",
}
STEP_LABELS = {
    "text_clean": "文本清洗",
    "clean_check": "清洗审核",
    "event_organize": "事件整理",
    "template_fill": "三字段结构化",
    "content_check": "内容审核",
    "mood_tag_extract": "元数据、心情与标签",
    "core_analysis": "核心分析",
    "cognition_analysis": "认知分析",
    "action_planning": "行动规划",
    "feedback_core_analysis": "反馈核心分析",
    "feedback_cognition_analysis": "反馈认知分析",
    "review_daily_material": "每日周回顾素材",
    "review_event_organize": "回顾事件组织",
    "review_analysis_action": "回顾分析与行动",
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
        "thinking_enabled": setting.thinking_enabled,
        "channel_model": serialize_channel_model(setting.channel_model),
        "updated_by": str(setting.updated_by) if setting.updated_by else None,
        "updated_at": setting.updated_at.isoformat() if setting.updated_at else None,
        "unavailable_reason": unavailable_reason(setting.channel_model),
    }


def serialize_step_setting(
    step_key: str,
    setting: ModelStepSetting | None,
    default_setting: ModelSetting | None,
) -> dict[str, Any]:
    override_model = setting.channel_model if setting else None
    effective_model = override_model or (default_setting.channel_model if default_setting else None)
    thinking_override = setting.thinking_enabled if setting else None
    effective_thinking = (
        thinking_override
        if thinking_override is not None
        else (default_setting.thinking_enabled if default_setting else None)
    )
    return {
        "id": str(setting.id) if setting else None,
        "step_key": step_key,
        "step_label": STEP_LABELS[step_key],
        "setting_key": STEP_SETTING_KEYS[step_key],
        "channel_model_id": str(setting.channel_model_id) if setting and setting.channel_model_id else None,
        "thinking_enabled": thinking_override,
        "channel_model": serialize_channel_model(override_model) if override_model else None,
        "effective_channel_model_id": str(effective_model.id) if effective_model else None,
        "effective_channel_model": serialize_channel_model(effective_model) if effective_model else None,
        "effective_thinking_enabled": effective_thinking,
        "updated_at": setting.updated_at.isoformat() if setting and setting.updated_at else None,
    }


def get_model_settings_payload(db: Session) -> dict[str, Any]:
    settings = (
        db.query(ModelSetting)
        .options(
            joinedload(ModelSetting.channel_model).joinedload(ChannelModel.model),
            joinedload(ModelSetting.channel_model).joinedload(ChannelModel.channel),
        )
        .all()
    )
    step_settings = (
        db.query(ModelStepSetting)
        .options(
            joinedload(ModelStepSetting.channel_model).joinedload(ChannelModel.model),
            joinedload(ModelStepSetting.channel_model).joinedload(ChannelModel.channel),
        )
        .all()
    )
    setting_map = {item.setting_key: item for item in settings}
    step_map = {item.step_key: item for item in step_settings}
    return {
        "settings": {key: serialize_setting(setting_map[key]) for key in SETTING_KEYS if key in setting_map},
        "steps": [
            serialize_step_setting(step_key, step_map.get(step_key), setting_map.get(setting_key))
            for step_key, setting_key in STEP_SETTING_KEYS.items()
        ],
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


def _load_channel_model(db: Session, channel_model_id: Any) -> ChannelModel:
    try:
        model_id = UUID(str(channel_model_id))
    except (TypeError, ValueError) as exc:
        raise ModelConfigError("渠道模型标识不合法") from exc
    channel_model = (
        db.query(ChannelModel)
        .options(joinedload(ChannelModel.model), joinedload(ChannelModel.channel))
        .filter(ChannelModel.id == model_id)
        .first()
    )
    if not channel_model:
        raise ModelConfigError("渠道模型不存在")
    return channel_model


def validate_thinking_choice(channel_model: ChannelModel, enabled: bool, label: str = "") -> None:
    mode = channel_model.model.reasoning_mode
    prefix = f"{label}：" if label else ""
    if mode == "unsupported" and enabled:
        raise ModelConfigError(f"{prefix}所选模型不支持思考模式")
    if mode == "always_on" and not enabled:
        raise ModelConfigError(f"{prefix}所选模型强制开启思考模式")
    if mode not in REASONING_MODES:
        raise ModelConfigError(f"{prefix}模型推理模式不合法")
    if mode in {"switchable", "always_on"}:
        thinkmode = validate_thinkmode(channel_model.channel.thinkmode)
        if not thinkmode:
            raise ModelConfigError(f"{prefix}所选渠道未配置思考参数")


def save_model_settings(
    db: Session,
    settings_data: dict[str, dict[str, Any]],
    steps_data: list[dict[str, Any]],
    user_id: UUID,
) -> dict[str, Any]:
    for setting_key, data in settings_data.items():
        if setting_key not in SETTING_KEYS:
            raise ModelConfigError("模型用途不合法")
        channel_model = _load_channel_model(db, data.get("channel_model_id"))
        validate_setting_choice(setting_key, channel_model)
        thinking_enabled = data.get("thinking_enabled")
        if setting_key == "transcription":
            if thinking_enabled is not None:
                raise ModelConfigError("语音转文字不能配置思考模式")
        elif not isinstance(thinking_enabled, bool):
            raise ModelConfigError(f"{setting_key} 必须配置默认思考状态")
        setting = db.query(ModelSetting).filter(ModelSetting.setting_key == setting_key).first()
        if not setting:
            setting = ModelSetting(setting_key=setting_key)
            db.add(setting)
        setting.channel_model_id = channel_model.id
        setting.thinking_enabled = thinking_enabled
        setting.updated_by = user_id
        setting.updated_at = datetime.utcnow()

    for data in steps_data:
        step_key = data.get("step_key")
        if step_key not in STEP_SETTING_KEYS:
            raise ModelConfigError("环节标识不合法")
        channel_model_id = data.get("channel_model_id")
        thinking_enabled = data.get("thinking_enabled")
        if thinking_enabled is not None and not isinstance(thinking_enabled, bool):
            raise ModelConfigError(f"{STEP_LABELS[step_key]}思考状态不合法")
        setting = db.query(ModelStepSetting).filter(ModelStepSetting.step_key == step_key).first()
        if channel_model_id is None and thinking_enabled is None:
            if setting:
                db.delete(setting)
            continue
        if not setting:
            setting = ModelStepSetting(step_key=step_key)
            db.add(setting)
        setting.channel_model_id = _load_channel_model(db, channel_model_id).id if channel_model_id else None
        setting.thinking_enabled = thinking_enabled
        setting.updated_by = user_id
        setting.updated_at = datetime.utcnow()

    try:
        db.flush()
        setting_map = {item.setting_key: item for item in db.query(ModelSetting).all()}
        step_map = {item.step_key: item for item in db.query(ModelStepSetting).all()}
        for key, setting in setting_map.items():
            validate_setting_choice(key, setting.channel_model)
            if key != "transcription":
                validate_thinking_choice(setting.channel_model, bool(setting.thinking_enabled), key)
        for step_key, setting_key in STEP_SETTING_KEYS.items():
            default = setting_map.get(setting_key)
            if not default:
                continue
            override = step_map.get(step_key)
            channel_model = override.channel_model if override and override.channel_model else default.channel_model
            thinking_enabled = (
                override.thinking_enabled
                if override and override.thinking_enabled is not None
                else default.thinking_enabled
            )
            validate_setting_choice(setting_key, channel_model)
            validate_thinking_choice(channel_model, bool(thinking_enabled), STEP_LABELS[step_key])
        db.commit()
    except Exception:
        db.rollback()
        raise
    return get_model_settings_payload(db)


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
    step_exists = (
        db.query(ModelStepSetting)
        .join(ChannelModel)
        .filter(ChannelModel.model_id == model_id)
        .first()
    )
    if exists or step_exists:
        raise ModelConfigError("模型正在被模型设置使用，不能执行该操作")


def ensure_channel_not_used(db: Session, channel_id: UUID) -> None:
    exists = (
        db.query(ModelSetting)
        .join(ChannelModel)
        .filter(ChannelModel.channel_id == channel_id)
        .first()
    )
    step_exists = (
        db.query(ModelStepSetting)
        .join(ChannelModel)
        .filter(ChannelModel.channel_id == channel_id)
        .first()
    )
    if exists or step_exists:
        raise ModelConfigError("渠道正在被模型设置使用，不能执行该操作")


def ensure_channel_model_not_used(db: Session, channel_model_id: UUID) -> None:
    exists = db.query(ModelSetting).filter(ModelSetting.channel_model_id == channel_model_id).first()
    step_exists = (
        db.query(ModelStepSetting)
        .filter(ModelStepSetting.channel_model_id == channel_model_id)
        .first()
    )
    if exists or step_exists:
        raise ModelConfigError("渠道模型正在被模型设置使用，不能执行该操作")


def decrypt_channel_key(channel: ApiChannel) -> str:
    if not channel.api_key_encrypted:
        raise ModelConfigError("渠道未配置密钥")
    return decrypt_text(channel.api_key_encrypted)
