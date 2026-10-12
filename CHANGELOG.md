# Changelog

## 1.3.0: audit fixes, refactor and UI polish (2026-10-12)

This release follows [`AUDIT_REPORT.md`](AUDIT_REPORT.md). No feature, agent, endpoint, route or stored-data
format was removed. Every API response keeps its shape; new fields are additive with defaults, so results saved by
earlier versions still load. The acceptance case (age 69, eGFR 28 → NOT ELIGIBLE with a renal Silent Exclusion
Trigger on pages 2 and 3) and all 9 seeded reference assessments give the same outcomes as before.

### Bug fixes: eligibility logic

- **C1. A newer lab result that can't be used no longer lets an older value decide.** Previously, if the newest
  result had a unit outside the conversion table, or had no date, it was skipped. An older value then decided the
  criterion and was reported as current, which could produce a wrong **ELIGIBLE**. That attribute is now
  `ambiguous`, the criterion is UNKNOWN, and missing information explains why. (`agents/patient_profile.py`)
- **C2. Compound criteria are evaluated in full.**
  - "Creatinine > 1.5 mg/dL **or** creatinine clearance < 40 mL/min" used to keep only the first clause. A patient
    with CrCl 30 could pass the exclusion, with nothing flagged for review.
  - "eGFR ≥ 30 **and** ≤ 90" lost its upper limit.
  - "ALT **or** AST > 100 U/L" ignored AST.
  Both clauses are now parsed (`Criterion.secondary_rule` + `rule_combinator`, optional fields) and combined with
  three-valued logic, so an undecided clause can never make a criterion pass. A second clause that can't be parsed
  makes the criterion UNKNOWN with a review reason, instead of being dropped.
  (`agents/protocol_extraction.py`, `engine/rule_evaluator.py`, `schemas/clinical.py`)
- **H1. "Stage" and "dosage" are no longer read as age.** "CKD stage 3 to 4" and "dosage of 10 to 20 mg" were
  parsed as `age between 3 and 4` (or 10–20), producing a false NOT ELIGIBLE. Age rules now need "age" as a whole
  word. (`agents/protocol_extraction.py`)
- **Lab names.** "Creatinine clearance" is now recognised as CrCl rather than creatinine, in protocol text and in
  patient lab names (the longest matching alias wins). (`engine/vocabulary.py`)
- **M1.** Condition criteria extracted by the LLM no longer create a false "Documented condition not provided"
  data-quality flag, and data-completeness criteria are linked on the LLM path too.
- Silent-trigger explanations no longer repeat "requires clinical confirmation" twice.

### Bug fixes: reliability, security, deployment

- **H2.** Protocol upload no longer blocks the server. PDF parsing and LLM extraction run in a worker thread, so
  status polling and health checks keep responding during an upload.
- **M2.** OpenAI and Gemini calls retry transient failures (timeouts, connection errors, 408/409/429/5xx) with
  exponential backoff and jitter, honouring `Retry-After`. Anthropic already retried through its SDK.
- **Q5.** The Anthropic client now uses the SDK's typed beta parameters (`client.beta.messages.create` with
  `betas=["server-side-fallback-2026-07-01"]` and `fallbacks="default"`) instead of raw extra headers/body. Same
  request, verified against the installed SDK.
- **M3.** LLM extraction sends only the pages that mention eligibility (plus one page either side), within a
  character budget. Which pages were sent is recorded in the extraction warnings.
- **M4.** Retrieval-index files are written atomically and `chunks.json` last. Reads share the build lock, and a
  corrupt or half-written index is rebuilt instead of failing the analysis.
- **M5.** New `MAX_PDF_PAGES` setting (default 300). Larger PDFs return 400 `TOO_MANY_PAGES` with a clear message.
- **M6.** Runs can no longer stay "running" forever:
  - a run that ends without saving a result is marked `ANALYSIS_INCOMPLETE`;
  - at startup, runs left queued/running by a restart are marked `ANALYSIS_INTERRUPTED` (`STALE_RUN_MINUTES`);
  - the progress page backs off its polling and explains when a run takes unusually long.
- **M7.** A failed session check on reload (network error, or Render waking up) no longer logs the user out. Only a
  401 ends the session; other errors show a retry screen.
- **M8.** A production frontend build without `VITE_API_URL` shows a configuration error instead of silently
  calling `localhost`.
- **M9.** New `LLM_SEMANTIC_EVALUATION` setting (default `true`, so behaviour is unchanged). Semantic evaluation now
  sends only the patient data a criterion can need: age, sex, conditions, medications, history, and labs from the
  criterion's clinical domain. Previously it sent the whole profile.
- **M10.** Runtime dependencies upgraded within their major versions: axios 1.20.0 and react-router-dom 6.30.6.
  This clears the high-severity axios and `@remix-run/router` advisories.
- **M11.** Login and registration are rate-limited per IP, and login also per email (`AUTH_RATE_LIMIT_PER_MINUTE`,
  default 10). Counters are in Redis when configured, otherwise memory.
- **L1.** The Vercel CORS regex in `render.yaml` matched any Vercel project named `cte-system-…`. It's removed; the
  exact production origin stays, with a commented team-scoped example.
