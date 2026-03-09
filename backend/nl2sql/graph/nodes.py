from __future__ import annotations

import json
from pathlib import Path

from nl2sql.core.agent2_sql_generator import build_sql
from nl2sql.core.engine import NL2SQLEngine
from nl2sql.core.models import Filter
from nl2sql.core.validate_plan import validate_query_plan

from .state import NL2SQLState


def _default_mapping() -> dict:
    return {
        "field_aliases": {
            "cancer_type": "ICD10",
            "histology": "ICDO3",
            "stage": "value_as_concept_name",
            "diagnosis_year": "condition_start_date",
        },
        "derived_filters": {
            "age_group": {
                "under_50": {
                    "field": "__expr__",
                    "op": "raw",
                    "value": "date_diff('year', person.birth_datetime, condition_occurrence.condition_start_date) < 50",
                },
                "50_and_above": {
                    "field": "__expr__",
                    "op": "raw",
                    "value": "date_diff('year', person.birth_datetime, condition_occurrence.condition_start_date) >= 50",
                },
            }
        },
        "eav_rules": {
            "stage_measurement_concepts": [
                "TNM Clin Stage Group",
                "TNM Path Stage Group",
            ]
        },
    }


class GraphNodes:
    def __init__(self, engine: NL2SQLEngine):
        self.engine = engine
        self.mapping = self._load_mapping()

    def _load_mapping(self) -> dict:
        default = _default_mapping()
        path = Path(__file__).resolve().parents[1] / "semantic" / "mapping.json"
        if not path.exists():
            return default
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                # shallow merge with defaults
                merged = default.copy()
                for k, v in data.items():
                    if isinstance(v, dict) and isinstance(merged.get(k), dict):
                        inner = merged[k].copy()
                        inner.update(v)
                        merged[k] = inner
                    else:
                        merged[k] = v
                return merged
        except Exception:
            return default
        return default

    def context_node(self, state: NL2SQLState) -> NL2SQLState:
        state.setdefault("warnings", [])
        state.setdefault("retry_count", 0)
        state.setdefault("max_retries", 2)
        state.setdefault("error", None)
        state.setdefault("needs_clarification", False)
        state.setdefault("clarification_question", None)
        state.setdefault("validation_level", "L1")
        state.setdefault("uncertainty_flag", False)
        state["effective_question"] = state.get("question", "")
        state["schema_context"] = self.engine._build_schema_context()
        return state

    def agent1_node(self, state: NL2SQLState) -> NL2SQLState:
        q = state.get("effective_question", state.get("question", ""))
        plan = self.engine.extractor.extract(
            question=q,
            schema_context="",
            constraints="Use business semantics only. Do not map to physical schema names.",
        )
        state["plan"] = plan
        state["plan_agent1"] = plan.model_copy(deep=True)

        if getattr(plan, "needs_clarification", False):
            state["needs_clarification"] = True
            state["clarification_question"] = plan.clarification_question
            state["error"] = "clarification_required"

        return state

    def agent2_node(self, state: NL2SQLState) -> NL2SQLState:
        if state.get("needs_clarification"):
            return state

        plan = state.get("plan")
        if plan is None:
            state["error"] = "missing_plan_before_agent2"
            return state

        if self.engine.resolver is None or not self.engine.allowed_fields:
            state["plan_agent2"] = plan.model_copy(deep=True)
            return state

        extra_constraints = state.get("constraints", "")
        if state.get("error") and state["error"] != "clarification_required":
            extra_constraints = (
                extra_constraints
                + "\nPrevious validation error: "
                + str(state["error"])
                + "\nFix invalid fields and return corrected QueryPlan JSON only."
            )

        try:
            resolved = self.engine.resolver.resolve(
                plan=plan,
                schema_context=state.get("schema_context", ""),
                constraints=(
                    "Map dimensions/filters to canonical schema fields only. "
                    "If intent is count, set dimensions=[] and sort=[]. "
                    "Do not output SQL.\n"
                    + extra_constraints
                ).strip(),
            )
            state["plan"] = resolved
            state["plan_agent2"] = resolved.model_copy(deep=True)
        except Exception as e:
            state["warnings"].append(f"Agent2 resolver fallback to rules: {e}")
            state["plan_agent2"] = plan.model_copy(deep=True)

        return state

    def _apply_field_aliases(self, plan):
        aliases = self.mapping.get("field_aliases", {})
        plan.dimensions = [aliases.get(d, d) for d in plan.dimensions]
        for f in plan.filters:
            f.field = aliases.get(f.field, f.field)
        return plan

    def _expand_diagnosis_year(self, plan, warnings: list[str]):
        expanded: list[Filter] = []
        for f in plan.filters:
            if f.field == "condition_start_date" and f.op == "=" and str(f.value).isdigit() and len(str(f.value)) == 4:
                year = int(str(f.value))
                expanded.append(Filter(field="condition_start_date", op=">=", value=f"{year}-01-01"))
                expanded.append(Filter(field="condition_start_date", op="<=", value=f"{year}-12-31"))
                warnings.append(f"Expanded diagnosis year {year} to date range.")
                continue
            expanded.append(f)
        plan.filters = expanded
        return plan

    def _apply_derived_filters(self, plan, warnings: list[str]):
        derived = self.mapping.get("derived_filters", {})
        age_map = derived.get("age_group", {})

        out_filters: list[Filter] = []
        for f in plan.filters:
            field_l = str(f.field).lower().strip()
            if field_l != "age_group":
                out_filters.append(f)
                continue

            token = str(f.value).lower().strip()
            if f.op == "<" and str(f.value).strip() == "50":
                token = "under_50"
            elif f.op in {">", ">="} and str(f.value).strip() == "50":
                token = "50_and_above"
            elif "under" in token and "50" in token:
                token = "under_50"
            elif "50" in token and ("above" in token or "over" in token or "+" in token):
                token = "50_and_above"

            mapping = age_map.get(token)
            if mapping:
                out_filters.append(
                    Filter(
                        field=mapping["field"],
                        op=mapping["op"],
                        value=mapping["value"],
                    )
                )
                warnings.append(f"Mapped age_group '{f.value}' -> derived age expression.")
            else:
                warnings.append(f"Dropped unsupported age_group value: {f.value}")

        plan.filters = out_filters
        return plan

    def _ensure_stage_eav_filters(self, plan, warnings: list[str]):
        stage_dims = {"stage", "value_as_concept_name"}
        has_stage_dim = any(d in stage_dims for d in plan.dimensions)
        has_stage_filter = any(f.field == "value_as_concept_name" for f in plan.filters)
        if not has_stage_dim and not has_stage_filter:
            return plan

        has_measurement = any(f.field == "measurement_concept_name" for f in plan.filters)
        if has_measurement:
            return plan

        concepts = self.mapping.get("eav_rules", {}).get("stage_measurement_concepts", [])
        if concepts:
            plan.filters.append(
                Filter(
                    field="measurement_concept_name",
                    op="in",
                    value=concepts,
                )
            )
            warnings.append("Added EAV anchor filter measurement_concept_name for stage query.")
        return plan

    def normalize_node(self, state: NL2SQLState) -> NL2SQLState:
        if state.get("needs_clarification"):
            return state

        plan = state.get("plan")
        if plan is None:
            state["error"] = "missing_plan_before_normalize"
            return state

        from nl2sql.core.plan_utils import normalize_filter_values, normalize_plan_fields

        plan = self.engine._merge_active_filters(plan, state.get("active_filters"))
        plan = self._apply_field_aliases(plan)
        plan = normalize_plan_fields(plan, self.engine.mapper, None)
        plan = normalize_filter_values(plan, self.engine.value_synonyms)
        plan = self._expand_diagnosis_year(plan, state["warnings"])
        plan = self._apply_derived_filters(plan, state["warnings"])
        plan = self._ensure_stage_eav_filters(plan, state["warnings"])

        plan = self.engine._canonicalize_fields(plan)
        plan = self.engine._normalize_sort_fields(plan)
        plan, normalize_warnings = self.engine._best_effort_normalize(plan)
        state["warnings"].extend(normalize_warnings)

        # If metric is unknown to template library, downgrade to count metric for safe execution.
        if self.engine.metrics and plan.metric not in self.engine.metrics:
            state["warnings"].append(
                f"Metric '{plan.metric}' not in metrics template library; fallback to count_patients."
            )
            plan.metric = "count_patients"
            state["uncertainty_flag"] = True

        state["plan"] = plan
        state["plan_agent2"] = plan.model_copy(deep=True)
        return state

    def validate_node(self, state: NL2SQLState) -> NL2SQLState:
        if state.get("needs_clarification"):
            return state

        plan = state.get("plan")
        if plan is None:
            state["error"] = "missing_plan_before_validate"
            return state

        warnings = validate_query_plan(
            plan,
            allowed_fields=self.engine.allowed_fields if self.engine.allowed_fields else None,
            allowed_metrics=set(self.engine.metrics.keys()) if self.engine.metrics else None,
            max_limit=1000,
            require_aggregation_metric=False,
        )
        state["warnings"].extend(warnings)

        blocking = [
            w
            for w in warnings
            if w.startswith("Unknown ")
            or w.startswith("Unsupported filter operator")
            or w.startswith("Unsupported sort direction")
        ]

        template_hit = (plan.metric == "count_patients") or (plan.metric in (self.engine.metrics or {}))

        if blocking:
            state["validation_level"] = "L3"
            state["uncertainty_flag"] = False
            if state.get("retry_count", 0) < state.get("max_retries", 2):
                state["retry_count"] = state.get("retry_count", 0) + 1
            state["error"] = "; ".join(blocking)
            return state

        if template_hit and not state.get("uncertainty_flag", False):
            state["validation_level"] = "L1"
            state["uncertainty_flag"] = False
        else:
            state["validation_level"] = "L2"
            state["uncertainty_flag"] = True
            state["warnings"].append("Heuristic path used; please verify semantic correctness.")

        state["error"] = None
        return state

    def plan_sql_node(self, state: NL2SQLState) -> NL2SQLState:
        if state.get("needs_clarification"):
            return state

        plan = state.get("plan")
        if plan is None:
            state["error"] = "missing_plan_before_planning"
            return state

        intent_val = str(getattr(plan.intent, "value", plan.intent))
        if intent_val == "unsupported":
            state["error"] = "unsupported_intent"
            return state

        try:
            physical_plan = self.engine.planner.build(plan, metrics=self.engine.metrics)
            state["physical_plan"] = physical_plan
            state["sql"] = build_sql(physical_plan)
        except Exception as e:
            state["error"] = f"plan_sql_failed: {e}"

        return state

    def final_node(self, state: NL2SQLState) -> NL2SQLState:
        from nl2sql.core.engine import TranslationResult

        plan = state.get("plan")
        if plan is None:
            raise RuntimeError("Graph final_node reached without plan")

        clarification = state.get("needs_clarification", False)
        valid = bool(state.get("sql")) and not clarification and not state.get("error")

        if clarification:
            question = state.get("clarification_question") or "Clarification required."
            state["warnings"].append(question)

        state["valid"] = valid
        state["result"] = TranslationResult(
            sql=state.get("sql", ""),
            plan=plan,
            physical_plan=state.get("physical_plan"),
            valid=valid,
            warnings=state.get("warnings", []),
            plan_agent1=state.get("plan_agent1"),
            plan_agent2=state.get("plan_agent2"),
            metadata={
                "validation_level": state.get("validation_level", "L1"),
                "uncertainty_flag": state.get("uncertainty_flag", False),
                "pipeline": "langgraph",
                "retry_count": state.get("retry_count", 0),
            },
        )
        return state


def route_after_validate(state: NL2SQLState) -> str:
    if state.get("needs_clarification"):
        return "final"

    err = state.get("error")
    if err and state.get("retry_count", 0) < state.get("max_retries", 2):
        return "agent2"
    if err:
        return "final"
    return "plan_sql"
