from __future__ import annotations

from enum import Enum
from typing import List, Optional, Union, Any

from pydantic import BaseModel, Field, validator


class Intent(str, Enum):
    count = "count"
    distribution = "distribution"
    trend = "trend"
    topN = "topN"
    mutation_prevalence = "mutation_prevalence"
    cohort_comparison = "cohort_comparison"
    unsupported = "unsupported"


class Filter(BaseModel):
    field: str
    op: str
    value: Union[str, int, float, List[Union[str, int, float]]]


class SortOption(BaseModel):
    field: str
    direction: str = Field(default="desc", pattern="^(asc|desc)$")


class OutputPrefs(BaseModel):
    preferred_visualization: Optional[str] = None


class QueryPlan(BaseModel):
    intent: Intent
    metric: str = Field(default="count_patients")
    dimensions: List[str] = Field(default_factory=list)
    filters: List[Filter] = Field(default_factory=list)
    sort: List[SortOption] = Field(default_factory=list)
    limit: int = Field(default=50)
    output: Optional[OutputPrefs] = None
    
    needs_clarification: bool = Field(default=False)
    clarification_question: Optional[str] = None

    @validator("limit")
    def _limit_positive(cls, v: int) -> int:
        return max(1, v)


class PhysicalPlan(BaseModel):
    """
    Represents the mapped plan that is passed to the SQL templates.
    All fields/tables have been resolved by the Semantic Layer.
    """
    intent: Intent
    metric_sql: str
    dimensions_sql: List[str]
    from_tables: List[str]
    joins: List[str]
    where_clauses: List[str]
    group_by: List[str]
    order_by: List[str]
    limit: int
