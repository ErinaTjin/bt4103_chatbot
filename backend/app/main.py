#main.py
#Starts the server
#Connects to DuckDB on startup
#Registers views on startup
#Exposes /health and /sql/execute

from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException

from app.db.duckdb_manager import duckdb_manager
from app.db.view_registry import register_views
from app.db.query_executor import execute_sql
from app.models.api import SQLRequest, SQLResponse


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan hook (replacement for @app.on_event).
    Code BEFORE `yield` runs once at startup.
    Code AFTER `yield` runs once at shutdown.
    """
    # ---- STARTUP ----
    con = duckdb_manager.connect()   # opens/creates persistent DuckDB file: data/anchor.duckdb
    register_views(con)              # creates views pointing to parquet files

    yield

    # ---- SHUTDOWN ----
    duckdb_manager.close()           # closes the DuckDB connection cleanly


app = FastAPI(
    title="ANCHOR DuckDB Execution Service",
    lifespan=lifespan
)


@app.get("/health") #when client sends HTTP GET request to /health, run this function, return JSON
def health():
    """
    Simple health check to confirm:
    - API is running
    - DuckDB connection works
    """
    try:
        con = duckdb_manager.con
        if con is None:
            raise RuntimeError("DuckDB connection not initialized.")
        con.execute("SELECT 1;").fetchone()
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/sql/execute", response_model=SQLResponse) #when client sends post request to execute SQL, uses request/response model to check
def sql_execute(req: SQLRequest):
    """
    Executes a read-only SQL query (SELECT/WITH only) against DuckDB,
    applies row limits, and returns results in structured JSON.

    Request body:
      {
        "sql": "SELECT ...",
        "row_limit": 1000   # optional
      }
    """
    try:
        con = duckdb_manager.con #reuse same connection 
        if con is None:
            raise RuntimeError("DuckDB connection not initialized.")
        return execute_sql(con, req.sql, req.row_limit)

    except ValueError as ve:
        # Raised by sql_guard (unsafe SQL / disallowed keywords / multiple statements)
        raise HTTPException(status_code=400, detail=str(ve))

    except Exception as e:
        # DuckDB runtime errors, parsing errors, etc.
        raise HTTPException(status_code=500, detail=f"DuckDB error: {e}")