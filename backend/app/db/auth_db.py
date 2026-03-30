"""
Single SQLite database for all user-related data and session state, replacing the previous sessions.db. This simplifies 
data management and ensures session persistence across backend restarts. The schema includes:
- users         : accounts + roles
- conversations : per-user chat history
- messages      : individual chat messages
- sessions      : NL2SQL session state (active_filters, last_sql, etc.)
- audit_logs    : one record per query for admin auditing
"""
import sqlite3
import os
from pathlib import Path

# Store auth DB next to the existing runtime DB
DB_PATH = Path(__file__).parent.parent.parent / "data" / "auth.db"

def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create all tables and seed default accounts if empty."""
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                username      TEXT    NOT NULL UNIQUE,
                password_hash TEXT    NOT NULL,
                role          TEXT    NOT NULL DEFAULT 'user',
                created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                title      TEXT    NOT NULL DEFAULT 'New conversation',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                role            TEXT    NOT NULL CHECK(role IN ('user', 'assistant')),
                content         TEXT    NOT NULL,
                timestamp       DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Sessions keyed by user_id so they survive backend restarts
        # and persist per-user across logins (until explicit reset)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                user_id    INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                state      TEXT    NOT NULL DEFAULT '{}',
                updated_at TEXT    NOT NULL
            )
        """)
        # Audit log — one row per query attempt
        conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp        DATETIME DEFAULT CURRENT_TIMESTAMP,
                user_id          INTEGER  REFERENCES users(id) ON DELETE SET NULL,
                username         TEXT,
                session_id       TEXT,
                nl_question      TEXT,
                resolved_question TEXT,
                generated_sql    TEXT,
                execution_ms     INTEGER,
                row_count        INTEGER,
                guardrail_decision TEXT NOT NULL DEFAULT 'pass',
                guardrail_reasons  TEXT,
                warnings         TEXT,
                error_message    TEXT
            )
        """)
        conn.commit()

    # Seed default accounts if no users exist
    from app.services.auth_service import hash_password
    with get_conn() as conn:
        count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if count == 0:
            conn.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                ("admin", hash_password("admin123"), "admin"),
            )
            conn.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                ("user", hash_password("user123"), "user"),
            )
            conn.commit()

# ── Session functions (moved from session_store.py) ──────────────────────────
 
import json
from datetime import datetime, timezone
from typing import Any
 
def _empty_state() -> dict[str, Any]:
    return {
        "chat_history": [],
        "active_filters": {},
        "last_sql": None,
        "warnings": [],
    }
 
 
def load_session(user_id: int) -> dict[str, Any]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT state FROM sessions WHERE user_id = ?", (user_id,)
        ).fetchone()
    if row is None:
        return _empty_state()
    return json.loads(row["state"])
 
 
def save_session(user_id: int, state: dict[str, Any]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO sessions (user_id, state, updated_at) VALUES (?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET state=excluded.state, updated_at=excluded.updated_at""",
            (user_id, json.dumps(state), now),
        )
        conn.commit()
 
 
def reset_session(user_id: int) -> None:
    save_session(user_id, _empty_state())
 
 
def clear_filters(user_id: int) -> dict[str, Any]:
    state = load_session(user_id)
    state["active_filters"] = {}
    save_session(user_id, state)
    return state
 
# ── Audit log functions ───────────────────────────────────────────────────────
 
def write_audit_log(
    user_id: int | None,
    username: str | None,
    session_id: str | None,
    nl_question: str,
    resolved_question: str | None = None,
    generated_sql: str | None = None,
    execution_ms: int | None = None,
    row_count: int | None = None,
    guardrail_decision: str = "pass",
    guardrail_reasons: list[str] | None = None,
    warnings: list[str] | None = None,
    error_message: str | None = None,
) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO audit_logs (
                user_id, username, session_id, nl_question, resolved_question,
                generated_sql, execution_ms, row_count,
                guardrail_decision, guardrail_reasons, warnings, error_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                user_id,
                username,
                session_id,
                nl_question,
                resolved_question,
                generated_sql,
                execution_ms,
                row_count,
                guardrail_decision,
                json.dumps(guardrail_reasons or []),
                json.dumps(warnings or []),
                error_message,
            ),
        )
        conn.commit()
 
def get_audit_logs(limit: int = 200, offset: int = 0) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT id, timestamp, username, session_id, nl_question,
                      resolved_question, generated_sql, execution_ms, row_count,
                      guardrail_decision, guardrail_reasons, warnings, error_message
               FROM audit_logs
               ORDER BY timestamp DESC
               LIMIT ? OFFSET ?""",
            (limit, offset),
        ).fetchall()
    return [dict(r) for r in rows]