import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { listPatients, listRuns, listTrials } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { AssessmentLauncher } from "../components/AssessmentLauncher";
import { ActivityIcon, ArrowRightIcon, FileIcon, PlusIcon, QuestionIcon, SearchIcon, SparklesIcon, UploadIcon, UsersIcon } from "../components/Icons";
import { ReviewNotice } from "../components/ReviewNotice";
import { EmptyState, ErrorState } from "../components/States";
import { StatusBadge } from "../components/StatusBadge";
import { formatDateTime } from "../lib/format";
import { useAsync } from "../lib/useAsync";
import type { RunSummary } from "../types";
import { ROUTES } from "../lib/routes";

/** Animates a number from 0 to `value` once it is known. */
function useCountUp(value: number, ms = 700): number {
  const [n, setN] = useState(0);
  useEffect(() => {
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
      setN(value);
      return;
    }
    let raf = 0;
    const start = performance.now();
    const step = (t: number) => {
      const p = Math.min(1, (t - start) / ms);
      setN(Math.round(value * (1 - Math.pow(1 - p, 3))));
      if (p < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [value, ms]);
  return n;
}

function StatCard({ label, value, hint, Icon, tone, delay }: { label: string; value: number; hint: string; Icon: typeof FileIcon; tone: string; delay: number }) {
  const n = useCountUp(value);
  return (
    <div className="card-interactive animate-fade-up p-4 sm:p-5" style={{ animationDelay: `${delay}ms` }}>
      <div className="flex items-start justify-between gap-3">
        <p className="eyebrow">{label}</p>
        <span className={`flex h-9 w-9 items-center justify-center rounded-lg ${tone}`}>
          <Icon className="text-lg" />
        </span>
      </div>
      <p className="mt-2 text-3xl font-semibold tabular-nums tracking-tight text-slate-900">{n}</p>
      <p className="mt-1 text-xs text-slate-500">{hint}</p>
    </div>
  );
}

const OUTCOMES = [
  { key: "ELIGIBLE", label: "Eligible", bar: "bg-emerald-500" },
  { key: "NOT_ELIGIBLE", label: "Not eligible", bar: "bg-red-500" },
  { key: "MORE_INFORMATION_REQUIRED", label: "More info required", bar: "bg-amber-500" },
] as const;

function OutcomeBar({ runs }: { runs: RunSummary[] }) {
  const done = runs.filter((r) => r.overall_status);
  if (done.length === 0) return null;
  return (
    <div>
      <div className="flex h-2.5 w-full overflow-hidden rounded-full bg-slate-100" role="img" aria-label="Distribution of assessment outcomes">
        {OUTCOMES.map((o) => {
          const c = done.filter((r) => r.overall_status === o.key).length;
          return c ? <span key={o.key} className={`${o.bar} h-full transition-all duration-700`} style={{ width: `${(c / done.length) * 100}%` }} /> : null;
        })}
      </div>
      <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-600">
        {OUTCOMES.map((o) => (
          <li key={o.key} className="flex items-center gap-1.5">
            <span className={`h-2 w-2 rounded-full ${o.bar}`} aria-hidden="true" />
            {o.label} <span className="font-semibold tabular-nums text-slate-800">{done.filter((r) => r.overall_status === o.key).length}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function SearchBox({ value, onChange, label }: { value: string; onChange: (v: string) => void; label: string }) {
  return (
    <div className="relative">
      <SearchIcon className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
      <input type="search" aria-label={label} placeholder="Filter…" className="input h-8 w-36 py-1 pl-8 text-xs sm:w-44" value={value} onChange={(e) => onChange(e.target.value)} />
    </div>
  );
}

function Section({ id, title, action, children, className = "" }: { id: string; title: string; action?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section aria-labelledby={id} className={`card p-4 sm:p-6 ${className}`}>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 id={id} className="section-title">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}

function DashboardSkeleton() {
  return (
    <div className="space-y-6" role="status" aria-label="Loading dashboard">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="card space-y-3 p-5">
            <div className="skeleton h-3 w-24" />
            <div className="skeleton h-8 w-16" />
            <div className="skeleton h-3 w-32" />
          </div>
        ))}
      </div>
      <div className="card space-y-3 p-6">
        <div className="skeleton h-4 w-40" />
        <div className="skeleton h-10 w-full max-w-xl" />
        <div className="skeleton h-10 w-full max-w-xl" />
      </div>
    </div>
  );
}

const RUN_FILTERS = [{ key: "ALL", label: "All" }, ...OUTCOMES.map((o) => ({ key: o.key, label: o.label }))];

export default function Dashboard() {
  const { user } = useAuth();
  const data = useAsync(async () => {
    const [trials, patients, runs] = await Promise.all([listTrials(), listPatients(), listRuns(50)]);
    return { trials, patients, runs };
  }, []);
  const [trialQ, setTrialQ] = useState("");
  const [patientQ, setPatientQ] = useState("");
  const [runFilter, setRunFilter] = useState<string>("ALL");

  const firstName = (user?.full_name || "").split(" ")[0];
  const d = data.data;

  const filtered = useMemo(() => {
    if (!d) return null;
    const q = (s: string, needle: string) => s.toLowerCase().includes(needle.trim().toLowerCase());
    return {
      trials: d.trials.filter((t) => q(t.title, trialQ)),
      patients: d.patients.filter((p) => q(p.label, patientQ)),
      runs: d.runs.filter((r) => runFilter === "ALL" || r.overall_status === runFilter),
    };
  }, [d, trialQ, patientQ, runFilter]);

  return (
    <div className="space-y-6">
      <div className="relative overflow-hidden rounded-2xl border border-slate-200 bg-gradient-to-br from-accent-50 via-surface to-surface p-5 sm:p-7">
        <div aria-hidden="true" className="pointer-events-none absolute -right-16 -top-20 h-64 w-64 rounded-full bg-accent-400/20 blur-3xl" />
        <div className="relative flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="eyebrow flex items-center gap-1.5 text-accent-700">
              <SparklesIcon /> Eligibility workspace
            </p>
            <h1 className="page-title mt-1">{firstName ? `Hello, ${firstName}` : "Dashboard"}</h1>
            <p className="mt-1 max-w-xl text-sm text-slate-600">
              Pick a protocol and a patient to run the six-agent eligibility workflow. Every decisive finding is cited to its protocol page.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Link to={ROUTES.uploadTrial} className="btn-secondary">
              <UploadIcon /> Upload protocol
            </Link>
            <Link to={ROUTES.newPatient} className="btn-primary">
              <PlusIcon /> New patient
            </Link>
          </div>
        </div>
      </div>

      {data.loading && !d ? <DashboardSkeleton /> : null}
      {data.error ? <ErrorState error={data.error} title="Could not load dashboard" onRetry={data.reload} /> : null}

      {d && filtered ? (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard label="Protocols" value={d.trials.length} hint={`${d.trials.filter((t) => t.status === "ready").length} ready for analysis`} Icon={FileIcon} tone="bg-accent-50 text-accent-700" delay={0} />
            <StatCard label="Patients" value={d.patients.length} hint="Synthetic profiles" Icon={UsersIcon} tone="bg-violet-500/10 text-violet-500" delay={60} />
            <StatCard label="Assessments" value={d.runs.length} hint={`${d.runs.filter((r) => r.status === "completed").length} completed`} Icon={ActivityIcon} tone="bg-emerald-50 text-emerald-700" delay={120} />
            <StatCard
              label="Need follow-up"
              value={d.runs.filter((r) => r.overall_status && r.overall_status !== "ELIGIBLE").length}
              hint="Not eligible or more info required"
              Icon={QuestionIcon}
              tone="bg-amber-50 text-amber-700"
              delay={180}
            />
          </div>

          <div className="grid gap-6 lg:grid-cols-5">
            <Section id="new-assessment" title="Run a new assessment" className="lg:col-span-3">
              {d.trials.length === 0 || d.patients.length === 0 ? (
                <p className="text-sm text-slate-600">
                  You need at least one ready trial and one patient.{" "}
                  {d.trials.length === 0 ? <Link to={ROUTES.uploadTrial} className="link">Upload a protocol</Link> : null}
                  {d.trials.length === 0 && d.patients.length === 0 ? " and " : null}
                  {d.patients.length === 0 ? <Link to={ROUTES.newPatient} className="link">create a patient</Link> : null}.
                </p>
              ) : (
                <AssessmentLauncher trials={d.trials} patients={d.patients} idPrefix="dash" />
              )}
            </Section>
            <Section id="outcomes-h" title="Outcomes at a glance" className="lg:col-span-2">
              {d.runs.some((r) => r.overall_status) ? (
                <OutcomeBar runs={d.runs} />
              ) : (
                <p className="text-sm text-slate-600">Outcomes appear here after your first assessment.</p>
              )}
              <div className="mt-5">
                <ReviewNotice compact />
              </div>
            </Section>
          </div>

          <div className="grid gap-6 lg:grid-cols-2">
            <Section id="trials-h" title="Trial protocols" action={d.trials.length > 3 ? <SearchBox value={trialQ} onChange={setTrialQ} label="Filter trials" /> : undefined}>
              {d.trials.length === 0 ? (
                <EmptyState title="No trial protocols yet">
                  <Link to={ROUTES.uploadTrial} className="link">Upload a protocol PDF</Link> to extract its criteria.
                </EmptyState>
              ) : filtered.trials.length === 0 ? (
                <p className="py-4 text-center text-sm text-slate-500">No trials match “{trialQ}”.</p>
              ) : (
                <ul className="-mx-2 space-y-1">
                  {filtered.trials.map((t) => (
                    <li key={t.id} className="flex items-start gap-3 rounded-lg px-2 py-2.5 transition-colors hover:bg-slate-50">
                      <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent-50 text-accent-700">
                        <FileIcon />
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="break-words text-sm font-medium text-slate-900">{t.title}</p>
                        <p className="text-xs text-slate-500">
                          {t.criteria_count} criteria · {t.protocol_version ?? "—"}
                          {t.page_count ? ` · ${t.page_count} pages` : ""} · {formatDateTime(t.created_at)}
                        </p>
                      </div>
                      <StatusBadge status={t.status} />
                    </li>
                  ))}
                </ul>
              )}
            </Section>

            <Section id="patients-h" title="Patients" action={d.patients.length > 3 ? <SearchBox value={patientQ} onChange={setPatientQ} label="Filter patients" /> : undefined}>
              {d.patients.length === 0 ? (
                <EmptyState title="No patient profiles yet">
                  <Link to={ROUTES.newPatient} className="link">Create a patient profile</Link> to run an assessment.
                </EmptyState>
              ) : filtered.patients.length === 0 ? (
                <p className="py-4 text-center text-sm text-slate-500">No patients match “{patientQ}”.</p>
              ) : (
                <ul className="-mx-2 space-y-1">
                  {filtered.patients.map((p) => (
                    <li key={p.id} className="group flex items-center gap-3 rounded-lg px-2 py-2.5 transition-colors hover:bg-slate-50">
                      <span aria-hidden="true" className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-violet-500/10 text-xs font-bold text-violet-500">
                        {p.label.match(/patient\s+(\w)/i)?.[1]?.toUpperCase() ?? p.label[0]?.toUpperCase()}
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="break-words text-sm font-medium text-slate-900">{p.label}</p>
                        <p className="text-xs text-slate-500">Version {p.version} · Updated {formatDateTime(p.updated_at)}</p>
                      </div>
                      <Link to={ROUTES.editPatient(p.id)} className="btn-ghost px-2.5 py-1 text-xs opacity-80 group-hover:opacity-100" aria-label={`Edit patient ${p.label}`}>
                        Edit
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </Section>
          </div>

          <Section
            id="runs-h"
            title="Recent assessments"
            action={
              <button type="button" className="btn-ghost py-1 text-sm" onClick={data.reload} disabled={data.loading}>
                {data.loading ? "Refreshing…" : "Refresh"}
              </button>
            }
          >
            {d.runs.length > 0 ? (
              <div role="tablist" aria-label="Filter assessments by outcome" className="mb-3 flex flex-wrap gap-1.5">
                {RUN_FILTERS.map((f) => {
                  const active = runFilter === f.key;
                  const count = f.key === "ALL" ? d.runs.length : d.runs.filter((r) => r.overall_status === f.key).length;
                  return (
                    <button
                      key={f.key}
                      type="button"
                      role="tab"
                      aria-selected={active}
                      onClick={() => setRunFilter(f.key)}
                      className={`rounded-full border px-3 py-1 text-xs font-medium transition-colors ${
                        active ? "border-accent-600 bg-accent-600 text-white" : "border-slate-200 text-slate-600 hover:border-slate-300 hover:bg-slate-50"
                      }`}
                    >
                      {f.label} <span className={`ml-0.5 tabular-nums ${active ? "text-white/80" : "text-slate-400"}`}>{count}</span>
                    </button>
                  );
                })}
              </div>
            ) : null}
            {d.runs.length === 0 ? (
              <EmptyState title="No assessments yet">Use “Run a new assessment” above to analyze a patient against a trial.</EmptyState>
            ) : filtered.runs.length === 0 ? (
              <p className="py-4 text-center text-sm text-slate-500">No assessments with this outcome yet.</p>
            ) : (
              <ul className="-mx-2 space-y-1">
                {filtered.runs.map((r, i) => {
                  const done = r.status === "completed" || r.status === "failed";
                  return (
                    <li key={r.run_id} className="animate-fade-up" style={{ animationDelay: `${Math.min(i, 10) * 30}ms` }}>
                      <Link
                        to={done ? ROUTES.results(r.run_id) : ROUTES.analysis(r.run_id)}
                        className="group flex flex-col gap-2 rounded-lg px-2 py-2.5 transition-colors hover:bg-slate-50 sm:flex-row sm:items-center sm:justify-between"
                        aria-label={`${done ? "View results" : "View progress"} for ${r.patient_label} in ${r.trial_title}`}
                      >
                        <div className="min-w-0">
                          <p className="break-words text-sm font-medium text-slate-900">{r.patient_label}</p>
                          <p className="text-xs text-slate-500">
                            {r.trial_title} · v{r.patient_profile_version} · {formatDateTime(r.created_at)}
                          </p>
                        </div>
                        <div className="flex items-center gap-3">
                          {r.overall_status ? <StatusBadge status={r.overall_status} /> : <StatusBadge status={r.status} />}
                          <ArrowRightIcon className="text-slate-400 transition-transform group-hover:translate-x-0.5 group-hover:text-accent-600" />
                        </div>
                      </Link>
                    </li>
                  );
                })}
              </ul>
            )}
          </Section>
        </>
      ) : null}
    </div>
  );
}
