import axios, { AxiosError, type AxiosProgressEvent, type InternalAxiosRequestConfig } from "axios";
import type {
  AnalyzeRequest,
  ApiErrorBody,
  Health,
  LoginRequest,
  PageOut,
  PatientCreate,
  PatientOut,
  PatientSummary,
  PatientUpdate,
  RegisterRequest,
  RunAudit,
  RunCreated,
  RunDetail,
  RunStatus,
  RunSummary,
  TokenOut,
  TrialDetail,
  TrialSummary,
  User,
} from "../types";
import { ROUTES } from "../lib/routes";

const CONFIGURED_API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.trim();

/** API base URL. The localhost fallback applies only to the dev server, never to a production build. */
export const API_URL: string = CONFIGURED_API_URL || (import.meta.env.DEV ? "http://localhost:8000" : "");

/** Set when a production build was made without VITE_API_URL; the app shows it instead of failing quietly. */
export const API_CONFIG_ERROR: string | null = API_URL
  ? null
  : "This build has no API address. Set VITE_API_URL in the hosting provider's environment variables (for example in Vercel project settings) and redeploy.";

const TOKEN_KEY = "cte_token";

// ------------------------------------------------------------------ token storage

export function getToken(): string | null {
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string): void {
  try {
    window.localStorage.setItem(TOKEN_KEY, token);
  } catch {
    // Storage unavailable (private mode / blocked); session will not persist across reloads.
  }
}

export function clearToken(): void {
  try {
    window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    // ignore
  }
}

// ------------------------------------------------------------------ axios instance

export const api = axios.create({
  baseURL: API_URL,
  timeout: 120_000,
  headers: { Accept: "application/json" },
});

interface RetryConfig extends InternalAxiosRequestConfig {
  __retryCount?: number;
}

const MAX_RETRIES = 2;
const RETRY_STATUSES = new Set([502, 503, 504]);

api.interceptors.request.use((config) => {
  const token = getToken();
  if (token) {
    config.headers.set("Authorization", `Bearer ${token}`);
  }
  return config;
});

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const config = error.config as RetryConfig | undefined;
    const status = error.response?.status;

    if (status === 401) {
      const url = config?.url ?? "";
      const isAuthCall = url.includes("/api/auth/login") || url.includes("/api/auth/register");
      if (!isAuthCall) {
        clearToken();
        if (window.location.pathname !== ROUTES.login) {
          const next = encodeURIComponent(window.location.pathname + window.location.search);
          window.location.assign(ROUTES.loginNext(next));
        }
      }
      return Promise.reject(error);
    }

    const method = (config?.method ?? "get").toLowerCase();
    const isNetworkError = !error.response && error.code !== AxiosError.ERR_CANCELED;
    const retryable = isNetworkError || (status !== undefined && RETRY_STATUSES.has(status));
    if (config && method === "get" && retryable) {
      const count = config.__retryCount ?? 0;
      if (count < MAX_RETRIES) {
        config.__retryCount = count + 1;
        await sleep(400 * 2 ** count);
        return api.request(config);
      }
    }
    return Promise.reject(error);
  },
);

// ------------------------------------------------------------------ error helpers

export interface ParsedApiError {
  status: number | null;
  code: string;
  message: string;
  details: Record<string, unknown>;
}

function isApiErrorBody(data: unknown): data is ApiErrorBody {
  if (typeof data !== "object" || data === null || !("error" in data)) return false;
  const err: unknown = data.error;
  return typeof err === "object" && err !== null && "message" in err;
}

/** Turn any thrown value (usually an AxiosError) into a structured error. */
export function parseApiError(err: unknown): ParsedApiError {
  if (axios.isAxiosError(err)) {
    const status = err.response?.status ?? null;
    const data: unknown = err.response?.data;
    if (isApiErrorBody(data)) {
      return {
        status,
        code: data.error.code || `HTTP_${status ?? "ERROR"}`,
        message: data.error.message,
        details: data.error.details ?? {},
      };
    }
    if (!err.response) {
      return {
        status: null,
        code: "NETWORK_ERROR",
        message: `Cannot reach the API at ${API_URL}. Check your connection or that the backend is running.`,
        details: {},
      };
    }
    return { status, code: `HTTP_${status}`, message: err.message, details: {} };
  }
  if (err instanceof Error) return { status: null, code: "CLIENT_ERROR", message: err.message, details: {} };
  return { status: null, code: "UNKNOWN_ERROR", message: "An unexpected error occurred.", details: {} };
}

