import logging

from models.evidence import DeploymentEvidence
from utils.data_integrity import load_dependencies
from utils.data_store import get_deployments

logger = logging.getLogger(__name__)


def _field(obj, name):
    return getattr(obj, name, None) if not isinstance(obj, dict) else obj.get(name)


def deployment_link_status(incident, deployments: list[dict] | None = None,
                           dependencies: set[tuple[str, str]] | None = None,
                           include_change: bool = True) -> tuple[str, str | None]:
    """Classify an incident's deployment link.

    Returns (status, detail) where status is one of:
      verified                - deployment exists and is on the incident's service
      documented_dependency   - deployment on another service, dependency documented
      quarantined             - deployment on another service, no documented dependency
      missing                 - referenced deployment does not exist
      none                    - incident references no deployment
    ``include_change=False`` leaves the deployment's change text out of the detail.
    """
    deployments = get_deployments() if deployments is None else deployments
    dependencies = load_dependencies() if dependencies is None else dependencies
    deployment_id = _field(incident, "deployment_id")
    service = _field(incident, "service")
    if not deployment_id:
        return "none", None
    dep = next((d for d in deployments if d.get("deployment_id") == deployment_id), None)
    if dep is None:
        return "missing", f"{deployment_id} does not exist in deployments.json"
    if dep.get("service") == service:
        return "verified", None
    if (service, dep.get("service")) in dependencies:
        return "documented_dependency", f"{deployment_id} is on {dep.get('service')} (documented dependency)"
    # include_change=False for prompts and answers: a quarantined deployment is not evidence
    # for this incident, and its free text is untrusted (it bypasses the retrieval rail).
    change = f" ({dep.get('change')!r})" if include_change else ""
    return "quarantined", (f"{deployment_id} belongs to {dep.get('service')}{change}, "
                           f"not {service}; link quarantined for data review")


def investigate_deployments(
    incidents: list,  # list[IncidentEvidence]
) -> list[DeploymentEvidence]:
    """Correlate incidents with deployments as structured evidence.

    Only the explicit ``deployment_id`` relationship is used, and only when it
    is consistent: the deployment must be on the incident's service, or the
    cross-service dependency must be documented in service_dependencies.json.
    Quarantined or missing links produce no deployment evidence (the
    validation stage reports them). There is deliberately no "same service"
    fallback: a deployment that merely shares a service name is not evidence
    for this incident (it usually belongs to a different incident).
    """
    deployments = get_deployments()
    if not incidents:
        return []
    dependencies = load_dependencies()
    by_id = {d.get("deployment_id"): d for d in deployments}

    evidence: list[DeploymentEvidence] = []
    seen: set[str] = set()
    for incident in incidents:
        status, detail = deployment_link_status(incident, deployments, dependencies)
        if status not in ("verified", "documented_dependency"):
            if status in ("quarantined", "missing"):
                logger.info("Deployment link for %s not used: %s",
                            _field(incident, "incident_id"), detail)
            continue
        d = by_id[_field(incident, "deployment_id")]
        if d["deployment_id"] in seen:
            continue
        seen.add(d["deployment_id"])
        evidence.append(DeploymentEvidence(
            deployment_id=d.get("deployment_id", "unknown"),
            service=d.get("service"),
            change=d.get("change"),
            time=d.get("time"),
            incident_id=_field(incident, "incident_id"),
            link_status=status,
        ))
    logger.info("Deployment agent correlated %d deployments", len(evidence))
    return evidence
