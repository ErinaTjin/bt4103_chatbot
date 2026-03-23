# app/db/session_store.py
"""
Manages the SQLite table called 'sessions' (uses the same nl2sql_runtime.db you already have, or a dedicated sessions.db)
File backed, meaning the session data is saved on disk and survives restarts.
Each row is one session
The 'sessions' table has the following columns:
- session_id (TEXT PRIMARY KEY): unique identifier for each session
- state (TEXT NOT NULL): JSON-encoded string representing the session state (chat history, filters, etc.)
- updated_at (TEXT NOT NULL): timestamp of the last update to the session, stored as an ISO 8601 string in UTC timezone
The session state is a JSON object with the following structure:
{
    "chat_history": [  # list of chat messages in the session
        {"role": "user", "content": "What is the total number of patients?"},  # example user message
        {"role": "user", "content": "SELECT COUNT(*) FROM patients;"}  # example assistant response
    ],
    "active_filters": {  # dictionary of active filters applied to the data
        "country": ["USA", "Canada"],  # example filter on the 'country' dimension
        "year": ["2020"]  # example filter on the 'year' dimension
    },
    "last_sql": "SELECT COUNT(*) FROM patients;",  # last executed SQL query
    "warnings": []  # list of warnings from the last turn, if any
}

"""

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# path to sessions.db file
DB_PATH = Path(__file__).parent.parent.parent / "data" / "sessions.db"

_local = threading.local()

"""
returns the SQLite connection for the current thread, creating it if it doesn't exist yet. The connection is stored in 
thread-local storage to ensure that each thread has its own connection, since SQLite connections are not thread-safe. 
The connection is configured to return rows as dictionaries (sqlite3.Row) for easier access to column values by name.
"""
def _conn() -> sqlite3.Connection:
    if not hasattr(_local, "con"):
        _local.con = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _local.con.row_factory = sqlite3.Row
    return _local.con

"""Initializes the database by creating the 'sessions' table if it doesn't already exist."""
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

# ---------- public API (for use by the rest of the application)----------

"""Loads the session state for the given session_id from the database. If no session exists, returns an empty state.
Takes session_id as input and returns a dictionary representing the session state, which includes chat history, active filters, 
last executed SQL, and warnings."""
def load_session(session_id: str) -> dict[str, Any]:
    row = _conn().execute(
        "SELECT state FROM sessions WHERE session_id = ?", (session_id,)
    ).fetchone()
    if row is None:
        return _empty_state()
    return json.loads(row["state"])

"""Saves the given session state to the database for the specified session_id. If a session with the same session_id already exists, 
it updates the existing record; otherwise, it inserts a new record. The session state is stored as a JSON-encoded string, 
and the updated_at timestamp is set to the current time in UTC."""
def save_session(session_id: str, state: dict[str, Any]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    _conn().execute(
        """INSERT INTO sessions (session_id, state, updated_at) VALUES (?, ?, ?)
           ON CONFLICT(session_id) DO UPDATE SET state=excluded.state, updated_at=excluded.updated_at""",
        (session_id, json.dumps(state), now),
    )
    _conn().commit()

"""Deletes the session with the specified session_id from the database. If no such session exists, the function does nothing."""
def reset_session(session_id: str) -> None:
    save_session(session_id, _empty_state())

"""Clears only the active filters from the session state for the given session_id, while preserving the chat history and 
other state information."""
def clear_filters(session_id: str) -> dict[str, Any]:
    state = load_session(session_id)
    state["active_filters"] = {}
    save_session(session_id, state)
    return state

"""Helper function that returns an empty session state dictionary with the default structure, including an empty chat history,"""
def _empty_state() -> dict[str, Any]:
    return {
        "chat_history": [],      # list of {role, content} dicts
        "active_filters": {},    # persisted dimension filters
        "last_sql": None,        # last executed SQL string
        "warnings": [],          # warnings from last turn
    }