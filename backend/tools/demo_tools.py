"""Demonstration tools (read-only lookups + SIMULATED remediation).

Nothing here changes a real system. ``REMEDIATION_MODE`` must be "simulated";
any other value makes consequential tools refuse, because no real executor is
implemented or authorized in this project.
"""

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from config import settings
from security import access
from security import principals as perm
from security.principals import Principal
from tools.registry import ResourceNotFound, ToolForbidden, ToolSpec

INCIDENT_ID = r"^INC-\d{3}$"
DEPLOYMENT_ID = r"^DEP-\d{3}$"
SERVICE = r"^[a-z]+-service$"


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class IncidentLookupArgs(_Args):
    incident_id: str = Field(..., pattern=INCIDENT_ID)


class DeploymentInspectArgs(_Args):
    deployment_id: str = Field(..., pattern=DEPLOYMENT_ID)


class RollbackArgs(_Args):
    deployment_id: str = Field(..., pattern=DEPLOYMENT_ID)
    reason: str = Field(..., min_length=10, max_length=300)


class RestartArgs(_Args):
    service: str = Field(..., pattern=SERVICE)
    mode: Literal["rolling", "graceful"] = "rolling"
    reason: str = Field(..., min_length=10, max_length=300)


def _incident(incident_id: str) -> dict | None:
    from utils.data_store import get_incidents

    return next((i for i in get_incidents() if i.get("id") == incident_id), None)


def _deployment(deployment_id: str) -> dict | None:
    from utils.data_store import get_deployments

    return next((d for d in get_deployments() if d.get("deployment_id") == deployment_id), None)


def _readable(principal: Principal, record: dict | None, what: str) -> dict:
    if record is None or not principal.can_access_service(record.get("service")):
        raise ResourceNotFound(f"{what} not found")      # same answer for missing and forbidden
    return record


# --------------------------------------------------------------------------- read-only

def incident_lookup(principal: Principal, args: IncidentLookupArgs) -> dict:
    rec = _readable(principal, _incident(args.incident_id), args.incident_id)
    return {k: rec.get(k) for k in ("id", "service", "severity", "status", "title", "root_cause", "deployment_id")}


def deployment_inspect(principal: Principal, args: DeploymentInspectArgs) -> dict:
    from utils.data_store import get_incidents

    dep = _readable(principal, _deployment(args.deployment_id), args.deployment_id)
    linked = [i["id"] for i in get_incidents()
              if i.get("deployment_id") == dep["deployment_id"] and principal.can_access_service(i.get("service"))]
    return {**{k: dep.get(k) for k in ("deployment_id", "service", "time", "change")},
            "linked_incidents_you_can_read": linked}


# --------------------------------------------------------------------------- consequential (simulated)

def _require_simulated() -> None:
    if settings.REMEDIATION_MODE != "simulated":
        raise ToolForbidden("real remediation is not implemented or authorized; set REMEDIATION_MODE=simulated")


def _rollback_target(principal: Principal, args: RollbackArgs) -> None:
    _readable(principal, _deployment(args.deployment_id), args.deployment_id)


def _restart_target(principal: Principal, args: RestartArgs) -> None:
    if not principal.can_access_service(args.service) or args.service not in access.tenant_services(principal.tenant):
        raise ResourceNotFound(f"{args.service} not found")


def simulated_rollback(principal: Principal, args: RollbackArgs) -> dict:
    _require_simulated()
    _rollback_target(principal, args)
    dep = _deployment(args.deployment_id) or {}
    return {"simulated": True, "action": "rollback_deployment", "deployment_id": args.deployment_id,
            "service": dep.get("service"), "outcome": "SIMULATED - no system was changed",
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def simulated_restart(principal: Principal, args: RestartArgs) -> dict:
    _require_simulated()
    _restart_target(principal, args)
    return {"simulated": True, "action": "restart_service", "service": args.service, "mode": args.mode,
            "outcome": "SIMULATED - no system was changed",
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def _rollback_impact(principal: Principal, args: RollbackArgs) -> str:
    dep = _deployment(args.deployment_id) or {}
    return (f"SIMULATED rollback of {args.deployment_id} on {dep.get('service')} (change: {dep.get('change')!r}). "
            f"In a real system this would revert that service's code/config to its previous release, may cause a "
            f"short service interruption, and could reintroduce the problem the release fixed. No real system is "
            f"changed in this project.")


def _restart_impact(principal: Principal, args: RestartArgs) -> str:
    return (f"SIMULATED {args.mode} restart of {args.service}. In a real system in-flight requests could fail "
            f"and caches would be cold. No real system is changed in this project.")


SPECS = [
    ToolSpec("incident_lookup", "Read one incident record you are authorized to see.", IncidentLookupArgs,
             perm.TOOLS_READ, incident_lookup, timeout_s=3),
    ToolSpec("deployment_inspect", "Read one deployment and the incidents linked to it that you may see.",
             DeploymentInspectArgs, perm.TOOLS_READ, deployment_inspect, timeout_s=3),
    ToolSpec("simulated_rollback_deployment", "SIMULATED rollback of a deployment (requires approval).",
             RollbackArgs, perm.ACTIONS_EXECUTE, simulated_rollback, timeout_s=5, consequential=True,
             impact=_rollback_impact, authorize_target=_rollback_target),
    ToolSpec("simulated_restart_service", "SIMULATED restart of a service (requires approval).",
             RestartArgs, perm.ACTIONS_EXECUTE, simulated_restart, timeout_s=5, consequential=True,
             impact=_restart_impact, authorize_target=_restart_target),
]
