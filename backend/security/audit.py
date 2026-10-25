"""Append-only security audit trail (JSON lines under ``AUDIT_DIR``).

Records authorization denials, tool invocations and every approval-lifecycle
transition with who, what (redacted arguments), when and the request ID.
Free-text values are passed through PII redaction before they are written.
Fail-soft for reads; a write failure is logged as an error (never silently).
"""

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path

from config import settings
from utils import log_context

logger = logging.getLogger(__name__)
_lock = threading.Lock()


def _path() -> Path:
    return Path(settings.AUDIT_DIR) / "audit.jsonl"


def _clean(value):
    from security.pii import redact_text

    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    return value


def audit_event(kind: str, principal=None, **fields) -> dict:
    event = {"at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"), "event": kind,
             "request_id": log_context.get("request_id"),
             "principal": getattr(principal, "name", None), "role": getattr(principal, "role", None),
             "tenant": getattr(principal, "tenant", None), **_clean(fields)}
    try:
        p = _path()
        p.parent.mkdir(parents=True, exist_ok=True)
        with _lock, open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, default=str) + "\n")
    except OSError:
        logger.error("Audit write failed for event %s", kind)
    return event


def read_events(tenant: str, limit: int = 200) -> list[dict]:
    p = _path()
    if not p.exists():
        return []
    rows = [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [r for r in rows if r.get("tenant") == tenant][-limit:]
