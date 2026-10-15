"""管理端模型配置接口。"""

from typing import Any
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload

from database import get_db
from models.model_config import ApiChannel, ChannelModel, ModelCatalog
from models.user import User
from routers.admin_backup import require_admin
from services.model_management import (
    ASR_CATEGORIES,
    EMBEDDING_CATEGORIES,
    LANGUAGE_CATEGORIES,
    MODEL_TYPES,
    REASONING_MODES,
    SETTING_KEYS,
    STEP_SETTING_KEYS,
    ModelConfigError,
    clear_channel_api_key,
    create_channel,
    create_model,
    delete_channel,
    delete_model,
    decrypt_channel_key,
    get_model_settings_payload,
    list_models,
    protocol_for_model_type,
    save_model_settings,
    serialize_channel,
    serialize_channel_model,
    serialize_model,
    set_channel_models,
    update_channel,
    update_model,
    ensure_channel_model_not_used,
    validate_setting_choice,
    validate_thinking_choice,
)
from services.model_runtime import ModelRuntimeError, resolve_model_setting, resolve_thinking_payload
from services.organize_settings import get_or_create_organize_pipeline_setting

router = APIRouter(prefix="/api/admin", tags=["管理端-模型管理"])


class ModelCreateRequest(BaseModel):
    model_type: str
    provider_name: str
    model_name: str
    reasoning_mode: str = "unsupported"
    ability_tier: str
    ability_category: str
    original_category: str | None = None
    core_features: str | None = None
    scenarios: str | None = None
    score: float | None = None
    score_label: str | None = None


class ModelUpdateRequest(BaseModel):
    provider_name: str | None = None
    model_name: str | None = None
    reasoning_mode: str | None = None
    ability_tier: str | None = None
    ability_category: str | None = None
    original_category: str | None = None
    core_features: str | None = None
    scenarios: str | None = None
    score: float | None = None
    score_label: str | None = None
    enabled: bool | None = None


class ChannelCreateRequest(BaseModel):
    name: str
    api_base_url: str
    api_key: str | None = None
    thinkmode: dict[str, Any] = {}
    enabled: bool = True


class ChannelUpdateRequest(BaseModel):
    name: str | None = None
    api_base_url: str | None = None
    api_key: str | None = None
    thinkmode: dict[str, Any] | None = None
    enabled: bool | None = None


class ChannelModelRequest(BaseModel):
    model_id: UUID
    enabled: bool = True


class DefaultModelSettingRequest(BaseModel):
    channel_model_id: UUID
    thinking_enabled: bool | None = None


class StepModelSettingRequest(BaseModel):
    step_key: str
    channel_model_id: UUID | None = None
    thinking_enabled: bool | None = None


class ModelSettingsRequest(BaseModel):
    settings: dict[str, DefaultModelSettingRequest]
    steps: list[StepModelSettingRequest] = Field(default_factory=list)


class ModelTestRequest(BaseModel):
    setting_key: str | None = None
    step_key: str | None = None
    channel_model_id: UUID | None = None
    thinking_enabled: bool | None = None


class OrganizePipelineSettingsRequest(BaseModel):
    clean_check_enabled: bool
    content_check_enabled: bool


def _bad_request(exc: Exception):
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/model-options")
def get_model_options(current_user: User = Depends(require_admin)):
    return {
        "model_types": MODEL_TYPES,
        "setting_keys": SETTING_KEYS,
        "language_categories": LANGUAGE_CATEGORIES,
        "asr_categories": ASR_CATEGORIES,
        "embedding_categories": EMBEDDING_CATEGORIES,
        "reasoning_modes": REASONING_MODES,
        "usage_labels": {
            "organize": "整理",
            "analysis": "分析",
            "review": "回顾",
            "chat": "对话",
            "transcription": "语音转文字",
            "embedding": "向量化",
            "graph": "事件建图",
            "graph_embedding": "图谱向量",
        },
    }


