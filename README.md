# How to Create an Admin User

This guide walks you through everything you need to know about admin accounts in this project — from the default seeded credentials to creating new admins and promoting existing users. No deep codebase knowledge required.

---

## 1. The Default Seeded Admin Account

When the backend starts up for the first time, it automatically creates two default accounts if the `users` table is empty:

| Username | Password   | Role  |
|----------|------------|-------|
| `admin`  | `admin123` | admin |
| `user`   | `user123`  | user  |

> **When does this run?** Every time the FastAPI server starts (`uvicorn`), but the seed only inserts rows if the table is completely empty. If users already exist, seeding is skipped.

---

## 2. Log In as Admin and Get a Token

Use the `POST /auth/login` endpoint. It returns a JWT bearer token valid for **8 hours**.

```bash
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "admin123"}'
```

**Example response:**

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "username": "admin",
  "role": "admin"
}
```

Copy the value of `access_token` — you will need it for all admin operations below.

---

## 3. Create a New Admin User

Use the `POST /admin/users` endpoint. This requires a valid admin token in the `Authorization` header.

```bash
curl -X POST http://localhost:8000/admin/users \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <YOUR_ADMIN_TOKEN>" \
  -d '{"username": "newadmin", "password": "securepassword", "role": "admin"}'
```

Replace `<YOUR_ADMIN_TOKEN>` with the `access_token` from Step 2.

**Example response:**

```json
{
  "id": 3,
  "username": "newadmin",
  "role": "admin",
  "created_at": "2026-03-28 10:00:00"
}
```

> The `role` field accepts either `"admin"` or `"user"`. If you omit it, it defaults to `"user"`.

---

## 4. Promote an Existing User to Admin

If a regular user already exists and you want to elevate their role, use `PATCH /admin/users/{id}/role`.

**Step 4a — Look up the user's ID:**

```bash
curl http://localhost:8000/admin/users \
  -H "Authorization: Bearer <YOUR_ADMIN_TOKEN>"
```

**Step 4b — Promote the user:**

```bash
curl -X PATCH http://localhost:8000/admin/users/2/role \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <YOUR_ADMIN_TOKEN>" \
  -d '{"role": "admin"}'
```

Replace `2` with the actual user ID. On success:

```json
{"ok": true}
```

> You can also demote an admin back to a regular user by passing `"role": "user"`.

---

## 5. Why `/auth/register` Cannot Create Admins

The public registration endpoint (`POST /auth/register`) is intentionally locked to the `"user"` role:

```python
def register_user(username: str, password: str) -> dict:
    """Public self-registration — always creates a 'user' role account."""
    return create_user(username, password, role="user")  # role is fixed here
```

Even if you try to pass a `role` field, the `RegisterRequest` model only accepts `username` and `password`. **Admin creation is exclusively available through `POST /admin/users`**, which requires an existing admin JWT.

---

## 6. One-Liner: Login + Create Admin in One Shot

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "admin123"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

curl -X POST http://localhost:8000/admin/users \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"username": "newadmin", "password": "securepassword", "role": "admin"}'
```

---

## 7. Production Security Notes

### Change the Default Admin Password
The default `admin` / `admin123` credentials are for development only. Rotate them before any shared or production deployment.

### Set the `AUTH_SECRET_KEY` Environment Variable

```python
SECRET_KEY = os.getenv("AUTH_SECRET_KEY", "change-me-in-production-use-env-var")
```

The fallback is a hardcoded string visible in source code — anyone can forge tokens with it. Set a strong secret before deploying:

```bash
# In backend/.env
AUTH_SECRET_KEY=your-random-256-bit-secret-here

# Generate one with:
python -c "import secrets; print(secrets.token_hex(32))"
```
