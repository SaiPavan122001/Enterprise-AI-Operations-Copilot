import logging

from models.evidence import DeploymentEvidence
from utils.data_store import get_deployments

logger = logging.getLogger(__name__)


def investigate_deployments(
    incidents: list,  # list[IncidentEvidence]
) -> list[DeploymentEvidence]:
    """Correlate incidents with deployments as structured evidence.

    Primary strategy: the explicit ``deployment_id`` relationship that
    already exists between incidents and deployments, which guarantees the
    exact deployment involved in each incident.

    Fallback: only when NO incident could be resolved via deployment_id,
    correlate by service name (best-effort; may include deployments related
    to other incidents on the same service).
    """
    deployments = get_deployments()
    if not incidents:
        return []

    by_id = {d.get("deployment_id"): d for d in deployments}

    matched: list[dict] = []
    seen_ids: set[str] = set()
    needs_service_fallback = False

    for incident in incidents:
        deployment_id = getattr(incident, "deployment_id", None) or (
            incident.get("deployment_id") if isinstance(incident, dict) else None
        )
        if deployment_id and deployment_id in by_id:
            if deployment_id not in seen_ids:
                matched.append(by_id[deployment_id])
                seen_ids.add(deployment_id)
        else:
            needs_service_fallback = True

    if needs_service_fallback and not matched:
        services = {
            getattr(i, "service", None) or (i.get("service") if isinstance(i, dict) else None)
            for i in incidents
        }
        services.discard(None)
        matched = [
            d for d in deployments if d.get("service") in services
        ][:10]
        logger.info(
            "Deployment agent fell back to service matching: %s", services
        )

    evidence = [
        # Only include fields that actually exist in the deployment data.
        DeploymentEvidence(
            deployment_id=d.get("deployment_id", "unknown"),
            service=d.get("service"),
            change=d.get("change"),
            time=d.get("time"),
        )
        for d in matched
    ]
    logger.info("Deployment agent correlated %d deployments", len(evidence))
    return evidence
