import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { analyze, errorMessage } from "../api/client";
import type { PatientSummary, TrialSummary } from "../types";
import { InlineError } from "./States";
import { useToast } from "./Toast";
import { ROUTES } from "../lib/routes";

/** Select trial (+ patient unless fixed) and start an eligibility run. */
export function AssessmentLauncher({
  trials,
  patients,
  fixedPatientId,
  idPrefix = "assess",
}: {
  trials: TrialSummary[];
  patients?: PatientSummary[];
  fixedPatientId?: string;
  idPrefix?: string;
}) {
  const navigate = useNavigate();
  const { notify } = useToast();
  const readyTrials = trials.filter((t) => t.status === "ready");
  const [trialId, setTrialId] = useState<string>(readyTrials[0]?.id ?? "");
  const [patientId, setPatientId] = useState<string>(fixedPatientId ?? patients?.[0]?.id ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    const pid = fixedPatientId ?? patientId;
    if (!trialId || !pid) {
      setError("Select both a trial and a patient.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const run = await analyze({ trial_id: trialId, patient_id: pid });
      notify("info", "Assessment started", "Six agents are analysing the patient against the protocol.");
      navigate(ROUTES.analysis(run.run_id));
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  };

  return (
    <form onSubmit={(e) => void onSubmit(e)} className="space-y-3" aria-busy={busy}>
      <div>
        <label htmlFor={`${idPrefix}-trial`} className="label">
          Trial protocol
        </label>
        <select id={`${idPrefix}-trial`} className="input" value={trialId} onChange={(e) => setTrialId(e.target.value)} required>
          <option value="">Select a trial…</option>
          {trials.map((t) => (
            <option key={t.id} value={t.id} disabled={t.status !== "ready"}>
              {t.title}
              {t.status !== "ready" ? ` (${t.status})` : ""}
            </option>
          ))}
        </select>
        {trials.length > 0 && readyTrials.length === 0 ? (
          <p className="mt-1 text-xs text-amber-900">
            No trial is ready for analysis yet.
            {trials.some((t) => t.status === "error")
              ? " Protocols marked “error” had no recognisable inclusion or exclusion criteria. Upload a text-based PDF with clearly headed “Inclusion Criteria” and “Exclusion Criteria” sections, or configure an LLM provider for free-form protocols."
              : " Protocols still processing will appear here when ready."}{" "}
            <Link to={ROUTES.uploadTrial} className="link">Upload a protocol</Link>
          </p>
        ) : null}
      </div>
      {fixedPatientId ? null : (
        <div>
          <label htmlFor={`${idPrefix}-patient`} className="label">
            Patient
          </label>
          <select id={`${idPrefix}-patient`} className="input" value={patientId} onChange={(e) => setPatientId(e.target.value)} required>
            <option value="">Select a patient…</option>
            {(patients ?? []).map((p) => (
              <option key={p.id} value={p.id}>
                {p.label} (v{p.version})
              </option>
            ))}
          </select>
        </div>
      )}
      <InlineError message={error} />
      <button type="submit" className="btn-primary w-full py-2.5 sm:w-auto" disabled={busy || !trialId || !(fixedPatientId ?? patientId)}>
        {busy ? "Starting assessment…" : "Run assessment"}
      </button>
    </form>
  );
}
