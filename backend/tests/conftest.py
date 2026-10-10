"""Test configuration: fully offline (no LLM, keyword retriever), isolated file store."""

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
})

import pytest  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


def _ensure_pdfs() -> None:
    from scripts.make_synthetic_protocol import DEMO_PROTOCOLS, FIXTURES as OUT, make_demo_protocol, make_protocol

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
    from app.storage import reset_store

    shutil.rmtree(get_settings().data_dir, ignore_errors=True)
    reset_store()
    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth_headers(client):
    def _make(email: str = "clinician@example.org") -> dict:
        r = client.post("/api/auth/register", json={"email": email, "password": "correct-horse-1", "full_name": "Test"})
        assert r.status_code == 201, r.text
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    return _make
