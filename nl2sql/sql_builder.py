from __future__ import annotations

from .models import QueryPlan


VIEW_NAME = "anchor_view"


def _metric_sql(metric: str, metrics: dict | None = None) -> str:
    if metrics and metric in metrics and metrics[metric].get("sql"):
        return f"{metrics[metric]['sql']} AS {metric}"
    if metric == "count_patients":
        return "COUNT(*) AS count_patients"
    # Fallback: treat metric as raw safe aggregate name
    return f"{metric}"


def _filters_sql(filters) -> str:
    if not filters:
        return ""
    clauses = []
    for f in filters:
        value = f.value
        if f.op.lower() == "in":
            clauses.append(f"{f.field} IN ({value})")
        else:
            clauses.append(f"{f.field} {f.op} '{value}'")
    return " WHERE " + " AND ".join(clauses)


def build_sql(plan: QueryPlan, metrics: dict | None = None) -> str:
    metric_sql = _metric_sql(plan.metric, metrics)
    filters_sql = _filters_sql(plan.filters)
    limit = plan.limit or 50

    if plan.intent == "distribution":
        dim = plan.dimensions[0] if plan.dimensions else "stage"
        return (
            f"SELECT {dim}, {metric_sql} "
            f"FROM {VIEW_NAME}{filters_sql} "
            f"GROUP BY {dim} "
            f"ORDER BY {metric_sql.split(' AS ')[-1]} DESC "
            f"LIMIT {limit}"
        )

    if plan.intent == "trend":
        dim = "year"
        return (
            f"SELECT {dim}, {metric_sql} "
            f"FROM {VIEW_NAME}{filters_sql} "
            f"GROUP BY {dim} "
            f"ORDER BY {dim} ASC "
            f"LIMIT {limit}"
        )

    if plan.intent == "topN":
        dim = plan.dimensions[0] if plan.dimensions else "cancer_type"
        return (
            f"SELECT {dim}, {metric_sql} "
            f"FROM {VIEW_NAME}{filters_sql} "
            f"GROUP BY {dim} "
            f"ORDER BY {metric_sql.split(' AS ')[-1]} DESC "
            f"LIMIT {limit}"
        )

    if plan.intent == "count":
        return (
            f"SELECT {metric_sql} "
            f"FROM {VIEW_NAME}{filters_sql} "
            f"LIMIT {limit}"
        )

    if plan.intent == "cohort_comparison":
        dim1 = plan.dimensions[0] if len(plan.dimensions) > 0 else "stage"
        dim2 = plan.dimensions[1] if len(plan.dimensions) > 1 else "cancer_type"
        return (
            f"SELECT {dim1}, {dim2}, {metric_sql} "
            f"FROM {VIEW_NAME}{filters_sql} "
            f"GROUP BY {dim1}, {dim2} "
            f"ORDER BY {metric_sql.split(' AS ')[-1]} DESC "
            f"LIMIT {limit}"
        )

    # unsupported
    return (
        f"SELECT {metric_sql} FROM {VIEW_NAME}{filters_sql} "
        f"LIMIT {limit}"
    )
