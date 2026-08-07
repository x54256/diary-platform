"""统一搜索响应契约。

搜索响应复用 DiaryEventResponse 字段，并追加检索附加字段：
- diary_id: 事件所属日记 ID（点击跳转用）
- diary_date: 事件日期（取自所属 diary.diary_date）
- rank: 相关度分（RRF 融合分 / similarity 值，前端仅排序用）
- analysis_run_id: 当前分析轮次 ID（供事件卡渲染分析区块与反馈）
- matched_chunk_types: 命中语义层（fact / self_understanding / cognition），前端层高亮用；
  纯关键词命中或语义分支不可用时为空列表（决策 3：结果单位=事件，命中层高亮）。
"""

from datetime import date
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel

from schemas.diary import DiaryEventResponse

# 检索模式：关键词 / 语义 / 混合（RRF 融合）。决策 9：前端始终 hybrid。
SearchMode = Literal["keyword", "semantic", "hybrid"]
SEARCH_MODE_VALUES = ("keyword", "semantic", "hybrid")


class EventSearchResultResponse(DiaryEventResponse):
    """搜索命中的事件卡响应：复用 DiaryEventResponse + 检索附加字段。"""

    diary_id: UUID
    diary_date: date
    rank: float = 0.0
    analysis_run_id: Optional[UUID] = None
    matched_chunk_types: list[str] = []


class SearchListResponse(BaseModel):
    """搜索结果列表响应。"""

    items: list[EventSearchResultResponse] = []
    total: int = 0
