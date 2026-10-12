import { Navigate, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "./AuthContext";
import { ErrorState, LoadingState } from "../components/States";
import { ROUTES } from "../lib/routes";

export function ProtectedRoute() {
  const { token, user, initializing, sessionError, retrySession } = useAuth();
  const location = useLocation();
  if (initializing) return <LoadingState label="Checking your session…" />;
  if (token && !user && sessionError) {
    return (
      <div className="mx-auto max-w-lg p-4 sm:p-8">
        <ErrorState error={sessionError} title="We couldn't reach the server" onRetry={retrySession} />
        <p className="mt-3 text-sm text-slate-600">
          The service may be starting up after a period of inactivity, which can take up to a minute. You are still
          signed in; try again shortly.
        </p>
      </div>
    );
  }
  if (!token) {
    const next = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={ROUTES.loginNext(next)} replace />;
  }
  return <Outlet />;
}
