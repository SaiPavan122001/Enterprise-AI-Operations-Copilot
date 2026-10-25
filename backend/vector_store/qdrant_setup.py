"""Qdrant collection setup and validation."""

import logging

from config import settings
from vector_store.qdrant_client import client
from qdrant_client.models import Distance, PayloadSchemaType, VectorParams

logger = logging.getLogger(__name__)

COLLECTION_NAME = settings.QDRANT_COLLECTION
VECTOR_SIZE = 384  # BAAI/bge-small-en-v1.5 embedding dimension


def collection_exists(collection_name: str = COLLECTION_NAME) -> bool:
    return collection_name in [
        c.name for c in client.get_collections().collections
    ]


def ensure_collection(collection_name: str = COLLECTION_NAME) -> bool:
    """Create the incidents collection (with useful payload indexes) if it
    does not exist. Returns True if a new collection was created."""
    if collection_exists(collection_name):
        logger.info("Qdrant collection '%s' already exists", collection_name)
        return False

    client.create_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(
            size=VECTOR_SIZE,
            distance=Distance.COSINE,
        ),
    )

    # Metadata indexes keep filtered searches fast as the dataset grows.
    for field in ("service", "severity", "status"):
        try:
            client.create_payload_index(
                collection_name=collection_name,
                field_name=field,
                field_schema=PayloadSchemaType.KEYWORD,
            )
            logger.info("Payload index created on '%s'", field)
        except Exception:
            logger.exception("Failed to create payload index on '%s'", field)

    logger.info("Qdrant collection '%s' created", collection_name)
    return True


if __name__ == "__main__":
    ensure_collection()


def sync_points(qclient, collection_name: str, points: list) -> dict:
    """Idempotent ingestion: upsert ``points`` and delete any point whose ID is
    not in this batch (e.g. an incident removed from the source data), then
    verify the stored IDs match exactly. Returns counts; raises on mismatch."""
    expected = {str(p.id) for p in points}
    if points:
        qclient.upsert(collection_name=collection_name, points=points)
    stored: dict[str, int | str] = {}   # str(id) -> original id (int or UUID string)
    offset = None
    while True:
        batch, offset = qclient.scroll(collection_name=collection_name, limit=256, offset=offset,
                                       with_payload=False, with_vectors=False)
        stored.update({str(p.id): p.id for p in batch})
        if offset is None:
            break
    stale = [stored[k] for k in sorted(set(stored) - expected)]
    if stale:
        from qdrant_client.models import PointIdsList

        qclient.delete(collection_name=collection_name, points_selector=PointIdsList(points=stale))
        logger.warning("Removed %d stale point(s) no longer present in the source data", len(stale))
    final = qclient.count(collection_name=collection_name, exact=True).count
    if final != len(expected):
        raise RuntimeError(f"Verification failed: expected exactly {len(expected)} points, found {final}")
    return {"upserted": len(points), "stale_removed": len(stale), "stored": final}
