#sql_guard.py

import re

DISALLOWED_KEYWORDS = [
    "insert", "update", "delete", "create", "drop", "alter", "truncate",
    "copy", "attach", "detach", "pragma", "call", "execute",
]

def ensure_select_only(sql: str) -> str:
    s = sql.strip().strip(";")
    lowered = s.lower()

    # Only allow SELECT or WITH ... SELECT
    if not (lowered.startswith("select") or lowered.startswith("with")):
        raise ValueError("Only SELECT queries are allowed.")

    # Prevent multiple statements: "SELECT ...; DROP TABLE ..."
    if ";" in s:
        raise ValueError("Multiple SQL statements are not allowed.")

    for kw in DISALLOWED_KEYWORDS:
        if re.search(rf"\b{kw}\b", lowered):
            raise ValueError(f"Disallowed SQL keyword: {kw}")

    return s