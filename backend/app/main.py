#main.py
#Starts the server
#Connects to DuckDB on startup
#Registers views on startup
#Exposes /health and /sql/execute

from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.db.duckdb_manager import duckdb_manager
from app.db.view_registry import register_views
from app.db.query_executor import execute_sql
from app.models.api import (
    SQLRequest,
    SQLResponse,
    NL2SQLRequest,
    NL2SQLResponse,
)
from app.services.nl2sql_service import nl2sql_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup:
    - connect DuckDB
    - register views
    - initialize NL2SQL engine
    Shutdown:
    - close DuckDB
    """
    con = duckdb_manager.connect()
    register_views(con)
    nl2sql_service.initialize()

    yield

    duckdb_manager.close()


app = FastAPI(
    title="ANCHOR NL2SQL + DuckDB Service",
    lifespan=lifespan
)

# Allow requests from the Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health():
    try:
        con = duckdb_manager.con
        if con is None:
            raise RuntimeError("DuckDB connection not initialized.")
        con.execute("SELECT 1;").fetchone()

        engine_ready = nl2sql_service.engine is not None

        return {
            "status": "ok",
            "duckdb": "connected",
            "nl2sql_engine": "ready" if engine_ready else "not_ready",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/sql/execute", response_model=SQLResponse)
def sql_execute(req: SQLRequest): #direct SQL execution when you already have SQL
    try:
        con = duckdb_manager.con
        if con is None:
            raise RuntimeError("DuckDB connection not initialized.")
        return execute_sql(con, req.sql, req.row_limit)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DuckDB error: {e}")


@app.post("/nl2sql/translate")
def nl2sql_translate(req: NL2SQLRequest):
    """
    Translate natural language to QueryPlan + SQL only.
    """
    try:
        result = nl2sql_service.translate(
            question=req.question,
            active_filters=req.active_filters,
        )

        return {
            "question": req.question,
            "sql": result.sql,
            "plan": result.plan.model_dump(),
            "plan_agent1": result.plan_agent1.model_dump() if result.plan_agent1 else None,
            "plan_agent2": result.plan_agent2.model_dump() if result.plan_agent2 else None,
            "warnings": result.warnings,
            "executed": False,
            "data": None,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"NL2SQL translation error: {e}")


@app.post("/nl2sql/execute", response_model=NL2SQLResponse)
def nl2sql_execute(req: NL2SQLRequest):
    """
    End-to-end:
    NL question -> SQL -> DuckDB execution -> structured response
    """
    try:
        return nl2sql_service.translate_and_execute(
            question=req.question,
            active_filters=req.active_filters,
            row_limit=req.row_limit,
        )

    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"NL2SQL execution error: {e}")
