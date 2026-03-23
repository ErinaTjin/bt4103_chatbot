from __future__ import annotations

import os
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
    clarification_limit_exceeded: bool
    mode: str

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
      agent1_context -> (clarify? finalize) -> agent2_sql_writer -> validate_sql
      -> (pass finalize | fail and retry once -> agent2_sql_writer)
    """

    def __init__(self, engine: NL2SQLEngine) -> None:
        self.engine = engine
        self.context_agent = ContextAgent(engine.llm)
        self.max_clarification_asks = int(os.getenv("MAX_CLARIFICATION_ASKS", "1"))
        self.strict_clarification_asks = int(os.getenv("MAX_CLARIFICATION_ASKS_STRICT", "3"))
        self._app = self._build_graph()

    def _build_graph(self):
        if StateGraph is None or END is None:
            raise RuntimeError(
                "LangGraph is not installed. Install it with: pip install langgraph"
            )

        graph = StateGraph(GraphState)
        graph.add_node("context_agent", self._node_context_agent)
        graph.add_node("agent1_context", self._node_agent1_context)
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
            {"to_writer": "agent2_sql_writer", "to_finalize": "finalize"},
        )
        graph.add_edge("agent2_sql_writer", "validate_sql")
        graph.add_conditional_edges(
            "validate_sql",
            self._route_after_validate,
            {"to_finalize": "finalize", "to_retry_writer": "agent2_sql_writer"},
        )
        graph.add_edge("finalize", END)

        return graph.compile()

    def _clarification_limit(self, mode: str) -> int:
        return self.strict_clarification_asks if str(mode).lower() == "strict" else self.max_clarification_asks

    @staticmethod
    def _is_high_risk_clarification(user_query: str, clarification_question: str | None = None) -> bool:
        """
        High-risk requests should not silently assume missing details.
        """
        text = f"{user_query} {clarification_question or ''}".lower()
        high_risk_keywords = {
            "treat",
            "treatment",
            "therapy",
            "drug",
            "medication",
            "dose",
            "dosage",
            "prescrib",
            "recommend",
            "advice",
            "prognosis",
            "survival",
            "mortality",
            "death",
            "emergency",
            "urgent",
        }
        return any(token in text for token in high_risk_keywords)

    def _should_ask_clarification(
        self,
        mode: str,
        user_query: str,
        clarification_question: str | None = None,
    ) -> bool:
        mode_normalized = str(mode).lower()
        if mode_normalized == "fast":
            return False
        if mode_normalized == "strict":
            return self._is_high_risk_clarification(user_query, clarification_question)
        return False

    def _clarification_ask_count(self, history: List[Dict[str, Any] | str] | None) -> int:
        if not history:
            return 0
        count = 0
        for item in history:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role", "")).lower()
            kind = str(item.get("kind", "")).lower()
            content = str(item.get("content", "")).lower()
            if role == "assistant" and (kind == "clarification" or "clarif" in content):
                count += 1
        return count

    def invoke(
        self,
        user_query: str,
        conversation_history: List[Dict[str, Any] | str] | None = None,
        active_filters: Dict[str, Any] | None = None,
        mode: str = "fast",
    ) -> TranslationResult:
        initial_state: GraphState = {
            "user_query": user_query,
            "conversation_history": conversation_history or [],
            "active_filters": active_filters or {},
            "warnings": [],
            "blocking_issues": [],
            "retry_count": 0,
            "clarification_limit_exceeded": False,
            "mode": mode,
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
        context_resolution = state.get("context_resolution", {})
        if context_resolution.get("needs_clarification", False):
            clarification_question = context_resolution.get("clarification_question")
            should_ask = self._should_ask_clarification(
                mode=state.get("mode", "fast"),
                user_query=state.get("user_query", ""),
                clarification_question=clarification_question,
            )
            if not should_ask:
                warnings = list(state.get("warnings", []))
                warnings.append(
                    "Proceeding without clarification due to mode policy."
                )
                state["warnings"] = warnings
                context_resolution["needs_clarification"] = False
                context_resolution["clarification_question"] = None
                state["context_resolution"] = context_resolution
                return "to_agent1"

            asked = self._clarification_ask_count(state.get("conversation_history"))
            if asked >= self._clarification_limit(state.get("mode", "fast")):
                state["clarification_limit_exceeded"] = True
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
        agent1 = state["agent1"]
        if agent1.get("needs_clarification", False):
            clarification_question = agent1.get("clarification_question")
            should_ask = self._should_ask_clarification(
                mode=state.get("mode", "fast"),
                user_query=state.get("resolved_question") or state.get("user_query", ""),
                clarification_question=clarification_question,
            )
            if not should_ask:
                warnings = list(state.get("warnings", []))
                warnings.append(
                    "Proceeding without clarification due to mode policy."
                )
                state["warnings"] = warnings
                agent1["needs_clarification"] = False
                agent1["clarification_question"] = None
                state["agent1"] = agent1
                return "to_writer"

            asked = self._clarification_ask_count(state.get("conversation_history"))
            if asked >= self._clarification_limit(state.get("mode", "fast")):
                state["clarification_limit_exceeded"] = True
            return "to_finalize"
        return "to_writer"

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

        if state.get("clarification_limit_exceeded", False):
            result = TranslationResult(
                sql="",
                plan={
                    "resolved_question": state.get("resolved_question", ""),
                    "needs_clarification": False,
                    "clarification_question": None,
                    "context_summary": context_resolution.get("context_summary"),
                    "active_filters": state.get("active_filters", {}),
                    "extracted_filters": [],
                    "error": "clarification_limit_exceeded",
                },
                valid=False,
                warnings=[
                    f"Clarification limit reached for mode={state.get('mode', 'fast')}. Please provide a complete question in one message."
                ],
                plan_agent1=state.get("plan_agent1"),
                plan_agent2=state.get("plan_agent2"),
            )
            return {"result": result}
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