/** Readable one-line message, including validation error locations when present. */
export function errorMessage(err: unknown): string {
  const parsed = parseApiError(err);
  let msg = parsed.message;
  const errors = parsed.details["errors"];
  if (Array.isArray(errors) && errors.length > 0) {
    const parts = errors.slice(0, 5).map((e) => {
      const item = e as { loc?: unknown[]; msg?: string };
      const loc = Array.isArray(item.loc) ? item.loc.filter((l) => l !== "body").join(".") : "";
      return loc ? `${loc}: ${item.msg ?? "invalid"}` : (item.msg ?? "invalid");
    });
    msg += ` ${parts.join("; ")}${errors.length > 5 ? ` (+${errors.length - 5} more)` : ""}`;
  }
  return parsed.code && !parsed.code.startsWith("HTTP_") ? `${msg} [${parsed.code}]` : msg;
}

// ------------------------------------------------------------------ endpoints

// health (public): limits and feature status
export async function getHealth(): Promise<Health> {
  return (await api.get<Health>("/api/health")).data;
}

// auth
export async function register(body: RegisterRequest): Promise<TokenOut> {
  return (await api.post<TokenOut>("/api/auth/register", body)).data;
}
export async function login(body: LoginRequest): Promise<TokenOut> {
  return (await api.post<TokenOut>("/api/auth/login", body)).data;
}
export async function me(): Promise<User> {
  return (await api.get<User>("/api/auth/me")).data;
}

// trials
export async function uploadTrial(
  file: File,
  title: string | null,
  onUploadProgress?: (e: AxiosProgressEvent) => void,
): Promise<TrialDetail> {
  const form = new FormData();
  form.append("file", file);
  if (title && title.trim()) form.append("title", title.trim());
  return (await api.post<TrialDetail>("/api/trials/upload", form, { onUploadProgress, timeout: 600_000 })).data;
}
export async function listTrials(): Promise<TrialSummary[]> {
  return (await api.get<TrialSummary[]>("/api/trials")).data;
}
export async function getPage(trialId: string, page: number): Promise<PageOut> {
  return (await api.get<PageOut>(`/api/trials/${encodeURIComponent(trialId)}/pages/${page}`)).data;
}

// patients
export async function createPatient(body: PatientCreate): Promise<PatientOut> {
  return (await api.post<PatientOut>("/api/patients", body)).data;
}
export async function listPatients(): Promise<PatientSummary[]> {
  return (await api.get<PatientSummary[]>("/api/patients")).data;
}
export async function getPatient(patientId: string): Promise<PatientOut> {
  return (await api.get<PatientOut>(`/api/patients/${encodeURIComponent(patientId)}`)).data;
}
export async function updatePatient(patientId: string, body: PatientUpdate): Promise<PatientOut> {
  return (await api.patch<PatientOut>(`/api/patients/${encodeURIComponent(patientId)}`, body)).data;
}

// eligibility
export async function analyze(body: AnalyzeRequest): Promise<RunCreated> {
  return (await api.post<RunCreated>("/api/eligibility/analyze", body)).data;
}
export async function listRuns(limit = 20): Promise<RunSummary[]> {
  return (await api.get<RunSummary[]>("/api/eligibility", { params: { limit } })).data;
}
export async function getRunStatus(runId: string): Promise<RunStatus> {
  return (await api.get<RunStatus>(`/api/eligibility/${encodeURIComponent(runId)}/status`)).data;
}
export async function getRun(runId: string): Promise<RunDetail> {
  return (await api.get<RunDetail>(`/api/eligibility/${encodeURIComponent(runId)}`)).data;
}
export async function getAudit(runId: string): Promise<RunAudit> {
  return (await api.get<RunAudit>(`/api/eligibility/${encodeURIComponent(runId)}/audit`)).data;
}
