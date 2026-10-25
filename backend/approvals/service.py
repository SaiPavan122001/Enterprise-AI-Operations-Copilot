"""Backend-enforced approval lifecycle for consequential actions.

    pending --approve--> approved --execute--> executed
       |                    |
       +--reject--> rejected +--(approval window passes)--> expired
       +--(pending window passes)--> expired

Rules (all enforced here, in code):
* propose: ``actions:propose``; only allowlisted *consequential* tools; arguments
  validated by the tool schema; the proposer must be able to access the target.
  The action is bound to ``args_hash`` = sha256(tool + canonical JSON arguments)
  and shows the exact arguments, requester and impact.
* approve / reject: ``actions:approve``; same tenant; NOT the requester
  (separation of duties); the approver must send the ``args_hash`` they were
  shown, so the approval binds to that exact action; pending and unexpired only.
* execute: ``actions:execute``; same tenant; the requester or an approver;
  status must be ``approved`` and within ``APPROVAL_VALID_MINUTES``; the
  submitted arguments must hash to the approved ``args_hash`` (tampering is
  refused); permission and target access are re-checked NOW (fresh
  authorization); the action is claimed atomically, so it runs at most once
  (replay is refused).
Every transition and every refusal is written to the audit trail.

Storage: JSON file (``APPROVALS_FILE``) under a process lock - single-process,
like the rest of this deployment.
"""

import hashlib
import json
import secrets
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config import settings
from security import principals as perm
from security.audit import audit_event
from security.principals import Principal
from tools import registry

_lock = threading.Lock()
STATUSES = ("pending", "approved", "rejected", "expired", "executed")


