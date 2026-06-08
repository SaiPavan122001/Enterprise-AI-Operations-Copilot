from vector_store.qdrant_client import client

info = client.get_collection(
    "enterprise_incidents"
)

print(info)