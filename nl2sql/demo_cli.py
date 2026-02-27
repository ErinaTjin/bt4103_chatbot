import json
import os
import sys

# Allow running this file directly: `python nl2sql/demo_cli.py`
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from nl2sql.extractor import QueryExtractor
from nl2sql.guardrails import check_sql
from nl2sql.plan_utils import (
    normalize_filter_values,
    normalize_plan_fields,
    validate_plan_fields,
)
from nl2sql.field_mapper import FieldMapper
from backend.semantic_layer.loader import SemanticLayerLoader
from nl2sql.sql_builder import build_sql


def main() -> None:
    extractor = QueryExtractor()

    semantic_dir = os.path.join(ROOT, "backend", "semantic_layer")
    sl = None
    if os.path.isdir(semantic_dir):
        sl = SemanticLayerLoader(semantic_dir).load()

    # Build synonym -> canonical field map from terminology.json
    mapping = {}
    allowed_fields = set()
    metrics = None
    value_synonyms = {}
    if sl and "anchor_view" in sl.tables:
        allowed_fields = {c.name for c in sl.tables["anchor_view"].columns}
        metrics = sl.metrics

        for canonical, synonyms in sl.terminology_fields.items():
            for s in [canonical] + list(synonyms):
                mapping[s] = canonical

        value_synonyms = sl.terminology_values or {}

    mapper = FieldMapper(mapping)

    print("NCCS NL→SQL MVP Demo (type 'exit' to quit)")
    if allowed_fields:
        print(f"Loaded semantic layer: {len(allowed_fields)} fields")
    else:
        print("Semantic layer not found; field validation disabled")

    while True:
        question = input("\nAsk: ").strip()
        if question.lower() in {"exit", "quit"}:
            break
        if not question:
            continue

        plan = extractor.extract(question)
        plan = normalize_plan_fields(plan, mapper, None)
        plan = normalize_filter_values(plan, value_synonyms)
        field_warnings = validate_plan_fields(plan, allowed_fields if allowed_fields else None)

        sql = build_sql(plan, metrics=metrics)
        guard = check_sql(sql)
        if field_warnings:
            guard["warnings"].extend(field_warnings)
            guard["ok"] = False

        print("\nQueryPlan JSON:")
        print(json.dumps(plan.dict(), indent=2))
        print("\nSQL:")
        print(sql)
        print("\nGuardrails:")
        print(json.dumps(guard, indent=2))


if __name__ == "__main__":
    main()
