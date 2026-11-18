import os

from dotenv import load_dotenv
from google import genai

from app.rag.rag_pipeline import (
    index_knowledge_base,
    generate_rag_response
)

# Load environment variables
load_dotenv()

# Initialize Gemini client
client = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY")
)

# Step 1: Index knowledge base
print("\n--- INDEXING KNOWLEDGE BASE ---")

total_chunks = index_knowledge_base(client)

print("Indexed chunks:", total_chunks)

# Step 2: Ask a question
question = "Suggest places in Goa for nightlife."

print("\n--- USER QUESTION ---")
print(question)

# Step 3: Generate RAG response
print("\n--- RAG RESPONSE ---")

answer = generate_rag_response(
    question=question,
    client=client
)

print(answer)