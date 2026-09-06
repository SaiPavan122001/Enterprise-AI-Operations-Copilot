from qdrant_client import QdrantClient

from config import settings

client = QdrantClient(path=settings.QDRANT_PATH)
