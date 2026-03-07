# query_executor.py

from __future__ import annotations

import time

from app.config import settings
from app.db.sql_policy import enforce_sql_policy
from app.db.view_registry import SCHEMA, VIEW_SPECS


def execute_sql(con, sql: str, row_limit: int | None = None):
    # Final enforced cap at execution time
    hard_limit = row_limit or settings.MAX_ROWS_DEFAULT
    hard_limit = min(hard_limit, settings.MAX_ROWS_HARD)

    safe_sql = enforce_sql_policy(
        sql,
        allowed_tables=VIEW_SPECS.keys(),
        allowed_schema=SCHEMA,
        hard_limit=hard_limit,
    )

    start = time.perf_counter()
    cur = con.execute(safe_sql)

    cols = [d[0] for d in cur.description]
    raw_rows = cur.fetchall()
    elapsed_ms = int((time.perf_counter() - start) * 1000)

    rows = [dict(zip(cols, r)) for r in raw_rows]

    return {
        "columns": cols,
        "rows": rows,
        "row_count": len(rows),
        "elapsed_ms": elapsed_ms,
        "applied_limit": hard_limit,
    }