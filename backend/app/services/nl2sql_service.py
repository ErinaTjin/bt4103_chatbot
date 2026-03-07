#nl2sql_service.py

import os
from pathlib import Path

from nl2sql.engine import NL2SQLEngine
from backend.semantic_layer.loader import SemanticLayerLoader
from app.db.query_executor import execute_sql
from app.db.duckdb_manager import duckdb_manager


class NL2SQLService:
    def __init__(self):
        self.engine = None

    def initialize(self):
        """
        Load semantic layer and initialize NL2SQL engine once at startup.
        """
        project_root = Path(__file__).resolve().parents[2]
        semantic_dir = project_root / "semantic_layer"

        semantic_api = None
        if semantic_dir.exists() and semantic_dir.is_dir():
            semantic_api = SemanticLayerLoader(str(semantic_dir)).load()

        self.engine = NL2SQLEngine(semantic_api=semantic_api)

    def translate(self, question: str, active_filters: dict | None = None):
        """
        Translate a natural language question into a QueryPlan + SQL.
        """
        if self.engine is None:
            raise RuntimeError("NL2SQL engine not initialized.")
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

        result = self.engine.translate(question, active_filters=active_filters)

        if not result.valid:
            return {
                "question": question,
                "sql": result.sql,
                "plan": result.plan.model_dump(),
                "warnings": result.warnings,
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
            "warnings": result.warnings,
            "executed": True,
            "data": data,
        }


nl2sql_service = NL2SQLService()