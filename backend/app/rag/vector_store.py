import math
from pathlib import Path


VECTOR_DB_DIR = Path(__file__).resolve().parents[2] / "vector_db"


def _cosine_similarity(a: list[float], b: list[float]) -> float:

    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot / (norm_a * norm_b)


class _VectorStoreCollection:

    def __init__(self, name: str):

        self.name = name
        self._documents: list[str] = []
        self._embeddings: list[list[float]] = []
        self._metadatas: list[dict] = []
        self._ids: list[str] = []

    def count(self) -> int:

        return len(self._documents)

    def add(
        self,
        documents: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict],
        ids: list[str]
    ):

        self._documents.extend(documents)
        self._embeddings.extend(embeddings)
        self._metadatas.extend(metadatas)
        self._ids.extend(ids)

    def query(
        self,
        query_embeddings: list[list[float]],
        n_results: int
    ) -> dict:

        if not self._documents:
            return {
                "documents": [[]],
                "metadatas": [[]],
                "distances": [[]],
                "ids": [[]]
            }

        query_embedding = query_embeddings[0]

        scored = []

        for i, embedding in enumerate(self._embeddings):
            similarity = _cosine_similarity(query_embedding, embedding)
            distance = 1.0 - similarity
            scored.append((distance, i))

        scored.sort(key=lambda x: x[0])
        top = scored[:n_results]

        return {
            "documents": [[self._documents[i] for _, i in top]],
            "metadatas": [[self._metadatas[i] for _, i in top]],
            "distances": [[dist for dist, _ in top]],
            "ids": [[self._ids[i] for _, i in top]]
        }


_shared_collection: "_VectorStoreCollection | None" = None


def _get_shared_collection() -> "_VectorStoreCollection":

    global _shared_collection

    if _shared_collection is None:

        _shared_collection = _VectorStoreCollection("place_explorer")

    return _shared_collection


def create_vector_store(collection_name: str = "place_explorer"):

    return _get_shared_collection()


def store_chunks(collection, embedded_chunks: list[dict]):

    if not embedded_chunks:
        return

    documents = [chunk["content"] for chunk in embedded_chunks]
    embeddings = [chunk["embedding"] for chunk in embedded_chunks]
    metadatas = [
        {
            "source": chunk["source"],
            "chunk_index": chunk["chunk_index"]
        }
        for chunk in embedded_chunks
    ]
    ids = [
        f"{chunk['source']}_{chunk['chunk_index']}"
        for chunk in embedded_chunks
    ]

    collection.add(
        documents=documents,
        embeddings=embeddings,
        metadatas=metadatas,
        ids=ids
    )


def search_similar_chunks(collection, query_embedding: list[float], top_k: int = 3):

    return collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k
    )
