# Audit Report: Clinical Trial Eligibility & Exclusion Contradiction System

Audited: 2026-10-12, commit `d9b661a` plus the uncommitted README/USER_GUIDE edits. No code was changed for this report.

**Method.** I read every backend module, the frontend API client, auth, hooks, pages and key components, and the
deployment files. I reproduced each correctness finding below by running the code. Repro snippets run from
`backend/` with the project venv. Baseline: `pytest` passes, both on the file store and on PostgreSQL 17, and
`npm run build` (type check + build) passes.

**Headline.** The architecture is sound and most of the checklist already passes (see [What is already
correct](#what-is-already-correct)). The serious problems are in **eligibility logic**: three reproduced bugs can
produce a wrong decision. Two of them can wrongly return **ELIGIBLE** without flagging anything for review.

| Severity | Count |
|---|---|
| Critical | 2 |
| High | 2 |
| Medium | 12 |
| Low | 11 |

## Resolution status (v1.3.0, 2026-10-12)

All Critical, High, Medium and Low findings are fixed, each with regression tests in
`backend/tests/test_audit_fixes.py` (frontend items are covered by the type check, lint and Vitest). Details are in
[`CHANGELOG.md`](CHANGELOG.md).

| Finding | Status |
|---|---|
| C1, C2, H1 (eligibility logic) | Fixed. Tests for each, plus the 69/28 acceptance case re-checked |
| H2 (blocking upload) | Fixed (worker thread) |
| M1–M12 | Fixed. M10 fixed within major versions; a moderate react-router advisory remains (v7-only fix) |
| L1–L9 | Fixed |
| L10 | Fixed (ruff, ESLint, Prettier configs; Vitest suite) |
| L11 | Accepted for the prototype and documented (token in `localStorage`) |
| Q1–Q4, Q6, Q7 | Decided by keeping current behaviour; see CHANGELOG, "Decisions" |
| Q5 | Verified against the installed SDK; switched to the typed beta parameters |

---

# Phase 1: System map

## 1.1 Folder structure

```
backend/
  app/
    main.py              FastAPI app: CORS, security headers, routers, startup logging
    config.py            Settings from environment only (pydantic-settings); production JWT check
    errors.py            AppError (status, code, message, details)
    api/routes/          Thin HTTP layer: auth, trials, patients, eligibility, health
    api/errors.py        Handlers turning every error into {"error": {code, message, details}}
    security/            jwt.py (bcrypt + HS256 JWT), deps.py (get_current_user)
    services/            Use cases: auth, trials (upload, index build), patients (versioning),
                         eligibility (start/read runs), analysis (background run), audit, llm, web_search
    agents/              A protocol_extraction · B patient_profile · C inclusion_matching ·
                         D exclusion_detection · E contradiction · web_research · F reviewer
    engine/              Deterministic core: comparators, units (validated conversion table), dates,
                         vocabulary (lab aliases, condition synonyms, domains), rule_evaluator
    nlp/                 Optional BioBERT concept matcher (advisory notes only)
    rag/                 pdf_loader (PyMuPDF + table detection), chunker, index (FAISS / keyword), retriever
    workflow/            state.py (typed LangGraph state), graph.py (the agent graph)
    state/               Live workflow state: Redis or in-process memory
    storage/             records.py (typed records), file_store.py (JSON), postgres_store.py (PostgreSQL)
    schemas/             clinical.py (domain + agent outputs), api.py (HTTP request/response models)
  scripts/               make_synthetic_protocol.py (fixture PDFs), seed.py (demo data + reference runs)
  tests/                 pytest suite + fixtures (5 synthetic PDFs, 10 synthetic patients)
frontend/src/
  api/client.ts          Axios instance, token storage, 401 redirect, GET retries, typed endpoint functions
  auth/                  AuthContext (session), ProtectedRoute
  pages/                 Login, Dashboard, TrialUpload, PatientForm, Analysis, Results, NotFound
  components/            AgentProgress, CriteriaTable, SilentExclusionCard, EvidencePanel, AuditTrail, …
  lib/                   format, highlight, patientForm (form <-> profile), rules, useAsync
  theme/                 Light/dark/system theme
demo/                    Playwright script that records a narrated walkthrough
docs/                    ARCHITECTURE.md, USER_GUIDE.md, DEMO_DATA.md, screenshots
render.yaml, docker-compose.yml, frontend/vercel.json
```

## 1.2 End-to-end flow

1. **Login.** `Login.tsx` calls `AuthContext.login`, which posts to `/api/auth/login`. The token is stored in
   `localStorage` (`cte_token`). `ProtectedRoute` gates the app, and on reload `AuthContext` revalidates the
   session with `GET /api/auth/me`.
2. **Upload protocol.** `TrialUpload.tsx` posts multipart to `/api/trials/upload`. `services.trials.upload_protocol`:
   - checks size and the `%PDF` magic bytes;
   - extracts text and tables per page with PyMuPDF;
   - runs **Agent A** (LLM if configured, else rule-based; every excerpt is verified on its page);
   - saves the trial and its document (page text + criteria), then returns the criteria.
   A background task then chunks the pages and builds the FAISS or keyword index.
3. **Patient profile.** `PatientForm.tsx` (form, or JSON import) posts to `/api/patients`, or PATCHes to create
   a new version. The response includes data-quality flags from **Agent B**.
4. **Run.** `AssessmentLauncher` posts to `/api/eligibility/analyze`, which returns `202 {run_id}`. A queued
   `RunRecord` pins the protocol version and patient version, and `BackgroundTasks` calls
   `services.analysis.run_analysis`.
5. **Agent pipeline** (`workflow/graph.py`):
   `validate_inputs → extract_protocol (A, reuses stored criteria) → normalize_patient (B) → retrieve_evidence →
   [inclusion_matching (C) ∥ exclusion_detection (D)] → detect_contradictions (E) → web_research → review_and_decide (F) → persist`.
   Any node error routes to `handle_error → persist`.
6. **Progress.** `Analysis.tsx` polls `/api/eligibility/{id}/status` every second, then opens the results page.
7. **Results.** `Results.tsx` calls `GET /api/eligibility/{id}`. `EvidencePanel` calls `/api/trials/{id}/pages/{n}`
   to show the cited text, and `AuditTrail` calls `/api/eligibility/{id}/audit`.

## 1.3 How state moves between agents

- **During a run:** a typed LangGraph `EligibilityState` (`workflow/state.py`). Each node returns a partial update.
  `logs` uses an append reducer, and `error` uses a first-error-wins reducer, so the two parallel branches can't
  overwrite each other. Runtime dependencies (LLM, index, NLP matcher, web search, prior assessment, reporter,
  persister) travel in `config["configurable"]`, not in the state.
- **Live progress:** each node reports start and end to `app/state` (Redis hash `cte:run:<id>:nodes` when
  `REDIS_URL` is set, otherwise process memory).
- **Durable:** the `persist` node writes the result or error to the run record (PostgreSQL `eligibility_runs`,
  or JSON). When the run ends, live progress is copied into `agent_logs`. Extracted criteria are stored per
  protocol version and reused (re-verified) by later runs. The audit trail is append-only.

## 1.4 API endpoints

All responses are JSON. Errors are always `{"error": {"code", "message", "details"}}`. "Auth" means a Bearer JWT.
A record owned by another user returns 404.

| Method | Path | Auth | Input | Output |
|---|---|---|---|---|
| GET | `/` | no | — | 307 redirect to `/docs` |
| GET | `/api/health` | no | — | status, storage/workflow-state backends, LLM/NLP/web-search status, review notice |
| POST | `/api/auth/register` | no | `{email, password (8–128), full_name?}` | 201 `TokenOut {access_token, token_type, user}`; 409 `EMAIL_TAKEN` |
| POST | `/api/auth/login` | no | `{email, password}` | `TokenOut`; 401 `INVALID_CREDENTIALS` |
| GET | `/api/auth/me` | yes | — | `UserOut` |
| POST | `/api/trials/upload` | yes | multipart `file` (PDF ≤ `MAX_UPLOAD_MB`), `title?` | 201 `TrialDetail` (criteria included); 400/413 errors |
| GET | `/api/trials` | yes | — | `TrialSummary[]` |
| GET | `/api/trials/{trial_id}` | yes | — | `TrialDetail` |
| GET | `/api/trials/{trial_id}/criteria` | yes | — | `Criterion[]` |
| GET | `/api/trials/{trial_id}/pages/{page}` | yes | — | `PageOut {trial_id, page, page_count, text}` |
| POST | `/api/patients` | yes | `{label, profile: PatientProfileInput}` | 201 `PatientOut` (with data-quality flags) |
| GET | `/api/patients` | yes | — | `PatientSummary[]` |
| GET | `/api/patients/{id}` | yes | — | `PatientOut` |
| PATCH | `/api/patients/{id}` | yes | `{label?, profile}` | `PatientOut` (new version) |
| POST | `/api/eligibility/analyze` | yes | `{trial_id, patient_id}` | 202 `RunCreated {run_id, status}`; 409 `TRIAL_NOT_READY` |
| GET | `/api/eligibility?limit=1..100` | yes | — | `RunSummary[]` |
| GET | `/api/eligibility/{run_id}/status` | yes | — | `RunStatus {status, overall_status, progress[], error}` |
| GET | `/api/eligibility/{run_id}` | yes | — | `RunDetail` (`result` = `EligibilityResult` as an untyped dict, see M12) |
| GET | `/api/eligibility/{run_id}/evidence` | yes | — | untyped dict: every citation behind the decision |
| GET | `/api/eligibility/{run_id}/audit` | yes | — | untyped dict: audit events + agent execution logs |

## 1.5 Frontend pages and the endpoints they call

| File | Calls |
|---|---|
| `auth/AuthContext.tsx` | `POST /auth/login`, `POST /auth/register`, `GET /auth/me` |
| `pages/Login.tsx` | login/register through AuthContext |
| `pages/Dashboard.tsx` | `GET /trials`, `GET /patients`, `GET /eligibility` |
| `pages/TrialUpload.tsx` | `POST /trials/upload` |
| `pages/PatientForm.tsx` | `GET /patients/{id}`, `POST /patients`, `PATCH /patients/{id}`, `GET /trials` |
| `components/AssessmentLauncher.tsx` | `POST /eligibility/analyze` |
| `pages/Analysis.tsx` | `GET /eligibility/{id}/status` (polling) |
| `pages/Results.tsx` | `GET /eligibility/{id}` |
| `components/EvidencePanel.tsx` | `GET /trials/{id}/pages/{n}` |
| `components/AuditTrail.tsx` | `GET /eligibility/{id}/audit` |
| *(unused)* | `getTrial`, `getCriteria`, `getEvidence` in `api/client.ts` (L6) |

---

# Phase 2: Findings

Severity: **Critical** can produce a wrong eligibility decision with nothing flagged; **High** can produce a wrong
decision, or breaks the service under normal use; **Medium** is a real defect with limited blast radius;
**Low** is hygiene or hardening.

## Critical

### C1. The newest lab value is ignored when its unit can't be converted, so an older value decides
- **File:** `backend/app/agents/patient_profile.py:52-60`, `:68-70`
- **Description:** if the most recent observation's unit is outside the validated conversion table, it is dropped
  (only a `unit_unconvertible` flag is recorded). The attribute is then resolved from the remaining older
  observation and reported as `status: ok`. The Reviewer doesn't look at that flag, so the decision rests on
  out-of-date data. The same thing happens when the newer observation is **undated**: dated observations sort
  first and the undated one is silently skipped.
- **Reproduction** (confirmed):
  ```python
  # patient_all_pass.json + a newer eGFR of 28 in "mL/min" (not mL/min/1.73m2), dated today
  run_eligibility(... protocol_renal.pdf ...)  # -> ELIGIBLE, INC-02 SATISFIED using the older eGFR 78
  ```
  Undated variant: eGFR 45 (dated 2026-08-01) plus eGFR 28 (no date) resolves to `45.0 ok`.
- **Proposed fix:** if any observation newer than (or not orderable against) the chosen one couldn't be used,
  mark the attribute `ambiguous` (value kept for display), so the criterion becomes UNKNOWN and the result is
  MORE_INFORMATION_REQUIRED, with a missing-information entry explaining why. Add regression tests for both
  variants.

### C2. Compound and two-sided numeric criteria keep only the first clause, with no review flag
- **File:** `backend/app/agents/protocol_extraction.py:320-344` (`_parse_lab`)
- **Description:** the parser takes the first operator and number it finds:
  - `"Creatinine > 1.5 mg/dL or creatinine clearance < 40 mL/min"` keeps only `creatinine > 1.5`. The CrCl clause
    disappears, isn't a required attribute, and no review reason is added. A patient with creatinine 1.2 and CrCl
    30 is NOT_TRIGGERED and can be **ELIGIBLE**.
  - `"eGFR >= 30 and <= 90 mL/min/1.73m2"` keeps only `egfr >= 30`, so the upper bound is lost. It also wrongly
    reports "Unit not stated", because the unit check looks right after the first number.
- **Reproduction** (confirmed): `parse_rule("Creatinine > 1.5 mg/dL or creatinine clearance < 40 mL/min")` →
  `{'attribute': 'creatinine', 'operator': 'gt', 'value': 1.5}` with `review_reasons == []`.
- **Proposed fix:**
  - Detect a second comparator, or a second lab alias, after the first match.
  - Turn symmetric two-sided bounds on the same attribute into `between` (inclusive only when both are ≥ and ≤).
  - For anything else (an OR across two labs), keep the first rule but add the second attribute to
    `required_attributes`, and add the review reason "Compound criterion; only the first clause is
    machine-evaluated", so it's never silently partial.
  - The Reviewer then treats a NOT_TRIGGERED/SATISFIED result on such a criterion as material uncertainty.
  - No schema change is needed. Add tests.

## High

### H1. "Stage" and "dosage" ranges are parsed as an age rule
- **File:** `backend/app/agents/protocol_extraction.py:248-257` (`_parse_age`)
- **Description:** the guard `"age" not in t` and the regex `(?:age[d]?|aged)\s*…` have no word boundary, so
  "st**age** 3 to 4" and "dos**age** of 10 to 20 mg" match as `age between 3 and 4` (or 10–20). A 69-year-old
  then fails it deterministically, and the patient is **NOT_ELIGIBLE** on a rule the protocol never stated.
- **Reproduction** (confirmed): `parse_rule("Chronic kidney disease stage 3 to 4")`, `parse_rule("CKD stage 3-4")`
  and `parse_rule("Stable dosage of 10 to 20 mg metformin")` all return `attribute='age', operator='between'`.
- **Proposed fix:** require `\bage[d]?\b`. In the second pattern, require the range to be followed by
  `years`/`year-old`/`of age`, which it already does. Add tests for stage, dosage, average, page and percentage.

### H2. Protocol upload blocks the event loop
- **File:** `backend/app/api/routes/trials.py:13-22`
- **Description:** `upload_trial` is `async def` but calls `trials.upload_protocol` synchronously. That covers
  PyMuPDF parsing, table detection and the LLM extraction call (up to 60 s plus provider retries). With the single
  uvicorn worker, every other request stalls for that whole time: status polling, other users, and Render's
  `/api/health` check, which can then restart the service mid-upload.
- **Reproduction:** with `LLM_PROVIDER` set, upload a multi-page PDF, then request `/api/health` from a second
  terminal. It doesn't respond until the upload finishes.
- **Proposed fix:** keep `await file.read(...)`, then `await run_in_threadpool(trials.upload_protocol, ...)`
  (`starlette.concurrency`). The API contract is unchanged.

## Medium

### M1. LLM-extracted condition criteria create a false "missing condition" flag
- **File:** `backend/app/agents/protocol_extraction.py:562`
- **Description:** the LLM path sets `required_attributes=["condition"]`, but the rule-based path uses
  `"condition:<terms>"`. `normalize_patient` skips only attributes containing `:`, so it adds
  `attributes["condition"] = missing` and a `missing` data-quality flag ("Documented condition not provided").
  That spurious row then appears in the data-quality flags and in "Patient values used".
- **Reproduction** (confirmed): a fake LLM returning one condition criterion gives
  `required_attributes == ['condition']`, and `normalize_patient` returns `('condition', 'missing', …)`.
- **Proposed fix:** in the LLM path, build `required_attributes` the same way as the rule-based path
  (`condition:<terms>`; `event:` for windows). Also apply `_link_data_completeness` to LLM output.

### M2. No retry or backoff for OpenAI and Gemini calls
- **File:** `backend/app/services/llm.py:88-111`, `:125-155`
- **Description:** Anthropic uses the SDK's `max_retries=2`. OpenAI and Gemini make a single `httpx.post`, so a
  transient 429, 5xx or timeout immediately drops extraction to rule-based. The default deployment uses Gemini's
  free tier, which rate-limits often.
- **Proposed fix:** a small shared retry helper (2 retries, exponential backoff with jitter, honoring
  `Retry-After`) for 429/5xx/connect/read errors. Keep the existing timeout.

### M3. LLM extraction sends the whole PDF in one prompt, with no size cap
- **File:** `backend/app/agents/protocol_extraction.py:535-537`
- **Description:** a long protocol can exceed the model's context window or cost a lot. It fails, then falls back
  quietly (only a warning in `extraction_warnings`).
- **Proposed fix:** send only the pages holding inclusion/exclusion sections. `pdf_loader._CRITERIA_HINT` already
  finds them; add one page either side and a character budget. Record which pages were sent.

### M4. Retrieval index files are written non-atomically and read without the lock
- **File:** `backend/app/rag/index.py:105-114`, `:138-148`; `backend/app/services/trials.py:149-155`
- **Description:** `chunks.json`, `index.faiss` and `meta.json` are written in place. `get_or_build_index` calls
  `load_index` outside `_BUILD_LOCK`. An analysis started right after upload (while the background build is
  writing) can read a half-written `chunks.json`. The `JSONDecodeError` isn't caught, so the `retrieve_evidence`
  node fails the whole run with `AGENT_FAILURE`.
- **Proposed fix:** write through `storage.file_store.atomic_write_text` (and a temp-file swap for the FAISS
  file), write `chunks.json` last, wrap `load_index` in the lock, and treat a corrupt index as "rebuild".

### M5. No page limit on PDFs
- **File:** `backend/app/rag/pdf_loader.py:66-69`
- **Description:** a 20 MB PDF can contain thousands of pages. Every page is extracted, and table detection (slow)
  runs on every page matching "inclusion/exclusion/eligibility". Combined with H2, that ties the service up for
  minutes.
- **Proposed fix:** a `MAX_PDF_PAGES` setting (default 300) that returns 400 `TOO_MANY_PAGES`. Optionally cap
  table detection to the first N matching pages.

### M6. Runs can stay "running" forever, and the UI polls forever
- **File:** `backend/app/services/analysis.py:97-142`; `frontend/src/pages/Analysis.tsx:23-51`
- **Description:** runs execute in `BackgroundTasks`. If the process restarts (Render free plan sleeps and
  redeploys), or `persist_state` itself raises, the record stays `queued`/`running` permanently. `Analysis.tsx`
  polls every second with no ceiling.
- **Proposed fix:**
  - Backend: at the end of `run_analysis`, if the record is still `running`, mark it `failed`
    (`ANALYSIS_INCOMPLETE`). On startup, mark runs that are `queued`/`running` and older than a threshold as
    `failed` (`ANALYSIS_INTERRUPTED`), so the user can retry.
  - Frontend: back off polling (1 s → 5 s) and show "This is taking longer than expected" with a retry option
    after ~3 minutes.

### M7. A failed session check on reload logs the user out, even on a network or cold-start error
- **File:** `frontend/src/auth/AuthContext.tsx:33-38`
- **Description:** any failure of `GET /api/auth/me` clears the token, including network errors and 502/503 while
  Render wakes up. Users get logged out on the first visit after idle.
- **Proposed fix:** clear the token only on 401. On other errors keep it and show a "Can't reach the server"
  state with a retry.

### M8. A production build silently points at localhost when `VITE_API_URL` is missing
- **File:** `frontend/src/api/client.ts:25`
- **Description:** if `VITE_API_URL` isn't set in Vercel, the deployed app calls `http://localhost:8000`, and
  every request fails with a confusing network error.
- **Proposed fix:** use the localhost fallback only in `import.meta.env.DEV`. In production, show a clear
  configuration error banner, and document the variable in `frontend/.env.example`.

### M9. Patient data is sent to a third-party LLM when semantic evaluation is enabled
- **File:** `backend/app/engine/rule_evaluator.py` (`_evaluate_semantic`), `render.yaml` (`LLM_PROVIDER=gemini`)
- **Description:** for criteria with no machine-readable rule, the full normalized profile (labs, diagnoses,
  medications, sex, dates) goes to the configured LLM. On Gemini's free tier, Google's terms allow prompts to be
  used to improve products. That's acceptable for the bundled synthetic data, but it isn't stated anywhere a user
  would see it.
- **Proposed fix:** add an `LLM_SEMANTIC_EVALUATION` setting (default on, to preserve behavior), send only the
  attributes the criterion needs, and document the data flow in the README and on the upload/patient pages.
  See question Q4.

### M10. Runtime frontend dependencies have published advisories
- **File:** `frontend/package.json` (`axios 1.7.9`, `react-router-dom 6.28.0` → `@remix-run/router ≤1.23.2`)
- **Description:** `npm audit` reports high-severity advisories for axios (GHSA-jr5f-v2jv-69x6, GHSA-3g43-6gmg-66jw,
  …) and `@remix-run/router`. It also reports build-time-only issues in esbuild/vite, postcss and braces. The
  practical exposure is low (fixed base URL, no proxy config), but these are runtime dependencies of a deployed app.
- **Proposed fix:** upgrade axios and react-router-dom within their major versions, upgrade vite and postcss, then
  re-run `npm audit`, build and the demo walkthrough.

### M11. No rate limiting on login or registration
- **File:** `backend/app/api/routes/auth.py:11-18`
- **Description:** passwords can be brute-forced and accounts created in bulk on the public deployment.
- **Proposed fix:** a small per-IP and per-email limiter on `/api/auth/*` (in Redis when configured, memory
  otherwise) that returns 429 `RATE_LIMITED`.

### M12. The core result contract is untyped at the API boundary
- **File:** `backend/app/schemas/api.py:141` (`result: dict`); `backend/app/api/routes/eligibility.py:37-44`
  (evidence and audit return `dict`)
- **Description:** OpenAPI doesn't describe `EligibilityResult`, evidence or audit, so `frontend/src/types.ts` is
  maintained by hand and can drift.
- **Proposed fix:** type `result` as `EligibilityResult | None`, and add `RunEvidence`/`RunAudit` response models
  with the same JSON shape. This is backward compatible; all new result fields have defaults, so stored older
  results still validate.

## Low

| # | File:line | Issue | Proposed fix |
|---|---|---|---|
| L1 | `render.yaml` (`FRONTEND_ORIGIN_REGEX`) | `https://cte-system(-[a-z0-9-]+)?\.vercel\.app` also matches any other Vercel project named `cte-system-…`. The risk is low because auth is a bearer token, not a cookie, but the allow-list is wider than intended. | Scope to the team's preview pattern, `https://cte-system-git-[a-z0-9-]+-<team>\.vercel\.app` |
| L2 | `backend/app/workflow/graph.py:65` | The reporter is called outside the node's try/except, so a progress-store error crashes the whole run instead of being logged | Wrap reporter calls; log and continue |
| L3 | `backend/app/services/trials.py:127-129` | The PDF is written to disk before the records are saved, leaving an orphan file if saving fails | Write after the records are saved, or delete on failure |
| L4 | `backend/app/services/trials.py:171-174` | An index-build failure sets `trial.error` while `status` stays `ready` | Store it as `index_error`, or leave `error` for upload failures only |
| L5 | `graph.py:74`, `analysis.py:138`, `trials.py:169` | Raw exception text (`str(exc)`) is returned to clients in `error.message` | Return a generic message plus the error code; keep the detail in server logs |
| L6 | `frontend/src/api/client.ts:201-206, 238-240` | `getTrial`, `getCriteria` and `getEvidence` are unused | Remove, or use `getEvidence` in the evidence view |
| L7 | `frontend/src/pages/TrialUpload.tsx:12` | `MAX_MB = 20` duplicates the backend's `MAX_UPLOAD_MB` | Read it from `/api/health` (add `max_upload_mb`) or a shared constant |
| L8 | `frontend/src/lib/useAsync.ts:12-38` | Data isn't cleared when deps change. "Open it" on the prior assessment briefly shows the old run under the new URL | Reset `data` when deps change |
| L9 | `backend/app/api/routes/trials.py:21` | The multipart body is fully received before the size check, so oversized uploads still consume bandwidth and disk | Reject on `Content-Length` early; keep the existing check |
| L10 | repo | No ruff/black, ESLint or Prettier configs; no frontend tests | Add configs (Phase 4), plus a small Vitest suite for `lib/` |
| L11 | `frontend/src/api/client.ts:31-53` | The JWT is in `localStorage`, so any XSS can read it | Accepted for a prototype. Document it; consider httpOnly cookies later |

---

## What is already correct

These checklist items were verified, so I propose no change:

- **JWT:**
  - signature and `exp` are validated (python-jose), and `type == "access"` is enforced;
  - unknown users return 401;
  - production refuses a weak `JWT_SECRET`.
- **Routes and data access:**
  - every route except health/register/login requires auth;
  - ownership checks return 404;
  - ids are validated (`^[A-Za-z0-9_-]{1,64}$`), which blocks path traversal;
  - PostgreSQL queries are parameterized, and table names are constants.
- **Uploads:** magic-byte check, size limit, empty/encrypted/scanned PDFs rejected with structured 400s, and
  stored file paths never use the client's filename.
- **LLM safety:** output is validated against Pydantic/JSON Schema, with a rule-based fallback; the untrusted-data
  instruction is in every prompt; excerpts are verified on the cited page, otherwise flagged with low confidence.
- **Decision rules:**
  - UNKNOWN is never collapsed into SATISFIED or NOT_TRIGGERED;
  - a proven exclusion overrides passing inclusions;
  - a boundary value with unstated inclusivity gives UNKNOWN;
  - unit conversions use an explicit table and refuse anything else;
  - findings without a citation are downgraded (evidence gate).
- **Acceptance case:** age 69 / eGFR 28 gives NOT_ELIGIBLE with a renal Silent Exclusion Trigger citing pages 2
  and 3 (`tests/test_acceptance.py`).
- **Graph:** no cycles, always terminates; a failure in either parallel branch routes to `handle_error`; failed
  runs are still saved.
- **Responses and config:** structured error responses everywhere; security headers; no secrets in code or
  anywhere in git history; `.env` is gitignored.
- **Frontend:**
  - TypeScript `strict` with `noUncheckedIndexedAccess`, and no `any`;
  - 401 clears the token and redirects with `?next=`;
  - every page has loading, error and empty states;
  - the evidence dialog traps focus and restores it on close;
  - statuses carry text labels, not color alone.

## Questions (I need your decision before acting)

1. **Q1. Decisive results on flagged criteria.** A deterministic UNSATISFIED or TRIGGERED result on a criterion
   whose *extraction* is flagged for review (low confidence, ambiguous wording) currently decides NOT_ELIGIBLE.
   Should those downgrade the overall status to MORE_INFORMATION_REQUIRED instead? That's safer, but it changes
   current outcomes.
2. **Q2. LLM-only exclusions.** An LLM-only (semantic) TRIGGERED result can produce NOT_ELIGIBLE. LLM-only
   results can never produce ELIGIBLE. Is the asymmetry intended?
3. **Q3. Open registration.** Anyone can register on the public deployment. Keep it open for the demo, or add an
   invite code / allow-list setting?
4. **Q4. Patient data to the LLM.** Is it guaranteed that only synthetic patient data reaches the deployment? If
   not, M9 should default semantic evaluation **off**.
5. **Q5. Anthropic request options.** `AnthropicLLM` sends `output_config` (effort + JSON schema) and a
   server-side-fallback beta header. Without an Anthropic key I couldn't confirm these are accepted by the pinned
   SDK (`anthropic==1.12.1`). Do you deploy with Anthropic? If so, I'll verify against the SDK before Phase 3.
6. **Q6. Phase 4 layering.** The backend already separates routes / services / agents / schemas / storage. I
   propose renaming `storage/` to `repositories/` and adding `core/` (config, security, logging) only if you want
   the exact names from the brief. It's a large import churn for no behavior change. Rename, or keep the current
   names?
7. **Q7. Phase 5 scope.** The UI already has a design system (Inter, a token palette, light/dark, status colors,
   responsive layouts). I propose targeted polish:
   - sticky table headers and right-aligned numbers;
   - expandable evidence rows in every table;
   - a step indicator on upload;
   - a more prominent status card.
   That's instead of a full visual redesign. OK?

## Proposed order for Phase 3

C1 → C2 → H1, each with regression tests (including the 69/28 case staying NOT_ELIGIBLE with its trigger). Then
H2, then M1–M12, with the full test suite and frontend build after each fix.
