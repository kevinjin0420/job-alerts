const ACCESS_TOKEN_KEY = "job-alerts-access-token";
const REFRESH_TOKEN_KEY = "job-alerts-refresh-token";
const EXPIRES_AT_KEY = "job-alerts-token-expires-at";

// Refresh a minute early so a request cannot land on a token that expires in flight.
const EXPIRY_SKEW_MS = 60 * 1000;

export interface SessionTokens {
  access_token: string;
  expires_in: number;
  /** Absent on a refresh response - Cognito reissues only the access token. */
  refresh_token?: string;
}

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/** Set by AuthProvider so an unrecoverable 401 clears the session, without
 * threading context through every call site. */
let unauthorizedHandler: (() => void) | null = null;

export function setUnauthorizedHandler(handler: (() => void) | null): void {
  unauthorizedHandler = handler;
}

export function readAccessToken(): string | null {
  return localStorage.getItem(ACCESS_TOKEN_KEY);
}

function readRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_TOKEN_KEY);
}

function readExpiresAt(): number | null {
  const raw = localStorage.getItem(EXPIRES_AT_KEY);
  if (raw === null) {
    return null;
  }
  const parsed = Number(raw);
  return Number.isFinite(parsed) ? parsed : null;
}

export function storeSession(tokens: SessionTokens): void {
  localStorage.setItem(ACCESS_TOKEN_KEY, tokens.access_token);
  localStorage.setItem(EXPIRES_AT_KEY, String(Date.now() + tokens.expires_in * 1000));
  if (tokens.refresh_token) {
    localStorage.setItem(REFRESH_TOKEN_KEY, tokens.refresh_token);
  }
}

export function clearSession(): void {
  localStorage.removeItem(ACCESS_TOKEN_KEY);
  localStorage.removeItem(REFRESH_TOKEN_KEY);
  localStorage.removeItem(EXPIRES_AT_KEY);
}

let refreshInFlight: Promise<string | null> | null = null;

async function performRefresh(): Promise<string | null> {
  const refreshToken = readRefreshToken();
  if (refreshToken === null) {
    return null;
  }
  try {
    const response = await fetch("/api/refresh", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
    if (!response.ok) {
      return null;
    }
    const tokens = (await response.json()) as SessionTokens;
    storeSession(tokens);
    return tokens.access_token;
  } catch {
    return null;
  }
}

/** Collapses parallel refreshes into one call - every query firing at once on a
 * stale token would otherwise each POST /api/refresh. */
function refreshAccessToken(): Promise<string | null> {
  refreshInFlight ??= performRefresh().finally(() => {
    refreshInFlight = null;
  });
  return refreshInFlight;
}

async function authorizationToken(): Promise<string | null> {
  const accessToken = readAccessToken();
  if (accessToken === null) {
    return null;
  }
  const expiresAt = readExpiresAt();
  // A session stored before refresh support has no recorded expiry - use it until it 401s.
  if (expiresAt === null || Date.now() < expiresAt - EXPIRY_SKEW_MS) {
    return accessToken;
  }
  return (await refreshAccessToken()) ?? accessToken;
}

async function errorMessageFrom(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    if (typeof body === "object" && body !== null && "error" in body) {
      const { error } = body as { error: unknown };
      if (typeof error === "string") {
        return error;
      }
    }
  } catch {
    // non-JSON error body, fall through to the status text below
  }
  return `${response.status} ${response.statusText}`;
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  /** Login is the one endpoint that must not send (or clear) a bearer token. */
  skipAuth?: boolean;
}

async function sendRequest<T>(path: string, options: RequestOptions, allowRefreshRetry: boolean): Promise<T> {
  const { method = "GET", body, skipAuth = false } = options;
  const headers: Record<string, string> = {};
  if (body !== undefined) {
    headers["content-type"] = "application/json";
  }
  if (!skipAuth) {
    const token = await authorizationToken();
    if (token !== null) {
      headers["authorization"] = `Bearer ${token}`;
    }
  }

  const response = await fetch(path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  if (response.status === 401 && !skipAuth) {
    // The server rejected this token outright, so a refresh is the only thing
    // that can save the session - one attempt, then sign out for real.
    if (allowRefreshRetry && (await refreshAccessToken()) !== null) {
      return sendRequest<T>(path, options, false);
    }
    clearSession();
    unauthorizedHandler?.();
    throw new ApiError(401, "unauthorized");
  }
  if (!response.ok) {
    throw new ApiError(response.status, await errorMessageFrom(response));
  }
  return (await response.json()) as T;
}

export function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  return sendRequest<T>(path, options, true);
}
