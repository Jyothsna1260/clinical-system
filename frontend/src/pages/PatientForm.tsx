import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { createPatient, errorMessage, getPatient, listTrials, updatePatient } from "../api/client";
import { AssessmentLauncher } from "../components/AssessmentLauncher";
import { DataQualityFlags } from "../components/DataQualityFlags";
import { PlusIcon } from "../components/Icons";
import { ErrorState, InlineError, LoadingState } from "../components/States";
import { WorkflowSteps } from "../components/WorkflowSteps";
import { formatDateTime } from "../lib/format";
import {
  emptyDiagnosis,
  emptyForm,
  emptyHistory,
  emptyLab,
  emptyMedication,
  formToProfile,
  missingRecommended,
  parseProfileJson,
  profileToForm,
  type DiagnosisRow,
  type HistoryRow,
  type LabRow,
  type MedicationRow,
  type PatientFormState,
  type PresentChoice,
} from "../lib/patientForm";
import { useAsync } from "../lib/useAsync";
import type { PatientOut, Sex } from "../types";
import { ROUTES } from "../lib/routes";

function MissingNote({ id, show, text }: { id: string; show: boolean; text: string }) {
  if (!show) return null;
  return (
    <p id={id} className="mt-1 text-xs font-semibold text-amber-900">
      ⚠ {text}
    </p>
  );
}

