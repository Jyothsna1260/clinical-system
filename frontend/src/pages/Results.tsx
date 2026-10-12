import { useCallback, useState, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { getRun } from "../api/client";
import { AuditTrail } from "../components/AuditTrail";
import { CheckCircleIcon, QuestionIcon, XOctagonIcon } from "../components/Icons";
import { useToast } from "../components/Toast";
import { CriteriaTable } from "../components/CriteriaTable";
import { EvidenceLinks } from "../components/EvidenceLinks";
import { EvidencePanel, type EvidenceTarget } from "../components/EvidencePanel";
import { ReviewNotice } from "../components/ReviewNotice";
import { SilentExclusionCard } from "../components/SilentExclusionCard";
import { WorkflowSteps } from "../components/WorkflowSteps";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { OverallStatusBadge, StatusBadge } from "../components/StatusBadge";
import { attributeLabel, formatDate, formatDateTime, formatValue, humanize } from "../lib/format";
import { useAsync } from "../lib/useAsync";
import type { CriterionEvaluation, EligibilityResult } from "../types";
import { ROUTES } from "../lib/routes";

interface Verdict {
  ring: string;
  glow: string;
  icon: string;
  Icon: typeof CheckCircleIcon;
  headline: string;
}

const MORE_INFO_VERDICT: Verdict = { ring: "border-amber-300", glow: "from-amber-50", icon: "bg-amber-100 text-amber-700", Icon: QuestionIcon, headline: "More information is required" };

const VERDICT: Record<string, Verdict> = {
  ELIGIBLE: { ring: "border-emerald-300", glow: "from-emerald-50", icon: "bg-emerald-100 text-emerald-700", Icon: CheckCircleIcon, headline: "Patient appears eligible" },
  NOT_ELIGIBLE: { ring: "border-red-300", glow: "from-red-50", icon: "bg-red-100 text-red-700", Icon: XOctagonIcon, headline: "Patient does not appear eligible" },
  MORE_INFORMATION_REQUIRED: MORE_INFO_VERDICT,
};

function countBy(evals: CriterionEvaluation[], status: string): number {
  return evals.filter((e) => e.status === status).length;
}

/** One plain-language sentence naming what decided the outcome. */
function summaryLine(r: EligibilityResult): string {
  const unknown = [...r.inclusion_results, ...r.exclusion_results].filter((e) => e.status === "UNKNOWN");
  let line: string;
  if (r.overall_status === "NOT_ELIGIBLE") {
    const decisive = r.decisive_evidence.filter((e) => e.status === "UNSATISFIED" || e.status === "TRIGGERED");
    const first = decisive[0];
    const evaluation = first
      ? [...r.inclusion_results, ...r.exclusion_results].find((e) => e.criterion_id === first.criterion_id)
      : undefined;
    line = first
      ? `Decided by ${decisive.map((e) => e.criterion_id).join(", ")}: ${evaluation?.original_text.replace(/\.$/, "") ?? first.expected_condition} ` +
        `(patient ${first.patient_value ?? "value not available"}).`
      : "A required criterion is not met.";
  } else if (r.overall_status === "ELIGIBLE") {
    line = `All ${r.inclusion_results.length} inclusion criteria are met and none of the ${r.exclusion_results.length} exclusion criteria is triggered.`;
  } else {
    const what = r.missing_information.map((m) => attributeLabel(m.attribute)).slice(0, 3);
    line = `${unknown.length} ${unknown.length === 1 ? "criterion" : "criteria"} could not be decided` +
      (what.length > 0 ? ` (needs: ${what.join(", ")}).` : ".");
  }
  const n = r.silent_exclusion_triggers.length;
  return n > 0 ? `${line} ${n} silent exclusion trigger${n === 1 ? "" : "s"} flagged.` : line;
}

function Metric({ label, value, total, tone }: { label: string; value: number; total?: number; tone: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-surface/70 px-3 py-2">
      <p className="text-[11px] font-medium uppercase tracking-wide text-slate-500">{label}</p>
      <p className={`text-lg font-semibold tabular-nums ${tone}`}>
        {value}
        {total !== undefined ? <span className="text-sm font-normal text-slate-400"> / {total}</span> : null}
      </p>
    </div>
  );
}

function SectionNav({ r }: { r: EligibilityResult }) {
  const links = [
    { href: "#set-h", label: "Silent triggers", n: r.silent_exclusion_triggers.length },
    { href: "#triggered-h", label: "Triggered exclusions", n: countBy(r.exclusion_results, "TRIGGERED") },
    { href: "#inclusion-criteria", label: "Inclusion", n: r.inclusion_results.length },
    { href: "#exclusion-criteria", label: "Exclusion", n: r.exclusion_results.length },
    { href: "#values-h", label: "Patient values", n: (r.patient_values_used ?? []).length },
    { href: "#missing-h", label: "Missing info", n: r.missing_information.length },
    { href: "#decisive-h", label: "Protocol evidence", n: r.decisive_evidence.length },
    { href: "#audit", label: "Audit trail" },
  ];
  return (
    <nav aria-label="Result sections" className="sticky top-16 z-20 -mx-4 border-b border-slate-200/70 bg-canvas/85 px-4 py-2 backdrop-blur print:hidden sm:mx-0 sm:rounded-xl sm:border">
      <ul className="flex gap-1 overflow-x-auto">
        {links.map((l) => (
          <li key={l.href} className="shrink-0">
            <a href={l.href} className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium text-slate-600 transition-colors hover:bg-slate-100 hover:text-slate-900">
              {l.label}
              {l.n !== undefined ? <span className="rounded-full bg-slate-100 px-1.5 text-[10px] tabular-nums text-slate-500">{l.n}</span> : null}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}

function Panel({ id, title, count, children }: { id: string; title: string; count?: number; children: ReactNode }) {
  return (
    <section aria-labelledby={id} className="card scroll-mt-32 p-4 sm:p-6">
      <h2 id={id} className="section-title mb-3">
        {title}
        {count !== undefined ? <span className="text-sm font-normal text-slate-600"> ({count})</span> : null}
      </h2>
      {children}
    </section>
  );
}

export default function Results() {
  const { runId = "" } = useParams<{ runId: string }>();
  const run = useAsync(() => getRun(runId), [runId]);
  const { notify } = useToast();
  const [evidence, setEvidence] = useState<EvidenceTarget | null>(null);
  const openEvidence = useCallback((t: EvidenceTarget) => setEvidence(t), []);
  const closeEvidence = useCallback(() => setEvidence(null), []);

  if (run.loading && !run.data) return <LoadingState label="Loading results…" />;
  if (run.error) return <ErrorState error={run.error} title="Could not load results" onRetry={run.reload} />;
  if (!run.data) return <EmptyState title="No result found." />;

  const d = run.data;
  const r = d.result;

  if (!r) {
    const inProgress = d.status === "queued" || d.status === "running";
    return (
      <div className="space-y-6">
        <h1 className="page-title">Assessment results</h1>
        <div className="card space-y-3 p-4 sm:p-6">
          <div className="flex flex-wrap items-center gap-3">
            <StatusBadge status={d.status} size="lg" />
            <p className="text-sm text-slate-700">
              {d.trial_title} · {d.patient_label} (v{d.patient_profile_version})
            </p>
          </div>
          {inProgress ? (
            <p className="text-sm">
              This analysis is still in progress. <Link to={ROUTES.analysis(d.run_id)} className="link">View progress</Link>
            </p>
          ) : (
            <div role="alert" className="rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-900">
              <p className="font-semibold">No result is available{d.error?.code ? ` (${String(d.error.code)})` : ""}.</p>
              <p className="mt-1">{d.error?.message ? String(d.error.message) : "The analysis did not produce a result."}</p>
              {d.error?.details && Object.keys(d.error.details).length > 0 ? (
                <p className="mt-1 break-words text-xs">{formatValue(d.error.details)}</p>
              ) : null}
            </div>
          )}
          <div className="flex flex-wrap gap-2">
            <button type="button" className="btn-secondary" onClick={run.reload}>Refresh</button>
            <Link to={ROUTES.dashboard} className="btn-secondary">Back to dashboard</Link>
          </div>
        </div>
        <ReviewNotice notice={d.human_review_notice} />
      </div>
    );
  }

  const notice = r.human_review_notice || d.human_review_notice;
  const triggered = r.exclusion_results.filter((e) => e.status === "TRIGGERED");
  const valuesUsed = r.patient_values_used ?? [];
  const externalRefs = r.external_references ?? [];
  const verdict = VERDICT[r.overall_status] ?? MORE_INFO_VERDICT;

  return (
    <div className="space-y-6">
      <WorkflowSteps current={4} />
      <ReviewNotice notice={notice} />

      <section
        aria-labelledby="summary-h"
        className={`relative overflow-hidden rounded-2xl border-2 bg-gradient-to-br ${verdict.ring} ${verdict.glow} via-surface to-surface p-5 shadow-card sm:p-7`}
      >
        <div className="flex flex-col gap-5 md:flex-row md:items-start md:justify-between">
          <div className="flex min-w-0 gap-4">
            <span className={`hidden h-14 w-14 shrink-0 animate-scale-in items-center justify-center rounded-2xl text-3xl sm:flex ${verdict.icon}`}>
              <verdict.Icon />
            </span>
            <div className="min-w-0 space-y-1">
              <p className="eyebrow">Eligibility assessment</p>
              <h1 id="summary-h" className="page-title">{verdict.headline}</h1>
              <p className="text-base font-medium text-slate-800">{summaryLine(r)}</p>
              <p className="break-words text-sm text-slate-700">
                <span className="font-semibold">Trial:</span> {d.trial_title}
              </p>
              <p className="break-words text-sm text-slate-700">
                <span className="font-semibold">Patient:</span> {d.patient_label}{" "}
                <span className="text-slate-500">(profile version {d.patient_profile_version})</span>
              </p>
              <p className="text-xs text-slate-500">
                Protocol version <span className="font-mono">{r.protocol_version || d.protocol_version}</span> · Analyzed {formatDateTime(r.analyzed_at)}
              </p>
            </div>
          </div>
          <div className="order-first flex shrink-0 flex-col items-start gap-3 md:order-none md:items-end" aria-label="Overall recommendation">
            <p className="eyebrow">Overall recommendation</p>
            <OverallStatusBadge status={r.overall_status} />
            <div className="flex gap-2 print:hidden">
              <button
                type="button"
                className="btn-secondary px-3 py-1.5 text-xs"
                onClick={() => {
                  void navigator.clipboard?.writeText(window.location.href).then(
                    () => notify("success", "Link copied", "Share it with a colleague who has access."),
                    () => notify("error", "Could not copy link"),
                  );
                }}
              >
                Copy link
              </button>
              <button type="button" className="btn-secondary px-3 py-1.5 text-xs" onClick={() => window.print()}>
                Print
              </button>
            </div>
          </div>
        </div>
        <div className="mt-5 grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Metric label="Inclusion met" value={countBy(r.inclusion_results, "SATISFIED")} total={r.inclusion_results.length} tone="text-emerald-700" />
          <Metric label="Exclusions triggered" value={countBy(r.exclusion_results, "TRIGGERED")} total={r.exclusion_results.length} tone="text-red-700" />
          <Metric label="Unknown" value={countBy(r.inclusion_results, "UNKNOWN") + countBy(r.exclusion_results, "UNKNOWN")} tone="text-amber-700" />
          <Metric label="Silent triggers" value={r.silent_exclusion_triggers.length} tone="text-amber-700" />
        </div>
        <div className="mt-4 rounded-xl border border-slate-200 bg-surface/80 p-4">
          <h2 className="eyebrow">Explanation</h2>
          <p className="mt-1 whitespace-pre-line text-sm leading-relaxed text-slate-900">{r.final_explanation}</p>
        </div>
      </section>

      <SectionNav r={r} />

      <Panel id="set-h" title="Silent exclusion triggers" count={r.silent_exclusion_triggers.length}>
        {r.silent_exclusion_triggers.length === 0 ? (
          <p className="text-sm text-slate-600">No silent exclusion triggers were detected.</p>
        ) : (
          <>
            <p className="mb-3 text-sm text-slate-700">
              Hidden contradictions where a patient appears to meet inclusion criteria but other findings may exclude them.
            </p>
            <div className="space-y-4">
              {r.silent_exclusion_triggers.map((t) => (
                <SilentExclusionCard key={t.trigger_id} trigger={t} onOpenEvidence={openEvidence} />
              ))}
            </div>
          </>
        )}
      </Panel>

      <Panel id="triggered-h" title="Triggered exclusions" count={triggered.length}>
        {triggered.length === 0 ? (
          <p className="text-sm text-slate-600">No exclusion criterion was triggered.</p>
        ) : (
          <ul className="space-y-3 text-sm">
            {triggered.map((e) => (
              <li key={e.criterion_id} className="rounded-md border border-red-300 bg-red-50 p-3 text-red-950">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-xs font-semibold">{e.criterion_id}</span>
                  <StatusBadge status={e.status} />
                </div>
                <p className="mt-1 font-medium">{e.original_text}</p>
                <p className="mt-1">
                  <span className="font-semibold">Patient value:</span> {e.patient_value ?? "Not available"}
                </p>
                <p className="mt-1">{e.explanation}</p>
                <div className="mt-2">
                  <EvidenceLinks refs={e.evidence_references} context={e.criterion_id} onOpen={openEvidence} />
                </div>
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <CriteriaTable title="Inclusion criteria" evaluations={r.inclusion_results} onOpenEvidence={openEvidence} />
      <CriteriaTable title="Exclusion criteria" evaluations={r.exclusion_results} onOpenEvidence={openEvidence} />

      <Panel id="values-h" title="Patient values used" count={valuesUsed.length}>
        {valuesUsed.length === 0 ? (
          <p className="text-sm text-slate-600">No patient values were recorded for this result.</p>
        ) : (
          <div className="-mx-4 max-h-[60vh] overflow-auto sm:mx-0">
            <table className="w-full min-w-[36rem] text-left text-sm">
              <thead className="sticky top-0 z-10 bg-surface text-xs uppercase text-slate-600 shadow-sm">
                <tr>
                  <th scope="col" className="px-4 py-2 sm:pl-0">Attribute</th>
                  <th scope="col" className="px-4 py-2 text-right">Value used</th>
                  <th scope="col" className="px-4 py-2">Observed</th>
                  <th scope="col" className="px-4 py-2">Source (as entered)</th>
                  <th scope="col" className="px-4 py-2">Criteria</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200">
                {valuesUsed.map((v, i) => (
                  <tr key={`${v.attribute}-${i}`} className="even:bg-slate-50/60">
                    <td className="px-4 py-2 font-medium sm:pl-0">{v.label}</td>
                    <td className="px-4 py-2 text-right tabular-nums">
                      {v.value}
                      {v.status !== "ok" ? <span className="ml-2 rounded bg-amber-100 px-1.5 text-xs text-amber-900">{humanize(v.status)}</span> : null}
                    </td>
                    <td className="px-4 py-2 text-slate-600">{v.observed_at ? formatDate(v.observed_at) : "—"}</td>
                    <td className="px-4 py-2 text-slate-600">{v.source ?? "—"}</td>
                    <td className="px-4 py-2 font-mono text-xs">{v.criterion_ids.length > 0 ? v.criterion_ids.join(", ") : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <div className="grid gap-6 lg:grid-cols-2">
        <Panel id="missing-h" title="Missing information" count={r.missing_information.length}>
          {r.missing_information.length === 0 ? (
            <p className="text-sm text-slate-600">No missing information reported.</p>
          ) : (
            <ul className="space-y-2 text-sm">
              {r.missing_information.map((m, i) => (
                <li key={i} className="rounded-md border border-amber-300 bg-amber-50 p-3 text-amber-950">
                  <p className="font-semibold">Missing: {attributeLabel(m.attribute)}</p>
                  <p>{m.reason}</p>
                  {m.criterion_ids.length > 0 ? <p className="mt-1 font-mono text-xs">Affects {m.criterion_ids.join(", ")}</p> : null}
                </li>
              ))}
            </ul>
          )}
        </Panel>

        <Panel id="conflicts-h" title="Unresolved conflicts" count={r.unresolved_conflicts.length}>
          {r.unresolved_conflicts.length === 0 ? (
            <p className="text-sm text-slate-600">No unresolved conflicts.</p>
          ) : (
            <ul className="space-y-2 text-sm">
              {r.unresolved_conflicts.map((c, i) => (
                <li key={i} className="rounded-md border border-slate-300 p-3">
                  <p className="font-semibold">{humanize(c.conflict_type)}</p>
                  <p className="text-slate-800">{c.description}</p>
                  {c.criterion_ids.length > 0 ? <p className="mt-1 font-mono text-xs">Criteria: {c.criterion_ids.join(", ")}</p> : null}
                  {c.attributes.length > 0 ? <p className="text-xs text-slate-600">Attributes: {c.attributes.join(", ")}</p> : null}
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>

      {r.prior_assessment ? (
        <Panel id="memory-h" title="Compared with previous assessment">
          <p className="text-sm text-slate-800">
            The previous assessment of this patient for this trial (profile version {r.prior_assessment.patient_profile_version}
            {r.prior_assessment.analyzed_at ? `, ${formatDateTime(r.prior_assessment.analyzed_at)}` : ""}) was{" "}
            <span className="font-semibold">{humanize(r.prior_assessment.overall_status ?? "unknown")}</span>.{" "}
            <Link to={ROUTES.results(r.prior_assessment.run_id)} className="link">Open it</Link>
          </p>
          {r.prior_assessment.changed_criteria.length > 0 ? (
            <ul className="mt-2 list-disc pl-5 font-mono text-xs">
              {r.prior_assessment.changed_criteria.map((c) => (
                <li key={c}>{c}</li>
              ))}
            </ul>
          ) : (
            <p className="mt-1 text-sm text-slate-600">No criterion outcome changed.</p>
          )}
        </Panel>
      ) : null}

      <Panel id="notes-h" title="Reviewer notes" count={r.reviewer_notes.length}>
        {r.reviewer_notes.length === 0 ? (
          <p className="text-sm text-slate-600">No reviewer notes.</p>
        ) : (
          <ul className="list-disc space-y-1 pl-5 text-sm">
            {r.reviewer_notes.map((n, i) => (
              <li key={i}>{n}</li>
            ))}
          </ul>
        )}
      </Panel>

      <Panel id="decisive-h" title="Protocol evidence behind the decision" count={r.decisive_evidence.length}>
        {r.decisive_evidence.length === 0 ? (
          <p className="text-sm text-slate-600">No decisive evidence recorded.</p>
        ) : (
          <ol className="space-y-3 text-sm">
            {r.decisive_evidence.map((e, i) => (
              <li key={`${e.criterion_id}-${i}`} className="rounded-md border border-slate-200 p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-xs font-semibold">{e.criterion_id}</span>
                  <StatusBadge status={e.status} />
                </div>
                <p className="mt-1">
                  <span className="font-semibold">Expected:</span> <code className="break-words">{e.expected_condition}</code>
                </p>
                <p>
                  <span className="font-semibold">Patient value:</span> {e.patient_value ?? "Not available"}
                </p>
                <div className="mt-2">
                  <EvidenceLinks refs={e.evidence_references} context={e.criterion_id} onOpen={openEvidence} />
                </div>
              </li>
            ))}
          </ol>
        )}
      </Panel>

      {externalRefs.length > 0 ? (
        <Panel id="external-h" title="External references (web search)" count={externalRefs.length}>
          <p className="mb-3 text-sm text-slate-700">
            Context for ambiguous protocol wording. Only the criterion text was searched, never patient data, and these
            references did not affect the result.
          </p>
          <ul className="space-y-3 text-sm">
            {externalRefs.map((x, i) => (
              <li key={`${x.criterion_id}-${i}`} className="rounded-md border border-slate-200 p-3">
                <p>
                  <span className="mr-2 font-mono text-xs font-semibold">{x.criterion_id}</span>
                  <a href={x.url} target="_blank" rel="noopener noreferrer nofollow" className="link break-words">{x.title}</a>
                </p>
                {x.snippet ? <p className="mt-1 text-slate-700">{x.snippet}</p> : null}
                <p className="mt-1 break-all text-xs text-slate-500">{x.url}</p>
              </li>
            ))}
          </ul>
        </Panel>
      ) : null}

      <div id="audit" className="scroll-mt-32">
        <AuditTrail runId={d.run_id} />
      </div>

      <ReviewNotice notice={notice} />

      <div className="flex flex-wrap gap-2">
        <Link to={ROUTES.dashboard} className="btn-secondary">Back to dashboard</Link>
        <Link to={ROUTES.editPatient(d.patient_id)} className="btn-secondary">Update patient data</Link>
      </div>

      {evidence ? <EvidencePanel trialId={d.trial_id} target={evidence} onClose={closeEvidence} /> : null}
    </div>
  );
}
