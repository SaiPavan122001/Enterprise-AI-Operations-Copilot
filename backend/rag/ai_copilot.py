from dotenv import load_dotenv
import os

load_dotenv()

from llama_index.core import (
    StorageContext,
    load_index_from_storage,
    Settings
)

from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.llms.google_genai import GoogleGenAI

# Embedding Model
Settings.embed_model = HuggingFaceEmbedding(
    model_name="BAAI/bge-small-en-v1.5"
)

# Gemini LLM
Settings.llm = GoogleGenAI(
    model="gemini-2.5-flash",
    api_key=os.getenv("GEMINI_API_KEY")
)

storage_context = StorageContext.from_defaults(
    persist_dir="storage"
)

index = load_index_from_storage(storage_context)

retriever = index.as_retriever(similarity_top_k=5)

question = input("Ask a question: ")

nodes = retriever.retrieve(question)

context = "\n\n".join(
    [node.text for node in nodes]
)

prompt = f"""
You are an Enterprise AI Operations Copilot.

Analyze the provided enterprise data and produce:

1. Root Cause
2. Supporting Evidence
3. Recommended Resolution
4. Risk Level

Question:
{question}

Enterprise Context:
{context}
"""

response = Settings.llm.complete(prompt)

print("\n")
print("=" * 60)
print("AI RCA REPORT")
print("=" * 60)
print("\n")

print(response.text)