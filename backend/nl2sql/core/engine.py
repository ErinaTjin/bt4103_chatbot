#engine.py
#main NL2SQL engine that orchestrates the full pipeline from natural language to SQL, 
# including semantic mapping, logical->physical planning, and guardrails.
from __future__ import annotations

from typing import Dict, Any, List

from .models import QueryPlan, PhysicalPlan
from .llm_adapter import LLMAdapter
from .extractor import QueryExtractor
from .plan_utils import (
    normalize_plan_fields,
    normalize_filter_values,
    validate_plan_fields,
)
from .field_mapper import FieldMapper
from .physical_planner import PhysicalPlanner
from .sql_builder import build_sql
from .guardrails import check_sql


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
        """
        Initializes the NL->SQL Engine.

        Args:
            llm: The LLM adapter used for QueryPlan extraction.
            semantic_api: Loaded semantic layer object containing:
                - tables
                - terminology_fields
                - terminology_values
                - metrics
                - joins
        """
        self.llm = llm or LLMAdapter()
        self.extractor = QueryExtractor(self.llm)
        self.semantic_api = semantic_api

        # Semantic / metadata setup
        self.mapper = self._init_mapper()
        self.allowed_fields = self._init_allowed_fields()
        self.value_synonyms = self._init_value_synonyms()
        self.metrics = self._init_metrics()

        # New: logical -> physical planning layer
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
        """
        Serializes the loaded semantic layer tables into a readable string for the LLM.
        """
        if not self.semantic_api or not hasattr(self.semantic_api, "tables"):
            return "No schema context provided."

        lines: list[str] = []
        for table_name, table in self.semantic_api.tables.items():
            table_desc = f" - {table.description}" if getattr(table, "description", "") else ""
            lines.append(f"Table: {table_name}{table_desc}")

            for col in table.columns:
                desc = f" - {col.description}" if getattr(col, "description", "") else ""
                lines.append(f"  * {col.name} ({col.type}){desc}")

        # optionally expose joins to the LLM for better planning quality
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
            # Avoid duplicates
            if not any(f.field == k for f in plan.filters):
                plan.filters.append(Filter(field=k, op="=", value=v))

        return plan

    # the full pipeline
    def translate(
        self,
        user_query: str,
        active_filters: Dict[str, Any] | None = None,
    ) -> TranslationResult:
        """
        Translates a natural language query into safe, ready-to-execute SQL.
        Pipeline:
            1. LLM extracts QueryPlan
            2. Semantic normalization
            3. Validate fields
            4. Build PhysicalPlan
            5. Render SQL from PhysicalPlan
            6. Run guardrails
        """
        # Build schema context for LLM extraction
        schema_context_str = self._build_schema_context()
        constraints_str = (
            "Strictly use only the allowed fields. "
            "Limits should never exceed 1000. "
            "Do not output SQL."
        )

        # 1. Extract intent & structured slots (JSON)
        plan = self.extractor.extract(
            question=user_query,
            schema_context=schema_context_str,
            constraints=constraints_str,
        )

        # Early return for clarification flow
        if getattr(plan, "needs_clarification", False):
            return TranslationResult(
                sql="",
                plan=plan,
                physical_plan=None,
                valid=False,
                warnings=[plan.clarification_question or "Clarification required."],
            )

        # Merge active filters if any
        plan = self._merge_active_filters(plan, active_filters)

        # 2. Semantic Mapping (user terms -> canonical field names)
        plan = normalize_plan_fields(plan, self.mapper, None)
        plan = normalize_filter_values(plan, self.value_synonyms)

        # 3. Field validation
        field_warnings = validate_plan_fields(
            plan,
            self.allowed_fields if self.allowed_fields else None,
        )

        # If extracted fields are unknown, do not continue into planner
        if field_warnings:
            return TranslationResult(
                sql="",
                plan=plan,
                physical_plan=None,
                valid=False,
                warnings=field_warnings,
            )

        # Unsupported intent guard
        if str(plan.intent) == "Intent.unsupported" or getattr(plan.intent, "value", "") == "unsupported":
            return TranslationResult(
                sql="",
                plan=plan,
                physical_plan=None,
                valid=False,
                warnings=["Unsupported query intent."],
            )

        # 4. Logical -> Physical planning
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

        # 5. Deterministic SQL generation from PhysicalPlan
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

        # 6. Pre-execution guardrails
        guard = check_sql(sql)
        warnings = list(guard["warnings"])

        return TranslationResult(
            sql=sql,
            plan=plan,
            physical_plan=physical_plan,
            valid=guard["ok"],
            warnings=warnings,
        )