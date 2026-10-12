import { Fragment, useState } from "react";
import type { CriterionEvaluation, EvidenceReference } from "../types";
import { EvidenceLinks } from "./EvidenceLinks";
import type { EvidenceTarget } from "./EvidencePanel";
import { ChevronIcon } from "./Icons";
import { StatusBadge } from "./StatusBadge";
import { attributeLabel, humanize } from "../lib/format";

// Left-edge color cue per status (the badge text remains the primary signal).
const STRIPE: Record<string, string> = {
  SATISFIED: "border-l-emerald-500",
  NOT_TRIGGERED: "border-l-emerald-500",
  UNSATISFIED: "border-l-red-500",
  TRIGGERED: "border-l-red-500",
  UNKNOWN: "border-l-amber-500",
};

const AGENT: Record<string, string> = {
  inclusion: "Inclusion Matching Agent",
  exclusion: "Exclusion Detection Agent",
};

function Reason({ e }: { e: CriterionEvaluation }) {
  return (
    <div className="space-y-1">
      <p>{e.explanation}</p>
      {e.uncertainty_notes.length > 0 ? (
        <ul className="list-disc space-y-0.5 pl-5 text-amber-900">
          {e.uncertainty_notes.map((n, i) => (
            <li key={i}>
              <span className="font-semibold">Uncertainty:</span> {n}
            </li>
          ))}
        </ul>
      ) : null}
      <p className="text-xs text-slate-600">Method: {humanize(e.comparison_method)}</p>
      {e.requires_human_review ? (
        <p className="text-xs font-semibold text-amber-900">Flagged for human review</p>
      ) : null}
    </div>
  );
}

function Rule({ e }: { e: CriterionEvaluation }) {
  return (
    <div className="space-y-1">
      <p className="text-slate-900">{e.original_text}</p>
      <p className="text-xs text-slate-600">
        <span className="font-semibold">Expected:</span> <code className="break-words">{e.expected_condition}</code>
      </p>
    </div>
  );
}

/** Numbers (with units) are right-aligned so they line up; sentences stay left-aligned. */
function isNumeric(value: string | null | undefined): boolean {
  return !!value && /^[<>≤≥~]?\s*-?\d/.test(value.trim());
}

function PatientValue({ e }: { e: CriterionEvaluation }) {
  return e.patient_value ? (
    <span className="tabular-nums">{e.patient_value}</span>
  ) : (
    <span className="text-slate-500">Not available</span>
  );
}

/** Protocol citations with their text, so the source is readable without opening the page. */
function Citations({
  refs,
  context,
  onOpen,
}: {
  refs: EvidenceReference[];
  context: string;
  onOpen: (t: EvidenceTarget) => void;
}) {
  if (refs.length === 0) return <p className="text-slate-600">No protocol citation was found for this criterion.</p>;
  return (
    <ul className="space-y-2">
      {refs.map((r, i) => (
        <li key={`${r.page}-${i}`} className="rounded-md border border-slate-200 bg-surface p-2.5">
          <div className="flex flex-wrap items-center gap-2 text-xs text-slate-600">
            <span className="font-semibold text-slate-800">Page {r.page}</span>
            <span>{r.source === "retrieval" ? "Retrieved supporting passage" : "Verbatim protocol citation"}</span>
            <button
              type="button"
              className="link ml-auto"
              onClick={() => onOpen({ page: r.page, excerpt: r.excerpt, context })}
            >
              Open page {r.page}
            </button>
          </div>
          <blockquote className="mt-1 border-l-2 border-accent-300 pl-2 text-slate-800">{r.excerpt}</blockquote>
        </li>
      ))}
    </ul>
  );
}

function DetailRow({ e, onOpen }: { e: CriterionEvaluation; onOpen: (t: EvidenceTarget) => void }) {
  return (
    <tr className={`border-l-4 bg-slate-50/70 ${STRIPE[e.status] ?? "border-l-transparent"}`}>
      <td colSpan={6} className="px-4 pb-4 pt-1">
        <div id={`detail-${e.criterion_id}`} className="grid gap-4 text-sm md:grid-cols-2">
          <div className="space-y-3">
            <div>
              <h4 className="eyebrow">Criterion (protocol text)</h4>
              <Rule e={e} />
            </div>
            <div>
              <h4 className="eyebrow">Patient value used</h4>
              <p>
                <PatientValue e={e} />
                {e.attribute ? <span className="text-slate-600"> ({attributeLabel(e.attribute)})</span> : null}
              </p>
            </div>
            <div>
              <h4 className="eyebrow">Reasoning ({AGENT[e.category] ?? "Matching agent"})</h4>
              <Reason e={e} />
            </div>
          </div>
          <div>
            <h4 className="eyebrow">Protocol source</h4>
            <Citations refs={e.evidence_references} context={e.criterion_id} onOpen={onOpen} />
          </div>
        </div>
      </td>
    </tr>
  );
}

