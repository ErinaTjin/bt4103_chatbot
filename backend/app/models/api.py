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