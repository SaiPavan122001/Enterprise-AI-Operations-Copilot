import logging

from config import settings
from models.evidence import IncidentEvidence
from vector_store.search_service import search_incidents

logger = logging.getLogger(__name__)


def incident_agent(query: str, limit: int = 5) -> dict:
    """Retrieve relevant incidents from Qdrant as structured evidence.

    Results below the configured relevance threshold are dropped so the
    downstream workflow receives only genuinely relevant incidents. When no
    incident passes the threshold the result is empty, which the evidence
    validation stage reports as insufficient evidence - nothing is invented.
    """
    logger.info("Incident agent searching Qdrant (limit=%d)", limit)

    results = search_incidents(query=query, limit=limit)

    incidents: list[IncidentEvidence] = []
    scores: list[float] = []
    for point in results:
        score = float(point.score) if point.score is not None else None
        if score is not None:
            scores.append(score)
            if score < settings.MIN_RELEVANCE_SCORE:
                logger.debug(
                    "Dropping incident %s below relevance threshold (%.3f < %.3f)",
                    point.payload.get("incident_id"), score, settings.MIN_RELEVANCE_SCORE,
                )
                continue
        payload = point.payload or {}
        incidents.append(
            IncidentEvidence(
                incident_id=payload.get("incident_id", "unknown"),
                service=payload.get("service"),
                severity=payload.get("severity"),
                status=payload.get("status"),
                title=payload.get("title"),
                root_cause=payload.get("root_cause"),
                deployment_id=payload.get("deployment_id"),
                relevance_score=score,
            )
        )

    logger.info("Incident agent kept %d/%d incidents", len(incidents), len(results))
    return {"incidents": incidents, "scores": scores}
