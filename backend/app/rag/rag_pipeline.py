from google.genai import types

from app.rag.document_loader import load_documents
from app.rag.text_splitter import split_documents
from app.rag.embedding_service import (
    embed_documents,
    embed_query
)
from app.rag.vector_store import (
    create_vector_store,
    store_chunks,
    search_similar_chunks
)


def index_knowledge_base(client):
    """
    Load, split, embed and store knowledge-base documents.
    """

    # Step 1: Load documents
    documents = load_documents()

    if not documents:
        return 0

    # Step 2: Split documents into chunks
    chunks = split_documents(
        documents,
        chunk_size=200,
        chunk_overlap=30
    )

    # Step 3: Generate document embeddings
    embedded_chunks = embed_documents(
        chunks,
        client
    )

    # Step 4: Create vector store
    collection = create_vector_store()

    # Step 5: Store embeddings
    store_chunks(
        collection,
        embedded_chunks
    )

    return collection.count()


def retrieve_context(
    question: str,
    client,
    top_k: int = 3
):
    """
    Retrieve relevant knowledge for a user question.
    """

    # Step 1: Generate query embedding
    query_embedding = embed_query(
        question,
        client
    )

    # Step 2: Connect to vector store
    collection = create_vector_store()

    # Step 3: Search relevant chunks
    results = search_similar_chunks(
        collection,
        query_embedding,
        top_k
    )

    # Step 4: Combine retrieved documents
    retrieved_documents = results["documents"][0]

    context = "\n\n".join(retrieved_documents)

    return context


def generate_rag_response(
    question: str,
    client,
    model: str = "gemini-3.8-flash"
):
    """
    Retrieve relevant knowledge and generate an answer.
    """

    print("\n--- STEP 1: RETRIEVING CONTEXT ---")

    context = retrieve_context(question, client)

    print("Retrieved context:")
    print(context)

    if not context:
        return "I couldn't find relevant information in my knowledge base."

    prompt = f"""
You are PlaceExplorer, an AI travel assistant.

Answer the user's question using the knowledge context below.

Rules:
- Use the provided context as your source of knowledge.
- Do not invent facts that are not present in the context.
- If the context does not contain the answer, say so.
- Give a clear and helpful response.

Knowledge Context:
{context}

User Question:
{question}
"""

    print("\n--- STEP 2: CALLING GEMINI ---")
    print("Model:", model)

    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.3
        )
    )

    print("\n--- STEP 3: GEMINI RESPONSE RECEIVED ---")

    if not response.text:
        print("Gemini returned an empty response.")
        return "No response generated."

    return response.text
