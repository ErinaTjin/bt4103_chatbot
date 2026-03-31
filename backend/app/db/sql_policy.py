#sql_poicy.py
#single source of truth for SQL policy enforcement

from __future__ import annotations

import re
from typing import Iterable

from app.db.schema_whitelist import get_schema_whitelists


DISALLOWED_KEYWORDS = {
    "insert",
    "update",
    "delete",
    "create",
    "drop",
    "alter",
    "truncate",
    "copy",
    "attach",
    "detach",
    "pragma",
    "call",
    "execute",
    "merge",
    "replace",
    "vacuum",
}

COMMENT_PATTERNS = (
    "--",
    "/*",
    "*/",
)

BLOCKED_COLUMNS = {
    "name",
    "full_name",
    "patient_name",
    "nric",
    "address",
    "free_text_notes",
    "free_text_note",
    "notes",
    "note_text",
    "person_id",
}

SAFE_OUTPUT_COLUMNS = {
    "year",
    "month",
    "quarter",
    "diagnosis_year",
    "gender",
    "sex",
    "race",
    "ethnicity",
    "age_group",
    "age_group_start",
    "stage",
    "stage_group",
    "tumor_site",
    "histology",
    "count",
    "patient_count",
    "case_count",
    "total",
    "proportion",
    "percentage",
    "rate",
}

AGGREGATE_FUNCTIONS = (
    "count",
    "sum",
    "avg",
    "min",
    "max",
    "median",
    "stddev",
    "variance",
)

_SCHEMA_WHITELISTS = get_schema_whitelists()
SCHEMA_COLUMN_WHITELIST = _SCHEMA_WHITELISTS.allowed_columns
SCHEMA_VALUE_WHITELIST = _SCHEMA_WHITELISTS.allowed_values_by_column


def _strip_outer_semicolon(sql: str) -> str:
    return sql.strip().rstrip(";").strip()


