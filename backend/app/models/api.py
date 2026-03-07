#api.py
#defines api contract (input and output type)

from pydantic import BaseModel, Field
from typing import Any

# Pydantic model that define request schema
class SQLRequest(BaseModel):
    sql: str
    row_limit: int | None = Field(default=None, ge=1)

# Pydantic model that define response schema
class SQLResponse(BaseModel):
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    elapsed_ms: int
    applied_limit: int

class NL2SQLRequest(BaseModel):
    question: str
    active_filters: dict[str, Any] | None = None
    row_limit: int | None = Field(default=None, ge=1)


class NL2SQLResponse(BaseModel):
    question: str
    sql: str
    plan: dict[str, Any]
    warnings: list[str]
    executed: bool
    data: SQLResponse | None = None