#api.py
#defines contract of endpoint
#prevents bad input and enforces consistent output shape

from pydantic import BaseModel, Field
from typing import Any

class SQLRequest(BaseModel):
    sql: str
    row_limit: int | None = Field(default=None, ge=1)

class SQLResponse(BaseModel):
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    elapsed_ms: int
    applied_limit: int