def _normalize_ws(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


def _ensure_no_comments(sql: str) -> None:
    lowered = sql.lower()
    for token in COMMENT_PATTERNS:
        if token in lowered:
            raise ValueError("SQL comments are not allowed.")


def _ensure_single_statement(sql: str) -> None:
    # after trimming one optional trailing semicolon, any remaining semicolon
    # indicates multiple statements
    stripped = _strip_outer_semicolon(sql)
    if ";" in stripped:
        raise ValueError("Multiple SQL statements are not allowed.")


def _ensure_read_only(sql: str) -> None:
    lowered = _normalize_ws(sql).lower()

    if not (lowered.startswith("select") or lowered.startswith("with")):
        raise ValueError("Only SELECT queries are allowed.")

    for kw in DISALLOWED_KEYWORDS:
        if re.search(rf"\b{re.escape(kw)}\b", lowered):
            raise ValueError(f"Disallowed SQL keyword: {kw}")


def _strip_string_literals(sql: str) -> str:
    # Remove quoted strings so keyword/column scans don't match literal text.
    return re.sub(r"'([^']|'')*'", "''", sql)


def _extract_top_level_select_list(sql: str) -> str | None:
    lowered = _strip_string_literals(sql).lower()
    depth = 0
    i = 0
    select_start = None

    while i < len(lowered):
        ch = lowered[i]
        if ch == "(":
            depth += 1
            i += 1
            continue
        if ch == ")":
            depth = max(0, depth - 1)
            i += 1
            continue

        if depth == 0 and lowered.startswith("select", i):
            prev_ok = i == 0 or not (lowered[i - 1].isalnum() or lowered[i - 1] == "_")
            next_i = i + 6
            next_ok = next_i >= len(lowered) or not (lowered[next_i].isalnum() or lowered[next_i] == "_")
            if prev_ok and next_ok:
                select_start = next_i
        i += 1

    if select_start is None:
        return None

    depth = 0
    i = select_start
    while i < len(lowered):
        ch = lowered[i]
        if ch == "(":
            depth += 1
            i += 1
            continue
        if ch == ")":
            depth = max(0, depth - 1)
            i += 1
            continue

        if depth == 0 and lowered.startswith("from", i):
            prev_ok = i == 0 or not (lowered[i - 1].isalnum() or lowered[i - 1] == "_")
            next_i = i + 4
            next_ok = next_i >= len(lowered) or not (lowered[next_i].isalnum() or lowered[next_i] == "_")
            if prev_ok and next_ok:
                return sql[select_start:i].strip()
        i += 1

    return None


def _split_top_level_csv(expr: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    current: list[str] = []

    for ch in expr:
        if ch == "(":
            depth += 1
            current.append(ch)
            continue
        if ch == ")":
            depth = max(0, depth - 1)
            current.append(ch)
            continue
        if ch == "," and depth == 0:
            piece = "".join(current).strip()
            if piece:
                parts.append(piece)
            current = []
            continue
        current.append(ch)

    tail = "".join(current).strip()
    if tail:
        parts.append(tail)
    return parts


def _expression_alias(expr: str) -> str | None:
    m = re.search(r"\bas\s+([A-Za-z_][A-Za-z0-9_]*)\s*$", expr, flags=re.IGNORECASE)
    if m:
        return m.group(1).lower()
    m2 = re.search(r"([A-Za-z_][A-Za-z0-9_]*)\s*$", expr)
    if m2:
        return m2.group(1).lower()
    return None


def _columns_from_expression(expr: str) -> set[str]:
    """Extract columns referenced in expression, excluding those inside aggregate functions."""
    stripped = _strip_string_literals(expr)
    
    # Columns inside aggregate functions are not directly exposed
    for agg_fn in AGGREGATE_FUNCTIONS:
        pattern = rf"\b{agg_fn}\s*\([^)]*\)"
        stripped = re.sub(pattern, "agg_fn()", stripped, flags=re.IGNORECASE)
    
    cols = {m.group(1).lower() for m in re.finditer(r"\b[A-Za-z_][A-Za-z0-9_]*\.([A-Za-z_][A-Za-z0-9_]*)\b", stripped)}
    cols |= {m.group(1).lower() for m in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*)\b", stripped)}

    reserved = {
        "select", "from", "where", "group", "by", "order", "join", "left", "right", "inner", "outer",
        "on", "as", "and", "or", "not", "null", "is", "in", "like", "case", "when", "then", "else",
        "end", "distinct", "with", "over", "partition", "rows", "range", "between", "asc", "desc",
        "agg_fn",
    }
    reserved |= set(AGGREGATE_FUNCTIONS)
    return {c for c in cols if c not in reserved}


def _expression_has_aggregate(expr: str) -> bool:
    return bool(re.search(r"\b(?:" + "|".join(AGGREGATE_FUNCTIONS) + r")\s*\(", expr, flags=re.IGNORECASE))


def _leaf_column_name(token: str) -> str:
    return token.split(".")[-1].lower()


def _extract_referenced_columns(sql: str) -> set[str]:
    cols: set[str] = set()
    stripped = _strip_string_literals(sql)
    keyword_tokens = {"not", "in", "like", "is", "between", "and", "or"}

    # Qualified references: alias.column
    for m in re.finditer(r"\b[A-Za-z_][A-Za-z0-9_]*\.([A-Za-z_][A-Za-z0-9_]*)\b", stripped):
        cols.add(m.group(1).lower())

    # Predicate-based references: col = ..., col IN (...), col LIKE ..., col BETWEEN ...
    for m in re.finditer(
        r"\b([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)\s*(?:=|<>|!=|<=|>=|<|>|\bnot\s+in\b|\bin\b|\bnot\s+like\b|\blike\b|\bis\b|\bbetween\b)",
        stripped,
        flags=re.IGNORECASE,
    ):
        leaf = _leaf_column_name(m.group(1))
        if leaf not in keyword_tokens:
            cols.add(leaf)

    select_list = _extract_top_level_select_list(sql)
    if select_list:
        for expr in _split_top_level_csv(select_list):
            raw = expr.strip()
            m = re.match(
                r"^(?:[A-Za-z_][A-Za-z0-9_]*\.)?([A-Za-z_][A-Za-z0-9_]*)(?:\s+as\s+[A-Za-z_][A-Za-z0-9_]*)?$",
                raw,
                flags=re.IGNORECASE,
            )
            if m:
                cols.add(m.group(1).lower())

    return cols


def _extract_literal_constraints(sql: str) -> list[tuple[str, str, str]]:
    constraints: list[tuple[str, str, str]] = []
    raw_sql = sql

    eq_pattern = re.compile(
        r"\b([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)\s*=\s*'([^']*)'",
        flags=re.IGNORECASE,
    )
    for m in eq_pattern.finditer(raw_sql):
        constraints.append((_leaf_column_name(m.group(1)), "eq", m.group(2).strip().lower()))

    neq_pattern = re.compile(
        r"\b([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)\s*(?:<>|!=)\s*'([^']*)'",
        flags=re.IGNORECASE,
    )
    for m in neq_pattern.finditer(raw_sql):
        constraints.append((_leaf_column_name(m.group(1)), "neq", m.group(2).strip().lower()))

    in_pattern = re.compile(
        r"\b([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)\s+in\s*\(([^)]*)\)",
        flags=re.IGNORECASE,
    )
    for m in in_pattern.finditer(raw_sql):
        col = _leaf_column_name(m.group(1))
        raw_list = m.group(2)
        for val in re.findall(r"'([^']*)'", raw_list):
            constraints.append((col, "in", val.strip().lower()))

    not_in_pattern = re.compile(
        r"\b([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)\s+not\s+in\s*\(([^)]*)\)",
        flags=re.IGNORECASE,
    )
    for m in not_in_pattern.finditer(raw_sql):
        col = _leaf_column_name(m.group(1))
        raw_list = m.group(2)
        for val in re.findall(r"'([^']*)'", raw_list):
            constraints.append((col, "not_in", val.strip().lower()))

    like_pattern = re.compile(
        r"\b([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)\s+like\s*'([^']*)'",
        flags=re.IGNORECASE,
    )
    for m in like_pattern.finditer(raw_sql):
        constraints.append((_leaf_column_name(m.group(1)), "like", m.group(2).strip().lower()))

    not_like_pattern = re.compile(
        r"\b([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)\s+not\s+like\s*'([^']*)'",
        flags=re.IGNORECASE,
    )
    for m in not_like_pattern.finditer(raw_sql):
        constraints.append((_leaf_column_name(m.group(1)), "not_like", m.group(2).strip().lower()))

    return constraints


def _pattern_matches_allowed_values(pattern: str, allowed_values: set[str]) -> bool:
    # Remove wildcard and punctuation noise from LIKE patterns.
    tokenized = re.sub(r"[%_]+", " ", pattern)
    tokenized = re.sub(r"[^a-z0-9\s]+", " ", tokenized)
    parts = [p for p in tokenized.split() if len(p) >= 2]

    if not parts:
        return True

    for part in parts:
        for allowed in allowed_values:
            if part in allowed or allowed in part:
                return True
    return False


def _ensure_schema_column_whitelist(
    sql: str,
    *,
    allowed_tables: Iterable[str],
    allowed_schema: str | None = None,
) -> None:
    if not SCHEMA_COLUMN_WHITELIST:
        return

    referenced_cols = _extract_referenced_columns(sql)
    allowed_table_set = {t.lower() for t in allowed_tables}
    allowed_schema_name = allowed_schema.lower() if allowed_schema else None
    unknown = sorted(
        col for col in referenced_cols
        if col not in SCHEMA_COLUMN_WHITELIST
        and col not in SAFE_OUTPUT_COLUMNS
        and col not in BLOCKED_COLUMNS
        and col not in allowed_table_set
        and col != allowed_schema_name
    )
    if unknown:
        raise ValueError(
            "SQL references columns outside schema whitelist: "
            + ", ".join(unknown)
        )


def _ensure_schema_value_whitelist(sql: str) -> None:
    if not SCHEMA_VALUE_WHITELIST:
        return

    violations: list[str] = []
    for col, op, literal_value in _extract_literal_constraints(sql):
        allowed_values = SCHEMA_VALUE_WHITELIST.get(col)
        if not allowed_values:
            continue

        if op in {"eq", "in", "neq", "not_in"}:
            if literal_value not in allowed_values:
                violations.append(f"{col} {op} '{literal_value}'")
            continue

        if op in {"like", "not_like"}:
            if not _pattern_matches_allowed_values(literal_value, allowed_values):
                violations.append(f"{col} {op} '{literal_value}'")
            continue

    if violations:
        raise ValueError(
            "SQL uses values outside schema whitelist: "
            + ", ".join(sorted(set(violations)))
        )


def _ensure_no_blocked_columns(sql: str) -> None:
    """
    Check for blocked columns used outside of aggregate functions.
    Columns inside COUNT(), SUM(), AVG(), etc. are not directly exposed so they're safe.
    """
    select_list = _extract_top_level_select_list(sql)
    if not select_list:
        return

    for expr in _split_top_level_csv(select_list):
        if _expression_has_aggregate(expr):
            continue
        used_cols = _columns_from_expression(expr)
        blocked_hit = sorted(c for c in used_cols if c in BLOCKED_COLUMNS)
        if blocked_hit:
            raise ValueError(f"Blocked sensitive column access: {', '.join(blocked_hit)}")


def _ensure_safe_output_projection(sql: str) -> None:
    select_list = _extract_top_level_select_list(sql)
    if not select_list:
        raise ValueError("Unable to validate SELECT projection for PHI guardrail.")

    if re.search(r"(^|,)\s*\*\s*(,|$)", select_list):
        raise ValueError("SELECT * is not allowed by PHI policy.")

    exprs = _split_top_level_csv(select_list)
    has_aggregate = any(_expression_has_aggregate(e) for e in exprs)

    for expr in exprs:
        # If this expression contains aggregates, columns inside are not directly exposed.
        if _expression_has_aggregate(expr):
            continue

        used_cols = _columns_from_expression(expr)
        blocked_hit = sorted(c for c in used_cols if c in BLOCKED_COLUMNS)
        if blocked_hit:
            raise ValueError(f"Blocked sensitive column access: {', '.join(blocked_hit)}")

        alias = _expression_alias(expr)
        if alias and alias in SAFE_OUTPUT_COLUMNS:
            continue

        if not used_cols:
            raise ValueError("Unsafe output projection detected. Use aggregate output or approved safe fields.")

        unsafe_cols = sorted(c for c in used_cols if c not in SAFE_OUTPUT_COLUMNS)
        if unsafe_cols:
            raise ValueError(
                "Unsafe output projection detected. Use aggregate output or approved safe fields. "
                f"Unsafe fields: {', '.join(unsafe_cols)}"
            )

    if not has_aggregate:
        # Non-aggregate outputs are only allowed if every field is from safe dimensions.
        for expr in exprs:
            if _expression_has_aggregate(expr):
                continue
            used_cols = _columns_from_expression(expr)
            if any(c not in SAFE_OUTPUT_COLUMNS for c in used_cols):
                raise ValueError("Patient-level output is not allowed by PHI policy.")


def _extract_referenced_tables(sql: str) -> set[tuple[str | None, str]]:
    """
    Extracts tables/views referenced after FROM/JOIN.

    Supports patterns like:
      FROM "anchor_view"."person" AS person
      JOIN "anchor_view"."death" AS death
      FROM anchor_view.person
      FROM person
      JOIN "person"
    """
    pattern = re.compile(
        r"""
        \b(?:from|join)\s+
        (?:
            "(?P<q_schema>[^"]+)"\."(?P<q_table>[^"]+)"
            |
            (?P<u_schema>[A-Za-z_][A-Za-z0-9_]*)\.(?P<u_table>[A-Za-z_][A-Za-z0-9_]*)
            |
            "(?P<q_table_only>[^"]+)"
            |
            (?P<u_table_only>[A-Za-z_][A-Za-z0-9_]*)
        )
        """,
        flags=re.IGNORECASE | re.VERBOSE,
    )

    found: set[tuple[str | None, str]] = set()
    for match in pattern.finditer(sql):
        schema = match.group("q_schema") or match.group("u_schema")
        table = (
            match.group("q_table")
            or match.group("u_table")
            or match.group("q_table_only")
            or match.group("u_table_only")
        )
        if table:
            found.add((schema.lower() if schema else None, table.lower()))
    return found

def _extract_cte_names(sql: str) -> set[str]:
    """Extract CTE names defined in WITH clause so they aren't flagged as external tables."""
    pattern = re.compile(
        r'\b(\w+)\s+AS\s*\(',
        flags=re.IGNORECASE
    )
    return {match.group(1).lower() for match in pattern.finditer(sql)}

def _ensure_allowed_tables(
    sql: str,
    allowed_tables: Iterable[str],
    allowed_schema: str | None = None,
) -> None:
    allowed_table_set = {t.lower() for t in allowed_tables}
    expected_schema = allowed_schema.lower() if allowed_schema else None

    cte_names = _extract_cte_names(sql)
    referenced = _extract_referenced_tables(sql)
    bad_refs: list[str] = []

    for schema, table in referenced:
        if table in cte_names:
            continue

        if table not in allowed_table_set:
            bad_refs.append(f"{schema + '.' if schema else ''}{table}")
            continue

        if expected_schema is not None and schema is not None and schema != expected_schema:
            bad_refs.append(f"{schema}.{table}")

    if bad_refs:
        raise ValueError(
            f"SQL references disallowed tables/views: {', '.join(sorted(set(bad_refs)))}"
        )


def apply_hard_limit(sql: str, limit: int) -> str:
    """
    Enforces a final outer LIMIT regardless of what the inner SQL contains.
    This is safer than trying to detect or edit an existing LIMIT clause.
    """
    if limit <= 0:
        raise ValueError("Limit must be positive.")
    inner = _strip_outer_semicolon(sql)
    return f"SELECT * FROM ({inner}) AS _safe_query LIMIT {limit}"


def enforce_sql_policy(
    sql: str,
    *,
    allowed_tables: Iterable[str],
    hard_limit: int,
    allowed_schema: str | None = None,
) -> str:
    """
    Final execution-time SQL gate.
    Returns a safe SQL string to execute.
    """
    if not sql or not sql.strip():
        raise ValueError("SQL is empty.")

    stripped = _strip_outer_semicolon(sql)

    _ensure_no_comments(stripped)
    _ensure_single_statement(stripped)
    _ensure_read_only(stripped)
    _ensure_schema_column_whitelist(
        stripped,
        allowed_tables=allowed_tables,
        allowed_schema=allowed_schema,
    )
    _ensure_schema_value_whitelist(stripped)
    _ensure_no_blocked_columns(stripped)
    _ensure_safe_output_projection(stripped)
    _ensure_allowed_tables(
        stripped,
        allowed_tables=allowed_tables,
        allowed_schema=allowed_schema,
    )

    return apply_hard_limit(stripped, hard_limit)
