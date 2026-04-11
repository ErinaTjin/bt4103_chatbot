#FastAPI application entry point, defining API endpoints
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
    write_auth_log, get_auth_logs,
)
from app.models.api import (
    SQLRequest, SQLResponse, NL2SQLRequest, NL2SQLResponse, ChatRequest, ChatResponse
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

context_agent = ContextAgent()   # initialised once at module level

#An async context manager that runs once when the server starts and once when it shuts down
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

# Global exception handler to catch unhandled exceptions and return JSON error responses instead of crashing the server
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
 
 #Dependency to get current user from the Authorization header; raises 401 if token is invalid or expired
def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)) -> dict:
    user = decode_token(credentials.credentials)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return user

#Dependency to require admin role for certain endpoints; raises 403 if user is not an admin
def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user
 
# ── Health ────────────────────────────────────────────────────────────────────

# A simple health check endpoint to verify the server is running and can connect to DuckDB. 
# Also checks if the NL2SQL engine is initialized and ready to handle requests, which can help catch initialization issues early.
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

# Executes raw SQL directly against DuckDB, bypassing the NL2SQL engine. It is protected by the same authentication 
# and authorization as the other endpoints, and it also enforces the same SQL policy and execution constraints 
# For developers and debugging purposes; not intended for production use or exposed in the frontend UI
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

# Runs only the translation part of the pipeline (Agent 0 + Agent 1 + Agent 2) without executing the SQL against DuckDB. 
# Returns the generated SQL, query plan, and warnings. Used for debugging and evaluating the pipeline — you can see what SQL was 
# generated without running it. Not called by the chat frontend.
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

# Runs the full pipeline including DuckDB execution but without session management or audit logging. 
# This is the stateless version of /nl2sql/chat — it does not load or save session state, does not write to audit_logs, 
# and does not check conversation ownership. Used for testing the pipeline directly. Not called by the chat frontend.
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
# Called by login page and admin user management page in the frontend; not called by the chat interface
# Takes {username, password}, calls authenticate_user() which verifies the password hash against the users table, 
# creates a JWT token containing username and role, and returns it. If credentials are wrong, raises HTTP 401.
@app.post("/auth/login", response_model=TokenResponse)
def login(req: LoginRequest):
    user = authenticate_user(req.username, req.password)
    if not user:
        write_auth_log(event="login", actor=req.username, success=False, detail="Invalid credentials")
        raise HTTPException(status_code=401, detail="Invalid username or password")
    write_auth_log(event="login", actor=user["username"], success=True)
    token = create_access_token(user["username"], user["role"])
    return TokenResponse(access_token=token, username=user["username"], role=user["role"])

# Takes {username, password}, calls register_user() which hashes the password and inserts a new users row with role='user',
# creates a JWT, and returns it. If the username already exists, raises HTTP 409 Conflict.
@app.post("/auth/register", response_model=TokenResponse, status_code=201)
def register(req: RegisterRequest):
    try:
        user = register_user(req.username, req.password)
    except ValueError as e:
        write_auth_log(event="register", actor=req.username, success=False, detail=str(e))
        raise HTTPException(status_code=409, detail=str(e))
    write_auth_log(event="register", actor=user["username"], success=True)
    token = create_access_token(user["username"], user["role"])
    return TokenResponse(access_token=token, username=user["username"], role=user["role"])

# A simple endpoint to return the current user's info based on the JWT token. Used by the frontend to check if the user is 
# logged in and to get their username and role. Requires a valid JWT in the Authorization header.
@app.get("/auth/me")
def me(current_user: dict = Depends(get_current_user)):
    return current_user

# ── Admin user management ─────────────────────────────────────────────────────
# Endpoints for listing users, creating users, deleting users, and updating user roles. 
# All require admin access. Called by the admin user management page in the frontend, not called by the chat interface. 
# These endpoints interact with the users table in the auth database and allow admins to manage user accounts.

@app.get("/admin/users", response_model=list[UserOut])
def admin_list_users(_: dict = Depends(require_admin)):
    return list_users()
 
