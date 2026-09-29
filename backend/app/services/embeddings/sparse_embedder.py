import asyncio
from functools import lru_cache
from typing import List
from fastembed import SparseTextEmbedding

from app.services.vector_db.schema import SparseVectorData


class FastEmbedSparseEmbedder:
    def __init__(self, model_name: str = "Qdrant/bm25"):
        self.model = SparseTextEmbedding(model_name=model_name)

    def _sync_embed_text(self, text: str) -> SparseVectorData:
        clean_text = text.strip()
        if not clean_text:
            return SparseVectorData(indices=[], values=[])

        result = list(self.model.embed([clean_text]))[0]
        return SparseVectorData(
            indices=result.indices.tolist(),
            values=result.values.tolist(),
        )

    async def embed_text(self, text: str) -> SparseVectorData:
        """Executes in a threadpool worker to keep the async event loop responsive."""
        return await asyncio.to_thread(self._sync_embed_text, text)

    def _sync_embed_batch(self, texts: List[str]) -> List[SparseVectorData]:
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

    async def embed_batch(self, texts: List[str]) -> List[SparseVectorData]:
        return await asyncio.to_thread(self._sync_embed_batch, texts)


@lru_cache(maxsize=1)
def get_sparse_embedder() -> FastEmbedSparseEmbedder:
    return FastEmbedSparseEmbedder()