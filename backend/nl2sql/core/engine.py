#engine.py
#main NL2SQL engine that orchestrates the full pipeline from natural language to SQL, 
# including semantic mapping, logical->physical planning, and guardrails.
from __future__ import annotations

from typing import Dict, Any, List

from nl2sql.core.models import QueryPlan, PhysicalPlan
from nl2sql.core.llm_adapter import LLMAdapter
from nl2sql.core.extractor import QueryExtractor
from nl2sql.core.plan_utils import (
    normalize_plan_fields,
    normalize_filter_values,
)
from nl2sql.core.validate_plan import validate_query_plan
from .field_mapper import FieldMapper
from .physical_planner import PhysicalPlanner
from .sql_builder import build_sql


# container for the final result
class TranslationResult:
    def __init__(
        self,
        sql: str,
        plan: QueryPlan,
        physical_plan: PhysicalPlan | None,
        valid: bool,
        warnings: List[str],
    ):
        self.sql = sql
        self.plan = plan
        self.physical_plan = physical_plan
        self.valid = valid
        self.warnings = warnings


class NL2SQLEngine:
    def __init__(
        self,
        llm: LLMAdapter | None = None,
        semantic_api: Any = None,
    ):
        self.llm = llm or LLMAdapter()
        self.extractor = QueryExtractor(self.llm)
        self.semantic_api = semantic_api

        # Semantic / metadata setup
        self.mapper = self._init_mapper()
        self.allowed_fields = self._init_allowed_fields()
        self.value_synonyms = self._init_value_synonyms()
        self.metrics = self._init_metrics()

        # logical -> physical planning layer
        self.planner = PhysicalPlanner(semantic_api=self.semantic_api)

    # mapping terminology via semantic layer
    def _init_mapper(self) -> FieldMapper:
        mapping: dict[str, str] = {}

        if self.semantic_api and hasattr(self.semantic_api, "terminology_fields"):
            for canonical, synonyms in self.semantic_api.terminology_fields.items():
                for s in [canonical] + list(synonyms):
                    mapping[s] = canonical

        return FieldMapper(mapping)

    # get list of allowed columns across ALL semantic tables
    def _init_allowed_fields(self) -> set[str]:
        if not self.semantic_api or not hasattr(self.semantic_api, "tables"):
            return set()

        allowed: set[str] = set()
        for table in self.semantic_api.tables.values():
            for c in table.columns:
                if c.name:
                    allowed.add(c.name)

        return allowed

    # list possible synonym mappings for values
    def _init_value_synonyms(self) -> Dict[str, List[str]]:
        if self.semantic_api and hasattr(self.semantic_api, "terminology_values"):
            return self.semantic_api.terminology_values
        return {}

    # load metric definitions from semantic layer
    def _init_metrics(self) -> Dict[str, dict]:
        if self.semantic_api and hasattr(self.semantic_api, "metrics"):
            return self.semantic_api.metrics
        return {}

    # converts semantic layer metadata into text description to be given to LLM
    def _build_schema_context(self) -> str:
        if not self.semantic_api or not hasattr(self.semantic_api, "tables"):
            return "No schema context provided."

        lines: list[str] = []
        for table_name, table in self.semantic_api.tables.items():
            table_desc = f" - {table.description}" if getattr(table, "description", "") else ""
            lines.append(f"Table: {table_name}{table_desc}")

            for col in table.columns:
                desc = f" - {col.description}" if getattr(col, "description", "") else ""
                lines.append(f"  * {col.name} ({col.type}){desc}")

        if hasattr(self.semantic_api, "joins") and self.semantic_api.joins:
            lines.append("Joins:")
            for j in self.semantic_api.joins:
                join_type = j.get("join_type", "LEFT")
                lines.append(
                    f"  * {j['left_table']}.{j['left_key']} "
                    f"{join_type} JOIN "
                    f"{j['right_table']}.{j['right_key']}"
                )

        return "\n".join(lines)

    def _merge_active_filters(self, plan: QueryPlan, active_filters: Dict[str, Any] | None) -> QueryPlan:
        if not active_filters:
            return plan

        from .models import Filter

        for k, v in active_filters.items():
            if not any(f.field == k for f in plan.filters):
                plan.filters.append(Filter(field=k, op="=", value=v))

        return plan

    # the full pipeline
    def translate(
        self,
        user_query: str,
        active_filters: Dict[str, Any] | None = None,
    ) -> TranslationResult:
        schema_context_str = self._build_schema_context()
        constraints_str = (
            "Strictly use only the allowed fields. "
            "Limits should never exceed 1000. "
            "Do not output SQL."
        )

        # 1. Extract plan
        plan = self.extractor.extract(
            question=user_query,
            schema_context=schema_context_str,
            constraints=constraints_str,
        )

        if getattr(plan, "needs_clarification", False):
            return TranslationResult(
                sql="",
                plan=plan,
                physical_plan=None,
                valid=False,
                warnings=[plan.clarification_question or "Clarification required."],
            )

        # 2. Merge active filters
        plan = self._merge_active_filters(plan, active_filters)

        # 3. Semantic normalization
        plan = normalize_plan_fields(plan, self.mapper, None)
        plan = normalize_filter_values(plan, self.value_synonyms)

        # 4. Structured-plan validation
        plan_warnings = validate_query_plan(
            plan,
            allowed_fields=self.allowed_fields if self.allowed_fields else None,
            allowed_metrics=set(self.metrics.keys()) if self.metrics else None,
            max_limit=1000,
            require_aggregation_metric=False,
        )

        if plan_warnings:
            return TranslationResult(
                sql="",
                plan=plan,
                physical_plan=None,
                valid=False,
                warnings=plan_warnings,
            )

        # 5. Unsupported intent guard
        if str(plan.intent) == "Intent.unsupported" or getattr(plan.intent, "value", "") == "unsupported":
            return TranslationResult(
                sql="",
                plan=plan,
                physical_plan=None,
                valid=False,
                warnings=["Unsupported query intent."],
            )

        # 6. Build physical plan
        try:
            physical_plan = self.planner.build(plan, metrics=self.metrics)
        except Exception as e:
            return TranslationResult(
                sql="",
                plan=plan,
                physical_plan=None,
                valid=False,
                warnings=[f"Physical planning failed: {e}"],
            )

        # 7. Build SQL
        try:
            sql = build_sql(physical_plan)
        except Exception as e:
            return TranslationResult(
                sql="",
                plan=plan,
                physical_plan=physical_plan,
                valid=False,
                warnings=[f"SQL generation failed: {e}"],
            )

        # No raw-SQL checking here anymore.
        # Final SQL policy is enforced only in app/db/sql_guard.py before execution.
        return TranslationResult(
            sql=sql,
            plan=plan,
            physical_plan=physical_plan,
            valid=True,
            warnings=[],
        )
