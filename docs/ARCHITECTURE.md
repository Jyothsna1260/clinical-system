# Architecture and code flow

This page explains how a request moves through the code, so you can find where to look or what to change.

## Layers

```
frontend  pages/  ──>  api/client.ts  ──HTTP/JSON──>  backend
                                                        │
backend   api/routes/     HTTP only: parse the request, call one service function, return its result
            │
          services/       one module per use case: auth, trials, patients, eligibility, analysis (background)
            │
            ├── storage/    PostgreSQL (DATABASE_URL) or the JSON file store; same interface
            ├── state/      live workflow state: Redis (REDIS_URL) or in-process memory
            ├── workflow/   LangGraph graph that runs the agents in order
            │     └── agents/  A–F + web research, using engine/ (rules, units, dates), rag/ (PDF, chunks,
            │                  index) and nlp/ (optional BioBERT concept matching)
            └── security/   password hashing, JWT tokens, current-user dependency
```

Rules that keep the flow clear:

- **Routes never contain business logic.** Each route is one call into `app/services/…`.
- **Services raise `AppError`** (`app/errors.py`) for expected failures. `app/api/errors.py` turns it into
  `{"error": {"code", "message", "details"}}` with the right HTTP status.
- **Ownership is checked in one place per resource:** `require_trial`, `require_patient`, `require_run`.
  A record owned by someone else returns the same 404 as a missing one.
- **Every service that reads or changes data writes an audit event** (`services/audit.py`).
- **Agents are pure.** They take inputs and return results; the workflow passes in the LLM client, index,
  clinical NLP matcher, web search client, prior-assessment memory, progress reporter and persister through
  `config["configurable"]`.

## Flow 1: sign in

```
Login.tsx → client.login() → POST /api/auth/login → services.auth.login()
  → store.user_by_email() → verify_password() → audit "user.login" → JWT returned
```

The token is kept in the browser and sent as `Authorization: Bearer …`. `security/deps.get_current_user`
decodes it on every protected request and loads the user from the store.

## Flow 2: upload a protocol

```
TrialUpload.tsx → client.uploadTrial() → POST /api/trials/upload (multipart)
  → services.trials.upload_protocol()
       1. validate size, emptiness and PDF magic bytes
       2. rag.pdf_loader.load_pdf_bytes()          text per page
       3. agents.protocol_extraction.extract_criteria()   Agent A: criteria with page + excerpt
       4. save PDF to DATA_DIR/uploads, save TrialRecord + ProtocolDocumentRecord
       5. audit "trial.uploaded"
  → background: services.trials.build_index_task()   chunks + retrieval index in DATA_DIR/indexes
```

The response already contains the extracted criteria, so the page can show them immediately.

## Flow 3: create or edit a patient

```
PatientForm.tsx → client.createPatient() / updatePatient()
  → services.patients.create_patient() / update_patient()
  → PatientRecord with versions [v1, v2, …]   (an edit appends a version, never overwrites)
```

## Flow 4: run an eligibility assessment

```
AssessmentLauncher → client.analyze() → POST /api/eligibility/analyze
  → services.eligibility.start_analysis()
       checks trial is ready, pins protocol version + latest patient version, saves a queued RunRecord
  → 202 {run_id}
  → background: services.analysis.run_analysis(run_id)
       workflow.graph.run_eligibility():
         validate_inputs → extract_protocol → normalize_patient (Agent B) → retrieve_evidence
           → [inclusion_matching (C) ∥ exclusion_detection (D)] → detect_contradictions (E)
           → web_research → review_and_decide (F) → persist
       each node reports progress → workflow state (Redis or memory, app/state/)
       persist → RunRecord.result / error, audit "analysis.completed" or "analysis.failed"
       at the end, the live agent state is copied into RunRecord.agent_logs (durable)

Analysis.tsx polls GET /api/eligibility/{run_id}/status until done, then opens Results.tsx,
which loads GET /{run_id}, /{run_id}/evidence and /{run_id}/audit.
```

Any failure inside a node becomes a structured error and goes to `handle_error`, which still runs
`persist`, so a failed run is always recorded and shown.

## Where the data lives

With `DATABASE_URL` set, records live in PostgreSQL (`app/storage/postgres_store.py`). Each record type has
its own table (`users`, `trials`, `protocol_documents`, `patients`, `eligibility_runs`, `audit_events`) with
the lookup and ownership columns as real indexed columns and foreign keys, and the full validated record in a
`data` JSONB column. The schema is created on startup. `update()` uses `SELECT … FOR UPDATE`, so the
parallel agents and several API workers never lose writes.

With `REDIS_URL` set, live per-agent progress is kept in Redis (`cte:run:<run_id>:nodes`, expires after
`RUN_STATE_TTL_SECONDS`). The status endpoint overlays it on the durable agent logs. If Redis becomes
unreachable mid-run, progress falls back to process memory and the run continues.

Without `DATABASE_URL`, the file store is used:

```
DATA_DIR/                     (backend/data locally, /app/data in Docker and on Render)
  store/users/<id>.json
  store/trials/<id>.json
  store/documents/<id>.json   page text + extracted criteria for one protocol version
  store/patients/<id>.json    all profile versions
  store/runs/<id>.json        status, per-agent logs, final result
  store/audit/<user_id>.jsonl append-only audit trail
  uploads/<trial_id>/v1.pdf
  indexes/<trial_id>/<document_id>/
```

## Where to change things

| To change… | Look in |
|---|---|
| An endpoint's URL or request shape | `backend/app/api/routes/`, `backend/app/schemas/api.py` |
| What an action does | `backend/app/services/<resource>.py` |
| How criteria are read from a PDF | `backend/app/agents/protocol_extraction.py` |
| How a rule is compared (thresholds, units, dates) | `backend/app/engine/` |
| The final ELIGIBLE / NOT_ELIGIBLE decision | `backend/app/agents/reviewer.py` |
| Order of the agents | `backend/app/workflow/graph.py` |
| How records are saved | `backend/app/storage/` (`file_store.py`, `postgres_store.py`) |
| Live workflow state | `backend/app/state/run_state.py` |
| Clinical NLP (BioBERT) matching | `backend/app/nlp/clinical.py`, used in `engine/rule_evaluator.py` |
| Web search for ambiguous criteria | `backend/app/services/web_search.py`, `backend/app/agents/web_research.py` |
| A screen | `frontend/src/pages/`, shared pieces in `frontend/src/components/` |
| An API call from the UI | `frontend/src/api/client.ts`, types in `frontend/src/types.ts` |
