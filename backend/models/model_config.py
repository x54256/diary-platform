"""AI 模型管理数据模型。"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from database import Base


class ModelCatalog(Base):
    """模型能力清单。"""

    __tablename__ = "model_catalog"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    model_type = Column(String(20), nullable=False)  # language / asr
    provider_name = Column(String(100), nullable=False)
    model_name = Column(String(200), nullable=False, unique=True)
    ability_tier = Column(String(100), nullable=False)
    ability_category = Column(String(50), nullable=False)
    original_category = Column(String(100), nullable=True)
    core_features = Column(Text, nullable=True)
    scenarios = Column(Text, nullable=True)
    score = Column(Float, nullable=True)
    score_label = Column(String(50), nullable=True)
    enabled = Column(Boolean, default=True, nullable=False)
    is_custom = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    channel_models = relationship("ChannelModel", back_populates="model", cascade="all, delete-orphan")


class ApiChannel(Base):
    """API 调用渠道。"""

    __tablename__ = "api_channels"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False, unique=True)
    api_base_url = Column(String(500), nullable=False)
    api_key_encrypted = Column(Text, nullable=True)
    enabled = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    channel_models = relationship("ChannelModel", back_populates="channel", cascade="all, delete-orphan")


class ChannelModel(Base):
    """渠道支持模型关系。"""

    __tablename__ = "channel_models"
    __table_args__ = (
        UniqueConstraint("channel_id", "model_id", name="uq_channel_models_channel_model"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    channel_id = Column(UUID(as_uuid=True), ForeignKey("api_channels.id", ondelete="CASCADE"), nullable=False)
    model_id = Column(UUID(as_uuid=True), ForeignKey("model_catalog.id", ondelete="CASCADE"), nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    channel = relationship("ApiChannel", back_populates="channel_models")
    model = relationship("ModelCatalog", back_populates="channel_models")
    settings = relationship("ModelSetting", back_populates="channel_model")


class ModelSetting(Base):
    """业务用途当前模型设置。"""

    __tablename__ = "model_settings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    setting_key = Column(String(30), nullable=False, unique=True)
    channel_model_id = Column(UUID(as_uuid=True), ForeignKey("channel_models.id"), nullable=False)
    updated_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    channel_model = relationship("ChannelModel", back_populates="settings")
    updater = relationship("User")
