
import os

from dotenv import load_dotenv
from google import genai

from app.rag.document_loader import load_documents
from app.rag.text_splitter import split_documents
from app.rag.embedding_service import embed_documents, embed_query
from app.rag.vector_store import (
    create_vector_store,
    store_chunks,
    search_similar_chunks
)


# Load environment variables
load_dotenv()

# Initialize Gemini
client = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY")
)


# 1. Load documents
documents = load_documents()

# 2. Split documents
chunks = split_documents(
    documents,
    chunk_size=200,
    chunk_overlap=30
)

# 3. Generate embeddings
embedded_chunks = embed_documents(
    chunks,
    client
)

# 4. Create vector store
collection = create_vector_store()

# 5. Store embeddings
store_chunks(
    collection,
    embedded_chunks
)

print("Stored chunks:", collection.count())


# 6. Generate query embedding
query = "Suggest places in Goa for nightlife"

query_embedding = embed_query(
    query,
    client
)

# 7. Retrieve relevant chunks
results = search_similar_chunks(
    collection,
    query_embedding,
    top_k=3
)


# 8. Display search results
print("\nUser query:", query)
print("\nRetrieved chunks:")

for i, document in enumerate(results["documents"][0]):

    metadata = results["metadatas"][0][i]
    distance = results["distances"][0][i]

    print(f"\nResult {i + 1}")
    print("Source:", metadata["source"])
    print("Chunk:", metadata["chunk_index"])
    print("Cosine distance:", distance)
    print("Content:", document)
