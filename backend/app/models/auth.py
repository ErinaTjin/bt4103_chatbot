from pydantic import BaseModel
from typing import Literal, Optional


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    role: Literal["admin", "user"]


class UserOut(BaseModel):
    id: int
    username: str
    role: str
    created_at: str


class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: Literal["admin", "user"] = "user"


class UpdateRoleRequest(BaseModel):
    role: Literal["admin", "user"]


class RegisterRequest(BaseModel):
    username: str
    password: str


# ── Conversation / message models ────────────────────────────────────────────

class ConversationOut(BaseModel):
    id: int
    title: str
    created_at: str


class ConversationCreated(BaseModel):
    id: int


class AppendMessageRequest(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ConversationMessageOut(BaseModel):
    id: int
    conversation_id: int
    role: str
    content: str
    timestamp: str
