"""Authentication and authorization for the API.

Two ways to authenticate, both verified server-side:

* **Browser sessions** (the frontend): ``POST /auth/login`` with username and
  password (``security/users.py``) sets an HttpOnly, SameSite=Strict session
  cookie. No credential is ever placed in the JavaScript bundle. Unsafe requests
  must also carry the session's CSRF token (``X-CSRF-Token``).
* **API keys** (service accounts, scripts): ``Authorization: Bearer <key>`` or
  ``X-API-Key``. ``API_KEYS`` holds ``name:role:sha256hex[:tenant[:svc1|svc2]]``
  entries - only hashes are stored; comparison is constant-time.

Every request is mapped to a ``Principal`` (role, tenant, readable services)
built from server-side data only. Endpoints declare the permission they need
(``require_permission``); resource-level checks (which incidents, deployments,
logs, runbooks) happen in ``security/access.py`` and the workflow.

Fail-closed: with ``AUTH_MODE=enforced`` (default; ``api_key`` is an alias) and
neither a user nor a valid API key configured, protected endpoints answer 503.
``AUTH_MODE=disabled`` must be set explicitly (local development only): it is
logged as a warning and grants a fixed ``local-dev`` investigator identity in
the default tenant.
"""

import hashlib
import hmac
import logging
import secrets
import sys
from dataclasses import dataclass

from fastapi import HTTPException, Request, status

from config import settings
from security import sessions
from security.access import resolve_services
from security.principals import ROLES, Principal

logger = logging.getLogger(__name__)

__all__ = ["ROLES", "Principal", "authenticate", "require_permission", "require_role", "hash_key", "parse_keys"]

ENFORCED_MODES = ("enforced", "api_key")
UNSAFE_METHODS = ("POST", "PUT", "PATCH", "DELETE")


@dataclass(frozen=True)
class KeyEntry:
    name: str
    role: str
    digest: str
    tenant: str = "default"
    services: tuple[str, ...] = ()


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def parse_keys(raw: str | None) -> list[KeyEntry]:
    """Parse API_KEYS; malformed entries are rejected (logged), never guessed."""
    entries = []
    for n, item in enumerate(x.strip() for x in (raw or "").split(",") if x.strip()):
        parts = item.split(":")
        if not 3 <= len(parts) <= 5 or parts[1] not in ROLES or len(parts[2]) != 64 or \
                any(c not in "0123456789abcdef" for c in parts[2].lower()):
            logger.error("API_KEYS entry %d is malformed (expected name:role:sha256hex[:tenant[:services]]) "
                         "- ignored", n + 1)
            continue
        tenant = parts[3] if len(parts) > 3 and parts[3] else "default"
        services = tuple(s for s in (parts[4].split("|") if len(parts) > 4 else []) if s)
        entries.append(KeyEntry(parts[0], parts[1], parts[2].lower(), tenant, services))
    return entries


def _presented_key(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth[:7].lower() == "bearer ":
        return auth[7:].strip() or None
    return request.headers.get("x-api-key", "").strip() or None


def _dev_principal() -> Principal:
    return Principal("local-dev", "investigator", "default", resolve_services("default", None), method="dev")


def _session_principal(request: Request) -> Principal | None:
    from security.users import get_user

    found = sessions.get(request.cookies.get(sessions.COOKIE_NAME))
    if found is None:
        return None
    sid, s = found
    user = get_user(s.username)              # fresh role/tenant/grants every request
    if user is None or user.disabled:
        sessions.revoke(request.cookies.get(sessions.COOKIE_NAME))
        return None
    if request.method in UNSAFE_METHODS and not hmac.compare_digest(
            request.headers.get("x-csrf-token", ""), s.csrf):
        logger.warning("Rejected cookie-authenticated %s without a valid CSRF token", request.method)
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            detail={"status": "error", "message": "Missing or invalid CSRF token."})
    return user.principal(session_id=sid)


