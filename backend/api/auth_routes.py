"""Browser sign-in: server-side sessions in an HttpOnly cookie (no credential in
the JavaScript bundle). See security/sessions.py and security/users.py."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from config import settings
from security import sessions
from security.audit import audit_event
from utils.auth import Principal, authenticate

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    password: str = Field(..., min_length=1, max_length=256)


def _client(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _identity(principal: Principal, csrf: str | None) -> dict:
    return {"status": "success", "user": principal.name, "role": principal.role, "tenant": principal.tenant,
            "services": sorted(principal.services), "permissions": sorted(principal.permissions),
            "auth_method": principal.method, "csrf_token": csrf}


@router.post("/login")
def login(body: LoginRequest, request: Request, response: Response):
    from security.users import authenticate_password

    client = _client(request)
    if sessions.locked_out(body.username, client):
        audit_event("login_locked_out", None, username=body.username)
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            detail={"status": "error", "message": "Too many failed sign-in attempts. Try later."})
    user = authenticate_password(body.username, body.password)
    if user is None:
        sessions.record_failure(body.username, client)
        audit_event("login_failed", None, username=body.username)
        # Same message for unknown users and wrong passwords.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            detail={"status": "error", "message": "Invalid username or password."})
    sessions.reset_failures(body.username, client)
    token, session = sessions.create(user.username)
    response.set_cookie(sessions.COOKIE_NAME, token, httponly=True, secure=settings.SESSION_COOKIE_SECURE,
                        samesite="strict", path="/", max_age=settings.SESSION_TTL_MINUTES * 60)
    principal = user.principal()
    audit_event("login", principal)
    return _identity(principal, session.csrf)


@router.post("/logout")
def logout(request: Request, response: Response, principal: Principal = Depends(authenticate)):
    sessions.revoke(request.cookies.get(sessions.COOKIE_NAME))
    response.delete_cookie(sessions.COOKIE_NAME, path="/")
    audit_event("logout", principal)
    return {"status": "success"}


@router.get("/me")
def me(request: Request, principal: Principal = Depends(authenticate)):
    found = sessions.get(request.cookies.get(sessions.COOKIE_NAME)) if principal.method == "session" else None
    return _identity(principal, found[1].csrf if found else None)
