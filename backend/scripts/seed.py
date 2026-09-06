"""Clean, single seed command for the Qdrant vector database.

    python -m scripts.seed

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

from config import DATA_DIR, settings
from vector_store.qdrant_client import client
from vector_store.qdrant_setup import COLLECTION_NAME, ensure_collection

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger("seed")

# Stable namespace so IDs are deterministic across runs and machines.
POINT_ID_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "enterprise-ai-operations-copilot")

model = SentenceTransformer("BAAI/bge-small-en-v1.5")

REQUIRED_FIELDS = ("id", "service", "severity", "status", "title", "root_cause")


def validate_data() -> list[dict]:
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
    logger.info("Validated %d incidents in %s", len(incidents), path.name)
    return incidents


def seed() -> int:
    incidents = validate_data()
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

    result = client.upsert(collection_name=COLLECTION_NAME, points=points)
    logger.info("Qdrant upsert result: %s", result.status)

    # Verify the stored record count.
    stored = client.count(collection_name=COLLECTION_NAME, exact=True).count
    if stored < len(incidents):
        raise RuntimeError(
            f"Verification failed: expected >= {len(incidents)} points, found {stored}"
        )
    logger.info(
        "Seed complete: %d incidents verified in collection '%s'%s",
        stored, COLLECTION_NAME, " (collection newly created)" if created else "",
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(seed())
    except Exception as exc:
        logger.error("Seed failed: %s", exc)
        sys.exit(1)
