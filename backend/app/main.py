import logging
import traceback

# DEBUG
logging.basicConfig(level=logging.DEBUG)

from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.db.duckdb_manager import duckdb_manager
from app.db.view_registry import register_views
from app.db.query_executor import execute_sql
from app.db.auth_db import init_db as init_auth_db
from app.models.api import (
    SQLRequest,
    SQLResponse,
    NL2SQLRequest,
    NL2SQLResponse,
)
from app.models.auth import (
    LoginRequest, TokenResponse, UserOut, CreateUserRequest, UpdateRoleRequest, RegisterRequest,
    ConversationOut, ConversationCreated, AppendMessageRequest, ConversationMessageOut,
)
from app.db.auth_db import get_conn as get_auth_conn
from app.services.nl2sql_service import nl2sql_service
from app.services.auth_service import (
    authenticate_user, create_access_token, decode_token,
    list_users, create_user, delete_user, update_user_role, register_user,
)
from app.db.session_store import init_db, load_session, save_session, reset_session, clear_filters
from nl2sql.core.context_agent import ContextAgent
from app.models.api import ChatRequest, ChatResponse
context_agent = ContextAgent()   # initialised once at module level


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_auth_db()          # create users table + seed defaults
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

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logging.error("Unhandled exception:\n" + traceback.format_exc())
    return JSONResponse(status_code=500, content={"detail": str(exc)})

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001"],
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


# ── Auth ─────────────────────────────────────────────────────────────────────

bearer_scheme = HTTPBearer()

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)) -> dict:
    user = decode_token(credentials.credentials)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return user

def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


@app.post("/auth/login", response_model=TokenResponse)
def login(req: LoginRequest):
    user = authenticate_user(req.username, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token = create_access_token(user["username"], user["role"])
    return TokenResponse(access_token=token, username=user["username"], role=user["role"])


@app.post("/auth/register", response_model=TokenResponse, status_code=201)
def register(req: RegisterRequest):
    try:
        user = register_user(req.username, req.password)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    token = create_access_token(user["username"], user["role"])
    return TokenResponse(access_token=token, username=user["username"], role=user["role"])


@app.get("/auth/me")
def me(current_user: dict = Depends(get_current_user)):
    return current_user


# ── Admin user management ─────────────────────────────────────────────────────

@app.get("/admin/users", response_model=list[UserOut])
def admin_list_users(_: dict = Depends(require_admin)):
    return list_users()


@app.post("/admin/users", response_model=UserOut, status_code=201)
def admin_create_user(req: CreateUserRequest, _: dict = Depends(require_admin)):
    try:
        return create_user(req.username, req.password, req.role)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not create user: {e}")


@app.delete("/admin/users/{user_id}", status_code=204)
def admin_delete_user(user_id: int, _: dict = Depends(require_admin)):
    if not delete_user(user_id):
        raise HTTPException(status_code=404, detail="User not found")


@app.patch("/admin/users/{user_id}/role")
def admin_update_role(user_id: int, req: UpdateRoleRequest, _: dict = Depends(require_admin)):
    if not update_user_role(user_id, req.role):
        raise HTTPException(status_code=404, detail="User not found")
    return {"ok": True}


# ── Conversations ─────────────────────────────────────────────────────────────

@app.get("/conversations", response_model=list[ConversationOut])
def list_conversations(current_user: dict = Depends(get_current_user)):
    with get_auth_conn() as conn:
        rows = conn.execute(
            "SELECT id, title, created_at FROM conversations WHERE user_id = ? ORDER BY created_at DESC",
            (current_user["id"],),
        ).fetchall()
    return [dict(r) for r in rows]


@app.post("/conversations", response_model=ConversationCreated, status_code=201)
def create_conversation(current_user: dict = Depends(get_current_user)):
    with get_auth_conn() as conn:
        cur = conn.execute(
            "INSERT INTO conversations (user_id, title) VALUES (?, ?)",
            (current_user["id"], "New conversation"),
        )
        conn.commit()
        return {"id": cur.lastrowid}


@app.get("/conversations/{conv_id}/messages", response_model=list[ConversationMessageOut])
def get_messages(conv_id: int, current_user: dict = Depends(get_current_user)):
    with get_auth_conn() as conn:
        # Verify ownership
        conv = conn.execute(
            "SELECT id FROM conversations WHERE id = ? AND user_id = ?",
            (conv_id, current_user["id"]),
        ).fetchone()
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")
        rows = conn.execute(
            "SELECT id, conversation_id, role, content, timestamp FROM messages WHERE conversation_id = ? ORDER BY timestamp ASC",
            (conv_id,),
        ).fetchall()
    return [dict(r) for r in rows]


@app.post("/conversations/{conv_id}/messages", response_model=ConversationMessageOut, status_code=201)
def append_message(conv_id: int, req: AppendMessageRequest, current_user: dict = Depends(get_current_user)):
    with get_auth_conn() as conn:
        # Verify ownership
        conv = conn.execute(
            "SELECT id, title FROM conversations WHERE id = ? AND user_id = ?",
            (conv_id, current_user["id"]),
        ).fetchone()
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")

        cur = conn.execute(
            "INSERT INTO messages (conversation_id, role, content) VALUES (?, ?, ?)",
            (conv_id, req.role, req.content),
        )

        # If this is the first user message, use it as the conversation title (truncated to 60 chars)
        if req.role == "user" and conv["title"] == "New conversation":
            title = req.content[:60]
            conn.execute("UPDATE conversations SET title = ? WHERE id = ?", (title, conv_id))

        conn.commit()
        row = conn.execute(
            "SELECT id, conversation_id, role, content, timestamp FROM messages WHERE id = ?",
            (cur.lastrowid,),
        ).fetchone()
    return dict(row)


# ── Session management endpoints for conversational context ───────────────────

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

    # ── Decide which active_filters to pass to the engine ──
    # If Agent 0 determined this is a brand new question (not a follow-up),
    # we pass empty filters so stale session filters don't contaminate the new query.
    # If it is a follow-up, we pass the full session filters so context is preserved.
    filters_for_engine = state["active_filters"] if resolution.is_follow_up else {}

    # ── Engine: Agent1 + Agent2 ──
    result = nl2sql_service.translate_and_execute(
        question=resolved_q,
        conversation_history=state["chat_history"],
        active_filters=filters_for_engine,
        mode=req.mode,
        row_limit=req.row_limit,
    )

    # ── Update session state ──
    # If new topic: replace active_filters entirely with what Agent1 extracted.
    # If follow-up: merge new filters on top of existing ones (new keys override).
    new_extracted = result.get("plan", {}).get("extracted_filters") or []
    new_filter_dict = {
        f["field"]: f["value"]
        for f in new_extracted
        if isinstance(f, dict) and f.get("field")
    }
    if resolution.is_follow_up:
        merged_filters = {**state["active_filters"], **new_filter_dict}
    else:
        # New topic — start fresh, only keep what this query introduced
        merged_filters = new_filter_dict

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
