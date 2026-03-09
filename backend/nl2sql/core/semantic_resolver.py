#semantic_resolver.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ResolvedColumn:
    table: str
    column: str
    sql_expr: Optional[str] = field(default=None)   # set for computed columns
    alias: Optional[str] = field(default=None)       # SELECT alias for computed columns

    @property
    def qualified(self) -> str:
        return f'{self.table}.{self.column}'


# Computed columns: concept name → {table, filter_expr, select_expr, alias}
# filter_expr  — SQL fragment used in WHERE clauses
# select_expr  — SQL fragment used in SELECT / GROUP BY (may differ, e.g. needs alias)
# alias        — name used in GROUP BY and ORDER BY after SELECT
COMPUTED_COLUMNS: dict[str, dict] = {
    "age": {
        "table": "person",
        "filter_expr": "YEAR(CURRENT_DATE) - person.year_of_birth",
        "select_expr": "(YEAR(CURRENT_DATE) - person.year_of_birth) AS age",
        "alias": "age",
    },
    "diagnosis_year": {
        "table": "condition_occurrence",
        "filter_expr": "YEAR(condition_occurrence.condition_start_date)",
        "select_expr": "YEAR(condition_occurrence.condition_start_date) AS diagnosis_year",
        "alias": "diagnosis_year",
    },
}


class SemanticResolver:
    """
    Resolves canonical field names to their physical table + column.
    Also exposes join graph metadata from the semantic layer.
    """

    def __init__(self, semantic_api: Any):
        self.semantic_api = semantic_api
        self.field_to_table = self._build_field_index()
        self.joins = getattr(semantic_api, "joins", []) if semantic_api else []

    def _build_field_index(self) -> dict[str, str]:
        field_to_table: dict[str, str] = {}

        if not self.semantic_api or not hasattr(self.semantic_api, "tables"):
            return field_to_table

        for table_name, table in self.semantic_api.tables.items():
            for col in table.columns:
                # If duplicate names exist across tables, first one wins for now.
                # To be improved with ambiguity handling.
                field_to_table.setdefault(col.name, table_name)

        return field_to_table

    def resolve_column(self, field_name: str) -> ResolvedColumn:
        # Check computed columns first
        if field_name in COMPUTED_COLUMNS:
            c = COMPUTED_COLUMNS[field_name]
            return ResolvedColumn(
                table=c["table"],
                column=field_name,
                sql_expr=c["filter_expr"],
                alias=c["alias"],
            )

        table = self.field_to_table.get(field_name)
        if not table:
            raise ValueError(f"Unknown field: {field_name}")
        return ResolvedColumn(table=table, column=field_name)

    def all_allowed_fields(self) -> set[str]:
        return set(self.field_to_table.keys()) | set(COMPUTED_COLUMNS.keys())