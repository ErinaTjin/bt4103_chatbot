from typing import Dict, Any, List

from .models import QueryPlan, PhysicalPlan
from .llm_adapter import LLMAdapter
from .extractor import QueryExtractor
from .plan_utils import normalize_plan_fields, normalize_filter_values, validate_plan_fields
from .field_mapper import FieldMapper
from .sql_builder import build_sql
from .guardrails import check_sql


class TranslationResult:
    def __init__(self, sql: str, plan: QueryPlan, valid: bool, warnings: List[str]):
        self.sql = sql
        self.plan = plan
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
        :param llm: The LLM Adapter. If None, uses default.
        :param semantic_api: API reference to the Semantic Layer. 
                             (e.g., provides terminology mappings, join graphs).
                             Currently simulates mapping with a basic FieldMapper.
        """
        self.llm = llm or LLMAdapter()
        self.extractor = QueryExtractor(self.llm)
        self.semantic_api = semantic_api

        # Setup Semantic Layer context
        self.mapper = self._init_mapper()
        self.allowed_fields = self._init_allowed_fields()
        self.value_synonyms = self._init_value_synonyms()
        self.metrics = self._init_metrics()

    def _init_mapper(self) -> FieldMapper:
        mapping = {}
        if self.semantic_api and hasattr(self.semantic_api, "terminology_fields"):
            for canonical, synonyms in self.semantic_api.terminology_fields.items():
                for s in [canonical] + list(synonyms):
                    mapping[s] = canonical
        return FieldMapper(mapping)

    def _init_allowed_fields(self) -> set:
        if self.semantic_api and hasattr(self.semantic_api, "tables") and "anchor_view" in self.semantic_api.tables:
            return {c.name for c in self.semantic_api.tables["anchor_view"].columns}
        return set()

    def _init_value_synonyms(self) -> Dict[str, List[str]]:
        if self.semantic_api and hasattr(self.semantic_api, "terminology_values"):
            return self.semantic_api.terminology_values
        return {}

    def _init_metrics(self) -> Dict[str, dict]:
        if self.semantic_api and hasattr(self.semantic_api, "metrics"):
            return self.semantic_api.metrics
        return {}

    def _build_schema_context(self) -> str:
        """Serializes the loaded semantic layer tables into a readable string for the LLM."""
        if not self.semantic_api or not hasattr(self.semantic_api, "tables"):
            return "No schema context provided."
        
        lines = []
        for table_name, table in self.semantic_api.tables.items():
            lines.append(f"Table: {table_name}")
            for col in table.columns:
                desc = f" - {col.description}" if col.description else ""
                lines.append(f"  * {col.name} ({col.type}){desc}")
        
        return "\n".join(lines)


    def translate(self, user_query: str, active_filters: Dict[str, Any] = None) -> TranslationResult:
        """
        Translates a natural language query into safe, ready-to-execute SQL.
        """
        # Build schema context for LLM extraction
        schema_context_str = self._build_schema_context()
        constraints_str = "Strictly use only the allowed fields. Limits should never exceed 1000."

        # 1. Extract intent & structured slots (JSON)
        plan = self.extractor.extract(
            question=user_query, 
            schema_context=schema_context_str, 
            constraints=constraints_str
        )

        # Merge active filters if any
        if active_filters:
            from .models import Filter
            for k, v in active_filters.items():
                # Avoid duplicates
                if not any(f.field == k for f in plan.filters):
                    plan.filters.append(Filter(field=k, op="=", value=v))


        # 2. Semantic Mapping (JSON to Physical Fields)
        # Note: In a full join-graph system, this is where we'd resolve table paths.
        plan = normalize_plan_fields(plan, self.mapper, None)
        plan = normalize_filter_values(plan, self.value_synonyms)

        field_warnings = validate_plan_fields(plan, self.allowed_fields if self.allowed_fields else None)

        # 3. Deterministic SQL Generation
        sql = build_sql(plan, metrics=self.metrics)

        # 4. Pre-Execution Guardrails
        guard = check_sql(sql)
        warnings = guard["warnings"]

        if field_warnings:
            warnings.extend(field_warnings)
            guard["ok"] = False

        return TranslationResult(
            sql=sql,
            plan=plan,
            valid=guard["ok"],
            warnings=warnings
        )
