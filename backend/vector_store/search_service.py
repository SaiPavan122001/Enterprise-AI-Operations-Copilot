from sentence_transformers import SentenceTransformer
from vector_store.qdrant_client import client
from qdrant_client.models import (
    Filter,
    FieldCondition,
    MatchValue
)


model = SentenceTransformer("BAAI/bge-small-en-v1.5")


def search_incidents(
    query,
    severity=None,
    service=None,
    status=None,
    limit=5
):
    query_vector = model.encode(query).tolist()

    conditions = []

    if severity:
        conditions.append(
            FieldCondition(
                key="severity",
                match=MatchValue(value=severity)
            )
        )

    if service:
        conditions.append(
            FieldCondition(
                key="service",
                match=MatchValue(value=service)
            )
        )

    if status:
        conditions.append(
            FieldCondition(
                key="status",
                match=MatchValue(value=status)
            )
        )

    search_filter = (
        Filter(must=conditions)
        if conditions
        else None
    )

    results = client.query_points(
        collection_name="enterprise_incidents",
        query=query_vector,
        query_filter=search_filter,
        limit=limit
    )

    return results.points