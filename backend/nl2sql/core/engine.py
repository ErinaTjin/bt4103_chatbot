from __future__ import annotations

from typing import Any, Dict, List

from nl2sql.core.llm_adapter import LLMAdapter
from nl2sql.core.agent1_extractor import Agent1QueryPlanExtractor
from nl2sql.core.agent2_resolver import Agent2QueryPlanResolver


class TranslationResult:
    def __init__(
        self,
        sql: str,
        plan: Dict[str, Any],
        valid: bool,
        warnings: List[str],
        plan_agent1: Dict[str, Any] | None = None,
        plan_agent2: Dict[str, Any] | None = None,
    ):
        self.sql = sql
        self.plan = plan
        self.valid = valid
        self.warnings = warnings
        self.plan_agent1 = plan_agent1
        self.plan_agent2 = plan_agent2


class NL2SQLEngine:
    def __init__(
        self,
        llm: LLMAdapter | None = None,
        semantic_api: Any = None,
    ):
        self.llm = llm or LLMAdapter()
        self.extractor = Agent1QueryPlanExtractor(self.llm)
        self.resolver = Agent2QueryPlanResolver(self.llm)
        self.semantic_api = semantic_api
        self.allowed_tables = self._init_allowed_tables()

    def _init_allowed_tables(self) -> set[str]:
        if not self.semantic_api or not hasattr(self.semantic_api, "tables"):
            return set()
        return set(self.semantic_api.tables.keys())

    def _build_schema_context(self, relevant_only: bool = False, hint: str = "") -> str:
        if not self.semantic_api or not hasattr(self.semantic_api, "tables"):
            return "No schema context provided."

        tables = self.semantic_api.tables
        selected_tables: list[str] = list(tables.keys())

        if relevant_only and hint.strip():
            lower_hint = hint.lower()
            candidates: list[str] = []
            for table_name, table in tables.items():
                text_parts = [table_name, getattr(table, "description", "")]
                text_parts.extend(c.name for c in table.columns)
                blob = " ".join(text_parts).lower()
                if any(token in blob for token in lower_hint.split() if len(token) > 2):
                    candidates.append(table_name)
            if candidates:
                selected_tables = candidates

        lines: list[str] = []
        for table_name in selected_tables:
            table = tables[table_name]
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

    def _build_terminology_mappings(self) -> str:
        if not self.semantic_api:
            return "No terminology mappings provided."

        lines: list[str] = ["Field mappings:"]
        for canonical, synonyms in getattr(self.semantic_api, "terminology_fields", {}).items():
            lines.append(f"- {canonical}: {', '.join(synonyms[:10])}")

        lines.append("Value mappings:")
        for canonical, synonyms in getattr(self.semantic_api, "terminology_values", {}).items():
            if isinstance(synonyms, list):
                lines.append(f"- {canonical}: {', '.join(synonyms[:8])}")
            elif isinstance(synonyms, dict):
                nested_parts = []
                for k, vals in list(synonyms.items())[:6]:
                    nested_parts.append(f"{k}=>{', '.join(vals[:4])}")
                lines.append(f"- {canonical}: {'; '.join(nested_parts)}")

        return "\n".join(lines)

    def _build_business_rules(self) -> str:
        return "\n".join(
            [
                "- Default to read-only clinical analytics queries.",
                "- Keep SQL deterministic and executable in DuckDB.",
                "- For percentage questions, use metric formulas from semantic metrics when possible.",
                "- Apply active filters unless explicitly overridden by user question.",
                "- For trend questions, order by temporal dimension ascending.",
                "- Prefer COUNT(DISTINCT person.person_id) for patient counts.",
            ]
        )

    def _build_sql_snippets(self) -> str:
        return "\n".join(
            [
                "1) Count by dimension:",
                "SELECT person.gender_concept_name, COUNT(DISTINCT person.person_id) AS count_patients",
                "FROM \"anchor_view\".\"person\" AS person",
                "GROUP BY person.gender_concept_name",
                "ORDER BY count_patients DESC",
                "LIMIT 50;",
                "",
                "2) Trend:",
                "SELECT YEAR(condition_occurrence.condition_start_date) AS diagnosis_year,",
                "COUNT(DISTINCT person.person_id) AS count_patients",
                "FROM \"anchor_view\".\"person\" AS person",
                "LEFT JOIN \"anchor_view\".\"condition_occurrence\" AS condition_occurrence",
                "ON person.person_id = condition_occurrence.person_id",
                "GROUP BY diagnosis_year",
                "ORDER BY diagnosis_year ASC",
                "LIMIT 100;",
                "",
                "3) Multi-value filter:",
                "... WHERE measurement.measurement_concept_name IN ('KRAS Mutation Conclusion', 'BRAF Mutation Conclusion')",
            ]
        )

    def _build_safety_instructions(self) -> str:
        return "\n".join(
            [
                "- Output one SQL statement only.",
                "- Only SELECT/WITH read-only queries are allowed.",
                "- Do not use comments (--, /* */).",
                "- Do not use DDL/DML keywords (INSERT/UPDATE/DELETE/CREATE/DROP/ALTER/TRUNCATE).",
                "- Keep LIMIT <= 1000.",
            ]
        )

    def _validate_sql_shape(self, sql: str) -> str | None:
        candidate = sql.strip().rstrip(";").strip().lower()
        if not candidate:
            return "Agent2 returned empty SQL."
        if ";" in candidate:
            return "Agent2 returned multiple SQL statements."
        if "--" in candidate or "/*" in candidate or "*/" in candidate:
            return "Agent2 SQL contains comments, which are not allowed."
        if not (candidate.startswith("select") or candidate.startswith("with")):
            return "Agent2 SQL must start with SELECT or WITH."

        disallowed = [
            "insert", "update", "delete", "create", "drop", "alter", "truncate", "pragma",
        ]
        for kw in disallowed:
            if f" {kw} " in f" {candidate} ":
                return f"Agent2 SQL contains disallowed keyword: {kw}."
        return None

    def translate(
        self,
        user_query: str,
        conversation_history: List[Dict[str, Any] | str] | None = None,
        active_filters: Dict[str, Any] | None = None,
    ) -> TranslationResult:
        warnings: List[str] = []

        agent1 = self.extractor.extract(
            question=user_query,
            conversation_history=conversation_history,
            active_filters=active_filters,
        )
        plan_agent1 = agent1.model_dump()

        if agent1.needs_clarification:
            return TranslationResult(
                sql="",
                plan={
                    "intent_summary": agent1.intent_summary,
                    "needs_clarification": True,
                    "clarification_question": agent1.clarification_question,
                    "active_filters": agent1.active_filters,
                    "extracted_filters": [f.model_dump() for f in agent1.extracted_filters],
                },
                valid=False,
                warnings=[agent1.clarification_question or "Clarification required."],
                plan_agent1=plan_agent1,
                plan_agent2=None,
            )

        schema_context = self._build_schema_context(
            relevant_only=True,
            hint=f"{user_query} {agent1.intent_summary}",
        )

        writer_output = self.resolver.resolve(
            user_question=user_query,
            intent_summary=agent1.intent_summary,
            schema_context=schema_context,
            terminology_mappings=self._build_terminology_mappings(),
            business_rules=self._build_business_rules(),
            sql_snippets=self._build_sql_snippets(),
            safety_instructions=self._build_safety_instructions(),
            conversation_history=conversation_history,
            active_filters=active_filters,
        )

        sql = writer_output.sql.strip()
        plan_agent2 = writer_output.model_dump()

        safety_error = self._validate_sql_shape(sql)
        if safety_error:
            warnings.append(safety_error)

        if writer_output.warnings:
            warnings.extend(writer_output.warnings)

        if writer_output.assumptions:
            warnings.extend([f"Assumption: {x}" for x in writer_output.assumptions])

        plan = {
            "intent_summary": agent1.intent_summary,
            "needs_clarification": False,
            "clarification_question": None,
            "active_filters": agent1.active_filters,
            "extracted_filters": [f.model_dump() for f in agent1.extracted_filters],
            "reasoning_summary": writer_output.reasoning_summary,
        }

        return TranslationResult(
            sql=sql,
            plan=plan,
            valid=len(warnings) == 0,
            warnings=warnings,
            plan_agent1=plan_agent1,
            plan_agent2=plan_agent2,
        )
