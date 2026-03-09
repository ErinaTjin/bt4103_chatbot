# nl2sql_service.py

from pathlib import Path

from app.config import settings
from app.db.duckdb_manager import duckdb_manager
from app.db.query_executor import execute_sql
from nl2sql.core.engine import NL2SQLEngine
from nl2sql.semantic.loader import SemanticLayerLoader


class NL2SQLService:
    def __init__(self):
        self.engine: NL2SQLEngine | None = None
        self.graph_workflow = None

    def initialize(self):
        """
        Load semantic layer and initialize NL2SQL engine once at startup.
        If USE_LANGGRAPH=true and langgraph is installed, use graph workflow as primary path.
        """
        semantic_dir = Path(settings.SEMANTIC_LAYER_DIR)

        semantic_api = None
        if semantic_dir.exists() and semantic_dir.is_dir():
            semantic_api = SemanticLayerLoader(str(semantic_dir)).load()

        self.engine = NL2SQLEngine(semantic_api=semantic_api)

        if settings.USE_LANGGRAPH:
            try:
                from nl2sql.graph import NL2SQLGraphWorkflow

                self.graph_workflow = NL2SQLGraphWorkflow(self.engine)
            except Exception as e:
                # Keep service available with deterministic fallback path.
                self.graph_workflow = None
                print(f"[NL2SQL] LangGraph disabled, fallback to engine pipeline: {e}")

    def translate(self, question: str, active_filters: dict | None = None):
        """
        Translate a natural language question into a QueryPlan + SQL.
        """
        if self.engine is None:
            raise RuntimeError("NL2SQL engine not initialized.")

        if self.graph_workflow is not None:
            return self.graph_workflow.invoke(
                question=question,
                active_filters=active_filters,
            )

        return self.engine.translate(question, active_filters=active_filters)

    def translate_and_execute(
        self,
        question: str,
        active_filters: dict | None = None,
        row_limit: int | None = None,
    ):
        """
        End-to-end pipeline:
        question -> plan -> SQL -> execution
        """
        if self.engine is None:
            raise RuntimeError("NL2SQL engine not initialized.")

        result = self.translate(question, active_filters=active_filters)

        if not result.valid:
            return {
                "question": question,
                "sql": result.sql,
                "plan": result.plan.model_dump(),
                "plan_agent1": result.plan_agent1.model_dump() if result.plan_agent1 else None,
                "plan_agent2": result.plan_agent2.model_dump() if result.plan_agent2 else None,
                "warnings": result.warnings,
                "metadata": getattr(result, "metadata", None),
                "executed": False,
                "data": None,
            }

        con = duckdb_manager.con
        if con is None:
            raise RuntimeError("DuckDB connection not initialized.")

        data = execute_sql(con, result.sql, row_limit=row_limit)

        return {
            "question": question,
            "sql": result.sql,
            "plan": result.plan.model_dump(),
            "plan_agent1": result.plan_agent1.model_dump() if result.plan_agent1 else None,
            "plan_agent2": result.plan_agent2.model_dump() if result.plan_agent2 else None,
            "warnings": result.warnings,
            "metadata": getattr(result, "metadata", None),
            "executed": True,
            "data": data,
        }


nl2sql_service = NL2SQLService()
