from __future__ import annotations

from typing import Any, Dict, List, TypedDict

from nl2sql.core.engine import NL2SQLEngine, TranslationResult
from nl2sql.core.context_agent import ContextAgent

try:
    from langgraph.graph import END, StateGraph
except ImportError:  # pragma: no cover - optional dependency
    END = None
    StateGraph = None


class GraphState(TypedDict, total=False):
    user_query: str
    resolved_question: str
    context_resolution: Dict[str, Any]
    conversation_history: List[Dict[str, Any] | str]
    active_filters: Dict[str, Any]
    warnings: List[str]
    blocking_issues: List[str]
    rewriter_feedback: str
    retry_count: int
    agent1_retry_count: int
    plan_validation_errors: List[str]

    agent1: Dict[str, Any]
    plan_agent1: Dict[str, Any]
    writer_output: Dict[str, Any]
    plan_agent2: Dict[str, Any]
    sql: str
    valid: bool
    plan: Dict[str, Any]
    result: TranslationResult


class NL2SQLLangGraph:
    """
    Graph orchestrator that wraps the existing Agent1/Agent2 components.

    Flow:
      context_agent -> agent1_context -> validate_query_plan
      -> (fail + retry once -> agent1_context | fail after retry -> finalize)
      -> agent2_sql_writer -> validate_sql
      -> (pass -> finalize | fail and retry once -> agent2_sql_writer)
    """

    def __init__(self, engine: NL2SQLEngine) -> None:
        self.engine = engine
        self.context_agent = ContextAgent(engine.llm)
        self._app = self._build_graph()

    def _build_graph(self):
        if StateGraph is None or END is None:
            raise RuntimeError(
                "LangGraph is not installed. Install it with: pip install langgraph"
            )

        graph = StateGraph(GraphState)
        graph.add_node("context_agent", self._node_context_agent)
        graph.add_node("agent1_context", self._node_agent1_context)
        graph.add_node("validate_query_plan", self._node_validate_query_plan)
        graph.add_node("agent2_sql_writer", self._node_agent2_sql_writer)
        graph.add_node("validate_sql", self._node_validate_sql)
        graph.add_node("finalize", self._node_finalize)

        graph.set_entry_point("context_agent")

        graph.add_conditional_edges(
            "context_agent",
            self._route_after_context,
            {"to_agent1": "agent1_context", "to_finalize": "finalize"},
        )
        graph.add_conditional_edges(
            "agent1_context",
            self._route_after_agent1,
            {"to_validate_plan": "validate_query_plan", "to_finalize": "finalize"},
        )
        graph.add_conditional_edges(
            "validate_query_plan",
            self._route_after_plan_validation,
            {
                "to_writer": "agent2_sql_writer",
                "to_retry_agent1": "agent1_context",
                "to_finalize": "finalize",
            },
        )
        graph.add_edge("agent2_sql_writer", "validate_sql")
        graph.add_conditional_edges(
            "validate_sql",
            self._route_after_validate,
            {"to_finalize": "finalize", "to_retry_writer": "agent2_sql_writer"},
        )
        graph.add_edge("finalize", END)

        return graph.compile()

    def invoke(
        self,
        user_query: str,
        conversation_history: List[Dict[str, Any] | str] | None = None,
        active_filters: Dict[str, Any] | None = None,
    ) -> TranslationResult:
        initial_state: GraphState = {
            "user_query": user_query,
            "conversation_history": conversation_history or [],
            "active_filters": active_filters or {},
            "warnings": [],
            "blocking_issues": [],
            "retry_count": 0,
            "agent1_retry_count": 0,
            "plan_validation_errors": [],
        }
        final_state = self._app.invoke(initial_state)
        return final_state["result"]

    def _node_context_agent(self, state: GraphState) -> GraphState:
        ctx = self.context_agent.resolve(
            question=state["user_query"],
            conversation_history=state.get("conversation_history"),
            active_filters=state.get("active_filters"),
        )
        return {
            "context_resolution": ctx.model_dump(),
            "resolved_question": ctx.standalone_question.strip(),
        }

    def _route_after_context(self, state: GraphState) -> str:
        if state.get("context_resolution", {}).get("needs_clarification", False):
            return "to_finalize"
        return "to_agent1"

    def _node_agent1_context(self, state: GraphState) -> GraphState:
        resolved_question = state.get("resolved_question") or state["user_query"]
        agent1 = self.engine.extractor.extract(
            question=resolved_question,
            conversation_history=state.get("conversation_history"),
            active_filters=state.get("active_filters"),
        )
        return {
            "agent1": agent1.model_dump(),
            "plan_agent1": agent1.model_dump(),
        }

    def _route_after_agent1(self, state: GraphState) -> str:
        if state["agent1"].get("needs_clarification", False):
            return "to_finalize"
        return "to_validate_plan"

    def _node_validate_query_plan(self, state: GraphState) -> GraphState:
        from nl2sql.core.models import Agent1ContextSummary
        agent1_data = state["agent1"]
        agent1 = Agent1ContextSummary.model_validate(agent1_data)
        errors = self.engine._validate_query_plan(agent1)
        return {
            "plan_validation_errors": errors,
        }

    def _route_after_plan_validation(self, state: GraphState) -> str:
        errors = state.get("plan_validation_errors", [])
        if not errors:
            return "to_writer"
        # retry Agent 1 once
        if state.get("agent1_retry_count", 0) < 1:
            state["agent1_retry_count"] = state.get("agent1_retry_count", 0) + 1
            # inject error feedback into the question for the retry
            feedback = "; ".join(errors)
            state["resolved_question"] = (
                (state.get("resolved_question") or state["user_query"])
                + f"\n\nPrevious attempt had validation issues: {feedback}. "
                "Please ensure intent_summary is specific and all filters have valid field, op, and value."
            )
            return "to_retry_agent1"
        # still failing after retry — go to finalize with structured error
        return "to_finalize"

    def _node_agent2_sql_writer(self, state: GraphState) -> GraphState:
        resolved_question = state.get("resolved_question") or state["user_query"]
        agent1 = state["agent1"]
        schema_context = self.engine._build_schema_context(
            relevant_only=True,
            hint=f"{resolved_question} {agent1.get('intent_summary', '')}",
        )

        extra_instruction = state.get("rewriter_feedback", "").strip()
        business_rules = self.engine._build_business_rules()
        if extra_instruction:
            business_rules = f"{business_rules}\n- Retry feedback:\n{extra_instruction}"

        writer_output = self.engine.resolver.resolve(
            user_question=resolved_question,
            intent_summary=agent1.get("intent_summary", ""),
            schema_context=schema_context,
            terminology_mappings=self.engine._build_terminology_mappings(),
            business_rules=business_rules,
            sql_snippets=self.engine._build_sql_snippets(),
            safety_instructions=self.engine._build_safety_instructions(),
            conversation_history=state.get("conversation_history"),
            active_filters=state.get("active_filters"),
        )

        return {
            "writer_output": writer_output.model_dump(),
            "plan_agent2": writer_output.model_dump(),
            "sql": writer_output.sql.strip(),
        }

    def _node_validate_sql(self, state: GraphState) -> GraphState:
        warnings = list(state.get("warnings", []))
        blocking_issues: List[str] = []
        sql = state.get("sql", "")

        shape_error = self.engine._validate_sql_shape(sql)
        if shape_error:
            blocking_issues.append(shape_error)

        extracted_filters = state["agent1"].get("extracted_filters", [])
        semantic_blocking, semantic_advisory = self.engine._validate_sql_semantics(
            sql=sql,
            user_query=state.get("resolved_question") or state["user_query"],
            extracted_filters=extracted_filters,
            active_filters=state.get("active_filters"),
        )
        blocking_issues.extend(semantic_blocking)
        warnings.extend(semantic_advisory)

        writer_output = state.get("writer_output", {})
        for w in writer_output.get("warnings") or []:
            warnings.append(w)
        for a in writer_output.get("assumptions") or []:
            warnings.append(f"Assumption: {a}")

        feedback = ""
        if blocking_issues:
            feedback = (
                "Fix the SQL and preserve user intent. "
                "Address all blocking issues exactly:\n- "
                + "\n- ".join(blocking_issues)
            )

        return {
            "warnings": warnings,
            "blocking_issues": blocking_issues,
            "valid": len(blocking_issues) == 0,
            "rewriter_feedback": feedback,
        }

    def _route_after_validate(self, state: GraphState) -> str:
        if state.get("valid", False):
            return "to_finalize"
        if state.get("retry_count", 0) >= 1:
            return "to_finalize"
        state["retry_count"] = state.get("retry_count", 0) + 1
        return "to_retry_writer"

    def _node_finalize(self, state: GraphState) -> GraphState:
        context_resolution = state.get("context_resolution", {})
        if context_resolution.get("needs_clarification", False):
            result = TranslationResult(
                sql="",
                plan={
                    "resolved_question": state.get("resolved_question", ""),
                    "needs_clarification": True,
                    "clarification_question": context_resolution.get("clarification_question"),
                    "context_summary": context_resolution.get("context_summary"),
                    "active_filters": state.get("active_filters", {}),
                    "extracted_filters": [],
                },
                valid=False,
                warnings=[
                    context_resolution.get("clarification_question")
                    or "Clarification required for follow-up context."
                ],
                plan_agent1=None,
                plan_agent2=None,
            )
            return {"result": result}

        # QueryPlan validation failed after retry
        plan_validation_errors = state.get("plan_validation_errors", [])
        if plan_validation_errors and state.get("agent1_retry_count", 0) >= 1:
            agent1 = state.get("agent1", {})
            result = TranslationResult(
                sql="",
                plan={
                    "intent_summary": agent1.get("intent_summary", ""),
                    "needs_clarification": False,
                    "clarification_question": None,
                    "active_filters": agent1.get("active_filters", {}),
                    "extracted_filters": agent1.get("extracted_filters", []),
                    "validation_errors": plan_validation_errors,
                },
                valid=False,
                warnings=[f"QueryPlan validation failed: {e}" for e in plan_validation_errors],
                plan_agent1=state.get("plan_agent1"),
                plan_agent2=None,
            )
            return {"result": result}

        agent1 = state.get("agent1", {})
        needs_clarification = agent1.get("needs_clarification", False)

        if needs_clarification:
            result = TranslationResult(
                sql="",
                plan={
                    "resolved_question": state.get("resolved_question", ""),
                    "intent_summary": agent1.get("intent_summary", ""),
                    "needs_clarification": True,
                    "clarification_question": agent1.get("clarification_question"),
                    "active_filters": agent1.get("active_filters", {}),
                    "extracted_filters": agent1.get("extracted_filters", []),
                },
                valid=False,
                warnings=[
                    agent1.get("clarification_question") or "Clarification required."
                ],
                plan_agent1=state.get("plan_agent1"),
                plan_agent2=None,
            )
            return {"result": result}

        result = TranslationResult(
            sql=state.get("sql", ""),
            plan={
                "resolved_question": state.get("resolved_question", ""),
                "context_summary": context_resolution.get("context_summary"),
                "intent_summary": agent1.get("intent_summary", ""),
                "needs_clarification": False,
                "clarification_question": None,
                "active_filters": agent1.get("active_filters", {}),
                "extracted_filters": agent1.get("extracted_filters", []),
                "reasoning_summary": (state.get("writer_output") or {}).get(
                    "reasoning_summary"
                ),
            },
            valid=state.get("valid", False),
            warnings=list(state.get("blocking_issues", [])) + list(state.get("warnings", [])),
            plan_agent1=state.get("plan_agent1"),
            plan_agent2=state.get("plan_agent2"),
        )
        return {"result": result}
