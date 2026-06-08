from llama_index.core import StorageContext
from llama_index.core import load_index_from_storage
from llama_index.core import Settings

from llama_index.embeddings.huggingface import HuggingFaceEmbedding

Settings.embed_model = HuggingFaceEmbedding(
    model_name="BAAI/bge-small-en-v1.5"
)

storage_context = StorageContext.from_defaults(
    persist_dir="storage"
)

index = load_index_from_storage(storage_context)

retriever = index.as_retriever()

nodes = retriever.retrieve(
    "Why is payroll generation failing?"
)

for node in nodes:
    print(node.text)
