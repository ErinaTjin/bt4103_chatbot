from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict

from nl2sql.core.models import PhysicalPlan, QueryPlan


class NL2SQLState(TypedDict, total=False):
    question: str
    effective_question: str
    active_filters: Optional[Dict[str, Any]]
    chat_history: List[Dict[str, Any]]

    schema_context: str
    constraints: str

    plan: Optional[QueryPlan]
    plan_agent1: Optional[QueryPlan]
    plan_agent2: Optional[QueryPlan]
    physical_plan: Optional[PhysicalPlan]
    sql: str

    warnings: List[str]
    error: Optional[str]
    retry_count: int
    max_retries: int

    needs_clarification: bool
    clarification_question: Optional[str]

    valid: bool
