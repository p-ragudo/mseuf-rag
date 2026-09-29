from functools import lru_cache
from typing import List
from fastembed import SparseTextEmbedding

from app.services.vector_db.schema import SparseVectorData


class FastEmbedSparseEmbedder:
    def __init__(self, model_name: str = "Qdrant/bm25"):
        # Model weights (~20MB) are loaded locally via ONNX Runtime without HTTP API calls
        self.model = SparseTextEmbedding(model_name=model_name)

    def embed_text(self, text: str) -> SparseVectorData:
        """Embeds a single string into sparse indices and BM25 values."""
        clean_text = text.strip()
        if not clean_text:
            return SparseVectorData(indices=[], values=[])

        # fastembed.embed returns a generator of SparseEmbedding objects
        result = list(self.model.embed([clean_text]))[0]
        return SparseVectorData(
            indices=result.indices.tolist(),
            values=result.values.tolist(),
        )

    def embed_batch(self, texts: List[str]) -> List[SparseVectorData]:
        """Batch-embeds a list of strings into sparse vectors."""
        if not texts:
            return []

        results = list(self.model.embed(texts))
        return [
            SparseVectorData(
                indices=res.indices.tolist(),
                values=res.values.tolist(),
            )
            for res in results
        ]


@lru_cache(maxsize=1)
def get_sparse_embedder() -> FastEmbedSparseEmbedder:
    """Singleton getter for the sparse embedder."""
    return FastEmbedSparseEmbedder()