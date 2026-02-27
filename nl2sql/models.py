from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, validator


class Intent(str, Enum):
    distribution = "distribution"
    trend = "trend"
    topN = "topN"
    comparison = "comparison"
    unsupported = "unsupported"


class Filter(BaseModel):
    field: str
    op: str
    value: str


class QueryPlan(BaseModel):
    intent: Intent
    metric: str = Field(default="count_patients")
    dimensions: List[str] = Field(default_factory=list)
    filters: List[Filter] = Field(default_factory=list)
    limit: int = Field(default=50)
    needs_clarification: bool = Field(default=False)
    clarification_question: Optional[str] = None

    @validator("limit")
    def _limit_positive(cls, v: int) -> int:
        return max(1, v)
