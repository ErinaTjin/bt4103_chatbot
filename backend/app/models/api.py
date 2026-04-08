#Pydantic request and response models that define the API contract
# SQL, NL2SQL, and Chat request/response models
from pydantic import BaseModel, Field
from typing import Any, Literal

#request model for a direct SQL execution endpoint
class SQLRequest(BaseModel):
    sql: str
    row_limit: int | None = Field(default=None, ge=1)

#response model for SQL execution results
class SQLResponse(BaseModel):
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    elapsed_ms: int
    applied_limit: int

#Request models for NL2SQL pipeline
class NL2SQLRequest(BaseModel):
    question: str
    conversation_history: list[dict[str, Any] | str] | None = None
    active_filters: dict[str, Any] | None = None
    mode: Literal["fast", "strict"] = "fast"
    row_limit: int | None = Field(default=None, ge=1)

#Response model for NL2SQL pipeline
class NL2SQLResponse(BaseModel):
    question: str
    sql: str
    plan: dict[str, Any]
    plan_agent0: dict[str, Any] | None = None
    plan_agent1: dict[str, Any] | None = None
    plan_agent2: dict[str, Any] | None = None
    warnings: list[str]
    executed: bool
    data: SQLResponse | None = None

#Chat endpoint models, extending NL2SQL with session and conversation context
class ChatRequest(BaseModel):
    session_id: str           # frontend UUID, used for audit log tracing only
    conversation_id: int      # DB conversation_id — keys the session state
    question: str
    mode: Literal["fast", "strict"] = "fast"
    row_limit: int | None = Field(default=None, ge=1)
 
class ChatResponse(NL2SQLResponse): #extends NL2SQLResponse with session_id, resolved_question, active_filters, chat_history
    session_id: str
    resolved_question: str 
    active_filters: dict[str, Any]
    chat_history: list[dict[str, Any]]