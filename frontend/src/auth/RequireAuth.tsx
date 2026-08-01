import { Navigate, Outlet, useLocation } from "react-router-dom";

import { useCurrentUser } from "../api/hooks";
import { useAuth } from "./AuthContext";
import { FullPageSpinner } from "../components/Skeleton";

/** Checked once here rather than per page, as the old dashboard did. */
export function RequireAuth() {
  const { isAuthenticated } = useAuth();
  const location = useLocation();
  const { data: currentUser, isPending, isError } = useCurrentUser();

  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  if (isPending) {
    return <FullPageSpinner />;
  }
  if (isError) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  if (!currentUser.onboarding_completed && location.pathname !== "/onboarding") {
    return <Navigate to="/onboarding" replace />;
  }
  return <Outlet />;
}

export function RequireAdmin() {
  const { data: currentUser, isPending } = useCurrentUser();

  if (isPending) {
    return <FullPageSpinner />;
  }
  if (!currentUser?.is_admin) {
    return <Navigate to="/listings" replace />;
  }
  return <Outlet />;
}
