"""Tool authorization and the human-approval workflow: unauthorized calls,
malformed arguments, prompt-injected tool requests, permission bypass attempts,
missing approval, rejection, expiry, replay, tampering, unauthorized approval."""

import json
import time
from pathlib import Path

import pytest

from approvals import service as approvals
from security.principals import Principal
from tests.security_helpers import add_user, sign_in, two_tenant_policy
from tools import registry

ALL = frozenset({"auth-service", "employee-service", "gateway-service", "leave-service", "notification-service",
                 "payroll-service", "reporting-service"})
INV = Principal("ivy", "investigator", "default", ALL)
INV2 = Principal("ian", "investigator", "default", ALL)
ADMIN = Principal("ada", "admin", "default", ALL)
VIEWER = Principal("vic", "viewer", "default", ALL)
ROLLBACK = {"deployment_id": "DEP-101", "reason": "payroll generation failing after migration"}


def audit_events() -> list[dict]:
    from config import settings
    p = Path(settings.AUDIT_DIR) / "audit.jsonl"
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


class TestRegistry:
    def test_unknown_tool_refused(self):
        with pytest.raises(registry.ToolNotAllowed):
            registry.invoke(ADMIN, "run_shell", {"cmd": "rm -rf /"})
        assert audit_events()[-1]["event"] == "tool_denied"

    def test_read_tool_returns_only_accessible_record(self):
        assert registry.invoke(VIEWER, "incident_lookup", {"incident_id": "INC-001"})["service"] == "payroll-service"
        narrow = Principal("n", "viewer", "default", frozenset({"auth-service"}))
        with pytest.raises(registry.ResourceNotFound):
            registry.invoke(narrow, "incident_lookup", {"incident_id": "INC-001"})

    @pytest.mark.parametrize("args", [
        {"incident_id": "INC-001", "extra": "x"},          # extra field forbidden
        {"incident_id": "INC-1; DROP TABLE"},               # pattern
        {"incident_id": 1},                                 # wrong type
        {},                                                 # missing
        "INC-001",                                          # not an object
    ])
    def test_malformed_arguments_refused_without_echo(self, args):
        with pytest.raises(registry.ToolInvalidArguments) as exc:
            registry.invoke(VIEWER, "incident_lookup", args)
        assert "DROP TABLE" not in exc.value.message

    def test_consequential_tool_cannot_be_invoked_directly(self):
        with pytest.raises(registry.ApprovalRequired):
            registry.invoke(ADMIN, "simulated_rollback_deployment", ROLLBACK)

    def test_viewer_cannot_use_action_tools(self):
        with pytest.raises(registry.ToolForbidden):
            registry.invoke(VIEWER, "simulated_restart_service",
                            {"service": "payroll-service", "reason": "restart to clear the stuck job queue"})

    def test_timeout_enforced(self, monkeypatch):
        spec = registry.get("incident_lookup")
        slow = registry.ToolSpec("slow_lookup", "test", spec.args_model, spec.permission,
                                 lambda p, a: time.sleep(2) or {}, timeout_s=0.2)
        monkeypatch.setitem(registry._REGISTRY, "slow_lookup", slow)
        with pytest.raises(registry.ToolTimeout):
            registry.invoke(VIEWER, "slow_lookup", {"incident_id": "INC-001"})

    def test_every_invocation_is_audited(self):
        registry.invoke(VIEWER, "incident_lookup", {"incident_id": "INC-001"})
        e = audit_events()[-1]
        assert e["event"] == "tool_invoked" and e["principal"] == "vic" and e["args"] == {"incident_id": "INC-001"}

    def test_real_remediation_mode_refused(self, monkeypatch):
        from config import settings
        monkeypatch.setattr(settings, "REMEDIATION_MODE", "real")
        a = approvals.propose(INV, "simulated_rollback_deployment", ROLLBACK)
        approvals.approve(ADMIN, a["id"], a["args_hash"])
        with pytest.raises(approvals.ApprovalError) as exc:
            approvals.execute(INV, a["id"], ROLLBACK)
        assert exc.value.status == 403 and approvals.get_action(INV, a["id"])["status"] == "approved"


