#sql_poicy.py
#single source of truth for SQL policy enforcement

from __future__ import annotations

import re
from typing import Iterable


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
    _ensure_allowed_tables(
        stripped,
        allowed_tables=allowed_tables,
        allowed_schema=allowed_schema,
    )

    return apply_hard_limit(stripped, hard_limit)
