import { Navigate, Outlet, useLocation } from "react-router-dom";

import { useCurrentUser } from "../api/hooks";
import { useAuth } from "./AuthContext";
import { FullPageSpinner } from "../components/Skeleton";

/** Gates every authenticated route: no token sends you to /login, an unfinished
 * setup sends you to /onboarding. Both run once here rather than per page. */
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