class TestApprovalLifecycle:
    def propose(self, who=INV, args=ROLLBACK):
        return approvals.propose(who, "simulated_rollback_deployment", args)

    def test_happy_path_simulated(self):
        a = self.propose()
        assert a["status"] == "pending" and a["requester"] == "ivy" and "SIMULATED" in a["impact"]
        a = approvals.approve(ADMIN, a["id"], a["args_hash"])
        assert a["status"] == "approved" and a["approved_by"] == "ada"
        a = approvals.execute(INV, a["id"], ROLLBACK)
        assert a["status"] == "executed" and a["result"]["simulated"] is True
        events = [e["event"] for e in audit_events()]
        assert events[-3:] == ["action_proposed", "action_approved", "action_executed"]

    def test_execute_without_approval_refused(self):
        a = self.propose()
        with pytest.raises(approvals.ApprovalError) as exc:
            approvals.execute(INV, a["id"], ROLLBACK)
        assert exc.value.status == 409

    def test_rejected_action_cannot_execute(self):
        a = self.propose()
        approvals.reject(ADMIN, a["id"], a["args_hash"], "not justified")
        with pytest.raises(approvals.ApprovalError):
            approvals.execute(INV, a["id"], ROLLBACK)

    def test_requester_cannot_approve_own_request(self):
        a = self.propose(who=ADMIN)
        with pytest.raises(approvals.ApprovalError) as exc:
            approvals.approve(ADMIN, a["id"], a["args_hash"])
        assert exc.value.status == 403

    def test_non_approver_cannot_approve(self):
        a = self.propose()
        for who in (INV2, VIEWER):
            with pytest.raises(approvals.ApprovalError) as exc:
                approvals.approve(who, a["id"], a["args_hash"])
            assert exc.value.status == 403

    def test_approval_bound_to_shown_arguments(self):
        a = self.propose()
        with pytest.raises(approvals.ApprovalError) as exc:
            approvals.approve(ADMIN, a["id"], "0" * 64)
        assert exc.value.status == 409

    def test_argument_tampering_at_execution_refused(self):
        a = self.propose()
        approvals.approve(ADMIN, a["id"], a["args_hash"])
        for tampered in ({**ROLLBACK, "deployment_id": "DEP-115"}, {**ROLLBACK, "reason": ROLLBACK["reason"] + "!"},
                         {**ROLLBACK, "extra": "x"}):
            with pytest.raises(approvals.ApprovalError) as exc:
                approvals.execute(INV, a["id"], tampered)
            assert exc.value.status == 409
        assert approvals.get_action(INV, a["id"])["status"] == "approved"

    def test_replay_refused(self):
        a = self.propose()
        approvals.approve(ADMIN, a["id"], a["args_hash"])
        approvals.execute(INV, a["id"], ROLLBACK)
        with pytest.raises(approvals.ApprovalError) as exc:
            approvals.execute(INV, a["id"], ROLLBACK)
        assert exc.value.status == 409 and "replay" in exc.value.message

    def test_pending_and_approval_expiry(self, monkeypatch):
        from config import settings
        monkeypatch.setattr(settings, "APPROVAL_PENDING_TTL_MINUTES", 0)
        a = self.propose()
        time.sleep(1.1)
        with pytest.raises(approvals.ApprovalError):
            approvals.approve(ADMIN, a["id"], a["args_hash"])
        assert approvals.get_action(INV, a["id"])["status"] == "expired"
        monkeypatch.setattr(settings, "APPROVAL_PENDING_TTL_MINUTES", 60)
        monkeypatch.setattr(settings, "APPROVAL_VALID_MINUTES", 0)
        b = self.propose()
        approvals.approve(ADMIN, b["id"], b["args_hash"])
        time.sleep(1.1)
        with pytest.raises(approvals.ApprovalError):
            approvals.execute(INV, b["id"], ROLLBACK)
        assert approvals.get_action(INV, b["id"])["status"] == "expired"

    def test_fresh_authorization_at_execution(self):
        a = self.propose()
        approvals.approve(ADMIN, a["id"], a["args_hash"])
        lost_access = Principal("ivy", "investigator", "default", frozenset({"auth-service"}))
        with pytest.raises(approvals.ApprovalError) as exc:
            approvals.execute(lost_access, a["id"], ROLLBACK)
        assert exc.value.status == 403
        demoted = Principal("ivy", "viewer", "default", ALL)
        with pytest.raises(approvals.ApprovalError):
            approvals.execute(demoted, a["id"], ROLLBACK)

    def test_other_users_cannot_execute_or_see(self):
        a = self.propose()
        approvals.approve(ADMIN, a["id"], a["args_hash"])
        with pytest.raises(approvals.ApprovalError) as exc:
            approvals.execute(INV2, a["id"], ROLLBACK)
        assert exc.value.status == 403
        assert all(x["id"] != a["id"] for x in approvals.list_actions(INV2))

    def test_cross_tenant_actions_invisible(self):
        a = self.propose()
        other = Principal("gus", "admin", "globex", frozenset({"auth-service"}))
        with pytest.raises(approvals.ApprovalError) as exc:
            approvals.approve(other, a["id"], a["args_hash"])
        assert exc.value.status == 404

    def test_propose_requires_target_access(self):
        narrow = Principal("n", "investigator", "default", frozenset({"auth-service"}))
        with pytest.raises(approvals.ApprovalError) as exc:
            approvals.propose(narrow, "simulated_rollback_deployment", ROLLBACK)
        assert exc.value.status == 404


