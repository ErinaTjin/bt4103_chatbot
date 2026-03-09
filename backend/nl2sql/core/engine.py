from __future__ import annotations

import re
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
        self.allowed_columns = self._init_allowed_columns()
        self.eav_tables = self._init_eav_tables()

    def _init_allowed_tables(self) -> set[str]:
        if not self.semantic_api or not hasattr(self.semantic_api, "tables"):
            return set()
        return set(self.semantic_api.tables.keys())

    def _init_allowed_columns(self) -> set[str]:
        if not self.semantic_api or not hasattr(self.semantic_api, "tables"):
            return set()
        cols: set[str] = set()
        for table in self.semantic_api.tables.values():
            for c in table.columns:
                cols.add(c.name)
        return cols

    def _init_eav_tables(self) -> set[str]:
        if not self.semantic_api or not hasattr(self.semantic_api, "tables"):
            return set()
        eav_like: set[str] = set()
        for table_name, table in self.semantic_api.tables.items():
            col_names = {c.name for c in table.columns}
            if "measurement_concept_name" in col_names and "value_as_concept_name" in col_names:
                eav_like.add(table_name)
        return eav_like

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

        if self.eav_tables:
            lines.append("EAV table semantics:")
            for table_name in sorted(self.eav_tables):
                lines.append(
                    f"- {table_name}: measurement_concept_name is the attribute selector; "
                    "value_as_concept_name is the measured result. "
                    "Both are required for precise filtering."
                )

        return "\n".join(lines)

    def _build_business_rules(self) -> str:
        return "\n".join(
            [
                "- Default to read-only clinical analytics queries.",
                "- Keep SQL deterministic and executable in DuckDB.",
                "- Use EAV semantics explicitly when EAV tables are involved.",
                "- For each requested concept in an EAV table, constrain both the concept column and the value/result column when applicable.",
                "- Every extracted filter from Agent1 must be reflected in SQL WHERE predicates or equivalent CTE predicates.",
                "- Use explicit JOIN clauses for every referenced table; never rely on implicit cross joins.",
                "- For percentage/prevalence/rate questions, define denominator cohort explicitly and separately from numerator where needed.",
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
                "3) EAV-safe filter pattern:",
                "SELECT m.measurement_concept_name, COUNT(DISTINCT p.person_id) AS patient_count",
                "FROM \"anchor_view\".\"person\" AS p",
                "JOIN \"anchor_view\".\"measurement_mutation\" AS m ON p.person_id = m.person_id",
                "WHERE m.measurement_concept_name IN (<requested_measurement_names>)",
                "AND m.value_as_concept_name = <requested_result_value>",
                "GROUP BY m.measurement_concept_name",
                "LIMIT 100;",
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

    def _extract_referenced_tables(self, sql: str) -> set[str]:
        pattern = re.compile(
            r"""
            \b(?:from|join)\s+
            (?:
                "[^"]+"\."(?P<q_table>[^"]+)"
                |
                [A-Za-z_][A-Za-z0-9_]*\.(?P<u_table>[A-Za-z_][A-Za-z0-9_]*)
                |
                "(?P<q_table_only>[^"]+)"
                |
                (?P<u_table_only>[A-Za-z_][A-Za-z0-9_]*)
            )
            """,
            flags=re.IGNORECASE | re.VERBOSE,
        )
        tables: set[str] = set()
        for match in pattern.finditer(sql):
            table = (
                match.group("q_table")
                or match.group("u_table")
                or match.group("q_table_only")
                or match.group("u_table_only")
            )
            if table:
                tables.add(table.lower())
        return tables

    def _validate_sql_semantics(
        self,
        sql: str,
        user_query: str,
        extracted_filters: list[dict[str, Any]],
        active_filters: dict[str, Any] | None,
    ) -> tuple[list[str], list[str]]:
        blocking: list[str] = []
        advisory: list[str] = []

        sql_lower = sql.lower()
        referenced_tables = self._extract_referenced_tables(sql)

        if len(referenced_tables) > 1 and " join " not in f" {sql_lower} ":
            blocking.append("SQL references multiple tables without explicit JOIN clauses.")

        # Enforce physical filter coverage for known schema columns.
        all_filters = list(extracted_filters)
        for k, v in (active_filters or {}).items():
            all_filters.append({"field": k, "op": "=", "value": v})

        for flt in all_filters:
            field = str(flt.get("field", "")).strip()
            if not field or field not in self.allowed_columns:
                continue
            if field.lower() not in sql_lower:
                blocking.append(f"SQL is missing required filter field: {field}")

        # EAV correctness checks.
        used_eav_tables = [t for t in referenced_tables if t in {x.lower() for x in self.eav_tables}]
        if used_eav_tables and "measurement_concept_name" not in sql_lower:
            blocking.append(
                "SQL uses EAV measurement table but does not constrain measurement_concept_name."
            )
        if used_eav_tables and "value_as_concept_name" not in sql_lower:
            advisory.append(
                "SQL uses EAV measurement table without an explicit value_as_concept_name constraint."
            )

        # Cohort anchoring checks for disease/diagnosis phrasing.
        query_lower = user_query.lower()
        asks_disease_cohort = any(
            token in query_lower for token in ["cancer", "diagnosed", "diagnosis", "icd", "cohort"]
        )
        if asks_disease_cohort and "condition_occurrence" in {t.lower() for t in self.allowed_tables}:
            if "condition_occurrence" not in referenced_tables:
                blocking.append(
                    "SQL is missing condition_occurrence cohort anchoring for a diagnosis/disease query."
                )

        asks_percentage = any(token in query_lower for token in ["percentage", "prevalence", "proportion", "rate"])
        if asks_percentage and "/" not in sql:
            advisory.append(
                "Percentage-style question detected but SQL does not clearly show numerator/denominator division."
            )

        return blocking, advisory

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

        blocking_issues: List[str] = []

        safety_error = self._validate_sql_shape(sql)
        if safety_error:
            blocking_issues.append(safety_error)

        semantic_blocking, semantic_advisory = self._validate_sql_semantics(
            sql=sql,
            user_query=user_query,
            extracted_filters=[f.model_dump() for f in agent1.extracted_filters],
            active_filters=active_filters,
        )
        blocking_issues.extend(semantic_blocking)
        warnings.extend(semantic_advisory)

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
            valid=len(blocking_issues) == 0,
            warnings=blocking_issues + warnings,
            plan_agent1=plan_agent1,
            plan_agent2=plan_agent2,
        )
