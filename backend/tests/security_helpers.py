"""Helpers for security tests: users in the per-test temporary store, signed-in
HTTPS test clients (Secure cookies are only sent over https), CSRF headers."""

import json

from fastapi.testclient import TestClient

PASSWORD = "correct-horse-battery-staple"


def add_user(name: str, role: str, tenant: str = "default", services: list[str] | None = None) -> None:
    from security.users import add_user as _add

    _add(name, role, PASSWORD, tenant, services)


class Session:
    """A signed-in browser-like client: cookie jar + CSRF header on unsafe calls."""

    def __init__(self, client: TestClient, csrf: str, identity: dict):
        self.client, self.csrf, self.identity = client, csrf, identity

    def get(self, path: str, **kw):
        return self.client.get(path, **kw)

    def post(self, path: str, json_body=None, csrf: bool = True, **kw):
        headers = {**kw.pop("headers", {}), **({"X-CSRF-Token": self.csrf} if csrf else {})}
        return self.client.post(path, json=json_body, headers=headers, **kw)


def client():
    from app import app

    return TestClient(app, base_url="https://testserver")


def sign_in(name: str, password: str = PASSWORD) -> Session:
    c = client()
    r = c.post("/auth/login", json={"username": name, "password": password})
    assert r.status_code == 200, r.text
    return Session(c, r.json()["csrf_token"], r.json())


def two_tenant_policy(tmp_path) -> str:
    """acme owns payroll + leave; globex owns auth + gateway."""
    p = tmp_path / "policy.json"
    p.write_text(json.dumps({
        "tenants": {"acme": {"services": ["payroll-service", "leave-service"]},
                    "globex": {"services": ["auth-service", "gateway-service"]}},
        "runbooks": {"payment_failure": ["payroll-service"], "jwt_auth_failure": ["auth-service"],
                     "gateway_outage": ["gateway-service"], "database_timeout": ["*"]},
    }), encoding="utf-8")
    return str(p)
