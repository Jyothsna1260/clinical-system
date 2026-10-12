"""Gemini client: request shape, schema fallback and error handling (HTTP is faked, no key needed)."""

import httpx
import pytest

from app.config import Settings
from app.services.llm import GeminiLLM, LLMError, get_llm

SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}}


def _response(status: int, payload: dict | None = None) -> httpx.Response:
    return httpx.Response(status, json=payload or {}, request=httpx.Request("POST", "https://example.test"))


def _ok(text: str) -> httpx.Response:
    return _response(200, {"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}]})


@pytest.fixture(autouse=True)
def no_backoff_sleep(monkeypatch):
    """Retries back off with time.sleep; skip the waiting in tests."""
    monkeypatch.setattr("app.services.llm.time.sleep", lambda _s: None)


def test_transient_errors_are_retried_then_succeed(monkeypatch):
    responses = iter([_response(503), _response(429), _ok('{"ok": true}')])
    calls = []

    def fake_post(*a, **k):
        calls.append(1)
        return next(responses)

    monkeypatch.setattr(httpx, "post", fake_post)
    assert GeminiLLM("k", "m", 5).complete_json("s", "u", SCHEMA) == {"ok": True}
    assert len(calls) == 3


def test_timeouts_are_retried_then_raise_llm_error(monkeypatch):
    calls = []

    def fake_post(*a, **k):
        calls.append(1)
        raise httpx.ReadTimeout("slow")

    monkeypatch.setattr(httpx, "post", fake_post)
    with pytest.raises(LLMError):
        GeminiLLM("k", "m", 5).complete_json("s", "u", SCHEMA)
    assert len(calls) == 3  # first try + 2 retries


def test_get_llm_builds_gemini_client_with_default_model():
    llm = get_llm(Settings(llm_provider="gemini", llm_api_key="k"))
    assert isinstance(llm, GeminiLLM) and llm.model == "gemini-flash-latest"
    assert get_llm(Settings(llm_provider="gemini", llm_api_key="")) is None


def test_sends_key_header_and_json_schema(monkeypatch):
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append((url, headers, json))
        return _ok('{"ok": true}')

    monkeypatch.setattr(httpx, "post", fake_post)
    assert GeminiLLM("secret", "gemini-flash-latest", 5).complete_json("sys", "user", SCHEMA) == {"ok": True}
    url, headers, body = calls[0]
    assert url.endswith("/gemini-flash-latest:generateContent")
    assert headers == {"x-goog-api-key": "secret"}
    assert body["generationConfig"]["responseJsonSchema"] == SCHEMA
    assert body["systemInstruction"]["parts"][0]["text"] == "sys"


def test_retries_without_schema_when_rejected(monkeypatch):
    responses = iter([_response(400, {"error": {"message": "bad schema"}}), _ok('{"ok": false}')])
    bodies = []

    def fake_post(url, headers, json, timeout):
        bodies.append(json)
        return next(responses)

    monkeypatch.setattr(httpx, "post", fake_post)
    assert GeminiLLM("k", "m", 5).complete_json("s", "u", SCHEMA) == {"ok": False}
    assert "responseJsonSchema" not in bodies[1]["generationConfig"]


@pytest.mark.parametrize("response", [
    _response(429),
    _response(500),
    _ok("not json"),
    _response(200, {"candidates": []}),
    _response(200, {"candidates": [{"content": {"parts": [{"text": "{"}]}, "finishReason": "MAX_TOKENS"}]}),
])
def test_failures_raise_llm_error(monkeypatch, response):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: response)
    with pytest.raises(LLMError):
        GeminiLLM("k", "m", 5).complete_json("s", "u", SCHEMA)
