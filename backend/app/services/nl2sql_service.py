import os
from pathlib import Path
from app.config import settings
from nl2sql.core.engine import NL2SQLEngine
from nl2sql.core.langgraph_pipeline import NL2SQLLangGraph
from nl2sql.semantic.loader import SemanticLayerLoader
from app.db.query_executor import execute_sql, QueryTimeoutError
from app.db.duckdb_manager import duckdb_manager

# DEBUG
import logging
log = logging.getLogger(__name__)


def _classify_guardrail_code(error_message: str) -> str:
    msg = error_message.lower()
    if "columns outside schema whitelist" in msg:
        return "COLUMN_WHITELIST_BLOCK"
    if "values outside schema whitelist" in msg:
        return "VALUE_WHITELIST_BLOCK"
    if "blocked sensitive column access" in msg:
        return "PHI_BLOCKED_COLUMN"
    if "select * is not allowed" in msg:
        return "PHI_SELECT_STAR_BLOCK"
    if "patient-level output is not allowed" in msg:
        return "PHI_PATIENT_LEVEL_BLOCK"
    if "unsafe output projection" in msg:
        return "PHI_UNSAFE_PROJECTION"
    if "healthcare validation" in msg:
        return "HEALTHCARE_VALIDATION_BLOCK"
    return "SAFETY_POLICY_BLOCK"

class NL2SQLService:
    def __init__(self):
        self.engine = None
        self.graph = None

    def initialize(self):
        """
        Load semantic layer and initialize NL2SQL engine once at startup.
        """
        semantic_dir = Path(settings.SEMANTIC_LAYER_DIR)

        semantic_api = None
        if semantic_dir.exists() and semantic_dir.is_dir():
            semantic_api = SemanticLayerLoader(str(semantic_dir)).load()

        self.engine = NL2SQLEngine(semantic_api=semantic_api)
        if os.getenv("USE_LANGGRAPH", "false").lower() in {"1", "true", "yes"}:
            try:
                self.graph = NL2SQLLangGraph(self.engine)
            except Exception:
                self.graph = None

    def translate(
        self,
        question: str,
        conversation_history: list[dict | str] | None = None,
        active_filters: dict | None = None,
        mode: str = "fast",
    ):
        """
        Translate a natural language question into Agent1 summary + SQL.
        """
        if self.engine is None:
            raise RuntimeError("NL2SQL engine not initialized.")
        if self.graph is not None:
            return self.graph.invoke(
                question,
                conversation_history=conversation_history,
                active_filters=active_filters,
                mode=mode,
            )
        return self.engine.translate(
            question,
            conversation_history=conversation_history,
            active_filters=active_filters,
            mode=mode,
        )

    def translate_and_execute(
        self,
        question: str,
        conversation_history: list[dict | str] | None = None,
        active_filters: dict | None = None,
        mode: str = "fast",
        row_limit: int | None = None,
    ):
        """
        End-to-end pipeline:
        question -> Agent1 context -> Agent2 SQL -> execution
        """
        if self.engine is None:
            raise RuntimeError("NL2SQL engine not initialized.")

        result = self.translate(
            question=question,
            conversation_history=conversation_history,
            active_filters=active_filters,
            mode=mode,
        )

        # DEBUG
        log.info("SQL generated: %s", result.sql)
        log.info("Valid: %s | Warnings: %s", result.valid, result.warnings)        

        if not result.valid:
            return {
                "question": question,
                "sql": result.sql,
                "plan": result.plan,
                "plan_agent1": result.plan_agent1,
                "plan_agent2": result.plan_agent2,
                "warnings": result.warnings,
                "executed": False,
                "data": None,
            }

        con = duckdb_manager.con
        if con is None:
            raise RuntimeError("DuckDB connection not initialized.")

        try:
            data = execute_sql(
                con,
                result.sql,
                row_limit=row_limit,
                block_on_critical_validation=(mode == "strict"),
            )
        except QueryTimeoutError as te:
            return {
                "question": question,
                "sql": result.sql,
                "plan": result.plan,
                "plan_agent1": result.plan_agent1,
                "plan_agent2": result.plan_agent2,
                "warnings": [str(te)],
                "executed": False,
                "data": None,
                "error": str(te),
            }
        except ValueError as policy_error:
            code = _classify_guardrail_code(str(policy_error))
            return {
                "question": question,
                "sql": result.sql,
                "plan": result.plan,
                "plan_agent1": result.plan_agent1,
                "plan_agent2": result.plan_agent2,
                "warnings": [f"[{code}] Query blocked by safety policy: {policy_error}"],
                "guardrail_codes": [code],
                "executed": False,
                "data": None,
                "error": str(policy_error),
            }

        combined_warnings = list(result.warnings or [])
        combined_warnings.extend(data.get("warnings", []))
        combined_warnings.extend(data.get("critical_validation_errors", []))
        # Preserve order while removing duplicates.
        combined_warnings = list(dict.fromkeys(combined_warnings))

        return {
            "question": question,
            "resolved_question": result.plan.get("resolved_question"),
            "sql": result.sql,
            "plan": result.plan,
            "plan_agent1": result.plan_agent1,
            "plan_agent2": result.plan_agent2,
            "warnings": combined_warnings,
            "executed": True,
            "data": data,
        }

nl2sql_service = NL2SQLService()