"""Web search for external context on ambiguous protocol criteria.

When a criterion is worded without a definition ("severe renal impairment", "adequate hepatic
function"), the reviewer benefits from seeing how such terms are commonly defined. The web
research step searches for the criterion wording and attaches the top results to the result as
external references.

Privacy and safety rules:
- Only protocol wording is sent to the search provider, never patient data.
- External references are shown to the reviewer as context. They never change a criterion's
  status or the overall decision, which stay grounded in the protocol and the patient record.
"""

import logging
from typing import Protocol

import httpx

from app.config import Settings

log = logging.getLogger(__name__)

TAVILY_URL = "https://api.tavily.com/search"


class WebSearchClient(Protocol):
    provider: str

    def search(self, query: str, max_results: int = 3) -> list[dict]:
        """Results as {"title", "url", "snippet"}."""
        ...


class TavilySearch:
    provider = "tavily"

    def __init__(self, api_key: str, timeout: float = 10.0):
        self._api_key = api_key
        self._timeout = timeout

    def search(self, query: str, max_results: int = 3) -> list[dict]:
        response = httpx.post(
            TAVILY_URL,
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={"query": query, "max_results": max_results, "search_depth": "basic", "include_answer": False},
            timeout=self._timeout,
        )
        response.raise_for_status()
        out = []
        for item in response.json().get("results", [])[:max_results]:
            url = str(item.get("url") or "")
            if not url.startswith(("https://", "http://")):
                continue
            out.append({"title": str(item.get("title") or url)[:300], "url": url[:2000],
                        "snippet": str(item.get("content") or "")[:600]})
        return out


def get_web_search(settings: Settings) -> WebSearchClient | None:
    if not settings.web_search_enabled:
        return None
    if settings.web_search_provider == "tavily":
        return TavilySearch(settings.web_search_api_key or "")
    return None
