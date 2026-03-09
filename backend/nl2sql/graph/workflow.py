from __future__ import annotations

from typing import Any, Dict, Optional

from nl2sql.core.engine import NL2SQLEngine, TranslationResult

from .nodes import GraphNodes, route_after_validate
from .state import NL2SQLState


class NL2SQLGraphWorkflow:
    def __init__(self, engine: NL2SQLEngine):
        self.engine = engine
        self._compiled = self._build_graph()

    def _build_graph(self):
        try:
            from langgraph.graph import END, START, StateGraph
        except ImportError as e:
            raise RuntimeError(
                "LangGraph is not installed. Install with: pip install langgraph"
            ) from e

        nodes = GraphNodes(self.engine)
        builder = StateGraph(NL2SQLState)

        builder.add_node("context", nodes.context_node)
        builder.add_node("agent1", nodes.agent1_node)
        builder.add_node("agent2", nodes.agent2_node)
        builder.add_node("normalize", nodes.normalize_node)
        builder.add_node("plan_sql", nodes.plan_sql_node)
        builder.add_node("validate", nodes.validate_node)
        builder.add_node("final", nodes.final_node)

        builder.add_edge(START, "context")
        builder.add_edge("context", "agent1")
        builder.add_edge("agent1", "agent2")
        builder.add_edge("agent2", "normalize")
        builder.add_edge("normalize", "plan_sql")
        builder.add_edge("plan_sql", "validate")
        builder.add_conditional_edges(
            "validate",
            route_after_validate,
            {
                "agent2": "agent2",
                "final": "final",
            },
        )
        builder.add_edge("final", END)

        return builder.compile()

    def invoke(
        self,
        question: str,
        active_filters: Optional[Dict[str, Any]] = None,
        chat_history: Optional[list[dict]] = None,
    ) -> TranslationResult:
        initial_state: NL2SQLState = {
            "question": question,
            "active_filters": active_filters,
            "chat_history": chat_history or [],
            "sql": "",
            "warnings": [],
            "retry_count": 0,
            "max_retries": 2,
            "error": None,
            "valid": False,
        }

        out = self._compiled.invoke(initial_state)
        result = out.get("result")
        if result is None:
            raise RuntimeError("LangGraph workflow did not produce a result")
        return result
