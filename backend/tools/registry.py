"""Tool registry: an explicit allowlist of typed tools.

Every invocation goes through ``invoke`` (or, for consequential tools,
``execute_approved`` from the approval workflow), which enforces in backend code:

1. the tool is in the allowlist (unknown names are refused, never resolved);
2. the authenticated principal holds the tool's permission;
3. arguments validate against the tool's schema (extra fields forbidden,
   constrained types and ID patterns);
4. resource-level access (the target record's service) - checked by the tool
   against the principal, and checked AGAIN at execution time;
5. a timeout;
6. an audit event (redacted arguments) for every attempt, allowed or denied.

Neither the LLM nor NeMo can call tools: the investigation workflow has no tool
access at all. Consequential tools never run from ``invoke``; they need an
approved action (approvals/service.py) and only simulate their effect unless
``REMEDIATION_MODE`` says otherwise (no real executor exists in this project).
"""

import logging
from collections.abc import Callable
from typing import Any
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError

from security.audit import audit_event
from security.principals import Principal

logger = logging.getLogger(__name__)
_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="tool")


class ToolError(Exception):
    status = 400
    code = "tool_error"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class ToolNotAllowed(ToolError):
    status, code = 404, "tool_not_allowed"


class ToolForbidden(ToolError):
    status, code = 403, "forbidden"


class ToolInvalidArguments(ToolError):
    status, code = 422, "invalid_arguments"


class ToolTimeout(ToolError):
    status, code = 504, "timeout"


class ApprovalRequired(ToolError):
    status, code = 409, "approval_required"


class ResourceNotFound(ToolError):
    """Raised by tools for records that do not exist OR that the principal may not
    read - the two are indistinguishable to the caller."""
    status, code = 404, "not_found"


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args_model: type[BaseModel]
    permission: str
    handler: Callable[[Principal, Any], dict]
    timeout_s: float = 5.0
    consequential: bool = False
    # For consequential tools: plain-language impact, shown to the approver.
    impact: Callable[[Principal, Any], str] | None = None
    # For consequential tools: authorization of the TARGET (raises on denial).
    authorize_target: Callable[[Principal, Any], None] | None = None

    def schema(self) -> dict:
        return self.args_model.model_json_schema()


_REGISTRY: dict[str, ToolSpec] = {}


def register(spec: ToolSpec) -> None:
    _REGISTRY[spec.name] = spec


def get(name: str) -> ToolSpec:
    spec = _REGISTRY.get(name)
    if spec is None:
        raise ToolNotAllowed(f"tool {name!r} is not in the allowlist")
    return spec


def available_for(principal: Principal) -> list[ToolSpec]:
    return [s for s in _REGISTRY.values() if principal.has(s.permission)]


def validate_args(spec: ToolSpec, raw_args) -> BaseModel:
    if not isinstance(raw_args, dict):
        raise ToolInvalidArguments("arguments must be a JSON object")
    try:
        return spec.args_model.model_validate(raw_args)
    except ValidationError as exc:
        # field names and error types only - never echo the submitted values
        fields = sorted({".".join(str(x) for x in e["loc"]) or "arguments" for e in exc.errors()})
        raise ToolInvalidArguments(f"invalid arguments: {', '.join(fields)}") from None


def _run(spec: ToolSpec, principal: Principal, args: BaseModel) -> dict:
    future = _pool.submit(spec.handler, principal, args)
    try:
        return future.result(timeout=spec.timeout_s)
    except FutureTimeout:
        future.cancel()
        raise ToolTimeout(f"tool {spec.name} exceeded {spec.timeout_s:g}s") from None


def check_permission(spec: ToolSpec, principal: Principal) -> None:
    if not principal.has(spec.permission):
        raise ToolForbidden(f"{principal.role} may not use {spec.name}")


def invoke(principal: Principal, name: str, raw_args) -> dict:
    """Run a NON-consequential tool for an authenticated principal."""
    try:
        spec = get(name)
        check_permission(spec, principal)
        if spec.consequential:
            raise ApprovalRequired(f"{name} changes systems: propose it as an action and get approval")
        args = validate_args(spec, raw_args)
        result = _run(spec, principal, args)
    except ToolError as exc:
        audit_event("tool_denied" if exc.status in (403, 404, 409) else "tool_failed", principal, tool=name,
                    code=exc.code, reason=exc.message)
        raise
    audit_event("tool_invoked", principal, tool=name, args=args.model_dump())
    return result


def execute_approved(principal: Principal, name: str, args: BaseModel) -> dict:
    """Run a consequential tool. Only called by the approval workflow after its own
    checks; permission and target access are re-checked here (defence in depth)."""
    spec = get(name)
    check_permission(spec, principal)
    if spec.authorize_target is not None:
        spec.authorize_target(principal, args)
    return _run(spec, principal, args)


def _install() -> None:
    from tools import demo_tools

    for spec in demo_tools.SPECS:
        register(spec)


_install()
