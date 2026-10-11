import type { NodeProgress } from "../types";
import { formatValue, humanize } from "../lib/format";
import { AlertTriangleIcon, CheckCircleIcon, ClockIcon, SpinnerIcon } from "./Icons";

export const NODE_LABELS: Record<string, { label: string; description: string }> = {
  validate_inputs: { label: "Validate inputs", description: "Checks the protocol and patient profile are usable." },
  extract_protocol: { label: "Extract protocol criteria", description: "Loads the structured inclusion/exclusion criteria." },
  normalize_patient: { label: "Normalize patient data", description: "Converts units and flags missing, stale or conflicting values." },
  retrieve_evidence: { label: "Retrieve evidence", description: "Finds supporting protocol passages for each criterion." },
  inclusion_matching: { label: "Inclusion matching", description: "Evaluates every inclusion criterion." },
  exclusion_detection: { label: "Exclusion detection", description: "Evaluates every exclusion criterion." },
  detect_contradictions: { label: "Detect contradictions", description: "Looks for silent exclusion triggers and conflicts." },
  web_research: { label: "Web research", description: "Looks up external definitions for ambiguous criteria (protocol wording only, never patient data)." },
  review_and_decide: { label: "Review and decide", description: "Combines findings into an overall recommendation." },
  persist: { label: "Save results", description: "Stores the result, evidence and audit trail." },
};

const PARALLEL = new Set(["inclusion_matching", "exclusion_detection"]);

function NodeIcon({ status }: { status: string }) {
  switch (status) {
    case "completed":
      return <CheckCircleIcon className="text-xl text-emerald-700" />;
    case "running":
      return <SpinnerIcon className="text-xl text-accent-600" />;
    case "failed":
      return <AlertTriangleIcon className="text-xl text-red-700" />;
    default:
      return <ClockIcon className="text-xl text-slate-500" />;
  }
}

const STATUS_TEXT: Record<string, string> = {
  pending: "Pending",
  running: "Running",
  completed: "Completed",
  failed: "Failed",
};

function SummaryDetails({ summary }: { summary: Record<string, unknown> }) {
  const entries = Object.entries(summary);
  if (entries.length === 0) return null;
  return (
    <dl className="mt-2 grid grid-cols-1 gap-x-4 gap-y-1 text-xs text-slate-700 sm:grid-cols-2">
      {entries.map(([k, v]) => (
        <div key={k} className="flex min-w-0 gap-1">
          <dt className="shrink-0 font-semibold">{k === "duration_ms" ? "Duration" : humanize(k)}:</dt>
          <dd className="min-w-0 break-words">{k === "duration_ms" ? `${formatValue(v)} ms` : formatValue(v) || "None"}</dd>
        </div>
      ))}
    </dl>
  );
}

function Step({ node }: { node: NodeProgress }) {
  const meta = NODE_LABELS[node.node] ?? { label: humanize(node.node), description: "" };
  const text = STATUS_TEXT[node.status] ?? humanize(node.status);
  const tone =
    node.status === "failed"
      ? "border-red-300 bg-red-50"
      : node.status === "running"
        ? "border-accent-200 bg-accent-50"
        : "border-slate-200 bg-surface";
  return (
    <div className={`flex gap-3 rounded-lg border p-3 transition-all duration-300 ${tone} ${node.status === "running" ? "shadow-glow" : ""} ${node.status === "completed" ? "animate-fade-in" : ""}`}>
      <div className="mt-0.5 shrink-0">
        <NodeIcon status={node.status} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline justify-between gap-x-3">
          <p className="font-medium text-slate-900">{meta.label}</p>
          <p className="text-sm font-semibold text-slate-700">{text}</p>
        </div>
        {meta.description ? <p className="text-sm text-slate-600">{meta.description}</p> : null}
        {node.summary ? <SummaryDetails summary={node.summary} /> : null}
      </div>
    </div>
  );
}

export function AgentProgress({ progress }: { progress: NodeProgress[] }) {
  // Group the parallel pair so it renders side by side.
  const items: (NodeProgress | NodeProgress[])[] = [];
  for (const node of progress) {
    if (PARALLEL.has(node.node)) {
      const last = items[items.length - 1];
      if (Array.isArray(last)) last.push(node);
      else items.push([node]);
    } else {
      items.push(node);
    }
  }
  const done = progress.filter((p) => p.status === "completed").length;
  const running = progress.some((p) => p.status === "running");
  const pct = progress.length ? Math.round((done / progress.length) * 100) : 0;
  return (
    <div>
      <div className="mb-4">
        <div className="mb-1.5 flex items-baseline justify-between text-sm">
          <p className="text-slate-600" aria-live="polite">
            {done} of {progress.length} steps completed
          </p>
          <p className="font-semibold tabular-nums text-slate-900">{pct}%</p>
        </div>
        <div
          className="h-2.5 w-full overflow-hidden rounded-full bg-slate-100"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={pct}
          aria-label="Workflow progress"
        >
          <div
            className={`h-full rounded-full bg-gradient-to-r from-accent-500 to-violet-500 transition-[width] duration-500 ease-out ${running ? "animate-progress-stripes" : ""}`}
            style={{
              width: `${Math.max(pct, 4)}%`,
              backgroundImage: running
                ? "linear-gradient(45deg, rgb(255 255 255 / 0.18) 25%, transparent 25%, transparent 50%, rgb(255 255 255 / 0.18) 50%, rgb(255 255 255 / 0.18) 75%, transparent 75%), linear-gradient(to right, rgb(var(--accent-500)), rgb(139 92 246))"
                : undefined,
              backgroundSize: running ? "1rem 1rem, 100% 100%" : undefined,
            }}
          />
        </div>
      </div>
      <ol className="space-y-2">
        {items.map((item, i) =>
          Array.isArray(item) ? (
            <li key={`parallel-${i}`} className="rounded-lg border border-dashed border-accent-300 bg-accent-50/30 p-2">
              <p className="mb-2 px-1 text-xs font-semibold uppercase tracking-wide text-slate-600">
                Runs in parallel
              </p>
              <ol className="grid gap-2 md:grid-cols-2">
                {item.map((n) => (
                  <li key={n.node}>
                    <Step node={n} />
                  </li>
                ))}
              </ol>
            </li>
          ) : (
            <li key={item.node}>
              <Step node={item} />
            </li>
          ),
        )}
      </ol>
    </div>
  );
}
