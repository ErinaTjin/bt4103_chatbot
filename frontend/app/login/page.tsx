"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { login, register } from "@/lib/auth";
import { useAuth } from "@/context/AuthContext";
import { Shield, User } from "lucide-react";

export default function LoginPage() {
  const router = useRouter();
  const { user, loading, setUser } = useAuth();
  const [tab, setTab] = useState<"login" | "signup">("login");
  const [roleHint, setRoleHint] = useState<"user" | "admin">("user");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!loading && user) router.replace("/chat");
  }, [loading, user, router]);

  const resetForm = () => {
    setUsername("");
    setPassword("");
    setConfirmPassword("");
    setError("");
  };

  const handleTabChange = (t: "login" | "signup") => {
    setTab(t);
    resetForm();
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setSubmitting(true);

    try {
      if (tab === "login") {
        const authUser = await login(username, password);
        if (!authUser) {
          setError(
            roleHint === "admin"
              ? "Invalid admin credentials"
              : "Invalid username or password"
          );
          return;
        }
        // Warn if they selected admin but logged in as user
        if (roleHint === "admin" && authUser.role !== "admin") {
          setError("This account does not have admin access");
          return;
        }
        setUser(authUser);
        router.push("/chat");
      } else {
        if (password !== confirmPassword) {
          setError("Passwords do not match");
          return;
        }
        if (password.length < 6) {
          setError("Password must be at least 6 characters");
          return;
        }
        const { user: newUser, error: regError } = await register(username, password);
        if (regError || !newUser) {
          setError(regError ?? "Registration failed");
          return;
        }
        setUser(newUser);
        router.push("/chat");
      }
    } catch (err) {
      const isTimeout = err instanceof Error && err.name === "AbortError";
      setError(isTimeout ? "Request timed out — is the backend running?" : "Cannot reach server. Please try again.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex items-center justify-center min-h-screen bg-gray-50">
      <div className="w-full max-w-sm bg-white rounded-2xl shadow-sm border border-gray-100 p-8">
        <h1 className="text-xl font-bold text-gray-800 mb-1">ANCHOR</h1>
        <p className="text-xs text-gray-400 mb-6 uppercase tracking-widest">Cancer Analytics</p>

        {/* Sign In / Sign Up tabs */}
        <div className="flex rounded-xl bg-gray-100 p-1 mb-6">
          {(["login", "signup"] as const).map((t) => (
            <button
              key={t}
              onClick={() => handleTabChange(t)}
              className={`flex-1 py-1.5 text-xs font-semibold rounded-lg transition-colors ${
                tab === t
                  ? "bg-white text-gray-800 shadow-sm"
                  : "text-gray-400 hover:text-gray-600"
              }`}
            >
              {t === "login" ? "Sign In" : "Sign Up"}
            </button>
          ))}
        </div>

        {/* Role selector — sign in only */}
        {tab === "login" && (
          <div className="flex gap-3 mb-5">
            <button
              type="button"
              onClick={() => setRoleHint("user")}
              className={`flex-1 flex items-center justify-center gap-2 py-2.5 rounded-xl border text-xs font-semibold transition-all ${
                roleHint === "user"
                  ? "border-blue-500 bg-blue-50 text-blue-600"
                  : "border-gray-200 text-gray-400 hover:border-gray-300"
              }`}
            >
              <User className="w-3.5 h-3.5" />
              User
            </button>
            <button
              type="button"
              onClick={() => setRoleHint("admin")}
              className={`flex-1 flex items-center justify-center gap-2 py-2.5 rounded-xl border text-xs font-semibold transition-all ${
                roleHint === "admin"
                  ? "border-purple-500 bg-purple-50 text-purple-600"
                  : "border-gray-200 text-gray-400 hover:border-gray-300"
              }`}
            >
              <Shield className="w-3.5 h-3.5" />
              Admin
            </button>
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-semibold text-gray-500 uppercase tracking-widest mb-1">
              Username
            </label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full px-4 py-2.5 rounded-xl border border-gray-200 text-sm text-gray-700 outline-none focus:border-blue-400 transition-colors"
              placeholder={roleHint === "admin" ? "Admin username" : "Enter username"}
              autoComplete="username"
              required
            />
          </div>

          <div>
            <label className="block text-xs font-semibold text-gray-500 uppercase tracking-widest mb-1">
              Password
            </label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full px-4 py-2.5 rounded-xl border border-gray-200 text-sm text-gray-700 outline-none focus:border-blue-400 transition-colors"
              placeholder="Enter password"
              autoComplete={tab === "login" ? "current-password" : "new-password"}
              required
            />
          </div>

          {tab === "signup" && (
            <div>
              <label className="block text-xs font-semibold text-gray-500 uppercase tracking-widest mb-1">
                Confirm Password
              </label>
              <input
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                className="w-full px-4 py-2.5 rounded-xl border border-gray-200 text-sm text-gray-700 outline-none focus:border-blue-400 transition-colors"
                placeholder="Re-enter password"
                autoComplete="new-password"
                required
              />
            </div>
          )}

          {tab === "signup" && (
            <p className="text-[10px] text-gray-400">
              New accounts are created with standard user access. Contact an admin to request elevated permissions.
            </p>
          )}

          {error && <p className="text-xs text-red-500">{error}</p>}

          <button
            type="submit"
            disabled={submitting}
            className={`w-full py-2.5 text-white text-sm font-semibold rounded-xl transition-colors disabled:opacity-50 ${
              tab === "login" && roleHint === "admin"
                ? "bg-purple-600 hover:bg-purple-700"
                : "bg-blue-600 hover:bg-blue-700"
            }`}
          >
            {submitting
              ? tab === "login" ? "Signing in..." : "Creating account..."
              : tab === "login" ? "Sign In" : "Create Account"}
          </button>
        </form>
      </div>
    </div>
  );
}
