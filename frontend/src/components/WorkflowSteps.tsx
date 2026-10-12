import { Link } from "react-router-dom";
import { ROUTES } from "../lib/routes";
import { CheckCircleIcon } from "./Icons";

const STEPS = [
  { label: "Upload protocol", to: ROUTES.uploadTrial },
  { label: "Add patient", to: ROUTES.newPatient },
  { label: "Run agents", to: null },
  { label: "Review results", to: null },
] as const;

/** Where the user is in the assessment flow: upload a protocol, add a patient, run the agents, review. */
export function WorkflowSteps({ current }: { current: 1 | 2 | 3 | 4 }) {
  return (
    <nav aria-label="Assessment steps" className="print:hidden">
      <ol className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs sm:text-sm">
        {STEPS.map((step, i) => {
          const n = i + 1;
          const state = n < current ? "done" : n === current ? "current" : "upcoming";
          const badge =
            state === "done" ? (
              <CheckCircleIcon className="text-base text-emerald-700" aria-hidden="true" />
            ) : (
              <span
                aria-hidden="true"
                className={`flex h-5 w-5 items-center justify-center rounded-full text-[11px] font-semibold ${
                  state === "current" ? "bg-accent-600 text-white" : "bg-slate-200 text-slate-600"
                }`}
              >
                {n}
              </span>
            );
          const text = (
            <span className={state === "current" ? "font-semibold text-slate-900" : "text-slate-600"}>
              {step.label}
              <span className="sr-only">{state === "done" ? " (completed)" : state === "current" ? " (current step)" : ""}</span>
            </span>
          );
          return (
            <li key={step.label} className="flex items-center gap-2" aria-current={state === "current" ? "step" : undefined}>
              {state !== "current" && step.to ? (
                <Link to={step.to} className="flex items-center gap-1.5 rounded hover:underline">
                  {badge}
                  {text}
                </Link>
              ) : (
                <span className="flex items-center gap-1.5">
                  {badge}
                  {text}
                </span>
              )}
              {n < STEPS.length ? (
                <span aria-hidden="true" className="text-slate-400">
                  →
                </span>
              ) : null}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
