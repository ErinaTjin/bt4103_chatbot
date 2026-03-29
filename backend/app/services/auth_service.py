import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.db.auth_db import get_conn

SECRET_KEY = os.getenv("AUTH_SECRET_KEY", "change-me-in-production-use-env-var")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 8  # 8 hours

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def get_user(username: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, username, password_hash, role FROM users WHERE username = ?",
            (username.lower(),),
        ).fetchone()
    return dict(row) if row else None


def authenticate_user(username: str, password: str) -> Optional[dict]:
    user = get_user(username)
    if not user or not verify_password(password, user["password_hash"]):
        return None
    return user


def create_access_token(username: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    # Embed user id in token for use in conversation endpoints
    user = get_user(username)
    uid = user["id"] if user else None
    return jwt.encode(
        {"sub": username, "role": role, "uid": uid, "exp": expire},
        SECRET_KEY,
        algorithm=ALGORITHM,
    )


def decode_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        uid = payload.get("uid")
        if uid is None:
            # Fallback for tokens minted before uid was added to the payload
            user = get_user(payload["sub"])
            uid = user["id"] if user else None
        return {"username": payload["sub"], "role": payload["role"], "id": uid}
    except JWTError:
        return None


# ── Admin user management ────────────────────────────────────────────────────

def list_users() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, username, role, created_at FROM users ORDER BY id"
        ).fetchall()
    return [dict(r) for r in rows]


def register_user(username: str, password: str) -> dict:
    """Public self-registration — always creates a 'user' role account."""
    if get_user(username):
        raise ValueError(f"Username '{username}' is already taken.")
    return create_user(username, password, role="user")


def create_user(username: str, password: str, role: str = "user") -> dict:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
            (username.lower(), hash_password(password), role),
        )
        conn.commit()
        row = conn.execute(
            "SELECT id, username, role, created_at FROM users WHERE username = ?",
            (username.lower(),),
        ).fetchone()
    return dict(row)


def delete_user(user_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
    return cur.rowcount > 0


def update_user_role(user_id: int, role: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE users SET role = ? WHERE id = ?", (role, user_id)
        )
        conn.commit()
    return cur.rowcount > 0
