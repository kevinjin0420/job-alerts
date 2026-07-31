import { useState, type FormEvent } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { useAuth } from "./AuthContext";

interface RedirectState {
  from?: string;
}

export function LoginPage() {
  const { isAuthenticated, pendingSession, signIn, completeNewPassword } = useAuth();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  if (isAuthenticated) {
    const state = location.state as RedirectState | null;
    return <Navigate to={state?.from ?? "/listings"} replace />;
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setIsSubmitting(true);
    try {
      if (pendingSession) {
        await completeNewPassword({ email, newPassword, session: pendingSession });
      } else {
        await signIn({ email, password });
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Login failed");
    } finally {
      setIsSubmitting(false);
    }
  };

  const inputClass =
    "mt-3 w-full rounded-none border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-neutral-500";

  return (
    <div className="min-h-dvh flex items-center justify-center p-6">
      <form
        onSubmit={submit}
        className="w-full max-w-sm rounded-none border border-neutral-300 dark:border-neutral-800 bg-white dark:bg-neutral-900 p-6"
      >
        <h1 className="text-sm font-semibold tracking-wide uppercase text-center">job-alerts</h1>
        <p className="mt-1 text-sm text-neutral-500 dark:text-neutral-500 text-center">Sign in to continue</p>

        {pendingSession && !error && (
          <div className="mt-3 text-sm text-neutral-600 dark:text-neutral-400">
            First login - please set a new password
          </div>
        )}
        {error && <div className="mt-3 text-sm text-red-600 dark:text-red-400">{error}</div>}

        <input
          type="email"
          autoComplete="username"
          placeholder="Email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          className={inputClass}
        />
        {pendingSession ? (
          <input
            type="password"
            autoComplete="new-password"
            placeholder="New password"
            value={newPassword}
            onChange={(event) => setNewPassword(event.target.value)}
            className={inputClass}
          />
        ) : (
          <input
            type="password"
            autoComplete="current-password"
            placeholder="Password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            className={inputClass}
          />
        )}

        <button
          type="submit"
          disabled={isSubmitting}
          className="mt-3 w-full rounded-none bg-neutral-900 hover:opacity-50 disabled:opacity-40 dark:bg-neutral-100 text-white dark:text-neutral-900 text-sm font-medium px-3 py-1.5"
        >
          {isSubmitting ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