@app.post("/admin/users", response_model=UserOut, status_code=201)
def admin_create_user(req: CreateUserRequest, current_admin: dict = Depends(require_admin)):
    try:
        new_user = create_user(req.username, req.password, req.role)
        write_auth_log(event="create_user", actor=current_admin["username"], target=req.username, detail=f"role={req.role}")
        return new_user
    except Exception as e:
        write_auth_log(event="create_user", actor=current_admin["username"], target=req.username, success=False, detail=str(e))
        raise HTTPException(status_code=400, detail=f"Could not create user: {e}")

@app.delete("/admin/users/{user_id}", status_code=204)
def admin_delete_user(user_id: int, current_admin: dict = Depends(require_admin)):
    # Fetch username before deleting so we can log it
    with get_auth_conn() as conn:
        row = conn.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()
    target_username = row["username"] if row else str(user_id)
    if not delete_user(user_id):
        raise HTTPException(status_code=404, detail="User not found")
    write_auth_log(event="delete_user", actor=current_admin["username"], target=target_username)

@app.patch("/admin/users/{user_id}/role")
def admin_update_role(user_id: int, req: UpdateRoleRequest, current_admin: dict = Depends(require_admin)):
    with get_auth_conn() as conn:
        row = conn.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()
    target_username = row["username"] if row else str(user_id)
    if not update_user_role(user_id, req.role):
        raise HTTPException(status_code=404, detail="User not found")
    write_auth_log(event="update_role", actor=current_admin["username"], target=target_username, detail=f"role={req.role}")
    return {"ok": True}

# ── Admin audit logs ──────────────────────────────────────────────────────────
# Returns paginated audit log records ordered by timestamp descending. The limit (default 200) and offset (default 0) 
# query parameters support pagination. Admin only. This is what the admin dashboard table and latency chart read from.
@app.get("/admin/logs")
def admin_audit_logs(
    limit: int = 200,
    offset: int = 0,
    _: dict = Depends(require_admin),
):
    """Return paginated NL2SQL query audit log records. Admin only."""
    return get_audit_logs(limit=limit, offset=offset)


@app.get("/admin/auth-logs")
def admin_auth_logs(
    limit: int = 200,
    offset: int = 0,
    _: dict = Depends(require_admin),
):
    """Return paginated auth event log records. Admin only."""
    return get_auth_logs(limit=limit, offset=offset)

# ── Conversations ─────────────────────────────────────────────────────────────
# Returns all conversations belonging to the current user, ordered by created_at DESC (newest first). This is what populates 
# the sidebar when the user logs in. Note it filters strictly by user_id — users cannot see each other's conversations.
@app.get("/conversations", response_model=list[ConversationOut])
def list_conversations(current_user: dict = Depends(get_current_user)):
    with get_auth_conn() as conn:
        rows = conn.execute(
            "SELECT id, title, created_at FROM conversations WHERE user_id = ? ORDER BY created_at DESC",
            (current_user["id"],),
        ).fetchall()
    return [dict(r) for r in rows]
 
# Inserts a new conversation row with title='New conversation' and the current user's user_id. 
# Returns the new conversation's id. Called by the frontend when the user sends their first message in a new chat — 
# the conversation is created lazily on the first send, not when the user clicks "New chat".
@app.post("/conversations", response_model=ConversationCreated, status_code=201)
def create_conversation(current_user: dict = Depends(get_current_user)):
    with get_auth_conn() as conn:
        cur = conn.execute(
            "INSERT INTO conversations (user_id, title) VALUES (?, ?)",
            (current_user["id"], "New conversation"),
        )
        conn.commit()
        return {"id": cur.lastrowid}

# Returns all messages for a conversation in chronological order. First verifies the conversation belongs to the current user — 
# if conv_id does not exist or belongs to a different user, raises HTTP 404. This ownership check prevents users from 
# reading each other's message history by guessing conversation IDs.
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

