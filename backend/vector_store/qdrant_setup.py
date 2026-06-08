from vector_store.qdrant_client import client
from qdrant_client.models import Distance, VectorParams



COLLECTION_NAME = "enterprise_incidents"

collections = [
    c.name
    for c in client.get_collections().collections
]

if COLLECTION_NAME not in collections:

    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=VectorParams(
            size=384,
            distance=Distance.COSINE
        )
    )

    print("Collection created")

else:
    print("Collection already exists")