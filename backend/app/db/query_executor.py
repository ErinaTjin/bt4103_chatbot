# query_executor.py

from __future__ import annotations

import time
import threading
from datetime import datetime

from app.config import settings
from app.db.sql_policy import enforce_sql_policy
from app.db.view_registry import SCHEMA, VIEW_SPECS


class QueryTimeoutError(Exception):
    """Raised when a DuckDB query exceeds the configured timeout."""
    pass


def _parse_iso_date(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text).date()
        except ValueError:
            try:
                return datetime.strptime(text[:10], "%Y-%m-%d").date()
            except ValueError:
                return None
    return None


def _normalize_stage(value: str) -> str:
    val = value.strip().upper().replace("STAGE", "").strip()
    if val.startswith("UNKNOWN"):
        return "UNKNOWN"
    if val in {"I", "II", "III", "IV"}:
        return val
    for prefix in ("I", "II", "III", "IV"):
        if val.startswith(prefix):
            return prefix
    return val


def _validate_healthcare_rules(data: dict) -> tuple[list[str], list[str]]:
    rows = data.get("rows", [])
    if not rows:
        return [], []

    warnings: list[str] = []
    critical: list[str] = []

    # Official stage values from schema.json "STAGING" section:
    # See: backend/nl2sql/semantic/schema.json
    # Stage values in value_as_concept_name: 'I', 'IIA', 'IIB', 'IIC', 'IIIA', 'IIIB', 'IIIC', 'IVA', 'IVB', 'IVC', 'Stage Unknown'
    valid_stages = {
        "I", "IIA", "IIB", "IIC",
        "IIIA", "IIIB", "IIIC",
        "IVA", "IVB", "IVC",
        "UNKNOWN", "STAGE UNKNOWN"
    }

    for idx, row in enumerate(rows, start=1):
        lowered = {str(k).lower(): v for k, v in row.items()}

        death_date = _parse_iso_date(lowered.get("death_date"))
        birth_date = _parse_iso_date(lowered.get("birth_date"))

        yob = lowered.get("year_of_birth")
        if death_date is not None and birth_date is not None and death_date <= birth_date:
            critical.append(
                f"Row {idx}: death_date must be after birth_date."
            )
        elif death_date is not None and isinstance(yob, int) and death_date.year <= yob:
            critical.append(
                f"Row {idx}: death_date year must be after year_of_birth."
            )

        for key, value in lowered.items():
            key_lower = key.lower()

            if "stage" in key_lower and isinstance(value, str) and value.strip():
                normalized = _normalize_stage(value)
                if normalized not in valid_stages:
                    warnings.append(
                        f"Row {idx}: invalid staging category '{value}' in column '{key}'."
                    )

            if isinstance(value, (int, float)):
                non_negative_field = (
                    "count" in key_lower
                    or "num" in key_lower
                    or "total" in key_lower
                    or "cases" in key_lower
                    or "patients" in key_lower
                    or "value" in key_lower
                )
                if non_negative_field and value < 0:
                    critical.append(
                        f"Row {idx}: negative value {value} in '{key}'."
                    )

    dedup_warnings = list(dict.fromkeys(warnings))
    dedup_critical = list(dict.fromkeys(critical))
    return dedup_warnings, dedup_critical


def execute_sql(
    con,
    sql: str,
    row_limit: int | None = None,
    timeout_seconds: int | None = None,
    block_on_critical_validation: bool = False,
):
    """
    Execute validated SQL against DuckDB with row limit and timeout enforcement.

    Args:
        con:             Active DuckDB connection.
        sql:             Raw SQL string (will be validated by sql_policy).
        row_limit:       Max rows to return. Capped at MAX_ROWS_HARD.
        timeout_seconds: Max seconds to wait for query execution.
                         Defaults to QUERY_TIMEOUT_SECONDS from settings.
        block_on_critical_validation:
                 If True, critical healthcare validation findings
                 will block output after SQL execution.

    Returns:
        dict with columns, rows, row_count, elapsed_ms, applied_limit.

    Raises:
        ValueError:        If sql_policy blocks the query.
        QueryTimeoutError: If the query exceeds the timeout.
        Exception:         Any DuckDB execution error.
    """
    # ── Row limit ─────────────────────────────────────────────────────────────
    hard_limit = row_limit or settings.MAX_ROWS_DEFAULT
    hard_limit = min(hard_limit, settings.MAX_ROWS_HARD)

    # ── Policy enforcement (raises ValueError on violation) ───────────────────
    safe_sql = enforce_sql_policy(
        sql,
        allowed_tables=VIEW_SPECS.keys(),
        allowed_schema=SCHEMA,
        hard_limit=hard_limit,
    )

    # ── Timeout setup ─────────────────────────────────────────────────────────
    timeout = timeout_seconds if timeout_seconds is not None else settings.QUERY_TIMEOUT_SECONDS

    # ── Execute in a thread so we can enforce the timeout ─────────────────────
    result_holder: dict = {}
    error_holder:  dict = {}

    def _run():
        try:
            t0 = time.perf_counter()
            cur = con.execute(safe_sql)
            cols = [d[0] for d in cur.description]
            raw_rows = cur.fetchall()
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            result_holder["data"] = {
                "columns":       cols,
                "rows":          [dict(zip(cols, r)) for r in raw_rows],
                "row_count":     len(raw_rows),
                "elapsed_ms":    elapsed_ms,
                "applied_limit": hard_limit,
            }
        except Exception as exc:
            error_holder["error"] = exc

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout=timeout)

    if thread.is_alive():
        # Thread is still running — query exceeded timeout.
        # DuckDB does not expose a cancel API so we let the daemon thread
        # eventually finish on its own; we just stop waiting and raise.
        raise QueryTimeoutError(
            f"Query exceeded the {timeout}s timeout and was aborted. "
            "Try a simpler or more specific question."
        )

    if "error" in error_holder:
        raise error_holder["error"]

    # ── Small-n suppression ──────────────────────────
    def _apply_small_n_suppression(data: dict, k: int = 5):
        rows = data.get("rows", [])
        if not rows:
            return data, False

        suppressed_any = False

        def _is_count_field(key: str) -> bool:
            k_lower = key.lower()
            return (
                "count" in k_lower
                or "num" in k_lower
                or "n_" in k_lower
                or "patients" in k_lower
                or "cases" in k_lower
                or "total" in k_lower
            )

        for row in rows:
            for key, val in list(row.items()):
                if isinstance(val, (int, float)) and _is_count_field(key):
                    try:
                        if val < k:
                            row[key] = f"<{k}"
                            suppressed_any = True
                    except Exception:
                        # If comparison fails for any reason, skip safely
                        continue

        return data, suppressed_any

    data = result_holder["data"]
    data, suppressed = _apply_small_n_suppression(data, k=5)

    warnings, critical = _validate_healthcare_rules(data)

    if warnings:
        data.setdefault("warnings", [])
        data["warnings"].extend(warnings)

    if critical:
        data.setdefault("critical_validation_errors", [])
        data["critical_validation_errors"].extend(critical)
        if block_on_critical_validation:
            joined = "; ".join(critical)
            raise ValueError(
                "Query result blocked by healthcare validation: " + joined
            )

    if suppressed:
        # Attach warnings for frontend display (MessageBubble already renders warnings)
        data.setdefault("warnings", [])
        data["warnings"].append("Small subgroup counts have been suppressed")

    return data