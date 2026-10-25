"""RBAC, sessions, CSRF, resource-level authorization and tenant isolation.
Negative paths first; nothing a client sends is trusted."""

import pytest

from security import access, sessions
from security.principals import ROLE_PERMISSIONS, Principal
from tests.security_helpers import PASSWORD, add_user, client, sign_in, two_tenant_policy


@pytest.fixture(autouse=True)
def enforced(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "AUTH_MODE", "enforced")
    monkeypatch.setattr(settings, "API_KEYS", "")


class TestSessions:
    def test_unauthenticated_requests_rejected(self):
        add_user("alice", "investigator")
        c = client()
        for method, path in (("post", "/investigate"), ("post", "/search"), ("get", "/tools"),
                             ("get", "/actions"), ("get", "/audit"), ("get", "/auth/me")):
            body = {"question": "Why is payroll generation failing?"} if path == "/investigate" else {"query": "x y"}
            r = getattr(c, method)(path, **({"json": body} if method == "post" else {}))
            assert r.status_code == 401, (path, r.status_code)

    def test_no_users_and_no_keys_is_fail_closed(self):
        assert client().post("/search", json={"query": "payroll"}).status_code == 503

    def test_login_sets_httponly_strict_secure_cookie(self):
        add_user("alice", "investigator")
        r = client().post("/auth/login", json={"username": "alice", "password": PASSWORD})
        cookie = r.headers["set-cookie"].lower()
        assert r.status_code == 200 and "httponly" in cookie and "samesite=strict" in cookie and "secure" in cookie
        assert "rca_session" in cookie and PASSWORD not in r.text

    def test_wrong_password_and_unknown_user_same_answer(self):
        add_user("alice", "investigator")
        a = client().post("/auth/login", json={"username": "alice", "password": "wrong-password-123"})
        b = client().post("/auth/login", json={"username": "nobody", "password": "wrong-password-123"})
        assert a.status_code == b.status_code == 401 and a.json() == b.json()

    def test_login_lockout_after_repeated_failures(self):
        add_user("alice", "investigator")
        c = client()
        for _ in range(5):
            c.post("/auth/login", json={"username": "alice", "password": "wrong-password-123"})
        assert c.post("/auth/login", json={"username": "alice", "password": PASSWORD}).status_code == 429

    def test_csrf_required_for_cookie_authenticated_unsafe_requests(self, monkeypatch):
        from api import routes
        monkeypatch.setattr(routes, "search_incidents", lambda **k: [])
        add_user("alice", "viewer")
        s = sign_in("alice")
        assert s.post("/search", {"query": "payroll"}, csrf=False).status_code == 403
        assert s.post("/search", {"query": "payroll"}, headers={"X-CSRF-Token": "forged"}, csrf=False).status_code == 403
        assert s.post("/search", {"query": "payroll"}).status_code == 200

    def test_logout_revokes_the_session(self):
        add_user("alice", "viewer")
        s = sign_in("alice")
        assert s.post("/auth/logout").status_code == 200
        assert s.get("/auth/me").status_code == 401

    def test_disabled_user_loses_access_immediately(self):
        from security.users import set_disabled
        add_user("alice", "viewer")
        s = sign_in("alice")
        set_disabled("alice")
        assert s.get("/auth/me").status_code == 401

    def test_role_is_read_from_the_server_on_every_request(self):
        from security.users import add_user as readd
        add_user("alice", "admin")
        s = sign_in("alice")
        readd("alice", "viewer", PASSWORD)          # demoted on the server
        assert s.get("/auth/me").json()["role"] == "viewer"
        assert s.get("/audit").status_code == 403

    def test_client_supplied_identity_fields_are_ignored(self, monkeypatch):
        from api import routes
        monkeypatch.setattr(routes, "search_incidents", lambda **k: [])
        add_user("vic", "viewer")
        s = sign_in("vic")
        forged = {"X-Role": "admin", "X-User": "root", "X-Tenant": "globex", "X-Permissions": "audit:read"}
        assert s.get("/audit", headers=forged).status_code == 403
        assert s.get("/auth/me", headers=forged).json()["role"] == "viewer"


class TestPermissions:
    @pytest.mark.parametrize("role,path,expected", [
        ("viewer", "/investigate", 403), ("viewer", "/actions", 200), ("viewer", "/audit", 403),
        ("investigator", "/audit", 403), ("admin", "/audit", 200),
    ])
    def test_role_matrix(self, role, path, expected):
        add_user("u", role)
        s = sign_in("u")
        r = s.post(path, {"question": "Why is payroll generation failing?"}) if path == "/investigate" \
            else s.get(path)
        assert r.status_code == expected

    def test_role_permissions_are_explicit_and_nested(self):
        assert ROLE_PERMISSIONS["viewer"] < ROLE_PERMISSIONS["investigator"] < ROLE_PERMISSIONS["admin"]
        assert "actions:approve" not in ROLE_PERMISSIONS["investigator"]
        assert Principal("x", "superuser").permissions == frozenset()      # unknown role: nothing