def authenticate(request: Request) -> Principal:
    mode = settings.AUTH_MODE
    if mode == "disabled":
        return _dev_principal()
    if mode not in ENFORCED_MODES:
        logger.error("Unknown AUTH_MODE %r - refusing requests", mode)
        raise _unavailable()
    principal = _session_principal(request)
    if principal is not None:
        return principal
    entries = parse_keys(settings.API_KEYS)
    if not entries and not _has_users():
        logger.error("Authentication is enabled but no user or API key is configured - refusing requests")
        raise _unavailable()
    key = _presented_key(request)
    if not key:
        raise _unauthorized("Authentication required.")
    if not entries:
        raise _unauthorized("Invalid credentials.")
    digest = hash_key(key)
    match = None
    for e in entries:                      # no early exit: same work for every key
        if hmac.compare_digest(e.digest, digest):
            match = e
    if match is None:
        logger.warning("Rejected request with an invalid API key")
        raise _unauthorized("Invalid credentials.")
    return Principal(match.name, match.role, match.tenant, resolve_services(match.tenant, list(match.services)),
                     method="api_key")


def _has_users() -> bool:
    from security.users import has_users

    try:
        return has_users()
    except Exception:
        return False


def require_permission(permission: str):
    """FastAPI dependency: authenticated principal holding ``permission``."""
    def dependency(request: Request) -> Principal:
        principal = authenticate(request)
        if not principal.has(permission):
            logger.warning("Principal %s (role %s) denied %s on %s", principal.name, principal.role,
                           permission, request.url.path)
            _audit_denied(principal, permission, request.url.path)
            raise forbidden()
        request.state.principal = principal
        return principal

    return dependency


def require_role(role: str):
    """Compatibility: the permissions of the lowest role that needs ``role``."""
    needed = ROLES.index(role)

    def dependency(request: Request) -> Principal:
        principal = authenticate(request)
        if ROLES.index(principal.role) < needed:
            raise forbidden()
        request.state.principal = principal
        return principal

    return dependency


def _audit_denied(principal: Principal, permission: str, path: str) -> None:
    from security.audit import audit_event

    audit_event("authorization_denied", principal, permission=permission, path=path)


def forbidden(message: str = "Not permitted.") -> HTTPException:
    return HTTPException(status.HTTP_403_FORBIDDEN, detail={"status": "error", "message": message})


def _unauthorized(message: str) -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail={"status": "error", "message": message},
                         headers={"WWW-Authenticate": "Bearer"})


def _unavailable() -> HTTPException:
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                         detail={"status": "error", "message": "Service is not configured for access."})


def startup_check() -> None:
    if settings.AUTH_MODE == "disabled":
        logger.warning("AUTH_MODE=disabled - the API is UNAUTHENTICATED. Use only for local development.")
    elif not parse_keys(settings.API_KEYS) and not _has_users():
        logger.error("Authentication is enforced but no user or API key is configured - protected endpoints "
                     "will return 503. Create a user: python -m security.users add <name> --role investigator")


if __name__ == "__main__":
    # python -m utils.auth new <name> <role> [tenant] [svc1|svc2]  -> new key (shown once) + API_KEYS entry
    # python -m utils.auth hash <key>                               -> sha256 of an existing key
    args = sys.argv[1:]
    if args[:1] == ["new"] and 3 <= len(args) <= 5 and args[2] in ROLES:
        k = secrets.token_urlsafe(32)
        extra = "".join(f":{x}" for x in args[3:])
        print(f"key (give to the caller, store nowhere else): {k}")
        print(f"API_KEYS entry: {args[1]}:{args[2]}:{hash_key(k)}{extra}")
    elif args[:1] == ["hash"] and len(args) == 2:
        print(hash_key(args[1]))
    else:
        raise SystemExit("usage: python -m utils.auth new <name> <viewer|investigator|admin> [tenant] [svc1|svc2]"
                         " | hash <key>")
