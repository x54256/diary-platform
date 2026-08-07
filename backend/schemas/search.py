"""日记级混合搜索响应契约。"""

from datetime import date
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

SemanticStatus = Literal["READY", "PARTIAL", "UNAVAILABLE"]


class SearchRanking(BaseModel):
    keyword_score: Optional[float] = None
    keyword_rank: Optional[int] = None
    semantic_score: Optional[float] = None
    semantic_rank: Optional[int] = None
    rrf_score: float
    rrf_rank: int


class DiarySearchMatch(BaseModel):
    event_id: UUID
    analysis_run_id: Optional[UUID] = None
    kind: str
    semantic_layer: Optional[str] = None
    snippet: str
    keyword_matched: bool = False


class DiarySearchResultResponse(BaseModel):
    diary_id: UUID
    title: Optional[str] = None
    diary_date: date
    ranking: SearchRanking
    matches: list[DiarySearchMatch] = Field(default_factory=list)


class SearchListResponse(BaseModel):
    items: list[DiarySearchResultResponse] = Field(default_factory=list)
    total: int = 0
    semantic_status: SemanticStatus = "READY"
