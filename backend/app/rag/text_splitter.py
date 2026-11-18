def split_documents(
    documents: list[dict],
    chunk_size: int = 500,
    chunk_overlap: int = 100
) -> list[dict]:

    chunks = []

    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be smaller than chunk_size")

    for document in documents:

        content = document["content"]
        source = document["source"]

        start = 0
        chunk_index = 0

        while start < len(content):

            end = start + chunk_size

            chunk_content = content[start:end].strip()

            if chunk_content:
                chunks.append({
                    "chunk_index": chunk_index,
                    "source": source,
                    "content": chunk_content
                })
                chunk_index += 1

            start += chunk_size - chunk_overlap

    return chunks
