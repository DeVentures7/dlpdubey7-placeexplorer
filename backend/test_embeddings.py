
import os

from google import genai
from dotenv import load_dotenv

from app.rag.document_loader import load_documents
from app.rag.text_splitter import split_documents
from app.rag.embedding_service import embed_documents, embed_query


# Load environment variables
load_dotenv()

# Initialize Gemini client
client = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY")
)


# Step 1: Load documents
documents = load_documents()

print("Documents loaded:", len(documents))


# Step 2: Split documents
chunks = split_documents(
    documents,
    chunk_size=200,
    chunk_overlap=30
)

print("Chunks created:", len(chunks))


# Step 3: Generate document embeddings
embedded_chunks = embed_documents(
    chunks,
    client
)

print("Embeddings generated:", len(embedded_chunks))


# Step 4: Inspect the first embedding
first_embedding = embedded_chunks[0]["embedding"]

print("First chunk:", embedded_chunks[0]["content"])
print("Embedding dimensions:", len(first_embedding))
print("First 5 vector values:", first_embedding[:5])


# Step 5: Generate a query embedding
query = "Suggest places in Goa for nightlife"

query_embedding = embed_query(
    query,
    client
)

print("\nQuery:", query)
print("Query embedding dimensions:", len(query_embedding))
