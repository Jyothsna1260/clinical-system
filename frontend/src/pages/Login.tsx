import { useState, type FormEvent } from "react";
import { Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { errorMessage } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { BrandMark } from "../components/AppLayout";
import { ActivityIcon, FileIcon, ShieldIcon, SparklesIcon } from "../components/Icons";
import { InlineError } from "../components/States";
import { ReviewNotice } from "../components/ReviewNotice";
import { ThemeToggle } from "../components/ThemeToggle";
import { useToast } from "../components/Toast";
import { ROUTES } from "../lib/routes";

// Synthetic demo account created by `python -m scripts.seed`; it holds synthetic data only.
const DEMO_EMAIL = "demo@example.org";
const DEMO_PASSWORD = "demo-password-123";

const FEATURES = [
  { Icon: SparklesIcon, title: "Six cooperating agents", text: "Protocol extraction, patient normalization, parallel inclusion / exclusion matching, contradiction detection and review." },
  { Icon: FileIcon, title: "Every finding cited", text: "Decisive results link to the exact protocol page and excerpt they came from." },
  { Icon: ActivityIcon, title: "Silent exclusion triggers", text: "Surfaces hidden contradictions, such as a patient who passes inclusion but may meet an undefined exclusion." },
  { Icon: ShieldIcon, title: "Human review built in", text: "Unknowns are never guessed. Results support, and never replace, clinical judgement." },
];

function safeNext(next: string | null): string {
  if (next && next.startsWith("/") && !next.startsWith("//") && !next.startsWith(ROUTES.login)) return next;
  return ROUTES.dashboard;
}

export default function Login() {
  const { token, login, register } = useAuth();
  const navigate = useNavigate();
  const { notify } = useToast();
  const [params] = useSearchParams();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const next = safeNext(params.get("next"));
  if (token) return <Navigate to={next} replace />;

  const isRegister = mode === "register";
  const passwordTooShort = isRegister && password.length > 0 && password.length < 8;

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (isRegister && password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    setBusy(true);
    try {
      if (isRegister) await register(email.trim(), password, fullName.trim() || null);
      else await login(email.trim(), password);
      notify("success", isRegister ? "Account created" : "Welcome back", "You are signed in.");
      navigate(next, { replace: true });
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  };

  const fillDemo = () => {
    setMode("login");
    setEmail(DEMO_EMAIL);
    setPassword(DEMO_PASSWORD);
    setError(null);
  };

  return (
    <div className="grid min-h-screen lg:grid-cols-[1.05fr_1fr]">
      <aside className="relative hidden overflow-hidden bg-gradient-to-br from-accent-600 via-indigo-600 to-violet-700 p-10 text-white lg:flex lg:flex-col lg:justify-between">
        <div aria-hidden="true" className="pointer-events-none absolute -right-24 -top-24 h-96 w-96 rounded-full bg-surface/10 blur-3xl" />
        <div aria-hidden="true" className="pointer-events-none absolute -bottom-32 -left-16 h-96 w-96 rounded-full bg-fuchsia-400/20 blur-3xl" />
        <div className="relative flex items-center gap-3">
          <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-surface/15 ring-1 ring-white/30 backdrop-blur">
            <svg viewBox="0 0 20 20" width="1.3em" height="1.3em" fill="none" stroke="currentColor" strokeWidth={2.4} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M5 10.5l3 3 7-7" />
            </svg>
          </span>
          <span className="text-lg font-semibold tracking-tight">Trial Eligibility Support</span>
        </div>
        <div className="relative max-w-lg">
          <h2 className="text-4xl font-semibold leading-tight tracking-tight">Screen patients against trial protocols, with every decision traced to the page.</h2>
          <ul className="mt-10 space-y-5">
            {FEATURES.map(({ Icon, title, text }, i) => (
              <li key={title} className="flex animate-fade-up gap-4" style={{ animationDelay: `${120 + i * 90}ms` }}>
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-surface/15 ring-1 ring-white/25">
                  <Icon className="text-lg" />
                </span>
                <div>
                  <p className="font-semibold">{title}</p>
                  <p className="text-sm text-white/80">{text}</p>
                </div>
              </li>
            ))}
          </ul>
        </div>
        <p className="relative text-xs text-white/70">Prototype for demonstration. Synthetic data only.</p>
      </aside>

      <div className="relative flex items-center justify-center px-4 py-10 sm:px-8">
        <div className="absolute right-4 top-4">
          <ThemeToggle showLabels />
        </div>
        <div className="w-full max-w-md animate-fade-up space-y-6">
          <div>
            <BrandMark size="lg" />
            <h1 className="mt-5 text-3xl font-semibold tracking-tight text-slate-900">
              {isRegister ? "Create your account" : "Welcome back"}
            </h1>
            <p className="mt-1.5 text-sm text-slate-600">
              {isRegister ? "Start screening synthetic patients in minutes." : "Sign in to continue to your workspace."}
            </p>
          </div>

          {!isRegister ? (
            <button
              type="button"
              onClick={fillDemo}
              className="group flex w-full items-center gap-3 rounded-xl border border-dashed border-accent-300 bg-accent-50/60 p-3 text-left transition-colors hover:border-accent-400 hover:bg-accent-50"
            >
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-accent-100 text-accent-700 transition-transform group-hover:scale-110">
                <SparklesIcon />
              </span>
              <span className="min-w-0">
                <span className="block text-sm font-semibold text-slate-900">Use the demo account</span>
                <span className="block truncate text-xs text-slate-600">Fills in {DEMO_EMAIL} with synthetic sample data</span>
              </span>
            </button>
          ) : null}

          <form onSubmit={(e) => void onSubmit(e)} className="card space-y-4 p-6" aria-busy={busy}>
            <div>
              <label htmlFor="email" className="label">Email</label>
              <input id="email" type="email" autoComplete="email" required placeholder="you@hospital.org" className="input" value={email} onChange={(e) => setEmail(e.target.value)} />
            </div>
            {isRegister ? (
              <div>
                <label htmlFor="full_name" className="label">
                  Full name <span className="font-normal text-slate-500">(optional)</span>
                </label>
                <input id="full_name" type="text" autoComplete="name" maxLength={200} className="input" value={fullName} onChange={(e) => setFullName(e.target.value)} />
              </div>
            ) : null}
            <div>
              <div className="flex items-center justify-between">
                <label htmlFor="password" className="label">Password</label>
                <button type="button" className="mb-1 text-xs font-medium text-accent-700 hover:underline" onClick={() => setShowPassword((s) => !s)} aria-controls="password">
                  {showPassword ? "Hide" : "Show"}
                </button>
              </div>
              <input
                id="password"
                type={showPassword ? "text" : "password"}
                autoComplete={isRegister ? "new-password" : "current-password"}
                required
                minLength={isRegister ? 8 : undefined}
                maxLength={128}
                aria-describedby={isRegister ? "password-hint" : undefined}
                aria-invalid={passwordTooShort || undefined}
                className={`input ${passwordTooShort ? "input-invalid" : ""}`}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
              {isRegister ? (
                <p id="password-hint" className={`mt-1 text-xs ${passwordTooShort ? "font-semibold text-amber-900" : "text-slate-600"}`}>
                  At least 8 characters{passwordTooShort ? ` (${password.length}/8)` : ""}.
                </p>
              ) : null}
            </div>
            <InlineError message={error} />
            <button type="submit" className="btn-primary w-full py-2.5" disabled={busy}>
              {busy ? (isRegister ? "Creating account…" : "Signing in…") : isRegister ? "Create account" : "Sign in"}
            </button>
            <p className="text-center text-sm text-slate-600">
              {isRegister ? "Already have an account?" : "No account yet?"}{" "}
              <button
                type="button"
                className="link"
                onClick={() => {
                  setMode(isRegister ? "login" : "register");
                  setError(null);
                }}
              >
                {isRegister ? "Sign in" : "Register"}
              </button>
            </p>
          </form>
          <ReviewNotice compact />
        </div>
      </div>
    </div>
  );
}
