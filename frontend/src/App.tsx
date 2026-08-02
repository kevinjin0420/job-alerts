import { Suspense, lazy } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { AuthProvider } from "./auth/AuthContext";
import { LoginPage } from "./auth/LoginPage";
import { RequireAdmin, RequireAuth } from "./auth/RequireAuth";
import { AppLayout } from "./components/AppLayout";
import { FullPageSpinner } from "./components/Skeleton";
import { AdminPage } from "./pages/AdminPage";
import { ConfigPage } from "./pages/ConfigPage";
import { ListingsPage } from "./pages/ListingsPage";
import { LlmLogsPage } from "./pages/LlmLogsPage";
import { LogsPage } from "./pages/LogsPage";
import { OnboardingPage } from "./pages/OnboardingPage";
import { ProfilePage } from "./pages/ProfilePage";
import { SourcesPage } from "./pages/SourcesPage";
import { ThemeProvider } from "./theme/ThemeContext";

// Chart.js is ~330KB of the bundle and only these two routes need it.
const MetricsPage = lazy(() => import("./pages/MetricsPage").then((module) => ({ default: module.MetricsPage })));
const ActivityPage = lazy(() => import("./pages/ActivityPage").then((module) => ({ default: module.ActivityPage })));

export function App() {
  return (
    <ThemeProvider>
      <BrowserRouter>
        <AuthProvider>
          <Suspense fallback={<FullPageSpinner />}>
            <Routes>
              <Route path="/login" element={<LoginPage />} />
              <Route element={<RequireAuth />}>
                <Route path="/onboarding" element={<OnboardingPage />} />
                <Route element={<AppLayout />}>
                  <Route index element={<Navigate to="/listings" replace />} />
                  <Route path="/listings" element={<ListingsPage />} />
                  <Route path="/metrics" element={<MetricsPage />} />
                  <Route path="/config" element={<ConfigPage />} />
                  <Route path="/profile" element={<ProfilePage />} />
                  <Route element={<RequireAdmin />}>
                    <Route path="/logs" element={<LogsPage />} />
                    <Route path="/llm-logs" element={<LlmLogsPage />} />
                    <Route path="/sources" element={<SourcesPage />} />
                    <Route path="/admin" element={<AdminPage />} />
                    <Route path="/activity" element={<ActivityPage />} />
                  </Route>
                </Route>
              </Route>
              <Route path="*" element={<Navigate to="/listings" replace />} />
            </Routes>
          </Suspense>
        </AuthProvider>
      </BrowserRouter>
    </ThemeProvider>
  );
}