- **L2.** A failure in the progress store (e.g. Redis) is logged and no longer stops an analysis.
- **L3.** The uploaded PDF is written to disk only after its records are saved, so there are no orphan files.
- **L4.** A retrieval-index failure is stored as `index_error` and no longer overwrites the trial's extraction
  error shown in the UI.
- **L5.** Error messages returned to clients no longer include raw exception text. Details stay in server logs,
  with an `error_type` field.
- **L9.** Oversized uploads are rejected from `Content-Length` before the body is received (413, with CORS headers
  so the browser can read it).
- **Middleware order:** CORS is now the outermost middleware, so every response, including early errors, carries
  CORS headers.
- **Prompt shutdown:** the PostgreSQL connection pool is closed when the app stops. It used to be torn down at
  interpreter exit, which added about 20 s to every restart.

### Refactors

- **M12. Typed API contracts.** `RunDetail.result` is typed as `EligibilityResult` (a legacy stored result that no
  longer validates is returned as saved), and `/evidence` and `/audit` have response models (`RunEvidence`,
  `RunAudit`). The JSON is unchanged, and the OpenAPI schema now describes it.
- **Structured logging:** a JSON formatter (`app/logging_config.py`) replaces the format-string pseudo-JSON, which
  broke on quotes and newlines. The handler always writes to the current stderr. Logs carry ids, node names and error types only, never patient values or
  protocol text.
- **Engine and agents:**
  - the numeric evaluator works on rules, which compound criteria reuse;
  - a single criteria-column regex replaces three copies;
  - long lines are wrapped;
  - an over-merged `if` is split back into readable branches.
- **Frontend:**
  - all route paths live in `src/lib/routes.ts` (34 hard-coded strings replaced);
  - unused API helpers are removed (`getTrial`, `getCriteria`, `getEvidence`);
  - async form handlers are explicitly voided;
  - upload limits come from `/api/health` instead of a duplicated constant;
  - `useAsync` clears stale data when its inputs change.
- **Tooling:**
  - backend: `pyproject.toml` with ruff (lint and import order; black-compatible formatter configured);
  - frontend: ESLint 9 (type-aware typescript-eslint, React hooks) and Prettier configs, plus `lint`, `test` and
    `format` scripts;
  - Vitest unit tests for `src/lib`;
  - `ruff check` and `eslint --max-warnings 0` both pass.

### UI improvements

- **Overall status card:** a one-line summary of what decided the outcome (e.g. "Decided by INC-02: eGFR must not
  be below 30 mL/min/1.73m2 (patient 28 mL/min/1.73m2). 1 silent exclusion trigger flagged."). The status badge
  comes first on phones.
- **Criteria tables:**
  - sticky header, a "Needs review" marker, and a two-line reasoning preview;
  - numbers right-aligned, text left-aligned;
  - every row expands to the protocol text, the patient value used, the agent's reasoning, uncertainties and
    method, and each protocol citation (page, citation type, quoted excerpt, "Open page" link);
  - "Expand all / Collapse all".
- **Patient values used:** sticky header, right-aligned tabular numbers, zebra striping.
- **Step indicator** (Upload protocol → Add patient → Run agents → Review results) on the upload, patient, analysis
  and results pages.
- **Readable labels:** attribute names in missing information and the summary read "LVEF", "eGFR" and
  "Myocardial infarction" instead of raw keys.
- **Plain-language states:** a server-waking-up screen, a slow-run notice, and the `TOO_MANY_PAGES` hint.
- Checked in light, dark and phone (390 px) layouts: no horizontal overflow and no console errors.

### Tests

- `tests/test_audit_fixes.py` adds 47 regression tests, one or more per finding, plus the acceptance case.
- Gemini retry tests run without real sleeps.
- Backend: 175 tests, all passing on the file store and on PostgreSQL 17 (1 skipped there: FAISS, which needs the
  embedding model).
- Frontend: 8 unit tests; type check, lint and production build pass.

### Decisions on the audit's open questions (behaviour kept as before)

- **Q1/Q2.** Decisive results on flagged criteria, and LLM-only TRIGGERED results, still decide NOT_ELIGIBLE. Every
  such result remains flagged for human review.
- **Q3.** Registration stays open, now rate-limited.
- **Q4.** Semantic evaluation stays on by default. Set `LLM_SEMANTIC_EVALUATION=false` if real patient data could
  reach the deployment.
- **Q6.** Folder names kept; `storage/` is the repository layer, documented as such.
- **Q7.** Targeted UI polish rather than a redesign.

### Known remaining items

- `npm audit` still reports: a moderate react-router advisory, fixed only in v7 (a major upgrade); and build/dev-time
  advisories in Vite 5's esbuild dev server, braces and postcss-selector-parser (via Tailwind 3). None affect the
  production bundle.
- Existing code was not mass-reformatted with ruff format or Prettier, to keep this change reviewable.

## 1.2.0: requirements alignment

- PostgreSQL store (`DATABASE_URL`), Redis workflow state (`REDIS_URL`), optional BioBERT concept matching,
  optional Tavily web research, and prior-assessment memory.
- Results sections for triggered exclusions, patient values used, external references and comparison with the
  previous assessment.
- Render blueprint with PostgreSQL and Key Value; Vercel as the frontend target.
