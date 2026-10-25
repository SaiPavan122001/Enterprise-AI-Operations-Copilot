"""Authentication / authorization: negative paths first. Qdrant and the workflow
are never reached on a rejected request (they are stubbed to fail loudly)."""

import pytest
from fastapi.testclient import TestClient

from app import app
from utils.auth import hash_key, parse_keys
from utils.rate_limit import investigate_limiter

INVESTIGATOR, VIEWER = "inv-key-" + "a" * 32, "view-key-" + "b" * 32
client = TestClient(app)
Q = {"question": "Why is payroll generation failing?"}


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    from api import routes
    from config import settings

    monkeypatch.setattr(settings, "AUTH_MODE", "api_key")
    monkeypatch.setattr(settings, "API_KEYS",
                        f"ops:investigator:{hash_key(INVESTIGATOR)},dash:viewer:{hash_key(VIEWER)}")
    monkeypatch.setattr(routes, "search_incidents", lambda query, limit, **k: [])

    class Boom:
        def invoke(self, *a, **k):
            raise AssertionError("workflow must not run")

        stream = invoke

    monkeypatch.setattr(routes, "rca_graph", Boom())
    investigate_limiter._hits.clear()
    yield
    investigate_limiter._hits.clear()


def bearer(key):
    return {"Authorization": f"Bearer {key}"}


@pytest.mark.parametrize("path", ["/investigate", "/investigate/stream", "/search"])
class TestEveryProtectedEndpoint:
    def body(self, path):
        return {"query": "payroll"} if path == "/search" else Q

    def test_missing_credentials(self, path):
        r = client.post(path, json=self.body(path))
        assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"
        assert r.json() == {"status": "error", "message": "Authentication required."}

    def test_invalid_key(self, path):
        assert client.post(path, json=self.body(path), headers=bearer("wrong-key")).status_code == 401

    def test_forged_key_using_the_stored_hash(self, path):
        assert client.post(path, json=self.body(path), headers=bearer(hash_key(INVESTIGATOR))).status_code == 401

    def test_wrong_scheme(self, path):
        r = client.post(path, json=self.body(path), headers={"Authorization": f"Basic {INVESTIGATOR}"})
        assert r.status_code == 401

    def test_not_configured_is_fail_closed(self, path, monkeypatch):
        from config import settings
        monkeypatch.setattr(settings, "API_KEYS", "")
        r = client.post(path, json=self.body(path), headers=bearer(INVESTIGATOR))
        assert r.status_code == 503

    def test_unknown_auth_mode_is_fail_closed(self, path, monkeypatch):
        from config import settings
        monkeypatch.setattr(settings, "AUTH_MODE", "maybe")
        assert client.post(path, json=self.body(path), headers=bearer(INVESTIGATOR)).status_code == 503


class TestRoles:
    def test_viewer_cannot_investigate(self):
        for path in ("/investigate", "/investigate/stream"):
            r = client.post(path, json=Q, headers=bearer(VIEWER))
            assert r.status_code == 403 and r.json()["message"] == "Not permitted."

    def test_viewer_can_search(self):
        assert client.post("/search", json={"query": "payroll"}, headers=bearer(VIEWER)).status_code == 200

    def test_x_api_key_header_accepted(self):
        assert client.post("/search", json={"query": "payroll"}, headers={"X-API-Key": VIEWER}).status_code == 200

    def test_health_is_public(self):
        assert client.get("/health").status_code == 200

    def test_explicitly_disabled_auth_allows_local_dev(self, monkeypatch):
        from config import settings
        monkeypatch.setattr(settings, "AUTH_MODE", "disabled")
        assert client.post("/search", json={"query": "payroll"}).status_code == 200


class TestKeyParsing:
    def test_malformed_entries_ignored_never_guessed(self):
        entries = parse_keys(f"good:viewer:{hash_key('x')},bad:superuser:{hash_key('y')},short:viewer:abc,noroles")
        assert [e.name for e in entries] == ["good"]


class TestRateLimitPerIdentity:
    def test_limit_counts_per_key_not_shared(self, monkeypatch):
        investigate_limiter._hits.clear()
        monkeypatch.setattr(investigate_limiter, "max_requests", 1)

        class Req:
            client = type("C", (), {"host": "10.0.0.1"})()

        assert investigate_limiter.check(Req(), "ops")
        assert not investigate_limiter.check(Req(), "ops")
        assert investigate_limiter.check(Req(), "other")     # same IP, different identity
