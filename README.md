# Clinical Trial Eligibility & Exclusion Contradiction System

An agentic clinical decision-support prototype. It reads a trial protocol PDF and a structured
patient profile, evaluates inclusion and exclusion criteria with six specialized agents, detects
**Silent Exclusion Triggers**, and cites every decisive finding to the protocol page it came from.

> **Clinical decision support only.** The system supports, and does not replace, review by a
> qualified clinician or trial investigator. Every result carries `human_review_required: true`
> and a human-review notice in both the API and the UI. All bundled data is synthetic.

| | |
|---|---|
| Author | [Jyothsna1260](https://github.com/Jyothsna1260) |
| GitHub repository | https://github.com/Jyothsna1260/clinical-system |
| Live frontend (Vercel) | _fill in after the Vercel deploy_, e.g. `https://cte-system.vercel.app` (Render static site today: https://cte-system-app.onrender.com) |
| Live API (Render) | https://cte-system-api.onrender.com/docs (free plan: the first request after idle takes about a minute) |
| Requirement checklist | [Requirements coverage](#requirements-coverage) |
| Demo login (after seeding) | `demo@example.org` / `demo-password-123` (or click **Use the demo account**) |
| User guide | [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md) |
| Architecture and code flow | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) |
| Demo data | [`docs/DEMO_DATA.md`](docs/DEMO_DATA.md): 4 synthetic protocols, 10 synthetic patients, 9 reference assessments |
| Demo video automation | [`demo/README.md`](demo/README.md): records a narrated walkthrough (MP4 + screenshots) |

![Results page](docs/images/07-results-light.png)

---

## What it does

1. **Upload**: a protocol PDF (≤ 20 MB; magic bytes checked) and a patient profile (form or JSON).
2. **Document processing + RAG**: PyMuPDF extracts text per page. Chunks of about 500 characters with 100 overlap keep trial, document, page and section. A sentence-transformers (`all-MiniLM-L6-v2`) FAISS index is persisted per trial.
3. **Agent A, Protocol Extraction**: finds the Inclusion and Exclusion sections and turns each item into a `Criterion` (operator, threshold, unit, page, excerpt). Each excerpt is **verified to appear on its cited page**. If it doesn't, the criterion is flagged for review and its confidence drops.
4. **Agent B, Patient Profile**: normalizes lab names (aliases) and units (validated table only, e.g. creatinine µmol/L ÷ 88.4 → mg/dL). Flags missing, stale (> 90 days), conflicting and ambiguous values. An undocumented diagnosis is never treated as absent.
5. **Agents C ∥ D, Inclusion Matching and Exclusion Detection** (parallel LangGraph branches): deterministic comparators decide SATISFIED / UNSATISFIED / UNKNOWN and TRIGGERED / NOT_TRIGGERED / UNKNOWN.
6. **Agent E, Contradiction**: groups criteria by clinical domain (renal, hepatic, cardiac, …) and raises a Silent Exclusion Trigger when the patient passes some inclusion criteria but a related rule in that domain fails or is unresolved. It also records conflicting rules, inconsistent values and missing data.
7. **Web research** (optional, `WEB_SEARCH_PROVIDER=tavily`): for unresolved criteria with undefined wording ("severe renal impairment"), searches the web for how the term is defined and attaches the results as external references. Only protocol wording is sent, never patient data, and the references never change a decision.
8. **Agent F, Reviewer**: drops or downgrades any finding without evidence, then applies the conservative decision table. It also records the **patient values used** (with their unit-conversion trace and the criteria each one decided) and, from persistent memory, **what changed since the previous assessment** of the same patient for the same trial.
9. **Clinical NLP** (optional, `CLINICAL_NLP_ENABLED=true`): a BioBERT sentence model (`pritamdeka/BioBERT-mnli-snli-scinli-scitail-mednli-stsb`) compares an unresolved condition criterion with differently worded patient diagnoses (e.g. "progressive IgA nephropathy" vs "severe renal impairment") and adds a review note with the similarity score. It never changes a status or confirms a diagnosis.
10. **Results dashboard**: overall status, final explanation, silent exclusion triggers, triggered exclusions, inclusion and exclusion tables, patient values used, missing information, conflicts, protocol evidence behind the decision, external references, comparison with the previous assessment, audit trail, and an evidence viewer that shows the page text with the excerpt highlighted.
11. **Interface**: React + Tailwind with the Inter typeface (self-hosted), Light / Dark / System themes with no flash on load, animated stats and agent progress, toasts, outcome filters and search, a sticky results navigator, and phone-width layouts. Statuses always carry text labels, not colour alone.

### Decision rules (enforced in `app/agents/reviewer.py`)

- A proven exclusion always wins over passing inclusion criteria.
- UNKNOWN is never treated as SATISFIED or NOT_TRIGGERED.
- A missing or conflicting decisive value gives `MORE_INFORMATION_REQUIRED`, never `ELIGIBLE`.
- `ELIGIBLE` only when every inclusion is SATISFIED, no exclusion is TRIGGERED, and no material uncertainty remains.
- Ambiguous protocol wording ("severe", "adequate", unstated range inclusivity) is flagged for review and never silently interpreted. A value exactly on a boundary whose inclusivity is unstated evaluates to UNKNOWN.
- A diagnosis is never inferred from a single lab value unless the protocol defines it that way.

### The acceptance scenario

`tests/fixtures/protocol_renal.pdf` (generated, so page numbers are known):
page 2 holds the inclusion criteria and page 3 the exclusion criteria.

| Criterion | Protocol text (page) | Patient (69 y, eGFR 28) | Result |
|---|---|---|---|
| INC-01 | Age 18 to 70 years inclusive (p.2) | 69 | SATISFIED |
| INC-02 | eGFR must not be below 30 mL/min/1.73m2 (p.2) | 28 | UNSATISFIED |
| EXC-01 | Severe renal impairment (p.3), no numeric definition | not documented | UNKNOWN, requires review: *not confirmed by eGFR alone* |

Overall result: **NOT_ELIGIBLE**, with a renal-domain Silent Exclusion Trigger that links INC-01 and EXC-01
to INC-02 and cites pages 2 and 3. With `protocol_renal_defined.pdf` ("…defined as eGFR below 30"),
EXC-01 becomes **TRIGGERED**.

---

## Requirements coverage

| Requirement | Where it is met |
|---|---|
| Protocol Extraction Agent: reads the PDF, extracts and structures inclusion/exclusion criteria | `agents/protocol_extraction.py` (rule-based + LLM with schema validation, table layouts, page-verified excerpts) |
| Patient Profile Agent: demographics, lab normalization, diagnoses, medications, history | `agents/patient_profile.py`, `engine/units.py`, `engine/vocabulary.py` |
| Inclusion Matching Agent: SATISFIED / UNSATISFIED / UNKNOWN | `agents/inclusion_matching.py`, `engine/rule_evaluator.py` |
| Exclusion Detection Agent: TRIGGERED / NOT_TRIGGERED / UNKNOWN | `agents/exclusion_detection.py` |
| Contradiction Agent: silent exclusion triggers and conflicting criteria | `agents/contradiction.py` |
| Decision/Reviewer Agent: final status, evidence validation | `agents/reviewer.py` (evidence gate + conservative decision table) |
| The 69-year-old / eGFR 28 example → Silent Exclusion Trigger | `tests/test_acceptance.py`, see [the acceptance scenario](#the-acceptance-scenario) |
| Python, FastAPI, Pydantic, async APIs | `backend/app/` (FastAPI routes, Pydantic v2 schemas, background analysis with progress polling) |
| LangGraph agent orchestration | `workflow/graph.py` (parallel inclusion ∥ exclusion branches, error routing) |
| LLM API (Gemini / Claude / OpenAI) | `services/llm.py` (`LLM_PROVIDER`) |
| Clinical NLP model (BioBERT) where appropriate | `nlp/clinical.py`: advisory concept matching for unresolved condition criteria |
| Sentence Transformers, FAISS, RAG | `rag/` (all-MiniLM-L6-v2 + FAISS per trial; retrieval validated against cited pages) |
| PostgreSQL | `storage/postgres_store.py` (`DATABASE_URL`; Compose and Render run it) |
| Redis / workflow-state mechanism | `state/run_state.py` (`REDIS_URL`) + typed LangGraph state (`workflow/state.py`) |
| Short-term and persistent agent memory | LangGraph state + Redis during a run; stored criteria per protocol version and comparison with the previous assessment |
| Web Search API | `services/web_search.py`, `agents/web_research.py` (Tavily; protocol wording only) |
| PDF processing | `rag/pdf_loader.py` (PyMuPDF, magic-byte and size checks) |
| JWT authentication | `security/jwt.py`, `security/deps.py`; every record is owner-scoped |
| React, TypeScript, Tailwind frontend | `frontend/src/` |
| UI: overall status, inclusion table, exclusion table, patient values used, triggered exclusions, missing information, silent exclusion triggers, protocol evidence, final explanation | `frontend/src/pages/Results.tsx` |
| Traceability: which patient value and which protocol criterion produced the decision | `decisive_evidence`, `patient_values_used`, page-cited `evidence_references`, evidence viewer, audit trail |
| Not presented as an independent medical decision | `human_review_required: true` and a human-review notice on every result, in the API and the UI |
| Deployment: backend on Render, frontend on Vercel | `render.yaml`, `frontend/vercel.json`, [Deploy](#deploy) |

---

## Architecture

```
backend/app/
  main.py, config.py, errors.py (AppError raised by services)
  storage/           records.py (typed records); postgres_store.py (PostgreSQL, used when DATABASE_URL is set);
                     file_store.py (atomic JSON documents + audit log, the fallback)
  state/             run_state.py: live workflow state in Redis (REDIS_URL) or process memory
  schemas/           clinical.py (Criterion, CriterionEvaluation, SilentExclusionTrigger, EligibilityResult, …), api.py
  api/routes/        thin HTTP routers: auth, trials, patients, eligibility, health  (+ api/errors.py handlers)
  agents/            protocol_extraction, patient_profile, inclusion_matching, exclusion_detection, contradiction,
                     web_research, reviewer
  engine/            comparators.py, units.py, dates.py, vocabulary.py, rule_evaluator.py
  nlp/               clinical.py: optional BioBERT concept matcher (review notes only)
  rag/               pdf_loader.py, chunker.py, index.py (FAISS / keyword), retriever.py (retrieval validation)
  workflow/          state.py (typed state), graph.py (LangGraph)
  services/          use cases: auth, trials, patients, eligibility, analysis (background runs), audit, llm, web_search
  security/          jwt.py, deps.py
backend/tests/       tests + fixtures/ (synthetic PDFs, 4 synthetic patients)
backend/scripts/     make_synthetic_protocol.py, seed.py
frontend/src/        pages/ (Login, Dashboard, TrialUpload, PatientForm, Analysis, Results), components/, api/client.ts, types.ts
```

**Workflow** (`app/workflow/graph.py`):

```
validate_inputs → extract_protocol → normalize_patient → retrieve_evidence
   → [inclusion_matching ∥ exclusion_detection] → detect_contradictions → web_research
   → review_and_decide → persist → END
```

If the protocol is unreadable, the profile is invalid, or zero criteria are extracted, the run goes to
`handle_error`. That node writes a structured error, and the failed run is still persisted.
Missing patient data does not stop a run; the affected criteria are marked UNKNOWN. Each node's
start, end, status and output summary is written to the workflow state (Redis when `REDIS_URL` is set, otherwise
process memory) while the run executes, and copied into the run record (`agent_logs`) when it ends; the status
endpoint overlays the live state on the durable logs.
Persistence is idempotent by `run_id`: a retry overwrites the previous outcome instead of duplicating it.

**Storage.** With `DATABASE_URL` set, every record (users, trials, protocol documents with their extracted
criteria and page text, versioned patient profiles, runs with their results and agent logs) and the audit trail
are stored in **PostgreSQL**: one table per record type, with ownership and lookup columns as indexed columns
and foreign keys, and the full validated record as JSONB. The schema is created on startup, and row locks
(`SELECT … FOR UPDATE`) make concurrent updates safe across API workers. Docker Compose and the Render blueprint
both run PostgreSQL.

Without `DATABASE_URL` (quick local runs and the default test suite), the same records are JSON documents under
`DATA_DIR/store/`, and the audit trail is an append-only JSON Lines file per user:

```
backend/data/
  store/users/<id>.json  trials/  documents/  patients/  runs/  audit/<user_id>.jsonl
  uploads/<trial_id>/v1.pdf
  indexes/<trial_id>/<document_id>/
```

In file mode, writes are atomic (temporary file + `os.replace`) and serialized by a process-wide lock, so run
the API with a single worker. Record ids are UUIDs; any id that is not a plain token is treated as not found, so
URL input can never reach a path outside the store. To back up or move the data, copy `backend/data/`;
to start clean, stop the API and delete it.

**LLM use.** Only Agent A calls the LLM by default; it is also used for semantic (non-numeric)
criteria when configured. Model output must validate against a strict schema. If it doesn't, Agent A falls
back to the rule-based extractor and a semantic check becomes UNKNOWN. A semantic-only judgement can never
make a patient ELIGIBLE on its own: it yields MORE_INFORMATION_REQUIRED. PDF text is passed as untrusted
data, and the model is told never to follow instructions inside it.

**Memory.** Short-term: the typed LangGraph state shared by the agents during a run, plus the live workflow state in
Redis. Persistent: extracted criteria are stored per protocol version and reused (re-verified against the page text)
by later runs, and the reviewer compares each new assessment with the previous one for the same patient and trial.

**Tech stack.** Python 3.12 (the plan specified 3.11; the pinned NumPy 2.5 requires 3.12), FastAPI, Pydantic v2, LangGraph, PyMuPDF,
sentence-transformers + faiss-cpu, BioBERT (optional), PostgreSQL (psycopg 3), Redis, Tavily web search (optional),
python-jose, passlib/bcrypt. Frontend: React 18, TypeScript,
Vite, Tailwind, React Router, Axios. All versions are pinned (`backend/requirements.txt`, `frontend/package.json`).

---

## Run locally

### Option A: Docker Compose (PostgreSQL + Redis + API + UI)

```bash
cp .env.example .env               # then set JWT_SECRET (see the comment in the file)
docker compose up --build          # records in PostgreSQL, workflow state in Redis, PDFs in ./backend/data
# API  http://localhost:8000/docs     UI  http://localhost:5173
docker compose exec backend python -m scripts.seed --api-url http://localhost:8000 --analyze
```

### Option B: without Docker

```bash
# backend
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m scripts.make_synthetic_protocol          # writes tests/fixtures/*.pdf
uvicorn app.main:app --reload --port 8000           # file store in backend/data/; set DATABASE_URL / REDIS_URL to use PostgreSQL / Redis
python -m scripts.seed --api-url http://localhost:8000 --analyze   # demo user + data + the 69/28 run

# frontend (second terminal)
cd frontend
cp .env.example .env                # VITE_API_URL=http://localhost:8000
npm ci && npm run dev               # http://localhost:5173
```

Demo: log in as `demo@example.org` / `demo-password-123`. Under **New assessment**, choose
*SYN-RENAL-001* and *Synthetic patient A - age 69, eGFR 28*, then run it. The results page shows
**NOT ELIGIBLE** and a renal Silent Exclusion Trigger citing pages 2 and 3; click "p. 2" or "p. 3"
to see the highlighted excerpt.

On Linux, create the data folder before the first `docker compose up` so the container user can write to it:
`mkdir -p backend/data && sudo chown 10001 backend/data`.

---

## Environment variables

| Variable | Default | Notes |
|---|---|---|
| `APP_ENV` | `development` | `production` refuses to start without a strong `JWT_SECRET` |
| `DATA_DIR` | `./data` | Uploaded PDFs, per-trial retrieval indexes, and JSON records (`store/`) when `DATABASE_URL` is empty |
| `DATABASE_URL` | — | PostgreSQL connection string; when set, all records and the audit trail are stored there |
| `REDIS_URL` | — | Redis connection string for live workflow state; otherwise process memory |
| `RUN_STATE_TTL_SECONDS` | `86400` | How long live workflow state is kept in Redis |
| `JWT_SECRET` | dev placeholder | **Required in production**, at least 32 random characters |
| `JWT_EXPIRE_MINUTES` | `720` | |
| `FRONTEND_ORIGIN` | `http://localhost:5173` | CORS; comma-separated list |
| `FRONTEND_ORIGIN_REGEX` | — | Optional CORS regex, e.g. for Vercel preview URLs |
| `LLM_PROVIDER` | `none` | `gemini` \| `anthropic` \| `openai` \| `none` (offline, rule-based). Without `LLM_API_KEY` the app stays offline. |
| `LLM_API_KEY` / `LLM_MODEL` | — | Model defaults: `gemini-flash-latest` / `claude-opus-5-5` / `gpt-4o-mini`. Free Gemini key: https://aistudio.google.com/apikey |
| `EMBEDDINGS_ENABLED` | `true` | `false` uses the deterministic keyword retriever |
| `EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | |
| `CLINICAL_NLP_ENABLED` / `CLINICAL_NLP_MODEL` / `CLINICAL_NLP_THRESHOLD` | `false` / BioBERT STS model / `0.75` | Needs about 1 GB RAM |
| `WEB_SEARCH_PROVIDER` / `WEB_SEARCH_API_KEY` / `WEB_SEARCH_MAX_QUERIES` | `none` / — / `3` | `tavily`; free key at https://tavily.com |
| `MAX_UPLOAD_MB` / `STALE_DAYS` | `20` / `90` | |
| `VITE_API_URL` (frontend) | `http://localhost:8000` | Baked in at build time |

Secrets come only from the environment; `.env.example` contains placeholders only.

---

## API

All endpoints except `health`, `register` and `login` need `Authorization: Bearer <token>`. Every record
is checked against its owner, and another user's record returns **404** (its existence is not revealed).
Errors always look like `{"error": {"code", "message", "details"}}`. OpenAPI docs are at `/docs`.

| Method | Path | |
|---|---|---|
| POST | `/api/auth/register`, `/api/auth/login` | returns `access_token` + user |
| GET | `/api/auth/me` | |
| POST | `/api/trials/upload` | multipart `file` (+ `title`); PDF only, ≤ 20 MB; returns extracted criteria |
| GET | `/api/trials`, `/api/trials/{id}`, `/api/trials/{id}/criteria`, `/api/trials/{id}/pages/{page}` | |
| POST / GET | `/api/patients`, `/api/patients/{id}` | |
| PATCH | `/api/patients/{id}` | creates a **new profile version** |
| POST | `/api/eligibility/analyze` | `{trial_id, patient_id}` → `202 {run_id}`; runs in BackgroundTasks |
| GET | `/api/eligibility/{run_id}/status` | per-node progress |
| GET | `/api/eligibility/{run_id}`, `/evidence`, `/audit` | result, citations, audit trail + agent logs |
| GET | `/api/eligibility` | recent runs |
| GET | `/api/health` | storage backend, workflow-state backend, LLM, clinical NLP and web search status |

Each run is linked to the trial, the protocol version (`v1-<sha256 prefix>`) and the patient profile version.
Uploads, analysis requests and completions, and every read of results or evidence are written to the audit log (`store/audit/`).

---

## Tests

```bash
cd backend && pytest            # fully offline (LLM_PROVIDER=none, keyword retriever, file store)
TEST_DATABASE_URL=postgresql://user@localhost:5432/cte_test pytest   # the same suite against PostgreSQL
cd frontend && npm run build    # type-check + production build
```

Coverage includes:
- the mandatory acceptance test (`tests/test_acceptance.py`), including the defined-renal variant;
- outcomes: all-pass → ELIGIBLE, missing eGFR → MORE_INFORMATION_REQUIRED, conflicting eGFR → MORE_INFORMATION_REQUIRED with the conflict listed, and a proven exclusion beating passing inclusions;
- upload errors: non-PDF and unreadable uploads → 400 structured error, plus the size limit;
- extraction: ambiguous criterion → review flag, excerpt not on its cited page → flagged, invalid LLM JSON → rule-based fallback or UNKNOWN (no crash);
- engine: creatinine µmol/L → mg/dL conversion, comparator boundaries (70 inclusive, 30 not below), stale/conflicting/missing flags;
- security and persistence: user B cannot read user A's trial, patient or run (404), API round-trip with idempotent re-persistence, path-like ids rejected, security headers;
- file store (`tests/test_storage.py`) and PostgreSQL store (`tests/test_postgres_store.py`): records survive a restart, ownership scoping, atomic concurrent updates, append-only audit log, unsafe ids;
- workflow state (`tests/test_run_state.py`): Redis (fakeredis) and memory backends, expiry, fallback when Redis is down, a full API run through Redis;
- traceability extensions (`tests/test_traceability_extensions.py`): patient values used, web research context that never changes a decision and never sends patient data, clinical NLP notes that keep UNKNOWN, prior-assessment memory;
- retrieval: retrieval validation, plus the real FAISS path (skipped when the embedding model can't be loaded offline).

---

## Deploy

**Backend → Render.** Push the repo, then in Render choose *New → Blueprint* and select `render.yaml`. It creates
the Docker web service (`backend/Dockerfile`), a **PostgreSQL** database (`DATABASE_URL`) and a **Key Value (Redis)**
instance (`REDIS_URL`), and wires them together. `JWT_SECRET` is generated. Set `LLM_API_KEY` (Gemini has a free key)
and optionally `WEB_SEARCH_API_KEY` when prompted.
Free-plan notes: 512 MB RAM, the service sleeps when idle (first request after a sleep takes about a minute), and the
free PostgreSQL database expires 30 days after creation. Records are in PostgreSQL, so they survive restarts; uploaded
PDF files and retrieval indexes are on the service's local disk and are lost on restart, but page text and criteria
are in the database, so analyses and evidence pages keep working. Embeddings and BioBERT are off on the free plan
(`EMBEDDINGS_ENABLED=false`, `CLINICAL_NLP_ENABLED=false`); the keyword retriever, all agents and page citations work
unchanged. Seed the deployment with `python -m scripts.seed --api-url https://<render-host> --analyze`.

**Frontend → Vercel.** Import the repo in Vercel with root directory `frontend` (framework preset: Vite), set the
environment variable `VITE_API_URL=https://<render-host>` and deploy. `frontend/vercel.json` provides the SPA rewrite.
Then make sure the Vercel URL is allowed by the API: `render.yaml` allows `https://cte-system.vercel.app` and its
preview URLs (`FRONTEND_ORIGIN_REGEX`); if your project name differs, update `FRONTEND_ORIGIN` /
`FRONTEND_ORIGIN_REGEX` on the Render service. Record both URLs in the table at the top of this README.

**Frontend → Render static site (alternative).** The blueprint also defines `cte-system-app`, built with
`VITE_API_URL` pointing at the API.

---

## Limitations and future work

- **Scope cuts:** runs execute in FastAPI BackgroundTasks, not a job queue, so a run is lost if the process
  restarts mid-run (a retry is idempotent); no roles or refresh tokens. BioBERT is used only for advisory concept
  matching; numeric rules use deterministic comparators, and no model output decides eligibility on its own.
- The file store is built for one API process on one machine; use PostgreSQL (and Redis) to run several workers.
- Uploaded PDF files and retrieval indexes are kept on local disk even with PostgreSQL; a multi-host deployment
  would move them to object storage.
- The evidence viewer shows the page text with the excerpt highlighted; it does not render the PDF.
- The rule-based extractor targets numbered/bulleted criteria with common phrasings ("not below", "at least",
  "≥", ranges, "within N days"). Unusual layouts (tables, multi-column, scanned PDFs) need the LLM path or manual review.
  Scanned PDFs without a text layer are rejected.
- ULN-relative thresholds ("ALT > 3 × ULN") need the patient's reference range and are left for review.
- The condition vocabulary and domain map (`engine/vocabulary.py`) are small, hand-curated tables. A production
  system would map to SNOMED CT / ICD-10 / LOINC.
- One protocol version per trial (uploading again creates a new trial). Patient profiles are versioned.
- Model confidence is never presented as clinical certainty. Final eligibility always requires study-team review.
