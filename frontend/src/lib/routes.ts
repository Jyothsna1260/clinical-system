/** Every client-side route in one place (the <Routes> table in App.tsx uses the same patterns). */
export const ROUTES = {
  login: "/login",
  dashboard: "/dashboard",
  uploadTrial: "/trials/upload",
  newPatient: "/patients/new",
  editPatient: (patientId: string) => `/patients/${encodeURIComponent(patientId)}/edit`,
  analysis: (runId: string) => `/analysis/${encodeURIComponent(runId)}`,
  results: (runId: string) => `/results/${encodeURIComponent(runId)}`,
  /** Login page that returns to `path` (already URL-encoded by the caller) after sign-in. */
  loginNext: (encodedPath: string) => `/login?next=${encodedPath}`,
} as const;

/** Route patterns for the router table. */
export const ROUTE_PATTERNS = {
  editPatient: "/patients/:id/edit",
  analysis: "/analysis/:runId",
  results: "/results/:runId",
} as const;
