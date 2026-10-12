import type { Criterion } from "../types";
import { formatPercent } from "../lib/format";
import { criterionRuleSummary } from "../lib/rules";
import { AlertTriangleIcon } from "./Icons";

function CriterionCard({ c }: { c: Criterion }) {
  return (
    <li className={`rounded-md border p-3 ${c.requires_human_review ? "border-amber-400 bg-amber-50/60" : "border-slate-200 bg-surface"}`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-xs font-semibold text-slate-800">{c.criterion_id}</span>
        <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-700">p. {c.source_page}</span>
        <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-700">
          Confidence {formatPercent(c.extraction_confidence)}
        </span>
        <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-700">
          {c.extraction_method === "llm" ? "LLM extraction" : "Rule-based extraction"}
        </span>
        {c.requires_human_review ? (
          <span className="inline-flex items-center gap-1 rounded-full border border-amber-400 bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-950">
            <AlertTriangleIcon /> Needs review
          </span>
        ) : null}
      </div>
      <p className="mt-2 text-sm text-slate-900">{c.original_text}</p>
      <p className="mt-1 text-xs text-slate-700">
        <span className="font-semibold">Normalized rule:</span> <code className="break-words">{criterionRuleSummary(c)}</code>
      </p>
      {c.required_attributes.length > 0 ? (
        <p className="mt-1 text-xs text-slate-600">
          <span className="font-semibold">Requires:</span> {c.required_attributes.join(", ")}
        </p>
      ) : null}
      {c.requires_human_review && c.review_reasons.length > 0 ? (
        <ul className="mt-2 list-disc pl-5 text-xs text-amber-950">
          {c.review_reasons.map((r, i) => (
            <li key={i}>{r}</li>
          ))}
        </ul>
      ) : null}
    </li>
  );
}

export function CriteriaPreview({ criteria }: { criteria: Criterion[] }) {
  const groups: { title: string; items: Criterion[] }[] = [
    { title: "Inclusion criteria", items: criteria.filter((c) => c.category === "inclusion") },
    { title: "Exclusion criteria", items: criteria.filter((c) => c.category === "exclusion") },
  ];
  const review = criteria.filter((c) => c.requires_human_review).length;
  return (
    <div className="space-y-6">
      <p className="text-sm text-slate-700">
        {criteria.length} criteria extracted
        {review > 0 ? `; ${review} flagged as needing review.` : "; none flagged for review."}
      </p>
      {groups.map((g) => (
        <section key={g.title} aria-label={g.title}>
          <h3 className="mb-2 font-semibold text-slate-900">
            {g.title} <span className="font-normal text-slate-600">({g.items.length})</span>
          </h3>
          {g.items.length === 0 ? (
            <p className="text-sm text-slate-600">None extracted.</p>
          ) : (
            <ul className="space-y-2">
              {g.items.map((c) => (
                <CriterionCard key={c.criterion_id} c={c} />
              ))}
            </ul>
          )}
        </section>
      ))}
    </div>
  );
}
