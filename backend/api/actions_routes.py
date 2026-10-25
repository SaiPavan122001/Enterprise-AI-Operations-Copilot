"""Tool invocation, the approval workflow and the audit trail over HTTP.
Every route authenticates the caller and checks permissions in backend code."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from approvals import service as approvals
from security import principals as perm
from security.audit import read_events
from tools import registry
from utils.auth import Principal, require_permission

router = APIRouter(tags=["tools", "actions"])


class InvokeRequest(BaseModel):
    args: dict[str, Any] = Field(default_factory=dict)


class ProposeRequest(BaseModel):
    tool: str = Field(..., min_length=1, max_length=64)
    args: dict[str, Any] = Field(default_factory=dict)


class DecisionRequest(BaseModel):
    args_hash: str = Field(..., min_length=64, max_length=64)
    note: str | None = Field(None, max_length=300)


class ExecuteRequest(BaseModel):
    args: dict[str, Any] = Field(default_factory=dict)


def _err(status: int, message: str) -> HTTPException:
    return HTTPException(status, detail={"status": "error", "message": message})


@router.get("/tools")
def list_tools(principal: Principal = Depends(require_permission(perm.TOOLS_LIST))):
    return {"status": "success", "tools": [
        {"name": s.name, "description": s.description, "permission": s.permission,
         "consequential": s.consequential, "requires_approval": s.consequential, "schema": s.schema()}
        for s in registry.available_for(principal)]}


@router.post("/tools/{name}/invoke")
def invoke_tool(name: str, body: InvokeRequest,
                principal: Principal = Depends(require_permission(perm.TOOLS_LIST))):
    try:
        return {"status": "success", "tool": name, "result": registry.invoke(principal, name, body.args)}
    except registry.ToolError as exc:
        raise _err(exc.status, exc.message) from None


@router.post("/actions")
def propose_action(body: ProposeRequest,
                   principal: Principal = Depends(require_permission(perm.ACTIONS_PROPOSE))):
    try:
        return {"status": "success", "action": approvals.propose(principal, body.tool, body.args)}
    except approvals.ApprovalError as exc:
        raise _err(exc.status, exc.message) from None


@router.get("/actions")
def list_actions(principal: Principal = Depends(require_permission(perm.ACTIONS_READ))):
    return {"status": "success", "actions": approvals.list_actions(principal)}


@router.get("/actions/{action_id}")
def get_action(action_id: str, principal: Principal = Depends(require_permission(perm.ACTIONS_READ))):
    try:
        return {"status": "success", "action": approvals.get_action(principal, action_id)}
    except approvals.ApprovalError as exc:
        raise _err(exc.status, exc.message) from None


@router.post("/actions/{action_id}/approve")
def approve_action(action_id: str, body: DecisionRequest,
                   principal: Principal = Depends(require_permission(perm.ACTIONS_APPROVE))):
    try:
        return {"status": "success", "action": approvals.approve(principal, action_id, body.args_hash, body.note)}
    except approvals.ApprovalError as exc:
        raise _err(exc.status, exc.message) from None


@router.post("/actions/{action_id}/reject")
def reject_action(action_id: str, body: DecisionRequest,
                  principal: Principal = Depends(require_permission(perm.ACTIONS_APPROVE))):
    try:
        return {"status": "success", "action": approvals.reject(principal, action_id, body.args_hash, body.note)}
    except approvals.ApprovalError as exc:
        raise _err(exc.status, exc.message) from None


@router.post("/actions/{action_id}/execute")
def execute_action(action_id: str, body: ExecuteRequest,
                   principal: Principal = Depends(require_permission(perm.ACTIONS_EXECUTE))):
    try:
        return {"status": "success", "action": approvals.execute(principal, action_id, body.args)}
    except approvals.ApprovalError as exc:
        raise _err(exc.status, exc.message) from None


@router.get("/audit")
def audit_log(limit: int = Query(100, ge=1, le=500),
              principal: Principal = Depends(require_permission(perm.AUDIT_READ))):
    return {"status": "success", "events": read_events(principal.tenant, limit)}
