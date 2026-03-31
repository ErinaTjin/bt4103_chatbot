from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.config import settings


@dataclass(frozen=True)
class SchemaWhitelists:
    allowed_columns: set[str]
    allowed_values_by_column: dict[str, set[str]]


_QUOTED_VALUE_PATTERN = re.compile(r"'([^']+)'")


def _extract_quoted_values(text: str) -> set[str]:
    return {m.group(1).strip().lower() for m in _QUOTED_VALUE_PATTERN.finditer(text) if m.group(1).strip()}


def _build_value_whitelist_for_column(column_name: str, description: str) -> set[str]:
    desc_lower = description.lower()
    values: set[str] = set()

    # Canonical value lists are usually documented in these phrases.
    if "distinct values in data" in desc_lower:
        values |= _extract_quoted_values(description)

    if column_name == "measurement_concept_name" and "only 14 valid values" in desc_lower:
        values |= _extract_quoted_values(description)

    if column_name == "value_as_concept_name":
        if "stage values" in desc_lower or "mutation values" in desc_lower or "grade values" in desc_lower:
            values |= _extract_quoted_values(description)

    return values


@lru_cache(maxsize=1)
def get_schema_whitelists() -> SchemaWhitelists:
    schema_path = Path(settings.SEMANTIC_LAYER_DIR) / "schema.json"
    if not schema_path.exists():
        return SchemaWhitelists(allowed_columns=set(), allowed_values_by_column={})

    with schema_path.open("r", encoding="utf-8") as f:
        schema = json.load(f)

    allowed_columns: set[str] = set()
    allowed_values_by_column: dict[str, set[str]] = {}

    for table in schema.get("tables", {}).values():
        for col in table.get("columns", []):
            name = str(col.get("name", "")).strip().lower()
            if not name:
                continue

            allowed_columns.add(name)

            description = str(col.get("description", ""))
            values = _build_value_whitelist_for_column(name, description)
            if values:
                allowed_values_by_column.setdefault(name, set()).update(values)

    return SchemaWhitelists(
        allowed_columns=allowed_columns,
        allowed_values_by_column=allowed_values_by_column,
    )