function Section({ title, description, children, action }: { title: string; description?: string; children: ReactNode; action?: ReactNode }) {
  const id = `sec-${title.replace(/\W+/g, "-").toLowerCase()}`;
  return (
    <section className="card p-4 sm:p-6" aria-labelledby={id}>
      <div className="mb-4 flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 id={id} className="section-title">{title}</h2>
          {description ? <p className="text-sm text-slate-600">{description}</p> : null}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

function AddButton({ onClick, label }: { onClick: () => void; label: string }) {
  return (
    <button type="button" onClick={onClick} className="btn-secondary py-1.5 text-sm">
      <PlusIcon /> {label}
    </button>
  );
}

function RemoveButton({ onClick, label }: { onClick: () => void; label: string }) {
  return (
    <button type="button" onClick={onClick} className="btn-danger-ghost text-sm" aria-label={label}>
      Remove
    </button>
  );
}

export default function PatientForm() {
  const { id } = useParams<{ id: string }>();
  const isEdit = Boolean(id);

  const existing = useAsync<PatientOut | null>(() => (id ? getPatient(id) : Promise.resolve(null)), [id]);
  const trials = useAsync(() => listTrials(), []);

  const [form, setForm] = useState<PatientFormState>(emptyForm);
  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saved, setSaved] = useState<PatientOut | null>(null);
  const [showJson, setShowJson] = useState(false);
  const [jsonText, setJsonText] = useState("");
  const [jsonError, setJsonError] = useState<string | null>(null);
  const [jsonOk, setJsonOk] = useState<string | null>(null);

  useEffect(() => {
    if (existing.data) setForm(profileToForm(existing.data.label, existing.data.profile));
    else if (!id) setForm(emptyForm());
    setSaved(null);
  }, [existing.data, id]);

  const set = <K extends keyof PatientFormState>(key: K, value: PatientFormState[K]) => setForm((f) => ({ ...f, [key]: value }));

  const updateRow = <T extends { key: string }>(list: "labs" | "diagnoses" | "medications" | "history", key: string, patch: Partial<T>) =>
    setForm((f) => ({ ...f, [list]: (f[list] as unknown as T[]).map((r) => (r.key === key ? { ...r, ...patch } : r)) }));
  const removeRow = (list: "labs" | "diagnoses" | "medications" | "history", key: string) =>
    setForm((f) => ({ ...f, [list]: (f[list] as { key: string }[]).filter((r) => r.key !== key) }));

  const missing = missingRecommended(form);

  const onLoadJson = () => {
    setJsonError(null);
    setJsonOk(null);
    try {
      const parsed = parseProfileJson(jsonText);
      setForm(profileToForm(parsed.label ?? form.label, parsed.profile));
      const { ignored } = parsed;
      setJsonOk(
        ignored.length > 0
          ? `Profile loaded into the form. Not imported (unrecognised fields): ${ignored.join(", ")}. Review the fields, then save.`
          : "Profile loaded into the form. Review the fields, then save.",
      );
    } catch (e) {
      setJsonError(e instanceof Error ? e.message : "Could not parse JSON.");
    }
  };

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setSaveError(null);
    const errs: string[] = [];
    if (!form.label.trim()) errs.push("Label is required.");
    const built = formToProfile(form);
    errs.push(...built.errors);
    setErrors(errs);
    if (errs.length > 0 || !built.profile) return;
    setSaving(true);
    try {
      // After the first create, further saves PATCH the same patient (new version).
      const targetId = id ?? saved?.id;
      const out = targetId
        ? await updatePatient(targetId, { label: form.label.trim(), profile: built.profile })
        : await createPatient({ label: form.label.trim(), profile: built.profile });
      setSaved(out);
      setForm(profileToForm(out.label, out.profile));
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (err) {
      setSaveError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  if (isEdit && existing.loading) return <LoadingState label="Loading patient…" />;
  if (isEdit && existing.error) return <ErrorState error={existing.error} title="Could not load patient" onRetry={existing.reload} />;

  const current = saved ?? existing.data;

  return (
    <div className="space-y-6">
      <div>
        <WorkflowSteps current={2} />
        <h1 className="page-title mt-3">{isEdit ? "Edit patient" : "New patient"}</h1>
        <p className="text-sm text-slate-600">
          {isEdit && current
            ? `Current version ${current.version} (versions: ${current.versions.join(", ")}). Saving creates a new version; past assessments keep the version they used.`
            : "Enter structured patient data. Leave unknown fields empty — they are reported as missing rather than guessed."}
        </p>
      </div>

      {saved ? (
        <section aria-labelledby="saved-h" aria-live="polite" className="card space-y-4 border-emerald-300 p-4 sm:p-6">
          <h2 id="saved-h" className="section-title">
            Saved “{saved.label}” — version {saved.version}
          </h2>
          <p className="text-xs text-slate-600">Updated {formatDateTime(saved.updated_at)}</p>
          <div>
            <h3 className="mb-2 font-semibold text-slate-900">Data quality flags</h3>
            <DataQualityFlags flags={saved.data_quality_flags} />
          </div>
          <div>
            <h3 className="mb-2 font-semibold text-slate-900">Run assessment</h3>
            {trials.loading ? <LoadingState label="Loading trials…" /> : null}
            {trials.error ? <ErrorState error={trials.error} title="Could not load trials" onRetry={trials.reload} /> : null}
            {trials.data && trials.data.length === 0 ? (
              <p className="text-sm text-slate-600">
                No trials yet. <Link to={ROUTES.uploadTrial} className="link">Upload a protocol</Link> first.
              </p>
            ) : null}
            {trials.data && trials.data.length > 0 ? (
              <div className="max-w-xl">
                <AssessmentLauncher trials={trials.data} fixedPatientId={saved.id} idPrefix="pf" />
              </div>
            ) : null}
          </div>
        </section>
      ) : null}

      {!saved && current && current.data_quality_flags.length > 0 ? (
        <section aria-labelledby="dq-h" className="card p-4 sm:p-6">
          <h2 id="dq-h" className="mb-2 font-semibold">Data quality flags (version {current.version})</h2>
          <DataQualityFlags flags={current.data_quality_flags} />
        </section>
      ) : null}

      <div className="card p-4 sm:p-6">
        <button type="button" className="btn-secondary" aria-expanded={showJson} aria-controls="json-panel" onClick={() => setShowJson((v) => !v)}>
          {showJson ? "Hide JSON import" : "Load JSON"}
        </button>
        {showJson ? (
          <div id="json-panel" className="mt-4 space-y-2">
            <label htmlFor="json-input" className="label">
              Paste a PatientProfileInput JSON (or {"{"}"label", "profile"{"}"})
            </label>
            <textarea
              id="json-input"
              rows={8}
              className="input font-mono text-xs"
              value={jsonText}
              onChange={(e) => setJsonText(e.target.value)}
              placeholder='{"demographics": {"age": 54, "sex": "female"}, "labs": [{"name": "eGFR", "value": 72, "unit": "mL/min/1.73m2", "observed_at": "2026-09-01"}], "as_of": "2026-10-01"}'
              spellCheck={false}
            />
            <button type="button" className="btn-secondary" onClick={onLoadJson} disabled={!jsonText.trim()}>
              Parse and load into form
            </button>
            <InlineError message={jsonError} />
            {jsonOk ? <p role="status" className="text-sm text-emerald-900">{jsonOk}</p> : null}
          </div>
        ) : null}
      </div>

      <form onSubmit={(e) => void onSubmit(e)} className="space-y-6" noValidate aria-busy={saving}>
        {missing.length > 0 ? (
          <div role="status" className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950">
            <p className="font-semibold">Missing recommended information</p>
            <p className="mt-1">Missing: {missing.join("; ")}</p>
            <p className="mt-1 text-xs">You can still save; missing values are reported as such in the assessment.</p>
          </div>
        ) : null}

        <Section title="Patient" description="A non-identifying label (do not enter names or MRNs in this prototype).">
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="label" className="label">Label (required)</label>
              <input id="label" className={`input ${!form.label.trim() ? "input-invalid" : ""}`} maxLength={200} value={form.label}
                aria-describedby="label-missing" onChange={(e) => set("label", e.target.value)} />
              <MissingNote id="label-missing" show={!form.label.trim()} text="Missing: label" />
            </div>
            <div>
              <label htmlFor="as_of" className="label">Assessment date (as of)</label>
              <input id="as_of" type="date" className={`input ${!form.as_of ? "input-invalid" : ""}`} value={form.as_of}
                aria-describedby="as-of-help" onChange={(e) => set("as_of", e.target.value)} />
              <p id="as-of-help" className="mt-1 text-xs text-slate-600">
                {form.as_of ? "Reference date for staleness checks." : "⚠ Missing: assessment date — today will be used."}
              </p>
            </div>
          </div>
        </Section>

        <Section title="Demographics">
          <div className="grid gap-4 sm:grid-cols-3">
            <div>
              <label htmlFor="age" className="label">Age (years)</label>
              <input id="age" type="number" inputMode="decimal" min={0} max={130} step="any"
                className={`input ${!form.age ? "input-invalid" : ""}`} value={form.age}
                aria-describedby="age-missing" onChange={(e) => set("age", e.target.value)} />
              <MissingNote id="age-missing" show={!form.age.trim()} text="Missing: age" />
            </div>
            <div>
              <label htmlFor="sex" className="label">Sex</label>
              <select id="sex" className={`input ${!form.sex ? "input-invalid" : ""}`} value={form.sex}
                aria-describedby="sex-missing" onChange={(e) => set("sex", e.target.value as "" | Sex)}>
                <option value="">Not recorded</option>
                <option value="male">Male</option>
                <option value="female">Female</option>
                <option value="other">Other</option>
                <option value="unknown">Unknown</option>
              </select>
              <MissingNote id="sex-missing" show={!form.sex} text="Missing: sex" />
            </div>
            <div>
              <label htmlFor="dob" className="label">Date of birth <span className="font-normal text-slate-500">(optional)</span></label>
              <input id="dob" type="date" className="input" value={form.date_of_birth} onChange={(e) => set("date_of_birth", e.target.value)} />
            </div>
          </div>
        </Section>

        <Section
          title="Laboratory results"
          description="Value must be numeric. Unit and observation date are needed for conversion and staleness checks."
          action={<AddButton label="Add lab" onClick={() => set("labs", [...form.labs, emptyLab()])} />}
        >
          {form.labs.length === 0 ? <p className="text-sm text-slate-600">No labs entered. ⚠ Missing: labs</p> : null}
          <ul className="space-y-3">
            {form.labs.map((r, i) => {
              const p = `lab-${r.key}`;
              const named = r.name.trim() || `lab ${i + 1}`;
              const unitMissing = !r.unit.trim();
              const dateMissing = !r.observed_at;
              return (
                <li key={r.key} className="rounded-md border border-slate-200 p-3">
                  <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
                    <div>
                      <label htmlFor={`${p}-name`} className="label">Name</label>
                      <input id={`${p}-name`} className="input" value={r.name} placeholder="e.g. eGFR"
                        onChange={(e) => updateRow<LabRow>("labs", r.key, { name: e.target.value })} />
                    </div>
                    <div>
                      <label htmlFor={`${p}-value`} className="label">Value</label>
                      <input id={`${p}-value`} type="number" step="any" inputMode="decimal" className="input" value={r.value}
                        onChange={(e) => updateRow<LabRow>("labs", r.key, { value: e.target.value })} />
                    </div>
                    <div>
                      <label htmlFor={`${p}-unit`} className="label">Unit</label>
                      <input id={`${p}-unit`} className={`input ${unitMissing ? "input-invalid" : ""}`} value={r.unit} placeholder="e.g. mL/min/1.73m2"
                        aria-describedby={`${p}-flags`} onChange={(e) => updateRow<LabRow>("labs", r.key, { unit: e.target.value })} />
                    </div>
                    <div>
                      <label htmlFor={`${p}-date`} className="label">Observed on</label>
                      <input id={`${p}-date`} type="date" className={`input ${dateMissing ? "input-invalid" : ""}`} value={r.observed_at}
                        aria-describedby={`${p}-flags`} onChange={(e) => updateRow<LabRow>("labs", r.key, { observed_at: e.target.value })} />
                    </div>
                    <div>
                      <label htmlFor={`${p}-ref`} className="label">Reference range</label>
                      <input id={`${p}-ref`} className="input" value={r.reference_range} placeholder="optional"
                        onChange={(e) => updateRow<LabRow>("labs", r.key, { reference_range: e.target.value })} />
                    </div>
                  </div>
                  <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
                    <p id={`${p}-flags`} className="text-xs font-semibold text-amber-900">
                      {[unitMissing ? "unit missing" : null, dateMissing ? "date missing" : null].filter(Boolean).length > 0
                        ? `⚠ ${[unitMissing ? "unit missing" : null, dateMissing ? "date missing" : null].filter(Boolean).join(", ")}`
                        : ""}
                    </p>
                    <RemoveButton label={`Remove ${named}`} onClick={() => removeRow("labs", r.key)} />
                  </div>
                </li>
              );
            })}
          </ul>
        </Section>

        <Section title="Diagnoses" action={<AddButton label="Add diagnosis" onClick={() => set("diagnoses", [...form.diagnoses, emptyDiagnosis()])} />}>
          {form.diagnoses.length === 0 ? <p className="text-sm text-slate-600">No diagnoses entered.</p> : null}
          <ul className="space-y-3">
            {form.diagnoses.map((r, i) => {
              const p = `dx-${r.key}`;
              return (
                <li key={r.key} className="rounded-md border border-slate-200 p-3">
                  <div className="grid gap-3 sm:grid-cols-3">
                    <div>
                      <label htmlFor={`${p}-name`} className="label">Diagnosis</label>
                      <input id={`${p}-name`} className="input" value={r.name}
                        onChange={(e) => updateRow<DiagnosisRow>("diagnoses", r.key, { name: e.target.value })} />
                    </div>
                    <div>
                      <label htmlFor={`${p}-code`} className="label">Code <span className="font-normal text-slate-500">(optional)</span></label>
                      <input id={`${p}-code`} className="input" value={r.code} placeholder="e.g. ICD-10 E11.9"
                        onChange={(e) => updateRow<DiagnosisRow>("diagnoses", r.key, { code: e.target.value })} />
                    </div>
                    <div>
                      <label htmlFor={`${p}-date`} className="label">Documented on</label>
                      <input id={`${p}-date`} type="date" className="input" value={r.documented_at}
                        onChange={(e) => updateRow<DiagnosisRow>("diagnoses", r.key, { documented_at: e.target.value })} />
                    </div>
                  </div>
                  <div className="mt-2 flex justify-end">
                    <RemoveButton label={`Remove diagnosis ${r.name || i + 1}`} onClick={() => removeRow("diagnoses", r.key)} />
                  </div>
                </li>
              );
            })}
          </ul>
        </Section>

        <Section title="Medications" action={<AddButton label="Add medication" onClick={() => set("medications", [...form.medications, emptyMedication()])} />}>
          {form.medications.length === 0 ? <p className="text-sm text-slate-600">No medications entered.</p> : null}
          <ul className="space-y-3">
            {form.medications.map((r, i) => {
              const p = `med-${r.key}`;
              return (
                <li key={r.key} className="rounded-md border border-slate-200 p-3">
                  <div className="grid gap-3 sm:grid-cols-3">
                    <div>
                      <label htmlFor={`${p}-name`} className="label">Medication</label>
                      <input id={`${p}-name`} className="input" value={r.name}
                        onChange={(e) => updateRow<MedicationRow>("medications", r.key, { name: e.target.value })} />
                    </div>
                    <div>
                      <label htmlFor={`${p}-start`} className="label">Start date</label>
                      <input id={`${p}-start`} type="date" className="input" value={r.start_date}
                        onChange={(e) => updateRow<MedicationRow>("medications", r.key, { start_date: e.target.value })} />
                    </div>
                    <div>
                      <label htmlFor={`${p}-stop`} className="label">Stop date <span className="font-normal text-slate-500">(empty = ongoing)</span></label>
                      <input id={`${p}-stop`} type="date" className="input" value={r.stop_date}
                        onChange={(e) => updateRow<MedicationRow>("medications", r.key, { stop_date: e.target.value })} />
                    </div>
                  </div>
                  <div className="mt-2 flex justify-end">
                    <RemoveButton label={`Remove medication ${r.name || i + 1}`} onClick={() => removeRow("medications", r.key)} />
                  </div>
                </li>
              );
            })}
          </ul>
        </Section>

        <Section title="History" description="Past or current conditions. Use Unknown when not documented."
          action={<AddButton label="Add history item" onClick={() => set("history", [...form.history, emptyHistory()])} />}>
          {form.history.length === 0 ? <p className="text-sm text-slate-600">No history entered.</p> : null}
          <ul className="space-y-3">
            {form.history.map((r, i) => {
              const p = `hx-${r.key}`;
              return (
                <li key={r.key} className="rounded-md border border-slate-200 p-3">
                  <div className="grid gap-3 sm:grid-cols-[2fr_1fr]">
                    <div>
                      <label htmlFor={`${p}-cond`} className="label">Condition</label>
                      <input id={`${p}-cond`} className="input" value={r.condition}
                        onChange={(e) => updateRow<HistoryRow>("history", r.key, { condition: e.target.value })} />
                    </div>
                    <div>
                      <label htmlFor={`${p}-present`} className="label">Present</label>
                      <select id={`${p}-present`} className="input" value={r.present}
                        onChange={(e) => updateRow<HistoryRow>("history", r.key, { present: e.target.value as PresentChoice })}>
                        <option value="yes">Yes</option>
                        <option value="no">No</option>
                        <option value="unknown">Unknown</option>
                      </select>
                    </div>
                  </div>
                  <div className="mt-2 flex justify-end">
                    <RemoveButton label={`Remove history item ${r.condition || i + 1}`} onClick={() => removeRow("history", r.key)} />
                  </div>
                </li>
              );
            })}
          </ul>
        </Section>

        {errors.length > 0 ? (
          <div role="alert" className="rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-900">
            <p className="font-semibold">Please fix the following before saving:</p>
            <ul className="mt-1 list-disc pl-5">
              {errors.map((e, i) => (
                <li key={i}>{e}</li>
              ))}
            </ul>
          </div>
        ) : null}
        <InlineError message={saveError} />

        <div className="flex flex-wrap gap-2">
          <button type="submit" className="btn-primary" disabled={saving}>
            {saving ? "Saving…" : isEdit || saved ? "Save as new version" : "Create patient"}
          </button>
          <Link to={ROUTES.dashboard} className="btn-secondary">Cancel</Link>
        </div>
      </form>
    </div>
  );
}
