from __future__ import annotations

import difflib
from typing import Any, Dict, List

from .agent1_extractor import Agent1QueryPlanExtractor
from .agent2_planner import PhysicalPlanner
from .agent2_resolver import Agent2QueryPlanResolver
from .agent2_sql_generator import build_sql
from .field_mapper import FieldMapper
from .llm_adapter import LLMAdapter
from .models import PhysicalPlan, QueryPlan
from .plan_utils import normalize_filter_values, normalize_plan_fields
from .validate_plan import validate_query_plan


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

        self.mapper = self._init_mapper()
        self.allowed_fields = self._init_allowed_fields()
        self.value_synonyms = self._init_value_synonyms()
        self.metrics = self._init_metrics()
        self.alias_map = self._build_alias_map()

        self.planner = PhysicalPlanner(semantic_api=self.semantic_api)

    def _init_mapper(self) -> FieldMapper:
        mapping: Dict[str, str] = {}
        if self.semantic_api and hasattr(self.semantic_api, "terminology_fields"):
            for canonical, synonyms in self.semantic_api.terminology_fields.items():
                for s in [canonical] + list(synonyms):
                    mapping[s] = canonical
        return FieldMapper(mapping)

    def _build_alias_map(self) -> Dict[str, str]:
        alias_map: Dict[str, str] = {}
        if not self.semantic_api or not hasattr(self.semantic_api, "terminology_fields"):
            return alias_map

        for canonical, synonyms in self.semantic_api.terminology_fields.items():
            alias_map[str(canonical).lower().strip()] = canonical
            for s in synonyms:
                alias_map[str(s).lower().strip()] = canonical
        return alias_map

    def _init_allowed_fields(self) -> set[str]:
        if not self.semantic_api or not hasattr(self.semantic_api, "tables"):
            return set()

        allowed: set[str] = set()
        for table in self.semantic_api.tables.values():
            for c in table.columns:
                if c.name:
                    allowed.add(c.name)

        # computed fields supported by semantic resolver
        allowed.update({"age", "diagnosis_year"})
        return allowed

    def _init_value_synonyms(self) -> Dict[str, List[str]]:
        if self.semantic_api and hasattr(self.semantic_api, "terminology_values"):
            return self.semantic_api.terminology_values
        return {}

    def _init_metrics(self) -> Dict[str, dict]:
        if self.semantic_api and hasattr(self.semantic_api, "metrics"):
            return self.semantic_api.metrics
        return {}

    def _resolve_field_alias(self, raw: str) -> str:
        if not raw:
            return raw

        token = raw.strip()
        key = token.lower()
        if key in self.alias_map:
            return self.alias_map[key]

        if "." in token:
            tail = token.split(".")[-1].strip().lower()
            if tail in self.alias_map:
                return self.alias_map[tail]

        return token

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

    def _normalize_sort_fields(self, plan: QueryPlan) -> QueryPlan:
        for s in plan.sort:
            if "." in s.field:
                s.field = s.field.split(".")[-1]
        return plan

    def _canonicalize_fields(self, plan: QueryPlan) -> QueryPlan:
        plan.dimensions = [self._resolve_field_alias(d) for d in plan.dimensions]
        for f in plan.filters:
            f.field = self._resolve_field_alias(f.field)
        for s in plan.sort:
            s.field = self._resolve_field_alias(s.field)
        return plan

    def _fuzzy_map_field(self, field: str) -> str | None:
        if not self.allowed_fields:
            return field
        if field in self.allowed_fields:
            return field
        cands = difflib.get_close_matches(field, list(self.allowed_fields), n=1, cutoff=0.72)
        return cands[0] if cands else None

    def _best_effort_normalize(self, plan: QueryPlan) -> tuple[QueryPlan, list[str]]:
        warnings: list[str] = []

        # 1) count intent should return a single aggregate row
        if str(getattr(plan.intent, "value", plan.intent)) == "count":
            if plan.dimensions:
                warnings.append("count intent detected: dropped dimensions for total count.")
            plan.dimensions = []
            plan.sort = []

        # 2) map business-level age_group to SQL expression filter
        mapped_filters = []
        for flt in plan.filters:
            field_l = str(flt.field).lower().strip()
            if field_l == "age_group":
                val = str(flt.value).lower().strip()
                if "under" in val and "50" in val:
                    flt.field = "__expr__"
                    flt.op = "raw"
                    flt.value = "date_diff('year', person.birth_datetime, condition_occurrence.condition_start_date) < 50"
                    warnings.append("Mapped age_group=under_50 to derived age expression.")
                    mapped_filters.append(flt)
                    continue
                if "50" in val and ("above" in val or "over" in val or "+" in val):
                    flt.field = "__expr__"
                    flt.op = "raw"
                    flt.value = "date_diff('year', person.birth_datetime, condition_occurrence.condition_start_date) >= 50"
                    warnings.append("Mapped age_group=50+ to derived age expression.")
                    mapped_filters.append(flt)
                    continue
                warnings.append(f"Dropped unsupported age_group value: {flt.value}")
                continue
            mapped_filters.append(flt)
        plan.filters = mapped_filters

        # 3) dimensions: map alias/fuzzy or drop
        fixed_dims: list[str] = []
        for d in plan.dimensions:
            alias = self._resolve_field_alias(d)
            mapped = self._fuzzy_map_field(alias)
            if mapped:
                if mapped != d:
                    warnings.append(f"Mapped dimension '{d}' -> '{mapped}'.")
                fixed_dims.append(mapped)
            else:
                warnings.append(f"Dropped unknown dimension field: {d}")
        plan.dimensions = fixed_dims

        # 4) filters: map alias/fuzzy or drop (except raw expr)
        fixed_filters = []
        for f in plan.filters:
            if f.field == "__expr__":
                fixed_filters.append(f)
                continue
            alias = self._resolve_field_alias(f.field)
            mapped = self._fuzzy_map_field(alias)
            if mapped:
                if mapped != f.field:
                    warnings.append(f"Mapped filter field '{f.field}' -> '{mapped}'.")
                f.field = mapped
                fixed_filters.append(f)
            else:
                warnings.append(f"Dropped unknown filter field: {f.field}")
        plan.filters = fixed_filters

        # 5) sort: keep only valid targets
        valid_sort_targets = set(plan.dimensions)
        valid_sort_targets.add(plan.metric)
        fixed_sort = []
        for s in plan.sort:
            sf = self._resolve_field_alias(s.field)
            if sf in valid_sort_targets:
                s.field = sf
                fixed_sort.append(s)
            else:
                warnings.append(f"Dropped unsupported sort field: {s.field}")
        plan.sort = fixed_sort

        if plan.limit is None or plan.limit <= 0:
            plan.limit = 50
        elif plan.limit > 1000:
            plan.limit = 1000

        return plan, warnings

    def translate(
        self,
        user_query: str,
        active_filters: Dict[str, Any] | None = None,
    ) -> TranslationResult:
        warnings: List[str] = []
        plan_agent1: QueryPlan | None = None
        plan_agent2: QueryPlan | None = None

        schema_context_str = self._build_schema_context()
        agent1_constraints_str = "Use business semantics only. Do not map to physical schema names."

        # 1) Agent1: NL -> logical plan
        plan = self.extractor.extract(
            question=user_query,
            schema_context="",
            constraints=agent1_constraints_str,
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

        # 2) merge UI filters
        plan = self._merge_active_filters(plan, active_filters)

        # 3) Agent2: schema-aware resolve
        if self.resolver is not None and self.allowed_fields:
            try:
                plan = self.resolver.resolve(
                    plan=plan,
                    schema_context=schema_context_str,
                    constraints=(
                        "Map dimensions/filters to canonical schema fields only. "
                        "If intent is count, set dimensions=[] and sort=[]. "
                        "Do not output SQL."
                    ),
                )
            except Exception as e:
                warnings.append(f"Agent2 resolver fallback to rules: {e}")

        # 4) deterministic normalization
        plan = normalize_plan_fields(plan, self.mapper, None)
        plan = normalize_filter_values(plan, self.value_synonyms)
        plan = self._normalize_sort_fields(plan)
        plan = self._canonicalize_fields(plan)
        plan_agent2 = plan.model_copy(deep=True)

        plan, normalize_warnings = self._best_effort_normalize(plan)
        warnings.extend(normalize_warnings)

        # 5) validate (warn-only in best-effort mode)
        plan_warnings = validate_query_plan(
            plan,
            allowed_fields=self.allowed_fields if self.allowed_fields else None,
            allowed_metrics=set(self.metrics.keys()) if self.metrics else None,
            max_limit=1000,
            require_aggregation_metric=False,
        )
        warnings.extend(plan_warnings)

        # 6) unsupported intent
        if str(getattr(plan.intent, "value", plan.intent)) == "unsupported":
            return TranslationResult(
                sql="",
                plan=plan,
                physical_plan=None,
                valid=False,
                warnings=warnings + ["Unsupported query intent."],
                plan_agent1=plan_agent1,
                plan_agent2=plan_agent2,
            )

        # 7) physical plan
        try:
            physical_plan = self.planner.build(plan, metrics=self.metrics)
        except Exception as e:
            return TranslationResult(
                sql="",
                plan=plan,
                physical_plan=None,
                valid=False,
                warnings=warnings + [f"Physical planning failed: {e}"],
                plan_agent1=plan_agent1,
                plan_agent2=plan_agent2,
            )

        # 8) SQL generation
        try:
            sql = build_sql(physical_plan)
        except Exception as e:
            return TranslationResult(
                sql="",
                plan=plan,
                physical_plan=physical_plan,
                valid=False,
                warnings=warnings + [f"SQL generation failed: {e}"],
                plan_agent1=plan_agent1,
                plan_agent2=plan_agent2,
            )

        return TranslationResult(
            sql=sql,
            plan=plan,
            physical_plan=physical_plan,
            valid=True,
            warnings=warnings,
            plan_agent1=plan_agent1,
            plan_agent2=plan_agent2,
        )
