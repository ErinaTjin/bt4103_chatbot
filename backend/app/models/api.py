from pydantic import BaseModel, Field
from typing import Any, Literal


class SQLRequest(BaseModel):
    sql: str
    row_limit: int | None = Field(default=None, ge=1)


class SQLResponse(BaseModel):
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    elapsed_ms: int
    applied_limit: int


class NL2SQLRequest(BaseModel):
    question: str
    conversation_history: list[dict[str, Any] | str] | None = None
    active_filters: dict[str, Any] | None = None
    mode: Literal["fast", "strict"] = "fast"
    row_limit: int | None = Field(default=None, ge=1)


class NL2SQLResponse(BaseModel):
    question: str
    sql: str
    plan: dict[str, Any]
    plan_agent1: dict[str, Any] | None = None
    plan_agent2: dict[str, Any] | None = None
    warnings: list[str]
    executed: bool
    data: SQLResponse | None = None

class ChatRequest(BaseModel):
    session_id: str
    question: str
    row_limit: int | None = Field(default=None, ge=1)

class ChatResponse(NL2SQLResponse):
    session_id: str
    resolved_question: str   # what Agent 0 produced
    active_filters: dict[str, Any]
    chat_history: list[dict[str, Any]]