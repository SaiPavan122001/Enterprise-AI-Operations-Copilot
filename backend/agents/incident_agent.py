import logging

from config import settings
from models.evidence import IncidentEvidence
from vector_store.search_service import search_incidents

logger = logging.getLogger(__name__)


def select_relevant(
    scored: list[tuple[str, float | None]],
    min_score: float | None = None,
    margin: float | None = None,
) -> list[str]:
    """Return the IDs (in rank order) that are relevant enough for the LLM.

    ``scored`` is the ranked retriever output as (id, cosine score). An item is
    kept only if its score is >= ``min_score`` (absolute floor) AND within
    ``margin`` of the best score (drops the unrelated tail that compressed
    bge similarities otherwise let through). Items without a score are kept
    only when no item has a score. Shared with the eval harness so the
    measured "LLM context" is exactly what production passes on.
    """
    min_score = settings.MIN_RELEVANCE_SCORE if min_score is None else min_score
    margin = settings.RELEVANCE_MARGIN if margin is None else margin
    scores = [s for _, s in scored if s is not None]
    if not scores:
        return [i for i, _ in scored]
    best = max(scores)
    return [i for i, s in scored if s is not None and s >= min_score and s >= best - margin]


def incident_agent(query: str, limit: int = 5, services=None) -> dict:
    """Retrieve relevant incidents from Qdrant as structured evidence.

    Results that fail the relevance filter (``select_relevant``) are dropped
    so the downstream workflow receives only genuinely relevant incidents.
    When nothing passes, the result is empty, which the evidence validation
    stage reports as insufficient evidence - nothing is invented.
    """
    logger.info("Incident agent searching Qdrant (limit=%d)", limit)

    results = search_incidents(query=query, limit=limit, services=services)

    scored = [
        ((point.payload or {}).get("incident_id", "unknown"),
         float(point.score) if point.score is not None else None)
        for point in results
    ]
    keep = set(select_relevant(scored))

    incidents: list[IncidentEvidence] = []
    scores: list[float] = []
    for point, (incident_id, score) in zip(results, scored):
        if score is not None:
            scores.append(score)
        if incident_id not in keep:
            logger.debug("Dropping incident %s (score=%s) - failed relevance filter",
                         incident_id, score)
            continue
        payload = point.payload or {}
        incidents.append(
            IncidentEvidence(
                incident_id=incident_id,
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
