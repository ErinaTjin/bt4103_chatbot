export type UserRole = "admin" | "user";

export interface AuthUser {
  username: string;
  role: UserRole;
  token: string;
}

const BACKEND_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";
const STORAGE_KEY = "auth_user";

export async function login(username: string, password: string): Promise<AuthUser | null> {
  const res = await fetch(`${BACKEND_URL}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });

  if (!res.ok) return null;

  const data = await res.json();
  const user: AuthUser = { username: data.username, role: data.role, token: data.access_token };

  localStorage.setItem(STORAGE_KEY, JSON.stringify(user));
  document.cookie = `auth_user=${encodeURIComponent(JSON.stringify({ username: user.username, role: user.role }))}; path=/`;
  return user;
}

export async function register(username: string, password: string): Promise<{ user: AuthUser | null; error: string | null }> {
  const res = await fetch(`${BACKEND_URL}/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });

  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    return { user: null, error: data.detail ?? "Registration failed" };
  }

  const data = await res.json();
  const user: AuthUser = { username: data.username, role: data.role, token: data.access_token };
  localStorage.setItem(STORAGE_KEY, JSON.stringify(user));
  document.cookie = `auth_user=${encodeURIComponent(JSON.stringify({ username: user.username, role: user.role }))}; path=/`;
  return { user, error: null };
}

export function logout(): void {
  localStorage.removeItem(STORAGE_KEY);
  document.cookie = "auth_user=; path=/; max-age=0";
}

export function getStoredUser(): AuthUser | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as AuthUser) : null;
  } catch {
    return null;
  }
}

export function getAuthHeader(): Record<string, string> {
  const user = getStoredUser();
  return user ? { Authorization: `Bearer ${user.token}` } : {};
}
