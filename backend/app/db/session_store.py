# app/db/session_store.py
"""
It owns all reads and writes to the sessions table and survives backend restarts because it writes to a 
file-backed SQLite DB (same nl2sql_runtime.db you already have, or a dedicated sessions.db)
"""

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).parent.parent.parent / "data" / "sessions.db"

_local = threading.local()

def _conn() -> sqlite3.Connection:
    if not hasattr(_local, "con"):
        _local.con = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _local.con.row_factory = sqlite3.Row
    return _local.con

def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = _conn()
    con.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            state      TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL
        )
    """)
    con.commit()

# ---------- public API ----------

def load_session(session_id: str) -> dict[str, Any]:
    row = _conn().execute(
        "SELECT state FROM sessions WHERE session_id = ?", (session_id,)
    ).fetchone()
    if row is None:
        return _empty_state()
    return json.loads(row["state"])

def save_session(session_id: str, state: dict[str, Any]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    _conn().execute(
        """INSERT INTO sessions (session_id, state, updated_at) VALUES (?, ?, ?)
           ON CONFLICT(session_id) DO UPDATE SET state=excluded.state, updated_at=excluded.updated_at""",
        (session_id, json.dumps(state), now),
    )
    _conn().commit()

def reset_session(session_id: str) -> None:
    save_session(session_id, _empty_state())

def clear_filters(session_id: str) -> dict[str, Any]:
    state = load_session(session_id)
    state["active_filters"] = {}
    save_session(session_id, state)
    return state

def _empty_state() -> dict[str, Any]:
    return {
        "chat_history": [],      # list of {role, content} dicts
        "active_filters": {},    # persisted dimension filters
        "last_sql": None,        # last executed SQL string
        "warnings": [],          # warnings from last turn
    }