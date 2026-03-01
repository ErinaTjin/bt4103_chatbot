#query_executor.py

import time
from app.config import settings
from app.db.sql_guard import ensure_select_only

def apply_limit(sql: str, limit: int) -> str:
    # If query already contains LIMIT, keep it (simple rule)
    if " limit " in sql.lower():
        return sql
    return f"{sql}\nLIMIT {limit}"

def execute_sql(con, sql: str, row_limit: int | None = None):
    safe_sql = ensure_select_only(sql)

    # Apply sensible limits
    limit = row_limit or settings.MAX_ROWS_DEFAULT
    limit = min(limit, settings.MAX_ROWS_HARD)
    safe_sql = apply_limit(safe_sql, limit)

    start = time.perf_counter()
    cur = con.execute(safe_sql)

    cols = [d[0] for d in cur.description]
    raw_rows = cur.fetchall()
    elapsed_ms = int((time.perf_counter() - start) * 1000)

    # Convert to list of dicts for JSON
    rows = [dict(zip(cols, r)) for r in raw_rows]

    return {
        "columns": cols,
        "rows": rows,
        "row_count": len(rows),
        "elapsed_ms": elapsed_ms,
        "applied_limit": limit,
    }