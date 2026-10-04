import asyncio
from typing import List, Optional
from fastembed import TextEmbedding

from app.services.embeddings.base import BaseEmbedder
from app.services.embeddings.schema import EmbedderConfig, EmbeddingResult


class FastEmbedEmbedder(BaseEmbedder):
    """
    In-process CPU-optimized dense embedder using FastEmbed (ONNX Runtime).
    Supports BAAI/bge-m3, BAAI/bge-small-en-v1.5, etc.
    """

    def __init__(self, config: EmbedderConfig) -> None:
        super().__init__(config)
        self.model_name = config.model_name or "BAAI/bge-m3"
        # Download once to cache and load into ONNX Runtime
        self.model = TextEmbedding(model_name=self.model_name)
        self._dim = config.output_dimensionality or 1024

    def _sync_embed(self, texts: List[str]) -> List[EmbeddingResult]:
        if not texts:
            return []
        embeddings_generator = self.model.embed(texts)
        return [EmbeddingResult(values=emb.tolist()) for emb in embeddings_generator]

    async def embed(
        self, texts: List[str], task_type: Optional[str] = None
    ) -> List[EmbeddingResult]:
        """Runs embedding in a thread worker so the async loop is never blocked."""
        return await asyncio.to_thread(self._sync_embed, texts)

    @property
    def dimension(self) -> int:
        return self._dim