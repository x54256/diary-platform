"""整理流水线运行时配置。"""

from dataclasses import dataclass

from database import SessionLocal
from models.organize_settings import OrganizePipelineSetting


@dataclass(frozen=True)
class OrganizePipelineOptions:
    clean_check_enabled: bool = False
    content_check_enabled: bool = False


def get_organize_pipeline_options() -> OrganizePipelineOptions:
    """读取最新配置，不使用进程缓存，管理端修改后立即生效。"""
    db = SessionLocal()
    try:
        setting = db.get(OrganizePipelineSetting, 1)
        if not setting:
            return OrganizePipelineOptions()
        return OrganizePipelineOptions(
            clean_check_enabled=setting.clean_check_enabled,
            content_check_enabled=setting.content_check_enabled,
        )
    finally:
        db.close()


def get_or_create_organize_pipeline_setting(db):
    setting = db.get(OrganizePipelineSetting, 1)
    if not setting:
        setting = OrganizePipelineSetting(id=1)
        db.add(setting)
        db.flush()
    return setting
