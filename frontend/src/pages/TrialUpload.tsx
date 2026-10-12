import { useState, type ChangeEvent, type DragEvent, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { getHealth, parseApiError, uploadTrial } from "../api/client";
import { CriteriaPreview } from "../components/CriteriaPreview";
import { FileIcon, UploadIcon } from "../components/Icons";
import { ReviewNotice } from "../components/ReviewNotice";
import { StatusBadge } from "../components/StatusBadge";
import { useToast } from "../components/Toast";
import { WorkflowSteps } from "../components/WorkflowSteps";
import type { TrialDetail } from "../types";
import { humanize } from "../lib/format";
import { useAsync } from "../lib/useAsync";
import { ROUTES } from "../lib/routes";

/** Used until /api/health reports the server's limit (the server enforces it either way). */
const DEFAULT_MAX_MB = 20;

function errorHints(maxMb: number, maxPages: number | undefined): Record<string, string> {
  return {
    INVALID_FILE_TYPE: "The file is not a valid PDF. Upload the protocol as a PDF document.",
    UNREADABLE_PDF: "The PDF could not be read (it may be scanned, encrypted or corrupted). Try a text-based PDF export.",
    FILE_TOO_LARGE: `The file exceeds the ${maxMb} MB limit.`,
    TOO_MANY_PAGES: `The PDF has more pages than the ${maxPages ?? "allowed"}-page limit. Upload the eligibility section or a shorter protocol.`,
    EMPTY_FILE: "The uploaded file is empty.",
  };
}

interface UploadError {
  code: string;
  message: string;
}

function validateFile(file: File, maxMb: number): string | null {
  const isPdf = file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
  if (!isPdf) return "Only PDF files are accepted.";
  if (file.size === 0) return "The selected file is empty.";
  if (file.size > maxMb * 1024 * 1024) return `The file is ${(file.size / 1024 / 1024).toFixed(1)} MB; the limit is ${maxMb} MB.`;
  return null;
}

export default function TrialUpload() {
  const { notify } = useToast();
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [clientError, setClientError] = useState<string | null>(null);
  const [apiError, setApiError] = useState<UploadError | null>(null);
  const [trial, setTrial] = useState<TrialDetail | null>(null);
  const health = useAsync(getHealth, []);
  const maxMb = health.data?.max_upload_mb ?? DEFAULT_MAX_MB;
  const hints = errorHints(maxMb, health.data?.max_pdf_pages);

  const pick = (f: File | null | undefined) => {
    setApiError(null);
    setTrial(null);
    if (!f) return;
    const err = validateFile(f, maxMb);
    setClientError(err);
    setFile(err ? null : f);
  };

  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragOver(false);
    pick(e.dataTransfer.files?.[0]);
  };

  const onChange = (e: ChangeEvent<HTMLInputElement>) => {
    pick(e.target.files?.[0]);
    e.target.value = "";
  };

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!file) {
      setClientError("Choose a PDF protocol to upload.");
      return;
    }
    setBusy(true);
    setApiError(null);
    setProgress(0);
    try {
      const out = await uploadTrial(file, title || null, (ev) => {
        if (ev.total) setProgress(Math.round((ev.loaded / ev.total) * 100));
      });
      setTrial(out);
      notify("success", "Protocol uploaded", `${out.criteria.length} criteria extracted from ${out.title}.`);
      setFile(null);
      setTitle("");
    } catch (err) {
      const parsed = parseApiError(err);
      setApiError({ code: parsed.code, message: parsed.message });
    } finally {
      setBusy(false);
      setProgress(null);
    }
  };

  const uploadDone = progress !== null && progress >= 100;

  return (
    <div className="space-y-6">
      <div>
        <WorkflowSteps current={1} />
        <h1 className="page-title mt-3">Upload trial protocol</h1>
        <p className="text-sm text-slate-600">
          Upload a protocol PDF (max {maxMb} MB). Inclusion and exclusion criteria are extracted for review.
        </p>
      </div>

      <form onSubmit={(e) => void onSubmit(e)} className="card space-y-4 p-4 sm:p-6" aria-busy={busy}>
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={onDrop}
          className={`flex flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed px-4 py-10 text-center transition-all duration-200 ${
            dragOver ? "scale-[1.01] border-accent-500 bg-accent-50" : "border-slate-300 bg-slate-50 hover:border-accent-300"
          }`}
        >
          <span className={`flex h-14 w-14 items-center justify-center rounded-2xl bg-accent-50 text-accent-700 transition-transform ${dragOver ? "-translate-y-1 scale-110" : ""}`}>
            <UploadIcon className="text-2xl" />
          </span>
          <p className="text-sm text-slate-700">Drag and drop a PDF here, or</p>
          <label htmlFor="protocol-file" className="btn-secondary cursor-pointer focus-within:ring-2 focus-within:ring-accent-600">
            Choose PDF file
            <input
              id="protocol-file"
              type="file"
              accept="application/pdf,.pdf"
              className="sr-only"
              onChange={onChange}
              aria-describedby="file-help"
            />
          </label>
          <p id="file-help" className="text-xs text-slate-600">PDF only, up to {maxMb} MB.</p>
          {file ? (
            <p className="flex items-center gap-2 text-sm font-medium text-slate-900">
              <FileIcon /> {file.name} <span className="font-normal text-slate-600">({(file.size / 1024 / 1024).toFixed(2)} MB)</span>
            </p>
          ) : null}
        </div>
        {clientError ? (
          <p role="alert" className="rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-900">{clientError}</p>
        ) : null}

        <div>
          <label htmlFor="trial-title" className="label">
            Trial title <span className="font-normal text-slate-500">(optional — defaults to the file name)</span>
          </label>
          <input id="trial-title" className="input" maxLength={300} value={title} onChange={(e) => setTitle(e.target.value)} />
        </div>

        {progress !== null ? (
          <div aria-live="polite">
            <div className="mb-1 flex justify-between text-xs text-slate-700">
              <span>{uploadDone ? "Uploaded — extracting criteria…" : "Uploading…"}</span>
              <span>{progress}%</span>
            </div>
            <div
              role="progressbar"
              aria-label="Upload progress"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={progress}
              className="h-2 w-full overflow-hidden rounded-full bg-slate-200"
            >
              <div className="h-full rounded-full bg-gradient-to-r from-accent-500 to-violet-500 transition-all" style={{ width: `${progress}%` }} />
            </div>
          </div>
        ) : null}

        {apiError ? (
          <div role="alert" className="rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-900">
            <p className="font-semibold">Upload failed ({apiError.code})</p>
            <p className="mt-1">{apiError.message}</p>
            {hints[apiError.code] ? <p className="mt-1">{hints[apiError.code]}</p> : null}
          </div>
        ) : null}

        <button type="submit" className="btn-primary" disabled={busy || !file}>
          {busy ? "Uploading…" : "Upload and extract"}
        </button>
      </form>

      {trial ? (
        <section aria-labelledby="extracted-h" className="card space-y-4 p-4 sm:p-6">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <h2 id="extracted-h" className="section-title break-words">{trial.title}</h2>
              <p className="text-xs text-slate-600">
                {trial.filename ?? "—"} · Protocol {trial.protocol_version ?? "—"} · {trial.page_count ?? "?"} pages
              </p>
            </div>
            <StatusBadge status={trial.status} />
          </div>
          <dl className="grid gap-2 text-sm sm:grid-cols-2">
            <div>
              <dt className="font-semibold text-slate-700">Extraction method</dt>
              <dd>{trial.extraction_method ? humanize(trial.extraction_method) : "—"}</dd>
            </div>
            <div>
              <dt className="font-semibold text-slate-700">Search index</dt>
              <dd>{trial.index_status}</dd>
            </div>
          </dl>
          {trial.extraction_warnings.length > 0 ? (
            <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950">
              <p className="font-semibold">Extraction warnings</p>
              <ul className="mt-1 list-disc pl-5">
                {trial.extraction_warnings.map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {trial.error ? (
            <div role="alert" className="rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-900">
              <p className="font-semibold">{trial.error.code ?? "Extraction error"}</p>
              <p>{trial.error.message ?? "The protocol could not be processed."}</p>
            </div>
          ) : null}
          <CriteriaPreview criteria={trial.criteria} />
          <ReviewNotice compact notice="Extracted criteria are machine-generated. Verify every criterion — especially those flagged “Needs review” — against the source protocol. This is clinical decision support only and supports, but does not replace, qualified clinical review." />
          <div className="flex flex-wrap gap-2">
            <Link to={ROUTES.dashboard} className="btn-primary">Go to dashboard</Link>
            <Link to={ROUTES.newPatient} className="btn-secondary">Create a patient</Link>
          </div>
        </section>
      ) : null}
    </div>
  );
}
