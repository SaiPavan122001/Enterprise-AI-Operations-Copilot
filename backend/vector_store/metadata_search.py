from sentence_transformers import SentenceTransformer
from vector_store.qdrant_client import client
from qdrant_client.models import (
    Filter,
    FieldCondition,
    MatchValue
)


model = SentenceTransformer("BAAI/bge-small-en-v1.5")


query = "payroll failure"

query_vector = model.encode(query).tolist()


search_filter = Filter(
    must=[
        FieldCondition(
            key="severity",
            match=MatchValue(value="Critical")
        )
    ]
)


results = client.query_points(
    collection_name="enterprise_incidents",
    query=query_vector,
    query_filter=search_filter,
    limit=5
)

for point in results.points:
    print("\nID:", point.id)
    print("Score:", point.score)
    print("Payload:", point.payload)