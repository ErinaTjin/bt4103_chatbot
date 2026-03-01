#query_executor.py

import time #for time.perf_counter()
from app.config import settings
from app.db.sql_guard import ensure_select_only

#applies default limit if sql doesn't already contain limit
def apply_limit(sql: str, limit: int) -> str:
    if " limit " in sql.lower():
        return sql
    return f"{sql}\nLIMIT {limit}"

#main execution function
def execute_sql(con, sql: str, row_limit: int | None = None):
    safe_sql = ensure_select_only(sql) #check sql before execution, raise error if needed

    # Apply sensible limits
    limit = row_limit or settings.MAX_ROWS_DEFAULT
    limit = min(limit, settings.MAX_ROWS_HARD)
    safe_sql = apply_limit(safe_sql, limit)

    start = time.perf_counter() #record start time
    cur = con.execute(safe_sql) #sends SQL to duckdb, which parses and executes it, returns result object

    cols = [d[0] for d in cur.description] #extract col names
    raw_rows = cur.fetchall() #all rows
    elapsed_ms = int((time.perf_counter() - start) * 1000) #execution time

    # Convert to list of dicts for JSON
    rows = [dict(zip(cols, r)) for r in raw_rows] #convert rows to json friendly format

    return {
        "columns": cols,
        "rows": rows,
        "row_count": len(rows),
        "elapsed_ms": elapsed_ms,
        "applied_limit": limit,
    }