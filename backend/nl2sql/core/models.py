# Pydantic schemas for representing the structured query plan and related data structures in the NL2SQL system.
from __future__ import annotations

from enum import Enum
from typing import Any, List, Optional, Union

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

# Not used
class QueryPlan(BaseModel):
    intent: Intent
    metric: Optional[str] = Field(default="count_patients")
    dimensions: Optional[List[str]] = Field(default_factory=list)
    filters: Optional[List[Filter]] = Field(default_factory=list)
    sort: Optional[List[SortOption]] = Field(default_factory=list)
    limit: Optional[int] = Field(default=50)
    output: Optional[OutputPrefs] = None

    needs_clarification: bool = Field(default=False)
    clarification_question: Optional[str] = None

    @validator("metric", pre=True, always=True)
    def _metric_default(cls, v):
        return v if v is not None else "count_patients"

    @validator("dimensions", "filters", "sort", pre=True, always=True)
    def _list_default(cls, v):
        return v if v is not None else []

    @validator("limit", pre=True, always=True)
    def _limit_positive(cls, v) -> int:
        if v is None:
            return 50
        return max(1, int(v))

# Not used
class PhysicalPlan(BaseModel):
    intent: Intent
    metric_sql: str
    dimensions_sql: List[str]
    from_tables: List[str]
    joins: List[str]
    where_clauses: List[str]
    group_by: List[str]
    order_by: List[str]
    limit: int


class Agent1ContextSummary(BaseModel):
    intent: Intent
    intent_summary: str
    needs_clarification: bool = False
    clarification_question: Optional[str] = None
    extracted_filters: List[Filter] = Field(default_factory=list)
    active_filters: dict[str, Any] = Field(default_factory=dict)
    validation_errors: List[str] = Field(default_factory=list)


class ContextResolution(BaseModel):
    standalone_question: str
    context_summary: Optional[str] = None
    needs_clarification: bool = False
    clarification_question: Optional[str] = None
    is_follow_up: bool = True  # False = brand new topic, active_filters should be ignored


class Agent2SQLWriterOutput(BaseModel):
    sql: str
    preferred_visualization: Optional[str] = None
    reasoning_summary: Optional[str] = None
    assumptions: Optional[List[str]] = None
    warnings: Optional[List[str]] = None