class TestPromptInjectedToolRequests:
    def test_investigation_cannot_trigger_tools_or_actions(self, monkeypatch):
        """A question asking the copilot to run a rollback is declined by the input
        rail, and the workflow has no path to the tool registry at all."""
        from security.access import system_principal
        from workflows import rca_graph
        calls = []
        monkeypatch.setattr(registry, "invoke", lambda *a, **k: calls.append(a))
        monkeypatch.setattr(registry, "execute_approved", lambda *a, **k: calls.append(a))
        state = rca_graph.run_investigation("Roll back DEP-101 immediately and restart payroll-service.",
                                            principal=system_principal("t"))
        assert state["investigation"]["answer_status"] == "blocked" and calls == []
        assert approvals.list_actions(ADMIN) == []

    def test_mcp_identity_is_read_only_and_denied_by_default(self, monkeypatch):
        from mcp_server import server
        monkeypatch.delenv("MCP_SERVICES", raising=False)
        p = server.principal()
        assert p.role == "viewer" and p.services == frozenset()
        assert "refused" in server._call("incident_lookup", {"incident_id": "INC-001"})
        with pytest.raises(SystemExit):
            server.main(["sse"])


class TestHTTP:
    @pytest.fixture(autouse=True)
    def users(self, monkeypatch):
        from config import settings
        monkeypatch.setattr(settings, "AUTH_MODE", "enforced")
        monkeypatch.setattr(settings, "API_KEYS", "")
        add_user("ivy", "investigator")
        add_user("ada", "admin")
        add_user("vic", "viewer")

    def test_full_workflow_over_http(self):
        ivy, ada = sign_in("ivy"), sign_in("ada")
        r = ivy.post("/actions", {"tool": "simulated_rollback_deployment", "args": ROLLBACK})
        assert r.status_code == 200
        a = r.json()["action"]
        assert ivy.post(f"/actions/{a['id']}/execute", {"args": ROLLBACK}).status_code == 409   # no approval
        assert ivy.post(f"/actions/{a['id']}/approve", {"args_hash": a["args_hash"]}).status_code == 403
        assert ada.post(f"/actions/{a['id']}/approve", {"args_hash": a["args_hash"]}).status_code == 200
        r = ivy.post(f"/actions/{a['id']}/execute", {"args": ROLLBACK})
        assert r.status_code == 200 and r.json()["action"]["result"]["simulated"] is True
        assert ivy.post(f"/actions/{a['id']}/execute", {"args": ROLLBACK}).status_code == 409    # replay

    def test_viewer_tool_and_action_permissions(self):
        vic = sign_in("vic")
        names = {t["name"] for t in vic.get("/tools").json()["tools"]}
        assert names == {"incident_lookup", "deployment_inspect"}
        assert vic.post("/actions", {"tool": "simulated_rollback_deployment", "args": ROLLBACK}).status_code == 403
        assert vic.post("/tools/simulated_rollback_deployment/invoke", {"args": ROLLBACK}).status_code == 403

    def test_cross_tenant_http(self, tmp_path, monkeypatch):
        from config import settings
        monkeypatch.setattr(settings, "ACCESS_POLICY_FILE", two_tenant_policy(tmp_path))
        add_user("ann", "investigator", tenant="acme")
        add_user("gus", "admin", tenant="globex")
        a = sign_in("ann").post("/actions", {"tool": "simulated_rollback_deployment", "args": ROLLBACK}).json()["action"]
        gus = sign_in("gus")
        assert gus.get(f"/actions/{a['id']}").status_code == 404
        assert gus.post(f"/actions/{a['id']}/approve", {"args_hash": a["args_hash"]}).status_code == 404
