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