class ApprovalError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def args_hash(tool: str, args: dict) -> str:
    canonical = json.dumps({"tool": tool, "args": args}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _path() -> Path:
    return Path(settings.APPROVALS_FILE)


def _load() -> dict:
    p = _path()
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _save(data: dict) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(p)


def _expire(action: dict, now: datetime) -> bool:
    """Apply time-based expiry; returns True if the status changed."""
    if action["status"] == "pending" and now > datetime.fromisoformat(action["expires_at"]):
        action["status"] = "expired"
    elif action["status"] == "approved" and now > datetime.fromisoformat(action["approval_expires_at"]):
        action["status"] = "expired"
    else:
        return False
    action["history"].append({"at": _iso(now), "event": "expired"})
    return True


def _public(action: dict) -> dict:
    return {k: v for k, v in action.items() if k != "_claim"}


def _get(data: dict, action_id: str, principal: Principal) -> dict:
    action = data.get(action_id)
    # unknown and other-tenant actions are indistinguishable
    if action is None or action["tenant"] != principal.tenant:
        raise ApprovalError(404, "action not found")
    return action


def _require(principal: Principal, permission: str, what: str) -> None:
    if not principal.has(permission):
        audit_event("approval_denied", principal, reason=f"missing {permission} for {what}")
        raise ApprovalError(403, f"{principal.role} may not {what}")


def propose(principal: Principal, tool: str, raw_args) -> dict:
    _require(principal, perm.ACTIONS_PROPOSE, "propose actions")
    try:
        spec = registry.get(tool)
        if not spec.consequential:
            raise ApprovalError(400, f"{tool} does not need approval; invoke it directly")
        args = registry.validate_args(spec, raw_args)
        if spec.authorize_target is not None:
            spec.authorize_target(principal, args)
    except registry.ToolError as exc:
        audit_event("action_propose_refused", principal, tool=tool, code=exc.code, reason=exc.message)
        raise ApprovalError(exc.status, exc.message) from None
    canonical = args.model_dump()
    now = _now()
    action = {
        "id": secrets.token_hex(12), "tool": tool, "args": canonical, "args_hash": args_hash(tool, canonical),
        "impact": spec.impact(principal, args) if spec.impact else "", "simulated": True,
        "requester": principal.name, "requester_role": principal.role, "tenant": principal.tenant,
        "status": "pending", "created_at": _iso(now),
        "expires_at": _iso(now + timedelta(minutes=settings.APPROVAL_PENDING_TTL_MINUTES)),
        "approved_by": None, "approved_at": None, "approval_expires_at": None,
        "rejected_by": None, "decision_note": None, "executed_by": None, "executed_at": None, "result": None,
        "history": [{"at": _iso(now), "event": "proposed", "by": principal.name}],
    }
    with _lock:
        data = _load()
        data[action["id"]] = action
        _save(data)
    audit_event("action_proposed", principal, action_id=action["id"], tool=tool, args=canonical,
                args_hash=action["args_hash"])
    return _public(action)


def list_actions(principal: Principal) -> list[dict]:
    _require(principal, perm.ACTIONS_READ, "read actions")
    with _lock:
        data = _load()
        now = _now()
        changed = [a for a in data.values() if _expire(a, now)]
        if changed:
            _save(data)
    visible = [a for a in data.values() if a["tenant"] == principal.tenant and
               (a["requester"] == principal.name or principal.has(perm.ACTIONS_APPROVE))]
    return [_public(a) for a in sorted(visible, key=lambda a: a["created_at"], reverse=True)]


def get_action(principal: Principal, action_id: str) -> dict:
    _require(principal, perm.ACTIONS_READ, "read actions")
    with _lock:
        data = _load()
        action = _get(data, action_id, principal)
        if action["requester"] != principal.name and not principal.has(perm.ACTIONS_APPROVE):
            raise ApprovalError(404, "action not found")
        if _expire(action, _now()):
            _save(data)
        return _public(action)


def _decide(principal: Principal, action_id: str, approve: bool, shown_hash: str, note: str | None) -> dict:
    verb = "approve" if approve else "reject"
    _require(principal, perm.ACTIONS_APPROVE, f"{verb} actions")
    with _lock:
        data = _load()
        action = _get(data, action_id, principal)
        now = _now()
        if _expire(action, now):
            _save(data)
        refusal = None
        if action["requester"] == principal.name:
            refusal = (403, "you cannot approve or reject your own request")
        elif action["status"] != "pending":
            refusal = (409, f"action is {action['status']}, not pending")
        elif shown_hash != action["args_hash"]:
            refusal = (409, "the action changed since it was shown to you; review it again")
        if refusal is None and approve:
            spec = registry.get(action["tool"])
            try:
                args = registry.validate_args(spec, action["args"])
                if spec.authorize_target is not None:
                    spec.authorize_target(principal, args)
            except registry.ToolError as exc:
                refusal = (403 if exc.status in (403, 404) else exc.status, "you may not approve this target")
        if refusal is not None:
            audit_event(f"action_{verb}_refused", principal, action_id=action_id, reason=refusal[1])
            raise ApprovalError(*refusal)
        if approve:
            action.update(status="approved", approved_by=principal.name, approved_at=_iso(now), decision_note=note,
                          approval_expires_at=_iso(now + timedelta(minutes=settings.APPROVAL_VALID_MINUTES)))
        else:
            action.update(status="rejected", rejected_by=principal.name, decision_note=note)
        action["history"].append({"at": _iso(now), "event": "approved" if approve else "rejected",
                                  "by": principal.name})
        _save(data)
    audit_event("action_approved" if approve else "action_rejected", principal, action_id=action_id,
                tool=action["tool"], args_hash=action["args_hash"])
    return _public(action)


def approve(principal: Principal, action_id: str, shown_hash: str, note: str | None = None) -> dict:
    return _decide(principal, action_id, True, shown_hash, note)


def reject(principal: Principal, action_id: str, shown_hash: str, note: str | None = None) -> dict:
    return _decide(principal, action_id, False, shown_hash, note)


def execute(principal: Principal, action_id: str, raw_args) -> dict:
    _require(principal, perm.ACTIONS_EXECUTE, "execute actions")
    with _lock:
        data = _load()
        action = _get(data, action_id, principal)
        now = _now()
        if _expire(action, now):
            _save(data)
        refusal = None
        if action["requester"] != principal.name and not principal.has(perm.ACTIONS_APPROVE):
            refusal = (403, "only the requester or an approver may execute this action")
        elif action["status"] == "executed":
            refusal = (409, "action was already executed (replay refused)")
        elif action["status"] != "approved":
            refusal = (409, f"action is {action['status']}; it needs a valid approval")
        else:
            spec = registry.get(action["tool"])
            try:
                args = registry.validate_args(spec, raw_args)
            except registry.ToolError:
                args = None
            if args is None or args_hash(action["tool"], args.model_dump()) != action["args_hash"]:
                refusal = (409, "arguments differ from the approved action (tampering refused)")
        if refusal is not None:
            audit_event("action_execute_refused", principal, action_id=action_id, reason=refusal[1])
            raise ApprovalError(*refusal)
        assert args is not None
        # Atomic single-use claim: no second execution can pass the status check.
        action["status"] = "executed"
        action["executed_by"] = principal.name
        action["executed_at"] = _iso(now)
        action["history"].append({"at": _iso(now), "event": "executing", "by": principal.name})
        _save(data)
    try:
        # Fresh authorization of permission AND target at execution time.
        result = registry.execute_approved(principal, action["tool"], args)
    except registry.ToolError as exc:
        with _lock:
            data = _load()
            data[action_id]["status"] = "approved"          # release the claim; nothing ran
            data[action_id]["executed_by"] = data[action_id]["executed_at"] = None
            data[action_id]["history"].append({"at": _iso(_now()), "event": "execution_refused",
                                               "by": principal.name, "reason": exc.message})
            _save(data)
        audit_event("action_execute_refused", principal, action_id=action_id, reason=exc.message)
        raise ApprovalError(403 if exc.status in (403, 404) else exc.status, exc.message) from None
    with _lock:
        data = _load()
        data[action_id]["result"] = result
        data[action_id]["history"].append({"at": _iso(_now()), "event": "executed", "by": principal.name})
        _save(data)
        action = data[action_id]
    audit_event("action_executed", principal, action_id=action_id, tool=action["tool"],
                args_hash=action["args_hash"], simulated=result.get("simulated"))
    return _public(action)
