from __future__ import annotations

from typing import Dict, List, Optional

from .field_mapper import FieldMapper
from .models import QueryPlan
from .schema_loader import CdmDictionary


def normalize_plan_fields(
    plan: QueryPlan,
    mapper: FieldMapper,
    cdm: Optional[CdmDictionary] = None,
) -> QueryPlan:
    plan.dimensions = [mapper.resolve(d, cdm) for d in plan.dimensions]
    for f in plan.filters:
        f.field = mapper.resolve(f.field, cdm)
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
        for s in [canonical] + list(synonyms):
            reverse[s.lower().strip()] = canonical

    for f in plan.filters:
        key = str(f.value).lower().strip()
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
