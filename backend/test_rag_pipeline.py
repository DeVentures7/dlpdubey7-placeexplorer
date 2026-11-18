
import os

from dotenv import load_dotenv
from google import genai

from app.rag.rag_pipeline import index_knowledge_base
from app.rag.embedding_service import embed_query
from app.rag.vector_store import (
    create_vector_store,
    search_similar_chunks
)


load_dotenv()

client = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY")
)

# 1. Index documents
print("\n--- INDEXING ---")

total_chunks = index_knowledge_base(client)

print("Indexed chunks:", total_chunks)


# 2. Check ChromaDB collection
print("\n--- COLLECTION CHECK ---")

collection = create_vector_store()

print("Collection count:", collection.count())


# 3. Generate query embedding
print("\n--- QUERY EMBEDDING ---")

question = "Suggest places in Goa for nightlife."

query_embedding = embed_query(question, client)

print("Query:", question)
print("Embedding dimensions:", len(query_embedding))


# 4. Search ChromaDB directly
print("\n--- CHROMADB SEARCH ---")

results = search_similar_chunks(
    collection,
    query_embedding,
    top_k=3
)

print("Result keys:", results.keys())
print("Documents:", results["documents"])
print("Metadata:", results["metadatas"])
print("Distances:", results["distances"])