@router.get("/organize-settings")
def get_organize_settings(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    setting = get_or_create_organize_pipeline_setting(db)
    db.commit()
    return {
        "clean_check_enabled": setting.clean_check_enabled,
        "content_check_enabled": setting.content_check_enabled,
        "updated_at": setting.updated_at,
    }


@router.put("/organize-settings")
def put_organize_settings(
    request: OrganizePipelineSettingsRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    setting = get_or_create_organize_pipeline_setting(db)
    setting.clean_check_enabled = request.clean_check_enabled
    setting.content_check_enabled = request.content_check_enabled
    setting.updated_by = current_user.id
    db.commit()
    db.refresh(setting)
    return {
        "clean_check_enabled": setting.clean_check_enabled,
        "content_check_enabled": setting.content_check_enabled,
        "updated_at": setting.updated_at,
    }


@router.get("/models")
def get_models(
    model_type: str | None = None,
    ability_tier: str | None = None,
    ability_category: str | None = None,
    provider_name: str | None = None,
    enabled: bool | None = Query(default=None),
    keyword: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    models, total = list_models(
        db,
        model_type,
        ability_tier,
        ability_category,
        provider_name,
        enabled,
        keyword,
        page,
        page_size,
    )
    return {
        "items": [serialize_model(item) for item in models],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.post("/models", status_code=201)
def post_model(
    request: ModelCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    try:
        return serialize_model(create_model(db, request.model_dump()))
    except ModelConfigError as exc:
        _bad_request(exc)


@router.get("/models/{model_id}")
def get_model(
    model_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    model = db.get(ModelCatalog, model_id)
    if not model:
        raise HTTPException(status_code=404, detail="模型不存在")
    return serialize_model(model)


@router.patch("/models/{model_id}")
def patch_model(
    model_id: UUID,
    request: ModelUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    model = db.get(ModelCatalog, model_id)
    if not model:
        raise HTTPException(status_code=404, detail="模型不存在")
    try:
        return serialize_model(update_model(db, model, request.model_dump(exclude_unset=True)))
    except ModelConfigError as exc:
        _bad_request(exc)


@router.delete("/models/{model_id}", status_code=204)
def remove_model(
    model_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    model = db.get(ModelCatalog, model_id)
    if not model:
        raise HTTPException(status_code=404, detail="模型不存在")
    try:
        delete_model(db, model)
    except ModelConfigError as exc:
        _bad_request(exc)


@router.get("/channels")
def get_channels(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    return [serialize_channel(item) for item in db.query(ApiChannel).order_by(ApiChannel.created_at.desc()).all()]


@router.post("/channels", status_code=201)
def post_channel(
    request: ChannelCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    return serialize_channel(create_channel(db, request.model_dump()))


@router.get("/channels/{channel_id}")
def get_channel(
    channel_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    channel = db.get(ApiChannel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="渠道不存在")
    return serialize_channel(channel)


@router.patch("/channels/{channel_id}")
def patch_channel(
    channel_id: UUID,
    request: ChannelUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    channel = db.get(ApiChannel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="渠道不存在")
    try:
        return serialize_channel(update_channel(db, channel, request.model_dump(exclude_unset=True)))
    except ModelConfigError as exc:
        _bad_request(exc)


@router.delete("/channels/{channel_id}", status_code=204)
def remove_channel(
    channel_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    channel = db.get(ApiChannel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="渠道不存在")
    try:
        delete_channel(db, channel)
    except ModelConfigError as exc:
        _bad_request(exc)


@router.post("/channels/{channel_id}/clear-api-key")
def post_clear_api_key(
    channel_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    channel = db.get(ApiChannel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="渠道不存在")
    try:
        return serialize_channel(clear_channel_api_key(db, channel))
    except ModelConfigError as exc:
        _bad_request(exc)


@router.get("/channels/{channel_id}/models")
def get_channel_models(
    channel_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    channel = db.get(ApiChannel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="渠道不存在")
    rows = (
        db.query(ChannelModel)
        .options(joinedload(ChannelModel.model), joinedload(ChannelModel.channel))
        .filter(ChannelModel.channel_id == channel_id)
        .all()
    )
    return [serialize_channel_model(item) for item in rows]


@router.put("/channels/{channel_id}/models")
def put_channel_models(
    channel_id: UUID,
    request: list[ChannelModelRequest],
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    channel = (
        db.query(ApiChannel)
        .options(joinedload(ApiChannel.channel_models))
        .filter(ApiChannel.id == channel_id)
        .first()
    )
    if not channel:
        raise HTTPException(status_code=404, detail="渠道不存在")
    try:
        rows = set_channel_models(db, channel, [item.model_dump() for item in request])
        return [serialize_channel_model(item) for item in rows]
    except ModelConfigError as exc:
        _bad_request(exc)


@router.get("/models/{model_id}/channels")
def get_model_channels(
    model_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    model = db.get(ModelCatalog, model_id)
    if not model:
        raise HTTPException(status_code=404, detail="模型不存在")
    rows = (
        db.query(ChannelModel)
        .options(joinedload(ChannelModel.model), joinedload(ChannelModel.channel))
        .filter(ChannelModel.model_id == model_id)
        .all()
    )
    return [serialize_channel_model(item) for item in rows]


@router.put("/models/{model_id}/channels")
def put_model_channels(
    model_id: UUID,
    request: list[dict[str, Any]],
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    model = db.get(ModelCatalog, model_id)
    if not model:
        raise HTTPException(status_code=404, detail="模型不存在")
    try:
        existing = {
            item.channel_id: item
            for item in db.query(ChannelModel).filter(ChannelModel.model_id == model_id).all()
        }
        seen: set[UUID] = set()
        for row in request:
            channel_id = UUID(str(row["channel_id"]))
            channel = db.get(ApiChannel, channel_id)
            if channel is None:
                raise ModelConfigError("渠道不存在")
            enabled = bool(row.get("enabled", True))
            item = existing.get(channel_id)
            if item:
                if item.enabled and not enabled:
                    ensure_channel_model_not_used(db, item.id)
                item.enabled = enabled
            else:
                db.add(ChannelModel(
                    channel_id=channel_id,
                    model_id=model.id,
                    enabled=enabled,
                ))
            seen.add(channel_id)
        for channel_id, item in existing.items():
            if channel_id not in seen:
                ensure_channel_model_not_used(db, item.id)
                db.delete(item)
        db.commit()
        rows = (
            db.query(ChannelModel)
            .options(joinedload(ChannelModel.model), joinedload(ChannelModel.channel))
            .filter(ChannelModel.model_id == model_id)
            .all()
        )
        return [serialize_channel_model(item) for item in rows]
    except ModelConfigError as exc:
        _bad_request(exc)


@router.get("/model-settings")
def get_model_settings(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    return get_model_settings_payload(db)


@router.put("/model-settings")
def put_model_settings(
    request: ModelSettingsRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    try:
        return save_model_settings(
            db,
            {key: value.model_dump() for key, value in request.settings.items()},
            [item.model_dump() for item in request.steps],
            current_user.id,
        )
    except ModelConfigError as exc:
        _bad_request(exc)


@router.post("/model-settings/test")
async def test_model_setting(
    request: ModelTestRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    if not request.setting_key:
        raise HTTPException(status_code=400, detail="模型用途不能为空")
    if request.step_key and STEP_SETTING_KEYS.get(request.step_key) != request.setting_key:
        raise HTTPException(status_code=400, detail="环节与模型用途不匹配")
    if request.channel_model_id:
        channel_model = (
            db.query(ChannelModel)
            .options(joinedload(ChannelModel.model), joinedload(ChannelModel.channel))
            .filter(ChannelModel.id == request.channel_model_id)
            .first()
        )
        if not channel_model:
            raise HTTPException(status_code=400, detail="渠道模型不存在")
        try:
            validate_setting_choice(request.setting_key, channel_model)
            if request.setting_key not in {"transcription", "embedding", "graph_embedding"}:
                if request.thinking_enabled is None:
                    raise ModelConfigError("测试语言模型时必须指定思考状态")
                validate_thinking_choice(channel_model, request.thinking_enabled, request.step_key or request.setting_key)
            api_key = decrypt_channel_key(channel_model.channel)
        except ModelConfigError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        protocol = protocol_for_model_type(channel_model.model.model_type)
        api_base_url = channel_model.channel.api_base_url.rstrip("/")
        model_name = channel_model.model.model_name
        thinking_payload = {}
        if request.setting_key not in {"transcription", "embedding", "graph_embedding"}:
            from services.model_runtime import RuntimeModelConfig
            thinking_payload = resolve_thinking_payload(RuntimeModelConfig(
                setting_key=request.setting_key,
                step_key=request.step_key,
                model_type=channel_model.model.model_type,
                protocol=protocol,
                api_base_url=api_base_url,
                api_key=api_key,
                model_name=model_name,
                reasoning_mode=channel_model.model.reasoning_mode,
                thinking_enabled=request.thinking_enabled,
                thinkmode=channel_model.channel.thinkmode or {},
            ))
    else:
        try:
            config = resolve_model_setting(request.setting_key, request.step_key)
        except ModelRuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        protocol = config.protocol
        api_base_url = config.api_base_url
        api_key = config.api_key
        model_name = config.model_name
        thinking_payload = resolve_thinking_payload(config) if protocol == "openai_chat" else {}
    if protocol == "openai_embeddings":
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{api_base_url}/embeddings",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"model": model_name, "input": ["向量化配置测试"], "dimensions": 1024},
            )
            response.raise_for_status()
            data = response.json().get("data") or []
            if not data or not data[0].get("embedding"):
                raise HTTPException(status_code=502, detail="embedding 接口未返回向量")
        return {"status": "ok", "message": "向量化测试通过"}
    if protocol != "openai_chat":
        return {"status": "skipped", "message": "ASR 首版不执行真实音频测试"}
    async with httpx.AsyncClient(timeout=30) as client:
        body = {
            "model": model_name,
            "messages": [{"role": "user", "content": "返回 ok"}],
        }
        body.update(thinking_payload)
        response = await client.post(
            f"{api_base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json=body,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
    return {"status": "ok" if "ok" in content.lower() else "unexpected", "content": content}
