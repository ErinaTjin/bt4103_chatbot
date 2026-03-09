from __future__ import annotations

from nl2sql.core.agent2_sql_generator import build_sql
from nl2sql.core.engine import NL2SQLEngine
from nl2sql.core.validate_plan import validate_query_plan

from .state import NL2SQLState


class GraphNodes:
    def __init__(self, engine: NL2SQLEngine):
        self.engine = engine

    def context_node(self, state: NL2SQLState) -> NL2SQLState:
        # v1 context behavior: preserve user question unchanged.
        # Future extension: resolve follow-ups with chat_history.
        state.setdefault("warnings", [])
        state.setdefault("retry_count", 0)
        state.setdefault("max_retries", 2)
        state.setdefault("error", None)
        state.setdefault("needs_clarification", False)
        state.setdefault("clarification_question", None)
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

    def normalize_node(self, state: NL2SQLState) -> NL2SQLState:
        if state.get("needs_clarification"):
            return state

        plan = state.get("plan")
        if plan is None:
            state["error"] = "missing_plan_before_normalize"
            return state

        from nl2sql.core.plan_utils import normalize_filter_values, normalize_plan_fields

        plan = self.engine._merge_active_filters(plan, state.get("active_filters"))
        plan = normalize_plan_fields(plan, self.engine.mapper, None)
        plan = normalize_filter_values(plan, self.engine.value_synonyms)
        plan = self.engine._canonicalize_fields(plan)
        plan = self.engine._normalize_sort_fields(plan)
        plan, normalize_warnings = self.engine._best_effort_normalize(plan)

        state["warnings"].extend(normalize_warnings)
        state["plan"] = plan
        state["plan_agent2"] = plan.model_copy(deep=True)
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

        if blocking and state.get("retry_count", 0) < state.get("max_retries", 2):
            state["retry_count"] = state.get("retry_count", 0) + 1
            state["error"] = "; ".join(blocking)
        elif blocking and not state.get("sql"):
            state["error"] = "; ".join(blocking)
        else:
            state["error"] = None

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
        )
        return state


def route_after_validate(state: NL2SQLState) -> str:
    if state.get("needs_clarification"):
        return "final"

    err = state.get("error")
    if err and state.get("retry_count", 0) < state.get("max_retries", 2):
        return "agent2"
    return "final"
