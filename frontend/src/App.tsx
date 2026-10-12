import { Navigate, Route, Routes } from "react-router-dom";
import { API_CONFIG_ERROR } from "./api/client";
import { ROUTE_PATTERNS, ROUTES } from "./lib/routes";
import { ProtectedRoute } from "./auth/ProtectedRoute";
import { AppLayout } from "./components/AppLayout";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import TrialUpload from "./pages/TrialUpload";
import PatientForm from "./pages/PatientForm";
import Analysis from "./pages/Analysis";
import Results from "./pages/Results";
import NotFound from "./pages/NotFound";

export default function App() {
  if (API_CONFIG_ERROR) {
    return (
      <main className="mx-auto max-w-lg p-6">
        <div role="alert" className="rounded-lg border border-red-300 bg-red-50 p-4 text-red-900">
          <h1 className="text-lg font-semibold">The app is not configured</h1>
          <p className="mt-1 text-sm">{API_CONFIG_ERROR}</p>
        </div>
      </main>
    );
  }
  return (
    <Routes>
      <Route path={ROUTES.login} element={<Login />} />
      <Route element={<ProtectedRoute />}>
        <Route element={<AppLayout />}>
          <Route path="/" element={<Navigate to={ROUTES.dashboard} replace />} />
          <Route path={ROUTES.dashboard} element={<Dashboard />} />
          <Route path={ROUTES.uploadTrial} element={<TrialUpload />} />
          <Route path={ROUTES.newPatient} element={<PatientForm />} />
          <Route path={ROUTE_PATTERNS.editPatient} element={<PatientForm />} />
          <Route path={ROUTE_PATTERNS.analysis} element={<Analysis />} />
          <Route path={ROUTE_PATTERNS.results} element={<Results />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Route>
    </Routes>
  );
}
