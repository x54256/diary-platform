"""热词与人物关系接口模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


Gender = Literal["male", "female", "unknown"]


class HotWordCreate(BaseModel):
    text: str = Field(min_length=1, max_length=100)

    @field_validator("text")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("热词不能为空")
        return value


class HotWordResponse(BaseModel):
    id: UUID
    text: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PersonRelationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    common_names: list[str] = Field(default_factory=list, max_length=20)
    gender: Gender = "unknown"
    relation: str = Field(min_length=1, max_length=100)

    @field_validator("name", "relation")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("字段不能为空")
        return value

    @field_validator("common_names")
    @classmethod
    def normalize_common_names(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for value in values:
            value = value.strip()
            if not value:
                continue
            key = value.casefold()
            if key not in seen:
                seen.add(key)
                normalized.append(value)
        return normalized


class PersonRelationResponse(PersonRelationCreate):
    id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
