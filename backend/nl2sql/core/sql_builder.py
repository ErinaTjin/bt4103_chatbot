#converts query plan into SQL
from __future__ import annotations

from .models import PhysicalPlan


def build_sql(plan: PhysicalPlan) -> str:
    select_parts = []
    if plan.dimensions_sql:
        select_parts.extend(plan.dimensions_sql)
    select_parts.append(plan.metric_sql)

    sql = f"SELECT {', '.join(select_parts)} "
    sql += f"FROM {plan.from_tables[0]} "

    if plan.joins:
        sql += " ".join(plan.joins) + " "

    if plan.where_clauses:
        sql += "WHERE " + " AND ".join(plan.where_clauses) + " "

    if plan.group_by:
        sql += "GROUP BY " + ", ".join(plan.group_by) + " "

    if plan.order_by:
        sql += "ORDER BY " + ", ".join(plan.order_by) + " "

    sql += f"LIMIT {plan.limit}"

    return sql.strip()