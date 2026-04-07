import json
import logging
import time
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
from app.db.auth_db import (
    init_db as init_auth_db,
    get_conn as get_auth_conn,
    load_session, save_session, reset_session, clear_filters,
    write_audit_log, get_audit_logs, delete_conversation,
)
from app.models.api import (
    SQLRequest, SQLResponse, NL2SQLRequest, NL2SQLResponse,
)
from app.models.auth import (
    LoginRequest, TokenResponse, UserOut, CreateUserRequest, UpdateRoleRequest,
    RegisterRequest, ConversationOut, ConversationCreated,
    AppendMessageRequest, ConversationMessageOut,
)
from app.services.nl2sql_service import nl2sql_service
from app.services.auth_service import (
    authenticate_user, create_access_token, decode_token,
    list_users, create_user, delete_user, update_user_role, register_user,
)
from nl2sql.core.context_agent import ContextAgent
from app.models.api import ChatRequest, ChatResponse

context_agent = ContextAgent()   # initialised once at module level

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_auth_db()          # create users table + seed defaults
    con = duckdb_manager.connect()
    register_views(con)
    nl2sql_service.initialize()
    yield
    duckdb_manager.close()


app = FastAPI(
    title="ANCHOR NL2SQL + DuckDB Service",
    lifespan=lifespan
)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logging.error(
        "Unhandled exception on %s %s: %s",
        request.method, request.url.path, exc,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    return JSONResponse(status_code=500, content={"detail": str(exc)})

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Auth helpers ──────────────────────────────────────────────────────────────

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
 
# ── Health ────────────────────────────────────────────────────────────────────

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

# ── SQL direct endpoints ──────────────────────────────────────────────────────

@app.post("/sql/execute", response_model=SQLResponse)
def sql_execute(req: SQLRequest, current_user: dict = Depends(get_current_user)):
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
def nl2sql_translate(req: NL2SQLRequest, current_user: dict = Depends(get_current_user)):
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
def nl2sql_execute(req: NL2SQLRequest, current_user: dict = Depends(get_current_user)):
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


# ── Auth endpoints ─────────────────────────────────────────────────────────────────────
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

# ── Admin audit logs ──────────────────────────────────────────────────────────
 
@app.get("/admin/logs")
def admin_audit_logs(
    limit: int = 200,
    offset: int = 0,
    _: dict = Depends(require_admin),
):
    """Return paginated audit log records. Admin only."""
    return get_audit_logs(limit=limit, offset=offset)

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
        if req.role == "user" and conv["title"] == "New conversation":
            conn.execute("UPDATE conversations SET title = ? WHERE id = ?", (req.content[:60], conv_id))
        conn.commit()
        row = conn.execute(
            "SELECT id, conversation_id, role, content, timestamp FROM messages WHERE id = ?",
            (cur.lastrowid,),
        ).fetchone()
    return dict(row)

# ── Session management + NL2SQL chat ─────────────────────────────────────────

"""Implements the /nl2sql/chat endpoint which handles follow-up questions in a conversational manner. It uses a
ContextAgent to resolve follow-up questions into standalone questions, and then passes them to the nl2sql_service for
translation and execution. The session state is loaded at the beginning of the request, updated with the new chat history,
active filters, last executed SQL, and warnings, and then saved back to the database. The endpoint also supports
resetting the session and clearing filters through additional endpoints."""
@app.post("/nl2sql/chat", response_model=ChatResponse)
def nl2sql_chat(req: ChatRequest, current_user: dict = Depends(get_current_user)):
    """
    Session is keyed by conversation_id — each conversation has its own isolated
    NL2SQL state (active_filters, chat_history for Agent 0).
    This prevents different conversations from sharing session memory.
    """
    user_id  = current_user["id"]
    username = current_user["username"]
    conv_id  = req.conversation_id
    t_start  = time.perf_counter()
 
    # Verify the conversation belongs to this user
    with get_auth_conn() as conn:
        conv = conn.execute(
            "SELECT id FROM conversations WHERE id = ? AND user_id = ?",
            (conv_id, user_id),
        ).fetchone()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
 
    # Load session state scoped to THIS conversation
    state = load_session(conv_id)
    request_history = req.conversation_history or []
    session_history = state.get("chat_history", [])
    conversation_history = request_history if request_history else session_history
    pending_clarification = state.get("pending_clarification")
    context_question = req.question
    if isinstance(pending_clarification, dict):
        original_question = str(pending_clarification.get("original_question", "")).strip()
        clarification_question = str(pending_clarification.get("clarification_question", "")).strip()
        if original_question:
            context_question = (
                "Previous question awaiting clarification:\n"
                f"{original_question}\n\n"
                f"Clarification asked: {clarification_question or 'Clarification required.'}\n"
                f"User answer: {req.question}"
            )
 
    # ── Agent 0: resolve follow-up into standalone question ──
    try:
        resolution = context_agent.resolve(
            question=context_question,
            conversation_history=conversation_history,
            active_filters=state["active_filters"],
        )
    except Exception as e:
        logging.error("context_agent.resolve failed: %s", e, exc_info=True)
        raise
 
    if resolution.needs_clarification:
        clarification_message = resolution.clarification_question or "Clarification required."
        write_audit_log(
            user_id=user_id, username=username, session_id=req.session_id,
            nl_question=req.question,
            guardrail_decision="clarification",
            guardrail_reasons=[clarification_message],
        )
        state["chat_history"].append({"role": "user", "content": req.question})
        state["chat_history"].append({"role": "assistant", "content": clarification_message})
        state["chat_history"] = state["chat_history"][-40:]
        state["pending_clarification"] = {
            "original_question": req.question,
            "resolved_question": resolution.standalone_question,
            "clarification_question": clarification_message,
        }
        save_session(conv_id, state)
        return {
            "session_id": req.session_id,
            "question": req.question,
            "resolved_question": resolution.standalone_question,
            "sql": "",
            "plan": {
                "resolved_question": resolution.standalone_question,
                "needs_clarification": True,
                "clarification_question": resolution.clarification_question,
                "active_filters": state["active_filters"],
                "context_summary": resolution.context_summary,
            },
            "plan_agent0": resolution.model_dump(),
            "plan_agent1": None, "plan_agent2": None,
            "warnings": [clarification_message],
            "executed": False, "data": None,
            "active_filters": state["active_filters"],
            "chat_history": state["chat_history"],
        }
 
    resolved_q = resolution.standalone_question
 
    # ── Gate active_filters based on is_follow_up ──
    filters_for_engine = state["active_filters"] if resolution.is_follow_up else {}
 
    # ── Engine: Agent1 + Agent2 ──
    try:
        result = nl2sql_service.translate_and_execute(
            question=resolved_q,
            conversation_history=state["chat_history"],
            active_filters=filters_for_engine,
            mode=req.mode,
            row_limit=req.row_limit,
        )
    except Exception as exc:
        elapsed_ms = int((time.perf_counter() - t_start) * 1000)
        write_audit_log(
            user_id=user_id, username=username, session_id=req.session_id,
            nl_question=req.question, resolved_question=resolved_q,
            execution_ms=elapsed_ms, guardrail_decision="error",
            error_message=str(exc),
        )
        raise
 
    elapsed_ms = int((time.perf_counter() - t_start) * 1000)
    data_obj   = result.get("data") or {}
    rows_list  = data_obj.get("rows") if isinstance(data_obj, dict) else None
    row_count  = data_obj.get("row_count") if isinstance(data_obj, dict) else None
    warnings   = result.get("warnings", [])
    generated_sql = result.get("sql", "")
    executed   = result.get("executed", False)

    error_msg = result.get("error")
    blocking = [w for w in warnings if not w.startswith("Assumption:")]
    if error_msg:
        guardrail_decision = "error"
    elif not executed and blocking:
        guardrail_decision = "block"
    else:
        guardrail_decision = "pass"

    write_audit_log(
        user_id=user_id, username=username, session_id=req.session_id,
        nl_question=req.question, resolved_question=resolved_q,
        generated_sql=generated_sql, execution_ms=elapsed_ms,
        row_count=row_count, guardrail_decision=guardrail_decision,
        guardrail_reasons=blocking if guardrail_decision == "block" else [],
        warnings=warnings, error_message=result.get("error"),
        result_preview=rows_list,
    )
 
    # ── Update session state scoped to this conversation ──
    new_extracted = result.get("plan", {}).get("extracted_filters") or []
    new_filter_dict = {
        f["field"]: f["value"]
        for f in new_extracted
        if isinstance(f, dict) and f.get("field")
    }
    merged_filters = (
        {**state["active_filters"], **new_filter_dict}
        if resolution.is_follow_up else new_filter_dict
    )

    state["pending_clarification"] = None
 
    state["chat_history"].append({"role": "user",      "content": req.question})
    state["chat_history"].append({"role": "assistant",  "content": resolved_q})
    state["last_sql"]       = generated_sql
    state["warnings"]       = warnings
    state["active_filters"] = merged_filters
    state["chat_history"]   = state["chat_history"][-40:]
 
    save_session(conv_id, state)
 
    return {
        **result,
        "session_id": req.session_id,
        "resolved_question": resolved_q,
        "active_filters": merged_filters,
        "chat_history": state["chat_history"],
    }
 
 
# ── Session endpoints (all conversation-scoped) ───────────────────────────────
 
@app.delete("/session/{conv_id}/reset")
def reset_conv_session(conv_id: int, current_user: dict = Depends(get_current_user)):
    """
    Reset NL2SQL session state for a conversation (clears active_filters and
    Agent 0 chat_history). The conversation record and its messages are kept
    so the user can still see them in the sidebar. Audit logs are unaffected.
    """
    with get_auth_conn() as conn:
        conv = conn.execute(
            "SELECT id FROM conversations WHERE id = ? AND user_id = ?",
            (conv_id, current_user["id"]),
        ).fetchone()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    reset_session(conv_id)
    return {"status": "reset", "conversation_id": conv_id}
 
 
@app.patch("/session/{conv_id}/filters")
def clear_conv_filters(conv_id: int, current_user: dict = Depends(get_current_user)):
    """Clear active filters for a conversation without touching chat history."""
    with get_auth_conn() as conn:
        conv = conn.execute(
            "SELECT id FROM conversations WHERE id = ? AND user_id = ?",
            (conv_id, current_user["id"]),
        ).fetchone()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    state = clear_filters(conv_id)
    return {"status": "filters_cleared", "active_filters": state["active_filters"]}
 
 
@app.get("/session/{conv_id}")
def get_conv_session(conv_id: int, current_user: dict = Depends(get_current_user)):
    """Return session state for a conversation."""
    with get_auth_conn() as conn:
        conv = conn.execute(
            "SELECT id FROM conversations WHERE id = ? AND user_id = ?",
            (conv_id, current_user["id"]),
        ).fetchone()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return load_session(conv_id)
 
 
@app.delete("/conversations/{conv_id}", status_code=204)
def delete_conv(conv_id: int, current_user: dict = Depends(get_current_user)):
    """
    Hard-delete a conversation, all its messages, and its session state.
    Audit logs for queries in this conversation are preserved (user_id kept,
    conversation link set to NULL via ON DELETE SET NULL).
    The conversation will disappear from the sidebar immediately.
    """
    deleted = delete_conversation(conv_id, current_user["id"])
    if not deleted:
        raise HTTPException(status_code=404, detail="Conversation not found")