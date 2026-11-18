
from google.genai import types


def embed_documents(
    chunks: list[dict],
    client,
    model: str = "gemini-embedding-001"
) -> list[dict]:

    if not chunks:
        return []

    # Extract text from all chunks
    texts = [chunk["content"] for chunk in chunks]

    # Generate embeddings using Gemini
    response = client.models.embed_content(
        model=model,
        contents=texts,
        config=types.EmbedContentConfig(
            task_type="RETRIEVAL_DOCUMENT"
        )
    )

    if len(response.embeddings) != len(chunks):
        raise ValueError("Embedding count does not match chunk count")

    embedded_chunks = []

    # Attach each embedding to its original chunk
    for chunk, embedding in zip(chunks, response.embeddings):

        embedded_chunks.append({
            **chunk,
            "embedding": embedding.values
        })

    return embedded_chunks


def embed_query(
    query: str,
    client,
    model: str = "gemini-embedding-001"
) -> list[float]:

    # Generate embedding for the user's question
    response = client.models.embed_content(
        model=model,
        contents=query,
        config=types.EmbedContentConfig(
            task_type="RETRIEVAL_QUERY"
        )
    )

    return response.embeddings[0].values
