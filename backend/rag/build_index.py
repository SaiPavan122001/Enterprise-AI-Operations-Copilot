from load_enterprise_data import (
    load_incidents,
    load_deployments,
    load_logs
)

from llama_index.core import VectorStoreIndex
from llama_index.core import SimpleDirectoryReader
from llama_index.core import Settings

from llama_index.embeddings.huggingface import HuggingFaceEmbedding

Settings.embed_model = HuggingFaceEmbedding(
    model_name="BAAI/bge-small-en-v1.5"
)

from load_enterprise_data import (
    load_incidents,
    load_deployments,
    load_logs
)

runbook_docs = SimpleDirectoryReader(
    "data/runbooks"
).load_data()

incident_docs = load_incidents()

deployment_docs = load_deployments()

log_docs = load_logs()

documents = (
    runbook_docs
    + incident_docs
    + deployment_docs
    + log_docs
)

index = VectorStoreIndex.from_documents(documents)

index.storage_context.persist(
    persist_dir="storage"
)

print("Index created successfully")