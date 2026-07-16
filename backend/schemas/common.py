"""响应模型通用序列化工具"""

from datetime import datetime, timezone
from typing import Optional


def serialize_utc_datetime(value: Optional[datetime]) -> Optional[str]:
    """将后端无时区 UTC 时间输出为带 Z 的 ISO 字符串。"""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.isoformat().replace("+00:00", "Z")