class TestResourceAccess:
    def test_principal_without_services_reads_nothing(self):
        p = Principal("x", "admin", "default", frozenset())
        assert not access.can_read(p, "payroll-service") and not access.can_read_runbook(p, "database_timeout")
        assert not access.can_read(None, "payroll-service")

    def test_unlisted_runbook_denied(self):
        p = access.system_principal()
        assert access.can_read_runbook(p, "payment_failure") and not access.can_read_runbook(p, "made_up_runbook")

    def test_scoped_detail_hides_other_services(self):
        p = Principal("x", "viewer", "acme", frozenset({"payroll-service"}))
        out = access.scoped_detail(p, "INC-009: DEP-109 belongs to auth-service ('Connection pool tuning')")
        assert "auth-service" not in out and "Connection pool" not in out and out.startswith("INC-009:")

    def test_workflow_without_principal_has_no_evidence(self):
        from workflows import rca_graph
        state = rca_graph.incident_node({"question": "Why is payroll generation failing?"})
        assert state["incidents"] == []


class TestTenantIsolation:
    @pytest.fixture
    def tenants(self, tmp_path, monkeypatch):
        from config import settings
        monkeypatch.setattr(settings, "ACCESS_POLICY_FILE", two_tenant_policy(tmp_path))
        add_user("ann", "investigator", tenant="acme")
        add_user("gus", "admin", tenant="globex")

    def test_identity_scope_comes_from_the_server_policy(self, tenants):
        assert sign_in("ann").identity["services"] == ["leave-service", "payroll-service"]

    def test_retrieval_only_returns_own_tenant_records(self, tenants):
        from workflows import rca_graph
        p = sign_in("ann")
        principal = Principal("ann", "investigator", "acme", frozenset(p.identity["services"]))
        state = rca_graph.incident_node({"question": "Users unable to login to the auth-service", "_principal": principal})
        assert all(i.service in {"payroll-service", "leave-service"} for i in state["incidents"])

    def test_named_incident_of_another_tenant_is_not_disclosed(self, tenants, monkeypatch):
        from agents.incident_matcher import MatchResult
        from workflows import rca_graph
        seen = {}
        monkeypatch.setattr(rca_graph, "match_incidents", lambda q, c: seen.setdefault("c", c) and MatchResult()
                            or MatchResult())
        principal = Principal("ann", "investigator", "acme", frozenset({"payroll-service", "leave-service"}))
        rca_graph.incident_matching_node({"question": "What caused INC-002?", "incidents": [], "_principal": principal})
        assert [c.incident_id for c in seen.get("c", [])] == []

    def test_search_endpoint_filters_by_tenant(self, tenants):
        s = sign_in("ann")
        r = s.post("/search", {"query": "users unable to login authentication", "limit": 20})
        assert r.status_code == 200
        assert {x["service"] for x in r.json()["results"]} <= {"payroll-service", "leave-service"}

    def test_tool_lookup_across_tenants_is_not_found(self, tenants):
        s = sign_in("ann")
        assert s.post("/tools/incident_lookup/invoke", {"args": {"incident_id": "INC-002"}}).status_code == 404
        assert s.post("/tools/incident_lookup/invoke", {"args": {"incident_id": "INC-001"}}).status_code == 200

    def test_audit_log_is_tenant_scoped(self, tenants):
        sign_in("ann").post("/tools/incident_lookup/invoke", {"args": {"incident_id": "INC-001"}})
        events = sign_in("gus").get("/audit").json()["events"]
        assert all(e.get("tenant") in ("globex", None) for e in events)
        assert not any(e.get("principal") == "ann" for e in events)


def test_api_key_scope_is_server_side(monkeypatch):
    from config import settings
    from utils.auth import hash_key
    monkeypatch.setattr(settings, "API_KEYS", f"svc:viewer:{hash_key('k' * 40)}:default:payroll-service")
    r = client().get("/auth/me", headers={"Authorization": "Bearer " + "k" * 40})
    assert r.json()["services"] == ["payroll-service"] and r.json()["auth_method"] == "api_key"


def test_session_store_clear_between_tests():
    assert sessions.get("anything") is None
