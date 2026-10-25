"""Structured logging: request / investigation / stage context on every record.

Every log record gets ``request_id``, ``investigation_id``, ``stage`` and
``principal`` (``-`` when unknown) from context variables, so lines from the
same request can be correlated across the API, the workflow stages and the LLM
layer. ``LOG_FORMAT=json`` emits one JSON object per line; the default text
format includes the request and investigation IDs.

What is logged: IDs, stage, provider, model, purpose, duration, outcome,
attempts, status codes, sizes. What is NOT logged: question text, prompts,
answers, record contents, API keys. As defence in depth the formatter redacts
anything that looks like a credential.
"""

import contextvars
import json
import logging
import re
import time
import uuid
from contextlib import contextmanager

FIELDS = ("request_id", "investigation_id", "stage", "principal")
_vars = {f: contextvars.ContextVar(f, default="-") for f in FIELDS}
# Extra structured fields a log call may pass with ``extra=``.
EXTRA_FIELDS = ("provider", "model", "purpose", "duration_ms", "outcome", "attempts", "status_code",
                "method", "path", "error_kind")
REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
SECRET_RE = re.compile(r"(sk-[A-Za-z0-9_-]{8,}|AIza[0-9A-Za-z_-]{20,}|(?i:bearer)\s+[A-Za-z0-9._~+/=-]{8,}"
                       r"|(?:pk|sk)-lf-[A-Za-z0-9-]{8,})")


def set_context(**values) -> dict:
    """Set context fields; returns tokens for ``reset_context``."""
    return {k: _vars[k].set(str(v)) for k, v in values.items() if k in _vars and v is not None}


def reset_context(tokens: dict) -> None:
    for k, t in tokens.items():
        _vars[k].reset(t)


def get(field: str) -> str:
    return _vars[field].get()


@contextmanager
def context(**values):
    tokens = set_context(**values)
    try:
        yield
    finally:
        reset_context(tokens)


def new_id() -> str:
    return uuid.uuid4().hex[:16]


def request_id_from(header: str | None) -> str:
    """Accept a caller's X-Request-ID only if it is a short safe token."""
    return header if header and REQUEST_ID_RE.match(header) else new_id()


# Personal data that may reach a log line (regex only - no NLP model per log line).
PII_LOG_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
                        r"|(?<![\w-])(?:\+?\d{1,3}[\s.-])?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}\b"
                        r"|(?i:\b(?:password|passwd|pwd|secret)\s*[:=]\s*\S+)"
                        r"|(?i:\b(?:employee|emp|staff)\s*(?:id|no\.?|number|#)?\s*[:#]?\s*\d{3,}\b)")


def redact(text: str) -> str:
    return PII_LOG_RE.sub("[REDACTED]", SECRET_RE.sub("[REDACTED]", text))


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        for f in FIELDS:
            if not hasattr(record, f):
                setattr(record, f, _vars[f].get())
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
               + f".{int(record.msecs):03d}Z",
               "level": record.levelname, "logger": record.name,
               "message": redact(record.getMessage())}
        out.update({f: getattr(record, f, "-") for f in FIELDS})
        out.update({f: getattr(record, f) for f in EXTRA_FIELDS if hasattr(record, f)})
        if record.exc_info:
            out["exception"] = redact(self.formatException(record.exc_info))
        return json.dumps(out, default=str)


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


TEXT_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | req=%(request_id)s inv=%(investigation_id)s | %(message)s"


def install(level: int, fmt: str) -> None:
    """Configure the root handler (idempotent)."""
    root = logging.getLogger()
    root.setLevel(level)
    if not root.handlers:
        root.addHandler(logging.StreamHandler())
    for handler in root.handlers:
        if not any(isinstance(f, ContextFilter) for f in handler.filters):
            handler.addFilter(ContextFilter())
        handler.setFormatter(JsonFormatter() if fmt == "json" else RedactingFormatter(TEXT_FORMAT))
