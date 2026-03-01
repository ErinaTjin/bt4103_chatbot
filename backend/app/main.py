#main.py
#Starts the server
#Connects to DuckDB on startup
#Registers views on startup
#Exposes /health and /sql/execute

from fastapi import FastAPI, HTTPException
from app.db.duckdb_manager import duckdb_manager
from app.db.view_registry import register_views
from app.db.query_executor import execute_sql
from app.models.api import SQLRequest, SQLResponse

app = FastAPI(title="ANCHOR DuckDB Execution Service")

@app.on_event("startup")
def startup():
    con = duckdb_manager.connect()
    register_views(con)

@app.on_event("shutdown")
def shutdown():
    duckdb_manager.close()

@app.get("/health")
def health():
    try:
        con = duckdb_manager.con
        con.execute("SELECT 1;").fetchone()
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/sql/execute", response_model=SQLResponse)
def sql_execute(req: SQLRequest):
    try:
        con = duckdb_manager.con
        return execute_sql(con, req.sql, req.row_limit)
    except ValueError as ve:
        # Guardrail failure
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DuckDB error: {e}")