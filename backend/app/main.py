# DEBUG 
import logging
logging.basicConfig(level=logging.INFO)

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
from app.db.session_store import init_db, load_session, save_session, reset_session, clear_filters

@asynccontextmanager
async def lifespan(app: FastAPI):
    con = duckdb_manager.connect()
    register_views(con)
    nl2sql_service.initialize()
    init_db()

    yield

    duckdb_manager.close()


app = FastAPI(
    title="ANCHOR NL2SQL + DuckDB Service",
    lifespan=lifespan
)

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
def sql_execute(req: SQLRequest):
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
    try:
        result = nl2sql_service.translate(
            question=req.question,
            conversation_history=req.conversation_history,
            active_filters=req.active_filters,
            mode=req.mode,
        )

        return {
            "question": req.question,
            "sql": result.sql,
            "plan": result.plan,
            "plan_agent1": result.plan_agent1,
            "plan_agent2": result.plan_agent2,
            "warnings": result.warnings,
            "executed": False,
            "data": None,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"NL2SQL translation error: {e}")


@app.post("/nl2sql/execute", response_model=NL2SQLResponse)
def nl2sql_execute(req: NL2SQLRequest):
    try:
        return nl2sql_service.translate_and_execute(
            question=req.question,
            conversation_history=req.conversation_history,
            active_filters=req.active_filters,
            mode=req.mode,
            row_limit=req.row_limit,
        )

    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"NL2SQL execution error: {e}")

#-------session management endpoints for conversational context-------
from app.db.session_store import (
    init_db, load_session, save_session, reset_session, clear_filters
)
from nl2sql.core.context_agent import ContextAgent
from app.models.api import ChatRequest, ChatResponse
context_agent = ContextAgent()   # initialised once at module level

"""Implements the /nl2sql/chat endpoint which handles follow-up questions in a conversational manner. It uses a 
ContextAgent to resolve follow-up questions into standalone questions, and then passes them to the nl2sql_service for 
translation and execution. The session state is loaded at the beginning of the request, updated with the new chat history, 
active filters, last executed SQL, and warnings, and then saved back to the database. The endpoint also supports 
resetting the session and clearing filters through additional endpoints."""
@app.post("/nl2sql/chat", response_model=ChatResponse)
def nl2sql_chat(req: ChatRequest):
    state = load_session(req.session_id)

    # ── Agent 0: resolve follow-up into standalone question ──
    resolution = context_agent.resolve(
        question=req.question,
        conversation_history=state["chat_history"],
        active_filters=state["active_filters"],
    )

    if resolution.needs_clarification:
        # Return the clarifying question without touching DB yet
        return {
            "session_id": req.session_id,
            "question": req.question,
            "resolved_question": req.question,
            "sql": "",
            "plan": {"needs_clarification": True,
                     "clarification_question": resolution.clarification_question},
            "plan_agent1": None,
            "plan_agent2": None,
            "warnings": [resolution.clarification_question],
            "executed": False,
            "data": None,
            "active_filters": state["active_filters"],
            "chat_history": state["chat_history"],
        }

    resolved_q = resolution.standalone_question

    # ── Engine: Agent1 + Agent2 ──
    result = nl2sql_service.translate_and_execute(
        question=resolved_q,
        conversation_history=state["chat_history"],
        active_filters=state["active_filters"],
        mode=req.mode,
        row_limit=req.row_limit,
    )

    # ── Update session state ──
    # Merge any new filters Agent1 extracted back into active_filters
    new_extracted = result.get("plan", {}).get("extracted_filters") or []
    new_filter_dict = {
        f["field"]: f["value"]
        for f in new_extracted
        if isinstance(f, dict) and f.get("field")
    }
    merged_filters = {**state["active_filters"], **new_filter_dict}

    state["chat_history"].append({"role": "user",    "content": req.question})
    state["chat_history"].append({"role": "assistant","content": resolved_q})
    state["last_sql"]       = result.get("sql")
    state["warnings"]       = result.get("warnings", [])
    state["active_filters"] = merged_filters

    # Keep history bounded (last 20 turns = 40 messages)
    state["chat_history"] = state["chat_history"][-40:]

    save_session(req.session_id, state)

    return {
        **result,
        "session_id": req.session_id,
        "resolved_question": resolved_q,
        "active_filters": merged_filters,
        "chat_history": state["chat_history"],
    }


@app.delete("/session/{session_id}")
def delete_session(session_id: str):
    reset_session(session_id)
    return {"status": "reset", "session_id": session_id}

@app.patch("/session/{session_id}/filters")
def patch_filters(session_id: str):
    state = clear_filters(session_id)
    return {"status": "filters_cleared", "active_filters": state["active_filters"]}

@app.get("/session/{session_id}")
def get_session(session_id: str):
    return load_session(session_id)