# Inserts a new message into a conversation. Also verifies ownership. Has one extra behaviour: if the message role is 'user' and 
# the conversation title is still 'New conversation' (i.e. this is the first message), it updates the conversation title to the 
# first 60 characters of the message content. This is how sidebar titles are set automatically.
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
# main endpoint for the chat interface. Takes a question and conversation history, loads session state, resolves follow-ups, 
# translates to SQL, executes, updates session, writes audit log, and returns response in a consistent format 
# regardless of which step failed. This is the core of the NL2SQL chat functionality.
@app.post("/nl2sql/chat", response_model=ChatResponse)
def nl2sql_chat(req: ChatRequest, current_user: dict = Depends(get_current_user)):
    """
    Session is keyed by conversation_id — each conversation has its own isolated NL2SQL state (active_filters, chat_history for Agent 0).
    This prevents different conversations from sharing session memory.
    """
    user_id  = current_user["id"]
    username = current_user["username"]
    conv_id  = req.conversation_id
    t_start  = time.perf_counter()
 
    # Verify the conversation belongs to this user. If not, raises HTTP 404. 
    # This prevents a user from injecting their question into another user's conversation session
    with get_auth_conn() as conn:
        conv = conn.execute(
            "SELECT id FROM conversations WHERE id = ? AND user_id = ?",
            (conv_id, user_id),
        ).fetchone()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
 
    # Load session state scoped to THIS conversation
    # Calls load_session(conv_id) to retrieve the conversation's {chat_history, active_filters, last_sql, warnings} from SQLite. 
    # If no session exists yet for this conversation, returns an empty state.
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
    # Calls context_agent.resolve() with the question, the last 6 messages of chat_history, and the current active_filters. 
    # Returns a ContextResolution with standalone_question, is_follow_up, and needs_clarification
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
        #If needs_clarification=True, writes a clarification audit log entry and returns immediately with the clarification question. 
        # The pipeline stops here — no SQL is generated.
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
    #is_follow_up=True, passes the current active_filters to the engine so they are inherited. 
    # If is_follow_up=False, passes an empty dict so the engine starts fresh with no inherited filters.

    filters_for_engine = state["active_filters"] if resolution.is_follow_up else {}
 
    # ── Engine: Agent1 + Agent2 ──
    # Calls nl2sql_service.translate_and_execute() with the resolved standalone question. 
    # This runs Agent 1, Agent 2, validation, and DuckDB execution. If this raises an unhandled exception, logs it to the audit log 
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
    
    # Audit loggig: elapsed time, determins guardrail decision, row count, warnings, generated SQL, etc.
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
    # Session update and response. Extracts the new filters from Agent 1's output, merges or replaces 
    # active_filters depending on is_follow_up, appends the question and resolved question to chat_history, 
    # trims history to the last 40 messages, saves the updated session back to SQLite, and returns the full response 
    # dict to the frontend
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
# Reset button endpoint: clears the session state for a conversation without deleting the conversation or its messages.
# Verifies ownership then calls reset_session(conv_id) which overwrites the session with an empty state — chat_history=[], 
# active_filters={}, last_sql=None.
# audit logs are unaffected and still link to the conversation, but the session state is cleared so the user can start fresh while still seeing their old messages and audit history.
@app.delete("/session/{conv_id}/reset")
def reset_conv_session(conv_id: int, current_user: dict = Depends(get_current_user)):
    with get_auth_conn() as conn:
        conv = conn.execute(
            "SELECT id FROM conversations WHERE id = ? AND user_id = ?",
            (conv_id, current_user["id"]),
        ).fetchone()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    reset_session(conv_id)
    return {"status": "reset", "conversation_id": conv_id}
 
# Clear filters endpoint: clears only the active_filters in the session state for a conversation, without affecting chat_history or other session fields.
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
 
# Verifies ownership then returns the raw session state dict for a conversation. 
# Used for debugging — the frontend does not call this in normal operation.
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
 
# Hard delete conversation: deletes the conversation row, all its messages, and its session state. 
# Audit logs for queries in this conversation are preserved (user_id kept, conversation link set to NULL via ON DELETE SET NULL). 
# The conversation will disappear from the sidebar immediately.
@app.delete("/conversations/{conv_id}", status_code=204)
def delete_conv(conv_id: int, current_user: dict = Depends(get_current_user)):
    deleted = delete_conversation(conv_id, current_user["id"])
    if not deleted:
        raise HTTPException(status_code=404, detail="Conversation not found")