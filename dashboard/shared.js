const TOKEN_STORAGE = "job-alerts-access-token";
let pendingSession = null;

function token() {
  return localStorage.getItem(TOKEN_STORAGE) || "";
}

async function apiFetch(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { ...(options.headers || {}), "Authorization": `Bearer ${token()}` },
  });
  if (response.status === 401) {
    localStorage.removeItem(TOKEN_STORAGE);
    showGate();
    throw new Error("unauthorized");
  }
  return response;
}

function showGate() {
  document.getElementById("gate").classList.remove("hidden");
  document.getElementById("app").classList.add("hidden");
}

function showAppShell() {
  document.getElementById("gate").classList.add("hidden");
  document.getElementById("app").classList.remove("hidden");
}

function revealAdminNav(isAdmin) {
  document.getElementById("admin-nav-link").classList.toggle("hidden", !isAdmin);
  document.getElementById("logs-nav-link").classList.toggle("hidden", !isAdmin);
  document.getElementById("sources-nav-link").classList.toggle("hidden", !isAdmin);
  document.getElementById("admin-nav-separator").classList.toggle("hidden", !isAdmin);
}

// For pages any signed-in user can view: redirects to /onboarding if setup
// isn't finished yet, otherwise reveals admin-only nav links if applicable.
async function setupNav() {
  try {
    const response = await apiFetch("/api/me");
    const me = await response.json();
    if (!me.onboarding_completed) {
      window.location.href = "/onboarding";
      return;
    }
    revealAdminNav(me.is_admin);
  } catch (error) {
    // apiFetch already shows the gate on 401
  }
}

// For admin-only pages: redirects to /onboarding if setup isn't finished,
// then to /metrics for non-admins. Returns whether the current user is an
// admin (false means the caller should stop).
async function requireAdmin() {
  const response = await apiFetch("/api/me");
  const me = await response.json();
  if (!me.onboarding_completed) {
    window.location.href = "/onboarding";
    return false;
  }
  if (!me.is_admin) {
    window.location.href = "/metrics";
    return false;
  }
  revealAdminNav(true);
  return true;
}

function syncThemeIcon() {
  const isDark = document.documentElement.classList.contains("dark");
  document.getElementById("theme-icon-sun").classList.toggle("hidden", !isDark);
  document.getElementById("theme-icon-moon").classList.toggle("hidden", isDark);
}

document.getElementById("theme-toggle-btn").addEventListener("click", () => {
  const isDark = !document.documentElement.classList.contains("dark");
  document.documentElement.classList.toggle("dark", isDark);
  localStorage.setItem("job-alerts-theme", isDark ? "dark" : "light");
  syncThemeIcon();
});

// Match whatever the inline head script already applied (system pref or a
// stored override) - no flash of the wrong icon on load.
syncThemeIcon();

document.getElementById("login-btn").addEventListener("click", async () => {
  const errorEl = document.getElementById("login-error");
  errorEl.classList.add("hidden");
  const email = document.getElementById("email-input").value.trim();

  const body = pendingSession
    ? { email, new_password: document.getElementById("new-password-input").value, session: pendingSession }
    : { email, password: document.getElementById("password-input").value };

  const response = await fetch("/api/login", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await response.json();

  if (!response.ok) {
    errorEl.textContent = data.error || "Login failed";
    errorEl.className = "mt-3 text-sm text-red-600 dark:text-red-400";
    return;
  }
  if (data.challenge === "NEW_PASSWORD_REQUIRED") {
    pendingSession = data.session;
    document.getElementById("password-input").classList.add("hidden");
    document.getElementById("new-password-input").classList.remove("hidden");
    errorEl.textContent = "First login - please set a new password";
    errorEl.className = "mt-3 text-sm text-neutral-600 dark:text-neutral-400";
    return;
  }
  localStorage.setItem(TOKEN_STORAGE, data.access_token);
  showApp();
});
