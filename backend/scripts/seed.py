"""Clean, single seed command for the Qdrant vector database.

    python -m scripts.seed            # accepts reviewed quarantined links (never joined)
    python -m scripts.seed --strict   # refuses ingestion unless every link verifies,
                                      # logs are service-specific and provenance is confirmed
                                      # (also: SEED_STRICT=1)

Steps:
1. Validate the enterprise data files
2. Create/verify the Qdrant collection (with payload indexes)
3. Generate embeddings for every incident
4. Insert/update points with deterministic IDs (safe to re-run)
5. Verify the stored record count
6. Report success/failure with a non-zero exit code on failure
"""

import json
import logging
import sys
import uuid

from qdrant_client.models import PointStruct
from sentence_transformers import SentenceTransformer

from config import DATA_DIR
from vector_store.qdrant_client import client
from vector_store.qdrant_setup import COLLECTION_NAME, ensure_collection, sync_points

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger("seed")

# Stable namespace so IDs are deterministic across runs and machines.
POINT_ID_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "enterprise-ai-operations-copilot")

model = SentenceTransformer("BAAI/bge-small-en-v1.5")

REQUIRED_FIELDS = ("id", "service", "severity", "status", "title", "root_cause")


def validate_data(strict: bool = False) -> list[dict]:
    path = DATA_DIR / "incidents.json"
    with open(path, "r", encoding="utf-8") as f:
        incidents = json.load(f)

    if not isinstance(incidents, list) or not incidents:
        raise ValueError(f"{path} contains no incidents")

    for incident in incidents:
        missing = [field for field in REQUIRED_FIELDS if not incident.get(field)]
        if missing:
            raise ValueError(
                f"Incident {incident.get('id', '?')} is missing fields: {missing}"
            )
    # Relationship integrity (incident -> deployment -> service -> logs).
    # Errors (incl. quarantined links nobody has reviewed) stop ingestion;
    # reviewed quarantines are ingested but never joined (see utils/data_integrity.py).
    from utils.data_integrity import (
        check_integrity, load_dependencies, load_review_decisions, strict_problems, write_report,
    )
    from utils.data_store import get_deployments, get_logs

    report = check_integrity(incidents, get_deployments(), get_logs(),
                             load_dependencies(), load_review_decisions())
    for issue in report.by_severity("warning"):
        logger.warning("Integrity warning [%s] %s: %s", issue.code, issue.record_id, issue.message)
    for issue in report.by_severity("quarantine"):
        logger.warning("Quarantined link [%s] %s: %s", issue.code, issue.record_id, issue.message)
    write_report(report)
    if not report.ok:
        details = "; ".join(f"{i.record_id}: {i.message}" for i in report.by_severity("error"))
        raise ValueError(f"Data integrity check failed: {details}")
    if strict:
        problems = strict_problems(report)
        if problems:
            raise ValueError("Strict ingestion refused (%d problem(s)): %s" % (len(problems), " | ".join(problems)))
    logger.info("Validated %d incidents in %s (%d verified deployment links, %d quarantined for review)",
                len(incidents), path.name, len(report.verified_links), len(report.quarantined_links))
    return incidents


def seed(strict: bool = False) -> int:
    incidents = validate_data(strict)
    created = ensure_collection()

    points = []
    for incident in incidents:
        text = (
            f"Service: {incident['service']}\n"
            f"Title: {incident['title']}\n"
            f"Root Cause: {incident['root_cause']}"
        )
        embedding = model.encode(text).tolist()
        payload = {
            "incident_id": incident["id"],
            "deployment_id": incident.get("deployment_id"),
            "service": incident["service"],
            "severity": incident["severity"],
            "status": incident["status"],
            "title": incident["title"],
            "root_cause": incident["root_cause"],
        }
        points.append(
            PointStruct(
                id=str(uuid.uuid5(POINT_ID_NAMESPACE, incident["id"])),
                vector=embedding,
                payload=payload,
            )
        )

    # Upsert, remove stale points, verify the exact ID set (idempotent).
    counts = sync_points(client, COLLECTION_NAME, points)
    logger.info(
        "Seed complete: %d incidents verified in collection '%s' (%d stale removed)%s",
        counts["stored"], COLLECTION_NAME, counts["stale_removed"],
        " (collection newly created)" if created else "",
    )
    return 0


if __name__ == "__main__":
    import os

    try:
        sys.exit(seed(strict="--strict" in sys.argv[1:] or os.getenv("SEED_STRICT") == "1"))
    except Exception as exc:
        logger.error("Seed failed: %s", exc)
        sys.exit(1)
