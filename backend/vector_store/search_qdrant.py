from vector_store.qdrant_client import client
from sentence_transformers import SentenceTransformer



model = SentenceTransformer(
    "BAAI/bge-small-en-v1.5"
)

query = "payroll generation failure"

query_vector = model.encode(query).tolist()

results = client.query_points(
    collection_name="enterprise_incidents",
    query=query_vector,
    limit=5
)

print(results)