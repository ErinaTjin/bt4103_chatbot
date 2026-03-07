# validate_plan.py
# Structured-plan validation only. Raw SQL policy lives in app/db/sql_policy.py.

from __future__ import annotations

from typing import Dict, List, Optional, Set

from .models import QueryPlan


ALLOWED_FILTER_OPS = {"=", "!=", ">", "<", ">=", "<=", "in", "like", "or_like"}
ALLOWED_SORT_DIRECTIONS = {"asc", "desc"}


def validate_query_plan(
    plan: QueryPlan,
    *,
    allowed_fields: Optional[Set[str]] = None,
    allowed_metrics: Optional[Set[str]] = None,
    max_limit: int = 1000,
    require_aggregation_metric: bool = False,
) -> List[str]:
    warnings: List[str] = []

    # metric validation
    if allowed_metrics is not None and plan.metric not in allowed_metrics:
        warnings.append(f"Unknown metric: {plan.metric}")

    # dimensions
    if allowed_fields is not None:
        for d in plan.dimensions:
            if d and d not in allowed_fields:
                warnings.append(f"Unknown dimension field: {d}")

    # filters
    if allowed_fields is not None:
        for f in plan.filters:
            if f.field and f.field not in allowed_fields:
                warnings.append(f"Unknown filter field: {f.field}")

    for f in plan.filters:
        op = f.op.lower().strip()
        if op not in ALLOWED_FILTER_OPS:
            warnings.append(f"Unsupported filter operator: {f.op}")

        if op == "in" and not isinstance(f.value, list):
            warnings.append("Operator 'in' requires a list value.")

    # sort validation
    valid_sort_targets = set(plan.dimensions)
    valid_sort_targets.add(plan.metric)

    for s in plan.sort:
        if s.direction.lower() not in ALLOWED_SORT_DIRECTIONS:
            warnings.append(f"Unsupported sort direction: {s.direction}")

        if s.field not in valid_sort_targets:
            warnings.append(
                f"Unsupported sort field: {s.field}. "
                f"Sort fields must be one of selected dimensions or the metric name."
            )

    # product-level policy
    if require_aggregation_metric and not plan.metric:
        warnings.append("This application requires an aggregate metric.")

    # clamp limit in place
    if plan.limit is None or plan.limit <= 0:
        plan.limit = 50
    elif plan.limit > max_limit:
        plan.limit = max_limit

    return warnings