export function CriteriaTable({
  title,
  evaluations,
  onOpenEvidence,
}: {
  title: string;
  evaluations: CriterionEvaluation[];
  onOpenEvidence: (t: EvidenceTarget) => void;
}) {
  const slug = title.replace(/\W+/g, "-").toLowerCase();
  const headingId = `tbl-${slug}`;
  const [open, setOpen] = useState<Set<string>>(() => new Set());
  const allOpen = evaluations.length > 0 && open.size === evaluations.length;
  const toggle = (id: string) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <section id={slug} aria-labelledby={headingId} className="card scroll-mt-32 overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 px-4 py-3">
        <h2 id={headingId} className="section-title">
          {title} <span className="text-sm font-normal text-slate-600">({evaluations.length})</span>
        </h2>
        {evaluations.length > 0 ? (
          <button
            type="button"
            className="btn-ghost hidden px-2.5 py-1 text-xs lg:inline-flex"
            onClick={() => setOpen(allOpen ? new Set() : new Set(evaluations.map((e) => e.criterion_id)))}
          >
            {allOpen ? "Collapse all" : "Expand all"}
          </button>
        ) : null}
      </div>
      {evaluations.length === 0 ? (
        <p className="px-4 py-6 text-sm text-slate-600">No {title.toLowerCase()} were evaluated.</p>
      ) : (
        <>
          {/* Desktop / tablet: table with a sticky header; each row expands to its evidence. */}
          <div className="hidden max-h-[75vh] overflow-auto lg:block">
            <table className="w-full table-fixed text-left text-sm">
              <caption className="sr-only">{title}. Expand a row to see its evidence and reasoning.</caption>
              <thead className="sticky top-0 z-10 bg-slate-50 text-xs uppercase tracking-wide text-slate-600 shadow-sm">
                <tr>
                  <th scope="col" className="w-12 px-2 py-2.5">
                    <span className="sr-only">Details</span>
                  </th>
                  <th scope="col" className="w-24 px-4 py-2.5">ID</th>
                  <th scope="col" className="w-40 px-4 py-2.5">Status</th>
                  <th scope="col" className="px-4 py-2.5">Criterion</th>
                  <th scope="col" className="w-48 px-4 py-2.5">Patient value</th>
                  <th scope="col" className="w-36 px-4 py-2.5">Evidence</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200 align-top">
                {evaluations.map((e) => {
                  const isOpen = open.has(e.criterion_id);
                  return (
                    <Fragment key={e.criterion_id}>
                      <tr
                        className={`border-l-4 transition-colors hover:bg-slate-50 ${STRIPE[e.status] ?? "border-l-transparent"}`}
                      >
                        <td className="px-2 py-3">
                          <button
                            type="button"
                            className="btn-ghost p-1.5"
                            aria-expanded={isOpen}
                            aria-controls={`detail-${e.criterion_id}`}
                            aria-label={`${isOpen ? "Hide" : "Show"} evidence and reasoning for ${e.criterion_id}`}
                            onClick={() => toggle(e.criterion_id)}
                          >
                            <ChevronIcon className={`transition-transform ${isOpen ? "rotate-90" : ""}`} />
                          </button>
                        </td>
                        <th scope="row" className="px-4 py-3 font-mono text-xs font-semibold text-slate-800">
                          {e.criterion_id}
                        </th>
                        <td className="px-4 py-3">
                          <StatusBadge status={e.status} />
                          {e.requires_human_review ? (
                            <p className="mt-1 text-xs font-medium text-amber-800">Needs review</p>
                          ) : null}
                        </td>
                        <td className="break-words px-4 py-3">
                          <p className="text-slate-900">{e.original_text}</p>
                          <p className="mt-0.5 line-clamp-2 text-xs text-slate-600">{e.explanation}</p>
                        </td>
                        <td className={`break-words px-4 py-3 ${isNumeric(e.patient_value) ? "text-right" : ""}`}>
                          <PatientValue e={e} />
                        </td>
                        <td className="px-4 py-3">
                          <EvidenceLinks refs={e.evidence_references} context={e.criterion_id} onOpen={onOpenEvidence} />
                        </td>
                      </tr>
                      {isOpen ? <DetailRow e={e} onOpen={onOpenEvidence} /> : null}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
          {/* Mobile: stacked cards (everything shown) */}
          <ul className="divide-y divide-slate-200 lg:hidden">
            {evaluations.map((e) => (
              <li
                key={e.criterion_id}
                className={`space-y-3 border-l-4 px-4 py-4 text-sm ${STRIPE[e.status] ?? "border-l-transparent"}`}
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-mono text-xs font-semibold text-slate-800">{e.criterion_id}</span>
                  <StatusBadge status={e.status} />
                </div>
                <div>
                  <p className="text-xs font-semibold uppercase text-slate-600">Rule</p>
                  <Rule e={e} />
                </div>
                <div>
                  <p className="text-xs font-semibold uppercase text-slate-600">Patient value</p>
                  <p className="break-words">
                    <PatientValue e={e} />
                  </p>
                </div>
                <div>
                  <p className="text-xs font-semibold uppercase text-slate-600">Reason</p>
                  <Reason e={e} />
                </div>
                <div>
                  <p className="mb-1 text-xs font-semibold uppercase text-slate-600">Evidence</p>
                  <EvidenceLinks refs={e.evidence_references} context={e.criterion_id} onOpen={onOpenEvidence} />
                </div>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
