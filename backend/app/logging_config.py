"""Structured (JSON Lines) logging.

Every record is one JSON object, so messages containing quotes or newlines stay parseable by log
tooling. Log messages carry identifiers (run, trial, user ids), node names and error types only:
patient values, protocol text and LLM payloads are never logged.
"""

import json
import logging
import sys
from datetime import UTC, datetime


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


class _StderrHandler(logging.StreamHandler):
    """Always writes to the current sys.stderr (test runners and servers may replace it after startup)."""

    @property
    def stream(self):
        return sys.stderr

    @stream.setter
    def stream(self, _value) -> None:
        pass


def configure_logging(level: str) -> None:
    handler = _StderrHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
