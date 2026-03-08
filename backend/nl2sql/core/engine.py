#engine.py
#main NL2SQL engine that orchestrates the full pipeline from natural language to SQL, 
# including semantic mapping, logical->physical planning, and guardrails.
from __future__ import annotations

from typing import Dict, Any, List

from backend.nl2sql.core.models import QueryPlan, PhysicalPlan
from backend.nl2sql.core.llm_adapter import LLMAdapter
from backend.nl2sql.core.agent1_extractor import Agent1QueryPlanExtractor
from backend.nl2sql.core.agent2_resolver import Agent2QueryPlanResolver
from backend.nl2sql.core.plan_utils import (
    normalize_plan_fields,
    normalize_filter_values,
)
from backend.nl2sql.core.validate_plan import validate_query_plan
from .field_mapper import FieldMapper
from .agent2_planner import PhysicalPlanner
from .agent2_sql_generator import build_sql


# container for the final result
class TranslationResult:
    def __init__(
        self,
        sql: str,
        plan: QueryPlan,
        physical_plan: PhysicalPlan | None,
        valid: bool,
        warnings: List[str],
        plan_agent1: QueryPlan | None = None,
        plan_agent2: QueryPlan | None = None,
    ):
        self.sql = sql
        self.plan = plan
        self.physical_plan = physical_plan
        self.valid = valid
        self.warnings = warnings
        self.plan_agent1 = plan_agent1
        self.plan_agent2 = plan_agent2


class NL2SQLEngine:
    def __init__(
        self,
        llm: LLMAdapter | None = None,
        semantic_api: Any = None,
        enable_agent2_resolver: bool = True,
    ):
        self.llm = llm or LLMAdapter()
        self.extractor = Agent1QueryPlanExtractor(self.llm)
        self.enable_agent2_resolver = enable_agent2_resolver
        self.resolver = Agent2QueryPlanResolver(self.llm) if enable_agent2_resolver else None
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
        resolver_warnings: List[str] = []
        plan_agent1: QueryPlan | None = None
        plan_agent2: QueryPlan | None = None
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
        plan_agent1 = plan.model_copy(deep=True)

        if getattr(plan, "needs_clarification", False):
            return TranslationResult(
                sql="",
                plan=plan,
                physical_plan=None,
                valid=False,
                warnings=[plan.clarification_question or "Clarification required."],
                plan_agent1=plan_agent1,
                plan_agent2=plan_agent2,
            )

        # 2. Merge active filters
        plan = self._merge_active_filters(plan, active_filters)

        # 3. Agent 2 schema-aware resolve (best-effort)
        if self.resolver is not None and self.allowed_fields:
            try:
                plan = self.resolver.resolve(
                    plan=plan,
                    schema_context=schema_context_str,
                    constraints=(
                        "Map dimensions/filters to canonical schema fields. "
                        "Preserve intent and metric unless invalid. "
                        "Do not output SQL."
                    ),
                )
            except Exception as e:
                resolver_warnings.append(f"Agent2 resolver fallback to rules: {e}")

        # 4. Semantic normalization
        plan = normalize_plan_fields(plan, self.mapper, None)
        plan = normalize_filter_values(plan, self.value_synonyms)
        plan_agent2 = plan.model_copy(deep=True)

        # 5. Structured-plan validation
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
                warnings=resolver_warnings + plan_warnings,
                plan_agent1=plan_agent1,
                plan_agent2=plan_agent2,
            )

        # 6. Unsupported intent guard
        if str(plan.intent) == "Intent.unsupported" or getattr(plan.intent, "value", "") == "unsupported":
            return TranslationResult(
                sql="",
                plan=plan,
                physical_plan=None,
                valid=False,
                warnings=resolver_warnings + ["Unsupported query intent."],
                plan_agent1=plan_agent1,
                plan_agent2=plan_agent2,
            )

        # 7. Build physical plan
        try:
            physical_plan = self.planner.build(plan, metrics=self.metrics)
        except Exception as e:
            return TranslationResult(
                sql="",
                plan=plan,
                physical_plan=None,
                valid=False,
                warnings=resolver_warnings + [f"Physical planning failed: {e}"],
                plan_agent1=plan_agent1,
                plan_agent2=plan_agent2,
            )

        # 8. Build SQL
        try:
            sql = build_sql(physical_plan)
        except Exception as e:
            return TranslationResult(
                sql="",
                plan=plan,
                physical_plan=physical_plan,
                valid=False,
                warnings=resolver_warnings + [f"SQL generation failed: {e}"],
                plan_agent1=plan_agent1,
                plan_agent2=plan_agent2,
            )

        # No raw-SQL checking here anymore.
        # Final SQL policy is enforced only in app/db/sql_guard.py before execution.
        return TranslationResult(
            sql=sql,
            plan=plan,
            physical_plan=physical_plan,
            valid=True,
            warnings=resolver_warnings,
            plan_agent1=plan_agent1,
            plan_agent2=plan_agent2,
        )
