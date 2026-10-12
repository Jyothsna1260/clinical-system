"""Test configuration: fully offline (no LLM, keyword retriever), isolated file store.

Set TEST_DATABASE_URL to run the whole suite (API tests included) against PostgreSQL instead.
"""

import json
import os
import shutil
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="cte-tests-"))
os.environ.update({
    "APP_ENV": "test",
    "DATA_DIR": str(_TMP / "data"),
    "LLM_PROVIDER": "none",
    "LLM_API_KEY": "",
    "EMBEDDINGS_ENABLED": "false",
    "JWT_SECRET": "test-secret",
    "DATABASE_URL": os.environ.get("TEST_DATABASE_URL", ""),
    "REDIS_URL": "",
    "WEB_SEARCH_PROVIDER": "none",
    "CLINICAL_NLP_ENABLED": "false",
    "AUTH_RATE_LIMIT_PER_MINUTE": "0",  # disabled for the suite; tests/test_audit_fixes.py enables it
})

import pytest  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


def _ensure_pdfs() -> None:
    from scripts.make_synthetic_protocol import DEMO_PROTOCOLS, make_demo_protocol, make_protocol
    from scripts.make_synthetic_protocol import FIXTURES as OUT

    for name, defined in (("protocol_renal.pdf", False), ("protocol_renal_defined.pdf", True)):
        if not (OUT / name).exists():
            make_protocol(OUT / name, defined)
    for name, spec in DEMO_PROTOCOLS.items():
        if not (OUT / name).exists():
            make_demo_protocol(OUT / name, spec)


_ensure_pdfs()


@pytest.fixture(scope="session")
def tmp_root() -> Path:
    return _TMP


@pytest.fixture
def fixture_path():
    return lambda name: FIXTURES / name


@pytest.fixture
def load_patient():
    def _load(name: str) -> dict:
        return json.loads((FIXTURES / name).read_text(encoding="utf-8"))

    return _load


@pytest.fixture
def renal_pages():
    from app.rag.pdf_loader import load_pdf

    return [p.to_dict() for p in load_pdf(FIXTURES / "protocol_renal.pdf")]


@pytest.fixture
def renal_defined_pages():
    from app.rag.pdf_loader import load_pdf

    return [p.to_dict() for p in load_pdf(FIXTURES / "protocol_renal_defined.pdf")]


@pytest.fixture
def run_workflow(load_patient):
    from app.workflow.graph import run_eligibility

    def _run(pages: list[dict], patient_fixture: str, **kwargs):
        patient = load_patient(patient_fixture)["profile"]
        return run_eligibility(run_id="test-run", trial_id="trial-test", pages=pages, patient_input=patient, **kwargs)

    return _run


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.main import app
    from app.security.rate_limit import reset_counter
    from app.state import reset_run_state
    from app.storage import get_store, reset_store

    shutil.rmtree(get_settings().data_dir, ignore_errors=True)
    reset_store()
    reset_run_state()
    reset_counter()
    if get_settings().database_url:
        get_store().truncate_all()
    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth_headers(client):
    def _make(email: str = "clinician@example.org") -> dict:
        r = client.post("/api/auth/register", json={"email": email, "password": "correct-horse-1", "full_name": "Test"})
        assert r.status_code == 201, r.text
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    return _make
