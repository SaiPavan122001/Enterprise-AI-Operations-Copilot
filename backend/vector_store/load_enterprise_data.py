import json

from vector_store.qdrant_client import client
from qdrant_client.models import PointStruct

from sentence_transformers import SentenceTransformer


COLLECTION_NAME = "enterprise_incidents"

model = SentenceTransformer(
    "BAAI/bge-small-en-v1.5"
)


with open(
    "data/incidents.json",
    "r"
) as f:

    incidents = json.load(f)


points = []

for idx, incident in enumerate(incidents):

    text = f"""
    Service: {incident['service']}
    Title: {incident['title']}
    Root Cause: {incident['root_cause']}
    """

    embedding = model.encode(text).tolist()

    payload = {
        "incident_id": incident["id"],
        "service": incident["service"],
        "severity": incident["severity"],
        "status": incident["status"],
        "title": incident["title"],
        "root_cause": incident["root_cause"]
    }

    points.append(
        PointStruct(
            id=idx,
            vector=embedding,
            payload=payload
        )
    )


result = client.upsert(
    collection_name=COLLECTION_NAME,
    points=points
)

print(result)
print(f"\nLoaded {len(points)} incidents")