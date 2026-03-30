from __future__ import annotations

import re
from typing import Any, Dict, List

from nl2sql.core.llm_adapter import LLMAdapter
from nl2sql.core.agent1_extractor import Agent1QueryPlanExtractor
from nl2sql.core.agent2_resolver import Agent2QueryPlanResolver
from nl2sql.core.context_agent import ContextAgent
from nl2sql.core.models import Agent1ContextSummary

# DEBUG
import logging
log = logging.getLogger(__name__)
log.info("=== engine.py loaded ===")

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
        self.context_agent = ContextAgent(self.llm)
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
                text_parts.extend(c.description for c in table.columns if c.description)  # added to handle mutation, grade & laterality
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
                "",
                "4) Stage breakdown with path-over-clin fallback:",
                "WITH stage_per_patient AS (",
                "    SELECT co.person_id,",
                "        COALESCE(",
                "            MAX(CASE WHEN m.measurement_concept_name = 'TNM Path Stage Group' THEN m.value_as_concept_name END),",
                "            MAX(CASE WHEN m.measurement_concept_name = 'TNM Clin Stage Group' THEN m.value_as_concept_name END)",
                "        ) AS raw_stage",
                "    FROM \"anchor_view\".\"condition_occurrence\" AS co",
                "    JOIN \"anchor_view\".\"measurement_mutation\" AS m ON co.person_id = m.person_id",
                "    WHERE co.ICD10 IN ('C18.0','C18.2','C18.3','C18.4','C18.5','C18.6','C18.7','C18.9','C19','C20')",
                "    AND m.measurement_concept_name IN ('TNM Path Stage Group', 'TNM Clin Stage Group')",
                "    GROUP BY co.person_id",
                "),",
                "stage_grouped AS (",
                "    SELECT person_id,",
                "        CASE WHEN raw_stage = 'I' THEN 'I'",
                "             WHEN raw_stage LIKE 'III%' THEN 'III'",
                "             WHEN raw_stage LIKE 'II%' THEN 'II'",
                "             WHEN raw_stage LIKE 'IV%' THEN 'IV'",
                "             ELSE 'Unknown' END AS stage",
                "    FROM stage_per_patient",
                "    WHERE raw_stage IS NOT NULL AND raw_stage != 'Stage Unknown'",
                ")",
                "SELECT stage, COUNT(DISTINCT person_id) AS case_count",
                "FROM stage_grouped",
                "GROUP BY stage ORDER BY stage;",
                "",
                "5) Age at diagnosis grouping (5-year):",
                "-- Use CTE to ensure age_group_start is available for GROUP BY and ORDER BY",
                "WITH age_groups AS (",
                "    SELECT",
                "        p.person_id,",
                "        CONCAT(",
                "            CAST(FLOOR((YEAR(co.condition_start_date) - p.year_of_birth) / 5) * 5 AS INTEGER),",
                "            '-',",
                "            CAST(FLOOR((YEAR(co.condition_start_date) - p.year_of_birth) / 5) * 5 + 4 AS INTEGER)",
                "        ) AS age_group,",
                "        CAST(FLOOR((YEAR(co.condition_start_date) - p.year_of_birth) / 5) * 5 AS INTEGER) AS age_group_start",
                "    FROM \"anchor_view\".\"person\" AS p",
                "    INNER JOIN \"anchor_view\".\"condition_occurrence\" AS co ON p.person_id = co.person_id",
                "    WHERE co.ICD10 IN ('C18.0','C18.2','C18.3','C18.4','C18.5','C18.6','C18.7','C18.9','C19','C20')",
                ")",
                "SELECT age_group, COUNT(DISTINCT person_id) AS case_count",
                "FROM age_groups",
                "GROUP BY age_group, age_group_start",
                "ORDER BY age_group_start;",
                "6) Cancer types and patients breakdown by ICD10:",
                "-- When asked 'how many cancer types and patients', always return a breakdown by ICD10:",
                "SELECT co.ICD10, COUNT(DISTINCT co.person_id) AS distinct_patients",
                "FROM \"anchor_view\".\"condition_occurrence\" AS co",
                "GROUP BY co.ICD10",
                "ORDER BY distinct_patients DESC;",
                "",
                "7) Early onset filter (age at diagnosis <= 49):",
                "-- Use this pattern for ANY cancer type, replacing the ICD10 filter as needed", 
                "SELECT COUNT(DISTINCT p.person_id) AS case_count",
                "FROM \"anchor_view\".\"person\" AS p",
                "INNER JOIN \"anchor_view\".\"condition_occurrence\" AS co ON p.person_id = co.person_id",
                "WHERE co.ICD10 IN (<relevant_ICD10_codes>)",
                " AND co.condition_start_date >= 'YYYY-01-01'", 
                " AND co.condition_start_date <= 'YYYY-12-31'","AND YEAR(co.condition_start_date) - p.year_of_birth <= 49;",
                "",
                "8) Age group breakdown filtered by any dimension (combined pattern):",
                "-- Use this pattern when combining age groups with ANY filter (stage, gender, mutation etc.)",
                "-- Replace <stage_filter> with the relevant filter value e.g. 'IV', 'Male', 'mutation detected'",
                "-- Replace <ICD10_codes> with relevant codes",
                "WITH stage_per_patient AS (",
                "    SELECT co.person_id,",
                "        COALESCE(",
                "            MAX(CASE WHEN m.measurement_concept_name = 'TNM Path Stage Group' THEN m.value_as_concept_name END),",
                "            MAX(CASE WHEN m.measurement_concept_name = 'TNM Clin Stage Group' THEN m.value_as_concept_name END)",
                "        ) AS raw_stage",
                "    FROM \"anchor_view\".\"condition_occurrence\" AS co",
                "    JOIN \"anchor_view\".\"measurement_mutation\" AS m ON co.person_id = m.person_id",
                "    WHERE co.ICD10 IN (<ICD10_codes>)",
                "    AND m.measurement_concept_name IN ('TNM Path Stage Group', 'TNM Clin Stage Group')",
                "    GROUP BY co.person_id",
                "),",
                "stage_grouped AS (",
                "    SELECT person_id,",
                "        CASE WHEN raw_stage = 'I' THEN 'I'",
                "             WHEN raw_stage LIKE 'III%' THEN 'III'",
                "             WHEN raw_stage LIKE 'II%' THEN 'II'",
                "             WHEN raw_stage LIKE 'IV%' THEN 'IV'",
                "             ELSE 'Unknown' END AS stage",
                "    FROM stage_per_patient",
                "    WHERE raw_stage IS NOT NULL AND raw_stage != 'Stage Unknown'",
                "),",
                "-- CRITICAL: always include person_id in this CTE for joining",
                "patient_age_stage AS (",
                "    SELECT",
                "        p.person_id,",
                "        CONCAT(",
                "            CAST(FLOOR((YEAR(co.condition_start_date) - p.year_of_birth) / 5) * 5 AS INTEGER),",
                "            '-',",
                "            CAST(FLOOR((YEAR(co.condition_start_date) - p.year_of_birth) / 5) * 5 + 4 AS INTEGER)",
                "        ) AS age_group,",
                "        CAST(FLOOR((YEAR(co.condition_start_date) - p.year_of_birth) / 5) * 5 AS INTEGER) AS age_group_start,",
                "        p.gender_source_value,",
                "        sg.stage",
                "    FROM \"anchor_view\".\"person\" AS p",
                "    INNER JOIN \"anchor_view\".\"condition_occurrence\" AS co ON p.person_id = co.person_id",
                "    INNER JOIN stage_grouped AS sg ON p.person_id = sg.person_id",
                "    WHERE co.ICD10 IN (<ICD10_codes>)",
                ")",
                "-- Filter by the relevant dimension in WHERE clause",
                "SELECT age_group, COUNT(DISTINCT person_id) AS case_count",
                "FROM patient_age_stage",
                "WHERE stage = '<stage_filter>'",
                "-- OR: WHERE gender_source_value = '<gender_filter>'",
                "GROUP BY age_group, age_group_start",
                "ORDER BY case_count DESC;",
                "",
                "9) Multi-attribute prevalence pivot pattern (use for mutations, grades, or any EAV breakdown):",
                "-- Use this pattern when question asks for prevalence/count/percentage of MULTIPLE attributes separately",
                "-- Replace <attribute_1>, <attribute_2> etc. with full measurement_concept_name values",
                "-- Replace <result_value> with value_as_concept_name to check e.g. 'mutation detected'",
                "-- Replace <ICD10_codes> with relevant codes",
                "-- Denominator = patients tested for ANY of the attributes, NOT all cohort patients",
                "WITH cohort_tested AS (",
                "    -- CRITICAL: measurement_concept_name filter here controls the denominator",
                "    -- removing this filter will inflate total_tested_patients with non-mutation records"
                "    SELECT DISTINCT co.person_id",
                "    FROM \"anchor_view\".\"condition_occurrence\" AS co",
                "    INNER JOIN \"anchor_view\".\"measurement_mutation\" AS m ON co.person_id = m.person_id",
                "    WHERE co.ICD10 IN (<ICD10_codes>)",
                "    AND m.measurement_concept_name IN ( -- DO NOT REMOVE THIS LINE",
                "        '<attribute_1>',",
                "        '<attribute_2>',",
                "        '<attribute_3>'",
                "    )",
                "),",
                "attribute_results AS (",
                "    -- Step 2: pivot — one flag column per attribute per patient",
                "    -- ALWAYS use MAX(CASE WHEN...) pattern, one per attribute",
                "    SELECT",
                "        m.person_id,",
                "        MAX(CASE WHEN m.measurement_concept_name = '<attribute_1>'",
                "            AND m.value_as_concept_name = '<result_value>' THEN 1 ELSE 0 END) AS has_attr1,",
                "        MAX(CASE WHEN m.measurement_concept_name = '<attribute_2>'",
                "            AND m.value_as_concept_name = '<result_value>' THEN 1 ELSE 0 END) AS has_attr2,",
                "        MAX(CASE WHEN m.measurement_concept_name = '<attribute_3>'",
                "            AND m.value_as_concept_name = '<result_value>' THEN 1 ELSE 0 END) AS has_attr3",
                "    FROM \"anchor_view\".\"measurement_mutation\" AS m",
                "    INNER JOIN cohort_tested AS ct ON m.person_id = ct.person_id",
                "    WHERE m.measurement_concept_name IN ( -- DO NOT REMOVE THIS LINE",
                "        '<attribute_1>',",
                "        '<attribute_2>',",
                "        '<attribute_3>'",
                "    )",
                "    GROUP BY m.person_id",
                ")",
                "-- Step 3: aggregate — count and percentage per attribute",
                "-- SUM(has_attrX) = patients positive for that attribute",
                "-- COUNT(DISTINCT person_id) = total tested patients (denominator)",
                "SELECT",
                "    COUNT(DISTINCT person_id) AS total_tested_patients,",
                "    SUM(has_attr1) AS patients_with_attr1,",
                "    ROUND(SUM(has_attr1) * 100.0 / COUNT(DISTINCT person_id), 2) AS attr1_percentage,",
                "    SUM(has_attr2) AS patients_with_attr2,",
                "    ROUND(SUM(has_attr2) * 100.0 / COUNT(DISTINCT person_id), 2) AS attr2_percentage,",
                "    SUM(has_attr3) AS patients_with_attr3,",
                "    ROUND(SUM(has_attr3) * 100.0 / COUNT(DISTINCT person_id), 2) AS attr3_percentage",
                "FROM attribute_results;",
                "-- Example for KRAS/BRAF/NRAS: replace <attribute_1> with 'KRAS Mutation Conclusion',",
                "-- <attribute_2> with 'BRAF Mutation Conclusion', <attribute_3> with 'NRAS Mutation Conclusion',",
                "-- <result_value> with 'mutation detected'",
                "",
                "10) Drug filter with multiple OR conditions — ALWAYS use parentheses:",
                "-- WRONG (breaks AND logic):",
                "-- WHERE mutation_filter AND drug LIKE '%x%' OR drug LIKE '%y%'",
                "-- CORRECT (parentheses group the OR conditions):",
                "SELECT COUNT(DISTINCT p.person_id) AS count_patients",
                "FROM \"anchor_view\".\"person\" AS p",
                "INNER JOIN \"anchor_view\".\"condition_occurrence\" AS co ON p.person_id = co.person_id",
                "INNER JOIN \"anchor_view\".\"measurement_mutation\" AS m ON p.person_id = m.person_id",
                "INNER JOIN \"anchor_view\".\"drug_exposure_cancerdrugs\" AS d ON p.person_id = d.person_id",
                "WHERE co.ICD10 IN ('C18.0','C18.2','C18.3','C18.4','C18.5','C18.6','C18.7','C18.9','C19','C20')",
                "AND m.measurement_concept_name = 'KRAS Mutation Conclusion'",
                "AND m.value_as_concept_name = 'no mutation detected'",
                "AND (",
                "    d.drug_source_value LIKE '%cetuximab%'",
                "    OR d.drug_source_value LIKE '%panitumumab%'",
                "    OR d.drug_source_value LIKE '%ERBITUX%'",
                "    OR d.drug_source_value LIKE '%VECTIBIX%'",
                ");",
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
    
    ALLOWED_FILTER_OPS = {"=", "!=", ">", "<", ">=", "<=", "in", "like", "or_like"}

    def _validate_query_plan(self, summary: Agent1ContextSummary) -> List[str]:
        errors: List[str] = []
        if not summary.intent_summary or not summary.intent_summary.strip():
            errors.append("Required field 'intent' is missing: intent_summary is empty.")
        if summary.extracted_filters is None:
            errors.append("Required field 'filters' is missing.")
        else:
            for i, f in enumerate(summary.extracted_filters):
                if not f.field or not f.field.strip():
                    errors.append(f"filters[{i}].field is empty or missing.")
                if not f.op or not f.op.strip():
                    errors.append(f"filters[{i}].op is empty or missing.")
                elif f.op.lower() not in self.ALLOWED_FILTER_OPS:
                    errors.append(
                        f"filters[{i}].op '{f.op}' is not a valid operator. "
                        f"Allowed: {sorted(self.ALLOWED_FILTER_OPS)}"
                    )
                elif f.op.lower() in {"in", "or_like"} and not isinstance(f.value, list):
                    errors.append(
                        f"filters[{i}].op='{f.op}' requires value to be a list, "
                        f"got {type(f.value).__name__}."
                    )
                if f.value is None:
                    errors.append(f"filters[{i}].value is None.")
        return errors

    def _qualify_table_names(self, sql: str) -> str:
        if not self.allowed_tables:
            return sql
        def replacer(match):
            keyword = match.group(1)
            table = match.group(2).strip('"')
            if table.lower() in {t.lower() for t in self.allowed_tables}:
                return f'{keyword} "anchor_view"."{table}"'
            return match.group(0)
        return re.sub(
            r'\b(FROM|JOIN)\s+"?([A-Za-z_][A-Za-z0-9_]*)"?',
            replacer,
            sql,
            flags=re.IGNORECASE,
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

        final_select = sql_lower.rsplit("select", 1)[-1].split("from")[0]
        if "person_id" in final_select and "count" not in final_select:
            blocking.append(
                "SQL returns individual patient-level person_id values. "
                "This is not permitted. Rephrase your question to use aggregation, "
                "e.g. 'how many patients' instead of 'show me all patients'."
            )

        if len(referenced_tables) > 1 and " join " not in f" {sql_lower} ":
            advisory.append("SQL references multiple tables without explicit JOIN clauses.")

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
                advisory.append(
                    "SQL is missing condition_occurrence cohort anchoring for a diagnosis/disease query."
                )

        asks_percentage = any(token in query_lower for token in ["percentage", "prevalence", "proportion", "rate"])
        if asks_percentage and "/" not in sql:
            advisory.append(
                "Percentage-style question detected but SQL does not clearly show numerator/denominator division."
            )

        return blocking, advisory

    def _fix_concat_comma(self, sql: str) -> str:
        """
        Fix two CONCAT issues:
        1. Missing comma after string literals: '-' CAST → '-', CAST
        2. Mismatched quotes in separator: '-" → '-'
        """
        # Fix mismatched quotes first
        sql = re.sub(r"'-\"", "'-'", sql)
        sql = re.sub(r'\"-\'', "'-'", sql)
        
        # Fix missing comma after string literal before CAST
        fixed = re.sub(
            r"('[^']*')\s*\n\s*(CAST\()",
            r"\1,\n            \2",
            sql
        )
        return fixed

    @staticmethod
    def _is_high_risk_clarification(user_query: str, clarification_question: str | None = None) -> bool:
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

    def translate(
        self,
        user_query: str,
        conversation_history: List[Dict[str, Any] | str] | None = None,
        active_filters: Dict[str, Any] | None = None,
        mode: str = "fast",
    ) -> TranslationResult:
        warnings: List[str] = []

        log.info("=== Engine.translate START: %s", user_query)

        # ── Agent 0: Context resolution ───────────────────────────────────────
        # Resolve follow-up questions into standalone questions using history.
        # Only runs when there is prior conversation context.
        trimmed_history = (conversation_history or [])[-6:]
        resolved_query = user_query
        if trimmed_history:
            resolution = self.context_agent.resolve(
                question=user_query,
                conversation_history=trimmed_history,
                active_filters=active_filters,
            )
            log.info("Context resolution: %s", resolution.model_dump())
            if resolution.needs_clarification and self._should_ask_clarification(
                mode=mode,
                user_query=user_query,
                clarification_question=resolution.clarification_question,
            ):
                return TranslationResult(
                    sql="",
                    plan={
                        "needs_clarification": True,
                        "clarification_question": resolution.clarification_question,
                        "active_filters": active_filters or {},
                    },
                    valid=False,
                    warnings=[resolution.clarification_question or "Clarification required."],
                )
            resolved_query = resolution.standalone_question
            # Reset active filters if this is a brand new topic
            if not resolution.is_follow_up:
                active_filters = {}
                log.info("New topic detected — active filters cleared")

        # ── Agent 1: Intent extraction ────────────────────────────────────────
        agent1 = self.extractor.extract(
            question=resolved_query,
            conversation_history=None,   # context already resolved by Agent0
            active_filters=active_filters,
        )
        plan_agent1 = agent1.model_dump()

        log.info("Agent1 output: %s", agent1.model_dump())

        if agent1.needs_clarification:
            should_ask = self._should_ask_clarification(
                mode=mode,
                user_query=user_query,
                clarification_question=agent1.clarification_question,
            )
            if not should_ask:
                warnings.append("Proceeding without clarification due to mode policy.")
                agent1.needs_clarification = False
                agent1.clarification_question = None
            else:
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

        # QueryPlan validation — before SQL generation
        plan_errors = self._validate_query_plan(agent1)
        if plan_errors:
            retry_question = (
                user_query
                + "\n\nPrevious attempt had validation issues: "
                + "; ".join(plan_errors)
                + ". Please ensure intent_summary is specific and all filters have valid field, op, and value."
            )
            agent1 = self.extractor.extract(
                question=retry_question,
                conversation_history=conversation_history,
                active_filters=active_filters,
            )
            plan_errors = self._validate_query_plan(agent1)
            if plan_errors:
                agent1.validation_errors = plan_errors
                return TranslationResult(
                    sql="",
                    plan={
                        "intent_summary": agent1.intent_summary,
                        "needs_clarification": False,
                        "clarification_question": None,
                        "active_filters": agent1.active_filters,
                        "extracted_filters": [f.model_dump() for f in agent1.extracted_filters],
                        "validation_errors": plan_errors,
                    },
                    valid=False,
                    warnings=[f"QueryPlan validation failed: {e}" for e in plan_errors],
                    plan_agent1=agent1.model_dump(),
                    plan_agent2=None,
                )

        schema_context = self._build_schema_context(
            relevant_only=True,
            hint=f"{user_query} {agent1.intent_summary}",
        )

        # DEBUG
        log.info("Schema context: %s", schema_context)

        # Agent 2 gets no conversation history — A0 already resolved the question
        # into a standalone form, and A1's intent_summary captures all semantic
        # context needed. Sending raw history to A2 inflates the prompt past the
        # context window and is a primary cause of hallucination.
        writer_output = self.resolver.resolve(
            user_question=user_query,
            intent_summary=agent1.intent_summary,
            schema_context=schema_context,
            terminology_mappings=self._build_terminology_mappings(),
            business_rules=self._build_business_rules(),
            sql_snippets=self._build_sql_snippets(),
            safety_instructions=self._build_safety_instructions(),
            conversation_history=None,
            active_filters=active_filters,
        )

        # DEBUG 
        log.info("Agent2 output: %s", writer_output.model_dump())

        sql = self._qualify_table_names(writer_output.sql.strip())
        sql = self._fix_concat_comma(sql)
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
            "intent": agent1.intent.value,
            "intent_summary": agent1.intent_summary,
            "resolved_question": resolved_query,
            "needs_clarification": False,
            "clarification_question": None,
            "active_filters": agent1.active_filters,
            "extracted_filters": [f.model_dump() for f in agent1.extracted_filters],
            "reasoning_summary": writer_output.reasoning_summary,
        }

        # Set preferred visualization based on intent
        visualization = "table"  # default
        if agent1.intent == "distribution":
            visualization = "bar"
        elif agent1.intent == "trend":
            visualization = "line"
        elif agent1.intent == "topN":
            visualization = "bar"
        elif agent1.intent == "count":
            visualization = "metric"  # Single number, show as metric card
        elif agent1.intent == "mutation_prevalence":
            visualization = "metric" # transformation to "grouped bar chart" will happen in frontend 
        elif agent1.intent == "cohort_comparison":
            visualization = "bar"
        # unsupported remains table

        plan["output"] = {"preferred_visualization": visualization}

        return TranslationResult(
            sql=sql,
            plan=plan,
            valid=len(blocking_issues) == 0,
            warnings=blocking_issues + warnings,
            plan_agent1=plan_agent1,
            plan_agent2=plan_agent2,
        )
