#semantic_resolver.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ResolvedColumn:
    table: str
    column: str

    @property
    def qualified(self) -> str:
        return f'{self.table}.{self.column}'


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
        table = self.field_to_table.get(field_name)
        if not table:
            raise ValueError(f"Unknown field: {field_name}")
        return ResolvedColumn(table=table, column=field_name)

    def all_allowed_fields(self) -> set[str]:
        return set(self.field_to_table.keys())