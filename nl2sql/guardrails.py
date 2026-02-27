import re


BANNED_KEYWORDS = [
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "ALTER",
    "CREATE",
    "TRUNCATE",
]

BANNED_IDENTIFIERS = [
    "patient_id",
    "mrn",
    "ssn",
]


def check_sql(sql: str) -> dict:
    warnings = []
    normalized = sql.strip().upper()

    if not normalized.startswith("SELECT"):
        warnings.append("SQL must start with SELECT")

    if "LIMIT" not in normalized:
        warnings.append("SQL must contain LIMIT")

    if not ("COUNT(" in normalized or "GROUP BY" in normalized):
        warnings.append("SQL must aggregate (COUNT or GROUP BY)")

    for kw in BANNED_KEYWORDS:
        if re.search(rf"\b{kw}\b", normalized):
            warnings.append(f"Disallowed keyword: {kw}")

    for col in BANNED_IDENTIFIERS:
        if re.search(rf"\b{col.upper()}\b", normalized):
            warnings.append(f"Disallowed identifier: {col}")

    return {"ok": len(warnings) == 0, "warnings": warnings}
