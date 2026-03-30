# query_executor.py

from __future__ import annotations

import time
import threading

from app.config import settings
from app.db.sql_policy import enforce_sql_policy
from app.db.view_registry import SCHEMA, VIEW_SPECS


class QueryTimeoutError(Exception):
    """Raised when a DuckDB query exceeds the configured timeout."""
    pass


def execute_sql(con, sql: str, row_limit: int | None = None, timeout_seconds: int | None = None):
    """
    Execute validated SQL against DuckDB with row limit and timeout enforcement.

    Args:
        con:             Active DuckDB connection.
        sql:             Raw SQL string (will be validated by sql_policy).
        row_limit:       Max rows to return. Capped at MAX_ROWS_HARD.
        timeout_seconds: Max seconds to wait for query execution.
                         Defaults to QUERY_TIMEOUT_SECONDS from settings.

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

    return result_holder["data"]