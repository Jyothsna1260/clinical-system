import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { getRunStatus } from "../api/client";
import { AgentProgress } from "../components/AgentProgress";
import { ReviewNotice } from "../components/ReviewNotice";
import { ErrorState, LoadingState } from "../components/States";
import { StatusBadge } from "../components/StatusBadge";
import { WorkflowSteps } from "../components/WorkflowSteps";
import { formatDateTime, formatValue } from "../lib/format";
import type { RunStatus } from "../types";
import { ROUTES } from "../lib/routes";

const MAX_CONSECUTIVE_FAILURES = 5;
const AUTO_NAVIGATE_MS = 1500;
/** After this long without a final status, tell the user and offer a way out. */
const SLOW_RUN_MS = 3 * 60_000;

/** Poll every second at first, then back off: runs normally finish in seconds. */
function pollDelay(elapsedMs: number): number {
  if (elapsedMs < 30_000) return 1000;
  if (elapsedMs < 120_000) return 3000;
  return 5000;
}

export default function Analysis() {
  const { runId = "" } = useParams<{ runId: string }>();
  const navigate = useNavigate();
  const [status, setStatus] = useState<RunStatus | null>(null);
  const [pollError, setPollError] = useState<unknown>(null);
  const [pollNonce, setPollNonce] = useState(0);
  const [slow, setSlow] = useState(false);
  const failures = useRef(0);

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    const started = Date.now();
    failures.current = 0;
    setPollError(null);
    setSlow(false);

    const tick = async () => {
      try {
        const s = await getRunStatus(runId);
        if (cancelled) return;
        failures.current = 0;
        setStatus(s);
        if (s.status === "completed" || s.status === "failed") return;
        if (Date.now() - started > SLOW_RUN_MS) setSlow(true);
      } catch (err) {
        if (cancelled) return;
        failures.current += 1;
        if (failures.current >= MAX_CONSECUTIVE_FAILURES) {
          setPollError(err);
          return;
        }
      }
      timer = window.setTimeout(tick, pollDelay(Date.now() - started));
    };
    void tick();
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [runId, pollNonce]);

  const retry = useCallback(() => setPollNonce((n) => n + 1), []);

  const completed = status?.status === "completed";
  const failed = status?.status === "failed";

  useEffect(() => {
    if (!completed) return;
    const t = window.setTimeout(() => navigate(ROUTES.results(runId)), AUTO_NAVIGATE_MS);
    return () => window.clearTimeout(t);
  }, [completed, navigate, runId]);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <WorkflowSteps current={completed ? 4 : 3} />
          <h1 className="page-title mt-3">Eligibility analysis</h1>
          <p className="break-all text-xs text-slate-600">Run {runId}</p>
          {status ? <p className="text-sm text-slate-600">Started {formatDateTime(status.created_at)}</p> : null}
        </div>
        {status ? <StatusBadge status={status.status} size="lg" /> : null}
      </div>

      {!status && !pollError ? <LoadingState label="Loading analysis status…" /> : null}
      {pollError ? <ErrorState error={pollError} title="Lost contact with the analysis service" onRetry={retry} /> : null}

      {status ? (
        <>
          <div aria-live="polite" className="sr-only">
            {completed ? "Analysis completed. Opening results." : failed ? "Analysis failed." : `Analysis ${status.status}.`}
          </div>

          {slow && !completed && !failed ? (
            <div role="status" className="rounded-lg border border-amber-300 bg-amber-50 p-4 text-amber-950">
              <p className="font-semibold">This is taking longer than expected.</p>
              <p className="mt-1 text-sm">
                Most assessments finish within a minute. If the service restarted, this run will be marked as
                interrupted shortly and you can start it again from the dashboard.
              </p>
              <Link to={ROUTES.dashboard} className="btn-secondary mt-3 inline-flex">Back to dashboard</Link>
            </div>
          ) : null}

          {completed ? (
            <div role="status" className="flex flex-col gap-3 rounded-lg border border-emerald-300 bg-emerald-50 p-4 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex flex-wrap items-center gap-3 text-emerald-950">
                <p className="font-semibold">Analysis complete.</p>
                {status.overall_status ? <StatusBadge status={status.overall_status} /> : null}
                <p className="text-sm">Opening results…</p>
              </div>
              <Link to={ROUTES.results(runId)} className="btn-primary">View results</Link>
            </div>
          ) : null}

          {failed ? (
            <div role="alert" className="rounded-lg border border-red-300 bg-red-50 p-4 text-red-900">
              <p className="font-semibold">Analysis failed{status.error?.code ? ` (${String(status.error.code)})` : ""}</p>
              <p className="mt-1 text-sm">{status.error?.message ? String(status.error.message) : "The workflow stopped before producing a result."}</p>
              {status.error?.details && Object.keys(status.error.details).length > 0 ? (
                <dl className="mt-2 text-xs">
                  {Object.entries(status.error.details).map(([k, v]) => (
                    <div key={k} className="flex gap-1">
                      <dt className="font-semibold">{k}:</dt>
                      <dd className="break-words">{formatValue(v)}</dd>
                    </div>
                  ))}
                </dl>
              ) : null}
              <div className="mt-3 flex flex-wrap gap-2">
                <Link to={ROUTES.results(runId)} className="btn-secondary">View run details</Link>
                <Link to={ROUTES.dashboard} className="btn-secondary">Back to dashboard</Link>
              </div>
            </div>
          ) : null}

          <section aria-labelledby="progress-h" className="card p-4 sm:p-6" aria-busy={!completed && !failed}>
            <h2 id="progress-h" className="section-title mb-1">Agent workflow</h2>
            <p className="mb-4 text-sm text-slate-600">
              Each step is a specialised agent. Inclusion matching and exclusion detection run in parallel.
            </p>
            <AgentProgress progress={status.progress} />
          </section>
        </>
      ) : null}

      <ReviewNotice compact />
    </div>
  );
}
