#!/usr/bin/env python3
"""Lightweight checks for guardrail analytics aggregation functions."""

import json
import sqlite3
import tempfile
from pathlib import Path

from app.db import auth_db


def _seed(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            username TEXT,
            guardrail_decision TEXT,
            guardrail_reasons TEXT
        )
        """
    )
    rows = [
        ("2026-03-30 10:00:00", "alice", "block", json.dumps(["PHI_BLOCKED_COLUMN"])),
        ("2026-03-30 11:00:00", "alice", "block", json.dumps(["VALUE_WHITELIST_BLOCK"])),
        ("2026-03-30 12:00:00", "bob", "block", json.dumps(["PHI_BLOCKED_COLUMN"])),
        ("2026-03-31 09:00:00", "bob", "pass", json.dumps([])),
        ("2026-03-31 10:00:00", "carol", "block", json.dumps(["PHI_BLOCKED_COLUMN", "VALUE_WHITELIST_BLOCK"])),
        ("2026-03-31 11:00:00", "carol", "block", None),
    ]
    conn.executemany(
        "INSERT INTO audit_logs (timestamp, username, guardrail_decision, guardrail_reasons) VALUES (?, ?, ?, ?)",
        rows,
    )
    conn.commit()


def run_test() -> int:
    original_db_path = auth_db.DB_PATH

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            test_db = Path(tmpdir) / "auth_test.db"
            auth_db.DB_PATH = test_db

            with auth_db.get_conn() as conn:
                _seed(conn)

            by_code = auth_db.get_guardrail_code_distribution(days=3650)
            by_code_map = {item["guardrail_code"]: item["blocked_count"] for item in by_code}
            assert by_code_map.get("PHI_BLOCKED_COLUMN") == 3, by_code_map
            assert by_code_map.get("VALUE_WHITELIST_BLOCK") == 2, by_code_map
            assert by_code_map.get("UNKNOWN_BLOCK_REASON") == 1, by_code_map

            daily = auth_db.get_guardrail_daily_trend(days=3650)
            daily_map = {(item["day"], item["guardrail_code"]): item["blocked_count"] for item in daily}
            assert daily_map.get(("2026-03-30", "PHI_BLOCKED_COLUMN")) == 2, daily_map
            assert daily_map.get(("2026-03-31", "UNKNOWN_BLOCK_REASON")) == 1, daily_map

            by_user = auth_db.get_guardrail_user_distribution(days=3650)
            user_map = {(item["username"], item["guardrail_code"]): item["blocked_count"] for item in by_user}
            assert user_map.get(("alice", "PHI_BLOCKED_COLUMN")) == 1, user_map
            assert user_map.get(("carol", "UNKNOWN_BLOCK_REASON")) == 1, user_map
    finally:
        auth_db.DB_PATH = original_db_path

    print("guardrail analytics tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_test())
