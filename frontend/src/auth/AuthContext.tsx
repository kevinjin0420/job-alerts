import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { apiRequest, clearSession, readAccessToken, setUnauthorizedHandler, storeSession } from "../api/client";
import { isNewPasswordChallenge, type LoginResponse } from "../api/types";

interface LoginCredentials {
  email: string;
  password: string;
}

interface NewPasswordSubmission {
  email: string;
  newPassword: string;
  session: string;
}

interface AuthContextValue {
  isAuthenticated: boolean;
  /** Non-null while Cognito is mid NEW_PASSWORD_REQUIRED challenge for a first-time login. */
  pendingSession: string | null;
  signIn: (credentials: LoginCredentials) => Promise<void>;
  completeNewPassword: (submission: NewPasswordSubmission) => Promise<void>;
  signOut: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [accessToken, setAccessToken] = useState<string | null>(() => readAccessToken());
  const [pendingSession, setPendingSession] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const signOut = useCallback(() => {
    clearSession();
    setAccessToken(null);
    setPendingSession(null);
    queryClient.clear();
  }, [queryClient]);

  useEffect(() => {
    setUnauthorizedHandler(signOut);
    return () => setUnauthorizedHandler(null);
  }, [signOut]);

  // A sign-in or sign-out in another tab should not leave this one out of sync.
  useEffect(() => {
    const syncFromStorage = () => setAccessToken(readAccessToken());
    window.addEventListener("storage", syncFromStorage);
    return () => window.removeEventListener("storage", syncFromStorage);
  }, []);

  const applyLoginResponse = useCallback((response: LoginResponse) => {
    if (isNewPasswordChallenge(response)) {
      setPendingSession(response.session);
      return;
    }
    storeSession(response);
    setAccessToken(response.access_token);
    setPendingSession(null);
  }, []);

  const signIn = useCallback(
    async ({ email, password }: LoginCredentials) => {
      const response = await apiRequest<LoginResponse>("/api/login", {
        method: "POST",
        body: { email, password },
        skipAuth: true,
      });
      applyLoginResponse(response);
    },
    [applyLoginResponse],
  );

  const completeNewPassword = useCallback(
    async ({ email, newPassword, session }: NewPasswordSubmission) => {
      const response = await apiRequest<LoginResponse>("/api/login", {
        method: "POST",
        body: { email, new_password: newPassword, session },
        skipAuth: true,
      });
      applyLoginResponse(response);
    },
    [applyLoginResponse],
  );

  const value = useMemo<AuthContextValue>(
    () => ({ isAuthenticated: accessToken !== null, pendingSession, signIn, completeNewPassword, signOut }),
    [accessToken, pendingSession, signIn, completeNewPassword, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (context === null) {
    throw new Error("useAuth must be used inside AuthProvider");
  }
  return context;
}
