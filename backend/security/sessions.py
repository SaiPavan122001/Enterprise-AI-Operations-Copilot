"""Server-side browser sessions.

The browser holds only an opaque random token in an HttpOnly, SameSite=Strict
cookie (JavaScript cannot read it). The server stores sha256(token) -> session;
the user's role, tenant and grants are re-read from the user store on EVERY
request, so disabling a user or changing a role takes effect immediately.

CSRF: state-changing requests authenticated by the cookie must also send the
session's CSRF token in ``X-CSRF-Token`` (returned by /auth/login and /auth/me,
kept in page memory, never in storage).

LIMITATION: sessions live in this process's memory (single-process deployment,
like the rate limiter); a restart signs everyone out.
"""

import hashlib
import secrets
import threading
import time
from dataclasses import dataclass

from config import settings

COOKIE_NAME = "rca_session"


@dataclass
class Session:
    username: str
    csrf: str
    created: float
    last_seen: float


_sessions: dict[str, Session] = {}
_failures: dict[str, list[float]] = {}
_lock = threading.Lock()


def _key(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create(username: str) -> tuple[str, Session]:
    token = secrets.token_urlsafe(32)
    now = time.time()
    s = Session(username=username, csrf=secrets.token_urlsafe(24), created=now, last_seen=now)
    with _lock:
        _sessions[_key(token)] = s
    return token, s


def get(token: str | None) -> tuple[str, Session] | None:
    """Valid session for the token (sliding idle timeout, absolute lifetime)."""
    if not token:
        return None
    k = _key(token)
    now = time.time()
    with _lock:
        s = _sessions.get(k)
        if s is None:
            return None
        if now - s.created > settings.SESSION_TTL_MINUTES * 60 or \
                now - s.last_seen > settings.SESSION_IDLE_MINUTES * 60:
            del _sessions[k]
            return None
        s.last_seen = now
        return k, s


def revoke(token: str | None) -> None:
    if token:
        with _lock:
            _sessions.pop(_key(token), None)


def revoke_user(username: str) -> None:
    with _lock:
        for k in [k for k, s in _sessions.items() if s.username == username]:
            del _sessions[k]


def clear() -> None:
    with _lock:
        _sessions.clear()
        _failures.clear()


# --------------------------------------------------------------------------- login throttling

def _fkey(username: str, client: str) -> str:
    return f"{username.lower()}|{client}"


def locked_out(username: str, client: str) -> bool:
    window = settings.LOGIN_LOCKOUT_MINUTES * 60
    now = time.time()
    with _lock:
        hits = [t for t in _failures.get(_fkey(username, client), []) if now - t < window]
        _failures[_fkey(username, client)] = hits
        return len(hits) >= settings.LOGIN_MAX_FAILURES


def record_failure(username: str, client: str) -> None:
    with _lock:
        _failures.setdefault(_fkey(username, client), []).append(time.time())


def reset_failures(username: str, client: str) -> None:
    with _lock:
        _failures.pop(_fkey(username, client), None)
