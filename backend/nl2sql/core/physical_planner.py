#physical_planner.py
from __future__ import annotations

from collections import deque
from typing import Any

from .models import PhysicalPlan, QueryPlan
from .semantic_resolver import SemanticResolver


class PhysicalPlanner:
    """
    Converts a logical QueryPlan into a PhysicalPlan using semantic metadata.
    """

    def __init__(self, semantic_api: Any, schema_name: str = "anchor_view") -> None:
        self.semantic_api = semantic_api
        self.schema_name = schema_name
        self.resolver = SemanticResolver(semantic_api)

    def build(self, plan: QueryPlan, metrics: dict | None = None) -> PhysicalPlan:
        needed_fields = set(plan.dimensions)
        needed_fields.update(f.field for f in plan.filters)

        metric_sql, metric_tables = self._resolve_metric(plan.metric, metrics)
        needed_tables = set(metric_tables)

        dimensions_sql: list[str] = []
        group_by: list[str] = []

        for dim in plan.dimensions:
            resolved = self.resolver.resolve_column(dim)
            needed_tables.add(resolved.table)
            expr = f'{resolved.table}.{resolved.column}'
            dimensions_sql.append(expr)
            group_by.append(expr)

        where_clauses: list[str] = []
        for flt in plan.filters:
            resolved = self.resolver.resolve_column(flt.field)
            needed_tables.add(resolved.table)
            expr = f'{resolved.table}.{resolved.column}'
            where_clauses.append(self._render_filter(expr, flt.op, flt.value))

        if not needed_tables:
            # fallback to person as default root table
            needed_tables.add("person")

        base_table = self._choose_base_table(needed_tables)
        join_clauses = self._build_join_clauses(base_table, needed_tables)

        order_by = self._build_order_by(plan, dimensions_sql, metric_sql)

        return PhysicalPlan(
            intent=plan.intent,
            metric_sql=metric_sql,
            dimensions_sql=dimensions_sql,
            from_tables=[f'"{self.schema_name}"."{base_table}" AS {base_table}'],
            joins=join_clauses,
            where_clauses=where_clauses,
            group_by=group_by,
            order_by=order_by,
            limit=plan.limit or 50,
        )

    def _resolve_dimension_expr(self, table: str, column: str) -> str:
        """
        Special handling for computed dimensions.
        year_of_birth is rendered as an age expression.
        """
        if column == "year_of_birth":
            return f"(YEAR(CURRENT_DATE) - {table}.year_of_birth) AS age"
        return f"{table}.{column}"
    
    def _resolve_metric(self, metric: str, metrics: dict | None) -> tuple[str, set[str]]:
        if metrics and metric in metrics:
            metric_def = metrics[metric]
            sql = metric_def.get("sql", "")
            used_tables = set(metric_def.get("tables", []))
            if sql:
                # Wrap in subexpression to safely alias window functions
               return f"({sql}) AS {metric}", used_tables

        # default metric
        return "COUNT(DISTINCT person.person_id) AS count_patients", set()

    def _render_filter(self, expr: str, op: str, value) -> str:
        op_lower = op.lower()

        if op_lower == "in":
            if isinstance(value, list):
                vals = ", ".join(self._quote(v) for v in value)
            else:
                # if LLM returned "a,b,c" as string, leave room for quick fallback
                vals = str(value)
            return f"{expr} IN ({vals})"

        if op_lower == "like":
            return f"{expr} LIKE {self._quote(value)}"
        
        if op_lower == "not like":
            return f"{expr} NOT LIKE {self._quote(value)}"

        if op_lower == "or_like":
            # Renders as: (expr LIKE '%val1%' OR expr LIKE '%val2%')
            if isinstance(value, list):
                parts = " OR ".join(f"{expr} LIKE {self._quote(v)}" for v in value)
                return f"({parts})"
            return f"{expr} LIKE {self._quote(value)}"

        return f"{expr} {op} {self._quote(value)}"

    def _quote(self, value) -> str:
        if isinstance(value, (int, float)):
            return str(value)
        escaped = str(value).replace("'", "''")
        return f"'{escaped}'"

    def _choose_base_table(self, needed_tables: set[str]) -> str:
        # choose person if involved, else deterministic first table
        if "person" in needed_tables:
            return "person"
        return sorted(needed_tables)[0]

    def _build_order_by(self, plan: QueryPlan, dimensions_sql: list[str], metric_sql: str) -> list[str]:
        # Extract alias — always the last word after AS
        metric_alias = metric_sql.strip().split(" AS ")[-1].strip()

        if plan.sort:
            order_by = []
            for s in plan.sort:
                if s.field in [d.split(".")[-1] for d in dimensions_sql]:
                    matching = [d for d in dimensions_sql if d.endswith(f".{s.field}")]
                    if matching:
                        order_by.append(f"{matching[0]} {s.direction.upper()}")
                else:
                    order_by.append(f"{s.field} {s.direction.upper()}")
            return order_by

        if plan.intent == "trend" and dimensions_sql:
            return [f"{dimensions_sql[0]} ASC"]

        return [f"{metric_alias} DESC"]

    def _build_join_clauses(self, base_table: str, needed_tables: set[str]) -> list[str]:
        """
        For now: shortest path from base_table to each required table.
        Assumes joins are described in semantic_api.joins.
        """
        joins_needed: list[str] = []
        already_joined = {base_table}

        for target in sorted(needed_tables):
            if target == base_table:
                continue

            path = self._find_join_path(base_table, target)
            if not path:
                raise ValueError(f"No join path found from {base_table} to {target}")

            for edge in path:
                left = edge["left_table"]
                right = edge["right_table"]
                left_key = edge["left_key"]
                right_key = edge["right_key"]
                join_type = edge.get("join_type", "LEFT").upper()

                if right in already_joined:
                    continue

                joins_needed.append(
                    f'{join_type} JOIN "{self.schema_name}"."{right}" AS {right} '
                    f'ON {left}.{left_key} = {right}.{right_key}'
                )
                already_joined.add(right)

        return joins_needed

    def _find_join_path(self, start: str, target: str) -> list[dict]:
        """
        BFS on directed/undirected interpretation of semantic joins.
        """
        graph: dict[str, list[tuple[str, dict]]] = {}

        for edge in getattr(self.semantic_api, "joins", []):
            l = edge["left_table"]
            r = edge["right_table"]

            graph.setdefault(l, []).append((r, edge))

            reverse_edge = {
                "left_table": r,
                "right_table": l,
                "left_key": edge["right_key"],
                "right_key": edge["left_key"],
                "join_type": edge.get("join_type", "LEFT"),
            }
            graph.setdefault(r, []).append((l, reverse_edge))

        queue = deque([(start, [])])
        visited = {start}

        while queue:
            node, path = queue.popleft()
            if node == target:
                return path

            for neighbor, edge in graph.get(node, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, path + [edge]))

        return []
