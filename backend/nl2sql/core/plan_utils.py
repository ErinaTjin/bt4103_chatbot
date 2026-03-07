#contains helper functions for cleaning and validating query plan
from __future__ import annotations

from typing import Dict, List, Optional

from .field_mapper import FieldMapper
from .models import QueryPlan
from ..schema_loader import CdmDictionary

def _remove_table_prefix(field: str) -> str:
    """
    remove table prefix from field name if present, so we are checking only the columns
    e.g. "condition_occurrence.condition_start_date" -> "condition_start_date"
    """
    if "." in field:
        return field.split(".")[-1]
    return field

def normalize_plan_fields(
    plan: QueryPlan,
    mapper: FieldMapper,
    cdm: Optional[CdmDictionary] = None,
) -> QueryPlan:
    # remove table prefixes first, then resolve through mapper
    plan.dimensions = [mapper.resolve(_remove_table_prefix(d), cdm) for d in plan.dimensions]
    for f in plan.filters:
        f.field = mapper.resolve(_remove_table_prefix(f.field), cdm)
    return plan


def normalize_filter_values(
    plan: QueryPlan,
    value_synonyms: Optional[Dict[str, List[str]]] = None,
) -> QueryPlan:
    if not value_synonyms:
        return plan

    # Build reverse lookup: synonym -> canonical
    reverse = {}
    for canonical, synonyms in value_synonyms.items():
        if isinstance(synonyms, list):
            for s in [canonical] + synonyms:
                reverse[s.lower().strip()] = canonical

    for f in plan.filters:
        # only nomalise scalar string value, not lists (used by in/or_like operations)
        if isinstance(f.value, str):
            key = f.value.lower().strip()
            if key in reverse:
                f.value = reverse[key]
    return plan


def validate_plan_fields(
    plan: QueryPlan,
    allowed_fields: Optional[set[str]] = None,
) -> List[str]:
    if not allowed_fields:
        return []

    warnings: List[str] = []
    for d in plan.dimensions:
        if d and d not in allowed_fields:
            warnings.append(f"Unknown dimension field: {d}")
    for f in plan.filters:
        if f.field and f.field not in allowed_fields:
            warnings.append(f"Unknown filter field: {f.field}")
    return warnings
